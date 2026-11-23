import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid4().hex


class Database:
    def __init__(self, directory):
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
              indexed_hash TEXT, error TEXT, created_at TEXT NOT NULL);
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
            CREATE TABLE IF NOT EXISTS query_logs (
              id TEXT PRIMARY KEY, user_id TEXT, question TEXT, timestamp TEXT NOT NULL,
              latency_ms REAL NOT NULL, sources TEXT NOT NULL, outcome TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
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

    def all(self, sql, args=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as c:
            c.execute(sql, args)

    def count(self, name, amount=1):
        self.execute('INSERT INTO counters VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value', (name, amount))

    def cached(self, key):
        row = self.one('SELECT vector FROM embeddings WHERE key=?', (key,))
        return json.loads(row['vector']) if row else None
