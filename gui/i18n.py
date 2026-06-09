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
        # save to
        "save.title": "Save To",
        "save.change": "Change…",
        # options
        "opts.preview": "Preview only (don't save files)",
        "opts.generate": "Generate Schedule",
        "opts.open_folder": "Open Output Folder",
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
        "settings.test.api_key_present": "API Key: provided.",
        "settings.test.api_key_missing": "API Key: missing — enter one above.",
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
        # worker log lines
        "worker.preview": "Preview: {id} ({last}, {first})",
        "worker.wrote": "Wrote {filename}",
        "worker.wrote_skipped_csv": "Wrote skipped members report: {filename}",
        "worker.no_members": "No members found in the database.",
        "worker.no_members_for_plan": "No members found for plan {plan}.",
        "worker.cannot_create_folder": "Cannot create output folder: {error}",
        # run summary
        "summary.verb.previewed": "Previewed",
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
        # save to
        "save.title": "保存到",
        "save.change": "更改…",
        # options
        "opts.preview": "仅预览（不保存文件）",
        "opts.generate": "生成日程表",
        "opts.open_folder": "打开输出文件夹",
        # settings dialog
        "settings.welcome": (
            "开始之前，请填写以下各项。\n"
            "您可以随时通过 ⚙ 设置按钮更改它们。"
        ),
        "settings.db_label": "数据库文件",
        "settings.output_label": "输出文件夹",
        "settings.api_key_label": "Google 地图 API 密钥",
        "settings.cache_label": "出行缓存文件",
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
        "settings.test.api_key_present": "API 密钥：已填写。",
        "settings.test.api_key_missing": "API 密钥：未填写 — 请在上方输入。",
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
        # worker log lines
        "worker.preview": "预览：{id}（{last}，{first}）",
        "worker.wrote": "已写入 {filename}",
        "worker.wrote_skipped_csv": "已写入跳过成员报告：{filename}",
        "worker.no_members": "数据库中找不到成员。",
        "worker.no_members_for_plan": "计划 {plan} 中找不到成员。",
        "worker.cannot_create_folder": "无法创建输出文件夹：{error}",
        # run summary
        "summary.verb.previewed": "已预览",
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
