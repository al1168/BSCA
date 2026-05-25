from gui.i18n import tr


def friendly_db_error(message: str) -> str:
    """Return a translated, plain-language error string for a database
    RuntimeError. Detects missing ODBC driver (IM002) and returns
    install instructions instead of the raw error."""
    if "IM002" in message or "data source name not found" in message.lower():
        return tr("errors.driver_missing")
    return tr("errors.db_generic", message=message)
