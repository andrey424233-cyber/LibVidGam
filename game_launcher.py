"""Запуск игр в отдельном процессе.

Работает на Windows и Linux.

Windows: использует CreateProcessW через ctypes — точно отслеживает
процесс игры и измеряет playtime.

Linux/macOS: использует subprocess.Popen + wait() в фоновом потоке.
Playtime измеряется так же.

Не блокирует UI, продолжает работать после закрытия приложения.
"""
import ctypes
import os
import subprocess
import sys
import threading
import time

from PyQt5.QtCore import QObject, pyqtSignal


IS_WINDOWS = sys.platform == 'win32'


# ============================================================
# Чёрный список exe
# ============================================================

EXE_BLACKLIST_PREFIXES = (
    'unins', 'vcredist', 'dxsetup', 'dxwebsetup',
    'setup', 'install', 'redist', 'dotnet',
)
EXE_BLACKLIST_EXACT = {
    'crashreportclient.exe',
    'unitycrashhandler.exe',
    'unitycrashhandler64.exe',
    'ue4prereqsetup_x64.exe',
    'ue4prereqsetup_x86.exe',
    # Служебные бинарники NW.js / Electron
    'nwjc.exe',
    'notification_helper.exe',
    'payload.exe',
    'credits.exe',
    'elevate.exe',
    'squirrel.exe',
    'update.exe',
}


# ============================================================
# Константы Windows API (только для win32)
# ============================================================

if IS_WINDOWS:
    from ctypes import wintypes

    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    INFINITE = 0xFFFFFFFF
    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x102

    STARTF_USESHOWWINDOW = 0x00000001
    SW_SHOWNORMAL = 1


# ============================================================
# NW.js — определение (кроссплатформенно)
# ============================================================

def _check_nwjs_markers(folder: str) -> bool:
    if not folder or not os.path.isdir(folder):
        return False
    try:
        entries = os.listdir(folder)
    except OSError:
        return False

    names = {n.lower() for n in entries}

    # Сильные маркеры — достаточно одного
    if 'package.json' in names:
        return True
    if 'package.nw' in names:
        return True
    if 'nw.dll' in names:
        return True
    if 'node.dll' in names:
        return True

    # Слабые маркеры — нужно 2 из них
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


def _is_nwjs_game(folder: str, check_parents: int = 2) -> bool:
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


# ============================================================
# Определение "это игра или нет"
# ============================================================

def is_probable_game_exe(file_name: str, folder: str = None) -> bool:
    """Определяет, является ли файл исполняемым файлом игры.

    Windows: считаем игрой только .exe.
    Linux: считаем игрой .exe или файл с битом "исполняемый".
    """
    low = (file_name or '').lower()

    if IS_WINDOWS:
        if not low.endswith('.exe'):
            return False
    else:
        # Linux / macOS — либо .exe (может запуститься через wine),
        # либо любой файл с битом X_OK
        if low.endswith('.exe'):
            pass
        elif folder:
            full = os.path.join(folder, file_name)
            if not os.path.isfile(full):
                return False
            if not os.access(full, os.X_OK):
                return False
        else:
            return False

    # NW.js-игра — разрешаем любой исполняемый файл, кроме мусора
    if folder and _is_nwjs_game(folder):
        if low in EXE_BLACKLIST_EXACT:
            return False
        for pref in EXE_BLACKLIST_PREFIXES:
            if low.startswith(pref):
                return False
        return True

    # Стандартная логика
    if low in EXE_BLACKLIST_EXACT:
        return False
    for pref in EXE_BLACKLIST_PREFIXES:
        if low.startswith(pref):
            return False
    return True


def find_cover_in_folder(folder: str):
    """Ищет обложку в папке игры."""
    if not folder or not os.path.isdir(folder):
        return None
    candidates = (
        'cover.jpg', 'cover.jpeg', 'cover.png',
        'poster.jpg', 'poster.jpeg', 'poster.png',
        'folder.jpg', 'folder.jpeg', 'folder.png',
        'icon.jpg', 'icon.jpeg', 'icon.png',
        'preview.jpg', 'preview.png',
    )
    try:
        names_lower = {n.lower(): n for n in os.listdir(folder)}
    except Exception:
        return None
    for c in candidates:
        if c in names_lower:
            return os.path.join(folder, names_lower[c])
    return None


# ============================================================
# Разбор аргументов командной строки
# ============================================================

def split_arguments(text: str):
    """Разбивает строку аргументов с учётом кавычек."""
    if not text:
        return []
    result = []
    current = ''
    quote = None
    for ch in text:
        if quote is None and ch in ('"', "'"):
            quote = ch
        elif quote is not None and ch == quote:
            quote = None
        elif ch == ' ' and quote is None:
            if current:
                result.append(current)
                current = ''
        else:
            current += ch
    if current:
        result.append(current)
    return result


# ============================================================
# Проверка "жив ли процесс"
# ============================================================

def is_process_alive(pid: int) -> bool:
    """Проверяет, существует ли процесс с указанным PID."""
    if not pid or pid <= 0:
        return False

    if not IS_WINDOWS:
        # POSIX: сигнал 0 не посылает, но проверяет существование
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
        except Exception:
            return True

    # Windows
    try:
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [
            wintypes.HANDLE, wintypes.DWORD
        ]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not handle:
            return False
        try:
            result = kernel32.WaitForSingleObject(handle, 0)
            return result == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return True


# ============================================================
# Windows: CreateProcessW через ctypes
# ============================================================

if IS_WINDOWS:
    from ctypes import wintypes

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    def _make_cmdline(exe_path: str, args_list) -> str:
        """Собирает командную строку с правильным экранированием."""
        parts = ['"' + exe_path + '"']
        for a in args_list:
            if a == '' or ' ' in a or '\t' in a:
                parts.append('"' + a.replace('"', '\\"') + '"')
            else:
                parts.append(a)
        return ' '.join(parts)

    def _launch_windows(exe_path: str, args_list, cwd: str):
        """Запускает .exe на Windows через CreateProcessW.
        Возвращает (handle, pid)."""
        cmdline = _make_cmdline(exe_path, args_list)

        si = _STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.dwFlags = STARTF_USESHOWWINDOW
        si.wShowWindow = SW_SHOWNORMAL
        si.lpDesktop = "winsta0\\default"

        pi = _PROCESS_INFORMATION()

        cmd_buf = ctypes.create_unicode_buffer(cmdline)
        cwd_buf = ctypes.create_unicode_buffer(cwd) if cwd else None

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateProcessW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR,
            ctypes.c_void_p, ctypes.c_void_p,
            wintypes.BOOL, wintypes.DWORD,
            ctypes.c_void_p, wintypes.LPCWSTR,
            ctypes.POINTER(_STARTUPINFOW),
            ctypes.POINTER(_PROCESS_INFORMATION),
        ]
        kernel32.CreateProcessW.restype = wintypes.BOOL

        ok = kernel32.CreateProcessW(
            exe_path, cmd_buf, None, None, False,
            CREATE_NEW_PROCESS_GROUP | CREATE_UNICODE_ENVIRONMENT,
            None, cwd_buf, ctypes.byref(si), ctypes.byref(pi),
        )
        if not ok:
            err = ctypes.get_last_error()
            raise OSError(err, ctypes.FormatError(err))

        kernel32.CloseHandle(pi.hThread)
        return pi.hProcess, int(pi.dwProcessId)

    def _wait_windows(handle):
        """Ждёт завершения процесса по handle."""
        if not handle:
            return
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [
            wintypes.HANDLE, wintypes.DWORD
        ]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        try:
            kernel32.WaitForSingleObject(handle, INFINITE)
        except Exception as e:
            print(f"[game_launcher] WaitForSingleObject: {e}")
        finally:
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass


# ============================================================
# Основной класс
# ============================================================

class GameLauncher(QObject):
    """Управляет запуском игр и измеряет playtime."""

    started = pyqtSignal(int, int)     # game_id, pid
    finished = pyqtSignal(int, int)    # game_id, seconds
    failed = pyqtSignal(int, str)      # game_id, error message

    def launch(self, game_id: int, exe_path: str,
               working_dir: str = None, arguments: str = None):
        t = threading.Thread(
            target=self._run,
            args=(game_id, exe_path, working_dir, arguments),
            daemon=True,
        )
        t.start()

    def _run(self, game_id, exe_path, working_dir, arguments):
        args = split_arguments(arguments)
        cwd = working_dir or os.path.dirname(exe_path)
        if cwd and not os.path.isdir(cwd):
            cwd = os.path.dirname(exe_path)

        start = time.time()

        # ============================
        # Linux / macOS
        # ============================
        if not IS_WINDOWS:
            try:
                proc = subprocess.Popen(
                    [exe_path] + args,
                    cwd=cwd or None,
                    shell=False,
                )
                self.started.emit(game_id, int(proc.pid))
                try:
                    proc.wait()
                except Exception:
                    return
                self.finished.emit(game_id, int(time.time() - start))
                return
            except FileNotFoundError:
                self.failed.emit(
                    game_id,
                    f"Файл не найден:\n{exe_path}"
                )
                return
            except PermissionError:
                self.failed.emit(
                    game_id,
                    f"Нет прав на запуск:\n{exe_path}\n\n"
                    "На Linux файл должен быть исполняемым:\n"
                    f'chmod +x "{exe_path}"'
                )
                return
            except Exception as e:
                self.failed.emit(
                    game_id,
                    f"Не удалось запустить:\n{e}"
                )
                return

        # ============================
        # Windows
        # ============================
        try:
            handle, pid = _launch_windows(exe_path, args, cwd)
            self.started.emit(game_id, pid)
            _wait_windows(handle)
            self.finished.emit(game_id, int(time.time() - start))
            return
        except OSError as e:
            err_text = str(e)
        except Exception as e:
            err_text = str(e)

        # Fallback через subprocess.Popen
        try:
            creationflags = CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(
                [exe_path] + args,
                cwd=cwd or None,
                shell=False,
                creationflags=creationflags,
            )
            self.started.emit(game_id, int(proc.pid))
            try:
                proc.wait()
            except Exception:
                return
            self.finished.emit(game_id, int(time.time() - start))
            return
        except Exception as e:
            self.failed.emit(
                game_id,
                "Не удалось запустить игру.\n\n"
                f"CreateProcessW: {err_text}\n"
                f"subprocess.Popen: {e}"
            )