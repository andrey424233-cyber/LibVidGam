"""Главная страница: топовые работы из трёх библиотек."""
import io
import os

from PIL import Image

from PyQt5.QtCore import (Qt, QAbstractListModel, QModelIndex, QObject,
                          QRunnable, QSize, QThreadPool, QTimer, pyqtSignal)
from PyQt5.QtGui import (QColor, QFont, QImage, QPainter, QPen)
from PyQt5.QtWidgets import (QAbstractItemView, QLabel, QListView,
                             QScrollArea, QStyle, QStyledItemDelegate,
                             QVBoxLayout, QWidget)

import cover_cache
from archive_reader import ArchiveReader
from cover_render import render_cover
from exe_icon import extract_exe_icon
from game_launcher import find_cover_in_folder
from video_reader import extract_thumbnail


FEATURED_BOOST = 3.0
FEATURED_LIMIT = 10
QUERY_MULTIPLIER = 3

CARD_MIN_W = 160
CARD_MAX_W = 300
CARD_ASPECT = 1.30
CARD_TITLE_H = 40
GAP = 8
COVER_TARGET = (480, 440)
SCROLLBAR_RESERVE = 14


def _cover_height(card_w: int) -> int:
    return int(card_w * CARD_ASPECT)


def _card_height(card_w: int) -> int:
    return _cover_height(card_w) + CARD_TITLE_H


# ============================================================
# Горизонтальный QListView с прокруткой колесом мыши
# ============================================================

class HorizontalListView(QListView):
    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            event.ignore()
            return
        bar = self.horizontalScrollBar()
        if bar is None or bar.maximum() <= 0:
            event.ignore()
            return
        bar.setValue(bar.value() - delta)
        event.accept()


# ============================================================
# Модель
# ============================================================

class FeaturedModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._covers = {}

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._items):
            return None
        if role == Qt.UserRole:
            return self._items[row]
        if role == Qt.DisplayRole:
            return self._items[row].get('title', '')
        if role == Qt.DecorationRole:
            return self._covers.get(row)
        return None

    def set_items(self, items):
        self.beginResetModel()
        self._items = list(items or [])
        self._covers = {}
        self.endResetModel()

    def set_cover(self, row, qimage):
        if not (0 <= row < len(self._items)):
            return
        if qimage is None or qimage.isNull():
            return
        self._covers[row] = qimage
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [Qt.DecorationRole])

    def clear(self):
        self.set_items([])


# ============================================================
# Делегат
# ============================================================

class CardDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        view = self.parent()
        if view is not None:
            gs = view.gridSize()
            if gs.isValid() and gs.width() > 0:
                return QSize(gs.width(), gs.height())
        return QSize(CARD_MIN_W + GAP, _card_height(CARD_MIN_W) + GAP)

    def paint(self, painter, option, index):
        item = index.data(Qt.UserRole)
        if item is None:
            return
        qimage = index.data(Qt.DecorationRole)

        pad = GAP // 2
        rect = option.rect.adjusted(pad, pad, -pad, -pad)
        hovered = bool(option.state & QStyle.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        bg_rect = rect.adjusted(1, 1, -1, -1)
        painter.setBrush(QColor('#1a1a1a'))
        if hovered:
            painter.setPen(QPen(QColor('#c0392b'), 2))
        else:
            painter.setPen(QPen(QColor('#2a2a2a'), 1))
        painter.drawRoundedRect(bg_rect, 6, 6)

        inner_pad = 4
        cover_h = rect.height() - CARD_TITLE_H - inner_pad * 2
        if cover_h < 40:
            cover_h = max(20, rect.height() - inner_pad * 2)
        cover_rect = rect.adjusted(
            inner_pad, inner_pad, -inner_pad,
            -(CARD_TITLE_H + inner_pad)
        )

        if qimage is not None and not qimage.isNull():
            pix = render_cover(qimage, cover_rect.width(), cover_rect.height())
            if not pix.isNull():
                painter.drawPixmap(cover_rect.topLeft(), pix)
            else:
                self._draw_placeholder(painter, cover_rect, item.get('kind'))
        else:
            self._draw_placeholder(painter, cover_rect, item.get('kind'))

        title_top = cover_rect.bottom() + 3
        title_rect = rect.adjusted(
            inner_pad, title_top - rect.top(), -inner_pad, -inner_pad
        )
        painter.setPen(QColor('#ffffff'))
        f = QFont(painter.font())
        f.setPointSize(max(9, min(13, rect.width() // 26)))
        painter.setFont(f)
        title = str(item.get('title', ''))
        elided = painter.fontMetrics().elidedText(
            title, Qt.ElideRight, title_rect.width()
        )
        painter.drawText(title_rect, Qt.AlignHCenter | Qt.AlignTop, elided)

        painter.restore()

    @staticmethod
    def _draw_placeholder(painter, rect, kind):
        painter.fillRect(rect, QColor('#0d0d0d'))
        icon = {'comic': '📚', 'video': '🎬', 'game': '🎮'}.get(kind, '🎬')
        painter.setPen(QColor('#444'))
        f = QFont(painter.font())
        f.setPointSize(max(18, rect.width() // 5))
        painter.setFont(f)
        painter.drawText(rect, Qt.AlignCenter, icon)


# ============================================================
# Загрузчик обложек
# ============================================================

class _CoverSignals(QObject):
    loaded = pyqtSignal(str, QImage)
    failed = pyqtSignal(str)


class CoverLoader(QRunnable):
    def __init__(self, kind, file_path, target_size, cover_hint=None):
        super().__init__()
        self.kind = kind
        self.file_path = file_path
        self.target_size = target_size
        self.cover_hint = cover_hint
        self.signals = _CoverSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            img = self._load()
            if img is not None and not img.isNull():
                self.signals.loaded.emit(self.file_path, img)
            else:
                self.signals.failed.emit(self.file_path)
        except Exception as e:
            print(f"[home_cover] {self.file_path}: {e}")
            self.signals.failed.emit(self.file_path)

    def _load(self):
        if self.cover_hint and os.path.isfile(self.cover_hint):
            img = self._from_image_file(self.cover_hint)
            if img is not None and not img.isNull():
                return img

        if self.kind == 'comic':
            return self._from_comic()
        if self.kind == 'video':
            return self._from_video()
        if self.kind == 'game':
            return self._from_game()
        return None

    def _from_image_file(self, path):
        try:
            with Image.open(path) as im:
                im.thumbnail(self.target_size, Image.LANCZOS)
                if im.mode not in ('RGB', 'RGBA'):
                    im = im.convert('RGB')
                buf = io.BytesIO()
                im.save(buf, format='PNG')
            buf.seek(0)
            q = QImage()
            q.loadFromData(buf.read())
            return q
        except Exception:
            return None

    def _from_comic(self):
        if not os.path.isfile(self.file_path):
            return None
        cached = cover_cache.load(self.file_path, self.target_size)
        if cached is not None and not cached.isNull():
            return cached
        try:
            img = ArchiveReader.extract_page(self.file_path, 0)
            img.thumbnail(self.target_size, Image.LANCZOS)
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            q = QImage()
            q.loadFromData(buf.read())
            try:
                cover_cache.save(self.file_path, self.target_size, q)
            except Exception:
                pass
            return q
        except Exception:
            return None

    def _from_video(self):
        if not os.path.isfile(self.file_path):
            return None
        cached = cover_cache.load(self.file_path, self.target_size)
        if cached is not None and not cached.isNull():
            return cached
        img = extract_thumbnail(self.file_path, self.target_size)
        if img is not None and not img.isNull():
            try:
                cover_cache.save(self.file_path, self.target_size, img)
            except Exception:
                pass
        return img

    def _from_game(self):
        if not os.path.isfile(self.file_path):
            return None
        cached = cover_cache.load(self.file_path, self.target_size)
        if cached is not None and not cached.isNull():
            return cached

        folder = os.path.dirname(self.file_path)
        auto = find_cover_in_folder(folder) if folder else None
        if auto:
            q = self._from_image_file(auto)
            if q is not None and not q.isNull():
                try:
                    cover_cache.save(self.file_path, self.target_size, q)
                except Exception:
                    pass
                return q

        q = extract_exe_icon(self.file_path, 256)
        if q is not None and not q.isNull():
            try:
                cover_cache.save(self.file_path, self.target_size, q)
            except Exception:
                pass
            return q
        return None


# ============================================================
# Загрузчик данных
# ============================================================

class _DataSignals(QObject):
    loaded = pyqtSignal(list, list, list)
    failed = pyqtSignal(str)


class DataLoader(QRunnable):
    def __init__(self, db, featured_tag):
        super().__init__()
        self.db = db
        self.featured_tag = (featured_tag or '').strip()
        self.signals = _DataSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            comics = self._top_comics()
            videos = self._top_videos()
            games = self._top_games()
            self.signals.loaded.emit(comics, videos, games)
        except Exception as e:
            self.signals.failed.emit(str(e))

    def _score(self, base, tags):
        s = float(base or 0)
        if self.featured_tag and self.featured_tag in tags:
            s *= FEATURED_BOOST
        return s

    def _top_comics(self):
        items = self.db.get_top_comics_by_views_with_tags(
            FEATURED_LIMIT * QUERY_MULTIPLIER
        )
        items = [c for c in items if os.path.isfile(c.get('file_path', ''))]
        scored = [
            (self._score(c.get('view_count', 0), c.get('tags') or []), c)
            for c in items
        ]
        scored.sort(key=lambda x: (-x[0], x[1].get('title', '')))
        return [c for _, c in scored[:FEATURED_LIMIT]]

    def _top_videos(self):
        items = self.db.get_top_videos_by_views_with_tags(
            FEATURED_LIMIT * QUERY_MULTIPLIER
        )
        items = [v for v in items if os.path.isfile(v.get('file_path', ''))]
        scored = [
            (self._score(v.get('watch_count', 0), v.get('tags') or []), v)
            for v in items
        ]
        scored.sort(key=lambda x: (-x[0], x[1].get('title', '')))
        return [v for _, v in scored[:FEATURED_LIMIT]]

    def _top_games(self):
        items = self.db.get_top_games_by_launches_with_tags(
            FEATURED_LIMIT * QUERY_MULTIPLIER
        )
        items = [g for g in items if os.path.isfile(g.get('exe_path', ''))]
        scored = [
            (self._score(g.get('launch_count', 0), g.get('tags') or []), g)
            for g in items
        ]
        scored.sort(key=lambda x: (-x[0], x[1].get('title', '')))
        return [g for _, g in scored[:FEATURED_LIMIT]]


# ============================================================
# Главное окно
# ============================================================

class HomeWindow(QWidget):
    comic_selected = pyqtSignal(str)
    video_selected = pyqtSignal(str)
    game_selected = pyqtSignal(str)

    RESIZE_DEBOUNCE_MS = 80

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.featured_tag = ''
        self._has_been_loaded = False

        self._cover_pool = QThreadPool(self)
        self._cover_pool.setMaxThreadCount(2)

        self._data_pool = QThreadPool(self)
        self._data_pool.setMaxThreadCount(1)
        self._data_loader = None

        self._cover_in_flight = set()
        self._cover_waiters = {}

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(self.RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self._update_grid_sizes)

        self._build_ui()

        QTimer.singleShot(0, self._update_grid_sizes)

    # ---------- UI ----------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("""
            QScrollArea { border: none; background-color: #121212; }
            QScrollBar:vertical {
                background: #1e1e1e; width: 10px; border: none;
            }
            QScrollBar::handle:vertical {
                background: #444; border-radius: 5px; min-height: 30px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
        """)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(24, 24, 24, 24)
        cl.setSpacing(18)

        self.header_label = QLabel("🏠 Главная")
        self.header_label.setStyleSheet(
            "QLabel { color: #ffffff; font-size: 26px; font-weight: bold; }"
        )
        cl.addWidget(self.header_label)

        self.hint_label = QLabel("")
        self.hint_label.setStyleSheet(
            "QLabel { color: #888; font-size: 12px; }"
        )
        self.hint_label.setWordWrap(True)
        cl.addWidget(self.hint_label)

        self.comics_title = self._section_title("Популярные комиксы")
        self.comics_model = FeaturedModel(self)
        self.comics_view = self._make_view(self.comics_model)
        cl.addWidget(self.comics_title)
        cl.addWidget(self.comics_view)

        self.videos_title = self._section_title("Популярные видео")
        self.videos_model = FeaturedModel(self)
        self.videos_view = self._make_view(self.videos_model)
        cl.addWidget(self.videos_title)
        cl.addWidget(self.videos_view)

        self.games_title = self._section_title("Популярные игры")
        self.games_model = FeaturedModel(self)
        self.games_view = self._make_view(self.games_model)
        cl.addWidget(self.games_title)
        cl.addWidget(self.games_view)

        cl.addStretch()
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)

        self.setStyleSheet("QWidget { background-color: #121212; }")

    @staticmethod
    def _section_title(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "QLabel { color: #ffffff; font-size: 18px; font-weight: bold;"
            " background: transparent; }"
        )
        return lbl

    def _make_view(self, model):
        view = HorizontalListView()
        view.setModel(model)
        view.setViewMode(QListView.IconMode)
        view.setFlow(QListView.LeftToRight)
        view.setWrapping(False)
        view.setResizeMode(QListView.Adjust)
        view.setMovement(QListView.Static)
        view.setSelectionMode(QAbstractItemView.NoSelection)
        view.setUniformItemSizes(True)
        view.setSpacing(0)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        view.setItemDelegate(CardDelegate(view))
        view.setMouseTracking(True)
        view.clicked.connect(self._on_item_clicked)
        view.setStyleSheet("""
            QListView { background: transparent; border: none; }
            QListView::item { background: transparent; }
            QScrollBar:horizontal {
                background: #1e1e1e; height: 8px;
                border: none; margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #444; border-radius: 4px;
                min-width: 40px;
            }
            QScrollBar::handle:horizontal:hover { background: #555; }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal { width: 0; }
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal { background: transparent; }
        """)
        return view

    # ---------- размеры ----------

    def _available_width(self):
        w = self.scroll.viewport().width()
        if w <= 0:
            w = self.width()
        return max(0, w - 48)

    def _compute_grid(self, avail):
        if avail <= 0:
            return CARD_MIN_W + GAP, _card_height(CARD_MIN_W) + GAP

        n = max(1, (avail + CARD_MAX_W + GAP - 1) // (CARD_MAX_W + GAP))
        card_w = (avail - (n - 1) * GAP) // n

        if card_w < CARD_MIN_W:
            n = max(1, avail // (CARD_MIN_W + GAP))
            card_w = (avail - (n - 1) * GAP) // n

        if card_w > CARD_MAX_W:
            card_w = CARD_MAX_W
        if card_w < CARD_MIN_W:
            card_w = CARD_MIN_W

        card_h = _card_height(card_w)
        return card_w + GAP, card_h + GAP

    def _update_grid_sizes(self):
        avail = self._available_width()
        if avail <= 0:
            return

        cell_w, cell_h = self._compute_grid(avail)
        new_size = QSize(cell_w, cell_h)

        for view in (self.comics_view, self.videos_view, self.games_view):
            if view.gridSize() != new_size:
                view.setGridSize(new_size)
            view.setFixedHeight(cell_h + SCROLLBAR_RESERVE)
            try:
                view.doItemsLayout()
            except Exception:
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    # ---------- public API ----------

    def set_featured_tag(self, tag):
        new_tag = (tag or '').strip()
        if new_tag == self.featured_tag:
            return
        self.featured_tag = new_tag
        if self._has_been_loaded:
            self.refresh()

    def refresh(self):
        self._has_been_loaded = True
        self._cancel_pending()

        if self.featured_tag:
            self.hint_label.setText(
                f"✨ Приоритетный тег: «{self.featured_tag}» "
                f"(буст ×{FEATURED_BOOST:g})"
            )
        else:
            self.hint_label.setText(
                "Приоритетный тег не выбран. Отбор по количеству просмотров."
            )

        self.comics_model.clear()
        self.videos_model.clear()
        self.games_model.clear()

        self._update_grid_sizes()

        loader = DataLoader(self.db, self.featured_tag)
        loader.signals.loaded.connect(self._on_data_loaded)
        loader.signals.failed.connect(self._on_data_failed)
        self._data_loader = loader
        self._data_pool.start(loader)

    def _cancel_pending(self):
        self._cover_waiters.clear()
        self._data_loader = None

    # ---------- приём данных ----------

    def _on_data_loaded(self, comics, videos, games):
        # ВАЖНО: добавляем поле kind — оно используется в _on_item_clicked,
        # чтобы понять, что открывать (комикс, видео или игру).
        comics_items = [dict(c, kind='comic') for c in comics]
        videos_items = [dict(v, kind='video') for v in videos]
        games_items = [dict(g, kind='game') for g in games]

        self.comics_model.set_items(comics_items)
        self.videos_model.set_items(videos_items)
        self.games_model.set_items(games_items)

        self._update_grid_sizes()

        for row, item in enumerate(comics_items):
            self._request_cover('comic', item['file_path'],
                                self.comics_model, row,
                                cover_hint=None)
        for row, item in enumerate(videos_items):
            self._request_cover('video', item['file_path'],
                                self.videos_model, row,
                                cover_hint=None)
        for row, item in enumerate(games_items):
            self._request_cover('game', item['exe_path'],
                                self.games_model, row,
                                cover_hint=item.get('cover_path') or None)

    def _on_data_failed(self, err):
        print(f"[home] data loader failed: {err}")

    # ---------- обложки ----------

    def _request_cover(self, kind, file_path, model, row, cover_hint):
        if not file_path:
            return
        if file_path in self._cover_waiters:
            self._cover_waiters[file_path].append((model, row))
            return

        self._cover_waiters[file_path] = [(model, row)]
        self._cover_in_flight.add(file_path)

        loader = CoverLoader(kind, file_path, COVER_TARGET, cover_hint)
        loader.signals.loaded.connect(self._on_cover_loaded)
        loader.signals.failed.connect(self._on_cover_failed)
        self._cover_pool.start(loader)

    def _on_cover_loaded(self, file_path, qimage):
        self._cover_in_flight.discard(file_path)
        waiters = self._cover_waiters.pop(file_path, [])
        for model, row in waiters:
            model.set_cover(row, qimage)

    def _on_cover_failed(self, file_path):
        self._cover_in_flight.discard(file_path)
        self._cover_waiters.pop(file_path, None)

    # ---------- клик ----------

    def _on_item_clicked(self, index):
        item = index.data(Qt.UserRole)
        if not item:
            return
        kind = item.get('kind')
        if kind == 'comic':
            self.comic_selected.emit(item.get('file_path', ''))
        elif kind == 'video':
            self.video_selected.emit(item.get('file_path', ''))
        elif kind == 'game':
            self.game_selected.emit(item.get('exe_path', ''))

    def closeEvent(self, event):
        try:
            self._cover_pool.clear()
        except Exception:
            pass
        try:
            self._data_pool.clear()
        except Exception:
            pass
        super().closeEvent(event)