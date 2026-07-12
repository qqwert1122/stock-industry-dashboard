from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .storage import load_json, write_json


FETCH_LOG_VERSION = 1
FETCH_LOG_LIMIT = 60
FETCH_STATUSES = {"success", "no_new_data", "failed"}
SECRET_NAME_PATTERNS = (
    "FRED_API_KEY",
    "ECOS_API_KEY",
    "DATA_GO_KR_SERVICE_KEY",
    "EIA_API_KEY",
    "SEC_USER_AGENT",
    "NREL_API_KEY",
    "OPENFDA_API_KEY",
    "KOSIS_API_KEY",
    "KRX_OPEN_API_KEY",
    "KRX_API_KEY",
    "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "USER_PAGES_DEPLOY_KEY",
)

_CURRENT_LOGGER: "FetchLogger | None" = None


@dataclass
class FetchRecord:
    source: str
    endpoint: str
    status: str
    message: str
    metric_count: int
    new_data_count: int
    started_at: str
    duration_ms: int
    http_status: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["endpoint"] = sanitize_endpoint(data.get("endpoint", ""))
        data["message"] = sanitize_message(data.get("message", ""))
        if data["status"] not in FETCH_STATUSES:
            data["status"] = "failed"
        return data


def now_iso(timezone_name: str) -> str:
    return datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")


def sanitize_endpoint(value: object) -> str:
    """Return a URL template safe for public logs.

    This project publishes Actions logs and generated site data. Stripping the
    whole query string is intentionally stricter than masking selected keys,
    because encoded variants of API keys are easy to miss.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if "?" not in text and "#" not in text:
        return text
    try:
        parts = urlsplit(text)
    except ValueError:
        return text.split("?", 1)[0].split("#", 1)[0]
    if parts.scheme and parts.netloc:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return text.split("?", 1)[0].split("#", 1)[0]


def sanitize_message(value: object) -> str:
    text = str(value or "")
    for token in SECRET_NAME_PATTERNS:
        text = text.replace(token, "인증키")
    words = []
    for word in text.split():
        if word.startswith("http://") or word.startswith("https://"):
            words.append(sanitize_endpoint(word))
        else:
            words.append(word)
    return " ".join(words)


class FetchLogger:
    def __init__(self, *, run_type: str, timezone_name: str) -> None:
        self.run_type = run_type
        self.timezone_name = timezone_name
        self.started_at = now_iso(timezone_name)
        self._started_monotonic = time.monotonic()
        self.records: list[FetchRecord] = []

    def source_started(self) -> tuple[str, float]:
        return now_iso(self.timezone_name), time.monotonic()

    def record(
        self,
        *,
        source: str,
        endpoint: str = "",
        status: str,
        message: str = "",
        metric_count: int = 0,
        new_data_count: int = 0,
        started_at: str | None = None,
        started_monotonic: float | None = None,
        duration_ms: int | None = None,
        http_status: int | None = None,
    ) -> None:
        if duration_ms is None:
            base = started_monotonic if started_monotonic is not None else self._started_monotonic
            duration_ms = max(0, int((time.monotonic() - base) * 1000))
        self.records.append(
            FetchRecord(
                source=str(source or ""),
                endpoint=sanitize_endpoint(endpoint),
                status=status if status in FETCH_STATUSES else "failed",
                message=str(message or ""),
                metric_count=max(0, int(metric_count or 0)),
                new_data_count=max(0, int(new_data_count or 0)),
                started_at=started_at or self.started_at,
                duration_ms=duration_ms,
                http_status=http_status,
            )
        )

    def finish(self) -> dict[str, Any]:
        finished_at = now_iso(self.timezone_name)
        counts = {"success": 0, "no_new_data": 0, "failed": 0}
        for record in self.records:
            counts[record.status] = counts.get(record.status, 0) + 1
        return {
            "run_id": self.started_at,
            "run_type": self.run_type,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "duration_ms": max(0, int((time.monotonic() - self._started_monotonic) * 1000)),
            "summary": counts,
            "records": [record.to_dict() for record in self.records],
        }


def current_logger() -> FetchLogger | None:
    return _CURRENT_LOGGER


@contextmanager
def use_fetch_logger(logger: FetchLogger) -> Iterator[FetchLogger]:
    global _CURRENT_LOGGER
    previous = _CURRENT_LOGGER
    _CURRENT_LOGGER = logger
    try:
        yield logger
    finally:
        _CURRENT_LOGGER = previous


def empty_history() -> dict[str, Any]:
    return {"version": FETCH_LOG_VERSION, "runs": []}


def load_fetch_log_history(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    loaded = load_json(target, None)
    if not isinstance(loaded, dict):
        return empty_history()
    runs = loaded.get("runs")
    if not isinstance(runs, list):
        runs = []
    return {
        "version": int(loaded.get("version") or FETCH_LOG_VERSION),
        "runs": [run for run in runs if isinstance(run, dict)],
    }


def append_fetch_log_run(
    history: dict[str, Any] | None,
    run: dict[str, Any],
    *,
    limit: int = FETCH_LOG_LIMIT,
) -> dict[str, Any]:
    document = history if isinstance(history, dict) else empty_history()
    runs = [item for item in document.get("runs", []) if isinstance(item, dict)]
    run_id = str(run.get("run_id") or "")
    if run_id:
        runs = [item for item in runs if str(item.get("run_id") or "") != run_id]
    runs.append(run)
    runs.sort(key=lambda item: str(item.get("started_at") or ""))
    if limit > 0:
        runs = runs[-limit:]
    return {
        "version": FETCH_LOG_VERSION,
        "updated_at": str(run.get("finished_at") or ""),
        "count": len(runs),
        "runs": runs,
    }


def save_fetch_log_history(path: str | Path, history: dict[str, Any]) -> None:
    target = Path(path)
    write_json(target, history)
