import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import rarfile
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QIcon, QKeySequence
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QStackedWidget, QPushButton, QLabel,
                             QFrame, QGraphicsDropShadowEffect, QMessageBox,
                             QShortcut)

from paths import CONFIG_PATH, DB_PATH, ICON_PATH, LOG_PATH, UNRAR_PATH
from database import Database
from home_window import HomeWindow
from library_window import LibraryWindow
from tags_window import TagsWindow
from authors_window import AuthorsWindow
from settings_window import SettingsWindow, default_folders
from video_library_window import VideoLibraryWindow
from game_library_window import GameLibraryWindow
from tag_drop_panel import TagDropPanel
from remote_control_window import RemoteControlWindow


if getattr(sys, 'frozen', False):
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')
    if os.path.exists(UNRAR_PATH):
        rarfile.UNRAR_TOOL = UNRAR_PATH


def setup_logging():
    handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000,
                                  backupCount=3, encoding='utf-8')
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def _load_config_dict():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


class SideMenu(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(75)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(8)

        self.btn_home = self._create_menu_button("🏠", "Главная")
        self.btn_library = self._create_menu_button("📚", "Комиксы")
        self.btn_videos = self._create_menu_button("📹", "Видео")
        self.btn_games = self._create_menu_button("🎮", "Игры")
        self.btn_tags = self._create_menu_button("🏷️", "Теги")
        self.btn_authors = self._create_menu_button("👤", "Авторы")
        self.btn_settings = self._create_menu_button("⚙️", "Настройки")

        layout.addWidget(self.btn_home, 0, Qt.AlignHCenter)
        layout.addWidget(self.btn_library, 0, Qt.AlignHCenter)
        layout.addWidget(self.btn_videos, 0, Qt.AlignHCenter)
        layout.addWidget(self.btn_games, 0, Qt.AlignHCenter)
        layout.addWidget(self.btn_tags, 0, Qt.AlignHCenter)
        layout.addWidget(self.btn_authors, 0, Qt.AlignHCenter)
        layout.addStretch()
        layout.addWidget(self.btn_settings, 0, Qt.AlignHCenter)

        self.setLayout(layout)
        self.set_active(self.btn_home)

    def _create_menu_button(self, icon, tooltip):
        btn = QPushButton(icon)
        btn.setFixedSize(55, 55)
        btn.setToolTip(tooltip)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(8)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(QColor(0, 0, 0, 100))
        btn.setGraphicsEffect(shadow)
        return btn

    def _all_buttons(self):
        return (self.btn_home, self.btn_library, self.btn_videos,
                self.btn_games, self.btn_tags, self.btn_authors,
                self.btn_settings)

    def set_active(self, active_btn):
        for btn in self._all_buttons():
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a; color: #888888;
                    font-size: 24px; border-radius: 10px; border: none;
                }
                QPushButton:hover { background-color: #3a3a3a; color: #e0e0e0; }
            """)
        active_btn.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: #ffffff;
                font-size: 24px; border-radius: 10px; border: none;
            }
            QPushButton:hover { background-color: #e74c3c; }
        """)


class TopBar(QWidget):
    toggle_tags_panel = pyqtSignal()
    remote_clicked = pyqtSignal()

    def __init__(self, title="Home", parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)

        layout = QHBoxLayout()
        layout.setContentsMargins(20, 0, 20, 0)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            "QLabel { color: #ffffff; font-size: 20px; font-weight: bold; }"
        )
        layout.addWidget(self.title_label)
        layout.addStretch()

        self.btn_remote = QPushButton("🎛️")
        self.btn_remote.setFixedSize(40, 40)
        self.btn_remote.setToolTip("Пульт управления телефоном (Ctrl+R)")
        self.btn_remote.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border-radius: 20px; border: none; font-size: 18px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_remote.clicked.connect(self.remote_clicked.emit)
        layout.addWidget(self.btn_remote)

        self.btn_tags_panel = QPushButton("🏷️")
        self.btn_tags_panel.setFixedSize(40, 40)
        self.btn_tags_panel.setToolTip("Показать/скрыть панель тегов")
        self.btn_tags_panel.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border-radius: 20px; border: none; font-size: 18px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_tags_panel.clicked.connect(self.toggle_tags_panel.emit)
        layout.addWidget(self.btn_tags_panel)

        self.btn_search = QPushButton("🔍 Поиск и фильтры")
        self.btn_search.setFixedSize(180, 40)
        self.btn_search.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border-radius: 20px; border: none; font-size: 14px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        sh = QGraphicsDropShadowEffect()
        sh.setBlurRadius(8); sh.setXOffset(0); sh.setYOffset(2)
        sh.setColor(QColor(0, 0, 0, 100))
        self.btn_search.setGraphicsEffect(sh)

        layout.addWidget(self.btn_search)
        self.setLayout(layout)

    def set_title(self, title):
        self.title_label.setText(title)

    def set_search_visible(self, visible):
        self.btn_search.setVisible(visible)


class ComicReaderApp(QMainWindow):
    PAGE_HOME = 0
    PAGE_LIBRARY = 1
    PAGE_VIDEOS = 2
    PAGE_GAMES = 3
    PAGE_TAGS = 4
    PAGE_AUTHORS = 5
    PAGE_SETTINGS = 6

    def __init__(self):
        super().__init__()

        config = _load_config_dict()
        defs = default_folders()

        self.comics_folder = config.get('comics_folder') or defs['comics_folder']
        self.videos_folder = config.get('videos_folder') or defs['videos_folder']
        self.games_folder = config.get('games_folder') or defs['games_folder']

        for path in (self.comics_folder, self.videos_folder, self.games_folder):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception:
                pass

        self.db = Database(DB_PATH)
        self.colors = self.load_colors()

        self.setWindowTitle("LibVidGam")
        self.resize(1500, 900)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.side_menu = SideMenu()
        main_layout.addWidget(self.side_menu)

        self.separator = QFrame()
        self.separator.setFrameShape(QFrame.VLine)
        self.separator.setFrameShadow(QFrame.Plain)
        self.separator.setFixedWidth(2)
        self.separator.setStyleSheet(
            "QFrame { background-color: #2a2a2a; border: none; }"
        )
        sep_sh = QGraphicsDropShadowEffect()
        sep_sh.setBlurRadius(15); sep_sh.setXOffset(5); sep_sh.setYOffset(0)
        sep_sh.setColor(QColor(0, 0, 0, 150))
        self.separator.setGraphicsEffect(sep_sh)
        main_layout.addWidget(self.separator)

        content = QWidget()
        cl = QVBoxLayout()
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        self.top_bar = TopBar("Главная")
        cl.addWidget(self.top_bar)

        self.pages = QStackedWidget()

        self.home_page = HomeWindow(self.db)
        self.pages.addWidget(self.home_page)

        self._library_ph = QWidget()
        self._videos_ph = QWidget()
        self._games_ph = QWidget()
        self._tags_ph = QWidget()
        self._authors_ph = QWidget()
        self._settings_ph = QWidget()
        self.pages.addWidget(self._library_ph)
        self.pages.addWidget(self._videos_ph)
        self.pages.addWidget(self._games_ph)
        self.pages.addWidget(self._tags_ph)
        self.pages.addWidget(self._authors_ph)
        self.pages.addWidget(self._settings_ph)

        self.library_page = None
        self.video_library_page = None
        self.game_library_page = None
        self.tags_page = None
        self.authors_page = None
        self.settings_page = None

        self.remote_window = None

        cl.addWidget(self.pages)
        content.setLayout(cl)
        main_layout.addWidget(content, 1)

        self.tag_panel = TagDropPanel(self.db)
        self.tag_panel.setVisible(False)
        self.tag_panel.btn_close.clicked.connect(self.toggle_tags_panel)
        main_layout.addWidget(self.tag_panel)

        central.setLayout(main_layout)

        self.side_menu.btn_home.clicked.connect(
            lambda: self.switch_page(self.PAGE_HOME, "Главная"))
        self.side_menu.btn_library.clicked.connect(
            lambda: self.switch_page(self.PAGE_LIBRARY, "Комиксы"))
        self.side_menu.btn_videos.clicked.connect(
            lambda: self.switch_page(self.PAGE_VIDEOS, "Видео"))
        self.side_menu.btn_games.clicked.connect(
            lambda: self.switch_page(self.PAGE_GAMES, "Игры"))
        self.side_menu.btn_tags.clicked.connect(
            lambda: self.switch_page(self.PAGE_TAGS, "Теги"))
        self.side_menu.btn_authors.clicked.connect(
            lambda: self.switch_page(self.PAGE_AUTHORS, "Авторы"))
        self.side_menu.btn_settings.clicked.connect(
            lambda: self.switch_page(self.PAGE_SETTINGS, "Настройки"))

        self.top_bar.toggle_tags_panel.connect(self.toggle_tags_panel)
        self.top_bar.remote_clicked.connect(self.open_remote_control)
        self.top_bar.btn_search.clicked.connect(self._on_search_clicked)

        QShortcut(QKeySequence("Ctrl+R"), self, self.open_remote_control)

        self.home_page.comic_selected.connect(self.open_comic)
        self.home_page.video_selected.connect(self.open_video)
        self.home_page.game_selected.connect(self._launch_game_from_home)

        self.reader_windows = []
        self.player_windows = []

        self.apply_colors(self.colors)

    def closeEvent(self, event):
        for reader in list(self.reader_windows):
            try:
                reader.close()
            except Exception:
                pass
        for player in list(self.player_windows):
            try:
                player.close()
            except Exception:
                pass
        if self.remote_window is not None:
            try:
                self.remote_window.close()
            except Exception:
                pass

        try:
            self.db.close()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------- пульт ----------

    def open_remote_control(self):
        mobile_server = None
        if self.settings_page is not None:
            mobile_server = getattr(self.settings_page, '_mobile_server', None)

        if mobile_server is None:
            QMessageBox.information(
                self, "Пульт управления",
                "Сначала запустите мобильный сервер:\n"
                "Настройки → Мобильный доступ → «Запустить сервер»."
            )
            self.switch_page(self.PAGE_SETTINGS, "Настройки")
            return

        if self.remote_window is None:
            self.remote_window = RemoteControlWindow(
                self.db, mobile_server, self
            )
        self.remote_window.show()
        self.remote_window.raise_()
        self.remote_window.activateWindow()

    # ---------- ленивое создание страниц ----------

    def _read_hidden_tags(self):
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    return list(json.load(f).get('hidden_tags', []))
        except Exception:
            pass
        return []

    def _ensure_library_page(self):
        if self.library_page is not None:
            return
        self.library_page = LibraryWindow(self.db, self.comics_folder)
        self.library_page.comic_selected.connect(self.open_comic)
        self.pages.removeWidget(self._library_ph)
        self._library_ph.deleteLater()
        self._library_ph = None
        self.pages.insertWidget(self.PAGE_LIBRARY, self.library_page)
        self._apply_page_style(self.library_page)
        try:
            self.library_page.hidden_tags = self._read_hidden_tags()
        except Exception:
            pass

    def _ensure_videos_page(self):
        if self.video_library_page is not None:
            return
        self.video_library_page = VideoLibraryWindow(self.db, self.videos_folder)
        self.video_library_page.video_selected.connect(self.open_video)
        self.pages.removeWidget(self._videos_ph)
        self._videos_ph.deleteLater()
        self._videos_ph = None
        self.pages.insertWidget(self.PAGE_VIDEOS, self.video_library_page)
        self._apply_page_style(self.video_library_page)
        try:
            self.video_library_page.hidden_tags = self._read_hidden_tags()
        except Exception:
            pass

    def _ensure_games_page(self):
        if self.game_library_page is not None:
            return
        self.game_library_page = GameLibraryWindow(self.db, self.games_folder)
        self.pages.removeWidget(self._games_ph)
        self._games_ph.deleteLater()
        self._games_ph = None
        self.pages.insertWidget(self.PAGE_GAMES, self.game_library_page)
        self._apply_page_style(self.game_library_page)
        try:
            self.game_library_page.hidden_tags = self._read_hidden_tags()
        except Exception:
            pass

    def _ensure_tags_page(self):
        if self.tags_page is not None:
            return
        self.tags_page = TagsWindow(self.db)
        self.tags_page.comic_selected.connect(self.open_comic)
        self.pages.removeWidget(self._tags_ph)
        self._tags_ph.deleteLater()
        self._tags_ph = None
        self.pages.insertWidget(self.PAGE_TAGS, self.tags_page)
        self._apply_page_style(self.tags_page)
        try:
            self.tags_page.hidden_tags = self._read_hidden_tags()
        except Exception:
            pass

    def _ensure_authors_page(self):
        if self.authors_page is not None:
            return
        self.authors_page = AuthorsWindow(self.db)
        self.authors_page.comic_selected.connect(self.open_comic)
        self.pages.removeWidget(self._authors_ph)
        self._authors_ph.deleteLater()
        self._authors_ph = None
        self.pages.insertWidget(self.PAGE_AUTHORS, self.authors_page)
        self._apply_page_style(self.authors_page)

    def _ensure_settings_page(self):
        if self.settings_page is not None:
            return
        self.settings_page = SettingsWindow(self)
        self.pages.removeWidget(self._settings_ph)
        self._settings_ph.deleteLater()
        self._settings_ph = None
        self.pages.insertWidget(self.PAGE_SETTINGS, self.settings_page)

    def _apply_page_style(self, page):
        colors = self.colors
        bg = colors.get('background', '#121212')
        text = colors.get('text', '#e0e0e0')
        secondary = colors.get('secondary_text', '#888888')
        accent = colors.get('accent', '#c0392b')
        card_bg = colors.get('card_background', '#1e1e1e')
        border = colors.get('border', '#3a3a3a')

        page.setStyleSheet(f"""
            QWidget {{ background-color: {bg}; }}
            QLabel {{ color: {text}; }}
        """)

        if hasattr(page, 'btn_add'):
            page.btn_add.setStyleSheet(f"""
                QPushButton {{
                    background-color: {accent}; color: white;
                    border: none; border-radius: 20px; font-size: 14px;
                }}
                QPushButton:hover {{ background-color: {accent}dd; }}
            """)
        if hasattr(page, 'btn_scan'):
            page.btn_scan.setStyleSheet(f"""
                QPushButton {{
                    background-color: {card_bg}; color: {text};
                    border: none; border-radius: 20px; font-size: 14px;
                }}
                QPushButton:hover {{ background-color: {border}; }}
            """)
        if hasattr(page, 'btn_passwords'):
            page.btn_passwords.setStyleSheet(f"""
                QPushButton {{
                    background-color: {card_bg}; color: {text};
                    border: none; border-radius: 20px; font-size: 14px;
                }}
                QPushButton:hover {{ background-color: {border}; }}
            """)
        if hasattr(page, 'btn_manage_archives'):
            page.btn_manage_archives.setStyleSheet(f"""
                QPushButton {{
                    background-color: {card_bg}; color: {text};
                    border: none; border-radius: 20px; font-size: 14px;
                }}
                QPushButton:hover {{ background-color: {border}; }}
            """)
        if hasattr(page, 'btn_clear_filter'):
            page.btn_clear_filter.setStyleSheet(f"""
                QPushButton {{
                    background-color: {card_bg}; color: {text};
                    border: none; border-radius: 20px; font-size: 14px;
                }}
                QPushButton:hover {{ background-color: {border}; }}
            """)
        if hasattr(page, 'count_label'):
            page.count_label.setStyleSheet(
                f"QLabel {{ color: {secondary}; font-size: 14px; }}"
            )
        if hasattr(page, 'btn_add_tag'):
            page.btn_add_tag.setStyleSheet(f"""
                QPushButton {{
                    background-color: {accent}; color: white;
                    border: none; border-radius: 20px; font-size: 14px;
                }}
                QPushButton:hover {{ background-color: {accent}dd; }}
            """)
        if hasattr(page, 'btn_add_author'):
            page.btn_add_author.setStyleSheet(f"""
                QPushButton {{
                    background-color: {accent}; color: white;
                    border: none; border-radius: 20px; font-size: 14px;
                }}
                QPushButton:hover {{ background-color: {accent}dd; }}
            """)

    # ---------- навигация с фильтром ----------

    def navigate_to_filtered(self, library_key: str, kind: str, value: str):
        if not value:
            return

        try:
            if library_key == 'comics':
                self._ensure_library_page()
                lib = self.library_page
                if kind == 'tag':
                    items = self.db.search_comics(
                        include_tags=[value], folder=self.comics_folder)
                    search = {'include_tags': [value]}
                    title = f"🏷️ {value}"
                else:
                    items = self.db.search_comics(
                        author_query=value, folder=self.comics_folder)
                    search = {'author': value}
                    title = f"👤 {value}"
                lib._has_been_loaded = True
                lib.current_search = search
                lib.current_filter = search
                self.switch_page(self.PAGE_LIBRARY, title)
                lib.load_comics(items)
                try:
                    lib._update_clear_filter_button()
                except Exception:
                    pass

            elif library_key == 'videos':
                self._ensure_videos_page()
                lib = self.video_library_page
                if kind == 'tag':
                    items = self.db.search_videos(
                        include_tags=[value], folder=self.videos_folder)
                    search = {'include_tags': [value]}
                    title = f"🏷️ {value}"
                else:
                    items = self.db.search_videos(
                        author_query=value, folder=self.videos_folder)
                    search = {'author': value}
                    title = f"👤 {value}"
                lib._has_been_loaded = True
                lib.current_search = search
                lib.current_filter = search
                self.switch_page(self.PAGE_VIDEOS, title)
                lib.load_videos(items)
                try:
                    lib._update_clear_filter_button()
                except Exception:
                    pass

            elif library_key == 'games':
                self._ensure_games_page()
                lib = self.game_library_page
                if kind == 'tag':
                    items = self.db.search_games(
                        include_tags=[value], folder=self.games_folder)
                    search = {'include_tags': [value]}
                    title = f"🏷️ {value}"
                else:
                    items = self.db.search_games(
                        author_query=value, folder=self.games_folder)
                    search = {'author': value}
                    title = f"👤 {value}"
                lib._has_been_loaded = True
                lib.current_search = search
                lib.current_filter = search
                self.switch_page(self.PAGE_GAMES, title)
                lib.load_games(items)
                try:
                    lib._update_clear_filter_button()
                except Exception:
                    pass
        except Exception as e:
            print(f"[navigate_to_filtered] {e}")

    def count_in_libraries(self, kind: str, value: str) -> dict:
        result = {'comics': 0, 'videos': 0, 'games': 0}
        if not value:
            return result
        try:
            if kind == 'tag':
                result['comics'] = len(self.db.search_comics(
                    include_tags=[value], folder=self.comics_folder))
                result['videos'] = len(self.db.search_videos(
                    include_tags=[value], folder=self.videos_folder))
                result['games'] = len(self.db.search_games(
                    include_tags=[value], folder=self.games_folder))
            else:
                result['comics'] = len(self.db.search_comics(
                    author_query=value, folder=self.comics_folder))
                result['videos'] = len(self.db.search_videos(
                    author_query=value, folder=self.videos_folder))
                result['games'] = len(self.db.search_games(
                    author_query=value, folder=self.games_folder))
        except Exception as e:
            print(f"[count_in_libraries] {e}")
        return result

    # ---------- restart ----------

    def restart_after_import(self):
        try:
            self.db.close()
        except Exception:
            pass

        import subprocess

        try:
            if getattr(sys, 'frozen', False):
                cmd = [sys.executable]
                cwd = os.path.dirname(sys.executable)
            else:
                script = os.path.abspath(sys.argv[0]) if sys.argv else ''
                cmd = [sys.executable] + list(sys.argv)
                cwd = os.path.dirname(script) if script else os.getcwd()
        except Exception as e:
            print(f"[restart] build cmd failed: {e}")
            QMessageBox.critical(
                self, "Ошибка перезапуска",
                f"Не удалось собрать команду перезапуска:\n{e}\n\n"
                "Закройте и запустите вручную."
            )
            return

        try:
            subprocess.Popen(cmd, cwd=cwd)
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка перезапуска",
                f"Не удалось перезапустить приложение:\n{e}\n\n"
                "Закройте и запустите вручную."
            )
            return

        QApplication.quit()

    # ---------- цвета ----------

    def load_colors(self):
        defaults = {
            'accent': '#c0392b', 'background': '#121212', 'panel': '#1e1e1e',
            'text': '#e0e0e0', 'secondary_text': '#888888',
            'menu_text': '#ffffff', 'card_background': '#1e1e1e',
            'border': '#3a3a3a',
        }
        config = _load_config_dict()
        defaults.update({k: v for k, v in config.items() if k in defaults})
        return defaults

    def apply_colors(self, colors):
        self.colors = colors
        bg = colors.get('background', '#121212')
        panel = colors.get('panel', '#1e1e1e')
        text = colors.get('text', '#e0e0e0')
        menu_text = colors.get('menu_text', '#ffffff')
        card_bg = colors.get('card_background', '#1e1e1e')
        border = colors.get('border', '#3a3a3a')

        self.setStyleSheet(f"QMainWindow {{ background-color: {bg}; }}")
        self.side_menu.setStyleSheet(f"QWidget {{ background-color: {panel}; }}")
        self.separator.setStyleSheet(
            f"QFrame {{ background-color: {border}; border: none; }}"
        )
        self.top_bar.setStyleSheet(
            f"QWidget {{ background-color: {panel}; "
            f"border-bottom: 1px solid {border}; }}"
        )
        self.top_bar.title_label.setStyleSheet(
            f"QLabel {{ color: {menu_text}; font-size: 20px; font-weight: bold; }}"
        )
        self.top_bar.btn_search.setStyleSheet(f"""
            QPushButton {{
                background-color: {card_bg}; color: {text};
                border-radius: 20px; border: none; font-size: 14px;
            }}
            QPushButton:hover {{ background-color: {border}; }}
        """)
        self.top_bar.btn_tags_panel.setStyleSheet(f"""
            QPushButton {{
                background-color: {card_bg}; color: {text};
                border-radius: 20px; border: none; font-size: 18px;
            }}
            QPushButton:hover {{ background-color: {border}; }}
        """)
        self.top_bar.btn_remote.setStyleSheet(f"""
            QPushButton {{
                background-color: {card_bg}; color: {text};
                border-radius: 20px; border: none; font-size: 18px;
            }}
            QPushButton:hover {{ background-color: {border}; }}
        """)
        self.pages.setStyleSheet(f"QStackedWidget {{ background-color: {bg}; }}")

        for page in (self.library_page, self.video_library_page,
                     self.game_library_page, self.tags_page,
                     self.authors_page):
            if page is not None:
                self._apply_page_style(page)

    # ---------- home ----------

    def reload_home(self):
        try:
            config = _load_config_dict()
            tag = (config.get('featured_tag', '') or '').strip()
        except Exception:
            tag = ''
        self.home_page.featured_tag = tag
        self.home_page.refresh()

    # ---------- hidden tags ----------

    def reload_hidden_tags(self):
        hidden = self._read_hidden_tags()
        for page in (self.library_page, self.video_library_page,
                     self.game_library_page, self.tags_page):
            if page is None:
                continue
            try:
                page.set_hidden_tags(hidden)
            except Exception:
                pass

    # ---------- folders ----------

    def reload_folders(self):
        config = _load_config_dict()
        defs = default_folders()

        new_comics = config.get('comics_folder') or defs['comics_folder']
        new_videos = config.get('videos_folder') or defs['videos_folder']
        new_games = config.get('games_folder') or defs['games_folder']

        for path in (new_comics, new_videos, new_games):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception:
                pass

        self.comics_folder = new_comics
        self.videos_folder = new_videos
        self.games_folder = new_games

        if self.library_page is not None:
            self.library_page.set_folder(self.comics_folder)
        if self.video_library_page is not None:
            self.video_library_page.set_folder(self.videos_folder)
        if self.game_library_page is not None:
            self.game_library_page.set_folder(self.games_folder)

    # ---------- tags panel ----------

    def toggle_tags_panel(self):
        visible = not self.tag_panel.isVisible()
        self.tag_panel.setVisible(visible)
        if visible:
            self.tag_panel.refresh()

    # ---------- navigation ----------

    def switch_page(self, index, title):
        if index == self.PAGE_LIBRARY:
            self._ensure_library_page()
        elif index == self.PAGE_VIDEOS:
            self._ensure_videos_page()
        elif index == self.PAGE_GAMES:
            self._ensure_games_page()
        elif index == self.PAGE_TAGS:
            self._ensure_tags_page()
        elif index == self.PAGE_AUTHORS:
            self._ensure_authors_page()
        elif index == self.PAGE_SETTINGS:
            self._ensure_settings_page()

        self.pages.setCurrentIndex(index)
        self.top_bar.set_title(title)
        self.top_bar.set_search_visible(index in (self.PAGE_LIBRARY,
                                                  self.PAGE_VIDEOS,
                                                  self.PAGE_GAMES))

        active = [self.side_menu.btn_home, self.side_menu.btn_library,
                  self.side_menu.btn_videos, self.side_menu.btn_games,
                  self.side_menu.btn_tags, self.side_menu.btn_authors,
                  self.side_menu.btn_settings][index]
        self.side_menu.set_active(active)

        if index == self.PAGE_HOME:
            if not self.home_page._has_been_loaded:
                self.home_page.refresh()
        elif index == self.PAGE_LIBRARY and self.library_page is not None:
            if not self.library_page._has_been_loaded:
                self.library_page._initial_load()
        elif index == self.PAGE_VIDEOS and self.video_library_page is not None:
            if not self.video_library_page._has_been_loaded:
                self.video_library_page._initial_load()
        elif index == self.PAGE_GAMES and self.game_library_page is not None:
            if not self.game_library_page._has_been_loaded:
                self.game_library_page._initial_load()
        elif index == self.PAGE_TAGS and self.tags_page is not None:
            self.tags_page._initial_load()
        elif index == self.PAGE_AUTHORS and self.authors_page is not None:
            self.authors_page._initial_load()

    def _on_search_clicked(self):
        idx = self.pages.currentIndex()
        if idx == self.PAGE_LIBRARY and self.library_page is not None:
            self.library_page.open_search()
        elif idx == self.PAGE_VIDEOS and self.video_library_page is not None:
            self.video_library_page.open_search()
        elif idx == self.PAGE_GAMES and self.game_library_page is not None:
            self.game_library_page.open_search()

    # ---------- readers / players ----------

    def open_comic(self, file_path):
        try:
            from reader_window import ReaderWindow
            reader = ReaderWindow(file_path, self.db)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось открыть файл:\n{e}")
            return
        reader.closed.connect(lambda r=reader: self._remove_reader(r))
        self.reader_windows.append(reader)
        reader.show()

    def _remove_reader(self, reader):
        try:
            self.reader_windows.remove(reader)
        except ValueError:
            pass
        try:
            file_path = reader.file_path
        except Exception:
            file_path = ''
        try:
            reader.deleteLater()
        except Exception:
            pass
        if self.library_page is not None and file_path:
            try:
                self.library_page.update_card_meta(file_path)
            except Exception:
                pass

    def open_video(self, file_path):
        playlist = [file_path]
        if self.video_library_page is not None:
            try:
                pl = self.video_library_page.get_playlist()
                if pl:
                    playlist = pl
            except Exception:
                pass

        if file_path in playlist:
            idx = playlist.index(file_path)
        else:
            playlist = [file_path]
            idx = 0

        try:
            from video_player_window import VideoPlayerWindow
            player = VideoPlayerWindow(file_path, self.db,
                                       playlist=playlist,
                                       playlist_index=idx)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось открыть видео:\n{e}")
            return
        player.closed.connect(lambda p=player: self._remove_player(p))
        self.player_windows.append(player)
        player.show()

    def _remove_player(self, player):
        try:
            self.player_windows.remove(player)
        except ValueError:
            pass
        try:
            file_path = player.file_path
        except Exception:
            file_path = ''
        try:
            player.deleteLater()
        except Exception:
            pass
        if self.video_library_page is not None and file_path:
            try:
                self.video_library_page.update_card_meta(file_path)
            except Exception:
                pass

    def _launch_game_from_home(self, exe_path):
        try:
            self._ensure_games_page()
            if hasattr(self.game_library_page, 'launch_game'):
                self.game_library_page.launch_game(exe_path)
            else:
                self.game_library_page._on_card_clicked(exe_path)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка запуска",
                                 f"Не удалось запустить игру:\n{e}")


def main():
    try:
        from paths import APP_DIR as _APP_DIR
        from data_transfer import apply_pending_import
        if apply_pending_import(_APP_DIR):
            print("[main] pending import applied")
    except Exception as _e:
        print(f"[main] pending import: {_e}")

    setup_logging()

    try:
        from paths import APP_DIR as _APP_DIR
        from updater import (cleanup_old_update_artifacts,
                             cleanup_update_residue)
        cleanup_old_update_artifacts(_APP_DIR)
        cleanup_update_residue(_APP_DIR)
    except Exception as _e:
        print(f"[main] cleanup: {_e}")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))

    app.setStyleSheet("""
        * { font-family: "Segoe UI", Arial, sans-serif; }
        QScrollBar:vertical { background: #1e1e1e; width: 10px; border: none; }
        QScrollBar::handle:vertical {
            background: #444444; border-radius: 5px; min-height: 30px;
        }
        QScrollBar::handle:vertical:hover { background: #555555; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """)

    window = ComicReaderApp()
    window.showMaximized()
    window.reload_home()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()