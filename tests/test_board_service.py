from datetime import datetime, timezone, timedelta
from app.services.board_service import (
    calculate_business_days,
    calculate_remaining_work_days,
    evaluate_sprint_work_items,
)


def test_calculate_business_days_same_day():
    dt = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)  # Monday
    assert calculate_business_days(dt, dt) == 0


def test_calculate_business_days_excludes_weekend():
    # Friday 10:00 to following Tuesday 10:00 -> Mon, Tue = 2 business days
    fri = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
    tue = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
    assert calculate_business_days(fri, tue) == 2


def test_calculate_business_days_over_four_days():
    # Friday 10:00 to Monday 10 days later (spanning 2 weekends)
    # Mon, Tue, Wed, Thu, Fri (week 1 = 5), Mon (week 2 = 6) -> 6 business days
    start = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
    days = calculate_business_days(start, end)
    assert days == 6
    assert days > 4


def test_calculate_remaining_work_days():
    now = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)  # Monday
    finish = datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)  # Wednesday
    # Tue, Wed = 2 work days remaining
    remaining = calculate_remaining_work_days(finish, now)
    assert remaining == 2


def test_evaluate_sprint_work_items_checks():
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    stale_date = (now - timedelta(days=9)).isoformat()  # > 4 business days ago
    yesterday = (now - timedelta(days=1)).isoformat()

    items = [
        # 1. Task done with hours: completed = 5.0 -> NOT FLAGGED
        {
            "id": 1,
            "fields": {
                "System.Id": 1,
                "System.Title": "Task with hours",
                "System.WorkItemType": "Task",
                "System.State": "Done",
                "Microsoft.VSTS.Scheduling.CompletedWork": 5.0,
                "Microsoft.VSTS.Scheduling.RemainingWork": 0.0,
            },
        },
        # 2. Task closed with 0.0 hours -> VALID (0 hours is valid per requirements) -> NOT FLAGGED
        {
            "id": 2,
            "fields": {
                "System.Id": 2,
                "System.Title": "Task closed with 0 hours",
                "System.WorkItemType": "Task",
                "System.State": "Closed",
                "Microsoft.VSTS.Scheduling.CompletedWork": 0.0,
                "Microsoft.VSTS.Scheduling.RemainingWork": 0.0,
            },
        },
        # 3. Task closed with blank (None) completed work -> FLAGGED!
        {
            "id": 3,
            "fields": {
                "System.Id": 3,
                "System.Title": "Task closed with blank hours",
                "System.WorkItemType": "Task",
                "System.State": "Done",
                "Microsoft.VSTS.Scheduling.CompletedWork": None,
                "Microsoft.VSTS.Scheduling.RemainingWork": 0.0,
            },
        },
        # 4. User story in review for 6 business days -> FLAGGED by Check 2 (and never flagged by Check 1 even with blank hours)
        {
            "id": 10,
            "fields": {
                "System.Id": 10,
                "System.Title": "Story stuck in review",
                "System.WorkItemType": "User Story",
                "System.State": "In Review",
                "Microsoft.VSTS.Scheduling.CompletedWork": None,  # blank hours, but is Story, so NOT flagged by Check 1
                "Microsoft.VSTS.Common.StateChangeDate": stale_date,
            },
        },
        # 5. User story in review yesterday -> NOT FLAGGED
        {
            "id": 11,
            "fields": {
                "System.Id": 11,
                "System.Title": "Story freshly in review",
                "System.WorkItemType": "User Story",
                "System.State": "In Review",
                "Microsoft.VSTS.Common.StateChangeDate": yesterday,
            },
        },
        # 6. Task closed with empty string hours -> FLAGGED
        {
            "id": 4,
            "fields": {
                "System.Id": 4,
                "System.Title": "Task closed with empty string hours",
                "System.WorkItemType": "Task",
                "System.State": "Closed",
                "Microsoft.VSTS.Scheduling.CompletedWork": "  ",
            },
        },
        # 7. Task closed with "0" as string -> VALID (0 hours valid) -> NOT FLAGGED
        {
            "id": 5,
            "fields": {
                "System.Id": 5,
                "System.Title": "Task closed with string zero",
                "System.WorkItemType": "Task",
                "System.State": "Closed",
                "Microsoft.VSTS.Scheduling.CompletedWork": "0",
            },
        },
        # 8. Bug closed with blank hours -> NOT FLAGGED (Check 1 strictly applies to Tasks only)
        {
            "id": 6,
            "fields": {
                "System.Id": 6,
                "System.Title": "Bug closed without hours",
                "System.WorkItemType": "Bug",
                "System.State": "Closed",
                "Microsoft.VSTS.Scheduling.CompletedWork": None,
            },
        },
    ]

    parsed, summary = evaluate_sprint_work_items(items, "myorg", "myproj", now)
    assert len(parsed) == 8

    # Check 1: strictly applicable to Tasks only and blank hours only (0 is valid)
    assert summary["total_tasks"] == 5
    assert summary["tasks_closed_count"] == 5
    assert summary["tasks_closed_without_hours_count"] == 2  # item 3 and item 4
    assert parsed[0]["is_closed_without_hours"] is False  # 5.0h
    assert parsed[1]["is_closed_without_hours"] is False  # 0.0h is valid!
    assert parsed[2]["is_closed_without_hours"] is True   # None (blank) is flagged!
    assert parsed[3]["is_closed_without_hours"] is False  # User story with blank hours is NEVER flagged by Check 1
    assert parsed[5]["is_closed_without_hours"] is True   # Empty string hours flagged!
    assert parsed[6]["is_closed_without_hours"] is False  # "0" is valid!
    assert parsed[7]["is_closed_without_hours"] is False  # Bug is NEVER flagged by Check 1 (Tasks only!)

    # Check 2
    assert summary["total_user_stories"] == 2
    assert summary["stories_in_review_count"] == 2
    assert summary["stories_in_review_stale_count"] == 1
    assert parsed[3]["is_stale_in_review"] is True
    assert parsed[3]["business_days_in_review"] > 4
    assert parsed[4]["is_stale_in_review"] is False

    # Flagged item IDs should contain 3 (blank task), 4 (empty string task), and 10 (stale story)
    assert set(summary["flagged_item_ids"]) == {3, 4, 10}


def test_calculate_sprint_milestones():
    from app.services.board_service import calculate_sprint_milestones

    work_items = [
        # Closed story with 2 child tasks
        {
            "id": 101,
            "title": "OAuth 2.0 Azure AD Authentication",
            "work_item_type": "User Story",
            "state": "Closed",
            "assigned_to_name": "Alice Johnson",
            "completed_work": 4.0,
            "parent_id": None,
        },
        {
            "id": 102,
            "title": "Implement JWT validation middleware",
            "work_item_type": "Task",
            "state": "Done",
            "completed_work": 6.0,
            "parent_id": 101,
        },
        {
            "id": 103,
            "title": "Add unit tests for token expiry",
            "work_item_type": "Task",
            "state": "Done",
            "completed_work": 2.5,
            "parent_id": 101,
        },
        # Resolved Bug
        {
            "id": 201,
            "title": "Fix memory leak in telemetry ingestion pipeline",
            "work_item_type": "Bug",
            "state": "Resolved",
            "assigned_to_name": "Bob Smith",
            "completed_work": 5.0,
            "parent_id": None,
        },
        # In-progress story (not closed -> should not be in achieved_items)
        {
            "id": 301,
            "title": "Real-time Slack Notifications",
            "work_item_type": "User Story",
            "state": "Active",
            "assigned_to_name": "Charlie",
            "completed_work": None,
            "parent_id": None,
        },
    ]

    milestone = calculate_sprint_milestones(work_items)

    assert milestone["total_stories"] == 3  # 101, 201, 301
    assert milestone["closed_stories_count"] == 2  # 101 and 201
    assert milestone["open_stories_count"] == 1  # 301
    assert milestone["completion_rate_pct"] == 66.7
    assert milestone["features_delivered_count"] == 1
    assert milestone["bugs_resolved_count"] == 1

    # Check achieved items
    achieved = milestone["achieved_items"]
    assert len(achieved) == 2
    story_item = next(i for i in achieved if i["id"] == 101)
    assert story_item["child_tasks_total"] == 2
    assert story_item["child_tasks_closed"] == 2
    assert story_item["hours_delivered"] == 12.5  # 4.0 story + 6.0 task + 2.5 task
    assert story_item["assigned_to_name"] == "Alice Johnson"

    bug_item = next(i for i in achieved if i["id"] == 201)
    assert bug_item["category"] == "Bug Fix & Quality"
    assert bug_item["hours_delivered"] == 5.0

    assert len(milestone["key_achievements"]) == 2


def test_milestone_streams_are_not_tied_to_any_single_teams_vocabulary():
    """A non-monitoring team's work (payments/checkout) must not be forced into alerting-flavored
    buckets by keyword matching on the title - this is the exact failure the old implementation had."""
    from app.services.board_service import calculate_sprint_milestones

    work_items = [
        {"id": 1, "title": "Refund calculation returns wrong currency", "work_item_type": "Bug",
         "state": "Closed", "completed_work": 3.0, "parent_id": 10, "area_path": "Payments\\Checkout"},
        {"id": 2, "title": "Support Apple Pay at checkout", "work_item_type": "User Story",
         "state": "Closed", "completed_work": 8.0, "parent_id": 10, "area_path": "Payments\\Checkout"},
    ]
    parent_lookup = {10: ("Checkout Redesign", "Feature")}

    milestone = calculate_sprint_milestones(work_items, parent_lookup)
    streams = {item["id"]: item["milestone_stream"] for item in milestone["achieved_items"]}

    # Both items share the same parent Feature, so both land in the Feature's own name as the stream -
    # not any alerting/monitoring bucket, regardless of what words appear in their titles.
    assert streams == {1: "Checkout Redesign", 2: "Checkout Redesign"}
    assert milestone["graph_data"]["streams"][0]["name"] == "Checkout Redesign"


def test_milestone_stream_falls_back_to_area_path_without_a_feature_parent():
    from app.services.board_service import calculate_sprint_milestones

    work_items = [
        {"id": 1, "title": "Fix flaky login test", "work_item_type": "Bug", "state": "Done",
         "completed_work": 1.0, "parent_id": None, "area_path": "Auth"},
    ]
    milestone = calculate_sprint_milestones(work_items)
    assert milestone["achieved_items"][0]["milestone_stream"] == "Auth"


def test_milestone_stream_ignores_a_non_feature_parent_and_falls_back_to_area_path():
    from app.services.board_service import calculate_sprint_milestones

    work_items = [
        {"id": 1, "title": "Child story under another story", "work_item_type": "User Story",
         "state": "Closed", "completed_work": 1.0, "parent_id": 99, "area_path": "iOS"},
    ]
    # Parent exists but is itself a User Story, not a Feature/Epic - must not be used as the stream name.
    parent_lookup = {99: ("Some Parent Story", "User Story")}
    milestone = calculate_sprint_milestones(work_items, parent_lookup)
    assert milestone["achieved_items"][0]["milestone_stream"] == "iOS"


def test_milestone_item_with_no_description_states_that_plainly():
    """A blank description must never be replaced with a plausible-sounding, domain-specific guess."""
    from app.services.board_service import calculate_sprint_milestones

    work_items = [
        {"id": 1, "title": "Improve search relevance ranking", "work_item_type": "User Story",
         "state": "Closed", "completed_work": 2.0, "parent_id": None},
    ]
    item = calculate_sprint_milestones(work_items)["achieved_items"][0]
    assert item["issue_summary"] == "No description was recorded on this user story."
    assert "alert" not in item["issue_summary"].lower()
    assert "monitor" not in item["issue_summary"].lower()
    assert item["achievement_summary"] == "Marked Closed with no acceptance criteria recorded."


def test_bug_resolution_rate_is_generic_not_alert_specific():
    from app.services.board_service import calculate_sprint_milestones

    work_items = [
        {"id": 1, "title": "Crash on startup", "work_item_type": "Bug", "state": "Closed", "completed_work": 1.0, "parent_id": None},
        {"id": 2, "title": "Wrong total on invoice", "work_item_type": "Bug", "state": "Active", "completed_work": None, "parent_id": None},
    ]
    graph = calculate_sprint_milestones(work_items)["graph_data"]
    assert "alert_stability_index" not in graph
    assert graph["bug_resolution_rate_pct"] == 50.0


def test_next_sprint_recommendations_are_derived_not_scripted():
    """Recommendations must describe this sprint's own data, never a fixed per-stream script."""
    from app.services.board_service import calculate_sprint_milestones

    work_items = [
        {"id": 1, "title": "Done work", "work_item_type": "User Story", "state": "Closed",
         "completed_work": 4.0, "parent_id": 50, "area_path": "Mobile\\Android"},
        {"id": 2, "title": "Still open work", "work_item_type": "User Story", "state": "Active",
         "completed_work": None, "parent_id": 50, "area_path": "Mobile\\Android"},
    ]
    parent_lookup = {50: ("Android Revamp", "Epic")}
    graph = calculate_sprint_milestones(work_items, parent_lookup)["graph_data"]
    stream = next(s for s in graph["streams"] if s["name"] == "Android Revamp")
    assert "1 item(s) in this stream are still open" in stream["next_sprint_recommendation"]
def test_is_work_item_in_iteration_cross_sprint_isolation():
    from app.services.board_service import is_work_item_in_iteration

    # Scenario: Bug 1084653 is in Oct (26-10) iteration
    bug_1084653 = {
        "id": 1084653,
        "fields": {
            "System.Id": 1084653,
            "System.Title": "Pipeline telemetry ingestion timeout",
            "System.WorkItemType": "Bug",
            "System.IterationPath": "MyProject\\26-10",
            "System.IterationId": 501,
        },
    }

    # User Story in Sep (26-09) iteration
    story_sep = {
        "id": 1084000,
        "fields": {
            "System.Id": 1084000,
            "System.Title": "Data exporter feature",
            "System.WorkItemType": "User Story",
            "System.IterationPath": "MyProject\\26-09",
            "System.IterationId": 401,
        },
    }

    # 1. September Sprint checks
    assert is_work_item_in_iteration(story_sep, target_iteration_path="MyProject\\26-09", target_iteration_name="26-09") is True
    # Bug 1084653 MUST NOT be in September Sprint!
    assert is_work_item_in_iteration(bug_1084653, target_iteration_path="MyProject\\26-09", target_iteration_name="26-09") is False

    # 2. October Sprint checks
    assert is_work_item_in_iteration(bug_1084653, target_iteration_path="MyProject\\26-10", target_iteration_name="26-10") is True
    # Sep story MUST NOT be in October Sprint!
    assert is_work_item_in_iteration(story_sep, target_iteration_path="MyProject\\26-10", target_iteration_name="26-10") is False

    # 3. Normalized slash checks (e.g. forward slash vs backward slash)
    assert is_work_item_in_iteration(bug_1084653, target_iteration_path="MyProject/26-10") is True
    assert is_work_item_in_iteration(bug_1084653, target_iteration_path="MyProject/26-09") is False

    # 4. Check by Iteration ID
    assert is_work_item_in_iteration(bug_1084653, target_iteration_id=501) is True
    assert is_work_item_in_iteration(bug_1084653, target_iteration_id=401) is False

