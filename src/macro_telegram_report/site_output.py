"""Static dashboard template composition and site output helpers."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DASHBOARD_STYLE_PARTS = (
    "dashboard-foundation.css",
    "dashboard-future.css",
    "dashboard-components.css",
    "dashboard-responsive.css",
    "dashboard-gauges.css",
)

DASHBOARD_SCRIPT_PARTS = (
    "dashboard-core.js",
    "dashboard-navigation.js",
    "dashboard-charts.js",
    "dashboard-metrics.js",
    "dashboard-overview.js",
    "dashboard-future.js",
    "dashboard-runtime.js",
)


def templates_path() -> Path:
    return Path(__file__).resolve().parent / "templates"


def read_template(name: str) -> str:
    return (templates_path() / name).read_text(encoding="utf-8")


def load_dashboard_template() -> str:
    """Compose source partials into the original single-file dashboard template."""
    template = read_template("dashboard.html")
    css = "\n\n".join(read_template(name).rstrip("\n") for name in DASHBOARD_STYLE_PARTS)
    script = "\n\n".join(read_template(name).rstrip("\n") for name in DASHBOARD_SCRIPT_PARTS)
    return template.replace("__DASHBOARD_CSS__", css).replace("__DASHBOARD_SCRIPT__", script)


def render_dashboard_html(payload: dict[str, Any]) -> str:
    json_text = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    measurement_id = os.environ.get("GA_MEASUREMENT_ID", "").strip()
    return (
        load_dashboard_template()
        .replace("__DASHBOARD_JSON__", json_text)
        .replace("__GA_MEASUREMENT_ID__", measurement_id)
    )


def load_admin_template() -> str:
    return read_template("admin.html")


def write_admin_html(output_path: Path) -> None:
    admin_path = output_path / "admin"
    admin_path.mkdir(parents=True, exist_ok=True)
    (admin_path / "index.html").write_text(load_admin_template(), encoding="utf-8")
    for filename in ("privacy.html", "terms.html"):
        template = templates_path() / filename
        if template.exists():
            (output_path / filename).write_text(template.read_text(encoding="utf-8"), encoding="utf-8")


def copy_signal_log_output(config: dict[str, Any], data_path: Path) -> None:
    signal_path = Path(
        str((config.get("alerts", {}) or {}).get("signal_log_file") or "data/signal_log.json")
    )
    if not signal_path.exists():
        return
    data_path.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(signal_path, data_path / "signal_log.json")


def dashboard_assets_source() -> Path | None:
    candidates = (
        Path.cwd() / "assets",
        Path(__file__).resolve().parents[2] / "assets",
    )
    return next((path for path in candidates if path.exists()), None)


def copy_dashboard_assets(output_path: Path) -> None:
    assets_source = dashboard_assets_source()
    if assets_source is None:
        return

    for directory in ("industry-icons", "future-images", "country-flags"):
        source = assets_source / directory
        target = output_path / "assets" / directory
        if not source.exists():
            continue
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target, dirs_exist_ok=True)

    assets_target = output_path / "assets"
    assets_target.mkdir(parents=True, exist_ok=True)
    for filename in (
        "marketbrief-logo.svg",
        "marketbrief-logo.png",
        "luceforge-studio-final.png",
        "pwa-icon-192.png",
        "pwa-icon-512.png",
    ):
        source_file = assets_source / filename
        if source_file.exists():
            shutil.copyfile(source_file, assets_target / filename)

    manifest = assets_source / "manifest.webmanifest"
    if manifest.exists():
        shutil.copyfile(manifest, output_path / "manifest.webmanifest")

    service_worker = assets_source / "service-worker.js"
    if service_worker.exists():
        build_ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        worker_text = service_worker.read_text(encoding="utf-8").replace("__BUILD_TS__", build_ts)
        (output_path / "service-worker.js").write_text(worker_text, encoding="utf-8")


def write_dashboard_shell(output_path: Path, payload: dict[str, Any]) -> None:
    """Write the static HTML shell and shared assets for any dashboard build mode."""
    copy_dashboard_assets(output_path)
    (output_path / "index.html").write_text(render_dashboard_html(payload), encoding="utf-8")
    write_admin_html(output_path)
    (output_path / ".nojekyll").write_text("", encoding="utf-8")
