from core.ado_client import AzureDevOpsClient


def test_flatten_timeline_derives_stage_job_and_task_names():
    build = {"id": 42, "queueTime": "2026-08-01T10:00:00Z", "sourceBranch": "refs/heads/main", "sourceVersion": "abc123", "requestedFor": {"displayName": "Build User"}, "definition": {"id": 7, "name": "backend-ci"}}
    timeline = {"records": [
        {"id": "stage", "type": "Stage", "name": "Build", "duration": 600000, "result": "succeeded"},
        {"id": "job", "parentId": "stage", "type": "Job", "name": "Linux", "duration": 500000, "result": "succeeded"},
        {"id": "task", "parentId": "job", "type": "Task", "name": "npm install", "duration": 240000, "result": "failed", "attempt": 2, "log": {"id": 9}},
    ]}
    metrics = AzureDevOpsClient("example", "test").flatten_timeline(build, timeline)
    task = next(metric for metric in metrics if metric.level == "task")
    assert (task.stage_name, task.job_name, task.task_name, task.retry_count, task.log_id) == ("Build", "Linux", "npm install", 1, 9)
    assert (task.source_branch, task.source_version, task.requested_by) == ("refs/heads/main", "abc123", "Build User")

def test_flatten_timeline_carries_build_run_boundaries():
    build = {
        "id": 36,
        "startTime": "2026-09-05T06:08:09.5066006Z",
        "finishTime": "2026-09-05T06:08:27.8545989Z",
        "definition": {"id": 1, "name": "pipeline-1"},
    }
    timeline = {
        "records": [
            {"id": "stage-36", "type": "Stage", "name": "__default", "startTime": "2026-09-05T06:08:09.5066006Z", "finishTime": "2026-09-05T06:08:14.469935Z", "result": "succeeded"}
        ]
    }
    metrics = AzureDevOpsClient("example", "test").flatten_timeline(build, timeline)
    assert len(metrics) == 1
    assert metrics[0].run_start_time.isoformat() == "2026-09-05T06:08:09.506600+00:00"
    assert metrics[0].run_finish_time.isoformat() == "2026-09-05T06:08:27.854598+00:00"


def test_flatten_timeline_ignores_orphan_internal_task_records():
    build = {
        "id": 43,
        "queueTime": "2026-08-01T10:00:00Z",
        "definition": {"id": 7, "name": "backend-ci"},
    }
    timeline = {"records": [
        {"id": "stage", "type": "Stage", "name": "__default"},
        {"id": "job", "parentId": "stage", "type": "Job", "name": "Job"},
        {"id": "task", "parentId": "job", "type": "Task", "name": "Run script"},
        {"id": "internal", "parentId": "stage", "type": "Task", "name": "Job", "duration": 4676},
    ]}
    metrics = AzureDevOpsClient("example", "test").flatten_timeline(build, timeline)
    assert [(m.level, m.stage_name, m.job_name, m.task_name) for m in metrics] == [
        ("stage", "__default", None, None),
        ("job", "__default", "Job", None),
        ("task", "__default", "Job", "Run script"),
    ]
