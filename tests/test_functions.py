import json
from types import SimpleNamespace

import azure.functions as func

from functions import function_app


def test_get_recommendations_skips_llm_for_insufficient_history(monkeypatch):
    class FakeRepository:
        def __init__(self, _connection_string):
            pass

        def count_runs(self, _pipeline_id):
            return 2

    monkeypatch.setattr(function_app, "get_settings", lambda: SimpleNamespace(sql_connection_string="test", min_history_runs=5))
    monkeypatch.setattr(function_app, "AlertRepository", FakeRepository)
    response = function_app.get_recommendations(func.HttpRequest("POST", "http://localhost/api/get_recommendations", body=b'{"pipeline_id": 7}'))
    assert response.status_code == 200
    assert "Not enough run history" in json.loads(response.get_body())["message"]