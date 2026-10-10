"""Страница «Авторы»: сетка карточек с обложками и счётчиком работ.

Клик по карточке автора открывает меню выбора библиотеки, если работы
этого автора есть в нескольких. Если библиотека одна — переходит
сразу в неё.
"""
import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
                             QGridLayout, QLabel, QPushButton,
                             QMessageBox, QInputDialog, QMenu)

from database import Database


AUTHOR_CARD_W = 360
AUTHOR_CARD_H = 360
AUTHOR_ICON_SIZE = 260
MAX_AUTHOR_COLS = 3


class AuthorCard(QWidget):
    """Карточка автора с обложкой и счётчиком работ."""

    clicked = pyqtSignal(int)

    def __init__(self, author: dict, db: Database, parent=None):
        super().__init__(parent)
        self.author = author
        self.db = db
        self.author_id = author['id']

        self.setFixedSize(AUTHOR_CARD_W, AUTHOR_CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            AuthorCard {
                background-color: #1a1a1a;
                border: 1px solid #2a2a2a;
                border-radius: 10px;
            }
            AuthorCard:hover {
                border: 1px solid #c0392b;
            }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.icon_label = QLabel("👤")
        self.icon_label.setFixedSize(AUTHOR_ICON_SIZE, AUTHOR_ICON_SIZE)
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

        self.name_label = QLabel(author['name'])
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("""
            QLabel { color: #ffffff; font-size: 16px; font-weight: bold;
                     background: transparent; }
        """)
        layout.addWidget(self.name_label)

        comics = author.get('comic_count', 0) or 0
        videos = author.get('video_count', 0) or 0
        games = author.get('game_count', 0) or 0
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
        cover_path = self.author.get('cover_path')
        if cover_path and os.path.exists(cover_path):
            try:
                pixmap = QPixmap(cover_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(
                        AUTHOR_ICON_SIZE, AUTHOR_ICON_SIZE,
                        Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                    self.icon_label.setPixmap(scaled)
                    self.icon_label.setText("")
            except Exception as e:
                print(f"Ошибка загрузки обложки автора: {e}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.author_id)
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

        edit_action = menu.addAction("✏️ Редактировать")
        edit_action.triggered.connect(self.open_edit_dialog)

        delete_action = menu.addAction("🗑️ Удалить автора")
        delete_action.triggered.connect(self.delete_author)

        menu.exec_(self.mapToGlobal(event.pos()))

    def _refresh_parent(self):
        parent = self.parent()
        while parent and not hasattr(parent, 'refresh'):
            parent = parent.parent()
        if parent:
            parent.refresh()

    def open_edit_dialog(self):
        from author_edit_dialog import AuthorEditDialog
        dialog = AuthorEditDialog(self.author, self.db, self)
        if dialog.exec_():
            self._refresh_parent()

    def delete_author(self):
        comics = self.author.get('comic_count', 0) or 0
        videos = self.author.get('video_count', 0) or 0
        games = self.author.get('game_count', 0) or 0
        total = comics + videos + games

        if total > 0:
            msg = (
                f"Удалить автора «{self.author['name']}»?\n\n"
                f"У него {total} работ. Они останутся в библиотеке, "
                f"но без автора."
            )
        else:
            msg = f"Удалить автора «{self.author['name']}»?"

        reply = QMessageBox.question(
            self, "Подтверждение", msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self.db.delete_author(self.author_id)
            self._refresh_parent()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось удалить: {e}")


class AuthorsWindow(QWidget):
    """Страница «Авторы»."""

    comic_selected = pyqtSignal(str)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._has_been_loaded = False

        self.setStyleSheet("QWidget { background-color: #121212; }")

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        actions_layout = QHBoxLayout()

        self.btn_add_author = QPushButton("+ Создать автора")
        self.btn_add_author.setFixedSize(180, 40)
        self.btn_add_author.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: white;
                border: none; border-radius: 20px; font-size: 14px;
            }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_add_author.clicked.connect(self.create_author)
        actions_layout.addWidget(self.btn_add_author)

        actions_layout.addStretch()

        self.count_label = QLabel("0 авторов")
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

    # ---------- public API ----------

    def _initial_load(self):
        if not self._has_been_loaded:
            self._has_been_loaded = True
            self.load_authors()

    def refresh(self):
        self._has_been_loaded = True
        self.load_authors()

    def load_authors(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            authors = self.db.get_all_authors_with_covers()
        except Exception as e:
            print(f"[authors] get_all_authors_with_covers: {e}")
            authors = []

        self.count_label.setText(f"{len(authors)} авторов")

        row, col = 0, 0
        for author in authors:
            card = AuthorCard(author, self.db)
            card.clicked.connect(self.on_author_clicked)
            self.grid_layout.addWidget(card, row, col)

            col += 1
            if col >= MAX_AUTHOR_COLS:
                col = 0
                row += 1

        self.grid_layout.setRowStretch(row + 1, 1)

    def create_author(self):
        name, ok = QInputDialog.getText(self, "Новый автор", "Имя автора:")
        if ok and name.strip():
            try:
                self.db.add_author(name.strip())
                self.load_authors()
            except Exception as e:
                QMessageBox.warning(self, "Ошибка",
                                    f"Не удалось создать автора: {e}")

    # ---------- переход в библиотеку с фильтром по автору ----------

    def on_author_clicked(self, author_id: int):
        author = self.db.get_author(author_id)
        if not author:
            return
        author_name = author['name']

        app = self.window()
        if app is None or not hasattr(app, 'navigate_to_filtered'):
            return

        # Считаем работы в каждой библиотеке
        try:
            counts = app.count_in_libraries('author', author_name)
        except Exception as e:
            print(f"[authors] count_in_libraries: {e}")
            counts = {'comics': 0, 'videos': 0, 'games': 0}

        available = [(key, counts.get(key, 0))
                     for key in ('comics', 'videos', 'games')
                     if counts.get(key, 0) > 0]

        if not available:
            QMessageBox.information(
                self, "Нет работ",
                f"У автора «{author_name}» нет работ ни в одной библиотеке."
            )
            return

        if len(available) == 1:
            app.navigate_to_filtered(available[0][0], 'author', author_name)
            return

        # Меню выбора библиотеки
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

        chosen = menu.exec_(self.cursor().pos())
        if chosen is None:
            return
        lib_key = actions.get(chosen)
        if lib_key:
            app.navigate_to_filtered(lib_key, 'author', author_name)