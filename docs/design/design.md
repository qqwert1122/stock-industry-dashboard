# 디자인 시스템 가이드 (design.md)

`templates/dashboard.html` 인라인 CSS(약 6,100줄)에서 실제 사용 중인 토큰·패턴을 추출해
**단일 기준**으로 확정한 문서다. 프론트 작업 시 새 스타일은 반드시 이 문서의 토큰·규칙을 따른다.
배치(메뉴 트리·상단 스택·고정 요소 좌표)는 [ia-consistency.md](ia-consistency.md)가 우선한다.

## 0. 원칙

1. **프레임워크 없음** — 인라인 CSS/JS 단일 템플릿(`templates/dashboard.html`) 유지. npm·빌드 도구 도입 금지.
2. **색은 변수로** — 새 색상은 `:root`와 `body.theme-dark`에 **쌍으로** CSS 변수를 정의하고 변수만 참조한다.
   하드코딩 hex는 캘린더 카테고리색처럼 라이트/다크 공용으로 검증된 경우만 예외.
3. **다크모드는 기본 요건** — 라이트만 만들고 끝내지 않는다. 모든 신규 컴포넌트는 두 테마에서 확인.
4. **파생색은 `color-mix`** — 배경 틴트 등은 `color-mix(in srgb, var(--chart-up) 8%, var(--surface))`
   패턴으로 기존 변수에서 파생시킨다. 유사한 새 hex를 늘리지 않는다.

## 1. 색상 토큰

### 1.1 기본 팔레트 (라이트 / 다크)

| 변수 | 라이트 | 다크 | 용도 |
|---|---|---|---|
| `--bg` | `#ffffff` | `#111111` | 페이지 배경 |
| `--surface` | `#ffffff` | `#151515` | 일반 표면 |
| `--sidebar` | `#f7f7f7` | `#181818` | 사이드바 배경 |
| `--panel` | `#ffffff` | `#1d1d1d` | 카드·패널 배경 |
| `--text` | `#171717` | `#f2f2f2` | 본문 텍스트 |
| `--muted` | `#6d6d6d` | `#a7a7a7` | 보조 텍스트 |
| `--line` | `#e6e6e6` | `#303030` | 테두리·구분선 |
| `--menu` / `--menu-active` | `#f0f0f0` / `#e6e6e6` | `#242424` / `#303030` | 메뉴 버튼 |
| `--detail-stat-bg` | `#f8f8f8` | `#1a1a1a` | 디테일 통계 셀 |
| `--shadow` | `0 8px 20px rgba(0,0,0,0.04)` | 같은 형태, 알파 0.18 | 카드 그림자 |

무채색 그레이스케일 기반. **채도 있는 색은 의미가 있을 때만** 쓴다(아래 1.2).

### 1.2 시맨틱 컬러

- **상승/하락 — 한국 관례 고정**: 상승 `--chart-up`(#f23645, 빨강) / 하락 `--chart-down`(#1f5eff, 파랑).
  등락 표시·시그널 트리거·차트 선 전부 이 두 변수만 사용. 초록=상승 같은 서구 관례 금지.
- **게이지 스케일**: `--gauge-cold`(파랑) → `--gauge-cool` → `--gauge-neutral`(노랑) →
  `--gauge-warm` → `--gauge-hot`(빨강). 연속 스케일은 `--gauge-gradient` 사용.
- **강조(액션·별표·메모)**: 즐겨찾기 `--favorite-star`(#f59e0b 계열), 메모 `--note-accent`(#f2b800).
- **AI 카드**: 시안→블루→인디고 저채도 그라디언트 `--ai-card-bg` + `--ai-card-border`.
  AI 관련 요소만 이 블루 톤을 쓴다 (일반 UI에 블루 강조 남용 금지).
- **시그널 상태**: 트리거 `--signal-trigger-*`(빨강 계열), 해제 `--signal-clear-*`(파랑 계열),
  백필 `--signal-backfill-*`(그레이). 배지·pill은 배경/텍스트 변수 쌍으로.
- **캘린더 카테고리** (하드코딩 허용 예외): Fed `#dc2626`, 한은 `#2563eb`, 미 지표 `#7c3aed`, 만기 `#c2410c`.

## 2. 타이포그래피

- 폰트 스택: `Inter, Pretendard, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`. 변경 금지.
- 크기 스케일 (자주 쓰는 순): **12px(기본 UI) · 13px(본문/버튼) · 11px(캡션·라벨) · 12.5/11.5px(미세 조정)**
  · 14–16px(부제·강조 값) · 18–21px(섹션 제목) · 26px+(히어로 수치, 드묾).
  새 텍스트는 이 스케일에서 고른다. 9–10px는 극히 제한적(축 라벨 등).
- 굵기 관례: 400(본문) · 500(살짝 강조) · 600–650(라벨·칩·버튼) · 700–760(제목·활성 메뉴) ·
  780–820(수치 강조) · 900(히어로). Inter 가변 웨이트를 활용한 650/760 같은 중간값이 이 프로젝트의 시그니처 —
  "조금 더 굵게"가 필요하면 50 단위로 조정한다.
- `letter-spacing: 0` 기본. 자간 조정은 대문자 라벨 등 명확한 이유가 있을 때만.

## 3. 레이아웃 · 반응형

- 셸: `--shell-max-width: 1540px`, 좌우 패딩 24px, 상단 22px, `--sidebar-width: 232px`, 그리드 gap 26px.
- 브레이크포인트는 **두 개뿐**: `1180px`(사이드바 접힘 등 중간), `760px`(모바일). 새 값 추가 금지.
- 고정 요소는 `env(safe-area-inset-*)`를 항상 반영 (`max(18px, env(safe-area-inset-right))` 패턴).
- 간격 스케일: 요소 내부 gap은 4·6·7·8·10·12·14px에서 선택 (7px·8px이 최빈값), 섹션 사이는 16–28px.
- 좌표·스택 순서·Drawer 동시 열림 금지 등은 [ia-consistency.md](ia-consistency.md) 3절 준수.

## 4. 컴포넌트 패턴

### 4.1 카드
- **지표 카드 `.metric`**: `border: 1px solid var(--line)` + `border-radius: 8px` + `background: var(--panel)`,
  내부 패딩 15px, `min-height: 348px` 그리드(헤더/본문/차트 158px).
- **부드러운 카드**(시그널 카드 등 피드형): 테두리 없이 `border-radius: 18–24px` + 배경색 구분.
- 그림자는 `var(--shadow)` / `var(--menu-shadow)`만. 임의 box-shadow 작성 금지.

### 4.2 칩 · 배지 · 버튼
- **칩(필터·토글)**: `border-radius: var(--chip-radius)`(16px), `min-height: 32px`, 패딩 `0 15px`,
  `font-size: 12px; font-weight: 650`. 활성 상태는 `aria-pressed="true"` 셀렉터로 배경/텍스트 반전
  (`--signal-filter-active-bg/text` 패턴).
- **완전 pill**(상태 배지·작은 카운터): `border-radius: 999px`.
- **원형 아이콘 버튼**(우상단 검색·히스토리, 스크롤탑, 모바일 토글): 40–46px 정사각 + `border-radius: 999px`
  + `1px solid var(--line)`. 신규 고정 버튼도 이 규격.
- **메뉴형 버튼**(설정 등): `border-radius: 14px`, `min-height: 40px`, `background: var(--menu)`,
  13px/760 텍스트.
- 상태 표현은 클래스 토글보다 **ARIA 속성**(`aria-pressed`, `aria-current`, `aria-expanded`)을
  스타일 훅으로 쓰는 기존 관례를 따른다.

### 4.3 라운딩 요약
`999px`(pill·원형) > `--chip-radius` 16px(칩) > `24px`(큰 부드러운 카드) > `14px`(메뉴 버튼) >
`8px`(지표 카드·테이블 셀 등 정보 밀도 높은 박스) > `6px`(인풋·미니 요소).
이 외 값(13px, 10px 등)을 새로 만들지 않는다.

## 5. 모션

- 인터랙션(호버·토글·등장): **140–260ms ease**. 기본값 180ms.
- **테마 전환만 520ms** — `body.theme-ready`가 붙은 뒤에만 transition 적용(첫 페인트 깜빡임 방지).
  새 컴포넌트가 테마 색을 쓰면 `body.theme-ready .새클래스` 목록에 추가해 520ms 전환에 동참시킨다.
- 루프 애니메이션(`updateDotBreath`, `moverTickerFlow` 등)은 최소화하고,
  `@media (prefers-reduced-motion: reduce)`에서 반드시 끈다.

## 6. z-index 층

실사용 값 기준의 층 구조. 새 요소는 소속 층의 값을 재사용하고, 새 층 발명 금지.

| 층 | 값 | 요소 |
|---|---|---|
| 콘텐츠 내 부유 | 1–20 | 카드 내 오버레이, sticky 헤더 |
| 사이드바 | 40 | `.sidebar` |
| 고정 버튼 | 57–60 | 스크롤탑, 우상단 버튼 그룹 |
| 검색 바·티커 | 70–90 | 검색 필드, 무버 티커 |
| 배너 | 110 | 오프라인 배너 |
| Drawer·모달 | 119–120 | 백드롭 119, 패널 120 |

## 7. 접근성 · 기타 관례

- 스크린리더 전용 텍스트는 `.sr-only` 재사용.
- 아이콘 버튼은 `aria-label` 필수, 열림 상태는 `aria-expanded`.
- 색만으로 의미 전달 금지 — 등락은 부호(＋/−)나 화살표 병기.
- 포커스 아웃라인은 `color-mix(... 45%, transparent)` 2px 패턴.
- 문구·주석은 한국어 (코드 식별자는 영어).

## 8. 신규 컴포넌트 체크리스트

- [ ] 색상: 변수만 사용, 새 변수는 `:root` + `body.theme-dark` 쌍으로 정의
- [ ] 라이트/다크 두 테마에서 렌더 확인 (`scripts/dev_dashboard.py` + mock)
- [ ] 폰트 크기·굵기가 2절 스케일 안에 있는가
- [ ] 라운딩이 4.3절 요약 안에 있는가
- [ ] 테마 전환 대상이면 `body.theme-ready` 목록에 추가했는가
- [ ] 모바일(760px)에서 확인, 고정 요소면 safe-area 반영 + ia-consistency 좌표 준수
- [ ] `prefers-reduced-motion` 대응 (루프 애니메이션이 있다면)
