# 개선 설계 총괄 문서 (2026-07)

이 디렉터리는 대시보드의 두 가지 개선 방향에 대한 **구현용 설계 문서**입니다.
코딩 에이전트는 이 README로 전체 맥락을 잡은 뒤, 담당 트랙 문서의 Phase 단위 TODO를 따라 구현합니다.

| 문서 | 내용 |
|---|---|
| [track-a-freshness-and-ai.md](track-a-freshness-and-ai.md) | **Track A — 데이터 신선도 · AI 카드 고도화 · 운영 가시성** (요구사항 2, 5, 6, 7) |
| [track-b-market-overview.md](track-b-market-overview.md) | **Track B — '시황' 메뉴 신설(수급 중심) · 지표 해석 레이어** (요구사항 3, 4) |
| [agent-prompts.md](agent-prompts.md) | Phase별 코딩 에이전트 실행 프롬프트 (복붙용) |
| [review-b2-investor-breakdown.md](review-b2-investor-breakdown.md) | **B2-③** — 투자자별 수급 전체 분해(11주체×주식/선물×매도/매수/순매수, 확정) + 실행 프롬프트 |
| [feature-metric-search.md](feature-metric-search.md) | **S1** — 전역 지표 검색 (우측 상단 버튼, 디바운스 필터, 카드+필터 뷰) + 실행 프롬프트 |
| [feature-compare-overlay.md](feature-compare-overlay.md) | **C1** — 지표 오버레이 비교 (디테일 패널 [+비교], 듀얼축 2개/=100 최대 4개) + 실행 프롬프트 |
| [feature-signal-history.md](feature-signal-history.md) | **H1** — 시그널 이력 (우측 Drawer 알림 피드, 트리거 기준 축적 + 소급 백필 + 차트 마커) + 실행 프롬프트 |
| [feature-event-calendar.md](feature-event-calendar.md) | **E1** — 이벤트 캘린더 (FOMC·금통위·만기·휴장일, AI 카드 연동) + 실행 프롬프트 |
| [feature-gauge-history.md](feature-gauge-history.md) | **G1** — 시장 게이지 히스토리 추이 뷰 (기존 축적 데이터 렌더만) + 실행 프롬프트 |
| [feature-metric-notes.md](feature-metric-notes.md) | **N1** — 지표 개인 메모 (별표 옆 버튼, PC 모달/모바일 바텀시트, localStorage+백업) + 실행 프롬프트 |
| [feature-qol-pack.md](feature-qol-pack.md) | **Q1~Q4** — 일일 변화 히트맵 / CSV 내보내기 / PWA / 주간 아카이브(보류) + 실행 프롬프트 |
| [feature-search-v2.md](feature-search-v2.md) | **S2** — 검색 고도화 (초성·별칭·랭킹 부스트·키보드 내비, 통합 검색은 보류) + 실행 프롬프트 |
| [ia-consistency.md](ia-consistency.md) | **IA 정합 규칙** — 메뉴 트리 최종본·상단 스택 순서·고정 요소 좌표 (프론트 Phase 공통 우선 기준) + B1.1 해시 라우팅 |

공통 제약(요구사항 1): **운영 비용 0원.** 유료 API·유료 호스팅·유료 모델 금지.
무료 한도(GitHub Actions, Gemini free tier, 각 공공/무료 API) 안에서만 동작해야 한다.

---

## 1. 현재 아키텍처 요약 (구현 전 필독)

에이전트가 코드를 다시 뒤지지 않도록 핵심만 정리한다. 세부는 해당 파일을 직접 열어 확인할 것.

### 1.1 빌드 파이프라인 (Python 정적 사이트 생성기)

- 진입점: `industry-dashboard` CLI → `src/macro_telegram_report/dashboard_cli.py`
  - 풀빌드: `dashboard.py::build_dashboard_site()` (dashboard.py:471)
  - 시세만 갱신: `--prices-only` → `refresh_prices_site()` (dashboard.py:513)
- `dashboard.py` (약 5,100줄, 단일 모듈)가 모든 수집기(`collect_*_metrics`)를 순차 호출해
  `metrics: list[dict]` 를 만들고, 아래 산출물을 `site/` 에 쓴다:
  - `site/data/dashboard.json` — 전체 페이로드 (metrics 158개 + market_gauges + morning_briefing 등)
  - `site/data/long_history.json` — 상세 차트용 장기 시계열
  - `site/data/market_gauges_history.json` — 게이지 히스토리
  - `site/index.html` — `templates/dashboard.html` 의 `__DASHBOARD_JSON__` 자리에
    페이로드 JSON을 치환해 생성 (`render_dashboard_html()`, dashboard.py:5130).
    **프론트엔드는 이 단일 HTML 템플릿 안의 인라인 JS가 임베드된 JSON을 클라이언트에서 렌더링**하는 구조.
- 장기 히스토리 저장소: `data/history/*.json` (repo에 커밋, 증분 병합) — `history_store.py::HistoryStore`
- HTTP: 모든 수집기가 `http_client.py::ThrottledSession` 공유 (호스트별 최소 간격 + 429/503 재시도)
- 수집 소스: FRED, ECOS, KRX Open API(data-dbg.krx.co.kr), Yahoo Finance(Naver 폴백),
  WSTS, SEC, EIA, USAspending, KOSIS, openFDA, ClinicalTrials, Launch Library, AFDC,
  World Bank, multpl.com, CNN Fear&Greed, DeFiLlama(스테이블코인) 등
- 시장 심리: `market_sentiment.py` — CNN F&G + **KRX 전종목 일별 스냅샷**
  (`stk_bydd_trd`/`ksq_bydd_trd`, `data/history/krx-*.json`에 축적) 기반 한국 Fear&Greed, VKOSPI
- AI 카드: `build_morning_briefing()` (dashboard.py:976) → Gemini `gemini-3.1-flash-lite`
  (REST 직접 호출, `request_gemini_briefing()`), 실패 시 `rule_based_morning_briefing()` 폴백.
  결과는 payload의 `morning_briefing` 키. **현재는 풀빌드에서만 생성 = 하루 1회.**

### 1.2 배포 파이프라인 (GitHub Actions)

- `.github/workflows/daily-macro-report.yml` — 매일 23:00 UTC(08:00 KST) 풀빌드
- `.github/workflows/intraday-prices.yml` — 평일 00:30–14:30 UTC 2시간 간격, `--prices-only`
- 두 워크플로 공통 흐름:
  1. 이전 산출물 복원 (`data/last_dashboard.json` → `site/data/dashboard.json`,
     없으면 공개 Pages URL에서 curl 폴백)
  2. 빌드 실행
  3. 산출물을 `data/` 캐시로 커밋(`[skip ci]`) → main에 push
  4. `site/` 를 `qqwert1122.github.io` (공개 리포)의 `stock-industry-dashboard/` 로 rsync 후 push
- **이 리포는 public** (2026-07-08 전환) → GitHub Actions 분수 무제한. 갱신 주기의 실질 상한은
  외부 API 예의(특히 Yahoo)와 커밋 소음. 시크릿은 계속 안전하나 **Actions 로그가 공개**되므로
  Track A의 "Public 리포 보안 수칙"(로그에 키 노출 방지, `pull_request_target` 금지)을 준수할 것.

### 1.3 metric dict 스키마 (현행 주요 필드)

```
id, status, history_key, history_merge, source, industry, industry_en,
depth, depth_en, group, group_en, name, name_en, meaning, meaning_en,
value, unit, display_value, frequency, observed_at, observed_label,
next_update_label, change_abs, change_pct, yoy_pct, history(60pt),
period_label, percentiles, is_stale, stale_days,
daily_status, is_new, is_updated_today, previous_run_*
```

`observed_at` 은 **데이터 기준일**(예: 월간 지표면 해당 월 1일)이며, "언제 수집했는지"는 현재 없음
(Track A에서 `fetched_at` 추가).

---

## 2. 두 트랙의 관계와 실행 순서

두 트랙은 **서로 독립적으로 병렬 진행 가능**하다. 단, 트랙 내부 Phase는 순서를 지킨다.

```
Track A:  A1 수집로그+fetched_at  →  A2 갱신주기 상향  →  A3 AI카드 다회화  →  A4 AI 타임라인 UI
Track B:  B1 시황/지표 2단 네비  →  B2 시황 데이터 수집(수급 우선)  →  B3 지표 해석 레이어
```

- A1을 가장 먼저: 갱신 주기를 올리기 전에 소스별 성공/실패/최신여부를 관측할 수단부터 확보.
- B1은 프론트 전용이라 데이터 작업 없이 먼저 가능. B2 지표는 B1의 시황 메뉴에 꽂힌다.
- B3(해석 레이어)는 산업 지표와 시황 지표 모두에 적용되므로 B2 이후가 자연스럽다.
- 충돌 주의: A4와 B1이 모두 `templates/dashboard.html` 을 크게 수정한다.
  동시에 진행한다면 B1(네비 구조 변경)을 먼저 머지하고 A4를 그 위에 얹을 것.

## 3. 코딩 에이전트 공통 지침

1. **문서의 Phase 하나가 PR 하나**. Phase 안의 TODO 순서대로 구현하고, 수용 기준(AC)을 모두 만족해야 완료.
2. 기존 코드 스타일을 따른다: 한국어 주석/문구, dict 기반 페이로드, 표준 라이브러리+requests 위주.
   새 프레임워크·빌드 도구·npm 의존성 도입 금지 (프론트는 현행 인라인 JS/CSS 유지).
3. 모든 외부 HTTP 호출은 반드시 `ThrottledSession` 을 통하고, 새 호스트는
   `http_client.py::HOST_MIN_INTERVALS` 에 보수적 간격을 등록한다.
4. 수집 실패가 빌드 전체를 죽이면 안 된다. 기존 패턴처럼 지표 단위로 `status: "error"` 처리하고
   진행한다 (Track A의 fetch log에 실패 기록).
5. 페이로드 스키마 변경 시 **하위 호환** 유지: 프론트 JS는 새 필드가 없어도 (이전 dashboard.json으로도)
   깨지지 않아야 한다. 워크플로의 "이전 산출물 복원" 단계 때문에 신·구 페이로드가 섞일 수 있다.
6. 검증: `pytest` 통과 + `scripts/dev_dashboard.py` 로 로컬 렌더 확인
   (외부 API 없이 확인할 때는 `site/data/dashboard.mock.json` 활용).
7. 문서에 "구현 시 검증 필요" 표시가 있는 외부 API 항목(특히 KRX 비공식 bld 코드)은
   실제 호출로 응답 스키마를 확인한 뒤 구현하고, 확인 결과를 PR 설명에 남긴다.
8. **프론트(templates/dashboard.html) 작업은 [ia-consistency.md](ia-consistency.md)의 배치 규칙이
   개별 기능 문서보다 우선한다** (메뉴 트리, 상단 스택 순서, 고정 요소 좌표, z-index).

## 4. 요구사항 ↔ 설계 매핑

| 요구사항 | 설계 위치 |
|---|---|
| 1. 비용 0원 운영 | 공통 제약. 각 트랙의 "무료 한도 예산" 절 |
| 2. 차단 없이 최대한 최신 데이터 + 지표별 최근 업데이트 일시 표시 | Track A — A1, A2 |
| 3. '시황' 상위 메뉴 (수급 상세) | Track B — B1, B2 |
| 4. 지표 정의·현재값 의미를 계산식으로 매핑 | Track B — B3 |
| 5. AI 카드 무료 한도 내 최대한 자주 + 하루 흐름 코멘트 | Track A — A3 |
| 6. AI 카드 타임라인 Row + 캘린더 피커 + 일 마감 카드 | Track A — A3, A4 |
| 7. /admin 수집 로그 페이지 | Track A — A1 |
