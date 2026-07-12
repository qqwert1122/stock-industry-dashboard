from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path
from textwrap import dedent

from macro_telegram_report.dashboard import make_metric
from macro_telegram_report.future_timeline import (
    build_future_timeline,
    check_reading_links,
    load_future_yaml,
    track_record_status,
    write_future_timeline,
)
from macro_telegram_report.site_output import load_dashboard_template


def write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).strip() + "\n", encoding="utf-8")


def test_future_timeline_resolves_metrics_and_company_chips(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: agi
          name: 범용 인공지능
          category: AI
          predicted:
            year: 2029
            source_label: 테스트 예측
            source: https://example.com/prediction
          status: upcoming
          as_of: 2026-07-10
          what: 여러 일을 배우는 AI입니다.
          why: 지식노동 비용이 바뀔 수 있습니다.
          now: 아직 신뢰성 검증이 필요합니다.
          glossary: [agi]
          metrics: [Microsoft]
          companies: [MSFT]
        """,
    )
    write_yaml(
        future_dir / "glossary.yaml",
        """
        - id: agi
          term: AGI
          short: 범용 인공지능입니다.
          source: https://example.com/glossary
          learn_more: https://example.com/agi
        """,
    )
    write_yaml(
        future_dir / "readings.yaml",
        """
        - technology: agi
          items:
            - title: AGI 입문
              url: https://example.com/agi
              type: 글
              level: 입문
              lang: KO
              effort: 10분
              why: AGI의 기본 의미를 잡을 수 있습니다.
              checked_at: 2026-07-10
              curated_by: human
        """,
    )
    metric = make_metric(
        industry="데이터인프라",
        name="Microsoft(MSFT)",
        source="Yahoo",
        source_url="https://finance.yahoo.com/quote/MSFT",
        frequency="일간",
        automation="무료 공개 JSON 자동 수집",
        status="ok",
        value=501.0,
        unit="$",
        previous_value=496.0,
        history=[(date(2026, 7, 9), 496.0), (date(2026, 7, 10), 501.0)],
        history_key="equity-MSFT",
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [metric], today=date(2026, 7, 10))

    assert document["warnings"] == []
    tech = document["technologies"][0]
    assert tech["metrics"][0]["id"] == metric["id"]
    assert tech["companies"][0]["metric_id"] == metric["id"]
    assert tech["companies"][0]["change_pct_label"] == "+1.0%"
    assert tech["readings"][0]["level"] == "입문"
    assert document["glossary"]["agi"]["learn_more"] == "https://example.com/agi"


def test_future_breakdown_computes_ladder_gap_and_bottleneck(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: robotaxi
          name: 로보택시
          category: 로봇·모빌리티
          predicted: {year: 2027, source_label: 테스트, source: https://example.com/prediction}
          status: upcoming
          as_of: 2026-07-10
          what: 무인 택시입니다.
          why: 이동 비용을 바꿀 수 있습니다.
          now: 일부 도시에서 운행 중입니다.
          bottleneck: "병목: 손재주"
        """,
    )
    write_yaml(
        future_dir / "glossary.yaml",
        """
        - id: l4
          term: L4
          short: 자율주행 단계입니다.
          source: https://example.com
        """,
    )
    write_yaml(
        future_dir / "ladders.yaml",
        """
        - id: dexterity
          name: 손재주 단계
          source: https://example.com/ladder
          rungs:
            - {level: A, label: 데모, desc: 데모 단계입니다.}
            - {level: B, label: 반복 작업, desc: 반복 작업 단계입니다.}
            - {level: C, label: 범용 작업, desc: 범용 작업 단계입니다.}
        """,
    )
    write_yaml(
        future_dir / "breakdown.yaml",
        """
        - tech: robotaxi
          requirements:
            - id: dexterity
              name: 손재주
              ladder: dexterity
              required_rung: C
              current_rung: A
              what: 물체를 안정적으로 다뤄야 합니다.
              gap: 두 단계가 남았습니다.
              confidence: high
              as_of: 2026-07-10
              source: https://example.com/source
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 10))

    requirement = document["technologies"][0]["breakdown"]["requirements"][0]
    assert requirement["gap_steps"] == 2
    assert requirement["bottleneck_score"] == 2
    assert requirement["is_bottleneck"] is True
    assert requirement["target_label"] == "범용 작업"
    assert document["breakdown"]["summary"]["requirement_count"] == 1
    assert not [warning for warning in document["warnings"] if warning["kind"].startswith("future_breakdown")]


def test_future_breakdown_marks_low_confidence_stale_and_resolves_links(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: humanoid-robots
          name: 휴머노이드 로봇
          category: 로봇·모빌리티
          predicted: {year: 2031, source_label: 테스트, source: https://example.com/prediction}
          status: distant
          as_of: 2026-07-10
          what: 사람 공간에서 일하는 로봇입니다.
          why: 노동 비용을 바꿀 수 있습니다.
          now: 시제품 단계입니다.
          bottleneck: "병목: 가격"
        """,
    )
    write_yaml(
        future_dir / "glossary.yaml",
        """
        - id: trl
          term: TRL
          short: 기술 성숙도입니다.
          source: https://example.com
        """,
    )
    write_yaml(
        future_dir / "breakdown.yaml",
        """
        - tech: humanoid-robots
          requirements:
            - id: robot-cost
              name: 가격
              target_label: 사람 임금과 비교 가능한 총소유비용
              current_label: 제품 가격과 유지비 검증 중
              what: 현장 총비용이 낮아져야 합니다.
              gap: 실제 총소유비용은 아직 낮은 확신으로 봐야 합니다.
              confidence: low
              as_of: 2025-01-01
              source: https://example.com/cost
              metric_ref: Tesla(TSLA)
              pursuing:
                - {label: Tesla Optimus, symbol: TSLA}
              gap_score: 3
        """,
    )
    metric = make_metric(
        industry="로봇",
        name="Tesla(TSLA)",
        source="Yahoo",
        source_url="https://finance.yahoo.com/quote/TSLA",
        frequency="일간",
        automation="무료 공개 JSON 자동 수집",
        status="ok",
        value=250.0,
        unit="$",
        previous_value=245.0,
        history=[(date(2026, 7, 9), 245.0), (date(2026, 7, 10), 250.0)],
        history_key="equity-TSLA",
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [metric], today=date(2026, 7, 10))

    requirement = document["technologies"][0]["breakdown"]["requirements"][0]
    assert requirement["confidence"] == "low"
    assert requirement["stale"] is True
    assert requirement["metric"]["id"] == metric["id"]
    assert requirement["pursuing"][0]["metric_id"] == metric["id"]
    assert requirement["is_bottleneck"] is True
    assert any(warning["kind"] == "future_breakdown" and "180일" in warning["message"] for warning in document["warnings"])


def test_future_breakdown_warns_for_unknown_ladder_rung(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: agi
          name: AGI
          category: AI
          predicted: {year: 2029, source_label: 테스트, source: https://example.com}
          status: upcoming
          as_of: 2026-07-10
          what: AI입니다.
          why: 생산성이 바뀔 수 있습니다.
          now: 발전 중입니다.
          bottleneck: "병목: 가속기"
        """,
    )
    write_yaml(
        future_dir / "glossary.yaml",
        """
        - id: agi
          term: AGI
          short: 범용 인공지능입니다.
          source: https://example.com
        """,
    )
    write_yaml(
        future_dir / "ladders.yaml",
        """
        - id: accelerator
          name: 가속기
          source: https://example.com/ladder
          rungs:
            - {level: Hopper, label: Hopper, desc: 이전 세대입니다.}
            - {level: Blackwell, label: Blackwell, desc: 현재 세대입니다.}
        """,
    )
    write_yaml(
        future_dir / "breakdown.yaml",
        """
        - tech: agi
          requirements:
            - id: accelerator
              name: 가속기
              ladder: accelerator
              required_rung: Rubin
              current_rung: Hopper
              what: 가속기 세대가 중요합니다.
              gap: 다음 세대가 필요합니다.
              confidence: medium
              as_of: 2026-07-10
              source: https://example.com/source
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 10))

    assert any("required_rung=Rubin" in warning["message"] for warning in document["warnings"])


def test_future_timeline_warns_but_builds_for_missing_prediction_source(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: missing-source
          name: 출처 누락 예측
          category: AI
          predicted:
            year: 2029
            source_label: 테스트 예측
          status: upcoming
          as_of: 2026-07-10
          what: 출처 경고를 확인하는 카드입니다.
          why: 빌드는 계속되어야 합니다.
          now: 경고만 남깁니다.
        """,
    )
    write_yaml(
        future_dir / "glossary.yaml",
        """
        - id: agi
          term: AGI
          short: 범용 인공지능입니다.
          source: https://example.com/glossary
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 10))

    assert document["summary"]["technology_count"] == 1
    assert any("predicted.source" in warning["message"] for warning in document["warnings"])


def test_future_readings_warns_when_beginner_item_is_missing(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: robotaxi
          name: 로보택시
          category: 로봇·모빌리티
          predicted: {year: 2027, source_label: 테스트, source: https://example.com}
          status: upcoming
          as_of: 2026-07-10
          what: 자율주행 호출 서비스입니다.
          why: 이동 비용을 바꿀 수 있습니다.
          now: 일부 도시에서 테스트 중입니다.
        """,
    )
    write_yaml(
        future_dir / "glossary.yaml",
        """
        - id: l4
          term: L4
          short: 자율주행 단계입니다.
          source: https://example.com
        """,
    )
    write_yaml(
        future_dir / "readings.yaml",
        """
        - technology: robotaxi
          items:
            - title: 심화 자료
              url: https://example.com/deep
              type: 리포트
              level: 심화
              lang: EN
              effort: 30분
              why: 더 깊게 볼 수 있습니다.
              checked_at: 2026-07-10
              curated_by: human
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 10))

    assert any(warning["kind"] == "reading" and "입문" in warning["message"] for warning in document["warnings"])


def test_future_readings_preserves_common_and_caps_level_count(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: agi
          name: AGI
          category: AI
          predicted: {year: 2029, source_label: 테스트, source: https://example.com}
          status: upcoming
          as_of: 2026-07-10
          what: AI입니다.
          why: 생산성이 바뀔 수 있습니다.
          now: 발전 중입니다.
        """,
    )
    write_yaml(
        future_dir / "glossary.yaml",
        """
        - id: agi
          term: AGI
          short: 범용 인공지능입니다.
          source: https://example.com
        """,
    )
    items = "\n".join(
        f"""
            - title: 입문 {index}
              url: https://example.com/{index}
              type: 글
              level: 입문
              lang: KO
              effort: 5분
              why: 읽을거리입니다.
              checked_at: 2026-07-10
              curated_by: human
        """.rstrip()
        for index in range(9)
    )
    write_yaml(
        future_dir / "readings.yaml",
        f"""
        - technology: _common
          items:
            - title: 공통 입문
              url: https://example.com/common
              type: 글
              level: 입문
              lang: KO
              effort: 5분
              why: 공통으로 읽을 수 있습니다.
              checked_at: 2026-07-10
              curated_by: agent
        - technology: agi
          items:
        {items}
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 10))

    assert len(document["technologies"][0]["readings"]) == 8
    assert document["common_readings"][0]["auto_collected"] is True
    assert any("8개" in warning["message"] for warning in document["warnings"])


def test_track_record_status_boundaries_are_inclusive() -> None:
    today = date(2026, 7, 10)

    assert track_record_status(2005, 2003, today) == "on_time"
    assert track_record_status(2005, 2007, today) == "on_time"
    assert track_record_status(2005, 2002, today) == "early"
    assert track_record_status(2005, 2008, today) == "late"
    assert track_record_status(2016, None, today) == "missed"
    assert track_record_status(2017, None, today) == "pending"


def test_track_record_builds_stats_and_warns_on_manual_status_mismatch(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: agi
          name: 범용 인공지능
          category: AI
          predicted:
            year: 2029
            source_label: 커즈와일
            source: https://example.com/kurzweil
          status: upcoming
          as_of: 2026-07-10
          what: 여러 일을 배우는 AI입니다.
          why: 생산성이 바뀔 수 있습니다.
          now: 발전 중입니다.
        """,
    )
    write_yaml(
        future_dir / "glossary.yaml",
        """
        - id: agi
          term: AGI
          short: 범용 인공지능입니다.
          source: https://example.com
        """,
    )
    items = "\n".join(
        f"""
        - id: k-{index}
          name: 커즈와일 예측 {index}
          predicted_by: 레이 커즈와일
          predicted_by_en: Ray Kurzweil
          by_id: kurzweil
          predicted_in: 1999
          predicted_for: 2009년
          predicted_for_year: 2009
          actual_year: {2009 + index}
          actual_label: 판정 기준
          status: {"missed" if index == 0 else "late"}
          what: 무엇을 예측했는지 설명합니다.
          outcome: 실제 결과를 설명합니다.
          lesson: 왜 맞거나 빗나갔는지 설명합니다.
          source: https://example.com/kurzweil-{index}
        """.rstrip()
        for index in range(5)
    )
    write_yaml(future_dir / "track_record.yaml", items)

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 10))

    subject = next(item for item in document["track_record"]["subjects"] if item["id"] == "kurzweil")
    assert subject["expose_score"] is True
    assert subject["judged_count"] == 5
    assert subject["on_time_count"] == 3
    assert "과거 적중 3/5" == subject["score_label"]
    assert document["technologies"][0]["track_record_subject"]["score_label"] == "과거 적중 3/5"
    assert any(warning["kind"] == "track_record_status" for warning in document["warnings"])


def test_achieved_future_technology_is_auto_included_in_track_record(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: commercial-space
          name: 우주 상업화
          category: 우주
          predicted:
            year: 2026
            source_label: 공개 발사 지표
            source: https://example.com/launch
          status: achieved
          as_of: 2026-07-10
          what: 민간 우주 활동입니다.
          why: 발사 비용을 바꿀 수 있습니다.
          now: 민간 발사가 일상이 됐습니다.
        """,
    )
    write_yaml(
        future_dir / "glossary.yaml",
        """
        - id: trl
          term: TRL
          short: 기술 성숙도입니다.
          source: https://example.com
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 10))

    auto_items = [item for item in document["track_record"]["items"] if item["auto_included"]]
    assert len(auto_items) == 1
    assert auto_items[0]["id"] == "future-commercial-space"
    assert auto_items[0]["status"] == "on_time"


class FakeResponse:
    status_code = 404
    headers: dict[str, str] = {}


class FakeSession:
    def head(self, *_args, **_kwargs):
        return FakeResponse()

    def get(self, *_args, **_kwargs):
        return FakeResponse()


def test_reading_link_check_warns_after_two_consecutive_failures(tmp_path: Path) -> None:
    status_path = tmp_path / "link_status.json"
    status_path.write_text(
        '{"version":1,"links":{"https://example.com/dead":{"consecutive_failures":1}}}',
        encoding="utf-8",
    )

    warnings = check_reading_links(
        [{"url": "https://example.com/dead"}],
        session=FakeSession(),
        status_path=status_path,
        today=date(2026, 7, 10),
    )

    assert warnings and "2회 연속 실패" in warnings[0]["message"]


def test_write_future_timeline_outputs_json(tmp_path: Path) -> None:
    target = tmp_path / "site" / "data" / "future.json"
    write_future_timeline(target, {"version": 1, "technologies": []})

    assert target.exists()
    assert '"technologies": []' in target.read_text(encoding="utf-8")


def test_future_expansion_content_covers_all_seven_technologies() -> None:
    future_dir = Path(__file__).resolve().parents[1] / "data" / "future"
    document = build_future_timeline(
        {"future": {"dir": str(future_dir)}},
        [],
        today=date(2026, 7, 12),
    )
    expected = {"quantum", "bci", "future-food", "uam", "carbon-capture", "geoengineering", "spatial"}
    technologies = {item["id"]: item for item in document["technologies"] if item["id"] in expected}

    assert set(technologies) == expected
    assert {"컴퓨팅", "인간증강", "식량", "기후"}.issubset(document["categories"])
    assert all(item["breakdown"]["requirements"] for item in technologies.values())
    assert all(item["readings"] for item in technologies.values())
    assert all(item["bottleneck"] for item in technologies.values())


def test_future_expansion_investability_and_governance_rules() -> None:
    future_dir = Path(__file__).resolve().parents[1] / "data" / "future"
    document = build_future_timeline(
        {"future": {"dir": str(future_dir)}},
        [],
        today=date(2026, 7, 12),
    )
    technologies = {item["id"]: item for item in document["technologies"]}

    assert technologies["bci"]["investable"] == "false"
    assert technologies["bci"]["companies"] == []
    assert technologies["bci"]["private_players"]
    assert technologies["future-food"]["investable"] == "partial"
    assert technologies["future-food"]["private_players"]
    assert technologies["geoengineering"]["nature"] == "governance"
    assert technologies["geoengineering"]["predicted"] is None
    assert technologies["geoengineering"]["status"] == "watch"
    assert technologies["geoengineering"]["band"] == "연도 미정 트랙"
    assert technologies["geoengineering"]["issues"]
    assert all(item["kind"] != "ladder" for item in technologies["geoengineering"]["breakdown"]["requirements"])
    assert not any(warning["kind"] == "prediction" and warning["id"] == "geoengineering" for warning in document["warnings"])


def test_future_expansion_template_reuses_cards_with_new_branches() -> None:
    template = load_dashboard_template()

    assert 'tech.status === "watch"' in template
    assert 'futureNoInvestableCompanies' in template
    assert 'futurePartialInvesting' in template
    assert 'futureGovernanceIssues' in template
    assert 'future-card ${tech.status === "achieved"' in template


def test_future_roadmap_merges_prediction_and_revision_ghost(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: robotaxi
          name: 로보택시
          category: 로봇
          status: upcoming
          as_of: 2026-07-12
          what: 설명
          why: 의미
          now: 현재
          predicted:
            year: 2029
            source_label: 외부 예측
            source: https://example.com/prediction
        """,
    )
    write_yaml(
        future_dir / "roadmap.yaml",
        """
        - tech: robotaxi
          as_of: 2026-07-12
          phases:
            - id: adoption
              name: 대중화
              start: 2029
              end: 2033
              status: projected
              desc: 일상 교통수단이 되는 구간입니다.
              basis: 도시 확장 속도를 이은 추정입니다.
              confidence: low
              revisions:
                - {date: 2026-01, start: 2028, end: 2032, note: 최초 추정}
                - {date: 2026-07, start: 2029, end: 2033, note: 1년 순연}
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 12))
    roadmap = document["technologies"][0]["roadmap"]

    assert roadmap["markers"][0]["year"] == 2029
    assert roadmap["markers"][0]["type"] == "prediction"
    assert roadmap["phases"][0]["ghost"] == {
        "start": 2028.0,
        "end": 2032.0,
        "date": "2026-01",
        "shift_years": 1.0,
        "direction": "delayed",
    }


def test_future_roadmap_warns_for_missing_basis_and_status_conflicts(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: sample
          name: 샘플
          category: 기술
          status: upcoming
          as_of: 2026-07-12
          what: 설명
          why: 의미
          now: 현재
          predicted:
            year: 2030
            source_label: 예측
            source: https://example.com
        """,
    )
    write_yaml(
        future_dir / "roadmap.yaml",
        """
        - tech: sample
          phases:
            - {id: future-done, name: 미래 완료, start: 2026, end: 2028, status: done, desc: 설명, confidence: high}
            - {id: past-active, name: 과거 진행, start: 2020, end: 2024, status: active, desc: 설명, confidence: high}
            - {id: no-basis, name: 근거 없음, start: 2028, end: 2030, status: projected, desc: 설명, confidence: low}
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 12))
    warning_kinds = [warning["kind"] for warning in document["warnings"]]

    assert "future_roadmap_basis" in warning_kinds
    assert warning_kinds.count("future_roadmap_status") == 2


def test_future_roadmap_excludes_governance_and_merges_changelog(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "technologies.yaml",
        """
        - id: product
          name: 제품 기술
          category: 기술
          nature: product
          status: upcoming
          as_of: 2026-07-12
          what: 설명
          why: 의미
          now: 현재
          predicted: {year: 2030, source_label: 예측, source: https://example.com}
        - id: governance
          name: 거버넌스 기술
          category: 기술
          nature: governance
          investable: false
          status: watch
          as_of: 2026-07-12
          what: 설명
          why: 의미
          now: 현재
          predicted: null
        """,
    )
    write_yaml(
        future_dir / "roadmap.yaml",
        """
        - tech: product
          phases:
            - {id: launch, name: 출시, start: 2025, end: 2028, status: active, desc: 설명, basis: 공개 일정, confidence: high}
        - tech: governance
          phases:
            - {id: debate, name: 논의, start: 2025, end: 2030, status: active, desc: 설명, basis: 국제 논의, confidence: high}
        """,
    )
    write_yaml(
        future_dir / "changelog.yaml",
        """
        - id: product-demo
          tech: product
          date: 2026-05-01
          status: achieved
          title: 시제품 공개
          title_en: Prototype unveiled
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 12))
    technologies = {item["id"]: item for item in document["technologies"]}

    assert technologies["governance"]["roadmap"] is None
    assert any(marker["ref"] == "f3" and marker["type"] == "achieved" for marker in technologies["product"]["roadmap"]["markers"])


def test_future_roadmap_real_content_and_svg_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    document = build_future_timeline(
        {"future": {"dir": str(root / "data" / "future")}},
        [],
        today=date(2026, 7, 12),
    )
    technologies = {item["id"]: item for item in document["technologies"]}
    template = load_dashboard_template()

    assert document["roadmap"]["summary"] == {"technology_count": 12, "phase_count": 50}
    assert technologies["robotaxi"]["roadmap"]["phases"]
    assert technologies["geoengineering"]["roadmap"] is None
    assert "future-roadmap-svg" in template
    assert "stroke-dasharray: 5 4" in template
    assert "roadmap-gradient-" in template
    assert "future-roadmap-ghost" in template


def test_future_company_arc_preserves_market_caps_endings_and_alternates(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "company_arcs.yaml",
        """
        - id: chips
          name: 반도체
          as_of: 2026
          companies:
            - symbol: LIVE
              name: 생존 기업
              listed: 2000
              end: ongoing
              metric: market_cap
              unit: usd_billion
              confidence: exact
              source_url: https://example.com/live
              series: [{y: 2000, v: 2}, {y: 2001, v: 4}, {y: 2002, v: 1}]
            - symbol: DEAD
              name: 사라진 기업
              listed: 1998
              end: acquired
              end_year: 2002
              end_note: 경쟁사에 인수
              metric: market_cap
              unit: usd_billion
              confidence: approx
              source_url: https://example.com/dead
              series: [{y: 1998, v: 10}, {y: 2000, v: 30}, {y: 2002, v: 12}]
            - symbol: SALES
              name: 매출 기업
              listed: 1999
              end: ongoing
              metric: revenue
              metric_label: 매출 기준
              confidence: exact
              source_url: https://example.com/sales
              series: [{y: 1999, v: 5}, {y: 2000, v: 6}, {y: 2001, v: 9}]
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 12))
    arc = document["company_arcs"][0]

    assert arc["companies"][0]["series"] == [
        {"y": 2000, "v": 2.0},
        {"y": 2001, "v": 4.0},
        {"y": 2002, "v": 1.0},
    ]
    assert arc["companies"][1]["end"] == "acquired"
    assert arc["companies"][0]["metric"] == "market_cap"
    assert arc["companies"][0]["unit"] == "usd_billion"
    assert arc["companies"][2]["metric_label"] == "매출 기준"
    assert not any(warning["kind"] == "future_company_arc_survivorship" for warning in document["warnings"])


def test_future_company_arc_warns_for_sources_survivorship_and_year_conflicts(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "company_arcs.yaml",
        """
        - id: warning-arc
          name: 경고 아크
          as_of: 2025
          companies:
            - symbol: A
              name: A
              listed: 2002
              end: ongoing
              metric: price
              series: [{y: 2000, v: 1}, {y: 2001, v: 2}, {y: 2002, v: 3}]
            - symbol: B
              name: B
              listed: 2000
              end: ongoing
              metric: revenue
              source_url: https://example.com/b
              series: [{y: 2000, v: 1}, {y: 2001, v: 2}, {y: 2002, v: 3}]
            - symbol: C
              name: C
              listed: 2000
              end: ongoing
              metric: price
              source_url: https://example.com/c
              series: [{y: 2000, v: 1}, {y: 2001, v: 2}, {y: 2002, v: 3}]
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 12))
    warning_kinds = {warning["kind"] for warning in document["warnings"]}

    assert "future_company_arc_source" in warning_kinds
    assert "future_company_arc_metric" in warning_kinds
    assert "future_company_arc_survivorship" in warning_kinds
    assert "future_company_arc_year" in warning_kinds


def test_future_company_arc_real_content_and_svg_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    document = build_future_timeline(
        {"future": {"dir": str(root / "data" / "future")}},
        [],
        today=date(2026, 7, 12),
    )
    template = load_dashboard_template()
    arcs = document["company_arcs"]

    assert len(arcs) == 5
    assert sum(len(arc["companies"]) for arc in arcs) == 20
    assert all(any(company["end"] != "ongoing" for company in arc["companies"]) for arc in arcs)
    assert all(company["metric"] == "market_cap" for arc in arcs for company in arc["companies"])
    assert all(company["unit"] == "usd_billion" for arc in arcs for company in arc["companies"])
    assert all(point["v"] > 0 for arc in arcs for company in arc["companies"] for point in company["series"])
    assert not any(warning["kind"].startswith("future_company_arc") for warning in document["warnings"])
    assert "company-arc-svg" in template
    assert 'company.metric !== "market_cap" ? "is-alternate"' in template
    assert "yFor(point.v)" in template
    assert 'futureCompanyArcIndex: "시가총액 · USD · 로그축"' in template
    assert "company-arc-scale-point" in template
    assert "visibleCompanyArcValues" in template
    assert "renderVisibleCompanyArcScale" in template
    assert "data-company-arc-plot" in template
    assert "--detail-chart-width:${width}px" in template
    assert "detailChartAvailableWidth()," in template
    assert "data-company-arc-step" in template
    assert 'companyArcEndMarker(company.end)' in template

    by_arc = {arc["id"]: arc for arc in arcs}
    internet_companies = {company["symbol"]: company for company in by_arc["internet"]["companies"]}
    semiconductor_companies = {company["symbol"]: company for company in by_arc["semiconductor"]["companies"]}
    assert next(point for point in internet_companies["CSCO"]["series"] if point["y"] == 2000) == {
        "y": 2000,
        "v": 536.369,
        "kind": "peak",
        "date": "2000-03-31",
        "label": "닷컴 고점 약 $536B",
        "label_en": "Dot-com peak near $536B",
    }
    assert next(point for point in internet_companies["CSCO"]["series"] if point["y"] == 2002)["kind"] == "trough"
    assert next(point for point in internet_companies["AMZN"]["series"] if point["y"] == 2001)["v"] == 2.2194
    assert next(point for point in semiconductor_companies["INTC"]["series"] if point["y"] == 2000)["kind"] == "peak"
    assert all(arc["track_record"] for arc in arcs)
    assert "company-arc-turning" in template


def test_future_company_arc_warns_when_required_turning_or_chapter_point_is_missing(tmp_path: Path) -> None:
    future_dir = tmp_path / "future"
    write_yaml(
        future_dir / "company_arcs.yaml",
        """
        - id: missing-anchor
          name: 변곡점 누락
          as_of: 2003
          chapters:
            - {from: 2000, to: 2003, note: 테스트}
          companies:
            - symbol: A
              name: A
              listed: 2000
              end: ongoing
              metric: price
              source_url: https://example.com/a
              turning_points: [{y: 2001, kind: peak}]
              series: [{y: 2000, v: 1}, {y: 2001, v: 3}, {y: 2002, v: 2}]
            - symbol: B
              name: B
              listed: 2000
              end: acquired
              end_year: 2002
              metric: price
              source_url: https://example.com/b
              series: [{y: 2000, v: 1}, {y: 2001, v: 2}, {y: 2002, v: 1}]
            - symbol: C
              name: C
              listed: 2000
              end: ongoing
              metric: price
              source_url: https://example.com/c
              series: [{y: 2000, v: 1}, {y: 2001, v: 2}, {y: 2002, v: 3}]
        """,
    )

    document = build_future_timeline({"future": {"dir": str(future_dir)}}, [], today=date(2026, 7, 12))
    warning_kinds = {warning["kind"] for warning in document["warnings"]}

    assert "future_company_arc_turning" in warning_kinds
    assert "future_company_arc_chapter_point" in warning_kinds


def test_future_expansion_has_images_three_level_readings_and_fresh_bci() -> None:
    root = Path(__file__).resolve().parents[1]
    document = build_future_timeline(
        {"future": {"dir": str(root / "data" / "future")}},
        [],
        today=date(2026, 7, 12),
    )
    expected = {"quantum", "bci", "future-food", "uam", "carbon-capture", "geoengineering", "spatial"}
    technologies = {item["id"]: item for item in document["technologies"] if item["id"] in expected}

    assert set(technologies) == expected
    for technology in technologies.values():
        image_path = root / technology["image"]
        assert image_path.exists() and image_path.stat().st_size > 0
        assert {reading["level"] for reading in technology["readings"]} == {"입문", "중급", "심화"}
    assert technologies["bci"]["as_of"] == "2026-07-12"
    assert technologies["bci"]["stale"] is False


def test_future_track_record_backlog_is_empty_after_verified_migrations() -> None:
    root = Path(__file__).resolve().parents[1]
    backlog = load_future_yaml(root / "data" / "future" / "track_record_backlog.yaml")
    document = build_future_timeline(
        {"future": {"dir": str(root / "data" / "future")}},
        [],
        today=date(2026, 7, 12),
    )

    assert backlog == []
    assert any(item["id"] == "quantum-kookaburra-2025" and item["status"] == "missed" for item in document["track_record"]["items"])


def test_every_future_technology_has_breakdown_and_five_readings_per_level() -> None:
    root = Path(__file__).resolve().parents[1] / "data" / "future"
    technologies = load_future_yaml(root / "technologies.yaml")
    breakdowns = load_future_yaml(root / "breakdown.yaml")
    reading_blocks = load_future_yaml(root / "readings.yaml")
    technology_ids = {str(item["id"]) for item in technologies}
    breakdown_ids = {str(item.get("tech") or item.get("technology") or "") for item in breakdowns}
    readings_by_tech = {
        str(block.get("technology") or ""): block.get("items") or []
        for block in reading_blocks
        if str(block.get("technology") or "") != "_common"
    }

    assert breakdown_ids == technology_ids
    assert set(readings_by_tech) == technology_ids
    for tech_id, readings in readings_by_tech.items():
        counts = Counter(str(item.get("level") or "") for item in readings)
        assert counts["입문"] >= 5, tech_id
        assert counts["중급"] >= 5, tech_id
        assert counts["심화"] >= 5, tech_id
        assert all(count <= 8 for count in counts.values()), tech_id
        urls = [str(item.get("url") or "") for item in readings]
        assert len(urls) == len(set(urls)), tech_id


def test_future_readings_exclude_known_generic_or_retired_pages() -> None:
    root = Path(__file__).resolve().parents[1] / "data" / "future"
    reading_blocks = load_future_yaml(root / "readings.yaml")
    urls = {
        str(item.get("url") or "")
        for block in reading_blocks
        for item in (block.get("items") or [])
    }

    assert urls.isdisjoint(
        {
            "https://www.nature.com/nbt/",
            "https://www.nature.com/natfood/",
            "https://www.nature.com/npjqi/",
            "https://www.idc.com/promo/arvr/",
            "https://www.dmv.ca.gov/portal/vehicle-industry-services/autonomous-vehicles/disengagement-reports/",
            "https://gfi.org/resource/environmental-impact-of-cultivated-meat/",
            "https://immersive-web.github.io/security-privacy/",
        }
    )


def test_future_singularity_is_a_non_investable_scenario_and_fusion_excludes_fission() -> None:
    root = Path(__file__).resolve().parents[1] / "data" / "future"
    technologies = {item["id"]: item for item in load_future_yaml(root / "technologies.yaml")}

    singularity = technologies["singularity-2045"]
    assert singularity["nature"] == "scenario"
    assert singularity["investable"] is False
    assert singularity["companies"] == []
    assert "LEV" in technologies["longevity-escape"]["name"]
    assert "OKLO" not in technologies["fusion-power"].get("companies", [])
