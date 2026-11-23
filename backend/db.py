import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid4().hex


class TestDatabase:
    def __init__(self, directory):
        import threading
        self.local = threading.local()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'guidely.sqlite3'
        with self.connect() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
              role TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
              expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY, filename TEXT NOT NULL, text TEXT NOT NULL,
              tags TEXT NOT NULL DEFAULT '[]', category TEXT NOT NULL DEFAULT '',
              state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
              indexed_hash TEXT, error TEXT, created_at TEXT NOT NULL, object_key TEXT);
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
              state TEXT NOT NULL, error TEXT, chunks INTEGER DEFAULT 0,
              elapsed_ms REAL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS embeddings (
              key TEXT PRIMARY KEY, kind TEXT NOT NULL, vector TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS conversations (
              id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
              title TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
              question TEXT NOT NULL, response TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS vector_chunks (id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, model TEXT NOT NULL, snippet TEXT NOT NULL, section TEXT NOT NULL, page INTEGER NOT NULL, vector TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS upload_intents (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), filename TEXT NOT NULL, object_key TEXT UNIQUE NOT NULL, size INTEGER NOT NULL, expires REAL NOT NULL, completed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS login_attempts (key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS query_logs (
              id TEXT PRIMARY KEY, user_id TEXT, question TEXT, timestamp TEXT NOT NULL,
              latency_ms REAL NOT NULL, sources TEXT NOT NULL, outcome TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        existing = getattr(self.local, 'connection', None)
        if existing is not None:
            yield existing
            return
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    @contextmanager
    def session(self, detached=False):
        previous = getattr(self.local, 'connection', None)
        if detached:
            self.local.connection = None
        try:
            with self.connect() as connection:
                self.local.connection = connection
                yield connection
        finally:
            self.local.connection = previous

    def all(self, sql, args=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as c:
            c.execute(sql, args)

    def savepoint(self):
        from contextlib import nullcontext
        return nullcontext()

    @property
    def lock(self):
        import threading
        if not hasattr(self, '_lock'):
            self._lock = threading.RLock()
        return self._lock

    def count(self, name, amount=1):
        self.execute('INSERT INTO counters VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=counters.value+excluded.value', (name, amount))

    def cached(self, key):
        row = self.one('SELECT vector FROM embeddings WHERE key=?', (key,))
        return json.loads(row['vector']) if row else None


class Database:
    """Short PostgreSQL connections; transaction pooler safe, no process-local sessions."""
    def __init__(self, settings):
        import threading
        self.url = settings.database_url
        self.local = threading.local()
        self.lock = TransactionLock(self)

    @contextmanager
    def connect(self):
        existing = getattr(self.local, 'connection', None)
        if existing is not None:
            yield existing
            return
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10,
                             prepare_threshold=None, options='-c statement_timeout=180000') as conn:
            yield conn

    def sql(self, sql):
        return sql.replace('?', '%s')

    def all(self, sql, args=()):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(self.sql(sql), args).fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as conn:
            conn.execute(self.sql(sql), args)

    def savepoint(self):
        connection = getattr(self.local, 'connection', None)
        if connection is None:
            raise RuntimeError('Savepoints require a mutation transaction.')
        return connection.transaction()

    session = TestDatabase.session
    count = TestDatabase.count
    cached = TestDatabase.cached


class TransactionLock:
    """One cross-instance mutation/index operation; nested blocks share a transaction."""
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        from .errors import AppError
        previous = getattr(self.db.local, 'connection', None)
        frames = getattr(self.db.local, 'lock_frames', [])
        manager = None
        conn = previous
        if conn is None:
            manager = self.db.connect()
            conn = manager.__enter__()
        # A normal reusable connection scope does not imply advisory-lock ownership.
        already_locked = any(frame[0] is conn for frame in frames)
        if not already_locked:
            try:
                acquired = conn.execute('SELECT pg_try_advisory_xact_lock(71842390) AS acquired').fetchone()['acquired']
            except BaseException:
                if manager is not None:
                    import sys
                    manager.__exit__(*sys.exc_info())
                raise
            if not acquired:
                if manager is not None:
                    manager.__exit__(None, None, None)
                raise AppError(409, 'indexing_conflict', 'Another document operation is running. Wait and retry.')
        frames.append((conn, manager, previous))
        self.db.local.lock_frames = frames
        self.db.local.connection = conn
        return self

    def __exit__(self, kind, error, traceback):
        conn, manager, previous = self.db.local.lock_frames.pop()
        self.db.local.connection = previous
        if manager is not None:
            return manager.__exit__(kind, error, traceback)



def database(settings):
    if settings.test_mode:
        return TestDatabase(settings.data_dir)
    if not settings.database_url:
        raise RuntimeError('Set DATABASE_URL; local persistence is available only with GUIDELY_TEST_MODE=true.')
    return Database(settings)
