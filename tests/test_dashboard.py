import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from macro_telegram_report.dashboard import (
    DEFAULT_INDUSTRIES,
    annotate_dashboard_updates,
    annotate_metric_freshness,
    briefing_generation_decision,
    briefing_metric_snapshot,
    briefing_session_context,
    build_freshness_summary,
    build_morning_briefing,
    classify_yahoo_trading_period,
    collect_stablecoin_metrics,
    collect_usaspending_metrics,
    completed_months,
    compute_spread_points,
    fiscal_month_to_calendar_date,
    intraday_price_config,
    kosis_code_param,
    load_admin_template,
    make_metric,
    market_narrative_context,
    month_date_range,
    openfda_month_range,
    collect_kofia_capital_market_metrics,
    parse_ecos_period,
    parse_ecos_points,
    parse_eia_period,
    parse_eia_points,
    parse_kofia_json_rows,
    kofia_points_from_rows,
    parse_kosis_period,
    parse_kosis_points,
    parse_usaspending_monthly_amounts,
    parse_world_bank_month,
    parse_yahoo_chart_points,
    persistent_market_events,
    render_dashboard_html,
    refresh_briefing_site,
    rule_based_morning_briefing,
    sec_capex_points,
    narrative_context_for_briefing,
    visible_dashboard_metrics,
)
from macro_telegram_report.briefing import build_briefing_card, write_briefing_outputs


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

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
        self.post_count = 0

    def post(self, url, **kwargs):
        self.post_count += 1
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

    def test_visible_dashboard_metrics_english_fields_do_not_keep_hangul_for_flow(self):
        metric = make_metric(
            industry="매크로",
            name="코스피 기타금융 20일 누적 순매수",
            source="KRX 정보데이터시스템",
            source_url="https://data.krx.co.kr/",
            frequency="일간",
            automation="공개 JSON 자동 수집",
            status="ok",
            value=123.0,
            unit="억원",
            observed_at="2026-07-08",
            previous_value=100.0,
            history=[(date(2026, 7, 7), 100.0), (date(2026, 7, 8), 123.0)],
            group="기타금융",
            depth="코스피",
            meaning=(
                "코스피에서 기타금융이 최근 20거래일 동안 순매수한 금액의 합계입니다. "
                "하루짜리 수급보다 잡음이 적어서, 같은 주체가 시장을 꾸준히 사는지 파는지 볼 때 씁니다."
            ),
        )

        visible = visible_dashboard_metrics([metric])[0]

        self.assertEqual(visible["name_en"], "KOSPI Other Financials 20d Net Buying")
        self.assertEqual(visible["group_en"], "Other Financials")
        self.assertEqual(visible["depth_en"], "KOSPI")
        for key in ("industry_en", "group_en", "depth_en", "name_en", "meaning_en", "unit_en", "frequency_en"):
            self.assertNotRegex(visible[key], r"[가-힣]")

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

        self.assertNotIn("__GA_MEASUREMENT_ID__", html)
        self.assertIn("ui_click", html)
        self.assertIn("marketbrief.analytics-consent", html)
        self.assertIn("방문 분석을 허용할까요?", html)
        self.assertIn("개발 미리보기에서는 실제 분석 데이터가 전송되지 않습니다.", html)
        self.assertIn("analyticsCollection", html)
        self.assertIn("analyticsConsentSettingLabel", html)
        self.assertIn("countrySelect", html)
        self.assertNotIn("fa-earth-americas", html)
        self.assertIn('normalized === "ALL" || normalized === "GLOBAL"', html)
        self.assertIn('country-filter-option${flag ? " has-flag" : ""}', html)
        self.assertIn("data-recent-alert-key", html)
        self.assertIn("openRecentAlert", html)
        self.assertIn("signalDrawerSheetHandle", html)
        self.assertIn('class="fa-regular fa-bell"', html)
        self.assertNotIn('class="fa-solid fa-bell"', html)
        self.assertIn("flex: 0 0 16px", html)
        self.assertIn("signal-status-circle", html)
        self.assertIn("signal-card-value-change", html)
        self.assertIn("signal-card-context-item", html)
        self.assertNotIn("signal-card-context-toggle", html)
        self.assertIn("signalEventRelativeTimeText", html)
        self.assertIn("signal-history-list", html)
        self.assertIn(".signal-history-item:last-child", html)
        self.assertIn("signalHistoryItemMarkup(event, true)", html)
        self.assertIn("signal-history-pagination", html)
        self.assertIn("signalHistoryPageSize = 10", html)
        self.assertIn('signalFilter: "current"', html)
        self.assertIn("현재 발동중", html)
        self.assertNotIn("signal-section-title", html)
        self.assertNotIn("signal-card-value-row", html)
        self.assertNotIn(".signal-section:first-child .signal-card", html)
        self.assertIn("{ preserveSignal: true }", html)
        self.assertIn("metric-detail-from-signal", html)
        self.assertNotIn("body.metric-detail-from-signal .metric-detail-drawer", html)
        self.assertIn("termsOfService", html)
        self.assertIn("footerDisclaimer", html)
        self.assertIn("languageKorean", html)
        self.assertIn("privacy.html", html)
        self.assertIn("terms.html", html)
        self.assertIn("site-footer-links", html)
        self.assertIn("if (consent === \"accepted\") enableAnalytics()", html)

        self.assertIn("테스트 대시보드", html)
        self.assertIn("assets/marketbrief-logo.svg", html)
        self.assertIn("DASHBOARD_DATA", html)
        self.assertIn("renderFavoriteMetrics", html)
        self.assertIn("favoriteCardStarMarkup", html)
        self.assertIn('fa-${active ? "solid" : "regular"} fa-star', html)
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
        self.assertIn("lastCheckedText", html)
        self.assertIn("dataAsOf", html)
        self.assertIn("searchToggle", html)
        self.assertIn("buildSearchIndex", html)
        self.assertIn("runMetricSearch", html)
        self.assertIn("metricSearchPlaceholder", html)
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

    def test_admin_template_reads_fetch_log_json(self):
        html = load_admin_template()

        self.assertIn("../data/fetch_log.json", html)
        self.assertIn("수집 로그", html)
        self.assertIn("실패만 보기", html)
        self.assertNotIn("../data/analytics.json", html)
        self.assertNotIn("이용 지표", html)

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

    def test_rule_based_briefing_uses_natural_subject_particle_for_metric_names(self):
        briefing = rule_based_morning_briefing(
            {
                "source_status": [],
                "metrics": [
                    {
                        "id": "phase-3",
                        "industry": "바이오",
                        "group": "파이프라인",
                        "name": "Phase 3 임상 시작",
                        "change_pct": 5.6,
                        "change_pct_label": "+5.6%",
                        "yoy_pct": 10.0,
                    }
                ],
            }
        )

        self.assertIn("Phase 3 임상 시작이 +5.6% 움직였습니다", briefing["summary"])
        self.assertNotIn("Phase 3 임상 시작가", briefing["summary"])

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
        self.assertIn("structural_lenses", str(session.post_json))
        self.assertIn("market_narrative", str(session.post_json))
        self.assertIn("stock_market", str(session.post_json))
        self.assertIn("멀티플", str(session.post_json))
        self.assertIn("Phase 3 임상 시작이", str(session.post_json))
        self.assertIn("AI 서버", str(session.post_json))
        self.assertNotIn("secret-test-key", str(briefing))
        self.assertNotIn("secret-test-key", str(session.post_json))

    def test_intraday_briefing_only_ranks_metrics_changed_since_previous_card(self):
        payload = {
            "metrics": [
                {
                    "id": "defense-old",
                    "industry": "방산",
                    "group": "대표주가",
                    "name": "방산 대표주",
                    "change_pct": -12.0,
                    "change_pct_label": "-12.0%",
                    "daily_status": "updated",
                },
                {
                    "id": "semi-new",
                    "industry": "반도체",
                    "group": "대표주가",
                    "name": "반도체 대표주",
                    "change_pct": 2.1,
                    "change_pct_label": "+2.1%",
                },
            ]
        }

        briefing = rule_based_morning_briefing(
            payload,
            {"changed_metrics": [{"id": "semi-new", "reason": "값 변화"}]},
        )

        self.assertEqual(briefing["top_movers"][0]["id"], "semi-new")
        self.assertNotEqual(briefing["top_movers"][0]["id"], "defense-old")
        self.assertIn("defense-old", [item["id"] for item in briefing["top_movers"]])

    def test_market_narrative_prefers_current_leadership_and_penalizes_recent_topic(self):
        def stock(metric_id, industry, change):
            return {
                "id": metric_id,
                "industry": industry,
                "group": "대표주가",
                "history_key": f"equity-{metric_id.upper()}",
                "name": metric_id,
                "status": "ok",
                "value": 100.0,
                "display_value": "$100",
                "change_pct": change,
                "change_pct_label": f"{change:+.1f}%",
            }

        payload = {
            "metrics": [
                stock("nvda", "반도체", 3.2),
                stock("amd", "반도체", 2.8),
                stock("lmt", "방산", -2.1),
                stock("hii", "방산", -2.0),
                {
                    "id": "spx",
                    "name": "S&P 500",
                    "industry": "매크로",
                    "group": "시장지수",
                    "status": "ok",
                    "value": 7000.0,
                    "change_pct": 0.5,
                },
            ],
            "freshness_summary": {"status": "current"},
        }
        context = market_narrative_context(
            payload,
            {"key": "us", "benchmark_names": ["S&P 500"]},
            [{"narrative_topics": ["산업:방산:weak"]}],
            changed_ids={"nvda", "amd", "lmt", "hii"},
        )

        self.assertEqual(context["candidates"][0]["industry"], "반도체")
        defense = next(item for item in context["candidates"] if item["industry"] == "방산")
        self.assertGreater(defense["repetition_penalty"], 0)
        self.assertEqual(context["market_breadth"]["sample_size"], 4)

    def test_persistent_crash_remains_but_advances_the_story(self):
        payload = {
            "metrics": [
                {
                    "id": "defense",
                    "industry": "방산",
                    "group": "대표주가",
                    "name": "방산 대표주",
                    "status": "ok",
                    "value": 88.0,
                    "display_value": "$88",
                    "change_pct": -12.0,
                    "change_pct_label": "-12.0%",
                }
            ]
        }
        previous = {
            "defense": {
                "id": "defense",
                "value": 92.0,
                "change_pct": -8.0,
                "observed_at": "2026-07-10",
            }
        }

        events = persistent_market_events(
            payload,
            previous,
            [{"narrative_topics": ["산업:방산:weak"]}],
        )

        self.assertEqual(events[0]["progression"], "낙폭 확대")
        self.assertTrue(events[0]["mentioned_recently"])
        self.assertIn("복사하지 말고", events[0]["instruction"])

    def test_rule_based_briefing_keeps_persistent_crash_below_new_story(self):
        payload = {
            "generated_label": "2026-07-10 14:00 KST",
            "source_status": [],
            "metrics": [
                {
                    "id": "semi-new",
                    "industry": "반도체",
                    "group": "대표주가",
                    "name": "NVIDIA(NVDA)",
                    "history_key": "equity-NVDA",
                    "status": "ok",
                    "value": 204.0,
                    "display_value": "$204",
                    "change_pct": 3.0,
                    "change_pct_label": "+3.0%",
                },
                {
                    "id": "defense-old",
                    "industry": "방산",
                    "group": "대표주가",
                    "name": "방산 대표주",
                    "history_key": "equity-DEFENSE",
                    "status": "ok",
                    "value": 88.0,
                    "display_value": "$88",
                    "change_pct": -10.0,
                    "change_pct_label": "-10.0%",
                },
            ],
        }
        context = {
            "changed_metrics": [{"id": "semi-new"}],
            "market_narrative": {
                "candidates": [{"industry": "반도체", "label": "반도체 주도"}]
            },
            "persistent_events": [
                {
                    "id": "defense-old",
                    "industry": "방산",
                    "name": "방산 대표주",
                    "change_pct_label": "-10.0%",
                    "progression": "큰 움직임 지속",
                }
            ],
        }

        briefing = rule_based_morning_briefing(payload, context)

        self.assertIn("반도체 주도", briefing["headline"])
        self.assertEqual(briefing["bullets"][-1]["title"], "계속 볼 사건")
        self.assertIn("큰 움직임 지속", briefing["bullets"][-1]["body"])

    def test_freshness_uses_publication_lag_instead_of_calendar_age_only(self):
        metrics = [
            {
                "id": "current-monthly",
                "name": "월간 지표",
                "source": "FRED API",
                "frequency": "월간",
                "status": "ok",
                "fetch_status": "no_new_data",
                "fetched_at": "2026-07-10T08:00:00+09:00",
                "observed_at": "2026-05-01",
            },
            {
                "id": "delayed-monthly",
                "name": "오래된 월간 지표",
                "source": "KOSIS OpenAPI",
                "frequency": "월간",
                "status": "ok",
                "fetch_status": "no_new_data",
                "fetched_at": "2026-07-10T08:00:00+09:00",
                "observed_at": "2025-03-01",
            },
        ]

        issues = annotate_metric_freshness(metrics, date(2026, 7, 10))
        summary = build_freshness_summary(
            metrics, "2026-07-10T08:00:00+09:00", date(2026, 7, 10)
        )

        self.assertFalse(metrics[0]["is_stale"])
        self.assertTrue(metrics[1]["is_stale"])
        self.assertEqual(len(issues), 1)
        self.assertEqual(summary["current_count"], 1)
        self.assertEqual(summary["delayed_count"], 1)

    def test_freshness_summary_treats_cached_fallback_as_displayable_data(self):
        metrics = [
            {
                "id": "cached-contracts",
                "name": "미국 방산 계약",
                "source": "USAspending API",
                "frequency": "월간",
                "status": "ok",
                "fetch_status": "failed",
                "fetched_at": "2026-07-10T08:00:00+09:00",
                "observed_at": "2026-06-01",
                "value": 1.5,
            }
        ]

        annotate_metric_freshness(metrics, date(2026, 7, 10))
        summary = build_freshness_summary(
            metrics, "2026-07-10T08:00:00+09:00", date(2026, 7, 10)
        )

        self.assertEqual(summary["status"], "current")
        self.assertEqual(summary["failed_count"], 0)
        self.assertEqual(summary["current_count"], 1)
        self.assertEqual(summary["sources"][0]["failed_count"], 0)

    def test_intraday_price_scope_switches_markets_without_increasing_calls(self):
        config = {
            "equities": {
                "items": [
                    {"name": "한국", "symbol": "005930.KS"},
                    {"name": "미국", "symbol": "NVDA"},
                    {"name": "연속", "symbol": "ES=F", "refresh_scope": "intraday"},
                ]
            }
        }
        korea, _ = intraday_price_config(config, datetime.fromisoformat("2026-07-10T10:00:00+09:00"))
        us, _ = intraday_price_config(config, datetime.fromisoformat("2026-07-10T20:00:00+09:00"))
        off, _ = intraday_price_config(config, datetime.fromisoformat("2026-07-10T07:30:00+09:00"))

        self.assertEqual([item["name"] for item in korea["equities"]["items"]], ["한국", "연속"])
        self.assertEqual([item["name"] for item in us["equities"]["items"]], ["미국", "연속"])
        self.assertEqual([item["name"] for item in off["equities"]["items"]], ["연속"])

    def test_yahoo_trading_period_classifies_extended_sessions(self):
        meta = {
            "currentTradingPeriod": {
                "pre": {"start": 100, "end": 199},
                "regular": {"start": 200, "end": 299},
                "post": {"start": 300, "end": 399},
            }
        }

        self.assertEqual(classify_yahoo_trading_period(meta, 150), "premarket")
        self.assertEqual(classify_yahoo_trading_period(meta, 250), "regular")
        self.assertEqual(classify_yahoo_trading_period(meta, 350), "afterhours")

    def test_briefing_session_context_selects_session_benchmarks(self):
        korea = briefing_session_context(datetime.fromisoformat("2026-07-09T10:00:00+09:00"))
        us = briefing_session_context(datetime.fromisoformat("2026-07-09T23:30:00+09:00"))
        off = briefing_session_context(datetime.fromisoformat("2026-07-09T08:00:00+09:00"))

        self.assertEqual(korea["label"], "한국장")
        self.assertEqual(korea["benchmark_names"], ["코스피", "코스닥"])
        self.assertEqual(us["label"], "미국장")
        self.assertIn("S&P 500", us["benchmark_names"])
        self.assertEqual(off["label"], "세션 외")

    def test_briefing_gate_no_change_skips(self):
        payload = {
            "metrics": [
                {"id": "kospi", "name": "코스피", "value": 100.0, "observed_at": "2026-07-09", "change_pct": 0.1}
            ]
        }
        snapshot = briefing_metric_snapshot(payload)
        previous_card = {"metric_snapshot": snapshot}

        decision = briefing_generation_decision(
            payload,
            previous_card,
            [],
            datetime.fromisoformat("2026-07-09T10:00:00+09:00"),
        )

        self.assertTrue(decision["skip"])
        self.assertFalse(decision["low_signal"])

    def test_briefing_gate_low_signal_once_generates(self):
        previous_payload = {
            "metrics": [
                {"id": "kospi", "name": "코스피", "value": 100.0, "observed_at": "2026-07-09", "change_pct": 0.1}
            ]
        }
        payload = {
            "metrics": [
                {"id": "kospi", "name": "코스피", "value": 100.2, "observed_at": "2026-07-09", "change_pct": 0.2}
            ]
        }

        decision = briefing_generation_decision(
            payload,
            {"metric_snapshot": briefing_metric_snapshot(previous_payload)},
            [{"low_signal": False}],
            datetime.fromisoformat("2026-07-09T10:00:00+09:00"),
        )

        self.assertFalse(decision["skip"])
        self.assertTrue(decision["low_signal"])
        self.assertFalse(decision["significant"])

    def test_briefing_gate_two_low_signal_cards_skip_until_significant_change(self):
        previous_payload = {
            "metrics": [
                {"id": "kospi", "name": "코스피", "value": 100.0, "observed_at": "2026-07-09", "change_pct": 0.1}
            ]
        }
        quiet_payload = {
            "metrics": [
                {"id": "kospi", "name": "코스피", "value": 100.2, "observed_at": "2026-07-09", "change_pct": 0.2}
            ]
        }
        active_payload = {
            "metrics": [
                {"id": "kospi", "name": "코스피", "value": 101.0, "observed_at": "2026-07-09", "change_pct": 0.2}
            ]
        }
        previous_card = {"metric_snapshot": briefing_metric_snapshot(previous_payload)}
        recent = [{"low_signal": True}, {"low_signal": True}]

        quiet = briefing_generation_decision(
            quiet_payload,
            previous_card,
            recent,
            datetime.fromisoformat("2026-07-09T10:00:00+09:00"),
        )
        active = briefing_generation_decision(
            active_payload,
            previous_card,
            recent,
            datetime.fromisoformat("2026-07-09T10:00:00+09:00"),
        )

        self.assertTrue(quiet["skip"])
        self.assertTrue(quiet["low_signal"])
        self.assertFalse(active["skip"])
        self.assertFalse(active["low_signal"])
        self.assertTrue(active["significant"])

    def test_refresh_briefing_site_skips_without_gemini_call_when_metrics_unchanged(self):
        payload = {
            "generated_at": "2026-07-09T09:00:00+09:00",
            "generated_label": "2026-07-09 09:00 KST",
            "timezone": "Asia/Seoul",
            "industries": ["매크로"],
            "source_status": [],
            "metrics": [
                {
                    "id": "kospi",
                    "industry": "매크로",
                    "group": "시장지수",
                    "name": "코스피",
                    "value": 100.0,
                    "display_value": "100",
                    "observed_at": "2026-07-09",
                    "change_pct": 0.1,
                    "history": [],
                    "status": "ok",
                }
            ],
        }
        with TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            data_path = site / "data"
            data_path.mkdir(parents=True)
            (data_path / "dashboard.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            previous_card = build_briefing_card(
                {"headline": "기존", "summary": "기존 카드", "bullets": []},
                card_type="intraday",
                generated_at="2026-07-09T09:00:00+09:00",
                generated_label="2026-07-09 09:00 KST",
                metric_snapshot=briefing_metric_snapshot(payload),
            )
            write_briefing_outputs(data_path, previous_card)
            session = FakePostSession({})

            with patch.dict("os.environ", {"GEMINI_API_KEY": "secret-test-key"}, clear=True):
                refreshed = refresh_briefing_site({"timezone": "Asia/Seoul"}, site, session, "intraday")

            self.assertEqual(session.post_count, 0)
            self.assertEqual(refreshed["morning_briefing"]["headline"], "기존")
            fetch_log = json.loads((data_path / "fetch_log.json").read_text(encoding="utf-8"))
            self.assertIn("카드 생성 스킵", fetch_log["runs"][-1]["records"][-1]["message"])

    def test_refresh_briefing_site_uses_rule_fallback_after_gemini_daily_limit(self):
        previous_payload = {
            "metrics": [
                {
                    "id": "kospi",
                    "industry": "매크로",
                    "group": "시장지수",
                    "name": "코스피",
                    "value": 100.0,
                    "display_value": "100",
                    "observed_at": "2026-07-09",
                    "change_pct": 0.1,
                    "history": [],
                    "status": "ok",
                }
            ]
        }
        payload = {
            "generated_at": "2026-07-09T10:00:00+09:00",
            "generated_label": "2026-07-09 10:00 KST",
            "timezone": "Asia/Seoul",
            "industries": ["매크로"],
            "source_status": [],
            "metrics": [
                {
                    "id": "kospi",
                    "industry": "매크로",
                    "group": "시장지수",
                    "name": "코스피",
                    "value": 101.0,
                    "display_value": "101",
                    "observed_at": "2026-07-09",
                    "change_pct": 0.1,
                    "change_pct_label": "+0.1%",
                    "history": [],
                    "status": "ok",
                }
            ],
        }
        with TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            data_path = site / "data"
            briefings_path = data_path / "briefings"
            briefings_path.mkdir(parents=True)
            (data_path / "dashboard.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            previous_card = build_briefing_card(
                {"headline": "기존", "summary": "기존 카드", "bullets": []},
                card_type="intraday",
                generated_at="2026-07-09T09:00:00+09:00",
                generated_label="2026-07-09 09:00 KST",
                metric_snapshot=briefing_metric_snapshot(previous_payload),
            )
            write_briefing_outputs(data_path, previous_card)
            today_key = datetime.now().date().isoformat()
            (briefings_path / "gemini_usage.json").write_text(
                json.dumps({"version": 1, "days": {today_key: {"count": 400}}}, ensure_ascii=False),
                encoding="utf-8",
            )
            session = FakePostSession({"candidates": []})

            with patch.dict("os.environ", {"GEMINI_API_KEY": "secret-test-key"}, clear=True):
                refreshed = refresh_briefing_site({"timezone": "Asia/Seoul"}, site, session, "intraday")

            self.assertEqual(session.post_count, 0)
            self.assertEqual(refreshed["morning_briefing"]["status"], "disabled")
            self.assertIn("400회", refreshed["morning_briefing"]["status_message"])

    def test_refresh_briefing_site_calls_gemini_when_changed_and_allowed(self):
        gemini_payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    '{"headline":"장중 변화","summary":"코스피 변화가 감지됐습니다.",'
                                    '"bullets":[{"title":"시장지수","body":"코스피가 움직였습니다.",'
                                    '"metric_ids":["kospi"]}]}'
                                )
                            }
                        ]
                    }
                }
            ]
        }
        previous_payload = {
            "metrics": [
                {
                    "id": "kospi",
                    "industry": "매크로",
                    "group": "시장지수",
                    "name": "코스피",
                    "value": 100.0,
                    "display_value": "100",
                    "observed_at": "2026-07-09",
                    "change_pct": 0.1,
                    "history": [],
                    "status": "ok",
                }
            ]
        }
        payload = {
            "generated_at": "2026-07-09T10:00:00+09:00",
            "generated_label": "2026-07-09 10:00 KST",
            "timezone": "Asia/Seoul",
            "industries": ["매크로"],
            "source_status": [],
            "metrics": [
                {
                    "id": "kospi",
                    "industry": "매크로",
                    "group": "시장지수",
                    "name": "코스피",
                    "value": 101.0,
                    "display_value": "101",
                    "observed_at": "2026-07-09",
                    "change_pct": 0.1,
                    "change_pct_label": "+0.1%",
                    "history": [],
                    "status": "ok",
                }
            ],
        }
        with TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            data_path = site / "data"
            data_path.mkdir(parents=True)
            (data_path / "dashboard.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            previous_card = build_briefing_card(
                {"headline": "기존", "summary": "기존 카드", "bullets": []},
                card_type="intraday",
                generated_at="2026-07-09T09:00:00+09:00",
                generated_label="2026-07-09 09:00 KST",
                metric_snapshot=briefing_metric_snapshot(previous_payload),
            )
            write_briefing_outputs(data_path, previous_card)
            session = FakePostSession(gemini_payload)

            with patch.dict("os.environ", {"GEMINI_API_KEY": "secret-test-key"}, clear=True):
                refreshed = refresh_briefing_site({"timezone": "Asia/Seoul"}, site, session, "intraday")

            self.assertEqual(session.post_count, 1)
            self.assertEqual(refreshed["morning_briefing"]["status"], "ok")
            self.assertEqual(refreshed["morning_briefing"]["headline"], "장중 변화")
            self.assertTrue(refreshed["morning_briefing"]["gemini_call_attempted"])

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

    def test_sec_capex_points_derives_quarters_from_cumulative_cash_flow(self):
        rows = [
            ("2025-06-01", "2025-08-31", 8_502_000_000, "2025-09-10"),
            ("2025-06-01", "2025-11-30", 20_535_000_000, "2025-12-11"),
            ("2025-06-01", "2026-02-28", 39_170_000_000, "2026-03-11"),
            ("2025-06-01", "2026-05-31", 55_663_000_000, "2026-06-22"),
        ]
        payload = {
            "facts": {
                "us-gaap": {
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "units": {
                            "USD": [
                                {
                                    "start": start,
                                    "end": end,
                                    "val": value,
                                    "form": "10-Q" if index < 3 else "10-K",
                                    "filed": filed,
                                }
                                for index, (start, end, value, filed) in enumerate(rows)
                            ]
                        }
                    }
                }
            }
        }

        self.assertEqual(
            sec_capex_points(payload),
            [
                (date(2025, 8, 31), 8_502_000_000),
                (date(2025, 11, 30), 12_033_000_000),
                (date(2026, 2, 28), 18_635_000_000),
                (date(2026, 5, 31), 16_493_000_000),
            ],
        )

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

    def test_usaspending_failure_keeps_cached_metric_and_marks_failed_attempt(self):
        class FailingSession:
            def post(self, *args, **kwargs):
                raise RuntimeError("temporary timeout")

        with TemporaryDirectory() as tmp:
            history_path = Path(tmp)
            (history_path / "usaspending-0.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "key": "usaspending-0",
                        "points": [["2026-05-01", 1.25], ["2026-06-01", 1.5]],
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "history": {"enabled": True, "dir": str(history_path)},
                "usaspending": {
                    "enabled": True,
                    "items": [{"name": "미국 NASA 계약 의무액", "industry": "우주"}],
                },
            }

            metrics = collect_usaspending_metrics(
                config, FailingSession(), date(2026, 7, 10)
            )

        self.assertEqual(metrics[0]["status"], "ok")
        self.assertEqual(metrics[0]["observed_at"], "2026-06-01")
        self.assertEqual(metrics[0]["display_value"], "$1.50B")
        self.assertTrue(metrics[0]["fetch_attempt_failed"])
        self.assertIn("이전 저장값 표시", metrics[0]["note"])

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

    def test_parse_kofia_daily_rows(self):
        payload = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {
                    "items": {
                        "item": [
                            {"basDt": "20260708", "invrDpsgAmt": "71000000000000"},
                            {"basDt": "20260709", "invrDpsgAmt": "72000000000000"},
                        ]
                    }
                },
            }
        }

        rows = parse_kofia_json_rows(payload)

        self.assertEqual(
            kofia_points_from_rows(rows, "invrDpsgAmt", scale=0.000000000001),
            [(date(2026, 7, 8), 71.0), (date(2026, 7, 9), 72.0)],
        )

    def test_kofia_cma_filters_total_rows(self):
        rows = [
            {"basDt": "20260709", "mngInvTgt": "RP형", "invrCtg": "합계", "actBal": "100"},
            {"basDt": "20260709", "mngInvTgt": "합계", "invrCtg": "개인", "actBal": "200"},
            {"basDt": "20260709", "mngInvTgt": "합계", "invrCtg": "합계", "actBal": "30000000000000"},
        ]

        self.assertEqual(
            kofia_points_from_rows(
                rows,
                "actBal",
                row_filter={"mngInvTgt": "합계", "invrCtg": "합계"},
                scale=0.000000000001,
            ),
            [(date(2026, 7, 9), 30.0)],
        )

    def test_collect_kofia_capital_market_metrics_builds_daily_metrics(self):
        payload_by_operation = {
            "getSecuritiesMarketTotalCapitalInfo": {
                "response": {
                    "header": {"resultCode": "00"},
                    "body": {"items": {"item": [
                        {"basDt": "20260708", "invrDpsgAmt": "71000000000000"},
                        {"basDt": "20260709", "invrDpsgAmt": "72000000000000"},
                    ]}},
                }
            },
            "getGrantingOfCreditBalanceInfo": {
                "response": {
                    "header": {"resultCode": "00"},
                    "body": {"items": {"item": [
                        {"basDt": "20260708", "crdTrFingWhl": "38000000000000"},
                        {"basDt": "20260709", "crdTrFingWhl": "39000000000000"},
                    ]}},
                }
            },
            "getCMAStatus": {
                "response": {
                    "header": {"resultCode": "00"},
                    "body": {"items": {"item": [
                        {"basDt": "20260709", "mngInvTgt": "RP형", "invrCtg": "합계", "actBal": "1"},
                        {"basDt": "20260708", "mngInvTgt": "합계", "invrCtg": "합계", "actBal": "30000000000000"},
                        {"basDt": "20260709", "mngInvTgt": "합계", "invrCtg": "합계", "actBal": "31000000000000"},
                    ]}},
                }
            },
        }

        class KofiaSession:
            def get(self, url, timeout=None, **kwargs):
                del timeout, kwargs
                operation = url.rsplit("/", 1)[-1].split("?", 1)[0]
                return FakeResponse(payload_by_operation[operation])

        with patch.dict("os.environ", {"DATA_GO_KR_SERVICE_KEY": "test-key"}):
            metrics = collect_kofia_capital_market_metrics(
                {"kofia": {"enabled": True, "endpoint": "https://example.test/service"}},
                KofiaSession(),
                date(2026, 7, 10),
            )

        by_key = {metric["history_key"]: metric for metric in metrics}
        self.assertEqual(by_key["kofia-securities-market-investor-deposits"]["frequency"], "일간")
        self.assertEqual(by_key["kofia-securities-market-investor-deposits"]["value"], 72.0)
        self.assertEqual(by_key["kofia-credit-financing-balance"]["value"], 39.0)
        self.assertEqual(by_key["kofia-cma-balance"]["value"], 31.0)
        self.assertTrue(all(metric["market_category"] == "신용·예탁금" for metric in metrics))

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
        self.assertEqual(parse_kosis_period("20260629", "D"), date(2026, 6, 29))
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
