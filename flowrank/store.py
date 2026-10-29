"""One request-scoped transaction; PostgreSQL RLS adds tenant isolation."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, created DOUBLE PRECISION NOT NULL, expires DOUBLE PRECISION NOT NULL,
 variant TEXT NOT NULL, personalized INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS videos (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, topic TEXT NOT NULL, caption TEXT NOT NULL,
 creator TEXT NOT NULL, media_url TEXT NOT NULL, poster_url TEXT NOT NULL, duration DOUBLE PRECISION NOT NULL,
 quality DOUBLE PRECISION NOT NULL, popularity DOUBLE PRECISION NOT NULL, created DOUBLE PRECISION NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','approved','blocked')), source TEXT NOT NULL, license TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS impressions (
 id TEXT PRIMARY KEY, token_hash TEXT NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
 video INTEGER NOT NULL REFERENCES videos(id), created DOUBLE PRECISION NOT NULL, variant TEXT NOT NULL,
 position INTEGER NOT NULL, features TEXT NOT NULL, score DOUBLE PRECISION NOT NULL,
 UNIQUE(id, token_hash, video)
);
CREATE TABLE IF NOT EXISTS feedback (
 event_id TEXT NOT NULL, token_hash TEXT NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
 impression TEXT NOT NULL, video INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('watch','like','skip','report')),
 watch DOUBLE PRECISION NOT NULL CHECK(watch >= 0 AND watch <= 1), created DOUBLE PRECISION NOT NULL,
 PRIMARY KEY(token_hash,event_id), UNIQUE(token_hash,impression,kind),
 FOREIGN KEY(impression,token_hash,video) REFERENCES impressions(id,token_hash,video) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, bucket INTEGER NOT NULL, hits INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS feedback_user_time ON feedback(token_hash,created);
CREATE INDEX IF NOT EXISTS impressions_user_time ON impressions(token_hash,created);
CREATE INDEX IF NOT EXISTS videos_eligible ON videos(status,topic,created);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires);
'''


class Store:
    def __init__(self, url=None, path=None):
        self.url = url if url is not None else os.environ.get('DATABASE_URL')
        if os.environ.get('VERCEL') and not self.url:
            raise RuntimeError('DATABASE_URL is required on Vercel; ephemeral storage is disabled')
        self.path = path or os.environ.get('FLOWRANK_SQLITE', 'data/product.db')
        if not self.url:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            with self.transaction() as tx:
                tx.connection.executescript(SCHEMA)

    @contextmanager
    def transaction(self, token_hash='', admin=False):
        if self.url:
            import psycopg
            from psycopg.rows import dict_row
            connection = psycopg.connect(self.url, row_factory=dict_row, connect_timeout=8, prepare_threshold=None)
            connection.execute("SET search_path TO flowrank,pg_catalog")
            connection.execute("SELECT set_config('app.session_hash', %s, true)", (token_hash,))
            # Only the separate maintenance login has the BYPASSRLS attribute.
        else:
            connection = sqlite3.connect(self.path, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
        try:
            yield Transaction(connection, bool(self.url))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class Transaction:
    def __init__(self, connection, postgres):
        self.connection, self.postgres = connection, postgres

    def execute(self, sql, values=()):
        return self.connection.execute(sql.replace('?', '%s') if self.postgres else sql, values)

    def rows(self, sql, values=()):
        return [dict(row) for row in self.execute(sql, values).fetchall()]

    def one(self, sql, values=()):
        row = self.execute(sql, values).fetchone()
        return dict(row) if row else None
