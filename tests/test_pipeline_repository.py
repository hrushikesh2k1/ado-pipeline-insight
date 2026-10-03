from app.repositories.pipeline_repository import percentile

def test_percentile_empty():
    assert percentile([], .9) is None

def test_percentile_interpolates():
    assert percentile([10, 20, 30, 40], .9) == 37.0


def test_recommendations_come_back_in_the_order_they_were_saved(monkeypatch):
    """Findings are saved worst first; a refresh must show them in that same order, not reversed."""
    import app.repositories.pipeline_repository as repo_module

    seen = {}
    monkeypatch.setattr(repo_module, "fetch_all", lambda query, params=(): seen.update(query=query, params=params) or [])
    repo_module.PipelineRepository().recommendations(3012, 50)
    assert "ORDER BY id ASC" in seen["query"] and "generated_at DESC" not in seen["query"]
    assert seen["params"] == (50, 3012)
