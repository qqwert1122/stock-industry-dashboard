from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from openpyxl import load_workbook

from .korea_exports import fetch_itemtrade_records
from .utils import add_months, fmt_number, fmt_pct, fmt_signed, month_key, pct_change, to_float
from .wsts import find_wsts_xlsx_url, parse_wsts_sheet

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
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
INDUSTRY_ICONS = {
    "반도체": "assets/industry-icons/semiconductor.png",
    "자동차": "assets/industry-icons/auto.png",
    "전기차": "assets/industry-icons/electric-car.png",
    "조선": "assets/industry-icons/shipbuilding.png",
    "철강/소재": "assets/industry-icons/steel-materials.png",
    "화학/정유": "assets/industry-icons/oil-barrel.png",
    "은행/금융": "assets/industry-icons/finance.png",
    "건설/부동산": "assets/industry-icons/construction-real-estate.png",
    "방산": "assets/industry-icons/tank.png",
    "스테이블코인": "assets/industry-icons/bitcoin.png",
    "전력": "assets/industry-icons/power.png",
    "로봇": "assets/industry-icons/robotics.png",
    "우주": "assets/industry-icons/space.png",
    "바이오": "assets/industry-icons/biotech.png",
    "배터리": "assets/industry-icons/battery.png",
    "데이터인프라": "assets/industry-icons/data-infrastructure.png",
    "매크로": "assets/industry-icons/macro-trend.png",
}
INDUSTRY_SUMMARIES = {
    "반도체": "메모리, 파운드리, 장비, AI 인프라 수요를 함께 봅니다.",
    "자동차": "완성차 판매와 승용차 수출로 자동차 수요 사이클을 봅니다.",
    "전기차": "순수 전기차 수출과 EV 판매 proxy로 전기차 침투율 흐름을 봅니다.",
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
EN_INDUSTRY_LABELS = {
    "반도체": "Semiconductors",
    "데이터인프라": "Data Infrastructure",
    "자동차": "Automobiles",
    "전기차": "EVs",
    "조선": "Shipbuilding",
    "철강/소재": "Steel & Materials",
    "화학/정유": "Chemicals & Refining",
    "은행/금융": "Banks & Financials",
    "건설/부동산": "Construction & Real Estate",
    "방산": "Defense",
    "스테이블코인": "Stablecoins",
    "전력": "Power",
    "로봇": "Robotics",
    "우주": "Space",
    "바이오": "Biotech",
    "배터리": "Batteries",
    "매크로": "Macro",
}
EN_GROUP_LABELS = {
    "판매액": "Sales",
    "시장 매출": "Market Revenue",
    "가격/수요": "Price/Demand",
    "투자/장비": "Investment/Equipment",
    "수출": "Exports",
    "판매/수요": "Sales/Demand",
    "판매량": "Sales Volume",
    "배터리 원재료": "Battery Raw Materials",
    "운임/해운": "Shipping Rates",
    "선가/발주": "Newbuild Prices/Orders",
    "원자재 가격": "Commodity Prices",
    "중국 경기": "China Macro",
    "에너지 가격": "Energy Prices",
    "원유/원료": "Crude/Feedstock",
    "화학 스프레드 proxy": "Chemical Spread Proxy",
    "스프레드/마진": "Spreads/Margins",
    "금리": "Rates",
    "스프레드": "Spreads",
    "금리/스프레드": "Rates/Spreads",
    "은행 건전성": "Bank Asset Quality",
    "대출/건전성": "Lending/Asset Quality",
    "주택 경기": "Housing Activity",
    "건설 선행": "Construction Leads",
    "금융비용": "Financing Costs",
    "주택 시장": "Housing Market",
    "환율": "FX",
    "리스크": "Risk",
    "시장 환경": "Market Conditions",
    "핵심 지표": "Core Metrics",
    "수주잔고": "Order Backlog",
    "신규주문": "New Orders",
    "방산 수요": "Defense Demand",
    "유통량": "Supply",
    "전력 수요": "Power Demand",
    "전력 가격": "Power Prices",
    "전력 수요/생산": "Power Demand/Generation",
    "CAPEX": "CAPEX",
    "산업 장비 가격": "Industrial Equipment Prices",
    "설비투자 proxy": "Capex Proxy",
    "항공우주 가격": "Aerospace Prices",
    "우주/방산 생산": "Space/Defense Production",
    "바이오 가격": "Biotech Prices",
    "진단 가격": "Diagnostics Prices",
    "배터리 가격": "Battery Prices",
    "EV 수요": "EV Demand",
    "EV 수출": "EV Exports",
    "국방 계약": "Defense Contracts",
    "우주 계약": "Space Contracts",
    "제품 가격": "Product Prices",
    "승인 이벤트": "Approval Events",
    "임상 이벤트": "Clinical Trial Events",
    "발사 이벤트": "Launch Events",
    "충전 인프라": "Charging Infrastructure",
}
EN_FREQUENCY_LABELS = {
    "일간": "Daily",
    "주간": "Weekly",
    "월간": "Monthly",
    "분기": "Quarterly",
    "연간": "Annual",
    "비정기": "Irregular",
    "월간/비정기": "Monthly/Irregular",
    "연간/비정기": "Annual/Irregular",
}
EN_UNIT_LABELS = {
    "$": "USD",
    "$/mt": "USD/mt",
    "$/mmbtu": "USD/mmbtu",
    "$/gal": "USD/gal",
    "원": "KRW",
    "지수": "Index",
    "천건": "k",
    "백만대": "M units",
    "백만달러": "USD mn",
    "건": "events",
    "곳": "stations",
    "개": "ports",
}
EN_EXPORT_ITEM_LABELS = {
    "반도체 IC": "Semiconductor ICs",
    "반도체 소자": "Semiconductor Devices",
    "무선통신기기": "Wireless Communication Devices",
    "승용차": "Passenger Cars",
    "전기차": "EVs",
    "선박": "Ships",
    "무기류/탄약": "Arms/Ammunition",
    "항공기/우주선": "Aircraft/Spacecraft",
    "변압기": "Transformers",
    "전력 케이블": "Power Cables",
    "산업용 로봇": "Industrial Robots",
    "백신/면역제품": "Vaccines/Immune Products",
    "의약품": "Pharmaceuticals",
    "축전지": "Rechargeable Batteries",
}
EN_METRIC_NAME_LABELS = {
    "전체 스테이블코인 유통량": "Total Stablecoin Supply",
    "USDT 유통량": "USDT Supply",
    "USDC 유통량": "USDC Supply",
    "니켈 가격": "Nickel Price",
    "유럽 천연가스 가격": "Europe Natural Gas Price",
    "호주 석탄 가격": "Australian Coal Price",
    "미국 국방부 계약 의무액": "US DoD Contract Obligations",
    "미국 방산 제조 계약 의무액": "US Defense Manufacturing Contract Obligations",
    "미국 NASA 계약 의무액": "US NASA Contract Obligations",
    "FDA 의약품 승인 활동": "FDA Drug Approval Activity",
    "글로벌 Phase 3 임상 시작": "Global Phase 3 Trial Starts",
    "글로벌 우주 발사 건수": "Global Space Launch Count",
    "미국 EV 충전소 수": "US EV Charging Stations",
    "미국 EV 충전 포트 수": "US EV Charging Ports",
    "미국 10년 국채금리": "US 10Y Treasury Yield",
    "미국 2년 국채금리": "US 2Y Treasury Yield",
    "미국 10Y-2Y 금리차": "US 10Y-2Y Treasury Spread",
    "미국 BAA 회사채-10년 국채 스프레드": "US BAA Corporate-10Y Treasury Spread",
    "미국 은행 대출 연체율": "US Bank Loan Delinquency Rate",
    "미국 상업은행 총대출": "US Commercial Bank Total Loans",
    "미국 주택착공": "US Housing Starts",
    "미국 건축허가": "US Building Permits",
    "미국 30년 모기지 금리": "US 30Y Mortgage Rate",
    "미국 주택가격지수": "US Home Price Index",
    "WTI 유가": "WTI Crude Oil Price",
    "Brent 유가": "Brent Crude Oil Price",
    "미국 산업용 화학 PPI": "US Industrial Chemicals PPI",
    "철광석 가격": "Iron Ore Price",
    "구리 가격": "Copper Price",
    "알루미늄 가격": "Aluminum Price",
    "미국 자동차 판매": "US Auto Sales",
    "미국 반도체 PPI": "US Semiconductor PPI",
    "미국 방산 자본재 신규주문": "US Defense Capital Goods New Orders",
    "미국 방산 자본재 수주잔고": "US Defense Capital Goods Backlog",
    "미국 전력 생산 PPI": "US Electric Power Generation PPI",
    "미국 전기/가스 유틸리티 산업생산": "US Electric & Gas Utilities Industrial Production",
    "미국 산업용 기계 신규주문": "US Industrial Machinery New Orders",
    "미국 산업 제어장치 PPI": "US Industrial Control Equipment PPI",
    "미국 방산/우주 장비 산업생산": "US Defense/Space Equipment Industrial Production",
    "미국 항공우주 부품 PPI": "US Aerospace Parts PPI",
    "미국 생물학적 제제 PPI": "US Biological Products PPI",
    "미국 체외진단 물질 PPI": "US In-vitro Diagnostics PPI",
    "미국 저장 배터리 제조 PPI": "US Storage Battery Manufacturing PPI",
    "원/달러 환율": "USD/KRW Exchange Rate",
    "DRAM/NAND 가격 대체 지표": "DRAM/NAND Price Proxy",
    "HBM 수요 대체 지표": "HBM Demand Proxy",
    "TSMC 월매출": "TSMC Monthly Revenue",
    "ASML 수주/매출": "ASML Orders/Revenue",
    "SEMI 장비 billings": "SEMI Equipment Billings",
    "빅테크 CAPEX": "Big Tech CAPEX",
    "글로벌 EV 판매량": "Global EV Sales",
    "리튬/배터리 원재료 가격": "Lithium/Battery Raw Material Prices",
    "주요 완성차 월별 판매": "Major Automaker Monthly Sales",
    "신조선가/LNG선 발주량 대체 지표": "Newbuild Price/LNG Carrier Orders Proxy",
    "해운 운임지수": "Shipping Freight Index",
    "중국 산업생산/제조업 PMI": "China Industrial Production/Manufacturing PMI",
    "나프타/올레핀 스프레드": "Naphtha/Olefin Spread",
    "정제마진 대체 지표": "Refining Margin Proxy",
    "한국 미분양/주택가격지수": "Korea Unsold Homes/Home Price Index",
    "한국 방산 수출 수주": "Korea Defense Export Orders",
    "USDT/USDC 준비금과 발행량": "USDT/USDC Reserves and Supply",
    "전력 수요/예비율": "Power Demand/Reserve Margin",
    "산업용 로봇 설치 대수": "Industrial Robot Installations",
    "위성 발사/수주 이벤트": "Satellite Launch/Order Events",
    "FDA 신약 승인/임상 이벤트": "FDA Drug Approval/Clinical Events",
    "리튬/니켈/코발트 가격": "Lithium/Nickel/Cobalt Prices",
}
EN_MEANING_LABELS = {
    "반도체 업황의 현재 수요 강도와 재고 순환을 확인하는 월간 지표입니다.": "Monthly indicator for semiconductor demand strength and inventory cycles.",
    "글로벌 반도체 매출 흐름으로 업황의 수요 강도와 재고 순환을 확인합니다.": "Tracks global semiconductor revenue to read demand strength and inventory cycles.",
    "반도체 가격 압력과 공급자 가격 흐름을 보는 가격 proxy입니다.": "Price proxy for semiconductor pricing pressure and producer price trends.",
    "할인율과 금융주 마진 기대를 좌우하는 시장 금리입니다.": "Market rate that drives discount rates and bank margin expectations.",
    "경기 기대와 은행 순이자마진 환경을 함께 보여주는 지표입니다.": "Shows both growth expectations and the net interest margin backdrop for banks.",
    "신용 위험과 자금 조달 여건이 얼마나 빡빡한지 확인합니다.": "Measures credit risk and how tight funding conditions are.",
    "대출 자산의 질과 금융 시스템 부담을 점검합니다.": "Checks loan asset quality and stress in the financial system.",
    "은행권 신용 공급과 실물 경기의 자금 수요를 봅니다.": "Tracks bank credit supply and real-economy loan demand.",
    "건설 경기의 실제 착공 모멘텀과 주택 공급 흐름을 보여줍니다.": "Shows actual construction momentum and the housing supply pipeline.",
    "향후 착공과 건설 활동을 선행해서 보여주는 지표입니다.": "Leading indicator for future starts and construction activity.",
    "주택 구매 부담과 부동산 수요에 직접 영향을 주는 비용입니다.": "Financing cost that directly affects housing affordability and real estate demand.",
    "가계 자산 효과와 부동산 경기 방향성을 확인합니다.": "Shows household wealth effects and the direction of the housing cycle.",
    "정유, 화학 원가와 인플레이션 압력을 동시에 움직이는 원재료 가격입니다.": "Feedstock price that affects refining, chemical costs, and inflation pressure.",
    "석유 제품 가격으로 정유 제품 수요와 crack spread 방향을 간접적으로 확인합니다.": "Oil product price proxy for refined product demand and crack spread direction.",
    "화학 제품 가격 사이클과 마진 방향을 간접적으로 봅니다.": "Proxy for chemical product price cycles and margin direction.",
    "철강 원가와 중국 투자 수요를 반영하는 핵심 원재료입니다.": "Core raw material reflecting steel costs and Chinese investment demand.",
    "전기화와 제조업 경기를 민감하게 반영하는 경기 민감 금속입니다.": "Cyclical metal that is sensitive to electrification and manufacturing activity.",
    "경량 소재와 제조업 수요, 전력비 영향을 함께 받는 소재 가격입니다.": "Material price affected by lightweighting demand, manufacturing demand, and power costs.",
    "배터리 양극재 원가와 소재 업체 마진 환경을 보여주는 원재료 proxy입니다.": "Raw material proxy for battery cathode costs and materials-company margins.",
    "니켈 가격은 배터리 양극재 원가와 소재 업체 마진 환경을 보여주는 원재료 proxy입니다.": "Nickel price is a raw material proxy for battery cathode costs and materials-company margins.",
    "전력 생산 원가와 산업 에너지 비용을 좌우하는 에너지 원료 지표입니다.": "Energy feedstock indicator that drives power generation costs and industrial energy costs.",
    "천연가스 가격은 전력 생산 원가와 산업 에너지 비용을 좌우하는 에너지 원료 지표입니다.": "Natural gas price indicates power generation costs and industrial energy cost pressure.",
    "석탄 가격은 화력발전 원가와 전력 가격 압력을 확인하는 원료 proxy입니다.": "Coal price is a feedstock proxy for thermal power costs and power price pressure.",
    "완성차 수요와 소비 경기 흐름을 확인하는 판매 지표입니다.": "Sales indicator for automaker demand and consumer-cycle conditions.",
    "순수 전기차 수출 흐름으로 EV 수요와 국내 전기차 생산 모멘텀을 확인합니다.": "Tracks BEV export flows to read EV demand and domestic EV production momentum.",
    "순수 전기차 수출 흐름으로 전기차 완성차 수요와 국내 EV 생산 모멘텀을 확인합니다.": "Tracks BEV export flows to read EV demand and domestic EV production momentum.",
    "방산 발주와 생산 사이클을 통해 방산 업체의 수요 환경을 확인합니다.": "Reads defense-company demand through order and production cycles.",
    "달러 연동 스테이블코인의 유통량 변화로 온체인 달러 유동성과 결제/거래 수요를 확인합니다.": "Tracks USD-pegged stablecoin supply to read on-chain dollar liquidity and payment/trading demand.",
    "전력 생산과 가격 흐름으로 전력 인프라와 전력 수요 사이클을 확인합니다.": "Tracks power production and prices to read power infrastructure and demand cycles.",
    "빅테크 CAPEX는 AI 데이터센터, 서버, 전력 인프라 투자 수요를 보여주는 핵심 proxy입니다.": "Big Tech CAPEX is a core proxy for AI data center, server, and power infrastructure investment demand.",
    "설비투자와 로봇 부품 수요를 가늠하는 proxy 지표입니다.": "Proxy for capex and robotics component demand.",
    "항공우주 생산과 가격 흐름으로 우주 밸류체인의 수요 환경을 확인합니다.": "Reads space value-chain demand through aerospace production and price trends.",
    "바이오 의약품과 진단 제품의 가격 사이클을 확인하는 지표입니다.": "Tracks the pricing cycle for biologics and diagnostics products.",
    "배터리 제품 가격 흐름으로 셀/소재 밸류체인의 업황을 점검합니다.": "Checks battery cell/materials conditions through battery product price trends.",
    "수출주 원화 환산 매출과 외국인 수급에 영향을 주는 매크로 변수입니다.": "Macro variable affecting exporters' KRW-translated revenue and foreign investor flows.",
    "시장 위험 회피 심리와 변동성 확대 여부를 봅니다.": "Tracks risk-off sentiment and volatility expansion.",
    "해당 품목의 대외 수요와 가격/물량 사이클을 확인합니다.": "Tracks external demand and price/volume cycles for the item.",
    "투자 판단에 필요한 업황 변화를 확인합니다.": "Tracks industry changes relevant to investment decisions.",
    "미국 방산 자본재 발주 흐름으로 방산 수요와 수주 모멘텀을 확인합니다.": "Tracks US defense capital goods orders to read defense demand and order momentum.",
    "아직 매출로 인식되지 않은 방산 수주잔고의 축적과 감소를 확인합니다.": "Tracks the buildup and drawdown of defense order backlog not yet recognized as revenue.",
    "전력 생산 가격 흐름으로 전력 인프라와 유틸리티 수익 환경을 확인합니다.": "Tracks power producer prices to read power infrastructure and utility revenue conditions.",
    "유틸리티 실물 생산 흐름으로 전력 수요와 경기 민감도를 확인합니다.": "Uses utilities production to read power demand and cyclical sensitivity.",
    "설비투자와 로봇 수요에 가까운 산업용 기계 발주 흐름을 확인합니다.": "Tracks industrial machinery orders as a proxy for capex and robotics demand.",
    "로봇과 설비투자 설비에 들어가는 산업 제어장치 가격 흐름을 확인합니다.": "Tracks industrial control equipment prices used in robotics and capex equipment.",
    "우주와 방산 장비 생산 사이클을 함께 보여주는 월간 생산 지표입니다.": "Monthly production indicator for both space and defense equipment cycles.",
    "항공우주 부품 가격 흐름으로 우주 밸류체인의 비용과 수요 환경을 봅니다.": "Tracks aerospace parts prices to read cost and demand conditions in the space value chain.",
    "바이오 의약품 제조 가격 흐름으로 바이오 업황의 가격 사이클을 확인합니다.": "Tracks biologics manufacturing prices to read the biotech pricing cycle.",
    "진단 제품 가격 흐름으로 진단/바이오 수요와 가격 환경을 확인합니다.": "Tracks diagnostics product prices to read diagnostics/biotech demand and pricing conditions.",
    "저장 배터리 제조 가격 흐름으로 배터리 셀 업황과 마진 환경을 확인합니다.": "Tracks storage battery manufacturing prices to read battery cell conditions and margins.",
    "미국 국방부가 집행한 계약 의무액으로 방산 예산 집행과 수주 환경의 큰 흐름을 확인합니다.": "Uses US DoD contract obligations to read the broad trend in defense budget execution and order conditions.",
    "미국 연방 방산/항공우주 제조업 계약 의무액으로 방산 제조 밸류체인의 수주 모멘텀을 확인합니다.": "Uses US federal defense/aerospace manufacturing obligations to read order momentum across the defense manufacturing value chain.",
    "NASA 계약 의무액은 우주 장비와 서비스 수요, 정부 우주 예산 집행 흐름을 보여주는 proxy입니다.": "NASA contract obligations proxy demand for space equipment and services and government space budget execution.",
    "FDA 의약품 승인 관련 기록 수로 바이오 규제 이벤트와 신약 모멘텀을 확인합니다.": "Counts FDA drug approval records to read biotech regulatory events and new-drug momentum.",
    "Phase 3 임상 시작 건수는 후기 파이프라인 활동성과 바이오 투자심리의 이벤트 밀도를 보여줍니다.": "Phase 3 trial starts show late-stage pipeline activity and event density for biotech sentiment.",
    "글로벌 발사 건수로 우주 산업 활동성과 위성 인프라 수요를 확인합니다.": "Global launch count indicates space industry activity and satellite infrastructure demand.",
    "미국 EV 충전소 수는 전기차 보급 환경과 충전 인프라 투자 흐름을 보여주는 지표입니다.": "US EV charging station count shows EV adoption conditions and charging infrastructure investment trends.",
    "미국 EV 충전 포트 수는 전기차 이용 편의성과 인프라 확장 속도를 확인하는 지표입니다.": "US EV charging port count shows EV usability and the pace of infrastructure expansion.",
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
        ("World Bank 원자재", collect_world_bank_commodity_metrics),
        ("SEC CAPEX", collect_sec_capex_metrics),
        ("USAspending 방산", collect_usaspending_metrics),
        ("EIA", collect_eia_metrics),
        ("openFDA", collect_openfda_metrics),
        ("ClinicalTrials.gov", collect_clinical_trials_metrics),
        ("Launch Library", collect_launch_library_metrics),
        ("AFDC EV 충전", collect_afdc_metrics),
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
        "industry_labels_en": {industry: english_industry(industry) for industry in industries},
        "industry_icons": INDUSTRY_ICONS,
        "source_status": source_status,
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


def collect_world_bank_commodity_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    del today
    commodity_config = config.get("world_bank_commodities", {})
    if not commodity_config.get("enabled", True):
        return []

    items = commodity_config.get("items", [])
    if not items:
        return []

    page_url = str(
        commodity_config.get("page_url")
        or "https://www.worldbank.org/en/research/commodity-markets"
    )
    xlsx_url = str(
        commodity_config.get("download_url") or find_world_bank_monthly_xlsx_url(page_url, session)
    )
    response = session.get(xlsx_url, timeout=(5, 60))
    response.raise_for_status()
    workbook = load_workbook(BytesIO(response.content), data_only=True, read_only=True)
    sheet_name = str(commodity_config.get("sheet") or "Monthly Prices")
    sheet = workbook[sheet_name] if sheet_name in workbook.sheetnames else workbook.active
    price_table = parse_world_bank_monthly_prices(
        sheet,
        header_row=int(commodity_config.get("header_row", 5)),
        data_start_row=int(commodity_config.get("data_start_row", 7)),
    )
    history_limit = int(config.get("dashboard", {}).get("history_points", 48))

    metrics: list[dict[str, Any]] = []
    for item in items:
        column = str(item.get("column") or "").strip()
        name = str(item.get("name") or column or "World Bank 원자재 가격")
        industry = str(item.get("industry") or "철강/소재")
        unit = str(item.get("unit") or "")
        group = str(item.get("group") or "원자재 가격")
        meaning = str(item.get("meaning") or infer_metric_meaning(industry, name))

        points = world_bank_column_points(price_table, column)
        if not points:
            metrics.append(
                make_metric(
                    industry=industry,
                    name=name,
                    source="World Bank Commodity Markets Pink Sheet",
                    source_url=page_url,
                    frequency="월간",
                    automation="무료 공개 엑셀 자동 수집",
                    status="error",
                    note=f"{column} 열을 찾을 수 없음",
                    group=group,
                    meaning=meaning,
                )
            )
            continue

        scale = to_float(item.get("scale")) or 1.0
        scaled_points = [(observed_month, value * scale) for observed_month, value in points]
        latest_month, latest_value = scaled_points[-1]
        previous_value = scaled_points[-2][1] if len(scaled_points) > 1 else None
        yoy_value = find_yoy_value(scaled_points, latest_month)
        metrics.append(
            make_metric(
                industry=industry,
                name=name,
                source="World Bank Commodity Markets Pink Sheet",
                source_url=xlsx_url,
                frequency="월간",
                automation="무료 공개 엑셀 자동 수집",
                status="ok",
                value=latest_value,
                unit=unit,
                observed_at=latest_month.isoformat(),
                previous_value=previous_value,
                yoy_value=yoy_value,
                history=scaled_points[-history_limit:],
                note=str(item.get("note") or ""),
                group=group,
                meaning=meaning,
            )
        )
    return metrics


def find_world_bank_monthly_xlsx_url(page_url: str, session: requests.Session) -> str:
    response = session.get(page_url, timeout=(5, 20))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    candidates: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        lower_href = href.lower()
        if lower_href.endswith(".xlsx") and "monthly" in lower_href:
            candidates.append(urljoin(page_url, href))
        elif "cmo-historical-data-monthly" in lower_href and ".xlsx" in lower_href:
            candidates.append(urljoin(page_url, href))
    if not candidates:
        raise ValueError("World Bank 월간 원자재 엑셀 링크를 찾을 수 없음")
    return candidates[0]


def parse_world_bank_monthly_prices(
    sheet: Any, *, header_row: int, data_start_row: int
) -> dict[str, list[tuple[date, float]]]:
    columns: dict[int, str] = {}
    values: dict[str, list[tuple[date, float]]] = {}
    for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        if row_index == header_row:
            for column_index, header in enumerate(row[1:], start=1):
                if header is None:
                    continue
                name = str(header).strip()
                if name:
                    columns[column_index] = name
                    values[name] = []
            continue

        if row_index < data_start_row or not columns:
            continue

        observed_month = parse_world_bank_month(row[0] if row else None)
        if observed_month is None:
            continue
        for column_index, name in columns.items():
            if column_index >= len(row):
                continue
            value = to_float(row[column_index])
            if value is not None:
                values[name].append((observed_month, value))
    return {name: points for name, points in values.items() if points}


def world_bank_column_points(
    price_table: dict[str, list[tuple[date, float]]], column_name: str
) -> list[tuple[date, float]]:
    if column_name in price_table:
        return price_table[column_name]

    normalized_target = normalize_lookup_text(column_name)
    for name, points in price_table.items():
        if normalize_lookup_text(name) == normalized_target:
            return points
    return []


def parse_world_bank_month(value: object) -> date | None:
    if isinstance(value, datetime):
        return date(value.year, value.month, 1)
    if isinstance(value, date):
        return date(value.year, value.month, 1)

    text = str(value or "").strip()
    if not text:
        return None
    if "M" in text:
        year_text, month_text = text.split("M", 1)
        try:
            return date(int(year_text), int(month_text), 1)
        except ValueError:
            return None
    try:
        parsed = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return date(parsed.year, parsed.month, 1)


def collect_sec_capex_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    del today
    capex_config = config.get("sec_capex", {})
    if not capex_config.get("enabled", True):
        return []

    companies = capex_config.get("companies", [])
    if not companies:
        return []

    source_url = str(
        capex_config.get("source_url")
        or "https://www.sec.gov/search-filings/edgar-application-programming-interfaces"
    )
    user_agent = str(
        os.getenv("SEC_USER_AGENT")
        or capex_config.get("user_agent")
        or "stock-industry-dashboard/0.1 contact@example.com"
    )
    history_limit = int(config.get("dashboard", {}).get("history_points", 48))
    metrics: list[dict[str, Any]] = []

    for company in companies:
        raw_cik = str(company.get("cik") or "").strip()
        if not raw_cik:
            continue
        cik = raw_cik.zfill(10)
        ticker = str(company.get("ticker") or cik)
        name = str(company.get("name") or f"{ticker} CAPEX")
        metric_name = name if "CAPEX" in name.upper() else f"{name} CAPEX"
        configured_tags = capex_config.get("tags")
        tags = [str(tag) for tag in configured_tags] if isinstance(configured_tags, list) else None

        api_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        try:
            response = session.get(
                api_url,
                headers={
                    "User-Agent": user_agent,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                },
                timeout=(5, 30),
            )
            response.raise_for_status()
            points = sec_capex_points(response.json(), tags)
            if not points:
                metrics.append(
                    make_metric(
                        industry="데이터인프라",
                        name=metric_name,
                        source="SEC Company Facts API",
                        source_url=source_url,
                        frequency="분기",
                        automation="무료 공식 API 자동 수집",
                        status="error",
                        note="CAPEX 태그 관측값 없음",
                        group="CAPEX",
                        meaning=sec_capex_meaning(),
                    )
                )
                continue

            billion_points = [(observed_at, value / 1_000_000_000) for observed_at, value in points]
            latest_date, latest_value = billion_points[-1]
            previous_value = billion_points[-2][1] if len(billion_points) > 1 else None
            yoy_value = find_yoy_value(billion_points, latest_date)
            metrics.append(
                make_metric(
                    industry="데이터인프라",
                    name=metric_name,
                    source="SEC Company Facts API",
                    source_url=api_url,
                    frequency="분기",
                    automation="무료 공식 API 자동 수집",
                    status="ok",
                    value=latest_value,
                    unit="$B",
                    observed_at=latest_date.isoformat(),
                    previous_value=previous_value,
                    yoy_value=yoy_value,
                    history=billion_points[-history_limit:],
                    group="CAPEX",
                    meaning=sec_capex_meaning(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep company cards independent.
            metrics.append(
                make_metric(
                    industry="데이터인프라",
                    name=metric_name,
                    source="SEC Company Facts API",
                    source_url=source_url,
                    frequency="분기",
                    automation="무료 공식 API 자동 수집",
                    status="error",
                    note=str(exc),
                    group="CAPEX",
                    meaning=sec_capex_meaning(),
                )
            )
    return metrics


def sec_capex_points(payload: dict[str, Any], tags: list[str] | None = None) -> list[tuple[date, float]]:
    tag_candidates = tags or [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquirePropertyAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "CapitalExpenditures",
    ]
    us_gaap = payload.get("facts", {}).get("us-gaap", {})
    best_points: list[tuple[date, float]] = []
    for tag in tag_candidates:
        fact = us_gaap.get(tag, {})
        rows = fact.get("units", {}).get("USD", [])
        if not rows:
            continue

        by_period: dict[tuple[date, date], tuple[str, float]] = {}
        for row in rows:
            if str(row.get("form") or "") not in {"10-Q", "10-K"}:
                continue
            start_date = parse_iso_date(row.get("start"))
            end_date = parse_iso_date(row.get("end"))
            value = to_float(row.get("val"))
            if start_date is None or end_date is None or value is None:
                continue
            if not is_quarter_duration(start_date, end_date):
                continue
            filed = str(row.get("filed") or "")
            key = (start_date, end_date)
            if key not in by_period or filed >= by_period[key][0]:
                by_period[key] = (filed, abs(value))

        points = sorted((end_date, value) for (_, end_date), (_, value) in by_period.items())
        if points and (not best_points or points[-1][0] > best_points[-1][0]):
            best_points = points
    return best_points


def parse_iso_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def is_quarter_duration(start_date: date, end_date: date) -> bool:
    days = (end_date - start_date).days + 1
    return 70 <= days <= 110


def sec_capex_meaning() -> str:
    return "빅테크 CAPEX는 AI 데이터센터, 서버, 전력 인프라 투자 수요를 보여주는 핵심 proxy입니다."


def collect_usaspending_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    spending_config = config.get("usaspending", {})
    if not spending_config.get("enabled", True):
        return []

    items = spending_config.get("items", [])
    if not items:
        return []

    endpoint = str(
        spending_config.get("endpoint")
        or "https://api.usaspending.gov/api/v2/search/spending_over_time/"
    )
    history_limit = int(config.get("dashboard", {}).get("history_points", 48))
    metrics: list[dict[str, Any]] = []

    for item in items:
        months_back = int(item.get("months_back") or spending_config.get("months_back") or 18)
        current_month = date(today.year, today.month, 1)
        end_month = add_months(current_month, -1)
        end_date = current_month - timedelta(days=1)
        start_month = add_months(end_month, -months_back + 1)
        filters: dict[str, Any] = {
            "time_period": [
                {"start_date": start_month.isoformat(), "end_date": end_date.isoformat()}
            ],
        }
        if item.get("naics_codes"):
            filters["naics_codes"] = [str(code) for code in item.get("naics_codes", [])]
        if item.get("award_type_codes"):
            filters["award_type_codes"] = [str(code) for code in item.get("award_type_codes", [])]
        if item.get("toptier_agencies"):
            filters["toptier_agencies"] = [str(code) for code in item.get("toptier_agencies", [])]
        if item.get("awarding_agency_codes"):
            filters["awarding_agency_codes"] = [
                str(code) for code in item.get("awarding_agency_codes", [])
            ]
        if item.get("agencies"):
            filters["agencies"] = item.get("agencies", [])

        payload = {
            "group": "month",
            "subawards": False,
            "filters": filters,
        }
        name = str(item.get("name") or "미국 방산 계약 의무액")
        industry = str(item.get("industry") or "방산")
        group = str(item.get("group") or "국방 계약")
        meaning = str(
            item.get("meaning")
            or "미국 연방 방산 계약 의무액으로 방산 수주와 예산 집행 모멘텀을 확인합니다."
        )

        try:
            response = session.post(endpoint, json=payload, timeout=(5, 30))
            response.raise_for_status()
            points = parse_usaspending_monthly_amounts(response.json())
            if not points:
                metrics.append(
                    make_metric(
                        industry=industry,
                        name=name,
                        source="USAspending API",
                        source_url=endpoint,
                        frequency="월간",
                        automation="무료 공식 API 자동 수집",
                        status="error",
                        note="관측값 없음",
                        group=group,
                        meaning=meaning,
                    )
                )
                continue

            billion_points = [(observed_month, value / 1_000_000_000) for observed_month, value in points]
            latest_month, latest_value = billion_points[-1]
            previous_value = billion_points[-2][1] if len(billion_points) > 1 else None
            yoy_value = find_yoy_value(billion_points, latest_month)
            metrics.append(
                make_metric(
                    industry=industry,
                    name=name,
                    source="USAspending API",
                    source_url=endpoint,
                    frequency="월간",
                    automation="무료 공식 API 자동 수집",
                    status="ok",
                    value=latest_value,
                    unit="$B",
                    observed_at=latest_month.isoformat(),
                    previous_value=previous_value,
                    yoy_value=yoy_value,
                    history=billion_points[-history_limit:],
                    group=group,
                    meaning=meaning,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one spending item should not break the page.
            metrics.append(
                make_metric(
                    industry=industry,
                    name=name,
                    source="USAspending API",
                    source_url=endpoint,
                    frequency="월간",
                    automation="무료 공식 API 자동 수집",
                    status="error",
                    note=str(exc),
                    group=group,
                    meaning=meaning,
                )
            )
    return metrics


def parse_usaspending_monthly_amounts(payload: dict[str, Any]) -> list[tuple[date, float]]:
    points: list[tuple[date, float]] = []
    for row in payload.get("results", []):
        period = row.get("time_period", {})
        fiscal_year = period.get("fiscal_year")
        fiscal_month = period.get("month")
        value = to_float(row.get("aggregated_amount"))
        if fiscal_year is None or fiscal_month is None or value is None:
            continue
        try:
            observed_month = fiscal_month_to_calendar_date(fiscal_year, fiscal_month)
        except ValueError:
            continue
        points.append((observed_month, value))
    return sorted(points)


def fiscal_month_to_calendar_date(fiscal_year: object, fiscal_month: object) -> date:
    year = int(fiscal_year)
    month = int(fiscal_month)
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid fiscal month: {fiscal_month}")
    if month <= 3:
        return date(year - 1, month + 9, 1)
    return date(year, month - 3, 1)


def collect_eia_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    del today
    eia_config = config.get("eia", {})
    if not eia_config.get("enabled", True):
        return []

    series_config = eia_config.get("series", [])
    if not series_config:
        return []

    api_key = os.getenv("EIA_API_KEY", "").strip()
    source_url = str(eia_config.get("source_url") or "https://www.eia.gov/opendata/")
    if not api_key:
        return [
            make_metric(
                industry=str(series.get("industry") or "매크로"),
                name=str(series.get("name") or series.get("series_id")),
                source="EIA Open Data API",
                source_url=source_url,
                frequency=str(series.get("frequency") or ""),
                automation="무료 공식 API 자동 수집",
                status="needs_key",
                note="GitHub Secrets에 EIA_API_KEY 등록 필요",
                group=str(series.get("group") or ""),
                meaning=str(series.get("meaning") or ""),
            )
            for series in series_config
            if series.get("series_id")
        ]

    history_limit = int(config.get("dashboard", {}).get("history_points", 48))
    fetch_limit = max(history_limit, 80)
    metrics: list[dict[str, Any]] = []
    for series in series_config:
        series_id = str(series.get("series_id") or "").strip()
        if not series_id:
            continue

        name = str(series.get("name") or series_id)
        industry = str(series.get("industry") or "매크로")
        unit = str(series.get("unit") or "")
        frequency = str(series.get("frequency") or "")
        value_field = str(series.get("value_field") or "")
        api_url = f"https://api.eia.gov/v2/seriesid/{series_id}"

        try:
            response = session.get(
                api_url,
                params={
                    "api_key": api_key,
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "length": fetch_limit,
                },
                timeout=(5, 30),
            )
            response.raise_for_status()
            points = parse_eia_points(response.json(), value_field)
            if not points:
                metrics.append(
                    make_metric(
                        industry=industry,
                        name=name,
                        source="EIA Open Data API",
                        source_url=source_url,
                        frequency=frequency,
                        automation="무료 공식 API 자동 수집",
                        status="error",
                        note="관측값 없음",
                        group=str(series.get("group") or ""),
                        meaning=str(series.get("meaning") or ""),
                    )
                )
                continue

            scale = to_float(series.get("scale")) or 1.0
            scaled_points = [(observed_at, value * scale) for observed_at, value in points]
            latest_date, latest_value = scaled_points[-1]
            previous_value = scaled_points[-2][1] if len(scaled_points) > 1 else None
            yoy_value = find_yoy_value(scaled_points, latest_date)
            metrics.append(
                make_metric(
                    industry=industry,
                    name=name,
                    source="EIA Open Data API",
                    source_url=api_url,
                    frequency=frequency,
                    automation="무료 공식 API 자동 수집",
                    status="ok",
                    value=latest_value,
                    unit=unit,
                    observed_at=latest_date.isoformat(),
                    previous_value=previous_value,
                    yoy_value=yoy_value,
                    history=scaled_points[-history_limit:],
                    group=str(series.get("group") or ""),
                    meaning=str(series.get("meaning") or ""),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one EIA series should not break the page.
            metrics.append(
                make_metric(
                    industry=industry,
                    name=name,
                    source="EIA Open Data API",
                    source_url=source_url,
                    frequency=frequency,
                    automation="무료 공식 API 자동 수집",
                    status="error",
                    note=str(exc),
                    group=str(series.get("group") or ""),
                    meaning=str(series.get("meaning") or ""),
                )
            )
    return metrics


def parse_eia_points(payload: dict[str, Any], value_field: str = "") -> list[tuple[date, float]]:
    rows = payload.get("response", {}).get("data", [])
    points: list[tuple[date, float]] = []
    for row in rows:
        observed_at = parse_eia_period(row.get("period"))
        value = eia_row_value(row, value_field)
        if observed_at is not None and value is not None:
            points.append((observed_at, value))
    return sorted(points)


def eia_row_value(row: dict[str, Any], value_field: str = "") -> float | None:
    if value_field:
        return to_float(row.get(value_field))
    for field in ["value", "price", "sales", "generation", "revenue", "customers"]:
        value = to_float(row.get(field))
        if value is not None:
            return value
    return None


def parse_eia_period(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 4 and text.isdigit():
        return date(int(text), 1, 1)
    if len(text) == 7 and text[4] == "-":
        try:
            return date(int(text[:4]), int(text[5:7]), 1)
        except ValueError:
            return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def collect_openfda_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    openfda_config = config.get("openfda", {})
    if not openfda_config.get("enabled", True):
        return []

    items = openfda_config.get("items", [])
    if not items:
        return []

    endpoint = str(openfda_config.get("endpoint") or "https://api.fda.gov/drug/drugsfda.json")
    source_url = str(openfda_config.get("source_url") or "https://open.fda.gov/apis/drug/drugsfda/")
    api_key = os.getenv("OPENFDA_API_KEY", "").strip()
    history_limit = int(config.get("dashboard", {}).get("history_points", 48))
    metrics: list[dict[str, Any]] = []

    for item in items:
        name = str(item.get("name") or "FDA 의약품 승인 활동")
        months_back = int(item.get("months_back") or openfda_config.get("months_back") or 18)
        base_search = str(
            item.get("search")
            or "submissions.submission_status:AP"
        )
        points: list[tuple[date, float]] = []
        try:
            for month in completed_months(today, months_back):
                start_text, end_text = openfda_month_range(month)
                search = f"{base_search} AND submissions.submission_status_date:[{start_text} TO {end_text}]"
                params = {"search": search, "limit": 1}
                if api_key:
                    params["api_key"] = api_key
                response = session.get(endpoint, params=params, timeout=(5, 20))
                if response.status_code == 404:
                    total = 0
                else:
                    response.raise_for_status()
                    total = int(response.json().get("meta", {}).get("results", {}).get("total") or 0)
                points.append((month, float(total)))

            metrics.append(
                event_count_metric(
                    points=points,
                    history_limit=history_limit,
                    industry=str(item.get("industry") or "바이오"),
                    name=name,
                    source="openFDA Drugs@FDA API",
                    source_url=source_url,
                    frequency="월간",
                    group=str(item.get("group") or "승인 이벤트"),
                    meaning=str(
                        item.get("meaning")
                        or "FDA 의약품 승인 관련 기록 수로 바이오 규제 이벤트와 신약 모멘텀을 확인합니다."
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one event source should not break the page.
            metrics.append(
                make_metric(
                    industry=str(item.get("industry") or "바이오"),
                    name=name,
                    source="openFDA Drugs@FDA API",
                    source_url=source_url,
                    frequency="월간",
                    automation="무료 공개 API 자동 수집",
                    status="error",
                    note=str(exc),
                    group=str(item.get("group") or "승인 이벤트"),
                    meaning=str(item.get("meaning") or ""),
                )
            )
    return metrics


def collect_clinical_trials_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    trials_config = config.get("clinical_trials", {})
    if not trials_config.get("enabled", True):
        return []

    items = trials_config.get("items", [])
    if not items:
        return []

    endpoint = str(trials_config.get("endpoint") or "https://clinicaltrials.gov/api/v2/studies")
    source_url = str(trials_config.get("source_url") or "https://clinicaltrials.gov/data-api")
    history_limit = int(config.get("dashboard", {}).get("history_points", 48))
    metrics: list[dict[str, Any]] = []

    for item in items:
        name = str(item.get("name") or "글로벌 임상 시작 건수")
        months_back = int(item.get("months_back") or trials_config.get("months_back") or 18)
        extra_query = str(item.get("query") or "")
        points: list[tuple[date, float]] = []
        try:
            for month in completed_months(today, months_back):
                start_date, end_date = month_date_range(month)
                query = (
                    f"AREA[StartDate]RANGE[{start_date.isoformat()},{end_date.isoformat()}]"
                )
                if extra_query:
                    query = f"{query} AND {extra_query}"
                response = session.get(
                    endpoint,
                    params={
                        "format": "json",
                        "pageSize": 1,
                        "countTotal": "true",
                        "query.term": query,
                    },
                    timeout=(5, 20),
                )
                response.raise_for_status()
                points.append((month, float(response.json().get("totalCount") or 0)))

            metrics.append(
                event_count_metric(
                    points=points,
                    history_limit=history_limit,
                    industry=str(item.get("industry") or "바이오"),
                    name=name,
                    source="ClinicalTrials.gov API",
                    source_url=source_url,
                    frequency="월간",
                    group=str(item.get("group") or "임상 이벤트"),
                    meaning=str(
                        item.get("meaning")
                        or "새로 시작되는 임상시험 수로 바이오 업계의 파이프라인 활동성을 확인합니다."
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep cards independent.
            metrics.append(
                make_metric(
                    industry=str(item.get("industry") or "바이오"),
                    name=name,
                    source="ClinicalTrials.gov API",
                    source_url=source_url,
                    frequency="월간",
                    automation="무료 공식 API 자동 수집",
                    status="error",
                    note=str(exc),
                    group=str(item.get("group") or "임상 이벤트"),
                    meaning=str(item.get("meaning") or ""),
                )
            )
    return metrics


def collect_launch_library_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    launch_config = config.get("launch_library", {})
    if not launch_config.get("enabled", True):
        return []

    items = launch_config.get("items", [])
    if not items:
        return []

    endpoint = str(launch_config.get("endpoint") or "https://ll.thespacedevs.com/2.3.0/launches/")
    source_url = str(launch_config.get("source_url") or "https://thespacedevs.com/llapi")
    history_limit = int(config.get("dashboard", {}).get("history_points", 48))
    metrics: list[dict[str, Any]] = []

    for item in items:
        name = str(item.get("name") or "글로벌 우주 발사 건수")
        months_back = int(item.get("months_back") or launch_config.get("months_back") or 18)
        try:
            months = completed_months(today, months_back)
            points = launch_library_monthly_counts(session, endpoint, months)
            metrics.append(
                event_count_metric(
                    points=points,
                    history_limit=history_limit,
                    industry=str(item.get("industry") or "우주"),
                    name=name,
                    source="The Space Devs Launch Library 2 API",
                    source_url=source_url,
                    frequency="월간",
                    group=str(item.get("group") or "발사 이벤트"),
                    meaning=str(
                        item.get("meaning")
                        or "글로벌 발사 건수로 우주 산업 활동성과 위성 인프라 수요를 확인합니다."
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep cards independent.
            metrics.append(
                make_metric(
                    industry=str(item.get("industry") or "우주"),
                    name=name,
                    source="The Space Devs Launch Library 2 API",
                    source_url=source_url,
                    frequency="월간",
                    automation="무료 공개 API 자동 수집",
                    status="error",
                    note=str(exc),
                    group=str(item.get("group") or "발사 이벤트"),
                    meaning=str(item.get("meaning") or ""),
                )
            )
    return metrics


def launch_library_monthly_counts(
    session: requests.Session, endpoint: str, months: list[date]
) -> list[tuple[date, float]]:
    if not months:
        return []

    start_date, _ = month_date_range(months[0])
    _, end_date = month_date_range(months[-1])
    counts: dict[date, float] = {month: 0.0 for month in months}
    offset = 0
    limit = 100
    while True:
        params = {
            "format": "json",
            "mode": "list",
            "limit": limit,
            "offset": offset,
            "ordering": "net",
            "net__gte": f"{start_date.isoformat()}T00:00:00Z",
            "net__lte": f"{end_date.isoformat()}T23:59:59Z",
        }
        response = get_with_rate_limit_retry(session, endpoint, params=params)
        response.raise_for_status()
        payload = response.json()
        for launch in payload.get("results", []):
            launch_date = parse_iso_date(str(launch.get("net") or "")[:10])
            if launch_date is None:
                continue
            launch_month = date(launch_date.year, launch_date.month, 1)
            if launch_month in counts:
                counts[launch_month] += 1

        offset += len(payload.get("results", []))
        total = int(payload.get("count") or 0)
        if offset >= total or not payload.get("next"):
            break
    return [(month, counts[month]) for month in months]


def get_with_rate_limit_retry(
    session: requests.Session, url: str, *, params: dict[str, Any], attempts: int = 3
) -> requests.Response:
    response: requests.Response | None = None
    for attempt in range(attempts):
        response = session.get(url, params=params, timeout=(5, 20))
        if response.status_code != 429 or attempt == attempts - 1:
            return response
        retry_after = to_float(response.headers.get("Retry-After")) or 10.0
        time.sleep(min(max(retry_after, 2.0), 20.0))
    if response is None:
        raise RuntimeError("request was not attempted")
    return response


def collect_afdc_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    afdc_config = config.get("afdc", {})
    if not afdc_config.get("enabled", True):
        return []

    api_key = os.getenv("NREL_API_KEY", "").strip() or os.getenv("NLR_API_KEY", "").strip()
    source_url = str(
        afdc_config.get("source_url")
        or "https://developer.nlr.gov/docs/transportation/alt-fuel-stations-v1/"
    )
    endpoint = str(
        afdc_config.get("endpoint")
        or "https://developer.nlr.gov/api/alt-fuel-stations/v1.json"
    )
    last_updated_endpoint = str(
        afdc_config.get("last_updated_endpoint")
        or "https://developer.nlr.gov/api/alt-fuel-stations/v1/last-updated.json"
    )
    if not api_key:
        return [
            make_metric(
                industry="전기차",
                name=str(item.get("name") or "미국 EV 충전 인프라"),
                source="NLR Alternative Fuel Stations API",
                source_url=source_url,
                frequency="일간",
                automation="무료 공식 API 자동 수집",
                status="needs_key",
                note="GitHub Secrets에 NREL_API_KEY 등록 필요",
                group=str(item.get("group") or "충전 인프라"),
                meaning=str(item.get("meaning") or ""),
            )
            for item in afdc_config.get("items", [])
        ]

    response = session.get(
        endpoint,
        params={
            "api_key": api_key,
            "fuel_type": "ELEC",
            "country": str(afdc_config.get("country") or "US"),
            "limit": 1,
        },
        timeout=(5, 20),
    )
    response.raise_for_status()
    payload = response.json()
    observed_at = today
    try:
        updated_response = session.get(
            last_updated_endpoint, params={"api_key": api_key}, timeout=(5, 20)
        )
        updated_response.raise_for_status()
        updated_at = str(updated_response.json().get("last_updated") or "")
        parsed = parse_iso_date(updated_at[:10])
        if parsed is not None:
            observed_at = parsed
    except Exception:
        observed_at = today

    counts = {
        "stations": to_float(payload.get("total_results")),
        "ports": to_float(
            payload.get("station_counts", {})
            .get("fuels", {})
            .get("ELEC", {})
            .get("total")
        ),
    }
    metrics: list[dict[str, Any]] = []
    for item in afdc_config.get("items", []):
        key = str(item.get("field") or "stations")
        value = counts.get(key)
        if value is None:
            continue
        metrics.append(
            make_metric(
                industry=str(item.get("industry") or "전기차"),
                name=str(item.get("name") or "미국 EV 충전 인프라"),
                source="NLR Alternative Fuel Stations API",
                source_url=source_url,
                frequency="일간",
                automation="무료 공식 API 자동 수집",
                status="ok",
                value=value,
                unit=str(item.get("unit") or ""),
                observed_at=observed_at.isoformat(),
                previous_value=None,
                yoy_value=None,
                history=[(observed_at, value)],
                group=str(item.get("group") or "충전 인프라"),
                meaning=str(
                    item.get("meaning")
                    or "미국 EV 충전 인프라 규모로 전기차 보급 환경과 인프라 투자 흐름을 확인합니다."
                ),
            )
        )
    return metrics


def completed_months(today: date, months_back: int) -> list[date]:
    end_month = add_months(date(today.year, today.month, 1), -1)
    start_month = add_months(end_month, -months_back + 1)
    months: list[date] = []
    cursor = start_month
    while cursor <= end_month:
        months.append(cursor)
        cursor = add_months(cursor, 1)
    return months


def month_date_range(month: date) -> tuple[date, date]:
    return month, add_months(month, 1) - timedelta(days=1)


def openfda_month_range(month: date) -> tuple[str, str]:
    start_date, end_date = month_date_range(month)
    return start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d")


def event_count_metric(
    *,
    points: list[tuple[date, float]],
    history_limit: int,
    industry: str,
    name: str,
    source: str,
    source_url: str,
    frequency: str,
    group: str,
    meaning: str,
) -> dict[str, Any]:
    if not points:
        return make_metric(
            industry=industry,
            name=name,
            source=source,
            source_url=source_url,
            frequency=frequency,
            automation="무료 공개 API 자동 수집",
            status="error",
            note="관측값 없음",
            group=group,
            meaning=meaning,
        )
    latest_month, latest_value = points[-1]
    previous_value = points[-2][1] if len(points) > 1 else None
    yoy_value = find_yoy_value(points, latest_month)
    return make_metric(
        industry=industry,
        name=name,
        source=source,
        source_url=source_url,
        frequency=frequency,
        automation="무료 공개 API 자동 수집",
        status="ok",
        value=latest_value,
        unit="건",
        observed_at=latest_month.isoformat(),
        previous_value=previous_value,
        yoy_value=yoy_value,
        history=points[-history_limit:],
        group=group,
        meaning=meaning,
    )


def normalize_lookup_text(value: str) -> str:
    return " ".join(value.lower().replace("*", "").split())


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
                    "industry_en": english_industry(clean_display_text(metric["industry"])),
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
                    "next_update_label": metric["next_update_label"],
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


def english_industry(industry: str) -> str:
    return EN_INDUSTRY_LABELS.get(industry, industry)


def english_group(group: str) -> str:
    return EN_GROUP_LABELS.get(group, group)


def english_frequency(frequency: str) -> str:
    if not frequency:
        return ""
    compact = frequency.replace(" ", "")
    if compact in EN_FREQUENCY_LABELS:
        return EN_FREQUENCY_LABELS[compact]
    parts = [EN_FREQUENCY_LABELS.get(part, part) for part in compact.split("/") if part]
    return "/".join(parts) if parts else frequency


def english_unit(unit: str) -> str:
    return EN_UNIT_LABELS.get(unit, unit)


def english_export_item(name: str) -> str:
    return EN_EXPORT_ITEM_LABELS.get(name, name)


def english_metric_name(name: str) -> str:
    if name in EN_METRIC_NAME_LABELS:
        return EN_METRIC_NAME_LABELS[name]

    wsts_match = re.match(r"^WSTS 반도체 판매액( 3MMA)? - (.+)$", name)
    if wsts_match:
        suffix = " 3MMA" if wsts_match.group(1) else ""
        return f"WSTS Semiconductor Sales{suffix} - {wsts_match.group(2)}"

    export_match = re.match(r"^한국 수출 (.+)\\(([^)]+)\\)$", name)
    if export_match:
        item = english_export_item(export_match.group(1))
        return f"Korea Exports: {item} ({export_match.group(2)})"

    return name


def english_metric_meaning(meaning: str, industry: str = "") -> str:
    if meaning in EN_MEANING_LABELS:
        return EN_MEANING_LABELS[meaning]

    export_match = re.match(
        r"^(.+) 수출은 해당 품목의 대외 수요와 가격/물량 사이클을 확인하는 지표입니다\\.$",
        meaning,
    )
    if export_match:
        item = english_export_item(export_match.group(1))
        return f"{item} exports track external demand and price/volume cycles for the item."

    industry_match = re.match(r"^(.+) 업황을 해석하기 위한 보조 지표입니다\\.$", meaning)
    if industry_match:
        target_industry = english_industry(industry_match.group(1) or industry)
        return f"Supplementary indicator for interpreting {target_industry} industry conditions."

    return meaning


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
        return "설비투자 proxy"
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
        return "화학 스프레드 proxy"
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
    if "휘발유" in name or "디젤" in name:
        return "석유 제품 가격으로 정유 제품 수요와 crack spread 방향을 간접적으로 확인합니다."
    if "화학 PPI" in name:
        return "화학 제품 가격 사이클과 마진 방향을 간접적으로 봅니다."
    if "철광석" in name:
        return "철강 원가와 중국 투자 수요를 반영하는 핵심 원재료입니다."
    if "구리" in name:
        return "전기화와 제조업 경기를 민감하게 반영하는 경기 민감 금속입니다."
    if "알루미늄" in name:
        return "경량 소재와 제조업 수요, 전력비 영향을 함께 받는 소재 가격입니다."
    if "니켈" in name:
        return "배터리 양극재 원가와 소재 업체 마진 환경을 보여주는 원재료 proxy입니다."
    if "천연가스" in name or "석탄" in name:
        return "전력 생산 원가와 산업 에너지 비용을 좌우하는 에너지 원료 지표입니다."
    if "자동차 판매" in name:
        return "완성차 수요와 소비 경기 흐름을 확인하는 판매 지표입니다."
    if "전기차" in name:
        return "순수 전기차 수출 흐름으로 EV 수요와 국내 전기차 생산 모멘텀을 확인합니다."
    if "방산" in name:
        return "방산 발주와 생산 사이클을 통해 방산 업체의 수요 환경을 확인합니다."
    if "스테이블코인" in name or "USDT" in name or "USDC" in name:
        return stablecoin_meaning()
    if "전력" in name or "유틸리티" in name:
        return "전력 생산과 가격 흐름으로 전력 인프라와 전력 수요 사이클을 확인합니다."
    if industry == "데이터인프라" or "CAPEX" in name.upper():
        return sec_capex_meaning()
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
      --menu-shadow: 0 8px 24px rgba(0, 0, 0, 0.055);
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
      --menu-shadow: 0 10px 28px rgba(0, 0, 0, 0.22);
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

    body.theme-ready {
      transition: background-color 520ms ease, color 520ms ease;
    }

    body.theme-ready .sidebar,
    body.theme-ready .side-menu button,
    body.theme-ready .menu-item,
    body.theme-ready .mobile-menu-toggle,
    body.theme-ready .drawer-close,
    body.theme-ready .drawer-backdrop,
    body.theme-ready .settings-button,
    body.theme-ready .settings-menu,
    body.theme-ready .settings-menu button,
    body.theme-ready .reorder-actions button,
    body.theme-ready .currency-toggle,
    body.theme-ready .theme-toggle,
    body.theme-ready .industry,
    body.theme-ready .industry-head,
    body.theme-ready .industry-icon-wrap,
    body.theme-ready .group,
    body.theme-ready .metric,
    body.theme-ready .metric-table-wrap,
    body.theme-ready .metric-table th,
    body.theme-ready .metric-table td,
    body.theme-ready .metric-toggle,
    body.theme-ready .metric-detail-panel,
    body.theme-ready .detail-stats,
    body.theme-ready .detail-stat,
    body.theme-ready .chart,
    body.theme-ready .empty {
      transition:
        background-color 520ms ease,
        border-color 520ms ease,
        box-shadow 520ms ease,
        color 520ms ease;
    }

    body.theme-ready .chart text,
    body.theme-ready .axis-line,
    body.theme-ready .guide,
    body.theme-ready .trend-line,
    body.theme-ready .current-dot {
      transition: fill 520ms ease, stroke 520ms ease;
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
      display: grid;
      grid-template-rows: minmax(0, 1fr) auto auto;
      gap: 12px;
      padding: 14px;
      border: 0;
      border-radius: 18px;
      background: var(--sidebar);
      box-shadow: var(--menu-shadow);
      overflow: visible;
    }

    .side-menu {
      display: grid;
      gap: 7px;
      min-width: 0;
      max-width: 100%;
      min-height: 0;
      align-content: start;
      overflow-y: auto;
      padding-right: 2px;
    }

    .menu-item {
      position: relative;
      min-width: 0;
      border-radius: 12px;
    }

    .side-menu button {
      width: 100%;
      min-height: 38px;
      border: 0;
      border-radius: 12px;
      background: transparent;
      padding: 0 12px;
      text-align: left;
      font-size: 14px;
      font-weight: 720;
      cursor: pointer;
    }

    .sidebar.is-reordering .side-menu button {
      padding-right: 36px;
      cursor: grab;
    }

    .side-menu button:hover {
      background: var(--menu);
    }

    .side-menu button[aria-pressed="true"] {
      background: var(--menu-active);
    }

    .side-menu button[aria-current="true"] {
      background: var(--menu-active);
    }

    .drawer-head,
    .mobile-menu-toggle,
    .drawer-backdrop {
      display: none;
    }

    .drawer-close,
    .mobile-menu-toggle {
      width: 42px;
      height: 42px;
      border: 0;
      border-radius: 999px;
      display: none;
      place-items: center;
      background: var(--menu);
      color: var(--text);
      cursor: pointer;
      font-size: 20px;
      box-shadow: var(--menu-shadow);
    }

    .drawer-close:hover,
    .mobile-menu-toggle:hover {
      background: var(--menu-active);
    }

    .drawer-close:focus-visible,
    .mobile-menu-toggle:focus-visible {
      outline: 2px solid var(--text);
      outline-offset: 3px;
    }

    .drag-handle {
      position: absolute;
      right: 10px;
      top: 50%;
      width: 18px;
      height: 18px;
      display: grid;
      place-items: center;
      color: var(--muted);
      opacity: 0;
      pointer-events: none;
      transform: translateY(-50%);
      transition: opacity 180ms ease;
    }

    .sidebar.is-reordering .drag-handle {
      opacity: 1;
      pointer-events: auto;
      cursor: grab;
    }

    .menu-item.is-dragging {
      opacity: 0.45;
    }

    .menu-settings {
      position: relative;
      display: grid;
      gap: 8px;
    }

    .settings-button,
    .settings-menu button,
    .reorder-actions button {
      min-width: 0;
      border: 0;
      cursor: pointer;
    }

    .settings-button {
      min-height: 40px;
      border-radius: 14px;
      display: grid;
      grid-template-columns: 20px minmax(0, 1fr) 14px;
      gap: 8px;
      align-items: center;
      padding: 0 12px;
      background: var(--menu);
      color: var(--text);
      font-size: 13px;
      font-weight: 760;
      text-align: left;
    }

    .settings-button:hover,
    .settings-button[aria-expanded="true"] {
      background: var(--menu-active);
    }

    .settings-chevron {
      color: var(--muted);
      font-size: 11px;
      transition: transform 180ms ease;
    }

    .settings-button[aria-expanded="true"] .settings-chevron {
      transform: rotate(180deg);
    }

    .settings-menu {
      position: absolute;
      left: 0;
      right: 0;
      bottom: calc(100% + 8px);
      z-index: 20;
      display: grid;
      gap: 5px;
      padding: 7px;
      border-radius: 14px;
      background: var(--surface);
      box-shadow: var(--menu-shadow);
    }

    .settings-menu[hidden],
    .reorder-actions[hidden] {
      display: none;
    }

    .settings-menu button {
      min-height: 36px;
      border-radius: 10px;
      display: grid;
      grid-template-columns: 18px minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 0 9px;
      background: transparent;
      color: var(--text);
      font-size: 12.5px;
      font-weight: 720;
      text-align: left;
    }

    .settings-menu button:hover {
      background: var(--menu);
    }

    .settings-meta {
      color: var(--muted);
      font-size: 11px;
      font-weight: 760;
    }

    .reorder-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }

    .reorder-actions button {
      min-height: 38px;
      border-radius: 12px;
      font-size: 13px;
      font-weight: 780;
    }

    .reorder-cancel {
      background: var(--menu);
      color: var(--text);
    }

    .reorder-save {
      background: var(--chart-down);
      color: #ffffff;
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

    .topbar-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 0 0 auto;
    }

    h1 {
      margin: 0;
      font-size: clamp(22px, 2.2vw, 30px);
      line-height: 1.12;
      font-weight: 810;
    }

    .currency-toggle,
    .theme-toggle {
      width: 44px;
      height: 44px;
      border: 0;
      border-radius: 999px;
      display: grid;
      place-items: center;
      position: relative;
      overflow: hidden;
      background: var(--menu);
      color: var(--text);
      cursor: pointer;
      font-size: 17px;
    }

    .currency-toggle:hover,
    .theme-toggle:hover {
      background: var(--menu-active);
    }

    .currency-toggle:focus-visible,
    .theme-toggle:focus-visible {
      outline: 2px solid var(--text);
      outline-offset: 3px;
    }

    .currency-toggle {
      font-size: 16px;
      font-weight: 820;
    }

    .currency-icon {
      position: absolute;
      left: 50%;
      top: 50%;
      display: grid;
      place-items: center;
      opacity: 0;
      transform: translate(-50%, -50%) scale(0.7) rotate(-18deg);
      transition: opacity 220ms ease, transform 220ms ease;
    }

    body.currency-usd .currency-icon-dollar,
    body.currency-krw .currency-icon-won {
      opacity: 1;
      transform: translate(-50%, -50%) scale(1) rotate(0deg);
    }

    body.currency-usd .currency-icon-won,
    body.currency-krw .currency-icon-dollar {
      opacity: 0;
      transform: translate(-50%, -50%) scale(0.7) rotate(18deg);
    }

    .theme-toggle:disabled {
      cursor: default;
    }

    .theme-icon-orbit {
      position: relative;
      width: 100%;
      height: 100%;
      display: block;
    }

    .theme-icon {
      position: absolute;
      left: 50%;
      top: 50%;
      width: 1em;
      height: 1em;
      display: grid;
      place-items: center;
      color: currentColor;
      opacity: 0;
      transform: translate(-50%, -50%) translate3d(30px, 26px, 0) scale(0.72) rotate(36deg);
      transform-origin: center;
      pointer-events: none;
    }

    body:not(.theme-dark) .theme-icon-moon,
    body.theme-dark .theme-icon-sun {
      opacity: 1;
      transform: translate(-50%, -50%) translate3d(0, 0, 0) scale(1) rotate(0deg);
    }

    body:not(.theme-dark) .theme-icon-sun,
    body.theme-dark .theme-icon-moon {
      opacity: 0;
      transform: translate(-50%, -50%) translate3d(30px, 26px, 0) scale(0.72) rotate(36deg);
    }

    .theme-icon.is-exiting {
      animation: themeIconExit 520ms cubic-bezier(0.65, 0, 0.35, 1) forwards;
    }

    .theme-icon.is-entering {
      animation: themeIconEnter 520ms cubic-bezier(0.22, 1, 0.36, 1) forwards;
    }

    @keyframes themeIconExit {
      0% {
        opacity: 1;
        transform: translate(-50%, -50%) translate3d(0, 0, 0) scale(1) rotate(0deg);
      }
      45% {
        opacity: 0.92;
        transform: translate(-50%, -50%) translate3d(-14px, -12px, 0) scale(0.94) rotate(-16deg);
      }
      100% {
        opacity: 0;
        transform: translate(-50%, -50%) translate3d(-38px, 30px, 0) scale(0.66) rotate(-52deg);
      }
    }

    @keyframes themeIconEnter {
      0% {
        opacity: 0;
        transform: translate(-50%, -50%) translate3d(38px, 30px, 0) scale(0.66) rotate(52deg);
      }
      55% {
        opacity: 0.96;
        transform: translate(-50%, -50%) translate3d(14px, -12px, 0) scale(0.94) rotate(16deg);
      }
      100% {
        opacity: 1;
        transform: translate(-50%, -50%) translate3d(0, 0, 0) scale(1) rotate(0deg);
      }
    }

    @media (prefers-reduced-motion: reduce) {
      body.theme-ready,
      body.theme-ready .sidebar,
      body.theme-ready .side-menu button,
      body.theme-ready .menu-item,
      body.theme-ready .mobile-menu-toggle,
      body.theme-ready .drawer-close,
      body.theme-ready .drawer-backdrop,
      body.theme-ready .settings-button,
      body.theme-ready .settings-menu,
      body.theme-ready .settings-menu button,
      body.theme-ready .reorder-actions button,
      body.theme-ready .currency-toggle,
      body.theme-ready .theme-toggle,
      body.theme-ready .industry,
      body.theme-ready .industry-head,
      body.theme-ready .industry-icon-wrap,
      body.theme-ready .group,
      body.theme-ready .metric,
      body.theme-ready .metric-table-wrap,
      body.theme-ready .metric-table th,
      body.theme-ready .metric-table td,
      body.theme-ready .metric-toggle,
      body.theme-ready .metric-detail-panel,
      body.theme-ready .detail-stats,
      body.theme-ready .detail-stat,
      body.theme-ready .chart,
      body.theme-ready .empty,
      body.theme-ready .chart text,
      body.theme-ready .axis-line,
      body.theme-ready .guide,
      body.theme-ready .trend-line,
      body.theme-ready .current-dot {
        transition-duration: 1ms;
      }

      .theme-icon.is-exiting,
      .theme-icon.is-entering {
        animation-duration: 1ms;
      }
    }

    .industry-stack {
      display: grid;
      gap: 0;
      min-width: 0;
    }

    .industry {
      min-width: 0;
      scroll-margin-top: 22px;
      padding-bottom: 28px;
      border-bottom: 1px solid var(--line);
      background: transparent;
      box-shadow: none;
      overflow: visible;
    }

    .industry:last-child {
      padding-bottom: 0;
      border-bottom: 0;
    }

    .industry-head {
      display: grid;
      grid-template-columns: 86px minmax(0, 1fr);
      gap: 16px;
      align-items: center;
      padding: 22px 0 16px;
      border-bottom: 0;
      background: transparent;
    }

    .industry-icon-wrap {
      width: 86px;
      height: 86px;
      border-radius: 999px;
      display: grid;
      place-items: center;
      background: var(--menu);
    }

    .industry-icon {
      width: 76px;
      height: 76px;
      object-fit: contain;
      display: block;
    }

    .industry h2 {
      margin: 0;
      font-size: 20px;
      line-height: 1.18;
      font-weight: 800;
    }

    .group {
      padding: 0 0 22px;
      border-bottom: 1px solid var(--line);
    }

    .group:last-child { border-bottom: 0; }

    .group-title {
      margin-bottom: 12px;
      color: var(--text);
      font-size: 14px;
      font-weight: 800;
    }

    .metric-table-wrap {
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      border-radius: 0;
      background: var(--panel);
      overflow: hidden;
    }

    .metric-table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }

    .metric-table th {
      height: 34px;
      padding: 0 12px;
      background: var(--menu);
      color: var(--muted);
      font-size: 11px;
      font-weight: 820;
      text-align: left;
      white-space: nowrap;
    }

    .metric-table td {
      padding: 7px 12px;
      border-top: 1px solid var(--line);
      color: var(--text);
      vertical-align: middle;
    }

    .metric-row {
      cursor: pointer;
    }

    .metric-row:hover td {
      background: var(--menu);
    }

    .metric-row.is-expanded td {
      background: var(--menu-active);
    }

    .metric-name-cell { width: 22%; }
    .metric-description-cell { width: 30%; }
    .metric-date-cell { width: 11%; }
    .metric-value-cell { width: 12%; }
    .metric-chart-cell { width: 14%; }

    .metric-toggle {
      width: 100%;
      min-width: 0;
      display: block;
      align-items: center;
      padding: 0;
      border: 0;
      background: transparent;
      color: var(--text);
      text-align: left;
      cursor: pointer;
    }

    .metric-toggle:focus-visible {
      outline: 2px solid var(--text);
      outline-offset: 3px;
      border-radius: 6px;
    }

    .metric-name {
      min-width: 0;
      font-size: 13px;
      line-height: 1.26;
      font-weight: 780;
      overflow-wrap: anywhere;
    }

    .metric-description {
      margin: 0;
      color: var(--muted);
      font-size: 12.5px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }

    .metric-mobile-description {
      display: none;
    }

    .metric-date {
      color: var(--muted);
      font-size: 12px;
      font-weight: 680;
      white-space: nowrap;
    }

    .metric-current-value {
      display: block;
      color: var(--text);
      font-size: 12.5px;
      line-height: 1.25;
      font-weight: 820;
      overflow-wrap: anywhere;
    }

    .metric-value-wrap {
      display: flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
    }

    .metric-change-badge {
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      gap: 3px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1;
      font-weight: 760;
      white-space: nowrap;
    }

    .metric-change-badge i {
      font-size: 10px;
    }

    .chart-mini {
      height: 34px;
      max-height: 34px;
      border: 0;
      border-radius: 0;
      background: transparent;
    }

    .metric-detail-row td {
      padding: 0 14px;
      border-top: 0;
      background: var(--surface);
    }

    .metric-detail-panel {
      max-height: 0;
      overflow: hidden;
      opacity: 0;
      transform: translateY(-4px);
      transition:
        max-height 380ms ease,
        opacity 260ms ease,
        transform 260ms ease;
    }

    .metric-detail-row.is-open .metric-detail-panel {
      max-height: 640px;
      opacity: 1;
      transform: translateY(0);
      border-top: 1px solid var(--line);
    }

    .metric-detail-inner {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 12px;
      padding: 16px 0 18px;
    }

    .detail-stats {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px 12px;
      align-content: start;
      padding: 12px;
      border-radius: 12px;
      background: var(--menu);
    }

    .detail-stat {
      min-width: 0;
      padding: 6px 4px;
      border: 0;
      border-radius: 0;
      background: transparent;
    }

    .detail-label {
      display: block;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.2;
      font-weight: 780;
    }

    .detail-value {
      display: block;
      margin-top: 6px;
      color: var(--text);
      font-size: 16px;
      line-height: 1.15;
      font-weight: 820;
      overflow-wrap: anywhere;
    }

    .detail-note {
      grid-column: 1 / -1;
      margin: 4px 0 0;
      padding: 10px 4px 0;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 12.5px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }

    .detail-chart {
      width: 100%;
      max-width: 100%;
      overflow-x: auto;
      overflow-y: hidden;
      padding: 2px 0 10px;
      -webkit-overflow-scrolling: touch;
    }

    .detail-chart .chart {
      width: max(100%, var(--detail-chart-width, 760px));
      min-width: max(100%, var(--detail-chart-width, 760px));
      height: 190px;
      display: block;
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

      body.drawer-open {
        overflow: hidden;
      }

      .sidebar {
        position: fixed;
        inset: 0 auto 0 0;
        z-index: 70;
        width: min(320px, calc(100vw - 54px));
        max-width: calc(100vw - 54px);
        min-height: 100dvh;
        grid-template-rows: auto minmax(0, 1fr) auto auto;
        padding: 14px;
        border-radius: 0 20px 20px 0;
        overflow: visible;
        transform: translateX(calc(-100% - 24px));
        transition: transform 260ms ease;
      }

      body.drawer-open .sidebar {
        transform: translateX(0);
      }

      .drawer-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        min-width: 0;
        padding: 2px 0 4px;
        font-size: 15px;
        font-weight: 820;
      }

      .drawer-close,
      .mobile-menu-toggle {
        display: grid;
        flex: 0 0 auto;
      }

      .drawer-backdrop {
        position: fixed;
        inset: 0;
        z-index: 60;
        display: block;
        background: rgba(18, 18, 18, 0.28);
        opacity: 0;
        pointer-events: none;
        transition: opacity 220ms ease;
      }

      .drawer-backdrop[hidden] {
        display: none;
      }

      body.drawer-open .drawer-backdrop {
        opacity: 1;
        pointer-events: auto;
      }

      .side-menu {
        display: grid;
        gap: 7px;
        max-width: 100%;
        overflow-x: hidden;
        overflow-y: auto;
        padding: 0 2px 0 0;
      }

      .side-menu button {
        width: 100%;
        white-space: normal;
      }

      .sidebar.is-reordering .side-menu button {
        padding-right: 34px;
      }

      .settings-menu {
        position: static;
        order: -1;
      }

      .reorder-actions {
        grid-template-columns: 1fr 1fr;
      }

      .topbar {
        display: grid;
        grid-template-columns: 42px minmax(0, 1fr) auto;
        align-items: center;
        gap: 8px;
      }

      .topbar-actions {
        gap: 6px;
      }

      h1 {
        min-width: 0;
        font-size: clamp(18px, 5vw, 22px);
      }

      .industry-head {
        grid-template-columns: 72px minmax(0, 1fr);
        gap: 12px;
        padding: 18px 0 12px;
      }

      .industry-icon-wrap {
        width: 72px;
        height: 72px;
      }

      .industry-icon {
        width: 64px;
        height: 64px;
      }

      .industry h2 {
        font-size: 18px;
      }

      .group { padding: 0 0 18px; }

      .metric-table-wrap {
        overflow-x: visible;
        overflow-y: visible;
        -webkit-overflow-scrolling: touch;
      }

      .metric-table {
        display: table;
        width: 100%;
        min-width: 0;
        table-layout: fixed;
      }

      .metric-table thead {
        display: table-header-group;
      }

      .metric-table tbody {
        display: table-row-group;
      }

      .metric-table tr {
        display: table-row;
      }

      .metric-table td {
        display: table-cell;
      }

      .metric-table col.metric-description-cell,
      .metric-table col.metric-date-cell,
      .metric-table th:nth-child(2),
      .metric-table th:nth-child(3),
      .metric-table th:nth-child(4),
      .metric-table td.metric-description-cell,
      .metric-table td.metric-date-cell {
        display: none;
      }

      .metric-table th[data-mobile-label] {
        font-size: 0;
      }

      .metric-table th[data-mobile-label]::after {
        content: attr(data-mobile-label);
        font-size: 10.5px;
      }

      .metric-row {
        padding: 0;
        border-top: 0;
      }

      .metric-row:first-child {
        border-top: 0;
      }

      .metric-row td {
        padding: 7px 6px;
        border-top: 1px solid var(--line);
      }

      .metric-row td:not(.metric-name-cell)::before {
        content: none;
      }

      .metric-name-cell { width: 52%; }
      .metric-value-cell { width: 20%; }
      .metric-chart-cell { width: 28%; }

      .metric-name {
        font-size: 12.5px;
        line-height: 1.22;
      }

      .metric-mobile-description {
        display: -webkit-box;
        margin-top: 4px;
        color: var(--muted);
        font-size: 10.5px;
        line-height: 1.28;
        font-weight: 580;
        overflow: hidden;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 2;
      }

      .metric-current-value {
        font-size: 11.5px;
        line-height: 1.2;
      }

      .metric-value-wrap {
        flex-direction: column;
        align-items: flex-start;
        gap: 4px;
      }

      .metric-change-badge {
        font-size: 10.5px;
      }

      .metric-chart-cell .chart-mini {
        height: 30px;
        max-height: 30px;
      }

      .metric-detail-row td {
        padding: 0 6px;
      }

      .metric-detail-inner {
        gap: 8px;
        padding: 10px 0 12px;
      }

      .detail-chart {
        overflow-x: hidden;
        padding: 0 0 6px;
      }

      .detail-chart .chart {
        width: 100%;
        min-width: 100%;
        height: 126px;
      }

      .detail-stats {
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 5px 7px;
        padding: 9px;
      }

      .detail-stat {
        padding: 3px 2px;
      }

      .detail-label {
        font-size: 9.5px;
        line-height: 1.12;
      }

      .detail-value {
        margin-top: 3px;
        font-size: 12px;
        line-height: 1.12;
      }

      .detail-note {
        display: none;
      }

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
    <aside class="sidebar" id="mobileDrawer" aria-label="업종 메뉴">
      <div class="drawer-head">
        <span data-i18n="drawerTitle">메뉴</span>
        <button class="drawer-close" id="drawerClose" type="button" aria-label="메뉴 닫기">
          <i class="fa-solid fa-xmark" aria-hidden="true"></i>
        </button>
      </div>
      <nav class="side-menu" id="industryFilters" aria-label="업종 메뉴"></nav>
      <div class="menu-settings" id="menuSettings">
        <div class="settings-menu" id="settingsMenu" role="menu" hidden>
          <button type="button" role="menuitem" data-setting-action="theme">
            <i class="fa-solid fa-circle-half-stroke" aria-hidden="true"></i>
            <span data-i18n="darkMode">다크모드</span>
            <span class="settings-meta" id="themeSettingLabel"></span>
          </button>
          <button type="button" role="menuitem" data-setting-action="language">
            <i class="fa-solid fa-language" aria-hidden="true"></i>
            <span data-i18n="language">언어변경</span>
            <span class="settings-meta" id="languageSettingLabel">KO</span>
          </button>
          <button type="button" role="menuitem" data-setting-action="reorder">
            <i class="fa-solid fa-arrow-up-wide-short" aria-hidden="true"></i>
            <span data-i18n="reorderMenu">메뉴 순서변경</span>
            <span></span>
          </button>
        </div>
        <button class="settings-button" id="settingsToggle" type="button" aria-label="설정" aria-expanded="false" aria-controls="settingsMenu">
          <i class="fa-solid fa-gear" aria-hidden="true"></i>
          <span data-i18n="settings">설정</span>
          <i class="fa-solid fa-chevron-up settings-chevron" aria-hidden="true"></i>
        </button>
      </div>
      <div class="reorder-actions" id="reorderActions" hidden>
        <button class="reorder-cancel" id="reorderCancel" type="button" data-i18n="cancel">취소</button>
        <button class="reorder-save" id="reorderSave" type="button" data-i18n="save">저장</button>
      </div>
    </aside>
    <div class="drawer-backdrop" id="drawerBackdrop" hidden></div>
    <section class="content">
      <header class="topbar">
        <button class="mobile-menu-toggle" id="mobileMenuToggle" type="button" aria-label="메뉴 열기" aria-expanded="false" aria-controls="mobileDrawer">
          <i class="fa-solid fa-bars" aria-hidden="true"></i>
        </button>
        <h1 data-i18n="title">산업별 지표 대시보드</h1>
        <div class="topbar-actions">
          <button class="currency-toggle" id="currencyToggle" type="button" aria-label="원화 표시" title="원화 표시">
            <i class="fa-solid fa-dollar-sign currency-icon currency-icon-dollar" aria-hidden="true"></i>
            <i class="fa-solid fa-won-sign currency-icon currency-icon-won" aria-hidden="true"></i>
          </button>
          <button class="theme-toggle" id="themeToggle" type="button" aria-label="다크모드 전환" title="다크모드 전환">
            <span class="theme-icon-orbit" aria-hidden="true">
              <i class="fa-solid fa-moon theme-icon theme-icon-moon"></i>
              <i class="fa-solid fa-sun theme-icon theme-icon-sun"></i>
            </span>
          </button>
        </div>
      </header>
      <section class="industry-stack" id="industryStack"></section>
      <div class="empty" id="empty" data-i18n="empty">표시할 지표가 없습니다.</div>
    </section>
  </main>

  <script>
    const DASHBOARD_DATA = __DASHBOARD_JSON__;
    const state = {
      activeIndustry: "",
      isReordering: false,
      draftIndustryOrder: null,
      draggedMenuItem: null,
      language: "ko",
      currency: "usd"
    };
    const mobileDrawerQuery = window.matchMedia ? window.matchMedia("(max-width: 760px)") : { matches: false };
    let scrollSpyFrame = 0;
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
    const translations = {
      ko: {
        title: "산업별 지표 대시보드",
        settings: "설정",
        darkMode: "다크모드",
        lightMode: "라이트",
        darkModeState: "다크",
        language: "언어변경",
        reorderMenu: "메뉴 순서변경",
        cancel: "취소",
        save: "저장",
        empty: "표시할 지표가 없습니다.",
        metric: "지표",
        description: "설명",
        lastUpdated: "마지막 업데이트일",
        nextUpdate: "다음 예정일",
        chart: "차트",
        metricSummary: "지표명/설명",
        metricValueShort: "지표",
        currentValue: "현재값",
        previousChange: "전기 변화",
        previousChangePct: "전기 변화율",
        yoy: "YoY",
        visiblePeriod: "표시 기간",
        updateFrequency: "업데이트 주기",
        irregular: "비정기",
        menuLabel: "업종 메뉴",
        drawerTitle: "메뉴",
        openMenu: "메뉴 열기",
        closeMenu: "메뉴 닫기",
        toggleTheme: "다크모드 전환",
        showKrw: "원화 표시",
        showUsd: "달러 표시"
      },
      en: {
        title: "Industry Metrics Dashboard",
        settings: "Settings",
        darkMode: "Dark mode",
        lightMode: "Light",
        darkModeState: "Dark",
        language: "Language",
        reorderMenu: "Reorder menu",
        cancel: "Cancel",
        save: "Save",
        empty: "No metrics to display.",
        metric: "Metric",
        description: "Description",
        lastUpdated: "Last updated",
        nextUpdate: "Next update",
        chart: "Chart",
        metricSummary: "Metric/description",
        metricValueShort: "Value",
        currentValue: "Current",
        previousChange: "Previous change",
        previousChangePct: "Previous %",
        yoy: "YoY",
        visiblePeriod: "Period",
        updateFrequency: "Frequency",
        irregular: "Irregular",
        menuLabel: "Industry menu",
        drawerTitle: "Menu",
        openMenu: "Open menu",
        closeMenu: "Close menu",
        toggleTheme: "Toggle dark mode",
        showKrw: "Show KRW",
        showUsd: "Show USD"
      }
    };

    function t(key) {
      return translations[state.language]?.[key] || translations.ko[key] || key;
    }

    function localizedIndustry(industry) {
      if (state.language !== "en") return industry || "";
      return DASHBOARD_DATA.industry_labels_en?.[industry] || industry || "";
    }

    function localizedField(item, field) {
      if (!item) return "";
      if (state.language === "en") {
        return item[`${field}_en`] || item[field] || "";
      }
      return item[field] || "";
    }

    function localizedGroup(group, items = []) {
      if (state.language !== "en") return group || "";
      const first = items.find((item) => item.group === group && item.group_en);
      return first?.group_en || group || "";
    }

    function localizedUnit(metric) {
      if (!metric) return "";
      return state.language === "en" ? (metric.unit_en || metric.unit || "") : (metric.unit || "");
    }

    function formatMetricNumberWithUnit(value, unit, signed = false, isChange = false) {
      if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
      const text = numberText(value, signed);
      if (unit === "$B") {
        const prefix = signed ? (value > 0 ? "+" : value < 0 ? "-" : "") : "";
        return `${prefix}$${numberText(Math.abs(value))}B`;
      }
      if (unit === "%") return `${text}${isChange ? "%p" : "%"}`;
      if (!unit) return text;
      return `${text} ${unit}`;
    }

    function numberText(value, signed = false) {
      if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
      const abs = Math.abs(value);
      const digits = abs >= 100 ? 1 : 2;
      const formatted = abs.toLocaleString(state.language === "en" ? "en-US" : "ko-KR", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
      });
      if (!signed || value === 0) return formatted;
      return `${value > 0 ? "+" : "-"}${formatted}`;
    }

    function dollarUnitScale(metric) {
      const unit = String(metric.unit || "");
      const rate = usdKrwRate();
      const english = state.language === "en";
      if (unit === "$B") return { scale: rate / 1000, unit: english ? "tn KRW" : "조원" };
      if (unit.includes("백만달러")) {
        return english ? { scale: rate / 1000, unit: "bn KRW" } : { scale: rate / 100, unit: "억원" };
      }
      if (unit === "$" || unit.includes("달러") || unit.toUpperCase().includes("USD")) {
        return { scale: rate, unit: english ? "KRW" : "원" };
      }
      return null;
    }

    function isDollarMetric(metric) {
      return Boolean(dollarUnitScale(metric));
    }

    function usdKrwRate() {
      const match = DASHBOARD_DATA.metrics.find((metric) => {
        const name = String(metric.name || "").toUpperCase();
        return typeof metric.value === "number" &&
          Number.isFinite(metric.value) &&
          String(metric.unit || "") === "원" &&
          (name.includes("환율") || name.includes("원/달러") || name.includes("USD/KRW"));
      });
      return match?.value || 1350;
    }

    function displayMetricValue(metric) {
      const scale = state.currency === "krw" ? dollarUnitScale(metric) : null;
      if (scale && typeof metric.value === "number" && Number.isFinite(metric.value)) {
        const separator = state.language === "en" ? " " : "";
        return `${numberText(metric.value * scale.scale)}${separator}${scale.unit}`;
      }
      if (state.language === "en" && typeof metric.value === "number" && Number.isFinite(metric.value)) {
        return formatMetricNumberWithUnit(metric.value, localizedUnit(metric));
      }
      if (!scale || typeof metric.value !== "number" || !Number.isFinite(metric.value)) {
        return metric.display_value;
      }
      return `${numberText(metric.value * scale.scale)}${scale.unit}`;
    }

    function displayMetricChange(metric) {
      const scale = state.currency === "krw" ? dollarUnitScale(metric) : null;
      if (scale && typeof metric.change_abs === "number" && Number.isFinite(metric.change_abs)) {
        const separator = state.language === "en" ? " " : "";
        return `${numberText(metric.change_abs * scale.scale, true)}${separator}${scale.unit}`;
      }
      if (state.language === "en" && typeof metric.change_abs === "number" && Number.isFinite(metric.change_abs)) {
        return formatMetricNumberWithUnit(metric.change_abs, localizedUnit(metric), true, true);
      }
      if (!scale || typeof metric.change_abs !== "number" || !Number.isFinite(metric.change_abs)) {
        return metric.change_abs_label;
      }
      return `${numberText(metric.change_abs * scale.scale, true)}${scale.unit}`;
    }

    function displayHistory(history, metric) {
      const scale = state.currency === "krw" ? dollarUnitScale(metric || {}) : null;
      if (!scale) return history;
      return (history || []).map((point) => ({
        ...point,
        value: point.value * scale.scale
      }));
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

    function directionClass(value) {
      if (typeof value !== "number" || !Number.isFinite(value) || value === 0) return "";
      return value > 0 ? "positive" : "negative";
    }

    function trendIconClass(value) {
      if (typeof value !== "number" || !Number.isFinite(value) || value === 0) return "fa-minus";
      return value > 0 ? "fa-arrow-trend-up" : "fa-arrow-trend-down";
    }

    function metricChangeBadge(metric) {
      const className = directionClass(metric.change_pct);
      const label = metric.change_pct_label || "n/a";
      return `<span class="metric-change-badge ${className}">
        <i class="fa-solid ${trendIconClass(metric.change_pct)}" aria-hidden="true"></i>
        <span>${escapeHtml(label)}</span>
      </span>`;
    }

    function groupRank(group) {
      const index = groupOrder.indexOf(group);
      return index === -1 ? 999 : index;
    }

    function baseVisibleIndustries() {
      return DASHBOARD_DATA.industries.filter((industry) =>
        DASHBOARD_DATA.metrics.some((metric) => metric.industry === industry)
      );
    }

    function storedIndustryOrder() {
      try {
        const parsed = JSON.parse(localStorage.getItem("dashboard-industry-order") || "[]");
        return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
      } catch {
        return [];
      }
    }

    function orderedIndustries(industries, order = null) {
      const selectedOrder = order || state.draftIndustryOrder || storedIndustryOrder();
      const rank = new Map(selectedOrder.map((industry, index) => [industry, index]));
      return [...industries].sort((a, b) => {
        const aRank = rank.has(a) ? rank.get(a) : Number.MAX_SAFE_INTEGER;
        const bRank = rank.has(b) ? rank.get(b) : Number.MAX_SAFE_INTEGER;
        if (aRank !== bRank) return aRank - bRank;
        return industries.indexOf(a) - industries.indexOf(b);
      });
    }

    function visibleIndustries() {
      return orderedIndustries(baseVisibleIndustries());
    }

    function industryId(industry) {
      return `industry-${Array.from(industry).map((char) => char.charCodeAt(0).toString(36)).join("-")}`;
    }

    function setActiveIndustry(industry) {
      if (!industry || state.activeIndustry === industry) return;
      state.activeIndustry = industry;
      document.querySelectorAll("[data-industry]").forEach((button) => {
        const active = button.dataset.industry === industry;
        button.setAttribute("aria-pressed", String(active));
        button.setAttribute("aria-current", String(active));
      });
    }

    function renderFilters() {
      const industries = visibleIndustries();
      if (!state.activeIndustry && industries.length) {
        state.activeIndustry = industries[0];
      }
      document.getElementById("industryFilters").innerHTML = industries.map((industry) => `
        <div class="menu-item" data-menu-item data-industry-item="${escapeHtml(industry)}" draggable="${state.isReordering}">
          <button type="button" data-industry="${escapeHtml(industry)}" data-target="${industryId(industry)}" aria-pressed="${state.activeIndustry === industry}" aria-current="${state.activeIndustry === industry}" ${state.isReordering ? 'tabindex="-1"' : ""}>
            ${escapeHtml(localizedIndustry(industry))}
          </button>
          <span class="drag-handle" aria-hidden="true"><i class="fa-solid fa-grip-lines"></i></span>
        </div>
      `).join("");
      document.querySelectorAll("[data-industry]").forEach((button) => {
        button.addEventListener("click", () => {
          if (state.isReordering) return;
          const industry = button.dataset.industry;
          const target = document.getElementById(button.dataset.target);
          if (!industry || !target) return;
          setActiveIndustry(industry);
          target.scrollIntoView({ behavior: "smooth", block: "start" });
          closeDrawerOnMobile();
        });
      });
      initMenuDrag();
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
      if (!Number.isFinite(year)) return "";
      const shortYear = String(year).padStart(2, "0");
      return state.language === "en" ? shortYear : `${shortYear}년`;
    }

    function chartDateParts(dateText) {
      const match = String(dateText || "").match(/^(\\d{4})-(\\d{1,2})/);
      if (!match) return null;
      const year = Number(match[1]);
      const month = Number(match[2]);
      if (!Number.isFinite(year) || !Number.isFinite(month)) return null;
      return { year, month };
    }

    function detailTickLabel(point, seenYears) {
      const date = chartDateParts(point.date);
      if (!date) return "";
      if (!seenYears.has(date.year)) {
        seenYears.add(date.year);
        return yearLabel(point.date);
      }
      if ([3, 6, 9].includes(date.month)) {
        return String(date.month);
      }
      return "";
    }

    function chartTicks(history, left, right, includeQuarterMonths = false) {
      const seen = new Set();
      const seenYears = new Set();
      const ticks = [];
      history.forEach((point, index) => {
        const label = includeQuarterMonths
          ? detailTickLabel(point, seenYears)
          : yearLabel(point.date);
        if (!label) return;
        const key = includeQuarterMonths ? `${point.date}-${label}` : String(point.date).slice(0, 4);
        if (seen.has(key)) return;
        seen.add(key);
        const x = left + (index / Math.max(history.length - 1, 1)) * (right - left);
        ticks.push({ label, x });
      });
      if (ticks.length === 1 && history.length > 1) {
        ticks.push({ label: yearLabel(history[history.length - 1].date), x: right });
      }
      return ticks.filter((tick, index) => index === 0 || tick.label !== ticks[index - 1].label);
    }

    function separatedLabelPositions(levels, minY, maxY, minGap = 13) {
      const sorted = [...levels]
        .sort((a, b) => a.y - b.y)
        .map((level) => ({ ...level, labelY: Math.min(maxY, Math.max(minY, level.y)) }));
      for (let index = 1; index < sorted.length; index += 1) {
        if (sorted[index].labelY - sorted[index - 1].labelY < minGap) {
          sorted[index].labelY = sorted[index - 1].labelY + minGap;
        }
      }
      for (let index = sorted.length - 1; index >= 0; index -= 1) {
        if (sorted[index].labelY > maxY) {
          sorted[index].labelY = maxY;
        }
        if (index > 0 && sorted[index].labelY - sorted[index - 1].labelY < minGap) {
          sorted[index - 1].labelY = sorted[index].labelY - minGap;
        }
      }
      return sorted.map((level) => ({
        ...level,
        labelY: Math.min(maxY, Math.max(minY, level.labelY))
      }));
    }

    function detailChartWidth(points) {
      const count = Array.isArray(points) ? points.length : 0;
      return Math.max(760, count * 54);
    }

    function miniChart(history, metric = null) {
      const displayPoints = displayHistory(history, metric);
      const chartClass = "chart chart-mini";
      if (!displayPoints || displayPoints.length < 2) {
        return `<svg class="${chartClass}" viewBox="0 0 160 36" role="img" aria-label="trend unavailable"></svg>`;
      }
      const values = displayPoints.map((point) => point.value).filter((value) => typeof value === "number" && Number.isFinite(value));
      const min = Math.min(...values);
      const max = Math.max(...values);
      const latest = displayPoints[displayPoints.length - 1].value;
      const first = displayPoints[0].value;
      const span = max - min || 1;
      const left = 4;
      const right = 156;
      const top = 5;
      const bottom = 31;
      const yFor = (value) => bottom - ((value - min) / span) * (bottom - top);
      const points = displayPoints.map((point, index) => {
        const x = left + (index / Math.max(displayPoints.length - 1, 1)) * (right - left);
        const y = yFor(point.value);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      const trend = latest >= first ? "up" : "down";
      return `<svg class="${chartClass}" viewBox="0 0 160 36" role="img" aria-label="trend">
        <polyline points="${points}" class="trend-line ${trend}"></polyline>
      </svg>`;
    }

    function chart(history, extraClass = "", metric = null) {
      if (extraClass.split(" ").includes("chart-mini")) {
        return miniChart(history, metric);
      }
      const displayPoints = displayHistory(history, metric);
      const chartClass = `chart${extraClass ? ` ${extraClass}` : ""}`;
      const isDetailChart = extraClass.split(" ").includes("chart-detail");
      const svgWidth = isDetailChart ? detailChartWidth(displayPoints) : 360;
      const chartStyle = isDetailChart ? ` style="--detail-chart-width: ${svgWidth}px"` : "";
      const left = 62;
      const right = svgWidth - 16;
      if (!displayPoints || displayPoints.length < 2) {
        return `<svg class="${chartClass}"${chartStyle} viewBox="0 0 ${svgWidth} 158" role="img" aria-label="trend unavailable">
          <line x1="${left}" y1="72" x2="${right}" y2="72" class="guide"></line>
        </svg>`;
      }
      const values = displayPoints.map((point) => point.value).filter((value) => typeof value === "number" && Number.isFinite(value));
      const min = Math.min(...values);
      const max = Math.max(...values);
      const latest = displayPoints[displayPoints.length - 1].value;
      const first = displayPoints[0].value;
      const span = max - min || 1;
      const top = 16;
      const bottom = 116;
      const yFor = (value) => bottom - ((value - min) / span) * (bottom - top);
      const points = displayPoints.map((point, index) => {
        const x = left + (index / Math.max(displayPoints.length - 1, 1)) * (right - left);
        const y = yFor(point.value);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      const trend = latest >= first ? "up" : "down";
      const levelValues = [];
      [max, latest, min].forEach((value) => {
        if (!levelValues.some((existing) => Math.abs(existing - value) < 1e-9)) {
          levelValues.push(value);
        }
      });
      const levels = separatedLabelPositions(
        levelValues.map((value) => ({
          value,
          label: formatAxisValue(value),
          y: yFor(value)
        })),
        14,
        118
      );
      const yGuides = levels.map((level) => {
        const y = level.y;
        const labelY = level.labelY;
        const connector = Math.abs(labelY - y) > 7
          ? `<line x1="50" y1="${labelY.toFixed(1)}" x2="${left}" y2="${y.toFixed(1)}" class="guide"></line>`
          : "";
        return `<g>
          <text x="8" y="${(labelY + 3).toFixed(1)}">${level.label}</text>
          ${connector}
          <line x1="${left}" y1="${y.toFixed(1)}" x2="${right}" y2="${y.toFixed(1)}" class="guide"></line>
        </g>`;
      }).join("");
      const xGuides = chartTicks(history, left, right, isDetailChart).map((tick) => `
        <text x="${tick.x.toFixed(1)}" y="146" text-anchor="middle">${tick.label}</text>
      `).join("");
      const latestX = right;
      const latestY = yFor(latest);
      return `<svg class="${chartClass}"${chartStyle} viewBox="0 0 ${svgWidth} 158" role="img" aria-label="trend">
        ${yGuides}
        <line x1="${left}" y1="126" x2="${right}" y2="126" class="axis-line"></line>
        ${xGuides}
        <polyline points="${points}" class="trend-line ${trend}"></polyline>
        <circle cx="${latestX}" cy="${latestY.toFixed(1)}" r="4" class="current-dot ${trend}"></circle>
      </svg>`;
    }

    function dateText(value) {
      if (!value) return t("irregular");
      if (String(value).includes("비정기")) return t("irregular");
      const match = String(value).match(/^(\\d{4})[.-](\\d{1,2})(?:[.-](\\d{1,2}))?/);
      if (!match) return value;
      if (state.language === "en") {
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const year = match[1];
        const month = monthNames[Math.max(0, Math.min(11, Number(match[2]) - 1))];
        return match[3] ? `${month} ${Number(match[3])}, ${year}` : `${month} ${year}`;
      }
      const year = match[1].slice(2);
      const month = String(Number(match[2]));
      const day = match[3] ? ` ${Number(match[3])}일` : "";
      return `${year}년 ${month}월${day}`;
    }

    function detailStat(label, value, className = "") {
      return `<div class="detail-stat">
        <span class="detail-label">${escapeHtml(label)}</span>
        <strong class="detail-value ${className}">${escapeHtml(value)}</strong>
      </div>`;
    }

    function metricDetail(metric) {
      return `<div class="metric-detail-panel">
        <div class="metric-detail-inner">
          <div class="detail-chart">${chart(metric.history, "chart-detail", metric)}</div>
          <div class="detail-stats">
            ${detailStat(t("currentValue"), displayMetricValue(metric))}
            ${detailStat(t("previousChange"), displayMetricChange(metric), directionClass(metric.change_abs))}
            ${detailStat(t("previousChangePct"), metric.change_pct_label, directionClass(metric.change_pct))}
            ${detailStat(t("yoy"), metric.yoy_pct_label, directionClass(metric.yoy_pct))}
            ${detailStat(t("visiblePeriod"), metric.period_label || metric.observed_label || "")}
            ${detailStat(t("updateFrequency"), localizedField(metric, "frequency") || t("irregular"))}
            <p class="detail-note">${escapeHtml(localizedField(metric, "meaning"))}</p>
          </div>
        </div>
      </div>`;
    }

    function metricRows(metric) {
      const detailId = `metric-detail-${metric.id}`;
      return `<tr class="metric-row" data-metric-row data-detail-id="${detailId}">
        <td class="metric-name-cell" data-label="${escapeHtml(t("metric"))}">
          <button class="metric-toggle" type="button" data-metric-toggle aria-expanded="false" aria-controls="${detailId}">
            <span class="metric-name">${escapeHtml(localizedField(metric, "name"))}</span>
            <span class="metric-mobile-description">${escapeHtml(localizedField(metric, "meaning"))}</span>
          </button>
        </td>
        <td class="metric-description-cell" data-label="${escapeHtml(t("description"))}">
          <p class="metric-description">${escapeHtml(localizedField(metric, "meaning"))}</p>
        </td>
        <td class="metric-date-cell" data-label="${escapeHtml(t("lastUpdated"))}">
          <span class="metric-date">${escapeHtml(dateText(metric.observed_label))}</span>
        </td>
        <td class="metric-date-cell" data-label="${escapeHtml(t("nextUpdate"))}">
          <span class="metric-date">${escapeHtml(dateText(metric.next_update_label))}</span>
        </td>
        <td class="metric-value-cell" data-label="${escapeHtml(t("currentValue"))}">
          <span class="metric-value-wrap">
            <span class="metric-current-value">${escapeHtml(displayMetricValue(metric))}</span>
            ${metricChangeBadge(metric)}
          </span>
        </td>
        <td class="metric-chart-cell" data-label="${escapeHtml(t("chart"))}">
          ${chart(metric.history, "chart-mini", metric)}
        </td>
      </tr>
      <tr class="metric-detail-row" id="${detailId}" aria-hidden="true">
        <td colspan="6">${metricDetail(metric)}</td>
      </tr>`;
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
            <div class="group-title">${escapeHtml(localizedGroup(group, items))}</div>
            <div class="metric-table-wrap">
              <table class="metric-table">
                <colgroup>
                  <col class="metric-name-cell">
                  <col class="metric-description-cell">
                  <col class="metric-date-cell">
                  <col class="metric-date-cell">
                  <col class="metric-value-cell">
                  <col class="metric-chart-cell">
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col" data-mobile-label="${escapeHtml(t("metricSummary"))}">${escapeHtml(t("metric"))}</th>
                    <th scope="col">${escapeHtml(t("description"))}</th>
                    <th scope="col">${escapeHtml(t("lastUpdated"))}</th>
                    <th scope="col">${escapeHtml(t("nextUpdate"))}</th>
                    <th scope="col" data-mobile-label="${escapeHtml(t("metricValueShort"))}">${escapeHtml(t("currentValue"))}</th>
                    <th scope="col" data-mobile-label="${escapeHtml(t("chart"))}">${escapeHtml(t("chart"))}</th>
                  </tr>
                </thead>
                <tbody>${items.map(metricRows).join("")}</tbody>
              </table>
            </div>
          </section>
        `).join("");

      return `<article class="industry" id="${industryId(industry)}" data-industry-section data-industry-name="${escapeHtml(industry)}">
        <div class="industry-head">
          <div class="industry-icon-wrap">${icon ? `<img class="industry-icon" src="${escapeHtml(icon)}" alt="">` : ""}</div>
          <div>
            <h2>${escapeHtml(localizedIndustry(industry))}</h2>
          </div>
        </div>
        <div class="group-stack">${groupHtml}</div>
      </article>`;
    }

    function renderIndustries() {
      const metrics = DASHBOARD_DATA.metrics;
      const stack = document.getElementById("industryStack");
      document.getElementById("empty").style.display = metrics.length ? "none" : "block";
      const byIndustry = metrics.reduce((map, metric) => {
        map.set(metric.industry, [...(map.get(metric.industry) || []), metric]);
        return map;
      }, new Map());
      stack.innerHTML = visibleIndustries()
        .filter((industry) => byIndustry.has(industry))
        .map((industry) => renderIndustry(industry, byIndustry.get(industry)))
        .join("");
      initMetricRows();
      updateActiveFromScroll();
    }

    function toggleMetricRow(row) {
      const detail = document.getElementById(row.dataset.detailId);
      const toggle = row.querySelector("[data-metric-toggle]");
      if (!detail || !toggle) return;
      const expanded = !row.classList.contains("is-expanded");
      row.classList.toggle("is-expanded", expanded);
      detail.classList.toggle("is-open", expanded);
      detail.setAttribute("aria-hidden", String(!expanded));
      toggle.setAttribute("aria-expanded", String(expanded));
      if (expanded) {
        const scroller = detail.querySelector(".detail-chart");
        if (scroller) {
          requestAnimationFrame(() => {
            scroller.scrollLeft = scroller.scrollWidth;
          });
        }
      }
    }

    function initMetricRows() {
      document.querySelectorAll("[data-metric-row]").forEach((row) => {
        row.addEventListener("click", () => toggleMetricRow(row));
      });
    }

    function currentMenuOrder() {
      return [...document.querySelectorAll("[data-menu-item]")]
        .map((item) => item.dataset.industryItem)
        .filter(Boolean);
    }

    function dragDirection(container) {
      return getComputedStyle(container).display === "flex" ? "horizontal" : "vertical";
    }

    function initMenuDrag() {
      document.querySelectorAll("[data-menu-item]").forEach((item) => {
        item.draggable = state.isReordering;
        item.addEventListener("dragstart", (event) => {
          if (!state.isReordering) {
            event.preventDefault();
            return;
          }
          state.draggedMenuItem = item;
          item.classList.add("is-dragging");
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", item.dataset.industryItem || "");
        });
        item.addEventListener("dragend", () => {
          item.classList.remove("is-dragging");
          state.draggedMenuItem = null;
          state.draftIndustryOrder = currentMenuOrder();
        });
      });

      const menu = document.getElementById("industryFilters");
      menu.ondragover = (event) => {
        if (!state.isReordering || !state.draggedMenuItem) return;
        event.preventDefault();
        const target = event.target.closest("[data-menu-item]");
        if (!target || target === state.draggedMenuItem || !menu.contains(target)) return;
        const rect = target.getBoundingClientRect();
        const horizontal = dragDirection(menu) === "horizontal";
        const insertAfter = horizontal
          ? event.clientX > rect.left + rect.width / 2
          : event.clientY > rect.top + rect.height / 2;
        menu.insertBefore(state.draggedMenuItem, insertAfter ? target.nextSibling : target);
      };
      menu.ondrop = (event) => {
        if (!state.isReordering) return;
        event.preventDefault();
        state.draftIndustryOrder = currentMenuOrder();
      };
    }

    function setSettingsOpen(open) {
      const toggle = document.getElementById("settingsToggle");
      const menu = document.getElementById("settingsMenu");
      toggle.setAttribute("aria-expanded", String(open));
      menu.hidden = !open;
    }

    function updateThemeSettingLabel() {
      const label = document.getElementById("themeSettingLabel");
      if (!label) return;
      label.textContent = document.body.classList.contains("theme-dark") ? t("darkModeState") : t("lightMode");
    }

    function updateLanguageText() {
      document.documentElement.lang = state.language;
      document.querySelectorAll("[data-i18n]").forEach((element) => {
        element.textContent = t(element.dataset.i18n);
      });
      document.querySelector(".side-menu")?.setAttribute("aria-label", t("menuLabel"));
      document.getElementById("mobileDrawer")?.setAttribute("aria-label", t("menuLabel"));
      document.getElementById("mobileMenuToggle")?.setAttribute("aria-label", t("openMenu"));
      document.getElementById("drawerClose")?.setAttribute("aria-label", t("closeMenu"));
      document.getElementById("settingsToggle")?.setAttribute("aria-label", t("settings"));
      document.getElementById("themeToggle")?.setAttribute("aria-label", t("toggleTheme"));
      document.getElementById("themeToggle")?.setAttribute("title", t("toggleTheme"));
      const languageLabel = document.getElementById("languageSettingLabel");
      if (languageLabel) languageLabel.textContent = state.language === "ko" ? "KO" : "EN";
      updateThemeSettingLabel();
      updateCurrencyButton();
    }

    function setLanguage(language) {
      state.language = language === "en" ? "en" : "ko";
      localStorage.setItem("dashboard-language", state.language);
      updateLanguageText();
      renderFilters();
      renderIndustries();
    }

    function initLanguage() {
      state.language = localStorage.getItem("dashboard-language") === "en" ? "en" : "ko";
      updateLanguageText();
    }

    function updateReorderControls() {
      document.querySelector(".sidebar")?.classList.toggle("is-reordering", state.isReordering);
      document.getElementById("reorderActions").hidden = !state.isReordering;
    }

    function startMenuReorder() {
      state.isReordering = true;
      state.draftIndustryOrder = visibleIndustries();
      setSettingsOpen(false);
      updateReorderControls();
      renderFilters();
    }

    function cancelMenuReorder() {
      state.isReordering = false;
      state.draftIndustryOrder = null;
      updateReorderControls();
      renderFilters();
    }

    function saveMenuReorder() {
      const order = currentMenuOrder();
      localStorage.setItem("dashboard-industry-order", JSON.stringify(order));
      state.isReordering = false;
      state.draftIndustryOrder = null;
      updateReorderControls();
      renderFilters();
      renderIndustries();
    }

    function initSettings() {
      const settings = document.getElementById("menuSettings");
      const toggle = document.getElementById("settingsToggle");
      toggle.addEventListener("click", () => {
        setSettingsOpen(toggle.getAttribute("aria-expanded") !== "true");
      });
      document.addEventListener("click", (event) => {
        if (!settings.contains(event.target)) setSettingsOpen(false);
      });
      document.querySelector('[data-setting-action="theme"]').addEventListener("click", () => {
        animateThemeToggle(document.body.classList.contains("theme-dark") ? "light" : "dark");
      });
      document.querySelector('[data-setting-action="language"]').addEventListener("click", () => {
        setLanguage(state.language === "ko" ? "en" : "ko");
      });
      document.querySelector('[data-setting-action="reorder"]').addEventListener("click", startMenuReorder);
      document.getElementById("reorderCancel").addEventListener("click", cancelMenuReorder);
      document.getElementById("reorderSave").addEventListener("click", saveMenuReorder);
      updateReorderControls();
    }

    function applyTheme(theme) {
      const isDark = theme === "dark";
      document.body.classList.toggle("theme-dark", isDark);
      localStorage.setItem("dashboard-theme", isDark ? "dark" : "light");
      updateThemeSettingLabel();
    }

    function animateThemeToggle(nextTheme) {
      const toggle = document.getElementById("themeToggle");
      const isDark = document.body.classList.contains("theme-dark");
      const outgoing = toggle.querySelector(isDark ? ".theme-icon-sun" : ".theme-icon-moon");
      const incoming = toggle.querySelector(isDark ? ".theme-icon-moon" : ".theme-icon-sun");
      toggle.disabled = true;
      toggle.querySelectorAll(".theme-icon").forEach((icon) => {
        icon.classList.remove("is-exiting", "is-entering");
      });
      void toggle.offsetWidth;
      outgoing.classList.add("is-exiting");
      incoming.classList.add("is-entering");
      applyTheme(nextTheme);
      window.setTimeout(() => {
        outgoing.classList.remove("is-exiting");
        incoming.classList.remove("is-entering");
        toggle.disabled = false;
      }, 540);
    }

    function initTheme() {
      const saved = localStorage.getItem("dashboard-theme");
      const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      applyTheme(saved || (prefersDark ? "dark" : "light"));
      requestAnimationFrame(() => document.body.classList.add("theme-ready"));
      document.getElementById("themeToggle").addEventListener("click", () => {
        animateThemeToggle(document.body.classList.contains("theme-dark") ? "light" : "dark");
      });
    }

    function updateCurrencyButton() {
      const toggle = document.getElementById("currencyToggle");
      if (!toggle) return;
      const isKrw = state.currency === "krw";
      toggle.setAttribute("aria-label", isKrw ? t("showUsd") : t("showKrw"));
      toggle.setAttribute("title", isKrw ? t("showUsd") : t("showKrw"));
    }

    function applyCurrency(currency) {
      state.currency = currency === "krw" ? "krw" : "usd";
      document.body.classList.toggle("currency-krw", state.currency === "krw");
      document.body.classList.toggle("currency-usd", state.currency === "usd");
      localStorage.setItem("dashboard-currency", state.currency);
      updateCurrencyButton();
    }

    function initCurrency() {
      applyCurrency(localStorage.getItem("dashboard-currency") === "krw" ? "krw" : "usd");
      document.getElementById("currencyToggle").addEventListener("click", () => {
        applyCurrency(state.currency === "usd" ? "krw" : "usd");
        renderIndustries();
      });
    }

    function setDrawerOpen(open) {
      const drawer = document.getElementById("mobileDrawer");
      const toggle = document.getElementById("mobileMenuToggle");
      const backdrop = document.getElementById("drawerBackdrop");
      if (!drawer || !toggle || !backdrop) return;
      const shouldOpen = Boolean(open && mobileDrawerQuery.matches);
      document.body.classList.toggle("drawer-open", shouldOpen);
      toggle.setAttribute("aria-expanded", String(shouldOpen));
      drawer.setAttribute("aria-hidden", String(mobileDrawerQuery.matches && !shouldOpen));
      backdrop.hidden = !shouldOpen;
      if (shouldOpen) {
        document.getElementById("drawerClose")?.focus({ preventScroll: true });
      }
    }

    function closeDrawerOnMobile() {
      if (mobileDrawerQuery.matches) setDrawerOpen(false);
    }

    function initMobileDrawer() {
      const toggle = document.getElementById("mobileMenuToggle");
      const close = document.getElementById("drawerClose");
      const backdrop = document.getElementById("drawerBackdrop");
      toggle?.addEventListener("click", () => {
        setDrawerOpen(!document.body.classList.contains("drawer-open"));
      });
      close?.addEventListener("click", () => setDrawerOpen(false));
      backdrop?.addEventListener("click", () => setDrawerOpen(false));
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setDrawerOpen(false);
      });
      if (mobileDrawerQuery.addEventListener) {
        mobileDrawerQuery.addEventListener("change", () => setDrawerOpen(false));
      } else if (mobileDrawerQuery.addListener) {
        mobileDrawerQuery.addListener(() => setDrawerOpen(false));
      }
      setDrawerOpen(false);
    }

    function updateActiveFromScroll() {
      const sections = [...document.querySelectorAll("[data-industry-section]")];
      if (!sections.length) return;
      const anchor = window.innerHeight * 0.5;
      let current = sections[0];
      for (const section of sections) {
        if (section.getBoundingClientRect().top <= anchor) {
          current = section;
        } else {
          break;
        }
      }
      setActiveIndustry(current.dataset.industryName);
    }

    function onScrollSpy() {
      if (scrollSpyFrame) return;
      scrollSpyFrame = requestAnimationFrame(() => {
        scrollSpyFrame = 0;
        updateActiveFromScroll();
      });
    }

    window.addEventListener("scroll", onScrollSpy, { passive: true });
    window.addEventListener("resize", onScrollSpy);

    function render() {
      renderFilters();
      renderIndustries();
    }

    initLanguage();
    initSettings();
    initTheme();
    initCurrency();
    initMobileDrawer();
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
