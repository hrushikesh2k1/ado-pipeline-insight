from datetime import datetime
from app.services.innersource_service import (
    get_quarter_for_month,
    extract_story_points,
    extract_closed_date,
    calculate_leaderboard,
    fetch_innersource_leaderboard,
    get_mock_innersource_leaderboard,
)


def test_get_quarter_for_month():
    assert get_quarter_for_month(1) == 1
    assert get_quarter_for_month(3) == 1
    assert get_quarter_for_month(4) == 2
    assert get_quarter_for_month(6) == 2
    assert get_quarter_for_month(7) == 3
    assert get_quarter_for_month(9) == 3
    assert get_quarter_for_month(10) == 4
    assert get_quarter_for_month(12) == 4


def test_extract_story_points():
    assert extract_story_points({"Microsoft.VSTS.Scheduling.StoryPoints": 8.0}) == 8.0
    assert extract_story_points({"Microsoft.VSTS.Scheduling.Effort": "13"}) == 13.0
    assert extract_story_points({"StoryPoints": 5}) == 5.0
    assert extract_story_points({"Microsoft.VSTS.Scheduling.Size": 3.5}) == 3.5
    assert extract_story_points({}) == 0.0
    assert extract_story_points({"Microsoft.VSTS.Scheduling.StoryPoints": "invalid"}) == 0.0


def test_extract_closed_date():
    dt = extract_closed_date({"Microsoft.VSTS.Common.ClosedDate": "2026-06-14T15:30:00Z"})
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 6
    assert dt.day == 14

    dt2 = extract_closed_date({"Microsoft.VSTS.Common.StateChangeDate": "2026-04-10T10:00:00Z"})
    assert dt2 is not None
    assert dt2.month == 4


def test_calculate_leaderboard():
    raw_items = [
        {
            "id": 101,
            "fields": {
                "System.Id": 101,
                "System.Title": "Add Azure EventHub Alert",
                "System.WorkItemType": "User Story",
                "System.State": "Closed",
                "System.AssignedTo": {"displayName": "SEBESTA Paul G", "uniqueName": "paul.sebesta@domain.com"},
                "Microsoft.VSTS.Scheduling.StoryPoints": 47.0,
                "Microsoft.VSTS.Common.ClosedDate": "2026-05-10T12:00:00Z",
            },
        },
        {
            "id": 102,
            "fields": {
                "System.Id": 102,
                "System.Title": "Earlier Q1 Item for Paul",
                "System.WorkItemType": "User Story",
                "System.State": "Closed",
                "System.AssignedTo": {"displayName": "SEBESTA Paul G", "uniqueName": "paul.sebesta@domain.com"},
                "Microsoft.VSTS.Scheduling.StoryPoints": 955.0,
                "Microsoft.VSTS.Common.ClosedDate": "2026-02-15T12:00:00Z",
            },
        },
        {
            "id": 103,
            "fields": {
                "System.Id": 103,
                "System.Title": "Optimize VM Memory alert",
                "System.WorkItemType": "User Story",
                "System.State": "Closed",
                "System.AssignedTo": {"displayName": "LEE James K", "uniqueName": "james.lee@domain.com"},
                "Microsoft.VSTS.Scheduling.StoryPoints": 113.0,
                "Microsoft.VSTS.Common.ClosedDate": "2026-06-01T12:00:00Z",
            },
        },
        {
            "id": 104,
            "fields": {
                "System.Id": 104,
                "System.Title": "Previous Year 2025 Story",
                "System.WorkItemType": "User Story",
                "System.State": "Closed",
                "System.AssignedTo": {"displayName": "LEE James K", "uniqueName": "james.lee@domain.com"},
                "Microsoft.VSTS.Scheduling.StoryPoints": 50.0,
                "Microsoft.VSTS.Common.ClosedDate": "2025-11-20T12:00:00Z",
            },
        },
    ]

    res = calculate_leaderboard(raw_items, year=2026, quarter=2, organization="test-org", project="test-proj")
    assert res["year"] == 2026
    assert res["quarter"] == 2
    assert res["stories_evaluated"] == 3  # 104 is 2025, so excluded

    # LEE James K has 113 in Q2, so should be Rank #1 for Q2
    assert res["leader"]["name"] == "LEE James K"
    assert res["leader"]["quarter_points"] == 113.0

    # SEBESTA Paul G has 47 in Q2, and 1002 total in 2026
    paul = next(p for p in res["leaderboard"] if "SEBESTA" in p["name"])
    assert paul["quarter_points"] == 47.0
    assert paul["year_total"] == 1002.0
    assert paul["q1_points"] == 955.0
    assert paul["q2_points"] == 47.0
    assert len(paul["stories"]) == 2


def test_mock_leaderboard():
    mock = get_mock_innersource_leaderboard(year=2026, quarter=2, organization="test-org", project="test-proj")
    assert mock["year"] == 2026
    assert mock["quarter"] == 2
    assert len(mock["leaderboard"]) >= 6
    names = [p["name"] for p in mock["leaderboard"]]
    assert "SEBESTAPaulG" in names
    assert "LEEJamesK" in names


def test_innersource_route(monkeypatch):
    import app.api.routes as routes

    monkeypatch.setattr(routes, "_resolve_pat", lambda org, pat=None: (_ for _ in ()).throw(RuntimeError("no token")))

    response = routes.get_innersource_leaderboard(organization="hex-org", project="cloud-proj", year=2026, quarter=2)
    data = response.model_dump()
    assert data["year"] == 2026
    assert data["quarter"] == 2
    assert "leaderboard" in data
    assert len(data["leaderboard"]) > 0
    first = data["leaderboard"][0]
    assert "name" in first
    assert "quarter_points" in first
    assert "year_total" in first


def test_parse_quarter_and_year_from_iteration():
    from app.services.innersource_service import parse_quarter_and_year_from_iteration

    y, q = parse_quarter_and_year_from_iteration("Cloud Technologies\\CloudOps\\2026\\26-09 (Sep Work)")
    assert y == 2026
    assert q == 3

    y, q = parse_quarter_and_year_from_iteration("Project\\2026\\Q1")
    assert y == 2026
    assert q == 1

    y, q = parse_quarter_and_year_from_iteration("Project\\2026\\26-04 (Apr Work)")
    assert y == 2026
    assert q == 2

    y, q = parse_quarter_and_year_from_iteration("Project\\2026\\26-11 (Nov Work)")
    assert y == 2026
    assert q == 4


def test_blob_storage_service(tmp_path, monkeypatch):
    from app.services.blob_storage_service import BlobStorageService

    service = BlobStorageService()
    service.local_cache_dir = tmp_path

    test_data = {"org": "test", "items": [1, 2, 3]}
    assert service.put_json("test_blob.json", test_data) is True
    loaded = service.get_json("test_blob.json")
    assert loaded == test_data


def test_fetch_innersource_leaderboard_writes_partitioned_blobs(monkeypatch):
    import app.services.innersource_service as service

    class FakeBlob:
        def __init__(self):
            self.data = {}

        def get_json(self, name):
            return self.data.get(name)

        def put_json(self, name, data):
            self.data[name] = data
            return True

    class FakeAdo:
        def query_wiql(self, project, wiql, top=None):
            return [101, 102]

        def get_work_items_batch(self, project, ids, fields=None):
            return [
                {
                    "id": 101,
                    "fields": {
                        "System.Id": 101,
                        "System.Title": "Q2 contribution",
                        "System.WorkItemType": "User Story",
                        "System.State": "Closed",
                        "System.AssignedTo": {"displayName": "Ava Stone", "uniqueName": "ava@example.test"},
                        "Microsoft.VSTS.Scheduling.StoryPoints": 8,
                        "Microsoft.VSTS.Common.ClosedDate": "2026-05-10T12:00:00Z",
                    },
                },
                {
                    "id": 102,
                    "fields": {
                        "System.Id": 102,
                        "System.Title": "Q3 contribution",
                        "System.WorkItemType": "Bug",
                        "System.State": "Resolved",
                        "System.AssignedTo": {"displayName": "Ava Stone", "uniqueName": "ava@example.test"},
                        "Microsoft.VSTS.Scheduling.StoryPoints": 5,
                        "Microsoft.VSTS.Common.ClosedDate": "2026-08-10T12:00:00Z",
                    },
                },
            ]

    blob = FakeBlob()
    monkeypatch.setattr(service, "get_blob_storage_service", lambda: blob)

    result = fetch_innersource_leaderboard(
        FakeAdo(),
        organization="hexagon-si-gpc",
        project="cloud technologies",
        year=2026,
        quarter=2,
        force_refresh=True,
    )

    assert result["total_quarter_points"] == 8
    assert result["total_year_points"] == 13
    assert result["storage_blob_name"].endswith("/2026/summary/q2.json")
    assert "innersource/hexagon-si-gpc/cloud_technologies/2026/manifest.json" in blob.data
    assert "innersource/hexagon-si-gpc/cloud_technologies/2026/items/q2.json" in blob.data
    assert "innersource/hexagon-si-gpc/cloud_technologies/2026/items/q3.json" in blob.data
    assert "innersource/hexagon-si-gpc/cloud_technologies/2026/summary/q2.json" in blob.data
    assert len(blob.data["innersource/hexagon-si-gpc/cloud_technologies/2026/items/q2.json"]) == 1
    assert len(blob.data["innersource/hexagon-si-gpc/cloud_technologies/2026/items/q3.json"]) == 1

    class ShouldNotCallAdo(FakeAdo):
        def query_wiql(self, project, wiql, top=None):
            raise AssertionError("cached summary should avoid Azure DevOps")

    cached = fetch_innersource_leaderboard(
        ShouldNotCallAdo(),
        organization="hexagon-si-gpc",
        project="cloud technologies",
        year=2026,
        quarter=2,
        force_refresh=False,
    )
    assert cached["cached"] is True
    assert cached["total_quarter_points"] == 8


def test_fetch_innersource_leaderboard_migrates_legacy_year_blob(monkeypatch):
    import app.services.innersource_service as service

    legacy_blob = "innersource/hexagon-si-gpc/cloud_technologies/2026_workitems.json"

    class FakeBlob:
        def __init__(self):
            self.data = {
                legacy_blob: {
                    "201": {
                        "id": 201,
                        "fields": {
                            "System.Id": 201,
                            "System.Title": "Legacy item",
                            "System.WorkItemType": "User Story",
                            "System.State": "Closed",
                            "System.AssignedTo": {"displayName": "Lee James"},
                            "Microsoft.VSTS.Scheduling.StoryPoints": 3,
                            "Microsoft.VSTS.Common.ClosedDate": "2026-02-10T12:00:00Z",
                        },
                    }
                },
                "innersource/hexagon-si-gpc/cloud_technologies/2026_meta.json": {"last_synced_at": "2026-10-01T00:00:00+00:00"},
            }

        def get_json(self, name):
            return self.data.get(name)

        def put_json(self, name, data):
            self.data[name] = data
            return True

    class ShouldNotCallAdo:
        def query_wiql(self, project, wiql, top=None):
            raise AssertionError("legacy migration should serve cache without ADO")

    blob = FakeBlob()
    monkeypatch.setattr(service, "get_blob_storage_service", lambda: blob)

    result = fetch_innersource_leaderboard(
        ShouldNotCallAdo(),
        organization="hexagon-si-gpc",
        project="cloud technologies",
        year=2026,
        quarter=1,
    )

    assert result["total_quarter_points"] == 3
    manifest = blob.data["innersource/hexagon-si-gpc/cloud_technologies/2026/manifest.json"]
    assert manifest["layout"] == "partitioned-quarter-v1"
    assert manifest["migrated_from_legacy"] is True
