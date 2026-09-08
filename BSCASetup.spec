# -*- mode: python ; coding: utf-8 -*-
# Build: .venv/Scripts/pyinstaller BSCASetup.spec
# Output: dist/BSCASetup.exe

import sys

from PyInstaller.utils.hooks import collect_submodules

# collect_submodules() resolves the package name in an isolated
# subprocess that inherits this process's sys.path, which does not carry
# the project root; without this insert, 'scripts' would resolve to
# pywin32's own win32/scripts package instead of ours.
sys.path.insert(0, SPECPATH)

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
        # Setup-script modules are loaded via importlib.import_module()
        # in setup_gui/setup_worker.py, so PyInstaller's static analysis
        # never sees them. Collect the whole package rather than listing
        # each step: a step added to setup_worker.py's STEPS is then
        # bundled automatically instead of failing in the built exe.
    ] + collect_submodules('scripts'),
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
