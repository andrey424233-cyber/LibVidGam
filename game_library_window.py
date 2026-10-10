import io
import os
import shutil
import traceback

from PIL import Image
from PyQt5.QtCore import (Qt, pyqtSignal, QTimer, QThread, QObject,
                          QRunnable, QThreadPool)
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
                             QLabel, QPushButton, QDialog, QLineEdit,
                             QMenu, QMessageBox, QFileDialog,
                             QGroupBox, QCheckBox,
                             QProgressDialog, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView)

import cover_cache
from cover_render import render_cover
from database import Database
from exe_icon import extract_exe_icon
from game_launcher import (GameLauncher, is_probable_game_exe,
                            find_cover_in_folder, is_process_alive)
from archive_extractor import (is_archive, load_passwords,
                                find_game_exe, mark_as_extracted,
                                passwords_path_near, process_archive_for_game,
                                is_extracted_marker, ensure_tools_configured,
                                UNRAR_PATH_FOUND, SEVENZIP_PATH_FOUND)
from group_card import GroupCard
from library_config import get_settings, set_settings
from search_filters_dialog import SearchFiltersDialog


GAME_COVER_SIZE = (500, 500)
LIBTAG_MIME = 'application/x-libtag'
FOLDER_MARKER_NAME = '.liblibdab_scanned'
BATCH_ROWS = 3
BATCH_INTERVAL_MS = 10


def format_playtime(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "0м"
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    if h > 0:
        return f"{h}ч {m:02d}м"
    if m > 0:
        return f"{m}м"
    return f"{s}с"


def human_size(num: int) -> str:
    try:
        n = float(num)
    except Exception:
        return "—"
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} ТБ"


def _same_path(a: str, b: str) -> bool:
    if not a or not b:
        return False
    try:
        return (os.path.normcase(os.path.normpath(a))
                == os.path.normcase(os.path.normpath(b)))
    except Exception:
        return False


# ============================================================
# Маркеры папок
# ============================================================

def read_folder_marker(folder: str) -> str:
    marker = os.path.join(folder, FOLDER_MARKER_NAME)
    if not os.path.isfile(marker):
        return ''
    try:
        with open(marker, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def write_folder_marker(folder: str, exe_path: str):
    marker = os.path.join(folder, FOLDER_MARKER_NAME)
    try:
        with open(marker, 'w', encoding='utf-8') as f:
            f.write(exe_path)
    except OSError as e:
        print(f"[scan] write_folder_marker({folder}): {e}")


def clear_folder_marker(folder: str):
    marker = os.path.join(folder, FOLDER_MARKER_NAME)
    try:
        if os.path.isfile(marker):
            os.remove(marker)
    except OSError as e:
        print(f"[scan] clear_folder_marker({folder}): {e}")


def is_folder_marker_fresh(folder: str) -> bool:
    marker = os.path.join(folder, FOLDER_MARKER_NAME)
    if not os.path.isfile(marker):
        return False
    try:
        marker_mtime = os.path.getmtime(marker)
        folder_mtime = os.path.getmtime(folder)
        return folder_mtime <= marker_mtime + 1.0
    except OSError:
        return False


# ============================================================
# Эвристический поиск архива для игры
# ============================================================

def find_archive_for_game(exe_path: str, games_folder: str) -> str:
    if not exe_path or not games_folder:
        return ''

    game_folder = os.path.dirname(exe_path)
    if not game_folder:
        return ''
    folder_name = os.path.basename(game_folder)
    if not folder_name:
        return ''

    candidates = [
        f"{folder_name}.rar.extracted",
        f"{folder_name}.zip.extracted",
        f"{folder_name}.7z.extracted",
    ]

    parent = os.path.dirname(game_folder)
    for name in candidates:
        p = os.path.join(parent, name)
        if os.path.isfile(p):
            return p

    if os.path.isdir(games_folder):
        try:
            for root, dirs, files in os.walk(games_folder):
                depth = root[len(games_folder):].count(os.sep)
                if depth >= 3:
                    dirs[:] = []
                    continue
                for name in candidates:
                    p = os.path.join(root, name)
                    if os.path.isfile(p):
                        return p
        except OSError:
            pass

    return ''


def collect_extracted_chain(exe_path: str, games_folder: str):
    result = []
    if not exe_path or not games_folder:
        return result

    games_norm = os.path.normcase(os.path.normpath(games_folder))
    current = os.path.dirname(exe_path)

    while True:
        current_norm = os.path.normcase(os.path.normpath(current))
        if current_norm == games_norm:
            break

        folder_name = os.path.basename(current)
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break

        if folder_name:
            try:
                for entry in os.listdir(parent):
                    if not entry.lower().endswith('.extracted'):
                        continue
                    name_without = entry[:-len('.extracted')]
                    base = os.path.splitext(name_without)[0]
                    if base.lower() == folder_name.lower():
                        full = os.path.join(parent, entry)
                        if os.path.isfile(full):
                            result.append(full)
            except OSError:
                pass

        parent_norm = os.path.normcase(os.path.normpath(parent))
        if parent_norm == games_norm:
            break
        current = parent

    return result


# ============================================================
# Фоновый загрузчик обложек игр
# ============================================================

class _GameCoverSignals(QObject):
    loaded = pyqtSignal(str, QImage)
    failed = pyqtSignal(str)


class GameCoverLoader(QRunnable):
    def __init__(self, exe_path: str, cover_path: str = None):
        super().__init__()
        self.exe_path = exe_path
        self.cover_path = cover_path
        self.signals = _GameCoverSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            img = self._load()
            if img is not None and not img.isNull():
                self.signals.loaded.emit(self.exe_path, img)
            else:
                self.signals.failed.emit(self.exe_path)
        except Exception as e:
            print(f"[game_cover] run({self.exe_path}): {e}")
            self.signals.failed.emit(self.exe_path)

    def _load(self):
        if self.cover_path and os.path.isfile(self.cover_path):
            try:
                img = self._from_file(self.cover_path)
                if img is not None and not img.isNull():
                    return img
            except Exception as e:
                print(f"[game_cover] user cover: {e}")

        try:
            cached = cover_cache.load(self.exe_path, GAME_COVER_SIZE)
            if cached is not None and not cached.isNull():
                return cached
        except Exception as e:
            print(f"[game_cover] disk cache: {e}")

        try:
            folder = os.path.dirname(self.exe_path)
            if folder and os.path.isdir(folder):
                auto = find_cover_in_folder(folder)
                if auto:
                    img = self._from_file(auto)
                    if img is not None and not img.isNull():
                        try:
                            cover_cache.save(self.exe_path, GAME_COVER_SIZE, img)
                        except Exception:
                            pass
                        return img
        except Exception as e:
            print(f"[game_cover] auto search: {e}")

        try:
            img = extract_exe_icon(self.exe_path, 256)
            if img is not None and not img.isNull():
                normalized = self._normalize_icon(img)
                if normalized is not None and not normalized.isNull():
                    try:
                        cover_cache.save(self.exe_path,
                                         GAME_COVER_SIZE, normalized)
                    except Exception:
                        pass
                    return normalized
                return img
        except Exception as e:
            print(f"[game_cover] exe icon: {e}")

        return None

    @staticmethod
    def _normalize_icon(qimage):
        try:
            im = Image.fromqimage(qimage)
            if im.mode not in ('RGB', 'RGBA'):
                im = im.convert('RGBA')
            max_side = max(GAME_COVER_SIZE)
            im.thumbnail((max_side, max_side), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format='PNG')
            buf.seek(0)
            q = QImage()
            q.loadFromData(buf.read())
            return q if not q.isNull() else None
        except Exception as e:
            print(f"[game_cover] icon normalize: {e}")
            return None

    @staticmethod
    def _from_file(path):
        try:
            im = Image.open(path)
            max_side = max(GAME_COVER_SIZE)
            im.thumbnail((max_side, max_side), Image.LANCZOS)
            if im.mode not in ('RGB', 'RGBA'):
                im = im.convert('RGB')
            buf = io.BytesIO()
            im.save(buf, format='PNG')
            buf.seek(0)
            q = QImage()
            q.loadFromData(buf.read())
            return q if not q.isNull() else None
        except Exception:
            return None


# ============================================================
# Фоновый воркер сканирования
# ============================================================

class ScanWorker(QThread):
    finished_ok = pyqtSignal(dict)

    def __init__(self, games_folder: str, passwords_path: str,
                 existing_paths: set, parent=None):
        super().__init__(parent)
        self.games_folder = games_folder
        self.passwords_path = passwords_path
        self.existing_paths = set(existing_paths)
        self._stop = False

    def stop(self):
        self._stop = True

    def _collect_archives(self):
        found = []
        if not os.path.isdir(self.games_folder):
            return found
        try:
            for root, dirs, files in os.walk(self.games_folder):
                if self._stop:
                    break
                depth = root[len(self.games_folder):].count(os.sep)
                if depth >= 3:
                    dirs[:] = []
                    continue
                for f in files:
                    if is_archive(f):
                        found.append(os.path.join(root, f))
        except Exception:
            pass
        return found

    def _scan_existing_folders(self):
        found = []
        if not os.path.isdir(self.games_folder):
            return found
        try:
            entries = os.listdir(self.games_folder)
        except OSError:
            return found

        for entry in entries:
            if self._stop:
                break
            full = os.path.join(self.games_folder, entry)

            if os.path.isfile(full):
                # Передаём папку — важно для NW.js-игр (nw.exe / nwjs.exe)
                if is_probable_game_exe(entry, self.games_folder):
                    found.append(full)
                continue

            if not os.path.isdir(full):
                continue
            if entry.startswith('__') or entry.startswith('.'):
                continue

            if is_folder_marker_fresh(full):
                saved_exe = read_folder_marker(full)
                if saved_exe and os.path.isfile(saved_exe):
                    if saved_exe not in self.existing_paths:
                        found.append(saved_exe)
                    continue

            try:
                exe = find_game_exe(full, is_probable_game_exe, max_depth=3)
                if exe:
                    found.append(exe)
                    write_folder_marker(full, exe)
                else:
                    write_folder_marker(full, '')
            except Exception as e:
                print(f"[scan] find_game_exe({full}): {e}")

        return found

    def run(self):
        result = {
            'new_games': [],
            'extracted': 0,
            'found_in_folders': 0,
            'skipped': 0,
            'archives_found': 0,
            'errors': [],
            'tools': {
                'unrar': bool(UNRAR_PATH_FOUND),
                'sevenzip': bool(SEVENZIP_PATH_FOUND),
            },
        }

        try:
            archives = self._collect_archives()
            result['archives_found'] = len(archives)

            if archives:
                try:
                    passwords = load_passwords(self.passwords_path)
                except Exception as e:
                    passwords = {}
                    result['errors'].append(f"passwords: {e}")

                for archive_path in archives:
                    if self._stop:
                        break

                    if is_extracted_marker(archive_path):
                        result['skipped'] += 1
                        continue

                    target_dir = os.path.splitext(archive_path)[0]
                    name = os.path.basename(archive_path)

                    if os.path.isdir(target_dir):
                        try:
                            existing_exe = find_game_exe(
                                target_dir, is_probable_game_exe, max_depth=4
                            )
                            if existing_exe:
                                marked = mark_as_extracted(archive_path)
                                write_folder_marker(target_dir, existing_exe)
                                title = os.path.splitext(
                                    os.path.basename(existing_exe)
                                )[0]
                                working_dir = os.path.dirname(existing_exe)
                                if existing_exe not in self.existing_paths:
                                    self.existing_paths.add(existing_exe)
                                    result['new_games'].append(
                                        (title, existing_exe,
                                         working_dir, marked)
                                    )
                                result['skipped'] += 1
                                continue
                        except OSError:
                            pass

                    try:
                        exe_path, marked_archive = process_archive_for_game(
                            archive_path, target_dir, passwords,
                            is_probable_game_exe,
                            max_depth=4, max_recurse=3,
                            log=None,
                        )
                        result['extracted'] += 1

                        if exe_path:
                            write_folder_marker(target_dir, exe_path)
                            title = os.path.splitext(
                                os.path.basename(exe_path)
                            )[0]
                            working_dir = os.path.dirname(exe_path)
                            if exe_path not in self.existing_paths:
                                self.existing_paths.add(exe_path)
                                result['new_games'].append(
                                    (title, exe_path,
                                     working_dir, marked_archive)
                                )
                        else:
                            result['errors'].append(
                                f"{name}: игра не найдена после распаковки"
                            )
                    except Exception as e:
                        result['errors'].append(f"{name}: {e}")

            if not self._stop:
                found_exes = self._scan_existing_folders()
                for fp in found_exes:
                    if fp in self.existing_paths:
                        continue
                    title = os.path.splitext(os.path.basename(fp))[0]
                    working_dir = os.path.dirname(fp)
                    self.existing_paths.add(fp)
                    result['new_games'].append((title, fp, working_dir, None))
                    result['found_in_folders'] += 1

            self.finished_ok.emit(result)

        except Exception as e:
            tb = traceback.format_exc()
            print(tb)
            result['errors'].append(f"FATAL: {e}")
            try:
                self.finished_ok.emit(result)
            except Exception:
                pass


# ============================================================
# Диалог управления архивами
# ============================================================

class ClickableCheck(QLabel):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(26, 26)
        self._refresh()

    def _refresh(self):
        if self._checked:
            self.setText("✓")
            self.setStyleSheet("""
                QLabel {
                    color: #ffffff; font-size: 18px; font-weight: bold;
                    background-color: #c0392b;
                    border: 2px solid #c0392b; border-radius: 4px;
                }
            """)
        else:
            self.setText("")
            self.setStyleSheet("""
                QLabel {
                    background-color: #1a1a1a;
                    border: 2px solid #666666; border-radius: 4px;
                }
            """)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool):
        v = bool(value)
        if v != self._checked:
            self._checked = v
            self._refresh()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._checked = not self._checked
            self._refresh()
        super().mousePressEvent(event)


class ArchiveManagerDialog(QDialog):
    def __init__(self, db: Database, games_folder: str, parent=None):
        super().__init__(parent)
        self.db = db
        self.games_folder = games_folder
        self._archives = []

        self.setWindowTitle("Управление архивами игр")
        self.setFixedSize(760, 560)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; background: transparent; }
            QTableWidget {
                background-color: #2a2a2a; color: #ffffff;
                border: 1px solid #3a3a3a; border-radius: 5px;
                gridline-color: #3a3a3a; font-size: 13px;
            }
            QTableWidget::item { padding: 6px; }
            QTableWidget::item:selected { background-color: #c0392b; }
            QHeaderView::section {
                background-color: #252525; color: #ffffff;
                border: none; padding: 10px;
                font-weight: bold; font-size: 13px;
            }
            QPushButton {
                background-color: #2a2a2a; color: #ffffff;
                border: none; border-radius: 5px; padding: 8px 15px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        hint = QLabel(
            "Отметьте архивы, которые вы уже проверили и игра из которых "
            "работает. Удаление необратимо."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("QLabel { color: #888; font-size: 12px; }")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "Архив", "Размер", "Игра"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().resizeSection(0, 40)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

        self.count_label = QLabel("Архивов: 0")
        self.count_label.setStyleSheet("QLabel { color: #888; }")
        layout.addWidget(self.count_label)

        buttons = QHBoxLayout()

        self.btn_select_all = QPushButton("Отметить все")
        self.btn_select_all.clicked.connect(lambda: self._set_all(True))
        buttons.addWidget(self.btn_select_all)

        self.btn_unselect_all = QPushButton("Снять все")
        self.btn_unselect_all.clicked.connect(lambda: self._set_all(False))
        buttons.addWidget(self.btn_unselect_all)

        self.btn_refresh = QPushButton("🔄 Обновить")
        self.btn_refresh.clicked.connect(self._reload)
        buttons.addWidget(self.btn_refresh)

        buttons.addStretch()

        self.btn_delete = QPushButton("🗑️ Удалить отмеченные")
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #8b2a2a; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 8px 18px; font-weight: bold;
            }
            QPushButton:hover { background-color: #a33; }
        """)
        self.btn_delete.clicked.connect(self._delete_selected)
        buttons.addWidget(self.btn_delete)

        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.reject)
        buttons.addWidget(self.btn_close)

        layout.addLayout(buttons)
        self.setLayout(layout)

        self._reload()

    def _reload(self):
        self._archives = []

        try:
            games = self.db.get_all_games()
        except Exception:
            games = []

        by_archive = {}
        for g in games:
            ap = g.get('archive_path')
            if ap:
                by_archive[os.path.normcase(os.path.normpath(ap))] = \
                    g.get('title', '')

        if not os.path.isdir(self.games_folder):
            self._rebuild_table()
            return

        try:
            for root, dirs, files in os.walk(self.games_folder):
                depth = root[len(self.games_folder):].count(os.sep)
                if depth >= 3:
                    dirs[:] = []
                    continue
                for f in files:
                    if not f.lower().endswith('.extracted'):
                        continue
                    full = os.path.join(root, f)
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        size = 0

                    norm = os.path.normcase(os.path.normpath(full))
                    game_title = by_archive.get(norm, '')

                    if not game_title:
                        base = f[:-len('.extracted')]
                        folder_candidate = os.path.splitext(base)[0]
                        for g in games:
                            exe = g['exe_path']
                            g_folder = os.path.dirname(exe)
                            if os.path.basename(g_folder).lower() == \
                                    folder_candidate.lower():
                                game_title = g.get('title', '')
                                break

                    self._archives.append((full, size, game_title))
        except OSError:
            pass

        self._archives.sort(key=lambda x: x[0].lower())
        self._rebuild_table()

    def _rebuild_table(self):
        self.table.setRowCount(0)
        for path, size, title in self._archives:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setRowHeight(row, 32)

            chk = ClickableCheck()
            self.table.setCellWidget(row, 0, chk)

            name_item = QTableWidgetItem(os.path.basename(path))
            name_item.setToolTip(path)
            self.table.setItem(row, 1, name_item)

            self.table.setItem(row, 2, QTableWidgetItem(human_size(size)))
            self.table.setItem(row, 3, QTableWidgetItem(title or '—'))

        self.count_label.setText(f"Архивов: {len(self._archives)}")

    def _set_all(self, value: bool):
        for row in range(self.table.rowCount()):
            w = self.table.cellWidget(row, 0)
            if isinstance(w, ClickableCheck):
                w.setChecked(value)

    def _delete_selected(self):
        to_delete = []
        for row in range(self.table.rowCount()):
            w = self.table.cellWidget(row, 0)
            if isinstance(w, ClickableCheck) and w.isChecked():
                path = self._archives[row][0]
                title = self._archives[row][2]
                to_delete.append((path, title))

        if not to_delete:
            QMessageBox.information(self, "Ничего не выбрано",
                                    "Отметьте хотя бы один архив.")
            return

        total_size = 0
        names = []
        for path, _title in to_delete:
            try:
                total_size += os.path.getsize(path)
            except OSError:
                pass
            names.append(os.path.basename(path))

        preview = "\n".join(f"• {n}" for n in names[:10])
        if len(names) > 10:
            preview += f"\n... и ещё {len(names) - 10}"

        reply = QMessageBox.question(
            self, "Удалить архивы?",
            f"Будет удалено {len(to_delete)} архив(ов), "
            f"общий размер {human_size(total_size)}.\n\n"
            f"{preview}\n\n"
            "Это действие нельзя отменить. Продолжить?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        deleted = 0
        errors = []
        for path, _title in to_delete:
            try:
                os.remove(path)
                deleted += 1
                norm = os.path.normcase(os.path.normpath(path))
                try:
                    for g in self.db.get_all_games():
                        ap = g.get('archive_path')
                        if ap and os.path.normcase(
                                os.path.normpath(ap)) == norm:
                            self.db.clear_game_archive_path(g['id'])
                except Exception:
                    pass
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")

        msg = f"Удалено архивов: {deleted}"
        if errors:
            msg += "\n\n⚠️ Ошибки:\n" + "\n".join(errors[:10])
        QMessageBox.information(self, "Готово", msg)
        self._reload()


# ============================================================
# Карточка игры
# ============================================================

class GameCard(QWidget):
    clicked = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    reset_requested = pyqtSignal(str)
    rescan_folder_requested = pyqtSignal(str)
    delete_archive_requested = pyqtSignal(str)
    delete_file_requested = pyqtSignal(str)
    tag_assigned = pyqtSignal(str, str)

    DEFAULT_STYLE = """
        GameCard {
            background-color: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 6px;
        }
    """
    DRAG_STYLE = """
        GameCard {
            background-color: #2a1a1a;
            border: 2px solid #c0392b;
            border-radius: 6px;
        }
    """
    SUCCESS_STYLE = """
        GameCard {
            background-color: #1a2a1a;
            border: 2px solid #27ae60;
            border-radius: 6px;
        }
    """
    RUNNING_STYLE = """
        GameCard {
            background-color: #1a1a2a;
            border: 2px solid #3498db;
            border-radius: 6px;
        }
    """

    def __init__(self, game, db, card_width=200, card_height=280, parent=None):
        super().__init__(parent)
        self.game = game
        self.db = db
        self.file_path = game['exe_path']
        self.card_width = card_width
        self.card_height = card_height
        self._is_running = False

        self._qimage = None
        self._scaled_cache = None
        self._scaled_cache_size = (0, 0)

        self.setFixedSize(card_width, card_height)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setStyleSheet(self.DEFAULT_STYLE)

        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        cover_h = card_height - 60

        self.cover_label = QLabel("🎮")
        self.cover_label.setFixedSize(card_width - 12, cover_h)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet("""
            QLabel { color: #555; font-size: 64px;
                     background: #0d0d0d; border-radius: 4px; }
        """)
        layout.addWidget(self.cover_label)

        self.title_label = QLabel(game['title'])
        self.title_label.setFixedSize(card_width - 12, 20)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(
            "QLabel { color: #fff; font-size: 12px; font-weight: bold;"
            " background: transparent; border: none; }"
        )
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.meta_label = QLabel("")
        self.meta_label.setFixedSize(card_width - 12, 18)
        self.meta_label.setAlignment(Qt.AlignCenter)
        self.meta_label.setStyleSheet(
            "QLabel { color: #999; font-size: 11px;"
            " background: transparent; border: none; }"
        )
        layout.addWidget(self.meta_label)

        self.setLayout(layout)
        self.refresh_meta()

    def refresh_meta(self):
        launches = self.game.get('launch_count', 0) or 0
        playtime = format_playtime(self.game.get('total_playtime', 0) or 0)
        self.meta_label.setText(f"▶  {launches}    ⏱  {playtime}")
        self.meta_label.setToolTip(
            f"Запусков: {launches}\nВсего сыграно: {playtime}"
        )

    def set_cover(self, qimage):
        if qimage is None or qimage.isNull():
            return
        self._qimage = qimage
        self._scaled_cache = None
        self._scaled_cache_size = (0, 0)
        self._apply_cover()

    def _apply_cover(self):
        if self._qimage is None:
            return
        try:
            w = self.cover_label.width()
            h = self.cover_label.height()
        except RuntimeError:
            return
        if w <= 0 or h <= 0:
            return

        if (self._scaled_cache is not None
                and self._scaled_cache_size == (w, h)
                and not self._scaled_cache.isNull()):
            try:
                self.cover_label.setPixmap(self._scaled_cache)
                self.cover_label.setText("")
            except RuntimeError:
                pass
            return

        pix = render_cover(self._qimage, w, h)
        if pix.isNull():
            return
        self._scaled_cache = pix
        self._scaled_cache_size = (w, h)
        try:
            self.cover_label.setPixmap(pix)
            self.cover_label.setText("")
        except RuntimeError:
            pass

    def resize_card(self, new_w, new_h):
        if new_w == self.card_width and new_h == self.card_height:
            return
        self.card_width = new_w
        self.card_height = new_h
        self.setFixedSize(new_w, new_h)

        cover_h = new_h - 60
        self.cover_label.setFixedSize(new_w - 12, cover_h)
        self.title_label.setFixedSize(new_w - 12, 20)
        self.meta_label.setFixedSize(new_w - 12, 18)

        self._scaled_cache = None
        self._scaled_cache_size = (0, 0)
        self._apply_cover()

    def set_running(self, running: bool):
        self._is_running = running
        self.setStyleSheet(self.RUNNING_STYLE if running else self.DEFAULT_STYLE)

    def is_running(self) -> bool:
        return self._is_running

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(LIBTAG_MIME):
            event.acceptProposedAction()
            if not self._is_running:
                self.setStyleSheet(self.DRAG_STYLE)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(LIBTAG_MIME):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        if not self._is_running:
            self.setStyleSheet(self.DEFAULT_STYLE)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if not self._is_running:
            self.setStyleSheet(self.DEFAULT_STYLE)
        if not event.mimeData().hasFormat(LIBTAG_MIME):
            event.ignore()
            return
        try:
            tag_name = bytes(event.mimeData().data(LIBTAG_MIME)).decode('utf-8')
            tag_id = self.db.get_tag_id(tag_name)
            if tag_id is None:
                tag_id = self.db.add_tag(tag_name)
            self.db.assign_tag_to_game(self.game['id'], tag_id)
            event.acceptProposedAction()
            self._flash_success()
            self.tag_assigned.emit(self.file_path, tag_name)
        except Exception as e:
            print(f"Ошибка назначения тега: {e}")
            event.ignore()

    def _flash_success(self):
        self.setStyleSheet(self.SUCCESS_STYLE)
        QTimer.singleShot(400, self._restore_style)

    def _restore_style(self):
        self.setStyleSheet(
            self.RUNNING_STYLE if self._is_running else self.DEFAULT_STYLE
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.file_path)
        elif event.button() == Qt.RightButton:
            self._show_menu(event)

    def _show_menu(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #1e1e1e; color: #e0e0e0;
                    border: 1px solid #3a3a3a; border-radius: 5px; padding: 5px; }
            QMenu::item:selected { background-color: #c0392b; }
        """)
        act_play = menu.addAction("▶ Запустить")
        act_reset = None
        if self._is_running:
            act_reset = menu.addAction("🔄 Сбросить статус запуска")
        menu.addSeparator()
        act_del_archive = menu.addAction("🗑️ Удалить архив (после проверки)")
        act_rescan = menu.addAction("🔄 Пересканировать папку")
        menu.addSeparator()
        act_edit = menu.addAction("✏️ Редактировать")
        act_delete = menu.addAction("🗑️ Удалить из библиотеки")
        menu.addSeparator()
        act_del_device = menu.addAction("💥 Удалить с устройства")

        chosen = menu.exec_(self.mapToGlobal(event.pos()))

        if chosen is None:
            return
        if chosen == act_play:
            QTimer.singleShot(0, lambda: self.clicked.emit(self.file_path))
        elif act_reset is not None and chosen == act_reset:
            QTimer.singleShot(
                0, lambda: self.reset_requested.emit(self.file_path))
        elif chosen == act_del_archive:
            QTimer.singleShot(
                0, lambda: self.delete_archive_requested.emit(self.file_path))
        elif chosen == act_rescan:
            QTimer.singleShot(
                0, lambda: self.rescan_folder_requested.emit(self.file_path))
        elif chosen == act_edit:
            QTimer.singleShot(
                0, lambda: self.edit_requested.emit(self.file_path))
        elif chosen == act_delete:
            QTimer.singleShot(
                0, lambda: self.delete_requested.emit(self.file_path))
        elif chosen == act_del_device:
            QTimer.singleShot(
                0, lambda: self.delete_file_requested.emit(self.file_path))


# ↓ ↓ ↓ СЮДА ВСТАВЬ ЧАСТЬ 2 ↓ ↓ ↓

class GameLibraryWindow(QWidget):
    game_launched = pyqtSignal(str)

    BASE_CARD_WIDTH = 200
    BASE_CARD_HEIGHT = 280
    SPACING = 15
    WATCHDOG_INTERVAL_MS = 3000

    def __init__(self, db: Database, games_folder: str, parent=None):
        super().__init__(parent)
        self.db = db
        self.games_folder = games_folder
        self._current_games = []
        self._current_display = []
        self._cover_cache = {}
        self._has_been_loaded = False
        self.hidden_tags = []
        self.current_filter = None
        self.current_search = {}

        self.filters = get_settings('games')
        self._expanded_groups = set()

        self._cards = {}
        self._running_games = {}
        self._scan_worker = None
        self._progress_dialog = None
        self._tools_initialized = False

        self._cover_waiters = {}
        self._cover_in_flight = set()

        self._cover_pool = QThreadPool(self)
        self._cover_pool.setMaxThreadCount(2)

        self._batch_timer = QTimer(self)
        self._batch_timer.setSingleShot(True)
        self._batch_timer.setInterval(BATCH_INTERVAL_MS)
        self._batch_timer.timeout.connect(self._create_next_batch)
        self._pending_rows = []
        self._batch_data = []
        self._batch_per_row = 4
        self._batch_card_w = 0
        self._batch_card_h = 0

        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(300)
        self._resize_timer.timeout.connect(self._on_resize)

        self._is_rebuilding = False

        self.launcher = GameLauncher()
        self.launcher.started.connect(self._on_game_started)
        self.launcher.finished.connect(self._on_game_finished)
        self.launcher.failed.connect(self._on_game_failed)

        self._watchdog = QTimer(self)
        self._watchdog.setInterval(self.WATCHDOG_INTERVAL_MS)
        self._watchdog.timeout.connect(self._check_running_games)
        self._watchdog.start()

        self.setStyleSheet("QWidget { background-color: #121212; }")

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        top = QHBoxLayout()

        self.btn_add = QPushButton("+ Добавить игру")
        self.btn_add.setFixedSize(160, 40)
        self.btn_add.setStyleSheet("""
            QPushButton { background-color: #c0392b; color: white;
                          border: none; border-radius: 20px; font-size: 14px; }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_add.clicked.connect(self.add_game)
        top.addWidget(self.btn_add)

        self.btn_scan = QPushButton("📁 Сканировать папку")
        self.btn_scan.setFixedSize(175, 40)
        self.btn_scan.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px; font-size: 14px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_scan.clicked.connect(self.scan_folder)
        top.addWidget(self.btn_scan)

        self.btn_manage_archives = QPushButton("📦 Архивы")
        self.btn_manage_archives.setFixedSize(140, 40)
        self.btn_manage_archives.setToolTip("Управление распакованными архивами")
        self.btn_manage_archives.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px; font-size: 14px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_manage_archives.clicked.connect(self.open_archive_manager)
        top.addWidget(self.btn_manage_archives)

        self.btn_passwords = QPushButton("🔐 Пароли")
        self.btn_passwords.setFixedSize(130, 40)
        self.btn_passwords.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px; font-size: 14px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_passwords.clicked.connect(self.open_passwords_dialog)
        top.addWidget(self.btn_passwords)

        self.btn_clear_filter = QPushButton("✖ Сбросить фильтр")
        self.btn_clear_filter.setFixedSize(180, 40)
        self.btn_clear_filter.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px; font-size: 14px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_clear_filter.clicked.connect(self._clear_filter)
        self.btn_clear_filter.setVisible(False)
        top.addWidget(self.btn_clear_filter)

        top.addStretch()

        self.count_label = QLabel("0 игр")
        self.count_label.setStyleSheet("QLabel { color: #888; font-size: 14px; }")
        top.addWidget(self.count_label)

        layout.addLayout(top)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background-color: #121212; }
        """)

        self.content_widget = QWidget()
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(self.SPACING)
        self.content_widget.setLayout(self.main_layout)

        self.scroll_area.setWidget(self.content_widget)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)

    # ---------- утилиты ----------

    def _cancel_batch(self):
        try:
            self._batch_timer.stop()
        except Exception:
            pass
        self._pending_rows = []
        self._batch_data = []

    def set_folder(self, folder: str):
        if folder == self.games_folder:
            return
        self.games_folder = folder
        if self._has_been_loaded:
            self._cancel_batch()
            self.load_games()

    def open_passwords_dialog(self):
        from archive_passwords_dialog import ArchivePasswordsDialog
        dialog = ArchivePasswordsDialog(self.db.db_path, self)
        dialog.exec_()

    def open_archive_manager(self):
        dialog = ArchiveManagerDialog(self.db, self.games_folder, self)
        dialog.exec_()

    def _check_running_games(self):
        if not self._running_games:
            return
        dirty = False
        for gid, (exe, pid) in list(self._running_games.items()):
            if pid and pid > 0 and not is_process_alive(pid):
                self._running_games.pop(gid, None)
                card = self._cards.get(exe)
                if card is not None:
                    try:
                        if card.is_running():
                            card.set_running(False)
                    except RuntimeError:
                        pass
                dirty = True
        if dirty:
            self._refresh_counts()

    def set_hidden_tags(self, tags):
        new_tags = list(tags or [])
        if new_tags == self.hidden_tags:
            return
        self.hidden_tags = new_tags
        if self._has_been_loaded:
            self.refresh()

    def _initial_load(self):
        if not self._has_been_loaded:
            self._has_been_loaded = True
            self.load_games()

    def refresh(self):
        self._cancel_batch()
        self._has_been_loaded = True
        self._cover_cache.clear()
        self.load_games()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._is_rebuilding and self._has_been_loaded:
            self._resize_timer.start()

    def _on_resize(self):
        if self._is_rebuilding:
            return
        self._cancel_batch()
        self.load_games(self._current_games or None)

    def _calculate_cards_per_row(self, card_width):
        vw = self.scroll_area.viewport().width() - 40
        return max(1, (vw + self.SPACING) // (card_width + self.SPACING))

    # ---------- построение ----------

    def load_games(self, games=None):
        if self._is_rebuilding:
            return
        self._is_rebuilding = True

        self._cancel_batch()
        self._cover_waiters.clear()

        try:
            self._check_running_games()

            while self.main_layout.count():
                item = self.main_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
            self._cards.clear()

            if games is None:
                if self.hidden_tags:
                    games = self.db.search_games(
                        exclude_tags=self.hidden_tags,
                        folder=self.games_folder
                    )
                else:
                    games = self.db.get_games_in_folder(self.games_folder)

            self._current_games = games
            self.count_label.setText(f"{len(games)} игр")

            self._current_display = self._build_display_structure(games)

            card_w = self.BASE_CARD_WIDTH
            card_h = self.BASE_CARD_HEIGHT
            per_row = self._calculate_cards_per_row(card_w)

            self._batch_data = self._current_display
            self._batch_per_row = per_row
            self._batch_card_w = card_w
            self._batch_card_h = card_h
            self._pending_rows = list(
                range(0, len(self._current_display), per_row)
            )
        finally:
            self._is_rebuilding = False

        if self._pending_rows:
            self._batch_timer.start()
        else:
            self.main_layout.addStretch()

    def _build_display_structure(self, games):
        result = []
        sort_by_views = self.filters.get('sort_by_views', False)
        group_series = self.filters.get('group_by_series', False)
        group_authors = self.filters.get('group_by_authors', False)

        if not group_series and not group_authors:
            items = list(games)
            if sort_by_views:
                items.sort(key=lambda g: -(g.get('launch_count', 0) or 0))
            for g in items:
                result.append({'kind': 'item', 'game': g})
            return result

        def author_key(g):
            name = g.get('author_name')
            return name if name else None

        def series_key(g):
            sid = g.get('series_id')
            if sid:
                return (sid, g.get('series_name') or '')
            return None

        def sort_by_order(items):
            return sorted(
                items,
                key=lambda g: (
                    g.get('series_order') or 999999,
                    (g.get('title') or '').lower()
                )
            )

        if group_authors:
            top_groups = {}
            without_top = []
            for g in games:
                a = author_key(g)
                if a:
                    top_groups.setdefault(a, []).append(g)
                else:
                    without_top.append(g)

            top_names = sorted(top_groups.keys())
            if sort_by_views:
                top_names.sort(
                    key=lambda n: -sum(
                        (g.get('launch_count', 0) or 0)
                        for g in top_groups[n]
                    )
                )

            for author_name in top_names:
                items = top_groups[author_name]
                author_group_key = f'author:{author_name}'
                author_expanded = author_group_key in self._expanded_groups
                result.append({
                    'kind': 'group',
                    'gtype': 'author',
                    'title': author_name,
                    'items': items,
                    'key': author_group_key,
                    'depth': 0,
                })

                if author_expanded:
                    if group_series:
                        series_groups = {}
                        without_series = []
                        for g in items:
                            sk = series_key(g)
                            if sk:
                                series_groups.setdefault(sk, []).append(g)
                            else:
                                without_series.append(g)

                        s_keys = sorted(
                            series_groups.keys(), key=lambda k: k[1])
                        if sort_by_views:
                            s_keys.sort(
                                key=lambda k: -sum(
                                    (g.get('launch_count', 0) or 0)
                                    for g in series_groups[k]
                                )
                            )

                        for sk in s_keys:
                            s_items = sort_by_order(series_groups[sk])
                            series_name = sk[1] or 'Без названия'
                            series_group_key = \
                                f'series:{author_name}|{sk[0]}'
                            series_expanded = (series_group_key
                                               in self._expanded_groups)
                            result.append({
                                'kind': 'group',
                                'gtype': 'series',
                                'title': series_name,
                                'items': s_items,
                                'key': series_group_key,
                                'depth': 1,
                            })
                            if series_expanded:
                                for g in s_items:
                                    result.append({
                                        'kind': 'item',
                                        'game': g,
                                        'depth': 2,
                                    })

                        for g in sort_by_order(without_series):
                            result.append({
                                'kind': 'item',
                                'game': g,
                                'depth': 2,
                            })
                    else:
                        for g in items:
                            result.append({
                                'kind': 'item',
                                'game': g,
                                'depth': 1,
                            })

            for g in without_top:
                result.append({'kind': 'item', 'game': g})

            return result

        if group_series:
            series_groups = {}
            without_series = []
            for g in games:
                sk = series_key(g)
                if sk:
                    series_groups.setdefault(sk, []).append(g)
                else:
                    without_series.append(g)

            s_keys = sorted(series_groups.keys(), key=lambda k: k[1])
            if sort_by_views:
                s_keys.sort(
                    key=lambda k: -sum(
                        (g.get('launch_count', 0) or 0)
                        for g in series_groups[k]
                    )
                )

            for sk in s_keys:
                s_items = sort_by_order(series_groups[sk])
                series_name = sk[1] or 'Без названия'
                series_group_key = f'series:{sk[0]}'
                series_expanded = series_group_key in self._expanded_groups
                result.append({
                    'kind': 'group',
                    'gtype': 'series',
                    'title': series_name,
                    'items': s_items,
                    'key': series_group_key,
                    'depth': 0,
                })
                if series_expanded:
                    for g in s_items:
                        result.append({
                            'kind': 'item',
                            'game': g,
                            'depth': 1,
                        })

            for g in without_series:
                result.append({'kind': 'item', 'game': g})

            return result

        return result

    def _create_next_batch(self):
        if not self._pending_rows:
            self.main_layout.addStretch()
            return

        batch = self._pending_rows[:BATCH_ROWS]
        self._pending_rows = self._pending_rows[BATCH_ROWS:]

        data = self._batch_data
        per_row = self._batch_per_row
        card_w = self._batch_card_w
        card_h = self._batch_card_h

        for start in batch:
            chunk = data[start:start + per_row]
            if not chunk:
                continue
            row = QHBoxLayout()
            row.setSpacing(self.SPACING)
            row.setContentsMargins(0, 0, 0, 0)
            for elem in chunk:
                widget = self._make_widget_for_element(elem, card_w, card_h)
                if widget is not None:
                    row.addWidget(widget)
            row.addStretch()
            rw = QWidget()
            rw.setLayout(row)
            self.main_layout.addWidget(rw)

        if self._pending_rows:
            self._batch_timer.start()

    def _make_widget_for_element(self, elem, card_w, card_h):
        kind = elem.get('kind')

        if kind == 'group':
            pixmaps = []
            for g in elem['items'][:4]:
                p = self._cover_cache.get(g['exe_path'])
                if p is not None and not p.isNull():
                    pixmaps.append(p)
            card = GroupCard(
                title=elem['title'],
                count=len(elem['items']),
                pixmaps=pixmaps,
                kind=elem['gtype'],
                expanded=elem['key'] in self._expanded_groups,
                width=card_w,
                height=card_h,
            )
            card.clicked.connect(
                lambda k=elem['key']: QTimer.singleShot(
                    0, lambda: self._toggle_group(k)
                )
            )
            QTimer.singleShot(
                0,
                lambda e=elem, cc=card: self._request_group_covers(e, cc)
            )
            return card

        if kind == 'item':
            game = elem['game']
            card = GameCard(game, self.db, card_w, card_h)
            card.clicked.connect(self._on_card_clicked)
            card.edit_requested.connect(self.open_edit_dialog)
            card.delete_requested.connect(self.delete_game)
            card.reset_requested.connect(self._reset_game_status)
            card.rescan_folder_requested.connect(self._rescan_folder)
            card.delete_archive_requested.connect(
                self._delete_archive_after_check)
            card.delete_file_requested.connect(
                self._delete_game_from_device)
            self._cards[game['exe_path']] = card
            if game['id'] in self._running_games:
                card.set_running(True)
            self._request_cover(game, card)
            return card

        return None

    def _request_group_covers(self, elem, card):
        try:
            needed = elem['items'][:4]
        except Exception:
            return
        if not needed:
            return

        pending = []
        for game in needed:
            exe = game['exe_path']
            if exe in self._cover_cache:
                continue
            pending.append(game)

        def _refresh():
            pixmaps = []
            for g in needed:
                p = self._cover_cache.get(g['exe_path'])
                if p is not None and not p.isNull():
                    pixmaps.append(p)
            try:
                card.set_pixmaps(pixmaps)
            except RuntimeError:
                pass

        if not pending:
            _refresh()
            return

        remaining = [0]
        for game in pending:
            exe = game['exe_path']
            if exe in self._cover_in_flight:
                continue
            remaining[0] += 1
            self._cover_in_flight.add(exe)
            loader = GameCoverLoader(exe, cover_path=game.get('cover_path'))

            def _on_loaded(file_path, qimage):
                self._cover_in_flight.discard(file_path)
                if qimage is not None and not qimage.isNull():
                    self._cover_cache[file_path] = qimage
                remaining[0] -= 1
                if remaining[0] <= 0:
                    QTimer.singleShot(0, _refresh)

            def _on_failed(file_path):
                self._cover_in_flight.discard(file_path)
                remaining[0] -= 1
                if remaining[0] <= 0:
                    QTimer.singleShot(0, _refresh)

            loader.signals.loaded.connect(_on_loaded)
            loader.signals.failed.connect(_on_failed)
            self._cover_pool.start(loader)

        if remaining[0] <= 0:
            _refresh()

    def _toggle_group(self, key):
        if self._is_rebuilding:
            return
        if key in self._expanded_groups:
            self._expanded_groups.discard(key)
        else:
            self._expanded_groups.add(key)
        self.load_games(self._current_games or None)

    # ---------- обложки ----------

    def _request_cover(self, game, card):
        exe_path = game['exe_path']

        cached = self._cover_cache.get(exe_path)
        if cached is not None and not cached.isNull():
            card.set_cover(cached)
            return

        if exe_path in self._cover_waiters:
            self._cover_waiters[exe_path].append(card)
            return

        self._cover_waiters[exe_path] = [card]
        self._cover_in_flight.add(exe_path)

        loader = GameCoverLoader(exe_path, cover_path=game.get('cover_path'))
        loader.signals.loaded.connect(self._on_cover_loaded)
        loader.signals.failed.connect(self._on_cover_failed)
        self._cover_pool.start(loader)

    def _on_cover_loaded(self, exe_path, qimage):
        self._cover_in_flight.discard(exe_path)
        if qimage is not None and not qimage.isNull():
            self._cover_cache[exe_path] = qimage
        waiters = self._cover_waiters.pop(exe_path, [])
        for card in waiters:
            try:
                card.set_cover(qimage)
            except RuntimeError:
                pass

    def _on_cover_failed(self, exe_path):
        self._cover_in_flight.discard(exe_path)
        self._cover_waiters.pop(exe_path, None)

    # ---------- запуск ----------

    def launch_game(self, exe_path: str):
        self._on_card_clicked(exe_path)

    def _on_card_clicked(self, exe_path: str):
        game = self.db.get_game_by_path(exe_path)
        if not game:
            return
        game_id = game['id']

        if game_id in self._running_games:
            _exe, pid = self._running_games[game_id]
            if pid and pid > 0 and not is_process_alive(pid):
                self._running_games.pop(game_id, None)
                card = self._cards.get(exe_path)
                if card is not None:
                    try:
                        card.set_running(False)
                    except RuntimeError:
                        pass
            else:
                QMessageBox.information(
                    self, "Уже запущено",
                    f"'{game['title']}' уже запущено."
                )
                return

        self.db.increment_game_launch(game_id)
        try:
            self.launcher.launch(
                game_id=game_id,
                exe_path=game['exe_path'],
                working_dir=game.get('working_dir')
                or os.path.dirname(exe_path),
                arguments=game.get('arguments') or None,
            )
        except Exception as e:
            QMessageBox.critical(self, "Ошибка запуска",
                                 f"Не удалось запустить игру:\n{e}")
            return

        self.game_launched.emit(exe_path)

    def _on_game_started(self, game_id: int, pid: int):
        game = self.db.get_game_by_id(game_id)
        if not game:
            return
        exe_path = game['exe_path']
        self._running_games[game_id] = (exe_path, pid)
        card = self._cards.get(exe_path)
        if card is not None:
            try:
                card.set_running(True)
            except RuntimeError:
                pass
        self._refresh_counts()

    def _on_game_finished(self, game_id: int, seconds: int):
        entry = self._running_games.pop(game_id, None)
        if entry:
            exe_path, _pid = entry
            card = self._cards.get(exe_path)
            if card is not None:
                try:
                    card.set_running(False)
                except RuntimeError:
                    pass
        try:
            self.db.add_game_playtime(game_id, seconds)
        except Exception:
            pass
        self._refresh_counts()

    def _on_game_failed(self, game_id: int, err: str):
        entry = self._running_games.pop(game_id, None)
        if entry:
            exe_path, _pid = entry
            card = self._cards.get(exe_path)
            if card is not None:
                try:
                    card.set_running(False)
                except RuntimeError:
                    pass
        QMessageBox.warning(self, "Ошибка запуска",
                            f"Не удалось запустить игру:\n{err}")
        self._refresh_counts()

    def _reset_game_status(self, exe_path: str):
        game = self.db.get_game_by_path(exe_path)
        if not game:
            return
        game_id = game['id']
        entry = self._running_games.get(game_id)
        if not entry:
            return
        _exe, pid = entry
        if pid and pid > 0 and is_process_alive(pid):
            reply = QMessageBox.question(
                self, "Игра ещё работает",
                "Процесс игры всё ещё активен.\n"
                "Снять статус «запущено»?\n\n"
                "(Это не закроет игру, но позволит запустить её повторно.)",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        self._running_games.pop(game_id, None)
        card = self._cards.get(exe_path)
        if card is not None:
            try:
                card.set_running(False)
            except RuntimeError:
                pass
        self._refresh_counts()

    def _rescan_folder(self, exe_path: str):
        folder = os.path.dirname(exe_path)
        if not folder or not os.path.isdir(folder):
            return
        clear_folder_marker(folder)
        parent = os.path.dirname(folder)
        if parent and parent != folder:
            marker_parent = os.path.join(parent, FOLDER_MARKER_NAME)
            if os.path.isfile(marker_parent):
                try:
                    saved = read_folder_marker(parent)
                    if saved and os.path.normcase(
                            os.path.normpath(saved)
                    ) == os.path.normcase(os.path.normpath(exe_path)):
                        clear_folder_marker(parent)
                except Exception:
                    pass
        QMessageBox.information(
            self, "Маркер сброшен",
            "При следующем сканировании папка будет проверена заново."
        )

    # ---------- удаление с устройства ----------

    def _delete_game_from_device(self, exe_path: str):
        game = self.db.get_game_by_path(exe_path)
        if not game:
            return

        game_id = game['id']
        title = game.get('title', '')

        entry = self._running_games.get(game_id)
        if entry:
            _exe, pid = entry
            if pid and pid > 0 and is_process_alive(pid):
                QMessageBox.warning(
                    self, "Игра запущена",
                    "Нельзя удалить файлы запущенной игры.\n"
                    "Сначала закройте игру."
                )
                return

        game_folder = os.path.dirname(exe_path)
        folder_is_root = _same_path(game_folder, self.games_folder)

        other_games = []
        if not folder_is_root and game_folder:
            try:
                for g in self.db.get_all_games():
                    if g['id'] == game_id:
                        continue
                    other_exe = g.get('exe_path', '')
                    if not other_exe:
                        continue
                    other_folder = os.path.dirname(other_exe)
                    if _same_path(other_folder, game_folder):
                        other_games.append(g.get('title', other_exe))
            except Exception:
                pass

        archive_path = game.get('archive_path') or ''
        if not archive_path or not os.path.isfile(archive_path):
            found = find_archive_for_game(exe_path, self.games_folder)
            if found:
                archive_path = found

        dlg = _GameDeleteDialog(
            game_title=title,
            game_folder=game_folder,
            exe_path=exe_path,
            folder_is_root=folder_is_root,
            archive_path=archive_path,
            other_games=other_games,
            parent=self,
        )
        if dlg.exec_() != QDialog.Accepted:
            return

        opts = dlg.selected_options()
        errors = []
        deleted_folder = False
        deleted_exe = False
        deleted_archive = False
        deleted_db = False

        if opts['folder']:
            if folder_is_root:
                if os.path.isfile(exe_path):
                    try:
                        os.remove(exe_path)
                        deleted_exe = True
                    except Exception as e:
                        errors.append(f"Не удалось удалить .exe: {e}")
            else:
                if os.path.isdir(game_folder):
                    try:
                        shutil.rmtree(game_folder)
                        deleted_folder = True
                    except Exception as e:
                        errors.append(
                            f"Не удалось удалить папку игры: {e}"
                        )

        if opts['archive'] and archive_path and os.path.isfile(archive_path):
            try:
                os.remove(archive_path)
                deleted_archive = True
            except Exception as e:
                errors.append(f"Не удалось удалить архив: {e}")

        if opts['db']:
            try:
                self._running_games.pop(game_id, None)
                self.db.delete_game(game_id)
                deleted_db = True
            except Exception as e:
                errors.append(f"Не удалось удалить из библиотеки: {e}")

        if deleted_folder or deleted_exe:
            try:
                self._cover_cache.pop(exe_path, None)
                cpath = cover_cache.cover_path(exe_path, GAME_COVER_SIZE)
                if os.path.isfile(cpath):
                    os.remove(cpath)
            except Exception:
                pass

        summary = []
        if deleted_folder:
            summary.append("✅ Папка игры удалена")
        if deleted_exe:
            summary.append("✅ Файл .exe удалён")
        if deleted_archive:
            summary.append("✅ Архив удалён")
        if deleted_db:
            summary.append("✅ Запись удалена из библиотеки")

        if errors:
            msg = "\n".join(summary) if summary else ""
            if msg:
                msg += "\n\n"
            msg += "⚠️ Ошибки:\n" + "\n".join(errors[:8])
            QMessageBox.warning(self, "Частично выполнено", msg)
        else:
            msg = "\n".join(summary) if summary else "Нечего было удалять."
            QMessageBox.information(self, "Готово", msg)

        QTimer.singleShot(50, self.refresh)

    def _delete_archive_after_check(self, exe_path: str):
        game = self.db.get_game_by_path(exe_path)
        if not game:
            return

        candidates = []
        seen = set()

        def add_candidate(p):
            if not p or not os.path.isfile(p):
                return
            key = os.path.normcase(os.path.normpath(p))
            if key in seen:
                return
            seen.add(key)
            candidates.append(p)

        add_candidate(game.get('archive_path') or '')
        add_candidate(find_archive_for_game(exe_path, self.games_folder))
        for p in collect_extracted_chain(exe_path, self.games_folder):
            add_candidate(p)

        if not candidates:
            QMessageBox.information(
                self, "Архив не найден",
                "Для этой игры не удалось найти связанные .extracted-файлы.\n\n"
                "Возможно, они уже удалены или игра была добавлена из папки."
            )
            return

        total_size = 0
        for p in candidates:
            try:
                total_size += os.path.getsize(p)
            except OSError:
                pass

        names = [os.path.basename(p) for p in candidates]
        preview = "\n".join(f"• {n}" for n in names[:10])
        if len(names) > 10:
            preview += f"\n... и ещё {len(names) - 10}"

        reply = QMessageBox.question(
            self, "Удалить архивы?",
            f"Игра: {game['title']}\n"
            f"Найдено архивов: {len(candidates)}\n"
            f"Общий размер: {human_size(total_size)}\n\n"
            f"{preview}\n\n"
            "Вы уверены, что запускали игру и она работает?\n"
            "Удаление необратимо.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        deleted = 0
        errors = []
        for p in candidates:
            try:
                os.remove(p)
                deleted += 1
            except Exception as e:
                errors.append(f"{os.path.basename(p)}: {e}")

        try:
            self.db.clear_game_archive_path(game['id'])
        except Exception:
            pass

        msg = f"Удалено архивов: {deleted} из {len(candidates)}"
        if errors:
            msg += "\n\n⚠️ Ошибки:\n" + "\n".join(errors[:5])
        QMessageBox.information(self, "Готово", msg)

    def _refresh_counts(self):
        for exe_path, card in list(self._cards.items()):
            game = self.db.get_game_by_path(exe_path)
            if not game:
                continue
            try:
                card.game = game
                card.refresh_meta()
            except RuntimeError:
                pass

    # ---------- поиск и фильтры ----------

    def open_search(self):
        dialog = SearchFiltersDialog(
            db=self.db,
            library_key='games',
            current_search=self.current_search,
            current_filters=self.filters,
            parent=self,
        )
        dialog.search_applied.connect(self.apply_search)
        dialog.filters_changed.connect(self._on_filters_changed)
        dialog.exec_()

    def apply_search(self, params):
        self.current_search = dict(params or {})
        self.current_filter = self.current_search or None

        exclude = list(params.get('exclude_tags') or [])
        for t in self.hidden_tags:
            if t not in exclude:
                exclude.append(t)

        games = self.db.search_games(
            include_tags=params.get('include_tags'),
            exclude_tags=exclude if exclude else None,
            title_query=params.get('title') or None,
            author_query=params.get('author') or None,
            folder=self.games_folder,
        )
        self.load_games(games)
        self._update_clear_filter_button()

    def _on_filters_changed(self, filters: dict):
        self.filters = dict(filters)
        set_settings(
            'games',
            sort_by_views=self.filters.get('sort_by_views', False),
            group_by_series=self.filters.get('group_by_series', False),
            group_by_authors=self.filters.get('group_by_authors', False),
        )
        self._expanded_groups.clear()
        if self.current_filter:
            self.load_games()
        else:
            self.load_games(self._current_games or None)
        self._update_clear_filter_button()

    def _update_clear_filter_button(self):
        has_search = bool(self.current_search and any(
            self.current_search.get(k) for k in
            ('title', 'author', 'include_tags', 'exclude_tags')
        ))
        has_filters = (
            self.filters.get('sort_by_views')
            or self.filters.get('group_by_series')
            or self.filters.get('group_by_authors')
        )
        self.btn_clear_filter.setVisible(has_search or has_filters)

    def _clear_filter(self):
        self.current_search = {}
        self.current_filter = None
        self._expanded_groups.clear()

        self.filters = {
            'sort_by_views': False,
            'group_by_series': False,
            'group_by_authors': False,
        }
        set_settings('games', **self.filters)

        self.btn_clear_filter.setVisible(False)
        self.refresh()

    # ---------- действия ----------

    def add_game(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "Выберите исполняемый файл игры", self.games_folder,
            "Исполняемые файлы (*.exe *.bat *.cmd);;Все файлы (*.*)"
        )
        if not fp:
            return
        title = os.path.splitext(os.path.basename(fp))[0]
        working_dir = os.path.dirname(fp)
        game_id = self.db.add_game(title, fp, working_dir=working_dir)
        if game_id:
            self.refresh()
            QMessageBox.information(self, "Успех",
                                    f"Игра '{title}' добавлена")

    # ---------- сканирование ----------

    def scan_folder(self):
        if self._scan_worker is not None and self._scan_worker.isRunning():
            QMessageBox.information(self, "Сканирование",
                                    "Сканирование уже выполняется.")
            return

        if not os.path.exists(self.games_folder):
            QMessageBox.warning(self, "Ошибка",
                                f"Папка {self.games_folder} не существует")
            return

        if not self._tools_initialized:
            try:
                ensure_tools_configured()
            except Exception as e:
                print(f"[scan] ensure_tools_configured: {e}")
            self._tools_initialized = True

        try:
            existing_paths = {g['exe_path'] for g in self.db.get_all_games()}
        except Exception:
            existing_paths = set()

        self._progress_dialog = QProgressDialog(
            "Сканирование…", "Отменить", 0, 0, self
        )
        self._progress_dialog.setWindowTitle("Сканирование папки игр")
        self._progress_dialog.setWindowModality(Qt.WindowModal)
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.setMinimumWidth(420)
        self._progress_dialog.setAutoClose(False)
        self._progress_dialog.setAutoReset(False)
        self._progress_dialog.setStyleSheet("""
            QProgressDialog { background-color: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; }
            QProgressBar {
                background-color: #2a2a2a; color: #e0e0e0;
                border: 1px solid #3a3a3a; border-radius: 5px;
                text-align: center; height: 22px;
            }
            QProgressBar::chunk { background-color: #c0392b; border-radius: 4px; }
            QPushButton {
                background-color: #2a2a2a; color: #e0e0e0;
                border: none; border-radius: 5px; padding: 6px 14px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self._progress_dialog.canceled.connect(self._cancel_scan)

        passwords_path = passwords_path_near(self.db.db_path)

        self._scan_worker = ScanWorker(
            games_folder=self.games_folder,
            passwords_path=passwords_path,
            existing_paths=existing_paths,
            parent=self,
        )
        self._scan_worker.finished_ok.connect(self._on_scan_finished)
        self._scan_worker.finished.connect(self._on_scan_thread_done)
        self._scan_worker.start()

        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("⏳ Сканирование…")

    def _cancel_scan(self):
        if self._scan_worker is not None:
            self._scan_worker.stop()

    def _on_scan_finished(self, result):
        added = 0
        new_games = result.get('new_games', [])

        for item in new_games:
            if len(item) == 4:
                title, exe_path, working_dir, archive_path = item
            else:
                title, exe_path, working_dir = item
                archive_path = None
            try:
                gid = self.db.add_game(
                    title, exe_path, working_dir=working_dir,
                    archive_path=archive_path,
                )
                if gid:
                    added += 1
            except Exception as e:
                result.setdefault('errors', []).append(
                    f"add_game {os.path.basename(exe_path)}: {e}"
                )

        QTimer.singleShot(50, self.refresh)

        parts = []
        if result.get('extracted', 0) > 0:
            parts.append(f"📦 Распаковано архивов: {result['extracted']}")
        if result.get('found_in_folders', 0) > 0:
            parts.append(f"📂 Найдено игр в готовых папках: "
                         f"{result['found_in_folders']}")
        if result.get('skipped', 0) > 0:
            parts.append(f"⏭️ Пропущено (уже обработаны): "
                         f"{result['skipped']}")
        if result.get('archives_found', 0) == 0:
            parts.append("📦 Архивов в папке не найдено")
        if added > 0:
            parts.append(f"✅ Добавлено игр в библиотеку: {added}")

        tools = result.get('tools', {})
        tool_info = (
            f"\n\n🔧 Инструменты: "
            f"UnRAR={'✓' if tools.get('unrar') else '✗'}, "
            f"7-Zip={'✓' if tools.get('sevenzip') else '✗'}"
        )

        errors = result.get('errors', [])
        if errors:
            parts.append("\n⚠️ Ошибки:")
            parts.extend(errors[:10])
            if len(errors) > 10:
                parts.append(f"... и ещё {len(errors) - 10}")

        if not parts and not errors:
            return

        text = "\n".join(parts) + (tool_info if errors else "")
        QTimer.singleShot(120, lambda: QMessageBox.information(
            self, "Сканирование завершено", text
        ))

    def _on_scan_thread_done(self):
        if self._progress_dialog is not None:
            try:
                self._progress_dialog.close()
            except Exception:
                pass
            self._progress_dialog = None

        worker = self._scan_worker
        self._scan_worker = None
        if worker is not None:
            try:
                worker.deleteLater()
            except Exception:
                pass

        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("📁 Сканировать папку")

    # ---------- редактирование / удаление ----------

    def open_edit_dialog(self, exe_path):
        from game_info_window import GameInfoDialog
        game = self.db.get_game_by_path(exe_path)
        if not game:
            return
        dialog = GameInfoDialog(game, self.db, self)
        if dialog.exec_() == QDialog.Accepted:
            self._cover_cache.pop(exe_path, None)
            try:
                import cover_cache as cc
                p = cc.cover_path(exe_path, GAME_COVER_SIZE)
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
            self.refresh()

    def delete_game(self, exe_path):
        game = self.db.get_game_by_path(exe_path)
        if not game:
            return
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Удалить игру из библиотеки?\n\nФайл останется на диске.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.db.delete_game(game['id'])
            self._running_games.pop(game['id'], None)
            self.refresh()

    def closeEvent(self, event):
        try:
            self._cover_pool.clear()
        except Exception:
            pass
        try:
            if self._scan_worker is not None and self._scan_worker.isRunning():
                self._scan_worker.stop()
                self._scan_worker.wait(1500)
        except Exception:
            pass
        super().closeEvent(event)


# ============================================================
# Диалог удаления игры с устройства
# ============================================================

class _GameDeleteDialog(QDialog):
    """Диалог выбора, что именно удалять: папку игры, архив, запись в БД."""

    def __init__(self, game_title, game_folder, exe_path, folder_is_root,
                 archive_path, other_games, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Удалить игру с устройства")
        self.setFixedSize(620, 480)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; background: transparent; }
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
            QPushButton {
                background-color: #2a2a2a; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 8px 16px; font-size: 13px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)

        self._folder_is_root = folder_is_root

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel(
            f"Удалить <b>{self._escape(game_title)}</b> с устройства?"
        )
        title.setStyleSheet(
            "QLabel { color: #ffffff; font-size: 16px; font-weight: bold; }"
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        exe_exists = os.path.isfile(exe_path) if exe_path else False
        if not exe_exists and not os.path.isdir(game_folder):
            warn = QLabel(
                "⚠️ Файл .exe и папка игры не найдены на диске. "
                "Можно удалить только запись из библиотеки."
            )
            warn.setWordWrap(True)
            warn.setStyleSheet(
                "QLabel { color: #e67e22; font-size: 12px; padding: 8px;"
                " background-color: #2a1e0a; border-radius: 5px; }"
            )
            layout.addWidget(warn)

        if other_games:
            warn = QLabel(
                f"⚠️ В этой папке найдены другие игры ({len(other_games)}). "
                "Удаление папки затронет их тоже."
            )
            warn.setWordWrap(True)
            warn.setStyleSheet(
                "QLabel { color: #e67e22; font-size: 12px; padding: 8px;"
                " background-color: #2a1e0a; border-radius: 5px; }"
            )
            layout.addWidget(warn)
            preview_names = ", ".join(other_games[:5])
            if len(other_games) > 5:
                preview_names += f" и ещё {len(other_games) - 5}"
            preview = QLabel(f"Другие игры: {preview_names}")
            preview.setWordWrap(True)
            preview.setStyleSheet("QLabel { color: #888; font-size: 11px; }")
            layout.addWidget(preview)

        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #3a3a3a;")
        layout.addWidget(line)

        if folder_is_root:
            self.chk_folder = QCheckBox("🗑️ Удалить файл .exe")
            self.chk_folder.setEnabled(exe_exists)
        else:
            self.chk_folder = QCheckBox("🗑️ Удалить папку игры (рекурсивно)")
            self.chk_folder.setEnabled(os.path.isdir(game_folder))

        self.chk_folder.setChecked(
            not other_games and
            (os.path.isdir(game_folder) or exe_exists)
        )
        layout.addWidget(self.chk_folder)

        if game_folder:
            path_lbl = QLabel(f"    {game_folder}")
            path_lbl.setWordWrap(True)
            path_lbl.setStyleSheet(
                "QLabel { color: #888; font-size: 11px; padding-left: 26px; }"
            )
            layout.addWidget(path_lbl)

        has_archive = bool(archive_path) and os.path.isfile(archive_path)
        self.chk_archive = QCheckBox("📦 Удалить архив игры")
        self.chk_archive.setEnabled(has_archive)
        self.chk_archive.setChecked(
            has_archive and archive_path.lower().endswith('.extracted')
        )
        layout.addWidget(self.chk_archive)

        if archive_path:
            arc_lbl = QLabel(f"    {archive_path}")
            arc_lbl.setWordWrap(True)
            arc_lbl.setStyleSheet(
                "QLabel { color: #888; font-size: 11px; padding-left: 26px; }"
            )
            layout.addWidget(arc_lbl)

        self.chk_db = QCheckBox("🗂️ Удалить запись из библиотеки")
        self.chk_db.setChecked(True)
        layout.addWidget(self.chk_db)

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setFixedWidth(120)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_delete = QPushButton("🗑️ Удалить")
        self.btn_delete.setFixedWidth(140)
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 8px 16px; font-weight: bold; font-size: 13px;
            }
            QPushButton:hover { background-color: #e74c3c; }
            QPushButton:disabled {
                background-color: #3a3a3a; color: #666;
            }
        """)
        self.btn_delete.clicked.connect(self._on_delete_clicked)

        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_delete)
        layout.addLayout(buttons)

        self._update_delete_enabled()
        self.chk_folder.toggled.connect(self._update_delete_enabled)
        self.chk_archive.toggled.connect(self._update_delete_enabled)
        self.chk_db.toggled.connect(self._update_delete_enabled)

    @staticmethod
    def _escape(text: str) -> str:
        return (text or '').replace('<', '&lt;').replace('>', '&gt;')

    def _update_delete_enabled(self):
        any_selected = (
            self.chk_folder.isChecked()
            or self.chk_archive.isChecked()
            or self.chk_db.isChecked()
        )
        self.btn_delete.setEnabled(any_selected)

    def _on_delete_clicked(self):
        if not self.btn_delete.isEnabled():
            return
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Удаление необратимо. Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self.accept()

    def selected_options(self):
        return {
            'folder': self.chk_folder.isChecked(),
            'archive': self.chk_archive.isChecked(),
            'db': self.chk_db.isChecked(),
        }