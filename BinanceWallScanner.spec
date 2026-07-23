# -*- mode: python ; coding: utf-8 -*-

import os
import sys


PYTHON_DIR = sys.base_prefix
DLLS_DIR = os.path.join(PYTHON_DIR, 'DLLs')
TKINTER_DIR = os.path.join(PYTHON_DIR, 'Lib', 'tkinter')
RUNTIME_ROOT = os.environ.get('TCLTK_RUNTIME_DIR', r'C:\TMM_Cutter\runtime')
TCL_DIR = os.environ.get('TCL_LIBRARY', os.path.join(RUNTIME_ROOT, 'tcl8.6'))
TK_DIR = os.environ.get('TK_LIBRARY', os.path.join(RUNTIME_ROOT, 'tk8.6'))
TKINTER_BINARIES = [
    (os.path.join(DLLS_DIR, '_tkinter.pyd'), '.'),
    (os.path.join(DLLS_DIR, 'tcl86t.dll'), '.'),
    (os.path.join(DLLS_DIR, 'tk86t.dll'), '.'),
]
TKINTER_DATAS = [
    (TKINTER_DIR, 'tkinter'),
    (TCL_DIR, '_tcl_data'),
    (TK_DIR, '_tk_data'),
    ('sounds', 'sounds'),
]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=TKINTER_BINARIES,
    datas=TKINTER_DATAS,
    hiddenimports=['_tkinter'],
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
    name='BinanceWallScanner',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BinanceWallScanner',
)
