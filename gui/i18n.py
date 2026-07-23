"""GUI internationalization. Pure-Python core lives here; the Qt
LanguageManager (in this same module, added in Task 2) wraps it with
a signal so widgets can react to language changes."""

_current_lang = "en"

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # app
        "app.main_title": "Monthly Schedule Generator",
        "app.settings_title": "Settings",
        "app.first_run_title": "Welcome — Initial Setup",
        # top bar
        "top.title": "Monthly Schedule Generator",
        "top.settings_tooltip": "Settings",
        # who
        "who.title": "Who",
        "who.single": "Single Member",
        "who.multiple": "Multiple Members",
        "who.plan": "Entire Plan",
        "who.all": "All Members",
        "who.member_id_label": "Member ID:",
        "who.member_ids_label": "Member IDs:",
        "who.plan_label": "Plan:",
        "who.placeholder": "e.g. 24010, 24011, 24015",
        "who.all_hint": "All members in the database will be scheduled. Per-plan folders are created under your output path.",
        # when
        "when.title": "When",
        "when.month_label": "Month:",
        "when.year_label": "Year:",
        "when.month.1": "January",
        "when.month.2": "February",
        "when.month.3": "March",
        "when.month.4": "April",
        "when.month.5": "May",
        "when.month.6": "June",
        "when.month.7": "July",
        "when.month.8": "August",
        "when.month.9": "September",
        "when.month.10": "October",
        "when.month.11": "November",
        "when.month.12": "December",
        "when.range_check": "Custom day range",
        "when.range_from": "From day:",
        "when.range_to": "To day:",
        # save to
        "save.title": "Save To",
        "save.change": "Change…",
        # options
        "opts.debug": "Debug (write per-day reason CSV next to each schedule)",
        "opts.mltc_folders": (
            "All Members: separate output into per-MLTC folders "
            "(off = one Month_Year_Timesheets folder)"
        ),
        "opts.generate": "Generate Schedule",
        "opts.open_folder": "Open Output Folder",
        "opts.print": "Print All Schedules",
        "print.title": "Print Schedules",
        "print.default_printer": "the default printer",
        "print.none": "No generated schedules to print.",
        "print.confirm.title": "Print Schedules",
        "print.confirm.body": (
            "Print {count} schedule(s) to \"{printer}\"?\n\n"
            "Each schedule is sent to the printer via Excel."
        ),
        "print.started": "Printing {count} schedule(s)…",
        "print.done": "Printed {count} schedule(s).",
        "print.failed": "Printing failed: {error}",
        "print.confirm.reprint_all": (
            "All {count} schedule(s) were already printed this session. "
            "Print them all again?"
        ),
        "print.confirm.remaining": (
            "{remaining} of {total} schedule(s) have not been printed "
            "yet. Print to {printer}?"
        ),
        "print.btn.remaining": "Print remaining {count}",
        "print.btn.all": "Print all {count}",
        "print.file_failed": "Print failed: {name} — {error}",
        "print.stopped_early": (
            "Stopped after repeated failures; {count} schedule(s) were "
            "not attempted."
        ),
        "print.stalled": (
            "The printer stopped making progress; {count} schedule(s) "
            "were not sent. It is likely out of paper or offline."
        ),
        "print.partial": (
            "Printed {printed} of {total} schedule(s); {failed} did not "
            "print. The printer may be out of paper or offline — fix the "
            "printer, then click Print All Schedules again. Schedules "
            "that already printed will be skipped."
        ),
        # settings dialog
        "settings.welcome": (
            "Before you get started, please fill in the fields "
            "below.\nYou can change these at any time using the ⚙ "
            "Settings button."
        ),
        "settings.db_label": "Database File",
        "settings.output_label": "Output Folder",
        "settings.api_key_label": "Google Maps API Key",
        "settings.cache_label": "Travel Cache File",
        "settings.rules.title": "Scheduling Rules",
        "settings.rules.earliest_in": "Earliest Time-In:",
        "settings.rules.latest_out": "Latest Time-Out:",
        "settings.rules.session": "Visit length min – max (HH:MM):",
        "settings.rules.travel_buffer": (
            "Travel buffer min – max (extra minutes on top of Google):"
        ),
        "settings.rules.time_in": (
            "Time-In offset min – max (minutes after Arrival):"
        ),
        "settings.rules.time_out": (
            "Time-Out offset min – max (minutes before Departure):"
        ),
        "settings.rules.dropoff_deadline": (
            "Drop off by availability end (home care):"
        ),
        "settings.rules.band_enabled": (
            "Morning/afternoon distribution:"
        ),
        "settings.rules.morning_percent": "Morning members (%):",
        "settings.rules.morning_window": (
            "Morning window length (HH:MM after earliest Time-In):"
        ),
        "settings.rules.morning_members": (
            "Always-morning member IDs (comma-separated):"
        ),
        "settings.rules.afternoon_members": (
            "Always-afternoon member IDs (comma-separated):"
        ),
        "settings.rules.band_invalid_ids.title": "Invalid Member IDs",
        "settings.rules.band_invalid_ids.body": (
            "Member ID lists must be numbers separated by commas "
            "(e.g. 24010, 24011)."
        ),
        "settings.rules.band_conflict.title": "Member In Both Lists",
        "settings.rules.band_conflict.body": (
            "These member IDs are in both the morning and afternoon "
            "lists: {ids}. Remove them from one list."
        ),
        "settings.rules.invalid_range.title": "Invalid Range",
        "settings.rules.invalid_range.body": (
            "Each minimum value must be on or before its maximum. "
            "Please fix the highlighted range before saving."
        ),
        "settings.browse": "Browse…",
        "settings.test_connection": "Test Connection",
        "settings.api_key.show": "Show",
        "settings.api_key.hide": "Hide",
        "settings.file_dialog.file": "Select File",
        "settings.file_dialog.folder": "Select Folder",
        "settings.test_result_title": "Connection Test",
        "settings.test.db_not_found": "Database: File not found — {path}",
        "settings.test.db_ok": "Database: Connected successfully.",
        "settings.test.db_fail": "Database: Connection failed — {error}",
        "settings.test.api_key_missing": "API Key: missing — enter one above.",
        "settings.test.api_key_valid": (
            "API Key: valid (Google accepted the test request)."
        ),
        "settings.test.api_key_invalid": (
            "API Key: rejected by Google — {error}"
        ),
        "settings.test.api_key_network_error": (
            "API Key: could not reach Google ({error}). "
            "Check your internet connection."
        ),
        # message dialogs
        "msg.missing_info.title": "Missing Info",
        "msg.missing_info.member_id": "Please enter a Member ID.",
        "msg.missing_info.member_ids": "Please enter at least one Member ID.",
        "msg.missing_info.output_folder": (
            "Please set an output folder in Settings (⚙)."
        ),
        "msg.invalid_ids.title": "Invalid IDs",
        "msg.invalid_ids.body": (
            "Member IDs must be numbers separated by commas.\n"
            "Could not read: {raw}"
        ),
        "msg.db_not_found.title": "Database Not Found",
        "msg.db_not_found.body": (
            "The database file could not be found:\n{path}\n\n"
            "Open Settings to fix the path."
        ),
        "msg.api_key_missing.title": "API Key Missing",
        "msg.api_key_missing.body": (
            "Open Settings and enter your Google Maps API key before generating."
        ),
        "msg.completed_errors.title": "Completed with errors",
        "msg.invalid_range.title": "Invalid Day Range",
        "msg.invalid_range.body": (
            "The 'From day' must be on or before the 'To day'."
        ),
        # worker log lines
        "worker.wrote": "Wrote {filename}",
        "worker.wrote_skipped_csv": "Wrote skipped members report: {filename}",
        "worker.skipped_csv_fallback": (
            "Warning: {primary} is locked (open in Excel?) — saved the "
            "skipped members report as {filename} instead."
        ),
        "worker.skipped_csv_failed": (
            "Warning: could not write the skipped members report "
            "({error}). The skipped members are listed in the summary."
        ),
        "worker.wrote_debug_csv": "Wrote debug report: {filename}",
        "worker.no_members": "No members found in the database.",
        "worker.no_members_for_plan": "No members found for plan {plan}.",
        "worker.cannot_create_folder": "Cannot create output folder: {error}",
        # run summary
        "summary.verb.wrote": "Wrote",
        "summary.headline": "{verb} {success} of {total} member(s) for {scope}",
        "summary.into": " into {dir}",
        "summary.failed_tail": "; {n} failed.",
        "summary.failures_header": "Failures:",
        "summary.failure_row_named": "  - ID {center_id} ({name}): {stage} — {reason}",
        "summary.failure_row_unnamed": "  - ID {center_id}: {stage} — {reason}",
        "summary.stage.geocode": "geocode",
        "summary.stage.route": "route",
        "summary.stage.generate": "generate",
        "summary.stage.write": "write",
        "summary.stage.lookup": "lookup",
        "summary.stage.eligibility": "eligibility",
        "summary.stage.one_off_conflict": "one-off conflict",
        "summary.stage.worker": "worker error",
        "summary.reason.not_found": "not found in database",
        "summary.reason.not_enrolled": "not enrolled during this month",
        "summary.reason.no_auth": "no active authorization for this month",
        "summary.reason.absent_month": "absent for the entire month",
        # scope (used by GUI summary builder)
        "scope.plan": "plan {code} {period}",
        "scope.all": "all members {period}",
        "scope.period": "{period}",
        # errors
        "errors.driver_missing": (
            "The Microsoft Access ODBC driver is not installed on this "
            "computer.\n\n"
            "To fix this:\n"
            '  1. Search the web for "Microsoft Access Database Engine '
            '2016 Redistributable"\n'
            "  2. Download and run the 64-bit installer from Microsoft\n"
            "  3. Restart this application\n\n"
            "If Microsoft Office (64-bit) is already installed, contact "
            "your IT support."
        ),
        "errors.db_generic": "Could not connect to the database:\n\n{message}",
    },
    "zh": {
        # app
        "app.main_title": "月度日程生成器",
        "app.settings_title": "设置",
        "app.first_run_title": "欢迎 — 初始设置",
        # top bar
        "top.title": "月度日程生成器",
        "top.settings_tooltip": "设置",
        # who
        "who.title": "人员",
        "who.single": "单个成员",
        "who.multiple": "多个成员",
        "who.plan": "整个计划",
        "who.all": "全部成员",
        "who.member_id_label": "成员编号：",
        "who.member_ids_label": "成员编号列表：",
        "who.plan_label": "计划：",
        "who.placeholder": "例如 24010, 24011, 24015",
        "who.all_hint": "数据库中所有成员将被排班。将在输出路径下按计划创建子文件夹。",
        # when
        "when.title": "时间",
        "when.month_label": "月份：",
        "when.year_label": "年份：",
        "when.month.1": "一月",
        "when.month.2": "二月",
        "when.month.3": "三月",
        "when.month.4": "四月",
        "when.month.5": "五月",
        "when.month.6": "六月",
        "when.month.7": "七月",
        "when.month.8": "八月",
        "when.month.9": "九月",
        "when.month.10": "十月",
        "when.month.11": "十一月",
        "when.month.12": "十二月",
        "when.range_check": "自定义日期范围",
        "when.range_from": "从：",
        "when.range_to": "到：",
        # save to
        "save.title": "保存到",
        "save.change": "更改…",
        # options
        "opts.debug": "调试（在每个日程旁写入每日原因 CSV）",
        "opts.mltc_folders": "所有成员：按 MLTC 分文件夹输出（关闭＝统一放入一个 月份_年份_Timesheets 文件夹）",
        "opts.generate": "生成日程表",
        "opts.open_folder": "打开输出文件夹",
        "opts.print": "打印所有日程表",
        "print.title": "打印日程表",
        "print.default_printer": "默认打印机",
        "print.none": "没有可打印的已生成日程表。",
        "print.confirm.title": "打印日程表",
        "print.confirm.body": (
            "将 {count} 份日程表打印到“{printer}”？\n\n"
            "每份日程表通过 Excel 发送到打印机。"
        ),
        "print.started": "正在打印 {count} 份日程表……",
        "print.done": "已打印 {count} 份日程表。",
        "print.failed": "打印失败：{error}",
        "print.confirm.reprint_all": (
            "本次运行中已打印全部 {count} 份日程表。要全部重新打印吗？"
        ),
        "print.confirm.remaining": (
            "还有 {remaining} 份（共 {total} 份）日程表尚未打印。"
            "要打印到 {printer} 吗？"
        ),
        "print.btn.remaining": "打印剩余 {count} 份",
        "print.btn.all": "全部打印 {count} 份",
        "print.file_failed": "打印失败：{name} — {error}",
        "print.stopped_early": (
            "连续失败后已停止；{count} 份日程表未尝试打印。"
        ),
        "print.stalled": (
            "打印机长时间没有进展；{count} 份日程表未发送。"
            "可能缺纸或离线。"
        ),
        "print.partial": (
            "已打印 {printed} 份（共 {total} 份）；{failed} 份未打印。"
            "打印机可能缺纸或离线——请检修打印机后再次点击"
            "“打印全部日程表”，已打印的日程表会自动跳过。"
        ),
        # settings dialog
        "settings.welcome": (
            "开始之前，请填写以下各项。\n"
            "您可以随时通过 ⚙ 设置按钮更改它们。"
        ),
        "settings.db_label": "数据库文件",
        "settings.output_label": "输出文件夹",
        "settings.api_key_label": "Google 地图 API 密钥",
        "settings.cache_label": "出行缓存文件",
        "settings.rules.title": "排班规则",
        "settings.rules.earliest_in": "最早签到时间：",
        "settings.rules.latest_out": "最晚签退时间：",
        "settings.rules.session": "访问时长 最短 – 最长（时:分）：",
        "settings.rules.travel_buffer": (
            "出行缓冲 最少 – 最多（在 Google 行程时间上加的额外分钟）："
        ),
        "settings.rules.time_in": (
            "签到偏移 最少 – 最多（到达后多少分钟）："
        ),
        "settings.rules.time_out": (
            "签出偏移 最少 – 最多（离开前多少分钟）："
        ),
        "settings.rules.dropoff_deadline": (
            "在可用时间结束前送回（家庭护理）："
        ),
        "settings.rules.band_enabled": "上午/下午分布：",
        "settings.rules.morning_percent": "上午成员比例（%）：",
        "settings.rules.morning_window": (
            "上午时段长度（最早签到后的 时:分）："
        ),
        "settings.rules.morning_members": (
            "固定上午的成员 ID（逗号分隔）："
        ),
        "settings.rules.afternoon_members": (
            "固定下午的成员 ID（逗号分隔）："
        ),
        "settings.rules.band_invalid_ids.title": "成员 ID 无效",
        "settings.rules.band_invalid_ids.body": (
            "成员 ID 列表必须是用逗号分隔的数字（例如 24010, 24011）。"
        ),
        "settings.rules.band_conflict.title": "成员同时在两个列表中",
        "settings.rules.band_conflict.body": (
            "以下成员 ID 同时出现在上午和下午列表中：{ids}。"
            "请从其中一个列表中移除。"
        ),
        "settings.rules.invalid_range.title": "范围无效",
        "settings.rules.invalid_range.body": (
            "每个最小值必须不大于其最大值。请先修正高亮显示的范围再保存。"
        ),
        "settings.browse": "浏览…",
        "settings.test_connection": "测试连接",
        "settings.api_key.show": "显示",
        "settings.api_key.hide": "隐藏",
        "settings.file_dialog.file": "选择文件",
        "settings.file_dialog.folder": "选择文件夹",
        "settings.test_result_title": "连接测试",
        "settings.test.db_not_found": "数据库：找不到文件 — {path}",
        "settings.test.db_ok": "数据库：连接成功。",
        "settings.test.db_fail": "数据库：连接失败 — {error}",
        "settings.test.api_key_missing": "API 密钥：未填写 — 请在上方输入。",
        "settings.test.api_key_valid": (
            "API 密钥：有效（Google 已接受测试请求）。"
        ),
        "settings.test.api_key_invalid": (
            "API 密钥：被 Google 拒绝 — {error}"
        ),
        "settings.test.api_key_network_error": (
            "API 密钥：无法连接到 Google（{error}）。请检查网络连接。"
        ),
        # message dialogs
        "msg.missing_info.title": "缺少信息",
        "msg.missing_info.member_id": "请输入成员编号。",
        "msg.missing_info.member_ids": "请至少输入一个成员编号。",
        "msg.missing_info.output_folder": (
            "请在设置 (⚙) 中设定输出文件夹。"
        ),
        "msg.invalid_ids.title": "无效的编号",
        "msg.invalid_ids.body": (
            "成员编号必须是用逗号分隔的数字。\n"
            "无法识别：{raw}"
        ),
        "msg.db_not_found.title": "找不到数据库",
        "msg.db_not_found.body": (
            "找不到数据库文件：\n{path}\n\n"
            "打开设置以修正路径。"
        ),
        "msg.api_key_missing.title": "缺少 API 密钥",
        "msg.api_key_missing.body": (
            "请打开设置并输入您的 Google 地图 API 密钥，然后再生成。"
        ),
        "msg.completed_errors.title": "完成但有错误",
        "msg.invalid_range.title": "日期范围无效",
        "msg.invalid_range.body": "“起始日”必须不晚于“截止日”。",
        # worker log lines
        "worker.wrote": "已写入 {filename}",
        "worker.wrote_skipped_csv": "已写入跳过成员报告：{filename}",
        "worker.skipped_csv_fallback": (
            "警告：{primary} 已被占用（可能在 Excel 中打开）——"
            "已将跳过成员报告另存为 {filename}。"
        ),
        "worker.skipped_csv_failed": (
            "警告：无法写入跳过成员报告（{error}）。"
            "被跳过的成员已在摘要中列出。"
        ),
        "worker.wrote_debug_csv": "已写入调试报告：{filename}",
        "worker.no_members": "数据库中找不到成员。",
        "worker.no_members_for_plan": "计划 {plan} 中找不到成员。",
        "worker.cannot_create_folder": "无法创建输出文件夹：{error}",
        # run summary
        "summary.verb.wrote": "已写入",
        "summary.headline": "{verb} {scope} 的 {total} 名成员中的 {success} 名",
        "summary.into": "，至 {dir}",
        "summary.failed_tail": "；{n} 名失败。",
        "summary.failures_header": "失败：",
        "summary.failure_row_named": "  - 编号 {center_id}（{name}）：{stage} — {reason}",
        "summary.failure_row_unnamed": "  - 编号 {center_id}：{stage} — {reason}",
        "summary.stage.geocode": "地理编码",
        "summary.stage.route": "路线",
        "summary.stage.generate": "生成",
        "summary.stage.write": "写入",
        "summary.stage.lookup": "查找",
        "summary.stage.eligibility": "资格",
        "summary.stage.one_off_conflict": "一次性冲突",
        "summary.stage.worker": "工作进程错误",
        "summary.reason.not_found": "数据库中未找到",
        "summary.reason.not_enrolled": "本月未入册",
        "summary.reason.no_auth": "本月无有效授权",
        "summary.reason.absent_month": "整月缺席",
        # scope
        "scope.plan": "计划 {code} {period}",
        "scope.all": "所有成员 {period}",
        "scope.period": "{period}",
        # errors
        "errors.driver_missing": (
            "此电脑上未安装 Microsoft Access ODBC 驱动程序。\n\n"
            "解决方法：\n"
            '  1. 在网上搜索 "Microsoft Access Database Engine 2016 '
            'Redistributable"\n'
            "  2. 从 Microsoft 下载并运行 64 位安装程序\n"
            "  3. 重启此应用程序\n\n"
            "如果已安装 Microsoft Office (64 位)，请联系您的 IT 支持。"
        ),
        "errors.db_generic": "无法连接到数据库：\n\n{message}",
    },
}


def get_language() -> str:
    return _current_lang


def set_language(lang: str) -> None:
    """Update the current language and persist the choice to settings.
    Does NOT emit a signal — that's the LanguageManager's job (Task 2)."""
    global _current_lang
    _current_lang = lang

    # Persist. Import inside the function to avoid an import cycle if
    # app_settings ever grows a reference back to i18n.
    from gui import app_settings
    settings = app_settings.load()
    settings["language"] = lang
    app_settings.save(settings)


def tr(key: str, **fmt) -> str:
    """Look up `key` in the current language's STRINGS table.
    Returns the key itself if the key is missing (visible bug, no crash).
    Applies `str.format(**fmt)` always so that missing format args raise
    KeyError on purpose — that's a bug."""
    s = STRINGS.get(_current_lang, {}).get(key, key)
    return s.format(**fmt)


from PyQt6.QtCore import QObject, pyqtSignal


class LanguageManager(QObject):
    """Singleton wrapper around module-level set_language() that emits
    a Qt signal so widgets can retranslate themselves."""

    languageChanged = pyqtSignal(str)

    _instance: "LanguageManager | None" = None

    @classmethod
    def instance(cls) -> "LanguageManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_language(self, lang: str) -> None:
        if lang == get_language():
            return
        set_language(lang)
        self.languageChanged.emit(lang)
