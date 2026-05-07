from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Iterable, Mapping

import config
import psycopg2
from psycopg2.extras import Json


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgreSQLRepositoryError(RuntimeError):
    pass


class PostgreSQLRepository:
    def __init__(self):
        self.connection: Any | None = None

    def __enter__(self) -> "PostgreSQLRepository":
        self.connect()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_args: Any) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()

    @contextmanager
    def transaction(self):
        self.connect()
        try:
            yield self
            self.commit()
        except Exception:
            self.rollback()
            raise

    def connect(self) -> Any:
        if self.connection is not None:
            return self.connection

        if config.POSTGRES_URL:
            self.connection = psycopg2.connect(config.POSTGRES_URL)
        else:
            self.connection = psycopg2.connect(**self._connection_kwargs())

        self.connection.autocommit = False
        return self.connection

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def commit(self) -> None:
        if self.connection is not None:
            self.connection.commit()

    def rollback(self) -> None:
        if self.connection is not None:
            self.connection.rollback()

    def fetch_all(
        self,
        query: str,
        params: Iterable[Any] | Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect().cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return self._rows_to_dicts(cursor, rows)

    def fetch_one(
        self,
        query: str,
        params: Iterable[Any] | Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self.connect().cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
            rows = self._rows_to_dicts(cursor, [row] if row else [])
            return rows[0] if rows else None

    def execute(
        self,
        query: str,
        params: Iterable[Any] | Mapping[str, Any] | None = None,
    ) -> int:
        with self.connect().cursor() as cursor:
            cursor.execute(query, params)
            return cursor.rowcount

    def create(
        self,
        table: str,
        data: Mapping[str, Any] | None = None,
        *,
        returning: Iterable[str] | str | None = None,
    ) -> list[dict[str, Any]] | int:
        table_name = self._quote_identifier(table)
        data = data or {}

        if data:
            columns = [self._quote_identifier(column) for column in data]
            placeholders = ", ".join(["%s"] * len(data))
            query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
            params = tuple(self._adapt_value(value) for value in data.values())
        else:
            query = f"INSERT INTO {table_name} DEFAULT VALUES"
            params = None

        if returning:
            query += f" RETURNING {self._columns(returning)}"
            return self.fetch_all(query, params)

        return self.execute(query, params)

    def read(
        self,
        table: str,
        *,
        columns: Iterable[str] | str = "*",
        where: str | None = None,
        params: Iterable[Any] | Mapping[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = 100,
    ) -> list[dict[str, Any]]:
        query = f"SELECT {self._columns(columns)} FROM {self._quote_identifier(table)}"

        if where:
            query += f" WHERE {where}"
        if order_by:
            query += f" ORDER BY {self._quote_identifier(order_by)}"
        if limit is not None:
            if isinstance(params, Mapping):
                query += " LIMIT %(limit)s"
                params = {**params, "limit": limit}
            else:
                query += " LIMIT %s"
                params = tuple(params or ()) + (limit,)

        return self.fetch_all(query, params)

    def update(
        self,
        table: str,
        data: Mapping[str, Any],
        where: str,
        params: Iterable[Any] | None = None,
        *,
        returning: Iterable[str] | str | None = None,
    ) -> list[dict[str, Any]] | int:
        if not data:
            raise PostgreSQLRepositoryError("update data must not be empty")
        if not where:
            raise PostgreSQLRepositoryError("update requires a where clause")

        assignments = ", ".join(f"{self._quote_identifier(column)} = %s" for column in data)
        query = f"UPDATE {self._quote_identifier(table)} SET {assignments} WHERE {where}"
        query_params = tuple(self._adapt_value(value) for value in data.values()) + tuple(params or ())

        if returning:
            query += f" RETURNING {self._columns(returning)}"
            return self.fetch_all(query, query_params)

        return self.execute(query, query_params)

    def delete(
        self,
        table: str,
        where: str,
        params: Iterable[Any] | None = None,
        *,
        returning: Iterable[str] | str | None = None,
    ) -> list[dict[str, Any]] | int:
        if not where:
            raise PostgreSQLRepositoryError("delete requires a where clause")

        query = f"DELETE FROM {self._quote_identifier(table)} WHERE {where}"

        if returning:
            query += f" RETURNING {self._columns(returning)}"
            return self.fetch_all(query, params)

        return self.execute(query, params)

    def _connection_kwargs(self) -> dict[str, Any]:
        kwargs = {
            "host": config.POSTGRES_HOST,
            "port": config.POSTGRES_PORT,
            "dbname": config.POSTGRES_DB,
            "user": config.POSTGRES_USER,
            "password": config.POSTGRES_PASSWORD,
        }
        return {key: value for key, value in kwargs.items() if value is not None}

    @staticmethod
    def _rows_to_dicts(cursor: Any, rows: Iterable[Any]) -> list[dict[str, Any]]:
        columns = [column[0] for column in cursor.description or []]
        return [dict(zip(columns, row, strict=False)) for row in rows]

    @classmethod
    def _columns(cls, columns: Iterable[str] | str) -> str:
        if columns == "*":
            return "*"
        if isinstance(columns, str):
            return cls._quote_identifier(columns)
        return ", ".join(cls._quote_identifier(column) for column in columns)

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        if not _IDENTIFIER_PATTERN.match(identifier):
            raise PostgreSQLRepositoryError(f"Invalid SQL identifier: {identifier}")
        return f'"{identifier}"'

    @staticmethod
    def _adapt_value(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return Json(value)
        return value
