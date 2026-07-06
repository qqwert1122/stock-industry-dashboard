from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from .fred import collect_fred
from .korea_exports import collect_korea_exports
from .models import Section
from .wsts import collect_wsts


def build_report(config: dict[str, Any], session: requests.Session) -> str:
    timezone = ZoneInfo(str(config.get("timezone", "Asia/Seoul")))
    now = datetime.now(timezone)
    today = now.date()

    sections: list[Section] = []
    collectors: list[tuple[str, Callable[[], Section | None]]] = [
        ("FRED", lambda: collect_fred(config, session)),
        ("WSTS", lambda: collect_wsts(config, session)),
        ("한국 수출", lambda: collect_korea_exports(config, session, today)),
    ]

    for title, collector in collectors:
        try:
            section = collector()
        except Exception as exc:  # Keep the morning report alive when one source is down.
            section = Section(title, [f"- 오류: {exc}"])
        if section and not section.is_empty():
            sections.append(section)

    return format_report(
        title=str(config.get("report", {}).get("title", "아침 매크로 리포트")),
        generated_at=now.strftime("%Y-%m-%d %H:%M %Z"),
        sections=sections,
    )


def format_report(title: str, generated_at: str, sections: list[Section]) -> str:
    parts = [f"[{title}]", generated_at]
    for section in sections:
        parts.append("")
        parts.append(section.title)
        parts.extend(section.lines)
    parts.append("")
    parts.append("자료: FRED, WSTS Historical Billings Report, 관세청 공공데이터")
    return "\n".join(parts)
