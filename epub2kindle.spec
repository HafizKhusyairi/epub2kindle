# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

_pil_hidden = collect_submodules('PIL')
_pil_exclude = {
    'PIL.ImageTk', 'PIL._imagingtk', 'PIL._tkinter_finder',
    'PIL.ImageQt', 'PIL.ImageGrab', 'PIL.ImageWin', 'PIL.PSDraw',
}
hidden_imports = [m for m in _pil_hidden if m not in _pil_exclude]

a = Analysis(
    ['_entry.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_tkinter', 'unittest', 'test', 'distutils'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='epub2kindle',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,      # strip=True can break macOS binaries
    upx=False,        # UPX unavailable on CI runners; triggers Windows Defender false positives
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None, # inherits from build host: ARM64 on macos-latest, x86_64 on macos-13
    codesign_identity=None,
    entitlements_file=None,
)
