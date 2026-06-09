import os
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from monthly_schedule.db import (
    get_member, get_members_by_plan,
    get_enrollments, get_authorizations, get_absences, get_availability,
    get_all_members,
    get_all_enrollments, get_all_authorizations,
    get_all_absences, get_all_availability, get_all_one_offs,
)
from monthly_schedule.eligibility_context import MemberContext
from monthly_schedule.per_day import OneOffConflict
from monthly_schedule.travel import load_cache, save_cache
from gui.errors import friendly_db_error
from gui.i18n import tr
from new_monthly_schedule import (
    Failure,
    REASON_NOT_FOUND,
    parse_center_ids,
    process_member,
    resolve_output_dir,
    schedule_filename,
    write_skipped_members_csv,
)


class ScheduleWorker(QThread):
    progress = pyqtSignal(int, int)        # (completed, total)
    log_line = pyqtSignal(str, dict)       # (key, fmt_args)
    finished = pyqtSignal(bool, dict)      # (success, payload)

    def __init__(
        self,
        mode,
        center_id,
        center_ids,
        plan_code,
        year,
        month,
        out_dir,
        preview,
        db_path,
        google_api_key,
        geo_cache,
        parent=None,
    ):
        super().__init__(parent)
        self.mode = mode
        self.center_id = center_id
        self.center_ids = center_ids
        self.plan_code = plan_code
        self.year = year
        self.month = month
        self.out_dir = out_dir
        self.preview = preview
        self.db_path = db_path
        self.google_api_key = google_api_key
        self.geo_cache = geo_cache

    def _emit_error(self, text: str):
        self.finished.emit(False, {"error_text": text})

    def run(self):
        try:
            self._run_inner()
        except Exception:
            # Last-resort guard so an uncaught exception in any helper
            # surfaces as a visible error instead of silently aborting
            # the QThread (and potentially the whole process).
            self._emit_error(
                "Unhandled error in worker:\n" + traceback.format_exc()
            )

    def _run_inner(self):
        api_key = self.google_api_key
        cache = load_cache(self.geo_cache)

        members = []
        failures = []

        try:
            if self.mode == "plan":
                members = get_members_by_plan(self.plan_code, self.db_path)
                if not members:
                    self._emit_error(
                        tr(
                            "worker.no_members_for_plan",
                            plan=self.plan_code.upper(),
                        )
                    )
                    return
            elif self.mode == "all":
                members = get_all_members(self.db_path)
                if not members:
                    self._emit_error(tr("worker.no_members"))
                    return
            else:
                id_list = (
                    [self.center_id]
                    if self.mode == "single"
                    else self.center_ids
                )
                for cid in id_list:
                    member = get_member(cid, self.db_path)
                    if member is None:
                        failures.append(
                            Failure(cid, "", "lookup", REASON_NOT_FOUND, None)
                        )
                    else:
                        members.append(member)
        except FileNotFoundError as exc:
            self._emit_error(str(exc))
            return
        except RuntimeError as exc:
            self._emit_error(friendly_db_error(str(exc)))
            return

        if not self.preview:
            try:
                os.makedirs(self.out_dir, exist_ok=True)
            except OSError as exc:
                self._emit_error(
                    tr("worker.cannot_create_folder", error=str(exc))
                )
                return

        total = len(members) + len(failures)
        success = 0

        # Eager-fetch all four supporting tables once and index by
        # center_id. Replaces 4×N ODBC connections (the per-member
        # pattern) with 4 — see docs/performance/2026-05-29-all-members-
        # baseline.md for why this matters.
        #
        # Note: we eager-fetch unconditionally even for single/multiple
        # modes (where N is small). The spec called those out as
        # "not worth restructuring", but the connection cost is the
        # same per query regardless of WHERE filter (~400 ms each), so
        # 4 unfiltered queries is roughly break-even at N=1 and a clear
        # win at N≥2. The simpler code path is worth the trivial memory
        # bump (~few MB at current table sizes). Revisit if Enrollment/
        # Authorization/Absences/Availability ever grow beyond ~100k rows.
        enroll_idx = get_all_enrollments(self.db_path)
        auth_idx = get_all_authorizations(self.db_path)
        absence_idx = get_all_absences(self.db_path)
        avail_idx = get_all_availability(self.db_path)
        one_off_idx = get_all_one_offs(self.db_path)

        for i, member in enumerate(members):
            try:
                cid = member["center_id"]
                ctx = MemberContext(
                    enrollments=enroll_idx.get(cid, []),
                    authorizations=auth_idx.get(cid, []),
                    absences=absence_idx.get(cid, []),
                    availabilities=avail_idx.get(cid, []),
                    one_offs=one_off_idx.get(cid, []),
                )
                if self.mode == "all":
                    raw_plan = member.get("health_plan")
                    plan = (str(raw_plan).strip().upper() if raw_plan else "") or "_NoPlan"
                    member_out_dir = os.path.join(
                        self.out_dir, f"{plan}_{self.year:04d}-{self.month:02d}"
                    )
                    if not self.preview:
                        os.makedirs(member_out_dir, exist_ok=True)
                else:
                    member_out_dir = self.out_dir
                ok, stage, reason, day = process_member(
                    member, ctx,
                    self.year, self.month, member_out_dir,
                    self.preview, api_key, cache,
                )
            except OneOffConflict as exc:
                # process_member catches OneOffConflict internally and
                # returns it via the failure tuple. This branch only fires
                # if a future refactor removes that inner catch.
                ok = False
                stage = "one_off_conflict"
                reason = exc.reason
                day = exc.day
            except Exception as exc:  # noqa: BLE001 - surface in summary, never kill run
                ok = False
                stage = "worker"
                reason = f"{type(exc).__name__}: {exc}"
                day = None
            if ok:
                success += 1
                if self.preview:
                    self.log_line.emit(
                        "worker.preview",
                        {
                            "id": member["center_id"],
                            "last": member["last_name"],
                            "first": member["first_name"],
                        },
                    )
                else:
                    fname = schedule_filename(
                        member["center_id"], self.year, self.month
                    )
                    self.log_line.emit("worker.wrote", {"filename": fname})
            else:
                failures.append(
                    Failure(
                        member["center_id"],
                        f"{member['last_name']}, {member['first_name']}",
                        stage, reason, day,
                    )
                )
            self.progress.emit(i + 1, len(members))

        save_cache(self.geo_cache, cache)

        if not self.preview:
            # Skipped-members CSV lives at the base output dir even in "all"
            # mode — skips can span multiple plans, so a single roll-up file
            # is more useful than per-plan duplicates.
            csv_path = write_skipped_members_csv(failures, self.out_dir)
            if csv_path is not None:
                self.log_line.emit(
                    "worker.wrote_skipped_csv",
                    {"filename": os.path.basename(csv_path)},
                )

        payload = {
            "verb_key": "summary.verb.previewed" if self.preview else "summary.verb.wrote",
            "success": success,
            "total": total,
            "scope": {
                "mode": self.mode,
                "plan_code": self.plan_code.upper() if self.mode == "plan" else None,
                "year": self.year,
                "month": self.month,
            },
            "out_dir": None if self.preview else self.out_dir,
            "failures": [
                {
                    "center_id": f.center_id,
                    "name": f.name,
                    "stage": f.stage,
                    "reason": f.reason,
                }
                for f in failures
            ],
        }
        self.finished.emit(len(failures) == 0 and total > 0, payload)
