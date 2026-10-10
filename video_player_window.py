import os

from PyQt5.QtCore import (Qt, pyqtSignal, QTimer, QUrl, QPoint, QObject,
                          QRunnable, QThreadPool)
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QSlider, QFrame, QShortcut, QMessageBox,
                             QStyle, QStyleOptionSlider, QScrollArea,
                             QSizePolicy)
from PyQt5.QtGui import QKeySequence, QPixmap, QImage

try:
    from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
    from PyQt5.QtMultimediaWidgets import QVideoWidget
    HAS_MULTIMEDIA = True
except ImportError:
    HAS_MULTIMEDIA = False
    QVideoWidget = None

from video_reader import extract_thumbnail, format_duration
import cover_cache


def _fmt_ms(ms):
    if not ms or ms < 0:
        return "0:00"
    s = ms // 1000
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


SIMILAR_THUMB_SIZE = (320, 180)


# ============================================================
# Кликабельный видеовиджет (пауза по клику)
# ============================================================

if HAS_MULTIMEDIA:
    class ClickableVideoWidget(QVideoWidget):
        """QVideoWidget с сигналом clicked — по клику ставим/снимаем паузу."""

        clicked = pyqtSignal()

        def mousePressEvent(self, event):
            if event.button() == Qt.LeftButton:
                self.clicked.emit()
            super().mousePressEvent(event)
else:
    ClickableVideoWidget = None


# ============================================================
# Кликабельный слайдер (перемотка по клику)
# ============================================================

class ClickableSlider(QSlider):
    """QSlider, который при клике на полоску перескакивает в эту позицию."""

    clicked_value = pyqtSignal(int)

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setPageStep(5000)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.maximum() > self.minimum():
            val = self._value_from_pos(event.pos())
            if val is not None:
                self.setValue(val)
                self.clicked_value.emit(val)
                event.accept()
                return
        super().mousePressEvent(event)

    def _value_from_pos(self, pos: QPoint):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self
        )
        handle = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self
        )
        if self.orientation() == Qt.Horizontal:
            groove_start = groove.x()
            groove_length = groove.width() - handle.width()
            if groove_length <= 0:
                return None
            x = pos.x() - groove_start - handle.width() // 2
            x = max(0, min(groove_length, x))
            span = self.maximum() - self.minimum()
            return self.minimum() + int(round(span * x / groove_length))
        else:
            groove_start = groove.y()
            groove_length = groove.height() - handle.height()
            if groove_length <= 0:
                return None
            y = pos.y() - groove_start - handle.height() // 2
            y = max(0, min(groove_length, y))
            span = self.maximum() - self.minimum()
            return self.minimum() + int(round(span * y / groove_length))


# ============================================================
# Загрузчик превью для мини-карточек
# ============================================================

class _MiniThumbSignals(QObject):
    loaded = pyqtSignal(str, QImage)
    failed = pyqtSignal(str)


class MiniThumbLoader(QRunnable):
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.signals = _MiniThumbSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            cached = cover_cache.load(self.file_path, SIMILAR_THUMB_SIZE)
            if cached is not None and not cached.isNull():
                self.signals.loaded.emit(self.file_path, cached)
                return
            img = extract_thumbnail(self.file_path, SIMILAR_THUMB_SIZE)
            if img is not None and not img.isNull():
                try:
                    cover_cache.save(self.file_path, SIMILAR_THUMB_SIZE, img)
                except Exception:
                    pass
                self.signals.loaded.emit(self.file_path, img)
            else:
                self.signals.failed.emit(self.file_path)
        except Exception:
            self.signals.failed.emit(self.file_path)


# ============================================================
# Мини-карточка похожего видео
# ============================================================

class MiniVideoCard(QWidget):
    """Кликабельная карточка похожего видео."""

    clicked = pyqtSignal(str)

    CARD_W = 240
    CARD_H = 72
    THUMB_W = 112
    THUMB_H = 63

    DEFAULT_STYLE = """
        MiniVideoCard {
            background-color: #161616;
            border: 1px solid #222;
            border-radius: 6px;
        }
    """
    HOVER_STYLE = """
        MiniVideoCard {
            background-color: #1f1f1f;
            border: 1px solid #c0392b;
            border-radius: 6px;
        }
    """

    def __init__(self, video: dict, parent=None):
        super().__init__(parent)
        self.video = video
        self.file_path = video.get('file_path', '')

        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(self.DEFAULT_STYLE)
        self.setMouseTracking(True)

        layout = QHBoxLayout()
        layout.setContentsMargins(4, 4, 6, 4)
        layout.setSpacing(6)

        self.thumb = QLabel("🎬")
        self.thumb.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("""
            QLabel { background: #0d0d0d; color: #555;
                     border-radius: 4px; font-size: 20px; }
        """)
        layout.addWidget(self.thumb)

        right = QVBoxLayout()
        right.setContentsMargins(0, 2, 0, 2)
        right.setSpacing(2)

        title = str(video.get('title', '') or '')
        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.title_label.setStyleSheet(
            "QLabel { color: #ffffff; font-size: 12px; font-weight: bold;"
            " background: transparent; }"
        )
        right.addWidget(self.title_label)

        match_count = int(video.get('match_count', 0) or 0)
        watches = int(video.get('watch_count', 0) or 0)

        parts = []
        if match_count > 0:
            if match_count == 1:
                parts.append("1 общий тег")
            else:
                parts.append(f"{match_count} общих тегов")
        parts.append(f"▶ {watches}")

        self.meta_label = QLabel("  ·  ".join(parts))
        self.meta_label.setStyleSheet(
            "QLabel { color: #888; font-size: 10px; background: transparent; }"
        )
        right.addWidget(self.meta_label)

        right.addStretch()
        layout.addLayout(right, 1)

        self.setLayout(layout)

    def set_thumbnail(self, qimage: QImage):
        if qimage is None or qimage.isNull():
            return
        pix = QPixmap.fromImage(qimage)
        if pix.isNull():
            return
        scaled = pix.scaled(self.thumb.width(), self.thumb.height(),
                            Qt.KeepAspectRatioByExpanding,
                            Qt.SmoothTransformation)
        try:
            self.thumb.setPixmap(scaled)
            self.thumb.setText("")
        except RuntimeError:
            pass

    def enterEvent(self, event):
        self.setStyleSheet(self.HOVER_STYLE)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self.DEFAULT_STYLE)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.file_path:
            self.clicked.emit(self.file_path)


# ============================================================
# Панель похожих видео
# ============================================================

class SimilarVideosPanel(QWidget):
    """Правая сворачиваемая панель со списком похожих видео."""

    video_selected = pyqtSignal(str)

    PANEL_WIDTH = 264

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._cards = {}
        self._thumb_pool = QThreadPool(self)
        self._thumb_pool.setMaxThreadCount(2)
        self._pending = {}
        self._current_video_id = None

        self.setFixedWidth(self.PANEL_WIDTH)
        self.setStyleSheet("""
            SimilarVideosPanel {
                background-color: #0d0d0d;
                border-left: 1px solid #222;
            }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("🔗 Похожие")
        title.setStyleSheet(
            "QLabel { color: #ffffff; font-size: 13px; font-weight: bold; }"
        )
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "QLabel { color: #666; font-size: 11px; padding: 2px 0; }"
        )
        layout.addWidget(self.status_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("""
            QScrollArea { border: none; background: #0d0d0d; }
            QScrollBar:vertical {
                background: #1a1a1a; width: 8px; border: none;
            }
            QScrollBar::handle:vertical {
                background: #333; border-radius: 4px; min-height: 20px;
            }
        """)

        self.content = QWidget()
        self.content.setStyleSheet("QWidget { background: #0d0d0d; }")
        self.list_layout = QVBoxLayout()
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.content.setLayout(self.list_layout)

        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

        self.setLayout(layout)

    # ---------- public ----------

    def set_current_video(self, video_id):
        """Перезагружает список похожих для указанного видео."""
        self._current_video_id = video_id
        self._clear()
        if video_id is None:
            return
        try:
            items = self.db.get_similar_videos(video_id, limit=20)
        except Exception as e:
            print(f"[similar] get_similar_videos: {e}")
            items = []

        if not items:
            self.status_label.setText("Похожих видео не найдено")
            return

        self.status_label.setText(f"Найдено: {len(items)}")
        for video in items:
            card = MiniVideoCard(video)
            card.clicked.connect(self.video_selected.emit)
            self.list_layout.addWidget(card)
            self._cards[video['file_path']] = card
            self._request_thumb(video, card)
        self.list_layout.addStretch()

    # ---------- внутреннее ----------

    def _clear(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._cards.clear()
        self._pending.clear()

    def _request_thumb(self, video, card):
        fp = video.get('file_path')
        if not fp:
            return

        cached = cover_cache.load(fp, SIMILAR_THUMB_SIZE)
        if cached is not None and not cached.isNull():
            card.set_thumbnail(cached)
            return

        if fp in self._pending:
            self._pending[fp].append(card)
            return
        self._pending[fp] = [card]

        loader = MiniThumbLoader(fp)
        loader.signals.loaded.connect(self._on_thumb_loaded)
        loader.signals.failed.connect(self._on_thumb_failed)
        self._thumb_pool.start(loader)

    def _on_thumb_loaded(self, fp, qimage):
        waiters = self._pending.pop(fp, [])
        for card in waiters:
            try:
                card.set_thumbnail(qimage)
            except RuntimeError:
                pass

    def _on_thumb_failed(self, fp):
        self._pending.pop(fp, None)

    def closeEvent(self, event):
        try:
            self._thumb_pool.clear()
        except Exception:
            pass
        super().closeEvent(event)


# ============================================================
# Плеер
# ============================================================

class VideoPlayerWindow(QWidget):
    """Окно просмотра видео с навигацией по плейлисту и режимом повтора."""

    closed = pyqtSignal()

    AUTOSAVE_INTERVAL_MS = 5000

    def __init__(self, file_path, db=None, playlist=None, playlist_index=0):
        super().__init__()
        self.db = db

        if playlist:
            self.playlist = list(playlist)
        else:
            self.playlist = [file_path]

        if 0 <= playlist_index < len(self.playlist):
            self.playlist_index = playlist_index
        else:
            self.playlist_index = 0

        if self.playlist[self.playlist_index] != file_path:
            if file_path in self.playlist:
                self.playlist_index = self.playlist.index(file_path)
            else:
                self.playlist = [file_path]
                self.playlist_index = 0

        self.file_path = self.playlist[self.playlist_index]

        self._view_counted = False
        self._pending_seek_ms = 0
        self._suppress_error = False
        self._closing = False
        self._loop_enabled = False
        self._error_shown = False

        if not HAS_MULTIMEDIA:
            QMessageBox.critical(self, "Ошибка",
                                 "QtMultimedia недоступен. "
                                 "Установите PyQt5 полностью.")
            QTimer.singleShot(0, self.close)
            return

        self._build_ui()
        self._create_player()
        self._connect_signals()

        self._load_video_at(self.playlist_index, suppress_errors=False)

    # ---------- UI ----------

    def _build_ui(self):
        self.setWindowTitle("Просмотр видео")
        self.resize(1100, 700)
        self.setStyleSheet("QWidget { background-color: #0a0a0a; color: #e0e0e0; }")

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(15, 10, 15, 10)

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(40, 40)
        self.btn_close.setToolTip("Закрыть (Esc)")
        self.btn_close.setStyleSheet(self._btn_style())
        self.btn_close.clicked.connect(self.close)
        top.addWidget(self.btn_close)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("QLabel { color: #fff; font-size: 14px; }")
        self.title_label.setMaximumWidth(500)
        top.addWidget(self.title_label)

        top.addStretch()

        self.index_label = QLabel("")
        self.index_label.setStyleSheet("QLabel { color: #888; font-size: 13px; }")
        top.addWidget(self.index_label)

        top.addSpacing(10)

        self.btn_similar = QPushButton("🔗")
        self.btn_similar.setFixedSize(40, 40)
        self.btn_similar.setCheckable(True)
        self.btn_similar.setToolTip("Похожие видео (R)")
        self.btn_similar.setStyleSheet(self._toggle_style(False))
        self.btn_similar.clicked.connect(self.toggle_similar_panel)
        top.addWidget(self.btn_similar)

        root.addLayout(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #2a2a2a;")
        root.addWidget(sep)

        # Центральная область: видео + панель похожих
        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.setSpacing(0)

        self.video_widget = ClickableVideoWidget()
        self.video_widget.clicked.connect(self.toggle_play)
        center_row.addWidget(self.video_widget, 1)

        self.similar_panel = SimilarVideosPanel(self.db)
        self.similar_panel.video_selected.connect(self._open_similar_video)
        self.similar_panel.setVisible(False)
        center_row.addWidget(self.similar_panel)

        root.addLayout(center_row, 1)

        bottom = QVBoxLayout()
        bottom.setContentsMargins(15, 10, 15, 15)
        bottom.setSpacing(8)

        self.slider = ClickableSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #2a2a2a; height: 6px; border-radius: 3px;
            }
            QSlider::sub-page:horizontal { background: #c0392b; border-radius: 3px; }
            QSlider::handle:horizontal {
                background: #c0392b; width: 14px; height: 14px;
                margin: -4px 0; border-radius: 7px;
            }
            QSlider::handle:horizontal:hover { background: #e74c3c; }
        """)
        self.slider.sliderMoved.connect(self._on_seek)
        self.slider.clicked_value.connect(self._on_seek)
        bottom.addWidget(self.slider)

        ctrl = QHBoxLayout()

        self.btn_prev_video = QPushButton("⏮")
        self.btn_prev_video.setFixedSize(45, 40)
        self.btn_prev_video.setToolTip("Предыдущее видео (P / PageUp)")
        self.btn_prev_video.setStyleSheet(self._btn_style())
        self.btn_prev_video.clicked.connect(self.go_to_prev)
        ctrl.addWidget(self.btn_prev_video)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(50, 40)
        self.btn_play.setToolTip("Play/Pause (Space)")
        self.btn_play.setStyleSheet(self._btn_style())
        self.btn_play.clicked.connect(self.toggle_play)
        ctrl.addWidget(self.btn_play)

        self.btn_next_video = QPushButton("⏭")
        self.btn_next_video.setFixedSize(45, 40)
        self.btn_next_video.setToolTip("Следующее видео (N / PageDown)")
        self.btn_next_video.setStyleSheet(self._btn_style())
        self.btn_next_video.clicked.connect(self.go_to_next)
        ctrl.addWidget(self.btn_next_video)

        self.btn_loop = QPushButton("🔁")
        self.btn_loop.setFixedSize(45, 40)
        self.btn_loop.setCheckable(True)
        self.btn_loop.setToolTip("Повтор видео по окончании (L)")
        self.btn_loop.setStyleSheet(self._loop_style(False))
        self.btn_loop.clicked.connect(self.toggle_loop)
        ctrl.addWidget(self.btn_loop)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setStyleSheet(
            "QLabel { color: #e0e0e0; font-size: 13px; padding-left: 10px; }"
        )
        ctrl.addWidget(self.time_label)

        ctrl.addStretch()

        vol_label = QLabel("🔊")
        vol_label.setStyleSheet("QLabel { color: #e0e0e0; }")
        ctrl.addWidget(vol_label)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(120)
        ctrl.addWidget(self.volume_slider)

        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setFixedSize(40, 40)
        self.btn_fullscreen.setToolTip("Полный экран (F11)")
        self.btn_fullscreen.setStyleSheet(self._btn_style())
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        ctrl.addWidget(self.btn_fullscreen)

        bottom.addLayout(ctrl)
        root.addLayout(bottom)

        self.setLayout(root)

        # Хоткеи
        QShortcut(QKeySequence(Qt.Key_Space), self, self.toggle_play)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.close)
        QShortcut(QKeySequence(Qt.Key_F11), self, self.toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key_Left),
                  self, lambda: self._seek_rel(-5000))
        QShortcut(QKeySequence(Qt.Key_Right),
                  self, lambda: self._seek_rel(5000))

        QShortcut(QKeySequence(Qt.Key_N), self, self.go_to_next)
        QShortcut(QKeySequence(Qt.Key_P), self, self.go_to_prev)
        QShortcut(QKeySequence(Qt.Key_PageDown), self, self.go_to_next)
        QShortcut(QKeySequence(Qt.Key_PageUp), self, self.go_to_prev)
        QShortcut(QKeySequence("Ctrl+Right"), self, self.go_to_next)
        QShortcut(QKeySequence("Ctrl+Left"), self, self.go_to_prev)

        QShortcut(QKeySequence(Qt.Key_L), self, self.toggle_loop)
        QShortcut(QKeySequence(Qt.Key_R), self, self.toggle_similar_panel)

    @staticmethod
    def _btn_style():
        return """
            QPushButton {
                background-color: #2a2a2a; color: #e0e0e0;
                border: none; border-radius: 5px; font-size: 16px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:pressed { background-color: #c0392b; }
            QPushButton:disabled { color: #555; background-color: #1a1a1a; }
        """

    @staticmethod
    def _loop_style(active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background-color: #c0392b; color: #ffffff;
                    border: none; border-radius: 5px; font-size: 16px;
                }
                QPushButton:hover { background-color: #e74c3c; }
            """
        return """
            QPushButton {
                background-color: #2a2a2a; color: #e0e0e0;
                border: none; border-radius: 5px; font-size: 16px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """

    @staticmethod
    def _toggle_style(active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background-color: #c0392b; color: #ffffff;
                    border: none; border-radius: 5px; font-size: 16px;
                }
                QPushButton:hover { background-color: #e74c3c; }
            """
        return """
            QPushButton {
                background-color: #2a2a2a; color: #e0e0e0;
                border: none; border-radius: 5px; font-size: 16px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """

    def _create_player(self):
        self.player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.player.setVideoOutput(self.video_widget)
        self.volume_slider.valueChanged.connect(self.player.setVolume)

        self._save_timer = QTimer(self)
        self._save_timer.setInterval(self.AUTOSAVE_INTERVAL_MS)
        self._save_timer.timeout.connect(self._auto_save)

    def _connect_signals(self):
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.stateChanged.connect(self._on_state)
        self.player.error.connect(self._on_error)
        self.player.mediaStatusChanged.connect(self._on_media_status)

    # ---------- панель похожих ----------

    def toggle_similar_panel(self):
        visible = not self.similar_panel.isVisible()
        self.similar_panel.setVisible(visible)
        self.btn_similar.setChecked(visible)
        self.btn_similar.setStyleSheet(self._toggle_style(visible))
        if visible:
            self._reload_similar()

    def _reload_similar(self):
        if not self.db or not self.similar_panel.isVisible():
            return
        video_id = None
        try:
            v = self.db.get_video_by_path(self.file_path)
            if v:
                video_id = v['id']
        except Exception:
            pass
        try:
            self.similar_panel.set_current_video(video_id)
        except Exception as e:
            print(f"[similar] reload: {e}")

    def _open_similar_video(self, file_path: str):
        if not file_path or file_path == self.file_path:
            return
        if file_path in self.playlist:
            idx = self.playlist.index(file_path)
            self._load_video_at(idx, suppress_errors=True)
        else:
            self.playlist = [file_path]
            self.playlist_index = 0
            self._load_video_at(0, suppress_errors=True)

    # ---------- загрузка файла ----------

    def _load_video_at(self, index, suppress_errors=True):
        if not (0 <= index < len(self.playlist)):
            return

        self._save_progress_now()

        self.playlist_index = index
        self.file_path = self.playlist[index]
        self._view_counted = False
        self._suppress_error = suppress_errors
        self._error_shown = False

        title = os.path.splitext(os.path.basename(self.file_path))[0]
        self.title_label.setText(title)
        self.setWindowTitle(f"Просмотр: {title}")
        self.index_label.setText(f"{index + 1} / {len(self.playlist)}")

        start_ms = 0
        if self.db:
            try:
                v = self.db.get_video_by_path(self.file_path)
                if v:
                    start_ms = int(v.get('last_position', 0) or 0)
            except Exception:
                pass
        self._pending_seek_ms = start_ms if start_ms > 5000 else 0

        self._update_nav_buttons()

        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.time_label.setText("0:00 / 0:00")

        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(self.file_path)))
        self.player.setVolume(self.volume_slider.value())
        self.player.play()

        if suppress_errors:
            QTimer.singleShot(500, self._release_suppress)

        self._increment_watch_count()

        # Обновляем панель похожих, если она открыта
        if self.similar_panel.isVisible():
            QTimer.singleShot(50, self._reload_similar)

    def _release_suppress(self):
        self._suppress_error = False

    def _update_nav_buttons(self):
        self.btn_prev_video.setEnabled(self.playlist_index > 0)
        self.btn_next_video.setEnabled(
            self.playlist_index < len(self.playlist) - 1
        )

    # ---------- навигация ----------

    def go_to_next(self):
        if self.playlist_index < len(self.playlist) - 1:
            self._load_video_at(self.playlist_index + 1)

    def go_to_prev(self):
        if self.playlist_index > 0:
            self._load_video_at(self.playlist_index - 1)

    # ---------- повтор ----------

    def toggle_loop(self):
        self._loop_enabled = not self._loop_enabled
        self.btn_loop.setChecked(self._loop_enabled)
        self.btn_loop.setStyleSheet(self._loop_style(self._loop_enabled))

    def _restart_current(self):
        try:
            self.player.setPosition(0)
            self.player.play()
        except Exception:
            pass

    # ---------- плеер ----------

    def _on_media_status(self, status):
        if status == QMediaPlayer.LoadedMedia:
            self._suppress_error = False
            self._error_shown = False
            if self._pending_seek_ms > 0:
                self.player.setPosition(self._pending_seek_ms)
                self._pending_seek_ms = 0
        elif status == QMediaPlayer.EndOfMedia:
            if self._loop_enabled:
                self._restart_current()
            elif self.playlist_index < len(self.playlist) - 1:
                self.go_to_next()

    def _increment_watch_count(self):
        if self._view_counted or not self.db:
            return
        self._view_counted = True
        try:
            v = self.db.get_video_by_path(self.file_path)
            if v:
                self.db.increment_watch_count(v['id'])
        except Exception:
            pass

    def toggle_play(self):
        if not HAS_MULTIMEDIA:
            return
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_seek(self, value):
        self.player.setPosition(value)

    def _seek_rel(self, delta_ms):
        pos = max(0, self.player.position() + delta_ms)
        self.player.setPosition(pos)

    def _on_position(self, pos):
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        dur = self.player.duration() or 0
        self.time_label.setText(f"{_fmt_ms(pos)} / {_fmt_ms(dur)}")

    def _on_duration(self, dur):
        self.slider.setRange(0, max(0, dur))

    def _on_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self.btn_play.setText("⏸")
            if not self._save_timer.isActive():
                self._save_timer.start()
        else:
            self.btn_play.setText("▶")
            if self._save_timer.isActive():
                self._save_timer.stop()

    def _on_error(self, *_):
        if self._suppress_error or self._closing:
            return
        if self._error_shown:
            return
        self._error_shown = True
        QMessageBox.warning(
            self, "Ошибка воспроизведения",
            "Не удалось воспроизвести файл.\n"
            "Проверьте, что установлены кодеки "
            "(Media Foundation / K-Lite)."
        )

    # ---------- сохранение прогресса ----------

    def _save_progress_now(self):
        if not self.db or not HAS_MULTIMEDIA:
            return
        try:
            pos = self.player.position()
            dur = self.player.duration() or 0
            if dur > 0 and pos >= dur - 3000 and not self._loop_enabled:
                pos = 0
            v = self.db.get_video_by_path(self.file_path)
            if v:
                self.db.save_video_progress(v['id'], pos)
        except Exception:
            pass

    def _auto_save(self):
        if not HAS_MULTIMEDIA:
            return
        if self.player.state() != QMediaPlayer.PlayingState:
            return
        self._save_progress_now()

    # ---------- окно ----------

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_fullscreen()

    def closeEvent(self, event):
        self._closing = True
        self._save_progress_now()
        try:
            self.player.stop()
            self.player.setMedia(QMediaContent())
        except Exception:
            pass
        try:
            if self._save_timer.isActive():
                self._save_timer.stop()
        except Exception:
            pass
        try:
            self.similar_panel._thumb_pool.clear()
        except Exception:
            pass
        self.closed.emit()
        super().closeEvent(event)