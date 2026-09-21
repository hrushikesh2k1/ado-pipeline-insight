from backend.app.repositories.pipeline_repository import percentile

def test_percentile_empty():
    assert percentile([], .9) is None

def test_percentile_interpolates():
    assert percentile([10, 20, 30, 40], .9) == 37.0
