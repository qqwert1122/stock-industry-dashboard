from __future__ import annotations

import argparse
import importlib
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from datetime import date, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SITE = ROOT / "site"
CONFIG = ROOT / "config.yaml"
DASHBOARD_SOURCE = ROOT / "src" / "macro_telegram_report" / "dashboard.py"
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
    )


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
    ) -> None:
        end_serial = end_year * 12 + end_month
        start_serial = end_serial - count + 1
        start_year = (start_serial - 1) // 12
        start_month = (start_serial - 1) % 12 + 1
        history = mock_months(start_year, start_month, count, start, step, wave)
        metrics.append(
            mock_metric(
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
            )
        )

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
    add("자동차", "미국 자동차 판매", "M대", "판매", 14.8, 0.03, 0.22)
    add("전기차", "글로벌 EV 판매", "M대", "판매", 1.0, 0.04, 0.08)
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
    add("로봇", "Teradyne(TER)", "$", "대표주가", 121, -0.55, 3.4, count=30)
    add("우주", "글로벌 발사 건수", "건", "활동성", 12, 0.08, 1.2)
    add("바이오", "Phase 3 임상 시작", "건", "파이프라인", 18, 0.05, 1.1)
    add("배터리", "리튬 가격", "$", "원자재", 13200, -34, 210)

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
    payload["morning_briefing"] = dashboard.rule_based_morning_briefing(payload)
    return payload


def render_mock_payload() -> bool:
    try:
        dashboard = load_dashboard_module()
        payload = build_mock_payload(dashboard)
        SITE.mkdir(parents=True, exist_ok=True)
        write_dashboard_preview(payload, dashboard)
        (SITE / "data").mkdir(parents=True, exist_ok=True)
        (SITE / "data" / "dashboard.mock.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    fast_paths = [DASHBOARD_SOURCE, ASSETS]
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
