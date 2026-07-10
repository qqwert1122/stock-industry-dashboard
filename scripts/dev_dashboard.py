from __future__ import annotations

import argparse
import importlib
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SITE = ROOT / "site"
CONFIG = ROOT / "config.yaml"
DASHBOARD_SOURCE = ROOT / "src" / "macro_telegram_report" / "dashboard.py"
DASHBOARD_TEMPLATE = ROOT / "src" / "macro_telegram_report" / "templates" / "dashboard.html"
ASSETS = ROOT / "assets"


LIVE_RELOAD_SNIPPET = """
<script>
(() => {
  if (!("EventSource" in window)) return;
  const events = new EventSource("/__reload");
  events.onmessage = (event) => {
    if (event.data === "reload") window.location.reload();
  };
})();
</script>
"""


class ReloadServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], handler_class: type[SimpleHTTPRequestHandler]):
        super().__init__(server_address, handler_class)
        self.reload_clients: list[queue.Queue[str]] = []

    def notify_reload(self) -> None:
        for client in list(self.reload_clients):
            client.put("reload")


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature.
        return

    def do_GET(self) -> None:
        if self.path == "/__reload":
            self.serve_reload_stream()
            return
        if self.path in ("/", "/index.html") or self.path.startswith("/index.html?"):
            self.serve_index_with_live_reload()
            return
        super().do_GET()

    def serve_index_with_live_reload(self) -> None:
        index_path = SITE / "index.html"
        if not index_path.exists():
            self.send_error(404, "site/index.html not found")
            return
        html = index_path.read_text(encoding="utf-8")
        if "</body>" in html:
            html = html.replace("</body>", LIVE_RELOAD_SNIPPET + "\n</body>")
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def serve_reload_stream(self) -> None:
        client: queue.Queue[str] = queue.Queue()
        self.server.reload_clients.append(client)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                message = client.get()
                self.wfile.write(f"data: {message}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.server.reload_clients.remove(client)  # type: ignore[attr-defined]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local dashboard preview with live reload.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--out", default=str(SITE))
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument(
        "--full-build",
        action="store_true",
        help="Collect fresh data before serving. Omit this while editing only the UI.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use generated dummy data for instant UI design previews.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.2,
        help="Seconds between file-change checks.",
    )
    return parser.parse_args()


def add_src_to_path() -> None:
    src_text = str(SRC)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)


def run_full_build(args: argparse.Namespace) -> bool:
    print("[dev] full build: collecting data and regenerating site")
    command = [
        sys.executable,
        "-m",
        "macro_telegram_report.dashboard_cli",
        "--config",
        args.config,
        "--out",
        args.out,
        "--env-file",
        args.env_file,
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{SRC}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    result = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if result.returncode:
        print(f"[dev] full build failed: exit {result.returncode}")
        return False
    return True


def load_dashboard_module():
    add_src_to_path()
    importlib.invalidate_caches()
    dashboard = importlib.import_module("macro_telegram_report.dashboard")
    return importlib.reload(dashboard)


def load_mock_config() -> dict[str, Any]:
    add_src_to_path()
    from macro_telegram_report.config import load_config

    return load_config(CONFIG)


def write_dashboard_preview(payload: dict[str, Any], dashboard: Any) -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    dashboard.copy_dashboard_assets(SITE)
    (SITE / "index.html").write_text(dashboard.render_dashboard_html(payload), encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")


def render_existing_payload() -> bool:
    data_path = SITE / "data" / "dashboard.json"
    if not data_path.exists():
        print("[dev] site/data/dashboard.json not found; run full build first")
        return False

    try:
        dashboard = load_dashboard_module()
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        payload["future"] = dashboard.build_future_timeline(
            load_mock_config(),
            payload.get("metrics", []),
            today=datetime.now(ZoneInfo("Asia/Seoul")).date(),
        )
        (data_path.parent / "future.json").write_text(
            json.dumps(payload["future"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        write_dashboard_preview(payload, dashboard)
        print("[dev] fast render: regenerated site/index.html from existing data")
        return True
    except Exception as exc:  # noqa: BLE001 - keep the dev server alive.
        print(f"[dev] fast render failed: {exc}")
        return False


def mock_months(start_year: int, start_month: int, count: int, start: float, step: float, wave: float = 0) -> list[tuple[date, float]]:
    points: list[tuple[date, float]] = []
    for index in range(count):
        month_number = start_month + index - 1
        year = start_year + month_number // 12
        month = month_number % 12 + 1
        value = start + step * index + ((index % 5) - 2) * wave
        points.append((date(year, month, 1), round(max(value, 0.01), 2)))
    return points


def mock_days(end: date, count: int, start: float, step: float, wave: float = 0) -> list[tuple[date, float]]:
    points: list[tuple[date, float]] = []
    for index in range(count):
        day = end - timedelta(days=count - index - 1)
        value = start + step * index + ((index % 7) - 3) * wave
        points.append((day, round(value, 2)))
    return points


def mock_metric(
    dashboard: Any,
    *,
    industry: str,
    name: str,
    value: float,
    unit: str,
    group: str,
    history: list[tuple[date, float]],
    frequency: str = "월간",
    depth: str = "",
    meaning: str = "",
    section: str = "",
    market_category: str = "",
    also_market_category: str | list[str] = "",
    chart_style: str = "",
    metric_id: str = "",
    history_key: str = "",
) -> dict[str, Any]:
    previous_value = history[-2][1] if len(history) >= 2 else None
    yoy_value = history[-13][1] if len(history) >= 13 else None
    return dashboard.make_metric(
        industry=industry,
        name=name,
        source="Design mock",
        source_url="",
        frequency=frequency,
        automation="무료로 안정적으로 자동화 가능",
        status="ok",
        value=value,
        unit=unit,
        observed_at=history[-1][0].isoformat(),
        previous_value=previous_value,
        yoy_value=yoy_value,
        history=history,
        group=group,
        depth=depth,
        meaning=meaning,
        section=section,
        market_category=market_category,
        also_market_category=also_market_category,
        chart_style=chart_style,
        metric_id=metric_id,
        history_key=history_key,
    )


def add_mock_percentile(metric: dict[str, Any], percentile: float) -> dict[str, Any]:
    values = sorted(
        float(point["value"])
        for point in metric.get("history") or []
        if isinstance(point, dict) and isinstance(point.get("value"), (int, float))
    )
    if not values:
        values = [float(metric.get("value") or 0)]
    metric["percentiles"] = {
        "y10": {
            "pct": percentile,
            "p20": mock_quantile(values, 0.2),
            "median": mock_quantile(values, 0.5),
            "p80": mock_quantile(values, 0.8),
            "min": values[0],
            "max": values[-1],
            "from": str((metric.get("history") or [{}])[0].get("date") or ""),
            "to": str((metric.get("history") or [{}])[-1].get("date") or ""),
        }
    }
    return metric


def mock_quantile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def previous_mock_metric(metric: dict[str, Any], dashboard: Any, *, updated: bool) -> dict[str, Any]:
    previous = dict(metric)
    history = list(metric.get("history") or [])
    if updated and len(history) >= 2:
        previous_history = history[:-1]
        previous_value = previous_history[-1]["value"]
        previous_observed_at = previous_history[-1]["date"]
        previous["value"] = previous_value
        previous["display_value"] = dashboard.format_value(previous_value, str(metric.get("unit") or ""))
        previous["observed_at"] = previous_observed_at
        previous["observed_label"] = dashboard.compact_date_label(previous_observed_at)
        previous["history"] = previous_history
    return previous


def metric_by_name(payload: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((metric for metric in payload.get("metrics", []) if metric.get("name") == name), None)


def mock_calendar(today: date, payload: dict[str, Any]) -> dict[str, Any]:
    cpi_metric = metric_by_name(payload, "미국 CPI")
    definitions = [
        (-3, "미국 CPI 발표", "us_data", "US", "인플레이션 방향 확인", cpi_metric),
        (0, "FOMC 결정", "fed", "US", "금리와 유동성 기대가 크게 움직일 수 있는 날", None),
        (1, "한국은행 금통위", "bok", "KR", "국내 금리 민감 업종을 볼 때 중요", None),
        (3, "한국 옵션만기", "expiry", "KR", "수급 변동성이 커질 수 있는 날", None),
        (18, "NYSE 휴장", "holiday", "US", "미국 주식시장 휴장", None),
        (27, "미국 PCE 발표", "us_data", "US", "연준이 선호하는 물가 지표", cpi_metric),
    ]
    events: list[dict[str, Any]] = []
    for offset, name, category, country, note, metric in definitions:
        day = today + timedelta(days=offset)
        event = {
            "date": day.isoformat(),
            "name": name,
            "category": category,
            "country": country,
            "note": note,
            "d_day": offset,
            "d_day_label": "D-day" if offset == 0 else f"D{offset:+d}",
        }
        if metric:
            event["metric_id"] = metric.get("id")
        events.append(event)
    return {
        "version": 1,
        "generated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "window": {"from": (today - timedelta(days=7)).isoformat(), "to": (today + timedelta(days=60)).isoformat()},
        "events": events,
        "upcoming": [event for event in events if 0 <= int(event["d_day"]) <= 1],
        "missing_years": [],
    }


def mock_long_history(payload: dict[str, Any]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for metric in payload.get("metrics", []):
        points = [
            [point.get("date"), point.get("value")]
            for point in metric.get("history", [])
            if point.get("date") and isinstance(point.get("value"), (int, float))
        ]
        if not points:
            continue
        entry = {
            "metric_id": metric.get("id", ""),
            "history_key": metric.get("history_key", ""),
            "points": points,
        }
        document[str(metric.get("id"))] = entry
        if metric.get("history_key"):
            document[str(metric.get("history_key"))] = entry
    return document


def mock_market_gauge_history(payload: dict[str, Any]) -> dict[str, Any]:
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    snapshots: list[dict[str, Any]] = []
    for index in range(45):
        day = today - timedelta(days=44 - index)
        thermometer_score = round(36 + index * 0.9 + ((index % 9) - 4) * 1.4, 1)
        cnn_score = round(48 + ((index % 13) - 6) * 2.2, 1)
        kospi_score = round(42 + ((index % 11) - 5) * 2.5 + index * 0.18, 1)
        kosdaq_score = round(58 - ((index % 10) - 5) * 2.0, 1)
        alert_count = 1 if index % 14 in {0, 1, 2, 3} else 0
        snapshots.append(
            {
                "date": day.isoformat(),
                "generated_at": datetime.combine(day, datetime.min.time(), ZoneInfo("Asia/Seoul")).replace(hour=8).isoformat(timespec="seconds"),
                "thermometer": {
                    "score": max(0, min(100, thermometer_score)),
                    "label": "중립" if thermometer_score < 60 else "과열",
                    "comment": "더미 시장 온도계 추이입니다.",
                    "components": [],
                },
                "recession": {
                    "alert_count": alert_count,
                    "warn_count": 1 if alert_count else 0,
                    "summary": "더미 침체 시그널 추이입니다.",
                    "signals": [],
                },
                "fear_greed": {
                    "comment": "더미 공포탐욕 추이입니다.",
                    "items": [
                        {"name": "미국 CNN", "score": max(0, min(100, cnn_score)), "label": "중립", "value_label": f"{cnn_score:.1f} 점"},
                        {"name": "코스피", "score": max(0, min(100, kospi_score)), "label": "중립", "value_label": f"{kospi_score:.1f} 점"},
                        {"name": "코스닥", "score": max(0, min(100, kosdaq_score)), "label": "중립", "value_label": f"{kosdaq_score:.1f} 점"},
                    ],
                },
            }
        )
    return {
        "version": 1,
        "updated_at": snapshots[-1]["generated_at"],
        "count": len(snapshots),
        "first_date": snapshots[0]["date"],
        "last_date": snapshots[-1]["date"],
        "snapshots": snapshots,
    }


def mock_signal_log(payload: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    vix = metric_by_name(payload, "VIX") or {}
    sahm = metric_by_name(payload, "Sahm Rule 침체 지표") or {}
    events = [
        {
            "ts": (now - timedelta(days=14)).isoformat(timespec="seconds"),
            "observed_at": (now.date() - timedelta(days=14)).isoformat(),
            "rule_key": "VIX|above|40",
            "metric_id": str(vix.get("id") or ""),
            "metric_name": "VIX",
            "direction": "triggered",
            "value": 42.6,
            "display_value": "42.6",
            "threshold_label": "≥ 40",
            "message": "공포 구간 더미 시그널입니다.",
            "context": {"KS11": 3120.4, "GSPC": 5488.2, "USDKRW": 1382.5},
            "telegram_sent": False,
            "backfilled": True,
        },
        {
            "ts": (now - timedelta(days=7)).isoformat(timespec="seconds"),
            "observed_at": (now.date() - timedelta(days=7)).isoformat(),
            "rule_key": "VIX|above|40",
            "metric_id": str(vix.get("id") or ""),
            "metric_name": "VIX",
            "direction": "cleared",
            "value": 29.2,
            "display_value": "29.2",
            "threshold_label": "≥ 40",
            "message": "공포 구간 더미 시그널이 해제됐습니다.",
            "context": {"KS11": 3188.6, "GSPC": 5561.8, "USDKRW": 1369.2},
            "telegram_sent": False,
        },
        {
            "ts": (now - timedelta(days=1)).isoformat(timespec="seconds"),
            "observed_at": (now.date() - timedelta(days=1)).isoformat(),
            "rule_key": "Sahm Rule|above|0.5",
            "metric_id": str(sahm.get("id") or ""),
            "metric_name": "Sahm Rule 침체 지표",
            "direction": "triggered",
            "value": 0.77,
            "display_value": "0.77%p",
            "threshold_label": "≥ 0.5",
            "message": "침체 가능성 더미 시그널입니다.",
            "context": {"KS11": 3210.2, "GSPC": 5608.3, "USDKRW": 1374.4},
            "telegram_sent": False,
        },
    ]
    return {"version": 1, "updated_at": now.isoformat(timespec="seconds"), "events": events}


def write_mock_briefings(dashboard: Any, data_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    briefings_dir = data_path / "briefings"
    if briefings_dir.exists():
        shutil.rmtree(briefings_dir)
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    cards: list[dict[str, Any]] = []
    base = payload.get("morning_briefing") or dashboard.rule_based_morning_briefing(payload)
    for card_type, hour, headline in [
        ("morning", 8, "아침 더미 브리핑"),
        ("intraday", 12, "장중 더미 브리핑"),
        ("close", 15, "한국장 마감 더미 브리핑"),
        ("us_close", 6, "미국장 마감 더미 브리핑"),
    ]:
        generated_at = now.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
        card = dict(base)
        card.pop("id", None)
        card.pop("card_type", None)
        card.pop("card_type_label", None)
        card["headline"] = headline
        card["summary"] = f"{headline}입니다. UI 점검용으로 급변, 개선, 주의 흐름을 모두 포함했습니다."
        cards.append(
            dashboard.build_briefing_card(
                card,
                card_type=card_type,
                generated_at=generated_at,
                generated_label=generated_at.replace("T", " ")[:16] + " KST",
            )
        )
    index: dict[str, Any] = {"version": 1, "cards": []}
    for card in cards:
        index = dashboard.write_briefing_outputs(data_path, card)
    return index


def build_mock_payload(dashboard: Any) -> dict[str, Any]:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    metrics: list[dict[str, Any]] = []
    end_year = 2026
    end_month = 6

    def add(
        industry: str,
        name: str,
        unit: str,
        group: str,
        start: float,
        step: float,
        wave: float = 0,
        *,
        frequency: str = "월간",
        depth: str = "",
        meaning: str = "",
        count: int = 54,
        section: str = "",
        market_category: str = "",
        also_market_category: str | list[str] = "",
        chart_style: str = "",
        metric_id: str = "",
        history_key: str = "",
    ) -> dict[str, Any]:
        end_serial = end_year * 12 + end_month
        start_serial = end_serial - count + 1
        start_year = (start_serial - 1) // 12
        start_month = (start_serial - 1) % 12 + 1
        history = mock_months(start_year, start_month, count, start, step, wave)
        metric = mock_metric(
            dashboard,
            industry=industry,
            name=name,
            value=history[-1][1],
            unit=unit,
            group=group,
            history=history,
            frequency=frequency,
            depth=depth,
            meaning=meaning,
            section=section,
            market_category=market_category,
            also_market_category=also_market_category,
            chart_style=chart_style,
            metric_id=metric_id,
            history_key=history_key,
        )
        metrics.append(metric)
        return metric

    def add_market(
        name: str,
        category: str,
        group: str,
        unit: str,
        start: float,
        step: float,
        wave: float = 0,
        *,
        frequency: str = "일간",
        count: int = 90,
        chart_style: str = "",
        metric_id: str = "",
        history_key: str = "",
        meaning: str = "",
    ) -> dict[str, Any]:
        history = mock_days(now.date(), count, start, step, wave)
        metric = mock_metric(
            dashboard,
            industry="매크로",
            name=name,
            value=history[-1][1],
            unit=unit,
            group=group,
            history=history,
            frequency=frequency,
            meaning=meaning,
            section="market",
            market_category=category,
            chart_style=chart_style,
            metric_id=metric_id,
            history_key=history_key,
        )
        metrics.append(metric)
        return metric

    def flow_meaning(market_label: str, investor: str, measure_label: str) -> str:
        return dashboard.flow_metric_meaning(market_label, investor, measure_label)

    add("반도체", "Worldwide", "$B", "판매액(WSTS)", 38, 0.42, 1.1, depth="전체 업황")
    add("반도체", "Asia Pacific", "$B", "판매액(WSTS)", 21, 0.28, 0.8, depth="전체 업황")
    add("반도체", "Americas", "$B", "판매액(WSTS)", 8, 0.11, 0.3, depth="전체 업황")
    add("반도체", "3MMA - Worldwide", "$B", "판매액(WSTS)", 37, 0.39, 0.65, depth="전체 업황")
    add("반도체", "삼성전자(005930.KS)", "원", "대표주가", 62000, 340, 800, depth="메모리 반도체", count=30)
    add("반도체", "SK하이닉스(000660.KS)", "원", "대표주가", 126000, 1700, 3000, depth="메모리 반도체", count=30)
    add("반도체", "Micron(MU)", "$", "대표주가", 82, 1.05, 2.4, depth="메모리 반도체", count=30)
    add("반도체", "NVIDIA(NVDA)", "$", "대표주가", 91, 2.2, 3.6, depth="AI/GPU", count=30)
    add("반도체", "AMD(AMD)", "$", "대표주가", 108, 1.1, 2.8, depth="AI/GPU", count=30)
    add("반도체", "Intel(INTC)", "$", "대표주가", 33, -0.08, 0.7, depth="CPU/프로세서", count=30)
    add("반도체", "TSMC 월매출", "NT$B", "파운드리", 240, 3.2, 7.5, depth="파운드리")
    add("반도체", "ASML(ASML)", "$", "대표주가", 690, 5.5, 11, depth="장비", count=30)
    add("반도체", "Applied Materials(AMAT)", "$", "대표주가", 145, 0.9, 3, depth="장비", count=30)

    add("데이터인프라", "Microsoft", "$B", "CAPEX", 14, 0.38, 0.4, meaning="AI 데이터센터와 클라우드 서버 투자가 얼마나 강한지 보여줍니다.")
    add("데이터인프라", "Amazon", "$B", "CAPEX", 16, 0.42, 0.5, meaning="AWS와 물류·서버 투자의 강도를 함께 볼 수 있는 지표입니다.")
    add("데이터인프라", "Alphabet", "$B", "CAPEX", 12, 0.31, 0.4, meaning="구글 클라우드와 AI 인프라 투자 흐름을 확인합니다.")
    add("데이터인프라", "Meta", "$B", "CAPEX", 8, 0.34, 0.45, meaning="AI 추천·광고 시스템과 데이터센터 투자 강도를 보여줍니다.")
    add("데이터인프라", "Alphabet(GOOGL)", "$", "대표주가", 134, 0.6, 2.1, count=30)
    add("데이터인프라", "Meta(META)", "$", "대표주가", 520, 1.4, 5.8, count=30)
    add("자동차", "미국 자동차 판매", "M대", "판매", 14.8, 0.03, 0.22)
    add("전기차", "글로벌 EV 판매", "M대", "판매", 1.0, 0.04, 0.08)
    add("전기차", "Tesla(TSLA)", "$", "대표주가", 238, -0.4, 5.6, count=30)
    add("조선", "BDI", "", "운임", 1280, 14, 120)
    add("철강/소재", "철광석", "$", "원자재", 104, -0.15, 2.8)
    add("철강/소재", "구리", "$", "원자재", 8200, 22, 85)
    add("철강/소재", "알루미늄", "$", "원자재", 2250, 5, 28)
    add("화학/정유", "WTI 유가", "$", "에너지", 72, 0.05, 1.6)
    add("은행/금융", "미국 기준금리", "%", "금리", 4.75, -0.02, 0.04)
    add("은행/금융", "장단기 금리차", "%", "금리", -0.55, 0.02, 0.05)
    add("건설/부동산", "미국 주택착공", "K건", "주택", 1320, 1.5, 35)
    add("방산", "미국 방산 제조 계약", "$B", "수주", 21, 0.22, 0.7)
    add("스테이블코인", "USDT/USDC 총 발행량", "$B", "유동성", 165, 0.9, 1.5)
    add("전력", "미국 전력수요", "TWh", "전력", 370, 0.6, 4.2)
    add("전력", "GE Vernova(GEV)", "$", "대표주가", 180, 1.8, 4.6, count=30)
    add("로봇", "Teradyne(TER)", "$", "대표주가", 121, -0.55, 3.4, count=30)
    add("로봇", "Uber(UBER)", "$", "대표주가", 84, 0.3, 2.0, count=30)
    add("로봇", "Mobileye(MBLY)", "$", "대표주가", 18, -0.08, 0.9, count=30)
    add("로봇", "Qualcomm(QCOM)", "$", "대표주가", 164, 0.2, 2.8, count=30)
    add("우주", "글로벌 발사 건수", "건", "활동성", 12, 0.08, 1.2)
    add("우주", "Rocket Lab(RKLB)", "$", "대표주가", 28, 0.15, 1.3, count=30)
    add("바이오", "Phase 3 임상 시작", "건", "파이프라인", 18, 0.05, 1.1)
    add("바이오", "Eli Lilly(LLY)", "$", "대표주가", 960, 2.8, 9.4, count=30)
    add("배터리", "리튬 가격", "$", "원자재", 13200, -34, 210)

    add_market("코스피", "종합", "시장지수", "", 2920, 4.2, 22, count=90)
    add_market("코스닥", "종합", "시장지수", "", 780, 1.1, 12, count=90)
    add_market("S&P 500", "종합", "시장지수", "", 5200, 6.4, 28, count=90)
    add_market("나스닥", "종합", "시장지수", "", 16800, 22, 120, count=90)
    add_market("다우", "종합", "시장지수", "", 39200, 16, 150, count=90)
    add_market("Sahm Rule 침체 지표", "종합", "경기침체", "%p", 0.42, 0.006, 0.03, frequency="월간", count=54)
    add_market("GDPNow 성장률", "종합", "경기침체", "%", 1.6, -0.02, 0.1, frequency="주간", count=36)
    add_market("미국 CPI", "종합", "물가", "%", 3.2, -0.01, 0.04, frequency="월간", count=54)
    add_market(
        "코스피 외국인 순매수",
        "수급",
        "외국인",
        "억원",
        -2100,
        65,
        520,
        chart_style="flow_bars",
        metric_id="mock-flow-kospi-foreign-net",
        meaning=flow_meaning("코스피", "외국인", "순매수"),
    )
    add_market(
        "코스피 외국인 매수",
        "수급",
        "외국인",
        "억원",
        42000,
        38,
        950,
        metric_id="mock-flow-kospi-foreign-buy",
        meaning=flow_meaning("코스피", "외국인", "매수"),
    )
    add_market(
        "코스피 외국인 매도",
        "수급",
        "외국인",
        "억원",
        43800,
        -12,
        900,
        metric_id="mock-flow-kospi-foreign-sell",
        meaning=flow_meaning("코스피", "외국인", "매도"),
    )
    add_market(
        "코스닥 개인 순매수",
        "수급",
        "개인",
        "억원",
        1600,
        -22,
        410,
        chart_style="flow_bars",
        metric_id="mock-flow-kosdaq-retail-net",
        meaning=flow_meaning("코스닥", "개인", "순매수"),
    )
    add_market("고객예탁금", "신용·예탁금", "예탁금", "조원", 54, 0.04, 0.8)
    add_market("신용융자 잔고", "신용·예탁금", "신용", "조원", 18.5, 0.02, 0.32)
    add_market("미국 10년 국채금리", "금리·채권", "금리", "%", 4.1, -0.002, 0.06)
    add_market("한국 기준금리", "금리·채권", "금리", "%", 2.75, 0, 0.02)
    add_market("미국 10Y-3M 금리차", "금리·채권", "경기침체", "%p", -1.4, 0.01, 0.03)
    add_market("미국 하이일드 회사채 OAS", "금리·채권", "신용", "%", 4.3, 0.008, 0.06)
    add_market(
        "미국 순유동성",
        "유동성",
        "미국 유동성",
        "$B",
        5400,
        5.2,
        24,
        metric_id="us-net-liquidity",
        history_key="us-net-liquidity",
        meaning=dashboard.US_NET_LIQUIDITY_MEANING,
    )
    add_market(
        "미국 연준 총자산",
        "유동성",
        "미국 유동성",
        "$B",
        6650,
        -1.2,
        10,
        metric_id="us-liquidity-walcl",
        history_key="fred-WALCL",
        meaning="연준 대차대조표 규모로 양적완화/긴축 방향을 보여줍니다. 글로벌 유동성의 큰 물줄기를 확인하는 지표입니다.",
    )
    add_market(
        "미국 TGA",
        "유동성",
        "미국 유동성",
        "$B",
        720,
        1.4,
        18,
        metric_id="us-tga",
        history_key="fiscaldata-tga",
        meaning=dashboard.US_TGA_MEANING,
    )
    add_market(
        "미국 역레포",
        "유동성",
        "미국 유동성",
        "$B",
        210,
        -2.1,
        14,
        metric_id="us-rrp",
        history_key="fred-RRPONTSYD",
        meaning=dashboard.US_RRP_MEANING,
    )
    liquidity_mock_values = {
        "한국은행 총자산": ("조원", 650, 1.8, 4.5),
        "한국 본원통화": ("조원", 305, -0.9, 2.8),
        "한국 M2": ("조원", 4160, 12.5, 22),
        "한국 Lf": ("조원", 5750, 9.4, 18),
        "한국 L": ("조원", 7350, 14.2, 26),
        "일본 BOJ 총자산": ("¥T", 760, -1.5, 4.8),
        "일본 본원통화": ("¥T", 670, 2.4, 6.2),
        "일본 M2": ("¥T", 1260, 4.5, 8.2),
        "일본 BOJ 당좌예금": ("¥T", 555, 1.2, 5.4),
        "유럽 초과유동성": ("€B", 2440, -12.0, 35),
        "유럽 유로시스템 총자산": ("€B", 9800, -35.0, 70),
        "유럽 M3": ("€B", 16900, 42.0, 110),
        "유럽 본원통화": ("€B", 4450, -18.0, 42),
    }
    for item in dashboard.KOREA_LIQUIDITY_ITEMS + dashboard.JAPAN_LIQUIDITY_ITEMS + dashboard.EUROPE_LIQUIDITY_ITEMS:
        unit, value, step, wave = liquidity_mock_values[str(item["name"])]
        add_market(
            str(item["name"]),
            "유동성",
            str(item["group"]),
            unit,
            value,
            step,
            wave,
            metric_id=str(item["metric_id"]),
            history_key=str(item["history_key"]),
            meaning=str(item["meaning"]),
        )
    add_market("원/달러 환율", "원자재·크립토", "환율", "원", 1360, 0.8, 12)
    add_market("비트코인", "원자재·크립토", "크립토", "$", 96000, 110, 2100)
    add_market("김치프리미엄", "원자재·크립토", "크립토", "%", 3.2, 0.04, 0.25)
    add_market("WTI 유가", "원자재·크립토", "원자재", "$", 72, 0.05, 1.6)
    add_market("VIX", "심리·변동성", "시장 심리", "", 34, 0.02, 0.35)
    add_market("VKOSPI", "심리·변동성", "변동성", "", 18, 0.01, 0.7)
    add_market("미국 CNN 공포탐욕지수", "심리·변동성", "공포탐욕", "점", 58, 0.05, 2.2)
    add_market("코스피 공포탐욕지수", "심리·변동성", "공포탐욕", "점", 42, 0.2, 2.6)
    add_market("코스닥 공포탐욕지수", "심리·변동성", "공포탐욕", "점", 64, -0.08, 2.9)
    add_market("한국 소비자심리지수(CCSI)", "종합", "심리", "", 98.5, -0.01, 0.2)
    add_market("한국 전산업 업황실적 BSI", "종합", "심리", "", 99, 0.02, 0.2)
    add_market("한국 경기선행지수 순환변동치", "종합", "경기", "", 99.2, 0.005, 0.08)
    add_market("코스피 PBR", "밸류에이션", "밸류에이션", "배", 0.78, 0.001, 0.005)
    add_market("S&P 500 Shiller CAPE", "밸류에이션", "밸류에이션", "배", 31, 0.04, 0.35, frequency="월간")

    mock_percentiles = {
        "VIX": 72.0,
        "미국 하이일드 회사채 OAS": 68.0,
        "코스피 PBR": 36.0,
        "S&P 500 Shiller CAPE": 84.0,
    }
    for metric in metrics:
        percentile = mock_percentiles.get(str(metric.get("name") or ""))
        if percentile is None:
            values = [
                float(point["value"])
                for point in metric.get("history") or []
                if isinstance(point, dict) and isinstance(point.get("value"), (int, float))
            ]
            current = float(metric.get("value") or 0)
            if values:
                lower_or_equal = sum(1 for value in values if value <= current)
                percentile = max(1.0, min(99.0, lower_or_equal / len(values) * 100))
            else:
                percentile = 50.0
        add_mock_percentile(metric, percentile)

    dashboard.apply_interpretations(metrics, load_mock_config())

    for index, metric in enumerate(metrics):
        group = str(metric.get("group") or "")
        if group == "대표주가" or group == "시장지수":
            metric["source"] = "Yahoo Finance chart API"
        elif group in {"수급", "프로그램", "공매도"}:
            metric["source"] = "KRX 정보데이터시스템"
        elif str(metric.get("frequency") or "") == "월간":
            metric["source"] = "FRED API"
        else:
            metric["source"] = "Design mock"
        metric["fetched_at"] = (now - timedelta(minutes=index % 17)).isoformat(timespec="seconds")
        metric["fetch_status"] = "success" if index % 6 == 0 else "no_new_data"
        metric["fetch_status_label"] = dashboard.fetch_status_label(metric["fetch_status"])

    dashboard.annotate_metric_freshness(metrics, now.date())

    industries = [industry for industry in dashboard.DEFAULT_INDUSTRIES if any(metric["industry"] == industry for metric in metrics)]
    payload = {
        "title": "산업별 지표 대시보드",
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_label": now.strftime("%Y-%m-%d %H:%M %Z"),
        "timezone": "Asia/Seoul",
        "industries": industries,
        "industry_labels_en": {industry: dashboard.english_industry(industry) for industry in industries},
        "industry_icons": dashboard.INDUSTRY_ICONS,
        "source_status": [{"name": "Design mock", "status": "ok", "message": "더미 데이터"}],
        "metrics": metrics,
    }
    payload["freshness_summary"] = dashboard.build_freshness_summary(
        metrics, str(payload["generated_at"]), now.date()
    )

    updated_ids = {metric["id"] for metric in metrics if metric["name"] in {"Worldwide", "NVIDIA(NVDA)", "Microsoft", "철광석", "Teradyne(TER)"}}
    new_ids = {metric["id"] for metric in metrics if metric["name"] in {"Micron(MU)", "Phase 3 임상 시작"}}
    previous = {
        "metrics": [
            previous_mock_metric(metric, dashboard, updated=metric["id"] in updated_ids)
            for metric in metrics
            if metric["id"] not in new_ids
        ]
    }
    dashboard.annotate_dashboard_updates(payload, previous)
    payload["market_gauges"] = dashboard.build_market_gauges(metrics)
    payload["morning_briefing"] = dashboard.rule_based_morning_briefing(payload)
    payload["future"] = dashboard.build_future_timeline(load_mock_config(), metrics, today=now.date())
    return payload


def render_mock_payload() -> bool:
    try:
        dashboard = load_dashboard_module()
        payload = build_mock_payload(dashboard)
        data_path = SITE / "data"
        data_path.mkdir(parents=True, exist_ok=True)
        generated_at = str(payload.get("generated_at") or datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"))
        payload["calendar"] = mock_calendar(datetime.now(ZoneInfo("Asia/Seoul")).date(), payload)
        payload["morning_briefing"] = dashboard.build_briefing_card(
            payload["morning_briefing"],
            card_type="morning",
            generated_at=generated_at,
            generated_label=str(payload.get("generated_label") or ""),
        )
        payload["briefing_index"] = write_mock_briefings(dashboard, data_path, payload)
        write_dashboard_preview(payload, dashboard)
        long_history = mock_long_history(payload)
        market_gauges_history = mock_market_gauge_history(payload)
        signal_log = mock_signal_log(payload)

        for filename in ("dashboard.mock.json", "dashboard.json"):
            (data_path / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (data_path / "calendar.json").write_text(json.dumps(payload["calendar"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (data_path / "future.json").write_text(json.dumps(payload["future"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (data_path / "long_history.json").write_text(json.dumps(long_history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (data_path / "market_gauges_history.json").write_text(
            json.dumps(market_gauges_history, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (data_path / "signal_log.json").write_text(json.dumps(signal_log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[dev] mock render: regenerated site/index.html from dummy data")
        return True
    except Exception as exc:  # noqa: BLE001 - keep the dev server alive.
        print(f"[dev] mock render failed: {exc}")
        return False


def newest_mtime(paths: list[Path]) -> float:
    newest = 0.0
    for path in paths:
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    newest = max(newest, child.stat().st_mtime)
    return newest


def find_available_port(host: str, start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No available port found from {start} to {start + 49}")


def start_server(host: str, port: int) -> ReloadServer:
    actual_port = find_available_port(host, port)
    server = ReloadServer((host, actual_port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[dev] open http://{host}:{actual_port}/")
    return server


def watch_loop(args: argparse.Namespace, server: ReloadServer) -> None:
    fast_paths = [DASHBOARD_SOURCE, DASHBOARD_TEMPLATE, ASSETS]
    full_paths = [Path(args.config)]
    fast_stamp = newest_mtime(fast_paths)
    full_stamp = newest_mtime(full_paths)
    render_preview = render_mock_payload if args.mock else render_existing_payload

    while True:
        time.sleep(max(args.poll_interval, 0.05))
        next_full_stamp = newest_mtime(full_paths)
        next_fast_stamp = newest_mtime(fast_paths)

        if next_full_stamp != full_stamp and not args.mock:
            full_stamp = next_full_stamp
            if run_full_build(args):
                fast_stamp = newest_mtime(fast_paths)
                server.notify_reload()
            continue

        if next_fast_stamp != fast_stamp:
            fast_stamp = next_fast_stamp
            if render_preview():
                server.notify_reload()


def main() -> int:
    args = parse_args()
    add_src_to_path()

    if args.mock:
        render_mock_payload()
    elif args.full_build:
        run_full_build(args)
    elif not (SITE / "data" / "dashboard.json").exists():
        print("[dev] existing dashboard data not found; running one full build")
        run_full_build(args)
    else:
        render_existing_payload()

    server = start_server(args.host, args.port)
    try:
        watch_loop(args, server)
    except KeyboardInterrupt:
        print("\n[dev] stopped")
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
