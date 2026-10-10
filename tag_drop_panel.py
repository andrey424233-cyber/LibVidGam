from PyQt5.QtCore import Qt, QMimeData, pyqtSignal
from PyQt5.QtGui import QDrag, QPixmap, QPainter, QColor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QAbstractItemView,
                             QPushButton)

from database import Database


LIBTAG_MIME = 'application/x-libtag'


class DraggableTagList(QListWidget):
    """Список тегов, которые можно перетаскивать на карточки."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a; color: #e0e0e0;
                border: 1px solid #2a2a2a; border-radius: 6px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-radius: 4px;
                margin: 2px 4px;
            }
            QListWidget::item:hover {
                background-color: #2a2a2a;
            }
            QListWidget::item:selected {
                background-color: #c0392b;
                color: #ffffff;
            }
        """)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if not item:
            return
        tag_name = item.data(Qt.UserRole)
        if not tag_name:
            return

        mime = QMimeData()
        mime.setData(LIBTAG_MIME, str(tag_name).encode('utf-8'))
        mime.setText(str(tag_name))

        drag = QDrag(self)
        drag.setMimeData(mime)

        pix = QPixmap(150, 32)
        pix.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(192, 57, 43, 235))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, 150, 32, 6, 6)
        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignCenter, str(tag_name))
        painter.end()
        drag.setPixmap(pix)
        drag.setHotSpot(pix.rect().center())

        drag.exec_(Qt.CopyAction)


class TagDropPanel(QWidget):
    """Правая выезжающая панель со всеми тегами."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setFixedWidth(220)
        self.setStyleSheet("""
            TagDropPanel {
                background-color: #151515;
                border-left: 1px solid #2a2a2a;
            }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("🏷️ Теги")
        title.setStyleSheet(
            "QLabel { color: #ffffff; font-size: 14px; font-weight: bold; }"
        )
        header.addWidget(title)
        header.addStretch()

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setToolTip("Скрыть панель")
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #888;
                border: none; font-size: 14px;
            }
            QPushButton:hover { color: #fff; }
        """)
        header.addWidget(self.btn_close)
        layout.addLayout(header)

        hint = QLabel("Перетащите тег на тайтл, чтобы назначить его.")
        hint.setWordWrap(True)
        hint.setStyleSheet("QLabel { color: #777; font-size: 11px; }")
        layout.addWidget(hint)

        self.tag_list = DraggableTagList()
        layout.addWidget(self.tag_list, 1)

        self.count_label = QLabel("0 тегов")
        self.count_label.setStyleSheet("QLabel { color: #666; font-size: 11px; }")
        layout.addWidget(self.count_label)

        self.setLayout(layout)

    def refresh(self):
        self.tag_list.clear()
        try:
            tags = self.db.get_all_tags()
        except Exception:
            tags = []
        for t in tags:
            name = t['name'] if isinstance(t, dict) else t
            item = QListWidgetItem(str(name))
            item.setData(Qt.UserRole, str(name))
            item.setToolTip(f"Перетащите «{name}» на тайтл")
            self.tag_list.addItem(item)
        self.count_label.setText(f"{len(tags)} тегов")