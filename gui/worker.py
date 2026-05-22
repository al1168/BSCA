import random

from PyQt6.QtCore import QThread, pyqtSignal

from monthly_schedule.db import get_member, get_members_by_plan
from monthly_schedule.travel import load_api_key, load_cache, save_cache
from gui.errors import friendly_db_error
from new_monthly_schedule import (
    Failure,
    format_summary,
    parse_center_ids,
    process_member,
    resolve_output_dir,
    schedule_filename,
)

import os


class ScheduleWorker(QThread):
    progress = pyqtSignal(int, int)   # (completed, total)
    log_line = pyqtSignal(str)        # one log line
    finished = pyqtSignal(bool, str)  # (success, summary)

    def __init__(
        self,
        mode,          # "single" | "multiple" | "plan"
        center_id,     # int or None
        center_ids,    # list[int] or None
        plan_code,     # str or None
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

    def run(self):
        try:
            api_key = load_api_key(self.google_config)
        except RuntimeError as exc:
            self.finished.emit(False, str(exc))
            return

        cache = load_cache(self.geo_cache)

        members = []
        failures = []

        try:
            if self.mode == "plan":
                members = get_members_by_plan(self.plan_code, self.db_path)
                if not members:
                    self.finished.emit(
                        False,
                        f"No members found for plan {self.plan_code.upper()}.",
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
                            Failure(cid, "", "lookup", "not found in database")
                        )
                    else:
                        members.append(member)
        except FileNotFoundError as exc:
            self.finished.emit(False, str(exc))
            return
        except RuntimeError as exc:
            self.finished.emit(False, friendly_db_error(str(exc)))
            return

        if not self.preview:
            try:
                os.makedirs(self.out_dir, exist_ok=True)
            except OSError as exc:
                self.finished.emit(False, f"Cannot create output folder: {exc}")
                return

        total = len(members) + len(failures)
        success = 0

        for i, member in enumerate(members):
            ok, stage, reason = process_member(
                member,
                self.year,
                self.month,
                self.out_dir,
                self.preview,
                api_key,
                cache,
            )
            if ok:
                success += 1
                if self.preview:
                    self.log_line.emit(
                        f"Preview: {member['center_id']} "
                        f"({member['last_name']}, {member['first_name']})"
                    )
                else:
                    fname = schedule_filename(
                        member["center_id"], self.year, self.month
                    )
                    self.log_line.emit(f"Wrote {fname}")
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

        scope = (
            f"plan {self.plan_code.upper()} "
            if self.mode == "plan"
            else ""
        ) + f"{self.year:04d}-{self.month:02d}"

        summary_dir = None if self.preview else self.out_dir
        summary = format_summary(
            "Previewed" if self.preview else "Wrote",
            success,
            total,
            scope,
            summary_dir,
            failures,
        )
        self.finished.emit(len(failures) == 0 and total > 0, summary)
