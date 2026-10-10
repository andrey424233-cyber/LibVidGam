"""Диалог поиска и фильтров с двумя вкладками: Поиск и Фильтры."""
import json
import os

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QComboBox,
                             QListWidget, QGroupBox, QCheckBox,
                             QTabWidget, QWidget)


DIALOG_STYLE = """
    QDialog { background-color: #1e1e1e; color: #e0e0e0; }
    QLabel { color: #e0e0e0; background: transparent; }
    QTabWidget::pane {
        border: 1px solid #3a3a3a; border-radius: 8px;
        background-color: #1e1e1e; top: -1px;
    }
    QTabBar::tab {
        background-color: #2a2a2a; color: #c0c0c0;
        padding: 10px 24px; font-size: 13px;
        border-top-left-radius: 6px; border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #c0392b; color: #ffffff;
    }
    QTabBar::tab:hover:!selected {
        background-color: #3a3a3a; color: #ffffff;
    }
    QGroupBox {
        color: #ffffff; border: 1px solid #3a3a3a;
        border-radius: 8px; margin-top: 10px; padding-top: 15px;
        background-color: #252525;
    }
    QGroupBox::title {
        subcontrol-origin: margin; left: 15px; padding: 0 5px;
        color: #ffffff; font-weight: bold;
    }
    QLineEdit {
        background-color: #2a2a2a; color: #ffffff;
        border: 1px solid #3a3a3a; border-radius: 5px;
        padding: 8px; selection-background-color: #c0392b; font-size: 13px;
    }
    QComboBox {
        background-color: #2a2a2a; color: #ffffff;
        border: 1px solid #3a3a3a; border-radius: 5px;
        padding: 5px; font-size: 13px;
    }
    QComboBox::drop-down { border: none; width: 30px; }
    QComboBox QAbstractItemView {
        background-color: #2a2a2a; color: #ffffff;
        border: 1px solid #3a3a3a;
        selection-background-color: #c0392b; selection-color: #ffffff;
    }
    QListWidget {
        background-color: #2a2a2a; color: #ffffff;
        border: 1px solid #3a3a3a; border-radius: 5px; font-size: 13px;
    }
    QListWidget::item { padding: 5px; min-height: 22px; }
    QListWidget::item:selected { background-color: #c0392b; }
    QPushButton {
        background-color: #2a2a2a; color: #ffffff;
        border: none; border-radius: 5px; padding: 8px 15px;
    }
    QPushButton:hover { background-color: #3a3a3a; }
    QCheckBox { color: #e0e0e0; font-size: 14px; padding: 8px 0; }
    QCheckBox::indicator {
        width: 20px; height: 20px;
        border: 2px solid #666; border-radius: 5px;
        background-color: #1a1a1a;
    }
    QCheckBox::indicator:checked {
        background-color: #c0392b; border-color: #c0392b;
    }
"""


class SearchFiltersDialog(QDialog):
    """Диалог с двумя вкладками: «Поиск» и «Фильтры».

    Поиск: применяется кнопкой «Применить». Диалог закрывается.
    Фильтры: применяются мгновенно при переключении чекбокса.
             Диалог остаётся открытым.
    """

    search_applied = pyqtSignal(dict)
    filters_changed = pyqtSignal(dict)

    def __init__(self, db, library_key,
                 current_search: dict,
                 current_filters: dict,
                 parent=None):
        super().__init__(parent)
        self.db = db
        self.library_key = library_key
        self._suppress_filter_signals = False

        self.setWindowTitle("Поиск и фильтры")
        self.setFixedSize(560, 720)
        self.setStyleSheet(DIALOG_STYLE)

        # Термины для конкретной библиотеки
        if library_key == 'games':
            self.view_label = "Сортировать по запускам"
            self.has_author = False
        else:
            self.view_label = "Сортировать по просмотрам"
            self.has_author = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Табы
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.search_tab = self._build_search_tab()
        self.tabs.addTab(self.search_tab, "🔍 Поиск")

        self.filters_tab = self._build_filters_tab()
        self.tabs.addTab(self.filters_tab, "⚙️ Фильтры")

        # Кнопка «Закрыть»
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.setFixedWidth(140)
        self.btn_close.clicked.connect(self.reject)
        bottom.addWidget(self.btn_close)
        layout.addLayout(bottom)

        self._apply_initial_state(current_search, current_filters)

    # ---------- вкладка «Поиск» ----------

    def _build_search_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        title_group = QGroupBox("Поиск по названию")
        tl = QVBoxLayout()
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Введите название...")
        tl.addWidget(self.title_input)
        title_group.setLayout(tl)
        layout.addWidget(title_group)

        self.author_input = None
        if self.has_author:
            author_group = QGroupBox("Поиск по автору")
            al = QVBoxLayout()
            self.author_input = QLineEdit()
            self.author_input.setPlaceholderText("Введите имя автора...")
            al.addWidget(self.author_input)
            author_group.setLayout(al)
            layout.addWidget(author_group)

        include_group = QGroupBox("Включить теги")
        il = QVBoxLayout()
        self.include_list = QListWidget()
        self.include_list.setMaximumHeight(90)
        il.addWidget(self.include_list)
        icl = QHBoxLayout()
        self.include_combo = QComboBox()
        self.include_combo.setEditable(True)
        self.btn_add_include = QPushButton("+")
        self.btn_add_include.setFixedSize(30, 30)
        self.btn_add_include.clicked.connect(self._add_include_tag)
        icl.addWidget(self.include_combo)
        icl.addWidget(self.btn_add_include)
        il.addLayout(icl)
        include_group.setLayout(il)
        layout.addWidget(include_group)

        exclude_group = QGroupBox("Исключить теги")
        el = QVBoxLayout()
        self.exclude_list = QListWidget()
        self.exclude_list.setMaximumHeight(90)
        el.addWidget(self.exclude_list)
        ecl = QHBoxLayout()
        self.exclude_combo = QComboBox()
        self.exclude_combo.setEditable(True)
        self.btn_add_exclude = QPushButton("+")
        self.btn_add_exclude.setFixedSize(30, 30)
        self.btn_add_exclude.clicked.connect(self._add_exclude_tag)
        ecl.addWidget(self.exclude_combo)
        ecl.addWidget(self.btn_add_exclude)
        el.addLayout(ecl)
        exclude_group.setLayout(el)
        layout.addWidget(exclude_group)

        layout.addStretch()

        bl = QHBoxLayout()
        bl.addStretch()
        self.btn_apply = QPushButton("Применить")
        self.btn_apply.setFixedWidth(160)
        self.btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #c0392b; color: #ffffff;
                border: none; border-radius: 5px;
                padding: 10px 20px; font-weight: bold; font-size: 14px;
            }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.btn_apply.clicked.connect(self._on_search_apply)
        bl.addWidget(self.btn_apply)
        layout.addLayout(bl)

        return page

    # ---------- вкладка «Фильтры» ----------

    def _build_filters_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(14)

        hint = QLabel(
            "Изменения применяются сразу. Состояние сохраняется между "
            "запусками приложения."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "QLabel { color: #888; font-size: 12px; padding: 4px 0; }"
        )
        layout.addWidget(hint)

        self.chk_sort_by_views = QCheckBox(self.view_label)
        self.chk_sort_by_views.toggled.connect(self._on_filters_toggled)
        layout.addWidget(self.chk_sort_by_views)

        self.chk_group_by_series = QCheckBox("Группировать по сериям")
        self.chk_group_by_series.toggled.connect(self._on_filters_toggled)
        layout.addWidget(self.chk_group_by_series)

        self.chk_group_by_authors = None
        if self.has_author:
            self.chk_group_by_authors = QCheckBox("Группировать по авторам")
            self.chk_group_by_authors.toggled.connect(self._on_filters_toggled)
            layout.addWidget(self.chk_group_by_authors)

        layout.addStretch()

        return page

    # ---------- инициализация ----------

    def _apply_initial_state(self, current_search, current_filters):
        self._update_tag_combos()

        if current_search:
            self.title_input.setText(current_search.get('title', '') or '')
            if self.author_input is not None:
                self.author_input.setText(current_search.get('author', '') or '')
            for t in current_search.get('include_tags', []) or []:
                self.include_list.addItem(t)
            for t in current_search.get('exclude_tags', []) or []:
                self.exclude_list.addItem(t)

        self._suppress_filter_signals = True
        try:
            self.chk_sort_by_views.setChecked(
                bool(current_filters.get('sort_by_views', False))
            )
            self.chk_group_by_series.setChecked(
                bool(current_filters.get('group_by_series', False))
            )
            if self.chk_group_by_authors is not None:
                self.chk_group_by_authors.setChecked(
                    bool(current_filters.get('group_by_authors', False))
                )
        finally:
            self._suppress_filter_signals = False

    def _update_tag_combos(self):
        try:
            tags = self.db.get_all_tags()
        except Exception:
            tags = []
        names = [t['name'] if isinstance(t, dict) else t for t in tags]

        # Скрытые теги не показываем в фильтре — они и так нигде не видны
        hidden = self._read_hidden_tags()
        if hidden:
            hidden_set = set(hidden)
            names = [n for n in names if n not in hidden_set]

        try:
            no_tags = self.db.NO_TAGS_NAME
        except Exception:
            no_tags = 'без тегов'
        if no_tags not in names:
            names.insert(0, no_tags)

        self.include_combo.clear()
        self.exclude_combo.clear()
        self.include_combo.addItems(names)
        self.exclude_combo.addItems(names)

    @staticmethod
    def _read_hidden_tags():
        """Читает список скрытых тегов из appearance_config.json."""
        try:
            from paths import CONFIG_PATH
            if not os.path.isfile(CONFIG_PATH):
                return []
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return list(data.get('hidden_tags', []) or [])
        except Exception:
            pass
        return []

    # ---------- обработчики ----------

    @staticmethod
    def _add_tag_to_list(combo, list_widget):
        tag = combo.currentText().strip()
        if not tag:
            return
        existing = [list_widget.item(i).text()
                    for i in range(list_widget.count())]
        if tag not in existing:
            list_widget.addItem(tag)

    def _add_include_tag(self):
        self._add_tag_to_list(self.include_combo, self.include_list)

    def _add_exclude_tag(self):
        self._add_tag_to_list(self.exclude_combo, self.exclude_list)

    def _on_filters_toggled(self, _checked=None):
        if self._suppress_filter_signals:
            return
        filters = {
            'sort_by_views': self.chk_sort_by_views.isChecked(),
            'group_by_series': self.chk_group_by_series.isChecked(),
            'group_by_authors': (self.chk_group_by_authors.isChecked()
                                 if self.chk_group_by_authors is not None
                                 else False),
        }
        self.filters_changed.emit(filters)

    def _on_search_apply(self):
        params = {
            'title': self.title_input.text().strip(),
            'include_tags': [self.include_list.item(i).text()
                             for i in range(self.include_list.count())],
            'exclude_tags': [self.exclude_list.item(i).text()
                             for i in range(self.exclude_list.count())],
            'author': (self.author_input.text().strip()
                       if self.author_input is not None else ''),
        }
        self.search_applied.emit(params)
        self.accept()