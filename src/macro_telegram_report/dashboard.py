from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from openpyxl import load_workbook

from .korea_exports import fetch_itemtrade_records
from .utils import add_months, fmt_number, fmt_pct, fmt_signed, month_key, pct_change, to_float
from .wsts import find_wsts_xlsx_url, parse_wsts_sheet

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
DEFAULT_INDUSTRIES = [
    "반도체",
    "자동차/전기차",
    "조선",
    "철강/소재",
    "화학/정유",
    "은행/금융",
    "건설/부동산",
    "방산",
    "스테이블코인",
    "전력",
    "로봇",
    "우주",
    "바이오",
    "배터리",
    "매크로",
]
INDUSTRY_ICONS = {
    "반도체": "assets/industry-icons/semiconductor.png",
    "자동차/전기차": "assets/industry-icons/auto-ev.png",
    "조선": "assets/industry-icons/shipbuilding.png",
    "철강/소재": "assets/industry-icons/steel-materials.png",
    "화학/정유": "assets/industry-icons/chemicals-refining.png",
    "은행/금융": "assets/industry-icons/finance.png",
    "건설/부동산": "assets/industry-icons/construction-real-estate.png",
    "방산": "assets/industry-icons/defense.png",
    "스테이블코인": "assets/industry-icons/stablecoins.png",
    "전력": "assets/industry-icons/power.png",
    "로봇": "assets/industry-icons/robotics.png",
    "우주": "assets/industry-icons/space.png",
    "바이오": "assets/industry-icons/biotech.png",
    "배터리": "assets/industry-icons/battery.png",
    "데이터인프라": "assets/industry-icons/data-infrastructure.png",
    "매크로": "assets/industry-icons/macro.png",
}
INDUSTRY_SUMMARIES = {
    "반도체": "메모리, 파운드리, 장비, AI 인프라 수요를 함께 봅니다.",
    "자동차/전기차": "완성차 판매와 EV, 배터리 원재료 흐름을 묶어 봅니다.",
    "조선": "운임, 선가, 발주, 선박 수출을 통해 수주 환경을 점검합니다.",
    "철강/소재": "원자재 가격과 중국 제조업 경기를 소재 업황 proxy로 봅니다.",
    "화학/정유": "유가, 원료, 제품 스프레드로 마진 방향을 확인합니다.",
    "은행/금융": "금리, 스프레드, 대출, 연체율로 금융 환경을 봅니다.",
    "건설/부동산": "착공, 허가, 금리, 가격으로 부동산 선행 흐름을 봅니다.",
    "방산": "수주, 생산, 수출 흐름으로 방산 수요를 확인합니다.",
    "스테이블코인": "온체인 달러 유동성과 결제/거래 수요를 봅니다.",
    "전력": "전력 가격, 생산, 장비 수출로 인프라 수요를 확인합니다.",
    "로봇": "설비투자와 로봇 수출 흐름을 묶어 봅니다.",
    "우주": "우주/항공 장비 생산과 이벤트 수요를 추적합니다.",
    "바이오": "바이오 제품 가격과 수출 흐름으로 업황을 봅니다.",
    "배터리": "배터리 가격, 원재료, 수출 흐름으로 셀/소재 업황을 봅니다.",
    "데이터인프라": "서버와 네트워크 인프라 투자 흐름을 봅니다.",
    "매크로": "환율과 변동성으로 시장 환경을 빠르게 확인합니다.",
}


def build_dashboard_site(config: dict[str, Any], output_dir: str | Path, session: requests.Session) -> dict[str, Any]:
    output_path = Path(output_dir)
    data_path = output_path / "data"
    data_path.mkdir(parents=True, exist_ok=True)

    payload = build_dashboard_payload(config, session)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)

    copy_dashboard_assets(output_path)
    (data_path / "dashboard.json").write_text(json_text + "\n", encoding="utf-8")
    (output_path / "index.html").write_text(render_dashboard_html(payload), encoding="utf-8")
    (output_path / ".nojekyll").write_text("", encoding="utf-8")
    return payload


def copy_dashboard_assets(output_path: Path) -> None:
    candidates = [
        Path.cwd() / "assets" / "industry-icons",
        Path(__file__).resolve().parents[2] / "assets" / "industry-icons",
    ]
    source = next((path for path in candidates if path.exists()), None)
    if source is None:
        return

    target = output_path / "assets" / "industry-icons"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def build_dashboard_payload(config: dict[str, Any], session: requests.Session) -> dict[str, Any]:
    timezone = str(config.get("timezone") or "Asia/Seoul")
    now = datetime.now(ZoneInfo(timezone))

    source_status: list[dict[str, str]] = []
    metrics: list[dict[str, Any]] = []

    collectors = [
        ("WSTS", collect_wsts_metrics),
        ("FRED", collect_fred_metrics),
        ("스테이블코인", collect_stablecoin_metrics),
        ("한국 수출", collect_korea_export_metrics),
    ]
    for source_name, collector in collectors:
        before = len(metrics)
        try:
            source_metrics = collector(config, session, now.date())
            metrics.extend(source_metrics)
            ok_count = sum(1 for item in source_metrics if item.get("status") == "ok")
            source_status.append(
                {
                    "name": source_name,
                    "status": "ok" if ok_count else "partial",
                    "message": f"{ok_count}/{len(source_metrics)}개 지표 자동 수집",
                }
            )
        except Exception as exc:  # noqa: BLE001 - dashboard should survive source-level failures.
            source_status.append({"name": source_name, "status": "error", "message": str(exc)})
            if len(metrics) == before:
                metrics.append(
                    make_metric(
                        industry="매크로",
                        name=f"{source_name} 수집 상태",
                        source=source_name,
                        source_url="",
                        frequency="",
                        automation="부분 자동화 가능",
                        status="error",
                        note=str(exc),
                    )
                )

    metrics.extend(collect_reference_metrics(config))
    metrics = visible_dashboard_metrics(metrics)
    industries = configured_industries(config, metrics)

    return {
        "title": "산업별 지표 대시보드",
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_label": now.strftime("%Y-%m-%d %H:%M %Z"),
        "timezone": timezone,
        "industries": industries,
        "industry_icons": INDUSTRY_ICONS,
        "source_status": [],
        "metrics": metrics,
    }


def collect_fred_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    dashboard_config = config.get("dashboard", {})
    fred_config = config.get("fred", {})
    if not fred_config.get("enabled", True):
        return []

    series_config = dashboard_config.get("fred_series") or fred_config.get("series", [])
    api_key = os.getenv("FRED_API_KEY", "").strip()
    history_limit = int(dashboard_config.get("history_points", 48))
    fetch_limit = max(history_limit, 80)

    if not api_key:
        return [
            make_metric(
                industry=str(series.get("industry") or "매크로"),
                name=str(series.get("name") or series.get("id")),
                source="FRED API",
                source_url=f"https://fred.stlouisfed.org/series/{str(series.get('id', '')).strip()}",
                frequency=str(series.get("frequency") or "FRED"),
                automation="무료로 안정적으로 자동화 가능",
                status="needs_key",
                note="GitHub Secrets에 FRED_API_KEY 등록 필요",
                group=str(series.get("group") or ""),
                meaning=str(series.get("meaning") or ""),
            )
            for series in series_config
            if series.get("id")
        ]

    metrics: list[dict[str, Any]] = []
    for series in series_config:
        series_id = str(series.get("id", "")).strip()
        if not series_id:
            continue

        name = str(series.get("name") or series_id)
        unit = str(series.get("unit") or "")
        industry = str(series.get("industry") or "매크로")
        frequency = str(series.get("frequency") or "FRED")
        source_url = f"https://fred.stlouisfed.org/series/{series_id}"

        try:
            points, source_label = fetch_fred_history(
                session=session,
                series_id=series_id,
                api_key=api_key,
                limit=fetch_limit,
            )
            if not points:
                metrics.append(
                    make_metric(
                        industry=industry,
                        name=name,
                        source="FRED",
                        source_url=source_url,
                        frequency=frequency,
                        automation="무료로 안정적으로 자동화 가능",
                        status="error",
                        note="관측값 없음",
                    )
                )
                continue

            latest_date, latest_value = points[-1]
            previous_value = points[-2][1] if len(points) > 1 else None
            yoy_value = find_yoy_value(points, latest_date)
            metrics.append(
                make_metric(
                    industry=industry,
                    name=name,
                    source=source_label,
                    source_url=source_url,
                    frequency=frequency,
                    automation="무료로 안정적으로 자동화 가능",
                    status="ok",
                    value=latest_value,
                    unit=unit,
                    observed_at=latest_date.isoformat(),
                    previous_value=previous_value,
                    yoy_value=yoy_value,
                    history=points[-history_limit:],
                    note=str(series.get("note") or ""),
                    group=str(series.get("group") or ""),
                    meaning=str(series.get("meaning") or ""),
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep each card independent.
            metrics.append(
                make_metric(
                    industry=industry,
                    name=name,
                    source="FRED",
                    source_url=source_url,
                    frequency=frequency,
                    automation="무료로 안정적으로 자동화 가능",
                    status="error",
                    note=str(exc),
                )
            )

    return metrics


def fetch_fred_history(
    session: requests.Session, series_id: str, api_key: str, limit: int
) -> tuple[list[tuple[date, float]], str]:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    response = session.get(FRED_OBSERVATIONS_URL, params=params, timeout=(5, 20))
    response.raise_for_status()
    payload = response.json()
    points = []
    for item in payload.get("observations", []):
        value = to_float(item.get("value"))
        if value is None:
            continue
        points.append((date.fromisoformat(str(item["date"])), value))
    points.sort(key=lambda point: point[0])
    return points[-limit:], "FRED API"


def collect_stablecoin_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    stablecoin_config = config.get("stablecoins", {})
    if not stablecoin_config.get("enabled", True):
        return []

    endpoint = str(
        stablecoin_config.get("endpoint")
        or "https://stablecoins.llama.fi/stablecoins?includePrices=true"
    )
    source_url = str(stablecoin_config.get("source_url") or "https://defillama.com/stablecoins")
    response = session.get(endpoint, timeout=(5, 20))
    response.raise_for_status()
    payload = response.json()
    assets = [
        asset
        for asset in payload.get("peggedAssets", [])
        if isinstance(asset, dict) and not asset.get("delisted")
    ]

    configured_assets = stablecoin_config.get("assets") or [
        {"symbol": "TOTAL", "name": "전체 스테이블코인 유통량"},
        {"symbol": "USDT", "name": "USDT 유통량"},
        {"symbol": "USDC", "name": "USDC 유통량"},
    ]

    metrics: list[dict[str, Any]] = []
    for item in configured_assets:
        symbol = str(item.get("symbol") or "").upper()
        asset_id = str(item.get("id") or "")
        name = str(item.get("name") or symbol or asset_id or "스테이블코인 유통량")

        if symbol == "TOTAL":
            values = stablecoin_total_values(assets)
        else:
            asset = find_stablecoin_asset(assets, symbol=symbol, asset_id=asset_id)
            if asset is None:
                metrics.append(
                    make_metric(
                        industry="스테이블코인",
                        name=name,
                        source="DefiLlama Stablecoins API",
                        source_url=source_url,
                        frequency="일간",
                        automation="무료로 안정적으로 자동화 가능",
                        status="error",
                        note=f"{symbol or asset_id} 자산을 찾을 수 없음",
                        group=str(item.get("group") or "유통량"),
                        meaning=str(item.get("meaning") or stablecoin_meaning()),
                    )
                )
                continue
            values = stablecoin_asset_values(asset)
            if not item.get("name"):
                name = f"{asset.get('name', symbol)}({asset.get('symbol', symbol)}) 유통량"

        current = values.get("current")
        if current is None:
            metrics.append(
                make_metric(
                    industry="스테이블코인",
                    name=name,
                    source="DefiLlama Stablecoins API",
                    source_url=source_url,
                    frequency="일간",
                    automation="무료로 안정적으로 자동화 가능",
                    status="error",
                    note="유통량 데이터 없음",
                    group=str(item.get("group") or "유통량"),
                    meaning=str(item.get("meaning") or stablecoin_meaning()),
                )
            )
            continue

        history = stablecoin_history_points(values, today)
        metrics.append(
            make_metric(
                industry="스테이블코인",
                name=name,
                source="DefiLlama Stablecoins API",
                source_url=source_url,
                frequency="일간",
                automation="무료 공개 API 자동 수집",
                status="ok",
                value=current / 1_000_000_000,
                unit="$B",
                observed_at=today.isoformat(),
                previous_value=stablecoin_billions(values.get("prev_day")),
                yoy_value=None,
                history=history,
                note=str(item.get("note") or ""),
                group=str(item.get("group") or "유통량"),
                meaning=str(item.get("meaning") or stablecoin_meaning()),
            )
        )
    return metrics


def find_stablecoin_asset(
    assets: list[dict[str, Any]], *, symbol: str, asset_id: str
) -> dict[str, Any] | None:
    for asset in assets:
        if asset_id and str(asset.get("id") or "") == asset_id:
            return asset
        if symbol and str(asset.get("symbol") or "").upper() == symbol:
            return asset
    return None


def stablecoin_asset_values(asset: dict[str, Any]) -> dict[str, float | None]:
    return {
        "current": stablecoin_supply_value(asset, "circulating"),
        "prev_day": stablecoin_supply_value(asset, "circulatingPrevDay"),
        "prev_week": stablecoin_supply_value(asset, "circulatingPrevWeek"),
        "prev_month": stablecoin_supply_value(asset, "circulatingPrevMonth"),
    }


def stablecoin_total_values(assets: list[dict[str, Any]]) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for key, source_key in [
        ("current", "circulating"),
        ("prev_day", "circulatingPrevDay"),
        ("prev_week", "circulatingPrevWeek"),
        ("prev_month", "circulatingPrevMonth"),
    ]:
        total = 0.0
        found = False
        for asset in assets:
            if str(asset.get("pegType") or "") != "peggedUSD":
                continue
            value = stablecoin_supply_value(asset, source_key)
            if value is None:
                continue
            total += value
            found = True
        values[key] = total if found else None
    return values


def stablecoin_supply_value(asset: dict[str, Any], key: str) -> float | None:
    value = asset.get(key)
    if isinstance(value, dict):
        return to_float(value.get("peggedUSD"))
    return to_float(value)


def stablecoin_history_points(values: dict[str, float | None], today: date) -> list[tuple[date, float]]:
    points = [
        (today - timedelta(days=30), stablecoin_billions(values.get("prev_month"))),
        (today - timedelta(days=7), stablecoin_billions(values.get("prev_week"))),
        (today - timedelta(days=1), stablecoin_billions(values.get("prev_day"))),
        (today, stablecoin_billions(values.get("current"))),
    ]
    return [(observed_at, value) for observed_at, value in points if value is not None]


def stablecoin_billions(value: float | None) -> float | None:
    return value / 1_000_000_000 if value is not None else None


def stablecoin_meaning() -> str:
    return "달러 연동 스테이블코인의 유통량 변화로 온체인 달러 유동성과 결제/거래 수요를 확인합니다."


def collect_wsts_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    del today
    wsts_config = config.get("wsts", {})
    if not wsts_config.get("enabled", True):
        return []

    xlsx_url = wsts_config.get("download_url") or find_wsts_xlsx_url(
        str(wsts_config["page_url"]), session
    )
    response = session.get(str(xlsx_url), timeout=60)
    response.raise_for_status()
    workbook = load_workbook(BytesIO(response.content), data_only=True, read_only=True)

    regions = [str(region) for region in wsts_config.get("regions", ["Worldwide"])]
    metrics: list[dict[str, Any]] = []
    metrics.extend(
        wsts_sheet_metrics(
            workbook["Monthly Data"],
            regions,
            label="WSTS 반도체 판매액",
            xlsx_url=str(xlsx_url),
            history_limit=int(config.get("dashboard", {}).get("history_points", 48)),
        )
    )
    if wsts_config.get("include_3mma", True) and "3MMA" in workbook.sheetnames:
        metrics.extend(
            wsts_sheet_metrics(
                workbook["3MMA"],
                regions,
                label="WSTS 반도체 판매액 3MMA",
                xlsx_url=str(xlsx_url),
                history_limit=int(config.get("dashboard", {}).get("history_points", 48)),
            )
        )
    return metrics


def wsts_sheet_metrics(
    sheet: Any, regions: list[str], label: str, xlsx_url: str, history_limit: int
) -> list[dict[str, Any]]:
    parsed = parse_wsts_sheet(sheet)
    metrics: list[dict[str, Any]] = []
    for region in regions:
        points = sorted(parsed.get(region, []), key=lambda point: point[0])
        name = f"{label} - {region}"
        if not points:
            metrics.append(
                make_metric(
                    industry="반도체",
                    name=name,
                    source="WSTS",
                    source_url=xlsx_url,
                    frequency="월간",
                    automation="무료로 안정적으로 자동화 가능",
                    status="error",
                    note="선택한 지역 데이터 없음",
                    group="판매액",
                    meaning="반도체 업황의 현재 수요 강도와 재고 순환을 확인하는 월간 지표입니다.",
                )
            )
            continue

        billion_points = [(observed_date, value / 1_000_000) for observed_date, value in points]
        latest_date, latest_value = billion_points[-1]
        previous_value = billion_points[-2][1] if len(billion_points) > 1 else None
        yoy_value = find_yoy_value(billion_points, latest_date)
        metrics.append(
            make_metric(
                industry="반도체",
                name=name,
                source="WSTS Historical Billings Report",
                source_url=xlsx_url,
                frequency="월간",
                automation="무료로 안정적으로 자동화 가능",
                status="ok",
                value=latest_value,
                unit="$B",
                observed_at=latest_date.isoformat(),
                previous_value=previous_value,
                yoy_value=yoy_value,
                history=billion_points[-history_limit:],
                group="판매액",
                meaning="반도체 업황의 현재 수요 강도와 재고 순환을 확인하는 월간 지표입니다.",
            )
        )
    return metrics


def collect_korea_export_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    export_config = config.get("korea_exports", {})
    if not export_config.get("enabled", True):
        return []

    items = export_config.get("items", [])
    if not items:
        return []

    endpoint = str(export_config["endpoint"])
    source_url = "https://www.data.go.kr/data/15101609/openapi.do"
    service_key = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()
    end_month = add_months(date(today.year, today.month, 1), -int(export_config.get("end_offset_months", 1)))
    start_month = add_months(end_month, -int(export_config.get("months_back", 15)) + 1)

    metrics: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or item.get("hs_code"))
        hs_code = str(item.get("hs_code", "")).strip()
        industry = str(item.get("industry") or infer_export_industry(hs_code))
        metric_name = f"한국 수출 {name}({hs_code})"

        if not service_key:
            metrics.append(
                make_metric(
                    industry=industry,
                    name=metric_name,
                    source="관세청 품목별 수출입실적 API",
                    source_url=source_url,
                    frequency="월간",
                    automation="무료로 안정적으로 자동화 가능",
                    status="needs_key",
                    note="GitHub Secrets에 DATA_GO_KR_SERVICE_KEY 등록 필요",
                    group=str(item.get("group") or "수출"),
                    meaning=str(item.get("meaning") or export_meaning(name)),
                )
            )
            continue

        try:
            records = fetch_itemtrade_records(
                session=session,
                endpoint=endpoint,
                service_key=service_key,
                hs_code=hs_code,
                start_month=start_month,
                end_month=end_month,
            )
            monthly = monthly_export_values(records)
            if not monthly:
                metrics.append(
                    make_metric(
                        industry=industry,
                        name=metric_name,
                        source="관세청 품목별 수출입실적 API",
                        source_url=source_url,
                        frequency="월간",
                        automation="무료로 안정적으로 자동화 가능",
                        status="error",
                        note=f"{month_key(start_month)}-{month_key(end_month)} 관측값 없음",
                        group=str(item.get("group") or "수출"),
                        meaning=str(item.get("meaning") or export_meaning(name)),
                    )
                )
                continue

            points = sorted((observed_month, value / 1_000_000_000) for observed_month, value in monthly.items())
            latest_month, latest_value = points[-1]
            previous_value = dict(points).get(add_months(latest_month, -1))
            yoy_value = dict(points).get(add_months(latest_month, -12))
            metrics.append(
                make_metric(
                    industry=industry,
                    name=metric_name,
                    source="관세청 품목별 수출입실적 API",
                    source_url=source_url,
                    frequency="월간",
                    automation="무료로 안정적으로 자동화 가능",
                    status="ok",
                    value=latest_value,
                    unit="$B",
                    observed_at=latest_month.isoformat(),
                    previous_value=previous_value,
                    yoy_value=yoy_value,
                    history=points,
                    group=str(item.get("group") or "수출"),
                    meaning=str(item.get("meaning") or export_meaning(name)),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one export item should not break the page.
            metrics.append(
                make_metric(
                    industry=industry,
                    name=metric_name,
                    source="관세청 품목별 수출입실적 API",
                    source_url=source_url,
                    frequency="월간",
                    automation="무료로 안정적으로 자동화 가능",
                    status="error",
                    note=str(exc),
                    group=str(item.get("group") or "수출"),
                    meaning=str(item.get("meaning") or export_meaning(name)),
                )
            )
    return metrics


def monthly_export_values(records: list[dict[str, str]]) -> dict[date, float]:
    monthly: dict[date, float] = defaultdict(float)
    for record in records:
        year_text = record.get("year", "").replace("-", ".").strip()
        try:
            year, month = year_text.split(".")[:2]
            observed_month = date(int(year), int(month), 1)
        except (ValueError, TypeError):
            continue

        export_value = to_float(record.get("expDlr"))
        if export_value is not None:
            monthly[observed_month] += export_value
    return dict(monthly)


def collect_reference_metrics(config: dict[str, Any]) -> list[dict[str, Any]]:
    reference_metrics = config.get("dashboard", {}).get("reference_metrics", [])
    metrics: list[dict[str, Any]] = []
    for item in reference_metrics:
        status = str(item.get("status") or "partial")
        metrics.append(
            make_metric(
                industry=str(item.get("industry") or "매크로"),
                name=str(item.get("name") or "미정 지표"),
                source=str(item.get("source") or ""),
                source_url=str(item.get("source_url") or ""),
                frequency=str(item.get("frequency") or ""),
                automation=str(item.get("automation") or status_to_automation(status)),
                status=status,
                note=str(item.get("note") or ""),
                group=str(item.get("group") or ""),
                meaning=str(item.get("meaning") or item.get("note") or ""),
            )
        )
    return metrics


def make_metric(
    *,
    industry: str,
    name: str,
    source: str,
    source_url: str,
    frequency: str,
    automation: str,
    status: str,
    value: float | None = None,
    unit: str = "",
    observed_at: str = "",
    previous_value: float | None = None,
    yoy_value: float | None = None,
    history: list[tuple[date, float]] | None = None,
    note: str = "",
    group: str = "",
    meaning: str = "",
) -> dict[str, Any]:
    change_abs = value - previous_value if value is not None and previous_value is not None else None
    change_pct = pct_change(value, previous_value) if value is not None else None
    yoy_pct = pct_change(value, yoy_value) if value is not None else None
    metric_id = hashlib.sha1(f"{industry}|{name}|{source}".encode("utf-8")).hexdigest()[:12]
    history_points = [
        {"date": observed_date.isoformat(), "value": observed_value}
        for observed_date, observed_value in (history or [])
    ]
    resolved_group = group or infer_metric_group(industry, name)
    resolved_meaning = meaning or infer_metric_meaning(industry, name)

    return {
        "id": metric_id,
        "industry": industry,
        "group": resolved_group,
        "name": name,
        "meaning": resolved_meaning,
        "source": source,
        "source_url": source_url,
        "frequency": frequency,
        "automation": automation,
        "status": status,
        "status_label": status_label(status),
        "value": value,
        "unit": unit,
        "display_value": format_value(value, unit) if value is not None else "대기",
        "observed_at": observed_at,
        "observed_label": compact_date_label(observed_at),
        "previous_value": previous_value,
        "change_abs": change_abs,
        "change_pct": change_pct,
        "change_abs_label": format_abs_change(change_abs, unit),
        "change_pct_label": fmt_pct(change_pct),
        "yoy_pct": yoy_pct,
        "yoy_pct_label": fmt_pct(yoy_pct),
        "history": history_points,
        "period_label": period_label(history_points, observed_at),
        "note": note,
    }


def configured_industries(config: dict[str, Any], metrics: list[dict[str, Any]]) -> list[str]:
    configured = list(config.get("dashboard", {}).get("industries") or DEFAULT_INDUSTRIES)
    seen = set(configured)
    for metric in metrics:
        industry = str(metric.get("industry") or "매크로")
        if industry not in seen:
            configured.append(industry)
            seen.add(industry)
    return configured


def visible_dashboard_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for metric in metrics:
        value = metric.get("value")
        if metric.get("status") == "ok" and isinstance(value, (int, float)):
            visible.append(
                {
                    "id": metric["id"],
                    "industry": clean_display_text(metric["industry"]),
                    "group": clean_display_text(metric["group"]),
                    "name": clean_display_text(metric["name"]),
                    "meaning": clean_display_text(metric["meaning"]),
                    "value": metric["value"],
                    "display_value": metric["display_value"],
                    "observed_label": metric["observed_label"],
                    "change_abs": metric["change_abs"],
                    "change_pct": metric["change_pct"],
                    "change_abs_label": metric["change_abs_label"],
                    "change_pct_label": metric["change_pct_label"],
                    "yoy_pct": metric["yoy_pct"],
                    "yoy_pct_label": metric["yoy_pct_label"],
                    "history": metric["history"],
                    "period_label": metric["period_label"],
                }
            )
    return visible


def clean_display_text(value: object) -> str:
    text = str(value or "")
    replacements = {
        "자동화 장비": "산업 장비",
        "자동화 설비": "설비투자",
        "자동화와": "설비투자와",
        "자동화": "설비투자",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def infer_export_industry(hs_code: str) -> str:
    if hs_code.startswith(("8541", "8542")):
        return "반도체"
    if hs_code.startswith("8703"):
        return "자동차/전기차"
    if hs_code.startswith("8901"):
        return "조선"
    return "매크로"


def infer_metric_group(industry: str, name: str) -> str:
    if "수출" in name:
        return "수출"
    if "WSTS" in name or "반도체 판매" in name:
        return "판매액"
    if industry == "방산":
        if "수주잔고" in name:
            return "수주잔고"
        if "신규주문" in name:
            return "신규주문"
        return "방산 수요"
    if industry == "스테이블코인":
        return "유통량"
    if industry == "전력":
        if "PPI" in name:
            return "전력 가격"
        return "전력 수요/생산"
    if industry == "로봇":
        if "PPI" in name:
            return "산업 장비 가격"
        return "설비투자 proxy"
    if industry == "우주":
        if "PPI" in name:
            return "항공우주 가격"
        return "우주/방산 생산"
    if industry == "바이오":
        return "바이오 가격"
    if industry == "배터리":
        return "배터리 가격"
    if industry == "은행/금융":
        if "금리차" in name or "스프레드" in name:
            return "스프레드"
        if "연체" in name or "대출" in name:
            return "은행 건전성"
        return "금리"
    if industry == "건설/부동산":
        if "모기지" in name:
            return "금융비용"
        return "주택 경기"
    if industry == "철강/소재":
        return "원자재 가격"
    if industry == "화학/정유":
        if "유가" in name:
            return "에너지 가격"
        return "화학 스프레드 proxy"
    if industry == "자동차/전기차":
        return "판매/수요"
    if industry == "매크로":
        if "환율" in name:
            return "환율"
        if "VIX" in name:
            return "리스크"
    return "핵심 지표"


def infer_metric_meaning(industry: str, name: str) -> str:
    if "WSTS" in name:
        return "글로벌 반도체 매출 흐름으로 업황의 수요 강도와 재고 순환을 확인합니다."
    if "반도체 PPI" in name:
        return "반도체 가격 압력과 공급자 가격 흐름을 보는 가격 proxy입니다."
    if "국채금리" in name:
        return "할인율과 금융주 마진 기대를 좌우하는 시장 금리입니다."
    if "금리차" in name:
        return "경기 기대와 은행 순이자마진 환경을 함께 보여주는 지표입니다."
    if "회사채" in name:
        return "신용 위험과 자금 조달 여건이 얼마나 빡빡한지 확인합니다."
    if "연체" in name:
        return "대출 자산의 질과 금융 시스템 부담을 점검합니다."
    if "총대출" in name:
        return "은행권 신용 공급과 실물 경기의 자금 수요를 봅니다."
    if "주택착공" in name:
        return "건설 경기의 실제 착공 모멘텀과 주택 공급 흐름을 보여줍니다."
    if "건축허가" in name:
        return "향후 착공과 건설 활동을 선행해서 보여주는 지표입니다."
    if "모기지" in name:
        return "주택 구매 부담과 부동산 수요에 직접 영향을 주는 비용입니다."
    if "주택가격" in name:
        return "가계 자산 효과와 부동산 경기 방향성을 확인합니다."
    if "유가" in name:
        return "정유, 화학 원가와 인플레이션 압력을 동시에 움직이는 원재료 가격입니다."
    if "화학 PPI" in name:
        return "화학 제품 가격 사이클과 마진 방향을 간접적으로 봅니다."
    if "철광석" in name:
        return "철강 원가와 중국 투자 수요를 반영하는 핵심 원재료입니다."
    if "구리" in name:
        return "전기화와 제조업 경기를 민감하게 반영하는 경기 민감 금속입니다."
    if "알루미늄" in name:
        return "경량 소재와 제조업 수요, 전력비 영향을 함께 받는 소재 가격입니다."
    if "자동차 판매" in name:
        return "완성차 수요와 소비 경기 흐름을 확인하는 판매 지표입니다."
    if "방산" in name:
        return "방산 발주와 생산 사이클을 통해 방산 업체의 수요 환경을 확인합니다."
    if "스테이블코인" in name or "USDT" in name or "USDC" in name:
        return stablecoin_meaning()
    if "전력" in name or "유틸리티" in name:
        return "전력 생산과 가격 흐름으로 전력 인프라와 전력 수요 사이클을 확인합니다."
    if "산업용 기계" in name or "산업 제어" in name:
        return "설비투자와 로봇 부품 수요를 가늠하는 proxy 지표입니다."
    if "우주" in name or "항공우주" in name:
        return "항공우주 생산과 가격 흐름으로 우주 밸류체인의 수요 환경을 확인합니다."
    if "생물학적" in name or "체외진단" in name:
        return "바이오 의약품과 진단 제품의 가격 사이클을 확인하는 지표입니다."
    if "배터리" in name:
        return "배터리 제품 가격 흐름으로 셀/소재 밸류체인의 업황을 점검합니다."
    if "환율" in name:
        return "수출주 원화 환산 매출과 외국인 수급에 영향을 주는 매크로 변수입니다."
    if "VIX" in name:
        return "시장 위험 회피 심리와 변동성 확대 여부를 봅니다."
    if "수출" in name:
        return "해당 품목의 대외 수요와 가격/물량 사이클을 확인합니다."
    if industry:
        return f"{industry} 업황을 해석하기 위한 보조 지표입니다."
    return "투자 판단에 필요한 업황 변화를 확인합니다."


def export_meaning(name: str) -> str:
    return f"{name} 수출은 해당 품목의 대외 수요와 가격/물량 사이클을 확인하는 지표입니다."


def period_label(history_points: list[dict[str, Any]], observed_at: str) -> str:
    if history_points:
        start = compact_date_label(str(history_points[0]["date"]))
        end = compact_date_label(str(history_points[-1]["date"]))
        return start if start == end else f"{start} - {end}"
    return compact_date_label(observed_at)


def compact_date_label(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return value[:10]
    if parsed.day == 1:
        return f"{parsed.year}.{parsed.month:02d}"
    return f"{parsed.year}.{parsed.month:02d}.{parsed.day:02d}"


def find_yoy_value(points: list[tuple[date, float]], latest_date: date) -> float | None:
    exact_month = next(
        (
            value
            for observed_date, value in reversed(points)
            if observed_date.year == latest_date.year - 1 and observed_date.month == latest_date.month
        ),
        None,
    )
    if exact_month is not None:
        return exact_month

    threshold = latest_date - timedelta(days=365)
    older_points = [(observed_date, value) for observed_date, value in points if observed_date <= threshold]
    return older_points[-1][1] if older_points else None


def format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "대기"
    if unit == "$B":
        return f"${fmt_number(value)}B"
    if unit == "%":
        return f"{fmt_number(value)}%"
    if unit == "원":
        return f"{fmt_number(value)}원"
    if unit:
        return f"{fmt_number(value)} {unit}"
    return fmt_number(value)


def format_abs_change(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "$B":
        return f"{fmt_signed(value)}B"
    if unit == "%":
        return f"{fmt_signed(value)}%p"
    if unit == "원":
        return f"{fmt_signed(value)}원"
    if unit:
        return f"{fmt_signed(value)} {unit}"
    return fmt_signed(value)


def status_label(status: str) -> str:
    return {
        "ok": "자동 수집",
        "needs_key": "키 필요",
        "partial": "부분 자동화",
        "manual": "수작업",
        "error": "오류",
    }.get(status, status)


def status_to_automation(status: str) -> str:
    if status == "manual":
        return "수작업 입력 필요"
    if status == "ok":
        return "무료로 안정적으로 자동화 가능"
    return "부분 자동화 가능"


def render_dashboard_html(payload: dict[str, Any]) -> str:
    json_text = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return MODERN_HTML_TEMPLATE.replace("__DASHBOARD_JSON__", json_text)


MODERN_HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css">
  <title>산업별 지표 대시보드</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #ffffff;
      --surface: #ffffff;
      --sidebar: #f7f7f7;
      --panel: #ffffff;
      --text: #171717;
      --muted: #6d6d6d;
      --line: #e6e6e6;
      --menu: #f0f0f0;
      --menu-active: #e6e6e6;
      --chart-up: #d83b32;
      --chart-down: #2f6fd6;
      --shadow: 0 10px 26px rgba(0, 0, 0, 0.06);
    }

    body.theme-dark {
      color-scheme: dark;
      --bg: #111111;
      --surface: #151515;
      --sidebar: #181818;
      --panel: #1d1d1d;
      --text: #f2f2f2;
      --muted: #a7a7a7;
      --line: #303030;
      --menu: #242424;
      --menu-active: #303030;
      --shadow: none;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-width: 320px;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, Pretendard, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }

    button {
      font: inherit;
      color: inherit;
    }

    .shell {
      display: grid;
      grid-template-columns: 232px minmax(0, 1fr);
      gap: 26px;
      width: min(1540px, 100%);
      min-height: 100vh;
      margin: 0 auto;
      padding: 22px 24px 42px;
    }

    .sidebar {
      position: sticky;
      top: 22px;
      align-self: start;
      min-width: 0;
      min-height: calc(100vh - 44px);
      padding: 18px 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--sidebar);
    }

    .sidebar-title {
      margin: 0 8px 14px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
      text-transform: uppercase;
    }

    .side-menu {
      display: grid;
      gap: 7px;
      min-width: 0;
      max-width: 100%;
    }

    .side-menu button {
      width: 100%;
      min-height: 38px;
      border: 0;
      border-radius: 8px;
      background: transparent;
      padding: 0 12px;
      text-align: left;
      font-size: 14px;
      font-weight: 720;
      cursor: pointer;
    }

    .side-menu button:hover {
      background: var(--menu);
    }

    .side-menu button[aria-pressed="true"] {
      background: var(--menu-active);
    }

    .content {
      min-width: 0;
      display: grid;
      gap: 20px;
      align-content: start;
    }

    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      min-height: 46px;
    }

    h1 {
      margin: 0;
      font-size: clamp(26px, 3vw, 40px);
      line-height: 1.05;
      font-weight: 810;
    }

    .theme-toggle {
      width: 44px;
      height: 44px;
      border: 0;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: var(--menu);
      color: var(--text);
      cursor: pointer;
      font-size: 17px;
    }

    .theme-toggle:hover {
      background: var(--menu-active);
    }

    .industry-stack {
      display: grid;
      gap: 18px;
      min-width: 0;
    }

    .industry {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .industry-head {
      display: grid;
      grid-template-columns: 78px minmax(0, 1fr);
      gap: 16px;
      align-items: center;
      padding: 18px 20px;
      border-bottom: 1px solid var(--line);
      background: var(--surface);
    }

    .industry-icon-wrap {
      width: 78px;
      height: 78px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: var(--menu);
    }

    .industry-icon {
      width: 64px;
      height: 64px;
      object-fit: contain;
      display: block;
    }

    .industry h2 {
      margin: 0;
      font-size: 23px;
      line-height: 1.15;
      font-weight: 800;
    }

    .group {
      padding: 18px 20px 20px;
      border-bottom: 1px solid var(--line);
    }

    .group:last-child { border-bottom: 0; }

    .group-title {
      margin-bottom: 12px;
      color: var(--text);
      font-size: 14px;
      font-weight: 800;
    }

    .metric-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .metric {
      min-height: 348px;
      display: grid;
      grid-template-rows: auto auto 158px;
      gap: 13px;
      padding: 15px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow: hidden;
    }

    .metric h3 {
      margin: 0;
      font-size: 16px;
      line-height: 1.32;
      font-weight: 790;
      overflow-wrap: anywhere;
    }

    .meaning {
      margin: 7px 0 0;
      min-height: 38px;
      color: var(--muted);
      font-size: 12.5px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }

    .metric-main {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: end;
    }

    .value {
      font-size: 31px;
      line-height: 1;
      font-weight: 820;
      overflow-wrap: anywhere;
    }

    .deltas {
      display: grid;
      gap: 5px;
      min-width: 92px;
      color: var(--muted);
      font-size: 12px;
      text-align: right;
    }

    .deltas strong {
      display: inline-block;
      min-width: 54px;
      color: var(--text);
      font-size: 13px;
    }

    .positive { color: var(--chart-up) !important; }
    .negative { color: var(--chart-down) !important; }

    .chart {
      width: 100%;
      height: 158px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      overflow: visible;
    }

    .chart text {
      fill: var(--muted);
      font-size: 10.5px;
      font-weight: 650;
    }

    .axis-line {
      stroke: var(--line);
      stroke-width: 1;
    }

    .guide {
      stroke: var(--line);
      stroke-width: 1;
      stroke-dasharray: 4 4;
    }

    .trend-line {
      fill: none;
      stroke-width: 3;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    .trend-line.up { stroke: var(--chart-up); }
    .trend-line.down { stroke: var(--chart-down); }

    .current-dot.up { fill: var(--chart-up); }
    .current-dot.down { fill: var(--chart-down); }

    .empty {
      display: none;
      margin: 28px 0;
      padding: 26px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
      text-align: center;
    }

    @media (max-width: 1180px) {
      .shell {
        grid-template-columns: 190px minmax(0, 1fr);
        gap: 18px;
        padding-inline: 18px;
      }

      .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }

    @media (max-width: 760px) {
      .shell {
        grid-template-columns: 1fr;
        gap: 14px;
        padding: 14px 10px 30px;
      }

      .sidebar {
        position: static;
        width: 100%;
        max-width: 100%;
        min-height: 0;
        padding: 12px;
        overflow: hidden;
      }

      .side-menu {
        display: flex;
        gap: 8px;
        max-width: 100%;
        overflow-x: auto;
        padding-bottom: 2px;
      }

      .side-menu button {
        width: auto;
        white-space: nowrap;
      }

      .topbar {
        align-items: flex-start;
      }

      .industry-head {
        grid-template-columns: 64px minmax(0, 1fr);
        gap: 12px;
        padding: 15px;
      }

      .industry-icon-wrap {
        width: 64px;
        height: 64px;
      }

      .industry-icon {
        width: 54px;
        height: 54px;
      }

      .group { padding: 15px; }
      .metric-grid { grid-template-columns: 1fr; }
      .metric-main { grid-template-columns: 1fr; }
      .deltas {
        grid-template-columns: repeat(3, minmax(0, 1fr));
        text-align: left;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <aside class="sidebar">
      <div class="sidebar-title">산업</div>
      <nav class="side-menu" id="industryFilters" aria-label="산업 필터"></nav>
    </aside>
    <section class="content">
      <header class="topbar">
        <h1>산업별 지표 대시보드</h1>
        <button class="theme-toggle" id="themeToggle" type="button" aria-label="다크모드 전환" title="다크모드 전환">
          <i class="fa-solid fa-moon" aria-hidden="true"></i>
        </button>
      </header>
      <section class="industry-stack" id="industryStack"></section>
      <div class="empty" id="empty">표시할 지표가 없습니다.</div>
    </section>
  </main>

  <script>
    const DASHBOARD_DATA = __DASHBOARD_JSON__;
    const state = { industry: "전체" };
    const groupOrder = [
      "판매액", "시장 매출", "가격/수요", "투자/장비", "수출",
      "판매/수요", "판매량", "배터리 원재료",
      "운임/해운", "선가/발주",
      "원자재 가격", "중국 경기",
      "에너지 가격", "원유/원료", "화학 스프레드 proxy", "스프레드/마진",
      "금리", "스프레드", "금리/스프레드", "은행 건전성", "대출/건전성",
      "주택 경기", "건설 선행", "금융비용", "주택 시장",
      "환율", "리스크", "시장 환경", "핵심 지표"
    ];

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[char]));
    }

    function directionClass(value) {
      if (typeof value !== "number" || !Number.isFinite(value) || value === 0) return "";
      return value > 0 ? "positive" : "negative";
    }

    function groupRank(group) {
      const index = groupOrder.indexOf(group);
      return index === -1 ? 999 : index;
    }

    function filteredMetrics() {
      return DASHBOARD_DATA.metrics
        .filter((metric) => state.industry === "전체" || metric.industry === state.industry);
    }

    function renderFilters() {
      const industries = ["전체", ...DASHBOARD_DATA.industries.filter((industry) =>
        DASHBOARD_DATA.metrics.some((metric) => metric.industry === industry)
      )];
      document.getElementById("industryFilters").innerHTML = industries.map((industry) => `
        <button type="button" data-industry="${escapeHtml(industry)}" aria-pressed="${state.industry === industry}">
          ${escapeHtml(industry)}
        </button>
      `).join("");
      document.querySelectorAll("[data-industry]").forEach((button) => {
        button.addEventListener("click", () => {
          state.industry = button.dataset.industry;
          render();
        });
      });
    }

    function formatAxisValue(value) {
      const abs = Math.abs(value);
      if (abs >= 1000) return `${(value / 1000).toFixed(1)}k`;
      if (abs >= 100) return value.toFixed(0);
      if (abs >= 10) return value.toFixed(1);
      return value.toFixed(2);
    }

    function yearLabel(dateText) {
      const year = Number(String(dateText).slice(2, 4));
      return Number.isFinite(year) ? `${String(year).padStart(2, "0")}y` : "";
    }

    function chartTicks(history, left, right) {
      const seen = new Set();
      const ticks = [];
      history.forEach((point, index) => {
        const year = String(point.date).slice(0, 4);
        if (seen.has(year)) return;
        seen.add(year);
        const x = left + (index / Math.max(history.length - 1, 1)) * (right - left);
        ticks.push({ label: yearLabel(point.date), x });
      });
      if (ticks.length === 1 && history.length > 1) {
        ticks.push({ label: yearLabel(history[history.length - 1].date), x: right });
      }
      return ticks.filter((tick, index) => index === 0 || tick.label !== ticks[index - 1].label);
    }

    function chart(history) {
      if (!history || history.length < 2) {
        return `<svg class="chart" viewBox="0 0 360 158" role="img" aria-label="trend unavailable">
          <line x1="62" y1="72" x2="344" y2="72" class="guide"></line>
        </svg>`;
      }
      const values = history.map((point) => point.value).filter((value) => typeof value === "number" && Number.isFinite(value));
      const min = Math.min(...values);
      const max = Math.max(...values);
      const latest = history[history.length - 1].value;
      const first = history[0].value;
      const span = max - min || 1;
      const left = 62;
      const right = 344;
      const top = 16;
      const bottom = 116;
      const yFor = (value) => bottom - ((value - min) / span) * (bottom - top);
      const points = history.map((point, index) => {
        const x = left + (index / Math.max(history.length - 1, 1)) * (right - left);
        const y = yFor(point.value);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      const trend = latest >= first ? "up" : "down";
      const levels = [
        { label: "최고", value: max },
        { label: "현재", value: latest },
        { label: "최저", value: min }
      ];
      const yGuides = levels.map((level) => {
        const y = yFor(level.value);
        return `<g>
          <text x="8" y="${(y + 3).toFixed(1)}">${level.label} ${formatAxisValue(level.value)}</text>
          <line x1="${left}" y1="${y.toFixed(1)}" x2="${right}" y2="${y.toFixed(1)}" class="guide"></line>
        </g>`;
      }).join("");
      const xGuides = chartTicks(history, left, right).map((tick) => `
        <text x="${tick.x.toFixed(1)}" y="146" text-anchor="middle">${tick.label}</text>
      `).join("");
      const latestX = right;
      const latestY = yFor(latest);
      return `<svg class="chart" viewBox="0 0 360 158" role="img" aria-label="trend">
        ${yGuides}
        <line x1="${left}" y1="126" x2="${right}" y2="126" class="axis-line"></line>
        ${xGuides}
        <polyline points="${points}" class="trend-line ${trend}"></polyline>
        <circle cx="${latestX}" cy="${latestY.toFixed(1)}" r="4" class="current-dot ${trend}"></circle>
      </svg>`;
    }

    function metricCard(metric) {
      return `<article class="metric">
        <div>
          <h3>${escapeHtml(metric.name)}</h3>
          <p class="meaning">${escapeHtml(metric.meaning)}</p>
        </div>
        <div class="metric-main">
          <div class="value">${escapeHtml(metric.display_value)}</div>
          <div class="deltas">
            <span>전기 <strong class="${directionClass(metric.change_abs)}">${escapeHtml(metric.change_abs_label)}</strong></span>
            <span>전기% <strong class="${directionClass(metric.change_pct)}">${escapeHtml(metric.change_pct_label)}</strong></span>
            <span>YoY <strong class="${directionClass(metric.yoy_pct)}">${escapeHtml(metric.yoy_pct_label)}</strong></span>
          </div>
        </div>
        ${chart(metric.history)}
      </article>`;
    }

    function renderIndustry(industry, metrics) {
      const groups = Map.groupBy
        ? Map.groupBy(metrics, (metric) => metric.group || "핵심 지표")
        : metrics.reduce((map, metric) => {
            const key = metric.group || "핵심 지표";
            map.set(key, [...(map.get(key) || []), metric]);
            return map;
          }, new Map());
      const icon = DASHBOARD_DATA.industry_icons?.[industry] || "";
      const groupHtml = [...groups.entries()]
        .sort(([a], [b]) => groupRank(a) - groupRank(b) || String(a).localeCompare(String(b), "ko"))
        .map(([group, items]) => `
          <section class="group">
            <div class="group-title">${escapeHtml(group)}</div>
            <div class="metric-grid">${items.map(metricCard).join("")}</div>
          </section>
        `).join("");

      return `<article class="industry">
        <div class="industry-head">
          <div class="industry-icon-wrap">${icon ? `<img class="industry-icon" src="${escapeHtml(icon)}" alt="">` : ""}</div>
          <div>
            <h2>${escapeHtml(industry)}</h2>
          </div>
        </div>
        <div class="group-stack">${groupHtml}</div>
      </article>`;
    }

    function renderIndustries() {
      const metrics = filteredMetrics();
      const stack = document.getElementById("industryStack");
      document.getElementById("empty").style.display = metrics.length ? "none" : "block";
      const byIndustry = metrics.reduce((map, metric) => {
        map.set(metric.industry, [...(map.get(metric.industry) || []), metric]);
        return map;
      }, new Map());
      stack.innerHTML = DASHBOARD_DATA.industries
        .filter((industry) => byIndustry.has(industry))
        .map((industry) => renderIndustry(industry, byIndustry.get(industry)))
        .join("");
    }

    function applyTheme(theme) {
      const isDark = theme === "dark";
      document.body.classList.toggle("theme-dark", isDark);
      const icon = document.querySelector("#themeToggle i");
      icon.className = isDark ? "fa-solid fa-sun" : "fa-solid fa-moon";
      localStorage.setItem("dashboard-theme", isDark ? "dark" : "light");
    }

    function initTheme() {
      const saved = localStorage.getItem("dashboard-theme");
      const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      applyTheme(saved || (prefersDark ? "dark" : "light"));
      document.getElementById("themeToggle").addEventListener("click", () => {
        applyTheme(document.body.classList.contains("theme-dark") ? "light" : "dark");
      });
    }

    function render() {
      renderFilters();
      renderIndustries();
    }

    initTheme();
    render();
  </script>
</body>
</html>
"""


GROUPED_HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>산업별 핵심 지표 대시보드</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f3ee;
      --paper: #fffdfa;
      --panel: #ffffff;
      --text: #202124;
      --muted: #6c6a63;
      --soft: #f0eee7;
      --line: #dedbd1;
      --accent: #2f6f73;
      --accent-soft: #e5f0ee;
      --good: #07805e;
      --bad: #c24135;
      --gold: #b48627;
      --shadow: 0 14px 30px rgba(39, 38, 34, 0.07);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-width: 320px;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, Pretendard, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }

    .shell {
      width: min(1480px, calc(100% - 32px));
      margin: 0 auto;
      padding: 26px 0 42px;
    }

    header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 18px;
      align-items: end;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }

    h1 {
      margin: 0;
      font-size: clamp(25px, 3vw, 38px);
      line-height: 1.08;
      font-weight: 790;
    }

    .subtitle {
      margin-top: 8px;
      color: var(--muted);
      font-size: 14px;
    }

    .updated {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
      text-align: right;
      white-space: nowrap;
    }

    .toolbar {
      position: sticky;
      top: 0;
      z-index: 5;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 16px 0;
      background: rgba(245, 243, 238, 0.92);
      backdrop-filter: blur(12px);
    }

    button {
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--paper);
      color: var(--text);
      padding: 0 13px;
      font: inherit;
      font-size: 13px;
      font-weight: 720;
      cursor: pointer;
    }

    button[aria-pressed="true"] {
      border-color: var(--accent);
      background: var(--accent-soft);
      color: #174b50;
    }

    .industry-stack {
      display: grid;
      gap: 18px;
    }

    .industry {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--paper);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .industry-head {
      display: grid;
      grid-template-columns: 92px minmax(0, 1fr);
      gap: 18px;
      align-items: center;
      padding: 18px 20px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, #fffefa, #f9f7f0);
    }

    .industry-icon-wrap {
      width: 92px;
      height: 92px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: #f4f1e8;
    }

    .industry-icon {
      width: 76px;
      height: 76px;
      object-fit: contain;
      display: block;
    }

    .industry h2 {
      margin: 0;
      font-size: 25px;
      line-height: 1.15;
      font-weight: 790;
    }

    .industry-summary {
      margin: 7px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }

    .group-stack {
      display: grid;
      gap: 0;
    }

    .group {
      padding: 18px 20px 20px;
      border-bottom: 1px solid var(--line);
    }

    .group:last-child { border-bottom: 0; }

    .group-title {
      display: flex;
      align-items: center;
      gap: 9px;
      margin-bottom: 12px;
      font-size: 14px;
      font-weight: 800;
      color: #3c3b36;
    }

    .group-title::before {
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--gold);
      flex: 0 0 auto;
    }

    .metric-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .metric {
      min-height: 268px;
      display: grid;
      grid-template-rows: auto auto 70px auto;
      gap: 12px;
      padding: 15px;
      border: 1px solid #ebe7dc;
      border-radius: 8px;
      background: var(--panel);
    }

    .metric h3 {
      margin: 0;
      font-size: 16px;
      line-height: 1.32;
      font-weight: 790;
      overflow-wrap: anywhere;
    }

    .meaning {
      margin: 7px 0 0;
      min-height: 38px;
      color: var(--muted);
      font-size: 12.5px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }

    .metric-main {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: end;
    }

    .value {
      font-size: 31px;
      line-height: 1;
      font-weight: 820;
      overflow-wrap: anywhere;
    }

    .deltas {
      display: grid;
      gap: 5px;
      min-width: 92px;
      color: var(--muted);
      font-size: 12px;
      text-align: right;
    }

    .deltas strong {
      display: inline-block;
      min-width: 54px;
      color: var(--text);
      font-size: 13px;
    }

    .positive { color: var(--good) !important; }
    .negative { color: var(--bad) !important; }

    .spark {
      width: 100%;
      height: 70px;
      border: 1px solid #efebe1;
      border-radius: 8px;
      background: linear-gradient(180deg, #fffdfa, #f9f7f1);
    }

    .period {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding-top: 9px;
      border-top: 1px solid #efebe1;
      color: var(--muted);
      font-size: 12px;
    }

    .period strong {
      color: #3f403b;
      font-weight: 760;
      white-space: nowrap;
    }

    .empty {
      display: none;
      margin: 28px 0;
      padding: 26px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
      text-align: center;
    }

    @media (max-width: 1120px) {
      .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }

    @media (max-width: 720px) {
      .shell {
        width: min(100% - 20px, 680px);
        padding-top: 16px;
      }

      header {
        grid-template-columns: 1fr;
        align-items: start;
      }

      .updated { text-align: left; white-space: normal; }
      .toolbar { position: static; }
      button { flex: 1 1 auto; }
      .industry-head {
        grid-template-columns: 70px minmax(0, 1fr);
        gap: 12px;
        padding: 15px;
      }
      .industry-icon-wrap {
        width: 70px;
        height: 70px;
      }
      .industry-icon {
        width: 60px;
        height: 60px;
      }
      .industry h2 { font-size: 21px; }
      .group { padding: 15px; }
      .metric-grid { grid-template-columns: 1fr; }
      .metric-main { grid-template-columns: 1fr; }
      .deltas {
        grid-template-columns: repeat(3, minmax(0, 1fr));
        text-align: left;
      }
      .value { font-size: 29px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1 id="title">산업별 핵심 지표 대시보드</h1>
        <div class="subtitle">비슷한 지표를 그룹으로 묶어 업황 변화를 빠르게 봅니다.</div>
      </div>
      <div class="updated" id="updated"></div>
    </header>
    <nav class="toolbar" id="industryFilters" aria-label="산업 필터"></nav>
    <section class="industry-stack" id="industryStack"></section>
    <div class="empty" id="empty">표시할 지표가 없습니다.</div>
  </main>

  <script>
    const DASHBOARD_DATA = __DASHBOARD_JSON__;
    const state = { industry: "전체" };
    const groupOrder = [
      "판매액", "시장 매출", "가격/수요", "투자/장비", "수출",
      "판매/수요", "판매량", "배터리 원재료",
      "운임/해운", "선가/발주",
      "원자재 가격", "중국 경기",
      "에너지 가격", "원유/원료", "화학 스프레드 proxy", "스프레드/마진",
      "금리", "스프레드", "금리/스프레드", "은행 건전성", "대출/건전성",
      "주택 경기", "건설 선행", "금융비용", "주택 시장",
      "환율", "리스크", "시장 환경", "핵심 지표"
    ];

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[char]));
    }

    function directionClass(value) {
      if (typeof value !== "number" || !Number.isFinite(value) || value === 0) return "";
      return value > 0 ? "positive" : "negative";
    }

    function groupRank(group) {
      const index = groupOrder.indexOf(group);
      return index === -1 ? 999 : index;
    }

    function filteredMetrics() {
      return DASHBOARD_DATA.metrics
        .filter((metric) => state.industry === "전체" || metric.industry === state.industry);
    }

    function renderFilters() {
      const industries = ["전체", ...DASHBOARD_DATA.industries.filter((industry) =>
        DASHBOARD_DATA.metrics.some((metric) => metric.industry === industry)
      )];
      document.getElementById("industryFilters").innerHTML = industries.map((industry) => `
        <button type="button" data-industry="${escapeHtml(industry)}" aria-pressed="${state.industry === industry}">
          ${escapeHtml(industry)}
        </button>
      `).join("");
      document.querySelectorAll("[data-industry]").forEach((button) => {
        button.addEventListener("click", () => {
          state.industry = button.dataset.industry;
          render();
        });
      });
    }

    function sparkline(history) {
      if (!history || history.length < 2) {
        return `<svg class="spark" viewBox="0 0 300 70" role="img" aria-label="trend unavailable">
          <line x1="16" y1="36" x2="284" y2="36" stroke="#ddd8cc" stroke-width="2" stroke-dasharray="5 5"></line>
        </svg>`;
      }
      const values = history.map((point) => point.value).filter((value) => typeof value === "number" && Number.isFinite(value));
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = max - min || 1;
      const width = 300;
      const height = 70;
      const padX = 12;
      const padY = 10;
      const points = history.map((point, index) => {
        const x = padX + (index / Math.max(history.length - 1, 1)) * (width - padX * 2);
        const y = height - padY - ((point.value - min) / span) * (height - padY * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      return `<svg class="spark" viewBox="0 0 300 70" role="img" aria-label="trend">
        <line x1="12" y1="60" x2="288" y2="60" stroke="#ebe5d8" stroke-width="1"></line>
        <polyline points="${points}" fill="none" stroke="#2f6f73" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
      </svg>`;
    }

    function metricCard(metric) {
      return `<article class="metric">
        <div>
          <h3>${escapeHtml(metric.name)}</h3>
          <p class="meaning">${escapeHtml(metric.meaning)}</p>
        </div>
        <div class="metric-main">
          <div class="value">${escapeHtml(metric.display_value)}</div>
          <div class="deltas">
            <span>전기 <strong class="${directionClass(metric.change_abs)}">${escapeHtml(metric.change_abs_label)}</strong></span>
            <span>전기% <strong class="${directionClass(metric.change_pct)}">${escapeHtml(metric.change_pct_label)}</strong></span>
            <span>YoY <strong class="${directionClass(metric.yoy_pct)}">${escapeHtml(metric.yoy_pct_label)}</strong></span>
          </div>
        </div>
        ${sparkline(metric.history)}
        <div class="period"><span>기간</span><strong>${escapeHtml(metric.period_label || metric.observed_label || "")}</strong></div>
      </article>`;
    }

    function renderIndustry(industry, metrics) {
      const groups = Map.groupBy
        ? Map.groupBy(metrics, (metric) => metric.group || "핵심 지표")
        : metrics.reduce((map, metric) => {
            const key = metric.group || "핵심 지표";
            map.set(key, [...(map.get(key) || []), metric]);
            return map;
          }, new Map());
      const icon = DASHBOARD_DATA.industry_icons?.[industry] || "";
      const summary = DASHBOARD_DATA.industry_summaries?.[industry] || "";
      const groupHtml = [...groups.entries()]
        .sort(([a], [b]) => groupRank(a) - groupRank(b) || String(a).localeCompare(String(b), "ko"))
        .map(([group, items]) => `
          <section class="group">
            <div class="group-title">${escapeHtml(group)}</div>
            <div class="metric-grid">${items.map(metricCard).join("")}</div>
          </section>
        `).join("");

      return `<article class="industry">
        <div class="industry-head">
          <div class="industry-icon-wrap">${icon ? `<img class="industry-icon" src="${escapeHtml(icon)}" alt="">` : ""}</div>
          <div>
            <h2>${escapeHtml(industry)}</h2>
            <p class="industry-summary">${escapeHtml(summary)}</p>
          </div>
        </div>
        <div class="group-stack">${groupHtml}</div>
      </article>`;
    }

    function renderIndustries() {
      const metrics = filteredMetrics();
      const stack = document.getElementById("industryStack");
      document.getElementById("empty").style.display = metrics.length ? "none" : "block";
      const byIndustry = metrics.reduce((map, metric) => {
        map.set(metric.industry, [...(map.get(metric.industry) || []), metric]);
        return map;
      }, new Map());
      stack.innerHTML = DASHBOARD_DATA.industries
        .filter((industry) => byIndustry.has(industry))
        .map((industry) => renderIndustry(industry, byIndustry.get(industry)))
        .join("");
    }

    function render() {
      document.getElementById("title").textContent = DASHBOARD_DATA.title;
      document.getElementById("updated").innerHTML = `업데이트 ${escapeHtml(DASHBOARD_DATA.generated_label)}<br>${escapeHtml(DASHBOARD_DATA.timezone)}`;
      renderFilters();
      renderIndustries();
    }

    render();
  </script>
</body>
</html>
"""


HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>산업별 핵심 지표 대시보드</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f6f2;
      --panel: #ffffff;
      --panel-soft: #fbfbf8;
      --text: #202124;
      --muted: #63645f;
      --line: #d8d8cf;
      --accent: #28666e;
      --accent-2: #8a5a44;
      --good: #087f5b;
      --bad: #c24135;
      --warn: #a66a00;
      --manual: #6f5cc2;
      --shadow: 0 10px 22px rgba(32, 33, 36, 0.06);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-width: 320px;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, Pretendard, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }

    a { color: inherit; }

    .shell {
      width: min(1440px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 36px;
    }

    header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 18px;
      align-items: end;
      padding: 8px 0 18px;
      border-bottom: 1px solid var(--line);
    }

    h1 {
      margin: 0;
      font-size: clamp(24px, 3vw, 38px);
      line-height: 1.08;
      font-weight: 760;
    }

    .sub {
      margin-top: 8px;
      color: var(--muted);
      font-size: 14px;
    }

    .timestamp {
      min-width: 210px;
      text-align: right;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }

    .summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 18px 0;
    }

    .summary-item,
    .source-item,
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }

    .summary-item {
      padding: 14px 16px;
      min-height: 82px;
    }

    .summary-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 680;
      text-transform: uppercase;
    }

    .summary-value {
      margin-top: 8px;
      font-size: 27px;
      line-height: 1;
      font-weight: 760;
    }

    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin: 18px 0;
    }

    button,
    select {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--text);
      font: inherit;
      font-size: 13px;
    }

    button {
      padding: 0 12px;
      cursor: pointer;
      font-weight: 650;
    }

    button[aria-pressed="true"] {
      border-color: var(--accent);
      background: #e8f1ef;
      color: #16464c;
    }

    select {
      padding: 0 32px 0 12px;
      margin-left: auto;
    }

    .sources {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }

    .sources:empty { display: none; }

    .source-item {
      padding: 12px 14px;
      min-height: 72px;
    }

    .source-name {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      font-size: 14px;
      font-weight: 720;
    }

    .source-message {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
    }

    .grid {
      display: grid;
      gap: 18px;
    }

    .industry-section {
      display: grid;
      gap: 14px;
    }

    .industry-head {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 12px;
      padding-top: 4px;
    }

    .industry-head h2 {
      margin: 0;
      font-size: 22px;
      line-height: 1.15;
      font-weight: 780;
    }

    .industry-count {
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }

    .group-section {
      display: grid;
      gap: 10px;
    }

    .group-title {
      margin: 0;
      color: #444641;
      font-size: 14px;
      font-weight: 760;
    }

    .group-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .metric {
      min-height: 270px;
      display: grid;
      grid-template-rows: auto auto auto 74px auto;
      gap: 12px;
      padding: 15px;
      overflow: hidden;
    }

    .metric-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }

    .metric h3 {
      margin: 0;
      font-size: 16px;
      line-height: 1.35;
      font-weight: 760;
      overflow-wrap: anywhere;
    }

    .meaning {
      min-height: 38px;
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }

    .pill,
    .status {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 0 9px;
      white-space: nowrap;
      font-size: 12px;
      font-weight: 720;
    }

    .pill {
      background: #eef0e8;
      color: #4b4d47;
    }

    .status { background: #ecefed; color: #3e514d; }
    .status.ok { background: #e4f3ed; color: var(--good); }
    .status.needs_key { background: #fff0d7; color: var(--warn); }
    .status.partial { background: #eeeef8; color: #4e4a9b; }
    .status.manual { background: #f0eaff; color: var(--manual); }
    .status.error { background: #fde8e4; color: var(--bad); }

    .metric-main {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
    }

    .value {
      font-size: 32px;
      line-height: 1;
      font-weight: 780;
      overflow-wrap: anywhere;
    }

    .observed {
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
    }

    .delta {
      display: grid;
      gap: 4px;
      min-width: 95px;
      text-align: right;
      font-size: 12px;
      color: var(--muted);
    }

    .delta strong {
      color: var(--text);
      font-size: 14px;
    }

    .positive { color: var(--good) !important; }
    .negative { color: var(--bad) !important; }

    .spark {
      width: 100%;
      height: 74px;
      border: 1px solid #ecece4;
      border-radius: 8px;
      background: linear-gradient(180deg, var(--panel-soft), #ffffff);
    }

    .meta {
      display: grid;
      gap: 7px;
      align-content: start;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }

    .meta-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-top: 1px solid #eeeeea;
      padding-top: 7px;
    }

    .meta-row span:first-child { color: #82837e; }

    .note {
      color: #4f514c;
      overflow-wrap: anywhere;
    }

    .period {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      border-top: 1px solid #eeeeea;
      padding-top: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }

    .empty {
      display: none;
      margin: 28px 0;
      padding: 26px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
      text-align: center;
    }

    footer {
      margin-top: 24px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }

    footer:empty { display: none; }

    @media (max-width: 1100px) {
      .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .sources { grid-template-columns: 1fr; }
      .group-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }

    @media (max-width: 720px) {
      .shell {
        width: min(100% - 20px, 680px);
        padding-top: 14px;
      }
      header {
        grid-template-columns: 1fr;
        align-items: start;
      }
      .timestamp { text-align: left; }
      .summary { grid-template-columns: 1fr; }
      .toolbar { align-items: stretch; }
      button { flex: 1 1 auto; }
      select { width: 100%; margin-left: 0; }
      .group-grid { grid-template-columns: 1fr; }
      .metric-main { grid-template-columns: 1fr; align-items: start; }
      .delta { text-align: left; grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .value { font-size: 29px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1 id="title">산업별 핵심 지표 대시보드</h1>
        <div class="sub" id="subtitle"></div>
      </div>
      <div class="timestamp" id="timestamp"></div>
    </header>

    <section class="summary" id="summary"></section>
    <nav class="toolbar" id="industryFilters" aria-label="산업 필터"></nav>
    <section class="sources" id="sources"></section>
    <section class="grid" id="metrics"></section>
    <div class="empty" id="empty">표시할 지표가 없습니다.</div>
    <footer id="footer"></footer>
  </main>

  <script>
    const DASHBOARD_DATA = __DASHBOARD_JSON__;
    const state = { industry: "전체" };

    function cls(status) {
      return String(status || "").replace(/[^a-zA-Z0-9_-]/g, "_");
    }

    function directionClass(value) {
      if (typeof value !== "number" || !Number.isFinite(value) || value === 0) return "";
      return value > 0 ? "positive" : "negative";
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[char]));
    }

    function displayMetrics() {
      return DASHBOARD_DATA.metrics.filter((metric) =>
        typeof metric.value === "number" &&
        Number.isFinite(metric.value)
      );
    }

    function renderSummary() {
      const metrics = displayMetrics();
      const industries = new Set(metrics.map((metric) => metric.industry)).size;
      const groups = new Set(metrics.map((metric) => `${metric.industry}::${metric.group}`)).size;
      const items = [
        ["지표", metrics.length],
        ["산업", industries],
        ["그룹", groups],
        ["업데이트", DASHBOARD_DATA.generated_label.split(" ")[0]]
      ];
      document.getElementById("summary").innerHTML = items.map(([label, value]) => `
        <article class="summary-item">
          <div class="summary-label">${label}</div>
          <div class="summary-value">${value}</div>
        </article>
      `).join("");
    }

    function renderFilters() {
      const industries = ["전체", ...DASHBOARD_DATA.industries];
      const buttons = industries.map((industry) => `
        <button type="button" data-industry="${escapeHtml(industry)}" aria-pressed="${state.industry === industry}">
          ${escapeHtml(industry)}
        </button>
      `).join("");
      document.getElementById("industryFilters").innerHTML = buttons;
      document.querySelectorAll("[data-industry]").forEach((button) => {
        button.addEventListener("click", () => {
          state.industry = button.dataset.industry;
          render();
        });
      });
    }

    function renderSources() {
      document.getElementById("sources").innerHTML = "";
    }

    function sparkline(history, status) {
      if (!history || history.length < 2) {
        return `<svg class="spark" viewBox="0 0 300 74" role="img" aria-label="history unavailable">
          <line x1="18" y1="38" x2="282" y2="38" stroke="#d8d8cf" stroke-width="2" stroke-dasharray="5 5"></line>
        </svg>`;
      }
      const values = history.map((point) => point.value).filter((value) => typeof value === "number" && Number.isFinite(value));
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = max - min || 1;
      const width = 300;
      const height = 74;
      const padX = 12;
      const padY = 10;
      const path = history.map((point, index) => {
        const x = padX + (index / Math.max(history.length - 1, 1)) * (width - padX * 2);
        const y = height - padY - ((point.value - min) / span) * (height - padY * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      const stroke = status === "error" ? "#c24135" : "#28666e";
      return `<svg class="spark" viewBox="0 0 300 74" role="img" aria-label="trend">
        <line x1="12" y1="64" x2="288" y2="64" stroke="#ecece4" stroke-width="1"></line>
        <polyline points="${path}" fill="none" stroke="${stroke}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
      </svg>`;
    }

    function filteredMetrics() {
      return displayMetrics()
        .filter((metric) => state.industry === "전체" || metric.industry === state.industry)
        .sort((a, b) => {
          const industryDelta = DASHBOARD_DATA.industries.indexOf(a.industry) - DASHBOARD_DATA.industries.indexOf(b.industry);
          if (industryDelta !== 0) return industryDelta;
          const groupDelta = String(a.group).localeCompare(String(b.group), "ko");
          if (groupDelta !== 0) return groupDelta;
          return String(a.name).localeCompare(String(b.name), "ko");
        });
    }

    function groupedMetrics(metrics) {
      const industries = [];
      for (const industry of DASHBOARD_DATA.industries) {
        const industryMetrics = metrics.filter((metric) => metric.industry === industry);
        if (!industryMetrics.length) continue;
        const groups = [];
        for (const metric of industryMetrics) {
          let group = groups.find((item) => item.name === metric.group);
          if (!group) {
            group = { name: metric.group || "핵심 지표", metrics: [] };
            groups.push(group);
          }
          group.metrics.push(metric);
        }
        industries.push({ name: industry, metrics: industryMetrics, groups });
      }
      return industries;
    }

    function renderMetrics() {
      const metrics = filteredMetrics();
      document.getElementById("empty").style.display = metrics.length ? "none" : "block";
      document.getElementById("metrics").innerHTML = groupedMetrics(metrics).map((industry) => `
        <section class="industry-section">
          <div class="industry-head">
            <h2>${escapeHtml(industry.name)}</h2>
            <span class="industry-count">${industry.metrics.length}개 지표</span>
          </div>
          ${industry.groups.map((group) => `
            <section class="group-section">
              <h3 class="group-title">${escapeHtml(group.name)}</h3>
              <div class="group-grid">
                ${group.metrics.map((metric) => `
                  <article class="metric">
                    <div class="metric-head">
                      <div>
                        <span class="pill">${escapeHtml(metric.observed_label || metric.frequency || "")}</span>
                        <h3>${escapeHtml(metric.name)}</h3>
                      </div>
                    </div>
                    <p class="meaning">${escapeHtml(metric.meaning)}</p>
                    <div class="metric-main">
                      <div class="value">${escapeHtml(metric.display_value)}</div>
                      <div class="delta">
                        <span>전기 <strong class="${directionClass(metric.change_abs)}">${escapeHtml(metric.change_abs_label)}</strong></span>
                        <span>전기% <strong class="${directionClass(metric.change_pct)}">${escapeHtml(metric.change_pct_label)}</strong></span>
                        <span>YoY <strong class="${directionClass(metric.yoy_pct)}">${escapeHtml(metric.yoy_pct_label)}</strong></span>
                      </div>
                    </div>
                    ${sparkline(metric.history, "ok")}
                    <div class="period">
                      <span>기간</span>
                      <strong>${escapeHtml(metric.period_label || metric.observed_label || "")}</strong>
                    </div>
                  </article>
                `).join("")}
              </div>
            </section>
          `).join("")}
        </section>
      `).join("");
    }

    function render() {
      document.getElementById("title").textContent = DASHBOARD_DATA.title;
      document.getElementById("subtitle").textContent = "산업별 지표를 성격이 비슷한 그룹으로 정리했습니다.";
      document.getElementById("timestamp").innerHTML = `업데이트 ${escapeHtml(DASHBOARD_DATA.generated_label)}`;
      document.getElementById("footer").textContent = "";
      renderSummary();
      renderFilters();
      renderSources();
      renderMetrics();
    }

    render();
  </script>
</body>
</html>
"""
