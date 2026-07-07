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

from .korea_exports import fetch_itemtrade_records
from .utils import add_months, fmt_number, fmt_pct, fmt_signed, month_key, pct_change, to_float
from .wsts import find_wsts_xlsx_url, parse_wsts_sheet

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
GEMINI_DEFAULT_MODEL = "gemini-3.1-flash-lite"
GEMINI_GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
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

    previous_payload = load_previous_dashboard_payload(data_path / "dashboard.json")
    payload = build_dashboard_payload(config, session)
    annotate_dashboard_updates(payload, previous_payload)
    payload["morning_briefing"] = build_morning_briefing(payload, session)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)

    copy_dashboard_assets(output_path)
    (data_path / "dashboard.json").write_text(json_text + "\n", encoding="utf-8")
    (output_path / "index.html").write_text(render_dashboard_html(payload), encoding="utf-8")
    (output_path / ".nojekyll").write_text("", encoding="utf-8")
    return payload


def load_previous_dashboard_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


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


def build_morning_briefing(payload: dict[str, Any], session: requests.Session) -> dict[str, Any]:
    briefing = rule_based_morning_briefing(payload)
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
    context = {
        "generated_label": payload.get("generated_label", ""),
        "narrative_context": narrative_context_for_briefing(briefing),
        "top_movers": briefing.get("top_movers", []),
        "improving_industries": briefing.get("improving_industries", []),
        "slowing_industries": briefing.get("slowing_industries", []),
        "equity_leads": briefing.get("equity_leads", []),
        "source_issues": briefing.get("source_issues", []),
        "daily_changes": payload.get("daily_changes", {}),
    }
    return (
        "너는 개인 투자자가 매일 아침 산업별 지표 대시보드를 빠르게 훑도록 돕는 한국어 브리핑 작성자다.\n"
        "아래 JSON 데이터만 근거로 사용하고, 매수/매도 추천이나 목표가는 쓰지 마라.\n"
        "가장 중요한 목표는 오늘 바뀐 지표가 어떤 의미인지 쉬운 말로 설명하는 것이다.\n"
        "각 지표를 언급할 때는 name만 쓰지 말고 반드시 kind와 industry를 함께 써라. 예: '로봇 대표주가(주식 가격) Teradyne(TER)'처럼 쓴다.\n"
        "narrative_context는 시장이 요즘 그 산업을 보는 관점이다. 단, 지표 데이터와 충돌하면 지표 데이터를 우선하고 내러티브는 해석 렌즈로만 사용하라.\n"
        "narrative_context.stock_market은 주식시장 전체가 주가를 가격화하는 방식이다. 대표주가가 움직일 때는 산업 실물지표와 stock_market의 밸류에이션·금리·포지셔닝 렌즈를 함께 사용하라.\n"
        "어려운 통계 용어를 피하고, 수요가 강해졌는지, 비용 부담이 커졌는지, 투자심리가 흔들렸는지처럼 사용자가 바로 이해할 수 있게 써라.\n"
        "주가 지표는 기업 실적 자체가 아니라 시장 기대와 위험 선호가 움직인 신호라는 점을 구분해서 설명하라.\n"
        "월간·분기 지표는 새 발표 전까지 그대로일 수 있으니, daily_changes와 top_movers를 우선해서 해석하라.\n"
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
        Path.cwd() / "assets" / "industry-icons",
        Path(__file__).resolve().parents[2] / "assets" / "industry-icons",
    ]
    source = next((path for path in candidates if path.exists()), None)
    if source is None:
        return

    target = output_path / "assets" / "industry-icons"
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target, dirs_exist_ok=True)


def build_dashboard_payload(config: dict[str, Any], session: requests.Session) -> dict[str, Any]:
    timezone = str(config.get("timezone") or "Asia/Seoul")
    now = datetime.now(ZoneInfo(timezone))

    source_status: list[dict[str, str]] = []
    metrics: list[dict[str, Any]] = []

    collectors = [
        ("WSTS", collect_wsts_metrics),
        ("FRED", collect_fred_metrics),
        ("ECOS 신용스프레드", collect_ecos_credit_spread_metrics),
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
                        depth=str(series.get("depth") or ""),
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
                    depth=str(series.get("depth") or ""),
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
    history_limit = int(config.get("dashboard", {}).get("history_points", 48))
    fetch_days = int(ecos_config.get("fetch_days", 730))
    row_count = int(ecos_config.get("row_count", 1000))
    if api_key == "sample":
        fetch_days = min(fetch_days, 14)
        row_count = min(row_count, 10)
    fetch_start = today - timedelta(days=fetch_days)
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
        try:
            corporate_points = fetch_ecos_points(
                session=session,
                base_url=str(ecos_config.get("endpoint") or "https://ecos.bok.or.kr/api"),
                api_key=api_key,
                stat_code=str(item.get("stat_code") or "817Y002"),
                period=str(item.get("period") or "D"),
                start=fetch_start,
                end=today,
                item_code=str(item.get("corporate_item_code") or ""),
                row_count=row_count,
            )
            treasury_points = fetch_ecos_points(
                session=session,
                base_url=str(ecos_config.get("endpoint") or "https://ecos.bok.or.kr/api"),
                api_key=api_key,
                stat_code=str(item.get("stat_code") or "817Y002"),
                period=str(item.get("period") or "D"),
                start=fetch_start,
                end=today,
                item_code=str(item.get("treasury_item_code") or ""),
                row_count=row_count,
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
                    history=points[-history_limit:],
                    note=str(item.get("note") or ""),
                    group=group,
                    meaning=meaning,
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
    row_count: int = 1000,
) -> list[tuple[date, float]]:
    if not item_code:
        return []
    start_text = start.strftime("%Y%m%d")
    end_text = end.strftime("%Y%m%d")
    url = (
        f"{base_url.rstrip('/')}/StatisticSearch/{api_key}/json/kr/1/{row_count}/"
        f"{stat_code}/{period}/{start_text}/{end_text}/{item_code}"
    )
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
    history_limit = int(config.get("dashboard", {}).get("history_points", 48))
    metrics: list[dict[str, Any]] = []

    for item in items:
        symbol = str(item.get("symbol") or "").strip()
        if not symbol:
            continue
        name = str(item.get("name") or symbol)
        industry = str(item.get("industry") or "매크로")
        url = endpoint_template.format(symbol=symbol)
        quote_url = f"{source_url.rstrip('/')}/quote/{symbol}"

        try:
            response = session.get(
                url,
                params={"range": str(item.get("range") or "2y"), "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0 stock-industry-dashboard/1.0"},
                timeout=(5, 20),
            )
            response.raise_for_status()
            payload = response.json()
            points, currency = parse_yahoo_chart_points(payload)
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
                    history=points[-history_limit:],
                    note=str(item.get("note") or ""),
                    group=str(item.get("group") or "대표주가"),
                    depth=str(item.get("depth") or ""),
                    meaning=str(item.get("meaning") or equity_price_meaning(name)),
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
    by_date: dict[date, float] = {}
    for index, timestamp in enumerate(timestamps):
        value = None
        if index < len(closes):
            value = to_float(closes[index])
        if value is None and index < len(adjclose):
            value = to_float(adjclose[index])
        if value is None:
            continue
        observed_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date()
        by_date[observed_at] = value
    return sorted(by_date.items()), currency


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
                    history=billion_points[-history_limit:],
                    group="CAPEX",
                    meaning=sec_capex_meaning(name),
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

    if not api_key:
        return [
            make_metric(
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
            for item in items
            if item.get("tbl_id") and item.get("item_id")
        ]

    metrics: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or item.get("tbl_id") or "KOSIS 지표")
        org_id = str(item.get("org_id") or item.get("orgId") or "").strip()
        tbl_id = str(item.get("tbl_id") or item.get("tblId") or "").strip()
        item_id = item.get("item_id") or item.get("itmId")
        prd_se = str(item.get("prd_se") or item.get("prdSe") or "M").strip()
        if not org_id or not tbl_id or not item_id:
            continue

        params: dict[str, Any] = {
            "method": "getList",
            "apiKey": api_key,
            "format": "json",
            "jsonVD": "Y",
            "prdSe": prd_se,
            "newEstPrdCnt": int(item.get("history_points") or history_limit),
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
                metrics.append(
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
                    history=points[-history_limit:],
                    group=str(item.get("group") or "국내 주택"),
                    meaning=str(item.get("meaning") or ""),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one KOSIS table should not break the page.
            metrics.append(
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
            history_limit=int(config.get("dashboard", {}).get("history_points", 48)),
        )
    )
    if wsts_config.get("include_3mma", True) and "3MMA" in workbook.sheetnames:
        metrics.extend(
            wsts_sheet_metrics(
                workbook["3MMA"],
                regions,
                is_3mma=True,
                xlsx_url=str(xlsx_url),
                history_limit=int(config.get("dashboard", {}).get("history_points", 48)),
            )
        )
    return metrics


def wsts_sheet_metrics(
    sheet: Any, regions: list[str], is_3mma: bool, xlsx_url: str, history_limit: int
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
                history=billion_points[-history_limit:],
                group="판매액(WSTS)",
                depth="전체 업황",
                meaning=meaning,
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
    resolved_depth = depth or infer_metric_depth(industry, name, resolved_group)

    return {
        "id": metric_id,
        "industry": industry,
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


def english_depth(depth: str) -> str:
    return EN_DEPTH_LABELS.get(depth, depth)


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

    stock_match = re.match(r"^(.+) 주가$", name)
    if stock_match:
        return f"{stock_match.group(1)} Stock Price"

    return name


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
    wsts_old_match = re.match(r"^WSTS 반도체 판매액( 3MMA)? - (.+)$", name)
    if wsts_old_match:
        return wsts_metric_meaning(wsts_old_match.group(2), bool(wsts_old_match.group(1)))
    if name.startswith("3MMA - "):
        return wsts_metric_meaning(name.removeprefix("3MMA - "), True)
    if name in WSTS_REGION_MEANINGS:
        return wsts_metric_meaning(name, False)
    if "WSTS" in name:
        return wsts_metric_meaning("Worldwide", False)
    if "반도체 PPI" in name:
        return "반도체 생산자 가격입니다. 반도체 가격이 오르는지 내리는지 볼 때 참고합니다."
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
    if "환율" in name:
        return "수출주 원화 환산 매출과 외국인 수급에 영향을 주는 매크로 변수입니다."
    if "VIX" in name:
        return "시장 위험 회피 심리와 변동성 확대 여부를 봅니다."
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
      --detail-stat-bg: #f8f8f8;
      --branch-line: #e0e0e0;
      --ai-card-bg: linear-gradient(135deg, rgba(6, 182, 212, 0.06) 0%, rgba(59, 130, 246, 0.08) 48%, rgba(79, 70, 229, 0.10) 100%);
      --ai-card-border: rgba(59, 130, 246, 0.12);
      --ai-inset-bg: rgba(255, 255, 255, 0.46);
      --ai-inset-border: rgba(59, 130, 246, 0.10);
      --ai-bullet-text: #7a7a7a;
      --ai-bullet-body: #9a9a9a;
      --favorite-star: #f59e0b;
      --chart-up: #f23645;
      --chart-down: #1f5eff;
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
      --detail-stat-bg: #1a1a1a;
      --branch-line: #3c3c3c;
      --ai-card-bg: linear-gradient(135deg, rgba(6, 182, 212, 0.10) 0%, rgba(59, 130, 246, 0.12) 48%, rgba(79, 70, 229, 0.14) 100%);
      --ai-card-border: rgba(96, 165, 250, 0.18);
      --ai-inset-bg: rgba(255, 255, 255, 0.045);
      --ai-inset-border: rgba(96, 165, 250, 0.12);
      --ai-bullet-text: #a8a8a8;
      --ai-bullet-body: #898989;
      --favorite-star: #fbbf24;
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
    body.theme-ready .scroll-top-button,
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

    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
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
      height: calc(100vh - 44px);
      max-height: calc(100vh - 44px);
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
      scrollbar-width: none;
      -ms-overflow-style: none;
      cursor: grab;
      overscroll-behavior: contain;
      -webkit-overflow-scrolling: touch;
      user-select: none;
    }

    .side-menu::-webkit-scrollbar {
      display: none;
    }

    .side-menu.is-drag-scrolling {
      cursor: grabbing;
    }

    .side-menu.is-drag-scrolling * {
      cursor: grabbing !important;
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
      color: var(--text);
    }

    .side-menu button[aria-current="true"] {
      background: var(--menu-active);
      color: var(--text);
    }

    .menu-depth-list {
      display: grid;
      gap: 3px;
      margin: 4px 0 6px 6px;
      padding-left: 4px;
    }

    .menu-depth-item {
      min-width: 0;
    }

    .side-menu .menu-depth-button {
      min-height: 31px;
      border-radius: 10px;
      padding: 0 10px;
      color: var(--muted);
      font-size: 12.5px;
      font-weight: 500;
    }

    .side-menu .menu-depth-button[aria-current="true"] {
      color: var(--text);
      background: var(--menu-active);
    }

    .sidebar.is-reordering .menu-depth-list {
      display: none;
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
      top: 19px;
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
      font-weight: 400;
      text-align: left;
    }

    .settings-menu button:hover {
      background: var(--menu);
    }

    .settings-meta {
      color: var(--muted);
      font-size: 11px;
      font-weight: 400;
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
      min-width: 94px;
      height: 40px;
      border: 0;
      border-radius: 24px;
      display: inline-grid;
      grid-template-columns: 20px auto 18px;
      align-items: center;
      justify-content: center;
      gap: 7px;
      position: relative;
      background: var(--menu);
      color: var(--text);
      cursor: pointer;
      padding: 0 11px;
      font-size: 13px;
      font-weight: 400;
    }

    .scroll-top-button {
      position: fixed;
      right: max(18px, env(safe-area-inset-right));
      bottom: max(18px, env(safe-area-inset-bottom));
      z-index: 58;
      width: 40px;
      height: 40px;
      border: 0;
      border-radius: 999px;
      display: inline-grid;
      place-items: center;
      flex: 0 0 auto;
      background: var(--menu);
      color: var(--text);
      cursor: pointer;
      font-size: 16px;
      box-shadow: var(--menu-shadow);
      opacity: 0;
      visibility: hidden;
      pointer-events: none;
      transform: translateY(10px);
    }

    body.theme-ready .scroll-top-button {
      transition:
        background-color 520ms ease,
        border-color 520ms ease,
        box-shadow 520ms ease,
        color 520ms ease,
        opacity 180ms ease,
        transform 180ms ease,
        visibility 180ms ease;
    }

    body.show-scroll-top .scroll-top-button {
      opacity: 1;
      visibility: visible;
      pointer-events: auto;
      transform: translateY(0);
    }

    .currency-toggle:hover,
    .theme-toggle:hover,
    .scroll-top-button:hover {
      background: var(--menu-active);
    }

    .currency-toggle:focus-visible,
    .theme-toggle:focus-visible,
    .scroll-top-button:focus-visible {
      outline: 2px solid var(--text);
      outline-offset: 3px;
    }

    .toggle-label {
      min-width: 0;
      white-space: nowrap;
      line-height: 1;
      transform: translateY(0);
    }

    .toggle-chevron {
      width: 16px;
      height: 16px;
      color: var(--muted);
      stroke-width: 2;
    }

    .currency-icon-slot,
    .theme-icon-orbit {
      position: relative;
      width: 20px;
      height: 20px;
      display: block;
      overflow: hidden;
      font-size: 16px;
    }

    .currency-icon {
      position: absolute;
      left: 50%;
      top: 50%;
      display: grid;
      place-items: center;
      opacity: 0;
      transform: translate(-50%, -50%) translateY(-15px);
      transition: opacity 220ms ease, transform 220ms ease;
    }

    body.currency-usd .currency-icon-dollar,
    body.currency-krw .currency-icon-won {
      opacity: 1;
      transform: translate(-50%, -50%) translateY(0);
    }

    body.currency-usd .currency-icon-won,
    body.currency-krw .currency-icon-dollar {
      opacity: 0;
      transform: translate(-50%, -50%) translateY(-15px);
    }

    .theme-toggle:disabled {
      cursor: default;
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
      transform: translate(-50%, -50%) translateY(-15px);
      transform-origin: center;
      pointer-events: none;
    }

    body:not(.theme-dark) .theme-icon-sun,
    body.theme-dark .theme-icon-moon {
      opacity: 1;
      transform: translate(-50%, -50%) translateY(0);
    }

    body:not(.theme-dark) .theme-icon-moon,
    body.theme-dark .theme-icon-sun {
      opacity: 0;
      transform: translate(-50%, -50%) translateY(-15px);
    }

    .toggle-label.is-exiting {
      animation: toggleLabelExit 240ms ease forwards;
    }

    .toggle-label.is-entering {
      animation: toggleLabelEnter 300ms ease forwards;
    }

    .currency-icon.is-exiting,
    .theme-icon.is-exiting {
      animation: toggleIconExit 240ms ease forwards;
    }

    .currency-icon.is-entering,
    .theme-icon.is-entering {
      animation: toggleIconEnter 300ms ease forwards;
    }

    @keyframes toggleLabelExit {
      0% {
        opacity: 1;
        transform: translateY(0);
      }
      100% {
        opacity: 0;
        transform: translateY(14px);
      }
    }

    @keyframes toggleLabelEnter {
      0% {
        opacity: 0;
        transform: translateY(-14px);
      }
      100% {
        opacity: 1;
        transform: translateY(0);
      }
    }

    @keyframes toggleIconExit {
      0% {
        opacity: 1;
        transform: translate(-50%, -50%) translateY(0);
      }
      100% {
        opacity: 0;
        transform: translate(-50%, -50%) translateY(15px);
      }
    }

    @keyframes toggleIconEnter {
      0% {
        opacity: 0;
        transform: translate(-50%, -50%) translateY(-15px);
      }
      100% {
        opacity: 1;
        transform: translate(-50%, -50%) translateY(0);
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
      body.theme-ready .scroll-top-button,
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

      .toggle-label.is-exiting,
      .toggle-label.is-entering,
      .currency-icon.is-exiting,
      .currency-icon.is-entering,
      .theme-icon.is-exiting,
      .theme-icon.is-entering {
        animation-duration: 1ms;
      }
    }

    .industry-stack {
      display: grid;
      gap: 4px;
      min-width: 0;
    }

    .daily-updates {
      min-width: 0;
      margin: 4px 0 18px;
    }

    .morning-briefing {
      position: relative;
      min-width: 0;
      display: grid;
      gap: 16px;
      margin: 0 0 18px;
      padding: 16px;
      border: 1px solid var(--ai-card-border);
      border-radius: 24px;
      background: var(--ai-card-bg);
      overflow: hidden;
    }

    .morning-briefing-head {
      min-width: 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .morning-briefing h2,
    .morning-briefing h3 {
      margin: 0;
    }

    .morning-briefing h2 {
      font-size: 17px;
      line-height: 1.2;
      font-weight: 760;
    }

    .briefing-title {
      min-width: 0;
      display: inline-flex;
      align-items: center;
      gap: 10px;
    }

    .ai-sparkle-icon {
      width: 22px;
      height: 22px;
      flex: 0 0 auto;
      overflow: visible;
      filter: drop-shadow(0 0 8px rgba(59, 130, 246, 0.18));
      animation: aiSparklePulse 1800ms ease-in-out infinite;
    }

    .ai-sparkle-icon path {
      fill: url(#aiSparkleGradient);
    }

    @keyframes aiSparklePulse {
      0%, 100% {
        transform: scale(1);
      }
      50% {
        transform: scale(1.07);
      }
    }

    @media (prefers-reduced-motion: reduce) {
      .ai-sparkle-icon {
        animation: none;
      }
    }

    .briefing-meta {
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 7px;
      border-radius: 999px;
      background: var(--ai-inset-bg);
      color: var(--muted);
      font-size: 11px;
      line-height: 1;
      white-space: nowrap;
      border: 1px solid var(--ai-inset-border);
    }

    .briefing-headline {
      margin: 0;
      font-size: 17px;
      line-height: 1.32;
      font-weight: 760;
    }

    .briefing-summary {
      margin: -2px 0 0;
      color: var(--text);
      font-size: 13px;
      line-height: 1.55;
      overflow-wrap: anywhere;
    }

    .briefing-bullets {
      min-width: 0;
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0 0 0 18px;
    }

    .briefing-bullet {
      min-width: 0;
      padding-left: 2px;
      color: var(--ai-bullet-text);
    }

    .briefing-bullet::marker {
      color: var(--ai-bullet-text);
      font-size: 0.9em;
    }

    .briefing-bullet-button,
    .briefing-bullet-static {
      display: block;
      width: 100%;
      min-width: 0;
      border: 0;
      background: transparent;
      color: var(--ai-bullet-text);
      padding: 0;
      text-align: left;
    }

    .briefing-bullet-button {
      cursor: pointer;
    }

    .briefing-bullet-button:hover .briefing-bullet-title {
      text-decoration: underline;
      text-underline-offset: 3px;
    }

    .briefing-bullet-title {
      display: inline;
      margin-right: 5px;
      font-size: 12px;
      line-height: 1.2;
      font-weight: 500;
    }

    .briefing-bullet-body {
      display: inline;
      color: var(--ai-bullet-body);
      font-size: 12px;
      line-height: 1.4;
      overflow-wrap: anywhere;
    }

    .briefing-disclaimer {
      margin: -2px 0 0;
      padding-top: 10px;
      border-top: 1px solid var(--ai-inset-border);
      display: grid;
      grid-template-columns: 16px minmax(0, 1fr);
      gap: 7px;
      align-items: center;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }

    .briefing-disclaimer-icon {
      width: 16px;
      height: 16px;
      border-radius: 999px;
      display: inline-grid;
      place-items: center;
      background: var(--menu);
      color: var(--muted);
      font-size: 9px;
      line-height: 1;
    }

    .favorite-metrics {
      min-width: 0;
      display: grid;
      gap: 16px;
      margin: 46px 0 30px;
      padding-bottom: 12px;
    }

    .favorite-metrics-head {
      display: flex;
      align-items: baseline;
      justify-content: flex-start;
      gap: 7px;
      padding: 0 4px;
    }

    .favorite-metrics .favorite-metrics-head h2 {
      margin: 0;
      color: var(--text);
      font-size: 20px;
      line-height: 1.12;
      font-weight: 900;
    }

    .favorite-metrics-count {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.1;
      font-weight: 500;
      white-space: nowrap;
    }

    .favorite-metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 220px));
      gap: 10px;
      justify-content: start;
      min-width: 0;
    }

    .favorite-card {
      position: relative;
      min-width: 0;
      min-height: 132px;
      display: grid;
      grid-template-rows: auto minmax(38px, 1fr);
      gap: 9px;
      border: 0;
      border-radius: 24px;
      background: var(--menu);
      color: var(--text);
      padding: 16px;
      text-align: left;
      cursor: pointer;
    }

    .favorite-card-star {
      position: absolute;
      right: 10px;
      top: 10px;
      width: 32px;
      height: 32px;
      border: 0;
      border-radius: 999px;
      display: grid;
      place-items: center;
      background: rgba(255, 255, 255, 0.42);
      color: var(--favorite-star);
      cursor: pointer;
      font-size: 13px;
    }

    body.theme-dark .favorite-card-star {
      background: rgba(255, 255, 255, 0.08);
    }

    .favorite-card-star:hover {
      background: var(--menu-active);
    }

    .favorite-card:hover {
      background: var(--menu-active);
    }

    .favorite-card:focus-visible,
    .favorite-card-star:focus-visible {
      outline: 2px solid var(--text);
      outline-offset: 3px;
    }

    .favorite-card-top {
      min-width: 0;
      display: grid;
      gap: 5px;
      padding-right: 34px;
    }

    .favorite-card-title {
      min-width: 0;
      color: var(--text);
      font-size: 10.5px;
      line-height: 1.24;
      font-weight: 400;
      overflow-wrap: anywhere;
    }

    .favorite-card-value {
      color: var(--text);
      font-size: 18px;
      line-height: 1.08;
      font-weight: 560;
      overflow-wrap: anywhere;
    }

    .favorite-card-meta {
      color: var(--muted);
      font-size: 10.5px;
      line-height: 1.2;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .favorite-card-chart {
      min-width: 0;
      align-self: end;
    }

    .favorite-card-chart .chart-mini {
      width: 100%;
      height: 42px;
      max-height: 42px;
    }

    .daily-update-details {
      min-width: 0;
      margin: -4px 0 0;
    }

    .daily-update-summary {
      width: max-content;
      max-width: 100%;
      display: inline-flex;
      align-items: center;
      gap: 3px;
      list-style: none;
      margin-left: 10px;
      padding: 0 4px;
      border: 0;
      background: transparent;
      color: var(--muted);
      font-size: 11.5px;
      line-height: 1.45;
      font-weight: 400;
      cursor: pointer;
      opacity: 0.72;
      user-select: none;
    }

    .daily-update-summary::-webkit-details-marker {
      display: none;
    }

    .daily-update-summary:hover {
      opacity: 1;
      color: var(--text);
    }

    .daily-update-summary-icon {
      display: inline-block;
      transform: translateY(-0.5px);
      transition: transform 180ms ease;
    }

    .daily-update-details[open] .daily-update-summary-icon {
      transform: translateY(-0.5px) rotate(90deg);
    }

    .daily-update-panel {
      margin-top: 8px;
    }

    .daily-updates-head {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 12px;
      margin: 0 0 8px;
      padding: 0 4px;
    }

    .daily-updates h2 {
      margin: 0;
      font-size: 13px;
      line-height: 1.2;
      font-weight: 500;
      color: var(--muted);
    }

    .daily-update-counts {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-start;
      gap: 6px;
      margin-top: 8px;
      padding: 0 4px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1;
      white-space: nowrap;
    }

    .daily-update-count {
      padding: 6px 8px;
      border-radius: 999px;
      background: var(--menu);
    }

    .daily-update-list {
      max-height: 238px;
      overflow: auto;
      border-radius: 6px;
      background: var(--line);
      display: grid;
      gap: 1px;
    }

    .daily-update-row,
    .daily-update-empty {
      min-width: 0;
      border: 0;
      background: var(--surface);
      color: var(--text);
    }

    .daily-update-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 120px 104px 148px;
      align-items: center;
      gap: 10px;
      width: 100%;
      padding: 9px 10px;
      text-align: left;
      cursor: pointer;
    }

    .daily-update-row:hover {
      background: var(--menu);
    }

    .daily-update-empty {
      padding: 14px 12px;
      color: var(--muted);
      font-size: 12px;
    }

    .daily-update-main {
      min-width: 0;
      display: flex;
      align-items: center;
      gap: 7px;
    }

    .daily-update-title {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 12.5px;
      line-height: 1.2;
      font-weight: 400;
    }

    .daily-update-meta,
    .daily-update-value,
    .daily-update-change {
      min-width: 0;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.2;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .daily-update-value {
      color: var(--text);
      text-align: right;
    }

    .daily-update-change {
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      gap: 4px;
      color: var(--muted);
      text-align: right;
    }

    .daily-update-change i {
      flex: 0 0 auto;
      font-size: 10px;
    }

    .daily-update-change-abs,
    .daily-update-change-pct {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .daily-update-change-pct {
      opacity: 0.9;
    }

    .industry {
      min-width: 0;
      scroll-margin-top: 22px;
      padding-bottom: 28px;
      background: transparent;
      box-shadow: none;
      overflow: visible;
    }

    .industry:last-child {
      padding-bottom: 0;
    }

    .industry-head {
      display: grid;
      grid-template-columns: 96px minmax(0, 1fr);
      gap: 18px;
      align-items: center;
      padding: 24px 0 18px;
      border-bottom: 0;
      background: transparent;
    }

    .industry-icon-wrap {
      width: 96px;
      height: 96px;
      border-radius: 999px;
      display: grid;
      place-items: center;
      background: var(--menu);
    }

    .industry-icon {
      width: 88px;
      height: 88px;
      object-fit: contain;
      display: block;
    }

    .industry h2 {
      margin: 0;
      font-size: 20px;
      line-height: 1.12;
      font-weight: 900;
    }

    .group {
      padding: 0 0 22px;
    }

    .depth-tree {
      --depth-content-left: 48px;
      --depth-line-left: 10px;
      --depth-corner-gap: 16px;
      --depth-corner-left: calc(var(--depth-line-left) - var(--depth-content-left));
      --depth-corner-width: calc(var(--depth-content-left) - var(--depth-line-left) - var(--depth-corner-gap));
      --depth-corner-height: 17px;
      position: relative;
      margin-left: 0;
      padding-left: var(--depth-content-left);
    }

    .depth-tree::before {
      content: "";
      position: absolute;
      left: var(--depth-line-left);
      top: var(--depth-branch-top, 14px);
      width: 1px;
      height: var(--depth-branch-height, 0px);
      background: var(--branch-line);
      border-radius: 999px;
    }

    .depth-section {
      position: relative;
      margin-left: 0;
      padding: 0 0 28px;
      border-bottom: 0;
    }

    .depth-section:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }

    .depth-title {
      position: relative;
      margin: 20px 0 10px;
      color: var(--text);
      font-size: 16px;
      line-height: 1.2;
      font-weight: 500;
    }

    .depth-title::before {
      content: "";
      position: absolute;
      box-sizing: border-box;
      left: var(--depth-corner-left);
      top: 50%;
      width: var(--depth-corner-width);
      height: var(--depth-corner-height);
      border-left: 1px solid var(--branch-line);
      border-bottom: 1px solid var(--branch-line);
      border-bottom-left-radius: 18px;
      transform: translateY(-100%);
    }

    .depth-section .group-title {
      margin: 10px 0 12px;
      color: var(--muted);
      font-size: 16px;
      font-weight: 500;
    }

    .group-title {
      margin: 14px 0 12px 10px;
      color: var(--text);
      font-size: 16px;
      font-weight: 500;
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

    .metric-table tbody,
    .metric-table tbody button,
    .metric-table tbody strong,
    .metric-table tbody .metric-name,
    .metric-table tbody .metric-date,
    .metric-table tbody .metric-current-value,
    .metric-table tbody .metric-change-badge,
    .metric-table tbody .metric-mobile-description,
    .metric-table tbody .detail-label,
    .metric-table tbody .detail-value {
      font-weight: 400;
    }

    .metric-row {
      cursor: pointer;
    }

    .metric-row:hover td {
      background: var(--menu);
    }

    .metric-row.is-highlighted td {
      background: var(--menu-active);
    }

    .metric-row.is-expanded td {
      background: var(--menu-active);
    }

    .metric-name-cell { width: 22%; }
    .metric-description-cell { width: 28%; }
    .metric-date-cell { width: 10%; }
    .metric-value-cell { width: 12%; }
    .metric-chart-cell { width: 13%; }
    .metric-favorite-cell { width: 5%; }

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

    .metric-name-wrap {
      min-width: 0;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      max-width: 100%;
      vertical-align: top;
    }

    .metric-name-wrap .metric-name {
      min-width: 0;
    }

    .metric-update-dot {
      flex: 0 0 auto;
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--chart-up);
      box-shadow: 0 0 0 3px rgba(242, 54, 69, 0.12);
      transform-origin: center;
      animation: updateDotBreath 1700ms ease-in-out infinite;
    }

    @keyframes updateDotBreath {
      0%, 100% {
        opacity: 0.86;
        transform: scale(1);
        box-shadow: 0 0 0 3px rgba(242, 54, 69, 0.12);
      }
      50% {
        opacity: 1;
        transform: scale(1.28);
        box-shadow: 0 0 0 6px rgba(242, 54, 69, 0.045);
      }
    }

    @media (prefers-reduced-motion: reduce) {
      .metric-update-dot {
        animation: none;
      }
    }

    .metric-new-badge {
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      height: 17px;
      padding: 0 6px;
      border-radius: 999px;
      background: var(--chart-up);
      color: #fff;
      font-size: 9.5px;
      line-height: 1;
      font-weight: 650;
      letter-spacing: 0;
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

    .metric-favorite-cell {
      text-align: right;
    }

    .metric-favorite-button {
      width: 34px;
      height: 34px;
      border: 0;
      border-radius: 999px;
      display: inline-grid;
      place-items: center;
      background: var(--menu);
      color: var(--muted);
      cursor: pointer;
      font-size: 14px;
    }

    .metric-favorite-button:hover {
      background: var(--menu-active);
      color: var(--text);
    }

    .metric-favorite-button.is-active {
      background: var(--menu-active);
      color: var(--favorite-star);
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
      max-height: 680px;
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
      padding: 0;
      border-radius: 0;
      background: transparent;
    }

    .detail-stat {
      min-width: 0;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--detail-stat-bg);
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

    .detail-chart {
      position: relative;
      width: 100%;
      max-width: 100%;
      display: grid;
      grid-template-columns: 42px minmax(0, 1fr);
      align-items: stretch;
      overflow: hidden;
      padding: 2px 0 10px;
    }

    .detail-chart-axis {
      width: 42px;
      min-width: 42px;
      height: 190px;
      border-right: 0;
      border-radius: 8px 0 0 8px;
      display: block;
    }

    .detail-chart-scroll {
      min-width: 0;
      overflow-x: auto;
      overflow-y: hidden;
      -webkit-overflow-scrolling: touch;
    }

    .detail-chart-scroll .chart {
      width: max(100%, var(--detail-chart-width, 520px));
      min-width: max(100%, var(--detail-chart-width, 520px));
      height: 190px;
      display: block;
    }

    .detail-chart-scroll .chart-detail {
      border-left: 0;
      border-radius: 0 8px 8px 0;
    }

    .detail-chart-tooltip {
      position: absolute;
      z-index: 5;
      left: 0;
      top: 0;
      width: min(220px, calc(100vw - 44px));
      padding: 9px 10px;
      border-radius: 12px;
      background: var(--text);
      color: var(--surface);
      box-shadow: var(--menu-shadow);
      opacity: 0;
      pointer-events: none;
      transform: translate(-50%, 12px);
      transition: opacity 140ms ease, transform 140ms ease;
    }

    .detail-chart-tooltip.is-visible {
      opacity: 1;
      transform: translate(-50%, 8px);
    }

    .detail-tooltip-title {
      margin-bottom: 6px;
      color: inherit;
      font-size: 11px;
      line-height: 1.25;
      font-weight: 650;
      overflow-wrap: anywhere;
    }

    .detail-tooltip-row {
      display: grid;
      grid-template-columns: 42px minmax(0, 1fr);
      gap: 8px;
      align-items: baseline;
      font-size: 11px;
      line-height: 1.35;
    }

    .detail-tooltip-label {
      color: color-mix(in srgb, currentColor 62%, transparent);
    }

    .detail-tooltip-value {
      min-width: 0;
      text-align: right;
      overflow-wrap: anywhere;
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

    .chart.chart-mini,
    .chart.detail-chart-axis,
    .detail-chart-scroll .chart.chart-detail {
      border: 0;
      border-radius: 0;
      background: transparent;
    }

    .chart text {
      fill: var(--muted);
      font-size: 10.5px;
      font-weight: 400;
    }

    .chart text.level-max {
      fill: var(--chart-down);
    }

    .chart text.level-min {
      fill: var(--chart-up);
    }

    .chart text.level-current {
      fill: var(--text);
    }

    .axis-line {
      stroke: var(--line);
      stroke-width: 1;
    }

    .guide {
      stroke: var(--line);
      stroke-width: 0.7;
      stroke-dasharray: 4 4;
    }

    .chart-background-line {
      stroke: var(--line);
      stroke-width: 0.55;
      stroke-dasharray: 3 5;
      opacity: 0.44;
    }

    .chart-background-line.level-line {
      opacity: 0.92;
      stroke-width: 0.7;
      stroke-dasharray: 4 5;
    }

    .chart-background-line.level-max {
      stroke: var(--chart-down);
    }

    .chart-background-line.level-min {
      stroke: var(--chart-up);
    }

    .chart-background-line.level-current {
      stroke: var(--text);
      stroke-width: 1.5;
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

    .detail-point-hit {
      cursor: crosshair;
      pointer-events: all;
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
        height: 100dvh;
        max-height: 100dvh;
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
        scrollbar-width: none;
        -ms-overflow-style: none;
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
        position: relative;
        z-index: 1;
        display: block;
        min-height: 84px;
        margin: 0;
        padding: 52px 0 0;
        background: transparent;
        box-shadow: none;
        backdrop-filter: none;
      }

      .mobile-menu-toggle {
        position: fixed;
        left: max(10px, env(safe-area-inset-left));
        top: max(10px, env(safe-area-inset-top));
        z-index: 58;
        width: 40px;
        height: 40px;
      }

      .topbar-actions {
        position: fixed;
        right: max(10px, env(safe-area-inset-right));
        top: max(10px, env(safe-area-inset-top));
        z-index: 58;
        gap: 6px;
      }

      .currency-toggle,
      .theme-toggle {
        min-width: 76px;
        width: auto;
        height: 40px;
        grid-template-columns: 18px auto 14px;
        gap: 5px;
        padding: 0 9px;
        border-radius: 24px;
        font-size: 12px;
      }

      .scroll-top-button {
        right: max(14px, env(safe-area-inset-right));
        bottom: max(18px, env(safe-area-inset-bottom));
        width: 40px;
        height: 40px;
        font-size: 15px;
      }

      .currency-toggle .toggle-label,
      .theme-toggle .toggle-label {
        display: inline;
      }

      .currency-icon-slot,
      .theme-icon-orbit {
        width: 18px;
        height: 18px;
        font-size: 15px;
      }

      .toggle-chevron {
        width: 14px;
        height: 14px;
      }

      h1 {
        min-width: 0;
        font-size: clamp(18px, 5vw, 22px);
      }

      .daily-updates {
        margin: 0 0 14px;
      }

      .morning-briefing {
        gap: 13px;
        margin-bottom: 12px;
        padding: 13px;
      }

      .morning-briefing-head {
        align-items: center;
        gap: 8px;
      }

      .morning-briefing h2 {
        font-size: 16px;
      }

      .briefing-meta {
        font-size: 10px;
      }

      .briefing-headline {
        font-size: 15px;
      }

      .briefing-summary,
      .briefing-bullet-body {
        font-size: 11.5px;
      }

      .favorite-metrics {
        gap: 14px;
        margin: 38px 0 24px;
        padding-bottom: 10px;
      }

      .favorite-metrics .favorite-metrics-head h2 {
        font-size: 18px;
      }

      .favorite-metrics-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
      }

      .favorite-card {
        min-height: 116px;
        padding: 14px;
      }

      .favorite-card-star {
        right: 8px;
        top: 8px;
        width: 28px;
        height: 28px;
        font-size: 12px;
      }

      .favorite-card-value {
        font-size: 15px;
      }

      .daily-updates-head {
        align-items: start;
        padding: 0 2px;
      }

      .daily-updates h2 {
        font-size: 12px;
      }

      .daily-update-summary {
        font-size: 11px;
        margin-left: 8px;
        padding: 0 2px;
      }

      .daily-update-counts {
        gap: 4px;
        font-size: 10.5px;
      }

      .daily-update-count {
        padding: 5px 7px;
      }

      .daily-update-list {
        max-height: 210px;
      }

      .daily-update-row {
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 5px 8px;
        padding: 8px 7px;
      }

      .daily-update-main {
        grid-column: 1;
        grid-row: 1;
      }

      .daily-update-value {
        grid-column: 2;
        grid-row: 1;
      }

      .daily-update-meta {
        grid-column: 1;
        grid-row: 2;
        font-size: 10.5px;
      }

      .daily-update-title {
        font-size: 12px;
      }

      .daily-update-value,
      .daily-update-change {
        font-size: 10.5px;
      }

      .daily-update-change {
        grid-column: 2;
        grid-row: 2;
        align-self: center;
        gap: 3px;
      }

      .industry-head {
        grid-template-columns: 80px minmax(0, 1fr);
        gap: 12px;
        padding: 18px 0 12px;
      }

      .industry-icon-wrap {
        width: 80px;
        height: 80px;
      }

      .industry-icon {
        width: 74px;
        height: 74px;
      }

      .industry h2 {
        font-size: 18px;
      }

      .group { padding: 0 0 18px; }

      .depth-section .group-title,
      .group-title {
        margin: 12px 0 10px 8px;
        font-size: 15px;
      }

      .depth-title {
        margin: 18px 0 8px;
        font-size: 15px;
      }

      .depth-tree {
        --depth-content-left: 42px;
        --depth-line-left: 8px;
        --depth-corner-gap: 14px;
        --depth-corner-height: 15px;
      }

      .depth-tree::before {
        left: var(--depth-line-left);
      }

      .depth-section {
        margin-left: 0;
        padding-left: 0;
      }

      .depth-title::before {
        border-bottom-left-radius: 16px;
      }

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

      .metric-name-cell { width: 46%; }
      .metric-value-cell { width: 20%; }
      .metric-chart-cell { width: 26%; }
      .metric-favorite-cell { width: 8%; }

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

      .metric-favorite-button {
        width: 30px;
        height: 30px;
        font-size: 12.5px;
      }

      .metric-detail-row td {
        padding: 0 6px;
      }

      .metric-detail-inner {
        gap: 8px;
        padding: 10px 0 12px;
      }

      .detail-chart {
        grid-template-columns: 40px minmax(0, 1fr);
        overflow: hidden;
        padding: 0 0 6px;
      }

      .detail-chart-axis {
        width: 40px;
        min-width: 40px;
        height: 158px;
      }

      .detail-chart-scroll .chart {
        width: max(100%, var(--detail-chart-width, 520px));
        min-width: max(100%, var(--detail-chart-width, 520px));
        height: 158px;
      }

      .detail-stats {
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 5px 7px;
        padding: 0;
      }

      .detail-stat {
        padding: 7px 6px;
        border-radius: 6px;
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
          <button class="scroll-top-button" id="scrollTopButton" type="button" aria-label="최상단 이동" title="최상단 이동">
            <i class="fa-solid fa-arrow-up" aria-hidden="true"></i>
          </button>
          <button class="currency-toggle" id="currencyToggle" type="button" aria-label="원화 표시" title="원화 표시">
            <span class="currency-icon-slot" aria-hidden="true">
              <i class="fa-solid fa-dollar-sign currency-icon currency-icon-dollar"></i>
              <i class="fa-solid fa-won-sign currency-icon currency-icon-won"></i>
            </span>
            <span class="toggle-label" id="currencyToggleLabel">달러</span>
            <svg xmlns="http://www.w3.org/2000/svg" class="toggle-chevron lucide lucide-chevrons-up-down-icon lucide-chevrons-up-down" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/></svg>
          </button>
          <button class="theme-toggle" id="themeToggle" type="button" aria-label="다크모드 전환" title="다크모드 전환">
            <span class="theme-icon-orbit" aria-hidden="true">
              <i class="fa-solid fa-sun theme-icon theme-icon-sun"></i>
              <i class="fa-solid fa-moon theme-icon theme-icon-moon"></i>
            </span>
            <span class="toggle-label" id="themeToggleLabel">라이트</span>
            <svg xmlns="http://www.w3.org/2000/svg" class="toggle-chevron lucide lucide-chevrons-up-down-icon lucide-chevrons-up-down" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/></svg>
          </button>
        </div>
      </header>
      <section class="daily-updates" id="dailyUpdates"></section>
      <section class="industry-stack" id="industryStack"></section>
      <div class="empty" id="empty" data-i18n="empty">표시할 지표가 없습니다.</div>
    </section>
  </main>

  <script>
    const DASHBOARD_DATA = __DASHBOARD_JSON__;
    const state = {
      activeIndustry: "",
      activeDepth: "",
      isReordering: false,
      draftIndustryOrder: null,
      draggedMenuItem: null,
      language: "ko",
      currency: "usd",
      favoriteMetricIds: new Set()
    };
    const favoriteMetricStorageKey = "dashboard-favorite-metrics";
    const mobileDrawerQuery = window.matchMedia ? window.matchMedia("(max-width: 760px)") : { matches: false };
    let scrollSpyFrame = 0;
    let suppressMenuClick = false;
    const groupOrder = [
      "판매액(WSTS)", "판매액", "시장 매출", "가격/수요", "투자/장비", "수출",
      "판매/수요", "판매량", "배터리 원재료",
      "운임/해운", "선가/발주",
      "원자재 가격", "중국 경기",
      "에너지 가격", "원유/원료", "화학 스프레드", "스프레드/마진",
      "금리", "신용 스프레드", "스프레드", "금리/스프레드", "은행 건전성", "대출/건전성",
      "주택 경기", "건설 선행", "금융비용", "주택 시장",
      "시장지수", "환율", "리스크", "시장 분위기", "핵심 지표", "대표주가"
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
        scrollTop: "최상단 이동",
        toggleTheme: "다크모드 전환",
        showKrw: "원화 표시",
        showUsd: "달러 표시",
        currencyKrwName: "원화",
        currencyUsdName: "달러",
        themeLightName: "라이트",
        themeDarkName: "다크",
        tooltipPeriod: "연도",
        tooltipValue: "지표",
        tooltipChange: "증감",
        todayChanges: "오늘 변경",
        showDailyChanges: "오늘 변경된 내용 확인하기",
        morningBriefing: "AI 요약",
        aiBriefing: "AI 요약",
        fallbackBriefing: "룰 기반 요약",
        favoriteMetrics: "별표한 지표",
        favoriteCount: "개",
        addFavorite: "별표 추가",
        removeFavorite: "별표 해제",
        briefingDisclaimer: "이 브리핑은 AI가 공개 지표를 바탕으로 자동 생성한 참고 자료입니다. 실제 투자 판단 전에는 원자료와 리스크를 함께 확인하세요.",
        updatedCount: "업데이트",
        newCount: "신규",
        noDailyChanges: "오늘 변경된 지표 없음",
        updatedBadge: "업데이트",
        newBadge: "New"
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
        scrollTop: "Back to top",
        toggleTheme: "Toggle dark mode",
        showKrw: "Show KRW",
        showUsd: "Show USD",
        currencyKrwName: "KRW",
        currencyUsdName: "USD",
        themeLightName: "Light",
        themeDarkName: "Dark",
        tooltipPeriod: "Period",
        tooltipValue: "Value",
        tooltipChange: "Change",
        todayChanges: "Today",
        showDailyChanges: "View today's changes",
        morningBriefing: "AI Summary",
        aiBriefing: "AI summary",
        fallbackBriefing: "Rule summary",
        favoriteMetrics: "Starred Metrics",
        favoriteCount: "items",
        addFavorite: "Add star",
        removeFavorite: "Remove star",
        briefingDisclaimer: "This summary is for quick reference from public indicators and is not investment advice or a buy/sell recommendation.",
        updatedCount: "Updated",
        newCount: "New",
        noDailyChanges: "No changed metrics today",
        updatedBadge: "Updated",
        newBadge: "New"
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

    function localizedDepth(depth, items = []) {
      if (state.language !== "en") return depth || "";
      const first = items.find((item) => item.depth === depth && item.depth_en);
      return first?.depth_en || depth || "";
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
      if (group === "대표주가") return 10000;
      const index = groupOrder.indexOf(group);
      return index === -1 ? 999 : index;
    }

    const depthOrder = ["전체 업황", "메모리 반도체", "AI/GPU", "CPU/프로세서", "파운드리", "장비", "패키징/후공정", "소자/부품"];

    function depthRank(depth) {
      const index = depthOrder.indexOf(depth);
      return index === -1 ? 999 : index;
    }

    function groupMetrics(items, keyFn) {
      if (Map.groupBy) return Map.groupBy(items, keyFn);
      return items.reduce((map, item) => {
        const key = keyFn(item);
        map.set(key, [...(map.get(key) || []), item]);
        return map;
      }, new Map());
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

    function idSegment(value) {
      return Array.from(String(value || "")).map((char) => char.charCodeAt(0).toString(36)).join("-");
    }

    function industryId(industry) {
      return `industry-${idSegment(industry)}`;
    }

    function depthId(industry, depth) {
      return `${industryId(industry)}-depth-${idSegment(depth)}`;
    }

    function semiconductorDepthEntries() {
      const semiconductorMetrics = DASHBOARD_DATA.metrics.filter((metric) => metric.industry === "반도체");
      return [...groupMetrics(semiconductorMetrics, (metric) => metric.depth || "전체 업황").entries()]
        .sort(([a], [b]) => depthRank(a) - depthRank(b) || String(a).localeCompare(String(b), "ko"))
        .filter(([depth, items]) => depth !== "전체 업황" && items.length);
    }

    function setActiveIndustry(industry, depth = "") {
      if (!industry) return;
      state.activeIndustry = industry;
      state.activeDepth = depth || "";
      document.querySelectorAll("[data-industry]").forEach((button) => {
        const active = button.dataset.industry === industry;
        button.setAttribute("aria-pressed", String(active));
        button.setAttribute("aria-current", String(active && !state.activeDepth));
      });
      document.querySelectorAll("[data-menu-depth]").forEach((button) => {
        const active = button.dataset.depthIndustry === industry && button.dataset.depthName === state.activeDepth;
        button.setAttribute("aria-pressed", String(active));
        button.setAttribute("aria-current", String(active));
      });
    }

    function renderMenuDepths(industry) {
      if (industry !== "반도체") return "";
      const depthItems = semiconductorDepthEntries().map(([depth, items]) => `
        <div class="menu-depth-item">
          <button type="button" class="menu-depth-button" data-menu-depth data-depth-industry="${escapeHtml(industry)}" data-depth-name="${escapeHtml(depth)}" data-target="${depthId(industry, depth)}" aria-pressed="${state.activeIndustry === industry && state.activeDepth === depth}" aria-current="${state.activeIndustry === industry && state.activeDepth === depth}" ${state.isReordering ? 'tabindex="-1"' : ""}>
            ${escapeHtml(localizedDepth(depth, items))}
          </button>
        </div>
      `).join("");
      return depthItems ? `<div class="menu-depth-list">${depthItems}</div>` : "";
    }

    function setBranchLine(container, markerSelector, topProperty, heightProperty, branchHeight, endInset = 0, startOvershoot = 0) {
      const markers = [...container.querySelectorAll(markerSelector)];
      if (!markers.length) return;
      const containerBox = container.getBoundingClientRect();
      const firstBox = markers[0].getBoundingClientRect();
      const lastBox = markers[markers.length - 1].getBoundingClientRect();
      const top = firstBox.top - containerBox.top + firstBox.height / 2 - branchHeight - startOvershoot;
      const end = lastBox.top - containerBox.top + lastBox.height / 2 - endInset;
      const topPx = Math.max(0, Math.round(top));
      const endPx = Math.max(topPx, Math.round(end));
      container.style.setProperty(topProperty, `${topPx}px`);
      container.style.setProperty(heightProperty, `${endPx - topPx}px`);
    }

    function updateBranchLines() {
      document.querySelectorAll(".depth-tree").forEach((tree) => {
        const cornerHeight = Number.parseFloat(getComputedStyle(tree).getPropertyValue("--depth-corner-height")) || 17;
        setBranchLine(tree, ".depth-title", "--depth-branch-top", "--depth-branch-height", cornerHeight, cornerHeight);
      });
    }

    function scheduleBranchLineUpdate() {
      requestAnimationFrame(updateBranchLines);
    }

    function renderFilters() {
      const industries = visibleIndustries();
      if (!state.activeIndustry && industries.length) {
        state.activeIndustry = industries[0];
      }
      document.getElementById("industryFilters").innerHTML = industries.map((industry) => `
        <div class="menu-item" data-menu-item data-industry-item="${escapeHtml(industry)}" draggable="${state.isReordering}">
          <button type="button" data-industry="${escapeHtml(industry)}" data-target="${industryId(industry)}" aria-pressed="${state.activeIndustry === industry}" aria-current="${state.activeIndustry === industry && !state.activeDepth}" ${state.isReordering ? 'tabindex="-1"' : ""}>
            ${escapeHtml(localizedIndustry(industry))}
          </button>
          ${renderMenuDepths(industry)}
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
      document.querySelectorAll("[data-menu-depth]").forEach((button) => {
        button.addEventListener("click", () => {
          if (state.isReordering) return;
          const industry = button.dataset.depthIndustry;
          const depth = button.dataset.depthName;
          const target = document.getElementById(button.dataset.target);
          if (!industry || !depth || !target) return;
          setActiveIndustry(industry, depth);
          target.scrollIntoView({ behavior: "smooth", block: "start" });
          closeDrawerOnMobile();
        });
      });
      initMenuDrag();
      initMenuScrollDrag();
      scheduleBranchLineUpdate();
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

    function monthLabel(month) {
      const monthNumber = Number(month);
      if (!Number.isFinite(monthNumber)) return "";
      if (state.language === "en") {
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        return monthNames[Math.max(0, Math.min(11, monthNumber - 1))] || String(monthNumber);
      }
      return `${monthNumber}월`;
    }

    function chartDateParts(dateText) {
      const match = String(dateText || "").match(/^(\\d{4})-(\\d{1,2})/);
      if (!match) return null;
      const year = Number(match[1]);
      const month = Number(match[2]);
      if (!Number.isFinite(year) || !Number.isFinite(month)) return null;
      return { year, month };
    }

    function chartPointDateLabel(dateText) {
      const date = chartDateParts(dateText);
      if (!date) return dateText || "";
      if (state.language === "en") {
        return `${monthLabel(date.month)} ${date.year}`;
      }
      return `${String(date.year).slice(2)}년 ${date.month}월`;
    }

    function detailTickLabel(point, seenYears) {
      const date = chartDateParts(point.date);
      if (!date) return "";
      if (!seenYears.has(date.year)) {
        seenYears.add(date.year);
        return yearLabel(point.date);
      }
      if ([3, 6, 9].includes(date.month)) {
        return monthLabel(date.month);
      }
      return "";
    }

    function chartTicks(history, left, right, includeQuarterMonths = false, xForPoint = null) {
      const seen = new Set();
      const seenYears = new Set();
      const ticks = [];
      history.forEach((point, index) => {
        const yearText = yearLabel(point.date);
        const label = includeQuarterMonths
          ? detailTickLabel(point, seenYears)
          : yearText;
        if (!label) return;
        const key = includeQuarterMonths ? `${point.date}-${label}` : String(point.date).slice(0, 4);
        if (seen.has(key)) return;
        seen.add(key);
        const x = xForPoint
          ? xForPoint(point, index)
          : left + (index / Math.max(history.length - 1, 1)) * (right - left);
        ticks.push({ label, x, priority: label === yearText ? 2 : 1 });
      });
      if (ticks.length === 1 && history.length > 1) {
        ticks.push({ label: yearLabel(history[history.length - 1].date), x: right, priority: 2 });
      }
      return compactChartTicks(
        ticks.filter((tick, index) => index === 0 || tick.label !== ticks[index - 1].label),
        includeQuarterMonths ? 46 : 54
      );
    }

    function compactChartTicks(ticks, minGap) {
      const kept = [];
      ticks.forEach((tick) => {
        const previous = kept[kept.length - 1];
        if (!previous || tick.x - previous.x >= minGap) {
          kept.push(tick);
          return;
        }
        if ((tick.priority || 0) > (previous.priority || 0)) {
          kept[kept.length - 1] = tick;
        }
      });
      return kept;
    }

    function separatedLabelPositions(levels, minY, maxY, minGap = 11) {
      const sorted = [...levels]
        .sort((a, b) => a.y - b.y)
        .map((level) => ({ ...level, preferredY: Math.min(maxY, Math.max(minY, level.y)) }));
      if (sorted.length <= 1) {
        return sorted.map((level) => ({ ...level, labelY: level.preferredY }));
      }

      const availableGap = (maxY - minY) / Math.max(sorted.length - 1, 1);
      const gap = Math.min(minGap, availableGap);
      const groups = sorted.map((_, index) => ({ start: index, end: index }));
      const positions = new Array(sorted.length);

      const layoutGroups = () => {
        groups.forEach((group) => {
          const count = group.end - group.start + 1;
          let startSum = 0;
          for (let index = group.start; index <= group.end; index += 1) {
            startSum += sorted[index].preferredY - (index - group.start) * gap;
          }
          const rawStart = startSum / count;
          const minStart = minY;
          const maxStart = maxY - (count - 1) * gap;
          const start = Math.min(maxStart, Math.max(minStart, rawStart));
          for (let index = group.start; index <= group.end; index += 1) {
            positions[index] = start + (index - group.start) * gap;
          }
        });
      };

      for (let pass = 0; pass < sorted.length; pass += 1) {
        layoutGroups();
        const mergeIndex = groups.findIndex((group, index) => {
          const next = groups[index + 1];
          return next && positions[next.start] - positions[group.end] < gap - 0.01;
        });
        if (mergeIndex === -1) break;
        const current = groups[mergeIndex];
        const next = groups[mergeIndex + 1];
        groups.splice(mergeIndex, 2, { start: current.start, end: next.end });
      }
      layoutGroups();

      return sorted.map((level, index) => ({
        ...level,
        labelY: Math.min(maxY, Math.max(minY, positions[index]))
      }));
    }

    function chartTimeValue(point) {
      const match = String(point?.date || "").match(/^(\\d{4})-(\\d{1,2})(?:-(\\d{1,2}))?/);
      if (!match) return null;
      const year = Number(match[1]);
      const month = Number(match[2]);
      const day = match[3] ? Number(match[3]) : 1;
      if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null;
      return Date.UTC(year, month - 1, day);
    }

    function chartMonthSpan(points) {
      if (!Array.isArray(points) || points.length < 2) return 0;
      const first = chartDateParts(points[0].date);
      const last = chartDateParts(points[points.length - 1].date);
      if (!first || !last) return 0;
      return Math.max(0, (last.year - first.year) * 12 + (last.month - first.month));
    }

    function chartTimeBounds(points) {
      const times = (points || [])
        .map(chartTimeValue)
        .filter((value) => typeof value === "number" && Number.isFinite(value));
      if (times.length < 2) return null;
      const min = Math.min(...times);
      const max = Math.max(...times);
      return max > min ? { min, max } : null;
    }

    function chartXScale(points, left, right) {
      const bounds = chartTimeBounds(points);
      if (!bounds) {
        return (point, index) => left + (index / Math.max(points.length - 1, 1)) * (right - left);
      }
      return (point, index) => {
        const time = chartTimeValue(point);
        if (typeof time !== "number" || !Number.isFinite(time)) {
          return left + (index / Math.max(points.length - 1, 1)) * (right - left);
        }
        const ratio = Math.min(1, Math.max(0, (time - bounds.min) / (bounds.max - bounds.min)));
        return left + ratio * (right - left);
      };
    }

    function detailChartAvailableWidth() {
      const containerWidth = document.getElementById("industryStack")?.clientWidth
        || document.querySelector(".content")?.clientWidth
        || window.innerWidth
        || 520;
      const axisWidth = mobileDrawerQuery.matches ? 40 : 42;
      const minimum = mobileDrawerQuery.matches ? 360 : 520;
      return Math.max(minimum, Math.floor(containerWidth - axisWidth));
    }

    function detailChartWidth(points) {
      const count = Array.isArray(points) ? points.length : 0;
      const perPointWidth = mobileDrawerQuery.matches ? 18 : 22;
      const perMonthWidth = mobileDrawerQuery.matches ? 11 : 14;
      const monthSpan = chartMonthSpan(points);
      const width = Math.max(
        detailChartAvailableWidth(),
        count * perPointWidth,
        monthSpan > 0 ? (monthSpan + 1) * perMonthWidth : 0
      );
      return Math.min(4200, width);
    }

    function detailChartUnit(metric) {
      const scale = state.currency === "krw" ? dollarUnitScale(metric || {}) : null;
      return scale ? scale.unit : localizedUnit(metric || {});
    }

    function detailPointValueLabel(value, unit) {
      return formatMetricNumberWithUnit(value, unit);
    }

    function detailPointChangeLabel(point, previous, unit) {
      if (!previous || typeof point.value !== "number" || typeof previous.value !== "number") return "n/a";
      if (!Number.isFinite(point.value) || !Number.isFinite(previous.value)) return "n/a";
      const absolute = point.value - previous.value;
      const pct = previous.value === 0 ? null : (absolute / Math.abs(previous.value)) * 100;
      const absoluteLabel = formatMetricNumberWithUnit(absolute, unit, true, true);
      const pctLabel = typeof pct === "number" && Number.isFinite(pct) ? `${numberText(pct, true)}%` : "n/a";
      return `${absoluteLabel} / ${pctLabel}`;
    }

    function detailChart(history, metric = null) {
      const displayPoints = displayHistory(history, metric);
      const svgWidth = detailChartWidth(displayPoints);
      const chartStyle = ` style="--detail-chart-width: ${svgWidth}px"`;
      const axisClass = "chart detail-chart-axis";
      const plotClass = "chart chart-detail";
      const isMobileChart = mobileDrawerQuery.matches;
      const chartHeight = isMobileChart ? 158 : 190;
      const axisWidth = isMobileChart ? 40 : 42;
      const axisGuideStart = axisWidth - 2;
      const left = 1;
      const right = svgWidth - 1;
      const top = isMobileChart ? 12 : 18;
      const axisY = chartHeight - 32;
      const bottom = axisY - 12;
      const labelBottom = chartHeight - 12;
      const levelMinY = top - 2;
      const levelMaxY = bottom + 2;
      const emptyPlot = `<svg class="${plotClass}"${chartStyle} viewBox="0 0 ${svgWidth} ${chartHeight}" preserveAspectRatio="none" role="img" aria-label="trend unavailable">
        <line x1="${left}" y1="${(top + bottom) / 2}" x2="${right}" y2="${(top + bottom) / 2}" class="guide"></line>
      </svg>`;
      if (!displayPoints || displayPoints.length < 2) {
        return `<div class="detail-chart">
          <svg class="${axisClass}" viewBox="0 0 ${axisWidth} ${chartHeight}" preserveAspectRatio="none" aria-hidden="true"></svg>
          <div class="detail-chart-scroll">${emptyPlot}</div>
        </div>`;
      }
      const values = displayPoints.map((point) => point.value).filter((value) => typeof value === "number" && Number.isFinite(value));
      if (values.length < 2) {
        return `<div class="detail-chart">
          <svg class="${axisClass}" viewBox="0 0 ${axisWidth} ${chartHeight}" preserveAspectRatio="none" aria-hidden="true"></svg>
          <div class="detail-chart-scroll">${emptyPlot}</div>
        </div>`;
      }
      const min = Math.min(...values);
      const max = Math.max(...values);
      const latest = displayPoints[displayPoints.length - 1].value;
      const first = displayPoints[0].value;
      const span = max - min || 1;
      const yFor = (value) => bottom - ((value - min) / span) * (bottom - top);
      const xFor = chartXScale(displayPoints, left, right);
      const points = displayPoints.map((point, index) => {
        const x = xFor(point, index);
        const y = yFor(point.value);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      const trend = latest >= first ? "up" : "down";
      const levelEntries = [];
      [
        { value: max, type: "max" },
        { value: latest, type: "current" },
        { value: min, type: "min" }
      ].forEach((candidate) => {
        const existing = levelEntries.find((entry) => Math.abs(entry.value - candidate.value) < 1e-9);
        if (existing) {
          existing.types.push(candidate.type);
        } else {
          levelEntries.push({ value: candidate.value, types: [candidate.type] });
        }
      });
      const levels = separatedLabelPositions(
        levelEntries.map((entry) => ({
          value: entry.value,
          label: formatAxisValue(entry.value),
          y: yFor(entry.value),
          className: entry.types.map((type) => `level-${type}`).join(" ")
        })),
        levelMinY,
        levelMaxY
      );
      const yAxis = levels.map((level) => {
        const labelY = level.labelY;
        return `<g>
          <text class="${level.className}" x="${axisGuideStart.toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="end" dominant-baseline="middle">${level.label}</text>
        </g>`;
      }).join("");
      const ticks = chartTicks(displayPoints, left, right, true, xFor);
      const yBackgroundLines = levels.map((level) => `
        <line x1="${left}" y1="${level.y.toFixed(1)}" x2="${right}" y2="${level.y.toFixed(1)}" class="chart-background-line level-line ${level.className}"></line>
      `).join("");
      const xBackgroundLines = ticks.map((tick) => `
        <line x1="${tick.x.toFixed(1)}" y1="${top}" x2="${tick.x.toFixed(1)}" y2="${axisY}" class="chart-background-line"></line>
      `).join("");
      const xGuides = ticks.map((tick) => {
        const anchor = tick.x <= left + 2 ? "start" : tick.x >= right - 2 ? "end" : "middle";
        return `<text x="${tick.x.toFixed(1)}" y="${labelBottom}" text-anchor="${anchor}">${tick.label}</text>`;
      }).join("");
      const tooltipUnit = detailChartUnit(metric || {});
      const pointHits = displayPoints.map((point, index) => {
        const x = xFor(point, index);
        const y = yFor(point.value);
        const previous = index > 0 ? displayPoints[index - 1] : null;
        return `<circle class="detail-point-hit" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="10" fill="transparent" stroke="transparent" tabindex="0"
          data-tooltip-title="${escapeHtml(localizedField(metric, "name"))}"
          data-tooltip-date="${escapeHtml(chartPointDateLabel(point.date))}"
          data-tooltip-value="${escapeHtml(detailPointValueLabel(point.value, tooltipUnit))}"
          data-tooltip-change="${escapeHtml(detailPointChangeLabel(point, previous, tooltipUnit))}"></circle>`;
      }).join("");
      const latestX = xFor(displayPoints[displayPoints.length - 1], displayPoints.length - 1);
      const latestY = yFor(latest);
      return `<div class="detail-chart">
        <svg class="${axisClass}" viewBox="0 0 ${axisWidth} ${chartHeight}" preserveAspectRatio="none" aria-hidden="true">
          ${yAxis}
          <line x1="${axisGuideStart}" y1="${axisY}" x2="${axisWidth}" y2="${axisY}" class="axis-line"></line>
        </svg>
        <div class="detail-chart-scroll">
          <svg class="${plotClass}"${chartStyle} viewBox="0 0 ${svgWidth} ${chartHeight}" preserveAspectRatio="none" role="img" aria-label="trend">
            ${yBackgroundLines}
            ${xBackgroundLines}
            <line x1="${left}" y1="${axisY}" x2="${right}" y2="${axisY}" class="axis-line"></line>
            ${xGuides}
            <polyline points="${points}" class="trend-line ${trend}"></polyline>
            <circle cx="${latestX}" cy="${latestY.toFixed(1)}" r="4" class="current-dot ${trend}"></circle>
            ${pointHits}
          </svg>
        </div>
        <div class="detail-chart-tooltip" role="status" aria-live="polite"></div>
      </div>`;
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
      const xFor = isDetailChart ? chartXScale(displayPoints, left, right) : null;
      const points = displayPoints.map((point, index) => {
        const x = xFor
          ? xFor(point, index)
          : left + (index / Math.max(displayPoints.length - 1, 1)) * (right - left);
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
          <text x="8" y="${labelY.toFixed(1)}" dominant-baseline="middle">${level.label}</text>
          ${connector}
          <line x1="${left}" y1="${y.toFixed(1)}" x2="${right}" y2="${y.toFixed(1)}" class="guide"></line>
        </g>`;
      }).join("");
      const xGuides = chartTicks(displayPoints, left, right, isDetailChart, xFor).map((tick) => `
        <text x="${tick.x.toFixed(1)}" y="146" text-anchor="middle">${tick.label}</text>
      `).join("");
      const latestX = xFor
        ? xFor(displayPoints[displayPoints.length - 1], displayPoints.length - 1)
        : right;
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

    function metricStatusMarkup(metric) {
      if (metric?.daily_status === "new") {
        return `<span class="metric-new-badge">${escapeHtml(t("newBadge"))}</span>`;
      }
      if (metric?.daily_status === "updated") {
        return `<span class="metric-update-dot" aria-label="${escapeHtml(t("updatedBadge"))}" title="${escapeHtml(t("updatedBadge"))}"></span>`;
      }
      return "";
    }

    function metricById(metricId) {
      return (DASHBOARD_DATA.metrics || []).find((metric) => metric.id === metricId) || null;
    }

    function savedFavoriteMetricIds() {
      try {
        const parsed = JSON.parse(localStorage.getItem(favoriteMetricStorageKey) || "[]");
        if (!Array.isArray(parsed)) return [];
        const validIds = new Set((DASHBOARD_DATA.metrics || []).map((metric) => metric.id));
        return parsed.map(String).filter((id) => validIds.has(id));
      } catch (_error) {
        return [];
      }
    }

    function saveFavoriteMetricIds() {
      localStorage.setItem(favoriteMetricStorageKey, JSON.stringify([...state.favoriteMetricIds]));
    }

    function initFavoriteMetrics() {
      state.favoriteMetricIds = new Set(savedFavoriteMetricIds());
    }

    function isFavoriteMetric(metricId) {
      return state.favoriteMetricIds.has(metricId);
    }

    function favoriteButtonMarkup(metric) {
      const active = isFavoriteMetric(metric.id);
      const label = active ? t("removeFavorite") : t("addFavorite");
      return `<button class="metric-favorite-button${active ? " is-active" : ""}" type="button" data-favorite-toggle="${escapeHtml(metric.id)}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}" aria-pressed="${active ? "true" : "false"}">
        <i class="fa-${active ? "solid" : "regular"} fa-star" aria-hidden="true"></i>
      </button>`;
    }

    function toggleFavoriteMetric(metricId) {
      if (!metricById(metricId)) return;
      if (state.favoriteMetricIds.has(metricId)) {
        state.favoriteMetricIds.delete(metricId);
      } else {
        state.favoriteMetricIds.add(metricId);
      }
      saveFavoriteMetricIds();
      renderDailyUpdates();
      renderIndustries();
    }

    function initFavoriteButtons() {
      document.querySelectorAll("[data-favorite-toggle]").forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          toggleFavoriteMetric(button.dataset.favoriteToggle);
        });
      });
    }

    function metricDetail(metric) {
      return `<div class="metric-detail-panel">
        <div class="metric-detail-inner">
          ${detailChart(metric.history, metric)}
          <div class="detail-stats">
            ${detailStat(t("currentValue"), displayMetricValue(metric))}
            ${detailStat(t("previousChange"), displayMetricChange(metric), directionClass(metric.change_abs))}
            ${detailStat(t("previousChangePct"), metric.change_pct_label, directionClass(metric.change_pct))}
            ${detailStat(t("yoy"), metric.yoy_pct_label, directionClass(metric.yoy_pct))}
            ${detailStat(t("visiblePeriod"), metric.period_label || metric.observed_label || "")}
            ${detailStat(t("updateFrequency"), localizedField(metric, "frequency") || t("irregular"))}
          </div>
        </div>
      </div>`;
    }

    function metricRows(metric) {
      const detailId = `metric-detail-${metric.id}`;
      return `<tr class="metric-row" data-metric-row data-metric-id="${escapeHtml(metric.id)}" data-detail-id="${detailId}">
        <td class="metric-name-cell" data-label="${escapeHtml(t("metric"))}">
          <button class="metric-toggle" type="button" data-metric-toggle aria-expanded="false" aria-controls="${detailId}">
            <span class="metric-name-wrap">
              <span class="metric-name">${escapeHtml(localizedField(metric, "name"))}</span>
              ${metricStatusMarkup(metric)}
            </span>
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
        <td class="metric-favorite-cell" data-label="${escapeHtml(t("favoriteMetrics"))}">
          ${favoriteButtonMarkup(metric)}
        </td>
      </tr>
      <tr class="metric-detail-row" id="${detailId}" aria-hidden="true">
        <td colspan="7">${metricDetail(metric)}</td>
      </tr>`;
    }

    function changedMetrics() {
      return (DASHBOARD_DATA.metrics || []).filter((metric) =>
        metric.daily_status === "updated" || metric.daily_status === "new"
      );
    }

    function jumpToMetric(metricId) {
      const row = document.querySelector(`[data-metric-id="${metricId}"]`);
      if (!row) return;
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.classList.add("is-highlighted");
      window.setTimeout(() => row.classList.remove("is-highlighted"), 1400);
    }

    function initDailyUpdateLinks() {
      document.querySelectorAll("[data-daily-update-metric]").forEach((button) => {
        button.addEventListener("click", () => jumpToMetric(button.dataset.dailyUpdateMetric));
      });
      document.querySelectorAll("[data-briefing-metric]").forEach((button) => {
        button.addEventListener("click", () => jumpToMetric(button.dataset.briefingMetric));
      });
      document.querySelectorAll("[data-favorite-card]").forEach((button) => {
        button.addEventListener("click", () => jumpToMetric(button.dataset.favoriteCard));
        button.addEventListener("keydown", (event) => {
          if (event.target.closest("[data-favorite-toggle]")) return;
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          jumpToMetric(button.dataset.favoriteCard);
        });
      });
    }

    function briefingStatusLabel(briefing) {
      if (briefing?.status === "ok") return t("aiBriefing");
      return t("fallbackBriefing");
    }

    function aiSparkleIconMarkup() {
      return `<svg class="ai-sparkle-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <defs>
          <linearGradient id="aiSparkleGradient" x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
            <stop offset="0" stop-color="#3b82f6"></stop>
            <stop offset="0.52" stop-color="#5c6cff"></stop>
            <stop offset="1" stop-color="#6366f1"></stop>
          </linearGradient>
        </defs>
        <path d="M11.017 2.814C11.213 1.777 12.787 1.777 12.983 2.814L14.034 8.372C14.189 9.189 14.811 9.811 15.628 9.966L21.186 11.017C22.223 11.213 22.223 12.787 21.186 12.983L15.628 14.034C14.811 14.189 14.189 14.811 14.034 15.628L12.983 21.186C12.787 22.223 11.213 22.223 11.017 21.186L9.966 15.628C9.811 14.811 9.189 14.189 8.372 14.034L2.814 12.983C1.777 12.787 1.777 11.213 2.814 11.017L8.372 9.966C9.189 9.811 9.811 9.189 9.966 8.372Z"></path>
      </svg>`;
    }

    function briefingBulletMarkup(item) {
      const metricIds = Array.isArray(item?.metric_ids) ? item.metric_ids.filter(Boolean) : [];
      const content = `<span class="briefing-bullet-title">${escapeHtml(item?.title || "")}</span>
        <span class="briefing-bullet-body">${escapeHtml(item?.body || "")}</span>`;
      if (metricIds.length) {
        return `<li class="briefing-bullet"><button class="briefing-bullet-button" type="button" data-briefing-metric="${escapeHtml(metricIds[0])}">${content}</button></li>`;
      }
      return `<li class="briefing-bullet"><span class="briefing-bullet-static">${content}</span></li>`;
    }

    function renderMorningBriefing() {
      const briefing = DASHBOARD_DATA.morning_briefing || {};
      if (!briefing.headline && !briefing.summary) return "";
      const bullets = Array.isArray(briefing.bullets) ? briefing.bullets : [];
      return `<section class="morning-briefing">
        <div class="morning-briefing-head">
          <div class="briefing-title">
            ${aiSparkleIconMarkup()}
            <h2>${escapeHtml(t("morningBriefing"))}</h2>
          </div>
        </div>
        <p class="briefing-headline">${escapeHtml(briefing.headline || "")}</p>
        ${briefing.summary ? `<p class="briefing-summary">${escapeHtml(briefing.summary)}</p>` : ""}
        ${bullets.length ? `<ul class="briefing-bullets">${bullets.map(briefingBulletMarkup).join("")}</ul>` : ""}
        <p class="briefing-disclaimer">
          <span class="briefing-disclaimer-icon" aria-hidden="true"><i class="fa-solid fa-info"></i></span>
          <span>${escapeHtml(t("briefingDisclaimer"))}</span>
        </p>
      </section>`;
    }

    function favoriteMetrics() {
      return (DASHBOARD_DATA.metrics || []).filter((metric) => state.favoriteMetricIds.has(metric.id));
    }

    function favoriteMetricCard(metric) {
      return `<div class="favorite-card" role="button" tabindex="0" data-favorite-card="${escapeHtml(metric.id)}">
        <button class="favorite-card-star" type="button" data-favorite-toggle="${escapeHtml(metric.id)}" aria-label="${escapeHtml(t("removeFavorite"))}" title="${escapeHtml(t("removeFavorite"))}">
          <i class="fa-solid fa-star" aria-hidden="true"></i>
        </button>
        <span class="favorite-card-top">
          <span class="favorite-card-meta">${escapeHtml(localizedIndustry(metric.industry))} · ${escapeHtml(localizedGroup(metric.group, [metric]))}</span>
          <span class="favorite-card-title">${escapeHtml(localizedField(metric, "name"))}</span>
          <span class="favorite-card-value">${escapeHtml(displayMetricValue(metric))}</span>
        </span>
        <span class="favorite-card-chart">${chart(metric.history, "chart-mini", metric)}</span>
      </div>`;
    }

    function renderFavoriteMetrics() {
      const metrics = favoriteMetrics();
      if (!metrics.length) return "";
      return `<section class="favorite-metrics">
        <div class="favorite-metrics-head">
          <h2>${escapeHtml(t("favoriteMetrics"))}</h2>
          <span class="favorite-metrics-count">${metrics.length}${state.language === "ko" ? "" : " "}${escapeHtml(t("favoriteCount"))}</span>
        </div>
        <div class="favorite-metrics-grid">${metrics.map(favoriteMetricCard).join("")}</div>
      </section>`;
    }

    function renderDailyUpdates() {
      const section = document.getElementById("dailyUpdates");
      if (!section) return;
      const summary = DASHBOARD_DATA.daily_changes || {};
      const changes = changedMetrics();
      const updatedCount = Number(summary.updated_count || changes.filter((metric) => metric.daily_status === "updated").length);
      const newCount = Number(summary.new_count || changes.filter((metric) => metric.daily_status === "new").length);
      const rows = changes.map((metric) => `
        <button class="daily-update-row" type="button" data-daily-update-metric="${escapeHtml(metric.id)}">
          <span class="daily-update-main">
            ${metricStatusMarkup(metric)}
            <span class="daily-update-title">${escapeHtml(localizedField(metric, "name"))}</span>
          </span>
          <span class="daily-update-meta">${escapeHtml(localizedIndustry(metric.industry))} · ${escapeHtml(localizedGroup(metric.group, [metric]))} · ${escapeHtml(dateText(metric.observed_label))}</span>
          <span class="daily-update-value">${escapeHtml(displayMetricValue(metric))}</span>
          <span class="daily-update-change ${directionClass(metric.change_pct)}">
            <i class="fa-solid ${trendIconClass(metric.change_pct)}" aria-hidden="true"></i>
            <span class="daily-update-change-abs">${escapeHtml(displayMetricChange(metric) || "n/a")}</span>
            <span class="daily-update-change-pct">${escapeHtml(metric.change_pct_label || "n/a")}</span>
          </span>
        </button>
      `).join("");
      section.innerHTML = `${renderMorningBriefing()}<details class="daily-update-details">
        <summary class="daily-update-summary">
          <span>${escapeHtml(t("showDailyChanges"))}</span>
          <span class="daily-update-summary-icon" aria-hidden="true">›</span>
        </summary>
        <div class="daily-update-panel">
          <div class="daily-update-list">
            ${rows || `<div class="daily-update-empty">${escapeHtml(t("noDailyChanges"))}</div>`}
          </div>
          <div class="daily-update-counts" aria-label="${escapeHtml(t("todayChanges"))}">
            <span class="daily-update-count">${escapeHtml(t("updatedCount"))} ${updatedCount}</span>
            <span class="daily-update-count">${escapeHtml(t("newCount"))} ${newCount}</span>
          </div>
        </div>
      </details>${renderFavoriteMetrics()}`;
      initDailyUpdateLinks();
    }

    function renderIndustry(industry, metrics) {
      const icon = DASHBOARD_DATA.industry_icons?.[industry] || "";
      const renderGroups = (items, hiddenGroup = "") => [...groupMetrics(items, (metric) => metric.group || "핵심 지표").entries()]
        .sort(([a], [b]) => groupRank(a) - groupRank(b) || String(a).localeCompare(String(b), "ko"))
        .map(([group, items]) => {
          const groupTitle = group === hiddenGroup ? "" : `<div class="group-title">${escapeHtml(localizedGroup(group, items))}</div>`;
          return `
            <section class="group">
            ${groupTitle}
            <div class="metric-table-wrap">
              <table class="metric-table">
                <colgroup>
                  <col class="metric-name-cell">
                  <col class="metric-description-cell">
                  <col class="metric-date-cell">
                  <col class="metric-date-cell">
                  <col class="metric-value-cell">
                  <col class="metric-chart-cell">
                  <col class="metric-favorite-cell">
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col" data-mobile-label="${escapeHtml(t("metricSummary"))}">${escapeHtml(t("metric"))}</th>
                    <th scope="col">${escapeHtml(t("description"))}</th>
                    <th scope="col">${escapeHtml(t("lastUpdated"))}</th>
                    <th scope="col">${escapeHtml(t("nextUpdate"))}</th>
                    <th scope="col" data-mobile-label="${escapeHtml(t("metricValueShort"))}">${escapeHtml(t("currentValue"))}</th>
                    <th scope="col" data-mobile-label="${escapeHtml(t("chart"))}">${escapeHtml(t("chart"))}</th>
                    <th scope="col"><span class="sr-only">${escapeHtml(t("favoriteMetrics"))}</span></th>
                  </tr>
                </thead>
                <tbody>${items.map(metricRows).join("")}</tbody>
              </table>
            </div>
          </section>
        `;
        }).join("");
      const semiconductorGroups = industry === "반도체"
        ? [...groupMetrics(metrics, (metric) => metric.depth || "전체 업황").entries()]
            .sort(([a], [b]) => depthRank(a) - depthRank(b) || String(a).localeCompare(String(b), "ko"))
        : [];
      const renderDepthSection = ([depth, items]) => `
        <section class="depth-section" id="${depthId(industry, depth)}" data-depth-section data-depth-name="${escapeHtml(depth)}">
          <div class="depth-title">${escapeHtml(localizedDepth(depth, items))}</div>
          ${renderGroups(items, depth)}
        </section>
      `;
      const groupHtml = industry === "반도체"
        ? [
            ...semiconductorGroups
              .filter(([depth]) => depth === "전체 업황")
              .map(([, items]) => renderGroups(items)),
            (() => {
              const depthHtml = semiconductorGroups
                .filter(([depth]) => depth !== "전체 업황")
                .map(renderDepthSection)
                .join("");
              return depthHtml ? `<div class="depth-tree">${depthHtml}</div>` : "";
            })()
          ].join("")
        : renderGroups(metrics);

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
      scheduleBranchLineUpdate();
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
        const scroller = detail.querySelector(".detail-chart-scroll");
        if (scroller) {
          requestAnimationFrame(() => {
            scroller.scrollLeft = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
          });
        }
      }
      scheduleBranchLineUpdate();
    }

    function tooltipMarkup(point) {
      return `<div class="detail-tooltip-title">${escapeHtml(point.dataset.tooltipTitle || "")}</div>
        <div class="detail-tooltip-row">
          <span class="detail-tooltip-label">${escapeHtml(t("tooltipPeriod"))}</span>
          <span class="detail-tooltip-value">${escapeHtml(point.dataset.tooltipDate || "")}</span>
        </div>
        <div class="detail-tooltip-row">
          <span class="detail-tooltip-label">${escapeHtml(t("tooltipValue"))}</span>
          <span class="detail-tooltip-value">${escapeHtml(point.dataset.tooltipValue || "")}</span>
        </div>
        <div class="detail-tooltip-row">
          <span class="detail-tooltip-label">${escapeHtml(t("tooltipChange"))}</span>
          <span class="detail-tooltip-value">${escapeHtml(point.dataset.tooltipChange || "")}</span>
        </div>`;
    }

    function showDetailTooltip(point, pinned = false) {
      const chart = point.closest(".detail-chart");
      const tooltip = chart?.querySelector(".detail-chart-tooltip");
      if (!chart || !tooltip) return;
      chart.dataset.tooltipPinned = pinned ? "true" : "false";
      tooltip.innerHTML = tooltipMarkup(point);
      tooltip.classList.add("is-visible");
      const chartRect = chart.getBoundingClientRect();
      const pointRect = point.getBoundingClientRect();
      const rawLeft = pointRect.left + pointRect.width / 2 - chartRect.left;
      const rawTop = pointRect.top - chartRect.top;
      const tooltipWidth = tooltip.offsetWidth || 180;
      const tooltipHeight = tooltip.offsetHeight || 80;
      const left = Math.min(Math.max(rawLeft, tooltipWidth / 2 + 4), chartRect.width - tooltipWidth / 2 - 4);
      const top = Math.min(Math.max(rawTop + 4, 4), Math.max(4, chartRect.height - tooltipHeight - 16));
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    }

    function hideDetailTooltip(chart, force = false) {
      if (!chart) return;
      if (!force && chart.dataset.tooltipPinned === "true") return;
      chart.dataset.tooltipPinned = "false";
      const tooltip = chart.querySelector(".detail-chart-tooltip");
      tooltip?.classList.remove("is-visible");
    }

    function initDetailChartTooltips() {
      document.querySelectorAll(".detail-point-hit").forEach((point) => {
        point.addEventListener("mouseenter", () => showDetailTooltip(point, false));
        point.addEventListener("focus", () => showDetailTooltip(point, false));
        point.addEventListener("click", (event) => {
          event.stopPropagation();
          showDetailTooltip(point, true);
        });
        point.addEventListener("mouseleave", () => hideDetailTooltip(point.closest(".detail-chart")));
        point.addEventListener("blur", () => hideDetailTooltip(point.closest(".detail-chart")));
      });
      document.querySelectorAll(".detail-chart-scroll").forEach((scroller) => {
        scroller.addEventListener("scroll", () => hideDetailTooltip(scroller.closest(".detail-chart"), true), { passive: true });
      });
    }

    function initMetricRows() {
      document.querySelectorAll("[data-metric-row]").forEach((row) => {
        row.addEventListener("click", () => toggleMetricRow(row));
      });
      initFavoriteButtons();
      initDetailChartTooltips();
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

    function initMenuScrollDrag() {
      const menu = document.getElementById("industryFilters");
      if (!menu || menu.dataset.scrollDragReady === "true") return;
      menu.dataset.scrollDragReady = "true";
      let dragState = null;

      menu.addEventListener("pointerdown", (event) => {
        if (state.isReordering || event.button !== 0 || menu.scrollHeight <= menu.clientHeight) return;
        dragState = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          startScrollTop: menu.scrollTop,
          moved: false,
          captured: false
        };
      });

      menu.addEventListener("pointermove", (event) => {
        if (!dragState || dragState.pointerId !== event.pointerId || state.isReordering) return;
        const deltaX = event.clientX - dragState.startX;
        const deltaY = event.clientY - dragState.startY;
        const dragThreshold = event.pointerType === "touch" ? 12 : 7;
        if (Math.abs(deltaY) > dragThreshold && Math.abs(deltaY) > Math.abs(deltaX)) {
          const maxScrollTop = Math.max(0, menu.scrollHeight - menu.clientHeight);
          const nextScrollTop = Math.min(maxScrollTop, Math.max(0, dragState.startScrollTop - deltaY));
          dragState.moved = true;
          suppressMenuClick = true;
          menu.classList.add("is-drag-scrolling");
          if (!dragState.captured) {
            menu.setPointerCapture?.(event.pointerId);
            dragState.captured = true;
          }
          menu.scrollTop = nextScrollTop;
          event.preventDefault();
        }
      });

      const stopDrag = (event) => {
        if (!dragState || dragState.pointerId !== event.pointerId) return;
        if (dragState.moved) {
          window.setTimeout(() => {
            suppressMenuClick = false;
          }, 80);
        }
        menu.classList.remove("is-drag-scrolling");
        if (dragState.captured) {
          menu.releasePointerCapture?.(event.pointerId);
        }
        dragState = null;
      };

      menu.addEventListener("pointerup", stopDrag);
      menu.addEventListener("pointercancel", stopDrag);
      menu.addEventListener("click", (event) => {
        if (!suppressMenuClick) return;
        event.preventDefault();
        event.stopPropagation();
        suppressMenuClick = false;
      }, true);
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

    function themeToggleLabelText(theme = null) {
      const selectedTheme = theme || (document.body.classList.contains("theme-dark") ? "dark" : "light");
      return selectedTheme === "dark" ? t("themeDarkName") : t("themeLightName");
    }

    function updateThemeToggleLabel() {
      const label = document.getElementById("themeToggleLabel");
      if (!label) return;
      label.textContent = themeToggleLabelText();
    }

    function animateToggleContent(toggle, outgoing, incoming, label, nextLabel, swapState) {
      if (!toggle) {
        swapState();
        return;
      }
      toggle.disabled = true;
      [outgoing, incoming, label].forEach((element) => {
        element?.classList.remove("is-exiting", "is-entering");
      });
      void toggle.offsetWidth;
      outgoing?.classList.add("is-exiting");
      label?.classList.add("is-exiting");
      window.setTimeout(() => {
        swapState();
        if (label) {
          label.textContent = nextLabel;
          label.classList.remove("is-exiting");
          label.classList.add("is-entering");
        }
        incoming?.classList.add("is-entering");
      }, 150);
      window.setTimeout(() => {
        [outgoing, incoming, label].forEach((element) => {
          element?.classList.remove("is-exiting", "is-entering");
        });
        toggle.disabled = false;
      }, 470);
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
      document.getElementById("scrollTopButton")?.setAttribute("aria-label", t("scrollTop"));
      document.getElementById("scrollTopButton")?.setAttribute("title", t("scrollTop"));
      document.getElementById("themeToggle")?.setAttribute("aria-label", t("toggleTheme"));
      document.getElementById("themeToggle")?.setAttribute("title", t("toggleTheme"));
      const languageLabel = document.getElementById("languageSettingLabel");
      if (languageLabel) languageLabel.textContent = state.language === "ko" ? "KO" : "EN";
      updateThemeSettingLabel();
      updateThemeToggleLabel();
      updateCurrencyButton();
    }

    function setLanguage(language) {
      state.language = language === "en" ? "en" : "ko";
      localStorage.setItem("dashboard-language", state.language);
      updateLanguageText();
      renderFilters();
      renderDailyUpdates();
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

    function applyTheme(theme, options = {}) {
      const isDark = theme === "dark";
      document.body.classList.toggle("theme-dark", isDark);
      localStorage.setItem("dashboard-theme", isDark ? "dark" : "light");
      updateThemeSettingLabel();
      if (options.updateToggleLabel !== false) updateThemeToggleLabel();
    }

    function animateThemeToggle(nextTheme) {
      const toggle = document.getElementById("themeToggle");
      const isDark = document.body.classList.contains("theme-dark");
      const outgoing = toggle.querySelector(isDark ? ".theme-icon-moon" : ".theme-icon-sun");
      const incoming = toggle.querySelector(isDark ? ".theme-icon-sun" : ".theme-icon-moon");
      const label = document.getElementById("themeToggleLabel");
      animateToggleContent(toggle, outgoing, incoming, label, themeToggleLabelText(nextTheme), () => {
        applyTheme(nextTheme, { updateToggleLabel: false });
      });
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

    function currencyToggleLabelText(currency = state.currency) {
      return currency === "krw" ? t("currencyKrwName") : t("currencyUsdName");
    }

    function updateCurrencyButton(options = {}) {
      const toggle = document.getElementById("currencyToggle");
      if (!toggle) return;
      const isKrw = state.currency === "krw";
      toggle.setAttribute("aria-label", isKrw ? t("showUsd") : t("showKrw"));
      toggle.setAttribute("title", isKrw ? t("showUsd") : t("showKrw"));
      const label = document.getElementById("currencyToggleLabel");
      if (label && options.updateLabel !== false) label.textContent = currencyToggleLabelText();
    }

    function applyCurrency(currency, options = {}) {
      state.currency = currency === "krw" ? "krw" : "usd";
      document.body.classList.toggle("currency-krw", state.currency === "krw");
      document.body.classList.toggle("currency-usd", state.currency === "usd");
      localStorage.setItem("dashboard-currency", state.currency);
      updateCurrencyButton(options);
    }

    function animateCurrencyToggle(nextCurrency) {
      const toggle = document.getElementById("currencyToggle");
      const isKrw = state.currency === "krw";
      const outgoing = toggle.querySelector(isKrw ? ".currency-icon-won" : ".currency-icon-dollar");
      const incoming = toggle.querySelector(isKrw ? ".currency-icon-dollar" : ".currency-icon-won");
      const label = document.getElementById("currencyToggleLabel");
      animateToggleContent(toggle, outgoing, incoming, label, currencyToggleLabelText(nextCurrency), () => {
        applyCurrency(nextCurrency, { updateLabel: false });
        renderDailyUpdates();
        renderIndustries();
      });
    }

    function initCurrency() {
      applyCurrency(localStorage.getItem("dashboard-currency") === "krw" ? "krw" : "usd");
      document.getElementById("currencyToggle").addEventListener("click", () => {
        animateCurrencyToggle(state.currency === "usd" ? "krw" : "usd");
      });
    }

    function initScrollTopButton() {
      document.getElementById("scrollTopButton")?.addEventListener("click", () => {
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
      updateScrollTopButtonVisibility();
    }

    function updateScrollTopButtonVisibility() {
      const revealAt = Math.max(280, window.innerHeight * 0.35);
      document.body.classList.toggle("show-scroll-top", window.scrollY > revealAt);
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
      let currentDepth = "";
      if (current.dataset.industryName === "반도체") {
        for (const section of current.querySelectorAll("[data-depth-section]")) {
          if (section.getBoundingClientRect().top <= anchor) {
            currentDepth = section.dataset.depthName || "";
          } else {
            break;
          }
        }
      }
      setActiveIndustry(current.dataset.industryName, currentDepth);
    }

    function onScrollSpy() {
      if (scrollSpyFrame) return;
      scrollSpyFrame = requestAnimationFrame(() => {
        scrollSpyFrame = 0;
        updateScrollTopButtonVisibility();
        updateActiveFromScroll();
      });
    }

    let resizeRenderFrame = 0;
    function onDashboardResize() {
      onScrollSpy();
      scheduleBranchLineUpdate();
      if (resizeRenderFrame) return;
      resizeRenderFrame = requestAnimationFrame(() => {
        resizeRenderFrame = 0;
        renderIndustries();
      });
    }

    window.addEventListener("scroll", onScrollSpy, { passive: true });
    window.addEventListener("resize", onDashboardResize);
    document.addEventListener("click", (event) => {
      if (event.target.closest(".detail-point-hit")) return;
      document.querySelectorAll(".detail-chart").forEach((chart) => hideDetailTooltip(chart, true));
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        document.querySelectorAll(".detail-chart").forEach((chart) => hideDetailTooltip(chart, true));
      }
    });

    function render() {
      renderFilters();
      renderDailyUpdates();
      renderIndustries();
    }

    initLanguage();
    initSettings();
    initTheme();
    initCurrency();
    initFavoriteMetrics();
    initScrollTopButton();
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
      "판매액(WSTS)", "판매액", "시장 매출", "가격/수요", "투자/장비", "수출",
      "판매/수요", "판매량", "배터리 원재료",
      "운임/해운", "선가/발주",
      "원자재 가격", "중국 경기",
      "에너지 가격", "원유/원료", "화학 스프레드", "스프레드/마진",
      "금리", "스프레드", "금리/스프레드", "은행 건전성", "대출/건전성",
      "주택 경기", "건설 선행", "금융비용", "주택 시장",
      "시장지수", "환율", "리스크", "시장 분위기", "핵심 지표"
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
