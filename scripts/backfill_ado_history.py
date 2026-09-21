"""Backfill completed Azure DevOps builds into Azure SQL.

Required environment variables:
  SQL_CONNECTION_STRING
  ADO_ORGANIZATION
  ADO_PROJECT
  ADO_PAT
Optional:
  ADO_PIPELINE_ID
  ADO_DAYS (default 90)

This is safe to rerun because ingestion uses run_id + timeline record_id upserts.
"""
from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from core.ado_client import AzureDevOpsClient
from core.db import AlertRepository


def main() -> None:
    # Local development: load the project .env without hardcoding any tenant/project values.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    organization = os.environ["ADO_ORGANIZATION"]
    project = os.environ["ADO_PROJECT"]
    pat = os.environ["ADO_PAT"]
    pipeline_id = int(os.environ["ADO_PIPELINE_ID"]) if os.environ.get("ADO_PIPELINE_ID") else None
    days = int(os.environ.get("ADO_DAYS", "90"))
    client = AzureDevOpsClient(organization, pat)
    repository = AlertRepository(os.environ["SQL_CONNECTION_STRING"])
    builds = client.list_builds(project, pipeline_id=pipeline_id, min_time=datetime.now(timezone.utc) - timedelta(days=days), top=200)
    if pipeline_id is None:
        pipeline_names = sorted({(b.get("definition") or {}).get("name", "unknown") for b in builds})
        print(f"Discovered {len(pipeline_names)} pipeline(s): {', '.join(pipeline_names[:20])}")
    completed = [b for b in builds if b.get("finishTime") and b.get("status") == "completed"]
    print(f"Found {len(completed)} completed Azure DevOps builds. Starting backfill...")
    total = 0
    for index, build in enumerate(completed, 1):
        build_id = int(build["id"])
        timeline = client.get_timeline(project, build_id)
        metrics = client.flatten_timeline(build, timeline)
        if not metrics:
            print(f"[{index}/{len(completed)}] run #{build_id}: no timeline records")
            continue
        repository.upsert_metrics(metrics)
        total += 1
        print(f"[{index}/{len(completed)}] run #{build_id}: {len(metrics)} timeline records")
    print(f"Backfill complete. Upserted {total} completed builds.")


if __name__ == "__main__":
    main()
