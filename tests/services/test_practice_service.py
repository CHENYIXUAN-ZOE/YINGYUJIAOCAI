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
                    "dialogue_samples": [],
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
    assert "keep your role consistent until you clearly say the role-play is changing" in payload["prompt"]["default_template"]
    assert "Keep it concrete, easy to answer, and clearly tied to the unit." in payload["prompt"]["final_prompt_preview"]


def test_get_context_adds_shopping_role_guidance(tmp_path):
    job_service = StubJobService()
    unit = job_service.payload["units"][0]
    unit["unit"]["unit_theme"] = "购物与价格询问"
    unit["unit"]["classification"]["unit_name"] = "Shopping"
    unit["vocabulary"] = [{"word": "doll"}, {"word": "sunglasses"}, {"word": "toy train"}, {"word": "yuan"}]
    unit["sentence_patterns"] = [
        {"pattern": "How much is it? / It's X yuan."},
        {"pattern": "How much are they? / They are X yuan."},
    ]
    unit["dialogue_samples"] = [
        {
            "turns": [
                {"speaker": "Mary", "text_en": "How much is this doll?"},
                {"speaker": "Shopkeeper", "text_en": "It's twenty yuan."},
            ]
        }
    ]
    unit["unit_task"] = {"task_intro": "学生选择商品并扮演顾客和售货员进行购物对话。"}
    service = PracticeService(job_service, StubPracticeClient(configured=False))

    payload = service.get_context("job_demo", "job_demo_unit_1")
    final_prompt = payload["prompt"]["final_prompt_preview"]

    assert "let the student act as the customer first" in final_prompt
    assert "take the shopkeeper role" in final_prompt
    assert "Guide the student to ask target questions such as 'How much is ...?'" in final_prompt
    assert "Do not switch roles in the middle of the shopping scene" in final_prompt
    assert "do not ask customer-side price questions" in final_prompt
    assert "prompt the student to ask about the price instead of asking it yourself" in final_prompt


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


def test_chat_plans_shopping_price_nudge_for_first_item_choice(tmp_path):
    job_service = StubJobService()
    unit = job_service.payload["units"][0]
    unit["unit"]["unit_theme"] = "购物与价格询问"
    unit["unit"]["classification"]["unit_name"] = "Shopping"
    unit["vocabulary"] = [{"word": "doll"}, {"word": "sunglasses"}, {"word": "toy train"}, {"word": "yuan"}]
    unit["sentence_patterns"] = [
        {"pattern": "How much is it? / It's X yuan."},
        {"pattern": "How much are they? / They are X yuan."},
    ]
    unit["dialogue_samples"] = [
        {
            "turns": [
                {"speaker": "Mary", "text_en": "How much is this doll?"},
                {"speaker": "Shopkeeper", "text_en": "It's twenty yuan."},
                {"speaker": "Mary", "text_en": "How much are these sunglasses?"},
                {"speaker": "Shopkeeper", "text_en": "They are thirty yuan."},
            ]
        }
    ]
    unit["unit_task"] = {"task_intro": "学生选择商品并扮演顾客和售货员进行购物对话。"}
    client = StubPracticeClient(
        configured=True,
        response=OpenAICompatiblePracticeChatResponse(
            assistant_message="Great choice! Here is a cute doll. How much is it?",
            request_id="req_demo",
            latency_ms=12,
            usage={"prompt_tokens": 10, "completion_tokens": 9},
        ),
    )
    service = PracticeService(job_service, client)

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
                "student_message": "I want a doll.",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["assistant_message"]["content"] == "Great choice! Ask me, 'How much is the doll?'"


def test_chat_shopping_policy_avoids_repeating_price_nudge(tmp_path):
    job_service = StubJobService()
    unit = job_service.payload["units"][0]
    unit["unit"]["unit_theme"] = "购物与价格询问"
    unit["unit"]["classification"]["unit_name"] = "Shopping"
    unit["vocabulary"] = [{"word": "doll"}, {"word": "toy train"}, {"word": "yuan"}]
    unit["sentence_patterns"] = [{"pattern": "How much is it? / It's X yuan."}]
    unit["dialogue_samples"] = [
        {
            "turns": [
                {"speaker": "Mary", "text_en": "How much is this doll?"},
                {"speaker": "Shopkeeper", "text_en": "It's twenty yuan."},
            ]
        }
    ]
    unit["unit_task"] = {"task_intro": "学生选择商品并扮演顾客和售货员进行购物对话。"}
    service = PracticeService(job_service, StubPracticeClient(configured=True))

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
                "messages": [{"role": "assistant", "content": "Great choice! Ask me, 'How much is the doll?'"}],
                "student_message": "It is nice.",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["assistant_message"]["content"] == "Yes, the doll is nice. Would you like to buy it?"


def test_chat_shopping_policy_answers_price_from_dialogue_example(tmp_path):
    job_service = StubJobService()
    unit = job_service.payload["units"][0]
    unit["unit"]["unit_theme"] = "购物与价格询问"
    unit["unit"]["classification"]["unit_name"] = "Shopping"
    unit["vocabulary"] = [{"word": "doll"}, {"word": "sunglasses"}, {"word": "toy train"}, {"word": "yuan"}]
    unit["sentence_patterns"] = [
        {"pattern": "How much is it? / It's X yuan."},
        {"pattern": "How much are they? / They are X yuan."},
    ]
    unit["dialogue_samples"] = [
        {
            "turns": [
                {"speaker": "Mary", "text_en": "How much is this doll?"},
                {"speaker": "Shopkeeper", "text_en": "It's twenty yuan."},
                {"speaker": "Mary", "text_en": "How much are these sunglasses?"},
                {"speaker": "Shopkeeper", "text_en": "They are thirty yuan."},
            ]
        }
    ]
    unit["unit_task"] = {"task_intro": "学生选择商品并扮演顾客和售货员进行购物对话。"}
    service = PracticeService(job_service, StubPracticeClient(configured=True))

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
                "student_message": "How much are the sunglasses?",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["assistant_message"]["content"] == "They are thirty yuan."


def test_chat_deictic_opening_introduces_anchor_item(tmp_path):
    job_service = StubJobService()
    unit = job_service.payload["units"][0]
    unit["unit"]["unit_theme"] = "Vegetables"
    unit["unit"]["classification"]["unit_name"] = "Vegetables"
    unit["vocabulary"] = [{"word": "tomatoes"}, {"word": "carrots"}, {"word": "beans"}, {"word": "these"}]
    unit["sentence_patterns"] = [
        {"pattern": "What are these/those?"},
        {"pattern": "They're + plural noun."},
        {"pattern": "Are these/those + plural noun?"},
    ]
    unit["unit_task"] = {"task_intro": "学习蔬菜名称，并用英语询问和回答它们是什么。"}
    service = PracticeService(job_service, StubPracticeClient(configured=True))

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

    assert payload["assistant_message"]["content"] == "Hello! Today let's talk about vegetables. Here are some tomatoes. What are these?"


def test_chat_deictic_policy_advances_with_context_after_correct_answer(tmp_path):
    job_service = StubJobService()
    unit = job_service.payload["units"][0]
    unit["unit"]["unit_theme"] = "Vegetables"
    unit["unit"]["classification"]["unit_name"] = "Vegetables"
    unit["vocabulary"] = [{"word": "tomatoes"}, {"word": "carrots"}, {"word": "beans"}, {"word": "these"}]
    unit["sentence_patterns"] = [
        {"pattern": "What are these/those?"},
        {"pattern": "They're + plural noun."},
        {"pattern": "Are these/those + plural noun?"},
    ]
    unit["unit_task"] = {"task_intro": "学习蔬菜名称，并用英语询问和回答它们是什么。"}
    service = PracticeService(job_service, StubPracticeClient(configured=True))

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
                "messages": [{"role": "assistant", "content": "Hello! Today let's talk about vegetables. Here are some tomatoes. What are these?"}],
                "student_message": "They're tomatoes.",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["assistant_message"]["content"] == "Good! Now look at these carrots. Are these tomatoes?"


def test_chat_deictic_policy_explains_after_negative_answer_and_moves_on(tmp_path):
    job_service = StubJobService()
    unit = job_service.payload["units"][0]
    unit["unit"]["unit_theme"] = "Vegetables"
    unit["unit"]["classification"]["unit_name"] = "Vegetables"
    unit["vocabulary"] = [{"word": "tomatoes"}, {"word": "carrots"}, {"word": "beans"}, {"word": "these"}]
    unit["sentence_patterns"] = [
        {"pattern": "What are these/those?"},
        {"pattern": "They're + plural noun."},
        {"pattern": "Are these/those + plural noun?"},
    ]
    unit["unit_task"] = {"task_intro": "学习蔬菜名称，并用英语询问和回答它们是什么。"}
    service = PracticeService(job_service, StubPracticeClient(configured=True))

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
                "messages": [
                    {"role": "assistant", "content": "Hello! Today let's talk about vegetables. Here are some tomatoes. What are these?"},
                    {"role": "user", "content": "They're tomatoes."},
                    {"role": "assistant", "content": "Good! Now look at these carrots. Are these tomatoes?"},
                ],
                "student_message": "No, they aren't.",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["assistant_message"]["content"] == "That's right. They're carrots. Now look at these beans. What are these?"
