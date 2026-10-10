import os
import tempfile

from PIL import Image

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QKeySequence
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QMessageBox, QFileDialog,
                             QShortcut, QApplication)

from database import Database


# Размеры обложки в диалоге
COVER_W = 280
COVER_H = 360


class TagEditDialog(QDialog):
    """Диалог редактирования тега: обложка + название."""

    def __init__(self, tag: dict, db: Database, parent=None):
        super().__init__(parent)
        self.tag = tag
        self.db = db
        self._temp_cover_file = None

        self.setWindowTitle(f"Редактирование тега: {tag['name']}")
        self.setFixedSize(560, 620)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; background: transparent; }
            QPushButton {
                background-color: #2a2a2a; color: #e0e0e0;
                border: none; border-radius: 5px; padding: 10px 14px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Заголовок
        title = QLabel(f"🏷️ {tag['name']}")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            QLabel {
                color: #ffffff; font-size: 20px; font-weight: bold;
                padding-bottom: 4px;
            }
        """)
        layout.addWidget(title)

        # Обложка
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

        # Кнопки управления обложкой
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

        # Подсказка
        hint = QLabel(
            "Обложка применяется сразу. Скопируйте картинку в буфер "
            "(из браузера, проводника) и нажмите Ctrl+V."
        )
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            "QLabel { color: #666; font-size: 11px; padding: 4px; }"
        )
        layout.addWidget(hint)

        layout.addStretch()

        # Кнопка закрытия
        bottom = QHBoxLayout()
        bottom.addStretch()

        self.btn_close = QPushButton("Закрыть")
        self.btn_close.setFixedWidth(160)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: white;
                border: none; border-radius: 5px; padding: 10px;
                font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_close.clicked.connect(self.accept)
        bottom.addWidget(self.btn_close)

        layout.addLayout(bottom)
        self.setLayout(layout)

        # Хоткеи для вставки из буфера
        QShortcut(QKeySequence("Ctrl+V"), self, self._paste_from_clipboard)
        QShortcut(QKeySequence("Ctrl+Shift+V"), self, self._paste_from_clipboard)

        self.load_current_cover()

    # ---------- отображение ----------

    def load_current_cover(self):
        cover_path = self.tag.get('cover_path')
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
        self.cover_label.setText("🏷️")

    # ---------- сохранение ----------

    def _covers_dir(self):
        d = os.path.join(os.path.dirname(self.db.db_path), 'tag_covers')
        os.makedirs(d, exist_ok=True)
        return d

    def _target_cover_path(self):
        """Единый путь для обложки тега — всегда PNG."""
        return os.path.join(self._covers_dir(), f"tag_{self.tag['id']}.png")

    def _cleanup_old_covers(self, keep_path=None):
        """Удаляет старые файлы обложек этого тега (с любым расширением),
        кроме keep_path."""
        covers_dir = self._covers_dir()
        keep_norm = None
        if keep_path:
            keep_norm = os.path.normcase(os.path.normpath(keep_path))
        prefix = f"tag_{self.tag['id']}."
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
        """Сохраняет PIL.Image в tag_covers/tag_{id}.png и обновляет БД."""
        target = self._target_cover_path()
        # Приводим к RGB/RGBA
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        # Ограничиваем размер, чтобы не хранить гигабайты
        max_side = 800
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)

        try:
            img.save(target, 'PNG')
        except Exception as e:
            raise RuntimeError(f"Не удалось сохранить обложку: {e}")

        # Убираем старые файлы с другими расширениями
        self._cleanup_old_covers(keep_path=target)

        self.db.update_tag_cover(self.tag['id'], target)
        self.tag['cover_path'] = target
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
        """Вставка картинки из буфера обмена (Ctrl+V)."""
        try:
            clipboard = QApplication.clipboard()

            # 1) Pixmap
            pix = clipboard.pixmap()
            if pix is not None and not pix.isNull():
                self._apply_pixmap(pix)
                return

            # 2) QImage
            img_qt = clipboard.image()
            if img_qt is not None and not img_qt.isNull():
                self._apply_pixmap(QPixmap.fromImage(img_qt))
                return

            # 3) Путь к файлу в буфере (файл-картинка из проводника)
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
                        print(f"[tag_edit] paste from file: {e}")
                        continue

            QMessageBox.information(
                self, "Буфер пуст",
                "В буфере нет изображения.\n"
                "Скопируйте картинку (например, из браузера или проводника) "
                "и попробуйте снова."
            )
        except Exception as e:
            QMessageBox.warning(self, "Ошибка",
                                f"Не удалось вставить из буфера: {e}")

    def _apply_pixmap(self, pix: QPixmap):
        """Сохраняет QPixmap во временный PNG, открывает через PIL,
        сохраняет в tag_covers."""
        if pix is None or pix.isNull():
            return

        tmp_dir = tempfile.gettempdir()
        tmp_path = os.path.join(tmp_dir, f"libvidgam_tag_{id(self)}.png")
        try:
            if not pix.save(tmp_path, 'PNG'):
                raise RuntimeError("QPixmap.save вернул False")
        except Exception as e:
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось сохранить вставленное изображение: {e}"
            )
            return

        try:
            with Image.open(tmp_path) as img:
                img.load()
                self._save_cover_from_image(img)
            QMessageBox.information(self, "Успех", "Обложка сохранена")
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка",
                f"Не удалось применить обложку: {e}"
            )
        finally:
            # Чистим временный файл
            try:
                if os.path.isfile(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    # ---------- удаление ----------

    def remove_cover(self):
        reply = QMessageBox.question(self, "Подтверждение",
                                     "Удалить обложку тега?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            # Удаляем все файлы тега (PNG и старые с другими расширениями)
            self._cleanup_old_covers(keep_path=None)
            self.db.clear_tag_cover(self.tag['id'])
            self.tag['cover_path'] = None
            self.load_current_cover()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось удалить обложку: {e}")

    # ---------- очистка временных файлов ----------

    def closeEvent(self, event):
        if self._temp_cover_file and os.path.exists(self._temp_cover_file):
            try:
                os.remove(self._temp_cover_file)
            except OSError:
                pass
        super().closeEvent(event)