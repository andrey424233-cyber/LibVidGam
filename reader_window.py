import io
import os

from PIL import Image
from PyQt5.QtCore import (Qt, pyqtSignal, QThread, QMutex, QMutexLocker,
                          QWaitCondition, QTimer)
from PyQt5.QtGui import QPixmap, QImage, QKeySequence, QWheelEvent
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QScrollArea, QSizePolicy, QSpinBox,
                             QSlider, QFrame, QShortcut, QStackedWidget,
                             QComboBox)

from archive_reader import OpenedArchive


class PageLoaderWorker(QThread):
    """Фоновый загрузчик. Использует один открытый OpenedArchive."""

    page_loaded = pyqtSignal(int, QImage)
    error = pyqtSignal(int, str)

    def __init__(self, archive: OpenedArchive, target_size=(1200, 1600),
                 parent=None):
        super().__init__(parent)
        self.archive = archive
        self._mutex = QMutex()
        self._wait_condition = QWaitCondition()
        self._queue = []
        self._running = True
        self._target_size = target_size

    def add_to_queue(self, page_index: int, priority: int = 0):
        with QMutexLocker(self._mutex):
            if not any(item[1] == page_index for item in self._queue):
                self._queue.append((priority, page_index))
                self._queue.sort(key=lambda x: x[0])
        self._wait_condition.wakeOne()

    def clear_queue(self):
        with QMutexLocker(self._mutex):
            self._queue.clear()

    def stop(self):
        with QMutexLocker(self._mutex):
            self._running = False
            self._queue.clear()
        self._wait_condition.wakeOne()

    def run(self):
        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break
                if not self._queue:
                    self._wait_condition.wait(self._mutex)
                    continue
                _priority, page_index = self._queue.pop(0)

            try:
                image = self.archive.read_page(page_index)
                image.thumbnail(self._target_size, Image.LANCZOS)

                if image.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', image.size, (255, 255, 255))
                    if image.mode == 'P':
                        image = image.convert('RGBA')
                    mask = image.split()[-1] if 'A' in image.mode else None
                    background.paste(image, mask=mask)
                    image = background
                elif image.mode != 'RGB':
                    image = image.convert('RGB')

                buffer = io.BytesIO()
                image.save(buffer, format='JPEG', quality=85)
                buffer.seek(0)

                qimage = QImage()
                qimage.loadFromData(buffer.read(), 'JPEG')
                self.page_loaded.emit(page_index, qimage)
            except Exception as e:
                self.error.emit(page_index, str(e))


class SinglePageView(QWidget):
    """Режим: Страница (листание)"""

    def __init__(self, total_pages: int, parent=None):
        super().__init__(parent)
        self.total_pages = total_pages
        self.current_page = 0

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background-color: #0a0a0a; }
        """)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_label.setStyleSheet("QLabel { background-color: #0a0a0a; }")

        self.scroll_area.setWidget(self.image_label)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)

    def display_page(self, page_index: int, pixmap: QPixmap):
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(self.scroll_area.viewport().size(),
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled)
        self.current_page = page_index

    def show_loading(self):
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("Загрузка...")
        self.image_label.setStyleSheet("""
            QLabel { color: #888; font-size: 24px; background-color: #0a0a0a; }
        """)

    def show_error(self, msg: str):
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText(f"Ошибка загрузки\n{msg}")


class GridView(QWidget):
    """Режим: Сетка (миниатюры всех страниц)"""

    page_selected = pyqtSignal(int)
    load_more_pages = pyqtSignal(list)

    BASE_THUMB_WIDTH = 150
    BASE_THUMB_HEIGHT = 200
    SPACING = 15

    def __init__(self, total_pages: int, parent=None):
        super().__init__(parent)
        self.total_pages = total_pages
        self.page_widgets = {}
        self.zoom_level = 1.0
        self._loaded_pixmap = {}
        self._last_loaded_range = (-1, -1)
        self._initial_load_requested = False
        self._thumbs_per_row = 5

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel(f"Все страницы ({total_pages})")
        title.setStyleSheet(
            "QLabel { color: #e0e0e0; font-size: 20px; font-weight: bold; }"
        )
        layout.addWidget(title)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background-color: #121212; }
        """)

        self.content_widget = QWidget()
        self.grid_layout = QVBoxLayout()
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(self.SPACING)
        self.content_widget.setLayout(self.grid_layout)

        self.scroll_area.setWidget(self.content_widget)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)

        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(300)
        self._resize_timer.timeout.connect(self._on_resize)

        self._create_grid()
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_load_requested:
            self._initial_load_requested = True
            QTimer.singleShot(200, self.load_initial_pages)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    def _on_resize(self):
        self._create_grid()
        QTimer.singleShot(100, self.load_initial_pages)

    def _calculate_thumbs_per_row(self):
        viewport_width = self.scroll_area.viewport().width() - 40
        thumb_width = int(self.BASE_THUMB_WIDTH * self.zoom_level)
        return max(1, (viewport_width + self.SPACING) // (thumb_width + self.SPACING))

    def _create_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.page_widgets.clear()
        self._thumbs_per_row = self._calculate_thumbs_per_row()

        thumb_width = int(self.BASE_THUMB_WIDTH * self.zoom_level)
        thumb_height = int(self.BASE_THUMB_HEIGHT * self.zoom_level)

        for i in range(0, self.total_pages, self._thumbs_per_row):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(self.SPACING)
            row_layout.setContentsMargins(0, 0, 0, 0)

            for j in range(self._thumbs_per_row):
                page_index = i + j
                if page_index >= self.total_pages:
                    break

                thumb = QLabel()
                thumb.setFixedSize(thumb_width, thumb_height + 25)
                thumb.setAlignment(Qt.AlignCenter)
                thumb.setCursor(Qt.PointingHandCursor)
                thumb.setProperty('page_index', page_index)
                thumb.setStyleSheet("""
                    QLabel {
                        background-color: #1e1e1e; border-radius: 8px;
                        border: 2px solid #3a3a3a; color: #888; font-size: 11px;
                    }
                    QLabel:hover { border: 2px solid #c0392b; color: #e0e0e0; }
                """)
                thumb.setText(f"Стр. {page_index + 1}")
                thumb.mousePressEvent = (
                    lambda event, idx=page_index: self._on_thumb_clicked(idx, event)
                )
                row_layout.addWidget(thumb)
                self.page_widgets[page_index] = thumb

            row_widget = QWidget()
            row_widget.setLayout(row_layout)
            self.grid_layout.addWidget(row_widget)

        self.grid_layout.addStretch()
        self._restore_loaded_images()

    def _restore_loaded_images(self):
        for page_index, pixmap in list(self._loaded_pixmap.items()):
            if page_index in self.page_widgets and pixmap and not pixmap.isNull():
                self._apply_pixmap_to_thumb(page_index, pixmap)

    def _apply_pixmap_to_thumb(self, page_index: int, pixmap: QPixmap):
        thumb = self.page_widgets.get(page_index)
        if thumb is None:
            return
        try:
            scaled = pixmap.scaled(thumb.width() - 4, thumb.height() - 29,
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
            thumb.setPixmap(scaled)
            thumb.setText("")
        except RuntimeError:
            pass

    def show_loading_at(self, page_index: int):
        thumb = self.page_widgets.get(page_index)
        if thumb is not None:
            thumb.setPixmap(QPixmap())
            thumb.setText("")
            thumb.setStyleSheet("""
                QLabel {
                    background-color: #1e1e1e; border-radius: 8px;
                    border: 2px solid #3a3a3a; color: #c0392b; font-size: 24px;
                }
            """)

    def _on_scroll(self, value):
        viewport = self.scroll_area.viewport()
        if viewport.height() < 100:
            return

        viewport_top = value
        viewport_bottom = viewport_top + viewport.height()

        visible_pages = []
        for page_index, widget in self.page_widgets.items():
            try:
                top = widget.pos().y()
                bottom = top + widget.height()
            except RuntimeError:
                continue
            if top <= viewport_bottom and bottom >= viewport_top:
                visible_pages.append(page_index)

        if visible_pages:
            min_page = max(0, min(visible_pages) - 5)
            max_page = min(self.total_pages - 1, max(visible_pages) + 5)
            if (min_page, max_page) != self._last_loaded_range:
                self._last_loaded_range = (min_page, max_page)
                self.load_more_pages.emit(list(range(min_page, max_page + 1)))

    def load_initial_pages(self):
        pages_per_screen = self._thumbs_per_row * 3
        min_page = 0
        max_page = min(self.total_pages - 1, pages_per_screen - 1)
        pages_to_load = list(range(min_page, max_page + 1))

        for idx in pages_to_load:
            if idx not in self._loaded_pixmap:
                self.show_loading_at(idx)

        self._last_loaded_range = (min_page, max_page)
        self.load_more_pages.emit(pages_to_load)

    def _on_thumb_clicked(self, page_index: int, event):
        if event.button() == Qt.LeftButton:
            self.page_selected.emit(page_index)

    def display_page(self, page_index: int, pixmap: QPixmap):
        if page_index not in self.page_widgets or pixmap is None or pixmap.isNull():
            return
        self._loaded_pixmap[page_index] = pixmap
        self._apply_pixmap_to_thumb(page_index, pixmap)

    def set_zoom(self, zoom: float):
        old_zoom = self.zoom_level
        self.zoom_level = max(0.5, min(5.0, zoom))
        if abs(self.zoom_level - old_zoom) > 0.05:
            self._create_grid()
            QTimer.singleShot(200, self.load_initial_pages)


# ============================================================
# Режим «Лента» — вертикальный скролл (webtoon-стиль)
# ============================================================

class FeedView(QWidget):
    """Режим: Лента (вертикальный скролл страниц).

    Страницы идут одна под другой. Загружаются по мере прокрутки.
    Видимые страницы подсвечиваются как «текущая» — синхронизируется
    с номером страницы и ползунком внизу окна.
    """

    page_changed = pyqtSignal(int)       # текущая видимая страница (номер)
    request_pages = pyqtSignal(list)     # запрос на загрузку страниц

    PLACEHOLDER_RATIO = 1.4              # высота заглушки / ширина
    BUFFER_ABOVE = 2                     # сколько страниц грузить выше видимой
    BUFFER_BELOW = 3                     # сколько страниц грузить ниже видимой
    MAX_CACHED_PIXMAPS = 12              # сколько pixmap'ов держать в памяти

    def __init__(self, total_pages: int, parent=None):
        super().__init__(parent)
        self.total_pages = total_pages
        self.current_page = 0
        self._labels = {}                  # index -> QLabel
        self._pixmaps = {}                 # index -> QPixmap (кэш)
        self._actual_heights = {}          # index -> высота (после загрузки)
        self._loaded = set()               # индексы, для которых есть pixmap
        self._loading = set()              # индексы, запрошенные на загрузку
        self._last_requested_range = (-1, -1)
        self._suppress_scroll_signal = False
        self._initial_load_done = False

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background-color: #0a0a0a; }
        """)

        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("QWidget { background-color: #0a0a0a; }")
        self.feed_layout = QVBoxLayout()
        self.feed_layout.setContentsMargins(0, 0, 0, 0)
        self.feed_layout.setSpacing(2)
        self.content_widget.setLayout(self.feed_layout)

        self.scroll_area.setWidget(self.content_widget)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)

        self._build_labels()

        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll)

        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._on_resize)

    # ---------- построение ----------

    def _build_labels(self):
        """Создаёт QLabel'ы для всех страниц."""
        while self.feed_layout.count():
            item = self.feed_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._labels.clear()

        width = max(100, self.scroll_area.viewport().width() or 800)
        placeholder_h = int(width * self.PLACEHOLDER_RATIO)

        for i in range(self.total_pages):
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                "QLabel { background-color: #0a0a0a; color: #333; "
                "font-size: 14px; }"
            )
            lbl.setText(f"{i + 1}")
            lbl.setFixedHeight(placeholder_h)
            # Ограничение по ширине — чтобы QLabel не «распирал» контейнер
            lbl.setMinimumWidth(50)
            self.feed_layout.addWidget(lbl)
            self._labels[i] = lbl

        self.feed_layout.addStretch()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_load_done:
            self._initial_load_done = True
            QTimer.singleShot(100, self._initial_load)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    def _on_resize(self):
        """Пересчитывает размеры всех label'ов и пересобирает layout."""
        anchor = self._visible_page_index()

        width = max(100, self.scroll_area.viewport().width() or 800)

        for idx, lbl in self._labels.items():
            pix = self._pixmaps.get(idx)
            if pix is not None and not pix.isNull():
                h = self._compute_height_for_pixmap(pix, width)
                try:
                    lbl.setFixedHeight(h)
                except RuntimeError:
                    pass
            else:
                try:
                    lbl.setFixedHeight(int(width * self.PLACEHOLDER_RATIO))
                except RuntimeError:
                    pass

        for idx in list(self._loaded):
            self._redraw_label(idx)

        if anchor is not None:
            # Прокрутка — после пересчёта layout
            QTimer.singleShot(
                0, lambda a=anchor: self._scroll_to_page(a, smooth=False)
            )
            # И повторный запрос на случай, если новые страницы попали
            # в поле зрения после пересчёта
            QTimer.singleShot(
                50, lambda a=anchor: self._request_around(a)
            )

    def _compute_height_for_pixmap(self, pixmap: QPixmap, target_width: int) -> int:
        if pixmap is None or pixmap.isNull() or pixmap.width() == 0:
            return int(target_width * self.PLACEHOLDER_RATIO)
        ratio = pixmap.height() / pixmap.width()
        return max(50, int(target_width * ratio))

    def _redraw_label(self, index: int):
        lbl = self._labels.get(index)
        pix = self._pixmaps.get(index)
        if lbl is None or pix is None or pix.isNull():
            return
        try:
            width = max(100, self.scroll_area.viewport().width() or 800)
            scaled = pix.scaled(width, self._compute_height_for_pixmap(pix, width),
                                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl.setPixmap(scaled)
            lbl.setText("")
            lbl.setFixedHeight(scaled.height() + 2)
        except RuntimeError:
            pass

    # ---------- загрузка ----------

    def _initial_load(self):
        self._request_around(self.current_page)
        # после первой загрузки — наверх к первой странице
        QTimer.singleShot(100, lambda: self._scroll_to_page(0, smooth=False))

    def _request_around(self, page_index: int):
        """Запрашивает страницы вокруг указанной.

        НЕ используем жёсткий блок по last_requested_range — если страница
        выгрузилась из кэша, её нужно запросить снова. Пустой to_load
        сам по себе означает, что ничего не нужно.
        """
        min_page = max(0, page_index - self.BUFFER_ABOVE)
        max_page = min(self.total_pages - 1, page_index + self.BUFFER_BELOW)
        wanted = list(range(min_page, max_page + 1))

        to_load = [i for i in wanted
                   if i not in self._loaded and i not in self._loading]
        if not to_load:
            return

        self._loading.update(to_load)
        self.request_pages.emit(to_load)

    def set_pixmap(self, page_index: int, pixmap: QPixmap):
        if pixmap is None or pixmap.isNull():
            self._loading.discard(page_index)
            return

        self._pixmaps[page_index] = pixmap
        self._loaded.add(page_index)
        self._loading.discard(page_index)
        self._redraw_label(page_index)
        self._trim_cache()

    def _trim_cache(self):
        """Удаляет pixmap'ы, далёкие от текущей страницы."""
        if len(self._pixmaps) <= self.MAX_CACHED_PIXMAPS:
            return
        current = self.current_page
        # сортируем по удалённости от текущей
        items = sorted(self._pixmaps.keys(),
                       key=lambda i: abs(i - current), reverse=True)
        to_remove = []
        while len(self._pixmaps) - len(to_remove) > self.MAX_CACHED_PIXMAPS:
            idx = items.pop(0)
            if abs(idx - current) <= self.BUFFER_BELOW + 2:
                break
            to_remove.append(idx)

        for idx in to_remove:
            self._pixmaps.pop(idx, None)
            self._loaded.discard(idx)
            lbl = self._labels.get(idx)
            if lbl is not None:
                try:
                    lbl.setPixmap(QPixmap())
                    lbl.setText(f"{idx + 1}")
                except RuntimeError:
                    pass

    # ---------- скролл ----------

    def _on_scroll(self, value):
        if self._suppress_scroll_signal:
            return
        page = self._visible_page_index()
        if page is not None and page != self.current_page:
            self.current_page = page
            self.page_changed.emit(page)
            self._request_around(page)

    def _visible_page_index(self):
        """Возвращает номер страницы, которая сейчас в центре видимой области.

        ВАЖНО: lbl.pos().y() — координата в content_widget.
        Центр viewport переводим в те же координаты: scroll_value + h/2.
        """
        viewport = self.scroll_area.viewport()
        if viewport.height() < 50:
            return None
        scroll_y = self.scroll_area.verticalScrollBar().value()
        center_y = scroll_y + viewport.height() // 2
        best_idx = None
        best_dist = None
        for idx, lbl in self._labels.items():
            try:
                top = lbl.pos().y()
                bottom = top + lbl.height()
            except RuntimeError:
                continue
            if top <= center_y <= bottom:
                return idx
            mid = (top + bottom) // 2
            dist = abs(mid - center_y)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

    # ---------- навигация ----------

    def goto_page(self, page_index: int):
        if not 0 <= page_index < self.total_pages:
            return
        self.current_page = page_index
        # Запрос сразу
        self._request_around(page_index)
        # Прокрутка — после того как layout пересчитается
        QTimer.singleShot(
            30, lambda i=page_index: self._scroll_to_page(i, smooth=False)
        )
        # Повторный запрос — на случай, если видимая область уехала
        QTimer.singleShot(
            60, lambda i=page_index: self._request_around(i)
        )

    def _scroll_to_page(self, page_index: int, smooth: bool = True):
        lbl = self._labels.get(page_index)
        if lbl is None:
            return
        try:
            y = lbl.pos().y()
        except RuntimeError:
            return
        bar = self.scroll_area.verticalScrollBar()
        self._suppress_scroll_signal = True
        try:
            if smooth:
                bar.setValue(y)
            else:
                bar.setValue(y)
        finally:
            # снимаем флаг в следующем цикле event loop
            QTimer.singleShot(0, self._release_scroll_suppress)

    def _release_scroll_suppress(self):
        self._suppress_scroll_signal = False

class ReaderWindow(QWidget):
    """Окно чтения. Один OpenedArchive на всё время жизни окна."""

    closed = pyqtSignal()

    MODE_SINGLE = 0
    MODE_GRID = 1
    MODE_FEED = 2

    def __init__(self, file_path: str, db=None):
        super().__init__()
        self.file_path = file_path
        self.db = db
        self.current_page = 0
        self._closing = False

        self.archive = OpenedArchive(file_path)
        self.total_pages = self.archive.page_count()

        self.page_cache = {}
        self._loading_pages = set()
        self._requested_page = None
        self.current_mode = self.MODE_SINGLE
        self._zoom_level = 1.0
        self._view_count_incremented = False
        self._page_cache_limit = 8

        self.loader = PageLoaderWorker(self.archive, target_size=(1200, 1600))
        self.loader.page_loaded.connect(self._on_page_loaded)
        self.loader.error.connect(self._on_load_error)
        self.loader.start()

        self.init_ui()

        # Восстанавливаем режим из БД и открываем последнюю страницу
        self._restore_mode()
        self._restore_progress()

    # ---------- восстановление состояния ----------

    def _restore_mode(self):
        mode = self.MODE_SINGLE
        if self.db:
            try:
                comic = self.db.get_comic_by_path(self.file_path)
                if comic:
                    mode = int(comic.get('reading_mode', 0) or 0)
            except Exception:
                pass
        if mode not in (self.MODE_SINGLE, self.MODE_GRID, self.MODE_FEED):
            mode = self.MODE_SINGLE
        self.current_mode = mode
        idx = self.mode_combo.findData(mode)
        if idx < 0:
            idx = 0
            self.current_mode = self.MODE_SINGLE
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.blockSignals(False)
        self.mode_stack.setCurrentIndex(self.current_mode)
        self._update_controls_visibility()

    def _restore_progress(self):
        start_page = 0
        if self.db:
            try:
                comic = self.db.get_comic_by_path(self.file_path)
                if comic:
                    start_page = int(comic.get('last_page_read', 0) or 0)
            except Exception:
                pass
        if not 0 <= start_page < self.total_pages:
            start_page = 0
        self.show_page(start_page)

    # ---------- UI ----------

    def init_ui(self):
        self.setWindowTitle("Чтение комикса")
        self.resize(1200, 800)
        self.setStyleSheet("QWidget { background-color: #0a0a0a; }")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(15, 10, 15, 10)

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(40, 40)
        self.btn_close.setToolTip("Закрыть (Esc)")
        self.btn_close.setStyleSheet(self._btn_style("#2a2a2a"))
        self.btn_close.clicked.connect(self.close)
        control_layout.addWidget(self.btn_close)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedSize(50, 40)
        self.btn_prev.setToolTip("Предыдущая страница (←)")
        self.btn_prev.setStyleSheet(self._btn_style("#2a2a2a"))
        self.btn_prev.clicked.connect(self.prev_page)
        control_layout.addWidget(self.btn_prev)

        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(max(1, self.total_pages))
        self.page_spin.setValue(1)
        self.page_spin.setFixedSize(80, 40)
        self.page_spin.setAlignment(Qt.AlignCenter)
        self.page_spin.setStyleSheet("""
            QSpinBox {
                background-color: #1e1e1e; color: #e0e0e0;
                border: 1px solid #3a3a3a; border-radius: 5px;
                font-size: 14px; padding: 5px;
            }
            QSpinBox:focus { border: 1px solid #c0392b; }
        """)
        self.page_spin.valueChanged.connect(self.go_to_page)
        control_layout.addWidget(self.page_spin)

        control_layout.addWidget(self._label("/"))

        self.total_label = self._label(f"{self.total_pages}")
        control_layout.addWidget(self.total_label)

        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedSize(50, 40)
        self.btn_next.setToolTip("Следующая страница (→)")
        self.btn_next.setStyleSheet(self._btn_style("#2a2a2a"))
        self.btn_next.clicked.connect(self.next_page)
        control_layout.addWidget(self.btn_next)

        control_layout.addStretch()

        title = os.path.splitext(os.path.basename(self.file_path))[0]
        self.title_label = self._label(title, max_width=300)
        control_layout.addWidget(self.title_label)

        control_layout.addStretch()

        self.mode_combo = QComboBox()
        # Порядок пунктов в UI: Страница → Лента → Сетка.
        # Значение (mode) хранится в itemData, чтобы не зависеть от порядка.
        self.mode_combo.addItem("📄 Страница", self.MODE_SINGLE)
        self.mode_combo.addItem("📜 Лента", self.MODE_FEED)
        self.mode_combo.addItem("🗂️ Сетка", self.MODE_GRID)
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.setFixedSize(170, 40)
        self.mode_combo.setToolTip("Режим чтения")
        self.mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a; color: #e0e0e0;
                border: none; border-radius: 5px;
                padding: 5px 10px; font-size: 14px;
            }
            QComboBox:hover { background-color: #3a3a3a; }
            QComboBox::drop-down { border: none; width: 30px; }
            QComboBox QAbstractItemView {
                background-color: #1e1e1e; color: #e0e0e0;
                border: 1px solid #3a3a3a;
                selection-background-color: #c0392b;
            }
        """)
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        control_layout.addWidget(self.mode_combo)

        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setFixedSize(40, 40)
        self.btn_fullscreen.setToolTip("Полный экран (F11)")
        self.btn_fullscreen.setStyleSheet(self._btn_style("#2a2a2a"))
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        control_layout.addWidget(self.btn_fullscreen)

        layout.addLayout(control_layout)

        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #2a2a2a;")
        layout.addWidget(separator)

        self.mode_stack = QStackedWidget()
        self.mode_stack.setStyleSheet("QStackedWidget { background-color: #0a0a0a; }")

        self.single_view = SinglePageView(self.total_pages)
        self.grid_view = GridView(self.total_pages)
        self.feed_view = FeedView(self.total_pages)

        self.mode_stack.addWidget(self.single_view)   # 0
        self.mode_stack.addWidget(self.grid_view)     # 1
        self.mode_stack.addWidget(self.feed_view)     # 2
        layout.addWidget(self.mode_stack)

        # Сигналы от view-компонентов
        self.grid_view.page_selected.connect(self._on_grid_page_selected)
        self.grid_view.load_more_pages.connect(self._on_load_more_pages)
        self.feed_view.request_pages.connect(self._on_feed_request_pages)
        self.feed_view.page_changed.connect(self._on_feed_page_changed)

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(15, 5, 15, 10)

        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setMinimum(0)
        self.progress_slider.setMaximum(max(0, self.total_pages - 1))
        self.progress_slider.setValue(0)
        self.progress_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #2a2a2a; height: 6px; border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #c0392b; width: 14px; height: 14px;
                margin: -4px 0; border-radius: 7px;
            }
            QSlider::handle:horizontal:hover { background: #e74c3c; }
            QSlider::sub-page:horizontal {
                background: #c0392b; border-radius: 3px;
            }
        """)
        self.progress_slider.valueChanged.connect(self.on_slider_changed)
        bottom_layout.addWidget(self.progress_slider)

        layout.addLayout(bottom_layout)
        self.setLayout(layout)

        # Хоткеи
        QShortcut(QKeySequence(Qt.Key_Left), self, self.prev_page)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.next_page)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.close)
        QShortcut(QKeySequence(Qt.Key_F11), self, self.toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key_Home), self, lambda: self.go_to_page(1))
        QShortcut(QKeySequence(Qt.Key_End),
                  self, lambda: self.go_to_page(self.total_pages))
        QShortcut(QKeySequence(Qt.Key_PageUp), self, self.prev_page)
        QShortcut(QKeySequence(Qt.Key_PageDown), self, self.next_page)
        QShortcut(QKeySequence("Ctrl++"), self, self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, self.zoom_reset)

    @staticmethod
    def _btn_style(bg_color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {bg_color}; color: #e0e0e0;
                border: none; border-radius: 5px; font-size: 16px;
            }}
            QPushButton:hover {{ background-color: #3a3a3a; }}
            QPushButton:pressed {{ background-color: #c0392b; }}
            QPushButton:disabled {{ color: #555; background-color: #1a1a1a; }}
        """

    @staticmethod
    def _label(text: str, max_width: int = None) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            "QLabel { color: #e0e0e0; font-size: 14px; background: transparent; }"
        )
        if max_width:
            label.setMaximumWidth(max_width)
        return label

    # ---------- смена режима ----------

    def on_mode_changed(self, index: int):
        mode = self.mode_combo.itemData(index)
        if mode not in (self.MODE_SINGLE, self.MODE_GRID, self.MODE_FEED):
            return
        old_mode = self.current_mode
        self.current_mode = mode
        self.mode_stack.setCurrentIndex(mode)
        self._update_controls_visibility()
        self._apply_mode_to_current_page(old_mode)
        self._save_mode_to_db()

    def _update_controls_visibility(self):
        """В сетке листание и ползунок не нужны."""
        is_grid = self.current_mode == self.MODE_GRID
        for w in (self.btn_prev, self.btn_next, self.page_spin,
                  self.total_label, self.progress_slider):
            w.setVisible(not is_grid)

    def _apply_mode_to_current_page(self, old_mode: int):
        """При переходе в другой режим — показываем текущую страницу."""
        if self.current_mode == self.MODE_SINGLE:
            if self.current_page in self.page_cache:
                self.single_view.display_page(
                    self.current_page, self.page_cache[self.current_page]
                )
                self.preload_pages(self.current_page)
            else:
                self.single_view.show_loading()
                self._request_page_load(self.current_page)

        elif self.current_mode == self.MODE_GRID:
            # Переносим всё, что уже в кэше
            for page_index, pixmap in list(self.page_cache.items()):
                self.grid_view.display_page(page_index, pixmap)
            self.grid_view.load_initial_pages()

        elif self.current_mode == self.MODE_FEED:
            # Передаём уже загруженные страницы в ленту
            for page_index, pixmap in list(self.page_cache.items()):
                self.feed_view.set_pixmap(page_index, pixmap)
            # Прокручиваем к текущей странице
            self.feed_view.goto_page(self.current_page)

    # ---------- загрузка страниц ----------

    def _request_page_load(self, page_index: int):
        if page_index not in self._loading_pages:
            self._loading_pages.add(page_index)
            self.loader.clear_queue()
            self.loader.add_to_queue(page_index, priority=0)

    def _on_load_more_pages(self, pages_to_load: list):
        """Из режима Сетка: запрос на загрузку видимых миниатюр."""
        for idx in pages_to_load:
            if idx in self.page_cache:
                self.grid_view.display_page(idx, self.page_cache[idx])
            elif idx not in self._loading_pages:
                self._loading_pages.add(idx)
                self.loader.add_to_queue(
                    idx, priority=abs(idx - self.current_page)
                )

    def _on_feed_request_pages(self, pages_to_load: list):
        """Из режима Лента: запрос на загрузку страниц."""
        for idx in pages_to_load:
            if idx not in self._loading_pages:
                self._loading_pages.add(idx)
                # Приоритет по удалённости от текущей
                self.loader.add_to_queue(
                    idx, priority=abs(idx - self.current_page)
                )

    def _on_page_loaded(self, page_index: int, qimage: QImage):
        if self._closing:
            return
        self._loading_pages.discard(page_index)
        pixmap = QPixmap.fromImage(qimage)

        # ВСЕГДА отдаём страницу в ленту — она снимет свой _loading
        # и обновит отрисовку, если пользователь снова откроет ленту.
        try:
            self.feed_view.set_pixmap(page_index, pixmap)
        except Exception:
            pass

        if self.current_mode != self.MODE_FEED:
            self.page_cache[page_index] = pixmap

        if self.current_mode == self.MODE_SINGLE:
            if page_index == self._requested_page:
                self.single_view.display_page(page_index, pixmap)
                self.preload_pages(page_index)
                self.save_progress()
        elif self.current_mode == self.MODE_GRID:
            self.grid_view.display_page(page_index, pixmap)

    def _on_load_error(self, page_index: int, error_msg: str):
        if self._closing:
            return
        self._loading_pages.discard(page_index)
        if self.current_mode == self.MODE_SINGLE \
                and page_index == self._requested_page:
            self.single_view.show_error(error_msg)

    # ---------- навигация по страницам ----------

    def show_page(self, page_index: int):
        if not 0 <= page_index < self.total_pages:
            return
        self.current_page = page_index
        self._requested_page = page_index
        self._increment_view_count()
        self._update_ui(page_index)

        if self.current_mode == self.MODE_SINGLE:
            self._show_single_page(page_index)
        elif self.current_mode == self.MODE_FEED:
            self.feed_view.goto_page(page_index)

    def _show_single_page(self, page_index: int):
        if page_index in self.page_cache:
            self.single_view.display_page(
                page_index, self.page_cache[page_index]
            )
            self.preload_pages(page_index)
            return
        self.single_view.show_loading()
        if page_index not in self._loading_pages:
            self._loading_pages.add(page_index)
            self.loader.clear_queue()
            self.loader.add_to_queue(page_index, priority=0)

    def _update_ui(self, page_index: int):
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(page_index + 1)
        self.page_spin.blockSignals(False)

        self.progress_slider.blockSignals(True)
        self.progress_slider.setValue(page_index)
        self.progress_slider.blockSignals(False)

        self.btn_prev.setEnabled(page_index > 0)
        self.btn_next.setEnabled(page_index < self.total_pages - 1)

    def preload_pages(self, page_index: int):
        keep_range = range(max(0, page_index - 2),
                           min(self.total_pages, page_index + 3))
        if self.current_mode == self.MODE_SINGLE:
            for k in [k for k in self.page_cache if k not in keep_range]:
                del self.page_cache[k]

        for offset in range(1, 3):
            for idx in (page_index + offset, page_index - offset):
                if 0 <= idx < self.total_pages and idx not in self.page_cache \
                        and idx not in self._loading_pages:
                    self._loading_pages.add(idx)
                    self.loader.add_to_queue(idx, priority=offset)

    def prev_page(self):
        if self.current_mode == self.MODE_GRID:
            return
        self.show_page(self.current_page - 1)

    def next_page(self):
        if self.current_mode == self.MODE_GRID:
            return
        self.show_page(self.current_page + 1)

    def go_to_page(self, page_number: int):
        page_index = page_number - 1
        if 0 <= page_index < self.total_pages:
            self.show_page(page_index)

    def on_slider_changed(self, value: int):
        if value != self.current_page:
            self.show_page(value)

    # ---------- сетка и лента ----------

    def _on_grid_page_selected(self, page_index: int):
        self.current_mode = self.MODE_SINGLE
        idx = self.mode_combo.findData(self.MODE_SINGLE)
        if idx < 0:
            idx = 0
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.blockSignals(False)
        self.mode_stack.setCurrentIndex(self.MODE_SINGLE)
        self._update_controls_visibility()
        self._save_mode_to_db()

        self.current_page = page_index
        self._update_ui(page_index)
        self._apply_mode_to_current_page(self.MODE_GRID)

    def _on_feed_page_changed(self, page_index: int):
        """Пользователь доскроллил до новой страницы в режиме Лента."""
        self.current_page = page_index
        self._requested_page = page_index
        self._increment_view_count()
        self._update_ui(page_index)
        self.save_progress()

    # ---------- сохранение ----------

    def _increment_view_count(self):
        if self._view_count_incremented or not self.db:
            return
        self._view_count_incremented = True
        try:
            comic = self.db.get_comic_by_path(self.file_path)
            if comic:
                self.db.increment_view_count(comic['id'])
        except Exception:
            pass

    def save_progress(self):
        if not self.db:
            return
        try:
            comic = self.db.get_comic_by_path(self.file_path)
            if comic:
                self.db.save_reading_progress(comic['id'], self.current_page)
        except Exception:
            pass

    def _save_mode_to_db(self):
        if not self.db:
            return
        try:
            comic = self.db.get_comic_by_path(self.file_path)
            if comic:
                self.db.save_reading_mode(comic['id'], self.current_mode)
        except Exception:
            pass

    # ---------- зум (для сетки) ----------

    def zoom_in(self):
        if self.current_mode == self.MODE_GRID:
            self._zoom_level = min(5.0, self._zoom_level * 1.2)
            self.grid_view.set_zoom(self._zoom_level)

    def zoom_out(self):
        if self.current_mode == self.MODE_GRID:
            self._zoom_level = max(0.5, self._zoom_level / 1.2)
            self.grid_view.set_zoom(self._zoom_level)

    def zoom_reset(self):
        if self.current_mode == self.MODE_GRID:
            self._zoom_level = 1.0
            self.grid_view.set_zoom(self._zoom_level)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier \
                and self.current_mode == self.MODE_GRID:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    # ---------- окно ----------

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left:
            self.prev_page()
        elif event.key() == Qt.Key_Right:
            self.next_page()
        elif event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._closing = True
        self.save_progress()
        self._save_mode_to_db()

        try:
            self.loader.stop()
        except Exception:
            pass

        if not self.loader.wait(3000):
            print("[reader] loader didn't stop in 3s, terminating")
            try:
                self.loader.terminate()
                self.loader.wait(500)
            except Exception as e:
                print(f"[reader] terminate: {e}")

        self.page_cache.clear()
        try:
            self.archive.close()
        except Exception:
            pass

        self.closed.emit()
        super().closeEvent(event)