from fastapi.testclient import TestClient
from backend.app.main import app

def test_root_without_frontend():
    response = TestClient(app).get("/")
    assert response.status_code == 200
