"""PostgreSQL storage backend with connection pooling and upsert."""

from __future__ import annotations

import os

import psycopg2
import psycopg2.extras
import psycopg2.pool

from .base import StorageBackend


class PostgresBackend(StorageBackend):
    """Persists records to a PostgreSQL table with batch upsert.

    Uses a ThreadedConnectionPool (min 1, max 4 connections).
    The `records` table is created automatically on init().

    Configuration via constructor args or environment variables:

        CDP_CAPTURE_DB_NAME  (default: cdp_capture)
        CDP_CAPTURE_DB_USER  (default: postgres)
        CDP_CAPTURE_DB_PASSWORD
        CDP_CAPTURE_DB_HOST  (default: 127.0.0.1)
        CDP_CAPTURE_DB_PORT  (default: 5432)
    """

    def __init__(
        self,
        dbname: str | None = None,
        user: str | None = None,
        password: str | None = None,
        host: str | None = None,
        port: str | None = None,
        table_name: str = "records",
    ):
        self._config = {
            "dbname": dbname or os.environ.get("CDP_CAPTURE_DB_NAME", "cdp_capture"),
            "user": user or os.environ.get("CDP_CAPTURE_DB_USER", "postgres"),
            "password": password or os.environ.get("CDP_CAPTURE_DB_PASSWORD", ""),
            "host": host or os.environ.get("CDP_CAPTURE_DB_HOST", "127.0.0.1"),
            "port": port or os.environ.get("CDP_CAPTURE_DB_PORT", "5432"),
        }
        self.table_name = table_name
        self._pool: psycopg2.pool.ThreadedConnectionPool | None = None

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Create pool, table, and indexes. Idempotent."""
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=4, **self._config
        )
        with self._session() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id BIGSERIAL PRIMARY KEY,
                        record_id VARCHAR(255) UNIQUE NOT NULL,
                        source_url TEXT,
                        title TEXT,
                        body_text TEXT,
                        author VARCHAR(255),
                        author_id VARCHAR(255),
                        record_type VARCHAR(50) DEFAULT '',
                        create_time TIMESTAMPTZ,
                        extra JSONB DEFAULT '{{}}',
                        captured_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name}_create_time
                    ON {self.table_name}(create_time DESC)
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name}_record_type
                    ON {self.table_name}(record_type)
                    """
                )
                conn.commit()

    def save(self, records: list[dict]) -> int:
        """Batch upsert records. Returns count of newly inserted rows."""
        if not records or self._pool is None:
            return 0

        sql = f"""
            INSERT INTO {self.table_name}
                (record_id, source_url, title, body_text, author, author_id,
                 record_type, create_time, extra, captured_at, updated_at)
            VALUES
                (%(record_id)s, %(source_url)s, %(title)s, %(body_text)s,
                 %(author)s, %(author_id)s, %(record_type)s, %(create_time)s,
                 %(extra)s, NOW(), NOW())
            ON CONFLICT (record_id) DO UPDATE SET
                title = EXCLUDED.title,
                body_text = EXCLUDED.body_text,
                author = EXCLUDED.author,
                extra = EXCLUDED.extra,
                updated_at = NOW()
        """

        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, sql, records)
            conn.commit()
            return len(records)
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            self._pool.closeall()
            self._pool = None

    @property
    def count(self) -> int:
        """Total records in the table."""
        if self._pool is None:
            return 0
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {self.table_name}")
                return cur.fetchone()[0]
        finally:
            self._pool.putconn(conn)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _session(self):
        """Context manager: get conn, commit on success, rollback on error."""
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            conn = self._pool.getconn()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                self._pool.putconn(conn)

        return _ctx()
