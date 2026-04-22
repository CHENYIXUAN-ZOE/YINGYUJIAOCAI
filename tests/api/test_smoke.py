from fastapi.testclient import TestClient

from app.api.deps import get_job_service
from app.core.config import Settings
from app.main import app
from app.repositories.export_repo import ExportRepository
from app.repositories.job_repo import JobRepository
from app.repositories.result_repo import ResultRepository
from app.repositories.review_repo import ReviewRepository
from app.services.job_service import JobService


client = TestClient(app)


def build_settings(tmp_path) -> Settings:
    data_dir = tmp_path / "data"
    parsed_dir = data_dir / "parsed"
    export_dir = data_dir / "exports"
    web_dir = tmp_path / "app" / "web"
    settings = Settings(
        base_dir=tmp_path,
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        parsed_dir=parsed_dir,
        export_dir=export_dir,
        job_dir=parsed_dir / "jobs",
        result_dir=parsed_dir / "results",
        review_dir=parsed_dir / "reviews",
        web_dir=web_dir,
        template_dir=web_dir / "templates",
        static_dir=web_dir / "static",
    )
    settings.ensure_directories()
    return settings


def build_service(settings: Settings) -> JobService:
    return JobService(
        upload_dir=settings.upload_dir,
        export_dir=settings.export_dir,
        job_repo=JobRepository(settings),
        result_repo=ResultRepository(settings),
        review_repo=ReviewRepository(settings),
        export_repo=ExportRepository(settings),
    )


def test_index_page():
    response = client.get("/")
    assert response.status_code == 200


def test_overview_page():
    response = client.get("/overview")
    assert response.status_code == 200
    assert "任务总览与内容产出统计" in response.text


def test_overview_api():
    response = client.get("/api/v1/overview")
    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload["data"]


def test_missing_job_returns_404():
    response = client.get("/api/v1/jobs/unknown")
    assert response.status_code == 404


def test_delete_job_api(tmp_path):
    settings = build_settings(tmp_path)
    service = build_service(settings)
    job = service.create_job("sample.pdf", b"%PDF-1.4")

    app.dependency_overrides[get_job_service] = lambda: service
    try:
        response = client.delete(f"/api/v1/jobs/{job.job_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"] == {"job_id": job.job_id, "deleted": True}


def test_upload_returns_file_size_details(monkeypatch):
    monkeypatch.setattr("app.api.routes.upload.get_settings", lambda: Settings(max_upload_size_mb=1))

    response = client.post(
        "/api/v1/upload",
        files={"file": ("too-large.pdf", b"x" * (1024 * 1024 + 16), "application/pdf")},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "FILE_TOO_LARGE"
    assert payload["error"]["details"]["limit_mb"] == 1
