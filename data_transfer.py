"""Импорт и экспорт ТОЛЬКО тегов.

Экспорт:
  * Создаёт в выбранной папке файл `tags_export.json` со списком тегов.
  * Если выбрана опция обложек — копирует обложки в подпапку
    `tags_export_covers/`.

Импорт:
  * Читает `tags_export.json` из выбранной папки.
  * Добавляет отсутствующие теги в БД (мгновенно, без перезапуска).
  * Если у тега есть обложка в `tags_export_covers/` и включена опция —
    копирует её в `tag_covers/` приложения и обновляет `cover_path`.
  * Существующие обложки не перезаписываются.
"""
import hashlib
import json
import os
import shutil
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QFileDialog, QCheckBox,
                             QMessageBox, QGroupBox)


TAGS_EXPORT_FILE = 'tags_export.json'
TAGS_COVERS_DIR = 'tags_export_covers'
TAG_COVERS_LOCAL = 'tag_covers'


def human_size(num):
    try:
        n = float(num)
    except Exception:
        return "—"
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} ТБ"


def _cover_filename(tag_name: str, ext: str) -> str:
    """Стабильное имя для обложки: md5(name)[:16] + ext."""
    h = hashlib.md5(tag_name.encode('utf-8')).hexdigest()[:16]
    if not ext:
        ext = '.png'
    if not ext.startswith('.'):
        ext = '.' + ext
    return f"tag_{h}{ext}"


def _local_tag_covers_dir(app_dir: str) -> str:
    return os.path.join(app_dir, TAG_COVERS_LOCAL)


# ============================================================
# Анализ источников
# ============================================================

def analyze_import_source(folder: str) -> dict:
    """Читает tags_export.json из папки. Возвращает:
      {
        'json_path': str,
        'tags': [{'name': str, 'cover': str|None}, ...],
        'covers_count': int,   # файлов в tags_export_covers/
        'size': int,           # размер json
      }
    Если файл не найден или битый — {'error': 'текст'}.
    """
    json_path = os.path.join(folder, TAGS_EXPORT_FILE)
    if not os.path.isfile(json_path):
        return {'error': f"Файл {TAGS_EXPORT_FILE} не найден в папке"}

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return {'error': f"Не удалось прочитать JSON: {e}"}

    if not isinstance(data, dict):
        return {'error': "Формат файла неверный"}

    tags_raw = data.get('tags', [])
    if not isinstance(tags_raw, list):
        return {'error': "Список тегов не найден в файле"}

    tags = []
    seen_names = set()
    for item in tags_raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name', '')).strip()
        if not name:
            continue
        # Пропускаем дубликаты внутри одного файла
        if name in seen_names:
            continue
        seen_names.add(name)

        cover = item.get('cover')
        if cover:
            cover = str(cover)
        else:
            cover = None
        tags.append({'name': name, 'cover': cover})

    covers_dir = os.path.join(folder, TAGS_COVERS_DIR)
    covers_count = 0
    if os.path.isdir(covers_dir):
        try:
            for name in os.listdir(covers_dir):
                if os.path.isfile(os.path.join(covers_dir, name)):
                    covers_count += 1
        except OSError:
            pass

    try:
        size = os.path.getsize(json_path)
    except OSError:
        size = 0

    return {
        'json_path': json_path,
        'tags': tags,
        'covers_count': covers_count,
        'size': size,
    }


def analyze_export_source(app_dir: str, db) -> dict:
    """Возвращает {'tags_count': N, 'with_covers': N, 'covers_size': bytes}."""
    try:
        tags = db.get_all_tags() or []
    except Exception:
        tags = []

    with_covers = 0
    covers_size = 0
    for t in tags:
        if not isinstance(t, dict):
            continue
        cp = t.get('cover_path')
        if cp and os.path.isfile(cp):
            with_covers += 1
            try:
                covers_size += os.path.getsize(cp)
            except OSError:
                pass

    return {
        'tags_count': len(tags),
        'with_covers': with_covers,
        'covers_size': covers_size,
    }


# ============================================================
# Экспорт
# ============================================================

def perform_export(app_dir: str, target_folder: str, db,
                   include_covers: bool = True) -> dict:
    """Экспортирует теги в target_folder.
    Возвращает {'exported': N, 'covers': N, 'errors': [...]}."""
    result = {'exported': 0, 'covers': 0, 'errors': []}

    try:
        os.makedirs(target_folder, exist_ok=True)
    except Exception as e:
        result['errors'].append(f"Не удалось создать папку: {e}")
        return result

    try:
        tags = db.get_all_tags() or []
    except Exception as e:
        result['errors'].append(f"Ошибка чтения тегов из БД: {e}")
        return result

    covers_out_dir = os.path.join(target_folder, TAGS_COVERS_DIR)
    if include_covers:
        try:
            if os.path.isdir(covers_out_dir):
                shutil.rmtree(covers_out_dir, ignore_errors=True)
            os.makedirs(covers_out_dir, exist_ok=True)
        except Exception as e:
            result['errors'].append(f"Не удалось создать папку обложек: {e}")
            include_covers = False

    export_tags = []
    for t in tags:
        if not isinstance(t, dict):
            continue
        name = t.get('name')
        if not name:
            continue
        cover_path = t.get('cover_path')

        cover_filename = None
        if include_covers and cover_path and os.path.isfile(cover_path):
            ext = os.path.splitext(cover_path)[1].lower() or '.png'
            cover_filename = _cover_filename(name, ext)
            try:
                shutil.copy2(
                    cover_path,
                    os.path.join(covers_out_dir, cover_filename)
                )
                result['covers'] += 1
            except Exception as e:
                result['errors'].append(f"Обложка '{name}': {e}")
                cover_filename = None

        export_tags.append({
            'name': name,
            'cover': cover_filename,
        })

    payload = {
        'version': 1,
        'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'tags': export_tags,
    }

    json_path = os.path.join(target_folder, TAGS_EXPORT_FILE)
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        result['errors'].append(f"Не удалось записать JSON: {e}")
        return result

    result['exported'] = len(export_tags)

    # Если обложек нет — не оставляем пустую папку
    if include_covers and result['covers'] == 0:
        try:
            if os.path.isdir(covers_out_dir):
                os.rmdir(covers_out_dir)
        except OSError:
            pass

    return result


# ============================================================
# Импорт
# ============================================================

def perform_import(app_dir: str, source_folder: str, db,
                   include_covers: bool = True) -> dict:
    """Импортирует теги из source_folder в БД.
    Возвращает:
      {
        'added': N,       # новых тегов добавлено
        'existing': N,    # уже были в БД
        'covers': N,      # обложек перенесено
        'errors': [...],
      }
    """
    result = {'added': 0, 'existing': 0, 'covers': 0, 'errors': []}

    info = analyze_import_source(source_folder)
    if 'error' in info:
        result['errors'].append(info['error'])
        return result

    tags = info.get('tags', [])
    if not tags:
        result['errors'].append("Файл не содержит тегов")
        return result

    # Существующие имена тегов в БД
    try:
        existing_names = set()
        existing_covers = {}
        for t in db.get_all_tags() or []:
            if not isinstance(t, dict):
                continue
            nm = t.get('name')
            if nm:
                existing_names.add(nm)
                existing_covers[nm] = t.get('cover_path')
    except Exception as e:
        result['errors'].append(f"Не удалось прочитать теги из БД: {e}")
        return result

    # Локальная папка для обложек
    local_covers_dir = _local_tag_covers_dir(app_dir)
    if include_covers:
        try:
            os.makedirs(local_covers_dir, exist_ok=True)
        except Exception as e:
            result['errors'].append(f"Не удалось создать {TAG_COVERS_LOCAL}: {e}")
            include_covers = False

    src_covers_dir = os.path.join(source_folder, TAGS_COVERS_DIR)

    for item in tags:
        name = item.get('name')
        cover_filename = item.get('cover')

        is_new = name not in existing_names

        # Добавляем тег, если его нет
        try:
            if is_new:
                db.add_tag(name)
                existing_names.add(name)
                result['added'] += 1
            else:
                result['existing'] += 1
        except Exception as e:
            result['errors'].append(f"Тег '{name}': {e}")
            continue

        # Обложка
        if not include_covers or not cover_filename:
            continue
        src_cover = os.path.join(src_covers_dir, cover_filename)
        if not os.path.isfile(src_cover):
            continue

        # Если у тега уже есть обложка — не перезаписываем
        current_cover = existing_covers.get(name)
        if current_cover and os.path.isfile(current_cover):
            continue

        try:
            tag_id = db.get_tag_id(name)
            if tag_id is None:
                continue

            ext = os.path.splitext(cover_filename)[1].lower() or '.png'
            local_name = _cover_filename(name, ext)
            dst_cover = os.path.join(local_covers_dir, local_name)

            shutil.copy2(src_cover, dst_cover)
            db.update_tag_cover(tag_id, dst_cover)
            existing_covers[name] = dst_cover
            result['covers'] += 1
        except Exception as e:
            result['errors'].append(f"Обложка тега '{name}': {e}")

    return result


# ============================================================
# Устаревшая функция (оставлена для совместимости с Main.py)
# ============================================================

def apply_pending_import(app_dir):
    """Раньше применяла отложенный импорт БД через _pending_import/.
    Теперь импорт тегов мгновенный, стагинг не нужен.
    Оставлено для обратной совместимости — всегда возвращает False."""
    return False


# ============================================================
# Диалог экспорта
# ============================================================

class DataExportDialog(QDialog):
    """Экспорт тегов в выбранную папку."""

    def __init__(self, app_dir, db, parent=None):
        super().__init__(parent)
        self.app_dir = app_dir
        self.db = db
        self.target_folder = ''

        self.setWindowTitle("Экспорт тегов")
        self.setFixedSize(580, 420)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; background: transparent; }
            QGroupBox {
                color: #ffffff; border: 1px solid #3a3a3a;
                border-radius: 8px; margin-top: 10px; padding-top: 16px;
                background-color: #252525;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 15px; padding: 0 5px;
                color: #ffffff; font-weight: bold;
            }
            QLineEdit {
                background-color: #2a2a2a; color: #ffffff;
                border: 1px solid #3a3a3a; border-radius: 5px;
                padding: 8px 10px; font-size: 13px;
            }
            QPushButton {
                background-color: #2a2a2a; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 8px 16px; font-size: 13px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
            QCheckBox { color: #e0e0e0; font-size: 13px; padding: 4px 0; }
            QCheckBox::indicator {
                width: 18px; height: 18px;
                border: 2px solid #666; border-radius: 4px;
                background-color: #1a1a1a;
            }
            QCheckBox::indicator:checked {
                background-color: #c0392b; border-color: #c0392b;
            }
            QCheckBox::indicator:disabled {
                background-color: #2a2a2a; border-color: #444;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        hint = QLabel(
            "Экспортирует список всех тегов и (опционально) их обложек "
            "в выбранную папку. Полезно для резервной копии или переноса "
            "тегов на другой компьютер."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("QLabel { color: #888; font-size: 12px; }")
        layout.addWidget(hint)

        folder_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Путь к папке для сохранения...")
        self.path_edit.setReadOnly(True)
        folder_row.addWidget(self.path_edit, 1)

        self.btn_browse = QPushButton("📁 Выбрать папку")
        self.btn_browse.setFixedWidth(160)
        self.btn_browse.clicked.connect(self._choose_folder)
        folder_row.addWidget(self.btn_browse)
        layout.addLayout(folder_row)

        info_group = QGroupBox("Что будет экспортировано")
        info_layout = QVBoxLayout()
        info_layout.setSpacing(8)

        info = analyze_export_source(self.app_dir, self.db)

        self.lbl_tags = QLabel(f"<b>Тегов:</b> {info['tags_count']}")
        self.lbl_tags.setStyleSheet("QLabel { color: #e0e0e0; font-size: 13px; }")
        info_layout.addWidget(self.lbl_tags)

        covers_text = f"<b>Обложек тегов:</b> {info['with_covers']}"
        if info['covers_size'] > 0:
            covers_text += f" ({human_size(info['covers_size'])})"
        self.lbl_covers = QLabel(covers_text)
        self.lbl_covers.setStyleSheet("QLabel { color: #e0e0e0; font-size: 13px; }")
        info_layout.addWidget(self.lbl_covers)

        self.chk_covers = QCheckBox("Экспортировать обложки тегов")
        self.chk_covers.setChecked(info['with_covers'] > 0)
        self.chk_covers.setEnabled(info['with_covers'] > 0)
        info_layout.addWidget(self.chk_covers)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setFixedWidth(120)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_export = QPushButton("📤 Экспортировать")
        self.btn_export.setFixedWidth(200)
        self.btn_export.setEnabled(info['tags_count'] > 0)
        self.btn_export.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 8px 16px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { background-color: #e74c3c; }
            QPushButton:disabled {
                background-color: #3a3a3a; color: #666;
            }
        """)
        self.btn_export.clicked.connect(self._do_export)

        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_export)
        layout.addLayout(buttons)

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку для экспорта", os.path.expanduser("~")
        )
        if not folder:
            return

        try:
            src_norm = os.path.normcase(os.path.normpath(self.app_dir))
            dst_norm = os.path.normcase(os.path.normpath(folder))
            if src_norm == dst_norm:
                QMessageBox.warning(
                    self, "Ошибка",
                    "Нельзя экспортировать в ту же папку, где хранятся "
                    "данные приложения."
                )
                return
        except Exception:
            pass

        self.target_folder = folder
        self.path_edit.setText(folder)

    def _do_export(self):
        if not self.target_folder:
            QMessageBox.information(self, "Не выбрана папка",
                                    "Укажите папку для сохранения.")
            return

        include_covers = self.chk_covers.isChecked()

        reply = QMessageBox.question(
            self, "Подтверждение экспорта",
            f"Экспортировать теги в:\n{self.target_folder}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        result = perform_export(
            self.app_dir, self.target_folder, self.db,
            include_covers=include_covers
        )

        parts = []
        if result['exported'] > 0:
            parts.append(f"✅ Экспортировано тегов: {result['exported']}")
        if result['covers'] > 0:
            parts.append(f"🖼️ Обложек: {result['covers']}")
        if result['errors']:
            parts.append("⚠️ Ошибки:\n" + "\n".join(
                f"• {e}" for e in result['errors'][:8]
            ))

        text = "\n\n".join(parts) if parts else "Нечего было экспортировать."
        QMessageBox.information(self, "Экспорт завершён", text)
        self.accept()


# ============================================================
# Диалог импорта
# ============================================================

class DataImportDialog(QDialog):
    """Импорт тегов из папки с tags_export.json."""

    def __init__(self, app_dir, db, parent=None):
        super().__init__(parent)
        self.app_dir = app_dir
        self.db = db
        self.source_folder = ''
        self._source_info = None

        self.setWindowTitle("Импорт тегов")
        self.setFixedSize(600, 460)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; background: transparent; }
            QGroupBox {
                color: #ffffff; border: 1px solid #3a3a3a;
                border-radius: 8px; margin-top: 10px; padding-top: 16px;
                background-color: #252525;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 15px; padding: 0 5px;
                color: #ffffff; font-weight: bold;
            }
            QLineEdit {
                background-color: #2a2a2a; color: #ffffff;
                border: 1px solid #3a3a3a; border-radius: 5px;
                padding: 8px 10px; font-size: 13px;
            }
            QPushButton {
                background-color: #2a2a2a; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 8px 16px; font-size: 13px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
            QCheckBox { color: #e0e0e0; font-size: 13px; padding: 4px 0; }
            QCheckBox::indicator {
                width: 18px; height: 18px;
                border: 2px solid #666; border-radius: 4px;
                background-color: #1a1a1a;
            }
            QCheckBox::indicator:checked {
                background-color: #c0392b; border-color: #c0392b;
            }
            QCheckBox::indicator:disabled {
                background-color: #2a2a2a; border-color: #444;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        hint = QLabel(
            "Выберите папку, в которой лежит файл tags_export.json "
            "(созданный через «Экспорт тегов»). Существующие теги не будут "
            "дублироваться."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("QLabel { color: #888; font-size: 12px; }")
        layout.addWidget(hint)

        folder_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Путь к папке с тегами...")
        self.path_edit.setReadOnly(True)
        folder_row.addWidget(self.path_edit, 1)

        self.btn_browse = QPushButton("📁 Выбрать папку")
        self.btn_browse.setFixedWidth(160)
        self.btn_browse.clicked.connect(self._choose_folder)
        folder_row.addWidget(self.btn_browse)
        layout.addLayout(folder_row)

        self.items_group = QGroupBox("Найдено в папке")
        info_layout = QVBoxLayout()
        info_layout.setSpacing(8)

        self.empty_label = QLabel("Выберите папку для анализа")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            "QLabel { color: #666; font-size: 13px; padding: 30px 0; }"
        )
        info_layout.addWidget(self.empty_label)

        self.lbl_total = QLabel("")
        self.lbl_total.setStyleSheet("QLabel { color: #e0e0e0; font-size: 13px; }")
        self.lbl_total.setVisible(False)
        info_layout.addWidget(self.lbl_total)

        self.lbl_new = QLabel("")
        self.lbl_new.setStyleSheet("QLabel { color: #27ae60; font-size: 13px; }")
        self.lbl_new.setVisible(False)
        info_layout.addWidget(self.lbl_new)

        self.lbl_existing = QLabel("")
        self.lbl_existing.setStyleSheet("QLabel { color: #888; font-size: 13px; }")
        self.lbl_existing.setVisible(False)
        info_layout.addWidget(self.lbl_existing)

        self.lbl_covers = QLabel("")
        self.lbl_covers.setStyleSheet("QLabel { color: #e0e0e0; font-size: 13px; }")
        self.lbl_covers.setVisible(False)
        info_layout.addWidget(self.lbl_covers)

        self.chk_covers = QCheckBox("Импортировать обложки тегов")
        self.chk_covers.setChecked(True)
        self.chk_covers.setVisible(False)
        info_layout.addWidget(self.chk_covers)

        self.items_group.setLayout(info_layout)
        layout.addWidget(self.items_group, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setFixedWidth(120)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_import = QPushButton("📥 Импортировать")
        self.btn_import.setFixedWidth(200)
        self.btn_import.setEnabled(False)
        self.btn_import.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 8px 16px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { background-color: #e74c3c; }
            QPushButton:disabled {
                background-color: #3a3a3a; color: #666;
            }
        """)
        self.btn_import.clicked.connect(self._do_import)

        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_import)
        layout.addLayout(buttons)

    def _existing_names(self):
        try:
            names = set()
            for t in self.db.get_all_tags() or []:
                if isinstance(t, dict) and t.get('name'):
                    names.add(t['name'])
            return names
        except Exception:
            return set()

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку с tags_export.json",
            os.path.expanduser("~")
        )
        if not folder:
            return

        info = analyze_import_source(folder)
        if 'error' in info:
            QMessageBox.warning(self, "Ошибка", info['error'])
            self.source_folder = ''
            self.path_edit.setText('')
            self.empty_label.setVisible(True)
            self.empty_label.setText("Выберите папку для анализа")
            for lbl in (self.lbl_total, self.lbl_new, self.lbl_existing,
                        self.lbl_covers):
                lbl.setVisible(False)
            self.chk_covers.setVisible(False)
            self.btn_import.setEnabled(False)
            return

        self.source_folder = folder
        self._source_info = info
        self.path_edit.setText(folder)

        # Считаем новые/существующие
        existing = self._existing_names()
        tags = info['tags']
        new_count = sum(1 for t in tags if t['name'] not in existing)
        existing_count = len(tags) - new_count

        self.empty_label.setVisible(False)

        self.lbl_total.setText(f"<b>Всего тегов в файле:</b> {len(tags)}")
        self.lbl_total.setVisible(True)

        self.lbl_new.setText(f"<b>Новых (будут добавлены):</b> {new_count}")
        self.lbl_new.setVisible(True)

        self.lbl_existing.setText(
            f"<b>Уже есть в библиотеке:</b> {existing_count}"
        )
        self.lbl_existing.setVisible(True)

        if info['covers_count'] > 0:
            self.lbl_covers.setText(
                f"<b>Файлов обложек:</b> {info['covers_count']}"
            )
            self.lbl_covers.setVisible(True)
            self.chk_covers.setVisible(True)
            self.chk_covers.setChecked(True)
        else:
            self.lbl_covers.setVisible(False)
            self.chk_covers.setVisible(False)
            self.chk_covers.setChecked(False)

        self.btn_import.setEnabled(len(tags) > 0)

    def _do_import(self):
        if not self.source_folder:
            return

        include_covers = self.chk_covers.isChecked()

        reply = QMessageBox.question(
            self, "Подтверждение импорта",
            f"Импортировать теги из:\n{self.source_folder}\n\n"
            "Существующие теги не будут дублироваться.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        result = perform_import(
            self.app_dir, self.source_folder, self.db,
            include_covers=include_covers
        )

        parts = []
        if result['added'] > 0:
            parts.append(f"✅ Добавлено новых тегов: {result['added']}")
        if result['existing'] > 0:
            parts.append(f"↺ Уже были в библиотеке: {result['existing']}")
        if result['covers'] > 0:
            parts.append(f"🖼️ Обложек перенесено: {result['covers']}")
        if result['errors']:
            parts.append("⚠️ Ошибки:\n" + "\n".join(
                f"• {e}" for e in result['errors'][:8]
            ))

        text = "\n\n".join(parts) if parts else "Нечего было импортировать."
        QMessageBox.information(self, "Импорт завершён", text)
        self.accept()