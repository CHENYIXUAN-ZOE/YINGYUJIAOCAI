from __future__ import annotations

import json
import re
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from app.core.config import Settings
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
- Keep each teacher turn brief and easy to understand.
- Use direct questions and simple follow-up questions.
- Reuse key words and sentence patterns naturally when helpful.
- Encourage the student to say a little more, but do not overload the student.
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
3. Help the student speak in short, manageable English.
4. Prefer natural continuation over explicit correction.
5. Keep the dialogue simple, spoken, and engaging.
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
- Ask questions that encourage short but meaningful expansion.
- Help the student combine key words and sentence patterns more flexibly.
- Allow slightly more natural follow-up and scene extension when it still fits the unit.
- Keep role-play light, focused, and age-appropriate.
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
3. Help the student speak in clear and meaningful English.
4. Prefer natural continuation over explicit correction.
5. Keep the dialogue spoken, focused, and engaging.
""".strip()

FINAL_PROMPT_INSTRUCTION = "Now begin the oral practice with a natural opening line as the teacher."

_DIGIT_GRADE_PATTERN = re.compile(r"(?<!\d)([3-6])(?:\s*[AaBb上下册]?|\s*年级)(?!\d)", re.IGNORECASE)
_CHINESE_GRADE_MAP = {
    "三年级": 3,
    "四年级": 4,
    "五年级": 5,
    "六年级": 6,
}


class PracticeService:
    def __init__(self, settings: Settings, job_service: JobService):
        self.settings = settings
        self.job_service = job_service

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
                "name": "doubao",
                "configured": self._provider_configured(),
                "endpoint_id_masked": self._mask_endpoint_id(self.settings.doubao_endpoint_id),
            },
        }

    def chat(self, payload: PracticeChatRequest) -> dict[str, Any]:
        if not self._provider_configured():
            raise AppError(
                "PRACTICE_PROVIDER_NOT_CONFIGURED",
                "Doubao practice provider is not configured",
                status_code=503,
            )

        # Validate job and unit against existing structured content.
        self.get_context(payload.job_id, payload.unit_id)

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

        response = self._request_doubao(outgoing_messages)
        assistant_message = self._extract_assistant_message(response)
        round_count = self._count_rounds(payload.messages, student_message, payload.is_opening_turn)

        return {
            "assistant_message": {"role": "assistant", "content": assistant_message},
            "round_count": round_count,
            "status_hint": "接近建议轮次，但可继续对话" if round_count >= 7 else "",
            "meta": {
                "request_id": response.get("id", ""),
                "provider": "doubao",
                "endpoint_id_masked": self._mask_endpoint_id(self.settings.doubao_endpoint_id),
                "latency_ms": response.get("_latency_ms", 0),
                "usage": response.get("usage", {}),
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

        return {
            "textbook_name": payload.get("book", {}).get("textbook_name") or classification.get("textbook_name", ""),
            "unit_code": classification.get("unit_code", ""),
            "unit_name": classification.get("unit_name", ""),
            "unit_theme": unit.get("unit_theme") or unit_package.get("unit_prompt", {}).get("unit_theme") or classification.get("unit_name", ""),
            "unit_task": unit_task.strip(),
            "key_vocabulary": vocabulary,
            "key_sentence_patterns": sentence_patterns,
        }

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

    def _provider_configured(self) -> bool:
        return bool(self.settings.doubao_api_key and self.settings.doubao_endpoint_id)

    def _chat_url(self) -> str:
        base_url = (self.settings.doubao_base_url or "").rstrip("/")
        if not base_url:
            return ""
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _request_doubao(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        url = self._chat_url()
        if not url:
            raise AppError(
                "PRACTICE_PROVIDER_NOT_CONFIGURED",
                "Doubao base URL is not configured",
                status_code=503,
            )

        request_payload = {
            "model": self.settings.doubao_endpoint_id,
            "messages": messages,
            "temperature": 0.7,
            "stream": False,
        }

        encoded_body = json.dumps(request_payload).encode("utf-8")
        req = urlrequest.Request(
            url,
            data=encoded_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.doubao_api_key}",
            },
            method="POST",
        )

        try:
            with urlrequest.urlopen(req, timeout=self.settings.doubao_timeout_sec) as response:
                raw_body = response.read().decode("utf-8")
            payload = json.loads(raw_body)
            return payload
        except urlerror.HTTPError as exc:
            details = {"status": exc.code}
            try:
                raw = exc.read().decode("utf-8")
                details["body"] = json.loads(raw)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                details["body"] = ""
            raise AppError(
                "PRACTICE_PROVIDER_REQUEST_FAILED",
                "Doubao request failed",
                status_code=502,
                details=details,
            ) from exc
        except (urlerror.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise AppError(
                "PRACTICE_PROVIDER_REQUEST_FAILED",
                "Doubao request failed",
                status_code=502,
                details={"message": str(exc)},
            ) from exc

    def _extract_assistant_message(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise AppError(
                "PRACTICE_PROVIDER_REQUEST_FAILED",
                "Doubao response did not contain choices",
                status_code=502,
            )
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            content = content.strip()
        elif isinstance(content, list):
            content = "".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") in {None, "text", "output_text"}
            ).strip()
        else:
            content = ""

        if not content:
            raise AppError(
                "PRACTICE_PROVIDER_REQUEST_FAILED",
                "Doubao response did not contain assistant content",
                status_code=502,
            )
        return content

    def _count_rounds(self, prior_messages: list[Any], student_message: str, is_opening_turn: bool) -> int:
        completed_user_turns = sum(1 for item in prior_messages if getattr(item, "role", "") == "user")
        if is_opening_turn:
            return completed_user_turns
        return completed_user_turns + (1 if student_message else 0)

    def _mask_endpoint_id(self, endpoint_id: str | None) -> str:
        if not endpoint_id:
            return ""
        if len(endpoint_id) <= 6:
            return endpoint_id
        return f"{endpoint_id[:3]}-****"
