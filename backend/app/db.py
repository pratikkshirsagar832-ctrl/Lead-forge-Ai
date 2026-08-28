"""
LeadForge — Local PostgreSQL Database Client

Replaces Supabase for all data operations.
Uses psycopg2 for synchronous queries.
"""

import os
import json
import logging
from datetime import datetime, date
from typing import Any, Optional
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

_pool: Optional[ThreadedConnectionPool] = None

# ── Connection Pool ──────────────────────────────────────────────

def get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            host=os.getenv("PG_HOST", "postgres"),
            port=int(os.getenv("PG_PORT", "5432")),
            dbname=os.getenv("PG_DATABASE", "leadforge"),
            user=os.getenv("PG_USER", "leadforge"),
            password=os.getenv("PG_PASSWORD", "leadforge_secret_2026"),
        )
        logger.info("[DB] PostgreSQL connection pool created")
    return _pool


@contextmanager
def get_conn():
    """Get a connection from the pool. Auto-commits on success, rolls back on error."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(cursor_factory=psycopg2.extras.RealDictCursor):
    """Get a cursor from a pooled connection."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            yield cur


# ── Query Helpers ────────────────────────────────────────────────

def query_one(sql: str, params: tuple = None) -> Optional[dict]:
    """Execute a query and return one row as dict, or None."""
    with get_cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def query_all(sql: str, params: tuple = None) -> list[dict]:
    """Execute a query and return all rows as list of dicts."""
    with get_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def execute(sql: str, params: tuple = None) -> None:
    """Execute a statement (INSERT/UPDATE/DELETE)."""
    with get_cursor() as cur:
        cur.execute(sql, params)


def execute_returning(sql: str, params: tuple = None) -> Optional[dict]:
    """Execute a statement with RETURNING and return the row."""
    with get_cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def call_fn(sql: str, params: tuple = None) -> Optional[dict]:
    """Call a PostgreSQL function and return the result."""
    with get_cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def call_fn_all(sql: str, params: tuple = None) -> list[dict]:
    """Call a PostgreSQL function and return all rows."""
    with get_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


# ── JSON serialization helper ────────────────────────────────────

def adapt_json(value: Any) -> str:
    """Serialize a Python value to JSON string for PostgreSQL JSONB."""
    return json.dumps(value)
