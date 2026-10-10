import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QTableWidget, QTableWidgetItem, QPushButton,
                             QLineEdit, QMessageBox, QHeaderView,
                             QAbstractItemView, QStyledItemDelegate)


class BigEditDelegate(QStyledItemDelegate):
    """Делает inline-редактор ячейки крупным и читаемым."""

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setMinimumHeight(48)
        editor.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 2px solid #c0392b;
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 16px;
                selection-background-color: #c0392b;
                selection-color: #ffffff;
            }
        """)
        return editor


class ArchivePasswordsDialog(QDialog):
    """Управление паролями архивов с играми."""

    ROW_HEIGHT = 72

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self.config_path = os.path.join(
            os.path.dirname(os.path.abspath(db_path)),
            'game_archive_passwords.json'
        )
        from archive_extractor import load_passwords, save_passwords
        self._load_passwords = load_passwords
        self._save_passwords = save_passwords
        self.passwords = self._load_passwords(self.config_path)

        self.setWindowTitle("Пароли архивов с играми")
        self.setFixedSize(800, 720)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; background: transparent; }
            QTableWidget {
                background-color: #2a2a2a; color: #ffffff;
                border: 1px solid #3a3a3a; border-radius: 5px;
                gridline-color: #3a3a3a;
                font-size: 16px;
            }
            QTableWidget::item {
                padding: 12px;
                color: #ffffff;
            }
            QTableWidget::item:selected {
                background-color: #c0392b; color: #ffffff;
            }
            QHeaderView::section {
                background-color: #252525; color: #ffffff;
                border: none; padding: 14px 12px;
                font-weight: bold; font-size: 15px;
            }
            QLineEdit {
                background-color: #2a2a2a; color: #ffffff;
                border: 1px solid #3a3a3a; border-radius: 5px;
                padding: 12px; font-size: 15px;
            }
            QLineEdit:focus { border: 1px solid #c0392b; }
            QPushButton {
                background-color: #2a2a2a; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 12px 20px; font-size: 15px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        hint = QLabel(
            "Если архив зашифрован, добавьте его имя и пароль.\n"
            "Имя указывается без пути, регистр не важен.\n"
            "Префикс работает как правило: «MyGame_» подойдёт ко всем архивам,\n"
            "имя которых начинается с этих символов.\n"
            "Ключ «*» задаёт пароль по умолчанию для всех остальных."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("QLabel { color: #888; font-size: 13px; }")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Имя архива / префикс", "Пароль"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(self.ROW_HEIGHT)
        self.table.verticalHeader().setMinimumSectionSize(self.ROW_HEIGHT)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )

        # Крупный редактор ячейки
        self._delegate = BigEditDelegate(self.table)
        self.table.setItemDelegate(self._delegate)

        layout.addWidget(self.table, 1)

        for key, value in self.passwords.items():
            self._append_row(key, value)

        buttons = QHBoxLayout()

        self.btn_add = QPushButton("+ Добавить")
        self.btn_add.setMinimumHeight(46)
        self.btn_add.clicked.connect(self._add_empty_row)
        buttons.addWidget(self.btn_add)

        self.btn_remove = QPushButton("− Удалить строку")
        self.btn_remove.setMinimumHeight(46)
        self.btn_remove.clicked.connect(self._remove_current_row)
        buttons.addWidget(self.btn_remove)

        buttons.addStretch()

        self.btn_save = QPushButton("💾 Сохранить")
        self.btn_save.setMinimumHeight(46)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 12px 28px; font-weight: bold; font-size: 15px;
            }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_save.clicked.connect(self._save)
        buttons.addWidget(self.btn_save)

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setMinimumHeight(46)
        self.btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(self.btn_cancel)

        layout.addLayout(buttons)

        fallback_row = QHBoxLayout()
        fallback_row.addWidget(QLabel("Пароль по умолчанию («*»):"))
        self.fallback_input = QLineEdit()
        self.fallback_input.setText(self.passwords.get('*', ''))
        self.fallback_input.setPlaceholderText("оставьте пустым, если не нужен")
        self.fallback_input.setMinimumHeight(46)
        fallback_row.addWidget(self.fallback_input, 1)
        layout.addLayout(fallback_row)

        self.setLayout(layout)

    def _append_row(self, key: str, value: str):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, self.ROW_HEIGHT)

        item_key = QTableWidgetItem(str(key))
        item_key.setFlags(item_key.flags() | Qt.ItemIsEditable)
        item_val = QTableWidgetItem(str(value))
        item_val.setFlags(item_val.flags() | Qt.ItemIsEditable)

        self.table.setItem(row, 0, item_key)
        self.table.setItem(row, 1, item_val)

    def _add_empty_row(self):
        self._append_row("", "")
        row = self.table.rowCount() - 1
        self.table.setCurrentCell(row, 0)
        self.table.editItem(self.table.item(row, 0))

    def _remove_current_row(self):
        row = self.table.currentRow()
        if row < 0:
            if self.table.rowCount() > 0:
                self.table.removeRow(self.table.rowCount() - 1)
            return
        self.table.removeRow(row)

    def _save(self):
        self.table.setCurrentCell(-1, -1)

        result = {}
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 0)
            val_item = self.table.item(row, 1)
            key = key_item.text().strip() if key_item else ''
            val = val_item.text() if val_item else ''
            if not key:
                continue
            result[key] = val

        fallback = self.fallback_input.text()
        if fallback:
            result['*'] = fallback

        self._save_passwords(self.config_path, result)
        self.passwords = result
        QMessageBox.information(self, "Сохранено",
                                f"Пароли сохранены в:\n{self.config_path}")
        self.accept()