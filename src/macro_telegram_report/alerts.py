"""텔레그램 알림: 임계값 돌파, 수집 실패, 주간 다이제스트.

상태 파일(data/alerts_state.json)에 마지막 상태를 저장해 같은 알림이
매일 반복 발송되지 않게 합니다(임계값을 벗어났다가 다시 돌파하면 재발송).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

from .history_store import parse_stored_points, safe_history_key
from .storage import load_json, write_json
from .telegram import send_telegram
from .utils import to_float


def load_alert_state(path: Path) -> dict[str, Any]:
    loaded = load_json(path, {})
    return loaded if isinstance(loaded, dict) else {}


def save_alert_state(path: Path, state: dict[str, Any]) -> None:
    write_json(path, state)


def load_signal_log(path: Path) -> dict[str, Any]:
    loaded = load_json(path, {})
    if isinstance(loaded, dict) and isinstance(loaded.get("events"), list):
        loaded.setdefault("version", 1)
        return loaded
    return {"version": 1, "events": []}


def save_signal_log(path: Path, document: dict[str, Any]) -> None:
    document["events"] = sorted(document.get("events", []), key=lambda item: str(item.get("observed_at") or item.get("ts") or ""))
    write_json(path, document)


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


def threshold_label(rule: dict[str, Any]) -> str:
    if rule.get("above") is not None:
        return f"≥ {rule['above']}"
    if rule.get("below") is not None:
        return f"≤ {rule['below']}"
    if rule.get("pct_above") is not None:
        return f"≥ P{rule['pct_above']}"
    if rule.get("pct_below") is not None:
        return f"≤ P{rule['pct_below']}"
    return ""


def market_context(payload: dict[str, Any]) -> dict[str, float]:
    fragments = {
        "KS11": ("코스피", "KOSPI"),
        "GSPC": ("S&P 500", "S&P500", "미국 S&P"),
        "USDKRW": ("원/달러", "USD/KRW", "환율"),
    }
    context: dict[str, float] = {}
    metrics = payload.get("metrics", [])
    for key, names in fragments.items():
        for metric in metrics:
            metric_name = str(metric.get("name") or "")
            if any(name.lower() in metric_name.lower() for name in names):
                value = to_float(metric.get("value"))
                if value is not None:
                    context[key] = value
                    break
    return context


def signal_event(
    *,
    rule: dict[str, Any],
    metric: dict[str, Any],
    direction: str,
    payload: dict[str, Any],
    now: datetime,
    backfilled: bool = False,
    observed_at: str | None = None,
    value: float | None = None,
) -> dict[str, Any]:
    event_value = value if value is not None else to_float(metric.get("value"))
    observed = observed_at or str(metric.get("observed_at") or now.date().isoformat())
    return {
        "ts": now.isoformat(timespec="seconds"),
        "observed_at": observed,
        "rule_key": rule_key(rule),
        "metric_id": str(metric.get("id") or metric.get("history_key") or metric.get("name") or ""),
        "metric_name": str(metric.get("name") or ""),
        "direction": direction,
        "value": event_value,
        "display_value": str(metric.get("display_value") or event_value or ""),
        "threshold_label": threshold_label(rule),
        "message": str(rule.get("message") or ""),
        "context": market_context(payload),
        "telegram_sent": False,
        **({"backfilled": True} if backfilled else {}),
    }


def append_signal_event(document: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    events = document.setdefault("events", [])
    fingerprint = (
        event.get("rule_key"),
        event.get("observed_at"),
        event.get("direction"),
        event.get("backfilled", False),
    )
    for existing in events:
        if (
            existing.get("rule_key"),
            existing.get("observed_at"),
            existing.get("direction"),
            existing.get("backfilled", False),
        ) == fingerprint:
            return existing
    events.append(event)
    return event


def rule_triggered_for_value(rule: dict[str, Any], value: float) -> bool | None:
    above = to_float(rule.get("above"))
    if above is not None:
        return value >= above
    below = to_float(rule.get("below"))
    if below is not None:
        return value <= below
    return None


def initialize_signal_log_backfill(
    config: dict[str, Any],
    payload: dict[str, Any],
    document: dict[str, Any],
    now: datetime,
) -> None:
    if document.get("events"):
        return
    history_dir = Path(str((config.get("history") or {}).get("dir") or "data/history"))
    for rule in (config.get("alerts", {}) or {}).get("rules", []):
        if rule.get("above") is None and rule.get("below") is None:
            continue
        metric = find_metric_by_fragment(payload.get("metrics", []), str(rule.get("metric") or ""))
        if not metric:
            continue
        key = str(metric.get("history_key") or metric.get("id") or "")
        path = history_dir / f"{safe_history_key(key)}.json"
        if not path.exists():
            continue
        loaded = load_json(path, {})
        if not isinstance(loaded, dict):
            continue
        previous: bool | None = None
        for point_date, point_value in parse_stored_points(loaded.get("points")):
            triggered = rule_triggered_for_value(rule, point_value)
            if triggered is None:
                continue
            if previous is not None and triggered == previous:
                continue
            if previous is None and not triggered:
                previous = triggered
                continue
            append_signal_event(
                document,
                signal_event(
                    rule=rule,
                    metric=metric,
                    direction="triggered" if triggered else "cleared",
                    payload=payload,
                    now=now,
                    backfilled=True,
                    observed_at=point_date.isoformat(),
                    value=point_value,
                ),
            )
            previous = triggered


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
    config: dict[str, Any],
    payload: dict[str, Any],
    state: dict[str, Any],
    *,
    signal_log: dict[str, Any] | None = None,
    now: datetime | None = None,
    new_signal_events: list[dict[str, Any]] | None = None,
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
            "metric_id": metric.get("id"),
            "metric_name": metric.get("name"),
        }
        if signal_log is not None and triggered != was_triggered:
            event = append_signal_event(
                signal_log,
                signal_event(
                    rule=rule,
                    metric=metric,
                    direction="triggered" if triggered else "cleared",
                    payload=payload,
                    now=now or datetime.now(),
                ),
            )
            if new_signal_events is not None:
                new_signal_events.append(event)
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
    signal_path = Path(str(alerts_config.get("signal_log_file") or "data/signal_log.json"))
    state = load_alert_state(state_path)
    signal_log = load_signal_log(signal_path)
    current = now or datetime.now()
    initialize_signal_log_backfill(config, payload, signal_log, current)
    new_signal_events: list[dict[str, Any]] = []
    sent: list[str] = []

    lines = threshold_alert_lines(
        config,
        payload,
        state,
        signal_log=signal_log,
        now=current,
        new_signal_events=new_signal_events,
    )
    lines += failure_alert_lines(payload, state)
    if lines:
        message = "📢 산업 지표 대시보드 알림\n\n" + "\n\n".join(lines)
        sent.append(message)

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

    telegram_delivered = False
    for message in sent:
        try:
            send_telegram(message, session)
            telegram_delivered = True
        except Exception:  # noqa: BLE001 - 알림 실패가 빌드를 막으면 안 됩니다.
            pass
    if telegram_delivered:
        for event in new_signal_events:
            event["telegram_sent"] = True

    save_alert_state(state_path, state)
    save_signal_log(signal_path, signal_log)
    return sent
