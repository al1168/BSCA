@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setting up for first time use, please wait...
    py -3.11 -m venv .venv
    if errorlevel 1 (
        echo ERROR: Python 3.11 not found. Please install it from python.org
        pause
        exit /b 1
    )
    .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies. See message above.
        pause
        exit /b 1
    )
)

start "" .venv\Scripts\pythonw.exe gui.py
