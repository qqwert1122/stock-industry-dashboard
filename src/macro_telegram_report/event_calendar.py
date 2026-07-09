from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .fetch_log import current_logger


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(days=offset + (nth - 1) * 7)


def previous_business_day(day: date, holidays: set[date]) -> date:
    current = day
    while current.weekday() >= 5 or current in holidays:
        current -= timedelta(days=1)
    return current


def load_calendar_yaml(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    events = loaded.get("events") if isinstance(loaded, dict) else loaded
    return events if isinstance(events, list) else []


def event_date(item: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(item.get("date")))
    except (TypeError, ValueError):
        return None


def holiday_set(events: list[dict[str, Any]], country: str | None = None) -> set[date]:
    holidays: set[date] = set()
    for item in events:
        if item.get("category") != "holiday":
            continue
        if country and item.get("country") != country:
            continue
        day = event_date(item)
        if day:
            holidays.add(day)
    return holidays


def expiry_events(year: int, manual_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kr_holidays = holiday_set(manual_events, "KR")
    us_holidays = holiday_set(manual_events, "US")
    events: list[dict[str, Any]] = []
    for month in range(1, 13):
        option_day = previous_business_day(nth_weekday(year, month, 3, 2), kr_holidays)
        events.append(
            {
                "date": option_day.isoformat(),
                "name": "한국 옵션만기",
                "category": "expiry",
                "country": "KR",
                "note": "매월 둘째 목요일 기준, 휴장 시 전영업일",
            }
        )
        if month in (3, 6, 9, 12):
            futures_day = previous_business_day(nth_weekday(year, month, 3, 2), kr_holidays)
            events.append(
                {
                    "date": futures_day.isoformat(),
                    "name": "한국 선물만기",
                    "category": "expiry",
                    "country": "KR",
                    "note": "3·6·9·12월 둘째 목요일 기준",
                }
            )
            quad_day = previous_business_day(nth_weekday(year, month, 4, 3), us_holidays)
            events.append(
                {
                    "date": quad_day.isoformat(),
                    "name": "미국 쿼드러플위칭",
                    "category": "expiry",
                    "country": "US",
                    "note": "3·6·9·12월 셋째 금요일 기준, 휴장 시 전영업일",
                }
            )
    return events


def metric_event_links(events: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    metrics = payload.get("metrics", [])
    for item in events:
        name = str(item.get("name") or "")
        if "CPI" in name:
            metric = next((m for m in metrics if "CPI" in str(m.get("name") or "")), None)
            if metric:
                item["metric_id"] = metric.get("id")


def record_calendar_warnings(missing_years: list[int]) -> None:
    if not missing_years:
        return
    logger = current_logger()
    if logger is None:
        return
    logger.record(
        source="이벤트 캘린더",
        endpoint="data/calendar/YYYY.yaml",
        status="failed",
        message=f"{', '.join(str(year) for year in missing_years)}년 캘린더 YAML이 없어 수동 일정이 비어 있습니다.",
        metric_count=0,
        new_data_count=0,
    )


def compact_event(item: dict[str, Any], today: date) -> dict[str, Any]:
    day = event_date(item) or today
    delta = (day - today).days
    result = {
        "date": day.isoformat(),
        "name": str(item.get("name") or ""),
        "category": str(item.get("category") or "event"),
        "country": str(item.get("country") or ""),
        "note": str(item.get("note") or ""),
        "d_day": delta,
        "d_day_label": "D-day" if delta == 0 else f"D{delta:+d}",
    }
    if item.get("metric_id"):
        result["metric_id"] = item.get("metric_id")
    return result


def build_event_calendar(
    config: dict[str, Any],
    payload: dict[str, Any],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or datetime.now().date()
    root = Path(str((config.get("calendar") or {}).get("dir") or "data/calendar"))
    years = {today.year, (today + timedelta(days=70)).year, (today - timedelta(days=10)).year}
    manual: list[dict[str, Any]] = []
    missing_years: list[int] = []
    for year in sorted(years):
        path = root / f"{year}.yaml"
        items = load_calendar_yaml(path)
        if not items and year == today.year:
            missing_years.append(year)
        manual.extend(items)
    all_events = list(manual)
    for year in sorted(years):
        all_events.extend(expiry_events(year, manual))
    metric_event_links(all_events, payload)
    start = today - timedelta(days=7)
    end = today + timedelta(days=60)
    compact = [compact_event(item, today) for item in all_events if (day := event_date(item)) and start <= day <= end]
    compact.sort(key=lambda item: (item["date"], item["category"], item["name"]))
    upcoming = [item for item in compact if 0 <= item["d_day"] <= 1]
    record_calendar_warnings(missing_years)
    return {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "events": compact,
        "upcoming": upcoming,
        "missing_years": missing_years,
    }


def write_event_calendar(path: Path, calendar: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calendar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
