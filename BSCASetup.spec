# -*- mode: python ; coding: utf-8 -*-
# Build: .venv/Scripts/pyinstaller BSCASetup.spec
# Output: dist/BSCASetup.exe

a = Analysis(
    ['setup.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pyodbc',
        'openpyxl',
        'requests',
        # Setup-script modules — loaded via importlib.import_module()
        # in setup_gui/setup_worker.py, so PyInstaller's static analysis
        # doesn't see them. Bundle them explicitly.
        'scripts',
        'scripts.create_supporting_tables',
        'scripts.add_long_lat_to_contacts',
        'scripts.backfill_enrollment_from_contacts',
        'scripts.backfill_authorization_from_contacts',
        'scripts.backfill_availability_from_hha',
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
    name='BSCASetup',
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
