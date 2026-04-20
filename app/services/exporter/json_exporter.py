from __future__ import annotations

import json
from pathlib import Path


def export_json(payload: dict, output_path: Path) -> Path:
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
