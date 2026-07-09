"""Rule-based metric interpretation helpers.

The dashboard already has definitions, history, and percentile stats. This
module turns those into short calculation-based explanations without any LLM
call, so the detail panel can show what the latest value means.
"""

from __future__ import annotations

import re
from typing import Any


ZONE_LABELS = {
    "hot": "역사적 고점권",
    "warm": "평균보다 높은 구간",
    "neutral": "중간 구간",
    "cool": "평균보다 낮은 구간",
    "cold": "역사적 저점권",
    "bad": "위험 신호",
    "watch": "경계 구간",
    "good": "우호적 구간",
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


def to_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value or "").replace(",", "").strip()
        if not text:
            return None
        return float(text)
    except ValueError:
        return None


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


def display_current_value(metric: dict[str, Any]) -> str:
    return str(metric.get("display_value") or metric.get("value") or "").strip()


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


def history_values(metric: dict[str, Any]) -> list[float]:
    history = metric.get("history")
    if not isinstance(history, list):
        return []
    return [
        float(point.get("value"))
        for point in history
        if isinstance(point, dict) and isinstance(point.get("value"), (int, float))
    ]


def flow_streak(values: list[float]) -> tuple[int, int]:
    if not values:
        return 0, 0
    latest = values[-1]
    direction = 1 if latest > 0 else -1 if latest < 0 else 0
    if direction == 0:
        return 0, 0
    streak = 0
    for value in reversed(values):
        step = 1 if value > 0 else -1 if value < 0 else 0
        if step != direction:
            break
        streak += 1
    return direction, streak


def flow_investor_name(name: str) -> str:
    match = re.match(
        r"^(?:코스피|코스닥|KOSPI|KOSDAQ|K200 선물|K200 Futures)\s+(.+?)\s+"
        r"(?:20일 누적 순매수|순매수|매수|매도|20d Net Buying|Net Buying|Buying|Selling)$",
        name,
    )
    return match.group(1) if match else "해당 주체"


def build_flow_interpretation(metric: dict[str, Any]) -> dict[str, Any]:
    name = str(metric.get("name") or "")
    values = history_values(metric)
    direction, streak = flow_streak(values)
    current = to_float(metric.get("value"))
    if direction == 0 or current is None:
        return {}
    investor = flow_investor_name(name)
    action = "순매수" if direction > 0 else "순매도"
    support_text = "수급이 지수를 받치는 구간" if direction > 0 else "수급이 지수에 부담을 주는 구간"
    zone = "good" if direction > 0 else "bad"
    streak_unit = "거래일" if str(metric.get("frequency") or "") == "일간" else "개 관측치"
    headline = f"{investor} {streak}{streak_unit} 연속 {action}, 현재 {display_current_value(metric)} - {support_text}입니다."
    level = "20일 누적 수급" if "20일 누적" in name or str(metric.get("history_key") or "").endswith("-net-20d") else "일간 순매수/순매도"
    trend = trend_label(metric)
    detail = trend or "순매수는 플러스, 순매도는 마이너스로 봅니다."
    return {
        "zone": zone,
        "level_label": level,
        "headline": headline,
        "detail_text": detail,
        "trend_label": trend,
        "text": " ".join(part for part in (headline, detail) if part),
        "caption": "계산 기반 해석",
        "source": "flow",
    }


def match_rule(metric: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
    priorities = ("id", "history_key", "name", "group", "industry", "chart_style", "name_contains")
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


def threshold_matches(value: float, threshold: dict[str, Any]) -> bool:
    if threshold.get("default") is True:
        return True
    if "at_or_above" in threshold:
        target = to_float(threshold.get("at_or_above"))
        return target is not None and value >= target
    if "above" in threshold:
        target = to_float(threshold.get("above"))
        return target is not None and value >= target
    if "above_strict" in threshold:
        target = to_float(threshold.get("above_strict"))
        return target is not None and value > target
    if "at_or_below" in threshold:
        target = to_float(threshold.get("at_or_below"))
        return target is not None and value <= target
    if "below" in threshold:
        target = to_float(threshold.get("below"))
        return target is not None and value < target
    if "below_strict" in threshold:
        target = to_float(threshold.get("below_strict"))
        return target is not None and value < target
    return False


def threshold_interpretation(
    metric: dict[str, Any],
    rule: dict[str, Any],
    pct: float | None,
    window_label: str,
) -> dict[str, Any]:
    thresholds = rule.get("thresholds")
    if not isinstance(thresholds, list):
        return {}
    value = to_float(metric.get("value"))
    if value is None:
        return {}
    selected = next(
        (
            threshold
            for threshold in thresholds
            if isinstance(threshold, dict) and threshold_matches(value, threshold)
        ),
        None,
    )
    if not isinstance(selected, dict):
        return {}
    headline = str(selected.get("text") or "").strip()
    if not headline:
        return {}
    zone = str(selected.get("zone") or "neutral")
    level_label = str(selected.get("label") or ZONE_LABELS.get(zone) or "기준선 판정")
    trend = trend_label(metric)
    details = []
    if pct is not None:
        details.append(percentile_level_label(metric, rule, pct, window_label))
    if trend:
        details.append(trend)
    detail_text = " ".join(details)
    return {
        "zone": zone,
        "level_label": level_label,
        "headline": headline,
        "detail_text": detail_text,
        "trend_label": trend,
        "text": " ".join(part for part in (headline, detail_text) if part),
        "caption": "계산 기반 해석",
        "source": "threshold",
    }


def percentile_level_label(metric: dict[str, Any], rule: dict[str, Any], pct: float, window_label: str) -> str:
    zone = percentile_zone(pct)
    zone_labels = rule.get("percentile_zone_labels") if isinstance(rule.get("percentile_zone_labels"), dict) else {}
    zone_label = str(zone_labels.get(zone) or ZONE_LABELS.get(zone) or "현재 위치")
    basis = str(rule.get("percentile_basis") or window_label or "전체 기간")
    if basis == "1871년 이후":
        return f"1871년 이후 상위 {pct:.1f}% - {zone_label}"
    return f"{basis} 범위 상위 {pct:.1f}% - {zone_label}"


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
    rule = match_rule(metric, configured_rules(config))
    if str(metric.get("chart_style") or "") == "flow_bars" or str(rule.get("polarity") or "") == "flow":
        flow = build_flow_interpretation(metric)
        if flow:
            return flow

    pct, window_label = window_percentile(metric)
    threshold = threshold_interpretation(metric, rule, pct, window_label)
    if threshold:
        return threshold

    if pct is None:
        return {}
    zone = percentile_zone(pct)
    level_label = percentile_level_label(metric, rule, pct, window_label)
    trend = trend_label(metric)
    meaning = str(metric.get("meaning") or "").strip()
    status = polarity_text(metric, rule, zone)
    detail_parts = [level_label]
    if trend:
        detail_parts.append(trend)
    if rule.get("percentile_basis") and status:
        detail_parts.append(status)
    detail_text = " ".join(detail_parts)
    headline = level_label if rule.get("percentile_basis") else status or meaning or level_label
    text_parts = [headline, detail_text]
    return {
        "zone": zone,
        "level_label": level_label,
        "headline": headline,
        "detail_text": detail_text,
        "trend_label": trend,
        "text": " ".join(part for part in text_parts if part),
        "caption": "계산 기반 해석",
        "source": "percentile",
    }


def apply_interpretations(metrics: list[dict[str, Any]], config: dict[str, Any]) -> None:
    for metric in metrics:
        if not isinstance(metric, dict) or metric.get("status") != "ok":
            continue
        interpretation = build_interpretation(metric, config)
        if interpretation:
            metric["interpretation"] = interpretation
