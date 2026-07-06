from __future__ import annotations

import os
from typing import Any

import requests

from .models import Section
from .utils import fmt_number, fmt_signed, to_float

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


def collect_fred(config: dict[str, Any], session: requests.Session) -> Section | None:
    fred_config = config.get("fred", {})
    if not fred_config.get("enabled", True):
        return None

    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        return Section("FRED", ["- FRED_API_KEY가 없어 FRED 수집을 건너뜁니다."])

    lines: list[str] = []
    for series in fred_config.get("series", []):
        series_id = str(series["id"]).strip()
        name = series.get("name") or series_id
        unit = series.get("unit", "")
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 10,
        }
        response = session.get(FRED_OBSERVATIONS_URL, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        observations = [
            item
            for item in payload.get("observations", [])
            if to_float(item.get("value")) is not None
        ]
        if not observations:
            lines.append(f"- {name}: 관측값 없음")
            continue

        latest = observations[0]
        latest_value = to_float(latest.get("value"))
        previous_value = to_float(observations[1].get("value")) if len(observations) > 1 else None
        if latest_value is None:
            lines.append(f"- {name}: 관측값 없음")
            continue

        change_text = ""
        if previous_value is not None:
            delta = latest_value - previous_value
            change_unit = "%p" if unit == "%" else unit
            change_text = f", 전기 {fmt_signed(delta)}{change_unit}"
        lines.append(
            f"- {name}: {fmt_number(latest_value)}{unit} ({latest['date']}{change_text})"
        )

    return Section("FRED", lines)
