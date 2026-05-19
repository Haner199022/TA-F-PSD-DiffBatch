# -*- mode: python ; coding: utf-8 -*-
# Windows-only build spec for TA-F PSD DiffBatch (v1.5.0+).
import os
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all

datas = [('normalize_psd.jsx', '.'), ('assets', 'assets'), ('scripts', 'scripts')]
# Ship the example config so a fresh checkout always has a NAS placeholder;
# ship the real config too if the build machine has one. nas_config.py
# prefers .json over .example.json at runtime, so layered shipping works.
datas += [('nas_config.example.json', '.')]
if os.path.exists('nas_config.json'):
    datas += [('nas_config.json', '.')]
binaries = []
hiddenimports = []
datas += collect_data_files('customtkinter')
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

icon_path = 'assets/AppIcon.ico' if os.path.exists('assets/AppIcon.ico') else None
version_file = 'version_info.txt' if os.path.exists('version_info.txt') else None

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy ML libraries that PyInstaller picks up from the system Python
        # env via pip-installed transitive deps but the app never imports.
        # Bundling them inflates the installer by 2+ GB (mostly torch DLLs).
        'torch', 'torchvision', 'torchaudio',
        'tensorflow', 'tensorboard',
        'transformers', 'datasets',
        'sklearn', 'scipy',
        'av', 'jinja2', 'fsspec',
        'matplotlib', 'pandas',
        'sympy', 'networkx',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TA-F PSD DiffBatch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX disabled in v1.5.0: trades ~15% larger output for a meaningful
    # drop in SmartScreen / antivirus false positives. The .exe is on a
    # private NAS to ~5 colleagues, so install-time friction matters more
    # than wire size. Re-enable only if a future build needs to stay under
    # a hard size budget.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
    version=version_file,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TA-F PSD DiffBatch',
)
