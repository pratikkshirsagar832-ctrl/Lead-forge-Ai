"""
LeadForge — Supabase-Compatibility Layer

Provides a supabase-like interface using local PostgreSQL.
This lets existing routers work with minimal changes.

Usage:
    from app.database import get_supabase_admin
    db = get_supabase_admin()
    result = db.table("users").select("*").eq("id", user_id).execute()
"""

import json
import logging
from datetime import datetime, date
from typing import Any, Optional

import psycopg2.extras

from app.db import get_conn, query_one as _q1, query_all as _qa, execute as _exec

logger = logging.getLogger(__name__)


class NotModifier:
    """Enables `.not_.in_()` and `.not_.is_()` syntax like Supabase."""
    def __init__(self, builder: QueryBuilder):
        self._builder = builder

    def in_(self, col: str, values: list):
        if values:
            placeholders = ", ".join(["%s"] * len(values))
            self._builder._where.append(f'"{col}" NOT IN ({placeholders})')
            self._builder._where_params.extend(values)
        return self._builder

    def is_(self, col: str, val):
        if val is None:
            self._builder._where.append(f'"{col}" IS NOT NULL')
        return self._builder


class QueryBuilder:
    """Mimics Supabase table query builder but runs on local PostgreSQL."""

    def __init__(self, table_name: str):
        self.table = table_name
        self._select_cols = "*"
        self._where = []
        self._where_params = []
        self._order = None
        self._limit_val = None
        self._offset_val = None
        self._ilike = None
        self._like = None
        self._neq = None
        self._not_in = None
        self._insert_data = None
        self._update_data = None
        self._delete = False
        self._count_only = False
        self._rpc_name = None
        self._rpc_params = None

    def select(self, cols: str = "*", count: str = None):
        self._select_cols = cols
        if count == "exact":
            self._count_only = True
        return self

    def insert(self, data: dict):
        self._insert_data = data
        return self

    def update(self, data: dict):
        self._update_data = data
        return self

    def delete(self):
        self._delete = True
        return self

    def eq(self, col: str, val):
        self._where.append(f'"{col}" = %s')
        self._where_params.append(val)
        return self

    def neq(self, col: str, val):
        self._where.append(f'"{col}" != %s')
        self._where_params.append(val)
        return self

    def gt(self, col: str, val):
        self._where.append(f'"{col}" > %s')
        self._where_params.append(val)
        return self

    def lt(self, col: str, val):
        self._where.append(f'"{col}" < %s')
        self._where_params.append(val)
        return self

    def gte(self, col: str, val):
        self._where.append(f'"{col}" >= %s')
        self._where_params.append(val)
        return self

    def lte(self, col: str, val):
        self._where.append(f'"{col}" <= %s')
        self._where_params.append(val)
        return self

    def ilike(self, col: str, pattern: str):
        self._where.append(f'"{col}" ILIKE %s')
        self._where_params.append(pattern)
        return self

    def like(self, col: str, pattern: str):
        self._where.append(f'"{col}" LIKE %s')
        self._where_params.append(pattern)
        return self

    def in_(self, col: str, values: list):
        if values:
            placeholders = ", ".join(["%s"] * len(values))
            self._where.append(f'"{col}" IN ({placeholders})')
            self._where_params.extend(values)
        return self

    def not_in(self, col: str, values: list):
        if values:
            placeholders = ", ".join(["%s"] * len(values))
            self._where.append(f'"{col}" NOT IN ({placeholders})')
            self._where_params.extend(values)
        return self

    def not_(self):
        """Returns a NotModifier that wraps the next chain call."""
        return NotModifier(self)

    def is_(self, col: str, val):
        if val is None:
            self._where.append(f'"{col}" IS NULL')
        else:
            self._where.append(f'"{col}" = %s')
            self._where_params.append(val)
        return self

    def order(self, col: str, desc: bool = False, nulls_last: bool = False):
        direction = "DESC" if desc else "ASC"
        nulls = "NULLS LAST" if nulls_last else ""
        self._order = f'"{col}" {direction} {nulls}'.strip()
        return self

    def limit(self, n: int):
        self._limit_val = n
        return self

    def range(self, start: int, end: int):
        self._offset_val = start
        self._limit_val = end - start + 1
        return self

    def maybe_single(self):
        self._limit_val = 1
        return self

    def execute(self) -> "QueryResult":
        try:
            if self._rpc_name:
                return self._execute_rpc()
            if self._insert_data:
                return self._execute_insert()
            if self._update_data:
                return self._execute_update()
            if self._delete:
                return self._execute_delete()
            return self._execute_select()
        except Exception as e:
            logger.error(f"[DB] Query error on {self.table}: {e}", exc_info=True)
            raise

    def _build_where(self) -> tuple[str, list]:
        if not self._where:
            return "", []
        return " WHERE " + " AND ".join(self._where), self._where_params

    def _execute_select(self) -> "QueryResult":
        where_clause, params = self._build_where()

        if self._count_only:
            sql = f'SELECT COUNT(*) as count FROM "{self.table}"{where_clause}'
            with get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, params)
                    row = cur.fetchone()
                    count = row["count"] if row else 0
                    return QueryResult(data=[], count=count)

        cols = self._select_cols
        sql = f'SELECT {cols} FROM "{self.table}"{where_clause}'

        if self._order:
            sql += f" ORDER BY {self._order}"
        if self._limit_val is not None:
            sql += f" LIMIT {self._limit_val}"
        if self._offset_val is not None:
            sql += f" OFFSET {self._offset_val}"

        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                data = [self._serialize_row(dict(r)) for r in rows]
                return QueryResult(data=data)

    def _execute_insert(self) -> "QueryResult":
        data = self._insert_data
        cols = list(data.keys())
        vals = [self._serialize_value(v) for v in data.values()]
        placeholders = ", ".join(["%s"] * len(cols))
        col_str = ", ".join([f'"{c}"' for c in cols])

        sql = f'INSERT INTO "{self.table}" ({col_str}) VALUES ({placeholders}) RETURNING *'

        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, vals)
                row = cur.fetchone()
                return QueryResult(data=[self._serialize_row(dict(row))] if row else [])

    def _execute_update(self) -> "QueryResult":
        data = self._update_data
        where_clause, where_params = self._build_where()

        set_parts = []
        set_params = []
        for k, v in data.items():
            set_parts.append(f'"{k}" = %s')
            set_params.append(self._serialize_value(v))

        sql = f'UPDATE "{self.table}" SET {", ".join(set_parts)}{where_clause} RETURNING *'

        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, set_params + where_params)
                rows = cur.fetchall()
                return QueryResult(data=[self._serialize_row(dict(r)) for r in rows])

    def _execute_delete(self) -> "QueryResult":
        where_clause, params = self._build_where()
        sql = f'DELETE FROM "{self.table}"{where_clause}'

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return QueryResult(data=[])

    def _execute_rpc(self) -> "QueryResult":
        sql = f"SELECT * FROM {self._rpc_name}({', '.join(['%s'] * len(self._rpc_params))})"
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, self._rpc_params)
                rows = cur.fetchall()
                data = [self._serialize_row(dict(r)) for r in rows]
                if data and len(data) == 1:
                    return QueryResult(data=data, single=True)
                return QueryResult(data=data)

    def _serialize_row(self, row: dict) -> dict:
        for k, v in row.items():
            if isinstance(v, (datetime, date)):
                row[k] = v.isoformat()
            elif isinstance(v, dict) or (isinstance(v, list) and v and isinstance(v[0], dict)):
                row[k] = v  # JSONB already parsed by psycopg2
        return row

    def _serialize_value(self, v):
        if isinstance(v, (dict, list)):
            return json.dumps(v)
        return v


class QueryResult:
    """Mimics Supabase query result."""

    def __init__(self, data: list = None, count: int = None, single: bool = False):
        self.data = data or []
        self.count = count
        self._single = single

    def __iter__(self):
        return iter(self.data)


class SupabaseClient:
    """Supabase-compatible client using local PostgreSQL."""

    def table(self, name: str) -> QueryBuilder:
        return QueryBuilder(name)

    def rpc(self, fn_name: str, params: dict = None) -> QueryBuilder:
        qb = QueryBuilder("")
        qb._rpc_name = fn_name
        qb._rpc_params = list(params.values()) if params else []
        return qb

    class _AuthStub:
        """Minimal auth stub — actual auth goes through /api/auth endpoints."""
        def get_user(self, token=None):
            return None
        def sign_in_with_password(self, **kw):
            return None
        def sign_up(self, **kw):
            return None
        def sign_out(self):
            return None

    @property
    def auth(self):
        return self._AuthStub()


def get_supabase_admin() -> SupabaseClient:
    """Drop-in replacement for the old Supabase admin client."""
    return SupabaseClient()


def get_supabase_client() -> SupabaseClient:
    """Drop-in replacement for the old Supabase client."""
    return SupabaseClient()
