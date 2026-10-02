from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.db import fetch_all, fetch_one, execute_commit
from app.schemas.connection import (
    ReleaseBranchCandidate,
    ReleaseDefinitionCreate,
    ReleaseDefinition,
    ReleaseScorecardHistoryItem,
)

logger = logging.getLogger(__name__)

# Fallback store for test mocking or when database is not configured
_FALLBACK_RELEASES: dict[str, dict[str, Any]] = {}
_FALLBACK_HISTORY: list[dict[str, Any]] = []


def _ensure_tables_exist() -> None:
    """Ensure dbo.release_definitions and dbo.release_scorecard_history exist in SQL Server,
    with columns for repository_id, repository_name, and optional pipeline_id.
    """
    sql = """
    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'release_definitions' AND schema_id = SCHEMA_ID('dbo'))
    BEGIN
        CREATE TABLE dbo.release_definitions (
            release_id NVARCHAR(64) PRIMARY KEY,
            name NVARCHAR(256) NOT NULL,
            organization_name NVARCHAR(256) NOT NULL,
            project_name NVARCHAR(256) NOT NULL,
            pipeline_id INT NULL,
            repository_id NVARCHAR(256) NULL,
            repository_name NVARCHAR(256) NULL,
            target_branch NVARCHAR(512) NOT NULL,
            scope_feature_title NVARCHAR(512) NULL,
            target_ship_date NVARCHAR(32) NULL,
            created_by NVARCHAR(256) NULL,
            created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
        );
    END;
    ELSE
    BEGIN
        IF COL_LENGTH('dbo.release_definitions', 'repository_id') IS NULL
            ALTER TABLE dbo.release_definitions ADD repository_id NVARCHAR(256) NULL;
        IF COL_LENGTH('dbo.release_definitions', 'repository_name') IS NULL
            ALTER TABLE dbo.release_definitions ADD repository_name NVARCHAR(256) NULL;
        IF COL_LENGTH('dbo.release_definitions', 'pipeline_id') IS NOT NULL
            ALTER TABLE dbo.release_definitions ALTER COLUMN pipeline_id INT NULL;
    END;

    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'release_scorecard_history' AND schema_id = SCHEMA_ID('dbo'))
    BEGIN
        CREATE TABLE dbo.release_scorecard_history (
            history_id INT IDENTITY(1,1) PRIMARY KEY,
            release_id NVARCHAR(64) NOT NULL,
            computed_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
            overall_status NVARCHAR(32) NOT NULL,
            dimension_data NVARCHAR(MAX) NOT NULL
        );
    END;
    """
    try:
        execute_commit(sql)
    except Exception as e:
        logger.debug("Could not verify/create release tables in SQL (likely running with mocked DB): %s", e)


_tables_checked = False


def ensure_schema() -> None:
    global _tables_checked
    if not _tables_checked:
        _ensure_tables_exist()
        _tables_checked = True


class ReleaseRepository:
    def get_branch_candidates(
        self,
        organization: str,
        project: str,
        repository_id: str | None = None,
        pipeline_id: int | None = None,
        pat: str | None = None,
    ) -> list[ReleaseBranchCandidate]:
        """Query branches for a repository or observed branches in dbo.pipeline_runs.
        If repository_id is provided, queries Azure DevOps repository refs API to return
        the real repository branches, cross-referenced with pipeline run telemetry.
        If pipeline_id is provided, queries distinct source_branch values in dbo.pipeline_runs.
        Every observed branch is returned without any filtering or naming assumptions.
        """
        candidates_map: dict[str, ReleaseBranchCandidate] = {}

        # 1. If repository_id is provided, query Git refs directly from Azure DevOps
        if repository_id and organization:
            try:
                from core.ado_client import AzureDevOpsClient
                from core.config import get_ado_pat
                resolved_pat = pat
                if not resolved_pat:
                    try:
                        resolved_pat = get_ado_pat(organization)
                    except Exception:
                        resolved_pat = ""
                if resolved_pat:
                    client = AzureDevOpsClient(organization, resolved_pat)
                    raw_refs = client.list_repository_branches(project, repository_id)
                    for r in raw_refs:
                        name = r.get("name") or ""
                        if name.startswith("refs/heads/"):
                            candidates_map[name] = ReleaseBranchCandidate(
                                branch=name,
                                last_built=None,
                                run_count=0,
                                is_default=False,
                            )
            except Exception as e:
                logger.debug("Could not query git refs from ADO repository: %s", e)

        # 2. Cross-reference or query from dbo.pipeline_runs
        where_clauses = ["source_branch IS NOT NULL", "source_branch != ''"]
        params: list[Any] = []
        if pipeline_id:
            where_clauses.append("pipeline_id = ?")
            params.append(pipeline_id)

        where_sql = " AND ".join(where_clauses)
        query = f"""
            SELECT source_branch, MAX(start_time) as last_built, COUNT(*) as run_count
            FROM dbo.pipeline_runs
            WHERE {where_sql}
            GROUP BY source_branch
            ORDER BY MAX(start_time) DESC
        """
        try:
            rows = fetch_all(query, tuple(params))
            for r in rows:
                sb = str(r.get("source_branch") or "").strip()
                if not sb:
                    continue
                lb = r.get("last_built")
                lb_str = lb.isoformat() if hasattr(lb, "isoformat") else str(lb) if lb else None
                count = int(r.get("run_count") or 0)

                # Match with or without refs/heads/
                matched_key = sb if sb in candidates_map else (
                    f"refs/heads/{sb}" if f"refs/heads/{sb}" in candidates_map else (
                        sb.replace("refs/heads/", "") if sb.replace("refs/heads/", "") in candidates_map else None
                    )
                )

                if matched_key and matched_key in candidates_map:
                    candidates_map[matched_key].last_built = lb_str
                    candidates_map[matched_key].run_count = count
                else:
                    candidates_map[sb] = ReleaseBranchCandidate(
                        branch=sb,
                        last_built=lb_str,
                        run_count=count,
                        is_default=False,
                    )
        except Exception as e:
            logger.debug("Could not query branch candidates from DB: %s", e)

        if candidates_map:
            # Sort: branches with builds first by last_built desc, then alphabetic
            sorted_candidates = sorted(
                candidates_map.values(),
                key=lambda x: (x.last_built or "", x.run_count, x.branch),
                reverse=True,
            )
            return sorted_candidates

        # No observed branches found — return empty list.
        # TRUST PRINCIPLE: Never fabricate branch data that looks real.
        # The frontend handles this case by allowing manual branch input.
        return []

    def create_release(self, data: ReleaseDefinitionCreate, created_by: str | None = None) -> ReleaseDefinition:
        ensure_schema()
        release_id = f"rel-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        row = {
            "release_id": release_id,
            "name": data.name.strip(),
            "organization_name": data.organization_name.strip(),
            "project_name": data.project_name.strip(),
            "pipeline_id": data.pipeline_id,
            "repository_id": data.repository_id.strip() if data.repository_id else None,
            "repository_name": data.repository_name.strip() if data.repository_name else None,
            "target_branch": data.target_branch.strip(),
            "scope_feature_title": data.scope_feature_title.strip() if data.scope_feature_title else None,
            "target_ship_date": data.target_ship_date.strip() if data.target_ship_date else None,
            # NOTE: created_by is currently the request client IP address (no auth).
            # Once authentication is implemented, replace with the authenticated user identity.
            "created_by": created_by or "system",
            "created_at": now_iso,
        }

        sql = """
            INSERT INTO dbo.release_definitions (
                release_id, name, organization_name, project_name, pipeline_id,
                repository_id, repository_name, target_branch, scope_feature_title,
                target_ship_date, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            row["release_id"],
            row["name"],
            row["organization_name"],
            row["project_name"],
            row["pipeline_id"],
            row["repository_id"],
            row["repository_name"],
            row["target_branch"],
            row["scope_feature_title"],
            row["target_ship_date"],
            row["created_by"],
            row["created_at"],
        )

        try:
            execute_commit(sql, params)
        except Exception as e:
            logger.warning("DB insert for release '%s' failed, storing in fallback memory cache: %s", release_id, e)
            _FALLBACK_RELEASES[release_id] = row

        return ReleaseDefinition(**row)

    def list_releases(self, organization: str, project: str) -> list[ReleaseDefinition]:
        ensure_schema()
        sql = """
            SELECT release_id, name, organization_name, project_name, pipeline_id,
                   repository_id, repository_name, target_branch, scope_feature_title,
                   target_ship_date, created_by, created_at
            FROM dbo.release_definitions
            WHERE LOWER(organization_name) = LOWER(?) AND LOWER(project_name) = LOWER(?)
            ORDER BY created_at DESC
        """
        try:
            rows = fetch_all(sql, (organization.strip(), project.strip()))
            if rows:
                return [
                    ReleaseDefinition(
                        release_id=str(r["release_id"]),
                        name=str(r["name"]),
                        organization_name=str(r["organization_name"]),
                        project_name=str(r["project_name"]),
                        pipeline_id=int(r["pipeline_id"]) if r.get("pipeline_id") is not None else None,
                        repository_id=r.get("repository_id"),
                        repository_name=r.get("repository_name"),
                        target_branch=str(r["target_branch"]),
                        scope_feature_title=r.get("scope_feature_title"),
                        target_ship_date=r.get("target_ship_date"),
                        created_by=r.get("created_by"),
                        created_at=r["created_at"].isoformat() if hasattr(r.get("created_at"), "isoformat") else str(r.get("created_at") or ""),
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.debug("DB list_releases query failed, using fallback cache: %s", e)

        # Fallback memory search
        matches = [
            ReleaseDefinition(**r)
            for r in _FALLBACK_RELEASES.values()
            if r["organization_name"].lower() == organization.lower()
            and r["project_name"].lower() == project.lower()
        ]
        return sorted(matches, key=lambda x: x.created_at, reverse=True)

    def get_release(self, release_id: str) -> ReleaseDefinition | None:
        ensure_schema()
        sql = """
            SELECT release_id, name, organization_name, project_name, pipeline_id,
                   repository_id, repository_name, target_branch, scope_feature_title,
                   target_ship_date, created_by, created_at
            FROM dbo.release_definitions
            WHERE release_id = ?
        """
        try:
            row = fetch_one(sql, (release_id.strip(),))
            if row:
                return ReleaseDefinition(
                    release_id=str(row["release_id"]),
                    name=str(row["name"]),
                    organization_name=str(row["organization_name"]),
                    project_name=str(row["project_name"]),
                    pipeline_id=int(row["pipeline_id"]) if row.get("pipeline_id") is not None else None,
                    repository_id=row.get("repository_id"),
                    repository_name=row.get("repository_name"),
                    target_branch=str(row["target_branch"]),
                    scope_feature_title=row.get("scope_feature_title"),
                    target_ship_date=row.get("target_ship_date"),
                    created_by=row.get("created_by"),
                    created_at=row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else str(row.get("created_at") or ""),
                )
        except Exception as e:
            logger.debug("DB get_release query failed, checking fallback cache: %s", e)

        if release_id in _FALLBACK_RELEASES:
            return ReleaseDefinition(**_FALLBACK_RELEASES[release_id])
        return None

    def delete_release(self, release_id: str) -> bool:
        ensure_schema()
        del_def = "DELETE FROM dbo.release_definitions WHERE release_id = ?"
        del_hist = "DELETE FROM dbo.release_scorecard_history WHERE release_id = ?"
        deleted = False
        try:
            execute_commit(del_hist, (release_id.strip(),))
            execute_commit(del_def, (release_id.strip(),))
            deleted = True
        except Exception as e:
            logger.error("DB delete_release failed for '%s': %s", release_id, e)

        if release_id in _FALLBACK_RELEASES:
            del _FALLBACK_RELEASES[release_id]
            deleted = True

        return deleted

    def record_scorecard_history(
        self,
        release_id: str,
        overall_status: str,
        dimension_statuses: dict[str, str],
        dimension_data: dict[str, Any],
    ) -> None:
        ensure_schema()
        now_dt = datetime.now(timezone.utc)
        payload = json.dumps({
            "dimension_statuses": dimension_statuses,
            "dimension_data": dimension_data,
        })
        sql = """
            INSERT INTO dbo.release_scorecard_history (release_id, computed_at, overall_status, dimension_data)
            VALUES (?, ?, ?, ?)
        """
        try:
            execute_commit(sql, (release_id, now_dt, overall_status, payload))
        except Exception as e:
            logger.warning("DB record_scorecard_history failed for release '%s': %s", release_id, e)
            _FALLBACK_HISTORY.append({
                "history_id": len(_FALLBACK_HISTORY) + 1,
                "release_id": release_id,
                "computed_at": now_dt.isoformat(),
                "overall_status": overall_status,
                "dimension_statuses": dimension_statuses,
            })

    def get_scorecard_history(self, release_id: str, limit: int = 20) -> list[ReleaseScorecardHistoryItem]:
        ensure_schema()
        sql = """
            SELECT TOP (?) history_id, release_id, computed_at, overall_status, dimension_data
            FROM dbo.release_scorecard_history
            WHERE release_id = ?
            ORDER BY computed_at DESC
        """
        items: list[ReleaseScorecardHistoryItem] = []
        try:
            rows = fetch_all(sql, (limit, release_id))
            for r in rows:
                statuses = {}
                try:
                    parsed = json.loads(r.get("dimension_data") or "{}")
                    statuses = parsed.get("dimension_statuses", {})
                except Exception:
                    pass
                ca = r.get("computed_at")
                items.append(ReleaseScorecardHistoryItem(
                    history_id=int(r.get("history_id") or 0),
                    release_id=str(r["release_id"]),
                    computed_at=ca.isoformat() if hasattr(ca, "isoformat") else str(ca or ""),
                    overall_status=str(r["overall_status"]),
                    dimension_statuses=statuses,
                ))
        except Exception as e:
            logger.debug("DB get_scorecard_history failed: %s", e)

        if items:
            return items

        # Fallback memory
        return [
            ReleaseScorecardHistoryItem(**h)
            for h in reversed(_FALLBACK_HISTORY)
            if h["release_id"] == release_id
        ][:limit]
