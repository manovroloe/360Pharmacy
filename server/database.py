from __future__ import annotations

"""Server-only Supabase PostgreSQL gateway.

The browser never receives DATABASE_URL or privileged Storage credentials.
Routes keep the existing db.select/insert/update API during the incremental
Clean Architecture migration. Every operation uses parameterized SQL.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID, uuid4
import re

try:
    import psycopg
    from psycopg import Error as PsycopgError
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError as exc:
    raise RuntimeError("Install dependencies with pip install -r requirements.txt (psycopg is required).") from exc

from settings import DATABASE_URL
from infrastructure.supabase_storage import storage


class DatabaseError(RuntimeError):
    pass


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
UUID_TABLES = {
    "profiles", "branches", "categories", "manufacturers", "suppliers", "products",
    "stock_receipts", "product_batches", "promotions", "customer_addresses", "prescriptions", "consultations",
    "orders", "order_items", "payments", "deliveries", "operating_expenses", "payroll_entries", "staff_tasks",
    "attendance_records", "staff_reports", "stock_deliveries", "stock_delivery_items",
}
_ACTIVE_TX: ContextVar[Any | None] = ContextVar("pharmacy360_postgres_transaction", default=None)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _as_db_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return Jsonb(value)
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}T", value):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return value


def _clean_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise DatabaseError("Invalid SQL identifier.")
    return value


def _quote(name: str) -> str:
    return '"' + _clean_identifier(name) + '"'


class SupabasePostgresGateway:
    """Thin server-side Postgres adapter: no hardcoded host/database."""

    @property
    def public_configured(self) -> bool:
        return bool(DATABASE_URL)

    @property
    def privileged_configured(self) -> bool:
        return bool(DATABASE_URL)

    def _connect(self):
        if not DATABASE_URL:
            raise DatabaseError("DATABASE_URL is missing. Copy your Supabase Postgres connection URI into server/.env.")
        if not DATABASE_URL.startswith(("postgresql://", "postgres://")):
            raise DatabaseError("DATABASE_URL must be the PostgreSQL URI from your Supabase project -> Connect.")
        try:
            # TLS is mandatory for hosted Supabase; disable prepared statements for
            # compatibility with the Supavisor transaction pooler (port 6543).
            return psycopg.connect(
                DATABASE_URL, row_factory=dict_row, sslmode="require",
                prepare_threshold=None, connect_timeout=12,
            )
        except PsycopgError as exc:
            raise DatabaseError("Supabase PostgreSQL connection failed. Check DATABASE_URL, SSL, and network/IPv4 pooler settings.") from exc

    @contextmanager
    def transaction(self):
        """All nested gateway queries participate in one ACID transaction."""
        already = _ACTIVE_TX.get()
        if already is not None:
            yield already
            return
        with self._connect() as conn:
            token = _ACTIVE_TX.set(conn)
            try:
                yield conn
            finally:
                _ACTIVE_TX.reset(token)

    @contextmanager
    def _using_conn(self):
        current = _ACTIVE_TX.get()
        if current is not None:
            yield current
        else:
            with self._connect() as conn:
                yield conn

    @staticmethod
    def _normalize_params(params: dict[str, Any] | Iterable[tuple[str, Any]] | None) -> list[tuple[str, Any]]:
        if params is None:
            return [("select", "*")]
        return list(params.items()) if isinstance(params, dict) else list(params)

    @staticmethod
    def _convert_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
        return {key: _json_ready(value) for key, value in dict(row).items()}

    def _where(self, params: list[tuple[str, Any]]) -> tuple[str, list[Any]]:
        clauses = []
        values = []
        for key, raw in params:
            if key in {"select", "order", "limit", "offset"}:
                continue
            col = _quote(str(key))
            expr = str(raw)
            op, value = expr.split(".", 1) if "." in expr else ("eq", expr)
            if op == "eq":
                if value.lower() == "null":
                    clauses.append(f"{col} IS NULL")
                else:
                    value = True if value.lower() == "true" else False if value.lower() == "false" else value
                    clauses.append(f"{col} = %s")
                    values.append(_as_db_value(value))
            elif op == "ilike":
                clauses.append(f"{col} ILIKE %s")
                values.append(value)
            elif op in {"gt", "gte", "lt", "lte"}:
                symbol = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
                clauses.append(f"{col} {symbol} %s")
                values.append(_as_db_value(value))
            elif op == "in" and value.startswith("(") and value.endswith(")"):
                parts = [x.strip().strip("'\"") for x in value[1:-1].split(",") if x.strip()]
                if parts:
                    clauses.append(f"{col} IN ({','.join(['%s'] * len(parts))})")
                    values.extend(_as_db_value(x) for x in parts)
                else:
                    clauses.append("FALSE")
            else:
                raise DatabaseError(f"Unsupported filter operator: {op}")
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", values

    @staticmethod
    def _order_limit(params: list[tuple[str, Any]]) -> tuple[str, list[Any]]:
        order_value = next((v for k,v in params if k == "order"), None)
        limit_value = next((v for k,v in params if k == "limit"), None)
        offset_value = next((v for k,v in params if k == "offset"), None)
        sql = ""
        args = []
        if order_value:
            chunks = []
            for segment in str(order_value).split(","):
                bits = segment.strip().split(".")
                col = _quote(bits[0])
                direction = "DESC" if "desc" in [x.lower() for x in bits[1:]] else "ASC"
                nulls_last = "nullslast" in [x.lower() for x in bits[1:]]
                chunks.append(f"{col} {direction}" + (" NULLS LAST" if nulls_last else ""))
            sql += " ORDER BY " + ", ".join(chunks)
        if limit_value is not None:
            try:
                limit = max(0, min(int(limit_value), 10000))
            except (TypeError, ValueError):
                limit = 100
            sql += " LIMIT %s"
            args.append(limit)
            if offset_value is not None:
                sql += " OFFSET %s"
                args.append(max(0,int(offset_value)))
        return sql, args

    def select(self, table: str, params=None, *, for_update: bool=False) -> list[dict[str, Any]]:
        table = _clean_identifier(table)
        pairs = self._normalize_params(params)
        selection = next((str(v) for k,v in pairs if k == "select"), "*")
        cols = "*" if selection == "*" else ",".join(_quote(c.strip()) for c in selection.split(",") if c.strip())
        clause, args = self._where(pairs)
        end, end_args = self._order_limit(pairs)
        # FOR UPDATE is only meaningful within an explicit transaction.
        if for_update and _ACTIVE_TX.get() is None:
            raise DatabaseError("FOR UPDATE requires db.transaction().")
        sql = f"SELECT {cols} FROM public.{_quote(table)}{clause}{end}" + (" FOR UPDATE" if for_update else "")
        try:
            with self._using_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, args + end_args)
                    return [self._convert_row(table, r) for r in cur.fetchall()]
        except PsycopgError as exc:
            raise DatabaseError("Database query failed.") from exc

    def insert(self, table: str, payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            with self.transaction():
                return [item for row in payload for item in self.insert(table, row)]
        table = _clean_identifier(table)
        row = dict(payload)
        if table in UUID_TABLES and not row.get("id"):
            row["id"] = str(uuid4())
        if not row:
            raise DatabaseError("Cannot insert an empty record.")
        keys = [_clean_identifier(k) for k in row]
        sql = f"INSERT INTO public.{_quote(table)} (" + ",".join(_quote(k) for k in keys) + ") VALUES (" + ",".join(["%s"]*len(keys)) + ") RETURNING *"
        try:
            with self._using_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, [_as_db_value(row[k]) for k in keys])
                    result = cur.fetchone()
                    return [self._convert_row(table, result)] if result else []
        except PsycopgError as exc:
            raise DatabaseError("Cannot insert record; check constraints and existing IDs.") from exc

    def update(self, table: str, filters: dict[str,str], payload: dict[str, Any]) -> list[dict[str, Any]]:
        table = _clean_identifier(table)
        if not payload:
            return []
        if not filters:
            raise DatabaseError("Refusing to update without filters.")
        cols = [_clean_identifier(k) for k in payload]
        clause, args = self._where(list(filters.items()))
        if not clause:
            raise DatabaseError("Refusing to update without filters.")
        query = f"UPDATE public.{_quote(table)} SET " + ",".join(f"{_quote(k)}=%s" for k in cols) + clause + " RETURNING *"
        try:
            with self._using_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, [_as_db_value(payload[k]) for k in cols] + args)
                    return [self._convert_row(table,r) for r in cur.fetchall()]
        except PsycopgError as exc:
            raise DatabaseError("Cannot update record; check constraints.") from exc

    def delete(self, table: str, filters: dict[str,str]) -> list[dict[str, Any]]:
        table = _clean_identifier(table)
        clause, args = self._where(list(filters.items()))
        if not clause:
            raise DatabaseError("Refusing to delete without filters.")
        try:
            with self._using_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"DELETE FROM public.{_quote(table)}{clause} RETURNING *", args)
                    return [self._convert_row(table,r) for r in cur.fetchall()]
        except PsycopgError as exc:
            raise DatabaseError("Cannot delete record; check related records.") from exc

    def upsert(self, table: str, payload: dict[str,Any] | list[dict[str,Any]], on_conflict: str | None=None) -> list[dict[str,Any]]:
        if isinstance(payload,list):
            with self.transaction():
                return [item for row in payload for item in self.upsert(table,row,on_conflict)]
        table = _clean_identifier(table)
        row = dict(payload)
        if table in UUID_TABLES and not row.get("id"):
            row["id"] = str(uuid4())
        keys = [_clean_identifier(k) for k in row]
        conflicts = [_clean_identifier(c.strip()) for c in (on_conflict or "id").split(",") if c.strip()]
        updates = [k for k in keys if k not in conflicts]
        change = "DO UPDATE SET " + ",".join(f"{_quote(k)}=EXCLUDED.{_quote(k)}" for k in updates) if updates else "DO NOTHING"
        sql = (f"INSERT INTO public.{_quote(table)} (" + ",".join(_quote(k) for k in keys) + ") VALUES (" + ",".join(["%s"]*len(keys)) + f") ON CONFLICT ({','.join(_quote(c) for c in conflicts)}) {change} RETURNING *")
        try:
            with self._using_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, [_as_db_value(row[k]) for k in keys])
                    result = cur.fetchone()
                    return [self._convert_row(table,result)] if result else self.select(table,{"select":"*",**{k:f"eq.{row[k]}" for k in conflicts}})
        except PsycopgError as exc:
            raise DatabaseError("Cannot upsert record; check constraints.") from exc

    # ---------- Supabase Storage adapter ----------

    def upload(self, bucket: str, path: str, data: bytes, content_type: str, upsert: bool = True) -> str:
        return storage.upload(bucket, path, data, content_type, upsert=upsert)

    def public_storage_url(self, bucket: str, path: str) -> str:
        return storage.public_url(bucket, path)

    def signed_storage_url(self, bucket: str, path: str, expires: int = 3600) -> str:
        return storage.signed_url(bucket, path, expires)

    def validate_storage_signature(self, bucket: str, path: str, exp: int, sig: str):
        raise DatabaseError("The old local-file signature scheme was retired. Use Supabase Storage signed URLs.")


db = SupabasePostgresGateway()
