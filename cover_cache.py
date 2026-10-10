"""Дисковый кэш обложек. Один раз прочитали из архива — потом PNG с диска.

Запись атомарная: пишем во временный файл в той же папке, потом os.replace.
Это защищает от битых PNG, если два потока (например home_window и
library_window) запросят обложку одного файла одновременно.
"""
import hashlib
import os
import tempfile
import threading

from PyQt5.QtGui import QImage

from paths import COVERS_DIR


_IO_LOCK = threading.RLock()


def _key(file_path: str, size: tuple) -> str:
    raw = f"{file_path}|{size[0]}x{size[1]}".encode('utf-8')
    return hashlib.md5(raw).hexdigest()


def cover_path(file_path: str, size: tuple) -> str:
    return os.path.join(COVERS_DIR, f"{_key(file_path, size)}.png")


def load(file_path: str, size: tuple):
    """Вернуть QImage или None."""
    p = cover_path(file_path, size)
    if not os.path.exists(p):
        return None
    with _IO_LOCK:
        try:
            img = QImage(p)
        except Exception:
            return None
    return img if not img.isNull() else None


def save(file_path: str, size: tuple, qimage: QImage):
    """Сохраняет QImage в кэш. Атомарно: tempfile + os.replace."""
    if qimage is None or qimage.isNull():
        return
    p = cover_path(file_path, size)

    with _IO_LOCK:
        try:
            os.makedirs(COVERS_DIR, exist_ok=True)
        except OSError:
            return

        tmp_path = None
        try:
            # Пишем рядом, в той же папке — тогда os.replace атомарен
            # (в пределах одной файловой системы).
            fd, tmp_path = tempfile.mkstemp(
                prefix='.tmp_cover_', suffix='.png', dir=COVERS_DIR
            )
            os.close(fd)

            ok = qimage.save(tmp_path, 'PNG')
            if not ok:
                raise RuntimeError("QImage.save вернул False")

            os.replace(tmp_path, p)
            tmp_path = None  # успех — чистить нечего
        except Exception as e:
            print(f"[cover_cache] save({p}): {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


def clear_all():
    with _IO_LOCK:
        try:
            for name in os.listdir(COVERS_DIR):
                try:
                    os.remove(os.path.join(COVERS_DIR, name))
                except Exception:
                    pass
        except OSError:
            pass