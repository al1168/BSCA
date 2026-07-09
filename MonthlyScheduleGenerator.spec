# -*- mode: python ; coding: utf-8 -*-
# Build: .venv/Scripts/pyinstaller MonthlyScheduleGenerator.spec
# Output: dist/MonthlyScheduleGenerator.exe

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pyodbc', 'openpyxl', 'requests',
        # Printing generated schedules via Excel COM (gui/printing.py):
        # pywin32 provides Dispatch/CoInitialize and the default-printer
        # lookup. Bundled so the Print button works in the frozen exe.
        'win32com.client', 'win32print', 'pythoncom', 'pywintypes',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest'],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MonthlyScheduleGenerator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
