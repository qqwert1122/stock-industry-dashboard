# Track A — 데이터 신선도 · AI 카드 고도화 · 운영 가시성

대상 요구사항: ②(최신 데이터 + 최근 업데이트 일시 표기), ⑤(AI 카드 갱신 빈도·품질),
⑥(AI 카드 타임라인·캘린더·마감 카드), ⑦(/admin 수집 로그)

Phase 순서: **A1 → A2 → A3 → A4** (A1이 관측 수단이므로 반드시 첫 번째)

---

## A1. 수집 로그(FetchLog) + `fetched_at` + /admin 페이지

### 목표
- 모든 수집기의 결과를 "성공 / 성공했으나 신규 데이터 없음 / 실패" 3분류로 구조화해 기록한다.
- 각 지표에 **데이터 기준일(observed_at)** 과 별개로 **마지막 수집 확인 시각(fetched_at)** 을 부여하고,
  디테일 패널에 정확히 표기한다.
- `/admin` 정적 페이지에서 최근 실행들의 소스별 수집 로그를 열람한다. (접근 제한 없음 — 공개 페이지임을 인지)

### 설계

#### A1-1. 새 모듈 `src/macro_telegram_report/fetch_log.py`

```python
@dataclass
class FetchRecord:
    source: str          # "FRED", "KRX 수급", "Yahoo/Naver 시세" 등 사람이 읽는 소스명
    endpoint: str        # URL 템플릿 수준 (API 키 등 쿼리 비밀값은 제거해 기록)
    status: str          # "success" | "no_new_data" | "failed"
    message: str         # 실패 사유 / "12/12 지표, 신규 관측 2건" 등
    metric_count: int    # 이 호출(군)이 만든 지표 수
    new_data_count: int  # 이번 실행에서 observed_at이 전진한 지표 수
    started_at: str      # ISO (KST)
    duration_ms: int
    http_status: int | None
class FetchLogger:      # 빌드 1회당 1인스턴스, 수집기들이 record()로 적재
```

- `build_dashboard_payload()` / `refresh_prices_site()` 시작 시 생성해 각 `collect_*` 에 전달.
  (수집기 시그니처 변경이 5,100줄 전반에 퍼지므로, **모듈 전역 컨텍스트 방식**
  `fetch_log.current_logger()` 로 접근하는 것을 허용한다 — 스레드 없음, 순차 실행 전제.)
- 판단 규칙:
  - `failed`: 예외/HTTP 오류로 지표를 만들지 못함 (기존 `status:"error"` 지표와 연동)
  - `no_new_data`: 호출은 성공했지만 모든 지표의 `observed_at` 이 이전 실행과 동일
  - `success`: 신규 관측이 1건 이상
- 실행 종료 시 산출:
  - 이번 실행 요약 `run = {run_id, run_type: "full"|"prices"|"briefing", started_at, finished_at, records: [...]}`
  - `data/fetch_log_history.json` 에 append (최근 **60개 실행**만 보존하는 링버퍼) → 워크플로가 커밋
  - `site/data/fetch_log.json` 으로 전체 히스토리 복사 (admin 페이지가 읽는 파일)
- 워크플로의 "이전 산출물 복원" 단계에 `fetch_log_history.json` 복원 추가
  (dashboard.json과 동일 패턴: `data/` 우선, 없으면 Pages URL 폴백).

#### A1-2. metric에 수집 시각 필드 추가

- 모든 지표에 추가: `fetched_at` (ISO, KST), `fetch_status` (`success`|`no_new_data`|`failed`)
- 풀빌드: 해당 실행 시각. `--prices-only`: 갱신된 시세 지표만 새 fetched_at,
  나머지 지표는 이전 페이로드 값 유지 (없으면 null 허용 — 프론트는 null이면 `generated_at` 폴백 표기)
- 디테일 패널 표기 (템플릿 `templates/dashboard.html` 의 지표 상세 영역):
  - `데이터 기준: 2026.07 (월간)` — 기존 observed_label
  - **추가** `마지막 확인: 2026-07-08 13:29 KST · 신규 데이터 없음` 형식.
    fetch_status가 `success` 면 `업데이트됨`, `failed` 면 `수집 실패(이전 값 표시 중)` 배지.

#### A1-3. /admin 페이지

- 산출 경로: `site/admin/index.html` (Pages 배포 후 `/stock-industry-dashboard/admin/`)
- 생성 방식: 템플릿 `templates/admin.html` 신규 작성, 빌드 시 정적 복사
  (데이터는 페이지 로드 시 `../data/fetch_log.json` fetch — 페이로드 임베드 불필요)
- 화면 구성 (본 사이트와 동일한 CSS 변수/다크모드 스타일 재사용):
  1. 실행 목록 (최근 60회): 시각, run_type, 소스별 success/no_new/failed 개수 요약 배지
  2. 실행 클릭 → 소스별 레코드 테이블: 상태, 메시지, 지표 수, 신규 수, 소요 ms, HTTP 상태
  3. 상단 필터: `실패만 보기` 토글
- 접근 제한 없음(요구사항). 단 endpoint 기록 시 **API 키·시크릿이 포함되지 않도록** URL 쿼리를 소거하는
  유틸을 fetch_log.py에 두고 테스트로 보증한다.

### A1 TODO
- [ ] `fetch_log.py` 신설: FetchRecord/FetchLogger, URL 비밀값 소거 유틸, 링버퍼 저장/로드
- [ ] `dashboard.py` 각 `collect_*_metrics` 에 record 적재 (소스 단위 granularity면 충분, 지표 단위 아님)
- [ ] `refresh_prices_site()` 경로에도 동일 적용
- [ ] metric `fetched_at`/`fetch_status` 부여 + 이전 페이로드에서 승계 로직
- [ ] `templates/dashboard.html` 디테일 패널에 "마지막 확인" 줄 추가 (신·구 페이로드 호환)
- [ ] `templates/admin.html` + 빌드 시 `site/admin/index.html` 산출
- [ ] 두 워크플로에 fetch_log_history 복원/커밋 추가
- [ ] 테스트: 비밀값 소거, 링버퍼 상한, no_new_data 판정(이전 페이로드 대비)

### A1 수용 기준 (AC)
- 풀빌드 후 `/admin` 에서 이번 실행의 소스별 상태 3분류가 보인다. 실패 소스는 사유 메시지가 남는다.
- 임의 지표 디테일에서 "데이터 기준일"과 "마지막 확인 시각(KST, 분 단위)"이 구분 표기된다.
- fetch_log.json 어디에도 API 키 문자열이 등장하지 않는다 (테스트로 검증).

---

## A2. 갱신 주기 상향 (차단 없이 최대한 최신)

### 무료 한도 예산 (2026-07 기준)

| 자원 | 한도 | 현재 사용 | 설계 후 사용 |
|---|---|---|---|
| GitHub Actions | **무제한** (public 리포, 표준 러너) | 풀빌드 1회 + 평일 시세 8회 | 평일 최대 ~44회 — 분수 제약 없음 |
| Yahoo Finance (비공식) | 명시 없음, 과도 호출 시 429 | 시세 45심볼 × 8회/일 | 45심볼 × ~42회/일 ≈ 1,900 req/일 — 호스트 간격 0.5s 유지, fetch_log로 429 감시 |
| FRED | 120 req/min | 풀빌드 1회만 | 변화 없음 (풀빌드만) |
| KRX open API | 일 10,000건 수준(키 발급 조건) | 일 수십 건 | 변화 없음 |
| Gemini free | 15 RPM / 250K TPM / **500 req/일** | 1회/일 | ≤ 60회/일 (A3 게이트로 실제로는 그 이하) |

**2026-07-08 리포 public 전환 완료 → Actions 분수 제약 해소. 이제 상한은 외부 API 예의(특히 Yahoo)와
커밋 소음뿐이다.** 아래 주기는 이를 반영해 한국장 15분 간격으로 설계한다.

> **Public 리포 보안 수칙 (전환 시 점검 완료, 상시 준수):**
> - Repository secrets는 public 전환과 무관하게 계속 비공개다 — 암호화 저장, 값 재조회 불가,
>   로그에서 자동 마스킹(`***`), 포크발 PR 워크플로에는 아예 주입되지 않는다.
> - 전체 git 히스토리(70커밋) 스캔 결과 하드코딩된 키·토큰 없음. `.env`는 커밋된 적 없음(`.env.example`만).
> - 상시 지켜야 할 것:
>   1. **Actions 로그가 공개된다.** 마스킹은 "시크릿 원문과 동일한 문자열"만 적용되므로,
>      `DATA_GO_KR_SERVICE_KEY` 처럼 URL 인코딩 형태(`%2B` 등)가 따로 존재하는 키는
>      인코딩된 변형이 traceback의 URL에 찍히면 마스킹이 안 될 수 있다 →
>      **인코딩/디코딩 두 형태를 모두 secrets로 등록**하거나, 수집 코드가 예외 메시지에
>      전체 URL(쿼리 포함)을 출력하지 않도록 한다 (A1의 URL 비밀값 소거 유틸을 로그·예외 경로에도 적용).
>   2. `pull_request_target` 트리거는 앞으로도 절대 도입 금지 (현재는 schedule/workflow_dispatch만 사용 — 안전).
>   3. public 리포의 schedule 워크플로는 **60일간 리포 활동이 없으면 자동 비활성화**된다.
>      현재는 봇이 매일 커밋하므로 사실상 무관하지만, 파이프라인이 장기 중단되면 재활성화 필요.

### A2-1. 워크플로 실행시간 최적화 (짧은 주기의 전제)

분수 제약은 사라졌지만, 15분 간격에서 실행이 5분씩 걸리면 concurrency 직렬화 큐가 밀려
실질 주기가 늘어진다. 여전히 필수.
- [ ] `astral-sh/setup-uv` 액션 도입, `uv pip install --system -e .` 로 교체 (수십 초 → 수 초)
- [ ] `actions/checkout` 에 `fetch-depth: 1`
- [ ] 시세 갱신 워크플로에서 불필요 단계 제거 확인
- 목표: **prices-only 실행 2분 이내** (큐 밀림 없이 15분 간격 유지 조건)

### A2-2. cron 재설계 (KST 기준, 모두 UTC로 환산해 기입)

| 워크플로 | cron (UTC) | KST | 목적 |
|---|---|---|---|
| daily-macro-report | `0 23 * * *` | 08:00 매일 | 풀빌드 (현행 유지) |
| intraday-prices | `*/15 0-6 * * 1-5` | 09:00–15:45 평일 **15분 간격** (28회) | 한국장 시세+게이지+AI카드 |
| intraday-prices | `*/30 14-20 * * 1-5` | 23:00–05:30 **30분 간격** (14회) | 미국장 (선물·크립토 포함) |
| market-close (신설, A3) | `50 6 * * 1-5` | 15:50 평일 | 한국장 마감 카드 |

- 평일 최대 44회 실행. Actions 분수는 무제한이지만 **Yahoo 등 외부 API 예의가 새 상한**이므로,
  fetch_log(A1)에서 429가 관측되면 즉시 30분 간격으로 되돌린다 (cron 한 줄 수정으로 롤백 가능하게
  두 스케줄을 주석으로 병기해 둘 것).
- GitHub cron은 지연이 흔하다(수 분~30분, 정시 부하 시 심함). 정확 발화가 아니라 "대략 15분 간격"임을
  전제로 하고, `concurrency` 그룹(기존 `stock-industry-dashboard-pages`)을 유지해 겹침 실행을 직렬화한다.
- 커밋 소음: 캐시 커밋이 평일 40여 개 쌓인다. **이번 단계에서는 커밋 유지** (메시지 현행 `[skip ci]` 그대로).
  intraday의 `data/` 캐시 커밋을 생략하고 Pages 복원 폴백에 의존하는 최적화는 가능하지만,
  `data/alerts_state.json`(알림 중복 방지)과 `data/history/` 증분이 유실될 수 있으므로 후속 과제로 미룬다.

### A2-3. 시세 수집 범위 점검

- `refresh_prices_site()` 는 현재 `collect_equity_price_metrics`(대표주+지수)만 갱신한다.
- [ ] 여기에 **시황 관련 경량 소스**를 추가 갱신 대상으로 편입 (전부 Yahoo 단일 호스트라 쓰로틀 부담 미미):
  환율 `KRW=X`/`JPY=X`(엔캐리 감시)/`JPYKRW=X`, 미 지수선물 `ES=F`/`NQ=F`,
  크립토 `BTC-USD`/`ETH-USD`, 금 `GC=F`
  (지표 정의는 Track B B2-4 참조 — B2보다 먼저 구현되면 이 심볼들은 편입 대기).
  단, KRX 수급·KOFIA 등 "일 1회 확정" 소스는 intraday에서 다시 부르지 않는다 — fetch_status가
  no_new_data만 쌓이고 호출 낭비. 소스별 `refresh_scope: "daily" | "intraday"` 구분을
  config.yaml에 명시한다.

### A2 AC
- 평일 한국장 중 사이트의 `generated_label` 이 15분 이내 최신으로 유지된다 (cron 지연 감안 30분 허용).
- prices-only 실행이 2분 이내로 끝나 concurrency 큐 밀림이 없다.
- 429로 인한 수집 실패가 fetch_log 기준 주간 0건 (발생 시 해당 호스트 간격 상향 또는 30분 간격 롤백).

---

## A3. AI 카드 다회 생성 + 하루 흐름 코멘트 + 마감 카드

### 무료 한도 검토
Gemini free tier: 15 RPM / 250K TPM(입력) / 500 req/일.
설계상 호출: 풀빌드 1 + 한국장 인트라데이 최대 28 + 미국장 14 + 마감 1 ≈ **최대 44회/일** (한도의 9%,
생성 게이트로 실제로는 그 이하).
실행당 1회 호출·프롬프트 수천 토큰이므로 RPM/TPM은 문제 없음. 429 시 1회 재시도 후 rule-based 폴백(기존 로직 유지).

### A3-1. 카드 타입과 생성 조건

| type | 생성 시점 | 내용 지침 |
|---|---|---|
| `morning` | 풀빌드(08:00) | 현행 아침 브리핑 (전일 대비 + 신규 관측 지표) |
| `intraday` | 시세 갱신 실행마다 **조건부** | 오늘 장중 흐름 중심 코멘트 |
| `close` | 15:50 실행 | 한국장 마감 카드 (당일 카드 흐름의 종합) |
| `us_close` | 06:15 실행 (21:15 UTC) | 미국장 마감 직후 요약 — 2026-07 구현 중 추가된 타입, 유지 |

**intraday 생성 게이트 (호출 낭비·잡음 방지, 요구사항 ⑤의 "의미 없으면 부각하지 않기"):**
1. 직전 카드 생성 이후 `observed_at` 이 전진했거나 값이 변한 지표가 1개 이상 — 없으면 생성 스킵(이전 카드 유지)
2. 유의미성 점수: 주요 지수(코스피/코스닥/S&P500/나스닥) 중 직전 카드 대비 |변화| ≥ 0.5%p 이거나,
   당일 등락 |≥1%| 지표가 존재하면 "유의미". 아니면 프롬프트에 `low_signal: true` 를 넘겨
   "특기할 변화가 없다"는 톤의 짧은 카드를 생성하되, **2회 연속 low_signal이면 생성 자체를 스킵**한다.

### A3-2. 장중 흐름(트래젝토리) 데이터

"오전 5% 상승했다가 오후 4% 하락" 류의 코멘트에는 당일 시계열이 필요하다.

- 새 파일 `data/intraday_track.json` (당일분만 유지, 자정 후 리셋):
  ```json
  { "date": "2026-07-08",
    "series": { "KS11": [{"t":"09:31","v":3125.4}, ...], "KQ11": [...], "GSPC": [...],
                 "USDKRW": [...], "USDJPY": [...], "ES_F": [...], "BTCUSD": [...] } }
  ```
- 갱신: 매 intraday 실행에서 주요 지수·환율·미 지수선물·BTC의 현재값을 append (30분 해상도면 충분).
  한국장 시간대에는 미 지수선물(ES=F)이 "오늘 밤 미장 기대"의 프록시이므로, 프롬프트 지침에
  "코스피 흐름과 미 선물·환율·BTC 방향이 엇갈리면 짚어줄 것"을 포함한다.
  USD/JPY가 장중 −1.5% 이상 급락(엔 급등) 중이면 엔캐리 청산 리스크를 반드시 언급하도록 지침에 명시.
- **세션 컨텍스트**: 프롬프트에 현재 세션(`한국장 | 미국장 | 세션 외`)을 명시해 서술 초점을 바꾼다 —
  한국장 카드는 코스피·수급 중심, 미국장(한국 새벽) 카드는 미 지수·환율·미 대표주 중심으로 쓰고
  "내일 한국장에 줄 함의"로 마무리. 게이트의 유의미성 판정 지수도 세션에 맞게 가중
  (미국장 시간대엔 S&P/나스닥 변화가 기준).
- 프롬프트에 당일 트래젝토리 요약(시가 대비 고점/저점/현재, 오전·오후 구간 방향)을 계산해 텍스트로 제공.
  원시 배열을 그대로 넣지 말고 `narrative_context` 에 요약 수치로 넣는다 (토큰 절약).
- 프롬프트 지침 추가: "직전 카드 요지(직전 headline/summary 전달)와 달라진 점을 중심으로,
  하루 흐름을 시간 순으로 서술. 유의미한 변화가 없으면 담백하게 짧게."

### A3-3. 브리핑 히스토리 저장 구조

- `site/data/briefings/index.json` — `{ "dates": ["2026-07-08", ...] }` (최신순, 상한 없음—파일이 작음)
- `site/data/briefings/2026-07-08.json` — 당일 카드 배열(시간순):
  ```json
  [ { "type":"morning|intraday|close", "generated_at":"...", "generated_label":"2026-07-08 09:31 KST",
      "headline":"...", "summary":"...", "bullets":[...], "top_movers":[...],
      "model":"gemini-3.1-flash-lite", "status":"ok|fallback" } ]
  ```
- `dashboard.json` 의 `morning_briefing` 키는 **가장 최근 카드**를 담아 하위 호환 유지
  (키 이름 변경 금지 — 프론트/알림 코드가 참조).
- 영속화: `data/briefings/` 를 repo에 커밋(워크플로 복원 단계에 추가). 일 파일 수가 늘어나므로
  365일 초과분은 빌드 시 정리하지 **않는다** (파일당 수 KB, 부담 없음).
- `close` 카드 프롬프트: 당일 카드 전체의 headline/summary 목록 + 최종 트래젝토리를 주고
  "오늘 하루를 마감하는 종합 평가"를 요청.

### A3-4. 신설 워크플로 `market-close.yml`

- `50 6 * * 1-5` (15:50 KST). `industry-dashboard --config config.yaml --out site --briefing-only close`
- [ ] CLI에 `--briefing-only [close|intraday]` 모드 추가: 수집 없이 기존 dashboard.json + intraday_track 기반으로
  카드만 생성·배포 (실행 1분 이내).

### A3 TODO
- [ ] 브리핑 생성부를 `dashboard.py` 에서 새 모듈 `briefing.py` 로 분리
      (build_morning_briefing/gemini_* /rule_based_* 계열 이동 — dashboard.py 비대화 완화)
- [ ] 카드 type 필드·생성 게이트·low_signal 로직
- [ ] intraday_track.json 축적 + 트래젝토리 요약 계산 + 프롬프트 반영
- [ ] briefings/ 저장 구조 + index.json + dashboard.json 하위 호환
- [ ] `--briefing-only` CLI 모드 + market-close.yml
- [ ] 워크플로 복원/커밋 단계에 briefings/, intraday_track.json 추가
- [ ] 테스트: 게이트 판정, 트래젝토리 요약 계산, close 카드 입력 구성

### A3 AC
- 한국장 중 지수가 움직인 날, AI 카드가 하루 여러 번 갱신되고 카드에 생성 시각(분 단위 KST)이 표시된다.
- 지표 변화가 전혀 없는 실행에서는 Gemini 호출이 발생하지 않는다 (fetch_log로 확인).
- 15:50 실행 후 type=close 카드가 그날 파일에 추가된다.
- Gemini 일 호출 수 ≤ 60 (fetch_log 집계).

---

## A4. AI 카드 타임라인 Row + 캘린더 피커 (프론트)

### UI 설계 (`templates/dashboard.html`)

- 위치: 현재 AI 카드(morning_briefing 영역) **바로 아래** 가로 스크롤 Row.
- Row 아이템 = 당일 카드 칩: `[15:50 마감] [15:01] [14:31] … [08:00 아침]` — 시각 + type 아이콘 + headline 1줄 말줄임.
- 최초 로드: 오늘 날짜의 `briefings/{today}.json` fetch → 최신 카드가 selected(포커스/스크롤 위치도 최신).
  파일이 없으면(주말 등) index.json의 가장 최근 날짜로 폴백.
- 칩 클릭 → 위 AI 카드 영역을 해당 카드 내용으로 교체 (렌더 함수를 카드 객체 입력으로 재사용).
  AI 카드 헤더에 `2026-07-08 14:31 KST · 장중` 처럼 **일자+시각+type 라벨** 상시 표시.
- 캘린더 피커: Row 우측에 달력 아이콘 버튼 → `<input type="date">` 네이티브 피커 사용
  (커스텀 달력 구현 금지 — 의존성·코드량 최소화). min/max와 선택 가능 날짜는 index.json 기반으로 안내하되,
  카드 없는 날짜 선택 시 "해당 날짜 카드 없음" 안내 후 가장 가까운 이전 날짜 제안.
- 과거 날짜 선택 시 해당 일 json을 lazy fetch → Row와 카드 교체, "오늘로 돌아가기" 버튼 노출.
- 스타일: 기존 CSS 변수·카드/칩 스타일 재사용, 다크모드 대응, 모바일에서 가로 스와이프 스크롤.

### A4 TODO
- [ ] AI 카드 렌더를 "카드 객체 → DOM" 순수 함수로 리팩터 (임베드 payload의 morning_briefing에만 결합된 부분 제거)
- [ ] 타임라인 Row + 칩 렌더 + 선택 상태 관리
- [ ] 날짜 피커 + index.json 연동 + lazy fetch/캐시
- [ ] 신·구 데이터 호환: briefings/ 가 아직 없으면 Row 자체를 숨기고 기존 단일 카드 동작 유지

### A4 AC
- 오늘 카드가 2개 이상인 날: Row에 시간순 정렬, 최신 포커스, 과거 칩 클릭 시 상단 카드 교체가 동작한다.
- 캘린더로 과거 영업일 선택 시 그날의 카드 흐름을 재생할 수 있다.
- briefings 데이터가 없는 배포본에서도 콘솔 에러 없이 기존 화면이 나온다.
