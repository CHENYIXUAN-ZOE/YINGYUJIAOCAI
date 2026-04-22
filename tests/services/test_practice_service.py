from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.job import ParseJob
from app.schemas.common import ParseStatus, ReviewStatus
from app.services.practice_service import PracticeService


class StubJobService:
    def __init__(self):
        self.job = ParseJob(
            job_id="job_demo",
            file_name="北师大版英语 3A.pdf",
            file_path="/tmp/sample.pdf",
            status=ParseStatus.reviewing,
            progress=100,
            created_at="2026-04-22T00:00:00Z",
            review_status=ReviewStatus.pending,
        )
        self.payload = {
            "book": {"textbook_name": "北师大版英语 3A", "grade": None},
            "units": [
                {
                    "unit": {
                        "unit_id": "job_demo_unit_1",
                        "unit_theme": "Talk about weekend plans",
                        "classification": {
                            "unit_code": "Unit 1",
                            "unit_name": "My Weekend Plan",
                            "textbook_name": "北师大版英语 3A",
                        },
                    },
                    "vocabulary": [
                        {"word": "park"},
                        {"word": "library"},
                    ],
                    "sentence_patterns": [
                        {"pattern": "What will you do on ...?"},
                        {"pattern": "I will ..."},
                    ],
                    "unit_task": {"task_intro": "谈论周末计划"},
                    "unit_prompt": {"unit_theme": "Talk about weekend plans"},
                }
            ],
        }

    def get_job(self, job_id: str):
        assert job_id == self.job.job_id
        return self.job

    def get_result(self, job_id: str, approved_only: bool = False, include_review_records: bool = True):
        assert job_id == self.job.job_id
        return self.payload


def build_settings(tmp_path) -> Settings:
    settings = Settings(
        base_dir=tmp_path,
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data" / "uploads",
        parsed_dir=tmp_path / "data" / "parsed",
        export_dir=tmp_path / "data" / "exports",
        job_dir=tmp_path / "data" / "parsed" / "jobs",
        result_dir=tmp_path / "data" / "parsed" / "results",
        review_dir=tmp_path / "data" / "parsed" / "reviews",
        web_dir=tmp_path / "app" / "web",
        template_dir=tmp_path / "app" / "web" / "templates",
        static_dir=tmp_path / "app" / "web" / "static",
        doubao_api_key=None,
        doubao_endpoint_id=None,
    )
    settings.ensure_directories()
    return settings


def test_get_context_builds_prompt_preview(tmp_path):
    service = PracticeService(build_settings(tmp_path), StubJobService())

    payload = service.get_context("job_demo", "job_demo_unit_1")

    assert payload["grade_band"] == "3-4"
    assert payload["unit"]["unit_theme"] == "Talk about weekend plans"
    assert "Current unit context:" in payload["prompt"]["final_prompt_preview"]
    assert "Key vocabulary: park, library" in payload["prompt"]["final_prompt_preview"]


def test_chat_requires_provider_configuration(tmp_path):
    service = PracticeService(build_settings(tmp_path), StubJobService())

    with pytest.raises(AppError) as exc_info:
        service.chat(
            type(
                "Req",
                (),
                {
                    "job_id": "job_demo",
                    "unit_id": "job_demo_unit_1",
                    "grade_band": "3-4",
                    "prompt_template": "template",
                    "final_prompt": "final prompt",
                    "messages": [],
                    "student_message": "",
                    "is_opening_turn": True,
                },
            )()
        )

    assert exc_info.value.code == "PRACTICE_PROVIDER_NOT_CONFIGURED"
