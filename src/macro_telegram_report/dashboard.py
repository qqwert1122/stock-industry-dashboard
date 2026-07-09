from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
import yaml
from bs4 import BeautifulSoup
from openpyxl import load_workbook

from .briefing import (
    briefing_date_key,
    build_briefing_card,
    increment_gemini_usage,
    load_briefing_index,
    load_gemini_usage,
    load_latest_briefing_card,
    load_recent_briefing_cards,
    update_intraday_track,
    write_briefing_outputs,
)
from .history_store import (
    HistoryStore,
    downsample_history,
    parse_stored_points,
    percentile_stats,
)
from .interpretation import apply_interpretations
from .fetch_log import (
    FetchLogger,
    append_fetch_log_run,
    current_logger,
    load_fetch_log_history,
    sanitize_message,
    save_fetch_log_history,
    use_fetch_logger,
)
from .event_calendar import build_event_calendar, write_event_calendar
from .korea_exports import fetch_itemtrade_records
from .alerts import process_alerts
from .market_gauges import build_market_gauges
from .market_flows import (
    FLOW_MEASURES,
    fetch_krx_futures_flow_rows,
    fetch_krx_main_investor_flow_rows,
    fetch_krx_stock_flow_rows,
    investor_slug,
    load_raw_flow_snapshot,
    raw_flow_investors,
    raw_flow_known_dates,
    raw_flow_series,
    raw_flow_snapshot_path,
    rolling_sum_series,
    store_raw_flow_rows,
)
from .market_valuation import (
    fetch_finra_margin_series,
    fetch_krx_valuation_series,
    fetch_multpl_series,
)
from .market_sentiment import (
    KRX_API_BASE,
    KRX_SOURCE_URL,
    build_korea_fear_greed_score,
    collect_market_snapshot,
    fetch_cnn_fear_greed,
    fetch_vkospi_points,
    merge_existing_and_incoming,
    metric_full_points,
    missing_recent_dates,
)
from .utils import add_months, fmt_number, fmt_pct, fmt_signed, month_key, pct_change, to_float
from .wsts import find_wsts_xlsx_url, parse_wsts_sheet

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
FISCALDATA_TGA_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
    "v1/accounting/dts/operating_cash_balance"
)
GEMINI_DEFAULT_MODEL = "gemini-3.1-flash-lite"
GEMINI_GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_DAILY_CALL_LIMIT = 400
MARKET_GAUGE_HISTORY_FILENAME = "market_gauges_history.json"
MARKET_GAUGE_HISTORY_VERSION = 1
FETCH_LOG_HISTORY_FILENAME = "fetch_log_history.json"
FETCH_LOG_FILENAME = "fetch_log.json"
FETCH_SOURCE_ENDPOINTS = {
    "WSTS": "https://www.wsts.org/76/Recent-News-Release",
    "FRED": FRED_OBSERVATIONS_URL,
    "미국 재무부 DTS": FISCALDATA_TGA_URL,
    "미국 유동성": FRED_OBSERVATIONS_URL,
    "ECOS 신용스프레드": "https://ecos.bok.or.kr/api/",
    "ECOS 매크로": "https://ecos.bok.or.kr/api/",
    "대표주가/시장지수": "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
    "스테이블코인": "https://stablecoins.llama.fi/stablecoins",
    "World Bank 원자재": "https://thedocs.worldbank.org/",
    "SEC CAPEX": "https://data.sec.gov/submissions/{cik}.json",
    "USAspending 방산": "https://api.usaspending.gov/api/v2/search/spending_over_time/",
    "EIA": "https://api.eia.gov/v2/",
    "openFDA": "https://api.fda.gov/",
    "ClinicalTrials.gov": "https://clinicaltrials.gov/api/v2/studies",
    "Launch Library": "https://ll.thespacedevs.com/2.3.0/launches/",
    "AFDC EV 충전": "https://developer.nrel.gov/api/alt-fuel-stations/v1/count.json",
    "KOSIS": "https://kosis.kr/openapi/",
    "한국 수출": "https://apis.data.go.kr/1220000/Itemtrade",
    "밸류에이션/수급": "https://finance.naver.com/",
    "시장 수급": "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
    "시장 파생지표": "https://api.upbit.com/v1/ticker",
    "시장 심리": "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start_date}",
}
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
    "전기차": "순수 전기차 수출과 EV 판매 흐름으로 전기차 보급 속도를 봅니다.",
    "조선": "운임, 선가, 발주, 선박 수출로 조선 수요와 이익 사이클을 봅니다.",
    "철강/소재": "원자재 가격과 중국 제조업 경기로 소재 수요를 봅니다.",
    "화학/정유": "유가, 원료, 제품 스프레드로 마진 방향을 확인합니다.",
    "은행/금융": "금리, 스프레드, 대출, 연체율로 은행 수익성과 신용위험을 봅니다.",
    "건설/부동산": "착공, 허가, 금리, 가격으로 부동산 선행 흐름을 봅니다.",
    "방산": "수주, 생산, 수출 흐름으로 방산 수요를 확인합니다.",
    "스테이블코인": "온체인 달러 유동성과 결제/거래 수요를 봅니다.",
    "전력": "전력 가격, 생산, 장비 수출로 인프라 수요를 확인합니다.",
    "로봇": "설비투자와 로봇 수출 흐름을 묶어 봅니다.",
    "우주": "우주/항공 장비 생산과 이벤트 수요를 추적합니다.",
    "바이오": "바이오 제품 가격과 수출 흐름으로 업황을 봅니다.",
    "배터리": "배터리 가격, 원재료, 수출 흐름으로 셀/소재 업황을 봅니다.",
    "데이터인프라": "서버와 네트워크 인프라 투자 흐름을 봅니다.",
    "매크로": "환율, 변동성, 금리로 시장 분위기를 빠르게 확인합니다.",
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
    "판매액(WSTS)": "Sales (WSTS)",
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
    "화학 스프레드": "Chemical Spreads",
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
    "시장 분위기": "Market Mood",
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
    "설비투자": "Capex/Investment",
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
    "주택 재고": "Housing Inventory",
    "국내 주택": "Korea Housing",
    "건설 허가": "Construction Permits",
    "대표주가": "Representative Stock Prices",
    "대표주가/시장지수": "Representative Stocks/Market Indexes",
    "신용 스프레드": "Credit Spreads",
    "시장지수": "Market Indexes",
    "미국 유동성": "US Liquidity",
}
EN_DEPTH_LABELS = {
    "전체 업황": "Overall Cycle",
    "메모리 반도체": "Memory Semiconductors",
    "AI/GPU": "AI/GPU",
    "CPU/프로세서": "CPU/Processors",
    "파운드리": "Foundry",
    "장비": "Equipment",
    "패키징/후공정": "Packaging/Back-end",
    "소자/부품": "Devices/Components",
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
    "메모리 IC": "Memory ICs",
    "프로세서/컨트롤러 IC": "Processor/Controller ICs",
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
    "한국 미분양 주택": "Korea Unsold Homes",
    "한국 주택매매가격지수": "Korea Home Sale Price Index",
    "한국 건축허가 동수": "Korea Building Permits Count",
    "미국 10년 국채금리": "US 10Y Treasury Yield",
    "미국 2년 국채금리": "US 2Y Treasury Yield",
    "미국 10Y-2Y 금리차": "US 10Y-2Y Treasury Spread",
    "미국 BAA 회사채-10년 국채 스프레드": "US BAA Corporate-10Y Treasury Spread",
    "미국 투자등급 회사채 OAS": "US Investment Grade Corporate OAS",
    "미국 BBB 회사채 OAS": "US BBB Corporate OAS",
    "미국 하이일드 회사채 OAS": "US High Yield Corporate OAS",
    "한국 회사채 AA- 3Y-국고채 3Y 스프레드": "Korea AA- Corporate 3Y-KTB 3Y Spread",
    "한국 회사채 BBB- 3Y-국고채 3Y 스프레드": "Korea BBB- Corporate 3Y-KTB 3Y Spread",
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
    "철광석": "Iron Ore",
    "구리 가격": "Copper Price",
    "구리": "Copper",
    "알루미늄 가격": "Aluminum Price",
    "알루미늄": "Aluminum",
    "미국 자동차 판매": "US Auto Sales",
    "미국 반도체 PPI": "US Semiconductor PPI",
    "미국 반도체 제조 PPI": "US Semiconductor Device Manufacturing PPI",
    "미국 반도체 장비 PPI": "US Semiconductor Machinery PPI",
    "미국 반도체 장비/부품 PPI": "US Semiconductor Machinery and Parts PPI",
    "미국 반도체 패키징 PPI": "US Semiconductor IC Packaging PPI",
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
    "미국 순유동성": "US Net Liquidity",
    "미국 역레포": "US Reverse Repo",
    "미국 TGA": "US Treasury General Account",
    "미국 연준 총자산": "Fed Total Assets",
    "원/달러 환율": "USD/KRW Exchange Rate",
    "코스피": "KOSPI",
    "코스닥": "KOSDAQ",
    "나스닥": "NASDAQ Composite",
    "S&P 500": "S&P 500",
    "다우": "Dow Jones Industrial Average",
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
WSTS_REGION_MEANINGS = {
    "Worldwide": (
        "전 세계 반도체 판매액입니다. 메모리와 비메모리를 모두 합친 시장 전체의 매출 흐름이라, "
        "반도체 업황이 커지는지 줄어드는지 볼 때 기준으로 씁니다."
    ),
    "Asia Pacific": (
        "아시아·태평양 지역 반도체 판매액입니다. 한국, 대만, 중국, 일본 등 주요 생산·소비 거점의 "
        "수요 흐름을 보는 데 유용합니다."
    ),
    "Americas": (
        "미주 지역 반도체 판매액입니다. 미국을 중심으로 데이터센터, 클라우드, 기업 IT 투자 수요가 "
        "반도체 매출에 얼마나 이어지는지 볼 때 참고합니다."
    ),
}
WSTS_3MMA_MEANING = (
    "3MMA는 최근 3개월 평균입니다. 한 달짜리 급등락을 줄여 실제 추세가 위인지 아래인지 "
    "보기 쉽게 해줍니다."
)
WSTS_REGION_MEANINGS_EN = {
    "Worldwide": (
        "Worldwide semiconductor sales show total global semiconductor revenue across memory and non-memory. "
        "They are the main baseline for judging whether the semiconductor cycle is expanding or slowing."
    ),
    "Asia Pacific": (
        "Asia Pacific semiconductor sales show demand across major Asian electronics and semiconductor hubs "
        "such as Korea, Taiwan, China, and Japan."
    ),
    "Americas": (
        "Americas semiconductor sales show demand in the Americas, led by the US. They help check how data center, "
        "cloud, AI, and enterprise IT demand feeds into chip revenue."
    ),
}
WSTS_3MMA_MEANING_EN = (
    "3MMA means a three-month moving average. It smooths one-month jumps and drops so the underlying trend is "
    "easier to see."
)
CAPEX_MEANINGS = {
    "Microsoft": (
        "Microsoft의 CAPEX는 Azure와 AI 데이터센터를 짓기 위한 서버, GPU, 네트워크, 전력 설비 투자를 "
        "보여줍니다. 금액이 커질수록 클라우드와 AI 인프라 확장 속도가 빠르다는 뜻으로 볼 수 있습니다."
    ),
    "Amazon": (
        "Amazon의 CAPEX는 AWS 데이터센터와 물류 인프라에 들어가는 설비투자 규모를 보여줍니다. 특히 AWS "
        "투자가 커질수록 클라우드·AI 서버 수요가 강하다는 신호로 볼 수 있습니다."
    ),
    "Alphabet": (
        "Alphabet의 CAPEX는 Google Cloud와 AI 데이터센터, 검색·유튜브 인프라 확장을 위한 투자 규모를 "
        "보여줍니다. AI 서비스 확대가 실제 설비투자로 이어지는지 볼 때 참고합니다."
    ),
    "Meta": (
        "Meta의 CAPEX는 AI 추천·광고 시스템과 소셜 서비스 운영을 위한 데이터센터 투자를 보여줍니다. "
        "서버와 GPU 투자 강도를 확인하는 데 유용합니다."
    ),
}
CAPEX_MEANINGS_EN = {
    "Microsoft": (
        "Microsoft CAPEX shows investment in servers, GPUs, networking, and power equipment for Azure and AI "
        "data centers. Rising spending suggests faster cloud and AI infrastructure buildout."
    ),
    "Amazon": (
        "Amazon CAPEX shows spending on AWS data centers and logistics infrastructure. Strong AWS-related "
        "investment is a signal of cloud and AI server demand."
    ),
    "Alphabet": (
        "Alphabet CAPEX shows investment in Google Cloud, AI data centers, and Search and YouTube infrastructure. "
        "It helps check whether AI service growth is turning into physical infrastructure spending."
    ),
    "Meta": (
        "Meta CAPEX shows data center investment for AI recommendation, advertising systems, and social services. "
        "It is useful for reading server and GPU investment intensity."
    ),
}
EN_MEANING_LABELS = {
    "반도체 업황의 현재 수요 강도와 재고 순환을 확인하는 월간 지표입니다.": "Monthly indicator for semiconductor demand strength and inventory cycles.",
    "글로벌 반도체 매출 흐름으로 업황의 수요 강도와 재고 순환을 확인합니다.": "Tracks global semiconductor revenue to read demand strength and inventory cycles.",
    "반도체 생산자 가격입니다. 반도체 가격이 오르는지 내리는지 볼 때 참고합니다.": "Semiconductor producer prices help show whether semiconductor prices are moving up or down.",
    "할인율과 금융주 마진 기대를 좌우하는 시장 금리입니다.": "Market rate that drives discount rates and bank margin expectations.",
    "경기 기대와 은행 순이자마진 방향을 함께 보여주는 지표입니다.": "Shows both growth expectations and the direction of bank net interest margins.",
    "신용 위험과 자금 조달 여건이 얼마나 빡빡한지 확인합니다.": "Measures credit risk and how tight funding conditions are.",
    "미국 투자등급 회사채 OAS는 우량 회사채 신용위험과 자금조달 여건을 보여주는 지표입니다.": "US investment grade corporate OAS shows credit risk and funding conditions for higher-quality corporate bonds.",
    "BBB 회사채 OAS는 경기 둔화와 신용위험 확대에 민감한 투자등급 하단 스프레드입니다.": "BBB corporate OAS tracks the lower end of investment grade credit, which is sensitive to slowdown and credit stress.",
    "하이일드 OAS는 위험자산 선호와 기업 부도위험 변화를 보여주는 대표 신용 스프레드입니다.": "High yield OAS is a representative credit spread for risk appetite and corporate default risk.",
    "한국 회사채 AA- 3년 금리와 국고채 3년 금리의 차이로 국내 우량 기업 신용위험과 자금조달 여건을 확인합니다.": "Spread between Korea AA- 3Y corporate bonds and 3Y government bonds, used to read domestic high-grade credit risk and funding conditions.",
    "한국 회사채 BBB- 3년 금리와 국고채 3년 금리의 차이로 국내 하위등급 신용위험과 위험회피 강도를 확인합니다.": "Spread between Korea BBB- 3Y corporate bonds and 3Y government bonds, used to read lower-grade credit risk and risk aversion.",
    "대출 자산의 질과 금융 시스템 부담을 점검합니다.": "Checks loan asset quality and stress in the financial system.",
    "은행권 신용 공급과 실물 경기의 자금 수요를 봅니다.": "Tracks bank credit supply and real-economy loan demand.",
    "건설 경기의 실제 착공 모멘텀과 주택 공급 흐름을 보여줍니다.": "Shows actual construction momentum and the housing supply pipeline.",
    "향후 착공과 건설 활동을 선행해서 보여주는 지표입니다.": "Leading indicator for future starts and construction activity.",
    "주택 구매 부담과 부동산 수요에 직접 영향을 주는 비용입니다.": "Financing cost that directly affects housing affordability and real estate demand.",
    "가계 자산 효과와 부동산 경기 방향성을 확인합니다.": "Shows household wealth effects and the direction of the housing cycle.",
    "정유, 화학 원가와 인플레이션 압력을 동시에 움직이는 원재료 가격입니다.": "Feedstock price that affects refining, chemical costs, and inflation pressure.",
    "석유 제품 가격입니다. 정유 제품 수요와 정유사 마진 방향을 볼 때 참고합니다.": "Oil product prices help show refined-product demand and refining-margin direction.",
    "화학 제품 생산자 가격입니다. 제품 가격이 원가보다 빠르게 움직이는지 볼 때 참고합니다.": "Chemical producer prices help show whether selling prices are moving faster than input costs.",
    "철강 원가와 중국 투자 수요를 반영하는 핵심 원재료입니다.": "Core raw material reflecting steel costs and Chinese investment demand.",
    "전기화와 제조업 경기를 민감하게 반영하는 경기 민감 금속입니다.": "Cyclical metal that is sensitive to electrification and manufacturing activity.",
    "경량 소재와 제조업 수요, 전력비 영향을 함께 받는 소재 가격입니다.": "Material price affected by lightweighting demand, manufacturing demand, and power costs.",
    "배터리 양극재 원가에 큰 영향을 주는 원재료 가격입니다.": "Raw material price with a large impact on battery cathode costs.",
    "니켈 가격은 배터리 양극재 원가에 큰 영향을 줍니다. 가격이 오르면 소재 업체와 배터리 업체의 수익성이 달라질 수 있습니다.": "Nickel prices have a large impact on battery cathode costs and can change margins for materials and battery companies.",
    "전력 생산 원가와 산업 에너지 비용을 좌우하는 에너지 원료 지표입니다.": "Energy feedstock indicator that drives power generation costs and industrial energy costs.",
    "천연가스 가격은 전력 생산 원가와 산업 에너지 비용을 좌우하는 에너지 원료 지표입니다.": "Natural gas price indicates power generation costs and industrial energy cost pressure.",
    "석탄 가격은 화력발전 원가에 영향을 줍니다. 가격이 오르면 전력 생산 비용이 커질 수 있습니다.": "Coal prices affect thermal power generation costs and can raise power production costs when they rise.",
    "완성차 수요와 소비 경기 흐름을 확인하는 판매 지표입니다.": "Sales indicator for automaker demand and consumer-cycle conditions.",
    "순수 전기차 수출 흐름으로 EV 수요와 국내 전기차 생산 모멘텀을 확인합니다.": "Tracks BEV export flows to read EV demand and domestic EV production momentum.",
    "순수 전기차 수출 흐름으로 전기차 완성차 수요와 국내 EV 생산 모멘텀을 확인합니다.": "Tracks BEV export flows to read EV demand and domestic EV production momentum.",
    "방산 발주와 생산 사이클을 통해 방산 업체 수요가 강해지는지 확인합니다.": "Tracks whether defense-company demand is strengthening through orders and production cycles.",
    "달러 연동 스테이블코인의 유통량 변화로 온체인 달러 유동성과 결제/거래 수요를 확인합니다.": "Tracks USD-pegged stablecoin supply to read on-chain dollar liquidity and payment/trading demand.",
    "전력 생산과 가격 흐름으로 전력 인프라와 전력 수요 사이클을 확인합니다.": "Tracks power production and prices to read power infrastructure and demand cycles.",
    "빅테크 CAPEX는 AI 데이터센터, 서버, 전력 인프라에 실제로 투자가 늘어나는지 보여줍니다.": "Big Tech CAPEX shows whether investment in AI data centers, servers, and power infrastructure is actually rising.",
    "공장 자동화와 로봇 설비 투자가 늘어나는지 볼 때 참고합니다.": "Helps show whether factory automation and robotics investment is increasing.",
    "항공우주 장비 생산과 가격 흐름입니다. 우주 산업의 주문과 비용 부담을 볼 때 참고합니다.": "Aerospace equipment production and price trends help show space-industry orders and cost pressure.",
    "바이오 의약품과 진단 제품의 가격 사이클을 확인하는 지표입니다.": "Tracks the pricing cycle for biologics and diagnostics products.",
    "배터리 제품 가격 흐름으로 셀/소재 밸류체인의 업황을 점검합니다.": "Checks battery cell/materials conditions through battery product price trends.",
    "수출주 원화 환산 매출과 외국인 수급에 영향을 주는 매크로 변수입니다.": "Macro variable affecting exporters' KRW-translated revenue and foreign investor flows.",
    "시장 위험 회피 심리와 변동성 확대 여부를 봅니다.": "Tracks risk-off sentiment and volatility expansion.",
    "해당 품목의 대외 수요와 가격/물량 사이클을 확인합니다.": "Tracks external demand and price/volume cycles for the item.",
    "투자 판단에 필요한 업황 변화를 확인합니다.": "Tracks industry changes relevant to investment decisions.",
    "미국 방산 자본재 발주 흐름으로 방산 수요와 수주 모멘텀을 확인합니다.": "Tracks US defense capital goods orders to read defense demand and order momentum.",
    "아직 매출로 인식되지 않은 방산 수주잔고의 축적과 감소를 확인합니다.": "Tracks the buildup and drawdown of defense order backlog not yet recognized as revenue.",
    "전력 생산 가격입니다. 전기요금과 전력 회사의 수익성이 좋아질지 나빠질지 볼 때 참고합니다.": "Power producer prices help show the direction of electricity prices and utility profitability.",
    "유틸리티 실물 생산 흐름으로 전력 수요와 경기 민감도를 확인합니다.": "Uses utilities production to read power demand and cyclical sensitivity.",
    "자동화와 로봇 수요에 가까운 산업용 기계 발주 흐름을 확인합니다.": "Tracks industrial machinery orders tied to automation and robotics demand.",
    "로봇과 설비투자 설비에 들어가는 산업 제어장치 가격 흐름을 확인합니다.": "Tracks industrial control equipment prices used in robotics and capex equipment.",
    "우주와 방산 장비 생산 사이클을 함께 보여주는 월간 생산 지표입니다.": "Monthly production indicator for both space and defense equipment cycles.",
    "항공우주 부품 가격입니다. 위성, 발사체, 항공 장비를 만드는 비용이 커지는지 볼 때 참고합니다.": "Aerospace parts prices help show whether the cost of satellites, launch vehicles, and aerospace equipment is rising.",
    "바이오 의약품 제조 가격 흐름으로 바이오 업황의 가격 사이클을 확인합니다.": "Tracks biologics manufacturing prices to read the biotech pricing cycle.",
    "진단 제품의 생산자 가격입니다. 진단 장비와 검사 제품 가격이 오르는지 내리는지 볼 때 참고합니다.": "Diagnostics producer prices help show whether diagnostic equipment and test-product prices are rising or falling.",
    "저장 배터리 제조 가격입니다. 배터리 셀 업체의 원가 부담과 판매 가격 흐름을 볼 때 참고합니다.": "Storage battery manufacturing prices help show battery-cell cost pressure and selling-price trends.",
    "연준이 공급한 돈에서 재무부 금고(TGA)와 역레포에 잠긴 돈을 뺀, 실제로 금융시장에 돌고 있는 달러 유동성입니다. 증가하면 위험자산에 우호적, 감소하면 부담이 되는 흐름으로 해석합니다. 계산은 WALCL, TGA, 역레포의 관측일이 다를 때 각 날짜 이전의 가장 최근 값을 사용합니다.": "US net liquidity subtracts cash locked in the Treasury General Account (TGA) and reverse repos from the money supplied by the Fed, approximating dollar liquidity circulating in financial markets. Rising liquidity is usually supportive for risk assets, while falling liquidity is a headwind. The calculation aligns WALCL, TGA, and reverse repo by using the latest observation available on or before each date.",
    "재무부가 연준에 맡겨둔 현금입니다. TGA가 늘면 시중 유동성이 흡수되고, 줄면 방출됩니다. 부채한도 협상 국면에서 크게 출렁입니다.": "Cash the US Treasury keeps at the Fed. When the TGA rises, liquidity is absorbed from the market; when it falls, liquidity is released. It can swing sharply around debt-ceiling episodes.",
    "시중 자금이 연준에 하루짜리로 파킹된 규모입니다. 줄어들면 그만큼 시장에 유동성이 풀려나오는 효과가 있습니다.": "Cash parked overnight at the Fed through reverse repos. When it falls, that cash is effectively released back toward markets.",
    "미국 국방부가 실제로 계약에 배정한 금액입니다. 방산 예산이 어느 분야로 흘러가는지 볼 때 중요합니다.": "US DoD contract obligations show where defense budget dollars are actually being committed.",
    "미국 연방 방산/항공우주 제조업 계약 의무액으로 방산 제조 밸류체인의 수주 모멘텀을 확인합니다.": "Uses US federal defense/aerospace manufacturing obligations to read order momentum across the defense manufacturing value chain.",
    "NASA 계약 의무액은 미국 정부가 우주 장비와 서비스에 실제로 얼마나 돈을 쓰고 있는지 보여줍니다.": "NASA contract obligations show how much the US government is actually spending on space equipment and services.",
    "FDA 의약품 승인 관련 기록 수로 바이오 규제 이벤트와 신약 모멘텀을 확인합니다.": "Counts FDA drug approval records to read biotech regulatory events and new-drug momentum.",
    "Phase 3 임상 시작 건수는 후기 파이프라인 활동성과 바이오 투자심리의 이벤트 밀도를 보여줍니다.": "Phase 3 trial starts show late-stage pipeline activity and event density for biotech sentiment.",
    "글로벌 발사 건수로 우주 산업 활동성과 위성 인프라 수요를 확인합니다.": "Global launch count indicates space industry activity and satellite infrastructure demand.",
    "미국 EV 충전소 수는 전기차를 이용하기 쉬워지고 있는지와 충전 인프라 투자 흐름을 보여줍니다.": "US EV charging station count shows whether EVs are getting easier to use and how charging infrastructure investment is moving.",
    "미국 EV 충전 포트 수는 전기차 이용 편의성과 인프라 확장 속도를 확인하는 지표입니다.": "US EV charging port count shows EV usability and the pace of infrastructure expansion.",
}


def build_dashboard_site(config: dict[str, Any], output_dir: str | Path, session: requests.Session) -> dict[str, Any]:
    output_path = Path(output_dir)
    data_path = output_path / "data"
    data_path.mkdir(parents=True, exist_ok=True)

    timezone_name = str(config.get("timezone") or "Asia/Seoul")
    previous_payload = load_previous_dashboard_payload(data_path / "dashboard.json")
    logger = FetchLogger(run_type="full", timezone_name=timezone_name)
    with use_fetch_logger(logger):
        payload = build_dashboard_payload(config, session, previous_payload)
        long_histories = enrich_metrics_with_history(
            payload.get("metrics", []), config, previous_payload
        )
        apply_interpretations(payload.get("metrics", []), config)
        payload["market_gauges"] = build_market_gauges(payload.get("metrics", []))
        payload["calendar"] = build_event_calendar(config, payload, today=datetime.now(ZoneInfo(timezone_name)).date())
        write_event_calendar(data_path / "calendar.json", payload["calendar"])
        market_gauge_history = update_market_gauge_history(
            load_previous_dashboard_payload(data_path / MARKET_GAUGE_HISTORY_FILENAME),
            payload,
            timezone_name,
        )
        payload["collection_issues"] = annotate_metric_freshness(
            payload.get("metrics", []), datetime.now(ZoneInfo(timezone_name)).date()
        )
        annotate_dashboard_updates(payload, previous_payload)
        briefing_generated_at = str(payload.get("generated_at") or datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds"))
        base_briefing = build_morning_briefing(payload, session)
        trajectory = update_intraday_track(data_path, payload, briefing_generated_at)
        briefing_time = datetime.fromisoformat(briefing_generated_at.replace("Z", "+00:00"))
        payload["morning_briefing"] = build_briefing_card(
            base_briefing,
            card_type="morning",
            generated_at=briefing_generated_at,
            generated_label=str(payload.get("generated_label") or ""),
            trajectory=trajectory,
            low_signal=False,
            session_context=briefing_session_context(briefing_time),
            gate_reason="일일 전체 빌드",
            metric_snapshot=briefing_metric_snapshot(payload),
        )
        payload["briefing_index"] = write_briefing_outputs(data_path, payload["morning_briefing"])
        try:
            process_alerts(config, payload, session)
        except Exception:  # noqa: BLE001 - 알림 실패가 배포를 막으면 안 됩니다.
            pass
        copy_signal_log_output(config, data_path)
    fetch_log_history = write_fetch_log_outputs(data_path, logger)
    payload["fetch_log_summary"] = fetch_log_history.get("runs", [])[-1].get("summary", {}) if fetch_log_history.get("runs") else {}
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)

    copy_dashboard_assets(output_path)
    (data_path / "dashboard.json").write_text(json_text + "\n", encoding="utf-8")
    (data_path / "long_history.json").write_text(
        json.dumps(long_histories, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (data_path / MARKET_GAUGE_HISTORY_FILENAME).write_text(
        json.dumps(market_gauge_history, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (output_path / "index.html").write_text(render_dashboard_html(payload), encoding="utf-8")
    write_admin_html(output_path)
    (output_path / ".nojekyll").write_text("", encoding="utf-8")
    return payload


def refresh_prices_site(
    config: dict[str, Any], output_dir: str | Path, session: requests.Session
) -> dict[str, Any]:
    """장중 시세만 갱신하는 경량 빌드.

    이전 전체 빌드 결과(dashboard.json)를 기반으로 대표주/시장지수 지표만
    다시 수집해 교체하고 페이지를 재생성합니다. 이전 결과가 없으면
    전체 빌드로 폴백합니다.
    """
    output_path = Path(output_dir)
    data_path = output_path / "data"
    data_path.mkdir(parents=True, exist_ok=True)

    previous_payload = load_previous_dashboard_payload(data_path / "dashboard.json")
    if not previous_payload or not previous_payload.get("metrics"):
        return build_dashboard_site(config, output_dir, session)

    timezone_name = str(config.get("timezone") or "Asia/Seoul")
    now = datetime.now(ZoneInfo(timezone_name))
    previous_by_key = previous_metric_index(previous_payload)
    logger = FetchLogger(run_type="prices", timezone_name=timezone_name)
    with use_fetch_logger(logger):
        started_at, started_monotonic = logger.source_started()
        fresh_metrics = collect_equity_price_metrics(config, session, now.date())
        ok_count = sum(1 for item in fresh_metrics if item.get("status") == "ok")
        message = f"{ok_count}/{len(fresh_metrics)}개 지표 자동 수집"
        apply_fetch_metadata(fresh_metrics, now.isoformat(timespec="seconds"), previous_by_key)
        record_fetch_result(
            "대표주가/시장지수",
            fresh_metrics,
            previous_by_key,
            started_at,
            started_monotonic,
            message,
        )
        fresh_long = enrich_metrics_with_history(fresh_metrics, config, previous_payload)

    payload = previous_payload
    metrics = payload.get("metrics", [])
    fresh_by_id = {
        str(metric.get("id")): metric
        for metric in fresh_metrics
        if metric.get("status") == "ok"
    }
    replaced = 0
    for index, metric in enumerate(metrics):
        fresh = fresh_by_id.get(str(metric.get("id")))
        if fresh is not None:
            # 일일 변경 배지 상태는 아침 전체 빌드 기준을 유지합니다.
            for keep_field in ("daily_status", "is_new", "is_updated_today",
                               "previous_run_observed_at", "previous_run_value",
                               "previous_run_display_value"):
                if keep_field in metric:
                    fresh[keep_field] = metric[keep_field]
            metrics[index] = fresh
            replaced += 1

    payload["generated_at"] = now.isoformat(timespec="seconds")
    payload["generated_label"] = now.strftime("%Y-%m-%d %H:%M %Z")
    payload["market_gauges"] = build_market_gauges(metrics)
    payload["calendar"] = build_event_calendar(config, payload, today=now.date())
    write_event_calendar(data_path / "calendar.json", payload["calendar"])
    payload["collection_issues"] = annotate_metric_freshness(metrics, now.date())
    apply_interpretations(metrics, config)
    payload["prices_refreshed_at"] = now.isoformat(timespec="seconds")

    try:
        process_alerts(config, payload, session, include_weekly=False)
    except Exception:  # noqa: BLE001
        pass
    copy_signal_log_output(config, data_path)

    long_history_path = data_path / "long_history.json"
    long_histories: dict[str, Any] = {}
    if long_history_path.exists():
        try:
            loaded = json.loads(long_history_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                long_histories = loaded
        except (OSError, json.JSONDecodeError):
            pass
    long_histories.update(fresh_long)

    copy_dashboard_assets(output_path)
    fetch_log_history = write_fetch_log_outputs(data_path, logger)
    payload["fetch_log_summary"] = fetch_log_history.get("runs", [])[-1].get("summary", {}) if fetch_log_history.get("runs") else {}
    (data_path / "dashboard.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    long_history_path.write_text(
        json.dumps(long_histories, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (output_path / "index.html").write_text(render_dashboard_html(payload), encoding="utf-8")
    write_admin_html(output_path)
    (output_path / ".nojekyll").write_text("", encoding="utf-8")
    payload["_prices_refreshed_count"] = replaced
    return payload


def briefing_metric_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for metric in payload.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        metric_id = str(metric.get("id") or "").strip()
        if not metric_id:
            continue
        snapshot[metric_id] = {
            "id": metric_id,
            "name": str(metric.get("name") or ""),
            "industry": str(metric.get("industry") or ""),
            "group": str(metric.get("group") or ""),
            "value": to_float(metric.get("value")),
            "display_value": str(metric.get("display_value") or ""),
            "observed_at": str(metric.get("observed_at") or ""),
            "change_pct": to_float(metric.get("change_pct")),
        }
    return snapshot


def observed_at_progressed(current: object, previous: object) -> bool:
    current_text = str(current or "").strip()
    previous_text = str(previous or "").strip()
    if not current_text or current_text == previous_text:
        return False
    current_date = parse_iso_date(current_text)
    previous_date = parse_iso_date(previous_text)
    if current_date and previous_date:
        return current_date > previous_date
    return bool(current_text and current_text != previous_text)


def briefing_metric_changes(
    current_snapshot: dict[str, Any],
    previous_snapshot: dict[str, Any] | None,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    if not previous_snapshot:
        return {
            "changed": True,
            "changed_count": len(current_snapshot),
            "changes": [],
            "reason": "이전 카드 지표 스냅샷 없음",
        }

    changes: list[dict[str, Any]] = []
    for metric_id, current in current_snapshot.items():
        if not isinstance(current, dict):
            continue
        previous = previous_snapshot.get(metric_id)
        if not isinstance(previous, dict):
            changes.append({"id": metric_id, "name": current.get("name", ""), "reason": "신규 지표"})
            continue
        if observed_at_progressed(current.get("observed_at"), previous.get("observed_at")):
            changes.append(
                {
                    "id": metric_id,
                    "name": current.get("name", ""),
                    "reason": "관측일 전진",
                    "previous_observed_at": previous.get("observed_at", ""),
                    "observed_at": current.get("observed_at", ""),
                }
            )
            continue
        if not numeric_values_equal(current.get("value"), previous.get("value")):
            changes.append(
                {
                    "id": metric_id,
                    "name": current.get("name", ""),
                    "reason": "값 변화",
                    "previous_value": previous.get("value"),
                    "value": current.get("value"),
                }
            )

    return {
        "changed": bool(changes),
        "changed_count": len(changes),
        "changes": changes[:limit],
        "reason": f"{len(changes)}개 지표 변화" if changes else "직전 카드 이후 지표 변화 없음",
    }


def briefing_session_context(now: datetime) -> dict[str, Any]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    kst = now.astimezone(ZoneInfo("Asia/Seoul"))
    minute = kst.hour * 60 + kst.minute
    korea_open = 9 * 60
    korea_close = 15 * 60 + 45
    us_open = 23 * 60
    us_close = 6 * 60 + 15
    if korea_open <= minute <= korea_close:
        return {
            "key": "korea",
            "label": "한국장",
            "benchmark_names": ["코스피", "코스닥"],
            "prompt_focus": "코스피·코스닥과 국내 수급 흐름을 중심으로 쓰고, 남은 한국장 또는 다음 한국장에 줄 함의로 마무리한다.",
        }
    if minute >= us_open or minute <= us_close:
        return {
            "key": "us",
            "label": "미국장",
            "benchmark_names": ["S&P 500", "S&P500 선물", "나스닥", "나스닥100 선물"],
            "prompt_focus": "미국 지수, 환율, 미국 대표주 흐름을 중심으로 쓰고, 내일 한국장에 줄 함의로 마무리한다.",
        }
    return {
        "key": "off",
        "label": "세션 외",
        "benchmark_names": ["코스피", "코스닥", "S&P 500", "나스닥"],
        "prompt_focus": "새로 변한 지표만 짧게 정리하고 다음 정규장에 확인할 점으로 마무리한다.",
    }


def normalized_metric_name(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def benchmark_change_summary(
    current_snapshot: dict[str, Any],
    previous_snapshot: dict[str, Any] | None,
    benchmark_names: list[str],
) -> dict[str, Any]:
    if not previous_snapshot:
        return {"significant": False, "drivers": []}
    targets = {normalized_metric_name(name) for name in benchmark_names}
    drivers: list[dict[str, Any]] = []
    for metric_id, current in current_snapshot.items():
        if not isinstance(current, dict):
            continue
        if normalized_metric_name(current.get("name")) not in targets:
            continue
        previous = previous_snapshot.get(metric_id)
        if not isinstance(previous, dict):
            continue
        current_value = to_float(current.get("value"))
        previous_value = to_float(previous.get("value"))
        if current_value is None or previous_value in (None, 0):
            continue
        change_pct = (current_value / previous_value - 1.0) * 100.0
        if abs(change_pct) >= 0.5:
            drivers.append(
                {
                    "id": metric_id,
                    "name": current.get("name", ""),
                    "change_pct": round(change_pct, 3),
                    "basis": "직전 카드 대비 기준 지수 변화",
                }
            )
    drivers.sort(key=lambda item: abs(float(item.get("change_pct") or 0)), reverse=True)
    return {"significant": bool(drivers), "drivers": drivers}


def daily_move_significance(payload: dict[str, Any]) -> dict[str, Any]:
    drivers: list[dict[str, Any]] = []
    for metric in payload.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        change_pct = to_float(metric.get("change_pct"))
        if change_pct is None or abs(change_pct) < 1.0:
            continue
        drivers.append(
            {
                "id": str(metric.get("id") or ""),
                "name": str(metric.get("name") or ""),
                "change_pct": round(change_pct, 3),
                "basis": "당일 등락률",
            }
        )
    drivers.sort(key=lambda item: abs(float(item.get("change_pct") or 0)), reverse=True)
    return {"significant": bool(drivers), "drivers": drivers[:8]}


def consecutive_low_signal_count(cards: list[dict[str, Any]]) -> int:
    count = 0
    for card in cards:
        if not isinstance(card, dict) or not card.get("low_signal"):
            break
        count += 1
    return count


def briefing_generation_decision(
    payload: dict[str, Any],
    previous_card: dict[str, Any] | None,
    recent_cards: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    current_snapshot = briefing_metric_snapshot(payload)
    previous_snapshot = (
        previous_card.get("metric_snapshot")
        if isinstance(previous_card, dict) and isinstance(previous_card.get("metric_snapshot"), dict)
        else None
    )
    changes = briefing_metric_changes(current_snapshot, previous_snapshot)
    session_context = briefing_session_context(now)
    benchmark = benchmark_change_summary(
        current_snapshot,
        previous_snapshot,
        list(session_context.get("benchmark_names") or []),
    )
    daily_move = daily_move_significance(payload)
    significant = bool(benchmark["significant"] or daily_move["significant"])
    low_signal = bool(changes["changed"] and not significant)
    low_signal_streak = consecutive_low_signal_count(recent_cards)

    skip = False
    reason = str(changes["reason"])
    if not changes["changed"]:
        skip = True
    elif low_signal and low_signal_streak >= 2:
        skip = True
        reason = "low_signal 카드 2회 연속 이후 유의미한 변화 없음"
    elif significant:
        drivers = [*benchmark.get("drivers", []), *daily_move.get("drivers", [])]
        lead = drivers[0] if drivers else {}
        reason = f"유의미한 변화: {lead.get('name') or '주요 지표'}"
    elif low_signal:
        reason = "변화는 있으나 유의미성 낮음"

    return {
        "skip": skip,
        "reason": reason,
        "low_signal": low_signal,
        "low_signal_streak": low_signal_streak,
        "significant": significant,
        "session": session_context,
        "changes": changes,
        "benchmark": benchmark,
        "daily_move": daily_move,
        "metric_snapshot": current_snapshot,
    }


def write_briefing_site_outputs(
    output_path: Path,
    data_path: Path,
    payload: dict[str, Any],
    logger: FetchLogger,
) -> None:
    fetch_log_history = write_fetch_log_outputs(data_path, logger)
    payload["fetch_log_summary"] = fetch_log_history.get("runs", [])[-1].get("summary", {}) if fetch_log_history.get("runs") else {}
    copy_dashboard_assets(output_path)
    (data_path / "dashboard.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_path / "index.html").write_text(render_dashboard_html(payload), encoding="utf-8")
    write_admin_html(output_path)
    (output_path / ".nojekyll").write_text("", encoding="utf-8")


def refresh_briefing_site(
    config: dict[str, Any],
    output_dir: str | Path,
    session: requests.Session,
    card_type: str,
) -> dict[str, Any]:
    """Generate a briefing card from the latest published dashboard payload."""
    output_path = Path(output_dir)
    data_path = output_path / "data"
    data_path.mkdir(parents=True, exist_ok=True)

    payload = load_previous_dashboard_payload(data_path / "dashboard.json")
    if not payload or not payload.get("metrics"):
        return build_dashboard_site(config, output_dir, session)

    timezone_name = str(config.get("timezone") or payload.get("timezone") or "Asia/Seoul")
    now = datetime.now(ZoneInfo(timezone_name))
    logger = FetchLogger(run_type=f"briefing-{card_type}", timezone_name=timezone_name)
    with use_fetch_logger(logger):
        started_at, started_monotonic = logger.source_started()
        previous_card = load_latest_briefing_card(data_path)
        recent_cards = load_recent_briefing_cards(data_path, limit=4)
        decision = briefing_generation_decision(payload, previous_card, recent_cards, now)
        payload["briefing_index"] = load_briefing_index(data_path)
        if decision["skip"]:
            if previous_card:
                payload["morning_briefing"] = previous_card
            logger.record(
                source="AI 요약",
                endpoint=GEMINI_GENERATE_URL.format(model=os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL)),
                status="no_new_data",
                message=f"카드 생성 스킵: {decision['reason']}",
                metric_count=int((decision.get("changes") or {}).get("changed_count") or 0),
                new_data_count=0,
                started_at=started_at,
                started_monotonic=started_monotonic,
            )
            write_briefing_site_outputs(output_path, data_path, payload, logger)
            return payload

    payload["generated_at"] = now.isoformat(timespec="seconds")
    payload["generated_label"] = now.strftime("%Y-%m-%d %H:%M %Z")
    usage = load_gemini_usage(data_path, briefing_date_key(payload["generated_at"]))
    gemini_allowed = int(usage.get("count") or 0) < GEMINI_DAILY_CALL_LIMIT
    gemini_guard_message = ""
    if not gemini_allowed:
        gemini_guard_message = f"Gemini 일일 호출 {GEMINI_DAILY_CALL_LIMIT}회 도달; 룰 기반 폴백"
    briefing_context = {
        "card_type": card_type,
        "session": decision["session"],
        "low_signal": bool(decision["low_signal"]),
        "reason": decision["reason"],
        "significant": bool(decision["significant"]),
        "benchmark_drivers": (decision.get("benchmark") or {}).get("drivers", []),
        "daily_move_drivers": (decision.get("daily_move") or {}).get("drivers", []),
        "changed_metrics": (decision.get("changes") or {}).get("changes", []),
        "recent_cards": [
            {
                "generated_at": str(card.get("generated_at") or ""),
                "card_type": str(card.get("card_type") or ""),
                "headline": str(card.get("headline") or ""),
                "low_signal": bool(card.get("low_signal")),
                "gate_reason": str(card.get("gate_reason") or ""),
            }
            for card in recent_cards[:6]
            if isinstance(card, dict)
        ],
        "gemini_daily_count_before": int(usage.get("count") or 0),
    }
    base_briefing = build_morning_briefing(
        payload,
        session,
        briefing_context=briefing_context,
        gemini_allowed=gemini_allowed,
        disabled_message=gemini_guard_message or None,
    )
    if base_briefing.get("gemini_call_attempted"):
        usage = increment_gemini_usage(data_path, payload["generated_at"])
        base_briefing["gemini_daily_count"] = int(usage.get("count") or 0)
    trajectory = update_intraday_track(data_path, payload, payload["generated_at"])
    card = build_briefing_card(
        base_briefing,
        card_type=card_type,
        generated_at=payload["generated_at"],
        generated_label=payload["generated_label"],
        trajectory=trajectory,
        low_signal=bool(decision["low_signal"]),
        session_context=decision["session"],
        gate_reason=decision["reason"],
        metric_snapshot=decision["metric_snapshot"],
    )
    payload["morning_briefing"] = card
    payload["briefing_index"] = write_briefing_outputs(data_path, card)

    status_detail = "Gemini 호출" if card.get("gemini_call_attempted") else "룰 기반 폴백"
    if gemini_guard_message:
        status_detail = gemini_guard_message
    logger.record(
        source="AI 요약",
        endpoint=GEMINI_GENERATE_URL.format(model=os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL)),
        status="success",
        message=f"카드 생성: {decision['reason']} ({status_detail})",
        metric_count=int((decision.get("changes") or {}).get("changed_count") or 0),
        new_data_count=1,
        started_at=started_at,
        started_monotonic=started_monotonic,
    )
    write_briefing_site_outputs(output_path, data_path, payload, logger)
    return payload


STALE_THRESHOLD_DAYS = [
    ("일간", 5),
    ("주간", 12),
    ("월간", 45),
    ("분기", 130),
    ("연간", 430),
]


def annotate_metric_freshness(metrics: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """지표 주기 대비 오래된 데이터에 is_stale 표시를 하고 지연 목록을 반환합니다."""
    stale_items: list[dict[str, Any]] = []
    for metric in metrics:
        metric["is_stale"] = False
        if metric.get("status") != "ok":
            continue
        observed = parse_iso_date(metric.get("observed_at"))
        if observed is None:
            continue
        frequency = str(metric.get("frequency") or "")
        threshold = next(
            (days for token, days in STALE_THRESHOLD_DAYS if token in frequency), None
        )
        if threshold is None:
            continue
        age = (today - observed).days
        if age > threshold:
            metric["is_stale"] = True
            metric["stale_days"] = age
            stale_items.append(
                {
                    "id": metric.get("id"),
                    "name": metric.get("name"),
                    "observed_at": metric.get("observed_at"),
                    "days": age,
                }
            )
    return stale_items


def attach_history_store(config: dict[str, Any]) -> HistoryStore | None:
    """config에 히스토리 저장소를 1회 생성해 붙입니다. 수집기와 enrichment가 공유합니다."""
    history_config = config.get("history", {}) or {}
    if not history_config.get("enabled", True):
        return None
    store = config.get("_history_store")
    if not isinstance(store, HistoryStore):
        store = HistoryStore(str(history_config.get("dir") or "data/history"))
        config["_history_store"] = store
    return store


def cached_history_last_date(config: dict[str, Any], key: str) -> date | None:
    """캐시된 마지막 관측일. None이면 최초 백필(전체 기간 요청)이 필요합니다."""
    store = attach_history_store(config)
    if store is None:
        return None
    series = store.series(key)
    return series[-1][0] if series else None


def enrich_metrics_with_history(
    metrics: list[dict[str, Any]],
    config: dict[str, Any],
    previous_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """지표를 장기 히스토리 캐시와 병합하고 백분위 통계와 장기 시리즈를 만듭니다.

    캐시는 repo에 커밋되는 data/history 밑 JSON 파일이므로, 최초 백필 이후에는
    수집기가 최근 구간만 가져와도 전체 기간 시계열이 유지됩니다.
    """
    history_config = config.get("history", {}) or {}
    display_points = int(history_config.get("display_points") or 60)
    store = attach_history_store(config)
    if store is None:
        # 축적이 꺼져 있으면 페이지 무게 보호를 위해 표시 포인트만 남깁니다.
        for metric in metrics:
            history = metric.get("history")
            if isinstance(history, list) and len(history) > display_points:
                metric["history"] = history[-display_points:]
        return {}

    max_long_points = int(history_config.get("long_history_max_points") or 480)

    previous_metrics = (previous_payload or {}).get("metrics", [])
    previous_history_by_id = {
        str(item.get("id")): item.get("history")
        for item in previous_metrics
        if isinstance(item, dict) and item.get("id")
    }

    long_histories: dict[str, Any] = {}
    for metric in metrics:
        if metric.get("status") != "ok":
            continue
        points = parse_stored_points(metric.get("history"))
        if not points:
            continue

        key = str(metric.get("history_key") or "") or f"id-{metric.get('id')}"
        merge_mode = str(metric.get("history_merge") or "full")

        # 이전 배포본의 히스토리를 먼저 병합해 캐시 최초 구축 시 데이터 공백을 줄입니다.
        previous_points = parse_stored_points(previous_history_by_id.get(str(metric.get("id"))))
        if previous_points:
            store.merge(key, previous_points, mode="full")

        full = store.merge(
            key,
            points,
            name=str(metric.get("name") or ""),
            unit=str(metric.get("unit") or ""),
            source=str(metric.get("source") or ""),
            mode=merge_mode,
        )
        if not full:
            continue

        # 스냅샷형 소스는 축적 초기에 캐시가 더 짧을 수 있으므로 긴 쪽을 표시합니다.
        if len(full) >= len(points):
            metric["history"] = [
                {"date": point_date.isoformat(), "value": value}
                for point_date, value in full[-display_points:]
            ]
            metric["period_label"] = period_label(
                metric["history"], str(metric.get("observed_at") or "")
            )

        stats = percentile_stats(full, to_float(metric.get("value")))
        if stats:
            metric["percentiles"] = stats

        if key == US_NET_LIQUIDITY_KEY:
            analysis_cutoff = full[-1][0] - timedelta(days=370)
            metric["_analysis_history"] = [
                {"date": point_date.isoformat(), "value": value}
                for point_date, value in full
                if point_date >= analysis_cutoff
            ]

        if metric.get("yoy_pct") is None and metric.get("value") is not None:
            yoy_value = find_yoy_value(full, full[-1][0])
            yoy_pct = pct_change(to_float(metric.get("value")), yoy_value)
            if yoy_pct is not None:
                metric["yoy_pct"] = yoy_pct
                metric["yoy_pct_label"] = fmt_pct(yoy_pct)

        sampled = downsample_history(full, max_points=max_long_points)
        if len(sampled) > display_points:
            long_histories[str(metric["id"])] = {
                "key": key,
                "unit": str(metric.get("unit") or ""),
                "points": [
                    [point_date.isoformat(), value] for point_date, value in sampled
                ],
            }

    store.save_all()
    return long_histories


def load_previous_dashboard_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def metric_identity(metric: dict[str, Any]) -> str:
    return str(metric.get("history_key") or metric.get("id") or "")


def previous_metric_index(previous_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(previous_payload, dict):
        return {}
    metrics = previous_payload.get("metrics")
    if not isinstance(metrics, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        key = metric_identity(metric)
        if key:
            indexed[key] = metric
        metric_id = str(metric.get("id") or "")
        if metric_id:
            indexed[metric_id] = metric
    return indexed


def metric_observed_advanced(metric: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    if metric.get("status") != "ok":
        return False
    observed_at = str(metric.get("observed_at") or "")
    if not observed_at:
        return False
    if not previous:
        return True
    previous_observed_at = str(previous.get("observed_at") or "")
    if not previous_observed_at:
        return True
    observed_date = parse_iso_date(observed_at)
    previous_date = parse_iso_date(previous_observed_at)
    if observed_date is not None and previous_date is not None:
        return observed_date > previous_date
    return observed_at != previous_observed_at


def fetch_status_label(status: str) -> str:
    return {
        "success": "업데이트됨",
        "no_new_data": "신규 데이터 없음",
        "failed": "수집 실패",
    }.get(status, status)


def infer_metric_fetch_status(metric: dict[str, Any], previous: dict[str, Any] | None) -> str:
    if metric.get("status") != "ok":
        return "failed"
    return "success" if metric_observed_advanced(metric, previous) else "no_new_data"


def apply_fetch_metadata(
    metrics: list[dict[str, Any]],
    fetched_at: str,
    previous_by_key: dict[str, dict[str, Any]],
) -> None:
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        previous = previous_by_key.get(metric_identity(metric)) or previous_by_key.get(str(metric.get("id") or ""))
        status = infer_metric_fetch_status(metric, previous)
        metric["fetched_at"] = fetched_at
        metric["fetch_status"] = status
        metric["fetch_status_label"] = fetch_status_label(status)


def source_new_data_count(
    metrics: list[dict[str, Any]],
    previous_by_key: dict[str, dict[str, Any]],
) -> int:
    count = 0
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        previous = previous_by_key.get(metric_identity(metric)) or previous_by_key.get(str(metric.get("id") or ""))
        if metric_observed_advanced(metric, previous):
            count += 1
    return count


def record_fetch_result(
    source_name: str,
    source_metrics: list[dict[str, Any]],
    previous_by_key: dict[str, dict[str, Any]],
    started_at: str,
    started_monotonic: float,
    message: str,
) -> None:
    logger = current_logger()
    if logger is None:
        return
    ok_count = sum(1 for item in source_metrics if isinstance(item, dict) and item.get("status") == "ok")
    new_count = source_new_data_count(source_metrics, previous_by_key)
    if not source_metrics:
        status = "no_new_data"
    elif ok_count <= 0:
        status = "failed"
    elif new_count > 0:
        status = "success"
    else:
        status = "no_new_data"
    logger.record(
        source=source_name,
        endpoint=FETCH_SOURCE_ENDPOINTS.get(source_name, ""),
        status=status,
        message=message,
        metric_count=len(source_metrics),
        new_data_count=new_count,
        started_at=started_at,
        started_monotonic=started_monotonic,
    )


def record_fetch_failure(
    source_name: str,
    started_at: str,
    started_monotonic: float,
    exc: Exception,
) -> None:
    logger = current_logger()
    if logger is None:
        return
    logger.record(
        source=source_name,
        endpoint=FETCH_SOURCE_ENDPOINTS.get(source_name, ""),
        status="failed",
        message=str(exc),
        metric_count=0,
        new_data_count=0,
        started_at=started_at,
        started_monotonic=started_monotonic,
    )


def write_fetch_log_outputs(data_path: Path, logger: FetchLogger) -> dict[str, Any]:
    run = logger.finish()
    history = append_fetch_log_run(
        load_fetch_log_history(data_path / FETCH_LOG_HISTORY_FILENAME),
        run,
    )
    save_fetch_log_history(data_path / FETCH_LOG_HISTORY_FILENAME, history)
    save_fetch_log_history(data_path / FETCH_LOG_FILENAME, history)
    return history


def market_gauge_snapshot_date(payload: dict[str, Any], timezone_name: str) -> str:
    generated_at = str(payload.get("generated_at") or "")
    try:
        instant = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=ZoneInfo(timezone_name))
        return instant.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    except (TypeError, ValueError):
        return datetime.now(ZoneInfo(timezone_name)).date().isoformat()


def compact_gauge_items(items: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compacted: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        compacted_item = {
            field: item[field]
            for field in fields
            if field in item and item[field] is not None and item[field] != ""
        }
        if compacted_item:
            compacted.append(compacted_item)
    return compacted


def market_gauge_history_snapshot(
    payload: dict[str, Any], timezone_name: str
) -> dict[str, Any] | None:
    gauges = payload.get("market_gauges")
    if not isinstance(gauges, dict) or not gauges:
        return None

    snapshot: dict[str, Any] = {
        "date": market_gauge_snapshot_date(payload, timezone_name),
        "generated_at": str(payload.get("generated_at") or ""),
    }
    thermometer = gauges.get("thermometer")
    if isinstance(thermometer, dict):
        snapshot["thermometer"] = {
            field: thermometer[field]
            for field in ("score", "label", "comment")
            if field in thermometer and thermometer[field] is not None and thermometer[field] != ""
        }
        snapshot["thermometer"]["components"] = compact_gauge_items(
            thermometer.get("components"),
            ("name", "metric_id", "metric_name", "value_label", "percentile", "heat", "basis"),
        )

    recession = gauges.get("recession")
    if isinstance(recession, dict):
        snapshot["recession"] = {
            field: recession[field]
            for field in ("alert_count", "warn_count", "summary")
            if field in recession and recession[field] is not None and recession[field] != ""
        }
        snapshot["recession"]["signals"] = compact_gauge_items(
            recession.get("signals"),
            ("name", "metric_id", "value_label", "status", "description"),
        )

    fear_greed = gauges.get("fear_greed")
    if isinstance(fear_greed, dict):
        snapshot["fear_greed"] = {
            field: fear_greed[field]
            for field in ("comment",)
            if field in fear_greed and fear_greed[field] is not None and fear_greed[field] != ""
        }
        snapshot["fear_greed"]["items"] = compact_gauge_items(
            fear_greed.get("items"),
            ("name", "metric_id", "metric_name", "score", "label", "value_label"),
        )

    if "thermometer" not in snapshot and "recession" not in snapshot and "fear_greed" not in snapshot:
        return None
    return snapshot


def update_market_gauge_history(
    previous_history: dict[str, Any] | None,
    payload: dict[str, Any],
    timezone_name: str,
) -> dict[str, Any]:
    existing = previous_history if isinstance(previous_history, dict) else {}
    raw_snapshots = existing.get("snapshots")
    if not isinstance(raw_snapshots, list):
        raw_snapshots = []
    snapshots = [
        snapshot
        for snapshot in raw_snapshots
        if isinstance(snapshot, dict) and snapshot.get("date")
    ]
    current = market_gauge_history_snapshot(payload, timezone_name)
    if current:
        current_date = str(current["date"])
        snapshots = [snapshot for snapshot in snapshots if str(snapshot.get("date")) != current_date]
        snapshots.append(current)
    snapshots.sort(key=lambda snapshot: str(snapshot.get("date") or ""))

    document: dict[str, Any] = {
        "version": MARKET_GAUGE_HISTORY_VERSION,
        "updated_at": str((current or {}).get("generated_at") or existing.get("updated_at") or ""),
        "count": len(snapshots),
        "snapshots": snapshots,
    }
    if snapshots:
        document["first_date"] = str(snapshots[0].get("date") or "")
        document["last_date"] = str(snapshots[-1].get("date") or "")
    return document


def annotate_dashboard_updates(payload: dict[str, Any], previous_payload: dict[str, Any] | None) -> None:
    metrics = payload.get("metrics", [])
    if not isinstance(metrics, list):
        payload["daily_changes"] = empty_daily_changes(payload)
        return

    previous_metrics = previous_payload.get("metrics", []) if isinstance(previous_payload, dict) else []
    previous_by_id = {
        str(metric.get("id")): metric
        for metric in previous_metrics
        if isinstance(metric, dict) and metric.get("id")
    }
    changed_metrics: list[dict[str, Any]] = []

    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        previous = previous_by_id.get(str(metric.get("id") or ""))
        status = ""
        if previous_payload and previous is None:
            status = "new"
        elif previous_payload and previous is not None and metric_was_updated(metric, previous):
            status = "updated"

        metric["daily_status"] = status
        metric["is_new"] = status == "new"
        metric["is_updated_today"] = status == "updated"
        if previous:
            metric["previous_run_observed_at"] = previous.get("observed_at", "")
            metric["previous_run_value"] = previous.get("value")
            metric["previous_run_display_value"] = previous.get("display_value", "")
        if status:
            changed_metrics.append(daily_change_item(metric, previous, status))

    payload["daily_changes"] = {
        "date": str(payload.get("generated_at") or "")[:10],
        "has_previous": bool(previous_payload),
        "updated_count": sum(1 for item in changed_metrics if item["status"] == "updated"),
        "new_count": sum(1 for item in changed_metrics if item["status"] == "new"),
        "metrics": changed_metrics,
    }


def empty_daily_changes(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": str(payload.get("generated_at") or "")[:10],
        "has_previous": False,
        "updated_count": 0,
        "new_count": 0,
        "metrics": [],
    }


def metric_was_updated(metric: dict[str, Any], previous: dict[str, Any]) -> bool:
    if str(metric.get("observed_at") or "") != str(previous.get("observed_at") or ""):
        return True
    if not numeric_values_equal(metric.get("value"), previous.get("value")):
        return True

    current_latest = latest_history_point(metric)
    previous_latest = latest_history_point(previous)
    if current_latest or previous_latest:
        if str((current_latest or {}).get("date") or "") != str((previous_latest or {}).get("date") or ""):
            return True
        if not numeric_values_equal(
            (current_latest or {}).get("value"),
            (previous_latest or {}).get("value"),
        ):
            return True
    return False


def latest_history_point(metric: dict[str, Any]) -> dict[str, Any] | None:
    history = metric.get("history")
    if not isinstance(history, list) or not history:
        return None
    latest = history[-1]
    return latest if isinstance(latest, dict) else None


def numeric_values_equal(left: object, right: object) -> bool:
    left_number = to_float(left)
    right_number = to_float(right)
    if left_number is None or right_number is None:
        return left == right
    tolerance = max(1e-9, abs(right_number) * 1e-9)
    return abs(left_number - right_number) <= tolerance


def daily_change_item(
    metric: dict[str, Any], previous: dict[str, Any] | None, status: str
) -> dict[str, Any]:
    return {
        "id": metric.get("id", ""),
        "status": status,
        "industry": metric.get("industry", ""),
        "industry_en": metric.get("industry_en", ""),
        "group": metric.get("group", ""),
        "group_en": metric.get("group_en", ""),
        "name": metric.get("name", ""),
        "name_en": metric.get("name_en", ""),
        "display_value": metric.get("display_value", ""),
        "observed_label": metric.get("observed_label", ""),
        "change_pct_label": metric.get("change_pct_label", ""),
        "previous_display_value": previous.get("display_value", "") if previous else "",
        "previous_observed_label": previous.get("observed_label", "") if previous else "",
    }


def build_morning_briefing(
    payload: dict[str, Any],
    session: requests.Session,
    *,
    briefing_context: dict[str, Any] | None = None,
    gemini_allowed: bool = True,
    disabled_message: str | None = None,
) -> dict[str, Any]:
    briefing = rule_based_morning_briefing(payload)
    if briefing_context:
        briefing["briefing_context"] = briefing_context
        briefing["low_signal"] = bool(briefing_context.get("low_signal"))
    briefing["gemini_call_attempted"] = False
    if not gemini_allowed:
        briefing["status"] = "disabled"
        briefing["status_message"] = disabled_message or "Gemini 요약 비활성화"
        return briefing
    if str(os.getenv("GEMINI_BRIEFING_ENABLED", "1")).strip().lower() in {"0", "false", "no", "off"}:
        briefing["status"] = "disabled"
        briefing["status_message"] = "Gemini 요약 비활성화"
        return briefing

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        briefing["status"] = "skipped"
        briefing["status_message"] = "Gemini API 키 없음"
        return briefing

    model = os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL).strip() or GEMINI_DEFAULT_MODEL
    try:
        prompt = gemini_morning_briefing_prompt(payload, briefing)
        briefing["gemini_call_attempted"] = True
        raw_text = request_gemini_briefing(session, api_key, model, prompt)
        parsed = parse_json_object(raw_text)
        return normalize_gemini_briefing(parsed, briefing, model)
    except Exception as exc:  # noqa: BLE001 - the dashboard should still publish without AI text.
        briefing["status"] = "error"
        briefing["status_message"] = f"Gemini 요약 실패: {exc}"
        briefing["model"] = model
        return briefing


def rule_based_morning_briefing(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = [metric for metric in payload.get("metrics", []) if isinstance(metric, dict)]
    top_movers = top_mover_metrics(metrics)
    improving_industries = industry_signal_rows(metrics, "change_pct", reverse=True)[:3]
    slowing_industries = industry_signal_rows(metrics, "yoy_pct", reverse=False)[:3]
    equity_leads = equity_lead_rows(metrics)[:3]
    source_issues = [
        {
            "name": str(source.get("name") or ""),
            "status": str(source.get("status") or ""),
            "message": str(source.get("message") or ""),
        }
        for source in payload.get("source_status", [])
        if isinstance(source, dict) and source.get("status") != "ok"
    ]
    headline = "오늘 변한 지표가 업황에 주는 의미를 먼저 확인하세요."
    if top_movers:
        first = top_movers[0]
        headline = f"{first['industry']} {first['name']} 변화가 눈에 띕니다."
    return {
        "status": "fallback",
        "status_message": "룰 기반 요약",
        "model": "",
        "generated_label": str(payload.get("generated_label") or ""),
        "headline": headline,
        "summary": rule_based_summary(top_movers, improving_industries, slowing_industries, source_issues),
        "bullets": rule_based_bullets(top_movers, improving_industries, slowing_industries, equity_leads),
        "top_movers": top_movers,
        "improving_industries": improving_industries,
        "slowing_industries": slowing_industries,
        "equity_leads": equity_leads,
        "source_issues": source_issues,
    }


def narrative_context_for_briefing(briefing: dict[str, Any], limit: int = 6) -> dict[str, Any]:
    narratives = load_industry_narratives()
    if not narratives:
        return {}

    industry_order = relevant_briefing_industries(briefing, limit)
    industry_map = narratives.get("industries") if isinstance(narratives.get("industries"), dict) else {}
    selected = []
    for industry in industry_order:
        item = industry_map.get(industry) if isinstance(industry_map, dict) else None
        if not isinstance(item, dict):
            continue
        selected.append(
            {
                "industry": industry,
                "narrative": short_text(item.get("narrative"), "", 130),
                "focus_metrics": [short_text(value, "", 32) for value in list(item.get("key_metrics") or [])[:4]],
                "lens": short_text(item.get("lens"), "", 130),
            }
        )
    if not selected:
        return {}
    return {
        "as_of": str(narratives.get("as_of") or ""),
        "global_frame": short_text(narratives.get("global_frame"), "", 170),
        "common_rules": [short_text(value, "", 90) for value in list(narratives.get("common_rules") or [])[:3]],
        "stock_market": compact_stock_market_narrative(narratives.get("stock_market")),
        "industries": selected,
    }


def compact_stock_market_narrative(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "narrative": short_text(value.get("narrative"), "", 230),
        "key_signals": [short_text(item, "", 32) for item in list(value.get("key_signals") or [])[:5]],
        "lens": short_text(value.get("lens"), "", 170),
        "rotation": short_text(value.get("rotation"), "", 130),
    }


def relevant_briefing_industries(briefing: dict[str, Any], limit: int) -> list[str]:
    ordered: list[str] = []

    def add(industry: Any) -> None:
        text = str(industry or "").strip()
        if text and text not in ordered:
            ordered.append(text)

    for metric in briefing.get("top_movers") or []:
        if isinstance(metric, dict):
            add(metric.get("industry"))
    for section in ("improving_industries", "slowing_industries", "equity_leads"):
        for row in briefing.get(section) or []:
            if isinstance(row, dict):
                add(row.get("industry"))
                for metric in row.get("drivers") or []:
                    if isinstance(metric, dict):
                        add(metric.get("industry"))
    return ordered[:limit]


def load_industry_narratives() -> dict[str, Any]:
    candidates = [
        Path.cwd() / "docs" / "industry_narratives.yaml",
        Path(__file__).resolve().parents[2] / "docs" / "industry_narratives.yaml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def top_mover_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated = [metric for metric in metrics if metric.get("daily_status") in {"updated", "new"}]
    candidates = updated or metrics
    ranked = [
        metric
        for metric in candidates
        if to_float(metric.get("change_pct")) is not None
        and not metric.get("exclude_from_movers")
    ]
    ranked.sort(key=lambda metric: abs(to_float(metric.get("change_pct")) or 0.0), reverse=True)
    return [brief_metric(metric) for metric in ranked[:5]]


def industry_signal_rows(
    metrics: list[dict[str, Any]], field: str, *, reverse: bool
) -> list[dict[str, Any]]:
    by_industry: dict[str, list[tuple[float, dict[str, Any]]]] = defaultdict(list)
    for metric in metrics:
        value = to_float(metric.get(field))
        if value is None:
            continue
        signal = value * metric_direction(metric)
        by_industry[str(metric.get("industry") or "매크로")].append((signal, metric))

    rows: list[dict[str, Any]] = []
    for industry, items in by_industry.items():
        if not items:
            continue
        score = sum(signal for signal, _metric in items) / len(items)
        drivers = sorted(items, key=lambda item: abs(item[0]), reverse=True)[:2]
        rows.append(
            {
                "industry": industry,
                "score": round(score, 2),
                "drivers": [brief_metric(metric) for _signal, metric in drivers],
            }
        )
    rows.sort(key=lambda row: row["score"], reverse=reverse)
    return rows


def equity_lead_rows(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_industry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        by_industry[str(metric.get("industry") or "매크로")].append(metric)

    rows: list[dict[str, Any]] = []
    for industry, items in by_industry.items():
        equities = [metric for metric in items if str(metric.get("group") or "") == "대표주가"]
        fundamentals = [metric for metric in items if str(metric.get("group") or "") != "대표주가"]
        equity_values = [to_float(metric.get("change_pct")) for metric in equities]
        fundamental_values = [to_float(metric.get("change_pct")) for metric in fundamentals]
        equity_values = [value for value in equity_values if value is not None]
        fundamental_values = [value for value in fundamental_values if value is not None]
        if not equity_values or not fundamental_values:
            continue
        equity_score = sum(equity_values) / len(equity_values)
        fundamental_score = sum(fundamental_values) / len(fundamental_values)
        gap = equity_score - fundamental_score
        if abs(equity_score) < 2 and abs(gap) < 3:
            continue
        if equity_score * fundamental_score > 0 and abs(gap) < 5:
            continue
        rows.append(
            {
                "industry": industry,
                "equity_score": round(equity_score, 2),
                "fundamental_score": round(fundamental_score, 2),
                "gap": round(gap, 2),
                "drivers": [
                    brief_metric(max(equities, key=lambda metric: abs(to_float(metric.get("change_pct")) or 0.0))),
                    brief_metric(max(fundamentals, key=lambda metric: abs(to_float(metric.get("change_pct")) or 0.0))),
                ],
            }
        )
    rows.sort(key=lambda row: abs(row["gap"]), reverse=True)
    return rows


def metric_direction(metric: dict[str, Any]) -> int:
    text = " ".join(
        str(metric.get(key) or "")
        for key in ("name", "group", "meaning")
    )
    lower_is_better_keywords = (
        "VIX",
        "스프레드",
        "금리",
        "연체율",
        "모기지",
        "위험",
        "리스크",
    )
    return -1 if any(keyword in text for keyword in lower_is_better_keywords) else 1


def brief_metric(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(metric.get("id") or ""),
        "industry": str(metric.get("industry") or ""),
        "group": str(metric.get("group") or ""),
        "kind": metric_kind_label(metric),
        "name": str(metric.get("name") or ""),
        "value": str(metric.get("display_value") or ""),
        "observed_label": str(metric.get("observed_label") or ""),
        "change_pct": to_float(metric.get("change_pct")),
        "change_pct_label": str(metric.get("change_pct_label") or ""),
        "yoy_pct": to_float(metric.get("yoy_pct")),
        "yoy_pct_label": str(metric.get("yoy_pct_label") or ""),
        "meaning": short_text(metric.get("meaning"), "", 120),
    }


def metric_kind_label(metric: dict[str, Any]) -> str:
    group = str(metric.get("group") or "")
    name = str(metric.get("name") or "")
    text = f"{group} {name}"
    if group == "대표주가":
        return "대표주가(주식 가격)"
    if group == "시장지수":
        return "시장지수"
    if "WSTS" in text or "판매액" in group:
        return "반도체 판매액"
    if "CAPEX" in text.upper():
        return "설비투자(CAPEX)"
    if any(keyword in text for keyword in ("원자재", "유가", "철광석", "구리", "알루미늄", "니켈", "석탄", "천연가스")):
        return "원자재/에너지 가격"
    if any(keyword in text for keyword in ("금리", "스프레드", "OAS", "연체율", "대출")):
        return "금융여건 지표"
    if "수출" in text:
        return "수출 지표"
    if any(keyword in text for keyword in ("승인", "임상", "발사", "계약", "충전")):
        return "산업 활동 지표"
    return group or "업황 지표"


def metric_change_meaning(metric: dict[str, Any]) -> str:
    group = str(metric.get("group") or "")
    name = str(metric.get("name") or "")
    text = f"{group} {name}"
    change = to_float(metric.get("change_pct"))
    improved = change is None or change * metric_direction(metric) >= 0

    if group == "대표주가":
        return "실적이 바로 바뀌었다기보다, 시장이 해당 산업의 기대와 위험을 다시 가격에 반영한 신호로 볼 수 있습니다."
    if group == "시장지수":
        return "개별 산업보다 전체 투자심리와 위험 선호가 움직였는지 확인하는 신호입니다."
    if "CAPEX" in text.upper():
        return "AI와 클라우드 인프라 투자가 앞으로도 강하게 이어질지 보여주는 단서입니다."
    if "판매액" in group or "WSTS" in group:
        return "반도체가 실제로 얼마나 팔리고 있는지 보여주기 때문에 업황의 바닥과 회복 속도를 보는 데 중요합니다."
    if any(keyword in text for keyword in ("원자재", "유가", "철광석", "구리", "알루미늄", "리튬")):
        return "소재와 제조업의 비용 부담이 커지는지 줄어드는지 확인하는 지표입니다."
    if any(keyword in text for keyword in ("금리", "스프레드", "모기지", "연체율")):
        return "돈을 빌리는 부담과 금융 스트레스가 완화되는지 악화되는지 보는 지표입니다."
    if any(keyword in text for keyword in ("승인", "임상", "발사", "계약", "충전")):
        return "해당 산업의 실제 활동량과 투자 속도가 살아나는지 확인하는 힌트입니다."
    return "하루 가격 움직임만 보기보다, 같은 산업의 수요·투자·실적 지표와 같이 보면 의미가 더 분명해집니다." if improved else "단기 변동일 수 있으니, 같은 산업의 수요·투자·실적 지표도 함께 확인하는 편이 좋습니다."


def metric_change_summary(metric: dict[str, Any]) -> str:
    change = str(metric.get("change_pct_label") or "변동")
    kind = str(metric.get("kind") or metric.get("group") or "지표")
    return f"{metric['industry']}의 {kind}인 {metric['name']}가 {change} 움직였습니다. {metric_change_meaning(metric)}"


def topic_label(text: str) -> str:
    return f"{text}{topic_particle(text)}"


def topic_particle(text: str) -> str:
    for char in reversed(str(text or "").strip()):
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3:
            return "은" if (code - 0xAC00) % 28 else "는"
        if char.isalnum():
            return "는"
    return "는"


def rule_based_summary(
    top_movers: list[dict[str, Any]],
    improving_industries: list[dict[str, Any]],
    slowing_industries: list[dict[str, Any]],
    source_issues: list[dict[str, Any]],
) -> str:
    parts = []
    if top_movers:
        parts.append(metric_change_summary(top_movers[0]))
    if improving_industries:
        industry = improving_industries[0]["industry"]
        parts.append(f"{industry} 쪽은 최근 지표 흐름이 상대적으로 좋아져 수요나 투자 강도가 살아있는지 볼 만합니다.")
    if slowing_industries:
        industry = slowing_industries[0]["industry"]
        parts.append(f"{topic_label(industry)} 전년 대비 힘이 약해진 항목이 있어, 회복이 이어지는지 한 번 더 확인하는 게 좋습니다.")
    if source_issues:
        parts.append("일부 지표는 아직 새 값이 들어오지 않았을 수 있어 오늘 바뀐 항목을 우선 보면 됩니다.")
    return " ".join(parts) or "오늘 새로 해석할 만큼 크게 움직인 지표가 아직 많지 않습니다."


def rule_based_bullets(
    top_movers: list[dict[str, Any]],
    improving_industries: list[dict[str, Any]],
    slowing_industries: list[dict[str, Any]],
    equity_leads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bullets: list[dict[str, Any]] = []
    if top_movers:
        bullets.append(
            {
                "title": "급변 지표",
                "body": metric_change_summary(top_movers[0]),
                "metric_ids": [item["id"] for item in top_movers[:3] if item.get("id")],
            }
        )
    if improving_industries:
        row = improving_industries[0]
        bullets.append(
            {
                "title": "좋아진 흐름",
                "body": f"{topic_label(row['industry'])} 여러 지표가 상대적으로 좋아져 수요나 투자 강도가 유지되는지 볼 만합니다.",
                "metric_ids": [item["id"] for item in row.get("drivers", []) if item.get("id")],
            }
        )
    if slowing_industries:
        row = slowing_industries[0]
        bullets.append(
            {
                "title": "주의할 흐름",
                "body": f"{topic_label(row['industry'])} 전년 대비 힘이 약해진 항목이 있어 회복 속도를 조심해서 봐야 합니다.",
                "metric_ids": [item["id"] for item in row.get("drivers", []) if item.get("id")],
            }
        )
    if equity_leads:
        row = equity_leads[0]
        bullets.append(
            {
                "title": "주가와 지표 차이",
                "body": f"{topic_label(row['industry'])} 주가와 실제 지표의 움직임 차이가 커서 기대가 앞서가는지 확인이 필요합니다.",
                "metric_ids": [item["id"] for item in row.get("drivers", []) if item.get("id")],
            }
        )
    return bullets

def gemini_morning_briefing_prompt(payload: dict[str, Any], briefing: dict[str, Any]) -> str:
    briefing_context = briefing.get("briefing_context") if isinstance(briefing.get("briefing_context"), dict) else {}
    session_context = briefing_context.get("session") if isinstance(briefing_context.get("session"), dict) else {}
    session_label = str(session_context.get("label") or "세션 외")
    prompt_focus = str(session_context.get("prompt_focus") or "")
    low_signal = bool(briefing_context.get("low_signal"))
    card_type = str(briefing_context.get("card_type") or "")
    context = {
        "generated_label": payload.get("generated_label", ""),
        "briefing_context": briefing_context,
        "session_label": session_label,
        "low_signal": low_signal,
        "narrative_context": narrative_context_for_briefing(briefing),
        "top_movers": briefing.get("top_movers", []),
        "improving_industries": briefing.get("improving_industries", []),
        "slowing_industries": briefing.get("slowing_industries", []),
        "equity_leads": briefing.get("equity_leads", []),
        "source_issues": briefing.get("source_issues", []),
        "daily_changes": payload.get("daily_changes", {}),
        "upcoming_events": (payload.get("calendar", {}) or {}).get("upcoming", []),
    }
    session_instruction = (
        f"현재 실행 세션은 '{session_label}'이다. {prompt_focus}\n"
        "한국장 카드라면 코스피·코스닥과 국내 수급을 우선하고, 미국장 카드라면 미국 지수·환율·미국 대표주를 우선하라.\n"
        "특히 미국장 카드는 마지막 문장에 내일 한국장에 줄 함의를 짧게 넣어라.\n"
    )
    low_signal_instruction = (
        "이번 카드는 low_signal=true다. 변화는 있지만 유의미성이 낮으므로 과장하지 말고, headline·summary를 담백하게 쓰고 bullets는 1~2개만 사용하라.\n"
        if low_signal
        else ""
    )
    close_instruction = ""
    if card_type == "close":
        close_instruction = (
            "이번 카드는 한국장 마감 카드다. recent_cards와 changed_metrics를 함께 보고 당일 한국장 흐름을 종합하라. "
            "코스피·코스닥·수급·환율을 우선하고 다음 거래일에 확인할 점으로 마무리하라.\n"
        )
    elif card_type == "us_close":
        close_instruction = (
            "이번 카드는 미국장 마감 카드다. 미국 지수·환율·미국 대표주 움직임을 우선하고 내일 한국장에 줄 함의로 마무리하라.\n"
        )
    return (
        "너는 개인 투자자가 매일 아침 산업별 지표 대시보드를 빠르게 훑도록 돕는 한국어 브리핑 작성자다.\n"
        "아래 JSON 데이터만 근거로 사용하고, 매수/매도 추천이나 목표가는 쓰지 마라.\n"
        f"{session_instruction}"
        f"{low_signal_instruction}"
        f"{close_instruction}"
        "가장 중요한 목표는 오늘 바뀐 지표가 어떤 의미인지 쉬운 말로 설명하는 것이다.\n"
        "각 지표를 언급할 때는 name만 쓰지 말고 반드시 kind와 industry를 함께 써라. 예: '로봇 대표주가(주식 가격) Teradyne(TER)'처럼 쓴다.\n"
        "narrative_context는 시장이 요즘 그 산업을 보는 관점이다. 단, 지표 데이터와 충돌하면 지표 데이터를 우선하고 내러티브는 해석 렌즈로만 사용하라.\n"
        "narrative_context.stock_market은 주식시장 전체가 주가를 가격화하는 방식이다. 대표주가가 움직일 때는 산업 실물지표와 stock_market의 밸류에이션·금리·포지셔닝 렌즈를 함께 사용하라.\n"
        "어려운 통계 용어를 피하고, 수요가 강해졌는지, 비용 부담이 커졌는지, 투자심리가 흔들렸는지처럼 사용자가 바로 이해할 수 있게 써라.\n"
        "주가 지표는 기업 실적 자체가 아니라 시장 기대와 위험 선호가 움직인 신호라는 점을 구분해서 설명하라.\n"
        "월간·분기 지표는 새 발표 전까지 그대로일 수 있으니, daily_changes와 top_movers를 우선해서 해석하라.\n"
        "upcoming_events에 오늘·내일 FOMC, 금통위, CPI, 만기일 같은 큰 일정이 있으면 관망 심리나 변동성 가능성을 짧게 언급하라.\n"
        "불확실하거나 데이터 공백이 있으면 사용자 친화적으로 짧게 말하라.\n"
        "출력은 설명 없이 JSON 객체 하나만 반환하라.\n"
        "스키마: {\"headline\": string, \"summary\": string, \"bullets\": "
        "[{\"title\": string, \"body\": string, \"metric_ids\": [string]}]}\n"
        "headline은 40자 이내로 오늘의 핵심 변화를 쉽게 말하라.\n"
        "summary는 2문장 이내로 '무엇이 변했고 왜 봐야 하는지'를 설명하라.\n"
        "bullets는 3~5개이며 title은 '급변 지표', '좋아진 흐름', '주의할 흐름', '주가와 지표 차이'처럼 짧은 항목명으로 쓰고, body는 '변한 지표의 종류 + 의미 + 다음에 볼 것'을 한 문장으로 써라.\n"
        f"데이터:\n{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}"
    )


def request_gemini_briefing(
    session: requests.Session, api_key: str, model: str, prompt: str
) -> str:
    url = GEMINI_GENERATE_URL.format(model=model)
    response = session.post(
        url,
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 900,
                "responseMimeType": "application/json",
            },
        },
        timeout=30,
    )
    response.raise_for_status()
    text = extract_gemini_text(response.json())
    if not text:
        raise RuntimeError("Gemini 응답에 텍스트가 없습니다.")
    return text


def extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""
    texts = [str(part.get("text") or "") for part in parts if isinstance(part, dict)]
    return "\n".join(text for text in texts if text).strip()


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Gemini JSON 응답이 객체가 아닙니다.")
    return parsed


def normalize_gemini_briefing(
    parsed: dict[str, Any], fallback: dict[str, Any], model: str
) -> dict[str, Any]:
    briefing = dict(fallback)
    briefing.update(
        {
            "status": "ok",
            "status_message": "Gemini 요약",
            "model": model,
            "headline": short_text(parsed.get("headline"), fallback.get("headline", ""), 80),
            "summary": short_text(parsed.get("summary"), fallback.get("summary", ""), 360),
            "bullets": normalize_briefing_bullets(parsed.get("bullets"), fallback.get("bullets", [])),
        }
    )
    return briefing


def normalize_briefing_bullets(value: Any, fallback: Any) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else fallback
    bullets: list[dict[str, Any]] = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        metric_ids = item.get("metric_ids")
        bullets.append(
            {
                "title": short_text(item.get("title"), "체크포인트", 40),
                "body": short_text(item.get("body"), "", 220),
                "metric_ids": [
                    str(metric_id)
                    for metric_id in (metric_ids if isinstance(metric_ids, list) else [])
                    if metric_id
                ][:3],
            }
        )
    return bullets

def short_text(value: Any, fallback: Any, max_length: int) -> str:
    text = str(value if value not in (None, "") else fallback or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_length]


def copy_dashboard_assets(output_path: Path) -> None:
    candidates = [
        Path.cwd() / "assets",
        Path(__file__).resolve().parents[2] / "assets",
    ]
    assets_source = next((path for path in candidates if path.exists()), None)
    if assets_source is None:
        return

    source = assets_source / "industry-icons"
    target = output_path / "assets" / "industry-icons"
    if source.exists():
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target, dirs_exist_ok=True)

    assets_target = output_path / "assets"
    assets_target.mkdir(parents=True, exist_ok=True)
    for filename in (
        "marketbrief-logo.svg",
        "marketbrief-logo.png",
        "pwa-icon-192.png",
        "pwa-icon-512.png",
    ):
        source_file = assets_source / filename
        if source_file.exists():
            shutil.copyfile(source_file, assets_target / filename)

    manifest = assets_source / "manifest.webmanifest"
    if manifest.exists():
        shutil.copyfile(manifest, output_path / "manifest.webmanifest")

    service_worker = assets_source / "service-worker.js"
    if service_worker.exists():
        build_ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        worker_text = service_worker.read_text(encoding="utf-8").replace("__BUILD_TS__", build_ts)
        (output_path / "service-worker.js").write_text(worker_text, encoding="utf-8")


def build_dashboard_payload(
    config: dict[str, Any],
    session: requests.Session,
    previous_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timezone = str(config.get("timezone") or "Asia/Seoul")
    now = datetime.now(ZoneInfo(timezone))
    fetched_at = now.isoformat(timespec="seconds")
    previous_by_key = previous_metric_index(previous_payload)

    source_status: list[dict[str, str]] = []
    metrics: list[dict[str, Any]] = []

    collectors = [
        ("WSTS", collect_wsts_metrics),
        ("FRED", collect_fred_metrics),
        ("ECOS 신용스프레드", collect_ecos_credit_spread_metrics),
        ("ECOS 매크로", collect_ecos_series_metrics),
        ("대표주가/시장지수", collect_equity_price_metrics),
        ("스테이블코인", collect_stablecoin_metrics),
        ("World Bank 원자재", collect_world_bank_commodity_metrics),
        ("SEC CAPEX", collect_sec_capex_metrics),
        ("USAspending 방산", collect_usaspending_metrics),
        ("EIA", collect_eia_metrics),
        ("openFDA", collect_openfda_metrics),
        ("ClinicalTrials.gov", collect_clinical_trials_metrics),
        ("Launch Library", collect_launch_library_metrics),
        ("AFDC EV 충전", collect_afdc_metrics),
        ("KOSIS", collect_kosis_metrics),
        ("한국 수출", collect_korea_export_metrics),
        ("밸류에이션/수급", collect_valuation_metrics),
        ("시장 수급", collect_market_flow_metrics),
    ]
    for source_name, collector in collectors:
        before = len(metrics)
        logger = current_logger()
        started_at, started_monotonic = logger.source_started() if logger else (fetched_at, time.monotonic())
        try:
            source_metrics = collector(config, session, now.date())
            metrics.extend(source_metrics)
            ok_count = sum(1 for item in source_metrics if item.get("status") == "ok")
            message = f"{ok_count}/{len(source_metrics)}개 지표 자동 수집"
            issue_summary = metric_issue_summary(source_metrics)
            if issue_summary:
                message = f"{message} ({issue_summary})"
            source_status.append(
                {
                    "name": source_name,
                    "status": "ok" if ok_count else "partial",
                    "message": sanitize_message(message),
                }
            )
            record_fetch_result(
                source_name,
                source_metrics,
                previous_by_key,
                started_at,
                started_monotonic,
                message,
            )
        except Exception as exc:  # noqa: BLE001 - dashboard should survive source-level failures.
            source_status.append({"name": source_name, "status": "error", "message": sanitize_message(str(exc))})
            record_fetch_failure(source_name, started_at, started_monotonic, exc)
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

    before = len(metrics)
    logger = current_logger()
    started_at, started_monotonic = logger.source_started() if logger else (fetched_at, time.monotonic())
    try:
        source_metrics = collect_us_liquidity_metrics(config, session, now.date(), metrics)
        metrics.extend(source_metrics)
        ok_count = sum(1 for item in source_metrics if item.get("status") == "ok")
        message = f"{ok_count}/{len(source_metrics)}개 지표 자동 수집"
        issue_summary = metric_issue_summary(source_metrics)
        if issue_summary:
            message = f"{message} ({issue_summary})"
        source_status.append(
            {
                "name": "미국 유동성",
                "status": "ok" if source_metrics and ok_count == len(source_metrics) else "partial",
                "message": sanitize_message(message),
            }
        )
        record_fetch_result(
            "미국 유동성",
            source_metrics,
            previous_by_key,
            started_at,
            started_monotonic,
            message,
        )
    except Exception as exc:  # noqa: BLE001 - liquidity failure should not block the dashboard.
        source_status.append({"name": "미국 유동성", "status": "error", "message": sanitize_message(str(exc))})
        record_fetch_failure("미국 유동성", started_at, started_monotonic, exc)
        if len(metrics) == before:
            metrics.append(
                make_metric(
                    industry="매크로",
                    name="미국 유동성 수집 상태",
                    source="미국 유동성",
                    source_url="",
                    frequency="",
                    automation="무료로 안정적으로 자동화 가능",
                    status="error",
                    note=str(exc),
                    group="미국 유동성",
                    section="market",
                    market_category="금리·채권",
                )
            )

    before = len(metrics)
    logger = current_logger()
    started_at, started_monotonic = logger.source_started() if logger else (fetched_at, time.monotonic())
    try:
        source_metrics = collect_market_sentiment_metrics(config, session, now.date(), metrics)
        metrics.extend(source_metrics)
        ok_count = sum(1 for item in source_metrics if item.get("status") == "ok")
        message = f"{ok_count}/{len(source_metrics)}개 지표 자동 수집"
        issue_summary = metric_issue_summary(source_metrics)
        if issue_summary:
            message = f"{message} ({issue_summary})"
        source_status.append(
            {
                "name": "시장 심리",
                "status": "ok" if source_metrics and ok_count == len(source_metrics) else "partial",
                "message": sanitize_message(message),
            }
        )
        record_fetch_result(
            "시장 심리",
            source_metrics,
            previous_by_key,
            started_at,
            started_monotonic,
            message,
        )
    except Exception as exc:  # noqa: BLE001 - sentiment failure should not block the dashboard.
        source_status.append({"name": "시장 심리", "status": "error", "message": sanitize_message(str(exc))})
        record_fetch_failure("시장 심리", started_at, started_monotonic, exc)
        if len(metrics) == before:
            metrics.append(
                make_metric(
                    industry="매크로",
                    name="시장 심리 수집 상태",
                    source="시장 심리",
                    source_url="",
                    frequency="",
                    automation="부분 자동화 가능",
                    status="error",
                    note=str(exc),
                    group="공포탐욕",
                )
            )

    before = len(metrics)
    logger = current_logger()
    started_at, started_monotonic = logger.source_started() if logger else (fetched_at, time.monotonic())
    try:
        source_metrics = collect_market_derived_metrics(config, session, now.date(), metrics)
        metrics.extend(source_metrics)
        ok_count = sum(1 for item in source_metrics if item.get("status") == "ok")
        message = f"{ok_count}/{len(source_metrics)}개 지표 자동 수집"
        source_status.append(
            {
                "name": "시장 파생지표",
                "status": "ok" if ok_count == len(source_metrics) else "partial",
                "message": sanitize_message(message),
            }
        )
        record_fetch_result(
            "시장 파생지표",
            source_metrics,
            previous_by_key,
            started_at,
            started_monotonic,
            message,
        )
    except Exception as exc:  # noqa: BLE001
        source_status.append({"name": "시장 파생지표", "status": "error", "message": sanitize_message(str(exc))})
        record_fetch_failure("시장 파생지표", started_at, started_monotonic, exc)
        if len(metrics) == before:
            metrics.append(
                make_metric(
                    industry="매크로",
                    name="시장 파생지표 수집 상태",
                    source="시장 파생지표",
                    source_url="",
                    frequency="",
                    automation="부분 자동화 가능",
                    status="error",
                    note=str(exc),
                    group="시장 분위기",
                    section="market",
                    market_category="심리·변동성",
                )
            )

    metrics.extend(collect_reference_metrics(config))
    apply_fetch_metadata(metrics, fetched_at, previous_by_key)
    assign_market_navigation_fields(metrics)
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
        "search_aliases": config.get("search_aliases", {}) or {},
        "source_status": source_status,
        "metrics": metrics,
    }


def metric_issue_summary(metrics: list[dict[str, Any]], limit: int = 3) -> str:
    issues: list[str] = []
    warning_tokens = ("이전 저장값 표시", "응답 실패", "관측값 없음", "API_KEY 없음")
    for metric in metrics:
        note = str(metric.get("note") or metric.get("status_label") or metric.get("status") or "").strip()
        has_warning_note = any(token in note for token in warning_tokens)
        if metric.get("status") == "ok" and not has_warning_note:
            continue
        name = str(metric.get("name") or "지표")
        compact = f"{name}: {note}" if note else name
        if compact not in issues:
            issues.append(compact)
    if not issues:
        return ""
    shown = issues[:limit]
    suffix = f" 외 {len(issues) - limit}개" if len(issues) > limit else ""
    return " / ".join(shown) + suffix


def collect_fred_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    dashboard_config = config.get("dashboard", {})
    fred_config = config.get("fred", {})
    if not fred_config.get("enabled", True):
        return []

    series_config = dashboard_config.get("fred_series") or fred_config.get("series", [])
    api_key = os.getenv("FRED_API_KEY", "").strip()

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
                depth=str(series.get("depth") or ""),
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

        history_key = f"fred-{series_id}"
        cached_last = cached_history_last_date(config, history_key)
        # 최초 1회만 전체 기간을 백필하고, 이후에는 개정치 반영을 위해 최근 450일만 다시 받습니다.
        observation_start = (
            (cached_last - timedelta(days=450)).isoformat() if cached_last else ""
        )

        try:
            points, source_label = fetch_fred_history(
                session=session,
                series_id=series_id,
                api_key=api_key,
                observation_start=observation_start,
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
                        depth=str(series.get("depth") or ""),
                    )
                )
                continue

            scale = to_float(series.get("scale")) or 1.0
            if scale != 1.0:
                points = [(point_date, value * scale) for point_date, value in points]
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
                    history=points,
                    note=str(series.get("note") or ""),
                    group=str(series.get("group") or ""),
                    depth=str(series.get("depth") or ""),
                    meaning=str(series.get("meaning") or ""),
                    history_key=history_key,
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
    session: requests.Session,
    series_id: str,
    api_key: str,
    observation_start: str = "",
) -> tuple[list[tuple[date, float]], str]:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
    }
    if observation_start:
        params["observation_start"] = observation_start
    response = session.get(FRED_OBSERVATIONS_URL, params=params, timeout=(5, 30))
    response.raise_for_status()
    payload = response.json()
    points = []
    for item in payload.get("observations", []):
        value = to_float(item.get("value"))
        if value is None:
            continue
        points.append((date.fromisoformat(str(item["date"])), value))
    points.sort(key=lambda point: point[0])
    return points, "FRED API"


US_LIQUIDITY_GROUP = "미국 유동성"
US_LIQUIDITY_CATEGORY = "금리·채권"
US_NET_LIQUIDITY_KEY = "us-net-liquidity"
US_TGA_DAILY_KEY = "fiscaldata-tga"
US_RRP_KEY = "fred-RRPONTSYD"


def collect_us_liquidity_metrics(
    config: dict[str, Any],
    session: requests.Session,
    today: date,
    existing_metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    liquidity_config = config.get("us_liquidity", {}) or {}
    if liquidity_config.get("enabled", True) is False:
        return []

    api_key = os.getenv("FRED_API_KEY", "").strip()
    walcl_points = component_points_from_metric_or_store(config, existing_metrics, "fred-WALCL")
    walcl_metric = metric_by_history_key(existing_metrics, "fred-WALCL")
    if not walcl_points and api_key:
        walcl_points, _ = fetch_scaled_fred_component(
            config=config,
            session=session,
            series_id="WALCL",
            api_key=api_key,
            history_key="fred-WALCL",
            scale=0.001,
        )

    tga_metric, tga_points = collect_tga_component_metric(config, session, api_key, today)
    rrp_metric, rrp_points = collect_rrp_component_metric(config, session, api_key)
    net_metric = build_net_liquidity_metric(walcl_points, tga_points, rrp_points)
    walcl_market_metric = build_walcl_market_metric(walcl_metric, walcl_points)

    ordered = [net_metric, walcl_market_metric, tga_metric, rrp_metric]
    return [metric for metric in ordered if metric]


def metric_by_history_key(
    metrics: list[dict[str, Any]], history_key: str
) -> dict[str, Any] | None:
    for metric in metrics:
        if isinstance(metric, dict) and str(metric.get("history_key") or "") == history_key:
            return metric
    return None


def component_points_from_metric_or_store(
    config: dict[str, Any],
    metrics: list[dict[str, Any]],
    history_key: str,
) -> list[tuple[date, float]]:
    metric = metric_by_history_key(metrics, history_key)
    incoming = parse_stored_points(metric.get("history") if isinstance(metric, dict) else None)
    return merged_component_points(config, history_key, incoming)


def merged_component_points(
    config: dict[str, Any],
    history_key: str,
    incoming: list[tuple[date, float]],
) -> list[tuple[date, float]]:
    merged: dict[date, float] = {}
    store = attach_history_store(config)
    if store is not None:
        for point_date, value in store.series(history_key):
            merged[point_date] = value
    for point_date, value in incoming:
        merged[point_date] = value
    return sorted(merged.items(), key=lambda item: item[0])


def fetch_scaled_fred_component(
    *,
    config: dict[str, Any],
    session: requests.Session,
    series_id: str,
    api_key: str,
    history_key: str,
    scale: float = 1.0,
) -> tuple[list[tuple[date, float]], str]:
    cached_last = cached_history_last_date(config, history_key)
    observation_start = (cached_last - timedelta(days=450)).isoformat() if cached_last else ""
    incoming, source_label = fetch_fred_history(
        session=session,
        series_id=series_id,
        api_key=api_key,
        observation_start=observation_start,
    )
    if scale != 1.0:
        incoming = [(point_date, value * scale) for point_date, value in incoming]
    return merged_component_points(config, history_key, incoming), source_label


def collect_rrp_component_metric(
    config: dict[str, Any],
    session: requests.Session,
    api_key: str,
) -> tuple[dict[str, Any], list[tuple[date, float]]]:
    name = "미국 역레포"
    source_url = "https://fred.stlouisfed.org/series/RRPONTSYD"
    if not api_key:
        return (
            make_metric(
                industry="매크로",
                name=name,
                source="FRED API",
                source_url=source_url,
                frequency="일간",
                automation="무료로 안정적으로 자동화 가능",
                status="needs_key",
                note="GitHub Secrets에 FRED_API_KEY 등록 필요",
                group=US_LIQUIDITY_GROUP,
                meaning=US_RRP_MEANING,
                metric_id="us-rrp",
                section="market",
                market_category=US_LIQUIDITY_CATEGORY,
                history_key=US_RRP_KEY,
            ),
            [],
        )
    try:
        points, source_label = fetch_scaled_fred_component(
            config=config,
            session=session,
            series_id="RRPONTSYD",
            api_key=api_key,
            history_key=US_RRP_KEY,
            scale=0.001,
        )
        if not points:
            raise ValueError("관측값 없음")
        latest_date, latest_value = points[-1]
        previous_value = points[-2][1] if len(points) > 1 else None
        yoy_value = find_yoy_value(points, latest_date)
        return (
            make_metric(
                industry="매크로",
                name=name,
                source=source_label,
                source_url=source_url,
                frequency="일간",
                automation="무료로 안정적으로 자동화 가능",
                status="ok",
                value=latest_value,
                unit="$B",
                observed_at=latest_date.isoformat(),
                previous_value=previous_value,
                yoy_value=yoy_value,
                history=points,
                group=US_LIQUIDITY_GROUP,
                meaning=US_RRP_MEANING,
                metric_id="us-rrp",
                section="market",
                market_category=US_LIQUIDITY_CATEGORY,
                history_key=US_RRP_KEY,
            ),
            points,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            make_metric(
                industry="매크로",
                name=name,
                source="FRED",
                source_url=source_url,
                frequency="일간",
                automation="무료로 안정적으로 자동화 가능",
                status="error",
                note=str(exc),
                group=US_LIQUIDITY_GROUP,
                meaning=US_RRP_MEANING,
                metric_id="us-rrp",
                section="market",
                market_category=US_LIQUIDITY_CATEGORY,
                history_key=US_RRP_KEY,
            ),
            [],
        )


US_NET_LIQUIDITY_MEANING = (
    "연준이 공급한 돈에서 재무부 금고(TGA)와 역레포에 잠긴 돈을 뺀, 실제로 금융시장에 돌고 있는 달러 "
    "유동성입니다. 증가하면 위험자산에 우호적, 감소하면 부담이 되는 흐름으로 해석합니다. 계산은 WALCL, "
    "TGA, 역레포의 관측일이 다를 때 각 날짜 이전의 가장 최근 값을 사용합니다."
)
US_TGA_MEANING = (
    "재무부가 연준에 맡겨둔 현금입니다. TGA가 늘면 시중 유동성이 흡수되고, 줄면 방출됩니다. "
    "부채한도 협상 국면에서 크게 출렁입니다."
)
US_RRP_MEANING = (
    "시중 자금이 연준에 하루짜리로 파킹된 규모입니다. 줄어들면 그만큼 시장에 유동성이 풀려나오는 효과가 있습니다."
)


def collect_tga_component_metric(
    config: dict[str, Any],
    session: requests.Session,
    api_key: str,
    today: date,
) -> tuple[dict[str, Any], list[tuple[date, float]]]:
    try:
        points = fetch_fiscaldata_tga_history(config, session)
        if not points:
            raise ValueError("FiscalData TGA 관측값 없음")
        return build_tga_metric(
            points,
            source="FiscalData DTS API",
            source_url=FISCALDATA_TGA_URL,
            frequency="일간",
            history_key=US_TGA_DAILY_KEY,
            note="",
        ), points
    except Exception as fiscal_exc:  # noqa: BLE001 - fallback to weekly FRED TGA.
        if not api_key:
            return (
                make_metric(
                    industry="매크로",
                    name="미국 TGA",
                    source="FiscalData DTS API",
                    source_url=FISCALDATA_TGA_URL,
                    frequency="일간",
                    automation="무료로 안정적으로 자동화 가능",
                    status="error",
                    note=f"FiscalData 실패: {fiscal_exc}",
                    group=US_LIQUIDITY_GROUP,
                    meaning=US_TGA_MEANING,
                    metric_id="us-tga",
                    section="market",
                    market_category=US_LIQUIDITY_CATEGORY,
                    history_key=US_TGA_DAILY_KEY,
                ),
                [],
            )
        try:
            points, source_label = fetch_scaled_fred_component(
                config=config,
                session=session,
                series_id="WTREGEN",
                api_key=api_key,
                history_key="fred-WTREGEN",
                scale=0.001,
            )
            if not points:
                raise ValueError("FRED WTREGEN 관측값 없음")
            return build_tga_metric(
                points,
                source=source_label,
                source_url="https://fred.stlouisfed.org/series/WTREGEN",
                frequency="주간",
                history_key="fred-WTREGEN",
                note=f"FiscalData 일간 TGA 실패로 FRED WTREGEN 주간값 사용: {fiscal_exc}",
            ), points
        except Exception as fred_exc:  # noqa: BLE001
            return (
                make_metric(
                    industry="매크로",
                    name="미국 TGA",
                    source="FiscalData/FRED",
                    source_url=FISCALDATA_TGA_URL,
                    frequency="일간/주간",
                    automation="무료로 안정적으로 자동화 가능",
                    status="error",
                    note=f"FiscalData 실패: {fiscal_exc}; FRED 실패: {fred_exc}",
                    group=US_LIQUIDITY_GROUP,
                    meaning=US_TGA_MEANING,
                    metric_id="us-tga",
                    section="market",
                    market_category=US_LIQUIDITY_CATEGORY,
                    history_key=US_TGA_DAILY_KEY,
                ),
                [],
            )


def fetch_fiscaldata_tga_history(
    config: dict[str, Any],
    session: requests.Session,
) -> list[tuple[date, float]]:
    cached_last = cached_history_last_date(config, US_TGA_DAILY_KEY)
    params: dict[str, str] = {
        "fields": "record_date,account_type,open_today_bal",
        "filter": "account_type:eq:Treasury General Account (TGA) Closing Balance",
        "sort": "record_date",
        "page[size]": "10000",
    }
    if cached_last:
        start = (cached_last - timedelta(days=45)).isoformat()
        params["filter"] = (
            "account_type:eq:Treasury General Account (TGA) Closing Balance,"
            f"record_date:gte:{start}"
        )
    response = session.get(FISCALDATA_TGA_URL, params=params, timeout=(10, 45))
    response.raise_for_status()
    payload = response.json()
    incoming: list[tuple[date, float]] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        point_date_text = str(item.get("record_date") or "")
        value = to_float(item.get("open_today_bal"))
        if value is None:
            continue
        try:
            point_date = date.fromisoformat(point_date_text)
        except ValueError:
            continue
        # FiscalData DTS balances are reported in millions of dollars.
        incoming.append((point_date, value / 1000.0))
    incoming.sort(key=lambda point: point[0])
    return merged_component_points(config, US_TGA_DAILY_KEY, incoming)


def build_tga_metric(
    points: list[tuple[date, float]],
    *,
    source: str,
    source_url: str,
    frequency: str,
    history_key: str,
    note: str,
) -> dict[str, Any]:
    latest_date, latest_value = points[-1]
    previous_value = points[-2][1] if len(points) > 1 else None
    yoy_value = find_yoy_value(points, latest_date)
    return make_metric(
        industry="매크로",
        name="미국 TGA",
        source=source,
        source_url=source_url,
        frequency=frequency,
        automation="무료로 안정적으로 자동화 가능",
        status="ok",
        value=latest_value,
        unit="$B",
        observed_at=latest_date.isoformat(),
        previous_value=previous_value,
        yoy_value=yoy_value,
        history=points,
        note=note,
        group=US_LIQUIDITY_GROUP,
        meaning=US_TGA_MEANING,
        metric_id="us-tga",
        section="market",
        market_category=US_LIQUIDITY_CATEGORY,
        history_key=history_key,
    )


def build_walcl_market_metric(
    walcl_metric: dict[str, Any] | None,
    walcl_points: list[tuple[date, float]],
) -> dict[str, Any] | None:
    if not walcl_points:
        return None
    latest_date, latest_value = walcl_points[-1]
    previous_value = walcl_points[-2][1] if len(walcl_points) > 1 else None
    yoy_value = find_yoy_value(walcl_points, latest_date)
    source = str((walcl_metric or {}).get("source") or "FRED API")
    meaning = str((walcl_metric or {}).get("meaning") or "")
    if not meaning:
        meaning = "연준 대차대조표 규모로 양적완화/긴축 방향을 보여줍니다. 글로벌 유동성의 큰 물줄기를 확인하는 지표입니다."
    return make_metric(
        industry="매크로",
        name="미국 연준 총자산",
        source=source,
        source_url="https://fred.stlouisfed.org/series/WALCL",
        frequency="주간",
        automation="무료로 안정적으로 자동화 가능",
        status="ok",
        value=latest_value,
        unit="$B",
        observed_at=latest_date.isoformat(),
        previous_value=previous_value,
        yoy_value=yoy_value,
        history=walcl_points,
        group=US_LIQUIDITY_GROUP,
        meaning=meaning,
        history_key="fred-WALCL",
        metric_id="us-liquidity-walcl",
        section="market",
        market_category=US_LIQUIDITY_CATEGORY,
    )


def build_net_liquidity_metric(
    walcl_points: list[tuple[date, float]],
    tga_points: list[tuple[date, float]],
    rrp_points: list[tuple[date, float]],
) -> dict[str, Any] | None:
    net_points = calculate_us_net_liquidity(walcl_points, tga_points, rrp_points)
    if not net_points:
        return make_metric(
            industry="매크로",
            name="미국 순유동성",
            source="FRED/FiscalData",
            source_url=FISCALDATA_TGA_URL,
            frequency="일간",
            automation="무료로 안정적으로 자동화 가능",
            status="error",
            note="WALCL, TGA, 역레포 중 계산에 필요한 시계열이 부족합니다.",
            group=US_LIQUIDITY_GROUP,
            meaning=US_NET_LIQUIDITY_MEANING,
            history_key=US_NET_LIQUIDITY_KEY,
            metric_id="us-net-liquidity",
            section="market",
            market_category=US_LIQUIDITY_CATEGORY,
        )
    latest_date, latest_value = net_points[-1]
    previous_value = net_points[-2][1] if len(net_points) > 1 else None
    yoy_value = find_yoy_value(net_points, latest_date)
    return make_metric(
        industry="매크로",
        name="미국 순유동성",
        source="FRED/FiscalData",
        source_url=FISCALDATA_TGA_URL,
        frequency="일간",
        automation="무료로 안정적으로 자동화 가능",
        status="ok",
        value=latest_value,
        unit="$B",
        observed_at=latest_date.isoformat(),
        previous_value=previous_value,
        yoy_value=yoy_value,
        history=net_points,
        group=US_LIQUIDITY_GROUP,
        meaning=US_NET_LIQUIDITY_MEANING,
        history_key=US_NET_LIQUIDITY_KEY,
        metric_id="us-net-liquidity",
        section="market",
        market_category=US_LIQUIDITY_CATEGORY,
    )


def calculate_us_net_liquidity(
    walcl_points: list[tuple[date, float]],
    tga_points: list[tuple[date, float]],
    rrp_points: list[tuple[date, float]],
) -> list[tuple[date, float]]:
    components = [walcl_points, tga_points, rrp_points]
    if any(not points for points in components):
        return []
    start = max(points[0][0] for points in components)
    end = max(points[-1][0] for points in components)
    if start > end:
        return []

    aligned: list[tuple[date, float]] = []
    indexes = [0, 0, 0]
    current = start
    while current <= end:
        values: list[float] = []
        for component_index, points in enumerate(components):
            while indexes[component_index] + 1 < len(points) and points[indexes[component_index] + 1][0] <= current:
                indexes[component_index] += 1
            if points[indexes[component_index]][0] > current:
                values = []
                break
            values.append(points[indexes[component_index]][1])
        if len(values) == 3:
            walcl, tga, rrp = values
            aligned.append((current, walcl - tga - rrp))
        current += timedelta(days=1)
    return aligned


def collect_ecos_credit_spread_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    ecos_config = config.get("ecos", {})
    if not ecos_config.get("enabled", True):
        return []

    items = ecos_config.get("credit_spreads", [])
    if not items:
        return []

    api_key = os.getenv("ECOS_API_KEY", "").strip()
    fetch_days = int(ecos_config.get("fetch_days", 730))
    backfill_days = int(ecos_config.get("backfill_days", 9200))
    row_count = int(ecos_config.get("row_count", 1000))
    if api_key == "sample":
        fetch_days = min(fetch_days, 14)
        backfill_days = min(backfill_days, 14)
        row_count = min(row_count, 10)
    source_url = str(ecos_config.get("source_url") or "https://ecos.bok.or.kr/api/")

    if not api_key:
        return [
            make_metric(
                industry=str(item.get("industry") or "은행/금융"),
                name=str(item.get("name") or "한국 신용 스프레드"),
                source="한국은행 ECOS API",
                source_url=source_url,
                frequency=str(item.get("frequency") or "일간"),
                automation="무료로 안정적으로 자동화 가능",
                status="needs_key",
                note="GitHub Secrets에 ECOS_API_KEY 등록 필요",
                group=str(item.get("group") or "신용 스프레드"),
                meaning=str(item.get("meaning") or ""),
            )
            for item in items
        ]

    metrics: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or "한국 신용 스프레드")
        industry = str(item.get("industry") or "은행/금융")
        frequency = str(item.get("frequency") or "일간")
        group = str(item.get("group") or "신용 스프레드")
        meaning = str(item.get("meaning") or "")
        stat_code = str(item.get("stat_code") or "817Y002")
        corporate_code = str(item.get("corporate_item_code") or "")
        treasury_code = str(item.get("treasury_item_code") or "")
        history_key = f"ecos-spread-{stat_code}-{corporate_code}-{treasury_code}"
        # 최초 1회는 ECOS가 제공하는 과거 구간을 넓게 백필하고, 이후엔 최근 구간만 갱신합니다.
        if cached_history_last_date(config, history_key) is None:
            item_fetch_start = today - timedelta(days=backfill_days)
            item_row_count = max(row_count, 20000)
        else:
            item_fetch_start = today - timedelta(days=fetch_days)
            item_row_count = row_count
        try:
            corporate_points = fetch_ecos_points(
                session=session,
                base_url=str(ecos_config.get("endpoint") or "https://ecos.bok.or.kr/api"),
                api_key=api_key,
                stat_code=stat_code,
                period=str(item.get("period") or "D"),
                start=item_fetch_start,
                end=today,
                item_code=corporate_code,
                row_count=item_row_count,
            )
            treasury_points = fetch_ecos_points(
                session=session,
                base_url=str(ecos_config.get("endpoint") or "https://ecos.bok.or.kr/api"),
                api_key=api_key,
                stat_code=stat_code,
                period=str(item.get("period") or "D"),
                start=item_fetch_start,
                end=today,
                item_code=treasury_code,
                row_count=item_row_count,
            )
            points = compute_spread_points(corporate_points, treasury_points)
            if not points:
                metrics.append(
                    make_metric(
                        industry=industry,
                        name=name,
                        source="한국은행 ECOS API",
                        source_url=source_url,
                        frequency=frequency,
                        automation="무료로 안정적으로 자동화 가능",
                        status="error",
                        note="관측값 없음",
                        group=group,
                        meaning=meaning,
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
                    source="한국은행 ECOS API",
                    source_url=source_url,
                    frequency=frequency,
                    automation="무료로 안정적으로 자동화 가능",
                    status="ok",
                    value=latest_value,
                    unit=str(item.get("unit") or "%"),
                    observed_at=latest_date.isoformat(),
                    previous_value=previous_value,
                    yoy_value=yoy_value,
                    history=points,
                    note=str(item.get("note") or ""),
                    group=group,
                    meaning=meaning,
                    history_key=history_key,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one ECOS item should not break the dashboard.
            metrics.append(
                make_metric(
                    industry=industry,
                    name=name,
                    source="한국은행 ECOS API",
                    source_url=source_url,
                    frequency=frequency,
                    automation="무료로 안정적으로 자동화 가능",
                    status="error",
                    note=str(exc),
                    group=group,
                    meaning=meaning,
                )
            )
    return metrics


def collect_ecos_series_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    """ECOS 단일 통계 시리즈(소비자심리지수, 선행지수 등) 수집기."""
    ecos_config = config.get("ecos", {})
    if not ecos_config.get("enabled", True):
        return []

    items = ecos_config.get("series", [])
    if not items:
        return []

    api_key = os.getenv("ECOS_API_KEY", "").strip()
    source_url = str(ecos_config.get("source_url") or "https://ecos.bok.or.kr/api/")
    fetch_days = int(ecos_config.get("series_fetch_days", 1100))
    backfill_days = int(ecos_config.get("backfill_days", 9200))

    if not api_key:
        return [
            make_metric(
                industry=str(item.get("industry") or "매크로"),
                name=str(item.get("name") or "ECOS 지표"),
                source="한국은행 ECOS API",
                source_url=source_url,
                frequency=str(item.get("frequency") or "월간"),
                automation="무료로 안정적으로 자동화 가능",
                status="needs_key",
                note="GitHub Secrets에 ECOS_API_KEY 등록 필요",
                group=str(item.get("group") or ""),
                meaning=str(item.get("meaning") or ""),
            )
            for item in items
        ]

    metrics: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or "ECOS 지표")
        industry = str(item.get("industry") or "매크로")
        frequency = str(item.get("frequency") or "월간")
        group = str(item.get("group") or "")
        meaning = str(item.get("meaning") or "")
        stat_code = str(item.get("stat_code") or "")
        period = str(item.get("period") or "M")
        item_code = str(item.get("item_code") or "")
        item_code2 = str(item.get("item_code2") or "")
        if not stat_code or not item_code:
            continue

        history_key = f"ecos-{stat_code}-{item_code}{('-' + item_code2) if item_code2 else ''}"
        if cached_history_last_date(config, history_key) is None:
            start = today - timedelta(days=backfill_days)
            row_count = 20000
        else:
            start = today - timedelta(days=fetch_days)
            row_count = 2000

        try:
            points = fetch_ecos_points(
                session=session,
                base_url=str(ecos_config.get("endpoint") or "https://ecos.bok.or.kr/api"),
                api_key=api_key,
                stat_code=stat_code,
                period=period,
                start=start,
                end=today,
                item_code=item_code,
                item_code2=item_code2,
                row_count=row_count,
            )
            scale = to_float(item.get("scale")) or 1.0
            if scale != 1.0:
                points = [(point_date, value * scale) for point_date, value in points]
            if not points:
                metrics.append(
                    make_metric(
                        industry=industry,
                        name=name,
                        source="한국은행 ECOS API",
                        source_url=source_url,
                        frequency=frequency,
                        automation="무료로 안정적으로 자동화 가능",
                        status="error",
                        note="관측값 없음",
                        group=group,
                        meaning=meaning,
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
                    source="한국은행 ECOS API",
                    source_url=source_url,
                    frequency=frequency,
                    automation="무료로 안정적으로 자동화 가능",
                    status="ok",
                    value=latest_value,
                    unit=str(item.get("unit") or ""),
                    observed_at=latest_date.isoformat(),
                    previous_value=previous_value,
                    yoy_value=yoy_value,
                    history=points,
                    note=str(item.get("note") or ""),
                    group=group,
                    meaning=meaning,
                    history_key=history_key,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one ECOS item should not break the dashboard.
            metrics.append(
                make_metric(
                    industry=industry,
                    name=name,
                    source="한국은행 ECOS API",
                    source_url=source_url,
                    frequency=frequency,
                    automation="무료로 안정적으로 자동화 가능",
                    status="error",
                    note=str(exc),
                    group=group,
                    meaning=meaning,
                )
            )
    return metrics


def fetch_ecos_points(
    *,
    session: requests.Session,
    base_url: str,
    api_key: str,
    stat_code: str,
    period: str,
    start: date,
    end: date,
    item_code: str,
    item_code2: str = "",
    row_count: int = 1000,
) -> list[tuple[date, float]]:
    if not item_code:
        return []
    period_upper = period.upper()
    if period_upper == "M":
        start_text, end_text = start.strftime("%Y%m"), end.strftime("%Y%m")
    elif period_upper == "Q":
        start_text = f"{start.year}Q{(start.month - 1) // 3 + 1}"
        end_text = f"{end.year}Q{(end.month - 1) // 3 + 1}"
    elif period_upper == "A":
        start_text, end_text = str(start.year), str(end.year)
    else:
        start_text, end_text = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    url = (
        f"{base_url.rstrip('/')}/StatisticSearch/{api_key}/json/kr/1/{row_count}/"
        f"{stat_code}/{period}/{start_text}/{end_text}/{item_code}"
    )
    if item_code2:
        url = f"{url}/{item_code2}"
    response = session.get(url, timeout=(5, 20))
    response.raise_for_status()
    return parse_ecos_points(response.json(), period)


def parse_ecos_points(payload: dict[str, Any], period: str = "D") -> list[tuple[date, float]]:
    result = payload.get("RESULT") or {}
    code = str(result.get("CODE") or "")
    if code and code != "INFO-200":
        raise ValueError(str(result.get("MESSAGE") or code))

    rows = (payload.get("StatisticSearch") or {}).get("row") or []
    points: list[tuple[date, float]] = []
    for row in rows:
        observed_at = parse_ecos_period(str(row.get("TIME") or ""), period)
        value = to_float(row.get("DATA_VALUE"))
        if observed_at is None or value is None:
            continue
        points.append((observed_at, value))
    points.sort(key=lambda point: point[0])
    return points


def parse_ecos_period(value: str, period: str = "D") -> date | None:
    if not value:
        return None
    compact_period = period.upper()
    try:
        if compact_period == "D" and len(value) >= 8:
            return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        if compact_period == "M" and len(value) >= 6:
            return date(int(value[:4]), int(value[4:6]), 1)
        if compact_period == "Q" and "Q" in value.upper():
            year_text, quarter_text = value.upper().split("Q", 1)
            return date(int(year_text), (int(quarter_text) - 1) * 3 + 1, 1)
        if len(value) >= 4:
            return date(int(value[:4]), 1, 1)
    except ValueError:
        return None
    return None


def compute_spread_points(
    corporate_points: list[tuple[date, float]],
    treasury_points: list[tuple[date, float]],
) -> list[tuple[date, float]]:
    treasury_by_date = dict(treasury_points)
    spreads = [
        (observed_at, round(corporate_value - treasury_by_date[observed_at], 4))
        for observed_at, corporate_value in corporate_points
        if observed_at in treasury_by_date
    ]
    spreads.sort(key=lambda point: point[0])
    return spreads


def collect_equity_price_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    del today
    equities_config = config.get("equities", {})
    if not equities_config.get("enabled", True):
        return []

    items = equities_config.get("items", [])
    if not items:
        return []

    endpoint_template = str(
        equities_config.get("endpoint")
        or "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    )
    source_url = str(equities_config.get("source_url") or "https://finance.yahoo.com/")
    metrics: list[dict[str, Any]] = []

    for item in items:
        symbol = str(item.get("symbol") or "").strip()
        if not symbol:
            continue
        name = str(item.get("name") or symbol)
        industry = str(item.get("industry") or "매크로")
        url = endpoint_template.format(symbol=symbol)
        quote_url = f"{source_url.rstrip('/')}/quote/{symbol}"
        history_key = f"equity-{symbol}"
        # 캐시가 없으면 상장 이후 전체(max)를 1회 백필하고, 이후에는 최근 3개월만 갱신합니다.
        fetch_range = "max" if cached_history_last_date(config, history_key) is None else str(
            item.get("range") or "3mo"
        )

        try:
            points, currency = fetch_equity_history_with_fallback(
                session, url, fetch_range, symbol
            )
            if not points:
                metrics.append(
                    make_metric(
                        industry=industry,
                        name=name,
                        source="Yahoo Finance chart API",
                        source_url=quote_url,
                        frequency="일간",
                        automation="무료 공개 JSON 자동 수집",
                        status="error",
                        note="관측값 없음",
                        group=str(item.get("group") or "대표주가"),
                        depth=str(item.get("depth") or ""),
                        meaning=str(item.get("meaning") or equity_price_meaning(name)),
                        section=str(item.get("section") or ""),
                        market_category=str(item.get("market_category") or ""),
                        also_market_category=item.get("also_market_category") or "",
                        refresh_scope=str(item.get("refresh_scope") or ""),
                        chart_style=str(item.get("chart_style") or ""),
                    )
                )
                continue

            unit = str(
                item.get("unit")
                or ("원" if currency == "KRW" else "$" if currency == "USD" else currency)
            )
            latest_date, latest_value = points[-1]
            previous_value = points[-2][1] if len(points) > 1 else None
            yoy_value = find_yoy_value(points, latest_date)
            metrics.append(
                make_metric(
                    industry=industry,
                    name=name,
                    source="Yahoo Finance chart API",
                    source_url=quote_url,
                    frequency="일간",
                    automation="무료 공개 JSON 자동 수집",
                    status="ok",
                    value=latest_value,
                    unit=unit,
                    observed_at=latest_date.isoformat(),
                    previous_value=previous_value,
                    yoy_value=yoy_value,
                    history=points,
                    note=str(item.get("note") or ""),
                    group=str(item.get("group") or "대표주가"),
                    depth=str(item.get("depth") or ""),
                    meaning=str(item.get("meaning") or equity_price_meaning(name)),
                    history_key=history_key,
                    section=str(item.get("section") or ""),
                    market_category=str(item.get("market_category") or ""),
                    also_market_category=item.get("also_market_category") or "",
                    refresh_scope=str(item.get("refresh_scope") or ""),
                    chart_style=str(item.get("chart_style") or ""),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one ticker should not break the dashboard.
            metrics.append(
                make_metric(
                    industry=industry,
                    name=name,
                    source="Yahoo Finance chart API",
                    source_url=quote_url,
                    frequency="일간",
                    automation="무료 공개 JSON 자동 수집",
                    status="error",
                    note=str(exc),
                    group=str(item.get("group") or "대표주가"),
                    depth=str(item.get("depth") or ""),
                    meaning=str(item.get("meaning") or equity_price_meaning(name)),
                    section=str(item.get("section") or ""),
                    market_category=str(item.get("market_category") or ""),
                    also_market_category=item.get("also_market_category") or "",
                    refresh_scope=str(item.get("refresh_scope") or ""),
                    chart_style=str(item.get("chart_style") or ""),
                )
            )
    return metrics


def parse_yahoo_chart_points(payload: dict[str, Any]) -> tuple[list[tuple[date, float]], str]:
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise ValueError(str(chart.get("error")))
    result = (chart.get("result") or [None])[0]
    if not isinstance(result, dict):
        return [], ""

    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    adjclose_item = ((result.get("indicators") or {}).get("adjclose") or [{}])[0]
    adjclose = adjclose_item.get("adjclose") or []
    meta = result.get("meta") or {}
    currency = str(meta.get("currency") or "")
    exchange_timezone = yahoo_exchange_timezone(meta)
    by_date: dict[date, float] = {}
    for index, timestamp in enumerate(timestamps):
        value = None
        if index < len(closes):
            value = to_float(closes[index])
        if value is None and index < len(adjclose):
            value = to_float(adjclose[index])
        if value is None:
            continue
        observed_at = datetime.fromtimestamp(int(timestamp), tz=exchange_timezone).date()
        by_date[observed_at] = value
    return sorted(by_date.items()), currency


def yahoo_exchange_timezone(meta: dict[str, Any]) -> timezone | ZoneInfo:
    timezone_name = str(
        meta.get("exchangeTimezoneName") or meta.get("timezone") or ""
    ).strip()
    if timezone_name:
        try:
            return ZoneInfo(timezone_name)
        except Exception:  # noqa: BLE001 - fall back to UTC when Yahoo returns an alias.
            pass
    return timezone.utc


def fetch_equity_history_with_fallback(
    session: requests.Session, url: str, fetch_range: str, symbol: str
) -> tuple[list[tuple[date, float]], str]:
    """Yahoo 차트 API를 우선 사용하고, 한국 종목/지수는 실패 시 네이버로 폴백합니다."""
    try:
        response = session.get(
            url,
            params={"range": fetch_range, "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0 stock-industry-dashboard/1.0"},
            timeout=(5, 30),
        )
        response.raise_for_status()
        points, currency = parse_yahoo_chart_points(response.json())
        if points:
            return points, currency
        raise ValueError("Yahoo 관측값 없음")
    except Exception:
        naver_symbol = naver_fallback_symbol(symbol)
        if not naver_symbol:
            raise
        count = 8000 if fetch_range == "max" else 90
        return fetch_naver_chart_points(session, naver_symbol, count), "KRW"


def naver_fallback_symbol(symbol: str) -> str:
    """네이버 fchart에서 쓸 심볼. 한국 종목/지수만 지원합니다."""
    if symbol == "^KS11":
        return "KOSPI"
    if symbol == "^KQ11":
        return "KOSDAQ"
    match = re.match(r"^(\d{6})\.(KS|KQ)$", symbol)
    if match:
        return match.group(1)
    return ""


def fetch_naver_chart_points(
    session: requests.Session, symbol: str, count: int
) -> list[tuple[date, float]]:
    response = session.get(
        "https://fchart.stock.naver.com/sise.nhn",
        params={
            "symbol": symbol,
            "timeframe": "day",
            "count": count,
            "requestType": "0",
        },
        headers={"User-Agent": "Mozilla/5.0 stock-industry-dashboard/1.0"},
        timeout=(5, 30),
    )
    response.raise_for_status()
    points: list[tuple[date, float]] = []
    for match in re.finditer(r'data="(\d{8})\|[^|]*\|[^|]*\|[^|]*\|([0-9.]+)\|', response.text):
        date_text, close_text = match.group(1), match.group(2)
        try:
            observed_at = date(int(date_text[:4]), int(date_text[4:6]), int(date_text[6:8]))
            points.append((observed_at, float(close_text)))
        except ValueError:
            continue
    points.sort(key=lambda point: point[0])
    return points


def equity_price_meaning(name: str) -> str:
    return f"{name} 주가는 시장이 해당 기업의 성장성과 위험을 어떻게 평가하는지 보여줍니다."


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

        history_key = f"stablecoin-{symbol or asset_id or name}"
        history: list[tuple[date, float]] = []
        history_merge = "latest"
        # 최초 1회는 DefiLlama 히스토리 엔드포인트로 전체 기간(2017~)을 백필합니다.
        if cached_history_last_date(config, history_key) is None:
            try:
                resolved_id = asset_id
                if not resolved_id and symbol != "TOTAL":
                    matched = find_stablecoin_asset(assets, symbol=symbol, asset_id="")
                    resolved_id = str((matched or {}).get("id") or "")
                history = fetch_stablecoin_chart_history(
                    session,
                    str(stablecoin_config.get("charts_endpoint") or "https://stablecoins.llama.fi/stablecoincharts/all"),
                    resolved_id if symbol != "TOTAL" else "",
                )
                if history:
                    history_merge = "full"
            except Exception:  # noqa: BLE001 - 백필 실패는 스냅샷 축적으로 대체합니다.
                history = []
        if not history:
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
                history_key=history_key,
                history_merge=history_merge,
            )
        )
    return metrics


def fetch_stablecoin_chart_history(
    session: requests.Session, charts_endpoint: str, asset_id: str
) -> list[tuple[date, float]]:
    """DefiLlama 차트 엔드포인트에서 유통량 전체 히스토리를 $B 단위로 가져옵니다."""
    params = {"stablecoin": asset_id} if asset_id else None
    response = session.get(charts_endpoint, params=params, timeout=(5, 30))
    response.raise_for_status()
    rows = response.json()
    points: list[tuple[date, float]] = []
    if not isinstance(rows, list):
        return points
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = to_float(row.get("date"))
        circulating = row.get("totalCirculatingUSD") or row.get("totalCirculating") or {}
        value = None
        if isinstance(circulating, dict):
            value = to_float(circulating.get("peggedUSD"))
        if timestamp is None or value is None:
            continue
        observed_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date()
        points.append((observed_at, value / 1_000_000_000))
    points.sort(key=lambda point: point[0])
    return points


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
                history=scaled_points,
                note=str(item.get("note") or ""),
                group=group,
                meaning=meaning,
                history_key=f"worldbank-{column}",
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
    metrics: list[dict[str, Any]] = []

    for company in companies:
        raw_cik = str(company.get("cik") or "").strip()
        if not raw_cik:
            continue
        cik = raw_cik.zfill(10)
        ticker = str(company.get("ticker") or cik)
        name = str(company.get("name") or ticker or "CAPEX")
        metric_name = str(company.get("metric_name") or name)
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
                        meaning=sec_capex_meaning(name),
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
                    history=billion_points,
                    group="CAPEX",
                    meaning=sec_capex_meaning(name),
                    history_key=f"sec-capex-{ticker}",
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
                    meaning=sec_capex_meaning(name),
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


def sec_capex_meaning(company_name: str = "빅테크") -> str:
    display_name = company_name.replace(" CAPEX", "").strip() or "빅테크"
    if display_name in CAPEX_MEANINGS:
        return CAPEX_MEANINGS[display_name]
    return (
        f"{display_name}의 CAPEX는 데이터센터, 서버, AI 인프라 같은 장기 설비투자 규모를 보여줍니다. "
        "투자가 커질수록 클라우드와 AI 인프라 수요가 강하다는 신호로 볼 수 있습니다."
    )


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
    metrics: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        history_key = f"usaspending-{item.get('key') or index}"
        months_back = int(item.get("months_back") or spending_config.get("months_back") or 18)
        # 최초 1회는 과거 구간을 넓게 백필합니다. 한 번의 응답에 전체 기간이 담기므로 추가 호출 부담이 없습니다.
        if cached_history_last_date(config, history_key) is None:
            months_back = max(
                months_back, int(spending_config.get("backfill_months") or 144)
            )
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
                    history=billion_points,
                    group=group,
                    meaning=meaning,
                    history_key=history_key,
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
        history_key = f"eia-{series_id}"
        # 최초 백필은 EIA 1회 응답 최대치(5000행), 이후에는 최근 구간만 갱신합니다.
        fetch_limit = 5000 if cached_history_last_date(config, history_key) is None else 120

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
                    history=scaled_points,
                    group=str(series.get("group") or ""),
                    meaning=str(series.get("meaning") or ""),
                    history_key=history_key,
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
    metrics: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        name = str(item.get("name") or "FDA 의약품 승인 활동")
        months_back = int(item.get("months_back") or openfda_config.get("months_back") or 18)
        history_key = f"openfda-{item.get('key') or index}"
        fetch_months = months_needing_fetch(
            config,
            history_key,
            today,
            months_back,
            backfill_months=int(openfda_config.get("backfill_months") or 240),
            max_backfill_per_run=int(openfda_config.get("backfill_per_run") or 24),
        )
        base_search = str(
            item.get("search")
            or "submissions.submission_status:AP"
        )
        points: list[tuple[date, float]] = []
        try:
            for month in fetch_months:
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
                    history_key=history_key,
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
    metrics: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        name = str(item.get("name") or "글로벌 임상 시작 건수")
        months_back = int(item.get("months_back") or trials_config.get("months_back") or 18)
        history_key = f"clinicaltrials-{item.get('key') or index}"
        fetch_months = months_needing_fetch(
            config,
            history_key,
            today,
            months_back,
            backfill_months=int(trials_config.get("backfill_months") or 240),
            max_backfill_per_run=int(trials_config.get("backfill_per_run") or 24),
        )
        extra_query = str(item.get("query") or "")
        points: list[tuple[date, float]] = []
        try:
            for month in fetch_months:
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
                    history_key=history_key,
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
    metrics: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        name = str(item.get("name") or "글로벌 우주 발사 건수")
        months_back = int(item.get("months_back") or launch_config.get("months_back") or 18)
        history_key = f"launchlibrary-{item.get('key') or index}"
        # Launch Library 무료 티어는 시간당 15회 제한이라 백필 폭을 보수적으로 잡습니다.
        if cached_history_last_date(config, history_key) is None:
            months_back = max(months_back, int(launch_config.get("backfill_months") or 48))
        try:
            months = completed_months(today, months_back)
            points = launch_library_monthly_counts(session, endpoint, months)
            metrics.append(
                event_count_metric(
                    points=points,
                    history_key=history_key,
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
    session: requests.Session, url: str, *, params: dict[str, Any], attempts: int = 1
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
                history_key=f"afdc-{key}",
                history_merge="latest",
                group=str(item.get("group") or "충전 인프라"),
                meaning=str(
                    item.get("meaning")
                    or "미국 EV 충전 인프라 규모로 전기차를 이용하기 쉬워지고 있는지 확인합니다."
                ),
            )
        )
    return metrics


def collect_kosis_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    del today
    kosis_config = config.get("kosis", {})
    if not kosis_config.get("enabled", True):
        return []

    items = kosis_config.get("items", [])
    if not items:
        return []

    api_key = os.getenv("KOSIS_API_KEY", "").strip()
    endpoint = str(
        kosis_config.get("endpoint")
        or "https://kosis.kr/openapi/Param/statisticsParameterData.do"
    )
    source_url = str(kosis_config.get("source_url") or "https://kosis.kr/openapi/")
    history_limit = int(config.get("dashboard", {}).get("history_points", 48))

    def cached_kosis_metric(item: dict[str, Any], history_key: str, note: str) -> dict[str, Any] | None:
        store = attach_history_store(config)
        if store is None:
            return None
        points = store.series(history_key)
        if not points:
            return None
        latest_date, latest_value = points[-1]
        previous_value = points[-2][1] if len(points) > 1 else None
        yoy_value = find_yoy_value(points, latest_date)
        return make_metric(
            industry=str(item.get("industry") or "건설/부동산"),
            name=str(item.get("name") or item.get("tbl_id") or "KOSIS 지표"),
            source="KOSIS OpenAPI",
            source_url=source_url,
            frequency=str(item.get("frequency") or "월간"),
            automation="무료 공식 API 자동 수집",
            status="ok",
            value=latest_value,
            unit=str(item.get("unit") or ""),
            observed_at=latest_date.isoformat(),
            previous_value=previous_value,
            yoy_value=yoy_value,
            history=points[-history_limit:],
            note=f"{note}; 이전 저장값 표시",
            group=str(item.get("group") or "국내 주택"),
            meaning=str(item.get("meaning") or ""),
            history_key=history_key,
        )

    if not api_key:
        metrics: list[dict[str, Any]] = []
        for item in items:
            if not item.get("tbl_id") or not item.get("item_id"):
                continue
            org_id = str(item.get("org_id") or item.get("orgId") or "").strip()
            tbl_id = str(item.get("tbl_id") or item.get("tblId") or "").strip()
            item_id = item.get("item_id") or item.get("itmId")
            history_key = f"kosis-{org_id}-{tbl_id}-{kosis_code_param(item_id).rstrip('+')}"
            cached = cached_kosis_metric(item, history_key, "KOSIS_API_KEY 없음")
            metrics.append(
                cached
                or make_metric(
                    industry=str(item.get("industry") or "건설/부동산"),
                    name=str(item.get("name") or item.get("tbl_id") or "KOSIS 지표"),
                    source="KOSIS OpenAPI",
                    source_url=source_url,
                    frequency=str(item.get("frequency") or "월간"),
                    automation="무료 공식 API 자동 수집",
                    status="needs_key",
                    note="GitHub Secrets에 KOSIS_API_KEY 등록 필요",
                    group=str(item.get("group") or "국내 주택"),
                    meaning=str(item.get("meaning") or ""),
                )
            )
        return metrics

    metrics: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or item.get("tbl_id") or "KOSIS 지표")
        org_id = str(item.get("org_id") or item.get("orgId") or "").strip()
        tbl_id = str(item.get("tbl_id") or item.get("tblId") or "").strip()
        item_id = item.get("item_id") or item.get("itmId")
        prd_se = str(item.get("prd_se") or item.get("prdSe") or "M").strip()
        if not org_id or not tbl_id or not item_id:
            continue

        history_key = f"kosis-{org_id}-{tbl_id}-{kosis_code_param(item_id).rstrip('+')}"
        # 최초 백필은 통계표 최대 기간(600기), 이후에는 최근 기간만 갱신합니다.
        if cached_history_last_date(config, history_key) is None:
            fetch_periods = int(item.get("backfill_points") or 600)
        else:
            fetch_periods = int(item.get("history_points") or history_limit)

        params: dict[str, Any] = {
            "method": "getList",
            "apiKey": api_key,
            "format": "json",
            "jsonVD": "Y",
            "prdSe": prd_se,
            "newEstPrdCnt": fetch_periods,
            "prdInterval": int(item.get("prd_interval") or 1),
            "orgId": org_id,
            "tblId": tbl_id,
            "itmId": kosis_code_param(item_id),
        }
        for index in range(1, 9):
            key = f"objL{index}"
            value = item.get(key)
            params[key] = kosis_code_param(value) if value is not None else ""

        try:
            response = session.get(
                endpoint,
                params=params,
                headers={"User-Agent": "Mozilla/5.0 stock-industry-dashboard/1.0"},
                timeout=(10, 60),
            )
            response.raise_for_status()
            payload = response.json()
            points = parse_kosis_points(payload, prd_se)
            if not points:
                cached = cached_kosis_metric(item, history_key, "KOSIS 관측값 없음")
                metrics.append(
                    cached
                    or
                    make_metric(
                        industry=str(item.get("industry") or "건설/부동산"),
                        name=name,
                        source="KOSIS OpenAPI",
                        source_url=source_url,
                        frequency=str(item.get("frequency") or "월간"),
                        automation="무료 공식 API 자동 수집",
                        status="error",
                        note="관측값 없음",
                        group=str(item.get("group") or "국내 주택"),
                        meaning=str(item.get("meaning") or ""),
                    )
                )
                continue

            latest_date, latest_value = points[-1]
            previous_value = points[-2][1] if len(points) > 1 else None
            yoy_value = find_yoy_value(points, latest_date)
            metrics.append(
                make_metric(
                    industry=str(item.get("industry") or "건설/부동산"),
                    name=name,
                    source="KOSIS OpenAPI",
                    source_url=source_url,
                    frequency=str(item.get("frequency") or "월간"),
                    automation="무료 공식 API 자동 수집",
                    status="ok",
                    value=latest_value,
                    unit=str(item.get("unit") or ""),
                    observed_at=latest_date.isoformat(),
                    previous_value=previous_value,
                    yoy_value=yoy_value,
                    history=points,
                    group=str(item.get("group") or "국내 주택"),
                    meaning=str(item.get("meaning") or ""),
                    history_key=history_key,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one KOSIS table should not break the page.
            cached = cached_kosis_metric(item, history_key, f"KOSIS 응답 실패: {exc}")
            metrics.append(
                cached
                or
                make_metric(
                    industry=str(item.get("industry") or "건설/부동산"),
                    name=name,
                    source="KOSIS OpenAPI",
                    source_url=source_url,
                    frequency=str(item.get("frequency") or "월간"),
                    automation="무료 공식 API 자동 수집",
                    status="error",
                    note=str(exc),
                    group=str(item.get("group") or "국내 주택"),
                    meaning=str(item.get("meaning") or ""),
                )
            )
    return metrics


def kosis_code_param(value: object) -> str:
    if isinstance(value, list):
        codes = [str(item).strip() for item in value if str(item).strip()]
    else:
        codes = [part.strip() for part in str(value).replace(",", "+").split("+") if part.strip()]
    return "+".join(codes) + ("+" if codes else "")


def parse_kosis_points(payload: object, prd_se: str) -> list[tuple[date, float]]:
    if isinstance(payload, dict):
        error_code = payload.get("err") or payload.get("errCd")
        if error_code:
            raise ValueError(str(payload.get("errMsg") or payload))
        rows = payload.get("data") or payload.get("result") or []
    else:
        rows = payload

    monthly_values: dict[date, float] = {}
    if not isinstance(rows, list):
        return []

    for row in rows:
        if not isinstance(row, dict):
            continue
        observed_at = parse_kosis_period(row.get("PRD_DE") or row.get("prdDe"), prd_se)
        value = to_float(row.get("DT") or row.get("dt"))
        if observed_at is None or value is None:
            continue
        monthly_values[observed_at] = monthly_values.get(observed_at, 0.0) + value
    return sorted(monthly_values.items())


def parse_kosis_period(value: object, prd_se: str = "M") -> date | None:
    text = re.sub(r"[^0-9]", "", str(value or ""))
    if not text:
        return None
    period = prd_se.upper()
    try:
        if period == "M" and len(text) >= 6:
            return date(int(text[:4]), int(text[4:6]), 1)
        if period == "Q" and len(text) >= 5:
            quarter = int(text[4])
            return date(int(text[:4]), (quarter - 1) * 3 + 1, 1)
        if len(text) >= 4:
            return date(int(text[:4]), 1, 1)
    except ValueError:
        return None
    return None


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


def months_needing_fetch(
    config: dict[str, Any],
    history_key: str,
    today: date,
    months_back: int,
    backfill_months: int,
    max_backfill_per_run: int,
) -> list[date]:
    """이벤트 카운트형 소스가 이번 실행에서 조회할 월 목록.

    최근 months_back개월은 항상 다시 세고(소급 반영), 그보다 오래된 구간은
    캐시에 없는 달만 실행당 max_backfill_per_run개씩 점진적으로 백필해
    무료 API 호출 한도를 넘지 않게 합니다.
    """
    recent = completed_months(today, months_back)
    store = attach_history_store(config)
    if store is None or not recent:
        return recent
    cached_dates = {point[0] for point in store.series(history_key)}
    older = [
        month
        for month in completed_months(today, max(backfill_months, months_back))
        if month < recent[0] and month not in cached_dates
    ]
    backfill = older[-max_backfill_per_run:] if max_backfill_per_run > 0 else []
    return sorted(set(backfill + recent))


def openfda_month_range(month: date) -> tuple[str, str]:
    start_date, end_date = month_date_range(month)
    return start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d")


def event_count_metric(
    *,
    points: list[tuple[date, float]],
    industry: str,
    name: str,
    source: str,
    source_url: str,
    frequency: str,
    group: str,
    meaning: str,
    history_key: str = "",
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
        history=points,
        group=group,
        meaning=meaning,
        history_key=history_key,
    )


def normalize_lookup_text(value: str) -> str:
    return " ".join(value.lower().replace("*", "").split())


def wsts_metric_name(region: str, is_3mma: bool) -> str:
    return f"3MMA - {region}" if is_3mma else region


def wsts_metric_meaning(region: str, is_3mma: bool) -> str:
    base = WSTS_REGION_MEANINGS.get(region) or (
        f"{region} 지역 반도체 판매액입니다. 지역별 수요가 반도체 업황에 어떻게 반영되는지 볼 때 참고합니다."
    )
    return f"{base} {WSTS_3MMA_MEANING}" if is_3mma else base


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
            is_3mma=False,
            xlsx_url=str(xlsx_url),
        )
    )
    if wsts_config.get("include_3mma", True) and "3MMA" in workbook.sheetnames:
        metrics.extend(
            wsts_sheet_metrics(
                workbook["3MMA"],
                regions,
                is_3mma=True,
                xlsx_url=str(xlsx_url),
            )
        )
    return metrics


def wsts_sheet_metrics(
    sheet: Any, regions: list[str], is_3mma: bool, xlsx_url: str
) -> list[dict[str, Any]]:
    parsed = parse_wsts_sheet(sheet)
    metrics: list[dict[str, Any]] = []
    for region in regions:
        points = sorted(parsed.get(region, []), key=lambda point: point[0])
        name = wsts_metric_name(region, is_3mma)
        meaning = wsts_metric_meaning(region, is_3mma)
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
                    group="판매액(WSTS)",
                    depth="전체 업황",
                    meaning=meaning,
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
                history=billion_points,
                group="판매액(WSTS)",
                depth="전체 업황",
                meaning=meaning,
                history_key=f"wsts-{'3mma-' if is_3mma else ''}{region}",
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
    months_back = int(export_config.get("months_back", 15))
    backfill_months = int(export_config.get("backfill_months", 120))

    metrics: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or item.get("hs_code"))
        hs_code = str(item.get("hs_code", "")).strip()
        industry = str(item.get("industry") or infer_export_industry(hs_code))
        metric_name = f"한국 수출 {name}({hs_code})"
        history_key = f"korea-export-{hs_code}"
        # 최초 1회는 backfill_months까지 12개월 창 단위로 백필하고, 이후엔 최근 구간만 갱신합니다.
        item_months_back = (
            backfill_months
            if cached_history_last_date(config, history_key) is None
            else months_back
        )
        start_month = add_months(end_month, -item_months_back + 1)

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
                    depth=str(item.get("depth") or ""),
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
                        depth=str(item.get("depth") or ""),
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
                    depth=str(item.get("depth") or ""),
                    meaning=str(item.get("meaning") or export_meaning(name)),
                    history_key=history_key,
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
                    depth=str(item.get("depth") or ""),
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


def collect_valuation_metrics(
    config: dict[str, Any], session: requests.Session, today: date
) -> list[dict[str, Any]]:
    """밸류에이션(멀티플)과 수급 과열 지표 수집기. 크롤 기반이라 전부 soft-fail합니다."""
    val_config = config.get("valuation", {})
    if not val_config.get("enabled", True):
        return []

    metrics: list[dict[str, Any]] = []

    for item in val_config.get("multpl", []):
        slug = str(item.get("slug") or "").strip()
        if not slug:
            continue
        name = str(item.get("name") or slug)
        source_url = f"https://www.multpl.com/{slug}"
        try:
            points = fetch_multpl_series(session, slug)
            latest_date, latest_value = points[-1]
            previous_value = points[-2][1] if len(points) > 1 else None
            metrics.append(
                make_metric(
                    industry=str(item.get("industry") or "매크로"),
                    name=name,
                    source="multpl.com",
                    source_url=source_url,
                    frequency="월간",
                    automation="공개 페이지 자동 수집",
                    status="ok",
                    value=latest_value,
                    unit=str(item.get("unit") or ""),
                    observed_at=latest_date.isoformat(),
                    previous_value=previous_value,
                    yoy_value=find_yoy_value(points, latest_date),
                    history=points,
                    group=str(item.get("group") or "밸류에이션"),
                    meaning=str(item.get("meaning") or ""),
                    history_key=f"multpl-{slug}",
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep cards independent.
            metrics.append(
                make_metric(
                    industry=str(item.get("industry") or "매크로"),
                    name=name,
                    source="multpl.com",
                    source_url=source_url,
                    frequency="월간",
                    automation="공개 페이지 자동 수집",
                    status="error",
                    note=str(exc),
                    group=str(item.get("group") or "밸류에이션"),
                    meaning=str(item.get("meaning") or ""),
                )
            )

    finra_config = val_config.get("finra_margin", {})
    if finra_config.get("enabled", True):
        finra_url = "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics"
        finra_name = str(finra_config.get("name") or "미국 신용융자 잔액(margin debt)")
        finra_meaning = str(
            finra_config.get("meaning")
            or "미국 증권사 고객의 신용융자 총액입니다. 급증하면 레버리지 과열, 급감하면 강제 청산 국면일 수 있습니다."
        )
        try:
            points = fetch_finra_margin_series(session)
            latest_date, latest_value = points[-1]
            previous_value = points[-2][1] if len(points) > 1 else None
            metrics.append(
                make_metric(
                    industry="매크로",
                    name=finra_name,
                    source="FINRA Margin Statistics",
                    source_url=finra_url,
                    frequency="월간",
                    automation="공개 페이지 자동 수집",
                    status="ok",
                    value=latest_value,
                    unit="$B",
                    observed_at=latest_date.isoformat(),
                    previous_value=previous_value,
                    yoy_value=find_yoy_value(points, latest_date),
                    history=points,
                    group="수급 과열",
                    meaning=finra_meaning,
                    history_key="finra-margin-debt",
                )
            )
        except Exception as exc:  # noqa: BLE001
            metrics.append(
                make_metric(
                    industry="매크로",
                    name=finra_name,
                    source="FINRA Margin Statistics",
                    source_url=finra_url,
                    frequency="월간",
                    automation="공개 페이지 자동 수집",
                    status="error",
                    note=str(exc),
                    group="수급 과열",
                    meaning=finra_meaning,
                )
            )

    krx_field_units = {"PER": "배", "PBR": "배", "배당수익률": "%"}
    for item in val_config.get("krx", []):
        prefix = str(item.get("name_prefix") or "코스피")
        ind_idx = str(item.get("ind_idx") or "1")
        ind_idx2 = str(item.get("ind_idx2") or "001")
        base_key = f"krx-val-{ind_idx}-{ind_idx2}"
        source_url = "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201060201"
        cached_last = cached_history_last_date(config, f"{base_key}-PER")
        if cached_last is None:
            start = parse_iso_date(item.get("backfill_start")) or date(2010, 1, 1)
        else:
            start = cached_last - timedelta(days=30)
        try:
            series_by_field = fetch_krx_valuation_series(session, ind_idx, ind_idx2, start, today)
            for field_name, points in series_by_field.items():
                if not points:
                    continue
                latest_date, latest_value = points[-1]
                previous_value = points[-2][1] if len(points) > 1 else None
                metrics.append(
                    make_metric(
                        industry="매크로",
                        name=f"{prefix} {field_name}",
                        source="KRX 정보데이터시스템",
                        source_url=source_url,
                        frequency="일간",
                        automation="공개 페이지 자동 수집",
                        status="ok",
                        value=latest_value,
                        unit=krx_field_units.get(field_name, ""),
                        observed_at=latest_date.isoformat(),
                        previous_value=previous_value,
                        yoy_value=find_yoy_value(points, latest_date),
                        history=points,
                        group="밸류에이션",
                        meaning=str(
                            item.get(f"meaning_{field_name}")
                            or krx_valuation_meaning(prefix, field_name)
                        ),
                        history_key=f"{base_key}-{field_name}",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - KRX는 비공식 엔드포인트라 차단될 수 있습니다.
            metrics.append(
                make_metric(
                    industry="매크로",
                    name=f"{prefix} PER/PBR/배당수익률",
                    source="KRX 정보데이터시스템",
                    source_url=source_url,
                    frequency="일간",
                    automation="공개 페이지 자동 수집",
                    status="error",
                    note=f"KRX 응답 실패(차단 가능): {exc}",
                    group="밸류에이션",
                )
            )

    return metrics


def krx_valuation_meaning(prefix: str, field_name: str) -> str:
    if field_name == "PER":
        return f"{prefix} 전체의 주가수익비율입니다. 과거 분포 대비 낮으면 저평가, 높으면 고평가 구간으로 봅니다."
    if field_name == "PBR":
        return (
            f"{prefix} 전체의 주가순자산비율입니다. 역사적으로 코스피 PBR 0.9 이하는 장기 저평가, "
            "1.3 이상은 고평가 구간으로 통했습니다."
        )
    return f"{prefix} 전체의 배당수익률입니다. 높을수록 배당 대비 주가가 싼 상태라는 뜻입니다."


def collect_market_flow_metrics(
    config: dict[str, Any],
    session: requests.Session,
    today: date,
) -> list[dict[str, Any]]:
    overview_config = config.get("market_overview", {}) or {}
    flows_config = overview_config.get("flows", {}) if isinstance(overview_config, dict) else {}
    if not flows_config.get("enabled", True):
        return []

    history_config = config.get("history", {}) or {}
    history_dir = str(history_config.get("dir") or "data/history")
    keep_days = int(flows_config.get("keep_calendar_days") or 760)
    lookback_days = int(flows_config.get("lookback_calendar_days") or 760)
    max_fetch = int(flows_config.get("max_backfill_days_per_run") or 3)
    endpoint = str(flows_config.get("krx_getjson_endpoint") or "")
    source_url = "https://data.krx.co.kr/"

    metric_docs: list[tuple[str, str, dict[str, Any]]] = []
    errors: list[str] = []

    for market, label in (("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")):
        path = raw_flow_snapshot_path(history_dir, market)
        document = load_raw_flow_snapshot(path, market)
        missing = missing_recent_dates(
            today=today,
            known_dates=raw_flow_known_dates(document),
            calendar_days=lookback_days,
            max_fetch=max_fetch,
        )
        for target_date in missing:
            try:
                rows = fetch_krx_stock_flow_rows(
                    session,
                    market=market,
                    start_date=target_date,
                    end_date=target_date,
                    endpoint=endpoint or "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                )
                document = store_raw_flow_rows(
                    history_dir=history_dir,
                    market=market,
                    observed_at=target_date,
                    rows=rows,
                    today=today,
                    keep_calendar_days=keep_days,
                )
            except Exception as exc:  # noqa: BLE001 - KRX 정보데이터시스템은 soft-fail.
                try:
                    fallback_date, rows = fetch_krx_main_investor_flow_rows(
                        session,
                        market=market,
                        endpoint=endpoint or "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                    )
                    if not rows or fallback_date is None:
                        raise RuntimeError("KRX 메인 투자자별 매매동향 응답 없음")
                    document = store_raw_flow_rows(
                        history_dir=history_dir,
                        market=market,
                        observed_at=fallback_date,
                        rows=rows,
                        today=today,
                        keep_calendar_days=keep_days,
                    )
                    break
                except Exception as fallback_exc:  # noqa: BLE001
                    errors.append(f"{label} {target_date.isoformat()}: {exc}; fallback: {fallback_exc}")
                    break
        document = load_raw_flow_snapshot(path, market)
        metric_docs.append((market, label, document))

    futures_market = "k200-futures"
    futures_path = raw_flow_snapshot_path(history_dir, futures_market)
    futures_doc = load_raw_flow_snapshot(futures_path, futures_market)
    missing = missing_recent_dates(
        today=today,
        known_dates=raw_flow_known_dates(futures_doc),
        calendar_days=lookback_days,
        max_fetch=max_fetch,
    )
    for target_date in missing:
        try:
            rows = fetch_krx_futures_flow_rows(
                session,
                start_date=target_date,
                end_date=target_date,
                endpoint=endpoint or "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
            )
            futures_doc = store_raw_flow_rows(
                history_dir=history_dir,
                market=futures_market,
                observed_at=target_date,
                rows=rows,
                today=today,
                keep_calendar_days=keep_days,
            )
        except Exception as exc:  # noqa: BLE001
            try:
                fallback_date, rows = fetch_krx_main_investor_flow_rows(
                    session,
                    market=futures_market,
                    endpoint=endpoint or "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                )
                if not rows or fallback_date is None:
                    raise RuntimeError("KRX 메인 투자자별 매매동향 응답 없음")
                futures_doc = store_raw_flow_rows(
                    history_dir=history_dir,
                    market=futures_market,
                    observed_at=fallback_date,
                    rows=rows,
                    today=today,
                    keep_calendar_days=keep_days,
                )
                break
            except Exception as fallback_exc:  # noqa: BLE001
                errors.append(f"K200 선물 {target_date.isoformat()}: {exc}; fallback: {fallback_exc}")
                break
    futures_doc = load_raw_flow_snapshot(futures_path, futures_market)
    metric_docs.append((futures_market, "K200 선물", futures_doc))

    metrics: list[dict[str, Any]] = []
    for market, market_label, document in metric_docs:
        metrics.extend(flow_metrics_from_raw_document(market, market_label, document, source_url))

    if not metrics and errors:
        metrics.append(
            make_metric(
                industry="매크로",
                name="KRX 수급 수집 상태",
                source="KRX 정보데이터시스템",
                source_url=source_url,
                frequency="일간",
                automation="공개 JSON 자동 수집",
                status="error",
                note="; ".join(errors[:3]),
                group="수급",
                section="market",
                market_category="수급",
                meaning="KRX 투자자별 매매동향 수집 상태입니다.",
            )
        )
    return metrics


def flow_metrics_from_raw_document(
    market: str,
    market_label: str,
    document: dict[str, Any],
    source_url: str,
) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    investors = raw_flow_investors(document)
    if not investors:
        return []

    for investor in investors:
        investor_id = investor_slug(investor)
        for measure, spec in FLOW_MEASURES.items():
            points = raw_flow_series(document, investor=investor, measure=measure)
            if not points:
                continue
            latest_date, latest_value = points[-1]
            previous_value = points[-2][1] if len(points) > 1 else None
            metric_id = f"krx-flow-{market}-{investor_id}-{measure}"
            measure_label = str(spec.get("label") or measure)
            chart_style = "flow_bars" if measure == "net" else ""
            metrics.append(
                make_metric(
                    industry="매크로",
                    name=f"{market_label} {investor} {measure_label}",
                    source="KRX 정보데이터시스템",
                    source_url=source_url,
                    frequency="일간",
                    automation="공개 JSON 자동 수집",
                    status="ok",
                    value=latest_value,
                    unit="억원",
                    observed_at=latest_date.isoformat(),
                    previous_value=previous_value,
                    yoy_value=find_yoy_value(points, latest_date),
                    history=points,
                    group=investor,
                    depth=market_label,
                    meaning=flow_metric_meaning(market_label, investor, measure_label),
                    history_key=metric_id,
                    metric_id=metric_id,
                    section="market",
                    market_category="수급",
                    chart_style=chart_style,
                    exclude_from_movers=measure != "net",
                )
            )

        net_points = raw_flow_series(document, investor=investor, measure="net")
        rolling = rolling_sum_series(net_points, 20)
        if rolling:
            latest_date, latest_value = rolling[-1]
            previous_value = rolling[-2][1] if len(rolling) > 1 else None
            metric_id = f"krx-flow-{market}-{investor_id}-net-20d"
            metrics.append(
                make_metric(
                    industry="매크로",
                    name=f"{market_label} {investor} 20일 누적 순매수",
                    source="KRX 정보데이터시스템",
                    source_url=source_url,
                    frequency="일간",
                    automation="공개 JSON 자동 수집",
                    status="ok",
                    value=latest_value,
                    unit="억원",
                    observed_at=latest_date.isoformat(),
                    previous_value=previous_value,
                    yoy_value=find_yoy_value(rolling, latest_date),
                    history=rolling,
                    group=investor,
                    depth=market_label,
                    meaning=f"{market_label}에서 {investor}이 최근 20거래일 동안 순매수한 금액의 합계입니다. 한 주체가 시장을 계속 받치는지 확인할 때 봅니다.",
                    history_key=metric_id,
                    metric_id=metric_id,
                    section="market",
                    market_category="수급",
                    chart_style="flow_bars",
                )
            )
    return metrics


def flow_metric_meaning(market_label: str, investor: str, measure_label: str) -> str:
    investor_meanings = {
        "개인": "개인투자자의 위험 선호와 반대매매·저가매수 흐름을 볼 때 중요합니다",
        "외국인": "환율, 글로벌 자금 흐름, 한국 시장 선호가 실제 매매로 들어오는지 볼 때 중요합니다",
        "기관": "국내 기관 자금이 시장을 받치는지, 리밸런싱 압력이 있는지 확인할 때 봅니다",
        "기관합계": "국내 기관 전체의 매매 방향을 한눈에 보기 위한 합산 지표입니다",
        "기관종합": "국내 기관 전체의 매매 방향을 한눈에 보기 위한 합산 지표입니다",
        "금융투자": "증권사·금융투자 쪽의 단기 포지션과 프로그램성 매매 압력을 볼 때 중요합니다",
        "보험": "보험사 자금의 주식 비중 조절 흐름을 확인할 때 봅니다",
        "투신": "펀드 자금 유입·유출이 실제 주식 매매로 이어지는지 확인할 때 봅니다",
        "기타금융": "기타 금융기관 자금의 보조적인 매매 방향을 확인할 때 봅니다",
        "은행": "은행권 자금의 위험자산 선호 변화를 보조적으로 확인할 때 봅니다",
        "연기금": "국민연금 등 장기 자금이 시장을 받치는지, 비중 조절에 나서는지 볼 때 중요합니다",
        "사모": "사모펀드와 전문투자자 쪽의 비교적 민감한 자금 흐름을 확인할 때 봅니다",
        "기타법인": "자사주, 지주회사, 일반 법인 자금이 시장에 들어오는지 볼 때 참고합니다",
    }
    investor_note = investor_meanings.get(investor, f"{investor} 자금의 매매 방향과 시장 영향력을 확인할 때 봅니다")
    if measure_label == "순매수":
        return (
            f"{market_label}에서 {investor}이 산 금액에서 판 금액을 뺀 값입니다. "
            f"플러스면 그 주체가 시장을 순매수한 것이고, 마이너스면 순매도한 것입니다. {investor_note}."
        )
    if measure_label == "매수":
        return (
            f"{market_label}에서 {investor}이 사들인 거래대금입니다. "
            f"순매수와 함께 보면 실제 매수 강도가 커진 것인지, 매도도 같이 늘어난 단순 거래 증가인지 구분할 수 있습니다. {investor_note}."
        )
    if measure_label == "매도":
        return (
            f"{market_label}에서 {investor}이 판 거래대금입니다. "
            f"매도가 빠르게 늘면 해당 주체의 차익실현이나 위험 축소 압력이 커졌는지 확인할 수 있습니다. {investor_note}."
        )
    return (
        f"{market_label}에서 {investor}의 {measure_label} 거래대금입니다. "
        f"누가 시장을 밀고 당기는지 확인하는 수급 지표입니다. {investor_note}."
    )


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


def metric_by_name(metrics: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for metric in metrics:
        if isinstance(metric, dict) and str(metric.get("name") or "") == name and metric.get("status") == "ok":
            return metric
    return None


def collect_market_derived_metrics(
    config: dict[str, Any],
    session: requests.Session,
    today: date,
    current_metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    del config
    metrics: list[dict[str, Any]] = []
    metrics.extend(collect_kimchi_premium_metric(session, today, current_metrics))
    yen_vol = yen_realized_volatility_metric(today, current_metrics)
    if yen_vol:
        metrics.append(yen_vol)
    return metrics


def collect_kimchi_premium_metric(
    session: requests.Session,
    today: date,
    current_metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    btc_metric = metric_by_name(current_metrics, "비트코인")
    usdkrw_metric = metric_by_name(current_metrics, "원/달러 환율")
    btc_usd = to_float((btc_metric or {}).get("value"))
    usdkrw = to_float((usdkrw_metric or {}).get("value"))
    if btc_usd is None or usdkrw is None or btc_usd <= 0 or usdkrw <= 0:
        return []
    try:
        response = session.get(
            "https://api.upbit.com/v1/ticker",
            params={"markets": "KRW-BTC"},
            timeout=(5, 20),
        )
        response.raise_for_status()
        payload = response.json()
        item = payload[0] if isinstance(payload, list) and payload else {}
        krw_btc = to_float(item.get("trade_price")) if isinstance(item, dict) else None
        if krw_btc is None or krw_btc <= 0:
            raise ValueError("업비트 BTC 가격 없음")
        premium = (krw_btc / (btc_usd * usdkrw) - 1.0) * 100.0
        observed_at = today.isoformat()
        return [
            make_metric(
                industry="매크로",
                name="김치프리미엄",
                source="Upbit/Yahoo Finance",
                source_url="https://api.upbit.com/v1/ticker",
                frequency="장중",
                automation="무료 공개 API 자동 수집",
                status="ok",
                value=premium,
                unit="%",
                observed_at=observed_at,
                previous_value=None,
                history=[(today, premium)],
                group="크립토",
                meaning="국내 비트코인 가격이 글로벌 달러 가격을 원화로 환산한 값보다 얼마나 높은지 보여줍니다. 높아질수록 국내 개인 위험선호가 강하다는 신호로 볼 수 있습니다.",
                history_key="kimchi-premium-btc",
                section="market",
                market_category="원자재·크립토",
                also_market_category=["심리·변동성"],
                refresh_scope="intraday",
            )
        ]
    except Exception as exc:  # noqa: BLE001
        return [
            make_metric(
                industry="매크로",
                name="김치프리미엄",
                source="Upbit/Yahoo Finance",
                source_url="https://api.upbit.com/v1/ticker",
                frequency="장중",
                automation="무료 공개 API 자동 수집",
                status="error",
                note=str(exc),
                group="크립토",
                meaning="국내 비트코인 가격이 글로벌 가격보다 얼마나 높은지 보여주는 지표입니다.",
                section="market",
                market_category="원자재·크립토",
            )
        ]


def yen_realized_volatility_metric(today: date, current_metrics: list[dict[str, Any]]) -> dict[str, Any] | None:
    yen = metric_by_name(current_metrics, "엔/달러 환율")
    points = parse_stored_points((yen or {}).get("history"))
    if len(points) < 11:
        return None
    returns: list[tuple[date, float]] = []
    for (prev_date, previous), (current_date, current) in zip(points[:-1], points[1:]):
        del prev_date
        if previous <= 0 or current <= 0:
            continue
        returns.append((current_date, (current / previous - 1.0) * 100.0))
    vol_points: list[tuple[date, float]] = []
    for index in range(9, len(returns)):
        window = [value for _, value in returns[index - 9 : index + 1]]
        mean = sum(window) / len(window)
        variance = sum((value - mean) ** 2 for value in window) / len(window)
        vol_points.append((returns[index][0], variance ** 0.5))
    if not vol_points:
        return None
    latest_date, latest_value = vol_points[-1]
    previous_value = vol_points[-2][1] if len(vol_points) > 1 else None
    return make_metric(
        industry="매크로",
        name="엔 환율 10일 실현변동성",
        source="Yahoo Finance chart API",
        source_url="https://finance.yahoo.com/quote/JPY=X",
        frequency="일간",
        automation="계산 지표",
        status="ok",
        value=latest_value,
        unit="%",
        observed_at=latest_date.isoformat() or today.isoformat(),
        previous_value=previous_value,
        history=vol_points,
        group="엔캐리",
        meaning="엔/달러 환율의 최근 10거래일 변동폭입니다. 변동성이 빠르게 커지면 엔캐리 포지션이 흔들릴 가능성을 점검합니다.",
        history_key="yen-realized-volatility-10d",
        section="market",
        market_category="심리·변동성",
    )


def collect_market_sentiment_metrics(
    config: dict[str, Any],
    session: requests.Session,
    today: date,
    current_metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sentiment_config = config.get("market_sentiment", {})
    if not sentiment_config.get("enabled", True):
        return []

    metrics: list[dict[str, Any]] = []
    store = attach_history_store(config)
    metrics.extend(collect_cnn_fear_greed_metric(config, session, today))
    try:
        metrics.extend(collect_korea_fear_greed_metrics(config, session, today, current_metrics, store))
    except Exception as exc:  # noqa: BLE001 - keep CNN sentiment visible if KRX has a temporary issue.
        for name, meaning in [
            ("코스피 공포탐욕지수", korea_fear_greed_meaning("코스피")),
            ("코스닥 공포탐욕지수", korea_fear_greed_meaning("코스닥")),
            ("VKOSPI", vkospi_meaning()),
        ]:
            metrics.append(
                make_metric(
                    industry="매크로",
                    name=name,
                    source="KRX Open API",
                    source_url=KRX_SOURCE_URL,
                    frequency="일간",
                    automation="무료 공식 API 자동 수집",
                    status="error",
                    note=str(exc),
                    group="공포탐욕",
                    meaning=meaning,
                )
            )
    return metrics


def collect_cnn_fear_greed_metric(
    config: dict[str, Any],
    session: requests.Session,
    today: date,
) -> list[dict[str, Any]]:
    sentiment_config = config.get("market_sentiment", {})
    cnn_config = sentiment_config.get("cnn", {})
    if not cnn_config.get("enabled", True):
        return []

    history_key = "cnn-fear-greed"
    cached_last = cached_history_last_date(config, history_key)
    if cached_last is None:
        start = parse_iso_date(cnn_config.get("backfill_start")) or date(2021, 2, 1)
    else:
        start = max(date(2021, 2, 1), cached_last - timedelta(days=45))
    source_url = str(cnn_config.get("source_url") or "https://www.cnn.com/markets/fear-and-greed")
    try:
        points, _payload = fetch_cnn_fear_greed(session, start_date=start)
        if not points:
            raise ValueError("CNN 공포탐욕 관측값 없음")
        latest_date, latest_value = points[-1]
        previous_value = points[-2][1] if len(points) > 1 else None
        return [
            make_metric(
                industry="매크로",
                name="미국 CNN 공포탐욕지수",
                source="CNN Fear & Greed Index",
                source_url=source_url,
                frequency="일간",
                automation="공개 JSON 자동 수집",
                status="ok",
                value=latest_value,
                unit="점",
                observed_at=latest_date.isoformat(),
                previous_value=previous_value,
                yoy_value=find_yoy_value(points, latest_date),
                history=points,
                group="공포탐욕",
                meaning=(
                    "CNN이 미국 주식시장의 여러 심리 지표를 합산해 발표하는 공포탐욕지수입니다. "
                    "0에 가까우면 공포, 100에 가까우면 탐욕이 강한 구간입니다."
                ),
                history_key=history_key,
            )
        ]
    except Exception as exc:  # noqa: BLE001
        return [
            make_metric(
                industry="매크로",
                name="미국 CNN 공포탐욕지수",
                source="CNN Fear & Greed Index",
                source_url=source_url,
                frequency="일간",
                automation="공개 JSON 자동 수집",
                status="error",
                note=str(exc),
                group="공포탐욕",
                meaning=(
                    "CNN이 미국 주식시장의 여러 심리 지표를 합산해 발표하는 공포탐욕지수입니다. "
                    "0에 가까우면 공포, 100에 가까우면 탐욕이 강한 구간입니다."
                ),
            )
        ]


def collect_korea_fear_greed_metrics(
    config: dict[str, Any],
    session: requests.Session,
    today: date,
    current_metrics: list[dict[str, Any]],
    store: HistoryStore | None,
) -> list[dict[str, Any]]:
    sentiment_config = config.get("market_sentiment", {})
    korea_config = sentiment_config.get("korea", {})
    if not korea_config.get("enabled", True):
        return []

    source_url = str(korea_config.get("source_url") or KRX_SOURCE_URL)
    auth_key = os.getenv("KRX_OPEN_API_KEY", "").strip() or os.getenv("KRX_API_KEY", "").strip()
    if not auth_key:
        return [
            make_metric(
                industry="매크로",
                name=name,
                source="KRX Open API",
                source_url=source_url,
                frequency="일간",
                automation="무료 공식 API 자동 수집",
                status="needs_key",
                note="GitHub Secrets에 KRX_OPEN_API_KEY 등록 필요",
                group="공포탐욕",
                meaning=meaning,
            )
            for name, meaning in [
                ("코스피 공포탐욕지수", korea_fear_greed_meaning("코스피")),
                ("코스닥 공포탐욕지수", korea_fear_greed_meaning("코스닥")),
                ("VKOSPI", vkospi_meaning()),
            ]
        ]

    history_config = config.get("history", {}) or {}
    history_dir = str(history_config.get("dir") or "data/history")
    base_url = str(korea_config.get("krx_api_base") or KRX_API_BASE)
    lookback_days = int(korea_config.get("lookback_calendar_days") or 430)
    keep_days = int(korea_config.get("keep_calendar_days") or 430)
    max_fetch = int(korea_config.get("max_backfill_days_per_run") or 8)
    high_low_window_days = int(korea_config.get("high_low_window_days") or 370)
    min_high_low_points = int(korea_config.get("min_high_low_points") or 120)

    metrics: list[dict[str, Any]] = []
    snapshots: dict[str, dict[str, Any]] = {}
    for market in ("KOSPI", "KOSDAQ"):
        snapshots[market] = collect_market_snapshot(
            session,
            auth_key=auth_key,
            base_url=base_url,
            history_dir=history_dir,
            market=market,
            today=today,
            lookback_calendar_days=lookback_days,
            max_fetch_days=max_fetch,
            keep_calendar_days=keep_days,
        )

    vkospi_key = "krx-vkospi"
    vkospi_incoming = fetch_vkospi_points(
        session,
        auth_key=auth_key,
        base_url=base_url,
        store=store,
        today=today,
        history_key=vkospi_key,
        lookback_calendar_days=lookback_days,
        max_fetch_days=max_fetch,
    )
    vkospi_points = merge_existing_and_incoming(store, vkospi_key, vkospi_incoming)
    if vkospi_points:
        latest_date, latest_value = vkospi_points[-1]
        previous_value = vkospi_points[-2][1] if len(vkospi_points) > 1 else None
        metrics.append(
            make_metric(
                industry="매크로",
                name="VKOSPI",
                source="KRX Open API",
                source_url=source_url,
                frequency="일간",
                automation="무료 공식 API 자동 수집",
                status="ok",
                value=latest_value,
                unit="",
                observed_at=latest_date.isoformat(),
                previous_value=previous_value,
                yoy_value=find_yoy_value(vkospi_points, latest_date),
                history=vkospi_points,
                group="공포탐욕",
                meaning=vkospi_meaning(),
                history_key=vkospi_key,
            )
        )

    metrics_by_history_key = {
        str(metric.get("history_key") or ""): metric
        for metric in current_metrics
        if isinstance(metric, dict) and metric.get("history_key")
    }
    index_points = {
        "KOSPI": metric_full_points(store, metrics_by_history_key.get("equity-^KS11"), "equity-^KS11"),
        "KOSDAQ": metric_full_points(store, metrics_by_history_key.get("equity-^KQ11"), "equity-^KQ11"),
    }

    for market, label in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        score_data = build_korea_fear_greed_score(
            market_label=label,
            index_points=index_points[market],
            snapshot_document=snapshots[market],
            vkospi_points=vkospi_points if market == "KOSPI" else None,
            high_low_window_days=high_low_window_days,
            min_high_low_points=min_high_low_points,
        )
        if score_data is None:
            metrics.append(
                make_metric(
                    industry="매크로",
                    name=f"{label} 공포탐욕지수",
                    source="KRX Open API/Yahoo Finance",
                    source_url=source_url,
                    frequency="일간",
                    automation="무료 공식 API 자동 수집",
                    status="error",
                    note="계산에 필요한 시장 심리 구성요소가 아직 부족합니다",
                    group="공포탐욕",
                    meaning=korea_fear_greed_meaning(label),
                )
            )
            continue

        score_key = f"korea-fear-greed-{market.lower()}"
        score_points = merge_existing_and_incoming(
            store,
            score_key,
            [(score_data["observed_at"], score_data["score"])],
        )
        latest_date, latest_value = score_points[-1]
        previous_value = score_points[-2][1] if len(score_points) > 1 else None
        metrics.append(
            make_metric(
                industry="매크로",
                name=f"{label} 공포탐욕지수",
                source="KRX Open API/Yahoo Finance",
                source_url=source_url,
                frequency="일간",
                automation="무료 공식 API 자동 수집",
                status="ok",
                value=latest_value,
                unit="점",
                observed_at=latest_date.isoformat(),
                previous_value=previous_value,
                yoy_value=find_yoy_value(score_points, latest_date),
                history=score_points,
                group="공포탐욕",
                meaning=korea_fear_greed_meaning(label),
                history_key=score_key,
                history_merge="latest",
            )
        )

    return metrics


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


HANGUL_RE = re.compile(r"[가-힣]")
EN_MARKET_FALLBACKS = {
    "코스피": "KOSPI",
    "코스닥": "KOSDAQ",
    "K200 선물": "K200 Futures",
    "선물": "Futures",
    "한국": "Korea",
    "미국": "US",
    "중국": "China",
    "일본": "Japan",
    "유럽": "Europe",
    "동남아": "Southeast Asia",
    "글로벌": "Global",
    "전세계": "Global",
}
EN_INVESTOR_FALLBACKS = {
    "개인": "Retail Investors",
    "외국인": "Foreign Investors",
    "기관합계": "Institutions Total",
    "기관": "Institutions",
    "금융투자": "Financial Investment",
    "보험": "Insurance",
    "투신": "Investment Trusts",
    "사모": "Private Funds",
    "은행": "Banks",
    "기타금융": "Other Financials",
    "연기금": "Pension Funds",
    "기타법인": "Other Corporations",
}
EN_FLOW_MEASURE_FALLBACKS = {
    "20일 누적 순매수": "20d Net Buying",
    "순매수": "Net Buying",
    "매수": "Buying",
    "매도": "Selling",
}
EN_PHRASE_FALLBACKS = {
    "한국장 마감": "Korea market close",
    "미국장 마감": "US market close",
    "공포탐욕지수": "Fear & Greed Index",
    "경기침체": "Recession",
    "시장온도계": "Market Thermometer",
    "시장 온도계": "Market Thermometer",
    "종합": "Overview",
    "수급": "Flows",
    "신용·예탁금": "Credit/Cash",
    "금리·채권": "Rates/Bonds",
    "원자재·크립토": "Commodities/Crypto",
    "심리·변동성": "Sentiment/Volatility",
    "밸류에이션": "Valuation",
    "캘린더": "Calendar",
    "대표주가": "Representative Stocks",
    "대표 주가": "Representative Stocks",
    "시장지수": "Market Indexes",
    "월매출": "Monthly Revenue",
    "판매액": "Sales",
    "판매량": "Sales Volume",
    "매출": "Revenue",
    "수출": "Exports",
    "가격": "Price",
    "기준금리": "Policy Rate",
    "국채금리": "Treasury Yield",
    "금리차": "Yield Spread",
    "회사채": "Corporate Bond",
    "하이일드": "High Yield",
    "스프레드": "Spread",
    "환율": "Exchange Rate",
    "유가": "Crude Oil Price",
    "철광석": "Iron Ore",
    "구리": "Copper",
    "알루미늄": "Aluminum",
    "리튬": "Lithium",
    "배터리": "Battery",
    "전력수요": "Power Demand",
    "전력 수요": "Power Demand",
    "주택착공": "Housing Starts",
    "건축허가": "Building Permits",
    "미분양 주택": "Unsold Homes",
    "주택가격지수": "House Price Index",
    "발표": "Release",
    "결정": "Decision",
    "휴장": "Holiday",
    "만기": "Expiry",
    "갱신 예정": "Scheduled update",
    "갱신": "Update",
    "예정": "Scheduled",
    "최근": "Recent",
    "누적": "Cumulative",
    "증가율": "Growth Rate",
    "변화율": "Change Rate",
    "변화": "Change",
    "지표": "Metric",
    "흐름": "Trend",
    "위험": "Risk",
    "주의": "Watch",
    "안정": "Stable",
    "낮음": "Low",
    "보통": "Moderate",
    "높음": "High",
}


def contains_hangul(value: object) -> bool:
    return bool(HANGUL_RE.search(str(value or "")))


def english_sentence_fallback(text: str) -> str:
    if re.search(r"순매수|매수|매도|수급|외국인|개인|기관", text):
        return "Tracks investor trading flows and helps show which group is buying or selling the market."
    if re.search(r"공포|탐욕|심리|변동성", text):
        return "Shows market sentiment and risk appetite."
    if re.search(r"침체|경기|실업|성장", text):
        return "Helps read the economic cycle and recession risk."
    if re.search(r"금리|스프레드|채권|회사채", text):
        return "Tracks rates, credit conditions, and funding stress."
    if re.search(r"환율|원/달러", text):
        return "Tracks currency moves that affect exporters, foreign flows, and market liquidity."
    if re.search(r"가격|원자재|유가|철광석|구리|알루미늄|리튬", text):
        return "Tracks price movements that affect costs, margins, and demand expectations."
    if re.search(r"판매|매출|수출|CAPEX|투자", text):
        return "Tracks demand and investment momentum for the related industry."
    if re.search(r"캘린더|일정|발표|결정|휴장|만기", text):
        return "Scheduled market event."
    return "Market indicator used to track investment conditions."


def english_generic_text(value: object, fallback: str = "Market indicator") -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not contains_hangul(text):
        return text
    exact = (
        EN_MEANING_LABELS.get(text)
        or EN_METRIC_NAME_LABELS.get(text)
        or EN_INDUSTRY_LABELS.get(text)
        or EN_GROUP_LABELS.get(text)
        or EN_DEPTH_LABELS.get(text)
        or EN_FREQUENCY_LABELS.get(text)
    )
    if exact:
        return exact

    flow_match = re.match(
        r"^(코스피|코스닥|K200 선물|선물)?\s*"
        r"(개인|외국인|기관합계|기관|금융투자|보험|투신|사모|은행|기타금융|연기금|기타법인)\s+"
        r"(20일 누적 순매수|순매수|매수|매도)$",
        text,
    )
    if flow_match:
        market, investor, measure = flow_match.groups()
        prefix = f"{EN_MARKET_FALLBACKS.get(market, market)} " if market else ""
        return f"{prefix}{EN_INVESTOR_FALLBACKS.get(investor, investor)} {EN_FLOW_MEASURE_FALLBACKS.get(measure, measure)}".strip()

    export_match = re.match(r"^한국 수출 (.+)\(([^)]+)\)$", text)
    if export_match:
        item = english_export_item(export_match.group(1))
        if contains_hangul(item):
            item = english_generic_text(item, "Export Item")
        return f"Korea Exports: {item} ({export_match.group(2)})"

    stock_match = re.match(r"^(.+) 주가$", text)
    if stock_match:
        company = EN_METRIC_NAME_LABELS.get(stock_match.group(1)) or english_generic_text(stock_match.group(1), "Company")
        return f"{company} Stock Price"

    release_match = re.match(r"^미국 (.+) 발표$", text)
    if release_match:
        return f"US {english_generic_text(release_match.group(1), 'Data')} release"

    translated = text
    replacements: dict[str, str] = {}
    replacements.update(EN_INVESTOR_FALLBACKS)
    replacements.update(EN_FLOW_MEASURE_FALLBACKS)
    replacements.update(EN_PHRASE_FALLBACKS)
    replacements.update(EN_MARKET_FALLBACKS)
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        translated = translated.replace(source, target)
    translated = re.sub(r"(\d+)일", r"\1d", translated)
    translated = re.sub(r"(\d+)년", r"\1y", translated)
    translated = re.sub(r"(\d+)개월", r"\1mo", translated)
    translated = translated.replace("에서", " in ").replace("동안", " for ")
    translated = re.sub(r"입니다|합니다|하세요|됩니다", "", translated)
    translated = HANGUL_RE.sub("", translated)
    translated = translated.replace("·", "/")
    translated = re.sub(r"\s*/\s*", "/", translated)
    translated = re.sub(r"\s+", " ", translated).strip()
    if translated and not contains_hangul(translated):
        return translated
    return fallback or english_sentence_fallback(text)


def english_industry(industry: str) -> str:
    value = EN_INDUSTRY_LABELS.get(industry, industry)
    return english_generic_text(value, "Industry") if contains_hangul(value) else value


def english_group(group: str) -> str:
    value = EN_GROUP_LABELS.get(group, group)
    return english_generic_text(value, "Group") if contains_hangul(value) else value


def english_depth(depth: str) -> str:
    value = EN_DEPTH_LABELS.get(depth, depth)
    return english_generic_text(value, "Section") if contains_hangul(value) else value


def english_frequency(frequency: str) -> str:
    if not frequency:
        return ""
    compact = frequency.replace(" ", "")
    if compact in EN_FREQUENCY_LABELS:
        return EN_FREQUENCY_LABELS[compact]
    parts = [EN_FREQUENCY_LABELS.get(part, part) for part in compact.split("/") if part]
    return "/".join(parts) if parts else frequency


def english_unit(unit: str) -> str:
    value = EN_UNIT_LABELS.get(unit, unit)
    return english_generic_text(value, "Unit") if contains_hangul(value) else value


def english_export_item(name: str) -> str:
    value = EN_EXPORT_ITEM_LABELS.get(name, name)
    return english_generic_text(value, "Export Item") if contains_hangul(value) else value


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

    stock_match = re.match(r"^(.+) 주가$", name)
    if stock_match:
        company = english_metric_name(stock_match.group(1))
        return f"{company} Stock Price"

    return english_generic_text(name, "Metric") if contains_hangul(name) else name


def english_metric_meaning(meaning: str, industry: str = "") -> str:
    if meaning in EN_MEANING_LABELS:
        return EN_MEANING_LABELS[meaning]

    for region, korean_meaning in WSTS_REGION_MEANINGS.items():
        english_meaning = WSTS_REGION_MEANINGS_EN[region]
        if meaning == korean_meaning:
            return english_meaning
        if meaning == f"{korean_meaning} {WSTS_3MMA_MEANING}":
            return f"{english_meaning} {WSTS_3MMA_MEANING_EN}"

    for company, korean_meaning in CAPEX_MEANINGS.items():
        if meaning == korean_meaning:
            return CAPEX_MEANINGS_EN[company]

    export_match = re.match(
        r"^(.+) 수출은 해당 품목의 대외 수요와 가격/물량 사이클을 확인하는 지표입니다\\.$",
        meaning,
    )
    if export_match:
        item = english_export_item(export_match.group(1))
        return f"{item} exports track external demand and price/volume cycles for the item."

    stock_match = re.match(r"^(.+) 주가는 시장이 해당 기업의 성장성과 위험을 어떻게 평가하는지 보여줍니다\\.$", meaning)
    if stock_match:
        return f"{stock_match.group(1)} stock price shows how the market values the company's growth and risk."

    capex_match = re.match(
        r"^(.+)의 CAPEX는 데이터센터, 서버, AI 인프라 같은 장기 설비투자 규모를 보여줍니다\. "
        r"투자가 커질수록 클라우드와 AI 인프라 수요가 강하다는 신호로 볼 수 있습니다\.$",
        meaning,
    )
    if capex_match:
        return (
            f"{capex_match.group(1)} CAPEX shows long-term investment in data centers, "
            "servers, and AI infrastructure. Rising investment can signal stronger cloud "
            "and AI infrastructure demand."
        )

    industry_match = re.match(r"^(.+) 흐름을 이해할 때 참고하는 보조 지표입니다\\.$", meaning)
    if industry_match:
        target_industry = english_industry(industry_match.group(1) or industry)
        return f"Supplementary indicator for understanding {target_industry} industry trends."

    return english_sentence_fallback(meaning) if contains_hangul(meaning) else meaning


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


def load_dashboard_template() -> str:
    template_path = Path(__file__).resolve().parent / "templates" / "dashboard.html"
    return template_path.read_text(encoding="utf-8")


def render_dashboard_html(payload: dict[str, Any]) -> str:
    json_text = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return load_dashboard_template().replace("__DASHBOARD_JSON__", json_text)


def copy_signal_log_output(config: dict[str, Any], data_path: Path) -> None:
    signal_path = Path(str((config.get("alerts", {}) or {}).get("signal_log_file") or "data/signal_log.json"))
    if not signal_path.exists():
        return
    data_path.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(signal_path, data_path / "signal_log.json")


def load_admin_template() -> str:
    template_path = Path(__file__).resolve().parent / "templates" / "admin.html"
    return template_path.read_text(encoding="utf-8")


def write_admin_html(output_path: Path) -> None:
    admin_path = output_path / "admin"
    admin_path.mkdir(parents=True, exist_ok=True)
    (admin_path / "index.html").write_text(load_admin_template(), encoding="utf-8")
