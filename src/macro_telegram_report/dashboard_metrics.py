"""Metric construction, classification, geography, and display formatting."""

from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta
from typing import Any

from .dashboard_localization import (
    CAPEX_MEANINGS,
    WSTS_3MMA_MEANING,
    WSTS_REGION_MEANINGS,
    clean_display_text,
    english_depth,
    english_frequency,
    english_group,
    english_industry,
    english_metric_meaning,
    english_metric_name,
    english_unit,
)
from .utils import add_months, fmt_number, fmt_pct, fmt_signed, pct_change
DEFAULT_INDUSTRIES = [
    "반도체",
    "데이터인프라",
    "자동차",
    "전기차",
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
def stablecoin_meaning() -> str:
    return "달러 연동 스테이블코인의 유통량 변화로 온체인 달러 유동성과 결제/거래 수요를 확인합니다."


def sec_capex_meaning(company_name: str = "빅테크") -> str:
    display_name = company_name.replace(" CAPEX", "").strip() or "빅테크"
    if display_name in CAPEX_MEANINGS:
        return CAPEX_MEANINGS[display_name]
    return (
        f"{display_name}의 CAPEX는 데이터센터, 서버, AI 인프라 같은 장기 설비투자 규모를 보여줍니다. "
        "투자가 커질수록 클라우드와 AI 인프라 수요가 강하다는 신호로 볼 수 있습니다."
    )


def wsts_metric_meaning(region: str, is_3mma: bool) -> str:
    base = WSTS_REGION_MEANINGS.get(region) or (
        f"{region} 지역 반도체 판매액입니다. 지역별 수요가 반도체 업황에 어떻게 반영되는지 볼 때 참고합니다."
    )
    return f"{base} {WSTS_3MMA_MEANING}" if is_3mma else base


def infer_flow_metric_meaning(name: str) -> str:
    text = str(name or "").strip()
    flow_match = re.match(r"^(.+?)\s+(.+?)\s+(20일 누적 순매수|순매수|매수|매도)$", text)
    if not flow_match:
        return ""
    market_label, investor, measure_label = flow_match.groups()
    if measure_label == "20일 누적 순매수":
        return (
            f"{market_label}에서 {investor}이 최근 20거래일 동안 순매수한 금액의 합계입니다. "
            "하루짜리 수급보다 잡음이 적어서, 같은 주체가 시장을 꾸준히 사는지 파는지 볼 때 씁니다."
        )
    return flow_metric_meaning(market_label, investor, measure_label)


def korea_fear_greed_meaning(label: str) -> str:
    return (
        f"{label} 시장의 가격 추세, 상승·하락 종목 수, 52주 신고가·신저가, 변동성을 합쳐 "
        "투자심리가 공포 쪽인지 탐욕 쪽인지 보여줍니다. 0에 가까우면 공포, "
        "100에 가까우면 탐욕이 강한 구간입니다."
    )


def vkospi_meaning() -> str:
    return (
        "VKOSPI는 코스피200 옵션 가격에 반영된 예상 변동성입니다. 숫자가 높아질수록 "
        "국내 주식시장이 앞으로 크게 흔들릴 수 있다고 보는 투자자가 많다는 뜻입니다."
    )


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
    depth: str = "",
    meaning: str = "",
    history_key: str = "",
    history_merge: str = "full",
    metric_id: str = "",
    section: str = "",
    market_category: str = "",
    also_market_category: str | list[str] = "",
    refresh_scope: str = "",
    chart_style: str = "",
    exclude_from_movers: bool = False,
) -> dict[str, Any]:
    change_abs = value - previous_value if value is not None and previous_value is not None else None
    change_pct = pct_change(value, previous_value) if value is not None else None
    yoy_pct = pct_change(value, yoy_value) if value is not None else None
    resolved_id = metric_id or hashlib.sha1(f"{industry}|{name}|{source}".encode("utf-8")).hexdigest()[:12]
    history_points = [
        {"date": observed_date.isoformat(), "value": observed_value}
        for observed_date, observed_value in (history or [])
    ]
    resolved_group = group or infer_metric_group(industry, name)
    resolved_meaning = meaning or infer_metric_meaning(industry, name)
    resolved_depth = depth or infer_metric_depth(industry, name, resolved_group)

    return {
        "id": resolved_id,
        "industry": industry,
        "section": section,
        "market_category": market_category,
        "also_market_category": also_market_category,
        "refresh_scope": refresh_scope,
        "chart_style": chart_style,
        "exclude_from_movers": exclude_from_movers,
        "depth": resolved_depth,
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
        "next_update_label": next_update_label(observed_at, frequency),
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
        "history_key": history_key,
        "history_merge": history_merge,
    }


def configured_industries(config: dict[str, Any], metrics: list[dict[str, Any]]) -> list[str]:
    configured = list(config.get("dashboard", {}).get("industries") or DEFAULT_INDUSTRIES)
    seen = set(configured)
    for metric in metrics:
        if str(metric.get("section") or "") == "market":
            continue
        industry = str(metric.get("industry") or "매크로")
        if industry not in seen:
            configured.append(industry)
            seen.add(industry)
    return configured


def normalize_market_categories(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_display_text(item) for item in value if clean_display_text(item)]
    text = clean_display_text(value)
    return [text] if text else []


def set_market_category(metric: dict[str, Any], category: str, *, primary: bool = False) -> None:
    if primary:
        metric["section"] = "market"
        metric["market_category"] = category
        return
    existing = normalize_market_categories(metric.get("also_market_category"))
    if category and category != metric.get("market_category") and category not in existing:
        existing.append(category)
    metric["also_market_category"] = existing


def assign_market_navigation_fields(metrics: list[dict[str, Any]]) -> None:
    """Map existing market-level indicators into the new 시황 navigation.

    Explicit collector/config fields win. These heuristics keep legacy payloads
    useful without changing metric names or history keys.
    """
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("name") or "")
        group = str(metric.get("group") or "")
        industry = str(metric.get("industry") or "")
        source = str(metric.get("source") or "")
        section = str(metric.get("section") or "")
        primary_category = str(metric.get("market_category") or "")

        if section == "market" and primary_category:
            metric["also_market_category"] = normalize_market_categories(metric.get("also_market_category"))
            continue

        if group == "시장지수" or name in {"코스피", "코스닥", "나스닥", "S&P 500", "다우"}:
            set_market_category(metric, "종합", primary=True)
        elif any(token in name for token in ("원/달러", "USD/KRW", "엔/달러", "엔/원", "S&P500 선물", "나스닥100 선물", "KOSPI200 선물", "KOSPI200 베이시스")):
            set_market_category(metric, "종합", primary=True)
        elif name in {"VIX", "VKOSPI"} or group == "공포탐욕" or "공포탐욕" in name:
            set_market_category(metric, "심리·변동성", primary=True)
        elif group in {"수급", "프로그램", "공매도"} or str(metric.get("chart_style") or "") == "flow_bars":
            set_market_category(metric, "수급", primary=True)
        elif group == "수급 과열" or "FINRA" in source or any(token in name for token in ("신용융자", "투자자예탁금", "CMA")):
            set_market_category(metric, "신용·예탁금", primary=True)
        elif group == "밸류에이션" and (industry == "매크로" or name.startswith(("코스피", "코스닥", "S&P 500"))):
            set_market_category(metric, "밸류에이션", primary=True)
        elif any(token in name for token in ("달러인덱스", "금 선물", "금 가격", "천연가스", "BTC", "ETH", "비트코인", "이더리움", "김치프리미엄")):
            set_market_category(metric, "원자재·크립토", primary=True)
        else:
            if group in {"금리", "신용 스프레드", "스프레드", "금리/스프레드"} or any(token in name for token in ("국채", "금리차", "기준금리", "회사채")):
                set_market_category(metric, "금리·채권")
            if industry in {"화학/정유", "철강/소재", "스테이블코인"} and any(token in name for token in ("유가", "WTI", "Brent", "구리", "스테이블코인")):
                set_market_category(metric, "원자재·크립토")

        metric["also_market_category"] = normalize_market_categories(metric.get("also_market_category"))


def infer_metric_country(metric: dict[str, Any]) -> str:
    """Return a compact geographic code for display and client-side filtering."""
    explicit = clean_display_text(metric.get("country") or "").upper()
    if explicit:
        return explicit

    name = clean_display_text(metric.get("name") or "")
    source = clean_display_text(metric.get("source") or "")
    history_key = clean_display_text(metric.get("history_key") or "")
    text = f"{name} {source} {history_key}"
    lowered = text.lower()

    # Region/global series must win over source-country heuristics such as FRED.
    if any(token in lowered for token in ("worldwide", "global", "world bank", "글로벌", "전세계", "세계 ")):
        return "GLOBAL"
    if any(token in lowered for token in ("asia pacific", "아시아 태평양")):
        return "APAC"
    if any(token in lowered for token in ("americas", "미주")):
        return "AMERICAS"
    if any(token in text for token in ("BDI", "철광석", "구리", "알루미늄", "리튬 가격", "USDT/USDC", "비트코인", "김치프리미엄", "Phase 3 임상")):
        return "GLOBAL"

    if any(token in text for token in ("한국", "코스피", "코스닥", "원/달러", "VKOSPI", ".KS", ".KQ")) or any(
        token in lowered for token in ("krx", "kosis", "ecos", "kofia", "data.go.kr")
    ):
        return "KR"
    if any(token in text for token in ("일본", "BOJ", "엔/달러", "엔/원", ".T)")) or history_key.startswith("boj-"):
        return "JP"
    if any(token in text for token in ("중국", "위안", "CNY")):
        return "CN"
    if any(token in text for token in ("유럽", "유로시스템", "ECB", "유로존")) or history_key.startswith("ecb-"):
        return "EU"
    if any(token in text for token in ("TSMC", "대만")):
        return "TW"
    if any(token in text for token in ("ASML", "네덜란드")):
        return "NL"

    us_names = (
        "미국", "S&P", "나스닥", "다우", "VIX", "Sahm", "GDPNow", "CNN",
        "WTI", "연준", "TGA", "역레포", "하이일드", "Micron", "NVIDIA", "AMD(",
        "Intel(", "Applied Materials", "Microsoft", "Amazon", "Alphabet", "Meta", "Tesla",
        "GE Vernova", "Teradyne", "Uber", "Mobileye", "Qualcomm", "Rocket Lab", "Eli Lilly",
    )
    if any(token in text for token in us_names) or any(
        token in lowered for token in ("fred", "fiscaldata", "finra", "openfda", "usaspending", "eia api", "nrel")
    ):
        return "US"
    return "GLOBAL"


def assign_metric_country_fields(metrics: list[dict[str, Any]]) -> None:
    for metric in metrics:
        if isinstance(metric, dict):
            metric["country"] = infer_metric_country(metric)


def visible_dashboard_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for metric in metrics:
        value = metric.get("value")
        if metric.get("status") == "ok" and isinstance(value, (int, float)):
            visible.append(
                {
                    "id": metric["id"],
                    "status": metric["status"],
                    "history_key": metric.get("history_key", ""),
                    "history_merge": metric.get("history_merge", "full"),
                    "section": clean_display_text(metric.get("section") or ""),
                    "market_category": clean_display_text(metric.get("market_category") or ""),
                    "also_market_category": [
                        clean_display_text(item)
                        for item in (
                            metric.get("also_market_category")
                            if isinstance(metric.get("also_market_category"), list)
                            else [metric.get("also_market_category")]
                        )
                        if clean_display_text(item)
                    ],
                    "refresh_scope": clean_display_text(metric.get("refresh_scope") or ""),
                    "chart_style": clean_display_text(metric.get("chart_style") or ""),
                    "exclude_from_movers": bool(metric.get("exclude_from_movers")),
                    "source": clean_display_text(metric.get("source") or ""),
                    "country": clean_display_text(metric.get("country") or "GLOBAL"),
                    "industry": clean_display_text(metric["industry"]),
                    "industry_en": english_industry(clean_display_text(metric["industry"])),
                    "depth": clean_display_text(metric.get("depth") or ""),
                    "depth_en": english_depth(clean_display_text(metric.get("depth") or "")),
                    "group": clean_display_text(metric["group"]),
                    "group_en": english_group(clean_display_text(metric["group"])),
                    "name": clean_display_text(metric["name"]),
                    "name_en": english_metric_name(clean_display_text(metric["name"])),
                    "meaning": clean_display_text(metric["meaning"]),
                    "meaning_en": english_metric_meaning(
                        clean_display_text(metric["meaning"]),
                        clean_display_text(metric["industry"]),
                    ),
                    "value": metric["value"],
                    "unit": clean_display_text(metric["unit"]),
                    "unit_en": english_unit(clean_display_text(metric["unit"])),
                    "display_value": metric["display_value"],
                    "frequency": clean_display_text(metric["frequency"]),
                    "frequency_en": english_frequency(clean_display_text(metric["frequency"])),
                    "observed_at": metric["observed_at"],
                    "observed_label": metric["observed_label"],
                    "fetched_at": metric.get("fetched_at", ""),
                    "fetch_status": metric.get("fetch_status", ""),
                    "fetch_status_label": metric.get("fetch_status_label", ""),
                    "next_update_label": metric["next_update_label"],
                    "change_abs": metric["change_abs"],
                    "change_pct": metric["change_pct"],
                    "change_abs_label": metric["change_abs_label"],
                    "change_pct_label": metric["change_pct_label"],
                    "yoy_pct": metric["yoy_pct"],
                    "yoy_pct_label": metric["yoy_pct_label"],
                    "history": metric["history"],
                    "period_label": metric["period_label"],
                    "interpretation": metric.get("interpretation") or {},
                }
            )
    return visible


def infer_export_industry(hs_code: str) -> str:
    if hs_code.startswith(("8541", "8542")):
        return "반도체"
    if hs_code.startswith("870380"):
        return "전기차"
    if hs_code.startswith("8703"):
        return "자동차"
    if hs_code.startswith("8901"):
        return "조선"
    return "매크로"


def infer_metric_group(industry: str, name: str) -> str:
    if "수출" in name:
        return "수출"
    if name in WSTS_REGION_MEANINGS or name.startswith("3MMA - "):
        return "판매액(WSTS)"
    if "WSTS" in name or "반도체 판매" in name:
        return "판매액(WSTS)"
    if industry == "방산":
        if "수주잔고" in name:
            return "수주잔고"
        if "신규주문" in name:
            return "신규주문"
        return "방산 수요"
    if industry == "스테이블코인":
        return "유통량"
    if industry == "전력":
        if "천연가스" in name or "석탄" in name:
            return "에너지 가격"
        if "판매량" in name or "발전량" in name:
            return "전력 수요"
        if "PPI" in name:
            return "전력 가격"
        return "전력 수요/생산"
    if industry == "데이터인프라":
        return "CAPEX"
    if industry == "로봇":
        if "PPI" in name:
            return "산업 장비 가격"
        return "설비투자"
    if industry == "우주":
        if "PPI" in name:
            return "항공우주 가격"
        return "우주/방산 생산"
    if industry == "바이오":
        return "바이오 가격"
    if industry == "배터리":
        if "니켈" in name or "리튬" in name or "코발트" in name:
            return "배터리 원재료"
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
        return "화학 스프레드"
    if industry == "자동차":
        return "판매/수요"
    if industry == "전기차":
        return "EV 수요"
    if industry == "매크로":
        if "환율" in name:
            return "환율"
        if "VIX" in name:
            return "리스크"
    return "핵심 지표"


def infer_metric_depth(industry: str, name: str, group: str = "") -> str:
    if industry != "반도체":
        return ""

    text = f"{name} {group}"
    if name in WSTS_REGION_MEANINGS or name.startswith("3MMA - ") or "전체" in text:
        return "전체 업황"
    if any(keyword in text for keyword in ["메모리", "DRAM", "NAND", "HBM", "SK하이닉스", "Micron", "삼성전자"]):
        return "메모리 반도체"
    if any(keyword in text for keyword in ["NVIDIA", "엔비디아", "GPU"]):
        return "AI/GPU"
    if "AMD" in text:
        return "AI/GPU"
    if any(keyword in text for keyword in ["CPU", "프로세서", "컨트롤러", "Intel"]):
        return "CPU/프로세서"
    if any(keyword in text for keyword in ["TSMC", "파운드리"]):
        return "파운드리"
    if any(keyword in text for keyword in ["ASML", "Applied Materials", "Lam Research", "장비"]):
        return "장비"
    if any(keyword in text for keyword in ["패키징", "후공정", "패키지"]):
        return "패키징/후공정"
    if any(keyword in text for keyword in ["소자", "부품", "트랜지스터", "다이오드", "웨이퍼"]):
        return "소자/부품"
    return "전체 업황"


def infer_metric_meaning(industry: str, name: str) -> str:
    flow_meaning = infer_flow_metric_meaning(name)
    if flow_meaning:
        return flow_meaning
    wsts_old_match = re.match(r"^WSTS 반도체 판매액( 3MMA)? - (.+)$", name)
    if wsts_old_match:
        return wsts_metric_meaning(wsts_old_match.group(2), bool(wsts_old_match.group(1)))
    if name.startswith("3MMA - "):
        return wsts_metric_meaning(name.removeprefix("3MMA - "), True)
    if name in WSTS_REGION_MEANINGS:
        return wsts_metric_meaning(name, False)
    if "WSTS" in name:
        return wsts_metric_meaning("Worldwide", False)
    if name in {"코스피", "코스닥", "S&P 500", "나스닥", "다우"}:
        market_meanings = {
            "코스피": "한국 대형주 중심의 대표 주가지수입니다. 국내 증시 전체 방향과 외국인 자금 흐름을 볼 때 기준점으로 씁니다.",
            "코스닥": "한국 성장주와 중소형주 비중이 큰 주가지수입니다. 개인투자자 심리와 성장주 위험 선호를 확인할 때 봅니다.",
            "S&P 500": "미국 대형주 500개로 구성된 대표 지수입니다. 글로벌 위험 선호와 미국 증시의 넓은 방향을 보는 기준입니다.",
            "나스닥": "기술주 비중이 높은 미국 주가지수입니다. AI, 반도체, 소프트웨어 같은 성장주 투자심리를 확인할 때 봅니다.",
            "다우": "미국 우량 대형주 중심의 주가지수입니다. 경기민감 대형주의 흐름과 미국 증시의 전통 산업 쪽 분위기를 볼 때 참고합니다.",
        }
        return market_meanings[name]
    if "Sahm Rule" in name:
        return "실업률이 최근 저점보다 얼마나 높아졌는지 보는 경기침체 신호입니다. 0.5%p를 넘으면 과거에는 침체 진입 가능성이 커진 경우가 많았습니다."
    if "GDPNow" in name:
        return "애틀랜타 연은이 실시간 경제지표를 반영해 추정하는 미국 GDP 성장률 전망입니다. 경기 기대가 좋아지는지 식는지 빠르게 볼 때 씁니다."
    if name == "미국 CPI" or "소비자물가" in name:
        return "미국 소비자물가 상승률입니다. 인플레이션 압력과 연준 금리 기대를 움직여 주식, 채권, 환율에 모두 영향을 줍니다."
    if "반도체 PPI" in name:
        return "반도체 생산자 가격입니다. 반도체 가격이 오르는지 내리는지 볼 때 참고합니다."
    if "기준금리" in name:
        return "중앙은행이 정하는 정책금리입니다. 예금·대출금리, 기업 조달비용, 주식시장 할인율에 영향을 주는 기본 금리입니다."
    if "국채금리" in name:
        return "할인율과 금융주 마진 기대를 좌우하는 시장 금리입니다."
    if "금리차" in name:
        return "경기 기대와 은행 순이자마진 방향을 함께 보여주는 지표입니다."
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
    if "휘발유" in name or "디젤" in name:
        return "석유 제품 가격입니다. 정유 제품 수요와 정유사 마진 방향을 볼 때 참고합니다."
    if "화학 PPI" in name:
        return "화학 제품 생산자 가격입니다. 제품 가격이 원가보다 빠르게 움직이는지 볼 때 참고합니다."
    if "철광석" in name:
        return "철강 원가와 중국 투자 수요를 반영하는 핵심 원재료입니다."
    if "구리" in name:
        return "전기화와 제조업 경기를 민감하게 반영하는 경기 민감 금속입니다."
    if "알루미늄" in name:
        return "경량 소재와 제조업 수요, 전력비 영향을 함께 받는 소재 가격입니다."
    if "니켈" in name:
        return "배터리 양극재 원가에 큰 영향을 주는 원재료 가격입니다."
    if "천연가스" in name or "석탄" in name:
        return "전력 생산 원가와 산업 에너지 비용을 좌우하는 에너지 원료 지표입니다."
    if "자동차 판매" in name:
        return "완성차 수요와 소비 경기 흐름을 확인하는 판매 지표입니다."
    if "전기차" in name:
        return "순수 전기차 수출 흐름으로 EV 수요와 국내 전기차 생산 모멘텀을 확인합니다."
    if "방산" in name:
        return "방산 발주와 생산 사이클을 통해 방산 업체 수요가 강해지는지 확인합니다."
    if "스테이블코인" in name or "USDT" in name or "USDC" in name:
        return stablecoin_meaning()
    if "전력" in name or "유틸리티" in name:
        return "전력 생산과 가격 흐름으로 전력 인프라와 전력 수요 사이클을 확인합니다."
    if industry == "데이터인프라" or "CAPEX" in name.upper():
        return sec_capex_meaning(name)
    if "산업용 기계" in name or "산업 제어" in name:
        return "공장 자동화와 로봇 설비 투자가 늘어나는지 볼 때 참고합니다."
    if "우주" in name or "항공우주" in name:
        return "항공우주 장비 생산과 가격 흐름입니다. 우주 산업의 주문과 비용 부담을 볼 때 참고합니다."
    if "생물학적" in name or "체외진단" in name:
        return "바이오 의약품과 진단 제품의 가격 사이클을 확인하는 지표입니다."
    if "배터리" in name:
        return "배터리 제품 가격 흐름으로 셀/소재 밸류체인의 업황을 점검합니다."
    if "고객예탁금" in name or "투자자예탁금" in name:
        return "증권계좌에 대기 중인 현금입니다. 늘어나면 주식시장으로 들어올 수 있는 대기 자금이 많아졌다는 뜻으로 봅니다."
    if "신용융자" in name:
        return "투자자가 빚을 내서 주식을 산 잔고입니다. 빠르게 늘면 과열 신호가 될 수 있고, 급감하면 반대매매 압력을 의심할 수 있습니다."
    if "환율" in name:
        return "수출주 원화 환산 매출과 외국인 수급에 영향을 주는 매크로 변수입니다."
    if "VIX" in name:
        return "시장 위험 회피 심리와 변동성 확대 여부를 봅니다."
    if "VKOSPI" in name:
        return vkospi_meaning()
    if "공포탐욕" in name:
        if "코스피" in name:
            return korea_fear_greed_meaning("코스피")
        if "코스닥" in name:
            return korea_fear_greed_meaning("코스닥")
        return "여러 시장 심리 지표를 묶어 투자심리가 공포 쪽인지 탐욕 쪽인지 보여줍니다. 낮을수록 공포, 높을수록 탐욕에 가깝습니다."
    if "비트코인" in name:
        return "대표적인 위험자산이자 크립토 유동성 지표입니다. 글로벌 유동성, 위험 선호, 크립토 시장 분위기를 빠르게 확인할 때 봅니다."
    if "PBR" in name:
        return "주가를 장부가치와 비교한 밸류에이션 지표입니다. 낮을수록 시장이 자산가치 대비 싸게 거래되는지 볼 때 참고합니다."
    if "CAPE" in name or "Shiller" in name:
        return "경기순환을 감안한 장기 이익 대비 주가 수준입니다. 미국 증시가 장기 평균보다 비싼지 싼지 판단할 때 봅니다."
    if "수출" in name:
        return "해당 품목의 대외 수요와 가격/물량 사이클을 확인합니다."
    if industry:
        return f"{industry} 흐름을 이해할 때 참고하는 보조 지표입니다."
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


def next_update_label(observed_at: str, frequency: str) -> str:
    if not observed_at:
        return "비정기"
    try:
        observed_date = date.fromisoformat(observed_at[:10])
    except ValueError:
        return "비정기"

    compact_frequency = frequency.replace(" ", "")
    if not compact_frequency or "비정기" in compact_frequency:
        return "비정기"
    if "일간" in compact_frequency:
        return compact_date_label((observed_date + timedelta(days=1)).isoformat())
    if "주간" in compact_frequency and "월간" not in compact_frequency:
        return compact_date_label((observed_date + timedelta(days=7)).isoformat())
    if "월간" in compact_frequency:
        return compact_date_label(add_months(observed_date, 1).isoformat())
    if "분기" in compact_frequency:
        return compact_date_label(add_months(observed_date, 3).isoformat())
    if "연간" in compact_frequency:
        return compact_date_label(add_months(observed_date, 12).isoformat())
    return "비정기"


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
    if unit == "$":
        return f"${fmt_number(value)}"
    if unit == "%":
        return f"{fmt_number(value)}%"
    if unit == "원":
        return f"{value:,.0f}원" if float(value).is_integer() else f"{fmt_number(value)}원"
    if unit:
        return f"{fmt_number(value)} {unit}"
    return fmt_number(value)


def format_abs_change(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "$B":
        return f"{fmt_signed(value)}B"
    if unit == "$":
        return f"${fmt_signed(value)}"
    if unit == "%":
        return f"{fmt_signed(value)}%p"
    if unit == "원":
        return f"{value:+,.0f}원" if float(value).is_integer() else f"{fmt_signed(value)}원"
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
