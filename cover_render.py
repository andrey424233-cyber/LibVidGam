"""Рендер обложек: размытый фон + эффект стопки страниц + рамка.

Все операции — на QPainter, без PIL и без промежуточных PNG.
Это позволяет рендерить сотни обложек без заметных задержек.
"""
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import (QPixmap, QPainter, QColor, QPen,
                         QLinearGradient, QBrush)


# ---------- стопка ----------

STACK_EXTRA_TOP = 22       # высота области стопки над обложкой
STACK_PAGES = 4            # число «кромок страниц»
STACK_LAYER_HEIGHT = 5     # высота одной кромки
STACK_MIN_SCALE = 0.82     # ширина самой узкой кромки (от ширины обложки)
STACK_MAX_SCALE = 1.00     # ширина самой широкой кромки


def apply_stack_effect(pixmap: QPixmap) -> QPixmap:
    """Рисует «стопку страниц» над обложкой и тонкую рамку по периметру.

    Возвращает новый QPixmap: высота = высота исходника + STACK_EXTRA_TOP.
    Если pixmap пустой — возвращает его же без изменений.
    """
    if pixmap is None or pixmap.isNull():
        return pixmap

    w = pixmap.width()
    h = pixmap.height()
    if w <= 0 or h <= 0:
        return pixmap

    result = QPixmap(w, h + STACK_EXTRA_TOP)
    result.fill(QColor(0, 0, 0, 0))

    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    _draw_stack_layers(painter, w)
    _draw_front_cover(painter, pixmap)
    _draw_stack_shadow(painter, w)
    _draw_border(painter, w, h)

    painter.end()
    return result


def _draw_stack_layers(painter: QPainter, w: int):
    """Рисует кромки страниц. Сверху — самая узкая, снизу — самая широкая."""
    n = STACK_PAGES
    if n <= 1:
        return

    for i in range(n):
        offset_y = i * STACK_LAYER_HEIGHT
        progress = i / (n - 1)
        layer_width = int(w * (STACK_MIN_SCALE
                               + (STACK_MAX_SCALE - STACK_MIN_SCALE) * progress))
        offset_x = (w - layer_width) // 2

        # Градиент: сверху светлее, снизу темнее — эффект толщины страницы.
        top_shade = 78 + int(progress * 42)      # 78..120
        bottom_shade = 18 + int(progress * 14)   # 18..32

        grad = QLinearGradient(0, offset_y, 0, offset_y + STACK_LAYER_HEIGHT)
        grad.setColorAt(0.0, QColor(top_shade, top_shade, top_shade, 255))
        grad.setColorAt(1.0, QColor(bottom_shade, bottom_shade, bottom_shade, 255))
        painter.fillRect(offset_x, offset_y, layer_width, STACK_LAYER_HEIGHT,
                         QBrush(grad))

        # Светлая линия сверху — блик.
        highlight = 150 + int(progress * 70)     # 150..220
        painter.setPen(QPen(QColor(highlight, highlight, highlight, 220), 1))
        painter.drawLine(offset_x, offset_y,
                         offset_x + layer_width - 1, offset_y)

        # Тёмная линия снизу — тень между страницами.
        painter.setPen(QPen(QColor(0, 0, 0, 200), 1))
        painter.drawLine(offset_x, offset_y + STACK_LAYER_HEIGHT - 1,
                         offset_x + layer_width - 1,
                         offset_y + STACK_LAYER_HEIGHT - 1)


def _draw_front_cover(painter: QPainter, pixmap: QPixmap):
    """Рисует саму обложку под стопкой."""
    painter.drawPixmap(0, STACK_EXTRA_TOP, pixmap)


def _draw_stack_shadow(painter: QPainter, w: int):
    """Мягкая тень от верхней обложки вниз на стопку."""
    depth = 16
    grad = QLinearGradient(0, STACK_EXTRA_TOP, 0, STACK_EXTRA_TOP + depth)
    grad.setColorAt(0.0, QColor(0, 0, 0, 110))
    grad.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.fillRect(0, STACK_EXTRA_TOP, w, depth, QBrush(grad))


def _draw_border(painter: QPainter, w: int, h: int):
    """Тонкая светлая рамка по периметру обложки (без стопки).

    Верхняя кромка рамки — прямо под стопкой. Боковые и нижняя — по краям
    обложки. Сделано так, чтобы рамка не пересекалась с кромками страниц.
    """
    painter.setRenderHint(QPainter.Antialiasing, False)

    # Внешняя тёмная линия (чтобы отделить обложку от фона карточки)
    painter.setPen(QPen(QColor(0, 0, 0, 200), 1))
    painter.drawRect(0, STACK_EXTRA_TOP, w - 1, h - 1)

    # Внутренняя светлая линия — собственно «окантовка»
    painter.setPen(QPen(QColor(255, 255, 255, 170), 1))
    painter.drawRect(1, STACK_EXTRA_TOP + 1, w - 3, h - 3)


# ---------- обложка с размытым фоном ----------

def render_cover(qimage, target_w: int, target_h: int,
                 blur_amount: int = 16,
                 darken_alpha: int = 110) -> QPixmap:
    """Возвращает QPixmap (target_w, target_h):
    фон — та же картинка, растянутая и размытая; передний план — обложка
    целиком по центру (без обрезки).
    """
    if qimage is None or qimage.isNull():
        return QPixmap()

    src = QPixmap.fromImage(qimage)
    result = QPixmap(target_w, target_h)
    result.fill(QColor(13, 13, 13))

    painter = QPainter(result)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    # Фон с обрезкой
    bg = src.scaled(target_w, target_h,
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation)
    if bg.width() > target_w or bg.height() > target_h:
        x = max(0, (bg.width() - target_w) // 2)
        y = max(0, (bg.height() - target_h) // 2)
        bg = bg.copy(x, y, target_w, target_h)

    # Размытие через downscale → upscale (без PIL)
    small_w = max(1, target_w // blur_amount)
    small_h = max(1, target_h // blur_amount)
    bg = bg.scaled(small_w, small_h,
                   Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    bg = bg.scaled(target_w, target_h,
                   Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    painter.drawPixmap(0, 0, bg)

    # Затемнение
    painter.fillRect(0, 0, target_w, target_h, QColor(0, 0, 0, darken_alpha))

    # Передний план по центру
    fg = src.scaled(target_w, target_h,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation)
    x = (target_w - fg.width()) // 2
    y = (target_h - fg.height()) // 2
    painter.drawPixmap(x, y, fg)

    painter.end()
    return result