# 기능 설계 — Tier 2 QoL 팩 (Q1~Q4)

상태: 확정 (2026-07-09). 독립적인 소규모 기능 4개 — **각 Phase가 별도 PR** (프롬프트도 개별).
공통 의존성: 프론트 체인(B1 → S1 → C1 → H1 → A4) 이후 순차 투입. 권장 순서: Q2 → Q1 → Q3 (Q4는 보류).

---

## Q1. 일일 변화 히트맵

목적: "오늘 뭐가 움직였나"를 한눈에 — AI 카드의 시각 버전. 데이터는 기존 `daily_changes` 재사용.

- 위치: 시황>종합, AI 카드 아래 (Track A4 타임라인 Row가 있으면 그 아래).
- 형태: 오늘 갱신된 지표(daily_changes.metrics)를 동일 크기 타일 그리드로. 타일 = 지표 축약명 +
  change_pct. 색: 기존 상승/하락 팔레트를 5단계 강도(±0.5/1.5/3%+)로 — **색상만으로 구분하지 않고
  수치 병기** (접근성).
- 정렬: |change_pct| 내림차순. 산업/시황 구분 라벨은 타일 하단 캡션.
- 타일 클릭 → 해당 지표 디테일. 갱신 지표 0개인 날은 섹션 자체를 숨김.
- 매도/매수 그로스 지표(B2-③)는 제외 (순매수와 중복 신호 — review-b2-investor-breakdown.md 4-3과 일관).

TODO: 타일 그리드 + 5단계 색 + 클릭 이동 + 빈 상태 + 그로스 제외 필터.
AC: 갱신 있는 날 히트맵이 변화율 순으로 보이고 타일 클릭 시 디테일로 이동. 다크모드 정상.

실행 프롬프트:
```
docs/design/README.md 공통 지침을 읽고 docs/design/feature-qol-pack.md의 Q1(일일 변화 히트맵)을 구현해줘. daily_changes 페이로드 재사용, 새 의존성 금지, 기존 팔레트 CSS 변수 확장. 완료 조건: Q1 AC. 브랜치 feat/q1-daily-heatmap.
```

---

## Q2. CSV 내보내기

목적: 지표 시계열을 직접 분석하고 싶을 때. 전부 클라이언트 사이드 (Blob 다운로드).

- 디테일 패널에 다운로드 버튼 (아이콘, 별표·메모 버튼 군 옆): 현재 지표의 long_history 전체를
  `date,value` CSV로. 파일명 `{지표명}_{오늘날짜}.csv` (파일명 안전화).
- C1 비교 모드일 때: 겹친 시리즈 전체를 wide 포맷(`date,시리즈1,시리즈2,…`)으로 — 관측일이 다르면
  빈 칸 (보간 금지).
- UTF-8 BOM 포함 (엑셀 한글 호환).

TODO: 단일 CSV + 비교 wide CSV + BOM + 파일명 안전화.
AC: 월간 지표 CSV가 엑셀에서 한글 깨짐 없이 열린다. 비교 모드에서 wide CSV가 내려온다.

실행 프롬프트:
```
docs/design/README.md 공통 지침을 읽고 docs/design/feature-qol-pack.md의 Q2(CSV 내보내기)를 구현해줘. 클라이언트 사이드 Blob만 사용, C1 비교 모드 wide 포맷 포함(C1 미머지 상태면 단일 CSV만 하고 PR 설명에 명시). 완료 조건: Q2 AC. 브랜치 feat/q2-csv-export.
```

---

## Q3. PWA 설치 지원

목적: 폰 홈화면에 앱처럼 설치 + 마지막 데이터 오프라인 열람.

- `site/manifest.webmanifest`: 이름·테마색(라이트/다크)·아이콘(512/192px 신규 제작, assets에 추가)·
  `start_url`/`scope`는 **GitHub Pages 하위 경로(`/stock-industry-dashboard/`) 기준** — 절대경로 주의.
- 서비스워커 캐시 전략 (신선도 요구와의 충돌 방지가 핵심):
  - 정적 자산(아이콘·manifest): cache-first
  - **`index.html`과 `data/*.json`: network-first, 실패 시 캐시 폴백** — 15분 갱신(A2)을 SW 캐시가
    막으면 안 된다. stale 데이터 표시 중에는 상단에 "오프라인 — HH:MM 기준 데이터" 배너.
  - SW 버전 = 빌드 시각 주입(`__BUILD_TS__` 치환) → 배포마다 자동 갱신, skipWaiting.
- iOS 사파리 한계(부분 지원)는 감수 — 설치 유도 배너는 만들지 않음 (브라우저 기본 동작만).

TODO: manifest + 아이콘 + SW(전략·버전 주입) + 오프라인 배너 + 빌드 산출 경로 연결.
AC: 모바일 크롬에서 설치 가능. 비행기모드에서 마지막 데이터가 배너와 함께 열린다.
새 배포 후 재방문 시 15분 내 최신 데이터가 보인다 (network-first 검증).

실행 프롬프트:
```
docs/design/README.md 공통 지침을 읽고 docs/design/feature-qol-pack.md의 Q3(PWA)를 구현해줘. 핵심 제약: index.html과 data/*.json은 반드시 network-first — 서비스워커가 데이터 신선도를 해치면 안 된다. GitHub Pages 하위 경로 scope 주의. 완료 조건: Q3 AC. 브랜치 feat/q3-pwa.
```

---

## Q4. 주간 리포트 아카이브 — **보류**

텔레그램 주간 다이제스트(alerts.py, 월요일 발송)를 사이트 페이지로도 보여주자는 안.
**Track A3의 마감(close) 카드 + A4 캘린더 피커가 배포되면 "하루/기간 되돌아보기" 요구를 상당 부분
흡수**하므로, A3/A4 운영 후에도 주간 단위 요약이 아쉬우면 그때 설계한다. 지금 만들면 중복 위험.
