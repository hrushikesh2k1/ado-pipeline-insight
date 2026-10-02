import requests

from core.ado_client import AzureDevOpsClient


def test_flatten_timeline_derives_stage_job_and_task_names():
    build = {"id": 42, "result": "failed", "queueTime": "2026-08-01T10:00:00Z", "sourceBranch": "refs/heads/main", "sourceVersion": "abc123", "requestedFor": {"displayName": "Build User"}, "definition": {"id": 7, "name": "backend-ci"}}
    timeline = {"records": [
        {"id": "stage", "type": "Stage", "name": "Build", "duration": 600000, "result": "succeeded"},
        {"id": "job", "parentId": "stage", "type": "Job", "name": "Linux", "duration": 500000, "result": "succeeded"},
        {"id": "task", "parentId": "job", "type": "Task", "name": "npm install", "duration": 240000, "result": "failed", "attempt": 2, "log": {"id": 9}},
    ]}
    metrics = AzureDevOpsClient("example", "test").flatten_timeline(build, timeline)
    task = next(metric for metric in metrics if metric.level == "task")
    assert (task.stage_name, task.job_name, task.task_name, task.retry_count, task.log_id) == ("Build", "Linux", "npm install", 1, 9)
    assert (task.source_branch, task.source_version, task.requested_by, task.run_result) == ("refs/heads/main", "abc123", "Build User", "failed")

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


class _FakeResponse:
    def __init__(self, value, token=None):
        self._value = value
        self.headers = {"x-ms-continuationtoken": token} if token else {}
        self.status_code = 200
        self.url = "https://dev.azure.com/example/project/_apis/build/builds"
        self.text = "{}"

    def raise_for_status(self):
        return None

    def json(self):
        return {"value": self._value}


class _FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=30):
        self.calls.append(dict(params or {}))
        if len(self.calls) == 1:
            return _FakeResponse([{"id": 3}, {"id": 2}], "next-token")
        return _FakeResponse([{"id": 1}])


def test_list_builds_follows_continuation_token():
    session = _FakeSession()
    client = AzureDevOpsClient("example", "test", session=session)
    builds = client.list_builds("project", pipeline_id=7, top=2, max_builds=5000)
    assert [b["id"] for b in builds] == [3, 2, 1]
    assert session.calls[0]["$top"] == 2
    assert session.calls[1]["continuationToken"] == "next-token"


def test_flatten_timeline_preserves_build_number():
    build = {
        "id": 44,
        "buildNumber": "20260920.1",
        "definition": {"id": 7, "name": "backend-ci"},
    }
    timeline = {"records": [{"id": "stage", "type": "Stage", "name": "Build"}]}
    metrics = AzureDevOpsClient("example", "test").flatten_timeline(build, timeline)
    assert metrics[0].build_number == "20260920.1"


class _StrictBatchSession:
    """Behaves like Azure DevOps: workitemsbatch answers 400 when `fields` and `$expand` are sent together."""

    def __init__(self):
        self.headers = {}
        self.payloads = []

    def post(self, url, json=None, params=None, timeout=30):
        self.payloads.append(json)
        if "fields" in json and "$expand" in json:
            raise requests.HTTPError("400 Client Error: Bad Request for url: workitemsbatch")
        return _FakeResponse([{"id": i, "fields": {}, "relations": []} for i in json["ids"]])


def test_work_items_batch_never_combines_fields_and_expand():
    session = _StrictBatchSession()
    client = AzureDevOpsClient("example", "test", session=session)

    with_relations = client.get_work_items_batch("project", [1, 2])
    assert [w["id"] for w in with_relations] == [1, 2]
    assert session.payloads[-1].get("$expand") == "relations" and "fields" not in session.payloads[-1]

    only_fields = client.get_work_items_batch("project", [3], fields=["System.Id", "System.Title"])
    assert [w["id"] for w in only_fields] == [3]
    assert session.payloads[-1]["fields"] == ["System.Id", "System.Title"] and "$expand" not in session.payloads[-1]
