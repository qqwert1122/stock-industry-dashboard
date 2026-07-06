from __future__ import annotations

import os
from collections import defaultdict
from datetime import date
from typing import Any
from urllib.parse import quote_plus, urlencode
from xml.etree import ElementTree

import requests

from .models import Section
from .utils import (
    add_months,
    display_month,
    fmt_number,
    fmt_pct,
    iter_month_windows,
    month_key,
    pct_change,
    to_float,
)


def collect_korea_exports(
    config: dict[str, Any], session: requests.Session, today: date
) -> Section | None:
    export_config = config.get("korea_exports", {})
    if not export_config.get("enabled", True):
        return None

    service_key = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not service_key:
        return Section(
            "한국 수출",
            ["- DATA_GO_KR_SERVICE_KEY가 없어 관세청 수출 수집을 건너뜁니다."],
        )

    items = export_config.get("items", [])
    if not items:
        return Section("한국 수출", ["- config.yaml에 korea_exports.items가 없습니다."])

    end_month = add_months(date(today.year, today.month, 1), -int(export_config.get("end_offset_months", 1)))
    start_month = add_months(end_month, -int(export_config.get("months_back", 15)) + 1)
    endpoint = str(export_config["endpoint"])

    lines: list[str] = []
    for item in items:
        name = str(item.get("name") or item.get("hs_code"))
        hs_code = str(item.get("hs_code", "")).strip()
        records = fetch_itemtrade_records(
            session=session,
            endpoint=endpoint,
            service_key=service_key,
            hs_code=hs_code,
            start_month=start_month,
            end_month=end_month,
        )
        line = summarize_export_item(name, hs_code, records)
        lines.append(line)

    return Section("한국 수출", lines)


def fetch_itemtrade_records(
    session: requests.Session,
    endpoint: str,
    service_key: str,
    hs_code: str,
    start_month: date,
    end_month: date,
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for window_start, window_end in iter_month_windows(start_month, end_month, max_months=12):
        params = {
            "strtYymm": month_key(window_start),
            "endYymm": month_key(window_end),
        }
        if hs_code:
            params["hsSgn"] = hs_code

        url = build_data_go_kr_url(endpoint, service_key, params)
        response = session.get(url, timeout=30)
        response.raise_for_status()
        records.extend(parse_itemtrade_xml(response.text))
    return records


def build_data_go_kr_url(endpoint: str, service_key: str, params: dict[str, str]) -> str:
    key = service_key if "%" in service_key else quote_plus(service_key)
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}serviceKey={key}&{urlencode(params)}"


def parse_itemtrade_xml(xml_text: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text)
    result_code = first_text(root, "resultCode")
    auth_code = first_text(root, "returnReasonCode")
    result_message = (
        first_text(root, "resultMsg")
        or first_text(root, "returnAuthMsg")
        or first_text(root, "errMsg")
    )
    if result_code and result_code not in {"00", "0"}:
        raise ValueError(f"관세청 API 오류 {result_code}: {result_message or 'unknown'}")
    if auth_code and auth_code not in {"00", "0"}:
        raise ValueError(f"공공데이터 인증 오류 {auth_code}: {result_message or 'unknown'}")

    records: list[dict[str, str]] = []
    for item in root.iter():
        if local_name(item.tag) != "item":
            continue
        record = {
            local_name(child.tag): (child.text or "").strip()
            for child in list(item)
            if child.text is not None
        }
        if record:
            records.append(record)
    return records


def first_text(root: ElementTree.Element, name: str) -> str | None:
    for element in root.iter():
        if local_name(element.tag) == name and element.text:
            return element.text.strip()
    return None


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def summarize_export_item(name: str, hs_code: str, records: list[dict[str, str]]) -> str:
    monthly: dict[date, float] = defaultdict(float)
    for record in records:
        year_text = record.get("year", "").replace("-", ".").strip()
        try:
            year, month = year_text.split(".")[:2]
            observed_month = date(int(year), int(month), 1)
        except (ValueError, TypeError):
            continue

        export_value = to_float(record.get("expDlr"))
        if export_value is None:
            continue
        monthly[observed_month] += export_value

    if not monthly:
        return f"- {name}({hs_code}): 데이터 없음"

    months = sorted(monthly)
    latest_month = months[-1]
    latest_value = monthly[latest_month]
    previous_value = monthly.get(add_months(latest_month, -1))
    yoy_value = monthly.get(add_months(latest_month, -12))

    latest_billions = latest_value / 1_000_000_000
    previous_billions = previous_value / 1_000_000_000 if previous_value is not None else None
    yoy_billions = yoy_value / 1_000_000_000 if yoy_value is not None else None

    return (
        f"- {name}({hs_code}): {display_month(latest_month)} "
        f"${fmt_number(latest_billions)}B "
        f"(MoM {fmt_pct(pct_change(latest_billions, previous_billions))}, "
        f"YoY {fmt_pct(pct_change(latest_billions, yoy_billions))})"
    )
