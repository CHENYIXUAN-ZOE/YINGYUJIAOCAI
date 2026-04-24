from __future__ import annotations

import re
from typing import Any

from app.clients.openai_compatible.practice_chat_client import OpenAICompatiblePracticeChatClient
from app.core.errors import AppError
from app.schemas.practice import PracticeChatRequest
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

        return {
            "assistant_message": {"role": "assistant", "content": assistant_message},
            "round_count": round_count,
            "status_hint": "接近建议轮次，但可继续对话" if round_count >= 7 else "",
            "meta": {
                "request_id": response.request_id,
                "provider": self.practice_client.provider_name,
                "model": self.practice_client.model_name(),
                "latency_ms": response.latency_ms,
                "usage": response.usage,
            },
        }

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

    def _message_role(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("role", "") or "").strip()
        return str(getattr(item, "role", "") or "").strip()

    def _message_content(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("content", "") or "")
        return str(getattr(item, "content", "") or "")
