"""Safe local smoke test for Azure DevOps connectivity and timeline shape."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from core.ado_client import AzureDevOpsClient


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    organization = os.environ["ADO_ORGANIZATION"]
    project = os.environ["ADO_PROJECT"]
    pat = os.environ["ADO_PAT"]
    pipeline_id = int(os.environ["ADO_PIPELINE_ID"]) if os.environ.get("ADO_PIPELINE_ID") else None

    client = AzureDevOpsClient(organization, pat)
    builds = client.list_builds(project, pipeline_id=pipeline_id, top=1)
    if not builds:
        print("No Azure DevOps builds found for the configured scope.")
        return

    build = builds[0]
    build_id = int(build["id"])
    timeline = client.get_timeline(project, build_id)
    metrics = client.flatten_timeline(build, timeline)
    levels = {level: sum(1 for m in metrics if m.level == level) for level in ("stage", "job", "task")}
    print(f"Connected to Azure DevOps organization={organization}, project={project}")
    print(f"Latest build: #{build_id} | {(build.get('definition') or {}).get('name', 'unknown')} | status={build.get('status')} | result={build.get('result')}")
    print(f"Timeline records: {len(timeline.get('records', []))} | normalized stage/job/task: {levels}")
    for metric in metrics[:12]:
        name = metric.task_name or metric.job_name or metric.stage_name or "unnamed"
        print(f"  {metric.level:5} | {metric.duration_seconds!s:>10} sec | {metric.result or 'n/a':9} | {name}")


if __name__ == "__main__":
    main()
