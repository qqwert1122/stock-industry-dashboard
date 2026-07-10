from __future__ import annotations

from datetime import date
from pathlib import Path
from textwrap import dedent

from macro_telegram_report.dashboard import make_metric
from macro_telegram_report.future_timeline import (
    build_future_timeline,
    check_reading_links,
    track_record_status,
    write_future_timeline,
)


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
