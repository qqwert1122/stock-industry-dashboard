"""KRX 수급 데이터 저장 보조 함수.

B2 수급 수집기는 일부 주체/측정값만 지표화하더라도, 후속 재처리를 위해
KRX 응답 원본 행 전체를 날짜별 스냅샷으로 보존합니다.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from .market_sentiment import krx_date, parse_date_key, parse_krx_number

RAW_FLOW_SNAPSHOT_VERSION = 1
KRX_GETJSON_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_STOCK_FLOW_BLD = "dbms/MDC/STAT/standard/MDCSTAT02203"
KRX_FUTURES_FLOW_BLD = "dbms/MDC/STAT/standard/MDCSTAT13502"
KRX_MAIN_INVESTOR_FLOW_BLD = "dbms/MDC/MAIN/MDCMAIN00103"

INVESTOR_SLUGS = {
    "개인": "individual",
    "외국인": "foreign",
    "기관": "institution",
    "기관합계": "institution-total",
    "기관종합": "institution-total",
    "금융투자": "financial-investment",
    "보험": "insurance",
    "투신": "investment-trust",
    "기타금융": "other-finance",
    "은행": "bank",
    "연기금": "pension",
    "사모": "private-fund",
    "기타법인": "other-corporate",
}

FLOW_MEASURES = {
    "sell": {
        "label": "매도",
        "fields": ("ASK_TRDVAL", "ASK_TRD_VAL", "SEL_TRDVAL", "SELL_TRDVAL", "ASK_AMT", "ACC_ASK_TRDVAL"),
    },
    "buy": {
        "label": "매수",
        "fields": ("BID_TRDVAL", "BID_TRD_VAL", "BUY_TRDVAL", "BID_AMT", "ACC_BID_TRDVAL"),
    },
    "net": {
        "label": "순매수",
        "fields": ("NETBID_TRDVAL", "NET_BID_TRDVAL", "NETBID_TRD_VAL", "NETBID_AMT"),
    },
}

STOCK_MARKET_IDS = {"kospi": "STK", "kosdaq": "KSQ"}


def raw_flow_snapshot_path(history_dir: str | Path, market: str) -> Path:
    return Path(history_dir) / f"krx-flow-raw-{str(market).lower()}.json"


def empty_raw_flow_snapshot(market: str) -> dict[str, Any]:
    return {
        "version": RAW_FLOW_SNAPSHOT_VERSION,
        "market": market,
        "dates": {},
        "empty_dates": [],
    }


def load_raw_flow_snapshot(path: str | Path, market: str) -> dict[str, Any]:
    document = empty_raw_flow_snapshot(market)
    target = Path(path)
    if not target.exists():
        return document
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return document
    if not isinstance(loaded, dict):
        return document
    if isinstance(loaded.get("dates"), dict):
        document["dates"] = loaded["dates"]
    if isinstance(loaded.get("empty_dates"), list):
        document["empty_dates"] = [str(item) for item in loaded["empty_dates"]]
    return document


def save_raw_flow_snapshot(path: str | Path, document: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def raw_flow_known_dates(document: dict[str, Any]) -> set[str]:
    dates = set(str(item) for item in (document.get("dates") or {}).keys())
    dates.update(str(item) for item in (document.get("empty_dates") or []))
    return dates


def normalize_raw_flow_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return JSON-safe row copies without dropping unknown KRX fields."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized.append({str(key): value for key, value in deepcopy(row).items()})
    return normalized


def merge_raw_flow_rows(
    document: dict[str, Any],
    observed_at: date,
    rows: list[dict[str, Any]],
) -> None:
    key = observed_at.isoformat()
    normalized = normalize_raw_flow_rows(rows)
    empty_dates = set(str(item) for item in document.get("empty_dates") or [])
    if not normalized:
        empty_dates.add(key)
        document["empty_dates"] = sorted(empty_dates)
        return

    document.setdefault("dates", {})[key] = normalized
    if key in empty_dates:
        empty_dates.remove(key)
    document["empty_dates"] = sorted(empty_dates)


def prune_raw_flow_snapshot(
    document: dict[str, Any],
    *,
    today: date,
    keep_calendar_days: int,
) -> None:
    cutoff = today - timedelta(days=keep_calendar_days)
    keep = {
        key
        for key in (document.get("dates") or {}).keys()
        if parse_date_key(str(key)) is not None and parse_date_key(str(key)) >= cutoff
    }
    document["dates"] = {
        key: value for key, value in (document.get("dates") or {}).items() if key in keep
    }
    document["empty_dates"] = [
        key
        for key in (document.get("empty_dates") or [])
        if parse_date_key(str(key)) is not None and parse_date_key(str(key)) >= cutoff
    ]


def store_raw_flow_rows(
    *,
    history_dir: str | Path,
    market: str,
    observed_at: date,
    rows: list[dict[str, Any]],
    today: date,
    keep_calendar_days: int,
) -> dict[str, Any]:
    path = raw_flow_snapshot_path(history_dir, market)
    document = load_raw_flow_snapshot(path, market)
    merge_raw_flow_rows(document, observed_at, rows)
    prune_raw_flow_snapshot(document, today=today, keep_calendar_days=keep_calendar_days)
    save_raw_flow_snapshot(path, document)
    return document


def investor_slug(value: str) -> str:
    text = str(value or "").strip()
    if text in INVESTOR_SLUGS:
        return INVESTOR_SLUGS[text]
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "unknown"


def row_investor_name(row: dict[str, Any]) -> str:
    for key in ("INVST_TP_NM", "INVST_NM", "INVST_TP", "INVESTOR_NM"):
        value = str(row.get(key) or "").strip()
        if value:
            return value.split("(", 1)[0].strip()
    return ""


def flow_row_unit_multiplier(row: dict[str, Any]) -> float:
    unit_text = " ".join(str(row.get(key) or "") for key in ("INVST_TP", "INVST_TP_NM", "INVST_NM"))
    if "십억원" in unit_text:
        return 10.0
    return 1.0


def flow_row_value(row: dict[str, Any], measure: str) -> float | None:
    fields = FLOW_MEASURES.get(measure, {}).get("fields", ())
    for field in fields:
        value = parse_krx_number(row.get(field))
        if value is not None:
            return value * flow_row_unit_multiplier(row)
    return None


def row_trade_date(row: dict[str, Any]) -> date | None:
    for key in ("TRD_DD", "BAS_DD", "basDd"):
        raw = str(row.get(key) or "").strip().replace("-", "")
        if len(raw) == 8 and raw.isdigit():
            try:
                return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
            except ValueError:
                return None
    return None


def raw_flow_series(
    document: dict[str, Any],
    *,
    investor: str,
    measure: str,
) -> list[tuple[date, float]]:
    series: list[tuple[date, float]] = []
    target = str(investor or "").strip()
    dates = document.get("dates") if isinstance(document.get("dates"), dict) else {}
    for key, rows in sorted(dates.items()):
        observed_at = parse_date_key(str(key))
        if observed_at is None or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row_investor_name(row) != target:
                continue
            value = flow_row_value(row, measure)
            if value is not None:
                series.append((observed_at, value))
            break
    return series


def raw_flow_investors(document: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    dates = document.get("dates") if isinstance(document.get("dates"), dict) else {}
    for rows in dates.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row_investor_name(row)
            if name and name not in ordered:
                ordered.append(name)
    return ordered


def rolling_sum_series(points: list[tuple[date, float]], window: int = 20) -> list[tuple[date, float]]:
    if not points:
        return []
    result: list[tuple[date, float]] = []
    values: list[float] = []
    for observed_at, value in points:
        values.append(value)
        result.append((observed_at, sum(values[-window:])))
    return result


def fetch_krx_getjson_rows(
    session: requests.Session,
    *,
    form: dict[str, Any],
    endpoint: str = KRX_GETJSON_URL,
) -> list[dict[str, Any]]:
    response = session.post(
        endpoint,
        data=form,
        headers={
            "User-Agent": "Mozilla/5.0 stock-industry-dashboard/1.0",
            "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd",
        },
        timeout=(5, 30),
    )
    response.raise_for_status()
    payload = response.json()
    for key in ("output", "OutBlock_1", "block1"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def fetch_krx_main_investor_flow_rows(
    session: requests.Session,
    *,
    market: str,
    endpoint: str = KRX_GETJSON_URL,
) -> tuple[date | None, list[dict[str, Any]]]:
    market_key = str(market).lower()
    form: dict[str, Any] = {
        "bld": KRX_MAIN_INVESTOR_FLOW_BLD,
        "locale": "ko_KR",
    }
    if market_key in STOCK_MARKET_IDS:
        form["mktId"] = STOCK_MARKET_IDS[market_key]
    elif market_key in {"k200-futures", "futures"}:
        form["prodId"] = "KR___FUK2I"
    else:
        form["mktId"] = str(market).upper()
    rows = fetch_krx_getjson_rows(session, endpoint=endpoint, form=form)
    observed_dates = [row_trade_date(row) for row in rows]
    observed_at = next((item for item in observed_dates if item is not None), None)
    return observed_at, rows


def fetch_krx_stock_flow_rows(
    session: requests.Session,
    *,
    market: str,
    start_date: date,
    end_date: date,
    endpoint: str = KRX_GETJSON_URL,
) -> list[dict[str, Any]]:
    market_id = STOCK_MARKET_IDS.get(str(market).lower(), str(market).upper())
    return fetch_krx_getjson_rows(
        session,
        endpoint=endpoint,
        form={
            "bld": KRX_STOCK_FLOW_BLD,
            "locale": "ko_KR",
            "mktId": market_id,
            "strtDd": krx_date(start_date),
            "endDd": krx_date(end_date),
            "share": "1",
            "money": "1",
        },
    )


def fetch_krx_futures_flow_rows(
    session: requests.Session,
    *,
    start_date: date,
    end_date: date,
    endpoint: str = KRX_GETJSON_URL,
) -> list[dict[str, Any]]:
    return fetch_krx_getjson_rows(
        session,
        endpoint=endpoint,
        form={
            "bld": KRX_FUTURES_FLOW_BLD,
            "locale": "ko_KR",
            "prodId": "KRDRVFUK2I",
            "strtDd": krx_date(start_date),
            "endDd": krx_date(end_date),
            "share": "1",
            "money": "1",
        },
    )
