"""Настройки библиотек: три переключателя на каждую.

Хранятся в appearance_config.json рядом с остальными настройками.
Ключи:
    <lib>_sort_by_views     — сортировать по просмотрам/запускам
    <lib>_group_by_series   — группировать по сериям
    <lib>_group_by_authors  — группировать по авторам

lib ∈ {'comics', 'videos', 'games'}.
"""
import json
import os
import threading

from paths import CONFIG_PATH


_LOCK = threading.RLock()

DEFAULTS = {
    'sort_by_views': False,
    'group_by_series': False,
    'group_by_authors': False,
}


def _load() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _save(cfg: dict):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[library_config] save: {e}")


def get_settings(library: str) -> dict:
    """Возвращает dict с тремя флагами для указанной библиотеки."""
    with _LOCK:
        cfg = _load()
    return {
        key: bool(cfg.get(f'{library}_{key}', DEFAULTS[key]))
        for key in DEFAULTS
    }


def set_setting(library: str, key: str, value: bool):
    """Сохраняет один флаг."""
    if key not in DEFAULTS:
        return
    with _LOCK:
        cfg = _load()
        cfg[f'{library}_{key}'] = bool(value)
        _save(cfg)


def set_settings(library: str, **kwargs):
    """Сохраняет несколько флагов сразу."""
    with _LOCK:
        cfg = _load()
        for k, v in kwargs.items():
            if k in DEFAULTS:
                cfg[f'{library}_{k}'] = bool(v)
        _save(cfg)