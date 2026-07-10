"""호스트별 최소 요청 간격과 429 재시도를 강제하는 세션.

무료 API를 매일 호출하는 프로젝트 특성상, 차단(레이트리밋)을 피하는 것이
데이터 연속성의 핵심입니다. 모든 수집기가 이 세션을 공유합니다.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

import requests

DEFAULT_MIN_INTERVAL = 0.25
HOST_MIN_INTERVALS = {
    "api.stlouisfed.org": 0.6,  # FRED: 120 req/min 제한 대비 절반 수준으로 유지
    "ecos.bok.or.kr": 0.5,
    "data.krx.co.kr": 2.0,  # KRX는 공식 API가 아니므로 보수적으로
    "data-dbg.krx.co.kr": 0.75,
    "freesis.kofia.or.kr": 2.0,
    "www.multpl.com": 1.0,
    "query1.finance.yahoo.com": 0.5,
    "stooq.com": 1.0,
    "apis.data.go.kr": 0.4,
    "kosis.kr": 0.5,
    "api.eia.gov": 0.5,
    "data.sec.gov": 0.5,
    "api.usaspending.gov": 0.5,
    "api.fda.gov": 0.5,
    "clinicaltrials.gov": 0.5,
    "ll.thespacedevs.com": 5.0,
    "api.upbit.com": 0.5,
    "api.fiscaldata.treasury.gov": 1.0,
    "www.stat-search.boj.or.jp": 1.0,
    "data-api.ecb.europa.eu": 1.0,
    "publicreporting.cftc.gov": 1.0,
    "www.googleapis.com": 1.0,
    "generativelanguage.googleapis.com": 1.0,
}
RATE_LIMIT_STATUSES = {429, 503}
MAX_RATE_LIMIT_RETRIES = 2


class ThrottledSession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self._last_request_at: dict[str, float] = {}

    def request(self, method, url, *args, **kwargs):  # noqa: ANN001 - requests signature
        host = urlparse(str(url)).netloc.lower()
        self._wait_for_host(host)
        response = super().request(method, url, *args, **kwargs)

        retries = 0
        while response.status_code in RATE_LIMIT_STATUSES and retries < MAX_RATE_LIMIT_RETRIES:
            retries += 1
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            delay = retry_after if retry_after is not None else min(8.0, 2.0 * retries)
            time.sleep(delay)
            self._wait_for_host(host)
            response = super().request(method, url, *args, **kwargs)
        return response

    def _wait_for_host(self, host: str) -> None:
        min_interval = HOST_MIN_INTERVALS.get(host, DEFAULT_MIN_INTERVAL)
        last = self._last_request_at.get(host)
        now = time.monotonic()
        if last is not None:
            wait = min_interval - (now - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request_at[host] = time.monotonic()


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return min(20.0, max(0.0, seconds))


def build_session(user_agent: str = "industry-dashboard/0.1 (+personal-investing)") -> ThrottledSession:
    session = ThrottledSession()
    session.headers.update({"User-Agent": user_agent})
    return session
