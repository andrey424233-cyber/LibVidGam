import json
import os

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QGroupBox, QFileDialog,
                             QMessageBox, QColorDialog, QFormLayout,
                             QDialog, QListWidget, QComboBox, QLineEdit,
                             QProgressBar, QApplication, QScrollArea)

from paths import CONFIG_PATH, APP_DIR, APP_VERSION
from data_transfer import DataImportDialog, DataExportDialog
import updater
from mobile_server import MobileServer, HAS_FLASK
from mobile_qr import make_qr_pixmap, HAS_QRCODE


DEFAULT_COLORS = {
    'accent': '#c0392b',
    'background': '#121212',
    'panel': '#1e1e1e',
    'text': '#e0e0e0',
    'secondary_text': '#888888',
    'menu_text': '#ffffff',
    'card_background': '#1e1e1e',
    'border': '#3a3a3a',
}

COLOR_SETTINGS = [
    ('accent', 'Акцентный цвет', DEFAULT_COLORS['accent']),
    ('background', 'Цвет фона', DEFAULT_COLORS['background']),
    ('panel', 'Цвет панелей', DEFAULT_COLORS['panel']),
    ('text', 'Цвет текста', DEFAULT_COLORS['text']),
    ('secondary_text', 'Вторичный текст', DEFAULT_COLORS['secondary_text']),
    ('menu_text', 'Текст меню', DEFAULT_COLORS['menu_text']),
    ('card_background', 'Фон карточек', DEFAULT_COLORS['card_background']),
    ('border', 'Цвет рамок', DEFAULT_COLORS['border']),
]


def default_folders():
    home = os.path.expanduser("~")
    return {
        'comics_folder': os.path.join(home, "Comics"),
        'videos_folder': os.path.join(home, "Videos"),
        'games_folder': os.path.join(home, "Games"),
    }


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


# ============================================================
# Фоновый воркер: проверка обновления
# ============================================================

class _CheckUpdateWorker(QThread):
    done = pyqtSignal(object)

    def __init__(self, updates_dir: str, current_version: str, parent=None):
        super().__init__(parent)
        self.updates_dir = updates_dir
        self.current_version = current_version

    def run(self):
        try:
            result = updater.check_for_update(self.updates_dir,
                                              self.current_version)
            self.done.emit(result)
        except Exception as e:
            print(f"[check_update] {e}")
            self.done.emit(None)


# ============================================================
# Фоновый воркер: распаковка обновления
# ============================================================

class _StageUpdateWorker(QThread):
    progress = pyqtSignal(int, int)
    hash_progress = pyqtSignal(int, int)
    done = pyqtSignal(bool, str)

    def __init__(self, app_dir: str, zip_path: str,
                 expected_sha256: str, parent=None):
        super().__init__(parent)
        self.app_dir = app_dir
        self.zip_path = zip_path
        self.expected_sha256 = expected_sha256

    def run(self):
        try:
            updater.stage_update(
                self.app_dir,
                self.zip_path,
                expected_sha256=self.expected_sha256,
                on_progress=lambda d, t: self.progress.emit(d, t),
                on_hash_progress=lambda d, t: self.hash_progress.emit(d, t),
            )
            self.done.emit(True, '')
        except Exception as e:
            self.done.emit(False, str(e))


# ============================================================
# Диалог скрытых тегов
# ============================================================

class HiddenTagsDialog(QDialog):
    def __init__(self, all_tags, selected_tags, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Скрытые теги")
        self.setFixedSize(440, 500)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; background: transparent; }
            QListWidget {
                background-color: #2a2a2a; color: #ffffff;
                border: 1px solid #3a3a3a; border-radius: 5px;
                font-size: 13px;
            }
            QListWidget::item { padding: 6px; min-height: 20px; }
            QListWidget::item:selected { background-color: #c0392b; color: #ffffff; }
            QComboBox {
                background-color: #2a2a2a; color: #ffffff;
                border: 1px solid #3a3a3a; border-radius: 5px;
                padding: 6px; font-size: 13px;
            }
            QComboBox::drop-down { border: none; width: 25px; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a; color: #ffffff;
                border: 1px solid #3a3a3a;
                selection-background-color: #c0392b;
                selection-color: #ffffff;
            }
            QPushButton {
                background-color: #2a2a2a; color: #e0e0e0;
                border: none; border-radius: 5px; padding: 8px 15px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Скрытые теги")
        title.setStyleSheet(
            "QLabel { color: #ffffff; font-size: 18px; font-weight: bold; }"
        )
        layout.addWidget(title)

        hint = QLabel(
            "Работы с этими тегами не отображаются в библиотеках."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("QLabel { color: #888888; font-size: 12px; }")
        layout.addWidget(hint)

        self.list_widget = QListWidget()
        for t in selected_tags:
            self.list_widget.addItem(t)
        layout.addWidget(self.list_widget, 1)

        add_row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.addItems(all_tags)

        self.btn_add = QPushButton("+ Добавить")
        self.btn_add.setFixedWidth(120)
        self.btn_add.clicked.connect(self.add_tag)

        self.btn_remove = QPushButton("− Удалить")
        self.btn_remove.setFixedWidth(100)
        self.btn_remove.clicked.connect(self.remove_tag)

        add_row.addWidget(self.combo, 1)
        add_row.addWidget(self.btn_add)
        add_row.addWidget(self.btn_remove)
        layout.addLayout(add_row)

        bottom = QHBoxLayout()
        bottom.addStretch()

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setFixedWidth(120)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton("Сохранить")
        self.btn_save.setFixedWidth(140)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 8px 15px; font-weight: bold;
            }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_save.clicked.connect(self.accept)

        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_save)
        layout.addLayout(bottom)

        self.setLayout(layout)

    def add_tag(self):
        tag = self.combo.currentText().strip()
        if not tag:
            return
        existing = [self.list_widget.item(i).text()
                    for i in range(self.list_widget.count())]
        if tag in existing:
            return
        self.list_widget.addItem(tag)

    def remove_tag(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        self.list_widget.takeItem(self.list_widget.row(item))

    def get_tags(self):
        return [self.list_widget.item(i).text()
                for i in range(self.list_widget.count())]


# ============================================================
# Страница настроек
# ============================================================

class SettingsWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.config_file = CONFIG_PATH

        config = self.load_config()
        self.colors = {
            **DEFAULT_COLORS,
            **{k: v for k, v in config.items() if k in DEFAULT_COLORS},
        }
        self.hidden_tags = list(config.get('hidden_tags', []))
        self.featured_tag = (config.get('featured_tag', '') or '').strip()
        self.updates_dir = (config.get('updates_dir', '') or '').strip()

        default_f = default_folders()
        self.comics_folder = config.get('comics_folder',
                                        default_f['comics_folder'])
        self.videos_folder = config.get('videos_folder',
                                        default_f['videos_folder'])
        self.games_folder = config.get('games_folder',
                                       default_f['games_folder'])

        # Обновления
        self._update_info = None
        self._check_worker = None
        self._stage_worker = None

        # Мобильный сервер
        self._mobile_server = None

        self.setStyleSheet("""
            QWidget { background-color: #121212; color: #e0e0e0; }
            QLabel { color: #e0e0e0; background: transparent; }
            QGroupBox {
                color: #e0e0e0; border: 1px solid #2a2a2a;
                border-radius: 10px; margin-top: 12px;
                padding-top: 20px; background-color: transparent;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 15px;
                padding: 0 5px; color: #ffffff; font-weight: bold;
            }
        """)

        # ---------- Внешний layout и scroll ----------
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("""
            QScrollArea { border: none; background-color: #121212; }
            QScrollBar:vertical {
                background: #1e1e1e; width: 10px; border: none;
            }
            QScrollBar::handle:vertical {
                background: #444; border-radius: 5px; min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: #555; }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical { background: transparent; }
        """)

        content = QWidget()
        content.setStyleSheet("QWidget { background-color: #121212; }")

        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        content.setLayout(layout)

        # ---------- Заголовок ----------
        title = QLabel("Настройки")
        title.setStyleSheet(
            "QLabel { color: #ffffff; font-size: 28px; font-weight: bold; }"
        )
        layout.addWidget(title)

        # ===== Цветовая схема =====
        color_group = QGroupBox("Цветовая схема")
        color_layout = QFormLayout()
        color_layout.setSpacing(10)

        self.color_buttons = {}
        self.color_labels = {}

        for color_key, label_text, default_color in COLOR_SETTINGS:
            btn = QPushButton()
            btn.setFixedSize(100, 40)
            current_color = self.colors.get(color_key, default_color)
            self._update_btn_style(btn, current_color, color_key)
            btn.clicked.connect(
                lambda checked, key=color_key: self.choose_color(key)
            )

            hex_label = QLabel(current_color)
            hex_label.setStyleSheet("QLabel { color: #e0e0e0; }")

            h_layout = QHBoxLayout()
            h_layout.addWidget(btn)
            h_layout.addWidget(hex_label)
            color_layout.addRow(QLabel(f"{label_text}:"), h_layout)

            self.color_buttons[color_key] = btn
            self.color_labels[color_key] = hex_label

        self.btn_reset_colors = QPushButton("🔄 Сбросить цвета")
        self.btn_reset_colors.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 5px; padding: 8px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_reset_colors.clicked.connect(self.reset_colors)
        color_layout.addRow("", self.btn_reset_colors)

        color_group.setLayout(color_layout)
        layout.addWidget(color_group)

        # ===== Папки библиотек =====
        folders_group = QGroupBox("Папки библиотек")
        folders_layout = QVBoxLayout()
        folders_layout.setSpacing(10)

        hint_folders = QLabel(
            "Пути, откуда приложение сканирует файлы. "
            "Изменения вступают в силу после перезапуска."
        )
        hint_folders.setWordWrap(True)
        hint_folders.setStyleSheet("QLabel { color: #888888; font-size: 12px; }")
        folders_layout.addWidget(hint_folders)

        self.comics_path_edit = self._make_folder_row(
            folders_layout, "Комиксы:", self.comics_folder, 'comics_folder')
        self.videos_path_edit = self._make_folder_row(
            folders_layout, "Видео:", self.videos_folder, 'videos_folder')
        self.games_path_edit = self._make_folder_row(
            folders_layout, "Игры:", self.games_folder, 'games_folder')

        folders_group.setLayout(folders_layout)
        layout.addWidget(folders_group)

        # ===== Обмен тегами =====
        transfer_group = QGroupBox("Обмен тегами")
        transfer_layout = QVBoxLayout()
        transfer_layout.setSpacing(10)

        hint_transfer = QLabel(
            "Экспорт всех тегов и их обложек в отдельную папку и импорт "
            "тегов из такой папки."
        )
        hint_transfer.setWordWrap(True)
        hint_transfer.setStyleSheet("QLabel { color: #888888; font-size: 12px; }")
        transfer_layout.addWidget(hint_transfer)

        transfer_row = QHBoxLayout()

        self.btn_import_data = QPushButton("📥 Импорт тегов")
        self.btn_import_data.setFixedHeight(40)
        self.btn_import_data.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px;
                          font-size: 14px; padding: 0 20px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_import_data.clicked.connect(self._open_import_dialog)
        transfer_row.addWidget(self.btn_import_data)

        self.btn_export_data = QPushButton("📤 Экспорт тегов")
        self.btn_export_data.setFixedHeight(40)
        self.btn_export_data.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px;
                          font-size: 14px; padding: 0 20px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_export_data.clicked.connect(self._open_export_dialog)
        transfer_row.addWidget(self.btn_export_data)

        transfer_row.addStretch()
        transfer_layout.addLayout(transfer_row)

        transfer_group.setLayout(transfer_layout)
        layout.addWidget(transfer_group)

        # ===== Мобильный доступ =====
        mobile_group = QGroupBox("📱 Мобильный доступ")
        mobile_layout = QVBoxLayout()
        mobile_layout.setSpacing(10)

        hint_mobile = QLabel(
            "Просмотр видео и комиксов с телефона в одной Wi-Fi-сети. "
            "Сервер запускается вручную и останавливается при закрытии "
            "приложения. Доступ защищён одноразовым токеном в QR-коде."
        )
        hint_mobile.setWordWrap(True)
        hint_mobile.setStyleSheet(
            "QLabel { color: #888888; font-size: 12px; }"
        )
        mobile_layout.addWidget(hint_mobile)

        self.lbl_mobile_status = QLabel("Сервер остановлен")
        self.lbl_mobile_status.setStyleSheet(
            "QLabel { color: #888888; font-size: 13px; padding: 4px 0; }"
        )
        mobile_layout.addWidget(self.lbl_mobile_status)

        self.lbl_mobile_url = QLabel("")
        self.lbl_mobile_url.setWordWrap(True)
        self.lbl_mobile_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_mobile_url.setStyleSheet(
            "QLabel { color: #c0392b; font-size: 13px; "
            "font-family: Consolas, monospace; padding: 4px 0; }"
        )
        mobile_layout.addWidget(self.lbl_mobile_url)

        self.lbl_mobile_qr = QLabel("")
        self.lbl_mobile_qr.setFixedSize(260, 260)
        self.lbl_mobile_qr.setAlignment(Qt.AlignCenter)
        self.lbl_mobile_qr.setStyleSheet("""
            QLabel { background-color: #1a1a1a; border: 1px solid #2a2a2a;
                     border-radius: 8px; }
        """)
        self.lbl_mobile_qr.setVisible(False)

        qr_wrap = QHBoxLayout()
        qr_wrap.addWidget(self.lbl_mobile_qr)
        qr_wrap.addStretch()
        mobile_layout.addLayout(qr_wrap)

        mobile_btns = QHBoxLayout()

        self.btn_mobile_start = QPushButton("▶ Запустить сервер")
        self.btn_mobile_start.setFixedHeight(40)
        self.btn_mobile_start.setStyleSheet("""
            QPushButton { background-color: #c0392b; color: white;
                          border: none; border-radius: 20px;
                          font-size: 14px; padding: 0 22px; }
            QPushButton:hover { background-color: #e74c3c; }
            QPushButton:disabled { background-color: #3a3a3a;
                                   color: #666; }
        """)
        self.btn_mobile_start.clicked.connect(self._mobile_start)
        mobile_btns.addWidget(self.btn_mobile_start)

        self.btn_mobile_stop = QPushButton("■ Остановить")
        self.btn_mobile_stop.setFixedHeight(40)
        self.btn_mobile_stop.setEnabled(False)
        self.btn_mobile_stop.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px;
                          font-size: 14px; padding: 0 22px; }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:disabled { background-color: #1a1a1a;
                                   color: #555; }
        """)
        self.btn_mobile_stop.clicked.connect(self._mobile_stop)
        mobile_btns.addWidget(self.btn_mobile_stop)

        self.btn_mobile_copy = QPushButton("📋 Скопировать URL")
        self.btn_mobile_copy.setFixedHeight(40)
        self.btn_mobile_copy.setEnabled(False)
        self.btn_mobile_copy.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px;
                          font-size: 14px; padding: 0 22px; }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:disabled { background-color: #1a1a1a;
                                   color: #555; }
        """)
        self.btn_mobile_copy.clicked.connect(self._mobile_copy_url)
        mobile_btns.addWidget(self.btn_mobile_copy)

        mobile_btns.addStretch()
        mobile_layout.addLayout(mobile_btns)

        if not HAS_FLASK:
            warn = QLabel(
                "⚠️ Flask не установлен. Выполните в терминале:\n"
                "pip install flask"
            )
            warn.setWordWrap(True)
            warn.setStyleSheet(
                "QLabel { color: #e67e22; font-size: 12px; padding: 8px;"
                " background-color: #2a1e0a; border-radius: 5px; }"
            )
            mobile_layout.addWidget(warn)
            self.btn_mobile_start.setEnabled(False)
        elif not HAS_QRCODE:
            warn = QLabel(
                "⚠️ Библиотека qrcode не установлена — QR-код не покажется,"
                " но URL можно открыть вручную. Для QR:\n"
                "pip install qrcode[pil]"
            )
            warn.setWordWrap(True)
            warn.setStyleSheet(
                "QLabel { color: #e67e22; font-size: 12px; padding: 8px;"
                " background-color: #2a1e0a; border-radius: 5px; }"
            )
            mobile_layout.addWidget(warn)

        mobile_group.setLayout(mobile_layout)
        layout.addWidget(mobile_group)

        # ===== Главная страница =====
        home_group = QGroupBox("Главная страница")
        home_layout = QVBoxLayout()
        home_layout.setSpacing(10)

        hint_home = QLabel(
            "Тег, дающий приоритет работам на главной странице. "
            "Отбор идёт по количеству просмотров, но работы с этим "
            "тегом получают буст ×3."
        )
        hint_home.setWordWrap(True)
        hint_home.setStyleSheet("QLabel { color: #888888; font-size: 12px; }")
        home_layout.addWidget(hint_home)

        row = QHBoxLayout()
        row.addWidget(QLabel("Приоритетный тег:"))
        self.featured_tag_combo = QComboBox()
        self.featured_tag_combo.setMinimumHeight(34)
        self.featured_tag_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a; color: #ffffff;
                border: 1px solid #3a3a3a; border-radius: 5px;
                padding: 6px 10px; font-size: 13px;
            }
            QComboBox::drop-down { border: none; width: 25px; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a; color: #ffffff;
                border: 1px solid #3a3a3a;
                selection-background-color: #c0392b;
                selection-color: #ffffff;
            }
        """)
        row.addWidget(self.featured_tag_combo, 1)

        btn_reload_tags = QPushButton("🔄 Обновить список")
        btn_reload_tags.setFixedHeight(34)
        btn_reload_tags.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 5px;
                          padding: 6px 14px; font-size: 13px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        btn_reload_tags.clicked.connect(self._reload_featured_tags)
        row.addWidget(btn_reload_tags)

        home_layout.addLayout(row)
        home_group.setLayout(home_layout)
        layout.addWidget(home_group)

        # ===== Скрытые теги =====
        hidden_group = QGroupBox("Скрытые теги")
        hidden_layout = QVBoxLayout()
        hidden_layout.setSpacing(10)

        hint = QLabel(
            "Работы с выбранными тегами не отображаются "
            "в библиотеках и на главной."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("QLabel { color: #888888; font-size: 12px; }")
        hidden_layout.addWidget(hint)

        self.lbl_hidden_count = QLabel(self._hidden_count_text())
        self.lbl_hidden_count.setStyleSheet(
            "QLabel { color: #c0392b; font-size: 13px; font-weight: bold; }"
        )
        hidden_layout.addWidget(self.lbl_hidden_count)

        self.btn_hidden_tags = QPushButton("🚫 Настроить скрытые теги")
        self.btn_hidden_tags.setFixedHeight(40)
        self.btn_hidden_tags.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px;
                          font-size: 14px; padding: 0 20px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        self.btn_hidden_tags.clicked.connect(self.open_hidden_tags_dialog)
        hidden_layout.addWidget(self.btn_hidden_tags)

        hidden_group.setLayout(hidden_layout)
        layout.addWidget(hidden_group)

        # ===== Обновления =====
        update_group = QGroupBox("Обновления")
        update_layout = QVBoxLayout()
        update_layout.setSpacing(10)

        hint_update = QLabel(
            "Локальное обновление. Укажите папку, куда вы кладёте "
            "новые версии (файл latest.json и zip-архив). Данные "
            "пользователя (библиотека, настройки, обложки) при "
            "обновлении сохраняются."
        )
        hint_update.setWordWrap(True)
        hint_update.setStyleSheet("QLabel { color: #888888; font-size: 12px; }")
        update_layout.addWidget(hint_update)

        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("Текущая версия:"))
        self.lbl_current_version = QLabel(APP_VERSION)
        self.lbl_current_version.setStyleSheet(
            "QLabel { color: #ffffff; font-weight: bold; font-size: 14px; }"
        )
        ver_row.addWidget(self.lbl_current_version)
        ver_row.addStretch()
        update_layout.addLayout(ver_row)

        upd_row = QHBoxLayout()
        upd_row.addWidget(QLabel("Папка:"))
        self.updates_dir_edit = QLineEdit(self.updates_dir)
        self.updates_dir_edit.setReadOnly(True)
        self.updates_dir_edit.setPlaceholderText(
            "Папка с latest.json и zip-архивом обновлений"
        )
        self.updates_dir_edit.setStyleSheet("""
            QLineEdit { background-color: #2a2a2a; color: #e0e0e0;
                        border: 1px solid #3a3a3a; border-radius: 5px;
                        padding: 8px 10px; font-size: 13px; }
        """)
        upd_row.addWidget(self.updates_dir_edit, 1)

        btn_pick_upd = QPushButton("📂 Выбрать")
        btn_pick_upd.setFixedWidth(120)
        btn_pick_upd.clicked.connect(self._pick_updates_dir)
        upd_row.addWidget(btn_pick_upd)
        update_layout.addLayout(upd_row)

        action_row = QHBoxLayout()

        self.btn_check_update = QPushButton("🔄 Проверить обновления")
        self.btn_check_update.setFixedHeight(40)
        self.btn_check_update.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 20px;
                          font-size: 14px; padding: 0 20px; }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:disabled { color: #555; background-color: #1a1a1a; }
        """)
        self.btn_check_update.clicked.connect(self._on_check_update)
        action_row.addWidget(self.btn_check_update)

        self.btn_install_update = QPushButton("📥 Установить")
        self.btn_install_update.setFixedHeight(40)
        self.btn_install_update.setVisible(False)
        self.btn_install_update.setStyleSheet("""
            QPushButton { background-color: #c0392b; color: white;
                          border: none; border-radius: 20px;
                          font-size: 14px; font-weight: bold;
                          padding: 0 20px; }
            QPushButton:hover { background-color: #e74c3c; }
            QPushButton:disabled { color: #666; background-color: #3a3a3a; }
        """)
        self.btn_install_update.clicked.connect(self._on_install_update)
        action_row.addWidget(self.btn_install_update)

        action_row.addStretch()
        update_layout.addLayout(action_row)

        self.lbl_update_status = QLabel("")
        self.lbl_update_status.setWordWrap(True)
        self.lbl_update_status.setStyleSheet(
            "QLabel { color: #888888; font-size: 12px; padding: 4px 0; }"
        )
        update_layout.addWidget(self.lbl_update_status)

        self.update_progress = QProgressBar()
        self.update_progress.setFixedHeight(22)
        self.update_progress.setRange(0, 100)
        self.update_progress.setValue(0)
        self.update_progress.setVisible(False)
        self.update_progress.setStyleSheet("""
            QProgressBar {
                background-color: #2a2a2a; color: #e0e0e0;
                border: 1px solid #3a3a3a; border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #c0392b; border-radius: 4px;
            }
        """)
        update_layout.addWidget(self.update_progress)

        update_group.setLayout(update_layout)
        layout.addWidget(update_group)

        # ===== Применить =====
        apply_layout = QHBoxLayout()
        apply_layout.addStretch()

        self.btn_apply = QPushButton("💾 Применить изменения")
        self.btn_apply.setFixedSize(220, 45)
        self.btn_apply.setStyleSheet("""
            QPushButton { background-color: #c0392b; color: white;
                          border: none; border-radius: 22px;
                          font-size: 16px; font-weight: bold; }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_apply.clicked.connect(self.apply_settings)
        apply_layout.addWidget(self.btn_apply)

        layout.addLayout(apply_layout)
        layout.addStretch()

        # ---------- Вставляем контейнер в scroll и задаём внешний layout ----------
        self._scroll.setWidget(content)
        outer_layout.addWidget(self._scroll)
        self.setLayout(outer_layout)

        self._reload_featured_tags()

    # ---------- строки папок ----------

    def _make_folder_row(self, parent_layout, title, initial_path, key):
        row = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setFixedWidth(80)
        row.addWidget(lbl)

        edit = QLineEdit(initial_path)
        edit.setReadOnly(True)
        edit.setStyleSheet("""
            QLineEdit { background-color: #2a2a2a; color: #e0e0e0;
                        border: 1px solid #3a3a3a; border-radius: 5px;
                        padding: 8px 10px; font-size: 13px; }
        """)
        row.addWidget(edit, 1)

        btn = QPushButton("📁 Выбрать")
        btn.setFixedSize(120, 36)
        btn.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #e0e0e0;
                          border: none; border-radius: 18px; font-size: 13px; }
            QPushButton:hover { background-color: #3a3a3a; }
        """)
        btn.clicked.connect(lambda: self._pick_folder(edit, key))
        row.addWidget(btn)

        parent_layout.addLayout(row)
        return edit

    def _pick_folder(self, edit, key):
        current = edit.text() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку", current)
        if folder:
            edit.setText(folder)

    # ---------- featured tag ----------

    def _reload_featured_tags(self):
        self.featured_tag_combo.clear()
        self.featured_tag_combo.addItem("— не выбрано —", "")
        try:
            db = (getattr(self.parent_window, 'db', None)
                  if self.parent_window else None)
            if db:
                tags = db.get_all_tags()
                for t in tags:
                    name = t['name'] if isinstance(t, dict) else t
                    self.featured_tag_combo.addItem(name, name)
        except Exception:
            pass
        idx = self.featured_tag_combo.findData(self.featured_tag)
        if idx >= 0:
            self.featured_tag_combo.setCurrentIndex(idx)

    # ---------- обмен тегами ----------

    def _get_db(self):
        return (getattr(self.parent_window, 'db', None)
                if self.parent_window else None)

    def _open_import_dialog(self):
        db = self._get_db()
        if db is None:
            QMessageBox.warning(self, "Ошибка",
                                "База данных недоступна.")
            return

        dialog = DataImportDialog(APP_DIR, db, self)
        accepted = dialog.exec_() == QDialog.Accepted
        if not accepted:
            return

        try:
            self._reload_featured_tags()
        except Exception as e:
            print(f"[settings] reload featured tags: {e}")

        try:
            parent = self.parent_window
            if parent is not None:
                tags_page = getattr(parent, 'tags_page', None)
                if tags_page is not None:
                    tags_page.refresh()
                self.lbl_hidden_count.setText(self._hidden_count_text())
        except Exception as e:
            print(f"[settings] after import refresh: {e}")

    def _open_export_dialog(self):
        db = self._get_db()
        if db is None:
            QMessageBox.warning(self, "Ошибка",
                                "База данных недоступна.")
            return

        dialog = DataExportDialog(APP_DIR, db, self)
        dialog.exec_()

    # ---------- мобильный доступ ----------

    def _mobile_start(self):
        if self._mobile_server is not None:
            return
        db = self._get_db()
        if db is None:
            QMessageBox.warning(self, "Ошибка",
                                "База данных недоступна.")
            return

        try:
            server = MobileServer(db)
            server.start()
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка мобильного сервера",
                f"Не удалось запустить сервер:\n{e}"
            )
            return

        self._mobile_server = server
        url = server.get_url()

        self.lbl_mobile_status.setText(
            f"✅ Сервер запущен на порту {server.port} "
            f"(IP: {server.local_ip})"
        )
        self.lbl_mobile_status.setStyleSheet(
            "QLabel { color: #27ae60; font-size: 13px; padding: 4px 0; }"
        )
        self.lbl_mobile_url.setText(url)
        self.btn_mobile_start.setEnabled(False)
        self.btn_mobile_stop.setEnabled(True)
        self.btn_mobile_copy.setEnabled(True)

        if HAS_QRCODE:
            pix = make_qr_pixmap(url, size=248)
            if not pix.isNull():
                self.lbl_mobile_qr.setPixmap(pix)
                self.lbl_mobile_qr.setVisible(True)

    def _mobile_stop(self):
        if self._mobile_server is None:
            return
        try:
            self._mobile_server.stop()
        except Exception as e:
            print(f"[settings] mobile stop: {e}")
        self._mobile_server = None

        self.lbl_mobile_status.setText("Сервер остановлен")
        self.lbl_mobile_status.setStyleSheet(
            "QLabel { color: #888888; font-size: 13px; padding: 4px 0; }"
        )
        self.lbl_mobile_url.setText("")
        self.lbl_mobile_qr.clear()
        self.lbl_mobile_qr.setVisible(False)
        self.btn_mobile_start.setEnabled(HAS_FLASK)
        self.btn_mobile_stop.setEnabled(False)
        self.btn_mobile_copy.setEnabled(False)

    def _mobile_copy_url(self):
        if self._mobile_server is None:
            return
        url = self._mobile_server.get_url()
        QApplication.clipboard().setText(url)
        QMessageBox.information(
            self, "Скопировано",
            f"URL скопирован в буфер обмена:\n{url}"
        )

    # ---------- обновления ----------

    def _pick_updates_dir(self):
        current = (self.updates_dir_edit.text().strip()
                   or os.path.expanduser("~"))
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку с обновлениями", current
        )
        if not folder:
            return

        self.updates_dir = folder
        self.updates_dir_edit.setText(folder)

        try:
            config = self.load_config()
            config['updates_dir'] = folder
            self.save_config(config)
        except Exception as e:
            print(f"[settings] save updates_dir: {e}")

        self._update_info = None
        self.btn_install_update.setVisible(False)
        self.lbl_update_status.setText("")

    def _on_check_update(self):
        if self._check_worker is not None and self._check_worker.isRunning():
            return

        updates_dir = self.updates_dir_edit.text().strip()
        if not updates_dir:
            QMessageBox.information(
                self, "Папка не указана",
                "Сначала выберите папку с обновлениями."
            )
            return

        if not os.path.isdir(updates_dir):
            QMessageBox.warning(
                self, "Папка не найдена",
                f"Папка не существует:\n{updates_dir}"
            )
            return

        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText("⏳ Проверка…")
        self.lbl_update_status.setStyleSheet(
            "QLabel { color: #888888; font-size: 12px; padding: 4px 0; }"
        )
        self.lbl_update_status.setText("Проверяем…")
        self.btn_install_update.setVisible(False)

        self._check_worker = _CheckUpdateWorker(
            updates_dir, APP_VERSION, self
        )
        self._check_worker.done.connect(self._on_check_done)
        self._check_worker.start()

    def _on_check_done(self, info):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText("🔄 Проверить обновления")

        if info is None:
            self.lbl_update_status.setStyleSheet(
                "QLabel { color: #27ae60; font-size: 12px; padding: 4px 0; }"
            )
            self.lbl_update_status.setText(
                f"✅ У вас последняя версия ({APP_VERSION})."
            )
            self._update_info = None
            self.btn_install_update.setVisible(False)
            return

        self._update_info = info

        version = info.get('version', '?')
        size = info.get('size', 0)
        date = info.get('release_date', '')
        changelog = info.get('changelog', '')

        parts = [f"🔔 Доступна версия {version}"]
        if date:
            parts.append(f"от {date}")
        if size:
            parts.append(f"({human_size(size)})")

        text = " ".join(parts)
        if changelog:
            text += f"\n\n{changelog}"

        self.lbl_update_status.setStyleSheet(
            "QLabel { color: #e67e22; font-size: 12px; padding: 4px 0; }"
        )
        self.lbl_update_status.setText(text)

        self.btn_install_update.setVisible(True)
        self.btn_install_update.setEnabled(True)
        self.btn_install_update.setText(f"📥 Установить {version}")

    def _on_install_update(self):
        if self._update_info is None:
            return
        if self._stage_worker is not None and self._stage_worker.isRunning():
            return

        info = self._update_info
        reply = QMessageBox.question(
            self, "Установка обновления",
            f"Установить версию {info.get('version', '?')}?\n\n"
            "Приложение будет перезапущено.\n"
            "Данные библиотеки, настройки и обложки сохранятся.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_install_update.setEnabled(False)
        self.btn_check_update.setEnabled(False)

        self.update_progress.setVisible(True)
        self.update_progress.setRange(0, 100)
        self.update_progress.setValue(0)
        self.lbl_update_status.setText("Проверка архива…")

        self._stage_worker = _StageUpdateWorker(
            APP_DIR,
            info['zip_path'],
            info.get('sha256', ''),
            self
        )
        self._stage_worker.hash_progress.connect(self._on_hash_progress)
        self._stage_worker.progress.connect(self._on_stage_progress)
        self._stage_worker.done.connect(self._on_stage_done)
        self._stage_worker.start()

    def _on_hash_progress(self, done, total):
        if total <= 0:
            return
        pct = int(done * 100 / total)
        self.update_progress.setValue(pct)
        self.lbl_update_status.setText(
            f"Проверка целостности архива… {pct}%"
        )

    def _on_stage_progress(self, done, total):
        if total <= 0:
            return
        pct = int(done * 100 / total)
        self.update_progress.setValue(pct)
        self.lbl_update_status.setText(f"Распаковка… {pct}%")

    def _on_stage_done(self, success, error):
        self.btn_install_update.setEnabled(True)
        self.btn_check_update.setEnabled(True)
        self.update_progress.setVisible(False)

        if not success:
            self.lbl_update_status.setStyleSheet(
                "QLabel { color: #e74c3c; font-size: 12px; padding: 4px 0; }"
            )
            self.lbl_update_status.setText(f"❌ Ошибка: {error}")
            QMessageBox.critical(
                self, "Ошибка обновления",
                f"Не удалось подготовить обновление:\n\n{error}"
            )
            return

        self.lbl_update_status.setStyleSheet(
            "QLabel { color: #27ae60; font-size: 12px; padding: 4px 0; }"
        )
        self.lbl_update_status.setText("✅ Обновление готово. Перезапустить?")

        reply = QMessageBox.question(
            self, "Обновление готово",
            "Приложение будет перезапущено для применения обновления.\n\n"
            "Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        ok = updater.apply_update_and_restart(APP_DIR)
        if not ok:
            QMessageBox.critical(
                self, "Ошибка",
                "Не удалось запустить скрипт обновления.\n"
                "Попробуйте закрыть приложение вручную и запустить "
                "заново — обновление применится автоматически."
            )
            return

        QApplication.quit()

    # ---------- цвета ----------

    @staticmethod
    def _update_btn_style(btn, color, key):
        if key in ('background', 'card_background'):
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color};"
                f" border: 1px solid #555; border-radius: 5px; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color};"
                f" border: none; border-radius: 5px; }}"
            )

    def choose_color(self, color_type):
        try:
            current = self.colors.get(color_type, '#ffffff')
            color = QColorDialog.getColor(QColor(current), self,
                                          "Выберите цвет")
            if not color.isValid():
                return
            hex_color = color.name()
            self.colors[color_type] = hex_color
            self._update_btn_style(self.color_buttons[color_type],
                                   hex_color, color_type)
            self.color_labels[color_type].setText(hex_color)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось выбрать цвет: {e}")

    def reset_colors(self):
        reply = QMessageBox.question(
            self, "Подтверждение",
            "Сбросить все цвета к значениям по умолчанию?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        for color_key, default_color in DEFAULT_COLORS.items():
            self.colors[color_key] = default_color
            self._update_btn_style(self.color_buttons[color_key],
                                   default_color, color_key)
            self.color_labels[color_key].setText(default_color)

        QMessageBox.information(
            self, "Успех",
            "Цвета сброшены. Нажмите 'Применить' для сохранения."
        )

    # ---------- скрытые теги ----------

    def _hidden_count_text(self):
        if not self.hidden_tags:
            return "Скрытых тегов нет"
        return "Скрытые теги настроены"

    def _get_all_tags(self):
        db = self._get_db()
        if db is None:
            return []
        try:
            tags = db.get_all_tags()
        except Exception:
            return []
        names = [t['name'] if isinstance(t, dict) else t for t in tags]
        if db.NO_TAGS_NAME not in names:
            names.insert(0, db.NO_TAGS_NAME)
        return names

    def open_hidden_tags_dialog(self):
        all_tags = self._get_all_tags()
        dialog = HiddenTagsDialog(all_tags, self.hidden_tags, self)
        if dialog.exec_() == QDialog.Accepted:
            self.hidden_tags = dialog.get_tags()
            self.lbl_hidden_count.setText(self._hidden_count_text())

    def reload_tag_choices(self):
        self._reload_featured_tags()

    # ---------- config ----------

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_config(self, data):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось сохранить настройки: {e}")

    # ---------- применить ----------

    def apply_settings(self):
        config = self.load_config()
        config.update(self.colors)
        config['hidden_tags'] = list(self.hidden_tags)
        config['comics_folder'] = self.comics_path_edit.text().strip()
        config['videos_folder'] = self.videos_path_edit.text().strip()
        config['games_folder'] = self.games_path_edit.text().strip()
        config['featured_tag'] = self.featured_tag_combo.currentData() or ''
        config['updates_dir'] = self.updates_dir_edit.text().strip()
        self.featured_tag = config['featured_tag']
        self.updates_dir = config['updates_dir']
        self.save_config(config)

        if self.parent_window and hasattr(self.parent_window, 'apply_colors'):
            try:
                self.parent_window.apply_colors(self.colors)
            except Exception as e:
                print(f"[apply_settings] apply_colors: {e}")

        reply = QMessageBox.question(
            self, "Настройки сохранены",
            "Изменения папок, скрытых тегов и приоритетного тега "
            "вступят в силу после перезапуска приложения.\n\n"
            "Перезапустить сейчас?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            if (self.parent_window is not None
                    and hasattr(self.parent_window, 'restart_after_import')):
                self.parent_window.restart_after_import()
            else:
                QMessageBox.information(
                    self, "Готово",
                    "Перезапустите приложение вручную."
                )

    # ---------- очистка ----------

    def closeEvent(self, event):
        try:
            if self._mobile_server is not None:
                self._mobile_server.stop()
        except Exception:
            pass
        super().closeEvent(event)