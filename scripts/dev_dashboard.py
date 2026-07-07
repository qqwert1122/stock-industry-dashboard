from __future__ import annotations

import argparse
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


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


def render_existing_payload() -> bool:
    data_path = SITE / "data" / "dashboard.json"
    if not data_path.exists():
        print("[dev] site/data/dashboard.json not found; run full build first")
        return False

    try:
        add_src_to_path()
        from macro_telegram_report.dashboard import copy_dashboard_assets, render_dashboard_html

        payload = json.loads(data_path.read_text(encoding="utf-8"))
        SITE.mkdir(parents=True, exist_ok=True)
        copy_dashboard_assets(SITE)
        (SITE / "index.html").write_text(render_dashboard_html(payload), encoding="utf-8")
        (SITE / ".nojekyll").write_text("", encoding="utf-8")
        print("[dev] fast render: regenerated site/index.html from existing data")
        return True
    except Exception as exc:  # noqa: BLE001 - keep the dev server alive.
        print(f"[dev] fast render failed: {exc}")
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

    while True:
        time.sleep(0.8)
        next_full_stamp = newest_mtime(full_paths)
        next_fast_stamp = newest_mtime(fast_paths)

        if next_full_stamp != full_stamp:
            full_stamp = next_full_stamp
            if run_full_build(args):
                fast_stamp = newest_mtime(fast_paths)
                server.notify_reload()
            continue

        if next_fast_stamp != fast_stamp:
            fast_stamp = next_fast_stamp
            if render_existing_payload():
                server.notify_reload()


def main() -> int:
    args = parse_args()
    add_src_to_path()

    if args.full_build:
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
