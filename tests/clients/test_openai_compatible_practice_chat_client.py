from __future__ import annotations

import io
import json
from urllib import error as urlerror

import pytest

from app.clients.openai_compatible.practice_chat_client import OpenAICompatiblePracticeChatClient
from app.core.config import Settings
from app.core.errors import AppError


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
        openai_api_key="secret",
        openai_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        practice_provider_name="qwen",
        practice_model="qwen3.5-flash",
        practice_timeout_sec=60,
    )
    settings.ensure_directories()
    return settings


class StubHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_create_chat_completion_parses_string_content(tmp_path, monkeypatch):
    client = OpenAICompatiblePracticeChatClient(build_settings(tmp_path))

    def fake_urlopen(request, timeout=0):
        assert request.full_url.endswith("/chat/completions")
        assert timeout == 60
        return StubHTTPResponse(
            {
                "id": "req_demo",
                "usage": {"prompt_tokens": 12},
                "choices": [{"message": {"content": " Hello! "}}],
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = client.create_chat_completion([{"role": "system", "content": "prompt"}])

    assert response.assistant_message == "Hello!"
    assert response.request_id == "req_demo"
    assert response.usage == {"prompt_tokens": 12}


def test_create_chat_completion_maps_http_errors(tmp_path, monkeypatch):
    client = OpenAICompatiblePracticeChatClient(build_settings(tmp_path))

    def fake_urlopen(request, timeout=0):
        raise urlerror.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"bad key"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(AppError) as exc_info:
        client.create_chat_completion([{"role": "system", "content": "prompt"}])

    assert exc_info.value.code == "PRACTICE_PROVIDER_REQUEST_FAILED"
    assert exc_info.value.details["status"] == 401
