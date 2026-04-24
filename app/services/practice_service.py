from __future__ import annotations

import re
from typing import Any

from app.clients.openai_compatible.practice_chat_client import OpenAICompatiblePracticeChatClient
from app.core.errors import AppError
from app.schemas.practice import PracticeChatRequest, PracticeReportRequest
from app.services.job_service import JobService

DEFAULT_PROMPT_TEMPLATE_3_4 = """
You are an elementary English oral practice teacher-partner for Grades 3-4.

Your task is to lead a student through a short spoken interaction based on the current textbook unit.
Keep the conversation closely aligned with the unit theme, key vocabulary, and key sentence patterns.
You may add light role-play when it feels natural, but do not go beyond the unit topic or the student's difficulty level.

Interaction style:
- Sound like both a gentle teacher and a natural speaking partner.
- Lead the conversation mainly through guided question-and-answer.
- Ask one main question at a time and wait for the student's response before continuing.
- Use short, clear, familiar spoken English.
- Keep each teacher turn to one or two short sentences.
- Keep most teacher turns under about 20 English words in total.
- Use direct questions and simple follow-up questions.
- Reuse key words and sentence patterns naturally when helpful.
- Encourage the student to say a little more, but do not overload the student.
- Ask concrete, answerable questions about the student, the classroom, the picture, daily actions, likes, or plans.
- If you use role-play, state the scene plainly first in one short sentence.
- Once a role-play scene is set, keep your role consistent until you clearly say the role-play is changing.
- Do not ask the student to guess something that exists only in your mind or in an unstated imaginary scene.
- Do not use abstract, poetic, dramatic, or tricky wording.
- Use English only.

Error handling:
- Do not explicitly point out mistakes.
- Do not give grammar explanations.
- If the student makes mistakes, use light natural reformulation and continue the conversation smoothly.

Conversation goals:
- Aim for about 7 to 8 rounds in total, but do not force the conversation to end mechanically.
- Try to naturally cover the key vocabulary and key sentence patterns during the interaction.
- Keep the conversation centered on the current unit.
- When the main practice goal is basically completed, close naturally.
- If the student wants to continue, keep responding smoothly within the unit topic and age-appropriate difficulty.

Behavior priority:
1. Stay on the current unit topic.
2. Keep the language suitable for Grades 3-4.
3. Prefer concrete, natural, easy-to-answer questions over creative or imaginary ones.
4. Prefer natural continuation over explicit correction.
5. Help the student speak in short, manageable English.
6. Keep the dialogue simple, spoken, and engaging.
""".strip()

DEFAULT_PROMPT_TEMPLATE_5_6 = """
You are an elementary English oral practice teacher-partner for Grades 5-6.

Your task is to lead a student through a short spoken interaction based on the current textbook unit.
Keep the conversation closely aligned with the unit theme, key vocabulary, and key sentence patterns.
You may add light role-play when it feels natural, but do not go beyond the unit topic or the student's difficulty level.

Interaction style:
- Sound like both a supportive teacher and a natural speaking partner.
- Lead the conversation mainly through guided question-and-answer.
- Ask one main question at a time and wait for the student's response before continuing.
- Use clear spoken English with slightly richer sentence variety.
- Keep each teacher turn to one or two short sentences.
- Keep most teacher turns under about 24 English words in total.
- Ask questions that encourage short but meaningful expansion.
- Help the student combine key words and sentence patterns more flexibly.
- Allow slightly more natural follow-up and scene extension when it still fits the unit.
- Keep role-play light, focused, and age-appropriate.
- Once a role-play scene is set, keep your role consistent until you clearly say the role-play is changing.
- Ask concrete, answerable questions grounded in the student, the classroom, daily life, or a clearly stated simple scene.
- If you use role-play, state the scene plainly first instead of jumping into an unstated situation.
- Do not ask the student to guess something that exists only in your mind or in an unstated imaginary scene.
- Do not use abstract, poetic, dramatic, or tricky wording.
- Use English only.

Error handling:
- Do not explicitly point out mistakes.
- Do not give grammar explanations.
- If the student makes mistakes, use light natural reformulation and continue the conversation smoothly.

Conversation goals:
- Aim for about 7 to 8 rounds in total, but do not force the conversation to end mechanically.
- Try to naturally cover the key vocabulary and key sentence patterns during the interaction.
- Keep the conversation centered on the current unit.
- When the main practice goal is basically completed, close naturally.
- If the student wants to continue, keep responding smoothly within the unit topic and school-level difficulty.

Behavior priority:
1. Stay on the current unit topic.
2. Keep the language suitable for Grades 5-6.
3. Prefer concrete, natural, easy-to-answer questions over creative or imaginary ones.
4. Prefer natural continuation over explicit correction.
5. Help the student speak in clear and meaningful English.
6. Keep the dialogue spoken, focused, and engaging.
""".strip()

FINAL_PROMPT_INSTRUCTION = (
    "Now begin the oral practice with one short, natural teacher line. "
    "Keep it concrete, easy to answer, and clearly tied to the unit."
)

_DIGIT_GRADE_PATTERN = re.compile(r"(?<!\d)([3-6])(?:\s*[AaBb上下册]?|\s*年级)(?!\d)", re.IGNORECASE)
_CHINESE_GRADE_MAP = {
    "三年级": 3,
    "四年级": 4,
    "五年级": 5,
    "六年级": 6,
}


class PracticeService:
    def __init__(self, job_service: JobService, practice_client: OpenAICompatiblePracticeChatClient):
        self.job_service = job_service
        self.practice_client = practice_client

    def get_context(self, job_id: str, unit_id: str) -> dict[str, Any]:
        context = self._build_context(job_id, unit_id)
        return {key: value for key, value in context.items() if key != "policy"}

    def _build_context(self, job_id: str, unit_id: str) -> dict[str, Any]:
        job = self.job_service.get_job(job_id)
        payload = self.job_service.get_result(job_id, approved_only=False, include_review_records=False)
        unit_package = self._find_unit_package(payload, unit_id)
        grade_band = self._detect_grade_band(job.file_name, payload, unit_package)
        default_template = self._get_default_template(grade_band)
        unit_context = self._build_unit_context(payload, unit_package)
        practice_policy = self._build_practice_policy(unit_package, unit_context)

        return {
            "job": {
                "job_id": job.job_id,
                "file_name": job.file_name,
                "status": job.status.value,
            },
            "unit": {
                "unit_id": unit_package["unit"]["unit_id"],
                "unit_code": unit_package["unit"]["classification"]["unit_code"],
                "unit_name": unit_package["unit"]["classification"]["unit_name"],
                "unit_theme": unit_context["unit_theme"],
                "unit_task": unit_context["unit_task"],
            },
            "grade_band": grade_band,
            "summary": {
                "vocabulary": unit_context["key_vocabulary"],
                "sentence_patterns": unit_context["key_sentence_patterns"],
            },
            "prompt": {
                "template_version": "v1",
                "default_template": default_template,
                "final_instruction": FINAL_PROMPT_INSTRUCTION,
                "final_prompt_preview": self.build_final_prompt(
                    default_template,
                    unit_context,
                    final_instruction=FINAL_PROMPT_INSTRUCTION,
                ),
            },
            "provider": {
                "name": self.practice_client.provider_name,
                "configured": self.practice_client.is_configured(),
                "model": self.practice_client.model_name(),
            },
            "policy": practice_policy,
        }

    def chat(self, payload: PracticeChatRequest) -> dict[str, Any]:
        if not self.practice_client.is_configured():
            raise AppError(
                "PRACTICE_PROVIDER_NOT_CONFIGURED",
                "Practice provider is not configured",
                status_code=503,
            )

        # Validate job and unit against existing structured content.
        context = self._build_context(payload.job_id, payload.unit_id)

        final_prompt = payload.final_prompt.strip()
        if not final_prompt:
            raise AppError("PRACTICE_INVALID_PROMPT", "final_prompt is required", status_code=400)

        outgoing_messages: list[dict[str, str]] = [{"role": "system", "content": final_prompt}]
        for item in payload.messages:
            content = self._message_content(item).strip()
            if not content:
                raise AppError("PRACTICE_INVALID_MESSAGES", "message content cannot be empty", status_code=400)
            outgoing_messages.append({"role": self._message_role(item), "content": content})

        student_message = (payload.student_message or "").strip()
        if payload.is_opening_turn:
            if student_message:
                raise AppError(
                    "PRACTICE_INVALID_MESSAGES",
                    "student_message must be empty on opening turn",
                    status_code=400,
                )
        else:
            if not student_message:
                raise AppError("PRACTICE_INVALID_MESSAGES", "student_message is required", status_code=400)
            outgoing_messages.append({"role": "user", "content": student_message})

        response = self.practice_client.create_chat_completion(outgoing_messages)
        assistant_message = self._apply_assistant_guardrails(
            context,
            response.assistant_message,
            payload.messages,
            student_message,
            payload.is_opening_turn,
        )
        round_count = self._count_rounds(payload.messages, student_message, payload.is_opening_turn)
        turn_tip = self._build_turn_tip(
            context,
            payload.messages,
            student_message,
            assistant_message,
            payload.is_opening_turn,
        )

        return {
            "assistant_message": {"role": "assistant", "content": assistant_message},
            "round_count": round_count,
            "status_hint": "接近建议轮次，但可继续对话" if round_count >= 7 else "",
            "turn_tip": turn_tip,
            "meta": {
                "request_id": response.request_id,
                "provider": self.practice_client.provider_name,
                "model": self.practice_client.model_name(),
                "latency_ms": response.latency_ms,
                "usage": response.usage,
            },
        }

    def build_report(self, payload: PracticeReportRequest) -> dict[str, Any]:
        context = self._build_context(payload.job_id, payload.unit_id)
        history = self._normalize_history(payload.messages)
        return self._build_session_report(context, history)

    def build_final_prompt(
        self,
        template: str,
        unit_context: dict[str, Any],
        *,
        final_instruction: str = FINAL_PROMPT_INSTRUCTION,
    ) -> str:
        lines = [template.strip(), "", "Current unit context:"]
        lines.append(f"- Textbook: {unit_context['textbook_name']}")
        lines.append(f"- Unit: {unit_context['unit_code']} - {unit_context['unit_name']}")
        lines.append(f"- Unit theme: {unit_context['unit_theme']}")
        lines.append(f"- Key vocabulary: {', '.join(unit_context['key_vocabulary'])}")
        lines.append(f"- Key sentence patterns: {' | '.join(unit_context['key_sentence_patterns'])}")
        if unit_context["unit_task"]:
            lines.append(f"- Optional unit task: {unit_context['unit_task']}")
        for guidance in unit_context.get("practice_guidance", []):
            lines.append(f"- Practice guidance: {guidance}")
        lines.extend(["", final_instruction.strip()])
        return "\n".join(lines).strip()

    def _find_unit_package(self, payload: dict[str, Any], unit_id: str) -> dict[str, Any]:
        for unit_package in payload.get("units", []):
            if unit_package.get("unit", {}).get("unit_id") == unit_id:
                return unit_package
        raise AppError("PRACTICE_CONTEXT_NOT_FOUND", "unit does not exist in current job", status_code=404)

    def _build_unit_context(self, payload: dict[str, Any], unit_package: dict[str, Any]) -> dict[str, Any]:
        unit = unit_package["unit"]
        classification = unit["classification"]
        vocabulary = [
            item.get("word", "").strip()
            for item in unit_package.get("vocabulary", [])
            if item.get("word", "").strip()
        ][:10]
        sentence_patterns = [
            item.get("pattern", "").strip()
            for item in unit_package.get("sentence_patterns", [])
            if item.get("pattern", "").strip()
        ][:5]
        unit_task = unit_package.get("unit_task", {}).get("task_intro", "") or ""
        unit_theme = (
            unit.get("unit_theme")
            or unit_package.get("unit_prompt", {}).get("unit_theme")
            or classification.get("unit_name", "")
        )

        return {
            "textbook_name": payload.get("book", {}).get("textbook_name") or classification.get("textbook_name", ""),
            "unit_code": classification.get("unit_code", ""),
            "unit_name": classification.get("unit_name", ""),
            "unit_theme": unit_theme,
            "unit_task": unit_task.strip(),
            "key_vocabulary": vocabulary,
            "key_sentence_patterns": sentence_patterns,
            "practice_guidance": self._build_practice_guidance(unit_task=unit_task, unit_theme=unit_theme, sentence_patterns=sentence_patterns),
        }

    def _build_practice_policy(self, unit_package: dict[str, Any], unit_context: dict[str, Any]) -> dict[str, Any]:
        if self._is_shopping_unit(unit_context):
            items = self._extract_shopping_items(unit_package)
            return {
                "type": "shopping_roleplay",
                "items": items,
                "price_answers": self._extract_shopping_price_answers(unit_package, items),
            }
        if self._is_deictic_identification_unit(unit_context):
            items = self._extract_deictic_items(unit_package)
            return {
                "type": "deictic_identification",
                "items": items,
                "topic": str(unit_context.get("unit_theme", "") or unit_context.get("unit_name", "") or "these things").strip(),
            }
        return {"type": "default"}

    def _build_practice_guidance(
        self,
        *,
        unit_task: str,
        unit_theme: str,
        sentence_patterns: list[str],
    ) -> list[str]:
        guidance: list[str] = []
        lowered_task = unit_task.lower()
        lowered_theme = unit_theme.lower()
        lowered_patterns = " | ".join(sentence_patterns).lower()
        shopping_markers = ("shopping", "购物", "顾客", "售货员", "店员", "价格", "how much", "yuan", "store", "buy", "sell")
        if any(marker in unit_task or marker in unit_theme for marker in ("购物", "顾客", "售货员", "店员", "价格")) or any(
            marker in lowered_task or marker in lowered_theme or marker in lowered_patterns
            for marker in shopping_markers
            if marker.isascii()
        ):
            guidance.extend(
                [
                    "In this shopping practice, let the student act as the customer first unless the task clearly says otherwise.",
                    "You should usually take the shopkeeper role and answer price questions briefly and naturally.",
                    "Guide the student to ask target questions such as 'How much is ...?' or 'How much are ...?' instead of mainly asking the student to give prices.",
                    "Do not switch roles in the middle of the shopping scene unless you clearly announce a new role-play setup.",
                    "As the shopkeeper, do not ask customer-side price questions such as 'How much is it?' or 'How much are they?'.",
                    "If the student chooses an item but has not asked the price yet, prompt the student to ask about the price instead of asking it yourself.",
                ]
            )
        return guidance

    def _detect_grade_band(self, file_name: str, payload: dict[str, Any], unit_package: dict[str, Any]) -> str:
        candidates = [
            file_name,
            payload.get("book", {}).get("textbook_name", ""),
            payload.get("book", {}).get("grade", ""),
            unit_package.get("unit", {}).get("classification", {}).get("textbook_name", ""),
        ]
        joined = " ".join(str(item or "") for item in candidates)

        for label, value in _CHINESE_GRADE_MAP.items():
            if label in joined:
                return "3-4" if value in {3, 4} else "5-6"

        match = _DIGIT_GRADE_PATTERN.search(joined)
        if match:
            grade = int(match.group(1))
            return "3-4" if grade in {3, 4} else "5-6"

        raise AppError(
            "PRACTICE_INVALID_GRADE_BAND",
            "unable to detect grade band for current textbook",
            status_code=400,
        )

    def _get_default_template(self, grade_band: str) -> str:
        if grade_band == "3-4":
            return DEFAULT_PROMPT_TEMPLATE_3_4
        if grade_band == "5-6":
            return DEFAULT_PROMPT_TEMPLATE_5_6
        raise AppError("PRACTICE_INVALID_GRADE_BAND", "unsupported grade band", status_code=400)

    def _count_rounds(self, prior_messages: list[Any], student_message: str, is_opening_turn: bool) -> int:
        completed_user_turns = sum(1 for item in prior_messages if self._message_role(item) == "user")
        if is_opening_turn:
            return completed_user_turns
        return completed_user_turns + (1 if student_message else 0)

    def _apply_assistant_guardrails(
        self,
        context: dict[str, Any],
        assistant_message: str,
        prior_messages: list[Any],
        student_message: str,
        is_opening_turn: bool,
    ) -> str:
        normalized = " ".join((assistant_message or "").split()).strip()
        if not normalized:
            return normalized
        policy = context.get("policy", {}) if isinstance(context, dict) else {}
        if policy.get("type") == "shopping_roleplay":
            planned = self._plan_shopping_response(policy, prior_messages, student_message, is_opening_turn)
            if planned:
                return planned
        if policy.get("type") == "deictic_identification":
            planned = self._plan_deictic_identification_response(policy, prior_messages, student_message, is_opening_turn)
            if planned:
                return planned
        return normalized

    def _is_shopping_unit(self, unit_context: dict[str, Any]) -> bool:
        joined = " ".join(
            [
                str(unit_context.get("unit_name", "") or ""),
                str(unit_context.get("unit_theme", "") or ""),
                str(unit_context.get("unit_task", "") or ""),
                " | ".join(unit_context.get("key_sentence_patterns", []) or []),
            ]
        ).lower()
        return any(
            marker in joined
            for marker in ["shopping", "购物", "顾客", "售货员", "店员", "价格", "how much", "yuan", "buy", "sell"]
        )

    def _is_deictic_identification_unit(self, unit_context: dict[str, Any]) -> bool:
        patterns = " | ".join(unit_context.get("key_sentence_patterns", []) or []).lower()
        if "what are these" in patterns or "what are those" in patterns:
            return True
        if "are these" in patterns or "are those" in patterns:
            return True
        return False

    def _extract_deictic_items(self, unit_package: dict[str, Any]) -> list[str]:
        ignored = {"these", "those", "shopping list", "list"}
        items: list[str] = []
        for item in unit_package.get("vocabulary", []):
            word = str(item.get("word", "") or "").strip().lower()
            if not word or word in ignored:
                continue
            if word not in items:
                items.append(word)
        return items

    def _extract_shopping_items(self, unit_package: dict[str, Any]) -> list[str]:
        ignored = {"yuan", "how much", "thank you", "here is the money", "eleven", "twenty", "fifty", "one hundred"}
        items: list[str] = []
        for item in unit_package.get("vocabulary", []):
            word = str(item.get("word", "") or "").strip().lower()
            if not word or word in ignored:
                continue
            if word not in items:
                items.append(word)
        return items

    def _extract_shopping_price_answers(self, unit_package: dict[str, Any], items: list[str]) -> dict[str, str]:
        price_answers: dict[str, str] = {}
        item_set = set(items)
        for dialogue in unit_package.get("dialogue_samples", []):
            turns = dialogue.get("turns", []) or []
            for index in range(len(turns) - 1):
                current = turns[index]
                nxt = turns[index + 1]
                current_text = str(current.get("text_en", "") or "")
                next_text = str(nxt.get("text_en", "") or "").strip()
                if not current_text or not next_text:
                    continue
                lowered = current_text.lower()
                if "how much" not in lowered:
                    continue
                for item in item_set:
                    if item in lowered and item not in price_answers:
                        price_answers[item] = next_text
        return price_answers

    def _plan_shopping_response(
        self,
        policy: dict[str, Any],
        prior_messages: list[Any],
        student_message: str,
        is_opening_turn: bool,
    ) -> str:
        items = policy.get("items", []) if isinstance(policy, dict) else []
        price_answers = policy.get("price_answers", {}) if isinstance(policy, dict) else {}
        normalized_student = " ".join((student_message or "").split()).strip()
        if is_opening_turn:
            return "Hello! Welcome to my shop. What would you like to buy today?"

        if not normalized_student:
            return ""

        lowered_student = normalized_student.lower()
        history = self._normalize_history(prior_messages)
        current_item = (
            self._detect_item_in_text(lowered_student, items)
            or self._last_student_item(history, items)
            or self._last_referenced_item(history, items)
        )

        if any(token in lowered_student for token in ["goodbye", "bye"]):
            return "Goodbye!"
        if "here is the money" in lowered_student:
            return "Thank you!"
        if "thank you" in lowered_student:
            return "You're welcome."

        if "how much" in lowered_student:
            if current_item and current_item in price_answers:
                return price_answers[current_item]
            if "are they" in lowered_student:
                return "They are thirty yuan."
            return "It is twenty yuan."

        if current_item:
            if not self._has_price_nudge_for_item(history, current_item):
                starter = "Great choice!" if any(token in lowered_student for token in ["want", "like", "take"]) else "Okay!"
                return f"{starter} Ask me, '{self._shopping_price_question(current_item)}'"

            if self._student_mentions_multiple_items(lowered_student, items):
                choices = self._items_in_text(lowered_student, items)
                if len(choices) >= 2:
                    return f"Would you like the {choices[0]} or the {choices[1]} first?"

            return f"Yes, the {current_item} is nice. Would you like to buy it?"

        if any(token in lowered_student for token in ["want", "buy", "take", "like"]):
            return "What would you like to buy?"

        return "What would you like to buy today?"

    def _plan_deictic_identification_response(
        self,
        policy: dict[str, Any],
        prior_messages: list[Any],
        student_message: str,
        is_opening_turn: bool,
    ) -> str:
        items = policy.get("items", []) if isinstance(policy, dict) else []
        topic = str(policy.get("topic", "") or "these things").strip().lower()
        normalized_student = " ".join((student_message or "").split()).strip()
        history = self._normalize_history(prior_messages)

        if not items:
            if is_opening_turn:
                return f"Hello! Today let's talk about {topic}. What are these?"
            return "Can you answer with a short sentence?"

        if is_opening_turn:
            first_item = items[0]
            return f"Hello! Today let's talk about {topic}. Here are some {first_item}. What are these?"

        lowered_student = normalized_student.lower()
        last_assistant = next((message for message in reversed(history) if message.get("role") == "assistant"), {})
        last_content = last_assistant.get("content", "").lower()
        current_item = self._last_anchor_item(history, items) or items[0]
        next_item = self._next_item(items, current_item)
        previous_item = self._previous_item(items, current_item)

        if "what are these" in lowered_student or "what are those" in lowered_student:
            return f"They're {current_item}."
        if "are these" in lowered_student or "are those" in lowered_student:
            if current_item == previous_item or not current_item:
                return "Yes, they are."
            return f"No, they aren't. They're {current_item}."

        if "what are these" in last_content or "what are those" in last_content:
            if self._student_matches_item_response(lowered_student, current_item):
                if next_item:
                    return f"Good! Now look at these {next_item}. Are these {current_item}?"
                return f"Good! They're {current_item}."
            return f"They're {current_item}. Can you say, 'They're {current_item}'?"

        if "are these" in last_content or "are those" in last_content:
            if self._is_yes_no_negative(lowered_student):
                if next_item:
                    return f"That's right. They're {current_item}. Now look at these {next_item}. What are these?"
                return f"That's right. They're {current_item}."
            if self._is_yes_no_positive(lowered_student):
                if next_item:
                    return f"Not quite. They're {current_item}. Now look at these {next_item}. What are these?"
                return f"They're {current_item}."
            if self._student_matches_item_response(lowered_student, current_item):
                if next_item:
                    return f"Good! Now look at these {next_item}. What are these?"
                return f"Good! They're {current_item}."
            return f"They're {current_item}. Can you say, 'They're {current_item}'?"

        return f"Here are some {current_item}. What are these?"

    def _build_turn_tip(
        self,
        context: dict[str, Any],
        prior_messages: list[Any],
        student_message: str,
        assistant_message: str,
        is_opening_turn: bool,
    ) -> dict[str, Any]:
        if is_opening_turn or not student_message.strip():
            return {"has_tip": False, "tips": []}

        policy = context.get("policy", {}) if isinstance(context, dict) else {}
        history = self._normalize_history(prior_messages)

        if policy.get("type") == "shopping_roleplay":
            tips = self._build_shopping_turn_tips(policy, history, student_message, assistant_message)
        elif policy.get("type") == "deictic_identification":
            tips = self._build_deictic_turn_tips(policy, history, student_message, assistant_message)
        else:
            tips = self._build_general_turn_tips(context, history, student_message)

        return {"has_tip": bool(tips), "tips": tips[:2]}

    def _build_session_report(self, context: dict[str, Any], history: list[dict[str, str]]) -> dict[str, Any]:
        policy = context.get("policy", {}) if isinstance(context, dict) else {}
        if policy.get("type") == "shopping_roleplay":
            return self._build_shopping_report(context, policy, history)
        if policy.get("type") == "deictic_identification":
            return self._build_deictic_report(context, policy, history)
        return self._build_general_report(context, history)

    def _build_shopping_turn_tips(
        self,
        policy: dict[str, Any],
        history: list[dict[str, str]],
        student_message: str,
        assistant_message: str,
    ) -> list[dict[str, str]]:
        items = policy.get("items", []) if isinstance(policy, dict) else []
        lowered_student = " ".join(student_message.split()).strip().lower()
        current_item = (
            self._detect_item_in_text(lowered_student, items)
            or self._last_student_item(history, items)
            or self._last_referenced_item(history, items)
        )
        expected_move = self._infer_shopping_expected_move(history, current_item)
        actual_move = self._infer_shopping_actual_move(lowered_student, current_item, items)

        if expected_move == "choose_item":
            if actual_move == "price_answer":
                return [
                    self._build_tip(
                        tip_type="stay_on_task",
                        title="这一步先别跳到报价",
                        message_cn="老师刚在问你想买什么，这一步先说商品，会更符合对话顺序。",
                        example_en=self._shopping_choice_sentence(current_item or "doll"),
                        reason_cn="先完成“选商品”，再进入问价，会比直接报价格更自然。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "ask_price":
                return [
                    self._build_tip(
                        tip_type="too_early",
                        title="这一步可以先把商品说出来",
                        message_cn="你已经想到下一步了，但老师这一句更希望你先说想买什么。",
                        example_en=self._shopping_choice_sentence(current_item or "doll"),
                        reason_cn="先选商品，再问价格，整段购物对话会更顺。",
                        optional_next_en=self._shopping_price_question(current_item or "doll"),
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "choose_item_keyword":
                return [
                    self._build_tip(
                        tip_type="make_it_full",
                        title="这句话可以再完整一点",
                        message_cn="你已经提到了商品，再补成完整句，店员会更容易接着往下说。",
                        example_en=self._shopping_choice_sentence(current_item or lowered_student or "doll"),
                        reason_cn="先把想买什么说完整，再进入下一步会更自然。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "choose_item":
                return [
                    self._build_tip(
                        tip_type="next_step",
                        title="这一步答得不错",
                        message_cn="你已经把商品说清楚了。想继续的话，下一句可以自然地去问价格。",
                        example_en=self._shopping_choice_sentence(current_item or "doll"),
                        reason_cn="这样更符合购物场景里“选商品 -> 问价格”的顺序。",
                        optional_next_en=self._shopping_price_question(current_item or "doll"),
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if expected_move == "ask_price":
            if actual_move == "price_answer":
                prompt_item = current_item or "it"
                return [
                    self._build_tip(
                        tip_type="stay_on_task",
                        title="这一步可以换成顾客会说的话",
                        message_cn="这一句更适合由顾客来问价格，而不是直接报价格。",
                        example_en=self._shopping_price_question(prompt_item) if prompt_item != "it" else "How much is it?",
                        reason_cn="这样能把学生放回顾客这一侧，也更符合本轮练习目标。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "choose_item":
                return [
                    self._build_tip(
                        tip_type="next_step",
                        title="这一步可以再推进半步",
                        message_cn="你已经把商品说清楚了，这一句可以继续主动问价格。",
                        example_en=self._shopping_price_question(current_item or "doll"),
                        reason_cn="老师这一句更希望你把对话推进到问价。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "choose_item_keyword":
                return [
                    self._build_tip(
                        tip_type="next_step",
                        title="这一步更适合直接问价格",
                        message_cn="这里已经不需要再重复商品名了，可以直接把价格问出来。",
                        example_en=self._shopping_price_question(current_item or "doll"),
                        reason_cn="这样会更贴近当前这一步真正要练的动作。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "ask_price":
                return [
                    self._build_tip(
                        tip_type="next_step",
                        title="这一步推进得不错",
                        message_cn="你已经主动问价格了。这一句就已经答到点上了，接下来可以继续决定买不买。",
                        example_en=self._shopping_price_question(current_item or "doll"),
                        reason_cn="真实购物对话里，问完价格后通常会进入购买决定。",
                        optional_next_en="I will take it.",
                        secondary_next_en="No, thank you.",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if expected_move == "accept_or_decline":
            if actual_move in {"accept_item", "decline_item"}:
                decision_example = "I will take it." if actual_move == "accept_item" else "No, thank you."
                return [
                    self._build_tip(
                        tip_type="next_step",
                        title="这一步回答到位了",
                        message_cn="你已经做出了购买决定，下一句可以付款、致谢或自然收尾。",
                        example_en=decision_example,
                        reason_cn="这会让购物对话更完整。",
                        optional_next_en="Here is the money." if actual_move == "accept_item" else "Thank you.",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "ask_price":
                return [
                    self._build_tip(
                        tip_type="stay_on_task",
                        title="这一步更适合做购买决定",
                        message_cn="价格已经出来了，这里更适合决定买不买，而不是再回到问价。",
                        example_en="I will take it.",
                        reason_cn="这样更符合当前这一轮老师在等你的回应。",
                        optional_next_en="No, thank you.",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if expected_move == "pay_and_close":
            if actual_move == "pay":
                return [
                    self._build_tip(
                        tip_type="next_step",
                        title="这一步已经很完整了",
                        message_cn="你已经完成付款，下一句可以礼貌地结束对话。",
                        example_en="Here is the money.",
                        reason_cn="这样会让这一轮收得更自然。",
                        optional_next_en="Thank you. Goodbye!",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "thanks":
                return [
                    self._build_tip(
                        tip_type="sound_more_natural",
                        title="这一步可以再补一个动作",
                        message_cn="如果前面已经买下来了，除了致谢，也可以把付款表达说出来。",
                        example_en="Here is the money.",
                        reason_cn="这样会更贴近完整的购物收尾。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if self._sounds_like_customer_price_answer(lowered_student):
            prompt_item = current_item or "it"
            return [
                self._build_tip(
                    tip_type="stay_on_task",
                    title="这一步可以换成顾客会说的话",
                    message_cn="在购物对话里，价格通常由店员来回答。你先问价格，会更像真实对话。",
                    example_en=self._shopping_price_question(prompt_item) if prompt_item != "it" else "How much is it?",
                    reason_cn="这样能把学生放回顾客这一侧，也更符合本轮练习目标。",
                    expected_move=expected_move,
                    actual_move=actual_move,
                )
            ]

        return []

    def _build_deictic_turn_tips(
        self,
        policy: dict[str, Any],
        history: list[dict[str, str]],
        student_message: str,
        assistant_message: str,
    ) -> list[dict[str, str]]:
        items = policy.get("items", []) if isinstance(policy, dict) else []
        lowered_student = " ".join(student_message.split()).strip().lower()
        current_item = self._detect_item_in_text(lowered_student, items) or self._last_anchor_item(history, items)
        expected_move = self._infer_deictic_expected_move(history)
        actual_move = self._infer_deictic_actual_move(lowered_student, current_item)

        if expected_move == "name_object":
            if actual_move == "yes_no_only":
                return [
                    self._build_tip(
                        tip_type="stay_on_task",
                        title="这一步更适合直接说出它们是什么",
                        message_cn="老师这一句是在问这些东西是什么，所以比起 yes / no，更适合直接说名称。",
                        example_en=f"They're {current_item}." if current_item else "They're carrots.",
                        reason_cn="这样会更贴近当前这一轮的回答目标。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "item_keyword":
                return [
                    self._build_tip(
                        tip_type="make_it_full",
                        title="这句话可以更完整一点",
                        message_cn="你已经说对了物品名，再补成完整句会更像自然回答。",
                        example_en=f"They're {current_item}.",
                        reason_cn="这一轮练的是“看到这些东西后，用完整句说出它们是什么”。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "item_full":
                next_item = self._next_item(items, current_item) or current_item
                return [
                    self._build_tip(
                        tip_type="next_step",
                        title="这一步做得不错",
                        message_cn="你已经用完整句回答了，下一步可以继续练判断句，或者换一组新物品。",
                        example_en=f"They're {current_item}.",
                        reason_cn="这一类单元通常会在“命名”和“判断”之间切换练习。",
                        optional_next_en=f"Are these {next_item}?",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if expected_move == "judge_yes_no":
            if actual_move == "item_keyword":
                prefix = "No, they aren't." if current_item else "No, they aren't."
                return [
                    self._build_tip(
                        tip_type="stay_on_task",
                        title="这一步可以先做判断",
                        message_cn="老师这一句更希望你先判断对不对，再补名称会更完整。",
                        example_en=f"{prefix} They're {current_item}." if current_item else "No, they aren't. They're carrots.",
                        reason_cn="先给 yes / no，再补名称，会更贴近当前这一轮。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "yes_no_only_negative":
                example = f"No, they aren't. They're {current_item}." if current_item else "No, they aren't. They're carrots."
                return [
                    self._build_tip(
                        tip_type="make_it_full",
                        title="这一步可以再多说半句",
                        message_cn="只回答 yes / no 已经不错了，再补出真正的名称会更完整。",
                        example_en=example,
                        reason_cn="这样既保留判断句，也把答案说完整了。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "yes_no_only_positive":
                return [
                    self._build_tip(
                        tip_type="sound_more_natural",
                        title="这一步可以更自然",
                        message_cn="如果老师是在让你判断，对应地用完整的 yes 句会更自然。",
                        example_en="Yes, they are.",
                        reason_cn="完整回答会比只说 yes 更清楚。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "item_full":
                return [
                    self._build_tip(
                        tip_type="stay_on_task",
                        title="这一步可以先判断再补名称",
                        message_cn="你已经说出答案了，但这一句更适合先给 yes / no，再决定要不要补名称。",
                        example_en="No, they aren't.",
                        reason_cn="这样更贴近老师这一轮真正期待的回答形式。",
                        optional_next_en=f"They're {current_item}." if current_item else "",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if current_item and self._looks_like_incomplete_reply(lowered_student):
            return [
                self._build_tip(
                    tip_type="make_it_full",
                    title="这句话可以更完整一点",
                    message_cn="你已经说对了物品名，再补成完整句会更像自然回答。",
                    example_en=f"They're {current_item}.",
                    reason_cn="这一轮练的是“看到这些东西后，用完整句说出它们是什么”。",
                    expected_move=expected_move,
                    actual_move=actual_move,
                )
            ]

        return []

    def _build_general_turn_tips(
        self,
        context: dict[str, Any],
        history: list[dict[str, str]],
        student_message: str,
    ) -> list[dict[str, str]]:
        lowered_student = " ".join(student_message.split()).strip().lower()
        last_assistant = next((message for message in reversed(history) if message.get("role") == "assistant"), {})
        last_prompt = last_assistant.get("content", "").lower()
        target_patterns = context.get("summary", {}).get("sentence_patterns", []) if isinstance(context, dict) else []
        vocabulary = context.get("summary", {}).get("vocabulary", []) if isinstance(context, dict) else []
        expected_move = self._infer_general_expected_move(last_prompt, target_patterns)
        actual_move = self._infer_general_actual_move(expected_move, student_message, vocabulary)

        if expected_move == "say_name":
            guessed_name = self._guess_name_from_reply(student_message)
            if actual_move == "name_keyword":
                return [
                    self._build_tip(
                        tip_type="make_it_full",
                        title="这句话可以更完整一点",
                        message_cn="如果是在自我介绍，把名字放进完整句里会更自然。",
                        example_en=f"My name is {guessed_name}." if guessed_name else "My name is Amy.",
                        reason_cn="这样更贴近问名字这一步的自然回答方式。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "on_track":
                current_example = f"My name is {guessed_name}." if guessed_name else "My name is Amy."
                return [
                    self._build_tip(
                        tip_type="next_step",
                        title="这一步回答到位了",
                        message_cn="你已经完成了自我介绍，下一句可以轻松地继续问候或反问对方。",
                        example_en=current_example,
                        reason_cn="这样会让开场更像自然对话。",
                        optional_next_en="Nice to meet you.",
                        secondary_next_en="What is your name?",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if expected_move == "state_plan":
            if actual_move == "keyword_only":
                return [
                    self._build_tip(
                        tip_type="make_it_full",
                        title="这句话可以更像完整回答",
                        message_cn="如果在说计划，把动作放进 “I will ...” 里面会更自然。",
                        example_en=self._weekend_plan_example(student_message, vocabulary),
                        reason_cn="这样更贴近计划类单元里这一轮真正需要的回答方式。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "on_track":
                current_example = self._weekend_plan_example(student_message, vocabulary)
                return [
                    self._build_tip(
                        tip_type="next_step",
                        title="这一步已经答对了",
                        message_cn="你已经说出了计划，下一句可以再补一个地点、时间或同伴。",
                        example_en=current_example,
                        reason_cn="这样会让回答更完整，但不会太难。",
                        optional_next_en="I will go to the park with my mom.",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if expected_move == "state_preference":
            preference_example = self._preference_example(student_message, vocabulary)
            if actual_move == "keyword_only":
                return [
                    self._build_tip(
                        tip_type="make_it_full",
                        title="这一步可以更像完整回答",
                        message_cn="如果是在表达喜好，可以直接把喜欢不喜欢说出来。",
                        example_en=preference_example,
                        reason_cn="这样会更贴近“Do you like ...?” 这一类问答。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "yes_no_only":
                return [
                    self._build_tip(
                        tip_type="sound_more_natural",
                        title="这一步可以更自然",
                        message_cn="只说 yes / no 也可以，但再补半句会更像真实对话。",
                        example_en=f"Yes, I do. {preference_example}",
                        reason_cn="这样既完成判断，也顺手把喜好说清楚。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if expected_move == "give_location":
            if actual_move == "question_back":
                return [
                    self._build_tip(
                        tip_type="stay_on_task",
                        title="这一步更适合回答位置",
                        message_cn="老师这一句是在问地点，所以这里更适合直接回答位置，而不是重复问题。",
                        example_en=self._location_answer_example(target_patterns, vocabulary),
                        reason_cn="当前这一轮需要的是“回答在哪里”，不是再问一次“在哪里”。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "keyword_only":
                return [
                    self._build_tip(
                        tip_type="make_it_full",
                        title="这句话可以再完整一点",
                        message_cn="如果你知道位置，可以把地点放进完整句里。",
                        example_en=self._location_answer_example(target_patterns, vocabulary),
                        reason_cn="这样会更贴近位置问答里的自然回答。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move == "on_track":
                current_example = self._location_answer_example(target_patterns, vocabulary)
                return [
                    self._build_tip(
                        tip_type="next_step",
                        title="这一步回答得不错",
                        message_cn="你已经说出了位置，下一句可以继续确认对方有没有听懂。",
                        example_en=current_example,
                        reason_cn="位置类单元通常会继续补一个方向或确认句。",
                        optional_next_en="It is next to the library.",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if expected_move == "name_object":
            if actual_move == "keyword_only":
                return [
                    self._build_tip(
                        tip_type="make_it_full",
                        title="这句话可以更完整一点",
                        message_cn="如果老师是在问这是什么，把物品放进完整句里会更自然。",
                        example_en=self._object_answer_example(target_patterns, student_message),
                        reason_cn="这样会更贴近“问物品名称”这一轮的回答方式。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if expected_move == "answer_yes_no":
            if actual_move == "yes_no_only":
                polarity_example = "No, it isn't." if self._is_yes_no_negative(lowered_student) else "Yes, it is."
                return [
                    self._build_tip(
                        tip_type="sound_more_natural",
                        title="这一步可以更自然",
                        message_cn="只说 yes / no 也可以，如果想更像完整对话，可以把判断说完整。",
                        example_en=polarity_example,
                        reason_cn="这样会更贴近判断句里的自然回答。",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]
            if actual_move not in {"yes_no_only", "yes_no_plus_detail", "on_track"}:
                return [
                    self._build_tip(
                        tip_type="stay_on_task",
                        title="这一步可以先做判断",
                        message_cn="老师这一句更希望你先回答 yes 或 no，再决定要不要补细节。",
                        example_en="Yes, it is.",
                        reason_cn="这样会更贴近当前这一轮最直接的回答方式。",
                        optional_next_en="No, it isn't.",
                        expected_move=expected_move,
                        actual_move=actual_move,
                    )
                ]

        if "what is your name" in last_prompt and "my name" not in lowered_student and "i am" not in lowered_student:
            return [
                self._build_tip(
                    tip_type="make_it_full",
                    title="这句话可以更完整一点",
                    message_cn="如果是在自我介绍，把名字放进完整句里会更自然。",
                    example_en=f"My name is {guessed_name}." if guessed_name else "My name is Amy.",
                    reason_cn="这样更贴近问名字这一步的自然回答方式。",
                    expected_move=expected_move,
                    actual_move=actual_move,
                )
            ]

        if self._looks_like_incomplete_reply(lowered_student) and target_patterns:
            return [
                self._build_tip(
                    tip_type="make_it_full",
                    title="这句话可以再完整一点",
                    message_cn="你已经开始回答了，再补成完整句，会更像真实对话。",
                    example_en=self._general_response_example(expected_move, target_patterns, vocabulary, student_message),
                    reason_cn="这里优先看“这一步该怎么答”，而不是直接套整单元的目标句型。",
                    expected_move=expected_move,
                    actual_move=actual_move,
                )
            ]

        if target_patterns:
            return [
                self._build_tip(
                    tip_type="next_step",
                    title="这一步可以继续往前走",
                    message_cn="你已经跟上了对话，下一轮可以继续把这一类回答说得更完整、更自然。",
                    example_en=self._general_response_example(expected_move, target_patterns, vocabulary, student_message),
                    reason_cn="这里先参考当前这一轮应该出现的回答形式。",
                    expected_move=expected_move,
                    actual_move=actual_move,
                )
            ]
        return []

    def _build_shopping_report(self, context: dict[str, Any], policy: dict[str, Any], history: list[dict[str, str]]) -> dict[str, Any]:
        user_messages = [message.get("content", "") for message in history if message.get("role") == "user"]
        items = policy.get("items", []) if isinstance(policy, dict) else []
        chose_item = any(self._detect_item_in_text(message.lower(), items) for message in user_messages)
        asked_price = any("how much" in message.lower() for message in user_messages)
        decided = any(token in message.lower() for message in user_messages for token in ["i will take", "i want", "no, thank", "no thank"])
        paid = any("here is the money" in message.lower() for message in user_messages)

        strengths: list[str] = []
        improvements: list[str] = []
        next_steps: list[str] = []

        if chose_item:
            strengths.append("你已经能主动说出自己想买什么。")
        else:
            improvements.append("可以更快进入购物场景，先明确说出想买的商品。")
        if asked_price:
            strengths.append("你已经主动使用了问价句型。")
        else:
            improvements.append("可以更主动练习问价句型。")
            next_steps.append("下次优先完成“选商品 -> 问价格”的前两步。")
        if decided:
            strengths.append("你已经开始向“决定是否购买”这一步推进了。")
        else:
            improvements.append("问完价格后，可以继续练习“买不买”的表达。")
        if paid:
            strengths.append("你已经把购物对话推进到付款环节了。")

        if not next_steps:
            next_steps.append("下次尝试完整练完“选商品 -> 问价格 -> 决定购买 -> 付款”这一整条链路。")

        pattern_progress = [
            {
                "pattern": "How much is/are ...?",
                "status": "used" if asked_price else "needs_more_practice",
                "note_cn": "问价句型是这个单元的核心目标。"
            },
            {
                "pattern": "Here is the money.",
                "status": "used" if paid else "not_reached",
                "note_cn": "付款表达通常出现在购物对话的后半段。"
            },
        ]

        summary = (
            "你已经能跟着购物场景继续对话了。"
            if chose_item
            else "这次对话已经进入购物主题，但还可以更快进入目标句型。"
        )

        return {
            "summary": summary,
            "strengths": strengths,
            "improvements": improvements,
            "pattern_progress": pattern_progress,
            "next_steps": next_steps,
        }

    def _build_deictic_report(self, context: dict[str, Any], policy: dict[str, Any], history: list[dict[str, str]]) -> dict[str, Any]:
        user_messages = [message.get("content", "") for message in history if message.get("role") == "user"]
        items = policy.get("items", []) if isinstance(policy, dict) else []
        named_item = any(self._detect_item_in_text(message.lower(), items) for message in user_messages)
        used_full_sentence = any("they are" in message.lower() or "they're" in message.lower() for message in user_messages)
        used_yes_no = any(self._is_yes_no_positive(message.lower()) or self._is_yes_no_negative(message.lower()) for message in user_messages)

        strengths: list[str] = []
        improvements: list[str] = []

        if named_item:
            strengths.append("你已经能识别并说出部分物品名称。")
        else:
            improvements.append("可以更主动说出这些东西的名称。")
        if used_full_sentence:
            strengths.append("你已经开始用完整句来回答了。")
        else:
            improvements.append("回答时可以尽量用完整句，比如 “They’re tomatoes.”")
        if used_yes_no:
            strengths.append("你已经练到了判断句的回答。")
        else:
            improvements.append("除了命名以外，也可以继续练习 yes / no 判断句。")

        return {
            "summary": "你已经进入了“these / those”这一类指物问答练习。",
            "strengths": strengths,
            "improvements": improvements,
            "pattern_progress": [
                {
                    "pattern": "What are these/those?",
                    "status": "used" if named_item else "needs_more_practice",
                    "note_cn": "这一句型对应“看到物品后说出它们是什么”。"
                },
                {
                    "pattern": "They’re + plural noun.",
                    "status": "used" if used_full_sentence else "needs_more_practice",
                    "note_cn": "完整回答会比只说名词更自然。"
                },
            ],
            "next_steps": [
                "下次可以继续练习“先看见物品，再用完整句回答它们是什么”。",
                "如果答完名称，还可以继续练“Are these/those ...?”"
            ],
        }

    def _build_general_report(self, context: dict[str, Any], history: list[dict[str, str]]) -> dict[str, Any]:
        user_messages = [message.get("content", "") for message in history if message.get("role") == "user"]
        target_patterns = context.get("summary", {}).get("sentence_patterns", []) if isinstance(context, dict) else []
        used_full_sentence = any(len(message.split()) >= 3 for message in user_messages)

        strengths = ["你已经能跟着当前单元继续对话。"] if user_messages else []
        improvements = [] if used_full_sentence else ["回答可以再完整一点，更贴近本单元目标句型。"]
        next_steps = ["下次优先尝试把回答放进完整句里。"]

        return {
            "summary": "这次对话已经围绕当前单元展开。",
            "strengths": strengths,
            "improvements": improvements,
            "pattern_progress": [
                {
                    "pattern": pattern,
                    "status": "in_progress",
                    "note_cn": "可以继续围绕这个句型多练几轮。"
                }
                for pattern in target_patterns[:2]
            ],
            "next_steps": next_steps,
        }

    def _normalize_history(self, prior_messages: list[Any]) -> list[dict[str, str]]:
        history: list[dict[str, str]] = []
        for item in prior_messages:
            role = self._message_role(item)
            content = " ".join(self._message_content(item).split()).strip()
            if role and content:
                history.append({"role": role, "content": content})
        return history

    def _detect_item_in_text(self, text: str, items: list[str]) -> str:
        for item in sorted(items, key=len, reverse=True):
            if item in text:
                return item
        return ""

    def _items_in_text(self, text: str, items: list[str]) -> list[str]:
        found: list[str] = []
        for item in sorted(items, key=len, reverse=True):
            if item in text and item not in found:
                found.append(item)
        return found

    def _last_student_item(self, history: list[dict[str, str]], items: list[str]) -> str:
        for message in reversed(history):
            if message.get("role") != "user":
                continue
            detected = self._detect_item_in_text(message.get("content", "").lower(), items)
            if detected:
                return detected
        return ""

    def _last_referenced_item(self, history: list[dict[str, str]], items: list[str]) -> str:
        for message in reversed(history):
            detected = self._detect_item_in_text(message.get("content", "").lower(), items)
            if detected:
                return detected
        return ""

    def _last_anchor_item(self, history: list[dict[str, str]], items: list[str]) -> str:
        for message in reversed(history):
            content = message.get("content", "").lower()
            for item in sorted(items, key=len, reverse=True):
                if re.search(rf"(?:here are some|look at these|look at those|these are|those are)\s+{re.escape(item)}\b", content):
                    return item
            detected = self._detect_item_in_text(content, items)
            if detected:
                return detected
        return ""

    def _has_price_nudge_for_item(self, history: list[dict[str, str]], item: str) -> bool:
        target = f"how much is the {item}"
        for message in history:
            if message.get("role") != "assistant":
                continue
            lowered = message.get("content", "").lower()
            if target in lowered:
                return True
        return False

    def _student_mentions_multiple_items(self, text: str, items: list[str]) -> bool:
        return len(self._items_in_text(text, items)) >= 2

    def _student_matches_item_response(self, text: str, item: str) -> bool:
        if not item:
            return False
        return item in text or f"they are {item}" in text or f"they're {item}" in text

    def _is_yes_no_negative(self, text: str) -> bool:
        return any(token in text for token in ["no, they aren't", "no they aren't", "no, they are not", "no they are not", "no"])

    def _is_yes_no_positive(self, text: str) -> bool:
        return any(token in text for token in ["yes, they are", "yes they are", "yes"])

    def _next_item(self, items: list[str], current_item: str) -> str:
        if current_item not in items:
            return items[0] if items else ""
        index = items.index(current_item)
        if index + 1 < len(items):
            return items[index + 1]
        return ""

    def _previous_item(self, items: list[str], current_item: str) -> str:
        if current_item not in items:
            return ""
        index = items.index(current_item)
        if index > 0:
            return items[index - 1]
        return current_item

    def _shopping_price_question(self, item: str) -> str:
        if item.endswith("s") and item != "glasses":
            return f"How much are the {item}?"
        if item in {"sunglasses", "glasses"}:
            return f"How much are the {item}?"
        return f"How much is the {item}?"

    def _shopping_choice_sentence(self, item: str) -> str:
        if item in {"sunglasses", "glasses"} or item.endswith("s"):
            return f"I want the {item}."
        article = "an" if item[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
        return f"I want {article} {item}."

    def _build_tip(
        self,
        *,
        tip_type: str,
        title: str,
        message_cn: str,
        example_en: str,
        reason_cn: str,
        optional_next_en: str = "",
        secondary_next_en: str = "",
        expected_move: str = "",
        actual_move: str = "",
    ) -> dict[str, str]:
        example_label_cn = self._tip_example_label(tip_type, optional_next_en)
        optional_label_cn = self._tip_optional_label(tip_type)
        payload = {
            "tip_type": tip_type,
            "title": title,
            "message_cn": message_cn,
            "example_en": example_en,
            "reason_cn": reason_cn,
            "example_label_cn": example_label_cn,
        }
        if optional_next_en:
            payload["optional_next_en"] = optional_next_en
            payload["optional_next_label_cn"] = optional_label_cn
        if secondary_next_en:
            payload["secondary_next_en"] = secondary_next_en
            payload["secondary_next_label_cn"] = "也可以这样接"
        if expected_move:
            payload["expected_move"] = expected_move
        if actual_move:
            payload["actual_move"] = actual_move
        return payload

    def _infer_shopping_expected_move(self, history: list[dict[str, str]], current_item: str) -> str:
        if not history:
            return "choose_item"
        last_assistant = next((message for message in reversed(history) if message.get("role") == "assistant"), {})
        prompt = last_assistant.get("content", "").lower()
        if "what would you like to buy" in prompt or "what do you want to buy" in prompt:
            return "choose_item"
        if "ask me" in prompt and "how much" in prompt:
            return "ask_price"
        if "want to know the price" in prompt or "know the price" in prompt:
            return "ask_price"
        if "would you like to buy it" in prompt or "do you want to buy it" in prompt:
            return "accept_or_decline"
        if "yuan" in prompt or re.search(r"\b(it is|it's|they are|they're)\b", prompt):
            return "accept_or_decline"
        if "here is the money" in prompt or "thank you" in prompt or "goodbye" in prompt:
            return "pay_and_close"
        if current_item:
            return "ask_price"
        return "choose_item"

    def _infer_shopping_actual_move(self, text: str, current_item: str, items: list[str]) -> str:
        if "here is the money" in text:
            return "pay"
        if any(token in text for token in ["thank you", "thanks", "goodbye", "bye"]):
            return "thanks"
        if self._sounds_like_customer_price_answer(text):
            return "price_answer"
        if "how much" in text:
            return "ask_price"
        if any(token in text for token in ["i will take", "i'll take", "yes, please", "yes please", "no, thank", "no thank", "i don't want", "i do not want"]):
            return "accept_item" if any(token in text for token in ["i will take", "i'll take", "yes, please", "yes please"]) else "decline_item"
        if current_item and self._looks_like_incomplete_reply(text):
            return "choose_item_keyword"
        if current_item and any(token in text for token in ["want", "like", "take", "buy"]):
            return "choose_item"
        if self._detect_item_in_text(text, items) and self._looks_like_incomplete_reply(text):
            return "choose_item_keyword"
        return "other"

    def _infer_deictic_expected_move(self, history: list[dict[str, str]]) -> str:
        last_assistant = next((message for message in reversed(history) if message.get("role") == "assistant"), {})
        prompt = last_assistant.get("content", "").lower()
        if "are these" in prompt or "are those" in prompt:
            return "judge_yes_no"
        return "name_object"

    def _infer_deictic_actual_move(self, text: str, current_item: str) -> str:
        if self._is_yes_no_negative(text):
            return "yes_no_only_negative"
        if self._is_yes_no_positive(text):
            return "yes_no_only_positive"
        if current_item and ("they are" in text or "they're" in text):
            return "item_full"
        if current_item and current_item in text:
            return "item_keyword"
        return "other"

    def _infer_general_expected_move(self, last_prompt: str, target_patterns: list[str]) -> str:
        prompt = self._focus_prompt(last_prompt)
        patterns = " | ".join(target_patterns).lower()
        if "what is your name" in prompt or "what's your name" in prompt:
            return "say_name"
        if "favorite" in prompt or "favourite" in prompt:
            return "state_preference"
        if "what will you do" in prompt or "what are you going to do" in prompt:
            return "state_plan"
        if "do you like" in prompt:
            return "state_preference"
        if "where is" in prompt or "where are" in prompt:
            return "give_location"
        if "what is this" in prompt or "what is that" in prompt or ("what are" in prompt and "these" not in prompt and "those" not in prompt):
            return "name_object"
        if prompt.startswith("is ") or prompt.startswith("are ") or " is it" in prompt or " are they" in prompt:
            return "answer_yes_no"
        if "where is" in patterns or "next to" in patterns or "behind" in patterns or "in front of" in patterns:
            return "give_location"
        return "general_response"

    def _infer_general_actual_move(self, expected_move: str, student_message: str, vocabulary: list[str]) -> str:
        text = " ".join(student_message.split()).strip().lower()
        if not text:
            return "empty"
        if expected_move == "say_name":
            if text.startswith("my name") or text.startswith("i am"):
                return "on_track"
            return "name_keyword"
        if expected_move == "state_plan":
            if text.startswith("i will"):
                return "on_track"
            return "keyword_only" if self._looks_like_incomplete_reply(text) else "other"
        if expected_move == "state_preference":
            if text.startswith("i like") or text.startswith("i don't like") or text.startswith("i do not like"):
                return "on_track"
            if text.startswith("my favorite") or text.startswith("my favourite"):
                return "on_track"
            if self._is_yes_no_positive(text) or self._is_yes_no_negative(text):
                return "yes_no_only"
            return "keyword_only" if self._looks_like_incomplete_reply(text) else "other"
        if expected_move == "give_location":
            if "where is" in text or "where are" in text:
                return "question_back"
            if any(marker in text for marker in ["next to", "behind", "in front of", "on the left", "on the right", "between", "near"]):
                return "on_track"
            return "keyword_only" if self._looks_like_incomplete_reply(text) else "other"
        if expected_move == "name_object":
            if text.startswith("it is") or text.startswith("it's") or text.startswith("they are") or text.startswith("they're"):
                return "on_track"
            return "keyword_only" if self._looks_like_incomplete_reply(text) else "other"
        if expected_move == "answer_yes_no":
            if self._is_yes_no_positive(text) or self._is_yes_no_negative(text):
                return "yes_no_only"
            return "other"
        return "on_track" if len(text.split()) >= 3 else "keyword_only"

    def _general_response_example(
        self,
        expected_move: str,
        target_patterns: list[str],
        vocabulary: list[str],
        student_message: str,
    ) -> str:
        if expected_move == "say_name":
            guessed_name = self._guess_name_from_reply(student_message)
            return f"My name is {guessed_name}." if guessed_name else "My name is Amy."
        if expected_move == "state_plan":
            return self._weekend_plan_example(student_message, vocabulary)
        if expected_move == "state_preference":
            return self._preference_example(student_message, vocabulary)
        if expected_move == "give_location":
            return self._location_answer_example(target_patterns, vocabulary)
        if expected_move == "name_object":
            return self._object_answer_example(target_patterns, student_message)
        if expected_move == "answer_yes_no":
            return "Yes, it is."
        response_pattern = self._preferred_response_pattern(target_patterns)
        return response_pattern or (target_patterns[0] if target_patterns else "I can say it in a full sentence.")

    def _preferred_response_pattern(self, target_patterns: list[str]) -> str:
        for pattern in target_patterns:
            response_side = self._response_side_from_pattern(pattern)
            if response_side:
                return response_side
        for pattern in target_patterns:
            lowered = pattern.lower().strip()
            if "?" not in lowered and "..." not in pattern:
                return pattern
        return ""

    def _response_side_from_pattern(self, pattern: str) -> str:
        parts = [part.strip() for part in re.split(r"\s*/\s*", pattern) if part.strip()]
        if len(parts) < 2:
            return ""
        for candidate in parts[1:]:
            lowered = candidate.lower()
            if "?" in candidate:
                continue
            if any(lowered.startswith(prefix) for prefix in ["it is", "it's", "they are", "they're", "my name is", "i am", "i like", "i will", "yes", "no", "here is"]):
                return candidate
        return ""

    def _location_answer_example(self, target_patterns: list[str], vocabulary: list[str]) -> str:
        lowered_patterns = [pattern.lower() for pattern in target_patterns]
        for pattern in target_patterns:
            lowered = pattern.lower()
            if any(marker in lowered for marker in ["next to", "behind", "in front of", "on the left", "on the right", "between", "near"]):
                if "..." in pattern:
                    continue
                if "?" in pattern:
                    continue
                return pattern
        target_place = self._first_non_empty(vocabulary) or "the library"
        if not str(target_place).startswith("the "):
            target_place = f"the {target_place}"
        return f"It is next to {target_place}."

    def _object_answer_example(self, target_patterns: list[str], student_message: str) -> str:
        candidate = re.sub(r"[^A-Za-z ]", " ", student_message).strip().lower()
        word = candidate.split()[0] if candidate.split() else "desk"
        article = "an" if word[:1] in {"a", "e", "i", "o", "u"} else "a"
        for pattern in target_patterns:
            lowered = pattern.lower()
            if lowered.startswith("it is") or lowered.startswith("it's"):
                if "..." not in pattern and "?" not in pattern:
                    return pattern
        return f"It is {article} {word}."

    def _focus_prompt(self, last_prompt: str) -> str:
        prompt = (last_prompt or "").strip().lower()
        if not prompt:
            return ""
        question_parts = re.findall(r"[^?.!]*\?", prompt)
        for part in reversed(question_parts):
            cleaned = part.strip()
            if cleaned:
                return cleaned
        segments = [segment.strip() for segment in re.split(r"[.!]+", prompt) if segment.strip()]
        return segments[-1] if segments else prompt

    def _preference_example(self, student_message: str, vocabulary: list[str]) -> str:
        lowered = student_message.lower()
        topic = self._detect_item_in_text(lowered, [str(item).lower() for item in vocabulary]) or self._first_non_empty(vocabulary) or "apples"
        cleaned = re.sub(r"[^a-z ]", " ", str(topic).lower()).strip()
        words = [word for word in cleaned.split() if word]
        if not words:
            return "I like apples."
        phrase = " ".join(self._pluralize_simple_noun(word) for word in words)
        return f"I like {phrase}."

    def _pluralize_simple_noun(self, word: str) -> str:
        if not word:
            return word
        if word.endswith(("s", "x", "z", "ch", "sh")):
            return f"{word}es"
        if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
            return f"{word[:-1]}ies"
        return f"{word}s"

    def _tip_example_label(self, tip_type: str, optional_next_en: str) -> str:
        if tip_type == "next_step" and optional_next_en:
            return "这一步可以这样答"
        if tip_type == "sound_more_natural":
            return "更自然的说法"
        return "可以这样说"

    def _tip_optional_label(self, tip_type: str) -> str:
        if tip_type == "next_step":
            return "接着还可以这样说"
        return "还可以这样说"

    def _sounds_like_customer_price_answer(self, text: str) -> bool:
        if "yuan" in text:
            return True
        if re.search(r"\b(it is|it's|they are|they're)\b", text) and re.search(r"\b\d+\b", text):
            return True
        return False

    def _looks_like_incomplete_reply(self, text: str) -> bool:
        words = re.findall(r"[a-zA-Z']+", text)
        if not words:
            return False
        if self._is_yes_no_positive(text) or self._is_yes_no_negative(text):
            return False
        if any(
            text.startswith(prefix)
            for prefix in ["i ", "i'", "my ", "it ", "it's", "it is", "they ", "they'", "yes", "no", "hello", "hi"]
        ):
            return False
        return len(words) <= 4

    def _guess_name_from_reply(self, student_message: str) -> str:
        candidate = re.sub(r"[^A-Za-z -]", " ", student_message).strip()
        if not candidate:
            return ""
        candidate = re.sub(r"^\s*my\s+name\s+is\s+", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"^\s*i\s+am\s+", "", candidate, flags=re.IGNORECASE)
        parts = [part for part in candidate.split() if part]
        if not parts:
            return ""
        return " ".join(part.capitalize() for part in parts[:2])

    def _weekend_plan_example(self, student_message: str, vocabulary: list[str]) -> str:
        lowered = student_message.lower()
        place = self._detect_item_in_text(lowered, [str(item).lower() for item in vocabulary])
        if place:
            if place.startswith("the "):
                return f"I will go to {place}."
            return f"I will go to the {place}."
        return "I will go to the park."

    def _first_non_empty(self, items: list[Any]) -> str:
        for item in items:
            value = str(item or "").strip()
            if value:
                return value
        return ""

    def _message_role(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("role", "") or "").strip()
        return str(getattr(item, "role", "") or "").strip()

    def _message_content(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("content", "") or "")
        return str(getattr(item, "content", "") or "")
