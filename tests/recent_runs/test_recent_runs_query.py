"""Tests for pagination, row clamping, and query structure of recent runs."""
import pytest
from app.repositories.pipeline_repository import PipelineRepository
from tests.conftest import Recorder


def test_runs_paging_math(monkeypatch):
    rec = Recorder(monkeypatch, one_row={"total": 130})
    result = PipelineRepository().runs(None, 3, 25, None)
    assert result["total_count"] == 130 and result["total_pages"] == 6 and result["page"] == 3 and result["page_size"] == 25
    items_query, items_params = rec.calls[-1]
    assert items_params[-2:] == (50, 25), "OFFSET must be (page-1)*page_size and FETCH must be page_size"
    assert "ORDER BY r.start_time DESC" in items_query


@pytest.mark.parametrize(
    "page,size,expected_page,expected_size",
    [(0, 10, 1, 10), (-4, 10, 1, 10), (1, 0, 1, 1), (1, 5000, 1, 1000)],
)
def test_runs_clamps_paging_inputs(monkeypatch, page, size, expected_page, expected_size):
    rec = Recorder(monkeypatch)
    result = PipelineRepository().runs(None, page, size, None)
    assert result["page"] == expected_page and result["page_size"] == expected_size
    assert rec.calls[-1][1][-2:] == ((expected_page - 1) * expected_size, expected_size)


def test_runs_with_no_rows_still_reports_one_page(monkeypatch):
    Recorder(monkeypatch, one_row={"total": 0})
    assert PipelineRepository().runs(None, 1, 100, None)["total_pages"] == 1


def test_runs_last_page_is_counted(monkeypatch):
    Recorder(monkeypatch, one_row={"total": 101})
    assert PipelineRepository().runs(None, 1, 100, None)["total_pages"] == 2
