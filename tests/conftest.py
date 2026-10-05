import os
import sys
from datetime import datetime, timedelta

# The suite exercises routes without signing in; tests/test_session_auth.py turns sign-in back on explicitly.
os.environ.setdefault("REQUIRE_LOGIN", "false")

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.repositories.pipeline_repository as repo_module

T0 = datetime(2026, 9, 1, 8, 0, 0)


def run_row(run_id, result, duration, queue_wait=10, degraded=0, start=T0):
    return {
        "run_id": run_id,
        "pipeline_id": 1,
        "queue_time": start - timedelta(seconds=queue_wait),
        "start_time": start,
        "finish_time": start + timedelta(seconds=duration),
        "result": result,
        "is_degraded": degraded,
        "data_quality": "complete",
        "duration_seconds": duration,
    }


def build(run_id, day, pipeline, duration, hour=9):
    return {
        "run_id": run_id,
        "build_number": str(run_id),
        "run_date": datetime(2026, 9, day, hour, 0),
        "pipeline_id": pipeline,
        "pipeline_name": f"pipe-{pipeline}",
        "duration_seconds": duration,
        "result": "succeeded",
    }


_UNSET = object()


class Recorder:
    def __init__(self, monkeypatch, all_rows=None, one_row=_UNSET):
        self.calls = []
        self.all_rows = all_rows if all_rows is not None else []
        self.one_row = {"total": 0, "ok": 1} if one_row is _UNSET else one_row
        monkeypatch.setattr(repo_module, "fetch_all", self._all)
        monkeypatch.setattr(repo_module, "fetch_one", self._one)

    def _all(self, query, params=()):
        self.calls.append((query, tuple(params)))
        return self.all_rows(query) if callable(self.all_rows) else self.all_rows

    def _one(self, query, params=()):
        self.calls.append((query, tuple(params)))
        return self.one_row


import pytest


@pytest.fixture(autouse=True)
def _clean_work_item_insights():
    """Saved insights and refresh jobs live in module-level memory; every test starts without them."""
    import app.repositories.work_item_insights_repository as insights_store
    import app.services.work_item_insights as insights_service

    insights_store.clear_memory()
    insights_service._jobs.clear()
    yield
    insights_store.clear_memory()
    insights_service._jobs.clear()
