from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "timezone": "Asia/Seoul",
    "report": {"title": "아침 매크로 리포트"},
    "fred": {"enabled": True, "series": []},
    "wsts": {
        "enabled": True,
        "page_url": "https://www.wsts.org/67/Historical-Billings-Report",
        "regions": ["Worldwide"],
        "include_3mma": True,
    },
    "korea_exports": {
        "enabled": True,
        "endpoint": "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList",
        "months_back": 15,
        "end_offset_months": 1,
        "items": [],
    },
}


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {config_path}")

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError("config.yaml의 최상위 값은 객체여야 합니다.")
    return deep_merge(DEFAULT_CONFIG, loaded)
