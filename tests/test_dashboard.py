import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from macro_telegram_report.dashboard import (
    DEFAULT_INDUSTRIES,
    annotate_dashboard_updates,
    build_morning_briefing,
    collect_stablecoin_metrics,
    completed_months,
    compute_spread_points,
    fiscal_month_to_calendar_date,
    kosis_code_param,
    make_metric,
    month_date_range,
    openfda_month_range,
    parse_ecos_period,
    parse_ecos_points,
    parse_eia_period,
    parse_eia_points,
    parse_kosis_period,
    parse_kosis_points,
    parse_usaspending_monthly_amounts,
    parse_world_bank_month,
    parse_yahoo_chart_points,
    render_dashboard_html,
    sec_capex_points,
    narrative_context_for_briefing,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url, timeout=None, **kwargs):
        self.url = url
        self.timeout = timeout
        self.kwargs = kwargs
        return FakeResponse(self.payload)


class FakePostSession:
    def __init__(self, payload):
        self.payload = payload
        self.post_url = ""
        self.post_headers = {}
        self.post_json = {}

    def post(self, url, **kwargs):
        self.post_url = url
        self.post_headers = kwargs.get("headers", {})
        self.post_json = kwargs.get("json", {})
        return FakeResponse(self.payload)


class DashboardTest(unittest.TestCase):
    def test_make_metric_formats_changes(self):
        metric = make_metric(
            industry="반도체",
            name="테스트 지표",
            source="테스트",
            source_url="https://example.com",
            frequency="월간",
            automation="무료로 안정적으로 자동화 가능",
            status="ok",
            value=12.0,
            unit="$B",
            observed_at="2026-06-01",
            previous_value=10.0,
            yoy_value=8.0,
            history=[(date(2026, 5, 1), 10.0), (date(2026, 6, 1), 12.0)],
        )

        self.assertEqual(metric["display_value"], "$12.00B")
        self.assertEqual(metric["change_pct_label"], "+20.0%")
        self.assertEqual(metric["yoy_pct_label"], "+50.0%")
        self.assertEqual(metric["status_label"], "자동 수집")
        self.assertEqual(metric["next_update_label"], "2026.07")

    def test_make_metric_formats_dollar_unit(self):
        metric = make_metric(
            industry="반도체",
            name="NVIDIA 주가",
            source="Yahoo Finance chart API",
            source_url="https://finance.yahoo.com/quote/NVDA",
            frequency="일간",
            automation="무료 공개 JSON 자동 수집",
            status="ok",
            value=151.25,
            unit="$",
            previous_value=150.0,
        )

        self.assertEqual(metric["display_value"], "$151.2")
        self.assertEqual(metric["change_abs_label"], "$+1.25")

    def test_parse_yahoo_chart_points(self):
        first = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())
        second = int(datetime(2026, 7, 2, tzinfo=timezone.utc).timestamp())
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD"},
                        "timestamp": [first, second],
                        "indicators": {
                            "quote": [{"close": [100.0, 101.5]}],
                        },
                    }
                ],
                "error": None,
            }
        }

        points, currency = parse_yahoo_chart_points(payload)

        self.assertEqual(currency, "USD")
        self.assertEqual(
            points,
            [(date(2026, 7, 1), 100.0), (date(2026, 7, 2), 101.5)],
        )

    def test_parse_yahoo_chart_points_uses_exchange_timezone(self):
        timestamp = int(datetime(2026, 7, 1, 15, 0, tzinfo=timezone.utc).timestamp())
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "KRW", "exchangeTimezoneName": "Asia/Seoul"},
                        "timestamp": [timestamp],
                        "indicators": {"quote": [{"close": [100.0]}]},
                    }
                ],
                "error": None,
            }
        }

        points, currency = parse_yahoo_chart_points(payload)

        self.assertEqual(currency, "KRW")
        self.assertEqual(points, [(date(2026, 7, 2), 100.0)])

    def test_render_dashboard_html_embeds_payload(self):
        html = render_dashboard_html(
            {
                "title": "테스트 대시보드",
                "generated_label": "2026-07-06 08:00 KST",
                "timezone": "Asia/Seoul",
                "industries": ["반도체"],
                "source_status": [],
                "metrics": [],
            }
        )

        self.assertIn("테스트 대시보드", html)
        self.assertIn("DASHBOARD_DATA", html)
        self.assertIn("renderFavoriteMetrics", html)
        self.assertIn("metric-favorite-button", html)
        self.assertIn('data-setting-action="timezone"', html)
        self.assertIn("dashboard-timezone", html)
        self.assertIn("America/New_York", html)
        self.assertIn("detailChartVisiblePoints", html)
        self.assertIn("data-point-x", html)
        self.assertIn("data-current-value", html)
        self.assertIn("data-current-y", html)
        self.assertIn("data-chart-top", html)
        self.assertIn("dynamicDetailChartState", html)
        self.assertIn("updateDynamicDetailPlot", html)
        self.assertIn("scheduleDynamicDetailAxis", html)
        self.assertIn("data-band-toggle", html)
        self.assertIn("lastUpdatedInline", html)
        self.assertIn("gauge-basis-title", html)
        self.assertIn("recession-signal-list", html)
        self.assertIn("fear-greed-gauge-list", html)
        self.assertIn("gauge-component-change", html)
        self.assertIn("initGaugeCardScrollDrag", html)
        self.assertIn("chart-band-swatch", html)
        self.assertIn("chart-band-switch", html)
        self.assertIn("percentileBandLegend", html)
        self.assertIn("한국 (KST, UTC+9)", html)
        self.assertIn('colspan="6"', html)

    def test_annotate_dashboard_updates_detects_updated_and_new_metrics(self):
        payload = {
            "generated_at": "2026-07-07T08:00:00+09:00",
            "metrics": [
                {
                    "id": "same",
                    "industry": "반도체",
                    "group": "판매액",
                    "name": "기존 지표",
                    "value": 12.0,
                    "display_value": "12.0",
                    "observed_at": "2026-06-01",
                    "observed_label": "2026.06",
                    "history": [{"date": "2026-06-01", "value": 12.0}],
                },
                {
                    "id": "updated",
                    "industry": "반도체",
                    "group": "판매액",
                    "name": "업데이트 지표",
                    "value": 15.0,
                    "display_value": "15.0",
                    "observed_at": "2026-07-01",
                    "observed_label": "2026.07",
                    "history": [{"date": "2026-07-01", "value": 15.0}],
                },
                {
                    "id": "new",
                    "industry": "데이터인프라",
                    "group": "CAPEX",
                    "name": "신규 지표",
                    "value": 1.0,
                    "display_value": "1.0",
                    "observed_at": "2026-07-01",
                    "observed_label": "2026.07",
                    "history": [{"date": "2026-07-01", "value": 1.0}],
                },
            ],
        }
        previous = {
            "metrics": [
                {
                    "id": "same",
                    "value": 12.0,
                    "display_value": "12.0",
                    "observed_at": "2026-06-01",
                    "observed_label": "2026.06",
                    "history": [{"date": "2026-06-01", "value": 12.0}],
                },
                {
                    "id": "updated",
                    "value": 14.0,
                    "display_value": "14.0",
                    "observed_at": "2026-06-01",
                    "observed_label": "2026.06",
                    "history": [{"date": "2026-06-01", "value": 14.0}],
                },
            ]
        }

        annotate_dashboard_updates(payload, previous)

        statuses = {metric["id"]: metric["daily_status"] for metric in payload["metrics"]}
        self.assertEqual(statuses["same"], "")
        self.assertEqual(statuses["updated"], "updated")
        self.assertEqual(statuses["new"], "new")
        self.assertEqual(payload["daily_changes"]["updated_count"], 1)
        self.assertEqual(payload["daily_changes"]["new_count"], 1)

    def test_annotate_dashboard_updates_does_not_mark_everything_new_without_previous(self):
        payload = {
            "generated_at": "2026-07-07T08:00:00+09:00",
            "metrics": [{"id": "metric", "value": 1.0, "history": []}],
        }

        annotate_dashboard_updates(payload, None)

        self.assertEqual(payload["metrics"][0]["daily_status"], "")
        self.assertEqual(payload["daily_changes"]["updated_count"], 0)
        self.assertEqual(payload["daily_changes"]["new_count"], 0)
        self.assertFalse(payload["daily_changes"]["has_previous"])

    def test_build_morning_briefing_falls_back_without_gemini_key(self):
        payload = {
            "generated_label": "2026-07-07 08:00 KST",
            "source_status": [],
            "metrics": [
                {
                    "id": "metric",
                    "industry": "반도체",
                    "group": "판매액",
                    "name": "테스트 지표",
                    "display_value": "$12.0B",
                    "observed_label": "2026.06",
                    "change_pct": 12.3,
                    "change_pct_label": "+12.3%",
                    "yoy_pct": 30.0,
                    "yoy_pct_label": "+30.0%",
                }
            ],
        }

        with patch.dict("os.environ", {}, clear=True):
            briefing = build_morning_briefing(payload, FakePostSession({}))

        self.assertEqual(briefing["status"], "skipped")
        self.assertEqual(briefing["top_movers"][0]["kind"], "반도체 판매액")
        self.assertIn("테스트 지표", briefing["summary"])
        self.assertIn("반도체 판매액", briefing["summary"])
        self.assertEqual(briefing["top_movers"][0]["id"], "metric")
        self.assertNotIn("watchlist", briefing)
        self.assertNotIn("caveats", briefing)

    def test_build_morning_briefing_explains_stock_price_metrics(self):
        payload = {
            "generated_label": "2026-07-07 08:00 KST",
            "source_status": [],
            "metrics": [
                {
                    "id": "ter",
                    "industry": "로봇",
                    "group": "대표주가",
                    "name": "Teradyne(TER)",
                    "display_value": "$88.0",
                    "observed_label": "2026.07.07",
                    "change_pct": -12.2,
                    "change_pct_label": "-12.2%",
                    "yoy_pct": -4.0,
                    "yoy_pct_label": "-4.0%",
                }
            ],
        }

        with patch.dict("os.environ", {}, clear=True):
            briefing = build_morning_briefing(payload, FakePostSession({}))

        self.assertEqual(briefing["top_movers"][0]["kind"], "대표주가(주식 가격)")
        self.assertIn("대표주가(주식 가격)", briefing["summary"])
        self.assertIn("시장", briefing["summary"])

    def test_narrative_context_is_compact_and_relevant(self):
        briefing = {
            "top_movers": [{"industry": "로봇", "name": "Teradyne(TER)"}],
            "improving_industries": [{"industry": "반도체"}],
            "slowing_industries": [{"industry": "전력"}],
        }

        context = narrative_context_for_briefing(briefing, limit=2)

        self.assertIn("global_frame", context)
        self.assertIn("stock_market", context)
        self.assertIn("멀티플", context["stock_market"]["narrative"])
        self.assertIn("할인율", context["stock_market"]["lens"])
        self.assertEqual([item["industry"] for item in context["industries"]], ["로봇", "반도체"])
        self.assertIn("대표주가", context["industries"][0]["lens"])
        self.assertIn("기대 재조정", context["industries"][1]["lens"])
        self.assertIn("주가", context["industries"][1]["narrative"])
        self.assertLess(len(str(context)), 1500)

    def test_build_morning_briefing_uses_gemini_secret_only_in_request_header(self):
        gemini_payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    '{"headline":"AI 브리핑","summary":"반도체 변동을 먼저 봅니다.",'
                                    '"bullets":[{"title":"반도체","body":"테스트 지표 변동이 큽니다.",'
                                    '"metric_ids":["metric"]}]}'
                                )
                            }
                        ]
                    }
                }
            ]
        }
        session = FakePostSession(gemini_payload)
        payload = {
            "generated_label": "2026-07-07 08:00 KST",
            "source_status": [],
            "metrics": [
                {
                    "id": "metric",
                    "industry": "반도체",
                    "group": "판매액",
                    "name": "테스트 지표",
                    "display_value": "$12.0B",
                    "observed_label": "2026.06",
                    "change_pct": 12.3,
                    "change_pct_label": "+12.3%",
                    "yoy_pct": 30.0,
                    "yoy_pct_label": "+30.0%",
                }
            ],
        }

        with patch.dict(
            "os.environ",
            {"GEMINI_API_KEY": "secret-test-key", "GEMINI_MODEL": "gemini-3.1-flash-lite"},
            clear=True,
        ):
            briefing = build_morning_briefing(payload, session)

        self.assertEqual(briefing["status"], "ok")
        self.assertEqual(briefing["headline"], "AI 브리핑")
        self.assertEqual(briefing["bullets"][0]["metric_ids"], ["metric"])
        self.assertNotIn("watchlist", briefing)
        self.assertNotIn("caveats", briefing)
        self.assertEqual(session.post_headers["x-goog-api-key"], "secret-test-key")
        self.assertIn("반도체 판매액", str(session.post_json))
        self.assertIn("narrative_context", str(session.post_json))
        self.assertIn("stock_market", str(session.post_json))
        self.assertIn("멀티플", str(session.post_json))
        self.assertIn("AI 서버", str(session.post_json))
        self.assertNotIn("secret-test-key", str(briefing))
        self.assertNotIn("secret-test-key", str(session.post_json))

    def test_default_industries_include_new_categories(self):
        for industry in [
            "자동차",
            "전기차",
            "데이터인프라",
            "방산",
            "스테이블코인",
            "전력",
            "로봇",
            "우주",
            "바이오",
            "배터리",
        ]:
            self.assertIn(industry, DEFAULT_INDUSTRIES)
        self.assertNotIn("자동차/전기차", DEFAULT_INDUSTRIES)

    def test_collect_stablecoin_metrics_builds_total_and_assets(self):
        session = FakeSession(
            {
                "peggedAssets": [
                    {
                        "id": "1",
                        "name": "Tether",
                        "symbol": "USDT",
                        "pegType": "peggedUSD",
                        "circulating": {"peggedUSD": 100_000_000_000},
                        "circulatingPrevDay": {"peggedUSD": 99_000_000_000},
                        "circulatingPrevWeek": {"peggedUSD": 98_000_000_000},
                        "circulatingPrevMonth": {"peggedUSD": 97_000_000_000},
                    },
                    {
                        "id": "2",
                        "name": "USD Coin",
                        "symbol": "USDC",
                        "pegType": "peggedUSD",
                        "circulating": {"peggedUSD": 50_000_000_000},
                        "circulatingPrevDay": {"peggedUSD": 49_500_000_000},
                        "circulatingPrevWeek": {"peggedUSD": 49_000_000_000},
                        "circulatingPrevMonth": {"peggedUSD": 48_000_000_000},
                    },
                    {
                        "id": "3",
                        "name": "Euro Coin",
                        "symbol": "EURC",
                        "pegType": "peggedEUR",
                        "circulating": {"peggedUSD": 10_000_000_000},
                    },
                ]
            }
        )
        metrics = collect_stablecoin_metrics(
            {
                "stablecoins": {
                    "assets": [
                        {"symbol": "TOTAL", "name": "전체 스테이블코인 유통량"},
                        {"symbol": "USDT", "name": "USDT 유통량"},
                    ]
                }
            },
            session,
            date(2026, 7, 7),
        )

        self.assertEqual(len(metrics), 2)
        self.assertEqual(metrics[0]["industry"], "스테이블코인")
        self.assertEqual(metrics[0]["display_value"], "$150.0B")
        self.assertEqual(metrics[0]["change_abs_label"], "+1.50B")
        self.assertEqual(metrics[1]["display_value"], "$100.0B")

    def test_parse_world_bank_month(self):
        self.assertEqual(parse_world_bank_month("2026M06"), date(2026, 6, 1))
        self.assertEqual(parse_world_bank_month("2026-06-30"), date(2026, 6, 1))
        self.assertIsNone(parse_world_bank_month("not-a-month"))

    def test_sec_capex_points_uses_quarter_duration_and_latest_filing(self):
        payload = {
            "facts": {
                "us-gaap": {
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "units": {
                            "USD": [
                                {
                                    "start": "2025-01-01",
                                    "end": "2025-03-31",
                                    "val": 10_000_000_000,
                                    "form": "10-Q",
                                    "filed": "2025-04-30",
                                },
                                {
                                    "start": "2025-01-01",
                                    "end": "2025-06-30",
                                    "val": 22_000_000_000,
                                    "form": "10-Q",
                                    "filed": "2025-07-30",
                                },
                                {
                                    "start": "2025-04-01",
                                    "end": "2025-06-30",
                                    "val": 13_000_000_000,
                                    "form": "10-Q",
                                    "filed": "2025-07-30",
                                },
                                {
                                    "start": "2025-04-01",
                                    "end": "2025-06-30",
                                    "val": 14_000_000_000,
                                    "form": "10-Q",
                                    "filed": "2026-01-30",
                                },
                            ]
                        }
                    }
                }
            }
        }

        points = sec_capex_points(payload)

        self.assertEqual(points, [(date(2025, 3, 31), 10_000_000_000), (date(2025, 6, 30), 14_000_000_000)])

    def test_sec_capex_points_chooses_newer_tag(self):
        payload = {
            "facts": {
                "us-gaap": {
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "units": {
                            "USD": [
                                {
                                    "start": "2017-01-01",
                                    "end": "2017-03-31",
                                    "val": 1_000_000_000,
                                    "form": "10-Q",
                                    "filed": "2017-04-30",
                                }
                            ]
                        }
                    },
                    "PaymentsToAcquireProductiveAssets": {
                        "units": {
                            "USD": [
                                {
                                    "start": "2026-01-01",
                                    "end": "2026-03-31",
                                    "val": 44_000_000_000,
                                    "form": "10-Q",
                                    "filed": "2026-04-30",
                                }
                            ]
                        }
                    },
                }
            }
        }

        self.assertEqual(sec_capex_points(payload), [(date(2026, 3, 31), 44_000_000_000)])

    def test_usaspending_fiscal_month_conversion(self):
        self.assertEqual(fiscal_month_to_calendar_date("2025", "1"), date(2024, 10, 1))
        self.assertEqual(fiscal_month_to_calendar_date("2025", "4"), date(2025, 1, 1))
        payload = {
            "results": [
                {
                    "time_period": {"fiscal_year": "2025", "month": "4"},
                    "aggregated_amount": 1_000_000_000,
                }
            ]
        }
        self.assertEqual(parse_usaspending_monthly_amounts(payload), [(date(2025, 1, 1), 1_000_000_000)])

    def test_parse_eia_period_and_points(self):
        self.assertEqual(parse_eia_period("2026-04"), date(2026, 4, 1))
        self.assertEqual(parse_eia_period("2026-06-29"), date(2026, 6, 29))
        payload = {
            "response": {
                "data": [
                    {"period": "2026-04", "sales": "302126.8"},
                    {"period": "2026-03", "sales": 290000},
                ]
            }
        }

        self.assertEqual(
            parse_eia_points(payload, "sales"),
            [(date(2026, 3, 1), 290000.0), (date(2026, 4, 1), 302126.8)],
        )

    def test_parse_ecos_points_and_credit_spread(self):
        payload = {
            "StatisticSearch": {
                "row": [
                    {"TIME": "20260701", "DATA_VALUE": "4.466"},
                    {"TIME": "20260702", "DATA_VALUE": "4.431"},
                ]
            }
        }

        corporate = parse_ecos_points(payload, "D")
        treasury = [
            (date(2026, 7, 1), 3.791),
            (date(2026, 7, 2), 3.747),
        ]

        self.assertEqual(parse_ecos_period("20260701", "D"), date(2026, 7, 1))
        self.assertEqual(
            corporate,
            [(date(2026, 7, 1), 4.466), (date(2026, 7, 2), 4.431)],
        )
        self.assertEqual(
            compute_spread_points(corporate, treasury),
            [(date(2026, 7, 1), 0.675), (date(2026, 7, 2), 0.684)],
        )

    def test_completed_month_helpers(self):
        self.assertEqual(
            completed_months(date(2026, 7, 7), 3),
            [date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1)],
        )
        self.assertEqual(month_date_range(date(2026, 2, 1)), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(openfda_month_range(date(2026, 6, 1)), ("20260601", "20260630"))

    def test_kosis_helpers(self):
        self.assertEqual(kosis_code_param(["a0", "a1"]), "a0+a1+")
        self.assertEqual(kosis_code_param("sales"), "sales+")
        self.assertEqual(parse_kosis_period("202605", "M"), date(2026, 5, 1))
        self.assertEqual(parse_kosis_period("2025", "Y"), date(2025, 1, 1))
        payload = [
            {"PRD_DE": "202604", "DT": "80,100"},
            {"PRD_DE": "202605", "DT": "82,000"},
        ]
        self.assertEqual(
            parse_kosis_points(payload, "M"),
            [(date(2026, 4, 1), 80100.0), (date(2026, 5, 1), 82000.0)],
        )


if __name__ == "__main__":
    unittest.main()
