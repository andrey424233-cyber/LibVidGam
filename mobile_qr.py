"""Генерация QR-кода для мобильного доступа.

Использует библиотеку `qrcode` (pip install qrcode[pil]).
Возвращает QPixmap для вставки в QLabel.
"""
from PyQt5.QtGui import QPixmap, QImage
import io

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False


def make_qr_pixmap(data: str, size: int = 260) -> QPixmap:
    """Генерирует QR-код для строки data.

    Возвращает QPixmap размера (size, size). Если qrcode не установлен —
    пустой QPixmap.
    """
    if not HAS_QRCODE or not data:
        return QPixmap()

    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)

        # Получаем PIL.Image и конвертируем в QImage через bytes
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        qimg = QImage()
        qimg.loadFromData(buf.read())
        if qimg.isNull():
            return QPixmap()

        pix = QPixmap.fromImage(qimg)
        if size > 0 and pix.width() != size:
            pix = pix.scaled(size, size,
                             aspectRatioMode=1,      # KeepAspectRatio
                             transformMode=1)         # SmoothTransformation
        return pix
    except Exception as e:
        print(f"[mobile_qr] {e}")
        return QPixmap()