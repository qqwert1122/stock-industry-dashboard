"""텔레그램 알림: 임계값 돌파, 수집 실패, 주간 다이제스트.

상태 파일(data/alerts_state.json)에 마지막 상태를 저장해 같은 알림이
매일 반복 발송되지 않게 합니다(임계값을 벗어났다가 다시 돌파하면 재발송).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

from .telegram import send_telegram
from .utils import to_float


def load_alert_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_alert_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_metric_by_fragment(metrics: list[dict[str, Any]], fragment: str) -> dict[str, Any] | None:
    lowered = fragment.lower()
    for metric in metrics:
        if metric.get("status") != "ok":
            continue
        if lowered in str(metric.get("name") or "").lower():
            return metric
    return None


def rule_key(rule: dict[str, Any]) -> str:
    parts = [str(rule.get("metric") or "")]
    for field in ("above", "below", "pct_above", "pct_below"):
        if rule.get(field) is not None:
            parts.append(f"{field}={rule[field]}")
    return "|".join(parts)


def metric_percentile_10y(metric: dict[str, Any]) -> float | None:
    stats = metric.get("percentiles")
    if not isinstance(stats, dict):
        return None
    window = stats.get("y10") or stats.get("all")
    if not isinstance(window, dict):
        return None
    return to_float(window.get("pct"))


def evaluate_rule(rule: dict[str, Any], metric: dict[str, Any]) -> tuple[bool, str]:
    """룰이 발동 상태인지와 상태 설명 문자열을 반환합니다."""
    value = to_float(metric.get("value"))
    pct = metric_percentile_10y(metric)
    triggered = False
    reasons: list[str] = []

    above = to_float(rule.get("above"))
    if above is not None and value is not None and value >= above:
        triggered = True
        reasons.append(f"값 {metric.get('display_value')} ≥ 기준 {above}")
    below = to_float(rule.get("below"))
    if below is not None and value is not None and value <= below:
        triggered = True
        reasons.append(f"값 {metric.get('display_value')} ≤ 기준 {below}")
    pct_above = to_float(rule.get("pct_above"))
    if pct_above is not None and pct is not None and pct >= pct_above:
        triggered = True
        reasons.append(f"10년 백분위 {pct}% ≥ 기준 {pct_above}%")
    pct_below = to_float(rule.get("pct_below"))
    if pct_below is not None and pct is not None and pct <= pct_below:
        triggered = True
        reasons.append(f"10년 백분위 {pct}% ≤ 기준 {pct_below}%")

    return triggered, "; ".join(reasons)


def threshold_alert_lines(
    config: dict[str, Any], payload: dict[str, Any], state: dict[str, Any]
) -> list[str]:
    alerts_config = config.get("alerts", {}) or {}
    rules = alerts_config.get("rules", [])
    metrics = payload.get("metrics", [])
    lines: list[str] = []
    rule_states = state.setdefault("rules", {})

    for rule in rules:
        fragment = str(rule.get("metric") or "").strip()
        if not fragment:
            continue
        metric = find_metric_by_fragment(metrics, fragment)
        if metric is None:
            continue
        key = rule_key(rule)
        triggered, reason = evaluate_rule(rule, metric)
        was_triggered = bool(rule_states.get(key, {}).get("triggered"))
        rule_states[key] = {
            "triggered": triggered,
            "value": metric.get("value"),
            "observed_at": metric.get("observed_at"),
        }
        if triggered and not was_triggered:
            note = str(rule.get("message") or "").strip()
            line = f"⚠️ {metric.get('name')}: {reason}"
            if note:
                line += f"\n   {note}"
            lines.append(line)
    return lines


def failure_alert_lines(payload: dict[str, Any], state: dict[str, Any]) -> list[str]:
    failures = [
        item
        for item in payload.get("source_status", [])
        if isinstance(item, dict) and item.get("status") == "error"
    ]
    current_names = sorted(str(item.get("name")) for item in failures)
    previous_names = state.get("failed_sources", [])
    state["failed_sources"] = current_names
    new_failures = [name for name in current_names if name not in previous_names]
    if not new_failures:
        return []
    detail = {str(item.get("name")): str(item.get("message") or "") for item in failures}
    return [
        f"🛠 수집 실패: {name} — {detail.get(name, '')[:120]}"
        for name in new_failures
    ]


def weekly_digest_text(payload: dict[str, Any]) -> str:
    metrics = [
        metric
        for metric in payload.get("metrics", [])
        if metric.get("status") == "ok" and metric_percentile_10y(metric) is not None
    ]
    gauges = payload.get("market_gauges", {}) or {}
    lines: list[str] = ["📅 주간 매크로 다이제스트"]

    thermometer = gauges.get("thermometer")
    if thermometer:
        lines.append(
            f"시장 온도계: {thermometer.get('score')} ({thermometer.get('label')})"
        )
    recession = gauges.get("recession")
    if recession:
        lines.append(f"침체 시그널: {recession.get('summary')}")

    highs = sorted(metrics, key=lambda m: metric_percentile_10y(m) or 0, reverse=True)[:5]
    lows = sorted(metrics, key=lambda m: metric_percentile_10y(m) or 100)[:5]
    if highs:
        lines.append("\n🔺 10년 백분위 상단 지표")
        for metric in highs:
            lines.append(
                f"- {metric.get('name')}: {metric.get('display_value')} (P{metric_percentile_10y(metric):.0f})"
            )
    if lows:
        lines.append("\n🔻 10년 백분위 하단 지표")
        for metric in lows:
            lines.append(
                f"- {metric.get('name')}: {metric.get('display_value')} (P{metric_percentile_10y(metric):.0f})"
            )
    lines.append("\n※ 자동 생성된 요약이며 투자 판단의 근거가 아닙니다.")
    return "\n".join(lines)


def process_alerts(
    config: dict[str, Any],
    payload: dict[str, Any],
    session: requests.Session,
    *,
    now: datetime | None = None,
    include_weekly: bool = True,
) -> list[str]:
    """알림 파이프라인. 텔레그램 미설정/실패 시 조용히 건너뜁니다.

    반환값은 발송을 시도한 메시지 목록(테스트용)입니다.
    """
    alerts_config = config.get("alerts", {}) or {}
    if not alerts_config.get("enabled", True):
        return []

    state_path = Path(str(alerts_config.get("state_file") or "data/alerts_state.json"))
    state = load_alert_state(state_path)
    sent: list[str] = []

    lines = threshold_alert_lines(config, payload, state)
    lines += failure_alert_lines(payload, state)
    if lines:
        message = "📢 산업 지표 대시보드 알림\n\n" + "\n\n".join(lines)
        sent.append(message)

    current = now or datetime.now()
    last_digest = str(state.get("last_weekly_digest") or "")
    today_text = current.date().isoformat()
    if (
        include_weekly
        and alerts_config.get("weekly_digest", True)
        and current.weekday() == 0
        and last_digest != today_text
    ):
        sent.append(weekly_digest_text(payload))
        state["last_weekly_digest"] = today_text

    for message in sent:
        try:
            send_telegram(message, session)
        except Exception:  # noqa: BLE001 - 알림 실패가 빌드를 막으면 안 됩니다.
            pass

    save_alert_state(state_path, state)
    return sent
