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
        job = self.job_service.get_job(job_id)
        payload = self.job_service.get_result(job_id, approved_only=False, include_review_records=False)
        unit_package = self._find_unit_package(payload, unit_id)
        grade_band = self._detect_grade_band(job.file_name, payload, unit_package)
        default_template = self._get_default_template(grade_band)
        unit_context = self._build_unit_context(payload, unit_package)

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
        }

    def chat(self, payload: PracticeChatRequest) -> dict[str, Any]:
        if not self.practice_client.is_configured():
            raise AppError(
                "PRACTICE_PROVIDER_NOT_CONFIGURED",
                "Practice provider is not configured",
                status_code=503,
            )

        # Validate job and unit against existing structured content.
        context = self.get_context(payload.job_id, payload.unit_id)

        final_prompt = payload.final_prompt.strip()
        if not final_prompt:
            raise AppError("PRACTICE_INVALID_PROMPT", "final_prompt is required", status_code=400)

        outgoing_messages: list[dict[str, str]] = [{"role": "system", "content": final_prompt}]
        for item in payload.messages:
            content = item.content.strip()
            if not content:
                raise AppError("PRACTICE_INVALID_MESSAGES", "message content cannot be empty", status_code=400)
            outgoing_messages.append({"role": item.role, "content": content})

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
        assistant_message = self._apply_assistant_guardrails(context, response.assistant_message)
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
        completed_user_turns = sum(1 for item in prior_messages if getattr(item, "role", "") == "user")
        if is_opening_turn:
            return completed_user_turns
        return completed_user_turns + (1 if student_message else 0)

    def _apply_assistant_guardrails(self, context: dict[str, Any], assistant_message: str) -> str:
        normalized = " ".join((assistant_message or "").split()).strip()
        if not normalized:
            return normalized
        if self._looks_like_shopping_price_practice(context):
            return self._rewrite_shopkeeper_price_prompt(normalized)
        return normalized

    def _looks_like_shopping_price_practice(self, context: dict[str, Any]) -> bool:
        unit = context.get("unit", {}) if isinstance(context, dict) else {}
        summary = context.get("summary", {}) if isinstance(context, dict) else {}
        joined = " ".join(
            [
                str(unit.get("unit_name", "") or ""),
                str(unit.get("unit_theme", "") or ""),
                str(unit.get("unit_task", "") or ""),
                " | ".join(summary.get("sentence_patterns", []) or []),
            ]
        ).lower()
        return any(
            marker in joined
            for marker in ["shopping", "购物", "顾客", "售货员", "店员", "价格", "how much", "yuan", "buy", "sell"]
        )

    def _rewrite_shopkeeper_price_prompt(self, assistant_message: str) -> str:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", assistant_message) if part.strip()]
        kept: list[str] = []
        removed_price_question = False

        for sentence in sentences:
            if re.match(r"(?i)^how much (is|are)\b", sentence):
                removed_price_question = True
                continue
            kept.append(sentence)

        if not removed_price_question:
            return assistant_message

        has_existing_question = any(sentence.endswith("?") for sentence in kept)
        mentions_price = any("price" in sentence.lower() for sentence in kept)
        if not has_existing_question and not mentions_price:
            kept.append("Do you want to know the price?")

        return " ".join(kept).strip() or "Do you want to know the price?"
