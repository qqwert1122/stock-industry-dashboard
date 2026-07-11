from __future__ import annotations

from datetime import date
from pathlib import Path

from macro_telegram_report.event_calendar import (
    build_event_calendar,
    expiry_events,
    load_calendar_yaml,
)
from macro_telegram_report.fetch_log import FetchLogger, use_fetch_logger


def test_expiry_events_2026() -> None:
    manual = load_calendar_yaml(Path("data/calendar/2026.yaml"))
    events = expiry_events(2026, manual)

    options = [item["date"] for item in events if item["name"] == "한국 옵션만기"]
    futures = [item["date"] for item in events if item["name"] == "한국 선물만기"]
    quad = [item["date"] for item in events if item["name"] == "미국 쿼드러플위칭"]

    assert options == [
        "2026-01-08",
        "2026-02-12",
        "2026-03-12",
        "2026-04-09",
        "2026-05-14",
        "2026-06-11",
        "2026-07-09",
        "2026-08-13",
        "2026-09-10",
        "2026-10-08",
        "2026-11-12",
        "2026-12-10",
    ]
    assert futures == ["2026-03-12", "2026-06-11", "2026-09-10", "2026-12-10"]
    assert quad == ["2026-03-20", "2026-06-18", "2026-09-18", "2026-12-18"]
    assert {item["category"] for item in events} == {"market"}


def test_manual_calendar_uses_event_type_categories() -> None:
    categories = {item["category"] for item in load_calendar_yaml(Path("data/calendar/2026.yaml"))}

    assert categories <= {"policy", "macro", "corporate", "industry", "holiday"}


def test_event_calendar_links_manual_cpi_but_ignores_metric_updates() -> None:
    payload = {
        "metrics": [
            {"id": "metric-cpi", "name": "미국 CPI", "next_update_label": "2026.07.14"},
            {"id": "metric-other", "name": "다른 지표", "next_update_label": "2026.07.10"},
        ]
    }

    calendar = build_event_calendar({"calendar": {"dir": "data/calendar"}}, payload, today=date(2026, 7, 9))

    cpi_events = [item for item in calendar["events"] if item["name"] == "미국 CPI 발표"]
    assert cpi_events
    assert cpi_events[0]["metric_id"] == "metric-cpi"
    assert not any(item["category"] == "site_update" for item in calendar["events"])
    assert not any("갱신 예정" in item["name"] for item in calendar["events"])


def test_event_calendar_missing_yaml_records_fetch_warning(tmp_path: Path) -> None:
    logger = FetchLogger(run_type="test", timezone_name="Asia/Seoul")
    with use_fetch_logger(logger):
        calendar = build_event_calendar(
            {"calendar": {"dir": str(tmp_path)}},
            {"metrics": []},
            today=date(2026, 7, 9),
        )

    run = logger.finish()
    assert calendar["missing_years"] == [2026]
    assert any(
        record["source"] == "이벤트 캘린더" and record["status"] == "failed"
        for record in run["records"]
    )
