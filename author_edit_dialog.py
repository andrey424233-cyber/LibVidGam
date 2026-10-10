"""Диалог редактирования автора: имя + обложка."""
import os
import tempfile

from PIL import Image

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QKeySequence
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QMessageBox, QFileDialog,
                             QShortcut, QApplication, QLineEdit)

from database import Database


COVER_W = 280
COVER_H = 360


class AuthorEditDialog(QDialog):
    """Диалог редактирования автора."""

    def __init__(self, author: dict, db: Database, parent=None):
        super().__init__(parent)
        self.author = author
        self.db = db

        self.setWindowTitle(f"Редактирование автора: {author['name']}")
        self.setFixedSize(560, 700)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; background: transparent; }
            QLineEdit {
                background-color: #2a2a2a; color: #ffffff;
                border: 1px solid #3a3a3a; border-radius: 5px;
                padding: 10px 14px; font-size: 14px;
            }
            QLineEdit:focus { border: 1px solid #c0392b; }
            QPushButton {
                background-color: #2a2a2a; color: #e0e0e0;
                border: none; border-radius: 5px; padding: 10px 14px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(self._lbl("Имя автора:"))
        self.name_input = QLineEdit(author['name'])
        layout.addWidget(self.name_input)

        layout.addWidget(self._lbl("Обложка:"))

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(COVER_W, COVER_H)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet("""
            QLabel {
                background-color: #1a1a1a;
                border-radius: 10px;
                border: 2px solid #3a3a3a;
                font-size: 96px;
                color: #444;
            }
        """)
        layout.addWidget(self.cover_label, alignment=Qt.AlignCenter)

        cover_buttons = QHBoxLayout()
        cover_buttons.setSpacing(8)

        self.btn_load_cover = QPushButton("📁 Загрузить")
        self.btn_load_cover.clicked.connect(self.load_cover)
        cover_buttons.addWidget(self.btn_load_cover)

        self.btn_paste = QPushButton("📋 Вставить (Ctrl+V)")
        self.btn_paste.setToolTip("Вставить изображение из буфера обмена (Ctrl+V)")
        self.btn_paste.clicked.connect(self._paste_from_clipboard)
        cover_buttons.addWidget(self.btn_paste)

        self.btn_remove_cover = QPushButton("🗑️ Удалить")
        self.btn_remove_cover.setStyleSheet("""
            QPushButton {
                background-color: #8b2a2a; color: #e0e0e0;
                border: none; border-radius: 5px; padding: 10px 14px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #a33; }
        """)
        self.btn_remove_cover.clicked.connect(self.remove_cover)
        cover_buttons.addWidget(self.btn_remove_cover)

        layout.addLayout(cover_buttons)

        hint = QLabel(
            "Обложка применяется сразу. Скопируйте картинку в буфер "
            "и нажмите Ctrl+V. Имя сохраняется по кнопке ниже."
        )
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            "QLabel { color: #666; font-size: 11px; padding: 4px; }"
        )
        layout.addWidget(hint)

        layout.addStretch()

        bottom = QHBoxLayout()
        bottom.addStretch()

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setFixedWidth(120)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton("💾 Сохранить")
        self.btn_save.setFixedWidth(160)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: white;
                border: none; border-radius: 5px; padding: 10px;
                font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_save.clicked.connect(self._save)
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_save)

        layout.addLayout(bottom)
        self.setLayout(layout)

        QShortcut(QKeySequence("Ctrl+V"), self, self._paste_from_clipboard)
        QShortcut(QKeySequence("Ctrl+Shift+V"), self, self._paste_from_clipboard)

        self.load_current_cover()

    @staticmethod
    def _lbl(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "QLabel { color: #e0e0e0; font-size: 13px;"
            " font-weight: bold; background: transparent; }"
        )
        return lbl

    # ---------- отображение ----------

    def load_current_cover(self):
        cover_path = self.author.get('cover_path')
        if cover_path and os.path.exists(cover_path):
            try:
                pixmap = QPixmap(cover_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(
                        COVER_W - 8, COVER_H - 8,
                        Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                    self.cover_label.setPixmap(scaled)
                    self.cover_label.setText("")
                    return
            except Exception as e:
                print(f"Ошибка загрузки обложки: {e}")
        self.cover_label.setPixmap(QPixmap())
        self.cover_label.setText("👤")

    # ---------- пути обложек ----------

    def _covers_dir(self):
        d = os.path.join(os.path.dirname(self.db.db_path), 'author_covers')
        os.makedirs(d, exist_ok=True)
        return d

    def _target_cover_path(self):
        return os.path.join(self._covers_dir(),
                            f"author_{self.author['id']}.png")

    def _cleanup_old_covers(self, keep_path=None):
        covers_dir = self._covers_dir()
        keep_norm = None
        if keep_path:
            keep_norm = os.path.normcase(os.path.normpath(keep_path))
        prefix = f"author_{self.author['id']}."
        try:
            for name in os.listdir(covers_dir):
                if not name.lower().startswith(prefix.lower()):
                    continue
                full = os.path.join(covers_dir, name)
                if keep_norm and os.path.normcase(
                        os.path.normpath(full)
                ) == keep_norm:
                    continue
                try:
                    os.remove(full)
                except OSError:
                    pass
        except OSError:
            pass

    def _save_cover_from_image(self, img: Image.Image):
        target = self._target_cover_path()
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')
        max_side = 800
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        try:
            img.save(target, 'PNG')
        except Exception as e:
            raise RuntimeError(f"Не удалось сохранить обложку: {e}")

        self._cleanup_old_covers(keep_path=target)
        self.db.update_author_cover(self.author['id'], target)
        self.author['cover_path'] = target
        self.load_current_cover()

    # ---------- загрузка файла ----------

    def load_cover(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите изображение", "",
            "Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;Все файлы (*.*)"
        )
        if not file_path:
            return
        try:
            img = Image.open(file_path)
            img.load()
            self._save_cover_from_image(img)
            QMessageBox.information(self, "Успех", "Обложка сохранена")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось сохранить обложку: {e}")

    # ---------- вставка из буфера ----------

    def _paste_from_clipboard(self):
        try:
            clipboard = QApplication.clipboard()

            pix = clipboard.pixmap()
            if pix is not None and not pix.isNull():
                self._apply_pixmap(pix)
                return

            img_qt = clipboard.image()
            if img_qt is not None and not img_qt.isNull():
                self._apply_pixmap(QPixmap.fromImage(img_qt))
                return

            mime = clipboard.mimeData()
            if mime is not None and mime.hasUrls():
                for url in mime.urls():
                    if not url.isLocalFile():
                        continue
                    fp = url.toLocalFile()
                    if not os.path.isfile(fp):
                        continue
                    try:
                        img = Image.open(fp)
                        img.load()
                        self._save_cover_from_image(img)
                        QMessageBox.information(self, "Успех",
                                                "Обложка сохранена")
                        return
                    except Exception as e:
                        print(f"[author_edit] paste from file: {e}")
                        continue

            QMessageBox.information(
                self, "Буфер пуст",
                "В буфере нет изображения.\n"
                "Скопируйте картинку и попробуйте снова."
            )
        except Exception as e:
            QMessageBox.warning(self, "Ошибка",
                                f"Не удалось вставить из буфера: {e}")

    def _apply_pixmap(self, pix: QPixmap):
        if pix is None or pix.isNull():
            return
        tmp_dir = tempfile.gettempdir()
        tmp_path = os.path.join(tmp_dir, f"libvidgam_author_{id(self)}.png")
        try:
            if not pix.save(tmp_path, 'PNG'):
                raise RuntimeError("QPixmap.save вернул False")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка",
                                f"Не удалось сохранить изображение: {e}")
            return
        try:
            with Image.open(tmp_path) as img:
                img.load()
                self._save_cover_from_image(img)
            QMessageBox.information(self, "Успех", "Обложка сохранена")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось применить обложку: {e}")
        finally:
            try:
                if os.path.isfile(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    # ---------- удаление обложки ----------

    def remove_cover(self):
        reply = QMessageBox.question(self, "Подтверждение",
                                     "Удалить обложку автора?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            self._cleanup_old_covers(keep_path=None)
            self.db.clear_author_cover(self.author['id'])
            self.author['cover_path'] = None
            self.load_current_cover()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось удалить обложку: {e}")

    # ---------- сохранение диалога (только имя) ----------

    def _save(self):
        new_name = self.name_input.text().strip()
        if not new_name:
            QMessageBox.warning(self, "Ошибка", "Имя не может быть пустым")
            return

        if new_name == self.author['name']:
            self.accept()
            return

        try:
            ok = self.db.rename_author(self.author['id'], new_name)
            if not ok:
                QMessageBox.warning(
                    self, "Ошибка",
                    f"Автор с именем «{new_name}» уже существует."
                )
                return
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось переименовать: {e}")
            return

        self.accept()