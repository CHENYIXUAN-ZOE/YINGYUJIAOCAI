from fastapi.testclient import TestClient

from app.api.deps import get_job_service, get_practice_service
from app.core.config import Settings
from app.main import app
from app.repositories.export_repo import ExportRepository
from app.repositories.job_repo import JobRepository
from app.repositories.result_repo import ResultRepository
from app.repositories.review_repo import ReviewRepository
from app.schemas.job import PdfPreflight
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


def test_practice_page():
    response = client.get("/practice")
    assert response.status_code == 200
    assert "口语对练测试" in response.text


def test_overview_api():
    response = client.get("/api/v1/overview")
    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload["data"]


def test_missing_job_returns_404():
    response = client.get("/api/v1/jobs/unknown")
    assert response.status_code == 404


def test_unknown_api_route_returns_json_error():
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "HTTP_404"


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


def test_upload_returns_preflight_summary(monkeypatch):
    monkeypatch.setattr(
        "app.services.job_service.pdf_preflight.analyze_pdf",
        lambda _path: PdfPreflight(
            file_size_mb=4.2,
            page_count=32,
            text_layer_detected=True,
            detected_pdf_type="text",
            estimated_duration_sec=240,
            estimated_duration_range="4 分钟 - 6 分钟",
            duration_budget_sec=600,
            within_duration_budget=True,
            warnings=[],
        ),
    )

    response = client.post(
        "/api/v1/upload",
        files={"file": ("sample.pdf", b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["preflight"]["page_count"] == 32
    assert payload["preflight"]["detected_pdf_type"] == "text"
    assert payload["preflight"]["estimated_duration_range"] == "4 分钟 - 6 分钟"


class BrokenJobService:
    def get_job_status(self, job_id: str):
        raise RuntimeError(f"boom for {job_id}")


def test_unhandled_api_error_returns_structured_json():
    isolated_client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_job_service] = lambda: BrokenJobService()
    try:
        response = isolated_client.get("/api/v1/jobs/job_demo")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert payload["error"]["retryable"] is True
    assert payload["error"]["technical_message"] == "boom for job_demo"


class StubPracticeService:
    def get_context(self, job_id: str, unit_id: str) -> dict:
        return {
            "job": {"job_id": job_id, "file_name": "sample.pdf", "status": "reviewing"},
            "unit": {
                "unit_id": unit_id,
                "unit_code": "Unit 1",
                "unit_name": "My Weekend Plan",
                "unit_theme": "Talk about weekend plans",
                "unit_task": "谈论周末计划",
            },
            "grade_band": "3-4",
            "summary": {
                "vocabulary": ["park", "library"],
                "sentence_patterns": ["What will you do on ...?", "I will ..."],
            },
            "prompt": {
                "template_version": "v1",
                "default_template": "template",
                "final_instruction": "Now begin.",
                "final_prompt_preview": "template\n\nCurrent unit context:\n...",
            },
            "provider": {"name": "qwen", "configured": True, "model": "qwen3.5-flash"},
        }

    def chat(self, request) -> dict:
        return {
            "assistant_message": {"role": "assistant", "content": "Hi! What will you do this Saturday?"},
            "round_count": 0 if request.is_opening_turn else 1,
            "status_hint": "",
            "turn_tip": {
                "has_tip": not request.is_opening_turn,
                "tips": [
                    {
                        "title": "这一步可以试试",
                        "message_cn": "可以再把回答说完整一点。",
                        "example_en": "I will go to the park.",
                        "reason_cn": "这样更贴近当前单元的目标句型。",
                    }
                ]
                if not request.is_opening_turn
                else [],
            },
            "meta": {"request_id": "req_demo", "provider": "qwen", "model": "qwen3.5-flash", "latency_ms": 10},
        }

    def build_report(self, request) -> dict:
        return {
            "summary": "你已经能跟着当前单元继续对话。",
            "strengths": ["能理解简单提问"],
            "improvements": ["可以更主动使用重点句型"],
            "pattern_progress": [
                {
                    "pattern": "What will you do on ...?",
                    "status": "in_progress",
                    "note_cn": "还可以继续多练几轮。",
                }
            ],
            "next_steps": ["下次尝试用完整句回答。"],
        }


def test_practice_context_api():
    app.dependency_overrides[get_practice_service] = lambda: StubPracticeService()
    try:
        response = client.get("/api/v1/practice/context", params={"job_id": "job_demo", "unit_id": "job_demo_unit_1"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["grade_band"] == "3-4"
    assert payload["provider"]["configured"] is True


def test_practice_chat_api():
    app.dependency_overrides[get_practice_service] = lambda: StubPracticeService()
    try:
        response = client.post(
            "/api/v1/practice/chat",
            json={
                "job_id": "job_demo",
                "unit_id": "job_demo_unit_1",
                "grade_band": "3-4",
                "prompt_template": "template",
                "final_prompt": "final",
                "messages": [],
                "student_message": "",
                "is_opening_turn": True,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["assistant_message"]["role"] == "assistant"


def test_practice_report_api():
    app.dependency_overrides[get_practice_service] = lambda: StubPracticeService()
    try:
        response = client.post(
            "/api/v1/practice/report",
            json={
                "job_id": "job_demo",
                "unit_id": "job_demo_unit_1",
                "messages": [
                    {"role": "assistant", "content": "Hi!"},
                    {"role": "user", "content": "I will go to the park."},
                ],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()["data"]
    assert "summary" in payload
    assert payload["pattern_progress"][0]["status"] == "in_progress"
