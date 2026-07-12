"""Small, consistent JSON file helpers used by dashboard state stores."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path, fallback: Any) -> Any:
    target = Path(path)
    if not target.exists():
        return fallback
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json(path: str | Path, value: Any, *, compact: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    options = (
        {"separators": (",", ":")}
        if compact
        else {"indent": 2}
    )
    target.write_text(
        json.dumps(value, ensure_ascii=False, **options) + "\n",
        encoding="utf-8",
    )
