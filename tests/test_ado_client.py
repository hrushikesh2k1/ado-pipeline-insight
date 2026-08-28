from core.ado_client import AzureDevOpsClient


def test_flatten_timeline_derives_stage_job_and_task_names():
    build = {"id": 42, "queueTime": "2026-08-01T10:00:00Z", "definition": {"id": 7, "name": "backend-ci"}}
    timeline = {"records": [
        {"id": "stage", "type": "Stage", "name": "Build", "duration": 600000, "result": "succeeded"},
        {"id": "job", "parentId": "stage", "type": "Job", "name": "Linux", "duration": 500000, "result": "succeeded"},
        {"id": "task", "parentId": "job", "type": "Task", "name": "npm install", "duration": 240000, "result": "failed", "attempt": 2, "log": {"id": 9}},
    ]}
    metrics = AzureDevOpsClient("example", "test").flatten_timeline(build, timeline)
    task = next(metric for metric in metrics if metric.level == "task")
    assert (task.stage_name, task.job_name, task.task_name, task.retry_count, task.log_id) == ("Build", "Linux", "npm install", 1, 9)