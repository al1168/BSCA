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
        # pywin32 — needed by add_document_to_authorization.py which
        # uses DAO via COM to create the native ATTACHMENT field
        # (ODBC can't create ATTACHMENT fields).
        'win32com.client',
        'pywintypes',
        'pythoncom',
        'win32timezone',
        # Setup-script modules — loaded via importlib.import_module()
        # in setup_gui/setup_worker.py, so PyInstaller's static analysis
        # doesn't see them. Bundle them explicitly.
        'scripts',
        'scripts.normalize_contacts_columns',
        'scripts.create_supporting_tables',
        'scripts.add_long_lat_to_contacts',
        'scripts.add_document_to_authorization',
        'scripts.add_document_to_transport_authorization',
        'scripts.add_created_at_to_authorization',
        'scripts.add_member_id_to_authorization',
        'scripts.add_auth_number_to_authorization',
        'scripts.add_plan_type_to_authorization',
        'scripts.change_dob_to_date_in_contacts',
        'scripts.backfill_enrollment_from_contacts',
        'scripts.backfill_authorization_from_contacts',
        'scripts.backfill_availability_from_hha',
        'scripts.backfill_emergency_contacts_from_contacts',
        # Optional opt-in step (via the GUI checkbox).
        'scripts.terminate_long_id_enrollments',
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
