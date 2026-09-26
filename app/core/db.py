from contextlib import contextmanager
from typing import Any, Iterator
import pyodbc
from app.core.config import get_settings


def normalize_connection_string(connection_string: str) -> str:
    normalized = connection_string
    normalized = normalized.replace("Encrypt=True", "Encrypt=yes").replace("Encrypt=False", "Encrypt=no")
    normalized = normalized.replace("TrustServerCertificate=False", "TrustServerCertificate=no").replace("TrustServerCertificate=True", "TrustServerCertificate=yes")
    normalized = normalized.replace("User ID=", "UID=").replace("user id=", "UID=")
    normalized = normalized.replace("Password=", "PWD=").replace("password=", "PWD=")
    normalized = normalized.replace("Initial Catalog=", "Database=").replace("initial catalog=", "Database=")
    return normalized


def connection_variants(connection_string: str) -> list[str]:
    variants: list[str] = []
    normalized = normalize_connection_string(connection_string)
    candidates = [connection_string, normalized] if normalized != connection_string else [connection_string]
    for s in candidates:
        if "ODBC Driver 18 for SQL Server" in s:
            variants.append(s.replace("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"))
        elif "ODBC Driver 17 for SQL Server" in s:
            variants.append(s.replace("ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"))
    seen: set[str] = set()
    unique: list[str] = []
    for item in [normalized, *variants]:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


@contextmanager
def get_connection() -> Iterator[pyodbc.Connection]:
    configured = get_settings().sql_connection_string
    if not configured:
        raise RuntimeError("SQL_CONNECTION_STRING is not configured.")
    errors: list[Exception] = []
    trial_strings = [configured, *connection_variants(configured)]
    seen: set[str] = set()
    unique_trials: list[str] = []
    for val in trial_strings:
        if val not in seen:
            seen.add(val)
            unique_trials.append(val)
    normalized = normalize_connection_string(configured)
    if normalized in unique_trials and unique_trials[0] != normalized:
        unique_trials.remove(normalized)
        unique_trials.insert(0, normalized)

    conn = None
    for value in unique_trials:
        try:
            conn = pyodbc.connect(value)
            break
        except Exception as exc:
            errors.append(exc)

    if conn is None:
        detail = str(errors[-1]) if errors else "unknown SQL connection error"
        if errors:
            raise RuntimeError(f"Unable to connect to Azure SQL. {detail}") from errors[-1]
        raise RuntimeError(f"Unable to connect to Azure SQL. {detail}")

    try:
        yield conn
    finally:
        conn.close()


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, *params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = fetch_all(query, params)
    return rows[0] if rows else None
