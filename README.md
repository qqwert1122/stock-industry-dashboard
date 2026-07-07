# 산업별 핵심 지표 대시보드

매일 아침 GitHub Actions가 FRED, ECOS, Yahoo Finance 주가, WSTS, 관세청 수출, World Bank 원자재, SEC CAPEX, USAspending, EIA, openFDA, ClinicalTrials.gov, Launch Library, NLR/NREL, KOSIS 데이터를 수집하고 정적 웹 대시보드를 생성해 GitHub Pages에 배포합니다. 내 컴퓨터가 꺼져 있어도 GitHub 서버에서 실행됩니다.

## 현재 MVP

- 반도체: WSTS 월간/3개월 평균 반도체 판매액, 한국 반도체 수출, 미국 반도체 PPI, 삼성전자/NVIDIA 주가
- 데이터인프라: Microsoft/Amazon/Alphabet/Meta CAPEX, NAVER/Microsoft 주가
- 자동차: 미국 자동차 판매, 한국 승용차 수출, 현대차/Toyota 주가
- 전기차: 한국 순수 전기차 수출, 미국 EV 충전소/충전 포트 수, LG에너지솔루션/Tesla 주가
- 조선: 한국 선박 수출, HD현대중공업/Huntington Ingalls 주가, BDI/신조선가/운임지수 자동화 후보
- 철강/소재: 철광석/구리/알루미늄 원자재 proxy, POSCO홀딩스/Nucor 주가
- 화학/정유: WTI/Brent, 미국 화학 PPI, LG화학/Exxon Mobil 주가
- 은행/금융: 기준금리 proxy, 장단기 금리차, FRED 등급별 회사채 OAS, ECOS 한국 회사채-국고채 스프레드, 연체율, 은행 대출, KB금융/JPMorgan 주가
- 건설/부동산: 미국 주택착공/건축허가/모기지/주택가격, 한국 미분양/주택가격/건축허가, 현대건설/D.R. Horton 주가
- 방산: 미국 방산 자본재 신규주문/수주잔고, 미국 국방부/방산 제조 계약 의무액, 한국 무기류/탄약 수출, 한화에어로스페이스/Lockheed Martin 주가
- 스테이블코인: DefiLlama 전체/USDT/USDC 유통량, Coinbase/Circle 주가
- 전력: 미국 전력 생산 PPI, 유틸리티 산업생산, 전력 판매/발전량/가격, 에너지 원료 가격, 한국 전력 장비 수출, 한국전력/GE Vernova 주가
- 로봇: 산업용 기계 신규주문, 산업 제어장치 PPI, 한국 산업용 로봇 수출, 두산로보틱스/Teradyne 주가
- 우주: 방산/우주 장비 산업생산, 항공우주 부품 PPI, 글로벌 우주 발사 건수, 한국 항공기/우주선 수출, 쎄트렉아이/Rocket Lab 주가
- 바이오: 생물학적 제제/체외진단 PPI, FDA 승인 활동, Phase 3 임상 시작, 한국 바이오 의약품 수출, 삼성바이오로직스/Eli Lilly 주가
- 배터리: 저장 배터리 제조 PPI, 니켈 가격, 한국 축전지 수출, 삼성SDI/Albemarle 주가
- 매크로: 원/달러 환율, VIX, 코스피/코스닥/나스닥/S&P 500/다우 지수

무료로 안정적인 공식 API가 없는 지표는 대시보드에서 `부분 자동화` 또는 `수작업` 상태로 표시합니다.
개별 회사채 스프레드는 무료 공식 API로 안정 수집하기 어려워, 현재 MVP는 FRED의 등급별 미국 회사채 OAS를 신용 스프레드 proxy로 사용합니다.

## 로컬 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
cp .env.example .env
industry-dashboard --config config.yaml --out site
```

생성된 파일은 `site/index.html`입니다.

## VSCode에서 외형 수정

외형만 바꿀 때는 API를 다시 수집하지 않고 기존 `site/data/dashboard.json`을 재사용합니다.

```bash
.venv/bin/python scripts/dev_dashboard.py
```

터미널에 표시되는 `http://127.0.0.1:8000/` 주소를 브라우저나 VSCode Simple Browser로 열면 됩니다.  
`src/macro_telegram_report/dashboard.py`의 `MODERN_HTML_TEMPLATE` 안 CSS/HTML/JS를 수정하면 `site/index.html`이 자동으로 다시 생성되고 브라우저가 새로고침됩니다.

데이터까지 새로 수집하고 싶을 때만 아래처럼 실행합니다.

```bash
.venv/bin/python scripts/dev_dashboard.py --full-build
```

## GitHub Pages 배포

1. 이 private 저장소에서 `Daily Industry Dashboard` workflow를 실행합니다.
2. workflow가 `site/`를 생성한 뒤 공개 저장소 `qqwert1122/qqwert1122.github.io`의 `stock-industry-dashboard/` 폴더로 배포합니다.
3. 이후 매일 23:00 UTC, 즉 한국시간 08:00에 다시 수집하고 배포합니다.

## Secrets

- `DATA_GO_KR_SERVICE_KEY`: 공공데이터포털 관세청 API의 Decoding 서비스키
- `FRED_API_KEY`: FRED 무료 API 키
- `ECOS_API_KEY`: 한국은행 ECOS Open API 무료 API 키. 한국 회사채-국고채 스프레드 수집에 사용합니다.
- `EIA_API_KEY`: EIA Open Data 무료 API 키
- `SEC_USER_AGENT`: SEC fair access용 User-Agent. 선택값이지만 이메일이나 연락 가능한 URL을 넣는 것을 권장합니다.
- `NREL_API_KEY`: NLR/NREL Alternative Fuel Stations 무료 API 키
- `OPENFDA_API_KEY`: openFDA 선택 API 키. 없어도 실행되지만 rate limit이 낮습니다.
- `KOSIS_API_KEY`: KOSIS OpenAPI 무료 API 키
- `USER_PAGES_DEPLOY_KEY`: 공개 Pages 저장소에 배포하기 위한 SSH deploy key

키가 없으면 해당 데이터 소스의 지표만 `키 필요`로 표시되고, 나머지 대시보드는 계속 생성됩니다.

## 설정

`config.yaml`에서 지표를 관리합니다.

- `dashboard.fred_series`: FRED API/CSV로 자동 수집할 지표
- `ecos.credit_spreads`: ECOS 시장금리에서 계산할 한국 회사채-국고채 스프레드
- `equities.items`: Yahoo Finance chart JSON에서 가져올 산업 대표 상장사 주가와 시장지수
- `wsts.regions`: WSTS에서 표시할 지역
- `korea_exports.items`: 관세청 HS 코드별 수출 지표
- `stablecoins.assets`: DefiLlama에서 가져올 스테이블코인 유통량 지표
- `world_bank_commodities.items`: World Bank Pink Sheet 엑셀에서 가져올 원자재 지표
- `sec_capex.companies`: SEC Company Facts에서 가져올 빅테크 CAPEX 기업
- `usaspending.items`: USAspending 계약 의무액 필터
- `eia.series`: EIA Open Data 시계열
- `openfda.items`: FDA 승인 활동 이벤트 지표
- `clinical_trials.items`: ClinicalTrials.gov 임상 이벤트 지표
- `launch_library.items`: Launch Library 우주 발사 이벤트 지표
- `afdc.items`: NLR/NREL EV 충전 인프라 지표
- `kosis.items`: KOSIS 한국 주택/건설 통계 지표
- `dashboard.reference_metrics`: 아직 완전 자동화하지 않은 무료/공식 데이터 후보

## 데이터 저장 구조

정적 사이트에는 매 실행마다 아래 파일이 생성됩니다.

```text
site/
  index.html
  data/
    dashboard.json
```

`dashboard.json`에는 지표별 최신값, 전기 변화, YoY 변화, 히스토리, 출처, 자동화 상태가 들어갑니다. SQLite나 Google Sheets 저장이 필요하면 이 JSON payload를 그대로 upsert 대상으로 쓰면 됩니다.

## 참고 출처

- FRED: https://fred.stlouisfed.org/
- ECOS Open API: https://ecos.bok.or.kr/api/
- Yahoo Finance: https://finance.yahoo.com/
- WSTS Historical Billings Report: https://www.wsts.org/67/Historical-Billings-Report
- 관세청 품목별 수출입실적 API: https://www.data.go.kr/data/15101609/openapi.do
- DefiLlama Stablecoins: https://defillama.com/stablecoins
- World Bank Commodity Markets: https://www.worldbank.org/en/research/commodity-markets
- KOSIS OpenAPI: https://kosis.kr/openapi/
- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- USAspending API: https://api.usaspending.gov/
- EIA Open Data: https://www.eia.gov/opendata/
- openFDA: https://open.fda.gov/apis/
- ClinicalTrials.gov API: https://clinicaltrials.gov/data-api
- The Space Devs Launch Library 2: https://thespacedevs.com/llapi
- NLR Alternative Fuel Stations: https://developer.nlr.gov/docs/transportation/alt-fuel-stations-v1/
- GitHub Pages Actions: https://github.com/actions/deploy-pages
