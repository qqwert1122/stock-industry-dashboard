"""Rule-based metric interpretation helpers.

The dashboard already has definitions, history, and percentile stats. This
module turns those into short calculation-based explanations without any LLM
call, so the detail panel can show what the latest value means.
"""

from __future__ import annotations

from typing import Any


ZONE_LABELS = {
    "hot": "역사적 고점권",
    "warm": "평균보다 높은 구간",
    "neutral": "중간 구간",
    "cool": "평균보다 낮은 구간",
    "cold": "역사적 저점권",
}

ZONE_ORDER = [
    (90.0, "hot"),
    (70.0, "warm"),
    (30.0, "neutral"),
    (10.0, "cool"),
    (0.0, "cold"),
]

DEFAULT_RULES = [
    {
        "match": {"group": "신용 스프레드"},
        "polarity": "lower_is_better",
        "hot_text": "스프레드가 크게 벌어져 신용 위험을 더 비싸게 반영하는 구간입니다.",
        "cold_text": "스프레드가 매우 좁아 신용시장이 낙관적인 구간입니다.",
    },
    {
        "match": {"name_contains": "공포탐욕"},
        "polarity": "higher_is_better",
        "hot_text": "탐욕이 강한 구간입니다. 단기 과열 여부를 함께 확인할 필요가 있습니다.",
        "cold_text": "공포가 강한 구간입니다. 위험 회피가 가격에 많이 반영된 상태입니다.",
    },
    {
        "match": {"name": "VIX"},
        "polarity": "lower_is_better",
        "hot_text": "변동성 기대가 크게 높아져 시장 불안이 강한 구간입니다.",
        "cold_text": "변동성 기대가 낮아 시장이 비교적 안정적으로 보는 구간입니다.",
    },
    {
        "match": {"group": "수급"},
        "polarity": "context",
    },
    {
        "match": {"chart_style": "flow_bars"},
        "polarity": "context",
    },
    {
        "match": {"group": "금리"},
        "polarity": "context",
    },
    {
        "match": {"group": "에너지 가격"},
        "polarity": "context",
    },
]


def percentile_zone(percentile: float | None) -> str:
    if percentile is None:
        return ""
    for threshold, zone in ZONE_ORDER:
        if percentile >= threshold:
            return zone
    return "cold"


def window_percentile(metric: dict[str, Any]) -> tuple[float | None, str]:
    stats = metric.get("percentiles")
    if not isinstance(stats, dict):
        return None, ""
    window = stats.get("y10") if isinstance(stats.get("y10"), dict) else stats.get("all")
    if not isinstance(window, dict):
        return None, ""
    pct = window.get("pct")
    if not isinstance(pct, (int, float)):
        return None, ""
    label = "10년" if stats.get("y10") else "전체 기간"
    return float(pct), label


def trend_label(metric: dict[str, Any]) -> str:
    history = metric.get("history")
    if not isinstance(history, list) or len(history) < 2:
        return ""
    values = [
        point.get("value")
        for point in history
        if isinstance(point, dict) and isinstance(point.get("value"), (int, float))
    ]
    if len(values) < 2:
        return ""

    direction = 0
    streak = 0
    for previous, current in zip(reversed(values[:-1]), reversed(values[1:])):
        step = 1 if current > previous else -1 if current < previous else 0
        if step == 0:
            break
        if direction == 0:
            direction = step
        if step != direction:
            break
        streak += 1

    change = values[-1] - values[-2]
    unit = str(metric.get("unit") or "")
    sign = "+" if change > 0 else ""
    if streak > 1:
        verb = "연속 상승" if direction > 0 else "연속 하락"
        return f"최근 {streak}개 관측치 {verb}, 직전 대비 {sign}{change:.2f}{unit}"
    if change > 0:
        return f"직전 대비 +{change:.2f}{unit}"
    if change < 0:
        return f"직전 대비 {change:.2f}{unit}"
    return "직전과 같은 수준"


def match_rule(metric: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
    priorities = ("id", "name", "group", "industry", "chart_style", "name_contains")
    for priority in priorities:
        for rule in rules:
            match = rule.get("match") if isinstance(rule, dict) else None
            if not isinstance(match, dict) or priority not in match:
                continue
            expected = str(match.get(priority) or "")
            actual = str(metric.get(priority) or "")
            if priority == "name_contains":
                actual = str(metric.get("name") or "")
                if expected and expected in actual:
                    return rule
            elif expected and actual == expected:
                return rule
    return {}


def configured_rules(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_rules = ((config.get("interpretation") or {}).get("rules") or [])
    rules = [rule for rule in raw_rules if isinstance(rule, dict)]
    return rules + DEFAULT_RULES


def polarity_text(metric: dict[str, Any], rule: dict[str, Any], zone: str) -> str:
    polarity = str(rule.get("polarity") or ((metric.get("interpretation") or {}).get("polarity") or "neutral"))
    if polarity == "lower_is_better":
        if zone in {"hot", "warm"}:
            return str(rule.get("hot_text") or "값이 높은 쪽에 있어 부담이 커진 구간입니다.")
        if zone in {"cool", "cold"}:
            return str(rule.get("cold_text") or "값이 낮은 쪽에 있어 부담이 완화된 구간입니다.")
    if polarity == "higher_is_better":
        if zone in {"hot", "warm"}:
            return str(rule.get("hot_text") or "값이 높은 쪽에 있어 모멘텀이 강한 구간입니다.")
        if zone in {"cool", "cold"}:
            return str(rule.get("cold_text") or "값이 낮은 쪽에 있어 모멘텀이 약한 구간입니다.")
    return ""


def build_interpretation(metric: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    pct, window_label = window_percentile(metric)
    if pct is None:
        return {}
    zone = percentile_zone(pct)
    level_label = f"{window_label} 범위 상위 {pct:.1f}% - {ZONE_LABELS.get(zone, '현재 위치')}"
    trend = trend_label(metric)
    rule = match_rule(metric, configured_rules(config))
    meaning = str(metric.get("meaning") or "").strip()
    status = polarity_text(metric, rule, zone)
    text_parts = [meaning, level_label]
    if trend:
        text_parts.append(trend)
    if status:
        text_parts.append(status)
    return {
        "zone": zone,
        "level_label": level_label,
        "trend_label": trend,
        "text": " ".join(part for part in text_parts if part),
        "caption": "계산 기반 해석",
    }


def apply_interpretations(metrics: list[dict[str, Any]], config: dict[str, Any]) -> None:
    for metric in metrics:
        if not isinstance(metric, dict) or metric.get("status") != "ok":
            continue
        interpretation = build_interpretation(metric, config)
        if interpretation:
            metric["interpretation"] = interpretation
