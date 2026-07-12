from __future__ import annotations

from macro_telegram_report.dashboard import make_metric, run_dashboard_collector


def metric(status: str = "ok", note: str = ""):
    return make_metric(
        industry="매크로",
        name="테스트 지표",
        source="테스트",
        source_url="https://example.com",
        frequency="일간",
        automation="무료 자동 수집",
        status=status,
        note=note,
        value=1.0 if status == "ok" else None,
    )


def test_run_dashboard_collector_records_complete_and_partial_sources():
    metrics = []
    statuses = []
    common = {
        "metrics": metrics,
        "source_status": statuses,
        "previous_by_key": {},
        "fetched_at": "2026-07-12T09:00:00+09:00",
    }

    run_dashboard_collector(source_name="정상", collector=lambda: [metric()], **common)
    run_dashboard_collector(
        source_name="주의",
        collector=lambda: [metric(note="API_KEY 없음, 이전 저장값 표시")],
        **common,
    )

    assert [item["status"] for item in statuses] == ["ok", "partial"]
    assert len(metrics) == 2


def test_run_dashboard_collector_isolates_failure_and_uses_error_overrides():
    metrics = []
    statuses = []

    def failing_collector():
        raise RuntimeError("temporary failure")

    run_dashboard_collector(
        source_name="실패 소스",
        collector=failing_collector,
        metrics=metrics,
        source_status=statuses,
        previous_by_key={},
        fetched_at="2026-07-12T09:00:00+09:00",
        error_metric_overrides={"group": "상태", "section": "market"},
    )

    assert statuses == [
        {"name": "실패 소스", "status": "error", "message": "temporary failure"}
    ]
    assert metrics[0]["name"] == "실패 소스 수집 상태"
    assert metrics[0]["group"] == "상태"
    assert metrics[0]["section"] == "market"
