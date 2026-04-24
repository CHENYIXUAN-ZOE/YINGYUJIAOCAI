from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from app.core.config import Settings
from app.core.errors import AppError


@dataclass(frozen=True)
class OpenAICompatiblePracticeChatResponse:
    assistant_message: str
    request_id: str
    latency_ms: int
    usage: dict[str, Any]


class OpenAICompatiblePracticeChatClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def provider_name(self) -> str:
        return (self.settings.practice_provider_name or "openai-compatible").strip().lower()

    def model_name(self) -> str:
        return (self.settings.practice_model or "").strip()

    def is_configured(self) -> bool:
        return bool(self.settings.openai_api_key and self.model_name() and self._chat_url())

    def create_chat_completion(self, messages: list[dict[str, str]]) -> OpenAICompatiblePracticeChatResponse:
        self._ensure_configured()

        request_payload = {
            "model": self.model_name(),
            "messages": messages,
            "temperature": self.settings.practice_temperature,
            "stream": False,
        }
        if self._should_disable_thinking():
            request_payload["enable_thinking"] = False

        encoded_body = json.dumps(request_payload).encode("utf-8")
        req = urlrequest.Request(
            self._chat_url(),
            data=encoded_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.openai_api_key}",
            },
            method="POST",
        )

        started_at = time.perf_counter()
        try:
            with urlrequest.urlopen(req, timeout=self.settings.practice_timeout_sec) as response:
                raw_body = response.read().decode("utf-8")
            payload = json.loads(raw_body)
        except urlerror.HTTPError as exc:
            details = {"status": exc.code}
            try:
                raw = exc.read().decode("utf-8")
                details["body"] = json.loads(raw)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                details["body"] = ""
            raise AppError(
                "PRACTICE_PROVIDER_REQUEST_FAILED",
                "Practice provider request failed",
                status_code=502,
                details=details,
            ) from exc
        except (urlerror.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise AppError(
                "PRACTICE_PROVIDER_REQUEST_FAILED",
                "Practice provider request failed",
                status_code=502,
                details={"message": str(exc)},
            ) from exc

        return OpenAICompatiblePracticeChatResponse(
            assistant_message=self._extract_assistant_message(payload),
            request_id=str(payload.get("id", "") or ""),
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            usage=payload.get("usage", {}) if isinstance(payload.get("usage"), dict) else {},
        )

    def _ensure_configured(self) -> None:
        if not self.settings.openai_api_key or not self.model_name():
            raise AppError(
                "PRACTICE_PROVIDER_NOT_CONFIGURED",
                "Practice provider is not configured",
                status_code=503,
            )
        if not self._chat_url():
            raise AppError(
                "PRACTICE_PROVIDER_NOT_CONFIGURED",
                "Practice provider base URL is not configured",
                status_code=503,
            )

    def _chat_url(self) -> str:
        base_url = (self.settings.openai_base_url or "").rstrip("/")
        if not base_url:
            return ""
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _should_disable_thinking(self) -> bool:
        model_name = self.model_name().lower()
        if not model_name.startswith("qwen3"):
            return False

        provider_name = self.provider_name
        if provider_name in {"qwen", "dashscope"}:
            return True

        base_url = (self.settings.openai_base_url or "").lower()
        return "dashscope.aliyuncs.com" in base_url

    def _extract_assistant_message(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise AppError(
                "PRACTICE_PROVIDER_REQUEST_FAILED",
                "Practice provider response did not contain choices",
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
                "Practice provider response did not contain assistant content",
                status_code=502,
            )
        return content
