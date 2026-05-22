_DRIVER_MISSING_HINT = (
    "The Microsoft Access ODBC driver is not installed on this computer.\n\n"
    "To fix this:\n"
    "  1. Search the web for \"Microsoft Access Database Engine 2016 Redistributable\"\n"
    "  2. Download and run the 64-bit installer from Microsoft\n"
    "  3. Restart this application\n\n"
    "If Microsoft Office (64-bit) is already installed, contact your IT support."
)


def friendly_db_error(message: str) -> str:
    """Return a plain-English error string for a database RuntimeError.
    Detects missing ODBC driver (IM002) and gives install instructions."""
    if "IM002" in message or "data source name not found" in message.lower():
        return _DRIVER_MISSING_HINT
    return f"Could not connect to the database:\n\n{message}"
