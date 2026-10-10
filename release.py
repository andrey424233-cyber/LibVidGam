"""Скрипт сборки релиза LibVidGam.

Что делает:
  1. Читает APP_VERSION из paths.py.
  2. Запускает pyinstaller LibVidGam.spec.
  3. Пакует dist/LibVidGam/ в LibVidGam-<версия>.zip.
  4. Считает SHA-256 и размер zip.
  5. Кладёт zip в папку обновлений.
  6. Обновляет latest.json в папке обновлений.

Использование:
    python release.py "D:\\LibVidGam_updates"

Если папка не указана — берётся updates_dir из appearance_config.json
или из переменной окружения LIBVIDGAM_UPDATES_DIR.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime


HERE = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(HERE, 'dist', 'LibVidGam')
SPEC_FILE = os.path.join(HERE, 'LibVidGam.spec')
CONFIG_PATH = os.path.join(HERE, 'appearance_config.json')

# Файлы и папки, которые НЕ попадают в zip обновления
# (данные пользователя, кэш, dev-мусор)
# Файлы и папки, которые НЕ попадают в zip обновления.
# Сравнение по имени, но с поддержкой вариантов без расширения.
EXCLUDE_FROM_ZIP = {
    'comics.db', 'comics.db-wal', 'comics.db-shm',
    'comics',           # без расширения
    'comics-wal', 'comics-shm',
    'appearance_config.json',
    'game_archive_passwords.json',
    'app.log', 'app',
    'update.log', 'update',
    'covers', 'tag_covers', 'author_covers', 'game_covers',
    '_updates', '_backup_update',
    'backup',
    '_apply_update.bat',
}


def read_version():
    """Читает APP_VERSION из paths.py без импорта модуля."""
    paths_file = os.path.join(HERE, 'paths.py')
    if not os.path.isfile(paths_file):
        raise RuntimeError("paths.py не найден")
    with open(paths_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith('APP_VERSION'):
                # APP_VERSION = "1.0.0"
                parts = line.split('=', 1)
                if len(parts) == 2:
                    val = parts[1].strip().strip('"').strip("'")
                    return val
    raise RuntimeError("APP_VERSION не найден в paths.py")


def resolve_updates_dir(argv):
    """Определяет папку обновлений."""
    # 1. Аргумент командной строки
    if len(argv) > 1:
        return os.path.abspath(argv[1])

    # 2. Переменная окружения
    env_dir = os.environ.get('LIBVIDGAM_UPDATES_DIR', '').strip()
    if env_dir:
        return os.path.abspath(env_dir)

    # 3. appearance_config.json
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            cfg_dir = (cfg.get('updates_dir') or '').strip()
            if cfg_dir:
                return os.path.abspath(cfg_dir)
        except Exception:
            pass

    return None


def run_pyinstaller():
    """Запускает pyinstaller LibVidGam.spec."""
    print("[release] Запуск PyInstaller…")
    if not os.path.isfile(SPEC_FILE):
        raise RuntimeError(f"Не найден {SPEC_FILE}")

    t0 = time.time()
    result = subprocess.run(
        ['pyinstaller', '--clean', SPEC_FILE],
        cwd=HERE,
        shell=False,
    )
    elapsed = time.time() - t0
    if result.returncode != 0:
        raise RuntimeError(
            f"PyInstaller завершился с кодом {result.returncode}"
        )
    print(f"[release] PyInstaller OK ({elapsed:.1f}с)")


def make_zip(zip_path):
    """Пакует dist/LibVidGam/ в zip, пропуская данные пользователя."""
    if not os.path.isdir(DIST_DIR):
        raise RuntimeError(f"Не найдена папка сборки: {DIST_DIR}")

    print(f"[release] Паковка в {os.path.basename(zip_path)}…")
    files_added = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(DIST_DIR):
            # Фильтруем папки
            dirs[:] = [d for d in dirs if d not in EXCLUDE_FROM_ZIP]

            for fname in files:
                # Пропускаем файлы данных и служебные
                if fname in EXCLUDE_FROM_ZIP:
                    continue
                # Пропускаем любые .db, .db-wal, .db-shm, .log
                low = fname.lower()
                if low.endswith('.db') or low.endswith('.db-wal') \
                        or low.endswith('.db-shm') or low.endswith('.log'):
                    continue
                # Пропускаем json-конфиги приложения
                if low in ('appearance_config.json',
                           'game_archive_passwords.json'):
                    continue
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, DIST_DIR)
                try:
                    zf.write(full, rel)
                    files_added += 1
                except Exception as e:
                    print(f"[release] пропуск {rel}: {e}")

    print(f"[release] В архив добавлено файлов: {files_added}")
    return files_added


def sha256_of_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def update_manifest(updates_dir, version, zip_name, zip_size, zip_hash,
                    changelog=''):
    """Создаёт/обновляет latest.json в папке обновлений."""
    manifest_path = os.path.join(updates_dir, 'latest.json')
    data = {
        'version': version,
        'release_date': datetime.now().strftime('%Y-%m-%d'),
        'changelog': changelog,
        'zip': zip_name,
        'sha256': zip_hash,
        'size': zip_size,
        'mandatory': False,
    }
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return manifest_path


def main():
    print("=" * 60)
    print(" LibVidGam — сборка релиза")
    print("=" * 60)

    # 1. Версия
    try:
        version = read_version()
    except Exception as e:
        print(f"[release] ОШИБКА: {e}")
        sys.exit(1)
    print(f"[release] Версия: {version}")

    # 2. Папка обновлений
    updates_dir = resolve_updates_dir(sys.argv)
    if not updates_dir:
        print()
        print("Папка обновлений не указана.")
        print("Использование:")
        print(f'  python release.py "D:\\путь\\к\\папке_обновлений"')
        print()
        print("Или задайте переменную окружения LIBVIDGAM_UPDATES_DIR,")
        print("или укажите updates_dir в appearance_config.json.")
        sys.exit(1)

    if not os.path.isdir(updates_dir):
        try:
            os.makedirs(updates_dir, exist_ok=True)
            print(f"[release] Создана папка: {updates_dir}")
        except Exception as e:
            print(f"[release] ОШИБКА создания папки: {e}")
            sys.exit(1)

    print(f"[release] Папка обновлений: {updates_dir}")

    # 3. PyInstaller
    try:
        run_pyinstaller()
    except Exception as e:
        print(f"[release] ОШИБКА PyInstaller: {e}")
        sys.exit(1)

    # 4. Zip
    zip_name = f"LibVidGam-{version}.zip"
    zip_path = os.path.join(updates_dir, zip_name)
    if os.path.isfile(zip_path):
        print(f"[release] Уже существует, перезаписываем: {zip_name}")

    try:
        make_zip(zip_path)
    except Exception as e:
        print(f"[release] ОШИБКА упаковки: {e}")
        sys.exit(1)

    # 5. Хеш и размер
    print("[release] Вычисление SHA-256…")
    try:
        zip_size = os.path.getsize(zip_path)
        zip_hash = sha256_of_file(zip_path)
    except Exception as e:
        print(f"[release] ОШИБКА подсчёта: {e}")
        sys.exit(1)

    print(f"[release] Размер:  {zip_size / 1024 / 1024:.1f} МБ")
    print(f"[release] SHA-256: {zip_hash[:32]}…")

    # 6. Манифест
    changelog = os.environ.get('LIBVIDGAM_CHANGELOG', '').strip()
    try:
        manifest_path = update_manifest(
            updates_dir, version, zip_name, zip_size, zip_hash,
            changelog=changelog,
        )
    except Exception as e:
        print(f"[release] ОШИБКА записи манифеста: {e}")
        sys.exit(1)

    # 7. Итог
    print()
    print("=" * 60)
    print(" ГОТОВО")
    print("=" * 60)
    print(f"  Версия:       {version}")
    print(f"  Zip-архив:    {zip_path}")
    print(f"  Манифест:     {manifest_path}")
    print()
    print("  Открой приложение → Настройки → Обновления →")
    print("  укажи папку и нажми «Проверить обновления».")
    print()


if __name__ == '__main__':
    main()