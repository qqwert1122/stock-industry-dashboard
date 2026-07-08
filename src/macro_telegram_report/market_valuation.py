"""밸류에이션/수급 지표 수집기 모음.

- multpl.com: S&P 500 Shiller CAPE, PER, 배당수익률 (1871년~ 월간, HTML 표 크롤)
- FINRA: 미국 증권사 신용융자(margin debt) 잔액 (월간, HTML 표 크롤)
- KRX 정보데이터시스템: KOSPI/KOSDAQ PER/PBR/배당수익률 (일간, 비공식 JSON)

전부 공식 API가 아니므로 실패해도 대시보드 빌드가 계속되도록 soft-fail합니다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

MULTPL_TABLE_URL = "https://www.multpl.com/{slug}/table/by-month"
FINRA_MARGIN_URL = "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics"
KRX_JSON_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_REFERER = "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201060201"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def parse_multpl_table(html: str) -> list[tuple[date, float]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find(id="datatable") or soup.find("table")
    points: dict[date, float] = {}
    if table is None:
        return []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        date_text = cells[0].get_text(strip=True)
        value_text = cells[1].get_text(strip=True).replace(" ", "").replace("%", "")
        try:
            observed_at = datetime.strptime(date_text, "%b %d, %Y").date()
            value = float(value_text.replace(",", ""))
        except ValueError:
            continue
        # 월초 값으로 정규화(당월 진행 중 값은 해당 월 1일로 기록)
        month_start = date(observed_at.year, observed_at.month, 1)
        if month_start not in points:
            points[month_start] = value
    return sorted(points.items())


def fetch_multpl_series(session: requests.Session, slug: str) -> list[tuple[date, float]]:
    response = session.get(
        MULTPL_TABLE_URL.format(slug=slug),
        headers={"User-Agent": BROWSER_USER_AGENT},
        timeout=(5, 30),
    )
    response.raise_for_status()
    points = parse_multpl_table(response.text)
    if not points:
        raise ValueError("multpl 표를 파싱하지 못했습니다")
    return points


def parse_finra_margin_table(html: str) -> list[tuple[date, float]]:
    """FINRA margin statistics 페이지에서 (월, debit balances $B) 시계열을 추출합니다."""
    soup = BeautifulSoup(html, "html.parser")
    points: dict[date, float] = {}
    for row in soup.find_all("tr"):
        cells = [cell.get_text(strip=True) for cell in row.find_all("td")]
        if len(cells) < 2:
            continue
        month_match = re.match(r"^([A-Z][a-z]{2})-(\d{2})$", cells[0])
        if not month_match:
            continue
        try:
            observed_at = datetime.strptime(cells[0], "%b-%y").date()
            value_millions = float(cells[1].replace(",", ""))
        except ValueError:
            continue
        points[observed_at] = value_millions / 1000.0
    return sorted(points.items())


def fetch_finra_margin_series(session: requests.Session, url: str = FINRA_MARGIN_URL) -> list[tuple[date, float]]:
    html = ""
    try:
        response = session.get(
            url,
            headers={
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=(5, 30),
        )
        response.raise_for_status()
        html = response.text
    except requests.RequestException:
        # FINRA는 python-requests의 TLS 핑거프린트를 차단하는 경우가 있어 curl로 재시도합니다.
        html = fetch_html_via_curl(url)
    points = parse_finra_margin_table(html)
    if not points:
        raise ValueError("FINRA margin 표를 파싱하지 못했습니다")
    return points


def fetch_html_via_curl(url: str, timeout_seconds: int = 40) -> str:
    if not shutil.which("curl"):
        raise RuntimeError("curl을 찾을 수 없어 FINRA 페이지를 가져오지 못했습니다")
    completed = subprocess.run(
        ["curl", "-sfL", "--max-time", str(timeout_seconds), "-A", "Mozilla/5.0", url],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


KRX_FIELDS = {
    "PER": "WT_PER",
    "PBR": "WT_STKPRC_NETASST_RTO",
    "배당수익률": "DIV_YD",
}


def fetch_krx_valuation_window(
    session: requests.Session,
    ind_idx: str,
    ind_idx2: str,
    start: date,
    end: date,
) -> dict[str, list[tuple[date, float]]]:
    """KRX 지수 PER/PBR/배당수익률 추이(MDCSTAT00702)를 기간 단위로 가져옵니다."""
    response = session.post(
        KRX_JSON_URL,
        data={
            "bld": "dbms/MDC/STAT/standard/MDCSTAT00702",
            "locale": "ko_KR",
            "searchType": "P",
            "indIdx": ind_idx,
            "indIdx2": ind_idx2,
            "strtDd": start.strftime("%Y%m%d"),
            "endDd": end.strftime("%Y%m%d"),
            "csvxls_isNo": "false",
        },
        headers={"User-Agent": BROWSER_USER_AGENT, "Referer": KRX_REFERER},
        timeout=(5, 30),
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("output") or []
    series: dict[str, list[tuple[date, float]]] = {name: [] for name in KRX_FIELDS}
    for row in rows:
        if not isinstance(row, dict):
            continue
        date_text = str(row.get("TRD_DD") or "").replace("/", "-")
        try:
            observed_at = date.fromisoformat(date_text)
        except ValueError:
            continue
        for name, field in KRX_FIELDS.items():
            raw = str(row.get(field) or "").replace(",", "").strip()
            if not raw or raw == "-":
                continue
            try:
                series[name].append((observed_at, float(raw)))
            except ValueError:
                continue
    for name in series:
        series[name].sort(key=lambda point: point[0])
    return series


def fetch_krx_valuation_series(
    session: requests.Session,
    ind_idx: str,
    ind_idx2: str,
    start: date,
    end: date,
    *,
    chunk_days: int = 365,
) -> dict[str, list[tuple[date, float]]]:
    """긴 기간은 1년 단위로 나눠 요청합니다(요청 간격은 세션 스로틀이 보장)."""
    merged: dict[str, dict[date, float]] = {name: {} for name in KRX_FIELDS}
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=chunk_days - 1), end)
        window = fetch_krx_valuation_window(session, ind_idx, ind_idx2, cursor, window_end)
        for name, points in window.items():
            for observed_at, value in points:
                merged[name][observed_at] = value
        cursor = window_end + timedelta(days=1)
    return {name: sorted(values.items()) for name, values in merged.items()}


def latest_stats(points: list[tuple[date, float]]) -> tuple[date, float, float | None]:
    latest_date, latest_value = points[-1]
    previous_value = points[-2][1] if len(points) > 1 else None
    return latest_date, latest_value, previous_value
