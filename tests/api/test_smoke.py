from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_index_page():
    response = client.get("/")
    assert response.status_code == 200


def test_overview_page():
    response = client.get("/overview")
    assert response.status_code == 200
    assert "功能设计与使用总览" in response.text


def test_missing_job_returns_404():
    response = client.get("/api/v1/jobs/unknown")
    assert response.status_code == 404
