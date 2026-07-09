from macro_telegram_report.dashboard import record_fetch_result
from macro_telegram_report.fetch_log import (
    FetchLogger,
    append_fetch_log_run,
    sanitize_endpoint,
    sanitize_message,
    use_fetch_logger,
)


def test_sanitize_endpoint_strips_query_and_fragment():
    endpoint = (
        "https://apis.data.go.kr/1220000/Itemtrade?"
        "serviceKey=abc%2Bsecret%3D&strtYymm=202606#frag"
    )

    sanitized = sanitize_endpoint(endpoint)

    assert sanitized == "https://apis.data.go.kr/1220000/Itemtrade"
    assert "abc" not in sanitized
    assert "serviceKey" not in sanitized
    assert "strtYymm" not in sanitized


def test_sanitize_message_redacts_secret_names_and_url_queries():
    message = (
        "GitHub Secrets에 KRX_OPEN_API_KEY 등록 필요: "
        "https://example.com/api?serviceKey=abc%2Bsecret%3D"
    )

    sanitized = sanitize_message(message)

    assert "KRX_OPEN_API_KEY" not in sanitized
    assert "serviceKey" not in sanitized
    assert "abc" not in sanitized
    assert "https://example.com/api" in sanitized


def test_append_fetch_log_run_keeps_recent_sixty():
    history = None
    for index in range(65):
        history = append_fetch_log_run(
            history,
            {
                "run_id": f"run-{index:02d}",
                "run_type": "full",
                "started_at": f"2026-07-08T00:{index:02d}:00+09:00",
                "finished_at": f"2026-07-08T00:{index:02d}:01+09:00",
                "records": [],
            },
        )

    assert history["count"] == 60
    assert history["runs"][0]["run_id"] == "run-05"
    assert history["runs"][-1]["run_id"] == "run-64"


def test_record_fetch_result_marks_no_new_data_against_previous_payload():
    previous = {
        "hist-a": {
            "id": "metric-a",
            "history_key": "hist-a",
            "observed_at": "2026-07-01",
        }
    }
    metrics = [
        {
            "id": "metric-a",
            "history_key": "hist-a",
            "status": "ok",
            "observed_at": "2026-07-01",
        }
    ]
    logger = FetchLogger(run_type="full", timezone_name="Asia/Seoul")

    with use_fetch_logger(logger):
        started_at, started_monotonic = logger.source_started()
        record_fetch_result(
            "테스트 소스",
            metrics,
            previous,
            started_at,
            started_monotonic,
            "1/1개 지표 자동 수집",
        )

    run = logger.finish()

    assert run["records"][0]["status"] == "no_new_data"
    assert run["records"][0]["new_data_count"] == 0
