from app.core.config import Settings


def test_settings_read_environment_at_instantiation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "demo-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("PRACTICE_PROVIDER_NAME", "qwen")
    monkeypatch.setenv("PRACTICE_MODEL", "qwen3.5-flash")
    monkeypatch.setenv("PRACTICE_TIMEOUT_SEC", "90")

    settings = Settings()

    assert settings.openai_api_key == "demo-key"
    assert settings.openai_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings.practice_provider_name == "qwen"
    assert settings.practice_model == "qwen3.5-flash"
    assert settings.practice_timeout_sec == 90
