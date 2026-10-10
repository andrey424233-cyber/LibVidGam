"""Локальное обновление приложения.

Windows:
  Создаёт .bat-скрипт, который дожидается закрытия приложения,
  заменяет файлы кода и перезапускает новую версию.

Linux / macOS:
  Автоматическое обновление через .bat не работает (нет .bat).
  Функция apply_update_and_restart() возвращает False — приложение
  сообщит пользователю, что на этой ОС обновление через файл
  не поддерживается. Обновляться можно вручную (распаковать архив
  поверх папки приложения).

ВАЖНО: zip обновления содержит только файлы кода. Данные пользователя
(comics.db, appearance_config.json, covers/, ...) не затрагиваются.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from typing import Optional, Callable


IS_WINDOWS = sys.platform == 'win32'


UPDATES_SUBDIR = '_updates'
STAGED_SUBDIR = 'staged'
STAGED_APP_SUBDIR = 'LibVidGam'
LATEST_MANIFEST = 'latest.json'
LAUNCH_LOG_NAME = '_update_launch.log'


# ============================================================
# Версии
# ============================================================

def parse_version(s: str):
    if not s:
        return (0,)
    parts = re.findall(r'\d+', str(s))
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts)


def version_is_newer(remote: str, local: str) -> bool:
    try:
        return parse_version(remote) > parse_version(local)
    except Exception:
        return False


# ============================================================
# Диагностика
# ============================================================

def _log_launch_error(app_dir: str, message: str):
    """Пишет сообщение в _update_launch.log и в print."""
    print(f"[updater] {message}")
    try:
        path = os.path.join(app_dir, LAUNCH_LOG_NAME)
        with open(path, 'a', encoding='utf-8') as f:
            import datetime
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] "
                    f"{message}\n")
    except Exception:
        pass


# ============================================================
# Проверка обновления
# ============================================================

def check_for_update(updates_dir: str,
                     current_version: str) -> Optional[dict]:
    """Читает latest.json из папки обновлений.

    Работает на любой ОС — просто читает локальный JSON.
    """
    if not updates_dir or not os.path.isdir(updates_dir):
        return None

    manifest_path = os.path.join(updates_dir, LATEST_MANIFEST)
    if not os.path.isfile(manifest_path):
        return None

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[updater] read manifest: {e}")
        return None

    if not isinstance(data, dict):
        return None

    version = str(data.get('version', '')).strip()
    if not version:
        return None

    if not version_is_newer(version, current_version):
        return None

    zip_name = str(data.get('zip', '')).strip()
    if not zip_name:
        return None

    zip_path = os.path.join(updates_dir, zip_name)
    if not os.path.isfile(zip_path):
        print(f"[updater] zip not found: {zip_path}")
        return None

    return {
        'version': version,
        'release_date': str(data.get('release_date', '')),
        'changelog': str(data.get('changelog', '')),
        'zip': zip_name,
        'zip_path': zip_path,
        'sha256': str(data.get('sha256', '')),
        'size': int(data.get('size', 0) or 0),
        'mandatory': bool(data.get('mandatory', False)),
        'updates_dir': updates_dir,
    }


# ============================================================
# Проверка целостности
# ============================================================

def _sha256_of_file(path: str,
                    on_progress: Optional[Callable[[int, int], None]] = None):
    h = hashlib.sha256()
    try:
        total = os.path.getsize(path)
    except OSError:
        total = 0
    done = 0
    try:
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                done += len(chunk)
                if on_progress:
                    try:
                        on_progress(done, total)
                    except Exception:
                        pass
    except Exception as e:
        print(f"[updater] sha256: {e}")
        return ''
    return h.hexdigest()


# ============================================================
# Пути staged-папки
# ============================================================

def _updates_root(app_dir: str) -> str:
    return os.path.join(app_dir, UPDATES_SUBDIR)


def _staged_root(app_dir: str) -> str:
    return os.path.join(_updates_root(app_dir), STAGED_SUBDIR)


def _staged_app_dir(app_dir: str) -> str:
    return os.path.join(_staged_root(app_dir), STAGED_APP_SUBDIR)


def clean_staged(app_dir: str):
    """Удаляет папку _updates/staged/, если она есть."""
    staged = _staged_root(app_dir)
    if os.path.isdir(staged):
        try:
            shutil.rmtree(staged, ignore_errors=True)
        except Exception as e:
            print(f"[updater] clean_staged: {e}")


# ============================================================
# Распаковка обновления в staged
# ============================================================

def stage_update(app_dir: str, zip_path: str,
                 expected_sha256: str = '',
                 on_progress: Optional[Callable[[int, int], None]] = None,
                 on_hash_progress: Optional[Callable[[int, int], None]] = None):
    """Распаковывает zip в _updates/staged/LibVidGam/.

    Проверяет sha256, если expected_sha256 не пустой.
    Бросает RuntimeError при любой проблеме.

    Работает на любой ОС — только файловые операции.
    """
    if not os.path.isfile(zip_path):
        raise RuntimeError(f"Файл обновления не найден: {zip_path}")

    # 1. Проверка хеша
    if expected_sha256:
        actual = _sha256_of_file(zip_path, on_hash_progress)
        if actual.lower() != expected_sha256.lower():
            raise RuntimeError(
                f"Хеш не совпал.\n"
                f"Ожидался: {expected_sha256[:16]}...\n"
                f"Получен:  {actual[:16]}..."
            )

    # 2. Очистка старой стадии
    clean_staged(app_dir)

    staged_app = _staged_app_dir(app_dir)
    try:
        os.makedirs(staged_app, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"Не удалось создать папку распаковки: {e}")

    # 3. Распаковка
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            members = zf.infolist()
            total_bytes = sum(m.file_size for m in members) or 1
            done = 0
            for m in members:
                zf.extract(m, staged_app)
                done += m.file_size
                if on_progress:
                    try:
                        on_progress(done, total_bytes)
                    except Exception:
                        pass
    except Exception as e:
        clean_staged(app_dir)
        raise RuntimeError(f"Ошибка распаковки: {e}")

    # 4. Разворачиваем вложенную LibVidGam/ если она есть
    exe_candidate = os.path.join(staged_app, 'LibVidGam.exe')
    if not os.path.isfile(exe_candidate):
        inner = os.path.join(staged_app, 'LibVidGam')
        if os.path.isfile(os.path.join(inner, 'LibVidGam.exe')):
            try:
                for name in os.listdir(inner):
                    src = os.path.join(inner, name)
                    dst = os.path.join(staged_app, name)
                    if os.path.exists(dst):
                        if os.path.isdir(dst):
                            shutil.rmtree(dst, ignore_errors=True)
                        else:
                            os.remove(dst)
                    shutil.move(src, dst)
                os.rmdir(inner)
            except Exception as e:
                clean_staged(app_dir)
                raise RuntimeError(
                    f"Ошибка разворачивания вложенной папки: {e}"
                )

    # Финальная проверка
    exe_candidate = os.path.join(staged_app, 'LibVidGam.exe')
    if not os.path.isfile(exe_candidate):
        # На Linux имя другое — ищем любой файл, похожий на исполняемый
        if not IS_WINDOWS:
            found_any = False
            for name in os.listdir(staged_app):
                if name.lower() == 'libvidgam' or \
                   name.lower().startswith('main'):
                    found_any = True
                    break
            if found_any:
                return staged_app
        clean_staged(app_dir)
        raise RuntimeError(
            "В архиве обновления не найден LibVidGam.exe.\n"
            "Проверьте структуру zip."
        )

    return staged_app


# ============================================================
# BAT-скрипт применения (только Windows)
# ============================================================

if IS_WINDOWS:
    def _write_update_bat(bat_path: str) -> None:
        """Создаёт bat-скрипт. Пути берутся из переменных окружения:
           LIBVIDGAM_APP     — папка приложения (куда копировать)
           LIBVIDGAM_STAGED  — staged папка (откуда брать новое)
           LIBVIDGAM_LOG     — путь к update.log
        """
        lines = [
            '@echo off',
            'setlocal',
            '',
            'if "%LIBVIDGAM_APP%"=="" (',
            '    echo ERROR: LIBVIDGAM_APP not set',
            '    exit /b 1',
            ')',
            '',
            'set "LOG=%LIBVIDGAM_LOG%"',
            'if "%LOG%"=="" set "LOG=%TEMP%\\libvidgam_update.log"',
            '',
            'echo. >> "%LOG%"',
            'echo [%date% %time%] === update start === >> "%LOG%"',
            'echo [%date% %time%] APP=%LIBVIDGAM_APP% >> "%LOG%"',
            'echo [%date% %time%] STAGED=%LIBVIDGAM_STAGED% >> "%LOG%"',
            '',
            'cd /d "%LIBVIDGAM_APP%"',
            'if errorlevel 1 (',
            '    echo [%date% %time%] ERROR: cannot cd to APP >> "%LOG%"',
            '    exit /b 1',
            ')',
            'echo [%date% %time%] cwd: %CD% >> "%LOG%"',
            '',
            'rem ---- Ждём, пока закроется процесс ----',
            ':wait_loop',
            'tasklist /fi "IMAGENAME eq LibVidGam.exe" 2>nul | find /i "LibVidGam.exe" >nul',
            'if not errorlevel 1 (',
            '    ping -n 2 127.0.0.1 >nul',
            '    goto wait_loop',
            ')',
            'echo [%date% %time%] old process closed >> "%LOG%"',
            '',
            'rem ---- Проверяем staged ----',
            'if not exist "%LIBVIDGAM_STAGED%\\LibVidGam.exe" (',
            '    echo [%date% %time%] ERROR: staged exe missing >> "%LOG%"',
            '    exit /b 1',
            ')',
            'echo [%date% %time%] staged ok >> "%LOG%"',
            '',
            'rem ---- Резервная копия ----',
            'set "BACKUP=%LIBVIDGAM_APP%\\_backup_update"',
            'if exist "%BACKUP%" rmdir /s /q "%BACKUP%" 2>nul',
            'mkdir "%BACKUP%" 2>nul',
            'if exist "LibVidGam.exe" copy /y "LibVidGam.exe" "%BACKUP%\\LibVidGam.exe" >nul 2>&1',
            'if exist "icon.ico" copy /y "icon.ico" "%BACKUP%\\icon.ico" >nul 2>&1',
            'if exist "UnRAR.exe" copy /y "UnRAR.exe" "%BACKUP%\\UnRAR.exe" >nul 2>&1',
            'if exist "7z.exe" copy /y "7z.exe" "%BACKUP%\\7z.exe" >nul 2>&1',
            'if exist "_internal" xcopy /e /i /y /q "_internal" "%BACKUP%\\_internal" >nul 2>&1',
            'echo [%date% %time%] backup created >> "%LOG%"',
            '',
            'rem ---- Удаляем старый код ----',
            'if exist "LibVidGam.exe" del /f /q "LibVidGam.exe" 2>>"%LOG%"',
            'if exist "icon.ico" del /f /q "icon.ico" 2>>"%LOG%"',
            'if exist "UnRAR.exe" del /f /q "UnRAR.exe" 2>>"%LOG%"',
            'if exist "7z.exe" del /f /q "7z.exe" 2>>"%LOG%"',
            'if exist "_internal" rmdir /s /q "_internal" 2>>"%LOG%"',
            'echo [%date% %time%] old code removed >> "%LOG%"',
            '',
            'rem ---- Копируем новое ----',
            'copy /y "%LIBVIDGAM_STAGED%\\LibVidGam.exe" "LibVidGam.exe" >>"%LOG%" 2>&1',
            'if exist "%LIBVIDGAM_STAGED%\\icon.ico" copy /y "%LIBVIDGAM_STAGED%\\icon.ico" "icon.ico" >>"%LOG%" 2>&1',
            'if exist "%LIBVIDGAM_STAGED%\\UnRAR.exe" copy /y "%LIBVIDGAM_STAGED%\\UnRAR.exe" "UnRAR.exe" >>"%LOG%" 2>&1',
            'if exist "%LIBVIDGAM_STAGED%\\7z.exe" copy /y "%LIBVIDGAM_STAGED%\\7z.exe" "7z.exe" >>"%LOG%" 2>&1',
            'if exist "%LIBVIDGAM_STAGED%\\_internal" xcopy /e /i /y /q "%LIBVIDGAM_STAGED%\\_internal" "_internal" >>"%LOG%" 2>&1',
            'echo [%date% %time%] new code copied >> "%LOG%"',
            '',
            'rem ---- Проверка ----',
            'if not exist "LibVidGam.exe" (',
            '    echo [%date% %time%] ERROR: exe not copied, restoring >> "%LOG%"',
            '    goto restore',
            ')',
            '',
            'rem ---- Запуск ----',
            'echo [%date% %time%] starting new exe >> "%LOG%"',
            'start "" "LibVidGam.exe"',
            'ping -n 5 127.0.0.1 >nul',
            'if exist "%LIBVIDGAM_STAGED%" rmdir /s /q "%LIBVIDGAM_STAGED%" 2>nul',
            'if exist "%BACKUP%" rmdir /s /q "%BACKUP%" 2>nul',
            'echo [%date% %time%] === done === >> "%LOG%"',
            'goto cleanup',
            '',
            ':restore',
            'if exist "%BACKUP%\\LibVidGam.exe" copy /y "%BACKUP%\\LibVidGam.exe" "LibVidGam.exe" >>"%LOG%" 2>&1',
            'if exist "%BACKUP%\\icon.ico" copy /y "%BACKUP%\\icon.ico" "icon.ico" >>"%LOG%" 2>&1',
            'if exist "%BACKUP%\\UnRAR.exe" copy /y "%BACKUP%\\UnRAR.exe" "UnRAR.exe" >>"%LOG%" 2>&1',
            'if exist "%BACKUP%\\7z.exe" copy /y "%BACKUP%\\7z.exe" "7z.exe" >>"%LOG%" 2>&1',
            'if exist "%BACKUP%\\_internal" xcopy /e /i /y /q "%BACKUP%\\_internal" "_internal" >>"%LOG%" 2>&1',
            'start "" "LibVidGam.exe"',
            'echo [%date% %time%] restored from backup >> "%LOG%"',
            '',
            ':cleanup',
            'del /f /q "%~f0" 2>nul',
            'exit /b 0',
            '',
        ]

        with open(bat_path, 'w', encoding='cp866', newline='\r\n') as f:
            f.write('\n'.join(lines))


# ============================================================
# Применение и перезапуск
# ============================================================

def apply_update_and_restart(app_dir: str) -> bool:
    """Создаёт bat-скрипт (только Windows) и запускает его.

    Возвращает True, если приложение должно закрыться.

    На Linux / macOS возвращает False — автоматическое обновление
    через файл не поддерживается. Пользователь обновляется вручную.
    """
    if not IS_WINDOWS:
        _log_launch_error(
            app_dir,
            "Автообновление недоступно на этой ОС. "
            "Распакуйте архив обновления поверх папки приложения."
        )
        return False

    staged_app = _staged_app_dir(app_dir)
    staged_exe = os.path.join(staged_app, 'LibVidGam.exe')
    if not os.path.isfile(staged_exe):
        _log_launch_error(app_dir, f"staged exe not found: {staged_exe}")
        return False

    log_path = os.path.join(app_dir, 'update.log')

    try:
        tmp_dir = tempfile.gettempdir()
        short_bat = os.path.join(tmp_dir, '_libvidgam_apply_update.bat')
        _write_update_bat(short_bat)
    except Exception as e:
        _log_launch_error(app_dir, f"write bat: {e}")
        return False

    env = os.environ.copy()
    env['LIBVIDGAM_APP'] = app_dir
    env['LIBVIDGAM_STAGED'] = staged_app
    env['LIBVIDGAM_LOG'] = log_path

    try:
        CREATE_NO_WINDOW = 0x08000000
        cmd_line = f'cmd.exe /c "{short_bat}"'
        _log_launch_error(app_dir, f"launching: {cmd_line}")
        subprocess.Popen(
            cmd_line,
            cwd=app_dir,
            creationflags=CREATE_NO_WINDOW,
            shell=True,
            close_fds=True,
            env=env,
        )
        return True
    except Exception as e:
        _log_launch_error(app_dir, f"launch bat failed: {e}")
        return False


# ============================================================
# Утилиты
# ============================================================

def has_pending_update(app_dir: str) -> bool:
    staged_app = _staged_app_dir(app_dir)
    return os.path.isfile(os.path.join(staged_app, 'LibVidGam.exe'))


def cleanup_old_update_artifacts(app_dir: str):
    """Удаляет старые bat-файлы и временные артефакты.

    На Linux ничего не делает — .bat там не создаются.
    """
    if not IS_WINDOWS:
        return

    try:
        for name in os.listdir(app_dir):
            if name.startswith('_apply_update') and name.endswith('.bat'):
                try:
                    os.remove(os.path.join(app_dir, name))
                except OSError:
                    pass
    except OSError:
        pass

    try:
        tmp_bat = os.path.join(tempfile.gettempdir(),
                               '_libvidgam_apply_update.bat')
        if os.path.isfile(tmp_bat):
            os.remove(tmp_bat)
    except OSError:
        pass


def cleanup_update_residue(app_dir: str):
    """Убирает артефакты, оставшиеся от прошлых обновлений:
       - update.log, _update_launch.log
       - _updates/ (если staged пуст)
       - app (пустой файл-мусор)
       - _apply_update.bat
       - _backup_update/ (если основной exe на месте)

    Вызывается при старте приложения ДО показа главного окна.
    Работает на любой ОС.
    """
    # 1. Логи обновления
    for name in ('update.log', '_update_launch.log'):
        try:
            p = os.path.join(app_dir, name)
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass

    # 2. Папка _updates — удаляем только если внутри нет staged с exe
    try:
        staged_exe = os.path.join(_staged_app_dir(app_dir), 'LibVidGam.exe')
        if not os.path.isfile(staged_exe):
            updates_root = _updates_root(app_dir)
            if os.path.isdir(updates_root):
                shutil.rmtree(updates_root, ignore_errors=True)
    except Exception:
        pass

    # 3. Пустой файл `app` (без расширения) — мусор от старых bat
    try:
        p = os.path.join(app_dir, 'app')
        if os.path.isfile(p) and os.path.getsize(p) == 0:
            os.remove(p)
    except OSError:
        pass

    # 4. Старый _apply_update.bat (только Windows)
    if IS_WINDOWS:
        try:
            for name in os.listdir(app_dir):
                if name.startswith('_apply_update') and name.endswith('.bat'):
                    try:
                        os.remove(os.path.join(app_dir, name))
                    except OSError:
                        pass
        except OSError:
            pass

    # 5. _backup_update — если основной exe уже на месте
    try:
        backup = os.path.join(app_dir, '_backup_update')
        if os.path.isdir(backup):
            main_exe = os.path.join(app_dir, 'LibVidGam.exe')
            if os.path.isfile(main_exe):
                shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        pass