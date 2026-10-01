"""Tests for Recent Runs product identification and stage_name retrieval for product filtering."""
from app.repositories.pipeline_repository import PipelineRepository
from tests.conftest import Recorder, run_row


def test_runs_includes_executed_stage_name_for_product_filtering(monkeypatch):
    """Verify that runs query selects the executed stage_name so the frontend can filter by product."""
    rec = Recorder(monkeypatch, one_row={"total": 1})
    PipelineRepository().runs(3010, 1, 10, None, 30)

    items_query, _ = rec.calls[1]
    assert "stage_name" in items_query
    assert "dbo.pipeline_stages" in items_query
    assert "result != 'skipped'" in items_query


def test_runs_returns_stage_name_in_items(monkeypatch):
    run_with_stage = {
        **run_row(1001, "succeeded", 2500),
        "build_number": "20260723.1",
        "source_branch": "refs/heads/copsoie",
        "stage_name": "Deploy copsoie OIE Dev",
    }
    Recorder(monkeypatch, all_rows=[run_with_stage], one_row={"total": 1})

    res = PipelineRepository().runs(3010, 1, 10, None, 30)
    assert len(res["items"]) == 1
    assert res["items"][0]["stage_name"] == "Deploy copsoie OIE Dev"
    assert res["items"][0]["source_branch"] == "refs/heads/copsoie"
