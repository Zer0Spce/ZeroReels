from PyInstaller.utils.hooks import collect_all

kokoro_datas, kokoro_bins, kokoro_hidden = collect_all("kokoro_onnx")
espeak_datas, espeak_bins, espeak_hidden = collect_all("espeakng_loader")
phon_datas, phon_bins, phon_hidden = collect_all("phonemizer")
ff_datas, ff_bins, ff_hidden = collect_all("imageio_ffmpeg")

a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    binaries=kokoro_bins + espeak_bins + phon_bins + ff_bins,
    datas=kokoro_datas + espeak_datas + phon_datas + ff_datas,
    hiddenimports=kokoro_hidden + espeak_hidden + phon_hidden + ff_hidden,
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
    name="ZeroReels",
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
    name="ZeroReels",
)
