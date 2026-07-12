"""AI briefing gating, narrative selection, and Gemini response normalization."""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import requests
import yaml

from .utils import numeric_values_equal, parse_iso_date, to_float

GEMINI_DEFAULT_MODEL = "gemini-3.1-flash-lite"
GEMINI_GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_DAILY_CALL_LIMIT = 400
def briefing_metric_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for metric in payload.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        metric_id = str(metric.get("id") or "").strip()
        if not metric_id:
            continue
        snapshot[metric_id] = {
            "id": metric_id,
            "name": str(metric.get("name") or ""),
            "industry": str(metric.get("industry") or ""),
            "group": str(metric.get("group") or ""),
            "value": to_float(metric.get("value")),
            "display_value": str(metric.get("display_value") or ""),
            "observed_at": str(metric.get("observed_at") or ""),
            "change_pct": to_float(metric.get("change_pct")),
        }
    return snapshot


def observed_at_progressed(current: object, previous: object) -> bool:
    current_text = str(current or "").strip()
    previous_text = str(previous or "").strip()
    if not current_text or current_text == previous_text:
        return False
    current_date = parse_iso_date(current_text)
    previous_date = parse_iso_date(previous_text)
    if current_date and previous_date:
        return current_date > previous_date
    return bool(current_text and current_text != previous_text)


def briefing_metric_changes(
    current_snapshot: dict[str, Any],
    previous_snapshot: dict[str, Any] | None,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    if not previous_snapshot:
        return {
            "changed": True,
            "changed_count": len(current_snapshot),
            "changes": [],
            "changed_ids": list(current_snapshot),
            "reason": "이전 카드 지표 스냅샷 없음",
        }

    changes: list[dict[str, Any]] = []
    for metric_id, current in current_snapshot.items():
        if not isinstance(current, dict):
            continue
        previous = previous_snapshot.get(metric_id)
        if not isinstance(previous, dict):
            changes.append({"id": metric_id, "name": current.get("name", ""), "reason": "신규 지표"})
            continue
        if observed_at_progressed(current.get("observed_at"), previous.get("observed_at")):
            changes.append(
                {
                    "id": metric_id,
                    "name": current.get("name", ""),
                    "reason": "관측일 전진",
                    "previous_observed_at": previous.get("observed_at", ""),
                    "observed_at": current.get("observed_at", ""),
                }
            )
            continue
        if not numeric_values_equal(current.get("value"), previous.get("value")):
            changes.append(
                {
                    "id": metric_id,
                    "name": current.get("name", ""),
                    "reason": "값 변화",
                    "previous_value": previous.get("value"),
                    "value": current.get("value"),
                }
            )

    return {
        "changed": bool(changes),
        "changed_count": len(changes),
        "changes": changes[:limit],
        "changed_ids": [str(item.get("id") or "") for item in changes if item.get("id")],
        "reason": f"{len(changes)}개 지표 변화" if changes else "직전 카드 이후 지표 변화 없음",
    }


def briefing_session_context(now: datetime) -> dict[str, Any]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    kst = now.astimezone(ZoneInfo("Asia/Seoul"))
    minute = kst.hour * 60 + kst.minute
    korea_open = 9 * 60
    korea_close = 15 * 60 + 45
    us_open = 23 * 60
    us_close = 6 * 60 + 15
    if korea_open <= minute <= korea_close:
        return {
            "key": "korea",
            "label": "한국장",
            "benchmark_names": ["코스피", "코스닥"],
            "prompt_focus": "코스피·코스닥과 국내 수급 흐름을 중심으로 쓰고, 남은 한국장 또는 다음 한국장에 줄 함의로 마무리한다.",
        }
    if minute >= us_open or minute <= us_close:
        return {
            "key": "us",
            "label": "미국장",
            "benchmark_names": ["S&P 500", "S&P500 선물", "나스닥", "나스닥100 선물"],
            "prompt_focus": "미국 지수, 환율, 미국 대표주 흐름을 중심으로 쓰고, 내일 한국장에 줄 함의로 마무리한다.",
        }
    return {
        "key": "off",
        "label": "세션 외",
        "benchmark_names": ["코스피", "코스닥", "S&P 500", "나스닥"],
        "prompt_focus": "새로 변한 지표만 짧게 정리하고 다음 정규장에 확인할 점으로 마무리한다.",
    }


def normalized_metric_name(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def benchmark_change_summary(
    current_snapshot: dict[str, Any],
    previous_snapshot: dict[str, Any] | None,
    benchmark_names: list[str],
) -> dict[str, Any]:
    if not previous_snapshot:
        return {"significant": False, "drivers": []}
    targets = {normalized_metric_name(name) for name in benchmark_names}
    drivers: list[dict[str, Any]] = []
    for metric_id, current in current_snapshot.items():
        if not isinstance(current, dict):
            continue
        if normalized_metric_name(current.get("name")) not in targets:
            continue
        previous = previous_snapshot.get(metric_id)
        if not isinstance(previous, dict):
            continue
        current_value = to_float(current.get("value"))
        previous_value = to_float(previous.get("value"))
        if current_value is None or previous_value in (None, 0):
            continue
        change_pct = (current_value / previous_value - 1.0) * 100.0
        if abs(change_pct) >= 0.5:
            drivers.append(
                {
                    "id": metric_id,
                    "name": current.get("name", ""),
                    "change_pct": round(change_pct, 3),
                    "basis": "직전 카드 대비 기준 지수 변화",
                }
            )
    drivers.sort(key=lambda item: abs(float(item.get("change_pct") or 0)), reverse=True)
    return {"significant": bool(drivers), "drivers": drivers}


def daily_move_significance(
    payload: dict[str, Any], changed_ids: set[str] | None = None
) -> dict[str, Any]:
    drivers: list[dict[str, Any]] = []
    for metric in payload.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        if changed_ids and str(metric.get("id") or "") not in changed_ids:
            continue
        change_pct = to_float(metric.get("change_pct"))
        if change_pct is None or abs(change_pct) < 1.0:
            continue
        drivers.append(
            {
                "id": str(metric.get("id") or ""),
                "name": str(metric.get("name") or ""),
                "change_pct": round(change_pct, 3),
                "basis": "당일 등락률",
            }
        )
    drivers.sort(key=lambda item: abs(float(item.get("change_pct") or 0)), reverse=True)
    return {"significant": bool(drivers), "drivers": drivers[:8]}


def consecutive_low_signal_count(cards: list[dict[str, Any]]) -> int:
    count = 0
    for card in cards:
        if not isinstance(card, dict) or not card.get("low_signal"):
            break
        count += 1
    return count


def briefing_generation_decision(
    payload: dict[str, Any],
    previous_card: dict[str, Any] | None,
    recent_cards: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    current_snapshot = briefing_metric_snapshot(payload)
    previous_snapshot = (
        previous_card.get("metric_snapshot")
        if isinstance(previous_card, dict) and isinstance(previous_card.get("metric_snapshot"), dict)
        else None
    )
    changes = briefing_metric_changes(current_snapshot, previous_snapshot)
    session_context = briefing_session_context(now)
    benchmark = benchmark_change_summary(
        current_snapshot,
        previous_snapshot,
        list(session_context.get("benchmark_names") or []),
    )
    changed_ids = {str(metric_id) for metric_id in changes.get("changed_ids", []) if metric_id}
    daily_move = daily_move_significance(payload, changed_ids or None)
    significant = bool(benchmark["significant"] or daily_move["significant"])
    low_signal = bool(changes["changed"] and not significant)
    low_signal_streak = consecutive_low_signal_count(recent_cards)

    skip = False
    reason = str(changes["reason"])
    if not changes["changed"]:
        skip = True
    elif low_signal and low_signal_streak >= 2:
        skip = True
        reason = "low_signal 카드 2회 연속 이후 유의미한 변화 없음"
    elif significant:
        drivers = [*benchmark.get("drivers", []), *daily_move.get("drivers", [])]
        lead = drivers[0] if drivers else {}
        reason = f"유의미한 변화: {lead.get('name') or '주요 지표'}"
    elif low_signal:
        reason = "변화는 있으나 유의미성 낮음"

    return {
        "skip": skip,
        "reason": reason,
        "low_signal": low_signal,
        "low_signal_streak": low_signal_streak,
        "significant": significant,
        "session": session_context,
        "changes": changes,
        "benchmark": benchmark,
        "daily_move": daily_move,
        "metric_snapshot": current_snapshot,
    }


def build_morning_briefing(
    payload: dict[str, Any],
    session: requests.Session,
    *,
    briefing_context: dict[str, Any] | None = None,
    gemini_allowed: bool = True,
    disabled_message: str | None = None,
) -> dict[str, Any]:
    briefing = rule_based_morning_briefing(payload, briefing_context)
    if briefing_context:
        briefing["briefing_context"] = briefing_context
        briefing["low_signal"] = bool(briefing_context.get("low_signal"))
    briefing["gemini_call_attempted"] = False
    if not gemini_allowed:
        briefing["status"] = "disabled"
        briefing["status_message"] = disabled_message or "Gemini 요약 비활성화"
        return briefing
    if str(os.getenv("GEMINI_BRIEFING_ENABLED", "1")).strip().lower() in {"0", "false", "no", "off"}:
        briefing["status"] = "disabled"
        briefing["status_message"] = "Gemini 요약 비활성화"
        return briefing

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        briefing["status"] = "skipped"
        briefing["status_message"] = "Gemini API 키 없음"
        return briefing

    model = os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL).strip() or GEMINI_DEFAULT_MODEL
    try:
        prompt = gemini_morning_briefing_prompt(payload, briefing)
        briefing["gemini_call_attempted"] = True
        raw_text = request_gemini_briefing(session, api_key, model, prompt)
        parsed = parse_json_object(raw_text)
        return normalize_gemini_briefing(parsed, briefing, model)
    except Exception as exc:  # noqa: BLE001 - the dashboard should still publish without AI text.
        briefing["status"] = "error"
        briefing["status_message"] = f"Gemini 요약 실패: {exc}"
        briefing["model"] = model
        return briefing


def rule_based_morning_briefing(
    payload: dict[str, Any], briefing_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    metrics = [metric for metric in payload.get("metrics", []) if isinstance(metric, dict)]
    changed_ids = {
        str(item.get("id") or "")
        for item in ((briefing_context or {}).get("changed_metrics") or [])
        if isinstance(item, dict) and item.get("id")
    }
    top_movers = top_mover_metrics(metrics, changed_ids=changed_ids or None)
    improving_industries = industry_signal_rows(metrics, "change_pct", reverse=True)[:3]
    slowing_industries = industry_signal_rows(metrics, "yoy_pct", reverse=False)[:3]
    equity_leads = equity_lead_rows(metrics)[:3]
    source_issues = [
        {
            "name": str(source.get("name") or ""),
            "status": str(source.get("status") or ""),
            "message": str(source.get("message") or ""),
        }
        for source in payload.get("source_status", [])
        if isinstance(source, dict) and source.get("status") != "ok"
    ]
    narrative_candidates = ((briefing_context or {}).get("market_narrative") or {}).get("candidates") or []
    persistent_events = (briefing_context or {}).get("persistent_events") or []
    headline = "오늘 변한 지표가 업황에 주는 의미를 먼저 확인하세요."
    if narrative_candidates:
        candidate = narrative_candidates[0]
        headline = f"{candidate.get('label') or candidate.get('industry')} 흐름이 두드러집니다."
    elif top_movers:
        first = top_movers[0]
        headline = f"{first['industry']} {first['name']} 변화가 눈에 띕니다."
    narrative_topics = [
        f"산업:{item['industry']}"
        for item in top_movers
        if item.get("industry")
    ][:3]
    bullets = rule_based_bullets(top_movers, improving_industries, slowing_industries, equity_leads)
    if persistent_events:
        event = persistent_events[0]
        change = str(event.get("change_pct_label") or "큰 폭 변동")
        progression = str(event.get("progression") or "큰 움직임 지속")
        bullets.append(
            {
                "title": "계속 볼 사건",
                "body": (
                    f"{event.get('industry')} {event.get('name')}가 당일 {change} 움직인 채 "
                    f"{progression} 중입니다. 새 흐름과 함께 시장 영향이 이어지는지 확인해야 합니다."
                ),
                "metric_ids": [str(event.get("id") or "")],
            }
        )
    return {
        "status": "fallback",
        "status_message": "룰 기반 요약",
        "model": "",
        "generated_label": str(payload.get("generated_label") or ""),
        "headline": headline,
        "summary": rule_based_summary(top_movers, improving_industries, slowing_industries, source_issues),
        "bullets": bullets[:5],
        "top_movers": top_movers,
        "improving_industries": improving_industries,
        "slowing_industries": slowing_industries,
        "equity_leads": equity_leads,
        "source_issues": source_issues,
        "narrative_topics": list(dict.fromkeys(narrative_topics)),
    }


def narrative_context_for_briefing(briefing: dict[str, Any], limit: int = 6) -> dict[str, Any]:
    narratives = load_industry_narratives()
    if not narratives:
        return {}

    industry_order = relevant_briefing_industries(briefing, limit)
    industry_map = narratives.get("industries") if isinstance(narratives.get("industries"), dict) else {}
    selected = []
    for industry in industry_order:
        item = industry_map.get(industry) if isinstance(industry_map, dict) else None
        if not isinstance(item, dict):
            continue
        selected.append(
            {
                "industry": industry,
                "narrative": short_text(item.get("narrative"), "", 130),
                "focus_metrics": [short_text(value, "", 32) for value in list(item.get("key_metrics") or [])[:4]],
                "lens": short_text(item.get("lens"), "", 130),
            }
        )
    if not selected:
        return {}
    return {
        "as_of": str(narratives.get("as_of") or ""),
        "global_frame": short_text(narratives.get("global_frame"), "", 170),
        "common_rules": [short_text(value, "", 90) for value in list(narratives.get("common_rules") or [])[:3]],
        "stock_market": compact_stock_market_narrative(narratives.get("stock_market")),
        "industries": selected,
    }


def compact_stock_market_narrative(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "narrative": short_text(value.get("narrative"), "", 230),
        "key_signals": [short_text(item, "", 32) for item in list(value.get("key_signals") or [])[:5]],
        "lens": short_text(value.get("lens"), "", 170),
        "rotation": short_text(value.get("rotation"), "", 130),
    }


def relevant_briefing_industries(briefing: dict[str, Any], limit: int) -> list[str]:
    ordered: list[str] = []

    def add(industry: Any) -> None:
        text = str(industry or "").strip()
        if text and text not in ordered:
            ordered.append(text)

    for metric in briefing.get("top_movers") or []:
        if isinstance(metric, dict):
            add(metric.get("industry"))
    for section in ("improving_industries", "slowing_industries", "equity_leads"):
        for row in briefing.get(section) or []:
            if isinstance(row, dict):
                add(row.get("industry"))
                for metric in row.get("drivers") or []:
                    if isinstance(metric, dict):
                        add(metric.get("industry"))
    return ordered[:limit]


def load_industry_narratives() -> dict[str, Any]:
    candidates = [
        Path.cwd() / "docs" / "industry_narratives.yaml",
        Path(__file__).resolve().parents[2] / "docs" / "industry_narratives.yaml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def is_representative_stock(metric: dict[str, Any]) -> bool:
    return str(metric.get("group") or "") == "대표주가" and str(metric.get("history_key") or "").startswith("equity-")


def equity_market_for_metric(metric: dict[str, Any]) -> str:
    history_key = str(metric.get("history_key") or "").upper()
    return "korea" if history_key.endswith((".KS", ".KQ")) else "us"


def recent_narrative_industries(cards: list[dict[str, Any]], limit: int = 4) -> dict[str, float]:
    penalties: dict[str, float] = defaultdict(float)
    for card_index, card in enumerate(cards[:limit]):
        if not isinstance(card, dict):
            continue
        topics = card.get("narrative_topics")
        if not isinstance(topics, list):
            continue
        weight = max(0.25, 1.15 - card_index * 0.25)
        for topic in topics[:4]:
            parts = str(topic or "").split(":")
            if len(parts) >= 2 and parts[0] in {"산업", "industry"} and parts[1]:
                penalties[parts[1]] += weight
    return dict(penalties)


def market_narrative_context(
    payload: dict[str, Any],
    session_context: dict[str, Any] | None,
    recent_cards: list[dict[str, Any]],
    *,
    changed_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Build evidence-ranked market narratives without using old prose as evidence."""
    metrics = [item for item in payload.get("metrics", []) if isinstance(item, dict)]
    session_key = str((session_context or {}).get("key") or "off")
    market_filter = "korea" if session_key == "korea" else "us" if session_key == "us" else ""
    stocks = [item for item in metrics if is_representative_stock(item)]
    session_stocks = [item for item in stocks if not market_filter or equity_market_for_metric(item) == market_filter]
    if len(session_stocks) >= 2:
        stocks = session_stocks

    benchmark_names = set((session_context or {}).get("benchmark_names") or [])
    benchmark_moves = [
        to_float(item.get("change_pct"))
        for item in metrics
        if str(item.get("name") or "") in benchmark_names and to_float(item.get("change_pct")) is not None
    ]
    benchmark_move = float(median(benchmark_moves)) if benchmark_moves else 0.0
    by_industry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stock in stocks:
        if to_float(stock.get("change_pct")) is None:
            continue
        industry = str(stock.get("industry") or "")
        if industry and industry != "매크로":
            by_industry[industry].append(stock)

    repetition_penalty = recent_narrative_industries(recent_cards)
    candidates: list[dict[str, Any]] = []
    for industry, industry_stocks in by_industry.items():
        if len(industry_stocks) < 2:
            continue
        moves = [float(to_float(item.get("change_pct")) or 0.0) for item in industry_stocks]
        median_move = float(median(moves))
        direction = "strong" if median_move >= 0 else "weak"
        aligned_count = sum(1 for value in moves if value >= 0) if direction == "strong" else sum(1 for value in moves if value < 0)
        breadth = aligned_count / len(moves)
        relative_move = median_move - benchmark_move
        changed_count = sum(1 for item in industry_stocks if not changed_ids or str(item.get("id") or "") in changed_ids)
        raw_score = abs(median_move) * 0.75 + abs(relative_move) * 0.55 + max(0.0, breadth - 0.5) * 2.0
        if changed_ids and changed_count:
            raw_score += min(1.0, changed_count * 0.25)
        if abs(median_move) < 0.6 and abs(relative_move) < 0.8:
            continue
        penalty = float(repetition_penalty.get(industry) or 0.0)
        persistent_major = abs(median_move) >= 3.0 and breadth >= 0.67
        if persistent_major:
            # A market-defining move may remain relevant all day. Repetition
            # lowers its priority, but cannot erase it from the candidate set.
            penalty = min(penalty, raw_score * 0.25)
        adjusted_score = raw_score - penalty
        evidence = sorted(
            industry_stocks,
            key=lambda item: abs(to_float(item.get("change_pct")) or 0.0),
            reverse=True,
        )[:4]
        fundamentals = [
            item
            for item in metrics
            if str(item.get("industry") or "") == industry
            and not is_representative_stock(item)
            and item.get("status") == "ok"
            and not item.get("is_stale")
            and (to_float(item.get("change_pct")) is not None or to_float(item.get("yoy_pct")) is not None)
        ]
        fundamentals.sort(
            key=lambda item: (bool(item.get("is_updated_today")), str(item.get("observed_at") or "")),
            reverse=True,
        )
        candidates.append(
            {
                "topic": f"산업:{industry}:{direction}",
                "industry": industry,
                "direction": direction,
                "label": f"{industry} {'주도' if direction == 'strong' else '약세'}",
                "median_change_pct": round(median_move, 2),
                "benchmark_change_pct": round(benchmark_move, 2),
                "relative_change_pct_point": round(relative_move, 2),
                "breadth": f"{aligned_count}/{len(moves)}",
                "raw_score": round(raw_score, 3),
                "repetition_penalty": round(penalty, 3),
                "score": round(adjusted_score, 3),
                "new_evidence_count": changed_count,
                "persistent_major": persistent_major,
                "evidence": [brief_metric(item) for item in evidence],
                "fundamental_checks": [brief_metric(item) for item in fundamentals[:2]],
            }
        )
    candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)

    breadth_moves = [to_float(item.get("change_pct")) for item in stocks]
    breadth_moves = [float(value) for value in breadth_moves if value is not None]
    cross_asset_names = {
        "VIX", "원/달러 환율", "미국 10년 국채금리", "S&P500 선물", "나스닥100 선물",
        "비트코인", "달러인덱스", "WTI 선물(CL)", "Brent 선물(BZ)",
    }
    cross_assets = [
        brief_metric(item)
        for item in metrics
        if str(item.get("name") or "") in cross_asset_names and to_float(item.get("value")) is not None
    ]
    return {
        "session": session_key,
        "benchmark_change_pct": round(benchmark_move, 2),
        "market_breadth": {
            "positive": sum(1 for value in breadth_moves if value > 0),
            "negative": sum(1 for value in breadth_moves if value < 0),
            "unchanged": sum(1 for value in breadth_moves if value == 0),
            "sample_size": len(breadth_moves),
        },
        "candidates": candidates[:6],
        "cross_assets": cross_assets,
        "freshness": payload.get("freshness_summary", {}),
        "recent_topic_history": [
            {"industry": industry, "penalty": round(value, 2)}
            for industry, value in sorted(repetition_penalty.items(), key=lambda item: item[1], reverse=True)
        ],
        "selection_rule": "score는 당일 산업 중앙값·시장 대비 상대강도·상승/하락 종목 비율·직전 카드 이후 새 변화로 계산하며, 최근 반복 주제에는 감점을 적용합니다.",
    }


def persistent_event_threshold(metric: dict[str, Any]) -> float:
    group = str(metric.get("group") or "")
    if group == "시장지수":
        return 2.0
    if group == "대표주가":
        return 5.0
    if str(metric.get("name") or "") in {"VIX", "VKOSPI", "원/달러 환율"}:
        return 3.0
    return 4.0


def persistent_market_events(
    payload: dict[str, Any],
    previous_snapshot: dict[str, Any] | None,
    recent_cards: list[dict[str, Any]],
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    recent_industries = recent_narrative_industries(recent_cards)
    events: list[dict[str, Any]] = []
    for metric in payload.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        current_change = to_float(metric.get("change_pct"))
        if current_change is None or abs(current_change) < persistent_event_threshold(metric):
            continue
        metric_id = str(metric.get("id") or "")
        previous = (previous_snapshot or {}).get(metric_id)
        previous_change = to_float(previous.get("change_pct")) if isinstance(previous, dict) else None
        if previous_change is None:
            progression = "신규 포착"
        elif current_change * previous_change < 0:
            progression = "방향 반전"
        elif abs(current_change) - abs(previous_change) >= 0.5:
            progression = "상승폭 확대" if current_change > 0 else "낙폭 확대"
        elif abs(previous_change) - abs(current_change) >= 0.5:
            progression = "상승폭 축소" if current_change > 0 else "낙폭 축소"
        else:
            progression = "큰 움직임 지속"
        industry = str(metric.get("industry") or "")
        events.append(
            {
                **brief_metric(metric),
                "topic": f"산업:{industry}:{'strong' if current_change >= 0 else 'weak'}",
                "progression": progression,
                "previous_card_change_pct": previous_change,
                "mentioned_recently": bool(recent_industries.get(industry)),
                "instruction": "반복 언급 시 원인 문장을 복사하지 말고 직전 카드 이후 확대·축소·반전과 새 흐름을 설명합니다.",
            }
        )
    events.sort(key=lambda item: abs(float(item.get("change_pct") or 0.0)), reverse=True)
    return events[:limit]


def is_persistent_market_metric(metric: dict[str, Any]) -> bool:
    change = to_float(metric.get("change_pct"))
    return change is not None and abs(change) >= persistent_event_threshold(metric)


def top_mover_metrics(
    metrics: list[dict[str, Any]], *, changed_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    if changed_ids:
        updated = [metric for metric in metrics if str(metric.get("id") or "") in changed_ids]
    else:
        updated = [metric for metric in metrics if metric.get("daily_status") in {"updated", "new"}]
    candidates = updated or metrics
    ranked = [
        metric
        for metric in candidates
        if to_float(metric.get("change_pct")) is not None
        and not metric.get("exclude_from_movers")
    ]
    ranked.sort(key=lambda metric: abs(to_float(metric.get("change_pct")) or 0.0), reverse=True)
    if changed_ids:
        persistent = [
            metric
            for metric in metrics
            if str(metric.get("id") or "") not in changed_ids
            and is_persistent_market_metric(metric)
            and not metric.get("exclude_from_movers")
        ]
        persistent.sort(key=lambda metric: abs(to_float(metric.get("change_pct")) or 0.0), reverse=True)
        ranked = [*ranked[:4], *persistent[:2]]
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for metric in ranked:
        metric_id = str(metric.get("id") or "")
        if metric_id in seen:
            continue
        seen.add(metric_id)
        deduped.append(metric)
    return [brief_metric(metric) for metric in deduped[:5]]


def industry_signal_rows(
    metrics: list[dict[str, Any]], field: str, *, reverse: bool
) -> list[dict[str, Any]]:
    by_industry: dict[str, list[tuple[float, dict[str, Any]]]] = defaultdict(list)
    for metric in metrics:
        value = to_float(metric.get(field))
        if value is None:
            continue
        signal = value * metric_direction(metric)
        by_industry[str(metric.get("industry") or "매크로")].append((signal, metric))

    rows: list[dict[str, Any]] = []
    for industry, items in by_industry.items():
        if not items:
            continue
        score = sum(signal for signal, _metric in items) / len(items)
        drivers = sorted(items, key=lambda item: abs(item[0]), reverse=True)[:2]
        rows.append(
            {
                "industry": industry,
                "score": round(score, 2),
                "drivers": [brief_metric(metric) for _signal, metric in drivers],
            }
        )
    rows.sort(key=lambda row: row["score"], reverse=reverse)
    return rows


def equity_lead_rows(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_industry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        by_industry[str(metric.get("industry") or "매크로")].append(metric)

    rows: list[dict[str, Any]] = []
    for industry, items in by_industry.items():
        equities = [metric for metric in items if str(metric.get("group") or "") == "대표주가"]
        fundamentals = [metric for metric in items if str(metric.get("group") or "") != "대표주가"]
        equity_values = [to_float(metric.get("change_pct")) for metric in equities]
        fundamental_values = [to_float(metric.get("change_pct")) for metric in fundamentals]
        equity_values = [value for value in equity_values if value is not None]
        fundamental_values = [value for value in fundamental_values if value is not None]
        if not equity_values or not fundamental_values:
            continue
        equity_score = sum(equity_values) / len(equity_values)
        fundamental_score = sum(fundamental_values) / len(fundamental_values)
        gap = equity_score - fundamental_score
        if abs(equity_score) < 2 and abs(gap) < 3:
            continue
        if equity_score * fundamental_score > 0 and abs(gap) < 5:
            continue
        rows.append(
            {
                "industry": industry,
                "equity_score": round(equity_score, 2),
                "fundamental_score": round(fundamental_score, 2),
                "gap": round(gap, 2),
                "drivers": [
                    brief_metric(max(equities, key=lambda metric: abs(to_float(metric.get("change_pct")) or 0.0))),
                    brief_metric(max(fundamentals, key=lambda metric: abs(to_float(metric.get("change_pct")) or 0.0))),
                ],
            }
        )
    rows.sort(key=lambda row: abs(row["gap"]), reverse=True)
    return rows


def metric_direction(metric: dict[str, Any]) -> int:
    text = " ".join(
        str(metric.get(key) or "")
        for key in ("name", "group", "meaning")
    )
    lower_is_better_keywords = (
        "VIX",
        "스프레드",
        "금리",
        "연체율",
        "모기지",
        "위험",
        "리스크",
    )
    return -1 if any(keyword in text for keyword in lower_is_better_keywords) else 1


def brief_metric(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(metric.get("id") or ""),
        "industry": str(metric.get("industry") or ""),
        "group": str(metric.get("group") or ""),
        "kind": metric_kind_label(metric),
        "name": str(metric.get("name") or ""),
        "value": str(metric.get("display_value") or ""),
        "observed_label": str(metric.get("observed_label") or ""),
        "change_pct": to_float(metric.get("change_pct")),
        "change_pct_label": str(metric.get("change_pct_label") or ""),
        "yoy_pct": to_float(metric.get("yoy_pct")),
        "yoy_pct_label": str(metric.get("yoy_pct_label") or ""),
        "meaning": short_text(metric.get("meaning"), "", 120),
    }


def metric_kind_label(metric: dict[str, Any]) -> str:
    group = str(metric.get("group") or "")
    name = str(metric.get("name") or "")
    text = f"{group} {name}"
    if group == "대표주가":
        return "대표주가(주식 가격)"
    if group == "시장지수":
        return "시장지수"
    if "WSTS" in text or "판매액" in group:
        return "반도체 판매액"
    if "CAPEX" in text.upper():
        return "설비투자(CAPEX)"
    if any(keyword in text for keyword in ("원자재", "유가", "철광석", "구리", "알루미늄", "니켈", "석탄", "천연가스")):
        return "원자재/에너지 가격"
    if any(keyword in text for keyword in ("금리", "스프레드", "OAS", "연체율", "대출")):
        return "금융여건 지표"
    if "수출" in text:
        return "수출 지표"
    if any(keyword in text for keyword in ("승인", "임상", "발사", "계약", "충전")):
        return "산업 활동 지표"
    return group or "업황 지표"


def metric_change_meaning(metric: dict[str, Any]) -> str:
    group = str(metric.get("group") or "")
    name = str(metric.get("name") or "")
    text = f"{group} {name}"
    change = to_float(metric.get("change_pct"))
    improved = change is None or change * metric_direction(metric) >= 0

    if group == "대표주가":
        return "실적이 바로 바뀌었다기보다, 시장이 해당 산업의 기대와 위험을 다시 가격에 반영한 신호로 볼 수 있습니다."
    if group == "시장지수":
        return "개별 산업보다 전체 투자심리와 위험 선호가 움직였는지 확인하는 신호입니다."
    if "CAPEX" in text.upper():
        return "AI와 클라우드 인프라 투자가 앞으로도 강하게 이어질지 보여주는 단서입니다."
    if "판매액" in group or "WSTS" in group:
        return "반도체가 실제로 얼마나 팔리고 있는지 보여주기 때문에 업황의 바닥과 회복 속도를 보는 데 중요합니다."
    if any(keyword in text for keyword in ("원자재", "유가", "철광석", "구리", "알루미늄", "리튬")):
        return "소재와 제조업의 비용 부담이 커지는지 줄어드는지 확인하는 지표입니다."
    if any(keyword in text for keyword in ("금리", "스프레드", "모기지", "연체율")):
        return "돈을 빌리는 부담과 금융 스트레스가 완화되는지 악화되는지 보는 지표입니다."
    if any(keyword in text for keyword in ("승인", "임상", "발사", "계약", "충전")):
        return "해당 산업의 실제 활동량과 투자 속도가 살아나는지 확인하는 힌트입니다."
    return "하루 가격 움직임만 보기보다, 같은 산업의 수요·투자·실적 지표와 같이 보면 의미가 더 분명해집니다." if improved else "단기 변동일 수 있으니, 같은 산업의 수요·투자·실적 지표도 함께 확인하는 편이 좋습니다."


def metric_change_summary(metric: dict[str, Any]) -> str:
    change = str(metric.get("change_pct_label") or "변동")
    kind = str(metric.get("kind") or metric.get("group") or "지표")
    name = str(metric.get("name") or "지표")
    return (
        f"{metric['industry']}의 {kind}인 {name}{subject_particle(name)} {change} 움직였습니다. "
        f"{metric_change_meaning(metric)}"
    )


def topic_label(text: str) -> str:
    return f"{text}{topic_particle(text)}"


def topic_particle(text: str) -> str:
    for char in reversed(str(text or "").strip()):
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3:
            return "은" if (code - 0xAC00) % 28 else "는"
        if char.isalnum():
            return "는"
    return "는"


def subject_particle(text: str) -> str:
    """Return the natural Korean subject particle for a metric name."""
    for char in reversed(str(text or "").strip()):
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3:
            return "이" if (code - 0xAC00) % 28 else "가"
        if char.isalnum():
            return "가"
    return "가"


def rule_based_summary(
    top_movers: list[dict[str, Any]],
    improving_industries: list[dict[str, Any]],
    slowing_industries: list[dict[str, Any]],
    source_issues: list[dict[str, Any]],
) -> str:
    parts = []
    if top_movers:
        parts.append(metric_change_summary(top_movers[0]))
    if improving_industries:
        industry = improving_industries[0]["industry"]
        parts.append(f"{industry} 쪽은 최근 지표 흐름이 상대적으로 좋아져 수요나 투자 강도가 살아있는지 볼 만합니다.")
    if slowing_industries:
        industry = slowing_industries[0]["industry"]
        parts.append(f"{topic_label(industry)} 전년 대비 힘이 약해진 항목이 있어, 회복이 이어지는지 한 번 더 확인하는 게 좋습니다.")
    if source_issues:
        parts.append("일부 지표는 아직 새 값이 들어오지 않았을 수 있어 오늘 바뀐 항목을 우선 보면 됩니다.")
    return " ".join(parts) or "오늘 새로 해석할 만큼 크게 움직인 지표가 아직 많지 않습니다."


def rule_based_bullets(
    top_movers: list[dict[str, Any]],
    improving_industries: list[dict[str, Any]],
    slowing_industries: list[dict[str, Any]],
    equity_leads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bullets: list[dict[str, Any]] = []
    if top_movers:
        bullets.append(
            {
                "title": "급변 지표",
                "body": metric_change_summary(top_movers[0]),
                "metric_ids": [item["id"] for item in top_movers[:3] if item.get("id")],
            }
        )
    if improving_industries:
        row = improving_industries[0]
        bullets.append(
            {
                "title": "좋아진 흐름",
                "body": f"{topic_label(row['industry'])} 여러 지표가 상대적으로 좋아져 수요나 투자 강도가 유지되는지 볼 만합니다.",
                "metric_ids": [item["id"] for item in row.get("drivers", []) if item.get("id")],
            }
        )
    if slowing_industries:
        row = slowing_industries[0]
        bullets.append(
            {
                "title": "주의할 흐름",
                "body": f"{topic_label(row['industry'])} 전년 대비 힘이 약해진 항목이 있어 회복 속도를 조심해서 봐야 합니다.",
                "metric_ids": [item["id"] for item in row.get("drivers", []) if item.get("id")],
            }
        )
    if equity_leads:
        row = equity_leads[0]
        bullets.append(
            {
                "title": "주가와 지표 차이",
                "body": f"{topic_label(row['industry'])} 주가와 실제 지표의 움직임 차이가 커서 기대가 앞서가는지 확인이 필요합니다.",
                "metric_ids": [item["id"] for item in row.get("drivers", []) if item.get("id")],
            }
        )
    return bullets

def gemini_morning_briefing_prompt(payload: dict[str, Any], briefing: dict[str, Any]) -> str:
    briefing_context = briefing.get("briefing_context") if isinstance(briefing.get("briefing_context"), dict) else {}
    session_context = briefing_context.get("session") if isinstance(briefing_context.get("session"), dict) else {}
    session_label = str(session_context.get("label") or "세션 외")
    prompt_focus = str(session_context.get("prompt_focus") or "")
    low_signal = bool(briefing_context.get("low_signal"))
    card_type = str(briefing_context.get("card_type") or "")
    context = {
        "generated_label": payload.get("generated_label", ""),
        "briefing_context": {
            key: briefing_context.get(key)
            for key in (
                "card_type", "low_signal", "reason", "significant", "benchmark_drivers",
                "daily_move_drivers", "changed_metrics",
            )
            if key in briefing_context
        },
        "session_label": session_label,
        "low_signal": low_signal,
        "market_narrative": briefing_context.get("market_narrative") or {},
        "structural_lenses": narrative_context_for_briefing(briefing),
        "recent_topic_history": briefing_context.get("recent_topic_history") or [],
        "persistent_events": briefing_context.get("persistent_events") or [],
        "day_card_flow": briefing_context.get("day_card_flow") or [],
        "top_movers": briefing.get("top_movers", []),
        "improving_industries": briefing.get("improving_industries", []),
        "slowing_industries": briefing.get("slowing_industries", []),
        "equity_leads": briefing.get("equity_leads", []),
        "source_issues": briefing.get("source_issues", []),
        "daily_changes": payload.get("daily_changes", {}),
        "upcoming_events": (payload.get("calendar", {}) or {}).get("upcoming", []),
    }
    session_instruction = (
        f"현재 실행 세션은 '{session_label}'이다. {prompt_focus}\n"
        "한국장 카드라면 코스피·코스닥과 국내 수급을 우선하고, 미국장 카드라면 미국 지수·환율·미국 대표주를 우선하라.\n"
        "특히 미국장 카드는 마지막 문장에 내일 한국장에 줄 함의를 짧게 넣어라.\n"
    )
    low_signal_instruction = (
        "이번 카드는 low_signal=true다. 변화는 있지만 유의미성이 낮으므로 과장하지 말고, headline·summary를 담백하게 쓰고 bullets는 1~2개만 사용하라.\n"
        if low_signal
        else ""
    )
    close_instruction = ""
    if card_type == "close":
        close_instruction = (
            "이번 카드는 한국장 마감 카드다. day_card_flow와 changed_metrics를 함께 보고 당일 한국장 흐름을 종합하라. "
            "코스피·코스닥·수급·환율을 우선하고 다음 거래일에 확인할 점으로 마무리하라.\n"
        )
    elif card_type == "us_close":
        close_instruction = (
            "이번 카드는 미국장 마감 카드다. 미국 지수·환율·미국 대표주 움직임을 우선하고 내일 한국장에 줄 함의로 마무리하라.\n"
        )
    return (
        "너는 개인 투자자가 매일 아침 산업별 지표 대시보드를 빠르게 훑도록 돕는 한국어 브리핑 작성자다.\n"
        "아래 JSON 데이터만 근거로 사용하고, 매수/매도 추천이나 목표가는 쓰지 마라.\n"
        f"{session_instruction}"
        f"{low_signal_instruction}"
        f"{close_instruction}"
        "가장 중요한 목표는 개별 등락을 나열하는 것이 아니라 지금 시장을 움직이는 주도 산업, 약한 산업, 수급과 교차자산의 연결을 설명하는 것이다.\n"
        "각 지표를 언급할 때는 name만 쓰지 말고 반드시 kind와 industry를 함께 써라. 예: '로봇 대표주가(주식 가격) Teradyne(TER)'처럼 쓴다.\n"
        "한국어 조사는 반드시 자연스럽게 맞춰라. 지표명을 주어로 쓸 때는 마지막 글자의 받침에 맞춰 이/가를 선택한다. "
        "예: 'Phase 3 임상 시작이 +5.6% 움직였습니다'가 맞고, 'Phase 3 임상 시작가'는 쓰지 마라.\n"
        "market_narrative.candidates는 당일 대표주 표본의 중앙 등락률, 시장 대비 상대강도, 상승·하락 종목 비율로 계산된 현재 근거다. score가 높은 후보부터 검토하되 evidence와 fundamental_checks가 실제로 뒷받침하는 범위에서만 주도/약세라고 표현하라.\n"
        "recent_topic_history는 반복을 피하기 위한 감점 기록일 뿐 현재 시장의 증거가 아니다. 직전 카드가 방산을 다뤘다는 이유만으로 방산을 다시 고르지 말고, 새 evidence가 있으며 여전히 최상위 후보일 때만 반복하라.\n"
        "persistent_events는 하루 종일 시장을 지배할 수 있는 급등·폭락·지수 충격이다. 여전히 극단적이면 후속 카드에도 남기되 같은 설명을 복사하지 말고 progression의 낙폭 확대·축소·반전 여부를 말하라. 새 변화가 더 중요하면 persistent event는 headline이 아니라 보조 bullet로 내려라.\n"
        "직전 카드 이후 새로 변한 changed_metrics를 우선하고, 이전 headline이나 문장을 다음 카드의 전제로 복사하지 마라. 선두 후보가 바뀌면 headline과 summary의 주제도 바꿔라.\n"
        "structural_lenses는 산업을 해석하는 일반 원리다. 현재 상황을 단정하는 자료가 아니므로 market_narrative와 지표 데이터가 뒷받침할 때만 적용하라.\n"
        "structural_lenses.stock_market은 대표주가를 해석하는 일반 렌즈다. 대표주가가 움직일 때는 산업 실물지표와 밸류에이션·금리·포지셔닝을 함께 확인하라.\n"
        "어려운 통계 용어를 피하고, 수요가 강해졌는지, 비용 부담이 커졌는지, 투자심리가 흔들렸는지처럼 사용자가 바로 이해할 수 있게 써라.\n"
        "주가 지표는 기업 실적 자체가 아니라 시장 기대와 위험 선호가 움직인 신호라는 점을 구분해서 설명하라.\n"
        "월간·분기 지표는 새 발표 전까지 그대로일 수 있으니, daily_changes와 top_movers를 우선해서 해석하라.\n"
        "upcoming_events에 오늘·내일 FOMC, 금통위, CPI, 만기일 같은 큰 일정이 있으면 관망 심리나 변동성 가능성을 짧게 언급하라.\n"
        "불확실하거나 데이터 공백이 있으면 사용자 친화적으로 짧게 말하라.\n"
        "출력은 설명 없이 JSON 객체 하나만 반환하라.\n"
        "스키마: {\"headline\": string, \"summary\": string, \"narrative_topics\": [string], \"bullets\": "
        "[{\"title\": string, \"body\": string, \"metric_ids\": [string]}]}\n"
        "headline은 40자 이내로 오늘의 핵심 변화를 쉽게 말하라.\n"
        "narrative_topics는 실제로 다룬 주제를 '산업:반도체:strong' 같은 형식으로 최대 3개만 기록하라.\n"
        "summary는 2문장 이내로 '무엇이 변했고 왜 봐야 하는지'를 설명하라.\n"
        "bullets는 3~5개이며 title은 '급변 지표', '좋아진 흐름', '주의할 흐름', '주가와 지표 차이'처럼 짧은 항목명으로 쓰고, body는 '변한 지표의 종류 + 의미 + 다음에 볼 것'을 한 문장으로 써라.\n"
        f"데이터:\n{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}"
    )


def request_gemini_briefing(
    session: requests.Session, api_key: str, model: str, prompt: str
) -> str:
    url = GEMINI_GENERATE_URL.format(model=model)
    response = session.post(
        url,
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 900,
                "responseMimeType": "application/json",
            },
        },
        timeout=30,
    )
    response.raise_for_status()
    text = extract_gemini_text(response.json())
    if not text:
        raise RuntimeError("Gemini 응답에 텍스트가 없습니다.")
    return text


def extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""
    texts = [str(part.get("text") or "") for part in parts if isinstance(part, dict)]
    return "\n".join(text for text in texts if text).strip()


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Gemini JSON 응답이 객체가 아닙니다.")
    return parsed


def normalize_gemini_briefing(
    parsed: dict[str, Any], fallback: dict[str, Any], model: str
) -> dict[str, Any]:
    briefing = dict(fallback)
    briefing.update(
        {
            "status": "ok",
            "status_message": "Gemini 요약",
            "model": model,
            "headline": short_text(parsed.get("headline"), fallback.get("headline", ""), 80),
            "summary": short_text(parsed.get("summary"), fallback.get("summary", ""), 360),
            "bullets": normalize_briefing_bullets(parsed.get("bullets"), fallback.get("bullets", [])),
            "narrative_topics": [
                short_text(topic, "", 64)
                for topic in (
                    parsed.get("narrative_topics")
                    if isinstance(parsed.get("narrative_topics"), list)
                    else fallback.get("narrative_topics", [])
                )
                if str(topic or "").strip()
            ][:3],
        }
    )
    return briefing


def normalize_briefing_bullets(value: Any, fallback: Any) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else fallback
    bullets: list[dict[str, Any]] = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        metric_ids = item.get("metric_ids")
        bullets.append(
            {
                "title": short_text(item.get("title"), "체크포인트", 40),
                "body": short_text(item.get("body"), "", 220),
                "metric_ids": [
                    str(metric_id)
                    for metric_id in (metric_ids if isinstance(metric_ids, list) else [])
                    if metric_id
                ][:3],
            }
        )
    return bullets

def short_text(value: Any, fallback: Any, max_length: int) -> str:
    text = str(value if value not in (None, "") else fallback or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_length]
