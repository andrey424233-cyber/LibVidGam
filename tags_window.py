"""Страница «Теги»: сетка карточек с обложками и счётчиком работ.

Клик по карточке тега открывает меню выбора библиотеки, если работы
с этим тегом есть в нескольких. Если библиотека одна — переходит
сразу в неё.
"""
import os

from PyQt5.QtCore import Qt, pyqtSignal, QPoint
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
                             QGridLayout, QLabel, QPushButton,
                             QMessageBox, QInputDialog, QMenu)

from database import Database


TAG_CARD_W = 360
TAG_CARD_H = 360
TAG_ICON_SIZE = 260
MAX_TAG_COLS = 3


class TagCard(QWidget):
    """Карточка тега с обложкой и счётчиком работ."""

    clicked = pyqtSignal(int)

    def __init__(self, tag: dict, db: Database, parent=None):
        super().__init__(parent)
        self.tag = tag
        self.db = db
        self.tag_id = tag['id']

        self.setFixedSize(TAG_CARD_W, TAG_CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            TagCard {
                background-color: #1a1a1a;
                border: 1px solid #2a2a2a;
                border-radius: 10px;
            }
            TagCard:hover {
                border: 1px solid #c0392b;
            }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.icon_label = QLabel("🏷️")
        self.icon_label.setFixedSize(TAG_ICON_SIZE, TAG_ICON_SIZE)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("""
            QLabel {
                background-color: #1e1e1e;
                border-radius: 12px;
                font-size: 72px;
                border: 2px solid #c0392b;
            }
        """)
        layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)

        self.name_label = QLabel(tag['name'])
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("""
            QLabel { color: #ffffff; font-size: 16px; font-weight: bold;
                     background: transparent; }
        """)
        layout.addWidget(self.name_label)

        comics = tag.get('comic_count', 0) or 0
        videos = tag.get('video_count', 0) or 0
        games = tag.get('game_count', 0) or 0
        total = comics + videos + games

        if total == 0:
            text = "нет работ"
        elif total == 1:
            text = "1 работа"
        else:
            text = f"{total} работ"

        self.count_label = QLabel(text)
        self.count_label.setAlignment(Qt.AlignCenter)
        self.count_label.setStyleSheet(
            "QLabel { color: #888; font-size: 13px; background: transparent; }"
        )

        details = []
        if comics:
            details.append(f"{comics} комиксов")
        if videos:
            details.append(f"{videos} видео")
        if games:
            details.append(f"{games} игр")
        if details:
            self.count_label.setToolTip(" · ".join(details))

        layout.addWidget(self.count_label)

        self.setLayout(layout)
        self.load_cover()

    def load_cover(self):
        cover_path = self.tag.get('cover_path')
        if cover_path and os.path.exists(cover_path):
            try:
                pixmap = QPixmap(cover_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(
                        TAG_ICON_SIZE, TAG_ICON_SIZE,
                        Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                    self.icon_label.setPixmap(scaled)
                    self.icon_label.setText("")
            except Exception as e:
                print(f"Ошибка загрузки обложки тега: {e}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.tag_id)
        elif event.button() == Qt.RightButton:
            self.show_context_menu(event)

    def show_context_menu(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e1e1e; color: #e0e0e0;
                border: 1px solid #3a3a3a; border-radius: 5px; padding: 5px;
            }
            QMenu::item:selected { background-color: #c0392b; }
        """)

        edit_action = menu.addAction("✏️ Редактировать тег")
        edit_action.triggered.connect(self.open_edit_dialog)

        delete_action = menu.addAction("🗑️ Удалить тег")
        delete_action.triggered.connect(self.delete_tag)

        menu.exec_(self.mapToGlobal(event.pos()))

    def _refresh_parent(self):
        parent = self.parent()
        while parent and not hasattr(parent, 'refresh'):
            parent = parent.parent()
        if parent:
            parent.refresh()

    def open_edit_dialog(self):
        from tag_edit_dialog import TagEditDialog
        dialog = TagEditDialog(self.tag, self.db, self)
        if dialog.exec_():
            self._refresh_parent()

    def delete_tag(self):
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить тег '{self.tag['name']}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.db.delete_tag(self.tag['name'])
            self._refresh_parent()


class TagsWindow(QWidget):
    """Страница тегов."""

    comic_selected = pyqtSignal(str)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.hidden_tags = []
        self._has_been_loaded = False

        self.setStyleSheet("QWidget { background-color: #121212; }")

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        actions_layout = QHBoxLayout()

        self.btn_add_tag = QPushButton("+ Создать тег")
        self.btn_add_tag.setFixedSize(150, 40)
        self.btn_add_tag.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: white;
                border: none; border-radius: 20px; font-size: 14px;
            }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_add_tag.clicked.connect(self.create_tag)
        actions_layout.addWidget(self.btn_add_tag)

        actions_layout.addStretch()

        self.count_label = QLabel("0 тегов")
        self.count_label.setStyleSheet("QLabel { color: #888; font-size: 14px; }")
        actions_layout.addWidget(self.count_label)

        layout.addLayout(actions_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea { border: none; background-color: #121212; }
        """)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(16)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_widget.setLayout(self.grid_layout)

        scroll_area.setWidget(self.grid_widget)
        layout.addWidget(scroll_area)

        self.setLayout(layout)

    def _initial_load(self):
        if not self._has_been_loaded:
            self._has_been_loaded = True
            self.load_tags()

    def set_hidden_tags(self, tags):
        new_tags = list(tags or [])
        if new_tags == self.hidden_tags:
            return
        self.hidden_tags = new_tags
        if self._has_been_loaded:
            self.load_tags()

    def refresh(self):
        self._has_been_loaded = True
        self.load_tags()

    def load_tags(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tags = self.db.get_all_tags()

        if self.hidden_tags:
            hidden_set = set(self.hidden_tags)
            tags = [t for t in tags if t['name'] not in hidden_set]

        self.count_label.setText(f"{len(tags)} тегов")

        row, col = 0, 0

        for tag in tags:
            card = TagCard(tag, self.db)
            card.clicked.connect(self.on_tag_clicked)
            self.grid_layout.addWidget(card, row, col)

            col += 1
            if col >= MAX_TAG_COLS:
                col = 0
                row += 1

        self.grid_layout.setRowStretch(row + 1, 1)

    def create_tag(self):
        tag_name, ok = QInputDialog.getText(self, "Новый тег", "Название тега:")
        if ok and tag_name.strip():
            self.db.add_tag(tag_name.strip())
            self.load_tags()

    # ---------- переход в библиотеку с фильтром по тегу ----------

    def on_tag_clicked(self, tag_id: int):
        tags = self.db.get_all_tags()
        tag_name = None
        for t in tags:
            if t['id'] == tag_id:
                tag_name = t['name']
                break

        if not tag_name:
            return

        app = self.window()
        if app is None or not hasattr(app, 'navigate_to_filtered'):
            return

        # Считаем работы в каждой библиотеке
        try:
            counts = app.count_in_libraries('tag', tag_name)
        except Exception as e:
            print(f"[tags] count_in_libraries: {e}")
            counts = {'comics': 0, 'videos': 0, 'games': 0}

        # Какие библиотеки непустые
        available = [(key, counts.get(key, 0))
                     for key in ('comics', 'videos', 'games')
                     if counts.get(key, 0) > 0]

        if not available:
            QMessageBox.information(
                self, "Нет работ",
                f"С тегом «{tag_name}» нет работ ни в одной библиотеке."
            )
            return

        # Если только одна — переходим сразу
        if len(available) == 1:
            app.navigate_to_filtered(available[0][0], 'tag', tag_name)
            return

        # Иначе — меню выбора
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e1e1e; color: #e0e0e0;
                border: 1px solid #3a3a3a; border-radius: 5px;
                padding: 5px; font-size: 13px;
            }
            QMenu::item { padding: 8px 24px; }
            QMenu::item:selected { background-color: #c0392b; }
        """)

        icons = {
            'comics': '📚',
            'videos': '📹',
            'games': '🎮',
        }
        names = {
            'comics': 'Комиксы',
            'videos': 'Видео',
            'games': 'Игры',
        }

        actions = {}
        for key, n in available:
            label = f"{icons[key]}  {names[key]} ({n})"
            act = menu.addAction(label)
            actions[act] = key

        # Показываем меню рядом с курсором
        chosen = menu.exec_(self.cursor().pos())
        if chosen is None:
            return
        lib_key = actions.get(chosen)
        if lib_key:
            app.navigate_to_filtered(lib_key, 'tag', tag_name)