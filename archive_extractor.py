"""Распаковка архивов (zip/rar/7z) для игр.

Приоритет внешних инструментов (unrar.exe / 7z.exe):
  * они в 5–10 раз быстрее, чем rarfile/py7zr (те читают архив через Python),
  * корректно работают с кириллицей в именах файлов (py7zr этим печально известен),
  * умеют многотомные архивы и понимают AES-шифрование.

Fallback на Python-библиотеки — если внешних утилит нет.

Оптимизация: сначала ищем игру в уже распакованной папке. Если нашли —
вложенные архивы вообще не трогаем.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile

try:
    import rarfile
    HAS_RARFILE = True
except ImportError:
    HAS_RARFILE = False

try:
    import py7zr
    HAS_PY7ZR = True
except ImportError:
    HAS_PY7ZR = False

try:
    import pyzipper
    HAS_PYZIPPER = True
except ImportError:
    HAS_PYZIPPER = False


ARCHIVE_EXTENSIONS = {'.zip', '.rar', '.7z'}
EXTRACTED_SUFFIX = '.extracted'
PASSWORDS_FILE = 'game_archive_passwords.json'

NESTED_ARCHIVE_MAX_DEPTH = 2

# Сколько секунд ждать распаковку одного архива. Распаковка 20 ГБ
# на HDD занимает 10–20 минут, поэтому лимит довольно щедрый.
EXTRACT_TIMEOUT_SEC = 3600


# Ленивая инициализация
_TOOLS_LOCK = threading.Lock()
_TOOLS_READY = False
UNRAR_PATH_FOUND = ''
SEVENZIP_PATH_FOUND = ''


# ---------- поиск кандидатов ----------

def _candidates_from_registry():
    result = []
    if sys.platform != 'win32':
        return result
    try:
        import winreg
    except ImportError:
        return result

    keys_to_check = [
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WinRAR'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\WinRAR'),
        (winreg.HKEY_CURRENT_USER, r'SOFTWARE\WinRAR'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\7-Zip'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\7-Zip'),
        (winreg.HKEY_CURRENT_USER, r'SOFTWARE\7-Zip'),
    ]
    for hive, key_path in keys_to_check:
        try:
            with winreg.OpenKey(hive, key_path) as k:
                for val_name in ('exe64', 'exe32', 'Path',
                                 'Path64', 'Path32'):
                    try:
                        val, _ = winreg.QueryValueEx(k, val_name)
                    except FileNotFoundError:
                        continue
                    if not val:
                        continue
                    if os.path.isfile(val):
                        folder = os.path.dirname(val)
                    elif os.path.isdir(val):
                        folder = val
                    else:
                        continue
                    for name in ('UnRAR.exe', 'Rar.exe',
                                 '7z.exe', '7za.exe'):
                        p = os.path.join(folder, name)
                        if os.path.isfile(p):
                            result.append(p)
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return result


def _collect_candidates(names, subfolders):
    cands = []
    for name in names:
        p = shutil.which(name)
        if p:
            cands.append(p)
    here = os.path.dirname(os.path.abspath(__file__))
    for name in names:
        p = os.path.join(here, name)
        if os.path.isfile(p):
            cands.append(p)
    cands.extend(_candidates_from_registry())
    bases = [
        os.environ.get('ProgramFiles'),
        os.environ.get('ProgramFiles(x86)'),
        os.environ.get('ProgramW6432'),
        r'C:\Program Files',
        r'C:\Program Files (x86)',
        r'C:\WinRAR',
        r'C:\RAR',
        r'C:\7-Zip',
        r'D:\Program Files',
        r'D:\Program Files (x86)',
        r'D:\WinRAR',
        r'D:\7-Zip',
    ]
    for base in bases:
        if not base:
            continue
        for folder in subfolders:
            for name in names:
                p = os.path.join(base, folder, name)
                if os.path.isfile(p):
                    cands.append(p)
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        for name in names:
            p = os.path.join(meipass, name)
            if os.path.isfile(p):
                cands.append(p)
    seen = set()
    unique = []
    for c in cands:
        c_norm = os.path.normcase(os.path.normpath(c))
        if c_norm in seen:
            continue
        seen.add(c_norm)
        unique.append(c)
    return unique


def _find_unrar():
    return _collect_candidates(
        ('UnRAR.exe', 'unrar.exe', 'Rar.exe', 'rar.exe'),
        ('WinRAR', 'RAR', 'UnRAR'),
    )


def _find_7zip():
    return _collect_candidates(
        ('7z.exe', '7za.exe', '7zr.exe'),
        ('7-Zip', '7zip'),
    )


def ensure_tools_configured():
    global _TOOLS_READY, UNRAR_PATH_FOUND, SEVENZIP_PATH_FOUND
    if _TOOLS_READY:
        return
    with _TOOLS_LOCK:
        if _TOOLS_READY:
            return
        try:
            if HAS_RARFILE:
                for cand in _find_unrar():
                    if os.path.isfile(cand) and os.access(cand, os.X_OK):
                        try:
                            rarfile.UNRAR_TOOL = cand
                            UNRAR_PATH_FOUND = cand
                            print(f"[archive_extractor] UnRAR: {cand}")
                            break
                        except Exception:
                            continue
                if not UNRAR_PATH_FOUND:
                    print("[archive_extractor] UnRAR.exe не найден — "
                          "для .rar будет использован 7-Zip")

            for cand in _find_7zip():
                if os.path.isfile(cand):
                    SEVENZIP_PATH_FOUND = cand
                    print(f"[archive_extractor] 7-Zip: {cand}")
                    break

            if not SEVENZIP_PATH_FOUND and not UNRAR_PATH_FOUND:
                print("[archive_extractor] ВНИМАНИЕ: ни UnRAR, "
                      "ни 7-Zip не найдены.")
        finally:
            _TOOLS_READY = True


# ---------- утилиты ----------

def is_archive(path: str) -> bool:
    if path.lower().endswith(EXTRACTED_SUFFIX):
        return False
    return os.path.splitext(path)[1].lower() in ARCHIVE_EXTENSIONS


def is_extracted_marker(path: str) -> bool:
    return path.lower().endswith(EXTRACTED_SUFFIX)


def mark_as_extracted(archive_path: str) -> str:
    if is_extracted_marker(archive_path):
        return archive_path
    new_path = archive_path + EXTRACTED_SUFFIX
    try:
        if not os.path.exists(new_path):
            os.rename(archive_path, new_path)
        return new_path
    except Exception as e:
        print(f"[archive_extractor] mark_as_extracted: {e}")
        return archive_path


def unmark_extracted(archive_path: str) -> str:
    if not is_extracted_marker(archive_path):
        return archive_path
    new_path = archive_path[:-len(EXTRACTED_SUFFIX)]
    try:
        if not os.path.exists(new_path):
            os.rename(archive_path, new_path)
        return new_path
    except Exception as e:
        print(f"[archive_extractor] unmark_extracted: {e}")
        return archive_path


def passwords_path_near(db_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(db_path)),
                        PASSWORDS_FILE)


def load_passwords(config_path: str) -> dict:
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_passwords(config_path: str, data: dict):
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[archive_extractor] save_passwords: {e}")


def get_password_for(passwords: dict, archive_name: str) -> str:
    name_lower = os.path.basename(archive_name).lower()
    if name_lower.endswith(EXTRACTED_SUFFIX):
        name_lower = name_lower[:-len(EXTRACTED_SUFFIX)]

    for key, pwd in passwords.items():
        k = key.strip()
        if k == '*' or not k:
            continue
        if k.lower() == name_lower:
            return str(pwd)

    best_len = 0
    best_pwd = None
    for key, pwd in passwords.items():
        k = key.strip()
        if k == '*' or not k:
            continue
        core = k.strip('*').strip().lower()
        if not core:
            continue
        if core in name_lower and len(core) > best_len:
            best_len = len(core)
            best_pwd = str(pwd)
    if best_pwd is not None:
        return best_pwd

    return str(passwords.get('*', '') or '')


# ---------- запуск внешних утилит ----------

def _run_extract_cmd(cmd, timeout=EXTRACT_TIMEOUT_SEC, log_fn=None,
                     progress_prefix="распаковка"):
    """Запускает внешнюю утилиту, читает stdout в отдельном потоке,
    логирует прогресс вида "42%". Возвращает (returncode, tail_text,
    duration_sec). При таймауте бросает RuntimeError.
    """
    if sys.platform == 'win32':
        try:
            creationflags = subprocess.CREATE_NO_WINDOW
        except AttributeError:
            creationflags = 0x08000000
    else:
        creationflags = 0

    t0 = time.time()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"Не найдена утилита: {cmd[0]}") from e

    tail = []
    max_tail = 60
    last_pct = -1
    last_log_time = [t0]

    def _reader():
        nonlocal last_pct
        try:
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b''):
                line = raw.decode('utf-8', errors='ignore').rstrip()
                if not line:
                    continue
                tail.append(line)
                if len(tail) > max_tail:
                    tail.pop(0)

                m = re.search(r'(\d{1,3})%', line)
                if not m:
                    continue
                try:
                    pct = int(m.group(1))
                except ValueError:
                    continue
                now = time.time()
                if (pct != last_pct and
                        (now - last_log_time[0] > 3 or pct - last_pct >= 5)):
                    last_pct = pct
                    last_log_time[0] = now
                    if log_fn:
                        try:
                            log_fn(f"{progress_prefix}: {pct}%")
                        except Exception:
                            pass
        except Exception:
            pass

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        reader.join(timeout=2)
        raise RuntimeError(
            f"Таймаут распаковки ({timeout} сек). "
            f"Возможно, файл слишком большой или завис."
        )
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass

    reader.join(timeout=3)
    duration = time.time() - t0
    return rc, "\n".join(tail), duration


# ---------- распаковка ----------

def _extract_via_7zip(archive_path: str, out_dir: str, password: str,
                      log_fn=None):
    """Распаковка через 7z.exe. Возвращает True при успехе,
    False — если 7z не смог (например, неверный формат),
    бросает RuntimeError при неверном пароле или битом архиве.
    """
    if not SEVENZIP_PATH_FOUND:
        return False

    cmd = [SEVENZIP_PATH_FOUND, 'x', f'-o{out_dir}', '-y',
           '-mmt=on', '-bso1', '-bse1']
    if password:
        cmd.append(f'-p{password}')
    else:
        # Голый -p заставит 7z запросить пароль; stdin у нас DEVNULL —
        # это приведёт к быстрому отказу вместо зависания.
        cmd.append('-p')
    cmd.append(archive_path)

    if log_fn:
        log_fn(f"7z: {os.path.basename(archive_path)}")
    rc, tail, dur = _run_extract_cmd(
        cmd, timeout=EXTRACT_TIMEOUT_SEC,
        log_fn=log_fn, progress_prefix="7z",
    )

    # 7z: 0 = OK, 1 = warning (частично извлеклось — часто это ок)
    if rc in (0, 1):
        if log_fn:
            log_fn(f"7z готово за {dur:.1f}с")
        return True

    low = tail.lower()
    if 'wrong password' in low or 'парол' in low or 'password' in low:
        raise RuntimeError("Неверный пароль")
    if 'data error' in low or 'crc' in low or 'corrupt' in low:
        raise RuntimeError("Повреждённый архив или неверный пароль")
    return False


def _extract_rar_via_unrar(archive_path: str, out_dir: str, password: str,
                           log_fn=None) -> bool:
    """Прямой вызов UnRAR.exe — самый быстрый способ для RAR."""
    if not UNRAR_PATH_FOUND:
        return False

    cmd = [UNRAR_PATH_FOUND, 'x', '-o+', '-idq']
    if password:
        cmd.append(f'-p{password}')
    else:
        # -p- = без пароля (быстрый отказ, если архив зашифрован)
        cmd.append('-p-')
    cmd.append(archive_path)
    # unrar требует, чтобы путь к out_dir заканчивался разделителем
    if not out_dir.endswith(os.sep):
        out_dir = out_dir + os.sep
    cmd.append(out_dir)

    if log_fn:
        log_fn(f"unrar: {os.path.basename(archive_path)}")
    rc, tail, dur = _run_extract_cmd(
        cmd, timeout=EXTRACT_TIMEOUT_SEC,
        log_fn=log_fn, progress_prefix="unrar",
    )

    if rc == 0:
        if log_fn:
            log_fn(f"unrar готово за {dur:.1f}с")
        return True

    low = tail.lower()
    if 'password' in low or 'парол' in low or 'wrong' in low:
        raise RuntimeError("Неверный пароль")
    if 'crc' in low or 'corrupt' in low or 'data error' in low:
        raise RuntimeError("Повреждённый архив")
    if 'volume' in low or 'first' in low:
        raise RuntimeError("Нужен первый том многотомного архива")
    return False


def _extract_zip(archive_path: str, out_dir: str, password: str,
                 log_fn=None):
    # Быстрый путь для незашифрованных zip — 7z.exe в разы быстрее
    if not password and SEVENZIP_PATH_FOUND:
        try:
            if _extract_via_7zip(archive_path, out_dir, '', log_fn):
                return
        except RuntimeError:
            # Скорее всего zip зашифрован — падаем в Python
            pass

    # pyzipper умеет AES-шифрование zip (его нет в стандартной библиотеке)
    if HAS_PYZIPPER and password:
        try:
            with pyzipper.AESZipFile(archive_path, 'r') as zf:
                zf.pwd = password.encode('utf-8')
                zf.extractall(out_dir)
                return
        except Exception:
            pass

    with zipfile.ZipFile(archive_path, 'r') as zf:
        pwd_bytes = password.encode('utf-8') if password else None
        zf.extractall(out_dir, pwd=pwd_bytes)


def _extract_rar(archive_path: str, out_dir: str, password: str,
                 log_fn=None):
    ensure_tools_configured()

    # 1) Прямой вызов UnRAR.exe — самый быстрый
    if UNRAR_PATH_FOUND:
        try:
            if _extract_rar_via_unrar(archive_path, out_dir, password, log_fn):
                return
        except RuntimeError:
            raise
        except Exception as e:
            print(f"[archive_extractor] unrar error: {e}")

    # 2) rarfile (Python, через UnRAR в фоне — медленнее)
    if HAS_RARFILE and UNRAR_PATH_FOUND:
        try:
            if log_fn:
                log_fn(f"rarfile: {os.path.basename(archive_path)}")
            with rarfile.RarFile(archive_path) as rf:
                if rf.needs_password() and not password:
                    raise RuntimeError("Архив защищён паролем")
                rf.extractall(out_dir, pwd=password if password else None)
                if log_fn:
                    log_fn("rarfile готово")
            return
        except rarfile.RarCannotExec:
            pass
        except rarfile.RarWrongPassword:
            raise RuntimeError("Неверный пароль")
        except rarfile.NeedFirstVolume:
            raise RuntimeError("Нужен первый том многотомного архива")
        except rarfile.Error as e:
            raise RuntimeError(f"rarfile: {e}")

    # 3) Fallback через 7-Zip
    if _extract_via_7zip(archive_path, out_dir, password, log_fn):
        return

    if not UNRAR_PATH_FOUND and not SEVENZIP_PATH_FOUND:
        raise RuntimeError(
            "Не найден ни UnRAR.exe, ни 7z.exe. "
            "Установите WinRAR или 7-Zip."
        )
    raise RuntimeError(
        "Не удалось распаковать RAR. Возможные причины: неверный пароль, "
        "битый архив, или нужен первый том многотомного архива."
    )


def _extract_7z(archive_path: str, out_dir: str, password: str,
                log_fn=None):
    # 1) Внешний 7z.exe — самый быстрый и совместимый
    if SEVENZIP_PATH_FOUND:
        try:
            if _extract_via_7zip(archive_path, out_dir, password, log_fn):
                return
        except RuntimeError:
            raise
        except Exception as e:
            print(f"[archive_extractor] 7z error: {e}")

    # 2) py7zr — медленный fallback
    if not HAS_PY7ZR:
        raise RuntimeError(
            "7z.exe не найден и py7zr не установлен. "
            "Установите 7-Zip или выполните: pip install py7zr"
        )
    try:
        if log_fn:
            log_fn(f"py7zr: {os.path.basename(archive_path)}")
        with py7zr.SevenZipFile(archive_path, mode='r',
                                password=password if password else None) as z:
            z.extractall(path=out_dir)
        if log_fn:
            log_fn("py7zr готово")
    except Exception as e:
        msg = str(e).lower()
        if 'password' in msg or 'crc' in msg:
            raise RuntimeError("Неверный пароль или повреждённый архив")
        raise


def extract_archive(archive_path: str, out_dir: str, password: str = '',
                    log_fn=None):
    ext = os.path.splitext(archive_path)[1].lower()
    os.makedirs(out_dir, exist_ok=True)
    if ext == '.zip':
        _extract_zip(archive_path, out_dir, password, log_fn)
    elif ext == '.rar':
        _extract_rar(archive_path, out_dir, password, log_fn)
    elif ext == '.7z':
        _extract_7z(archive_path, out_dir, password, log_fn)
    else:
        raise RuntimeError(f"Неподдерживаемый формат: {ext}")


def extract_archive_smart(archive_path: str, out_dir: str, passwords: dict,
                          log_fn=None):
    ensure_tools_configured()
    pwd = get_password_for(passwords, os.path.basename(archive_path))
    tried = []
    last_err = None

    if pwd:
        try:
            extract_archive(archive_path, out_dir, pwd, log_fn=log_fn)
            return
        except Exception as e:
            last_err = e
            tried.append(f"config('{pwd[:4]}…')")

    try:
        extract_archive(archive_path, out_dir, '', log_fn=log_fn)
        return
    except Exception as e:
        if last_err is None:
            last_err = e
        tried.append("no-password")

    seen = {pwd, ''}
    for key, val in passwords.items():
        if key == '*':
            continue
        sval = str(val)
        if not sval or sval in seen:
            continue
        seen.add(sval)
        try:
            extract_archive(archive_path, out_dir, sval, log_fn=log_fn)
            return
        except Exception as e:
            last_err = e
            tried.append(f"'{key}'('{sval[:4]}…')")

    if last_err is not None:
        raise RuntimeError(
            f"{last_err}\n"
            f"Проверено паролей: {len(tried)} ({', '.join(tried)})."
        )
    raise RuntimeError("Не удалось распаковать архив: неизвестная ошибка")


# ---------- сплющивание, поиск .exe, рекурсия ----------

def flatten_single_root(folder: str):
    try:
        entries = os.listdir(folder)
    except OSError:
        return
    entries = [e for e in entries if not e.startswith('__MACOSX')]
    if len(entries) != 1:
        return
    single = os.path.join(folder, entries[0])
    if not os.path.isdir(single):
        return
    try:
        for item in os.listdir(single):
            src = os.path.join(single, item)
            dst = os.path.join(folder, item)
            if os.path.exists(dst):
                continue
            shutil.move(src, dst)
        try:
            os.rmdir(single)
        except OSError:
            pass
    except Exception as e:
        print(f"[archive_extractor] flatten_single_root: {e}")


def _check_nwjs_markers(folder: str) -> bool:
    if not folder or not os.path.isdir(folder):
        return False

    try:
        entries = os.listdir(folder)
    except OSError:
        return False

    names = {n.lower() for n in entries}

    if 'package.json' in names:
        return True
    if 'package.nw' in names:
        return True
    if 'nw.dll' in names:
        return True
    if 'node.dll' in names:
        return True

    markers = 0
    if 'www' in names and os.path.isdir(os.path.join(folder, 'www')):
        markers += 1
    if 'locales' in names and os.path.isdir(os.path.join(folder, 'locales')):
        markers += 1
    if 'icudtl.dat' in names:
        markers += 1
    if 'resources.pak' in names:
        markers += 1
    if 'nw_100_percent.pak' in names:
        markers += 1
    if 'nw_200_percent.pak' in names:
        markers += 1
    if any(n.startswith('nw_elf') for n in names):
        markers += 1
    if 'nwjs.app' in names:
        markers += 1

    return markers >= 2


def _is_nwjs_folder(folder: str, check_parents: int = 2) -> bool:
    if not folder or not os.path.isdir(folder):
        return False

    current = os.path.abspath(folder)
    for _ in range(check_parents + 1):
        if _check_nwjs_markers(current):
            return True
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    return False


def find_game_exe(folder: str, blacklist_fn, max_depth: int = 4):
    candidates = []
    root_depth = folder.rstrip(os.sep).count(os.sep)

    for root, dirs, files in os.walk(folder):
        depth = root.count(os.sep) - root_depth
        if depth >= max_depth:
            dirs[:] = []
            continue

        is_nwjs = _is_nwjs_folder(root)

        for f in files:
            low = f.lower()
            if not low.endswith('.exe'):
                continue

            try:
                ok = blacklist_fn(f)
            except TypeError:
                try:
                    ok = blacklist_fn(f, root)
                except Exception:
                    ok = True

            if not ok:
                continue

            fp = os.path.join(root, f)
            try:
                size = os.path.getsize(fp)
            except OSError:
                size = 0

            name_priority = 0
            if is_nwjs:
                folder_name = os.path.basename(root).lower()
                stem = os.path.splitext(low)[0]

                if stem == folder_name:
                    name_priority = -4
                elif low in ('nw.exe', 'nwjs.exe', 'nwjs-sdk.exe'):
                    name_priority = -3
                elif low in ('game.exe', 'rpgmv.exe',
                             'rpgmv-player.exe', 'nwjs-player.exe'):
                    name_priority = -2
                elif 'nw' in low:
                    name_priority = -1
                elif low in ('nwjc.exe', 'notification_helper.exe',
                             'payload.exe', 'credits.exe',
                             'elevate.exe', 'squirrel.exe',
                             'update.exe'):
                    name_priority = 5

            candidates.append((depth, name_priority, -size, fp))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][3]


def list_nested_archives(folder: str,
                         max_depth: int = NESTED_ARCHIVE_MAX_DEPTH):
    result = []
    if not os.path.isdir(folder):
        return result

    root_depth = folder.rstrip(os.sep).count(os.sep)
    try:
        for root, dirs, files in os.walk(folder):
            depth = root.count(os.sep) - root_depth
            if depth >= max_depth:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs
                       if not d.startswith('__') and not d.startswith('.')]
            for f in files:
                full = os.path.join(root, f)
                if is_archive(full):
                    result.append((depth, full))
    except OSError:
        pass

    result.sort(key=lambda x: (x[0], x[1]))
    return [p for _d, p in result]


def list_top_level_archives(folder: str):
    result = []
    try:
        for name in os.listdir(folder):
            full = os.path.join(folder, name)
            if os.path.isfile(full) and is_archive(full):
                result.append(full)
    except OSError:
        pass
    return result


def process_archive_for_game(archive_path: str, out_dir: str,
                             passwords: dict, blacklist_fn,
                             max_depth: int = 4,
                             recurse_depth: int = 0,
                             max_recurse: int = 3,
                             log=None):
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    name = os.path.basename(archive_path)
    _log(f"распаковка: {name}")

    t0 = time.time()
    try:
        extract_archive_smart(archive_path, out_dir, passwords, log_fn=_log)
    except Exception as e:
        _log(f"ошибка распаковки {name}: {e}")
        raise
    elapsed = time.time() - t0
    _log(f"{name}: распаковано за {elapsed:.1f}с")

    flatten_single_root(out_dir)
    mark_as_extracted(archive_path)

    _log(f"поиск игры в {name}")
    exe = find_game_exe(out_dir, blacklist_fn, max_depth=max_depth)
    if exe:
        _log(f"найдено: {os.path.basename(exe)}")
        return exe

    if recurse_depth >= max_recurse:
        _log(f"{name}: игры нет, лимит вложенности достигнут")
        return None

    nested_archives = list_nested_archives(out_dir)
    if not nested_archives:
        _log(f"{name}: игры и вложенных архивов нет")
        return None

    _log(f"{name}: вложенных архивов: {len(nested_archives)}")

    for nested_archive in nested_archives:
        nested_out = os.path.splitext(nested_archive)[0]
        try:
            exe = process_archive_for_game(
                nested_archive, nested_out, passwords, blacklist_fn,
                max_depth=max_depth,
                recurse_depth=recurse_depth + 1,
                max_recurse=max_recurse,
                log=log,
            )
            if exe:
                return exe
        except Exception as e:
            _log(f"{os.path.basename(nested_archive)}: ошибка — {e}")
            continue

    return None