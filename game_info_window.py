import os
import tempfile

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QKeySequence
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QTextEdit, QSpinBox, QPushButton,
                             QComboBox, QListWidget, QGroupBox,
                             QMessageBox, QFileDialog, QShortcut,
                             QApplication)

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


class GameInfoDialog(QDialog):
    def __init__(self, game: dict, db: Database, parent=None):
        super().__init__(parent)
        self.game = game
        self.db = db
        self._new_cover_source = None
        self._temp_cover_file = None

        self.setWindowTitle(f"Редактирование: {game['title']}")
        self.setFixedSize(640, 860)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ===== Обложка + название =====
        top = QHBoxLayout()

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(180, 240)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet("""
            QLabel {
                background-color: #0d0d0d; color: #555;
                border: 2px solid #3a3a3a; border-radius: 6px;
                font-size: 56px;
            }
        """)
        self._load_current_cover()
        top.addWidget(self.cover_label)

        right = QVBoxLayout()

        right.addWidget(self._lbl("Название:"))
        self.title_input = QLineEdit(game['title'])
        right.addWidget(self.title_input)

        right.addWidget(self._lbl("Путь к .exe:"))
        self.exe_input = QLineEdit(game.get('exe_path', ''))
        self.exe_input.setReadOnly(True)
        right.addWidget(self.exe_input)

        right.addWidget(self._lbl("Рабочая директория:"))
        row1 = QHBoxLayout()
        self.wd_input = QLineEdit(game.get('working_dir') or '')
        row1.addWidget(self.wd_input, 1)
        btn_wd = QPushButton("...")
        btn_wd.setFixedWidth(35)
        btn_wd.clicked.connect(self._pick_working_dir)
        row1.addWidget(btn_wd)
        right.addLayout(row1)

        right.addWidget(self._lbl("Аргументы запуска:"))
        self.args_input = QLineEdit(game.get('arguments') or '')
        self.args_input.setPlaceholderText("-windowed -skiplauncher")
        right.addWidget(self.args_input)

        right.addWidget(self._lbl("Серия:"))
        series_row = QHBoxLayout()
        self.series_combo = QComboBox()
        self.series_combo.setEditable(True)
        self.series_combo.setPlaceholderText("Выберите или создайте серию")
        self.series_combo.addItem("")
        try:
            for s in self.db.get_all_series():
                name = s['name'] if isinstance(s, dict) else s
                self.series_combo.addItem(name)
        except Exception as e:
            print(f"[game_info] get_all_series: {e}")
        if game.get('series_name'):
            self.series_combo.setCurrentText(game['series_name'])
        series_row.addWidget(self.series_combo, 1)

        self.order_spin = QSpinBox()
        self.order_spin.setMinimum(1)
        self.order_spin.setMaximum(9999)
        self.order_spin.setValue(game.get('series_order', 1) or 1)
        self.order_spin.setFixedWidth(80)
        self.order_spin.setToolTip("Порядковый номер в серии")
        series_row.addWidget(self.order_spin)
        right.addLayout(series_row)

        right.addWidget(self._lbl("Обложка:"))
        cover_btns = QHBoxLayout()
        btn_cover = QPushButton("📁 Загрузить")
        btn_cover.clicked.connect(self._pick_cover)
        cover_btns.addWidget(btn_cover)

        self.btn_paste = QPushButton("📋 Вставить (Ctrl+V)")
        self.btn_paste.clicked.connect(self._paste_from_clipboard)
        cover_btns.addWidget(self.btn_paste)

        btn_cover_reset = QPushButton("🗑️ Убрать")
        btn_cover_reset.clicked.connect(self._reset_cover)
        cover_btns.addWidget(btn_cover_reset)

        right.addLayout(cover_btns)
        right.addStretch()

        top.addLayout(right, 1)
        layout.addLayout(top)

        # ===== Описание =====
        d_group = QGroupBox("Описание")
        dl = QVBoxLayout()
        self.desc_input = QTextEdit()
        self.desc_input.setPlainText(game.get('description', '') or '')
        self.desc_input.setMaximumHeight(90)
        dl.addWidget(self.desc_input)
        d_group.setLayout(dl)
        layout.addWidget(d_group)

        # ===== Теги =====
        t_group = QGroupBox("Теги")
        tl = QVBoxLayout()
        self.tags_list = QListWidget()
        self.tags_list.setMaximumHeight(120)
        try:
            for t in self.db.get_game_tags(game['id']):
                self.tags_list.addItem(t)
        except Exception as e:
            print(f"[game_info] get_game_tags: {e}")
        tl.addWidget(self.tags_list)

        tags_row = QHBoxLayout()
        self.tag_combo = QComboBox()
        self.tag_combo.setEditable(True)
        try:
            self.tag_combo.addItems([
                t['name'] if isinstance(t, dict) else t
                for t in self.db.get_all_tags()
            ])
        except Exception:
            pass

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

        # ===== Статистика =====
        s_group = QGroupBox("Статистика")
        sl = QHBoxLayout()
        launches = game.get('launch_count', 0) or 0
        from game_library_window import format_playtime
        playtime = format_playtime(game.get('total_playtime', 0) or 0)
        sl.addWidget(QLabel(f"Запусков: {launches}"))
        sl.addSpacing(20)
        sl.addWidget(QLabel(f"Всего сыграно: {playtime}"))
        sl.addStretch()
        s_group.setLayout(sl)
        layout.addWidget(s_group)

        # ===== Кнопки =====
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

        QShortcut(QKeySequence("Ctrl+V"), self, self._paste_from_clipboard)
        QShortcut(QKeySequence("Ctrl+Shift+V"), self, self._paste_from_clipboard)

    @staticmethod
    def _lbl(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "QLabel { color: #e0e0e0; font-size: 13px;"
            " font-weight: bold; background: transparent; }"
        )
        return lbl

    # ---------- обложка ----------

    def _load_current_cover(self):
        cover_path = self.game.get('cover_path')
        if cover_path and os.path.exists(cover_path):
            pix = QPixmap(cover_path)
            if not pix.isNull():
                scaled = pix.scaled(180, 240, Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation)
                self.cover_label.setPixmap(scaled)
                return
        exe = self.game.get('exe_path')
        if exe:
            from game_launcher import find_cover_in_folder
            auto = find_cover_in_folder(os.path.dirname(exe))
            if auto:
                pix = QPixmap(auto)
                if not pix.isNull():
                    scaled = pix.scaled(180, 240, Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation)
                    self.cover_label.setPixmap(scaled)
                    return
        self.cover_label.setText("🎮")

    def _pick_cover(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "Выберите обложку", "",
            "Изображения (*.png *.jpg *.jpeg *.bmp *.webp);;Все файлы (*.*)"
        )
        if not fp:
            return
        pix = QPixmap(fp)
        if pix.isNull():
            QMessageBox.warning(self, "Ошибка", "Не удалось загрузить изображение")
            return
        self._new_cover_source = fp
        self._temp_cover_file = None
        scaled = pix.scaled(180, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.cover_label.setPixmap(scaled)

    def _paste_from_clipboard(self):
        try:
            clipboard = QApplication.clipboard()
            pix = clipboard.pixmap()
            if pix is not None and not pix.isNull():
                self._apply_clipboard_pixmap(pix)
                return
            img = clipboard.image()
            if img is not None and not img.isNull():
                self._apply_clipboard_pixmap(QPixmap.fromImage(img))
                return
            mime = clipboard.mimeData()
            if mime is not None and mime.hasUrls():
                for url in mime.urls():
                    if url.isLocalFile():
                        fp = url.toLocalFile()
                        if os.path.isfile(fp):
                            p = QPixmap(fp)
                            if not p.isNull():
                                self._new_cover_source = fp
                                self._temp_cover_file = None
                                scaled = p.scaled(
                                    180, 240,
                                    Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation
                                )
                                self.cover_label.setPixmap(scaled)
                                return
            QMessageBox.information(
                self, "Буфер пуст",
                "В буфере нет изображения.\n"
                "Скопируйте картинку и попробуйте снова."
            )
        except Exception as e:
            QMessageBox.warning(self, "Ошибка",
                                f"Не удалось вставить из буфера: {e}")

    def _apply_clipboard_pixmap(self, pix: QPixmap):
        tmp_dir = tempfile.gettempdir()
        tmp_path = os.path.join(tmp_dir, f"libvidgam_paste_{id(self)}.png")
        try:
            if not pix.save(tmp_path, 'PNG'):
                raise RuntimeError("QPixmap.save вернул False")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка",
                                f"Не удалось сохранить изображение: {e}")
            return

        self._new_cover_source = tmp_path
        self._temp_cover_file = tmp_path
        scaled = pix.scaled(180, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.cover_label.setPixmap(scaled)

    def _reset_cover(self):
        self._new_cover_source = None
        if self._temp_cover_file and os.path.exists(self._temp_cover_file):
            try:
                os.remove(self._temp_cover_file)
            except Exception:
                pass
        self._temp_cover_file = None
        self.game['cover_path'] = None
        self.cover_label.setPixmap(QPixmap())
        self.cover_label.setText("🎮")

    def _pick_working_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Рабочая директория", self.wd_input.text() or ""
        )
        if folder:
            self.wd_input.setText(folder)

    # ---------- теги ----------

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

    # ---------- сохранение ----------

    def _cleanup_old_cover_files(self, covers_dir, keep_path):
        if not os.path.isdir(covers_dir):
            return
        keep_norm = None
        if keep_path:
            keep_norm = os.path.normcase(os.path.normpath(keep_path))
        prefix = f"game_{self.game['id']}."
        try:
            for name in os.listdir(covers_dir):
                if not name.lower().startswith(prefix.lower()):
                    continue
                full = os.path.join(covers_dir, name)
                if keep_norm and os.path.normcase(os.path.normpath(full)) == keep_norm:
                    continue
                try:
                    os.remove(full)
                except OSError:
                    pass
        except OSError:
            pass

    def _save(self):
        try:
            title = self.title_input.text().strip()
            if not title:
                QMessageBox.warning(self, "Ошибка", "Название не может быть пустым")
                return

            # Серия
            series_name = self.series_combo.currentText().strip()
            series_id = None
            if series_name:
                try:
                    series_id = self.db.add_series(series_name)
                except Exception as e:
                    QMessageBox.warning(
                        self, "Ошибка серии",
                        f"Не удалось сохранить серию: {e}"
                    )
                    return

            cover_path = self.game.get('cover_path')
            covers_dir = os.path.join(
                os.path.dirname(self.db.db_path), 'game_covers'
            )

            if self._new_cover_source:
                os.makedirs(covers_dir, exist_ok=True)
                new_path = os.path.join(
                    covers_dir, f"game_{self.game['id']}.png"
                )
                try:
                    from PIL import Image
                    img = Image.open(self._new_cover_source)
                    if img.mode not in ('RGB', 'RGBA'):
                        img = img.convert('RGB')
                    img.save(new_path, 'PNG')
                    cover_path = new_path
                except Exception as e:
                    QMessageBox.warning(
                        self, "Ошибка обложки",
                        f"Не удалось сохранить обложку: {e}"
                    )
                    return
                self._cleanup_old_cover_files(covers_dir, keep_path=new_path)
            elif cover_path is None:
                self._cleanup_old_cover_files(covers_dir, keep_path=None)

            self.db.update_game(
                self.game['id'],
                title=title,
                working_dir=self.wd_input.text().strip() or None,
                arguments=self.args_input.text().strip() or None,
                cover_path=cover_path,
                description=self.desc_input.toPlainText().strip(),
                series_id=series_id,
                series_order=(self.order_spin.value() if series_id else None),
            )

            tag_names = [
                self.tags_list.item(i).text()
                for i in range(self.tags_list.count())
                if self.tags_list.item(i).text() != self.db.NO_TAGS_NAME
            ]
            self.db.set_game_tags(self.game['id'], tag_names)

            if self._temp_cover_file and os.path.exists(self._temp_cover_file):
                try:
                    os.remove(self._temp_cover_file)
                except Exception:
                    pass

            QMessageBox.information(self, "Успех", "Изменения сохранены")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить: {e}")

    def closeEvent(self, event):
        if self._temp_cover_file and os.path.exists(self._temp_cover_file):
            try:
                os.remove(self._temp_cover_file)
            except Exception:
                pass
        super().closeEvent(event)