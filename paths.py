"""Единая точка правды для путей. Работает и в dev, и в PyInstaller .exe.

Поддерживает Windows, Linux и macOS.

Правила:
  * APP_DIR       — папка, куда пишутся данные (БД, конфиг, логи, кэш).
                    В dev — папка со скриптами,
                    в .exe — папка рядом с .exe.
  * RESOURCES_DIR — папка с ресурсами (иконка, встроенные .exe).
                    В dev — папка со скриптами,
                    в .exe — sys._MEIPASS.
  * resource(...) — путь к ресурсу (иконка, бинарник).
  * tool_path(...) — ищет внешний инструмент (UnRAR, 7z):
                    сначала APP_DIR, потом RESOURCES_DIR, потом PATH.
"""
import os
import shutil
import sys


# ─── Версия приложения ───
APP_VERSION = "1.1.0"


# ─── Определение платформы ───
IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform.startswith('linux')
IS_MAC = sys.platform == 'darwin'


def _is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def app_dir() -> str:
    """Папка для пользовательских данных (БД, конфиг, логи, кэш)."""
    if _is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resources_dir() -> str:
    """Папка с упакованными ресурсами (иконка, встроенные exe)."""
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


def resource(rel_path: str) -> str:
    """Путь к ресурсу внутри упаковки (или рядом со скриптами в dev)."""
    return os.path.join(resources_dir(), rel_path)


def tool_path(*names) -> str:
    """Ищет первый доступный файл из списка имён.

    Приоритет:
      1) APP_DIR/<name>       — рядом с .exe или скриптами
      2) RESOURCES_DIR/<name> — в _MEIPASS
      3) PATH                 — системная установка (shutil.which)
    """
    if not names:
        return ''
    for name in names:
        if not name:
            continue
        # 1, 2 — локально
        for base in (app_dir(), resources_dir()):
            candidate = os.path.join(base, name)
            if os.path.isfile(candidate):
                return candidate
        # 3 — в PATH
        p = shutil.which(name)
        if p:
            return p
    # Не нашли — возвращаем первое имя как fallback
    return names[0]


APP_DIR = app_dir()
RESOURCES_DIR = resources_dir()

DB_PATH = os.path.join(APP_DIR, 'comics.db')
CONFIG_PATH = os.path.join(APP_DIR, 'appearance_config.json')
LOG_PATH = os.path.join(APP_DIR, 'app.log')
COVERS_DIR = os.path.join(APP_DIR, 'covers')


# ─── Иконка приложения ───
# Windows: .ico; Linux/macOS: .png
ICON_PATH = ''
for icon_name in ('icon.ico', 'icon.png'):
    p = resource(icon_name)
    if os.path.isfile(p):
        ICON_PATH = p
        break


# ─── Инструменты распаковки архивов ───
# Используются только в archive_extractor при работе с .rar/.7z играми.
# На Linux ищутся unrar / 7z без расширения.

if IS_WINDOWS:
    UNRAR_PATH = tool_path(
        'UnRAR.exe', 'unrar.exe', 'Rar.exe', 'rar.exe'
    )
    SEVENZIP_PATH = tool_path(
        '7z.exe', '7za.exe', '7zr.exe'
    )
else:
    UNRAR_PATH = tool_path(
        'unrar', 'rar', 'unrar-free'
    )
    SEVENZIP_PATH = tool_path(
        '7z', '7za', '7zr', '7zz'
    )


try:
    os.makedirs(COVERS_DIR, exist_ok=True)
except OSError:
    pass