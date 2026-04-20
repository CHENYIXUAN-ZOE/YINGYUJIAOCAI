from __future__ import annotations

from pathlib import Path


def load_pdf(file_path: Path) -> dict:
    return {
        "file_name": file_path.name,
        "stem": file_path.stem,
        "file_path": str(file_path),
    }
