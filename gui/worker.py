import os

from PyQt6.QtCore import QThread, pyqtSignal

from monthly_schedule.db import (
    get_member, get_members_by_plan,
    get_enrollments, get_authorizations, get_absences, get_availability,
)
from monthly_schedule.eligibility_context import MemberContext
from monthly_schedule.travel import load_api_key, load_cache, save_cache
from gui.errors import friendly_db_error
from gui.i18n import tr
from new_monthly_schedule import (
    Failure,
    REASON_NOT_FOUND,
    parse_center_ids,
    process_member,
    resolve_output_dir,
    schedule_filename,
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
        google_config,
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
        self.google_config = google_config
        self.geo_cache = geo_cache

    def _emit_error(self, text: str):
        self.finished.emit(False, {"error_text": text})

    def run(self):
        try:
            api_key = load_api_key(self.google_config)
        except RuntimeError as exc:
            self._emit_error(str(exc))
            return

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
                            Failure(cid, "", "lookup", REASON_NOT_FOUND)
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

        for i, member in enumerate(members):
            ctx = MemberContext(
                enrollments=get_enrollments(member["center_id"], self.db_path),
                authorizations=get_authorizations(member["center_id"], self.db_path),
                absences=get_absences(member["center_id"], self.db_path),
                availabilities=get_availability(member["center_id"], self.db_path),
            )
            ok, stage, reason = process_member(
                member, ctx,
                self.year, self.month, self.out_dir,
                self.preview, api_key, cache,
            )
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
                        stage,
                        reason,
                    )
                )
            self.progress.emit(i + 1, len(members))

        save_cache(self.geo_cache, cache)

        payload = {
            "verb_key": "summary.verb.previewed" if self.preview else "summary.verb.wrote",
            "success": success,
            "total": total,
            "scope": {
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
