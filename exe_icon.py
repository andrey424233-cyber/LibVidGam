"""Извлечение иконки .exe файла.

Windows: использует QFileIconProvider — нативный провайдер иконок.
Linux/macOS: возвращает None — там .exe-файлов нет, и иконки берутся
из файлов cover.png / poster.jpg рядом с игрой (см. game_launcher).

Возвращает QImage или None.
"""
import os
import sys

from PyQt5.QtGui import QImage


IS_WINDOWS = sys.platform == 'win32'


# Кэш в памяти: (exe_path, size) -> QImage или None
_MEM_CACHE = {}

# Единственный экземпляр провайдера на процесс
_PROVIDER = None


def _get_provider():
    global _PROVIDER
    if _PROVIDER is None:
        try:
            from PyQt5.QtWidgets import QFileIconProvider
            _PROVIDER = QFileIconProvider()
        except Exception:
            _PROVIDER = False
    return _PROVIDER or None


def extract_exe_icon(exe_path: str, size: int = 256):
    """Извлекает иконку .exe. Возвращает QImage или None.

    На Windows — через QFileIconProvider.
    На Linux / macOS — сразу None.
    """
    # На не-Windows системах .exe иконки недоступны
    if not IS_WINDOWS:
        return None

    if not exe_path:
        return None

    key = (exe_path, size)
    if key in _MEM_CACHE:
        return _MEM_CACHE[key]

    if not os.path.isfile(exe_path):
        _MEM_CACHE[key] = None
        return None

    img = None
    try:
        provider = _get_provider()
        if provider is not None:
            from PyQt5.QtCore import QFileInfo
            icon = provider.icon(QFileInfo(exe_path))
            if icon is not None and not icon.isNull():
                # Пробуем несколько размеров, берём первый непустой
                for try_size in (256, 128, 64, 48, 32, 16):
                    pix = icon.pixmap(try_size, try_size)
                    if pix is not None and not pix.isNull():
                        img = pix.toImage()
                        break
    except Exception as e:
        print(f"[exe_icon] {exe_path}: {e}")
        img = None

    _MEM_CACHE[key] = img
    return img


def clear_cache():
    """Сбросить кэш в памяти."""
    _MEM_CACHE.clear()