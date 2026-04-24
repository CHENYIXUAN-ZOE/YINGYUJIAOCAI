from __future__ import annotations

import pytest

from app.clients.openai_compatible.practice_chat_client import OpenAICompatiblePracticeChatResponse
from app.core.errors import AppError
from app.schemas.job import ParseJob
from app.schemas.practice import PracticeReportRequest
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
    assert payload["turn_tip"]["has_tip"] is False
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


def test_chat_skips_tip_when_shopping_reply_is_already_on_track(tmp_path):
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
                "student_message": "I want a doll.",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["turn_tip"]["has_tip"] is False
    assert payload["turn_tip"]["tips"] == []


def test_chat_returns_shopping_role_alignment_tip(tmp_path):
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
                    {"role": "assistant", "content": "Hello! Welcome to my shop. What would you like to buy today?"},
                    {"role": "user", "content": "I want a doll."},
                    {"role": "assistant", "content": "Great choice! Ask me, 'How much is the doll?'"},
                ],
                "student_message": "It is twenty yuan.",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["turn_tip"]["has_tip"] is True
    assert payload["turn_tip"]["tips"][0]["tip_type"] == "stay_on_task"
    assert payload["turn_tip"]["tips"][0]["example_en"] == "How much is the doll?"


def test_chat_shopping_tip_prefers_current_reply_move_over_unit_target_pattern(tmp_path):
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
                "messages": [{"role": "assistant", "content": "Hello! Welcome to my shop. What would you like to buy today?"}],
                "student_message": "How much is the doll?",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["turn_tip"]["has_tip"] is True
    assert payload["turn_tip"]["tips"][0]["tip_type"] == "too_early"
    assert payload["turn_tip"]["tips"][0]["example_en"] == "I want a doll."
    assert payload["turn_tip"]["tips"][0]["optional_next_en"] == "How much is the doll?"


def test_chat_returns_name_intro_completion_tip(tmp_path):
    job_service = StubJobService()
    job_service.payload["units"][0]["sentence_patterns"] = [
        {"pattern": "What is your name?"},
        {"pattern": "My name is ..."},
    ]
    job_service.payload["units"][0]["unit_task"] = {"task_intro": "打招呼并介绍自己。"}
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
                "messages": [{"role": "assistant", "content": "Hello! What is your name?"}],
                "student_message": "Amy",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["turn_tip"]["has_tip"] is True
    assert payload["turn_tip"]["tips"][0]["tip_type"] == "make_it_full"
    assert payload["turn_tip"]["tips"][0]["example_en"] == "My name is Amy."


def test_chat_skips_tip_when_name_reply_is_already_complete(tmp_path):
    job_service = StubJobService()
    job_service.payload["units"][0]["sentence_patterns"] = [
        {"pattern": "What is your name?"},
        {"pattern": "My name is ..."},
    ]
    job_service.payload["units"][0]["unit_task"] = {"task_intro": "打招呼并介绍自己。"}
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
                "messages": [{"role": "assistant", "content": "Hello! What is your name?"}],
                "student_message": "My name is Amy.",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["turn_tip"]["has_tip"] is False
    assert payload["turn_tip"]["tips"] == []


def test_chat_location_tip_prefers_answer_pattern_not_question_pattern(tmp_path):
    job_service = StubJobService()
    job_service.payload["units"][0]["unit"]["unit_theme"] = "My School"
    job_service.payload["units"][0]["unit"]["classification"]["unit_name"] = "My School"
    job_service.payload["units"][0]["vocabulary"] = [{"word": "library"}, {"word": "playground"}]
    job_service.payload["units"][0]["sentence_patterns"] = [
        {"pattern": "Where is the library?"},
        {"pattern": "It is next to the playground."},
    ]
    job_service.payload["units"][0]["unit_task"] = {"task_intro": "询问并回答地点位置。"}
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
                "messages": [{"role": "assistant", "content": "Where is the library?"}],
                "student_message": "Where is the library?",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["turn_tip"]["has_tip"] is True
    assert payload["turn_tip"]["tips"][0]["tip_type"] == "stay_on_task"
    assert payload["turn_tip"]["tips"][0]["example_en"] == "It is next to the playground."


def test_chat_preference_tip_prefers_current_answer_not_object_naming_pattern(tmp_path):
    job_service = StubJobService()
    job_service.payload["units"][0]["unit"]["unit_theme"] = "Fruits"
    job_service.payload["units"][0]["unit"]["classification"]["unit_name"] = "Fruits"
    job_service.payload["units"][0]["vocabulary"] = [{"word": "apple"}, {"word": "banana"}]
    job_service.payload["units"][0]["sentence_patterns"] = [
        {"pattern": "What is it?"},
        {"pattern": "It's an apple."},
    ]
    job_service.payload["units"][0]["unit_task"] = {"task_intro": "说一说你最喜欢的水果。"}
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
                "messages": [{"role": "assistant", "content": "Hello! Let's talk about fruits. What is your favorite fruit?"}],
                "student_message": "apple",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["turn_tip"]["has_tip"] is True
    assert payload["turn_tip"]["tips"][0]["tip_type"] == "make_it_full"
    assert payload["turn_tip"]["tips"][0]["example_en"] == "I like apples."


def test_chat_yes_no_tip_uses_judgement_reply_after_multi_sentence_prompt(tmp_path):
    job_service = StubJobService()
    job_service.payload["units"][0]["unit"]["unit_theme"] = "Fruits"
    job_service.payload["units"][0]["unit"]["classification"]["unit_name"] = "Fruits"
    job_service.payload["units"][0]["vocabulary"] = [{"word": "banana"}, {"word": "lemon"}]
    job_service.payload["units"][0]["sentence_patterns"] = [
        {"pattern": "It's a lemon."},
        {"pattern": "Is a lemon sour?"},
    ]
    job_service.payload["units"][0]["unit_task"] = {"task_intro": "谈论水果的味道。"}
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
                "messages": [{"role": "assistant", "content": "That is interesting! Most bananas are sweet. Is a lemon sour?"}],
                "student_message": "no",
                "is_opening_turn": False,
            },
        )()
    )

    assert payload["turn_tip"]["has_tip"] is True
    assert payload["turn_tip"]["tips"][0]["tip_type"] == "sound_more_natural"
    assert payload["turn_tip"]["tips"][0]["example_en"] == "No, it isn't."


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


def test_build_report_summarizes_shopping_progress(tmp_path):
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

    report = service.build_report(
        PracticeReportRequest(
            job_id="job_demo",
            unit_id="job_demo_unit_1",
            messages=[
                {"role": "assistant", "content": "Hello! Welcome to my shop. What would you like to buy today?"},
                {"role": "user", "content": "I want a doll."},
                {"role": "assistant", "content": "Great choice! Ask me, 'How much is the doll?'"},
                {"role": "user", "content": "How much is the doll?"},
            ],
        )
    )

    assert "购物场景" in report["summary"]
    assert any("问价句型" in item for item in report["strengths"])
    assert report["pattern_progress"][0]["status"] == "used"
