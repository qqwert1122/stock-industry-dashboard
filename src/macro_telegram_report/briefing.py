"""Briefing card history and lightweight trajectory tracking."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

BRIEFINGS_DIRNAME = "briefings"
BRIEFING_INDEX_FILENAME = "index.json"
GEMINI_USAGE_FILENAME = "gemini_usage.json"
INTRADAY_TRACK_FILENAME = "intraday_track.json"
BRIEFING_HISTORY_VERSION = 1

CARD_LABELS = {
    "morning": "아침",
    "intraday": "장중",
    "close": "한국장 마감",
    "us_close": "미국장 마감",
}


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def briefing_date_key(generated_at: str) -> str:
    try:
        return datetime.fromisoformat(generated_at.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return datetime.now().date().isoformat()


def briefing_card_id(card_type: str, generated_at: str, headline: str) -> str:
    digest = hashlib.sha1(f"{card_type}|{generated_at}|{headline}".encode("utf-8")).hexdigest()[:10]
    return f"{briefing_date_key(generated_at)}-{card_type}-{digest}"


def low_signal_card(briefing: dict[str, Any]) -> bool:
    bullets = briefing.get("bullets")
    top_movers = briefing.get("top_movers")
    return not bullets and not top_movers


def build_briefing_card(
    briefing: dict[str, Any],
    *,
    card_type: str,
    generated_at: str,
    generated_label: str,
    trajectory: dict[str, Any] | None = None,
    low_signal: bool | None = None,
    session_context: dict[str, Any] | None = None,
    gate_reason: str = "",
    metric_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    card = dict(briefing)
    card_type = card_type if card_type in CARD_LABELS else "morning"
    card["id"] = str(card.get("id") or briefing_card_id(card_type, generated_at, str(card.get("headline") or "")))
    card["card_type"] = card_type
    card["card_type_label"] = CARD_LABELS[card_type]
    card["generated_at"] = generated_at
    card["generated_label"] = generated_label
    card["low_signal"] = low_signal_card(card) if low_signal is None else bool(low_signal)
    if session_context:
        card["session_context"] = session_context
    if gate_reason:
        card["gate_reason"] = gate_reason
    if metric_snapshot is not None:
        card["metric_snapshot"] = metric_snapshot
    if trajectory:
        card["trajectory"] = trajectory
    return card


def day_briefing_path(data_path: Path, date_key: str) -> Path:
    return data_path / BRIEFINGS_DIRNAME / f"{date_key}.json"


def briefing_index_path(data_path: Path) -> Path:
    return data_path / BRIEFINGS_DIRNAME / BRIEFING_INDEX_FILENAME


def gemini_usage_path(data_path: Path) -> Path:
    return data_path / BRIEFINGS_DIRNAME / GEMINI_USAGE_FILENAME


def load_day_document(data_path: Path, date_key: str) -> dict[str, Any]:
    document = load_json(day_briefing_path(data_path, date_key), {})
    if not isinstance(document, dict):
        document = {}
    cards = document.get("cards")
    return {
        "version": BRIEFING_HISTORY_VERSION,
        "date": date_key,
        "cards": cards if isinstance(cards, list) else [],
    }


def compact_card(card: dict[str, Any]) -> dict[str, Any]:
    narrative_topics = card.get("narrative_topics")
    return {
        "id": str(card.get("id") or ""),
        "date": briefing_date_key(str(card.get("generated_at") or "")),
        "card_type": str(card.get("card_type") or ""),
        "card_type_label": str(card.get("card_type_label") or ""),
        "generated_at": str(card.get("generated_at") or ""),
        "generated_label": str(card.get("generated_label") or ""),
        "headline": str(card.get("headline") or ""),
        "low_signal": bool(card.get("low_signal")),
        "session_label": str((card.get("session_context") or {}).get("label") or ""),
        "gate_reason": str(card.get("gate_reason") or ""),
        "gemini_call_attempted": bool(card.get("gemini_call_attempted")),
        "narrative_topics": [
            str(topic)
            for topic in (narrative_topics if isinstance(narrative_topics, list) else [])
            if str(topic or "").strip()
        ][:4],
    }


def load_briefing_index(data_path: Path) -> dict[str, Any]:
    index = load_json(briefing_index_path(data_path), {})
    if not isinstance(index, dict):
        return {"version": BRIEFING_HISTORY_VERSION, "cards": []}
    cards = index.get("cards")
    if not isinstance(cards, list):
        cards = []
    return {
        "version": int(index.get("version") or BRIEFING_HISTORY_VERSION),
        "updated_at": str(index.get("updated_at") or ""),
        "cards": [card for card in cards if isinstance(card, dict)],
    }


def load_recent_briefing_cards(data_path: Path, *, limit: int = 10) -> list[dict[str, Any]]:
    cards = load_briefing_index(data_path).get("cards", [])
    sorted_cards = sorted(cards, key=lambda item: str(item.get("generated_at") or ""), reverse=True)
    return sorted_cards[:limit] if limit > 0 else sorted_cards


def load_latest_briefing_card(data_path: Path) -> dict[str, Any] | None:
    for summary in load_recent_briefing_cards(data_path, limit=20):
        date_key = str(summary.get("date") or briefing_date_key(str(summary.get("generated_at") or "")))
        card_id = str(summary.get("id") or "")
        day_document = load_day_document(data_path, date_key)
        for card in reversed(day_document.get("cards", [])):
            if not isinstance(card, dict):
                continue
            if card_id and str(card.get("id") or "") != card_id:
                continue
            return card
    return None


def load_gemini_usage(data_path: Path, date_key: str) -> dict[str, Any]:
    document = load_json(gemini_usage_path(data_path), {})
    if not isinstance(document, dict):
        document = {}
    days = document.get("days")
    if not isinstance(days, dict):
        days = {}
    count = 0
    day = days.get(date_key)
    if isinstance(day, dict):
        try:
            count = int(day.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
    return {
        "version": BRIEFING_HISTORY_VERSION,
        "date": date_key,
        "count": max(0, count),
        "days": days,
    }


def increment_gemini_usage(data_path: Path, generated_at: str) -> dict[str, Any]:
    date_key = briefing_date_key(generated_at)
    usage = load_gemini_usage(data_path, date_key)
    days = dict(usage.get("days") or {})
    day = days.get(date_key) if isinstance(days.get(date_key), dict) else {}
    count = max(0, int(day.get("count") or 0)) + 1
    days[date_key] = {"count": count, "updated_at": generated_at}
    # Keep the file tiny even if the repository lives for years.
    kept_keys = sorted(days.keys())[-45:]
    document = {
        "version": BRIEFING_HISTORY_VERSION,
        "updated_at": generated_at,
        "days": {key: days[key] for key in kept_keys},
    }
    write_json(gemini_usage_path(data_path), document)
    return {"version": BRIEFING_HISTORY_VERSION, "date": date_key, "count": count, "days": document["days"]}


def write_briefing_outputs(data_path: Path, card: dict[str, Any], *, max_cards: int = 80) -> dict[str, Any]:
    date_key = briefing_date_key(str(card.get("generated_at") or ""))
    day_doc = load_day_document(data_path, date_key)
    cards = [item for item in day_doc["cards"] if isinstance(item, dict) and item.get("id") != card.get("id")]
    cards.append(card)
    cards.sort(key=lambda item: str(item.get("generated_at") or ""))
    day_doc["cards"] = cards
    write_json(day_briefing_path(data_path, date_key), day_doc)

    index_path = briefing_index_path(data_path)
    index = load_json(index_path, {})
    if not isinstance(index, dict):
        index = {}
    indexed_cards = [
        item for item in index.get("cards", []) if isinstance(item, dict) and item.get("id") != card.get("id")
    ]
    indexed_cards.append(compact_card(card))
    indexed_cards.sort(key=lambda item: str(item.get("generated_at") or ""), reverse=True)
    indexed_cards = indexed_cards[:max_cards]
    document = {
        "version": BRIEFING_HISTORY_VERSION,
        "updated_at": str(card.get("generated_at") or ""),
        "cards": indexed_cards,
    }
    write_json(index_path, document)
    return document


def important_metric_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    names = {
        "원/달러 환율",
        "엔/달러 환율",
        "엔/원 환율",
        "S&P500 선물",
        "나스닥100 선물",
        "코스피",
        "코스닥",
        "미국 CNN 공포탐욕지수",
        "VKOSPI",
    }
    snapshot: dict[str, Any] = {}
    for metric in payload.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("name") or "")
        if name not in names:
            continue
        value = metric.get("value")
        if isinstance(value, (int, float)):
            snapshot[name] = {
                "value": value,
                "display_value": metric.get("display_value", ""),
                "change_pct": metric.get("change_pct"),
                "observed_at": metric.get("observed_at", ""),
            }
    return snapshot


def trajectory_summary(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    movers: list[dict[str, Any]] = []
    for name, item in current.items():
        before = previous.get(name)
        if not isinstance(before, dict):
            continue
        value = item.get("value")
        previous_value = before.get("value")
        if not isinstance(value, (int, float)) or not isinstance(previous_value, (int, float)) or previous_value == 0:
            continue
        change_pct = (value / previous_value - 1.0) * 100.0
        if abs(change_pct) >= 0.3:
            movers.append(
                {
                    "name": name,
                    "change_pct": round(change_pct, 2),
                    "display_value": item.get("display_value", ""),
                }
            )
    movers.sort(key=lambda item: abs(float(item.get("change_pct") or 0)), reverse=True)
    yen = next((item for item in movers if item["name"] == "엔/달러 환율" and item["change_pct"] <= -1.5), None)
    return {
        "movers": movers[:6],
        "yen_carry_risk": bool(yen),
        "summary": "엔화가 빠르게 강해져 엔캐리 청산 위험을 함께 봐야 합니다." if yen else "",
    }


def update_intraday_track(data_path: Path, payload: dict[str, Any], generated_at: str) -> dict[str, Any]:
    path = data_path / INTRADAY_TRACK_FILENAME
    document = load_json(path, {})
    if not isinstance(document, dict):
        document = {}
    snapshots = document.get("snapshots")
    if not isinstance(snapshots, list):
        snapshots = []
    current = important_metric_snapshot(payload)
    previous = snapshots[-1].get("metrics", {}) if snapshots and isinstance(snapshots[-1], dict) else {}
    snapshots.append({"generated_at": generated_at, "metrics": current})
    snapshots = snapshots[-80:]
    document = {
        "version": BRIEFING_HISTORY_VERSION,
        "updated_at": generated_at,
        "snapshots": snapshots,
    }
    write_json(path, document)
    return trajectory_summary(previous if isinstance(previous, dict) else {}, current)
