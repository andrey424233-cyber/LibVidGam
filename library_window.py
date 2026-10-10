import os

from PIL import Image
from PyQt5.QtCore import (Qt, pyqtSignal, QTimer, QEvent,
                          QObject, QRunnable, QThreadPool, QSize)
from PyQt5.QtGui import QPixmap, QImage, QWheelEvent
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
                             QLabel, QPushButton, QDialog,
                             QMessageBox, QFileDialog)

import cover_cache
from archive_reader import ArchiveReader
from cover_render import apply_stack_effect
from database import Database
from group_card import GroupCard
from library_config import get_settings, set_settings
from search_filters_dialog import SearchFiltersDialog


LIBTAG_MIME = 'application/x-libtag'
BATCH_ROWS = 3
BATCH_INTERVAL_MS = 10
COVER_TARGET = (360, 480)


# ============================================================
# Фоновый загрузчик обложек комиксов
# ============================================================

class _CoverSignals(QObject):
    loaded = pyqtSignal(str, QPixmap)
    failed = pyqtSignal(str)


class ComicCoverLoader(QRunnable):
    def __init__(self, file_path, target_size):
        super().__init__()
        self.file_path = file_path
        self.target_size = target_size
        self.signals = _CoverSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            pixmap = self._load()
            if pixmap is not None and not pixmap.isNull():
                self.signals.loaded.emit(self.file_path, pixmap)
            else:
                self.signals.failed.emit(self.file_path)
        except Exception:
            self.signals.failed.emit(self.file_path)

    def _load(self):
        if not os.path.isfile(self.file_path):
            return None

        cached = cover_cache.load(self.file_path, self.target_size)
        if cached is not None and not cached.isNull():
            raw = QPixmap.fromImage(cached)
            return apply_stack_effect(raw)

        try:
            img = ArchiveReader.extract_page(self.file_path, 0)
        except Exception:
            return None

        img.thumbnail(self.target_size, Image.LANCZOS)
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        try:
            import io
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            qimg = QImage()
            qimg.loadFromData(buf.read())
            if not qimg.isNull():
                cover_cache.save(self.file_path, self.target_size, qimg)
        except Exception:
            pass

        try:
            import io
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            qimg = QImage()
            qimg.loadFromData(buf.read())
            if qimg.isNull():
                return None
            return apply_stack_effect(QPixmap.fromImage(qimg))
        except Exception:
            return None


# ============================================================
# Карточка комикса
# ============================================================

class ComicCard(QWidget):
    clicked = pyqtSignal(str)
    tag_assigned = pyqtSignal(str, str)

    DEFAULT_STYLE = """
        ComicCard {
            background-color: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 6px;
        }
    """
    DRAG_STYLE = """
        ComicCard {
            background-color: #2a1a1a;
            border: 2px solid #c0392b;
            border-radius: 6px;
        }
    """
    SUCCESS_STYLE = """
        ComicCard {
            background-color: #1a2a1a;
            border: 2px solid #27ae60;
            border-radius: 6px;
        }
    """

    def __init__(self, comic: dict, db: Database,
                 card_width: int, card_height: int, parent=None):
        super().__init__(parent)
        self.comic = comic
        self.db = db
        self.file_path = comic['file_path']
        self.card_width = card_width
        self.card_height = card_height

        self._stack_pixmap = None
        self._scaled_cache = None
        self._scaled_cache_size = (0, 0)
        self._tags = []

        self.setFixedSize(card_width, card_height)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setStyleSheet(self.DEFAULT_STYLE)

        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        cover_height = card_height - 44

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(card_width - 8, cover_height)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet(
            "QLabel { background: transparent; border: none; }"
        )
        layout.addWidget(self.cover_label)

        self.title_label = QLabel(comic['title'])
        self.title_label.setFixedSize(card_width - 8, 20)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("""
            QLabel { color: #ffffff; font-size: 11px; font-weight: bold;
                     background: transparent; border: none; }
        """)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        view_count = comic.get('view_count', 0) or 0
        self.views_label = QLabel(f"👁 {view_count}")
        self.views_label.setFixedSize(card_width - 8, 15)
        self.views_label.setAlignment(Qt.AlignCenter)
        self.views_label.setStyleSheet("""
            QLabel { color: #aaaaaa; font-size: 10px;
                     background: transparent; border: none; }
        """)
        layout.addWidget(self.views_label)

        self.setLayout(layout)
        self._update_tooltip()

    # ---------- обложка ----------

    def set_cover_pixmap(self, pixmap: QPixmap):
        if pixmap is None or pixmap.isNull():
            return
        self._stack_pixmap = pixmap
        self._scaled_cache = None
        self._scaled_cache_size = (0, 0)
        self._apply_cover()

    def _apply_cover(self):
        if self._stack_pixmap is None:
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
            except RuntimeError:
                pass
            return

        scaled = self._stack_pixmap.scaled(
            w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        if scaled.isNull():
            return
        self._scaled_cache = scaled
        self._scaled_cache_size = (w, h)
        try:
            self.cover_label.setPixmap(scaled)
        except RuntimeError:
            pass

    def resize_card(self, new_w: int, new_h: int):
        if new_w == self.card_width and new_h == self.card_height:
            return
        self.card_width = new_w
        self.card_height = new_h
        self.setFixedSize(new_w, new_h)

        cover_height = new_h - 44
        self.cover_label.setFixedSize(new_w - 8, cover_height)
        self.title_label.setFixedSize(new_w - 8, 20)
        self.views_label.setFixedSize(new_w - 8, 15)

        self._scaled_cache = None
        self._scaled_cache_size = (0, 0)
        self._apply_cover()

    # ---------- теги в тултипе ----------

    def set_tags(self, tags):
        self._tags = list(tags or [])
        self._update_tooltip()

    def _update_tooltip(self):
        views = self.comic.get('view_count', 0) or 0
        lines = [f"Просмотров: {views}"]
        if self._tags:
            lines.append("")
            lines.append("🏷️ Теги: " + ", ".join(self._tags))
        else:
            lines.append("")
            lines.append("🏷️ Теги не назначены")
        self.setToolTip("\n".join(lines))

    # ---------- drag&drop ----------

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(LIBTAG_MIME):
            event.acceptProposedAction()
            self.setStyleSheet(self.DRAG_STYLE)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(LIBTAG_MIME):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self.DEFAULT_STYLE)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.setStyleSheet(self.DEFAULT_STYLE)
        if not event.mimeData().hasFormat(LIBTAG_MIME):
            event.ignore()
            return
        try:
            tag_name = bytes(event.mimeData().data(LIBTAG_MIME)).decode('utf-8')
            tag_id = self.db.get_tag_id(tag_name)
            if tag_id is None:
                tag_id = self.db.add_tag(tag_name)
            self.db.assign_tag_to_comic(self.comic['id'], tag_id)
            event.acceptProposedAction()
            self._flash_success()
            self.tag_assigned.emit(self.file_path, tag_name)
            try:
                tags = self.db.get_comic_tags(self.comic['id'])
                self.set_tags(tags)
            except Exception:
                pass
        except Exception as e:
            print(f"Ошибка назначения тега: {e}")
            event.ignore()

    def _flash_success(self):
        self.setStyleSheet(self.SUCCESS_STYLE)
        QTimer.singleShot(400, lambda: self.setStyleSheet(self.DEFAULT_STYLE))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.file_path)
        elif event.button() == Qt.RightButton:
            self.show_context_menu(event)

    def show_context_menu(self, event):
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #1e1e1e; color: #e0e0e0;
                    border: 1px solid #3a3a3a; border-radius: 5px; padding: 5px; }
            QMenu::item:selected { background-color: #c0392b; }
        """)
        edit_action = menu.addAction("✏️ Редактировать")
        edit_action.triggered.connect(self.open_edit_dialog)
        delete_action = menu.addAction("🗑️ Удалить из библиотеки")
        delete_action.triggered.connect(self.delete_comic)
        menu.exec_(self.mapToGlobal(event.pos()))

    def _refresh_parent(self):
        parent = self.parent()
        while parent and not hasattr(parent, 'refresh'):
            parent = parent.parent()
        if parent:
            parent.refresh()

    def open_edit_dialog(self):
        from comic_info_window import ComicInfoDialog
        dialog = ComicInfoDialog(self.comic, self.db, self)
        if dialog.exec_() == QDialog.Accepted:
            self._refresh_parent()

    def delete_comic(self):
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Удалить комикс из библиотеки?\n\nФайл останется на диске.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.db.delete_comic(self.comic['id'])
                self._refresh_parent()
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось удалить: {e}")



class LibraryWindow(QWidget):
    comic_selected = pyqtSignal(str)

    BASE_CARD_WIDTH = 180
    BASE_CARD_HEIGHT = 280
    SPACING = 15
    ZOOM_MIN = 0.3
    ZOOM_MAX = 3.0
    ZOOM_STEP = 1.2

    def __init__(self, db: Database, comics_folder: str, parent=None):
        super().__init__(parent)
        self.db = db
        self.comics_folder = comics_folder
        self.current_filter = None
        self.current_search = {}
        self.zoom_level = 1.0
        self._current_comics = []
        self._current_display = []
        self._cards = {}
        self._has_been_loaded = False
        self.hidden_tags = []

        self.filters = get_settings('comics')
        self._expanded_groups = set()

        self._cover_cache = {}
        self._cover_waiters = {}
        self._cover_in_flight = set()

        self._cover_pool = QThreadPool(self)
        self._cover_pool.setMaxThreadCount(2)

        self._row_widgets = []
        self._current_cards_per_row = 0
        self._card_size = (0, 0)

        self._batch_timer = QTimer(self)
        self._batch_timer.setSingleShot(True)
        self._batch_timer.setInterval(BATCH_INTERVAL_MS)
        self._batch_timer.timeout.connect(self._create_next_batch)
        self._pending_rows = []
        self._batch_data = []
        self._batch_per_row = 5
        self._batch_card_w = 0
        self._batch_card_h = 0

        self._zoom_timer = QTimer()
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.setInterval(80)
        self._zoom_timer.timeout.connect(self._apply_pending_zoom)

        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(300)
        self._resize_timer.timeout.connect(self._on_resize)

        self._is_rebuilding = False
        self._pending_zoom_level = None

        self.setStyleSheet("QWidget { background-color: #121212; }")

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        actions_layout = QHBoxLayout()

        self.btn_add = QPushButton("+ Добавить")
        self.btn_add.setFixedSize(130, 40)
        self.btn_add.setStyleSheet("""
            QPushButton { background-color: #c0392b; color: white;
                          border: none; border-radius: 20px; font-size: 14px; }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_add.clicked.connect(self.add_comic)
        actions_layout.addWidget(self.btn_add)

        self.btn_scan = QPushButton("📁 Сканировать папку")
        self.btn_scan.setFixedSize(180, 40)
        self.btn_scan.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px; font-size: 14px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_scan.clicked.connect(self.scan_folder)
        actions_layout.addWidget(self.btn_scan)

        self.btn_clear_filter = QPushButton("✖ Сбросить фильтр")
        self.btn_clear_filter.setFixedSize(180, 40)
        self.btn_clear_filter.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px; font-size: 14px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_clear_filter.clicked.connect(self._clear_filter)
        self.btn_clear_filter.setVisible(False)
        actions_layout.addWidget(self.btn_clear_filter)

        actions_layout.addStretch()

        self.count_label = QLabel("0 комиксов")
        self.count_label.setStyleSheet("QLabel { color: #888; font-size: 14px; }")
        actions_layout.addWidget(self.count_label)
        layout.addLayout(actions_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background-color: #121212; }
        """)
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.setFocusPolicy(Qt.StrongFocus)

        self.content_widget = QWidget()
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(self.SPACING)
        self.content_widget.setLayout(self.main_layout)

        self.scroll_area.setWidget(self.content_widget)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)

    # ---------- зум ----------

    def eventFilter(self, obj, event):
        if obj is self.scroll_area.viewport() and event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                self._handle_zoom_wheel(event)
                return True
        return super().eventFilter(obj, event)

    def _handle_zoom_wheel(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        base = (self._pending_zoom_level
                if self._pending_zoom_level is not None
                else self.zoom_level)
        if delta > 0:
            new_zoom = min(self.ZOOM_MAX, base * self.ZOOM_STEP)
        else:
            new_zoom = max(self.ZOOM_MIN, base / self.ZOOM_STEP)
        if abs(new_zoom - self.zoom_level) < 0.005 and abs(new_zoom - base) < 0.005:
            return
        self._pending_zoom_level = new_zoom
        self._zoom_timer.start()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self._handle_zoom_wheel(event)
            event.accept()
        else:
            super().wheelEvent(event)

    # ---------- порционная сборка ----------

    def _cancel_batch(self):
        try:
            self._batch_timer.stop()
        except Exception:
            pass
        self._pending_rows = []
        self._batch_data = []

    # ---------- папка ----------

    def set_folder(self, folder: str):
        if folder == self.comics_folder:
            return
        self.comics_folder = folder
        if self._has_been_loaded:
            self._cancel_batch()
            self.load_comics()

    # ---------- скрытые теги ----------

    def set_hidden_tags(self, tags):
        new_tags = list(tags or [])
        if new_tags == self.hidden_tags:
            return
        self.hidden_tags = new_tags
        if self._has_been_loaded:
            self.refresh()

    # ---------- первая загрузка / refresh ----------

    def _initial_load(self):
        if not self._has_been_loaded:
            self._has_been_loaded = True
            self.load_comics()

    def refresh(self):
        self._cancel_batch()
        self._has_been_loaded = True
        self._cover_cache.clear()
        self.load_comics()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._is_rebuilding and self._has_been_loaded:
            self._resize_timer.start()

    def _on_resize(self):
        if self._is_rebuilding:
            return
        self._cancel_batch()
        self.load_comics(self._current_comics or None)

    def get_card_size(self):
        return (int(self.BASE_CARD_WIDTH * self.zoom_level),
                int(self.BASE_CARD_HEIGHT * self.zoom_level))

    def _calculate_cards_per_row(self, card_width):
        viewport_width = self.scroll_area.viewport().width() - 40
        return max(1, (viewport_width + self.SPACING)
                   // (card_width + self.SPACING))

    # ---------- обложки ----------

    def _request_cover(self, comic, card):
        file_path = comic['file_path']

        cached = self._cover_cache.get(file_path)
        if cached is not None and not cached.isNull():
            card.set_cover_pixmap(cached)
            return

        if file_path in self._cover_waiters:
            self._cover_waiters[file_path].append(card)
            return

        self._cover_waiters[file_path] = [card]
        self._cover_in_flight.add(file_path)

        loader = ComicCoverLoader(file_path, COVER_TARGET)
        loader.signals.loaded.connect(self._on_cover_loaded)
        loader.signals.failed.connect(self._on_cover_failed)
        self._cover_pool.start(loader)

    def _on_cover_loaded(self, file_path, pixmap):
        self._cover_in_flight.discard(file_path)
        if pixmap is not None and not pixmap.isNull():
            self._cover_cache[file_path] = pixmap
        waiters = self._cover_waiters.pop(file_path, [])
        for card in waiters:
            try:
                card.set_cover_pixmap(pixmap)
            except RuntimeError:
                pass

    def _on_cover_failed(self, file_path):
        self._cover_in_flight.discard(file_path)
        self._cover_waiters.pop(file_path, None)

    # ---------- построение сетки ----------

    def load_comics(self, comics=None):
        if self._is_rebuilding:
            return
        self._is_rebuilding = True

        self._cancel_batch()
        self._cover_waiters.clear()
        self._cards.clear()

        try:
            while self.main_layout.count():
                item = self.main_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
            self._row_widgets = []

            if comics is None:
                if self.hidden_tags:
                    comics = self.db.search_comics(
                        exclude_tags=self.hidden_tags,
                        folder=self.comics_folder
                    )
                else:
                    comics = self.db.get_comics_in_folder(self.comics_folder)

            self._current_comics = comics
            self.count_label.setText(f"{len(comics)} комиксов")

            self._current_display = self._build_display_structure(comics)

            card_width, card_height = self.get_card_size()
            self._card_size = (card_width, card_height)
            cards_per_row = self._calculate_cards_per_row(card_width)
            self._current_cards_per_row = cards_per_row

            self._batch_data = self._current_display
            self._batch_per_row = cards_per_row
            self._batch_card_w = card_width
            self._batch_card_h = card_height
            self._pending_rows = list(
                range(0, len(self._current_display), cards_per_row)
            )
        finally:
            self._is_rebuilding = False

        if self._pending_rows:
            self._batch_timer.start()
        else:
            self.main_layout.addStretch()

    def _build_display_structure(self, comics):
        result = []

        sort_by_views = self.filters.get('sort_by_views', False)
        group_series = self.filters.get('group_by_series', False)
        group_authors = self.filters.get('group_by_authors', False)

        if not group_series and not group_authors:
            items = list(comics)
            if sort_by_views:
                items.sort(key=lambda c: -(c.get('view_count', 0) or 0))
            for c in items:
                result.append({'kind': 'item', 'comic': c})
            return result

        def author_key(c):
            name = c.get('author_name')
            return name if name else None

        def series_key(c):
            sid = c.get('series_id')
            if sid:
                return (sid, c.get('series_name') or '')
            return None

        def sort_by_order(items):
            return sorted(
                items,
                key=lambda c: (
                    c.get('series_order') or 999999,
                    (c.get('title') or '').lower()
                )
            )

        if group_authors:
            top_groups = {}
            without_top = []

            for c in comics:
                a = author_key(c)
                if a:
                    top_groups.setdefault(a, []).append(c)
                else:
                    without_top.append(c)

            top_names = sorted(top_groups.keys())
            if sort_by_views:
                top_names.sort(
                    key=lambda n: -sum(
                        (c.get('view_count', 0) or 0)
                        for c in top_groups[n]
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
                        for c in items:
                            sk = series_key(c)
                            if sk:
                                series_groups.setdefault(sk, []).append(c)
                            else:
                                without_series.append(c)

                        s_keys = sorted(
                            series_groups.keys(), key=lambda k: k[1])
                        if sort_by_views:
                            s_keys.sort(
                                key=lambda k: -sum(
                                    (c.get('view_count', 0) or 0)
                                    for c in series_groups[k]
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
                                for c in s_items:
                                    result.append({
                                        'kind': 'item',
                                        'comic': c,
                                        'depth': 2,
                                    })

                        for c in sort_by_order(without_series):
                            result.append({
                                'kind': 'item',
                                'comic': c,
                                'depth': 2,
                            })
                    else:
                        for c in items:
                            result.append({
                                'kind': 'item',
                                'comic': c,
                                'depth': 1,
                            })

            for c in without_top:
                result.append({'kind': 'item', 'comic': c})

            return result

        if group_series:
            series_groups = {}
            without_series = []
            for c in comics:
                sk = series_key(c)
                if sk:
                    series_groups.setdefault(sk, []).append(c)
                else:
                    without_series.append(c)

            s_keys = sorted(series_groups.keys(), key=lambda k: k[1])
            if sort_by_views:
                s_keys.sort(
                    key=lambda k: -sum(
                        (c.get('view_count', 0) or 0)
                        for c in series_groups[k]
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
                    for c in s_items:
                        result.append({
                            'kind': 'item',
                            'comic': c,
                            'depth': 1,
                        })

            for c in without_series:
                result.append({'kind': 'item', 'comic': c})

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
            row_layout = QHBoxLayout()
            row_layout.setSpacing(self.SPACING)
            row_layout.setContentsMargins(0, 0, 0, 0)
            for elem in chunk:
                widget = self._make_widget_for_element(elem, card_w, card_h)
                if widget is not None:
                    row_layout.addWidget(widget)
            row_layout.addStretch()
            row_widget = QWidget()
            row_widget.setLayout(row_layout)
            self.main_layout.addWidget(row_widget)
            self._row_widgets.append(row_widget)

        if self._pending_rows:
            self._batch_timer.start()

    def _make_widget_for_element(self, elem, card_w, card_h):
        kind = elem.get('kind')

        if kind == 'group':
            pixmaps = []
            for c in elem['items'][:4]:
                p = self._cover_cache.get(c['file_path'])
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
            comic = elem['comic']
            card = ComicCard(comic, self.db, card_w, card_h)
            card.clicked.connect(self.comic_selected.emit)
            self._cards[comic['file_path']] = card
            self._request_cover(comic, card)
            try:
                tags = self.db.get_comic_tags(comic['id'])
                card.set_tags(tags)
            except Exception as e:
                print(f"[library] load tags: {e}")
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
        for comic in needed:
            fp = comic['file_path']
            if fp in self._cover_cache:
                continue
            pending.append(comic)

        def _refresh():
            pixmaps = []
            for c in needed:
                p = self._cover_cache.get(c['file_path'])
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
        for comic in pending:
            fp = comic['file_path']
            if fp in self._cover_in_flight:
                continue
            remaining[0] += 1
            self._cover_in_flight.add(fp)
            loader = ComicCoverLoader(fp, COVER_TARGET)

            def _on_loaded(file_path, pixmap):
                self._cover_in_flight.discard(file_path)
                if pixmap is not None and not pixmap.isNull():
                    self._cover_cache[file_path] = pixmap
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
        self.load_comics(self._current_comics or None)

    # ---------- обновление метаданных карточки ----------

    def update_card_meta(self, file_path):
        """Обновляет метаданные карточки (просмотры + теги) без пересборки.

        Используется после закрытия читалки, чтобы не сбрасывать скролл.
        """
        card = self._cards.get(file_path)
        if card is None:
            return
        try:
            comic = self.db.get_comic_by_path(file_path)
            if not comic:
                return
            card.comic = comic
            views = comic.get('view_count', 0) or 0
            card.views_label.setText(f"👁 {views}")
            try:
                tags = self.db.get_comic_tags(comic['id'])
                card.set_tags(tags)
            except Exception:
                pass
        except Exception as e:
            print(f"[library] update_card_meta: {e}")

    # ---------- зум ----------

    def _apply_pending_zoom(self):
        if self._pending_zoom_level is not None:
            self.zoom_level = self._pending_zoom_level
            self._pending_zoom_level = None
            self._resize_timer.stop()
            self._relayout_for_zoom()

    def _zoom(self, new_zoom):
        if abs(new_zoom - self.zoom_level) <= 0.005:
            return
        self.zoom_level = new_zoom
        self._resize_timer.stop()
        self._relayout_for_zoom()

    def _relayout_for_zoom(self):
        if self._pending_rows:
            self._cancel_batch()
            self._cover_waiters.clear()
            self.load_comics(self._current_comics or None)
            return

        card_width, card_height = self.get_card_size()
        new_cards_per_row = self._calculate_cards_per_row(card_width)

        if new_cards_per_row != self._current_cards_per_row:
            self._cover_waiters.clear()
            self.load_comics(self._current_comics or None)
            return

        self._card_size = (card_width, card_height)
        for row_widget in self._row_widgets:
            layout = row_widget.layout()
            if layout is None:
                continue
            for i in range(layout.count()):
                item = layout.itemAt(i)
                w = item.widget() if item is not None else None
                if isinstance(w, (ComicCard, GroupCard)):
                    w.resize_card(card_width, card_height)

    def zoom_in(self):
        self._zoom(min(self.ZOOM_MAX, self.zoom_level * self.ZOOM_STEP))

    def zoom_out(self):
        self._zoom(max(self.ZOOM_MIN, self.zoom_level / self.ZOOM_STEP))

    def zoom_reset(self):
        self._zoom(1.0)

    # ---------- поиск и фильтры ----------

    def open_search(self):
        dialog = SearchFiltersDialog(
            db=self.db,
            library_key='comics',
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
        comics = self.db.search_comics(
            include_tags=params.get('include_tags'),
            exclude_tags=params.get('exclude_tags'),
            title_query=params.get('title'),
            author_query=params.get('author'),
            folder=self.comics_folder,
        )
        self.load_comics(comics)
        self._update_clear_filter_button()

    def _on_filters_changed(self, filters: dict):
        self.filters = dict(filters)
        set_settings(
            'comics',
            sort_by_views=self.filters.get('sort_by_views', False),
            group_by_series=self.filters.get('group_by_series', False),
            group_by_authors=self.filters.get('group_by_authors', False),
        )
        self._expanded_groups.clear()
        if self.current_filter:
            self.load_comics()
        else:
            self.load_comics(self._current_comics or None)
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
        set_settings('comics', **self.filters)

        self.btn_clear_filter.setVisible(False)
        self.refresh()

    # ---------- добавление / сканирование ----------

    def add_comic(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите комикс", self.comics_folder,
            "Архивы (*.zip *.rar *.cbz *.cbr);;Все файлы (*.*)"
        )
        if not file_path:
            return
        if not ArchiveReader.is_supported(file_path):
            QMessageBox.warning(self, "Ошибка", "Неподдерживаемый формат файла")
            return
        title = os.path.splitext(os.path.basename(file_path))[0]
        page_count = ArchiveReader.get_page_count(file_path)
        comic_id = self.db.add_comic(title, file_path, page_count)
        if comic_id:
            self.refresh()
            QMessageBox.information(self, "Успех", f"Комикс '{title}' добавлен")

    def scan_folder(self):
        if not os.path.exists(self.comics_folder):
            QMessageBox.warning(self, "Ошибка",
                                f"Папка {self.comics_folder} не существует")
            return

        removed_count = self.db.cleanup_missing_comics()
        added = 0
        existing_paths = {c['file_path'] for c in self.db.get_all_comics()}

        for root, _dirs, files in os.walk(self.comics_folder):
            for file in files:
                if not ArchiveReader.is_supported(file):
                    continue
                file_path = os.path.join(root, file)
                if file_path in existing_paths:
                    continue
                title = os.path.splitext(file)[0]
                page_count = ArchiveReader.get_page_count(file_path)
                if self.db.add_comic(title, file_path, page_count):
                    added += 1
                    existing_paths.add(file_path)

        self.refresh()

        parts = []
        if added > 0:
            parts.append(f"✅ Добавлено новых: {added}")
        if removed_count > 0:
            parts.append(f"🗑️ Удалено отсутствующих: {removed_count}")
        QMessageBox.information(
            self, "Сканирование завершено",
            "\n".join(parts) if parts else "Изменений не обнаружено."
        )

    def closeEvent(self, event):
        try:
            self._cover_pool.clear()
        except Exception:
            pass
        super().closeEvent(event)