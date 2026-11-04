# -*- mode: python ; coding: utf-8 -*-
# Build a single standalone Siphon.exe that bundles Python and every package,
# so the finished file needs nothing installed to run.
#
#   Run Derle.bat (in the project root) on Windows — it installs the build
#   tools and calls this spec.  The result is dist\Siphon.exe.
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = []
binaries = []
hiddenimports = [
    'bs4', 'cloudscraper', 'Crypto.Cipher.AES', 'm3u8',
    'imageio_ffmpeg', 'imageio_ffmpeg.binaries',
    'customtkinter', 'curl_cffi', '_cffi_backend',
    'certifi', 'faulthandler',
    'siphon.core.crashlog', 'siphon.core.updater', 'siphon.core.browser',
    'socks', 'urllib3.contrib.socks',
]

# Package data: cloudscraper browser profiles, certifi certs, CustomTkinter
# themes, the bundled ffmpeg, the curl_cffi binary.
for pkg in ('cloudscraper', 'certifi', 'customtkinter', 'curl_cffi',
            'imageio_ffmpeg'):
    collected = collect_all(pkg)
    datas += collected[0]
    binaries += collected[1]
    hiddenimports += collected[2]

datas += [
    ('..\\..\\LICENSE', '.'),
    ('..\\..\\THIRD_PARTY_NOTICES.md', '.'),
]


a = Analysis(
    ['..\\..\\src\\siphon\\entrypoints\\browse.py'],
    pathex=['..\\..\\src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['ctranslate2', 'sentencepiece', 'opencc', 'numpy', 'yaml',
              'torch', 'tensorflow'],
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
    name='Siphon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='Siphon.version',
)
