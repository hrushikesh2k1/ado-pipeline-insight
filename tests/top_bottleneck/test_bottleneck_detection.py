"""Tests for identifying top bottleneck stages, jobs, and tasks from execution timelines."""
import pytest
from app.repositories.pipeline_repository import PipelineRepository
from tests.conftest import Recorder, run_row


def test_run_analysis_finds_the_longest_records_and_counts_failures(monkeypatch):
    run = {
        **run_row(5, "failed", 40, 10),
        "pipeline_name": "CI",
        "organization_name": "o",
        "project_name": "p",
        "source_branch": "main",
        "source_version": "abc",
        "requested_by": "dev",
        "build_number": "1",
    }
    hierarchy = {
        "stages": [
            {"duration_seconds": 30, "result": "failed"},
            {"duration_seconds": 10, "result": "succeeded"},
        ],
        "jobs": [
            {"duration_seconds": 5.5, "result": "succeeded"},
            {"duration_seconds": 25, "result": "Failed"},
        ],
        "tasks": [
            {"duration_seconds": None, "result": None},
            {"duration_seconds": 2.25, "result": "succeeded"},
        ],
    }
    Recorder(monkeypatch, one_row=run)
    repo = PipelineRepository()
    monkeypatch.setattr(repo, "timeline", lambda run_id: {"run_id": run_id, **hierarchy})
    m = repo.run_analysis(5)["metrics"]

    assert m["run_duration_seconds"] == 40.0
    assert m["queue_seconds"] == 10.0
    assert m["longest_stage"]["duration_seconds"] == 30
    assert m["longest_job"]["duration_seconds"] == 25
    assert m["failed_records"] == 2
    assert m["stage_duration_total_seconds"] == 40.0
    assert m["job_duration_total_seconds"] == 30.5
    assert m["task_duration_total_seconds"] == 2.25
    assert (m["stage_count"], m["job_count"], m["task_count"]) == (2, 2, 2)


def test_run_analysis_handles_empty_timeline_gracefully(monkeypatch):
    run = {
        **run_row(10, "succeeded", 50, 5),
        "pipeline_name": "CI",
        "organization_name": "o",
        "project_name": "p",
        "source_branch": "main",
        "source_version": "abc",
        "requested_by": "dev",
        "build_number": "2",
    }
    Recorder(monkeypatch, one_row=run)
    repo = PipelineRepository()
    monkeypatch.setattr(repo, "timeline", lambda run_id: {"run_id": run_id, "stages": [], "jobs": [], "tasks": []})
    m = repo.run_analysis(10)["metrics"]

    assert m["longest_stage"] is None
    assert m["longest_job"] is None
    assert m["failed_records"] == 0
