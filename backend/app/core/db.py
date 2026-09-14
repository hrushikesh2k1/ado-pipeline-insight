from contextlib import contextmanager
from typing import Any, Iterator
import pyodbc
from backend.app.core.config import get_settings


def connection_variants(connection_string: str) -> list[str]:
    variants: list[str] = []
    if "ODBC Driver 18 for SQL Server" in connection_string:
        variants.append(connection_string.replace("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"))
    elif "ODBC Driver 17 for SQL Server" in connection_string:
        variants.append(connection_string.replace("ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"))
    return variants

@contextmanager
def get_connection() -> Iterator[pyodbc.Connection]:
    configured = get_settings().sql_connection_string
    if not configured:
        raise RuntimeError("SQL_CONNECTION_STRING is not configured.")
    errors: list[Exception] = []
    for value in [configured, *connection_variants(configured)]:
        try:
            conn = pyodbc.connect(value)
            try:
                yield conn
            finally:
                conn.close()
            return
        except Exception as exc:
            errors.append(exc)
    detail = str(errors[-1]) if errors else "unknown SQL connection error"
    if errors:
        raise RuntimeError(f"Unable to connect to Azure SQL. {detail}") from errors[-1]
    raise RuntimeError(f"Unable to connect to Azure SQL. {detail}")


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, *params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = fetch_all(query, params)
    return rows[0] if rows else None
