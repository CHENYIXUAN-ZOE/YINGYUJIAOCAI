import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    project_name: str = "口语练习"
    api_prefix: str = "/api/v1"
    base_dir: Path = Path(__file__).resolve().parents[2]
    data_dir: Path = base_dir / "data"
    upload_dir: Path = data_dir / "uploads"
    parsed_dir: Path = data_dir / "parsed"
    export_dir: Path = data_dir / "exports"
    job_dir: Path = parsed_dir / "jobs"
    result_dir: Path = parsed_dir / "results"
    review_dir: Path = parsed_dir / "reviews"
    web_dir: Path = base_dir / "app" / "web"
    template_dir: Path = web_dir / "templates"
    static_dir: Path = web_dir / "static"
    max_upload_size_mb: int = 50
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_base_url: str | None = os.getenv("OPENAI_BASE_URL")
    github_remote_url: str | None = os.getenv("GITHUB_REMOTE_URL")

    def ensure_directories(self) -> None:
        for path in [
            self.data_dir,
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
