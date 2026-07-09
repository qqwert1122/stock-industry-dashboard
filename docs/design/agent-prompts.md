# 코딩 에이전트 실행 프롬프트 모음

사용법: 아래 프롬프트를 Phase 순서대로 에이전트에게 그대로 전달한다.
- 병렬 가능: Track A와 Track B는 동시 진행 가능. 단 **A1 → A2 → A3 → A4**, **B1 → B2 → B3** 내부 순서 엄수.
- 머지 순서 주의: **B1을 A4보다 먼저 머지**할 것 (둘 다 templates/dashboard.html 대수술).
- 한 Phase가 끝나면 PR 링크와 "⚠️ 검증 필요" 항목의 확인 결과를 받고 다음 Phase를 시작한다.

---

## A1 — 수집 로그 + fetched_at + /admin

```
docs/design/README.md를 먼저 읽고(특히 1절 아키텍처 요약과 3절 공통 지침), docs/design/track-a-freshness-and-ai.md의 A1 섹션을 구현해줘.

범위: A1 TODO 체크리스트 전부. 새 모듈 src/macro_telegram_report/fetch_log.py, 모든 collect_* 수집기의 소스 단위 기록, metric의 fetched_at/fetch_status 필드, 디테일 패널의 "마지막 확인" 표기, templates/admin.html → site/admin/index.html, 두 워크플로의 fetch_log_history 복원/커밋.

완료 조건: A1 수용 기준(AC) 3개 전부 충족. pytest 통과. scripts/dev_dashboard.py로 로컬 렌더 확인. 특히 fetch_log 어디에도 API 키가 남지 않는 것을 테스트로 보증할 것(URL 쿼리 소거 유틸 필수 — 이 리포는 public이고 Actions 로그와 배포 산출물이 모두 공개된다).

브랜치 feat/a1-fetch-log 에서 작업하고 PR 하나로 정리해줘. 페이로드 스키마는 하위 호환(새 필드가 없는 구 dashboard.json으로도 프론트가 깨지지 않아야 함).
```

## A2 — 갱신 주기 상향 (A1 머지 후)

```
docs/design/README.md와 docs/design/track-a-freshness-and-ai.md의 A2 섹션을 구현해줘. A1(fetch_log)이 이미 머지되어 있다.

범위: A2-1 워크플로 실행시간 최적화(uv 도입, fetch-depth 1, 목표: prices-only 2분 이내), A2-2 cron 재설계(한국장 15분/미국장 30분 — 문서의 UTC cron 표 그대로, 30분 간격 롤백용 스케줄을 주석으로 병기), A2-3 intraday 수집 범위 편입(KRW=X, JPY=X, JPYKRW=X, ES=F, NQ=F, BTC-USD, ETH-USD, GC=F — config.yaml에 refresh_scope 구분 도입).

주의: market-close.yml은 A3 범위이므로 만들지 마. Yahoo 심볼 8개는 실제 응답을 확인하고 편입하되, 실패 심볼은 문서의 폴백을 따르거나 PR 설명에 보고해줘. 커밋 캐시 동작(data/ 커밋, [skip ci])은 변경 금지.

완료 조건: A2 AC 3개. workflow 파일은 act 없이도 리뷰 가능하도록 diff를 최소화. 브랜치 feat/a2-cadence.
```

## A3 — AI 카드 다회 생성 + 마감 카드 (A2 머지 후)

```
docs/design/README.md와 docs/design/track-a-freshness-and-ai.md의 A3 섹션을 구현해줘.

범위: A3 TODO 전부 — 브리핑 로직을 briefing.py로 분리, 카드 type(morning/intraday/close)과 생성 게이트(변경 없으면 스킵, low_signal 2연속 스킵), data/intraday_track.json 축적과 트래젝토리 요약의 프롬프트 반영(USD/JPY -1.5% 급락 시 엔캐리 리스크 언급 지침 포함), site/data/briefings/ 저장 구조와 index.json, dashboard.json의 morning_briefing 키 하위 호환 유지, --briefing-only CLI 모드, market-close.yml 신설, 워크플로 복원/커밋 단계 추가.

주의: GEMINI_API_KEY 없이 개발하게 될 것 — rule-based 폴백 경로와 게이트 로직은 키 없이 전부 테스트 가능해야 한다. Gemini 호출부는 기존 request_gemini_briefing 패턴(REST 직접 호출) 유지.

완료 조건: A3 AC 4개. 게이트 판정/트래젝토리 요약/close 카드 입력 구성에 대한 pytest. 브랜치 feat/a3-briefing-cards.
```

## A4 — AI 카드 타임라인 UI (A3 그리고 **B1 머지 후**)

```
docs/design/README.md와 docs/design/track-a-freshness-and-ai.md의 A4 섹션을 구현해줘. B1(2단 네비)이 이미 머지된 templates/dashboard.html 위에서 작업한다.

범위: A4 TODO 전부 — AI 카드 렌더를 카드 객체 입력의 순수 함수로 리팩터, 카드 아래 가로 스크롤 타임라인 Row(최신 포커스, 칩 클릭 시 상단 카드 교체, 카드 헤더에 일자+시각+type 상시 표시), 네이티브 input[type=date] 캘린더 피커와 briefings/index.json 연동, 과거 날짜 lazy fetch.

주의: 새 프레임워크/의존성 금지, 기존 인라인 JS/CSS 스타일과 CSS 변수(다크모드 포함) 재사용. briefings/ 데이터가 없는 구 배포본에서도 Row를 숨기고 기존 단일 카드로 동작해야 한다(A4 AC 3번).

완료 조건: A4 AC 3개. scripts/dev_dashboard.py + mock 데이터로 모바일 폭까지 확인. 브랜치 feat/a4-briefing-timeline.
```

## B1 — 시황/지표 2단 네비게이션 (즉시 착수 가능)

```
docs/design/README.md를 읽고 docs/design/track-b-market-overview.md의 B1 섹션을 구현해줘. 프론트(templates/dashboard.html) 전용 작업이고 데이터 수집 변경은 없다.

범위: B1 TODO 전부 — 루트 [시황|지표] 2단 사이드바 상태 머신(← 뒤로가기, localStorage 복원, 최초 기본값 시황>종합), metric.section/market_category 해석(필드 없으면 industry로 폴백), 시황 하위 메뉴 7개의 본문 렌더(기존 테이블/디테일/스파크라인 컴포넌트 재사용 — 새 레이아웃 금지), market_gauges 카드를 시황>종합으로 이동, 모바일 토글 메뉴 대응.

핵심 제약: B2 이전이므로 시황 지표 데이터가 아직 없다 — 시황 하위 메뉴는 비어 있어도 정상 동작하고, 구 dashboard.json(section 필드 없음)으로 콘솔 에러가 없어야 한다(B1 AC). 산업 탭의 기존 기능(드래그 정렬, 즐겨찾기)은 그대로 유지.

완료 조건: B1 AC 2개. 브랜치 feat/b1-market-nav. 이 PR은 A4보다 먼저 머지되어야 한다.
```

## B2 — 시황 데이터 수집 (B1 머지 후, 2개 PR로 분할)

### B2-① 수급·신용·공매도 (핵심)

```
docs/design/README.md와 docs/design/track-b-market-overview.md의 B2 섹션 중 B2-1(수급), B2-2(신용·예탁금·공매도)를 구현해줘. B1이 머지되어 있어 section:"market" 지표는 시황 탭에 자동 표시된다.

시작 전 필수: 문서의 ⚠️ 항목 검증 — KRX getJsonData의 bld 코드(투자자별 주식/선물/프로그램)와 FREESIS 엔드포인트를 실제 호출로 확인하고, 응답을 tests/fixtures에 저장한 뒤 파서를 픽스처 기반으로 테스트해줘. 검증 결과(실제 bld 코드, 필드명)를 PR 설명에 기록.

범위: market_flows.py 신설(KRX 투자자별 주식·선물·프로그램 수급), 2년 증분 백필(max_backfill_days_per_run 패턴), 20일 누적 파생 지표, chart_style:"flow_bars" 프론트 막대+누적선, FREESIS(신용융자/예탁금/CMA), 공매도(잔고 T+2 지연 표기), config.yaml market_overview 섹션.

제약: 모든 호출은 ThrottledSession 경유, 신규 호스트는 HOST_MIN_INTERVALS에 보수적으로 등록. 비공식 소스는 일 1회(풀빌드)만, 실패 시 지표 단위 error로 격리(빌드는 성공해야 함). 완료 조건: B2 AC 중 수급/신용 항목. 브랜치 feat/b2-flows.
```

### B2-② 자산군 보강 + 기존 지표 이관

```
docs/design/README.md와 docs/design/track-b-market-overview.md의 B2-3, B2-4, B2-5를 구현해줘.

범위: (1) B2-4 신규 지표 — 선물(ES=F/NQ=F, K200 선물가·베이시스·미결제약정), 한국 국고채 3Y/10Y·기울기·한미 금리차·기준금리, 금·Henry Hub·달러인덱스, BTC/ETH·김치프리미엄(Upbit), 엔캐리 모니터 6종(USD/JPY, JPY/KRW, CFTC COT 주간, JGB 10Y, 미일 금리차, 엔 실현변동성 — 텔레그램 알림은 범위 제외). (2) B2-3/B2-5 기존 지표 이관 — 문서의 완전 이관/병행 노출 표 그대로. (3) ADR·52주 신고저 계산 지표와 F&G/VKOSPI 지표화.

시작 전 필수: ⚠️ 항목(CFTC 계약코드, MOF CSV, Yahoo 심볼 JPYKRW=X·GC=F·DX-Y.NYB·^KS200, ECOS 아이템코드, KRX fut_bydd_trd, Upbit) 실제 호출 검증 후 결과를 PR 설명에 기록. 실패 시 문서의 폴백 사용.

절대 규칙: 이관 시 history_key 불변, 텔레그램 알림 rules의 지표 이름 불변(alerts: 의 VIX·코스피 PBR·환율 룰이 이관 후에도 동작해야 함 — B2 AC). 완료 조건: B2 AC 전부. 브랜치 feat/b2-assets.
```

## 기능 확장 프롬프트 (2026-07-09 추가)

각 기능의 실행 프롬프트는 해당 설계 문서 마지막 절에 있다 (중복 관리 방지를 위해 여기 복사하지 않음).
**투입 순서와 조건** — 프론트는 같은 템플릿 파일을 고치므로 동시에 1개 PR만:

| 순서 | Phase | 프롬프트 위치 | 투입 조건 |
|---|---|---|---|
| 1 | S1 전역 검색 | feature-metric-search.md 5절 | B1 머지 후 |
| 1.5 | S2-A 검색 품질 팩 | feature-search-v2.md 5절 | S1 직후 (S1 미착수면 합본 1PR 가능 — 프롬프트가 판단 지시) |
| 2 | C1 오버레이 비교 | feature-compare-overlay.md 8절 | S1 머지 후 |
| 3 | H1 시그널 이력 | feature-signal-history.md 5절 | C1 머지 후 (백엔드 포함 단일 PR) |
| 4 | A4 AI 타임라인 | 이 문서 A4 | A3 + H1 머지 후 |
| 5 | B2-③ 수급 전체 분해 | review-b2-investor-breakdown.md 7절 | B2-①·② 머지 후 (프론트 체인과 병렬 가능) |
| 6 | E1 이벤트 캘린더 | feature-event-calendar.md 6절 | B1 머지 후 (프론트 체인 빈 슬롯에) |
| 7 | G1 게이지 히스토리 | feature-gauge-history.md 5절 | B1 머지 후 (〃) |
| 8 | N1 개인 메모 | feature-metric-notes.md 6절 | 프론트 체인 이후 |
| 9 | Q2 CSV → Q1 히트맵 → Q3 PWA | feature-qol-pack.md 각 절 | 프론트 체인 이후, 순서대로 |

Q4(주간 아카이브)는 보류 — A3/A4 운영 후 재평가.

## B3 — 지표 해석 레이어 (B2 머지 후)

```
docs/design/README.md와 docs/design/track-b-market-overview.md의 B3 섹션을 구현해줘.

범위: B3 TODO 전부 — interpretation.py(퍼센타일 5구간 zone, 추세, polarity 규칙, 문장 템플릿 — LLM 호출 없음), config.yaml interpretation: 규칙(신용 스프레드·금리·유가·수급·심리 우선 등록, 나머지는 defaults의 가치판단 없는 서술형), 엔캐리 모니터 그룹 요약 배지(포지션 누적/중립/청산 진행 — B2-4e의 판정식), 디테일 패널 UI(zone 배지 + "계산 기반 해석" 캡션, AI 문구와 구분).

주의: 규칙 매칭 우선순위 id > name > group > industry를 테스트로 보증. polarity 미지정 지표에 좋다/나쁘다 단정 문구가 절대 나오면 안 된다(B3 AC). interpretation 필드 없는 구 페이로드 호환.

완료 조건: B3 AC 3개. 브랜치 feat/b3-interpretation.
```
