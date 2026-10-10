"""Карточка группы: коллаж обложек + название + счётчик.

Размеры и разметка совпадают с обычной карточкой библиотеки:
  * Сверху — коллаж (высота как обложка у ComicCard)
  * Снизу — название группы и счётчик работ (как title/views)

Отличия от обычной карточки:
  * Красная рамка (маркер группы)
  * В правом верхнем углу коллажа — маленький бейдж с числом работ
"""
from PyQt5.QtCore import Qt, pyqtSignal, QRect
from PyQt5.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QImage
from PyQt5.QtWidgets import QWidget, QSizePolicy


def _plural_works(n):
    """N работа / N работы / N работ."""
    try:
        n = int(n)
    except Exception:
        return f"{n} работ"
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} работа"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return f"{n} работы"
    return f"{n} работ"


class GroupCard(QWidget):
    clicked = pyqtSignal()

    def __init__(self, title, count, pixmaps,
                 kind='author', expanded=False,
                 width=180, height=240, parent=None):
        super().__init__(parent)
        self.title = title
        self.count = count
        self.kind = kind
        self.expanded = expanded
        self._card_w = width
        self._card_h = height

        converted = []
        for p in (pixmaps or []):
            if p is None or p.isNull():
                continue
            if isinstance(p, QImage):
                p = QPixmap.fromImage(p)
            converted.append(p)
        self.pixmaps = converted[:4]

        self.setFixedSize(width, height)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_pixmaps(self, pixmaps):
        converted = []
        for p in (pixmaps or []):
            if p is None or p.isNull():
                continue
            if isinstance(p, QImage):
                p = QPixmap.fromImage(p)
            converted.append(p)
        self.pixmaps = converted[:4]
        self.update()

    def set_expanded(self, expanded):
        if self.expanded != expanded:
            self.expanded = expanded
            self.update()

    def resize_card(self, new_w, new_h):
        if new_w == self._card_w and new_h == self._card_h:
            return
        self._card_w = new_w
        self._card_h = new_h
        self.setFixedSize(new_w, new_h)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w = self.width()
        h = self.height()

        # Фон всей карточки — как у обычной
        bg_rect = self.rect().adjusted(1, 1, -2, -2)
        painter.setBrush(QColor('#1a1a1a'))
        pen_w = 3 if self.expanded else 2
        painter.setPen(QPen(QColor('#c0392b'), pen_w))
        painter.drawRoundedRect(bg_rect, 6, 6)

        # Разметка — как у ComicCard:
        #   верх:   коллаж = h - 44
        #   низ:    title 20 + count 15
        pad = 4
        title_h = 20
        count_h = 15
        cover_h = h - title_h - count_h - 2 * pad
        if cover_h < 40:
            cover_h = max(20, h - 2 * pad)

        cover_rect = QRect(pad, pad, w - 2 * pad, cover_h)

        if self.pixmaps and cover_rect.width() > 4 and cover_rect.height() > 4:
            self._draw_collage(painter, cover_rect)
        else:
            painter.fillRect(cover_rect, QColor('#0d0d0d'))
            icon = '👤' if self.kind == 'author' else '📚'
            painter.setPen(QColor('#444'))
            f = QFont(painter.font())
            f.setPointSize(max(24, min(64, cover_rect.width() // 3)))
            painter.setFont(f)
            painter.drawText(cover_rect, Qt.AlignCenter, icon)

        # Бейдж с количеством — в правом верхнем углу коллажа
        self._draw_badge(painter, cover_rect)

        # Название группы — как title у ComicCard
        title_rect = QRect(pad, cover_rect.bottom() + 1,
                           w - 2 * pad, title_h)
        painter.setPen(QColor('#ffffff'))
        f = QFont(painter.font())
        f.setPointSize(max(9, min(12, w // 22)))
        f.setBold(True)
        painter.setFont(f)
        icon = '👤' if self.kind == 'author' else '📚'
        full_title = f"{icon} {self.title}"
        elided = painter.fontMetrics().elidedText(
            full_title, Qt.ElideRight, title_rect.width()
        )
        painter.drawText(title_rect, Qt.AlignHCenter | Qt.AlignTop, elided)

        # Счётчик работ — как views у ComicCard
        count_rect = QRect(pad, title_rect.bottom(),
                           w - 2 * pad, count_h)
        painter.setPen(QColor('#aaaaaa'))
        f = QFont(painter.font())
        f.setPointSize(8)
        f.setBold(False)
        painter.setFont(f)
        painter.drawText(count_rect, Qt.AlignHCenter | Qt.AlignTop,
                         _plural_works(self.count))

        painter.end()

    def _draw_collage(self, painter, rect):
        if rect.width() <= 4 or rect.height() <= 4:
            return
        n = len(self.pixmaps)
        if n == 0:
            return
        if n == 1:
            pix = self.pixmaps[0].scaled(
                rect.size(), Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
            painter.drawPixmap(rect, pix)
            return

        if n == 2:
            cols, rows = 2, 1
        else:
            cols, rows = 2, 2

        cell_w = rect.width() // cols
        cell_h = rect.height() // rows
        if cell_w <= 0 or cell_h <= 0:
            return

        for i, pix in enumerate(self.pixmaps):
            col = i % cols
            row = i // cols
            if row >= rows:
                break
            cell_rect = QRect(
                rect.left() + col * cell_w,
                rect.top() + row * cell_h,
                cell_w, cell_h
            )
            scaled = pix.scaled(
                cell_rect.size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
            painter.drawPixmap(cell_rect, scaled)

    def _draw_badge(self, painter, cover_rect):
        text = str(self.count)
        f = QFont(painter.font())
        f.setPointSize(9)
        f.setBold(True)
        painter.setFont(f)

        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(text)
        badge_w = max(28, text_w + 16)
        badge_h = 20

        badge_rect = QRect(
            cover_rect.right() - badge_w - 4,
            cover_rect.top() + 4,
            badge_w, badge_h
        )

        painter.setBrush(QColor(192, 57, 43, 235))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 10, 10)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(badge_rect, Qt.AlignCenter, text)