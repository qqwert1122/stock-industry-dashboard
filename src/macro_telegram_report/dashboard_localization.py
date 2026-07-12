"""Dashboard display text cleanup and English localization rules."""

from __future__ import annotations

import re
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
    "한국 유동성": "Korea Liquidity",
    "일본 유동성": "Japan Liquidity",
    "유럽 유동성": "Europe Liquidity",
    "국제 유동성": "Global Liquidity",
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
    "$B": "$B",
    "$/mt": "USD/mt",
    "$/mmbtu": "USD/mmbtu",
    "$/gal": "USD/gal",
    "원": "KRW",
    "조원": "tn KRW",
    "€B": "€B",
    "¥T": "¥T",
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
    "한국 주간 아파트 매매가격지수": "Korea Weekly Apartment Sale Price Index",
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
    "한국은행 총자산": "Bank of Korea Total Assets",
    "한국 본원통화": "Korea Monetary Base",
    "한국 M2": "Korea M2",
    "한국 Lf": "Korea Lf",
    "한국 L": "Korea L",
    "일본 BOJ 총자산": "BOJ Total Assets",
    "일본 본원통화": "Japan Monetary Base",
    "일본 M2": "Japan M2",
    "일본 BOJ 당좌예금": "BOJ Current Account Balances",
    "유럽 초과유동성": "Europe Excess Liquidity",
    "유럽 유로시스템 총자산": "Eurosystem Total Assets",
    "유럽 M3": "Europe M3",
    "유럽 본원통화": "Europe Base Money",
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
    "한국은행 대차대조표의 자산 총액입니다. 중앙은행이 시장에 공급한 유동성의 큰 방향을 볼 때 기준으로 씁니다.": "Total assets on the Bank of Korea balance sheet. It is a baseline for the broad direction of central-bank liquidity supplied to markets.",
    "현금통화와 금융기관의 중앙은행 예치금을 합친 돈의 바탕입니다. 은행 시스템에 공급된 기본 유동성이 늘고 줄어드는지 확인합니다.": "The base layer of money, combining currency in circulation and financial-institution deposits at the central bank. It shows whether basic liquidity in the banking system is expanding or contracting.",
    "현금, 요구불예금, 수시입출식 예금 등 비교적 바로 쓸 수 있는 돈을 넓게 묶은 통화량입니다. 가계와 기업의 자금 여유를 볼 때 핵심으로 봅니다.": "Broad money covering cash, demand deposits, and liquid savings deposits. It is a key gauge of household and corporate cash availability.",
    "M2보다 더 넓게 금융기관이 공급한 유동성을 보는 지표입니다. 은행권 밖까지 포함한 자금 여건의 폭을 확인합니다.": "A broader liquidity measure than M2 that captures financial-institution liquidity beyond the banking core.",
    "국채, 회사채 같은 시장성 금융상품까지 포함한 가장 넓은 유동성 지표입니다. 한국 경제 전체의 돈의 양이 얼마나 넓게 풀려 있는지 볼 때 씁니다.": "The broadest Korean liquidity measure, including marketable instruments such as government and corporate bonds. It shows how widely money is available across the economy.",
    "일본은행 대차대조표의 자산 총액입니다. 일본 중앙은행이 시장에 공급한 유동성의 큰 물줄기를 보여줍니다.": "Total assets on the Bank of Japan balance sheet. It shows the broad flow of central-bank liquidity supplied to Japanese markets.",
    "일본의 현금통화와 일본은행 당좌예금 등을 합친 기본 통화량입니다. BOJ 정책이 실제 유동성으로 얼마나 남아 있는지 볼 때 봅니다.": "Japan's base money, including currency in circulation and BOJ current account balances. It helps show how much BOJ policy remains as actual liquidity.",
    "일본 경제 안에서 가계와 기업이 비교적 쉽게 쓸 수 있는 돈의 규모입니다. 민간 유동성이 늘고 줄어드는지 확인합니다.": "Money that households and companies in Japan can use relatively easily. It tracks whether private-sector liquidity is expanding or contracting.",
    "금융기관이 일본은행에 맡겨둔 당좌예금 잔액입니다. 은행 시스템 안에 남아 있는 초과 유동성의 크기를 볼 때 참고합니다.": "Current account balances that financial institutions hold at the Bank of Japan. It is a useful gauge of excess liquidity inside the banking system.",
    "유로존 은행 시스템에 필요한 지급준비를 넘어서 남아 있는 유동성입니다. 숫자가 클수록 은행권에 여유자금이 많이 남아 있다는 뜻입니다.": "Liquidity remaining in the euro-area banking system above required reserves. A larger reading means more surplus cash is left in banks.",
    "ECB와 유로존 중앙은행들의 총자산입니다. 양적완화와 긴축으로 중앙은행 유동성이 커지는지 줄어드는지 보여줍니다.": "Total assets of the ECB and euro-area national central banks. It shows whether central-bank liquidity is expanding or shrinking through QE or tightening.",
    "유로존의 넓은 통화량입니다. 가계와 기업, 금융기관에 풀린 돈의 규모와 민간 유동성 흐름을 볼 때 씁니다.": "Broad euro-area money supply used to read the amount of money available to households, companies, and financial institutions.",
    "유로존의 현금과 중앙은행 예치금을 합친 기본 통화량입니다. ECB 정책이 은행 시스템 안의 돈의 바탕을 얼마나 크게 만들고 있는지 보여줍니다.": "Euro-area base money, combining currency and central-bank deposits. It shows how large the foundation of money in the banking system is under ECB policy.",
    "미국 국방부가 실제로 계약에 배정한 금액입니다. 방산 예산이 어느 분야로 흘러가는지 볼 때 중요합니다.": "US DoD contract obligations show where defense budget dollars are actually being committed.",
    "미국 연방 방산/항공우주 제조업 계약 의무액으로 방산 제조 밸류체인의 수주 모멘텀을 확인합니다.": "Uses US federal defense/aerospace manufacturing obligations to read order momentum across the defense manufacturing value chain.",
    "NASA 계약 의무액은 미국 정부가 우주 장비와 서비스에 실제로 얼마나 돈을 쓰고 있는지 보여줍니다.": "NASA contract obligations show how much the US government is actually spending on space equipment and services.",
    "FDA 의약품 승인 관련 기록 수로 바이오 규제 이벤트와 신약 모멘텀을 확인합니다.": "Counts FDA drug approval records to read biotech regulatory events and new-drug momentum.",
    "Phase 3 임상 시작 건수는 후기 파이프라인 활동성과 바이오 투자심리의 이벤트 밀도를 보여줍니다.": "Phase 3 trial starts show late-stage pipeline activity and event density for biotech sentiment.",
    "글로벌 발사 건수로 우주 산업 활동성과 위성 인프라 수요를 확인합니다.": "Global launch count indicates space industry activity and satellite infrastructure demand.",
    "미국 EV 충전소 수는 전기차를 이용하기 쉬워지고 있는지와 충전 인프라 투자 흐름을 보여줍니다.": "US EV charging station count shows whether EVs are getting easier to use and how charging infrastructure investment is moving.",
    "미국 EV 충전 포트 수는 전기차 이용 편의성과 인프라 확장 속도를 확인하는 지표입니다.": "US EV charging port count shows EV usability and the pace of infrastructure expansion.",
    "전국 아파트 매매가격을 매주 조사한 지수입니다. 월간 통계보다 빠르게 국내 주택가격의 상승·하락 방향과 가계 자산 심리 변화를 확인할 수 있습니다.": "A weekly index of apartment sale prices nationwide. It shows the direction of Korean home prices and household wealth sentiment faster than monthly statistics.",
    "유로존의 현금과 중앙은행 예치금을 합친 기본 통화량의 지급준비 유지기간 평균입니다. ECB 정책이 은행 시스템 안의 돈의 바탕을 얼마나 크게 만들고 있는지 보여줍니다.": "Average euro-area base money over the reserve maintenance period, combining currency and central-bank deposits. It shows the monetary foundation available in the banking system under ECB policy.",
}

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
    "유동성": "Liquidity",
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
