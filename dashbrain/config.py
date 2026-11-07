from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

def load_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else ROOT / "config.json"
    return json.loads(p.read_text())

def load_personality(path: str | Path | None = None) -> str:
    p = Path(path) if path else ROOT / "personality.txt"
    return p.read_text().strip()
