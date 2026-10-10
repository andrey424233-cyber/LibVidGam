# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec для LibVidGam."""
import os


block_cipher = None


datas = []

if os.path.isfile('icon.ico'):
    datas.append(('icon.ico', '.'))

for tool in ('UnRAR.exe', '7z.exe'):
    if os.path.isfile(tool):
        datas.append((tool, '.'))


hiddenimports = [
    # Работа с архивами
    'py7zr',
    'pyzipper',
    'rarfile',

    # Изображения
    'PIL',
    'PIL.Image',
    'PIL.ImageFilter',

    # Видео/кадры
    'cv2',
    'numpy',

    # Qt
    'PyQt5.QtMultimedia',
    'PyQt5.QtMultimediaWidgets',

    # Windows
    'winreg',

    # Flask + мобильный доступ
    'flask',
    'flask_sock',
    'simple_websocket',
    'wsproto',
    'werkzeug',
    'werkzeug.serving',
    'jinja2',
    'markupsafe',
    'itsdangerous',
    'click',
    'blinker',
    'h11',

    # QR-код
    'qrcode',
    'qrcode.image.pil',
    'qrcode.image.pure',
]


excludes = [
    'tkinter',
    'matplotlib',
    'scipy',
    'pandas',
    'IPython',
    'jupyter',
    'notebook',
    'PyQt5.QtWebEngineWidgets',
    'PyQt5.QtWebEngineCore',
    'PyQt5.QtWebEngine',
    'PyQt5.QtQuick',
    'PyQt5.QtQml',
    'PyQt5.QtDesigner',
    'PyQt5.QtHelp',
    'PyQt5.QtTest',
    'PyQt5.QtBluetooth',
    'PyQt5.QtNfc',
    'PyQt5.QtPositioning',
    'PyQt5.QtSerialPort',
    'PyQt5.QtSensors',
    'PyQt5.QtSql',
    'PyQt5.QtXml',
]


a = Analysis(
    ['Main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)


exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LibVidGam',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico' if os.path.isfile('icon.ico') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='LibVidGam',
)