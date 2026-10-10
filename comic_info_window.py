from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QTextEdit, QSpinBox, QPushButton,
                             QComboBox, QListWidget,
                             QGroupBox, QMessageBox)
from PyQt5.QtCore import Qt

from database import Database


DIALOG_STYLE = """
    QDialog { background-color: #1e1e1e; color: #e0e0e0; }
    QLabel { color: #e0e0e0; background: transparent; }
    QGroupBox {
        color: #ffffff; border: 1px solid #3a3a3a;
        border-radius: 8px; margin-top: 10px; padding-top: 15px;
        background-color: #252525;
    }
    QGroupBox::title {
        subcontrol-origin: margin; left: 15px; padding: 0 5px;
        color: #ffffff; font-weight: bold;
    }
    QLineEdit, QSpinBox {
        background-color: #2a2a2a; color: #ffffff;
        border: 1px solid #3a3a3a; border-radius: 5px;
        padding: 8px; selection-background-color: #c0392b; font-size: 13px;
    }
    QLineEdit:focus, QSpinBox:focus { border: 1px solid #c0392b; }
    QLineEdit::placeholder { color: #888888; }
    QSpinBox { padding: 5px; }
    QComboBox {
        background-color: #2a2a2a; color: #ffffff;
        border: 1px solid #3a3a3a; border-radius: 5px;
        padding: 8px; font-size: 13px;
    }
    QComboBox:focus { border: 1px solid #c0392b; }
    QComboBox::drop-down { border: none; width: 30px; }
    QComboBox QAbstractItemView {
        background-color: #2a2a2a; color: #ffffff;
        border: 1px solid #3a3a3a;
        selection-background-color: #c0392b; selection-color: #ffffff;
        font-size: 14px; padding: 4px; outline: none;
    }
    QComboBox QAbstractItemView::item { padding: 6px 8px; min-height: 24px; }
    QComboBox QAbstractItemView::item:hover { background-color: #3a3a3a; }
    QTextEdit {
        background-color: #2a2a2a; color: #ffffff;
        border: 1px solid #3a3a3a; border-radius: 5px;
        padding: 8px; selection-background-color: #c0392b; font-size: 13px;
    }
    QTextEdit:focus { border: 1px solid #c0392b; }
    QListWidget {
        background-color: #2a2a2a; color: #ffffff;
        border: 1px solid #3a3a3a; border-radius: 5px; font-size: 13px;
    }
    QListWidget::item { color: #ffffff; padding: 5px; min-height: 22px; }
    QListWidget::item:selected { background-color: #c0392b; color: #ffffff; }
    QPushButton {
        background-color: #2a2a2a; color: #ffffff;
        border: none; border-radius: 5px; padding: 8px 15px;
    }
    QPushButton:hover { background-color: #3a3a3a; }
"""


class ComicInfoDialog(QDialog):
    """Диалог редактирования информации о комиксе"""

    def __init__(self, comic: dict, db: Database, parent=None):
        super().__init__(parent)
        self.comic = comic
        self.db = db
        self.setWindowTitle(f"Редактирование: {comic['title']}")
        self.setFixedSize(600, 780)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ===== Основная информация =====
        info_group = QGroupBox("Основная информация")
        info_layout = QVBoxLayout()
        info_layout.setSpacing(10)

        info_layout.addWidget(self._create_label("Название:"))
        self.title_input = QLineEdit(comic['title'])
        self.title_input.setPlaceholderText("Введите название комикса...")
        info_layout.addWidget(self.title_input)

        info_layout.addWidget(self._create_label("Автор:"))
        self.author_combo = QComboBox()
        self.author_combo.setEditable(True)
        self.author_combo.setPlaceholderText("Выберите или введите автора")
        self.author_combo.addItem("")
        self.author_combo.addItems(self.db.get_all_authors())
        if comic.get('author_name'):
            self.author_combo.setCurrentText(comic['author_name'])
        info_layout.addWidget(self.author_combo)

        info_layout.addWidget(self._create_label("Серия:"))
        series_layout = QHBoxLayout()

        self.series_combo = QComboBox()
        self.series_combo.setEditable(True)
        self.series_combo.setPlaceholderText("Выберите или создайте серию")
        self.series_combo.addItem("")
        for s in self.db.get_all_series():
            self.series_combo.addItem(s['name'] if isinstance(s, dict) else s)
        if comic.get('series_name'):
            self.series_combo.setCurrentText(comic['series_name'])
        series_layout.addWidget(self.series_combo, 1)

        self.order_spin = QSpinBox()
        self.order_spin.setMinimum(1)
        self.order_spin.setMaximum(9999)
        self.order_spin.setValue(comic.get('series_order', 1) or 1)
        self.order_spin.setFixedWidth(80)
        self.order_spin.setToolTip("Порядковый номер в серии")
        series_layout.addWidget(self.order_spin)

        info_layout.addLayout(series_layout)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # ===== Описание =====
        desc_group = QGroupBox("Описание")
        desc_layout = QVBoxLayout()
        self.desc_input = QTextEdit()
        self.desc_input.setPlainText(comic.get('description', '') or '')
        self.desc_input.setMaximumHeight(120)
        desc_layout.addWidget(self.desc_input)
        desc_group.setLayout(desc_layout)
        layout.addWidget(desc_group)

        # ===== Теги =====
        tags_group = QGroupBox("Теги")
        tags_layout = QVBoxLayout()

        self.tags_list = QListWidget()
        self.tags_list.setMaximumHeight(140)
        for tag in self.db.get_comic_tags(comic['id']):
            self.tags_list.addItem(tag)
        tags_layout.addWidget(self.tags_list)

        tags_buttons = QHBoxLayout()
        self.tag_combo = QComboBox()
        self.tag_combo.setEditable(True)
        self.tag_combo.setPlaceholderText("Выберите или введите тег")
        self.tag_combo.addItems([
            t['name'] if isinstance(t, dict) else t for t in self.db.get_all_tags()
        ])

        self.btn_add_tag = QPushButton("+ Добавить")
        self.btn_add_tag.setFixedWidth(120)
        self.btn_add_tag.clicked.connect(self.add_tag)

        self.btn_remove_tag = QPushButton("- Удалить")
        self.btn_remove_tag.setFixedWidth(100)
        self.btn_remove_tag.clicked.connect(self.remove_tag)

        tags_buttons.addWidget(self.tag_combo, 1)
        tags_buttons.addWidget(self.btn_add_tag)
        tags_buttons.addWidget(self.btn_remove_tag)
        tags_layout.addLayout(tags_buttons)

        tags_group.setLayout(tags_layout)
        layout.addWidget(tags_group)

        # ===== Статистика =====
        views_group = QGroupBox("Статистика")
        views_layout = QHBoxLayout()
        views_layout.addWidget(QLabel(f"Количество просмотров: {comic.get('view_count', 0) or 0}"))
        views_layout.addStretch()
        views_group.setLayout(views_layout)
        layout.addWidget(views_group)

        # ===== Кнопки =====
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setFixedWidth(120)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton("💾 Сохранить")
        self.btn_save.setFixedWidth(150)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 10px 20px; font-weight: bold; font-size: 14px;
            }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_save.clicked.connect(self.save)

        buttons_layout.addWidget(self.btn_cancel)
        buttons_layout.addWidget(self.btn_save)
        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def _create_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("""
            QLabel { color: #e0e0e0; font-size: 13px;
                     font-weight: bold; background: transparent; }
        """)
        return label

    def add_tag(self):
        tag_name = self.tag_combo.currentText().strip()
        if not tag_name:
            return
        for i in range(self.tags_list.count()):
            if self.tags_list.item(i).text() == tag_name:
                QMessageBox.warning(self, "Ошибка", "Этот тег уже добавлен")
                return
        self.tags_list.addItem(tag_name)

    def remove_tag(self):
        current_item = self.tags_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Ошибка", "Выберите тег для удаления")
            return
        self.tags_list.takeItem(self.tags_list.row(current_item))

    def save(self):
        try:
            title = self.title_input.text().strip()
            if not title:
                QMessageBox.warning(self, "Ошибка", "Название не может быть пустым")
                return

            author_name = self.author_combo.currentText().strip()
            series_name = self.series_combo.currentText().strip()

            author_id = None
            if author_name:
                author_id = self.db.get_author_id(author_name) or self.db.add_author(author_name)

            series_id = self.db.add_series(series_name) if series_name else None

            self.db.update_comic(
                self.comic['id'],
                title=title,
                author_id=author_id,
                series_id=series_id,
                series_order=self.order_spin.value(),
                description=self.desc_input.toPlainText().strip()
            )

            tag_names = [
                self.tags_list.item(i).text()
                for i in range(self.tags_list.count())
                if self.tags_list.item(i).text() != self.db.NO_TAGS_NAME
            ]
            self.db.set_comic_tags(self.comic['id'], tag_names)

            QMessageBox.information(self, "Успех", "Изменения сохранены")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить: {e}")