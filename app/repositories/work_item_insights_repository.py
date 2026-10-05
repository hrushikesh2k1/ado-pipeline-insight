"""Saved work item insights: one row per scope (organization, project, team and tag).

A row holds the area list, every work item of the scope with its area, and the uploaded alert inventory, so the page
opens at once and the AI is only asked about items that are new or have changed. Without SQL_CONNECTION_STRING (local
development) the same data is kept in memory. When SQL is configured, a database failure is raised, not hidden.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from typing import Any

from app.core.config import get_settings
from app.core.db import execute_commit, fetch_one, get_connection

_TABLE = "dbo.wi_insight_scopes"
_JSON_FIELDS = {"areas": "areas_json", "items": "items_json", "inventory": "inventory_json", "notes": "notes_json"}
_PLAIN_FIELDS = ("organization", "project", "team", "tag", "months", "areas_version", "area_source", "refreshed_at")
_DEFAULTS: dict[str, Any] = {
    "organization": "", "project": "", "team": "", "tag": "", "months": 6, "areas": [], "areas_version": 0,
    "area_source": None, "items": [], "inventory": None, "notes": [], "refreshed_at": None,
}

_memory: dict[str, dict[str, Any]] = {}
_memory_lock = threading.Lock()
_table_ready = False


def scope_key(organization: str, project: str, team: str = "", tag: str = "") -> str:
    """A fixed-length key for the scope; case does not matter."""
    raw = "\x1f".join(part.strip().lower() for part in (organization, project, team, tag))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sql_enabled() -> bool:
    return bool(get_settings().sql_connection_string)


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    execute_commit(f"""
    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'wi_insight_scopes' AND schema_id = SCHEMA_ID('dbo'))
    BEGIN
        CREATE TABLE {_TABLE} (
            scope_key NVARCHAR(64) NOT NULL PRIMARY KEY,
            organization NVARCHAR(256) NOT NULL DEFAULT '',
            project NVARCHAR(256) NOT NULL DEFAULT '',
            team NVARCHAR(256) NOT NULL DEFAULT '',
            tag NVARCHAR(256) NOT NULL DEFAULT '',
            months INT NOT NULL DEFAULT 6,
            areas_json NVARCHAR(MAX) NULL,
            areas_version INT NOT NULL DEFAULT 0,
            area_source NVARCHAR(16) NULL,
            items_json NVARCHAR(MAX) NULL,
            inventory_json NVARCHAR(MAX) NULL,
            notes_json NVARCHAR(MAX) NULL,
            refreshed_at NVARCHAR(32) NULL,
            updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
        );
    END;
    """)
    _table_ready = True


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(_DEFAULTS)
    for name in _PLAIN_FIELDS:
        if row.get(name) is not None:
            record[name] = row[name]
    for name, column in _JSON_FIELDS.items():
        if row.get(column):
            record[name] = json.loads(row[column])
    return record


def get(key: str) -> dict[str, Any] | None:
    """The saved record for a scope, or None when nothing was saved yet."""
    if not _sql_enabled():
        with _memory_lock:
            return copy.deepcopy(_memory[key]) if key in _memory else None
    _ensure_table()
    row = fetch_one(f"SELECT * FROM {_TABLE} WHERE scope_key = ?", (key,))
    return _decode(row) if row else None


def save(key: str, **fields: Any) -> None:
    """Create or update the record; only the fields given are changed."""
    unknown = set(fields) - set(_DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown field(s): {', '.join(sorted(unknown))}")
    if not _sql_enabled():
        with _memory_lock:
            record = _memory.setdefault(key, copy.deepcopy(_DEFAULTS))
            record.update(copy.deepcopy(fields))
        return
    _ensure_table()
    values: dict[str, Any] = {}
    for name, value in fields.items():
        if name in _JSON_FIELDS:
            values[_JSON_FIELDS[name]] = None if value is None else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            values[name] = value
    if not values:
        return
    assignments = ", ".join(f"{column} = ?" for column in values)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE {_TABLE} SET {assignments}, updated_at = SYSUTCDATETIME() WHERE scope_key = ?", *values.values(), key)
        if cursor.rowcount == 0:
            columns = ", ".join(["scope_key", *values])
            marks = ", ".join("?" for _ in range(len(values) + 1))
            cursor.execute(f"INSERT INTO {_TABLE} ({columns}) VALUES ({marks})", key, *values.values())
        conn.commit()


def clear_memory() -> None:
    """For tests."""
    with _memory_lock:
        _memory.clear()
