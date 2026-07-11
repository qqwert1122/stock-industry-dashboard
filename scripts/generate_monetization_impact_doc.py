#!/usr/bin/env python3
"""운영 대시보드 지표별 광고·유료화 영향도 문서를 생성합니다."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LEVEL_LABELS = {
    1: "낮음",
    2: "중간",
    3: "높음",
    4: "치명적",
}


@dataclass(frozen=True)
class SourceProfile:
    code: str
    ad: int
    paid: int
    alert: int
    action: str
    reference: str


SOURCE_PROFILES: dict[str, SourceProfile] = {
    "FRED API": SourceProfile(
        "S2", 2, 3, 3,
        "시계열별 원저작권·상업 이용 조건을 확인하고 FRED 고지문과 출처를 유지",
        "https://fred.stlouisfed.org/docs/api/terms_of_use.html",
    ),
    "WSTS Historical Billings Report": SourceProfile(
        "S4", 3, 4, 4,
        "WSTS 자료의 공개 전시·재배포·유료 제공 범위를 서면 확인하고 필요 시 라이선스 계약",
        "https://www.wsts.org/67/Historical-Billings-Report",
    ),
    "Yahoo Finance chart API": SourceProfile(
        "S3", 4, 4, 4,
        "상업적 재사용 허가 또는 정식 시세 벤더 계약 전 광고·유료 제공을 보류",
        "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
    ),
    "KRX 정보데이터시스템": SourceProfile(
        "S3", 3, 4, 4,
        "수익사업·재배포용 시세/수급 데이터 계약 필요 여부를 KRX·코스콤에 확인",
        "https://openapi.krx.co.kr/contents/OPP/DATA/OPPDATA003.jsp",
    ),
    "KRX Open API": SourceProfile(
        "S3", 3, 4, 4,
        "OPEN API 약관 외에 시세 재배포·수익사업 계약 필요 여부를 KRX에 확인",
        "https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO002.jsp",
    ),
    "KRX Open API/Yahoo Finance": SourceProfile(
        "S3", 4, 4, 4,
        "KRX와 Yahoo 양쪽의 상업 이용·재배포 권리를 모두 해결하기 전 유료 제공 보류",
        "https://openapi.krx.co.kr/contents/OPP/DATA/OPPDATA003.jsp",
    ),
    "Upbit/Yahoo Finance": SourceProfile(
        "S3", 4, 4, 4,
        "두 제공자의 상업 이용·파생지표 생성·재배포 조건을 모두 확인하고 정식 데이터로 교체 검토",
        "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
    ),
    "한국은행 ECOS API": SourceProfile(
        "S1", 2, 2, 3,
        "ECOS 이용조건·출처표시·가공표시를 확인하고 원자료와 계산값을 구분",
        "https://ecos.bok.or.kr/api/",
    ),
    "관세청 품목별 수출입실적 API": SourceProfile(
        "S1", 2, 2, 3,
        "공공데이터 이용조건과 공공누리 유형을 확인하고 HS 코드·가공 산식을 표시",
        "https://www.data.go.kr/data/15101609/openapi.do",
    ),
    "KOSIS OpenAPI": SourceProfile(
        "S1", 2, 2, 3,
        "통계표별 이용조건과 출처·갱신시점을 표시하고 원통계와 가공값을 구분",
        "https://kosis.kr/openapi/",
    ),
    "SEC Company Facts API": SourceProfile(
        "S1", 1, 2, 2,
        "SEC fair-access 정책, 회사 공시 원문 링크, 단위·회계기간을 유지",
        "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
    ),
    "USAspending API": SourceProfile(
        "S1", 1, 2, 2,
        "공식 출처와 필터·집계 기준을 표시하고 정부의 보증·승인으로 오인되지 않게 구성",
        "https://api.usaspending.gov/",
    ),
    "EIA Open Data API": SourceProfile(
        "S1", 1, 2, 2,
        "EIA 출처, 시계열 ID, 단위, 수정 가능성을 표시",
        "https://www.eia.gov/opendata/",
    ),
    "openFDA Drugs@FDA API": SourceProfile(
        "S1", 1, 2, 2,
        "openFDA 비보증 고지와 집계 기준을 표시하고 의학·투자 조언으로 표현하지 않음",
        "https://open.fda.gov/apis/",
    ),
    "ClinicalTrials.gov API": SourceProfile(
        "S1", 1, 2, 2,
        "시험 등록정보의 한계와 검색·집계 조건을 표시하고 성공 가능성으로 해석하지 않음",
        "https://clinicaltrials.gov/data-api",
    ),
    "NLR Alternative Fuel Stations API": SourceProfile(
        "S1", 1, 2, 2,
        "NLR API 이용조건, 기준일, 중복·폐쇄 시설 처리 방식을 표시",
        "https://developer.nlr.gov/docs/transportation/alt-fuel-stations-v1/",
    ),
    "World Bank Commodity Markets Pink Sheet": SourceProfile(
        "S2", 2, 3, 3,
        "World Bank 자료 라이선스·출처표시와 원자료 파일 재배포 가능 범위를 확인",
        "https://www.worldbank.org/en/research/commodity-markets",
    ),
    "DefiLlama Stablecoins API": SourceProfile(
        "S6", 2, 3, 3,
        "API 약관·표시 조건·정의 변경 가능성을 확인하고 자산별 집계 산식을 공개",
        "https://defillama.com/stablecoins",
    ),
    "The Space Devs Launch Library 2 API": SourceProfile(
        "S6", 2, 3, 3,
        "API 이용조건·호출 한도·출처표시를 확인하고 취소·연기 발사를 집계에서 구분",
        "https://thespacedevs.com/llapi",
    ),
    "CNN Fear & Greed Index": SourceProfile(
        "S4", 3, 4, 4,
        "비공식 수집·독점 지수 재사용을 중단하거나 CNN의 서면 허가/정식 제공 경로 확보",
        "https://www.cnn.com/markets/fear-and-greed",
    ),
    "multpl.com": SourceProfile(
        "S4", 3, 4, 4,
        "스크래핑·재배포·상업 이용 허가를 서면 확인하거나 허가된 대체 데이터로 전환",
        "https://www.multpl.com/",
    ),
    "FINRA Margin Statistics": SourceProfile(
        "S2", 2, 3, 3,
        "FINRA 이용조건·출처표시와 원자료 재배포 범위를 확인하고 집계 기준을 표시",
        "https://www.finra.org/investors/learn-to-invest/advanced-investing/margin-statistics",
    ),
}

DEFAULT_SOURCE_PROFILE = SourceProfile(
    "S7", 3, 4, 4,
    "출처 이용약관·저작권·상업 이용·재배포 허용 여부를 확인하기 전 수익화 보류",
    "",
)


CONTENT_PROFILES = {
    "C1": {
        "name": "객관적 산업·실물·공식 통계",
        "paid": 1,
        "alert": 2,
        "action": "원자료·단위·기준일을 유지하고 알림은 사실 통지로 제한",
    },
    "C2": {
        "name": "거시·금리·경기·유동성 지표",
        "paid": 2,
        "alert": 3,
        "action": "해석 근거와 관측시점을 표시하고 자산배분·매매 행동 문구를 금지",
    },
    "C3": {
        "name": "개별 종목·지수·선물·환율·가상자산 가격",
        "paid": 3,
        "alert": 4,
        "action": "정식 시세 권리를 확보하고 매수·매도·목표가·손절가 알림을 금지",
    },
    "C4": {
        "name": "수급·밸류에이션·심리·파생 신호",
        "paid": 3,
        "alert": 4,
        "action": "산식·원천·한계를 공개하고 개인화 추천·행동지시를 금지; 유료화 전 금융법 검토",
    },
}


DIRECT_INSTRUMENT_GROUPS = {
    "대표주가", "시장지수", "선물", "환율", "엔캐리", "크립토", "원자재 가격",
}
DERIVED_SIGNAL_GROUPS = {
    "공포탐욕", "밸류에이션", "수급 과열", "기관", "외국인", "개인", "리스크",
}
MACRO_GROUP_FRAGMENTS = (
    "금리", "스프레드", "경기침체", "유동성", "물가", "한국 경기", "은행 건전성",
)


def level_text(level: int) -> str:
    return f"{LEVEL_LABELS[level]}({level})"


def source_profile(source: str) -> SourceProfile:
    return SOURCE_PROFILES.get(source, DEFAULT_SOURCE_PROFILE)


def content_code(metric: dict[str, Any]) -> str:
    group = str(metric.get("group") or "")
    source = str(metric.get("source") or "")
    name = str(metric.get("name") or "")
    industry = str(metric.get("industry") or "")

    if group in DIRECT_INSTRUMENT_GROUPS or group == "대표주가":
        return "C3"
    if source in {"Yahoo Finance chart API", "Upbit/Yahoo Finance"}:
        return "C3"
    if group in DERIVED_SIGNAL_GROUPS:
        return "C4"
    if source in {
        "KRX 정보데이터시스템", "KRX Open API", "KRX Open API/Yahoo Finance",
        "CNN Fear & Greed Index", "multpl.com", "FINRA Margin Statistics",
    }:
        return "C4"
    if any(fragment in group for fragment in MACRO_GROUP_FRAGMENTS):
        return "C2"
    if industry in {"매크로", "은행/금융"}:
        return "C2"
    if any(token in name for token in ("VIX", "VKOSPI", "PER", "PBR", "CAPE", "순매수")):
        return "C4"
    return "C1"


def assess_metric(metric: dict[str, Any]) -> dict[str, Any]:
    source = str(metric.get("source") or "")
    source_rule = source_profile(source)
    content = content_code(metric)
    content_rule = CONTENT_PROFILES[content]
    return {
        "ad": source_rule.ad,
        "paid": max(source_rule.paid, int(content_rule["paid"])),
        "alert": max(source_rule.alert, int(content_rule["alert"])),
        "source_code": source_rule.code,
        "content_code": content,
    }


def markdown_escape(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def source_reference_table(metrics: list[dict[str, Any]]) -> list[str]:
    counts = Counter(str(metric.get("source") or "") for metric in metrics)
    rows = [
        "| 코드 | 출처 | 지표 수 | 광고 | 유료 화면 | 유료 알림 | 필수 조치 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for source, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        profile = source_profile(source)
        source_label = markdown_escape(source)
        if profile.reference:
            source_label = f"[{source_label}]({profile.reference})"
        rows.append(
            f"| {profile.code} | {source_label} | {count} | {level_text(profile.ad)} | "
            f"{level_text(profile.paid)} | {level_text(profile.alert)} | {markdown_escape(profile.action)} |"
        )
    return rows


def summary_table(metrics: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, Counter[int]] = {
        "광고": Counter(),
        "유료 화면": Counter(),
        "유료 알림": Counter(),
    }
    for metric in metrics:
        assessed = assess_metric(metric)
        counts["광고"][assessed["ad"]] += 1
        counts["유료 화면"][assessed["paid"]] += 1
        counts["유료 알림"][assessed["alert"]] += 1
    rows = [
        "| 시나리오 | 낮음(1) | 중간(2) | 높음(3) | 치명적(4) |",
        "|---|---:|---:|---:|---:|",
    ]
    for scenario in ("광고", "유료 화면", "유료 알림"):
        rows.append(
            f"| {scenario} | {counts[scenario][1]} | {counts[scenario][2]} | "
            f"{counts[scenario][3]} | {counts[scenario][4]} |"
        )
    return rows


def metric_tables(metrics: list[dict[str, Any]]) -> list[str]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    industry_order: list[str] = []
    for metric in metrics:
        industry = str(metric.get("industry") or "미분류")
        if industry not in grouped:
            industry_order.append(industry)
        grouped[industry].append(metric)

    lines: list[str] = []
    for industry in industry_order:
        items = grouped[industry]
        lines.extend([
            f"### {markdown_escape(industry)} ({len(items)}개)",
            "",
            "| 그룹 | 지표 | 출처 | 광고 | 유료 화면 | 유료 알림 | 판정 코드 |",
            "|---|---|---|---:|---:|---:|---|",
        ])
        for metric in items:
            assessed = assess_metric(metric)
            lines.append(
                f"| {markdown_escape(metric.get('group'))} | {markdown_escape(metric.get('name'))} | "
                f"{markdown_escape(metric.get('source'))} | {level_text(assessed['ad'])} | "
                f"{level_text(assessed['paid'])} | {level_text(assessed['alert'])} | "
                f"{assessed['source_code']} · {assessed['content_code']} |"
            )
        lines.append("")
    return lines


def build_document(payload: dict[str, Any], input_path: Path) -> str:
    metrics = [metric for metric in payload.get("metrics", []) if isinstance(metric, dict)]
    generated_at = str(payload.get("generated_at") or "미상")
    lines = [
        "# 지표별 광고·유료화 영향도",
        "",
        f"- 기준 데이터: `{input_path.as_posix()}`",
        f"- 대시보드 생성 시각: `{generated_at}`",
        f"- 평가 지표 수: **{len(metrics)}개**",
        "- 문서 성격: 제품·운영 의사결정을 위한 1차 위험 분류이며 법률의견이나 데이터 라이선스 승인이 아님",
        "",
        "## 핵심 결론",
        "",
        "1. 광고는 단순 UI 변경이 아니라 현재 데이터 사용을 상업적 이용으로 바꾸므로 출처별 권리 검토가 먼저다.",
        "2. 유료 화면은 원자료 재배포 권리와 금융정보 판매 성격을 함께 검토해야 한다.",
        "3. 유료 알림은 객관적 수치 통지로 제한해도 데이터 권리 문제가 남으며, 매수·매도·목표가·비중 조정 문구가 들어가면 금융규제 위험이 급격히 커진다.",
        "4. `치명적(4)`은 사용 불가 확정이 아니라 계약·서면 허가·법률 검토 전 출시 보류를 뜻한다.",
        "",
        "## 등급 정의",
        "",
        "| 등급 | 의미 | 출시 원칙 |",
        "|---|---|---|",
        "| 낮음(1) | 공식 공개자료 중심이며 일반적인 출처표시·정확성 관리가 핵심 | 체크리스트 충족 후 가능 |",
        "| 중간(2) | 이용조건·가공표시·면책·갱신 기준 확인 필요 | 조건부 가능 |",
        "| 높음(3) | 상업 이용 또는 금융 해석 리스크가 커서 서면 확인·대체 소스 검토 필요 | 확인 전 제한적 운영 |",
        "| 치명적(4) | 시세 재배포·독점 지수·스크래핑·개별 투자신호 등 핵심 위험 존재 | 계약·법률 검토 전 보류 |",
        "",
        "## 전체 분포",
        "",
        *summary_table(metrics),
        "",
        "## 판정 방법",
        "",
        "최종 등급은 `출처 위험`과 `콘텐츠/알림 성격 위험` 중 더 높은 값을 적용했다. 따라서 같은 출처라도 종목 가격·수급·밸류에이션 지표는 유료 알림 등급이 더 높을 수 있다.",
        "",
        "### 콘텐츠 코드",
        "",
        "| 코드 | 유형 | 유료 화면 기본값 | 유료 알림 기본값 | 필수 제한 |",
        "|---|---|---:|---:|---|",
    ]
    for code, profile in CONTENT_PROFILES.items():
        lines.append(
            f"| {code} | {profile['name']} | {level_text(int(profile['paid']))} | "
            f"{level_text(int(profile['alert']))} | {profile['action']} |"
        )
    lines.extend([
        "",
        "### 출처별 공통 판정",
        "",
        *source_reference_table(metrics),
        "",
        "## 지표별 판정",
        "",
    ])
    lines.extend(metric_tables(metrics))
    lines.extend([
        "## 출시 게이트",
        "",
        "### 광고 출시 전",
        "",
        "- 지표별 원저작권자·이용약관·공공누리 유형·재배포 가능 여부를 증빙 링크 또는 회신으로 보관한다.",
        "- Yahoo, KRX 시세/수급, WSTS, CNN, multpl 지표는 해결 전 광고 페이지에서 제거하거나 대체한다.",
        "- 광고 요청에 로그인 ID, 이메일, Telegram ID, 즐겨찾기·메모 데이터를 전달하지 않는다.",
        "- 광고와 콘텐츠를 명확히 분리하고 무효 트래픽·자체 클릭·레이아웃 이동을 모니터링한다.",
        "",
        "### 유료 화면 출시 전",
        "",
        "- 결제 여부는 서버 entitlement로 검사하며 정적 JSON이나 CSS로만 숨기지 않는다.",
        "- 유료 제공이 허용되지 않은 원자료는 무료/유료를 막론하고 제거하거나 정식 계약 데이터로 교체한다.",
        "- 데이터 기준일, 지연 여부, 수정 가능성, 산식, 원천을 화면과 약관에 표시한다.",
        "- 디지털콘텐츠 청약철회·해지·환불·자동결제 고지를 마련한다.",
        "",
        "### 유료 알림 출시 전",
        "",
        "- 알림은 `지표명 + 관측값 + 기준값 + 관측시각 + 원출처` 형태의 사실 통지로 제한한다.",
        "- `매수`, `매도`, `분할매수`, `손절`, `목표가`, `비중 확대/축소`, `수익 보장` 문구를 금지한다.",
        "- 종목·지수·선물·수급·밸류에이션·심리 알림은 금융규제 검토 완료 전 무료 베타 또는 내부 기능으로 제한한다.",
        "- 사용자 즐겨찾기·메모·보유종목을 이용한 개인별 추천과 유료 1:1 상담은 별도 인허가 검토 없이 제공하지 않는다.",
        "",
        "## 주요 정책 참고",
        "",
        "- [Google 게시자 정책](https://support.google.com/adsense/answer/10502938?hl=en)",
        "- [Google 무효 트래픽 정책](https://support.google.com/adsense/answer/16737?hl=en)",
        "- [자본시장법 제101조](https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0101&lsiSeq=273695&urlMode=lsScJoRltInfoR)",
        "- [금융위원회 유사투자자문업 제도 안내](https://www.fsc.go.kr/edu/news/83077)",
        "- [전자상거래법 제17조](https://www.law.go.kr/LSW/lsInfoP.do?ancYnChk=0&chrClsCd=010202&efYd=20260120&lsiSeq=282793&urlMode=lsInfoP)",
        "- [개인정보 보호법 제28조의8](https://law.go.kr/LSW/lsInfoP.do?lsiSeq=283839&viewCls=lsRvsDocInfoR)",
        "",
        "## 갱신 방법",
        "",
        "```bash",
        "python scripts/generate_monetization_impact_doc.py \\",
        "  --input data/last_dashboard.json \\",
        "  --output docs/monetization-impact-by-metric.md",
        "```",
        "",
        "지표나 출처가 추가되면 `S7`로 분류되며, 해당 출처의 이용조건을 조사해 스크립트의 `SOURCE_PROFILES`에 명시적으로 추가해야 한다.",
        "",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/last_dashboard.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/monetization-impact-by-metric.md"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    document = build_document(payload, args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding="utf-8")


if __name__ == "__main__":
    main()
