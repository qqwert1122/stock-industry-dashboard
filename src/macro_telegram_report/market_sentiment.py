"""Market sentiment collectors and scoring helpers.

CNN Fear & Greed is copied from CNN's published dataviz JSON. Korean market
scores are transparent, local composites built from index momentum, breadth,
52-week highs/lows, and volatility.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .history_store import HistoryStore, parse_stored_points, percentile_of
from .utils import to_float

CNN_FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start_date}"
KRX_API_BASE = "https://data-dbg.krx.co.kr/svc/apis"
KRX_SOURCE_URL = "https://openapi.krx.co.kr/"
KRX_STOCK_APIS = {"KOSPI": "stk_bydd_trd", "KOSDAQ": "ksq_bydd_trd"}
KRX_STOCK_LABELS = {"KOSPI": "코스피", "KOSDAQ": "코스닥"}
VKOSPI_INDEX_NAME = "코스피 200 변동성지수"
SNAPSHOT_VERSION = 1


def parse_cnn_timestamp(value: object) -> date | None:
    if value is None:
        return None
    try:
        timestamp = float(value) / 1000.0
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date()


def parse_cnn_fear_greed_payload(payload: dict[str, Any]) -> list[tuple[date, float]]:
    historical = payload.get("fear_and_greed_historical") or {}
    raw_points = historical.get("data") or []
    by_date: dict[date, float] = {}
    for item in raw_points:
        if not isinstance(item, dict):
            continue
        observed_at = parse_cnn_timestamp(item.get("x"))
        score = to_float(item.get("y"))
        if observed_at is not None and score is not None:
            by_date[observed_at] = round(score, 2)

    current = payload.get("fear_and_greed") or {}
    current_score = to_float(current.get("score"))
    current_date = parse_iso_datetime_date(current.get("timestamp"))
    if current_date is not None and current_score is not None:
        by_date[current_date] = round(current_score, 2)
    return sorted(by_date.items())


def parse_iso_datetime_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def fetch_cnn_fear_greed(
    session: requests.Session,
    *,
    start_date: date,
) -> tuple[list[tuple[date, float]], dict[str, Any]]:
    response = session.get(
        CNN_FEAR_GREED_URL.format(start_date=start_date.isoformat()),
        headers={"User-Agent": "Mozilla/5.0 stock-industry-dashboard/1.0"},
        timeout=(5, 30),
    )
    response.raise_for_status()
    payload = response.json()
    return parse_cnn_fear_greed_payload(payload), payload


def parse_krx_number(value: object) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def krx_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def fetch_krx_openapi_rows(
    session: requests.Session,
    *,
    base_url: str,
    category: str,
    api_id: str,
    auth_key: str,
    target_date: date,
) -> list[dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/{category}/{api_id}.json"
    response = session.get(
        url,
        params={"basDd": krx_date(target_date)},
        headers={"AUTH_KEY": auth_key},
        timeout=(5, 30),
    )
    response.raise_for_status()
    payload = response.json()
    resp_code = str(payload.get("respCode") or "").strip()
    if resp_code and resp_code not in {"0000", "0", "200"}:
        resp_msg = str(payload.get("respMsg") or "KRX Open API error")
        raise ValueError(f"{api_id} {resp_code}: {resp_msg}")
    rows = payload.get("OutBlock_1") or []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def market_candidate_dates(today: date, calendar_days: int) -> list[date]:
    end = today - timedelta(days=1)
    start = end - timedelta(days=max(1, calendar_days))
    dates: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor += timedelta(days=1)
    return dates


def missing_recent_dates(
    *,
    today: date,
    known_dates: set[str],
    calendar_days: int,
    max_fetch: int,
) -> list[date]:
    candidates = market_candidate_dates(today, calendar_days)
    missing = [candidate for candidate in candidates if candidate.isoformat() not in known_dates]
    if max_fetch <= 0:
        return []
    return missing[-max_fetch:]


def snapshot_path(history_dir: str | Path, market: str) -> Path:
    return Path(history_dir) / f"krx-market-snapshot-{market.lower()}.json"


def load_snapshot_document(path: Path, market: str) -> dict[str, Any]:
    document: dict[str, Any] = {
        "version": SNAPSHOT_VERSION,
        "market": market,
        "dates": {},
        "breadth": {},
        "empty_dates": [],
    }
    if not path.exists():
        return document
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return document
    if not isinstance(loaded, dict):
        return document
    if isinstance(loaded.get("dates"), dict):
        document["dates"] = loaded["dates"]
    if isinstance(loaded.get("breadth"), dict):
        document["breadth"] = loaded["breadth"]
    if isinstance(loaded.get("empty_dates"), list):
        document["empty_dates"] = [str(item) for item in loaded["empty_dates"]]
    return document


def save_snapshot_document(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def snapshot_known_dates(document: dict[str, Any]) -> set[str]:
    dates = set(str(item) for item in (document.get("dates") or {}).keys())
    dates.update(str(item) for item in (document.get("empty_dates") or []))
    return dates


def merge_krx_stock_rows(document: dict[str, Any], observed_at: date, rows: list[dict[str, Any]]) -> None:
    key = observed_at.isoformat()
    closes: dict[str, float] = {}
    advancers = decliners = unchanged = 0
    for row in rows:
        ticker = str(row.get("ISU_CD") or "").strip()
        close = parse_krx_number(row.get("TDD_CLSPRC"))
        if not ticker or close is None or close <= 0:
            continue
        closes[ticker] = close
        change = parse_krx_number(row.get("CMPPREVDD_PRC"))
        if change is None:
            change = parse_krx_number(row.get("FLUC_RT"))
        if change is None:
            continue
        if change > 0:
            advancers += 1
        elif change < 0:
            decliners += 1
        else:
            unchanged += 1

    empty_dates = set(str(item) for item in document.get("empty_dates") or [])
    if not closes:
        empty_dates.add(key)
        document["empty_dates"] = sorted(empty_dates)
        return

    (document.setdefault("dates", {}))[key] = closes
    (document.setdefault("breadth", {}))[key] = {
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "total": advancers + decliners + unchanged,
    }
    if key in empty_dates:
        empty_dates.remove(key)
        document["empty_dates"] = sorted(empty_dates)


def prune_snapshot_document(document: dict[str, Any], *, today: date, keep_calendar_days: int) -> None:
    cutoff = today - timedelta(days=keep_calendar_days)
    keep = {
        key
        for key in (document.get("dates") or {}).keys()
        if parse_date_key(key) is not None and parse_date_key(key) >= cutoff
    }
    document["dates"] = {
        key: value for key, value in (document.get("dates") or {}).items() if key in keep
    }
    document["breadth"] = {
        key: value for key, value in (document.get("breadth") or {}).items() if key in keep
    }
    document["empty_dates"] = [
        key
        for key in (document.get("empty_dates") or [])
        if parse_date_key(key) is not None and parse_date_key(key) >= cutoff
    ]


def parse_date_key(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def latest_snapshot_date(document: dict[str, Any]) -> date | None:
    parsed = [parse_date_key(str(key)) for key in (document.get("dates") or {}).keys()]
    dates = [item for item in parsed if item is not None]
    return max(dates) if dates else None


def breadth_score(document: dict[str, Any], observed_at: date) -> tuple[float | None, dict[str, Any] | None]:
    row = (document.get("breadth") or {}).get(observed_at.isoformat())
    if not isinstance(row, dict):
        return None, None
    advancers = int(to_float(row.get("advancers")) or 0)
    decliners = int(to_float(row.get("decliners")) or 0)
    denominator = advancers + decliners
    if denominator <= 0:
        return None, row
    return round(100.0 * advancers / denominator, 1), row


def high_low_counts(
    document: dict[str, Any],
    observed_at: date,
    *,
    window_days: int,
    min_points: int,
) -> dict[str, int]:
    raw_dates = document.get("dates") or {}
    target_key = observed_at.isoformat()
    current = raw_dates.get(target_key)
    if not isinstance(current, dict):
        return {"new_highs": 0, "new_lows": 0, "eligible": 0}

    cutoff = observed_at - timedelta(days=window_days)
    window_keys = [
        key
        for key in raw_dates.keys()
        if (parsed := parse_date_key(str(key))) is not None and cutoff <= parsed <= observed_at
    ]
    window_keys.sort()
    history_by_ticker: dict[str, list[float]] = {}
    for key in window_keys:
        closes = raw_dates.get(key)
        if not isinstance(closes, dict):
            continue
        for ticker, raw_close in closes.items():
            close = to_float(raw_close)
            if close is None:
                continue
            history_by_ticker.setdefault(str(ticker), []).append(close)

    new_highs = new_lows = eligible = 0
    for ticker, raw_close in current.items():
        close = to_float(raw_close)
        values = history_by_ticker.get(str(ticker), [])
        if close is None or len(values) < min_points:
            continue
        eligible += 1
        if close >= max(values):
            new_highs += 1
        if close <= min(values):
            new_lows += 1
    return {"new_highs": new_highs, "new_lows": new_lows, "eligible": eligible}


def high_low_score(counts: dict[str, int]) -> float | None:
    highs = int(counts.get("new_highs") or 0)
    lows = int(counts.get("new_lows") or 0)
    total = highs + lows
    if total <= 0:
        return None
    return round(100.0 * highs / total, 1)


def collect_market_snapshot(
    session: requests.Session,
    *,
    auth_key: str,
    base_url: str,
    history_dir: str | Path,
    market: str,
    today: date,
    lookback_calendar_days: int,
    max_fetch_days: int,
    keep_calendar_days: int,
) -> dict[str, Any]:
    path = snapshot_path(history_dir, market)
    document = load_snapshot_document(path, market)
    dates = missing_recent_dates(
        today=today,
        known_dates=snapshot_known_dates(document),
        calendar_days=lookback_calendar_days,
        max_fetch=max_fetch_days,
    )
    api_id = KRX_STOCK_APIS[market]
    for target_date in dates:
        rows = fetch_krx_openapi_rows(
            session,
            base_url=base_url,
            category="sto",
            api_id=api_id,
            auth_key=auth_key,
            target_date=target_date,
        )
        merge_krx_stock_rows(document, target_date, rows)
    prune_snapshot_document(document, today=today, keep_calendar_days=keep_calendar_days)
    save_snapshot_document(path, document)
    return document


def fetch_vkospi_points(
    session: requests.Session,
    *,
    auth_key: str,
    base_url: str,
    store: HistoryStore | None,
    today: date,
    history_key: str,
    lookback_calendar_days: int,
    max_fetch_days: int,
) -> list[tuple[date, float]]:
    known = {point[0].isoformat() for point in (store.series(history_key) if store else [])}
    dates = missing_recent_dates(
        today=today,
        known_dates=known,
        calendar_days=lookback_calendar_days,
        max_fetch=max_fetch_days,
    )
    incoming: list[tuple[date, float]] = []
    for target_date in dates:
        rows = fetch_krx_openapi_rows(
            session,
            base_url=base_url,
            category="idx",
            api_id="drvprod_dd_trd",
            auth_key=auth_key,
            target_date=target_date,
        )
        for row in rows:
            if str(row.get("IDX_NM") or "").strip() != VKOSPI_INDEX_NAME:
                continue
            value = parse_krx_number(row.get("CLSPRC_IDX"))
            if value is not None:
                incoming.append((target_date, value))
            break
    incoming.sort(key=lambda point: point[0])
    return incoming


def merge_existing_and_incoming(
    store: HistoryStore | None,
    key: str,
    incoming: list[tuple[date, float]],
) -> list[tuple[date, float]]:
    merged: dict[date, float] = {}
    if store is not None:
        merged.update(dict(store.series(key)))
    merged.update(dict(incoming))
    return sorted(merged.items())


def metric_full_points(
    store: HistoryStore | None,
    metric: dict[str, Any] | None,
    history_key: str,
) -> list[tuple[date, float]]:
    merged: dict[date, float] = {}
    if store is not None:
        merged.update(dict(store.series(history_key)))
    if metric is not None:
        merged.update(dict(parse_stored_points(metric.get("history"))))
    return sorted(merged.items())


def rolling_momentum_scores(
    points: list[tuple[date, float]],
    *,
    window: int = 125,
) -> list[tuple[date, float]]:
    values = [value for _, value in points]
    dates = [point_date for point_date, _ in points]
    scores: list[tuple[date, float]] = []
    if len(values) < max(20, window):
        return scores
    for index in range(window - 1, len(values)):
        window_values = values[index - window + 1 : index + 1]
        average = sum(window_values) / len(window_values)
        if average:
            scores.append((dates[index], (values[index] / average - 1.0) * 100.0))
    return scores


def rolling_realized_volatility(
    points: list[tuple[date, float]],
    *,
    window: int = 20,
) -> list[tuple[date, float]]:
    if len(points) < window + 1:
        return []
    returns: list[tuple[date, float]] = []
    for index in range(1, len(points)):
        previous = points[index - 1][1]
        current = points[index][1]
        if previous <= 0 or current <= 0:
            continue
        returns.append((points[index][0], math.log(current / previous)))
    vol_points: list[tuple[date, float]] = []
    for index in range(window - 1, len(returns)):
        window_returns = [value for _, value in returns[index - window + 1 : index + 1]]
        mean = sum(window_returns) / len(window_returns)
        variance = sum((value - mean) ** 2 for value in window_returns) / len(window_returns)
        vol_points.append((returns[index][0], math.sqrt(variance) * math.sqrt(252) * 100.0))
    return vol_points


def percentile_component_score(
    points: list[tuple[date, float]],
    *,
    inverse: bool = False,
    min_points: int = 20,
) -> tuple[float | None, float | None]:
    if len(points) < min_points:
        return None, None
    current = points[-1][1]
    pct = percentile_of([value for _, value in points], current)
    if pct is None:
        return None, current
    return round(100.0 - pct if inverse else pct, 1), current


def build_korea_fear_greed_score(
    *,
    market_label: str,
    index_points: list[tuple[date, float]],
    snapshot_document: dict[str, Any],
    vkospi_points: list[tuple[date, float]] | None = None,
    high_low_window_days: int = 370,
    min_high_low_points: int = 120,
) -> dict[str, Any] | None:
    observed_at = latest_snapshot_date(snapshot_document)
    if observed_at is None:
        return None

    components: list[dict[str, Any]] = []
    momentum_points = rolling_momentum_scores(index_points)
    momentum_score, momentum_value = percentile_component_score(momentum_points, min_points=20)
    if momentum_score is not None:
        components.append(
            {
                "name": "가격 추세",
                "score": momentum_score,
                "value": momentum_value,
                "basis": "지수가 125거래일 평균보다 얼마나 위에 있는지",
            }
        )

    breadth, breadth_row = breadth_score(snapshot_document, observed_at)
    if breadth is not None:
        components.append(
            {
                "name": "등락 종목",
                "score": breadth,
                "value": breadth,
                "basis": "오른 종목 비중",
                "detail": breadth_row,
            }
        )

    counts = high_low_counts(
        snapshot_document,
        observed_at,
        window_days=high_low_window_days,
        min_points=min_high_low_points,
    )
    high_low = high_low_score(counts)
    if high_low is not None:
        components.append(
            {
                "name": "52주 신고·신저",
                "score": high_low,
                "value": high_low,
                "basis": "52주 신고가 종목 비중",
                "detail": counts,
            }
        )

    volatility_basis = "VKOSPI가 낮을수록 투자심리가 안정적이라는 방식"
    volatility_score, volatility_value = percentile_component_score(
        vkospi_points or [],
        inverse=True,
        min_points=20,
    )
    if volatility_score is None:
        volatility_basis = "최근 20거래일 지수 변동성이 낮을수록 투자심리가 안정적이라는 방식"
        volatility_score, volatility_value = percentile_component_score(
            rolling_realized_volatility(index_points),
            inverse=True,
            min_points=20,
        )
    if volatility_score is not None:
        components.append(
            {
                "name": "변동성",
                "score": volatility_score,
                "value": volatility_value,
                "basis": volatility_basis,
            }
        )

    if len(components) < 3:
        return None

    score = round(sum(component["score"] for component in components) / len(components), 1)
    return {
        "market": market_label,
        "score": score,
        "observed_at": observed_at,
        "components": components,
    }
