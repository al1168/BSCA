# -*- mode: python ; coding: utf-8 -*-
# Build: .venv/Scripts/pyinstaller ApplyHHAAnswers.spec
# Output: dist/ApplyHHAAnswers.exe

a = Analysis(
    ['apply_hha.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pyodbc',
        # Imported statically, but listed explicitly to mirror
        # BSCASetup.spec and survive future refactors to importlib.
        'scripts',
        'scripts.apply_hha_answers',
        'monthly_schedule',
        'monthly_schedule.hha_answer_parser',
        'setup_gui',
        'setup_gui.log_buffer',
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
    name='ApplyHHAAnswers',
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
