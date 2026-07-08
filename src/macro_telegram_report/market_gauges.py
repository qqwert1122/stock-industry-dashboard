"""시장 온도계와 경기침체 시그널 계산.

AI가 아니라 투명한 룰 기반 계산입니다. 각 구성요소의 백분위(최근 10년)와
변환 방식이 payload에 그대로 남아 사용자가 근거를 확인할 수 있습니다.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .utils import to_float

THERMOMETER_COMPONENTS = [
    # (지표 이름 부분일치, 방향: +1이면 백분위 높음=과열, -1이면 백분위 낮음=과열, 표시명)
    ("VIX", -1, "VIX (변동성)"),
    ("하이일드 회사채 OAS", -1, "미국 하이일드 스프레드"),
    ("코스피 PBR", 1, "코스피 PBR"),
    ("Shiller CAPE", 1, "S&P 500 CAPE"),
    ("한국 신용융자 잔고", 1, "한국 신용융자(YoY)"),
    ("margin debt", 1, "미국 신용융자(YoY)"),
]
YOY_HEAT_NAMES = ("신용융자", "margin debt")
FEAR_GREED_METRICS = [
    ("미국 CNN 공포탐욕지수", "미국 CNN"),
    ("코스피 공포탐욕지수", "코스피"),
    ("코스닥 공포탐욕지수", "코스닥"),
]


def find_metric(metrics: list[dict[str, Any]], name_fragment: str) -> dict[str, Any] | None:
    fragment = name_fragment.lower()
    for metric in metrics:
        if metric.get("status") != "ok":
            continue
        if fragment in str(metric.get("name") or "").lower():
            return metric
    return None


def metric_percentile(metric: dict[str, Any], window: str = "y10") -> float | None:
    stats = metric.get("percentiles")
    if not isinstance(stats, dict):
        return None
    window_stats = stats.get(window) or stats.get("all")
    if not isinstance(window_stats, dict):
        return None
    return to_float(window_stats.get("pct"))


def yoy_series_percentile(metric: dict[str, Any]) -> float | None:
    """레벨이 장기 우상향하는 지표(신용융자 등)는 YoY 증가율의 백분위로 열기를 잽니다."""
    history = metric.get("history")
    if not isinstance(history, list) or len(history) < 24:
        return None
    points: list[tuple[date, float]] = []
    for item in history:
        try:
            points.append((date.fromisoformat(str(item.get("date"))), float(item.get("value"))))
        except (TypeError, ValueError):
            continue
    if len(points) < 24:
        return None
    points.sort(key=lambda point: point[0])
    yoy_values: list[float] = []
    by_date = points
    for index, (point_date, value) in enumerate(by_date):
        target = point_date - timedelta(days=365)
        base = None
        for prev_date, prev_value in by_date[:index]:
            if abs((prev_date - target).days) <= 45:
                base = prev_value
        if base and base != 0:
            yoy_values.append((value - base) / base * 100.0)
    if len(yoy_values) < 12:
        return None
    current = yoy_values[-1]
    below = sum(1 for value in yoy_values if value < current)
    equal = sum(1 for value in yoy_values if value == current)
    return round(100.0 * (below + 0.5 * equal) / len(yoy_values), 1)


def thermometer_label(score: float) -> tuple[str, str]:
    if score >= 80:
        return "과열", "여러 지표가 역사적 고점 부근입니다. 신규 매수 속도를 늦추고 분할 접근이 필요한 구간입니다."
    if score >= 60:
        return "과열 주의", "시장 열기가 평균보다 높습니다. 장기투자자라면 무리한 추격 매수를 피할 구간입니다."
    if score >= 45:
        return "중립", "밸류에이션과 심리가 역사적 평균 부근입니다. 계획된 적립식 투자를 유지하기 좋은 구간입니다."
    if score >= 25:
        return "냉각", "시장 심리가 위축되어 있습니다. 장기 관점에서는 우량 자산을 점검할 기회일 수 있습니다."
    return "공포", "역사적으로 공포 구간은 장기투자자에게 유리한 매수 기회였던 경우가 많습니다."


def fear_greed_label(score: float) -> str:
    if score >= 76:
        return "극단적 탐욕"
    if score >= 56:
        return "탐욕"
    if score >= 45:
        return "중립"
    if score >= 25:
        return "공포"
    return "극단적 공포"


def build_thermometer(metrics: list[dict[str, Any]]) -> dict[str, Any] | None:
    components: list[dict[str, Any]] = []
    for fragment, direction, display_name in THERMOMETER_COMPONENTS:
        metric = find_metric(metrics, fragment)
        if metric is None:
            continue
        use_yoy = any(token in fragment for token in YOY_HEAT_NAMES)
        pct = yoy_series_percentile(metric) if use_yoy else metric_percentile(metric)
        if pct is None:
            continue
        heat = pct if direction > 0 else 100.0 - pct
        components.append(
            {
                "name": display_name,
                "metric_id": metric.get("id"),
                "metric_name": metric.get("name"),
                "value_label": metric.get("display_value"),
                "percentile": pct,
                "heat": round(heat, 1),
                "basis": "최근 10년 YoY 증가율 백분위" if use_yoy else "최근 10년 백분위",
            }
        )
    if len(components) < 3:
        return None
    score = round(sum(component["heat"] for component in components) / len(components), 1)
    label, comment = thermometer_label(score)
    return {
        "score": score,
        "label": label,
        "comment": comment,
        "components": components,
    }


def build_fear_greed_gauges(metrics: list[dict[str, Any]]) -> dict[str, Any] | None:
    items: list[dict[str, Any]] = []
    for metric_name, display_name in FEAR_GREED_METRICS:
        metric = find_metric(metrics, metric_name)
        if metric is None:
            continue
        score = to_float(metric.get("value"))
        if score is None:
            continue
        bounded_score = max(0.0, min(100.0, score))
        items.append(
            {
                "name": display_name,
                "metric_id": metric.get("id"),
                "metric_name": metric.get("name"),
                "score": round(bounded_score, 1),
                "label": fear_greed_label(bounded_score),
                "value_label": metric.get("display_value"),
            }
        )
    if not items:
        return None
    return {
        "comment": "0에 가까울수록 공포, 100에 가까울수록 탐욕이 강한 구간입니다.",
        "items": items,
    }


def signal_item(
    name: str,
    value_label: str,
    status: str,
    description: str,
    metric_id: Any = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "value_label": value_label,
        "status": status,  # ok | warn | alert
        "description": description,
        "metric_id": metric_id,
    }


def build_recession_signals(metrics: list[dict[str, Any]]) -> dict[str, Any] | None:
    signals: list[dict[str, Any]] = []

    curve = find_metric(metrics, "10Y-3M")
    if curve is not None:
        value = to_float(curve.get("value"))
        if value is not None:
            if value < 0:
                status, description = "alert", "수익률곡선이 역전 상태입니다. 역사적으로 역전 후 1~2년 내 침체가 잦았습니다."
            elif value < 0.5:
                status, description = "warn", "수익률곡선이 평탄합니다. 역전 여부를 지켜볼 구간입니다."
            else:
                status, description = "ok", "수익률곡선이 정상 기울기입니다."
            signals.append(
                signal_item("미국 10Y-3M 금리차", f"{value:+.2f}%p", status, description, curve.get("id"))
            )

    sahm = find_metric(metrics, "Sahm Rule")
    if sahm is not None:
        value = to_float(sahm.get("value"))
        if value is not None:
            if value >= 0.5:
                status, description = "alert", "Sahm Rule 기준(0.50)을 넘었습니다. 침체가 이미 시작됐을 가능성이 있습니다."
            elif value >= 0.3:
                status, description = "warn", "실업률이 저점 대비 반등 중입니다. 고용 둔화 초기 신호입니다."
            else:
                status, description = "ok", "고용 흐름에 침체 신호가 없습니다."
            signals.append(
                signal_item("Sahm Rule", f"{value:.2f}%p", status, description, sahm.get("id"))
            )

    hy_oas = find_metric(metrics, "하이일드 회사채 OAS")
    if hy_oas is not None:
        value = to_float(hy_oas.get("value"))
        if value is not None:
            if value >= 6.0:
                status, description = "alert", "하이일드 스프레드가 위기 수준으로 벌어졌습니다. 신용시장이 침체를 가격에 반영 중입니다."
            elif value >= 4.5:
                status, description = "warn", "신용 스프레드가 확대되고 있습니다. 기업 부도위험 경계 구간입니다."
            else:
                status, description = "ok", "신용시장이 안정적입니다."
            signals.append(
                signal_item("하이일드 스프레드", f"{value:.2f}%", status, description, hy_oas.get("id"))
            )

    gdpnow = find_metric(metrics, "GDPNow")
    if gdpnow is not None:
        value = to_float(gdpnow.get("value"))
        if value is not None:
            if value < 0:
                status, description = "alert", "GDPNow가 마이너스 성장을 추정하고 있습니다."
            elif value < 1.0:
                status, description = "warn", "미국 성장률 추정치가 1% 아래로 둔화됐습니다."
            else:
                status, description = "ok", "미국 성장률 추정치가 견조합니다."
            signals.append(
                signal_item("GDPNow 성장률", f"{value:.1f}%", status, description, gdpnow.get("id"))
            )

    leading = find_metric(metrics, "경기선행지수")
    if leading is not None:
        value = to_float(leading.get("value"))
        yoy = to_float(leading.get("change_pct"))
        if value is not None:
            if value < 99 and (yoy or 0) < 0:
                status, description = "warn", "한국 선행지수가 기준선 아래에서 하락 중입니다. 국내 경기 둔화 신호입니다."
            elif value < 100:
                status, description = "warn", "한국 선행지수가 기준선(100) 아래입니다."
            else:
                status, description = "ok", "한국 선행지수가 기준선 위에 있습니다."
            signals.append(
                signal_item("한국 경기선행지수", f"{value:.1f}", status, description, leading.get("id"))
            )

    if not signals:
        return None
    alert_count = sum(1 for signal in signals if signal["status"] == "alert")
    warn_count = sum(1 for signal in signals if signal["status"] == "warn")
    if alert_count >= 2:
        summary = "복수의 침체 신호가 켜져 있습니다. 방어적인 자산 배분을 점검할 시점입니다."
    elif alert_count == 1:
        summary = "침체 신호가 하나 켜져 있습니다. 다른 지표의 추세 전환 여부를 함께 확인하세요."
    elif warn_count >= 1:
        summary = "일부 지표가 주의 구간입니다. 아직 침체 신호는 아닙니다."
    else:
        summary = "주요 침체 신호가 모두 정상 범위입니다."
    return {
        "signals": signals,
        "alert_count": alert_count,
        "warn_count": warn_count,
        "summary": summary,
    }


def build_market_gauges(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    gauges: dict[str, Any] = {}
    thermometer = build_thermometer(metrics)
    if thermometer:
        gauges["thermometer"] = thermometer
    recession = build_recession_signals(metrics)
    if recession:
        gauges["recession"] = recession
    fear_greed = build_fear_greed_gauges(metrics)
    if fear_greed:
        gauges["fear_greed"] = fear_greed
    return gauges
