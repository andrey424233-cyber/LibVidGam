"""Мобильный доступ: HTTP + WebSocket сервер для связи с Android-приложением.

Запускается из LibVidGam, слушает локальную сеть. Все запросы защищены
одноразовым токеном — 32-символьная hex-строка, генерируется при старте.

Эндпоинты:
    GET  /                     — HTML-страница (для отладки в браузере)
    GET  /api/videos[?tag=&title=] — список видео (с опциональной фильтрацией)
    GET  /api/tags             — список тегов
    GET  /api/comics           — список комиксов (JSON)
    GET  /cover/video/<id>     — обложка видео (PNG)
    GET  /cover/comic/<id>     — обложка комикса (PNG)
    GET  /stream/<id>          — видео с поддержкой HTTP Range
    GET  /stream/comic-page/.. — страница комикса (JPEG)
    WS   /ws/remote            — канал команд с ПК на телефон
"""
import io
import json
import mimetypes
import os
import secrets
import socket
import threading
import time

try:
    from flask import (Flask, request, jsonify, send_file, Response,
                       make_response, abort, render_template_string)
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    Flask = None

try:
    from flask_sock import Sock
    HAS_FLASK_SOCK = True
except ImportError:
    HAS_FLASK_SOCK = False
    Sock = None


# ============================================================
# Утилиты
# ============================================================

def get_local_ip() -> str:
    """Определяет локальный IPv4-адрес для QR-кода.

    Проблема: если на ПК есть Docker, WSL, VirtualBox, Radmin VPN и т.п.,
    они создают виртуальные адаптеры, и стандартный метод через connect
    к 8.8.8.8 может вернуть IP виртуального адаптера (например, 172.17.0.1),
    который недостижим с телефона.

    Решение: собрать всех кандидатов и выбрать похожего на реальный LAN.
    """
    candidates = []

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        try:
            s.connect(('8.8.8.8', 80))
            candidates.append(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith('127.'):
                candidates.append(ip)
    except Exception:
        pass

    try:
        _, _, ips = socket.gethostbyname_ex(socket.gethostname())
        for ip in ips:
            if ip and not ip.startswith('127.'):
                candidates.append(ip)
    except Exception:
        pass

    seen = set()
    unique = []
    for ip in candidates:
        if ip not in seen:
            seen.add(ip)
            unique.append(ip)

    def priority(ip: str) -> int:
        if ip.startswith('192.168.'):
            return 0
        if ip.startswith('10.'):
            return 1
        if ip.startswith('172.'):
            try:
                second = int(ip.split('.')[1])
                if 16 <= second <= 31:
                    return 2
            except Exception:
                pass
            return 90
        if ip.startswith('169.254.'):
            return 95
        if ip.startswith('127.'):
            return 100
        if ip.startswith('26.'):
            return 80
        return 50

    unique.sort(key=priority)

    for ip in unique:
        if priority(ip) < 50:
            print(f"[mobile] Selected local IP: {ip} (from {unique})")
            return ip

    if unique:
        print(f"[mobile] Fallback local IP: {unique[0]} (from {unique})")
        return unique[0]

    return '127.0.0.1'


def find_free_port(start: int = 8000, tries: int = 20) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    return start


# ============================================================
# HTML для отладки через браузер
# ============================================================

MOBILE_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LibVidGam</title>
</head>
<body style="background:#121212;color:#e0e0e0;font-family:sans-serif;padding:20px">
<h1>LibVidGam</h1>
<p>Мобильный клиент — Android-приложение. Эта страница для отладки.</p>
<p><b>API:</b></p>
<ul>
  <li>GET /api/videos</li>
  <li>GET /api/videos?tag=&lt;имя&gt;&amp;title=&lt;подстрока&gt;</li>
  <li>GET /api/tags</li>
  <li>GET /api/comics</li>
  <li>GET /cover/video/&lt;id&gt;</li>
  <li>GET /stream/&lt;id&gt;</li>
  <li>WS  /ws/remote</li>
</ul>
</body>
</html>
"""


# ============================================================
# Сервер
# ============================================================

class MobileServer:
    """HTTP + WebSocket сервер для связи с Android."""

    def __init__(self, db, host: str = '0.0.0.0', port: int = 0):
        if not HAS_FLASK:
            raise RuntimeError(
                "Flask не установлен. Выполните: pip install flask"
            )

        self.db = db
        self.host = host
        self.port = port or find_free_port(8000)
        self.token = secrets.token_hex(16)
        self.local_ip = get_local_ip()

        self._app = None
        self._server_thread = None
        self._running = False
        self._werkzeug_server = None

        self._ws_clients = []
        self._ws_lock = threading.Lock()

        self._build_app()

    # ---------- публичный API ----------

    def start(self):
        if self._running:
            return
        self._running = True
        self._server_thread = threading.Thread(
            target=self._run, daemon=True, name='MobileServer'
        )
        self._server_thread.start()
        time.sleep(0.3)

    def stop(self):
        if not self._running:
            return
        self._running = False

        with self._ws_lock:
            for ws in list(self._ws_clients):
                try:
                    ws.close()
                except Exception:
                    pass
            self._ws_clients.clear()

        try:
            if self._werkzeug_server is not None:
                self._werkzeug_server.shutdown()
        except Exception:
            pass

    def is_running(self) -> bool:
        return self._running

    def get_url(self) -> str:
        return f"http://{self.local_ip}:{self.port}/?t={self.token}"

    def get_short_url(self) -> str:
        return f"http://{self.local_ip}:{self.port}/"

    def send_command(self, payload: dict):
        text = json.dumps(payload, ensure_ascii=False)
        with self._ws_lock:
            clients = list(self._ws_clients)
        for ws in clients:
            try:
                ws.send(text)
            except Exception as e:
                print(f"[mobile] WS send failed: {e}")
                with self._ws_lock:
                    try:
                        self._ws_clients.remove(ws)
                    except ValueError:
                        pass

    def client_count(self) -> int:
        with self._ws_lock:
            return len(self._ws_clients)

    # ---------- внутреннее ----------

    def _run(self):
        try:
            from werkzeug.serving import make_server
            self._werkzeug_server = make_server(
                self.host, self.port, self._app,
                threaded=True,
            )
            self._werkzeug_server.serve_forever()
        except Exception as e:
            print(f"[mobile] server error: {e}")
            self._running = False

    def _build_app(self):
        app = Flask(__name__)
        app.config['JSON_AS_ASCII'] = False

        sock = None
        if HAS_FLASK_SOCK:
            sock = Sock(app)

        @app.before_request
        def check_token():
            path = request.path
            if path in ('/favicon.ico',):
                return None
            if path.startswith('/ws/'):
                return None

            t = request.args.get('t', '')
            if t and secrets.compare_digest(t, self.token):
                return None

            t = request.cookies.get('lvg_token', '')
            if t and secrets.compare_digest(t, self.token):
                return None

            abort(404)

        @app.after_request
        def set_token_cookie(response):
            t = request.args.get('t', '')
            if t and secrets.compare_digest(t, self.token):
                response.set_cookie(
                    'lvg_token', self.token,
                    max_age=60 * 60 * 24,
                    httponly=True,
                    samesite='Lax',
                )
            return response

        # ---------- страницы ----------

        @app.route('/')
        def index():
            return render_template_string(MOBILE_HTML, token=self.token)

        # ---------- API ----------

        @app.route('/api/videos')
        def api_videos():
            tag = request.args.get('tag', '').strip()
            title = request.args.get('title', '').strip()

            try:
                if tag or title:
                    videos = self.db.search_videos(
                        include_tags=[tag] if tag else None,
                        title_query=title if title else None,
                    )
                else:
                    videos = self.db.get_all_videos()
            except Exception as e:
                print(f"[mobile] api_videos: {e}")
                return jsonify([])

            result = []
            for v in videos:
                fp = v.get('file_path', '')
                if not fp or not os.path.isfile(fp):
                    continue
                result.append({
                    'id': v['id'],
                    'title': v.get('title', ''),
                    'duration': int(v.get('duration', 0) or 0),
                    'watch_count': int(v.get('watch_count', 0) or 0),
                })
            return jsonify(result)

        @app.route('/api/tags')
        def api_tags():
            try:
                tags = self.db.get_all_tags()
            except Exception as e:
                print(f"[mobile] api_tags: {e}")
                return jsonify([])

            names = []
            for t in tags:
                if isinstance(t, dict):
                    nm = t.get('name', '')
                    if nm:
                        names.append(nm)
            names.sort(key=lambda s: s.lower())
            return jsonify(names)

        @app.route('/api/comics')
        def api_comics():
            try:
                comics = self.db.get_all_comics()
            except Exception as e:
                print(f"[mobile] api_comics: {e}")
                return jsonify([])
            result = []
            for c in comics:
                fp = c.get('file_path', '')
                if not fp or not os.path.isfile(fp):
                    continue
                result.append({
                    'id': c['id'],
                    'title': c.get('title', ''),
                    'page_count': int(c.get('page_count', 0) or 0),
                    'view_count': int(c.get('view_count', 0) or 0),
                })
            return jsonify(result)

        # ---------- обложки ----------

        @app.route('/cover/video/<int:video_id>')
        def cover_video(video_id):
            try:
                v = self.db.get_video(video_id)
            except Exception:
                v = None
            if not v:
                abort(404)
            fp = v.get('file_path', '')
            if not fp:
                abort(404)
            return self._send_cover_for_video(fp)

        @app.route('/cover/comic/<int:comic_id>')
        def cover_comic(comic_id):
            try:
                c = self.db.get_comic(comic_id)
            except Exception:
                c = None
            if not c:
                abort(404)
            fp = c.get('file_path', '')
            if not fp:
                abort(404)
            return self._send_cover_for_comic(fp)

        # ---------- видео ----------

        @app.route('/stream/<int:video_id>')
        def stream_video(video_id):
            try:
                v = self.db.get_video(video_id)
            except Exception:
                v = None
            if not v:
                abort(404)
            fp = v.get('file_path', '')
            if not fp or not os.path.isfile(fp):
                abort(404)
            return self._send_video(fp)

        @app.route('/stream/comic-page/<int:comic_id>/<int:page_index>')
        def stream_comic_page(comic_id, page_index):
            try:
                c = self.db.get_comic(comic_id)
            except Exception:
                c = None
            if not c:
                abort(404)
            fp = c.get('file_path', '')
            if not fp or not os.path.isfile(fp):
                abort(404)
            return self._send_comic_page(fp, page_index)

        # ---------- WebSocket ----------

        if sock is not None:
            @sock.route('/ws/remote')
            def ws_remote(ws):
                t = request.args.get('t', '')
                if not t or not secrets.compare_digest(t, self.token):
                    try:
                        ws.close()
                    except Exception:
                        pass
                    return

                with self._ws_lock:
                    self._ws_clients.append(ws)
                print(f"[mobile] WS connected, total={len(self._ws_clients)}")

                try:
                    while True:
                        msg = ws.receive(timeout=60)
                        if msg is None:
                            break
                except Exception as e:
                    print(f"[mobile] WS loop: {e}")
                finally:
                    with self._ws_lock:
                        try:
                            self._ws_clients.remove(ws)
                        except ValueError:
                            pass
                    print(f"[mobile] WS disconnected, "
                          f"total={len(self._ws_clients)}")

        self._app = app

    # ---------- обложки ----------

    def _send_cover_for_video(self, file_path):
        try:
            import cover_cache
            from video_library_window import VIDEO_COVER_SIZE
            cpath = cover_cache.cover_path(file_path, VIDEO_COVER_SIZE)
            if os.path.isfile(cpath):
                return send_file(cpath, mimetype='image/png',
                                 conditional=True, max_age=86400)
        except Exception as e:
            print(f"[mobile] cover video: {e}")
        return self._placeholder_cover()

    def _send_cover_for_comic(self, file_path):
        try:
            import cover_cache
            from library_window import COVER_TARGET
            cpath = cover_cache.cover_path(file_path, COVER_TARGET)
            if os.path.isfile(cpath):
                return send_file(cpath, mimetype='image/png',
                                 conditional=True, max_age=86400)
        except Exception as e:
            print(f"[mobile] cover comic: {e}")
        return self._placeholder_cover()

    def _placeholder_cover(self):
        png_1x1 = bytes.fromhex(
            '89504e470d0a1a0a0000000d49484452000000010000000108060000001f'
            '15c4890000000d49444154789c6360606060000000050001a5f64540000000'
            '0049454e44ae426082'
        )
        return Response(png_1x1, mimetype='image/png')

    # ---------- видео ----------

    def _send_video(self, file_path):
        try:
            mime = self._guess_video_mime(file_path)
            resp = make_response(send_file(
                file_path,
                mimetype=mime,
                conditional=True,
                etag=True,
                last_modified=os.path.getmtime(file_path),
            ))
            resp.headers['Accept-Ranges'] = 'bytes'
            resp.headers['Cache-Control'] = 'private, max-age=3600'
            return resp
        except Exception as e:
            print(f"[mobile] stream: {e}")
            abort(500)

    @staticmethod
    def _guess_video_mime(path: str) -> str:
        low = path.lower()
        if low.endswith('.mkv'):
            return 'video/x-matroska'
        if low.endswith('.webm'):
            return 'video/webm'
        if low.endswith('.mp4') or low.endswith('.m4v'):
            return 'video/mp4'
        if low.endswith('.avi'):
            return 'video/x-msvideo'
        if low.endswith('.mov'):
            return 'video/quicktime'
        return mimetypes.guess_type(path)[0] or 'application/octet-stream'

    # ---------- комиксы ----------

    def _send_comic_page(self, file_path, page_index):
        try:
            from archive_reader import ArchiveReader
            img = ArchiveReader.extract_page(file_path, page_index)
            img.thumbnail((1600, 1600))
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=85)
            buf.seek(0)
            return Response(buf.read(), mimetype='image/jpeg',
                            headers={'Cache-Control': 'public, max-age=86400'})
        except Exception as e:
            print(f"[mobile] comic page: {e}")
            abort(404)