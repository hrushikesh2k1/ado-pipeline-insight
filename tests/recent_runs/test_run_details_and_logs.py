"""Tests for individual run details, timelines, and failure logs."""
import pytest
from app.repositories.pipeline_repository import PipelineRepository
from tests.conftest import Recorder


def test_logs_join_failure_excerpts_or_explain_their_absence(monkeypatch):
    Recorder(
        monkeypatch,
        all_rows=[
            {"task_name": "a", "failure_log_excerpt": "one", "result": "failed"},
            {"task_name": "b", "failure_log_excerpt": None, "result": "failed"},
            {"task_name": "c", "failure_log_excerpt": "two", "result": "failed"},
        ],
    )
    assert PipelineRepository().logs(5)["log"] == "one\n\ntwo"

    Recorder(monkeypatch, all_rows=[])
    assert "No detailed failure log" in PipelineRepository().logs(5)["log"]


def test_unknown_run_analysis_raises_value_error(monkeypatch):
    Recorder(monkeypatch, one_row=None)
    with pytest.raises(ValueError, match="was not found"):
        PipelineRepository().run_analysis(999999)
