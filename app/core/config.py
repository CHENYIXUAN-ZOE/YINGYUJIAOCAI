import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    project_name: str = "教材内容产出工具"
    api_prefix: str = "/api/v1"
    base_dir: Path = Path(__file__).resolve().parents[2]
    data_dir: Path = base_dir / "data"
    temp_dir: Path = data_dir / "tmp"
    upload_dir: Path = data_dir / "uploads"
    parsed_dir: Path = data_dir / "parsed"
    export_dir: Path = data_dir / "exports"
    job_dir: Path = parsed_dir / "jobs"
    result_dir: Path = parsed_dir / "results"
    review_dir: Path = parsed_dir / "reviews"
    web_dir: Path = base_dir / "app" / "web"
    template_dir: Path = web_dir / "templates"
    static_dir: Path = web_dir / "static"
    max_upload_size_mb: int = Field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_SIZE_MB", "200")))
    openai_api_key: str | None = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_base_url: str | None = Field(default_factory=lambda: os.getenv("OPENAI_BASE_URL"))
    practice_provider_name: str = Field(default_factory=lambda: os.getenv("PRACTICE_PROVIDER_NAME", "openai-compatible"))
    practice_model: str | None = Field(default_factory=lambda: os.getenv("PRACTICE_MODEL"))
    practice_timeout_sec: int = Field(default_factory=lambda: int(os.getenv("PRACTICE_TIMEOUT_SEC", "60")))
    google_cloud_project: str | None = Field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT"))
    google_cloud_location: str = Field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_LOCATION", "global"))
    google_application_credentials: str | None = Field(
        default_factory=lambda: os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )
    gemini_model: str = Field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    gemini_ocr_model: str = Field(
        default_factory=lambda: os.getenv("GEMINI_OCR_MODEL") or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    )
    gemini_max_retries: int = Field(default_factory=lambda: int(os.getenv("GEMINI_MAX_RETRIES", "3")))
    doubao_api_key: str | None = Field(default_factory=lambda: os.getenv("DOUBAO_API_KEY"))
    doubao_endpoint_id: str | None = Field(default_factory=lambda: os.getenv("DOUBAO_ENDPOINT_ID"))
    doubao_base_url: str = Field(
        default_factory=lambda: os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    )
    doubao_timeout_sec: int = Field(default_factory=lambda: int(os.getenv("DOUBAO_TIMEOUT_SEC", "60")))
    ocr_page_batch_size: int = Field(default_factory=lambda: int(os.getenv("OCR_PAGE_BATCH_SIZE", "4")))
    ocr_render_dpi: int = Field(default_factory=lambda: int(os.getenv("OCR_RENDER_DPI", "160")))
    target_parse_duration_sec: int = Field(
        default_factory=lambda: int(os.getenv("TARGET_PARSE_DURATION_SEC", "600"))
    )
    preflight_sample_pages: int = Field(default_factory=lambda: int(os.getenv("PREFLIGHT_SAMPLE_PAGES", "3")))
    allow_placeholder_fallback: bool = Field(
        default_factory=lambda: os.getenv("ALLOW_PLACEHOLDER_FALLBACK", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    )
    github_remote_url: str | None = Field(default_factory=lambda: os.getenv("GITHUB_REMOTE_URL"))

    def ensure_directories(self) -> None:
        for path in [
            self.data_dir,
            self.temp_dir,
            self.upload_dir,
            self.parsed_dir,
            self.export_dir,
            self.job_dir,
            self.result_dir,
            self.review_dir,
            self.template_dir,
            self.static_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def resolve_google_credentials_path(self) -> Path | None:
        if self.google_application_credentials:
            candidate = Path(self.google_application_credentials).expanduser()
            return candidate if candidate.exists() else candidate
        candidate = self.base_dir / "API" / "API.txt"
        if candidate.exists():
            return candidate
        return None


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@lru_cache
def get_settings() -> Settings:
    base_dir = Path(__file__).resolve().parents[2]
    _load_env_file(base_dir / ".env")
    _load_env_file(base_dir / ".env.local")
    settings = Settings()
    settings.ensure_directories()
    return settings
