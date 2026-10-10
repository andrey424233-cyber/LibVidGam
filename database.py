import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Dict, List, Optional


class Database:
    """База данных комиксов, видео и игр."""

    NO_TAGS_NAME = "без тегов"

    def __init__(self, db_path: str = "comics.db"):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute('PRAGMA foreign_keys = ON')
        self._conn.execute('PRAGMA journal_mode = WAL')
        self._conn.execute('PRAGMA synchronous = NORMAL')
        self.init_db()

    @contextmanager
    def _connect(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def reopen(self):
        """Переоткрывает соединение с БД. Используется после импорта."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute('PRAGMA foreign_keys = ON')
            self._conn.execute('PRAGMA journal_mode = WAL')
            self._conn.execute('PRAGMA synchronous = NORMAL')
        self.init_db()

    # ---------- фильтр по папке ----------

    @staticmethod
    def _folder_prefix(folder: str) -> Optional[str]:
        if not folder:
            return None
        try:
            f = os.path.normpath(folder)
        except Exception:
            return None
        if not f.endswith(os.sep):
            f += os.sep
        return f.lower()

    @classmethod
    def _in_folder(cls, file_path: str, folder: str) -> bool:
        if not file_path or not folder:
            return False
        try:
            fp = os.path.normpath(file_path).lower()
        except Exception:
            return False
        prefix = cls._folder_prefix(folder)
        if prefix is None:
            return False
        return fp.startswith(prefix)

    # ---------- инициализация ----------

    def init_db(self):
        with self._connect() as conn:
            cur = conn.cursor()

            cur.execute("SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name='comics'")
            if cur.fetchone() is not None:
                cur.execute("PRAGMA table_info(comics)")
                cols = [c[1] for c in cur.fetchall()]
                for name, ddl in (
                    ('series_id', 'INTEGER'), ('series_order', 'INTEGER'),
                    ('author_id', 'INTEGER'), ('description', 'TEXT'),
                    ('last_page_read', 'INTEGER DEFAULT 0'),
                    ('reading_mode', 'INTEGER DEFAULT 0'),
                    ('view_count', 'INTEGER DEFAULT 0'),
                ):
                    if name not in cols:
                        cur.execute(f'ALTER TABLE comics ADD COLUMN {name} {ddl}')

                cur.execute("PRAGMA table_info(tags)")
                tcols = [c[1] for c in cur.fetchall()]
                if 'cover_path' not in tcols:
                    cur.execute('ALTER TABLE tags ADD COLUMN cover_path TEXT')

            cur.execute("SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name='authors'")
            if cur.fetchone() is not None:
                cur.execute("PRAGMA table_info(authors)")
                acols = [c[1] for c in cur.fetchall()]
                if 'cover_path' not in acols:
                    cur.execute('ALTER TABLE authors ADD COLUMN cover_path TEXT')

            cur.execute("SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name='games'")
            if cur.fetchone() is not None:
                cur.execute("PRAGMA table_info(games)")
                gcols = [c[1] for c in cur.fetchall()]
                if 'archive_path' not in gcols:
                    cur.execute('ALTER TABLE games ADD COLUMN archive_path TEXT')
                if 'series_id' not in gcols:
                    cur.execute('ALTER TABLE games ADD COLUMN series_id INTEGER')
                if 'series_order' not in gcols:
                    cur.execute('ALTER TABLE games ADD COLUMN series_order INTEGER')
                if 'author_id' not in gcols:
                    cur.execute('ALTER TABLE games ADD COLUMN author_id INTEGER')

            cur.execute('''
                CREATE TABLE IF NOT EXISTS series (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    cover_path TEXT,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS authors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    cover_path TEXT
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS comics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    file_path TEXT UNIQUE NOT NULL,
                    page_count INTEGER,
                    series_id INTEGER,
                    series_order INTEGER,
                    author_id INTEGER,
                    description TEXT,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_read TIMESTAMP,
                    last_page_read INTEGER DEFAULT 0,
                    reading_mode INTEGER DEFAULT 0,
                    view_count INTEGER DEFAULT 0,
                    FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE SET NULL,
                    FOREIGN KEY (author_id) REFERENCES authors (id) ON DELETE SET NULL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    cover_path TEXT
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS comic_tags (
                    comic_id INTEGER,
                    tag_id INTEGER,
                    FOREIGN KEY (comic_id) REFERENCES comics (id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE,
                    PRIMARY KEY (comic_id, tag_id)
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    file_path TEXT UNIQUE NOT NULL,
                    duration INTEGER DEFAULT 0,
                    series_id INTEGER,
                    series_order INTEGER,
                    author_id INTEGER,
                    description TEXT,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_watched TIMESTAMP,
                    last_position INTEGER DEFAULT 0,
                    watch_count INTEGER DEFAULT 0,
                    FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE SET NULL,
                    FOREIGN KEY (author_id) REFERENCES authors (id) ON DELETE SET NULL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS video_tags (
                    video_id INTEGER,
                    tag_id INTEGER,
                    FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE,
                    PRIMARY KEY (video_id, tag_id)
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    exe_path TEXT UNIQUE NOT NULL,
                    working_dir TEXT,
                    arguments TEXT,
                    cover_path TEXT,
                    archive_path TEXT,
                    description TEXT,
                    series_id INTEGER,
                    series_order INTEGER,
                    author_id INTEGER,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_launched TIMESTAMP,
                    launch_count INTEGER DEFAULT 0,
                    total_playtime INTEGER DEFAULT 0,
                    FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE SET NULL,
                    FOREIGN KEY (author_id) REFERENCES authors (id) ON DELETE SET NULL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS game_tags (
                    game_id INTEGER,
                    tag_id INTEGER,
                    FOREIGN KEY (game_id) REFERENCES games (id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE,
                    PRIMARY KEY (game_id, tag_id)
                )
            ''')

            for ddl in (
                'CREATE INDEX IF NOT EXISTS idx_comics_file_path ON comics(file_path)',
                'CREATE INDEX IF NOT EXISTS idx_comics_series ON comics(series_id)',
                'CREATE INDEX IF NOT EXISTS idx_comics_author ON comics(author_id)',
                'CREATE INDEX IF NOT EXISTS idx_comics_view_count ON comics(view_count)',
                'CREATE INDEX IF NOT EXISTS idx_comic_tags_comic ON comic_tags(comic_id)',
                'CREATE INDEX IF NOT EXISTS idx_comic_tags_tag ON comic_tags(tag_id)',
                'CREATE INDEX IF NOT EXISTS idx_videos_file_path ON videos(file_path)',
                'CREATE INDEX IF NOT EXISTS idx_videos_series ON videos(series_id)',
                'CREATE INDEX IF NOT EXISTS idx_videos_author ON videos(author_id)',
                'CREATE INDEX IF NOT EXISTS idx_videos_watch_count ON videos(watch_count)',
                'CREATE INDEX IF NOT EXISTS idx_video_tags_video ON video_tags(video_id)',
                'CREATE INDEX IF NOT EXISTS idx_video_tags_tag ON video_tags(tag_id)',
                'CREATE INDEX IF NOT EXISTS idx_games_exe_path ON games(exe_path)',
                'CREATE INDEX IF NOT EXISTS idx_games_series ON games(series_id)',
                'CREATE INDEX IF NOT EXISTS idx_games_launch_count ON games(launch_count)',
                'CREATE INDEX IF NOT EXISTS idx_game_tags_game ON game_tags(game_id)',
                'CREATE INDEX IF NOT EXISTS idx_game_tags_tag ON game_tags(tag_id)',
            ):
                cur.execute(ddl)

            self._migrate_no_tags(cur)

    def _migrate_no_tags(self, cur):
        cur.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)',
                    (self.NO_TAGS_NAME,))
        cur.execute('SELECT id FROM tags WHERE name = ?', (self.NO_TAGS_NAME,))
        no_tags_id = cur.fetchone()[0]

        cur.execute('''
            SELECT c.id FROM comics c
            LEFT JOIN comic_tags ct ON c.id = ct.comic_id
            WHERE ct.comic_id IS NULL
        ''')
        for (comic_id,) in cur.fetchall():
            cur.execute('INSERT OR IGNORE INTO comic_tags '
                        '(comic_id, tag_id) VALUES (?, ?)',
                        (comic_id, no_tags_id))

    # ---------- helpers ----------

    @staticmethod
    def _rows_to_dicts(cur) -> List[Dict]:
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    @staticmethod
    def _row_to_dict(cur) -> Optional[Dict]:
        row = cur.fetchone()
        if not row:
            return None
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))

    @staticmethod
    def _split_tags(raw) -> List[str]:
        if not raw:
            return []
        return [t for t in str(raw).split('|') if t]

    # ============================================================
    # СЕРИИ И АВТОРЫ
    # ============================================================

    def add_series(self, name: str, description: str = "") -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('INSERT OR IGNORE INTO series (name, description) '
                        'VALUES (?, ?)', (name, description))
            cur.execute('SELECT id FROM series WHERE name = ?', (name,))
            return cur.fetchone()[0]

    def get_all_series(self) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT s.*, COUNT(c.id) as comic_count
                FROM series s LEFT JOIN comics c ON s.id = c.series_id
                GROUP BY s.id ORDER BY s.name
            ''')
            return self._rows_to_dicts(cur)

    def get_series_comics(self, series_id: int) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('SELECT * FROM comics WHERE series_id = ? '
                        'ORDER BY series_order ASC', (series_id,))
            return self._rows_to_dicts(cur)

    def get_series_by_id(self, series_id: int) -> Optional[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('SELECT * FROM series WHERE id = ?', (series_id,))
            return self._row_to_dict(cur)

    def add_author(self, name: str) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('INSERT OR IGNORE INTO authors (name) VALUES (?)',
                        (name,))
            cur.execute('SELECT id FROM authors WHERE name = ?', (name,))
            return cur.fetchone()[0]

    def get_all_authors(self) -> List[str]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('SELECT name FROM authors ORDER BY name')
            return [r[0] for r in cur.fetchall()]

    def get_author_id(self, name: str) -> Optional[int]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('SELECT id FROM authors WHERE name = ?', (name,))
            r = cur.fetchone()
            return r[0] if r else None

    def get_author(self, author_id: int) -> Optional[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('SELECT * FROM authors WHERE id = ?', (author_id,))
            return self._row_to_dict(cur)

    def get_all_authors_with_covers(self) -> List[Dict]:
        """Список авторов с обложками и счётчиком работ по трём библиотекам."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT a.*,
                       (SELECT COUNT(*) FROM comics
                        WHERE author_id = a.id) as comic_count,
                       (SELECT COUNT(*) FROM videos
                        WHERE author_id = a.id) as video_count,
                       (SELECT COUNT(*) FROM games
                        WHERE author_id = a.id) as game_count
                FROM authors a
                ORDER BY a.name
            ''')
            return self._rows_to_dicts(cur)

    def update_author_cover(self, author_id: int, cover_path):
        with self._connect() as conn:
            conn.execute('UPDATE authors SET cover_path = ? WHERE id = ?',
                         (cover_path, author_id))

    def clear_author_cover(self, author_id: int):
        with self._connect() as conn:
            conn.execute('UPDATE authors SET cover_path = NULL WHERE id = ?',
                         (author_id,))

    def rename_author(self, author_id: int, new_name: str) -> bool:
        new_name = (new_name or '').strip()
        if not new_name:
            return False
        with self._connect() as conn:
            try:
                conn.execute('UPDATE authors SET name = ? WHERE id = ?',
                             (new_name, author_id))
                return True
            except sqlite3.IntegrityError:
                return False

    def delete_author(self, author_id: int):
        with self._connect() as conn:
            conn.execute('DELETE FROM authors WHERE id = ?', (author_id,))

    # ============================================================
    # ТЕГИ (общие)
    # ============================================================

    def add_tag(self, tag_name: str) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)',
                        (tag_name,))
            cur.execute('SELECT id FROM tags WHERE name = ?', (tag_name,))
            return cur.fetchone()[0]

    def get_all_tags(self) -> List[Dict]:
        """Список тегов со счётчиками работ по трём библиотекам."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT t.id, t.name, t.cover_path,
                       (SELECT COUNT(*) FROM comic_tags
                        WHERE tag_id = t.id) AS comic_count,
                       (SELECT COUNT(*) FROM video_tags
                        WHERE tag_id = t.id) AS video_count,
                       (SELECT COUNT(*) FROM game_tags
                        WHERE tag_id = t.id) AS game_count
                FROM tags t
                WHERE t.name != ?
                ORDER BY t.name
            ''', (self.NO_TAGS_NAME,))
            return self._rows_to_dicts(cur)

    def get_tag_id(self, tag_name: str) -> Optional[int]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('SELECT id FROM tags WHERE name = ?', (tag_name,))
            r = cur.fetchone()
            return r[0] if r else None

    def update_tag_cover(self, tag_id: int, cover_path):
        with self._connect() as conn:
            conn.execute('UPDATE tags SET cover_path = ? WHERE id = ?',
                         (cover_path, tag_id))

    def clear_tag_cover(self, tag_id: int):
        with self._connect() as conn:
            conn.execute('UPDATE tags SET cover_path = NULL WHERE id = ?',
                         (tag_id,))

    def delete_tag(self, tag_name: str):
        if tag_name == self.NO_TAGS_NAME:
            return
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                DELETE FROM comic_tags
                WHERE tag_id = (SELECT id FROM tags WHERE name = ?)
            ''', (tag_name,))
            cur.execute('''
                DELETE FROM video_tags
                WHERE tag_id = (SELECT id FROM tags WHERE name = ?)
            ''', (tag_name,))
            cur.execute('''
                DELETE FROM game_tags
                WHERE tag_id = (SELECT id FROM tags WHERE name = ?)
            ''', (tag_name,))
            cur.execute('DELETE FROM tags WHERE name = ?', (tag_name,))

    # ============================================================
    # КОМИКСЫ
    # ============================================================

    def cleanup_missing_comics(self) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('SELECT id, file_path FROM comics')
            removed = 0
            for cid, fp in cur.fetchall():
                if not os.path.exists(fp):
                    cur.execute('DELETE FROM comics WHERE id = ?', (cid,))
                    removed += 1
            return removed

    def _update_no_tags_for_comic(self, comic_id: int):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT COUNT(*) FROM comic_tags ct
                JOIN tags t ON ct.tag_id = t.id
                WHERE ct.comic_id = ? AND t.name != ?
            ''', (comic_id, self.NO_TAGS_NAME))
            real_count = cur.fetchone()[0]
            cur.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)',
                        (self.NO_TAGS_NAME,))
            cur.execute('SELECT id FROM tags WHERE name = ?',
                        (self.NO_TAGS_NAME,))
            no_id = cur.fetchone()[0]
            if real_count == 0:
                cur.execute('INSERT OR IGNORE INTO comic_tags '
                            '(comic_id, tag_id) VALUES (?, ?)',
                            (comic_id, no_id))
            else:
                cur.execute('DELETE FROM comic_tags '
                            'WHERE comic_id = ? AND tag_id = ?',
                            (comic_id, no_id))

    def assign_tag_to_comic(self, comic_id: int, tag_id: int):
        with self._connect() as conn:
            conn.execute('INSERT OR IGNORE INTO comic_tags '
                         '(comic_id, tag_id) VALUES (?, ?)',
                         (comic_id, tag_id))
        self._update_no_tags_for_comic(comic_id)

    def remove_tag_from_comic(self, comic_id: int, tag_id: int):
        with self._connect() as conn:
            conn.execute('DELETE FROM comic_tags '
                         'WHERE comic_id = ? AND tag_id = ?',
                         (comic_id, tag_id))
        self._update_no_tags_for_comic(comic_id)

    def set_comic_tags(self, comic_id: int, tag_names: List[str]):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('DELETE FROM comic_tags WHERE comic_id = ?',
                        (comic_id,))
            for name in tag_names:
                cur.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)',
                            (name,))
                cur.execute('SELECT id FROM tags WHERE name = ?', (name,))
                tid = cur.fetchone()[0]
                cur.execute('INSERT OR IGNORE INTO comic_tags '
                            '(comic_id, tag_id) VALUES (?, ?)',
                            (comic_id, tid))
        self._update_no_tags_for_comic(comic_id)

    def increment_view_count(self, comic_id: int):
        with self._connect() as conn:
            conn.execute('UPDATE comics SET view_count = view_count + 1 '
                         'WHERE id = ?', (comic_id,))

    def get_view_count(self, comic_id: int) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('SELECT view_count FROM comics WHERE id = ?',
                        (comic_id,))
            r = cur.fetchone()
            return r[0] if r else 0

    def add_comic(self, title, file_path, page_count,
                  series_id=None, series_order=None, author_id=None,
                  description=""):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT OR IGNORE INTO comics
                (title, file_path, page_count, series_id, series_order,
                 author_id, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (title, file_path, page_count, series_id, series_order,
                  author_id, description))
            cur.execute('SELECT id FROM comics WHERE file_path = ?',
                        (file_path,))
            row = cur.fetchone()
            cid = row[0] if row else 0
        if cid:
            self._update_no_tags_for_comic(cid)
        return cid

    def update_comic(self, comic_id: int, **kwargs):
        if not kwargs:
            return
        set_clause = ', '.join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [comic_id]
        with self._connect() as conn:
            conn.execute(f'UPDATE comics SET {set_clause} WHERE id = ?', vals)

    def _get_comic_by(self, where, value):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(f'''
                SELECT c.*, s.name as series_name, a.name as author_name
                FROM comics c
                LEFT JOIN series s ON c.series_id = s.id
                LEFT JOIN authors a ON c.author_id = a.id
                WHERE {where}
            ''', (value,))
            return self._row_to_dict(cur)

    def get_comic(self, comic_id):
        return self._get_comic_by('c.id = ?', comic_id)

    def get_comic_by_path(self, fp):
        return self._get_comic_by('c.file_path = ?', fp)

    def get_all_comics(self) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT c.*, s.name as series_name, a.name as author_name
                FROM comics c
                LEFT JOIN series s ON c.series_id = s.id
                LEFT JOIN authors a ON c.author_id = a.id
                ORDER BY c.title
            ''')
            return self._rows_to_dicts(cur)

    def get_comics_in_folder(self, folder: str) -> List[Dict]:
        comics = self.get_all_comics()
        if not folder:
            return comics
        return [c for c in comics
                if self._in_folder(c.get('file_path'), folder)]

    def get_top_comics_by_views(self, limit: int = 24) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT c.*, s.name as series_name, a.name as author_name
                FROM comics c
                LEFT JOIN series s ON c.series_id = s.id
                LEFT JOIN authors a ON c.author_id = a.id
                ORDER BY c.view_count DESC, c.title ASC
                LIMIT ?
            ''', (limit,))
            return self._rows_to_dicts(cur)

    def get_top_comics_by_views_with_tags(self, limit: int = 24) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT c.*, s.name as series_name, a.name as author_name,
                       GROUP_CONCAT(t.name, '|') as tags_concat
                FROM comics c
                LEFT JOIN series s ON c.series_id = s.id
                LEFT JOIN authors a ON c.author_id = a.id
                LEFT JOIN comic_tags ct ON c.id = ct.comic_id
                LEFT JOIN tags t ON ct.tag_id = t.id AND t.name != ?
                GROUP BY c.id
                ORDER BY c.view_count DESC, c.title ASC
                LIMIT ?
            ''', (self.NO_TAGS_NAME, limit))
            rows = self._rows_to_dicts(cur)
        for r in rows:
            r['tags'] = self._split_tags(r.pop('tags_concat', None))
        return rows

    def get_comic_tags(self, comic_id: int) -> List[str]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT t.name FROM tags t
                JOIN comic_tags ct ON t.id = ct.tag_id
                WHERE ct.comic_id = ? AND t.name != ?
            ''', (comic_id, self.NO_TAGS_NAME))
            return [r[0] for r in cur.fetchall()]

    def get_all_tags_for_display(self, comic_id: int) -> List[str]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT t.name FROM tags t
                JOIN comic_tags ct ON t.id = ct.tag_id
                WHERE ct.comic_id = ? ORDER BY t.name
            ''', (comic_id,))
            return [r[0] for r in cur.fetchall()]

    def save_reading_progress(self, comic_id: int, page: int):
        with self._connect() as conn:
            conn.execute('''
                UPDATE comics SET last_page_read = ?,
                                  last_read = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (page, comic_id))

    def save_reading_mode(self, comic_id: int, mode: int):
        with self._connect() as conn:
            conn.execute('UPDATE comics SET reading_mode = ? WHERE id = ?',
                         (mode, comic_id))

    def get_reading_mode(self, comic_id: int) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('SELECT reading_mode FROM comics WHERE id = ?',
                        (comic_id,))
            r = cur.fetchone()
            return r[0] if r else 0

    def delete_comic(self, comic_id: int):
        with self._connect() as conn:
            conn.execute('DELETE FROM comics WHERE id = ?', (comic_id,))

    def search_comics(self, include_tags=None, exclude_tags=None,
                      title_query=None, author_query=None, series_id=None,
                      min_views=None, max_views=None,
                      folder=None) -> List[Dict]:
        query = '''
            SELECT DISTINCT c.*, s.name as series_name,
                            a.name as author_name
            FROM comics c
            LEFT JOIN series s ON c.series_id = s.id
            LEFT JOIN authors a ON c.author_id = a.id
        '''
        params, conds = [], []
        if include_tags:
            ph = ','.join('?' for _ in include_tags)
            conds.append(f'''
                c.id IN (
                    SELECT comic_id FROM comic_tags ct2
                    JOIN tags t2 ON ct2.tag_id = t2.id
                    WHERE t2.name IN ({ph})
                    GROUP BY comic_id
                    HAVING COUNT(DISTINCT t2.name) = {len(include_tags)}
                )
            ''')
            params.extend(include_tags)
        if exclude_tags:
            ph = ','.join('?' for _ in exclude_tags)
            conds.append(f'''
                c.id NOT IN (
                    SELECT comic_id FROM comic_tags ct3
                    JOIN tags t3 ON ct3.tag_id = t3.id
                    WHERE t3.name IN ({ph})
                )
            ''')
            params.extend(exclude_tags)
        if title_query:
            conds.append('c.title LIKE ?')
            params.append(f'%{title_query}%')
        if author_query:
            conds.append('a.name LIKE ?')
            params.append(f'%{author_query}%')
        if series_id is not None:
            conds.append('c.series_id = ?')
            params.append(series_id)
        if min_views is not None:
            conds.append('c.view_count >= ?')
            params.append(min_views)
        if max_views is not None:
            conds.append('c.view_count <= ?')
            params.append(max_views)
        if conds:
            query += ' WHERE ' + ' AND '.join(conds)
        query += ' ORDER BY c.title'
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            results = self._rows_to_dicts(cur)
        if folder:
            results = [c for c in results
                       if self._in_folder(c.get('file_path'), folder)]
        return results

    # ============================================================
    # ВИДЕО
    # ============================================================

    def cleanup_missing_videos(self) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('SELECT id, file_path FROM videos')
            removed = 0
            for vid, fp in cur.fetchall():
                if not os.path.exists(fp):
                    cur.execute('DELETE FROM videos WHERE id = ?', (vid,))
                    removed += 1
            return removed

    def _update_no_tags_for_video(self, video_id: int):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT COUNT(*) FROM video_tags vt
                JOIN tags t ON vt.tag_id = t.id
                WHERE vt.video_id = ? AND t.name != ?
            ''', (video_id, self.NO_TAGS_NAME))
            real_count = cur.fetchone()[0]
            cur.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)',
                        (self.NO_TAGS_NAME,))
            cur.execute('SELECT id FROM tags WHERE name = ?',
                        (self.NO_TAGS_NAME,))
            no_id = cur.fetchone()[0]
            if real_count == 0:
                cur.execute('INSERT OR IGNORE INTO video_tags '
                            '(video_id, tag_id) VALUES (?, ?)',
                            (video_id, no_id))
            else:
                cur.execute('DELETE FROM video_tags '
                            'WHERE video_id = ? AND tag_id = ?',
                            (video_id, no_id))

    def assign_tag_to_video(self, video_id: int, tag_id: int):
        with self._connect() as conn:
            conn.execute('INSERT OR IGNORE INTO video_tags '
                         '(video_id, tag_id) VALUES (?, ?)',
                         (video_id, tag_id))
        self._update_no_tags_for_video(video_id)

    def remove_tag_from_video(self, video_id: int, tag_id: int):
        with self._connect() as conn:
            conn.execute('DELETE FROM video_tags '
                         'WHERE video_id = ? AND tag_id = ?',
                         (video_id, tag_id))
        self._update_no_tags_for_video(video_id)

    def set_video_tags(self, video_id: int, tag_names: List[str]):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('DELETE FROM video_tags WHERE video_id = ?',
                        (video_id,))
            for name in tag_names:
                cur.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)',
                            (name,))
                cur.execute('SELECT id FROM tags WHERE name = ?', (name,))
                tid = cur.fetchone()[0]
                cur.execute('INSERT OR IGNORE INTO video_tags '
                            '(video_id, tag_id) VALUES (?, ?)',
                            (video_id, tid))
        self._update_no_tags_for_video(video_id)

    def add_video(self, title, file_path, duration=0,
                  series_id=None, series_order=None, author_id=None,
                  description=""):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT OR IGNORE INTO videos
                (title, file_path, duration, series_id, series_order,
                 author_id, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (title, file_path, duration, series_id, series_order,
                  author_id, description))
            cur.execute('SELECT id FROM videos WHERE file_path = ?',
                        (file_path,))
            row = cur.fetchone()
            vid = row[0] if row else 0
        if vid:
            self._update_no_tags_for_video(vid)
        return vid

    def update_video(self, video_id: int, **kwargs):
        if not kwargs:
            return
        set_clause = ', '.join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [video_id]
        with self._connect() as conn:
            conn.execute(f'UPDATE videos SET {set_clause} WHERE id = ?', vals)

    def _get_video_by(self, where, value):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(f'''
                SELECT v.*, s.name as series_name, a.name as author_name
                FROM videos v
                LEFT JOIN series s ON v.series_id = s.id
                LEFT JOIN authors a ON v.author_id = a.id
                WHERE {where}
            ''', (value,))
            return self._row_to_dict(cur)

    def get_video(self, video_id):
        return self._get_video_by('v.id = ?', video_id)

    def get_video_by_path(self, fp):
        return self._get_video_by('v.file_path = ?', fp)

    def get_all_videos(self) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT v.*, s.name as series_name, a.name as author_name
                FROM videos v
                LEFT JOIN series s ON v.series_id = s.id
                LEFT JOIN authors a ON v.author_id = a.id
                ORDER BY v.title
            ''')
            return self._rows_to_dicts(cur)

    def get_videos_in_folder(self, folder: str) -> List[Dict]:
        videos = self.get_all_videos()
        if not folder:
            return videos
        return [v for v in videos
                if self._in_folder(v.get('file_path'), folder)]

    def get_top_videos_by_views(self, limit: int = 24) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT v.*, s.name as series_name, a.name as author_name
                FROM videos v
                LEFT JOIN series s ON v.series_id = s.id
                LEFT JOIN authors a ON v.author_id = a.id
                ORDER BY v.watch_count DESC, v.title ASC
                LIMIT ?
            ''', (limit,))
            return self._rows_to_dicts(cur)

    def get_top_videos_by_views_with_tags(self, limit: int = 24) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT v.*, s.name as series_name, a.name as author_name,
                       GROUP_CONCAT(t.name, '|') as tags_concat
                FROM videos v
                LEFT JOIN series s ON v.series_id = s.id
                LEFT JOIN authors a ON v.author_id = a.id
                LEFT JOIN video_tags vt ON v.id = vt.video_id
                LEFT JOIN tags t ON vt.tag_id = t.id AND t.name != ?
                GROUP BY v.id
                ORDER BY v.watch_count DESC, v.title ASC
                LIMIT ?
            ''', (self.NO_TAGS_NAME, limit))
            rows = self._rows_to_dicts(cur)
        for r in rows:
            r['tags'] = self._split_tags(r.pop('tags_concat', None))
        return rows

    def get_video_tags(self, video_id: int) -> List[str]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT t.name FROM tags t
                JOIN video_tags vt ON t.id = vt.tag_id
                WHERE vt.video_id = ? AND t.name != ?
            ''', (video_id, self.NO_TAGS_NAME))
            return [r[0] for r in cur.fetchall()]

    def get_all_tags_for_video(self, video_id: int) -> List[str]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT t.name FROM tags t
                JOIN video_tags vt ON t.id = vt.tag_id
                WHERE vt.video_id = ? ORDER BY t.name
            ''', (video_id,))
            return [r[0] for r in cur.fetchall()]

    def get_similar_videos(self, video_id: int, limit: int = 20) -> List[Dict]:
        """Похожие видео: сортировка по числу общих тегов, затем по
        просмотрам. Если у текущего видео нет тегов — топ по просмотрам.

        Возвращает список словарей с полями video.*, series_name,
        author_name и match_count (число общих тегов).
        """
        with self._connect() as conn:
            cur = conn.cursor()

            # Теги текущего видео (без NO_TAGS_NAME)
            cur.execute('''
                SELECT vt.tag_id FROM video_tags vt
                JOIN tags t ON vt.tag_id = t.id
                WHERE vt.video_id = ? AND t.name != ?
            ''', (video_id, self.NO_TAGS_NAME))
            current_tag_ids = [r[0] for r in cur.fetchall()]

            # Нет тегов — топ по просмотрам
            if not current_tag_ids:
                cur.execute('''
                    SELECT v.*, s.name as series_name,
                           a.name as author_name,
                           0 as match_count
                    FROM videos v
                    LEFT JOIN series s ON v.series_id = s.id
                    LEFT JOIN authors a ON v.author_id = a.id
                    WHERE v.id != ?
                    ORDER BY v.watch_count DESC, v.title ASC
                    LIMIT ?
                ''', (video_id, limit))
                return self._rows_to_dicts(cur)

            placeholders = ','.join('?' for _ in current_tag_ids)
            # JOIN + GROUP BY вместо HAVING без GROUP BY:
            # JOIN отсекает видео без общих тегов,
            # GROUP BY v.id агрегирует совпадения.
            cur.execute(f'''
                SELECT v.*, s.name as series_name,
                       a.name as author_name,
                       COUNT(DISTINCT vt.tag_id) as match_count
                FROM videos v
                LEFT JOIN series s ON v.series_id = s.id
                LEFT JOIN authors a ON v.author_id = a.id
                INNER JOIN video_tags vt ON vt.video_id = v.id
                WHERE vt.tag_id IN ({placeholders})
                  AND v.id != ?
                GROUP BY v.id
                ORDER BY match_count DESC, v.watch_count DESC, v.title ASC
                LIMIT ?
            ''', tuple(current_tag_ids) + (video_id, limit))
            return self._rows_to_dicts(cur)

    def increment_watch_count(self, video_id: int):
        with self._connect() as conn:
            conn.execute('UPDATE videos SET watch_count = watch_count + 1 '
                         'WHERE id = ?', (video_id,))

    def save_video_progress(self, video_id: int, position_ms: int):
        with self._connect() as conn:
            conn.execute('''
                UPDATE videos SET last_position = ?,
                                  last_watched = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (position_ms, video_id))

    def delete_video(self, video_id: int):
        with self._connect() as conn:
            conn.execute('DELETE FROM videos WHERE id = ?', (video_id,))

    def search_videos(self, include_tags=None, exclude_tags=None,
                      title_query=None, author_query=None,
                      min_watch=None, max_watch=None,
                      folder=None) -> List[Dict]:
        query = '''
            SELECT DISTINCT v.*, s.name as series_name,
                            a.name as author_name
            FROM videos v
            LEFT JOIN series s ON v.series_id = s.id
            LEFT JOIN authors a ON v.author_id = a.id
        '''
        params, conds = [], []
        if include_tags:
            ph = ','.join('?' for _ in include_tags)
            conds.append(f'''
                v.id IN (
                    SELECT video_id FROM video_tags vt2
                    JOIN tags t2 ON vt2.tag_id = t2.id
                    WHERE t2.name IN ({ph})
                    GROUP BY video_id
                    HAVING COUNT(DISTINCT t2.name) = {len(include_tags)}
                )
            ''')
            params.extend(include_tags)
        if exclude_tags:
            ph = ','.join('?' for _ in exclude_tags)
            conds.append(f'''
                v.id NOT IN (
                    SELECT video_id FROM video_tags vt3
                    JOIN tags t3 ON vt3.tag_id = t3.id
                    WHERE t3.name IN ({ph})
                )
            ''')
            params.extend(exclude_tags)
        if title_query:
            conds.append('v.title LIKE ?')
            params.append(f'%{title_query}%')
        if author_query:
            conds.append('a.name LIKE ?')
            params.append(f'%{author_query}%')
        if min_watch is not None:
            conds.append('v.watch_count >= ?')
            params.append(min_watch)
        if max_watch is not None:
            conds.append('v.watch_count <= ?')
            params.append(max_watch)
        if conds:
            query += ' WHERE ' + ' AND '.join(conds)
        query += ' ORDER BY v.title'
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            results = self._rows_to_dicts(cur)
        if folder:
            results = [v for v in results
                       if self._in_folder(v.get('file_path'), folder)]
        return results

    # ============================================================
    # ИГРЫ
    # ============================================================

    def cleanup_missing_games(self) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('SELECT id, exe_path FROM games')
            removed = 0
            for gid, fp in cur.fetchall():
                if not os.path.exists(fp):
                    cur.execute('DELETE FROM games WHERE id = ?', (gid,))
                    removed += 1
            return removed

    def _update_no_tags_for_game(self, game_id: int):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT COUNT(*) FROM game_tags gt
                JOIN tags t ON gt.tag_id = t.id
                WHERE gt.game_id = ? AND t.name != ?
            ''', (game_id, self.NO_TAGS_NAME))
            real_count = cur.fetchone()[0]
            cur.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)',
                        (self.NO_TAGS_NAME,))
            cur.execute('SELECT id FROM tags WHERE name = ?',
                        (self.NO_TAGS_NAME,))
            no_id = cur.fetchone()[0]
            if real_count == 0:
                cur.execute('INSERT OR IGNORE INTO game_tags '
                            '(game_id, tag_id) VALUES (?, ?)',
                            (game_id, no_id))
            else:
                cur.execute('DELETE FROM game_tags '
                            'WHERE game_id = ? AND tag_id = ?',
                            (game_id, no_id))

    def assign_tag_to_game(self, game_id: int, tag_id: int):
        with self._connect() as conn:
            conn.execute('INSERT OR IGNORE INTO game_tags '
                         '(game_id, tag_id) VALUES (?, ?)',
                         (game_id, tag_id))
        self._update_no_tags_for_game(game_id)

    def remove_tag_from_game(self, game_id: int, tag_id: int):
        with self._connect() as conn:
            conn.execute('DELETE FROM game_tags '
                         'WHERE game_id = ? AND tag_id = ?',
                         (game_id, tag_id))
        self._update_no_tags_for_game(game_id)

    def set_game_tags(self, game_id: int, tag_names: List[str]):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('DELETE FROM game_tags WHERE game_id = ?', (game_id,))
            for name in tag_names:
                cur.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)',
                            (name,))
                cur.execute('SELECT id FROM tags WHERE name = ?', (name,))
                tid = cur.fetchone()[0]
                cur.execute('INSERT OR IGNORE INTO game_tags '
                            '(game_id, tag_id) VALUES (?, ?)',
                            (game_id, tid))
        self._update_no_tags_for_game(game_id)

    def add_game(self, title, exe_path, working_dir=None, arguments=None,
                 description="", cover_path=None, archive_path=None,
                 series_id=None, series_order=None, author_id=None):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT OR IGNORE INTO games
                (title, exe_path, working_dir, arguments, description,
                 cover_path, archive_path, series_id, series_order, author_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, exe_path, working_dir, arguments, description,
                  cover_path, archive_path, series_id, series_order, author_id))
            if archive_path:
                cur.execute('''
                    UPDATE games SET archive_path = ?
                    WHERE exe_path = ? AND (archive_path IS NULL OR archive_path = '')
                ''', (archive_path, exe_path))
            cur.execute('SELECT id FROM games WHERE exe_path = ?', (exe_path,))
            row = cur.fetchone()
            gid = row[0] if row else 0
        if gid:
            self._update_no_tags_for_game(gid)
        return gid

    def update_game(self, game_id: int, **kwargs):
        if not kwargs:
            return
        set_clause = ', '.join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [game_id]
        with self._connect() as conn:
            conn.execute(f'UPDATE games SET {set_clause} WHERE id = ?', vals)

    def _get_game_by(self, where, value):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(f'''
                SELECT g.*,
                       s.name as series_name,
                       a.name as author_name
                FROM games g
                LEFT JOIN series s ON g.series_id = s.id
                LEFT JOIN authors a ON g.author_id = a.id
                WHERE {where}
            ''', (value,))
            return self._row_to_dict(cur)

    def get_game(self, game_id):
        return self._get_game_by('g.id = ?', game_id)

    def get_game_by_id(self, game_id):
        return self._get_game_by('g.id = ?', game_id)

    def get_game_by_path(self, exe_path):
        return self._get_game_by('g.exe_path = ?', exe_path)

    def get_all_games(self) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT g.*,
                       s.name as series_name,
                       a.name as author_name
                FROM games g
                LEFT JOIN series s ON g.series_id = s.id
                LEFT JOIN authors a ON g.author_id = a.id
                ORDER BY g.title
            ''')
            return self._rows_to_dicts(cur)

    def get_games_in_folder(self, folder: str) -> List[Dict]:
        games = self.get_all_games()
        if not folder:
            return games
        return [g for g in games
                if self._in_folder(g.get('exe_path'), folder)]

    def get_top_games_by_launches(self, limit: int = 24) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT * FROM games
                ORDER BY launch_count DESC, title ASC
                LIMIT ?
            ''', (limit,))
            return self._rows_to_dicts(cur)

    def get_top_games_by_launches_with_tags(self, limit: int = 24) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT g.*,
                       s.name as series_name,
                       a.name as author_name,
                       GROUP_CONCAT(t.name, '|') as tags_concat
                FROM games g
                LEFT JOIN series s ON g.series_id = s.id
                LEFT JOIN authors a ON g.author_id = a.id
                LEFT JOIN game_tags gt ON g.id = gt.game_id
                LEFT JOIN tags t ON gt.tag_id = t.id AND t.name != ?
                GROUP BY g.id
                ORDER BY g.launch_count DESC, g.title ASC
                LIMIT ?
            ''', (self.NO_TAGS_NAME, limit))
            rows = self._rows_to_dicts(cur)
        for r in rows:
            r['tags'] = self._split_tags(r.pop('tags_concat', None))
        return rows

    def get_game_tags(self, game_id: int) -> List[str]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT t.name FROM tags t
                JOIN game_tags gt ON t.id = gt.tag_id
                WHERE gt.game_id = ? AND t.name != ?
            ''', (game_id, self.NO_TAGS_NAME))
            return [r[0] for r in cur.fetchall()]

    def increment_game_launch(self, game_id: int):
        with self._connect() as conn:
            conn.execute('''
                UPDATE games
                SET launch_count = launch_count + 1,
                    last_launched = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (game_id,))

    def add_game_playtime(self, game_id: int, seconds: int):
        if seconds <= 0:
            return
        with self._connect() as conn:
            conn.execute('''
                UPDATE games
                SET total_playtime = total_playtime + ?
                WHERE id = ?
            ''', (seconds, game_id))

    def delete_game(self, game_id: int):
        with self._connect() as conn:
            conn.execute('DELETE FROM games WHERE id = ?', (game_id,))

    def clear_game_archive_path(self, game_id: int):
        with self._connect() as conn:
            conn.execute('UPDATE games SET archive_path = NULL WHERE id = ?',
                         (game_id,))

    def search_games(self, include_tags=None, exclude_tags=None,
                     title_query=None, author_query=None,
                     min_launch=None, max_launch=None,
                     folder=None) -> List[Dict]:
        query = '''
            SELECT DISTINCT g.*,
                   s.name as series_name,
                   a.name as author_name
            FROM games g
            LEFT JOIN series s ON g.series_id = s.id
            LEFT JOIN authors a ON g.author_id = a.id
        '''
        params, conds = [], []
        if include_tags:
            ph = ','.join('?' for _ in include_tags)
            conds.append(f'''
                g.id IN (
                    SELECT game_id FROM game_tags gt2
                    JOIN tags t2 ON gt2.tag_id = t2.id
                    WHERE t2.name IN ({ph})
                    GROUP BY game_id
                    HAVING COUNT(DISTINCT t2.name) = {len(include_tags)}
                )
            ''')
            params.extend(include_tags)
        if exclude_tags:
            ph = ','.join('?' for _ in exclude_tags)
            conds.append(f'''
                g.id NOT IN (
                    SELECT game_id FROM game_tags gt3
                    JOIN tags t3 ON gt3.tag_id = t3.id
                    WHERE t3.name IN ({ph})
                )
            ''')
            params.extend(exclude_tags)
        if title_query:
            conds.append('g.title LIKE ?')
            params.append(f'%{title_query}%')
        if author_query:
            conds.append('a.name LIKE ?')
            params.append(f'%{author_query}%')
        if min_launch is not None:
            conds.append('g.launch_count >= ?')
            params.append(min_launch)
        if max_launch is not None:
            conds.append('g.launch_count <= ?')
            params.append(max_launch)
        if conds:
            query += ' WHERE ' + ' AND '.join(conds)
        query += ' ORDER BY g.title'
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            results = self._rows_to_dicts(cur)
        if folder:
            results = [g for g in results
                       if self._in_folder(g.get('exe_path'), folder)]
        return results