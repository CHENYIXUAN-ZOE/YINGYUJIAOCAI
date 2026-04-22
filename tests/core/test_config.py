from app.core.config import Settings


def test_settings_read_environment_at_instantiation(monkeypatch):
    monkeypatch.setenv("DOUBAO_API_KEY", "demo-key")
    monkeypatch.setenv("DOUBAO_ENDPOINT_ID", "ep-demo")
    monkeypatch.setenv("DOUBAO_TIMEOUT_SEC", "90")

    settings = Settings()

    assert settings.doubao_api_key == "demo-key"
    assert settings.doubao_endpoint_id == "ep-demo"
    assert settings.doubao_timeout_sec == 90
