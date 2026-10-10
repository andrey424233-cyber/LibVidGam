from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QTextEdit, QSpinBox, QPushButton,
                             QComboBox, QListWidget, QGroupBox, QMessageBox)
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
    QComboBox {
        background-color: #2a2a2a; color: #ffffff;
        border: 1px solid #3a3a3a; border-radius: 5px;
        padding: 8px; font-size: 13px;
    }
    QComboBox::drop-down { border: none; width: 30px; }
    QComboBox QAbstractItemView {
        background-color: #2a2a2a; color: #ffffff;
        border: 1px solid #3a3a3a;
        selection-background-color: #c0392b; selection-color: #ffffff;
    }
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


class VideoInfoDialog(QDialog):
    def __init__(self, video: dict, db: Database, parent=None):
        super().__init__(parent)
        self.video = video
        self.db = db
        self.setWindowTitle(f"Редактирование: {video['title']}")
        self.setFixedSize(600, 720)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Основная информация
        info_group = QGroupBox("Основная информация")
        il = QVBoxLayout()
        il.setSpacing(10)

        il.addWidget(self._lbl("Название:"))
        self.title_input = QLineEdit(video['title'])
        il.addWidget(self.title_input)

        il.addWidget(self._lbl("Автор:"))
        self.author_combo = QComboBox()
        self.author_combo.setEditable(True)
        self.author_combo.addItem("")
        self.author_combo.addItems(self.db.get_all_authors())
        if video.get('author_name'):
            self.author_combo.setCurrentText(video['author_name'])
        il.addWidget(self.author_combo)

        il.addWidget(self._lbl("Серия:"))
        row = QHBoxLayout()
        self.series_combo = QComboBox()
        self.series_combo.setEditable(True)
        self.series_combo.addItem("")
        for s in self.db.get_all_series():
            self.series_combo.addItem(s['name'] if isinstance(s, dict) else s)
        if video.get('series_name'):
            self.series_combo.setCurrentText(video['series_name'])
        row.addWidget(self.series_combo, 1)

        self.order_spin = QSpinBox()
        self.order_spin.setMinimum(1)
        self.order_spin.setMaximum(9999)
        self.order_spin.setValue(video.get('series_order', 1) or 1)
        self.order_spin.setFixedWidth(80)
        row.addWidget(self.order_spin)
        il.addLayout(row)

        info_group.setLayout(il)
        layout.addWidget(info_group)

        # Описание
        d_group = QGroupBox("Описание")
        dl = QVBoxLayout()
        self.desc_input = QTextEdit()
        self.desc_input.setPlainText(video.get('description', '') or '')
        self.desc_input.setMaximumHeight(100)
        dl.addWidget(self.desc_input)
        d_group.setLayout(dl)
        layout.addWidget(d_group)

        # Теги
        t_group = QGroupBox("Теги")
        tl = QVBoxLayout()
        self.tags_list = QListWidget()
        self.tags_list.setMaximumHeight(140)
        for t in self.db.get_video_tags(video['id']):
            self.tags_list.addItem(t)
        tl.addWidget(self.tags_list)

        tags_row = QHBoxLayout()
        self.tag_combo = QComboBox()
        self.tag_combo.setEditable(True)
        self.tag_combo.addItems([
            t['name'] if isinstance(t, dict) else t for t in self.db.get_all_tags()
        ])

        btn_add = QPushButton("+ Добавить")
        btn_add.setFixedWidth(120)
        btn_add.clicked.connect(self._add_tag)

        btn_rm = QPushButton("− Удалить")
        btn_rm.setFixedWidth(100)
        btn_rm.clicked.connect(self._remove_tag)

        tags_row.addWidget(self.tag_combo, 1)
        tags_row.addWidget(btn_add)
        tags_row.addWidget(btn_rm)
        tl.addLayout(tags_row)

        t_group.setLayout(tl)
        layout.addWidget(t_group)

        # Статистика
        s_group = QGroupBox("Статистика")
        sl = QHBoxLayout()
        sl.addWidget(QLabel(f"Просмотров: {video.get('watch_count', 0) or 0}"))
        sl.addStretch()
        s_group.setLayout(sl)
        layout.addWidget(s_group)

        # Кнопки
        buttons = QHBoxLayout()
        buttons.addStretch()

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
        self.btn_save.clicked.connect(self._save)

        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_save)
        layout.addLayout(buttons)

        self.setLayout(layout)

    @staticmethod
    def _lbl(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "QLabel { color: #e0e0e0; font-size: 13px;"
            " font-weight: bold; background: transparent; }"
        )
        return lbl

    def _add_tag(self):
        name = self.tag_combo.currentText().strip()
        if not name:
            return
        for i in range(self.tags_list.count()):
            if self.tags_list.item(i).text() == name:
                QMessageBox.warning(self, "Ошибка", "Этот тег уже добавлен")
                return
        self.tags_list.addItem(name)

    def _remove_tag(self):
        item = self.tags_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Ошибка", "Выберите тег для удаления")
            return
        self.tags_list.takeItem(self.tags_list.row(item))

    def _save(self):
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

            self.db.update_video(
                self.video['id'],
                title=title,
                author_id=author_id,
                series_id=series_id,
                series_order=self.order_spin.value(),
                description=self.desc_input.toPlainText().strip(),
            )

            tag_names = [
                self.tags_list.item(i).text()
                for i in range(self.tags_list.count())
                if self.tags_list.item(i).text() != self.db.NO_TAGS_NAME
            ]
            self.db.set_video_tags(self.video['id'], tag_names)

            QMessageBox.information(self, "Успех", "Изменения сохранены")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить: {e}")