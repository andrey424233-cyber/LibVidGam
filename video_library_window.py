import os

from PyQt5.QtCore import (Qt, pyqtSignal, QTimer, QObject, QRunnable,
                          QThreadPool)
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
                             QLabel, QPushButton, QDialog, QLineEdit,
                             QMenu, QMessageBox, QFileDialog)

import cover_cache
from cover_render import render_cover
from video_reader import (is_supported, get_duration, extract_thumbnail,
                          format_duration)
from database import Database
from group_card import GroupCard
from library_config import get_settings, set_settings
from search_filters_dialog import SearchFiltersDialog


VIDEO_COVER_SIZE = (480, 270)
LIBTAG_MIME = 'application/x-libtag'
BATCH_ROWS = 3
BATCH_INTERVAL_MS = 10


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


# ============================================================
# Фоновый загрузчик превью
# ============================================================

class ThumbSignals(QObject):
    loaded = pyqtSignal(str, QImage)
    failed = pyqtSignal(str)


class ThumbLoader(QRunnable):
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.signals = ThumbSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            img = extract_thumbnail(self.file_path, VIDEO_COVER_SIZE)
            if img is not None and not img.isNull():
                self.signals.loaded.emit(self.file_path, img)
            else:
                self.signals.failed.emit(self.file_path)
        except Exception:
            self.signals.failed.emit(self.file_path)


# ============================================================
# Карточка видео
# ============================================================

class VideoCard(QWidget):
    clicked = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    delete_file_requested = pyqtSignal(str)
    tag_assigned = pyqtSignal(str, str)

    DEFAULT_STYLE = """
        VideoCard {
            background-color: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 6px;
        }
    """
    DRAG_STYLE = """
        VideoCard {
            background-color: #2a1a1a;
            border: 2px solid #c0392b;
            border-radius: 6px;
        }
    """
    SUCCESS_STYLE = """
        VideoCard {
            background-color: #1a2a1a;
            border: 2px solid #27ae60;
            border-radius: 6px;
        }
    """

    def __init__(self, video, db, card_width=300, card_height=230, parent=None):
        super().__init__(parent)
        self.video = video
        self.db = db
        self.file_path = video['file_path']
        self.card_width = card_width
        self.card_height = card_height

        self._qimage = None
        self._scaled_cache = None
        self._scaled_cache_size = (0, 0)
        self._tags = []

        self.setFixedSize(card_width, card_height)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setStyleSheet(self.DEFAULT_STYLE)

        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        thumb_h = card_height - 42

        self.thumb_label = QLabel("🎬")
        self.thumb_label.setFixedSize(card_width - 8, thumb_h)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("""
            QLabel { color: #555; font-size: 42px;
                     background: #0d0d0d; border-radius: 4px; }
        """)
        layout.addWidget(self.thumb_label)

        self.title_label = QLabel(video['title'])
        self.title_label.setFixedSize(card_width - 8, 16)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(
            "QLabel { color: #fff; font-size: 12px; font-weight: bold;"
            " background: transparent; border: none; }"
        )
        self.title_label.setWordWrap(False)
        layout.addWidget(self.title_label)

        dur = format_duration(video.get('duration', 0) or 0)
        watches = video.get('watch_count', 0) or 0
        self.meta_label = QLabel(f"{dur}    ▶  {watches}")
        self.meta_label.setFixedSize(card_width - 8, 14)
        self.meta_label.setAlignment(Qt.AlignCenter)
        self.meta_label.setStyleSheet(
            "QLabel { color: #999; font-size: 11px;"
            " background: transparent; border: none; }"
        )
        layout.addWidget(self.meta_label)

        self.setLayout(layout)
        self._update_tooltip()

    # ---------- превью ----------

    def set_thumbnail(self, qimage):
        if qimage is None or qimage.isNull():
            return
        self._qimage = qimage
        self._scaled_cache = None
        self._scaled_cache_size = (0, 0)
        self._apply_thumbnail()

    def _apply_thumbnail(self):
        if self._qimage is None:
            return
        try:
            w = self.thumb_label.width()
            h = self.thumb_label.height()
        except RuntimeError:
            return
        if w <= 0 or h <= 0:
            return

        if (self._scaled_cache is not None
                and self._scaled_cache_size == (w, h)
                and not self._scaled_cache.isNull()):
            try:
                self.thumb_label.setPixmap(self._scaled_cache)
                self.thumb_label.setText("")
            except RuntimeError:
                pass
            return

        pix = render_cover(self._qimage, w, h)
        if pix.isNull():
            return
        self._scaled_cache = pix
        self._scaled_cache_size = (w, h)
        try:
            self.thumb_label.setPixmap(pix)
            self.thumb_label.setText("")
        except RuntimeError:
            pass

    # ---------- теги в тултипе ----------

    def set_tags(self, tags):
        """Устанавливает список тегов. Показывается в тултипе карточки."""
        self._tags = list(tags or [])
        self._update_tooltip()

    def _update_tooltip(self):
        dur = format_duration(self.video.get('duration', 0) or 0)
        watches = self.video.get('watch_count', 0) or 0
        lines = [
            f"Длительность: {dur}",
            f"Просмотров: {watches}",
        ]
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
            self.db.assign_tag_to_video(self.video['id'], tag_id)
            event.acceptProposedAction()
            self._flash_success()
            self.tag_assigned.emit(self.file_path, tag_name)
            # Обновляем тултип после назначения тега
            try:
                tags = self.db.get_video_tags(self.video['id'])
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
            self._show_menu(event)

    def _show_menu(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #1e1e1e; color: #e0e0e0;
                    border: 1px solid #3a3a3a; border-radius: 5px; padding: 5px; }
            QMenu::item:selected { background-color: #c0392b; }
        """)
        action_play = menu.addAction("▶ Воспроизвести")
        action_edit = menu.addAction("✏️ Редактировать")
        menu.addSeparator()
        action_del_lib = menu.addAction("🗑️ Удалить из библиотеки")
        action_del_dev = menu.addAction("🗑️ Удалить с устройства")

        chosen = menu.exec_(self.mapToGlobal(event.pos()))

        if chosen == action_play:
            QTimer.singleShot(0, lambda: self.clicked.emit(self.file_path))
        elif chosen == action_edit:
            QTimer.singleShot(0, lambda: self.edit_requested.emit(self.file_path))
        elif chosen == action_del_lib:
            QTimer.singleShot(0, lambda: self.delete_requested.emit(self.file_path))
        elif chosen == action_del_dev:
            QTimer.singleShot(0, lambda: self.delete_file_requested.emit(self.file_path))


# ============================================================
# Окно библиотеки
# ============================================================

class VideoLibraryWindow(QWidget):
    video_selected = pyqtSignal(str)

    BASE_CARD_WIDTH = 300
    BASE_CARD_HEIGHT = 230
    SPACING = 15

    def __init__(self, db: Database, videos_folder: str, parent=None):
        super().__init__(parent)
        self.db = db
        self.videos_folder = videos_folder
        self._current_videos = []
        self._current_display = []
        self._cards = {}
        self._thumb_cache = {}
        self._pending = set()
        self._waiters = {}
        self._has_been_loaded = False
        self.hidden_tags = []
        self.current_filter = None
        self.current_search = {}

        self.filters = get_settings('videos')
        self._expanded_groups = set()

        self._thumb_pool = QThreadPool(self)
        self._thumb_pool.setMaxThreadCount(2)

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

        self.setStyleSheet("QWidget { background-color: #121212; }")

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        top = QHBoxLayout()

        self.btn_add = QPushButton("+ Добавить видео")
        self.btn_add.setFixedSize(170, 40)
        self.btn_add.setStyleSheet("""
            QPushButton { background-color: #c0392b; color: white;
                          border: none; border-radius: 20px; font-size: 14px; }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_add.clicked.connect(self.add_video)
        top.addWidget(self.btn_add)

        self.btn_scan = QPushButton("📁 Сканировать папку")
        self.btn_scan.setFixedSize(180, 40)
        self.btn_scan.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px; font-size: 14px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_scan.clicked.connect(self.scan_folder)
        top.addWidget(self.btn_scan)

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

        self.count_label = QLabel("0 видео")
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
        if folder == self.videos_folder:
            return
        self.videos_folder = folder
        if self._has_been_loaded:
            self._cancel_batch()
            self.load_videos()

    def get_playlist(self):
        try:
            return [v['file_path'] for v in self._current_videos]
        except Exception:
            return []

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
            self.load_videos()

    def refresh(self):
        self._cancel_batch()
        self._has_been_loaded = True
        self._thumb_cache.clear()
        self.load_videos()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._is_rebuilding and self._has_been_loaded:
            self._resize_timer.start()

    def _on_resize(self):
        if self._is_rebuilding:
            return
        self._cancel_batch()
        self.load_videos(self._current_videos or None)

    def _calculate_cards_per_row(self, card_width):
        vw = self.scroll_area.viewport().width() - 40
        return max(1, (vw + self.SPACING) // (card_width + self.SPACING))

    # ---------- построение ----------

    def load_videos(self, videos=None):
        if self._is_rebuilding:
            return
        self._is_rebuilding = True

        self._cancel_batch()
        self._waiters.clear()
        self._cards.clear()

        try:
            while self.main_layout.count():
                item = self.main_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()

            if videos is None:
                if self.hidden_tags:
                    videos = self.db.search_videos(
                        exclude_tags=self.hidden_tags,
                        folder=self.videos_folder
                    )
                else:
                    videos = self.db.get_videos_in_folder(self.videos_folder)

            self._current_videos = videos
            self.count_label.setText(f"{len(videos)} видео")

            self._current_display = self._build_display_structure(videos)

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

    def _build_display_structure(self, videos):
        result = []
        sort_by_views = self.filters.get('sort_by_views', False)
        group_series = self.filters.get('group_by_series', False)
        group_authors = self.filters.get('group_by_authors', False)

        if not group_series and not group_authors:
            items = list(videos)
            if sort_by_views:
                items.sort(key=lambda v: -(v.get('watch_count', 0) or 0))
            for v in items:
                result.append({'kind': 'item', 'video': v})
            return result

        def author_key(v):
            name = v.get('author_name')
            return name if name else None

        def series_key(v):
            sid = v.get('series_id')
            if sid:
                return (sid, v.get('series_name') or '')
            return None

        def sort_by_order(items):
            return sorted(
                items,
                key=lambda v: (
                    v.get('series_order') or 999999,
                    (v.get('title') or '').lower()
                )
            )

        if group_authors:
            top_groups = {}
            without_top = []
            for v in videos:
                a = author_key(v)
                if a:
                    top_groups.setdefault(a, []).append(v)
                else:
                    without_top.append(v)

            top_names = sorted(top_groups.keys())
            if sort_by_views:
                top_names.sort(
                    key=lambda n: -sum(
                        (v.get('watch_count', 0) or 0)
                        for v in top_groups[n]
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
                        for v in items:
                            sk = series_key(v)
                            if sk:
                                series_groups.setdefault(sk, []).append(v)
                            else:
                                without_series.append(v)

                        s_keys = sorted(
                            series_groups.keys(), key=lambda k: k[1])
                        if sort_by_views:
                            s_keys.sort(
                                key=lambda k: -sum(
                                    (v.get('watch_count', 0) or 0)
                                    for v in series_groups[k]
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
                                for v in s_items:
                                    result.append({
                                        'kind': 'item',
                                        'video': v,
                                        'depth': 2,
                                    })

                        for v in sort_by_order(without_series):
                            result.append({
                                'kind': 'item',
                                'video': v,
                                'depth': 2,
                            })
                    else:
                        for v in items:
                            result.append({
                                'kind': 'item',
                                'video': v,
                                'depth': 1,
                            })

            for v in without_top:
                result.append({'kind': 'item', 'video': v})

            return result

        if group_series:
            series_groups = {}
            without_series = []
            for v in videos:
                sk = series_key(v)
                if sk:
                    series_groups.setdefault(sk, []).append(v)
                else:
                    without_series.append(v)

            s_keys = sorted(series_groups.keys(), key=lambda k: k[1])
            if sort_by_views:
                s_keys.sort(
                    key=lambda k: -sum(
                        (v.get('watch_count', 0) or 0)
                        for v in series_groups[k]
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
                    for v in s_items:
                        result.append({
                            'kind': 'item',
                            'video': v,
                            'depth': 1,
                        })

            for v in without_series:
                result.append({'kind': 'item', 'video': v})

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
            for v in elem['items'][:4]:
                p = self._thumb_cache.get(v['file_path'])
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
                lambda e=elem, cc=card: self._request_group_thumbs(e, cc)
            )
            return card

        if kind == 'item':
            video = elem['video']
            card = VideoCard(video, self.db, card_w, card_h)
            card.clicked.connect(self.video_selected.emit)
            card.edit_requested.connect(self.open_edit_dialog)
            card.delete_requested.connect(self.delete_video)
            card.delete_file_requested.connect(self.delete_video_file)
            row_parent = None
            self._cards[video['file_path']] = card
            self._request_thumbnail(video, card)
            try:
                tags = self.db.get_video_tags(video['id'])
                card.set_tags(tags)
            except Exception as e:
                print(f"[video_library] load tags: {e}")
            return card

        return None

    def _request_group_thumbs(self, elem, card):
        try:
            needed = elem['items'][:4]
        except Exception:
            return
        if not needed:
            return

        pending = []
        for video in needed:
            fp = video['file_path']
            if fp in self._thumb_cache:
                continue
            pending.append(video)

        def _refresh():
            pixmaps = []
            for v in needed:
                p = self._thumb_cache.get(v['file_path'])
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
        for video in pending:
            fp = video['file_path']
            if fp in self._pending:
                continue
            remaining[0] += 1
            self._pending.add(fp)

            loader = ThumbLoader(fp)

            def _on_loaded(file_path, qimage):
                self._pending.discard(file_path)
                if qimage is not None and not qimage.isNull():
                    self._thumb_cache[file_path] = qimage
                remaining[0] -= 1
                if remaining[0] <= 0:
                    QTimer.singleShot(0, _refresh)

            def _on_failed(file_path):
                self._pending.discard(file_path)
                remaining[0] -= 1
                if remaining[0] <= 0:
                    QTimer.singleShot(0, _refresh)

            loader.signals.loaded.connect(_on_loaded)
            loader.signals.failed.connect(_on_failed)
            self._thumb_pool.start(loader)

        if remaining[0] <= 0:
            _refresh()

    def _toggle_group(self, key):
        if self._is_rebuilding:
            return
        if key in self._expanded_groups:
            self._expanded_groups.discard(key)
        else:
            self._expanded_groups.add(key)
        self.load_videos(self._current_videos or None)

    # ---------- обновление метаданных карточки ----------

    def update_card_meta(self, file_path):
        """Обновляет метаданные карточки (просмотры + теги) без пересборки.

        Используется после закрытия плеера, чтобы не сбрасывать скролл.
        """
        card = self._cards.get(file_path)
        if card is None:
            return
        try:
            video = self.db.get_video_by_path(file_path)
            if not video:
                return
            card.video = video
            dur = format_duration(video.get('duration', 0) or 0)
            watches = video.get('watch_count', 0) or 0
            card.meta_label.setText(f"{dur}    ▶  {watches}")
            try:
                tags = self.db.get_video_tags(video['id'])
                card.set_tags(tags)
            except Exception:
                pass
        except Exception as e:
            print(f"[video_library] update_card_meta: {e}")

    # ---------- превью ----------

    def _request_thumbnail(self, video, card):
        fp = video['file_path']

        if fp in self._thumb_cache:
            card.set_thumbnail(self._thumb_cache[fp])
            return

        disk = cover_cache.load(fp, VIDEO_COVER_SIZE)
        if disk is not None and not disk.isNull():
            self._thumb_cache[fp] = disk
            card.set_thumbnail(disk)
            return

        if fp in self._pending:
            self._waiters.setdefault(fp, []).append(card)
            return
        self._pending.add(fp)
        self._waiters[fp] = [card]

        loader = ThumbLoader(fp)
        loader.signals.loaded.connect(self._on_thumb_loaded)
        loader.signals.failed.connect(self._on_thumb_failed)
        self._thumb_pool.start(loader)

    def _on_thumb_loaded(self, fp, qimage):
        self._pending.discard(fp)
        waiters = self._waiters.pop(fp, [])
        if qimage is None or qimage.isNull():
            return
        self._thumb_cache[fp] = qimage
        try:
            cover_cache.save(fp, VIDEO_COVER_SIZE, qimage)
        except Exception:
            pass
        for c in waiters:
            try:
                c.set_thumbnail(qimage)
            except RuntimeError:
                pass

    def _on_thumb_failed(self, fp):
        self._pending.discard(fp)
        self._waiters.pop(fp, None)

    # ---------- поиск и фильтры ----------

    def open_search(self):
        dialog = SearchFiltersDialog(
            db=self.db,
            library_key='videos',
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

        videos = self.db.search_videos(
            include_tags=params.get('include_tags'),
            exclude_tags=exclude if exclude else None,
            title_query=params.get('title') or None,
            author_query=params.get('author') or None,
            folder=self.videos_folder,
        )
        self.load_videos(videos)
        self._update_clear_filter_button()

    def _on_filters_changed(self, filters: dict):
        self.filters = dict(filters)
        set_settings(
            'videos',
            sort_by_views=self.filters.get('sort_by_views', False),
            group_by_series=self.filters.get('group_by_series', False),
            group_by_authors=self.filters.get('group_by_authors', False),
        )
        self._expanded_groups.clear()
        if self.current_filter:
            self.load_videos()
        else:
            self.load_videos(self._current_videos or None)
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
        set_settings('videos', **self.filters)

        self.btn_clear_filter.setVisible(False)
        self.refresh()

    # ---------- действия ----------

    def add_video(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "Выберите видео", self.videos_folder,
            "Видео (*.mp4 *.mkv *.avi *.mov *.webm *.m4v);;Все файлы (*.*)"
        )
        if not fp:
            return
        if not is_supported(fp):
            QMessageBox.warning(self, "Ошибка", "Неподдерживаемый формат файла")
            return
        title = os.path.splitext(os.path.basename(fp))[0]
        duration = get_duration(fp)
        vid = self.db.add_video(title, fp, duration)
        if vid:
            self.refresh()
            QMessageBox.information(self, "Успех", f"Видео '{title}' добавлено")

    def scan_folder(self):
        if not os.path.exists(self.videos_folder):
            QMessageBox.warning(self, "Ошибка",
                                f"Папка {self.videos_folder} не существует")
            return

        removed = self.db.cleanup_missing_videos()
        added = 0
        existing = {v['file_path'] for v in self.db.get_all_videos()}

        for root, _dirs, files in os.walk(self.videos_folder):
            for f in files:
                if not is_supported(f):
                    continue
                fp = os.path.join(root, f)
                if fp in existing:
                    continue
                title = os.path.splitext(f)[0]
                duration = get_duration(fp)
                if self.db.add_video(title, fp, duration):
                    added += 1
                    existing.add(fp)

        self.refresh()

        parts = []
        if added > 0:
            parts.append(f"✅ Добавлено: {added}")
        if removed > 0:
            parts.append(f"🗑️ Удалено отсутствующих: {removed}")
        QMessageBox.information(
            self, "Сканирование завершено",
            "\n".join(parts) if parts else "Изменений не обнаружено."
        )

    def open_edit_dialog(self, file_path):
        from video_info_window import VideoInfoDialog
        video = self.db.get_video_by_path(file_path)
        if not video:
            return
        dialog = VideoInfoDialog(video, self.db, self)
        if dialog.exec_() == QDialog.Accepted:
            self.refresh()

    def delete_video(self, file_path):
        video = self.db.get_video_by_path(file_path)
        if not video:
            return
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Удалить видео из библиотеки?\n\nФайл останется на диске.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.db.delete_video(video['id'])
            self.refresh()

    def delete_video_file(self, file_path):
        try:
            video = self.db.get_video_by_path(file_path)
            if not video:
                return

            exists = os.path.isfile(file_path)
            size_str = ""
            if exists:
                try:
                    size_str = f" ({human_size(os.path.getsize(file_path))})"
                except OSError:
                    pass

            file_name = os.path.basename(file_path)

            if exists:
                msg = (
                    f"Удалить файл с устройства?\n\n"
                    f"Файл: {file_name}{size_str}\n"
                    f"Путь: {file_path}\n\n"
                    "Файл будет удалён безвозвратно.\n"
                    "Продолжить?"
                )
            else:
                msg = (
                    f"Файл не найден на диске:\n{file_path}\n\n"
                    "Удалить только запись из библиотеки?"
                )

            reply = QMessageBox.question(
                self, "Удалить с устройства", msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

            if exists:
                try:
                    os.remove(file_path)
                except Exception as e:
                    QMessageBox.critical(
                        self, "Ошибка удаления",
                        f"Не удалось удалить файл:\n{e}"
                    )
                    return

            try:
                cpath = cover_cache.cover_path(file_path, VIDEO_COVER_SIZE)
                if os.path.isfile(cpath):
                    os.remove(cpath)
            except Exception:
                pass

            self._thumb_cache.pop(file_path, None)
            self._pending.discard(file_path)
            self._waiters.pop(file_path, None)
            self._cards.pop(file_path, None)

            try:
                self.db.delete_video(video['id'])
            except Exception as e:
                QMessageBox.warning(
                    self, "Ошибка БД",
                    f"Файл удалён, но не удалось удалить запись из БД:\n{e}"
                )

            QTimer.singleShot(50, self.refresh)
        except Exception as e:
            print(f"[delete_video_file] {e}")

    def closeEvent(self, event):
        try:
            self._thumb_pool.clear()
        except Exception:
            pass
        super().closeEvent(event)