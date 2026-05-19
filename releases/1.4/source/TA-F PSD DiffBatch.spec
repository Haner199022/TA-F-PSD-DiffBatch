# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all

datas = [('normalize_psd.jsx', '.'), ('assets', 'assets'), ('scripts', 'scripts')]
binaries = []
hiddenimports = []
datas += collect_data_files('customtkinter')
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Optional icon and version metadata — used on Windows; safely ignored on Mac.
icon_path = 'assets/AppIcon.ico' if os.path.exists('assets/AppIcon.ico') else None
version_file = 'version_info.txt' if (sys.platform == 'win32' and os.path.exists('version_info.txt')) else None

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='TA-F PSD DiffBatch',
)
app = BUNDLE(
    coll,
    name='TA-F PSD DiffBatch.app',
    icon=None,
    bundle_identifier=None,
)
