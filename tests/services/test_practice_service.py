from __future__ import annotations

import pytest

from app.clients.openai_compatible.practice_chat_client import OpenAICompatiblePracticeChatResponse
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


class StubPracticeClient:
    provider_name = "qwen"

    def __init__(self, configured: bool = True, response: OpenAICompatiblePracticeChatResponse | None = None):
        self.configured = configured
        self.response = response or OpenAICompatiblePracticeChatResponse(
            assistant_message="Hi! What will you do this Saturday?",
            request_id="req_demo",
            latency_ms=12,
            usage={"prompt_tokens": 10, "completion_tokens": 9},
        )
        self.messages: list[dict[str, str]] = []

    def is_configured(self) -> bool:
        return self.configured

    def model_name(self) -> str:
        return "qwen3.5-flash" if self.configured else ""

    def create_chat_completion(self, messages: list[dict[str, str]]) -> OpenAICompatiblePracticeChatResponse:
        self.messages = messages
        return self.response


def test_get_context_builds_prompt_preview(tmp_path):
    service = PracticeService(StubJobService(), StubPracticeClient(configured=False))

    payload = service.get_context("job_demo", "job_demo_unit_1")

    assert payload["grade_band"] == "3-4"
    assert payload["unit"]["unit_theme"] == "Talk about weekend plans"
    assert "Current unit context:" in payload["prompt"]["final_prompt_preview"]
    assert "Key vocabulary: park, library" in payload["prompt"]["final_prompt_preview"]
    assert "Do not ask the student to guess something that exists only in your mind" in payload["prompt"]["default_template"]
    assert "Keep most teacher turns under about 20 English words in total." in payload["prompt"]["default_template"]
    assert "Keep it concrete, easy to answer, and clearly tied to the unit." in payload["prompt"]["final_prompt_preview"]


def test_get_context_adds_shopping_role_guidance(tmp_path):
    job_service = StubJobService()
    unit = job_service.payload["units"][0]
    unit["unit"]["unit_theme"] = "购物与价格询问"
    unit["unit"]["classification"]["unit_name"] = "Shopping"
    unit["sentence_patterns"] = [
        {"pattern": "How much is it? / It's X yuan."},
        {"pattern": "How much are they? / They are X yuan."},
    ]
    unit["unit_task"] = {"task_intro": "学生选择商品并扮演顾客和售货员进行购物对话。"}
    service = PracticeService(job_service, StubPracticeClient(configured=False))

    payload = service.get_context("job_demo", "job_demo_unit_1")
    final_prompt = payload["prompt"]["final_prompt_preview"]

    assert "let the student act as the customer first" in final_prompt
    assert "take the shopkeeper role" in final_prompt
    assert "Guide the student to ask target questions such as 'How much is ...?'" in final_prompt


def test_chat_requires_provider_configuration(tmp_path):
    service = PracticeService(StubJobService(), StubPracticeClient(configured=False))

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


def test_chat_uses_provider_client_response(tmp_path):
    client = StubPracticeClient(configured=True)
    service = PracticeService(StubJobService(), client)

    payload = service.chat(
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

    assert payload["assistant_message"]["content"] == "Hi! What will you do this Saturday?"
    assert payload["meta"]["request_id"] == "req_demo"
    assert payload["meta"]["provider"] == "qwen"
    assert payload["meta"]["model"] == "qwen3.5-flash"
    assert client.messages[0] == {"role": "system", "content": "final prompt"}
