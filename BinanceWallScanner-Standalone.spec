# -*- mode: python ; coding: utf-8 -*-

import os
import sys


PYTHON_DIR = sys.base_prefix
DLLS_DIR = os.path.join(PYTHON_DIR, 'DLLs')
TKINTER_DIR = os.path.join(PYTHON_DIR, 'Lib', 'tkinter')
RUNTIME_ROOT = os.environ.get('TCLTK_RUNTIME_DIR', r'C:\TMM_Cutter\runtime')
DEFAULT_TCL_DIR = os.path.join(RUNTIME_ROOT, 'tcl8.6')
DEFAULT_TK_DIR = os.path.join(RUNTIME_ROOT, 'tk8.6')
if not os.path.exists(os.path.join(DEFAULT_TCL_DIR, 'init.tcl')):
    DEFAULT_TCL_DIR = os.path.join(PYTHON_DIR, 'tcl', 'tcl8.6')
if not os.path.exists(os.path.join(DEFAULT_TK_DIR, 'tk.tcl')):
    DEFAULT_TK_DIR = os.path.join(PYTHON_DIR, 'tcl', 'tk8.6')
TCL_DIR = os.environ.get('TCL_LIBRARY', DEFAULT_TCL_DIR)
TK_DIR = os.environ.get('TK_LIBRARY', DEFAULT_TK_DIR)
TKINTER_BINARIES = [
    (os.path.join(DLLS_DIR, '_tkinter.pyd'), '.'),
    (os.path.join(DLLS_DIR, 'tcl86t.dll'), '.'),
    (os.path.join(DLLS_DIR, 'tk86t.dll'), '.'),
    (r'C:\TMM_Cutter\ffmpeg.exe', '.'),
]
TKINTER_DATAS = [
    (TKINTER_DIR, 'tkinter'),
    (TCL_DIR, '_tcl_data'),
    (TK_DIR, '_tk_data'),
    ('sounds', 'sounds'),
    ('assets', 'assets'),
    ('custom_logic.py', '.'),
]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=TKINTER_BINARIES,
    datas=TKINTER_DATAS,
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        '_tkinter',
    ],
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
    a.binaries,
    a.datas,
    [],
    name='BinanceWallScanner-Standalone',
    icon='assets\\merged_project_icon.ico',
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
