# 산업별 핵심 지표 대시보드

매일 아침 GitHub Actions가 FRED, WSTS, 관세청 수출 데이터를 수집하고 정적 웹 대시보드를 생성해 GitHub Pages에 배포합니다. 내 컴퓨터가 꺼져 있어도 GitHub 서버에서 실행됩니다.

## 현재 MVP

- 반도체: WSTS 월간 반도체 판매액, 한국 반도체 수출, 미국 반도체 PPI
- 자동차/전기차: 미국 자동차 판매, 한국 승용차 수출
- 조선: 한국 선박 수출, BDI/신조선가/운임지수 자동화 후보
- 철강/소재: FRED 원자재 가격 proxy
- 화학/정유: WTI/Brent, 미국 화학 PPI
- 은행/금융: 기준금리 proxy, 장단기 금리차, 회사채 스프레드, 연체율, 은행 대출
- 건설/부동산: 주택착공, 건축허가, 모기지 금리, 주택가격지수

무료로 안정적인 공식 API가 없는 지표는 대시보드에서 `부분 자동화` 또는 `수작업` 상태로 표시합니다.

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

## GitHub Pages 배포

1. 이 폴더를 GitHub 저장소로 올립니다.
2. 저장소의 `Settings > Pages`에서 `Source`를 `GitHub Actions`로 설정합니다.
3. 저장소의 `Settings > Secrets and variables > Actions`에 필요한 키를 등록합니다.
4. `Actions` 탭에서 `Daily Industry Dashboard` workflow를 한 번 수동 실행합니다.
5. 이후 매일 23:00 UTC, 즉 한국시간 08:00에 다시 수집하고 Pages에 배포합니다.

## Secrets

- `DATA_GO_KR_SERVICE_KEY`: 공공데이터포털 관세청 API의 Decoding 서비스키
- `FRED_API_KEY`: FRED 무료 API 키

키가 없으면 해당 데이터 소스의 지표만 `키 필요`로 표시되고, 나머지 대시보드는 계속 생성됩니다.

## 설정

`config.yaml`에서 지표를 관리합니다.

- `dashboard.fred_series`: FRED API/CSV로 자동 수집할 지표
- `wsts.regions`: WSTS에서 표시할 지역
- `korea_exports.items`: 관세청 HS 코드별 수출 지표
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
- WSTS Historical Billings Report: https://www.wsts.org/67/Historical-Billings-Report
- 관세청 품목별 수출입실적 API: https://www.data.go.kr/data/15101609/openapi.do
- GitHub Pages Actions: https://github.com/actions/deploy-pages
