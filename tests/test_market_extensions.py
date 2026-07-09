import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from macro_telegram_report.alerts import process_alerts
from macro_telegram_report.dashboard import (
    assign_market_navigation_fields,
    calculate_us_net_liquidity,
    collect_global_liquidity_metrics,
    collect_us_liquidity_metrics,
    flow_metrics_from_raw_document,
    make_metric,
    parse_boj_points,
    parse_ecb_csv_points,
    update_market_gauge_history,
    visible_dashboard_metrics,
)
from macro_telegram_report.history_store import HistoryStore, percentile_stats
from macro_telegram_report.http_client import parse_retry_after
from macro_telegram_report.market_gauges import build_market_gauges
from macro_telegram_report.market_sentiment import (
    build_korea_fear_greed_score,
    fetch_krx_openapi_rows,
    high_low_counts,
    high_low_score,
    parse_cnn_fear_greed_payload,
)
from macro_telegram_report.market_valuation import (
    parse_finra_margin_table,
    parse_multpl_table,
)
from macro_telegram_report.market_flows import load_raw_flow_snapshot, merge_raw_flow_rows


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self.payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeKrxSession:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}
        self.params = {}
        self.url = ""

    def get(self, url, **kwargs):
        self.url = url
        self.headers = kwargs.get("headers", {})
        self.params = kwargs.get("params", {})
        return FakeResponse(self.payload)


class FakeLiquiditySession:
    def get(self, url, params=None, **kwargs):
        params = params or {}
        if "fiscaldata.treasury.gov" in url:
            return FakeResponse(
                {
                    "data": [
                        {
                            "record_date": "2024-01-02",
                            "account_type": "Treasury General Account (TGA) Closing Balance",
                            "open_today_bal": "800000",
                        },
                        {
                            "record_date": "2024-01-04",
                            "account_type": "Treasury General Account (TGA) Closing Balance",
                            "open_today_bal": "900000",
                        },
                    ]
                }
            )
        if params.get("series_id") == "RRPONTSYD":
            return FakeResponse(
                {
                    "observations": [
                        {"date": "2024-01-02", "value": "500000"},
                        {"date": "2024-01-05", "value": "400000"},
                    ]
                }
            )
        raise AssertionError(f"unexpected request: {url} {params}")


class FakeGlobalLiquiditySession:
    def get(self, url, params=None, **kwargs):
        params = params or {}
        if "ecos.bok.or.kr" in url:
            parts = url.split("/")
            stat_code = parts[10]
            item_code = parts[14]
            value = {
                ("103Y002", "BCAA1"): "650000",
                ("102Y004", "ABA1"): "305000",
                ("161Y005", "BBHS00"): "4160000",
                ("171Y003", "LAS0000"): "5750000",
                ("172Y001", "XS00000"): "7350000",
            }[(stat_code, item_code)]
            return FakeResponse(
                {
                    "StatisticSearch": {
                        "row": [
                            {"TIME": "202401", "DATA_VALUE": str(float(value) - 1000)},
                            {"TIME": "202402", "DATA_VALUE": value},
                        ]
                    }
                }
            )
        if "stat-search.boj.or.jp" in url:
            code = params.get("code")
            value = {
                "MABJMTA": 7600000,
                "MABS1AN11": 6700000,
                "MAM1NAM2M2MO": 12600000,
                "MACAB2201": 5550000,
            }[code]
            return FakeResponse(
                {
                    "STATUS": 200,
                    "RESULTSET": [
                        {
                            "SERIES_CODE": code,
                            "VALUES": {
                                "SURVEY_DATES": [202401, 202402],
                                "VALUES": [value - 1000, value],
                            },
                        }
                    ],
                }
            )
        if "data-api.ecb.europa.eu" in url:
            key = url.rsplit("/", 1)[-1]
            value = {
                "D.U2.C.EXLIQ.U2.EUR": 2440000,
                "M.U2.N.C.T00.A.1.Z5.0000.Z01.E": 9800000,
                "M.U2.Y.V.M30.X.1.U2.2300.Z01.E": 16900000,
                "M.U2.C.LT00001.Z5.EUR": 4450000,
            }[key]
            return FakeResponse(
                text=(
                    "KEY,TIME_PERIOD,OBS_VALUE\n"
                    f"ECB.{key},2024-01,{value - 1000}\n"
                    f"ECB.{key},2024-02,{value}\n"
                )
            )
        raise AssertionError(f"unexpected request: {url} {params}")


class MarketExtensionsTest(unittest.TestCase):
    def test_dev_mock_payload_includes_market_gauges(self):
        import scripts.dev_dashboard as dev_dashboard

        dashboard = dev_dashboard.load_dashboard_module()
        payload = dev_dashboard.build_mock_payload(dashboard)
        gauges = payload.get("market_gauges") or {}

        self.assertIn("thermometer", gauges)
        self.assertIn("recession", gauges)
        self.assertIn("fear_greed", gauges)
        self.assertGreaterEqual(len(gauges["thermometer"]["components"]), 3)
        self.assertGreaterEqual(len(gauges["recession"]["signals"]), 2)
        self.assertEqual(
            [item["name"] for item in gauges["fear_greed"]["items"]],
            ["미국 CNN", "코스피", "코스닥"],
        )
        metrics_by_name = {str(metric.get("name") or ""): metric for metric in payload.get("metrics", [])}
        self.assertEqual(metrics_by_name["Sahm Rule 침체 지표"]["interpretation"]["source"], "threshold")
        self.assertIn("기준 0.5", metrics_by_name["Sahm Rule 침체 지표"]["interpretation"]["headline"])
        self.assertEqual(metrics_by_name["미국 10Y-3M 금리차"]["interpretation"]["source"], "threshold")
        self.assertIn("역전 기준 0", metrics_by_name["미국 10Y-3M 금리차"]["interpretation"]["headline"])
        self.assertEqual(metrics_by_name["VIX"]["interpretation"]["source"], "threshold")
        self.assertIn("기준 30", metrics_by_name["VIX"]["interpretation"]["headline"])
        self.assertEqual(metrics_by_name["미국 하이일드 회사채 OAS"]["interpretation"]["source"], "threshold")
        self.assertIn("기준 5%p", metrics_by_name["미국 하이일드 회사채 OAS"]["interpretation"]["headline"])
        self.assertEqual(metrics_by_name["코스피 PBR"]["interpretation"]["source"], "threshold")
        self.assertIn("기준 0.9", metrics_by_name["코스피 PBR"]["interpretation"]["headline"])
        self.assertEqual(metrics_by_name["코스피 외국인 순매수"]["interpretation"]["source"], "flow")
        self.assertIn("외국인", metrics_by_name["코스피 외국인 순매수"]["interpretation"]["headline"])
        self.assertEqual(metrics_by_name["S&P 500 Shiller CAPE"]["interpretation"]["source"], "percentile")
        self.assertIn("1871년 이후", metrics_by_name["S&P 500 Shiller CAPE"]["interpretation"]["headline"])

    def test_retry_after_is_capped_for_dashboard_builds(self):
        self.assertEqual(parse_retry_after("120"), 20.0)
        self.assertEqual(parse_retry_after("2.5"), 2.5)
        self.assertIsNone(parse_retry_after("not-a-number"))

    def test_visible_metrics_keep_history_enrichment_fields(self):
        metric = make_metric(
            industry="매크로",
            name="테스트",
            source="테스트 소스",
            source_url="https://example.com",
            frequency="월간",
            automation="자동",
            status="ok",
            value=1.0,
            observed_at="2026-07-01",
            history=[(date(2026, 7, 1), 1.0)],
            history_key="custom-history-key",
            history_merge="latest",
        )

        visible = visible_dashboard_metrics([metric])[0]

        self.assertEqual(visible["status"], "ok")
        self.assertEqual(visible["history_key"], "custom-history-key")
        self.assertEqual(visible["history_merge"], "latest")

    def test_visible_metrics_keep_market_navigation_fields(self):
        metric = make_metric(
            industry="매크로",
            name="테스트 수급",
            source="테스트",
            source_url="https://example.com",
            frequency="일간",
            automation="자동",
            status="ok",
            value=1.0,
            observed_at="2026-07-08",
            history=[(date(2026, 7, 8), 1.0)],
            group="수급",
            section="market",
            market_category="수급",
            also_market_category=["심리·변동성"],
            chart_style="flow_bars",
            refresh_scope="intraday",
        )

        visible = visible_dashboard_metrics([metric])[0]

        self.assertEqual(visible["section"], "market")
        self.assertEqual(visible["market_category"], "수급")
        self.assertEqual(visible["also_market_category"], ["심리·변동성"])
        self.assertEqual(visible["chart_style"], "flow_bars")
        self.assertEqual(visible["refresh_scope"], "intraday")

    def test_assign_market_navigation_moves_indices_and_parallels_rates(self):
        kospi = make_metric(
            industry="매크로",
            name="코스피",
            source="Yahoo",
            source_url="https://example.com",
            frequency="일간",
            automation="자동",
            status="ok",
            value=3000,
            observed_at="2026-07-08",
            history=[(date(2026, 7, 8), 3000)],
            group="시장지수",
        )
        rate = make_metric(
            industry="은행/금융",
            name="미국 10년 국채금리",
            source="FRED",
            source_url="https://example.com",
            frequency="일간",
            automation="자동",
            status="ok",
            value=4.1,
            observed_at="2026-07-08",
            history=[(date(2026, 7, 8), 4.1)],
            group="금리",
        )

        assign_market_navigation_fields([kospi, rate])

        self.assertEqual(kospi["section"], "market")
        self.assertEqual(kospi["market_category"], "종합")
        self.assertNotEqual(rate.get("section"), "market")
        self.assertEqual(rate["also_market_category"], ["금리·채권"])

    def test_us_net_liquidity_aligns_components_as_of_each_day(self):
        walcl = [(date(2024, 1, 1), 7000.0), (date(2024, 1, 3), 7100.0)]
        tga = [(date(2024, 1, 2), 800.0), (date(2024, 1, 4), 900.0)]
        rrp = [(date(2024, 1, 2), 500.0), (date(2024, 1, 5), 400.0)]

        points = calculate_us_net_liquidity(walcl, tga, rrp)

        self.assertEqual(points[0], (date(2024, 1, 2), 5700.0))
        self.assertEqual(points[1], (date(2024, 1, 3), 5800.0))
        self.assertEqual(points[2], (date(2024, 1, 4), 5700.0))
        self.assertEqual(points[-1], (date(2024, 1, 5), 5800.0))

    def test_official_liquidity_parsers_read_boj_and_ecb_shapes(self):
        boj_points = parse_boj_points(
            {
                "STATUS": 200,
                "RESULTSET": [
                    {
                        "VALUES": {
                            "SURVEY_DATES": [202401, 202402],
                            "VALUES": [1000, 1100],
                        }
                    }
                ],
            }
        )
        ecb_points = parse_ecb_csv_points(
            "KEY,TIME_PERIOD,OBS_VALUE\n"
            "ILM.D.U2.C.EXLIQ.U2.EUR,2024-01-02,2000\n"
            "ILM.D.U2.C.EXLIQ.U2.EUR,2024-01-03,2100\n"
        )

        self.assertEqual(boj_points, [(date(2024, 1, 1), 1000.0), (date(2024, 2, 1), 1100.0)])
        self.assertEqual(ecb_points, [(date(2024, 1, 2), 2000.0), (date(2024, 1, 3), 2100.0)])

    @patch.dict("os.environ", {"FRED_API_KEY": "test-key"})
    def test_us_liquidity_collector_builds_market_group_in_display_order(self):
        walcl = make_metric(
            industry="매크로",
            name="미국 연준 총자산",
            source="FRED API",
            source_url="https://fred.stlouisfed.org/series/WALCL",
            frequency="주간",
            automation="자동",
            status="ok",
            value=7100,
            unit="$B",
            observed_at="2024-01-03",
            previous_value=7000,
            history=[(date(2024, 1, 1), 7000.0), (date(2024, 1, 3), 7100.0)],
            group="유동성",
            history_key="fred-WALCL",
        )

        metrics = collect_us_liquidity_metrics(
            {"history": {"enabled": False}},
            FakeLiquiditySession(),
            date(2024, 1, 5),
            [walcl],
        )

        self.assertEqual([metric["name"] for metric in metrics], ["미국 순유동성", "미국 연준 총자산", "미국 TGA", "미국 역레포"])
        self.assertTrue(all(metric["group"] == "미국 유동성" for metric in metrics))
        self.assertTrue(all(metric["section"] == "market" for metric in metrics))
        self.assertTrue(all(metric["market_category"] == "유동성" for metric in metrics))
        self.assertEqual(metrics[0]["value"], 5800.0)
        self.assertIn("가장 최근 값을 사용", metrics[0]["meaning"])
        self.assertEqual(metrics[2]["frequency"], "일간")
        self.assertEqual(metrics[2]["history_key"], "fiscaldata-tga")

    @patch.dict("os.environ", {"ECOS_API_KEY": "test-key"})
    def test_global_liquidity_collector_builds_region_groups(self):
        metrics = collect_global_liquidity_metrics(
            {"history": {"enabled": False}},
            FakeGlobalLiquiditySession(),
            date(2024, 2, 29),
        )

        by_name = {metric["name"]: metric for metric in metrics}
        self.assertEqual(len(metrics), 13)
        self.assertEqual(by_name["한국 M2"]["value"], 4160.0)
        self.assertEqual(by_name["한국 M2"]["unit"], "조원")
        self.assertEqual(by_name["일본 BOJ 총자산"]["value"], 760.0)
        self.assertEqual(by_name["일본 BOJ 총자산"]["unit"], "¥T")
        self.assertEqual(by_name["유럽 초과유동성"]["value"], 2440.0)
        self.assertEqual(by_name["유럽 초과유동성"]["frequency"], "일간")
        self.assertTrue(all(metric["section"] == "market" for metric in metrics))
        self.assertTrue(all(metric["market_category"] == "유동성" for metric in metrics))
        self.assertEqual(
            [metric["group"] for metric in metrics[:5]],
            ["한국 유동성", "한국 유동성", "한국 유동성", "한국 유동성", "한국 유동성"],
        )

    def test_flow_metrics_from_raw_document_generates_gross_and_net_metrics(self):
        rows = json.loads((Path(__file__).resolve().parent / "fixtures" / "krx_flow_stock_rows.json").read_text(encoding="utf-8"))
        document = load_raw_flow_snapshot(Path("missing.json"), "kospi")
        merge_raw_flow_rows(document, date(2026, 7, 8), rows)

        metrics = flow_metrics_from_raw_document("kospi", "KOSPI", document, "https://data.krx.co.kr/")
        by_name = {metric["name"]: metric for metric in metrics}

        self.assertIn("KOSPI 기타금융 매수", by_name)
        self.assertIn("KOSPI 기타금융 순매수", by_name)
        self.assertEqual(by_name["KOSPI 기타금융 순매수"]["chart_style"], "flow_bars")
        self.assertEqual(by_name["KOSPI 기타금융 매수"]["exclude_from_movers"], True)
        self.assertIn("산 금액에서 판 금액을 뺀 값", by_name["KOSPI 기타금융 순매수"]["meaning"])
        self.assertIn("사들인 거래대금", by_name["KOSPI 기타금융 매수"]["meaning"])
        self.assertNotIn("매크로 흐름을 이해할 때 참고하는 보조 지표", by_name["KOSPI 기타금융 순매수"]["meaning"])

    def test_history_store_does_not_persist_empty_placeholder(self):
        with TemporaryDirectory() as tmp:
            store = HistoryStore(tmp)
            self.assertEqual(store.series("empty-key"), [])

            store.save_all()

            self.assertFalse(Path(tmp, "empty-key.json").exists())

    def test_history_store_merges_points_and_calculates_percentile(self):
        with TemporaryDirectory() as tmp:
            store = HistoryStore(tmp)
            points = [
                (date(2020, 1, 1), 10.0),
                (date(2021, 1, 1), 20.0),
                (date(2022, 1, 1), 30.0),
                (date(2023, 1, 1), 40.0),
                (date(2024, 1, 1), 50.0),
                (date(2025, 1, 1), 60.0),
                (date(2026, 1, 1), 70.0),
                (date(2027, 1, 1), 80.0),
            ]

            merged = store.merge("test metric", points, name="테스트", unit="%")
            store.save_all()

            self.assertEqual(merged[-1], (date(2027, 1, 1), 80.0))
            stored = json.loads(Path(tmp, "test-metric.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["last_date"], "2027-01-01")
            stats = percentile_stats(merged, 80.0)
            self.assertEqual(stats["all"]["pct"], 93.8)

    def test_market_gauges_build_thermometer_and_recession_signals(self):
        def metric(name, value, percentile):
            return {
                "id": name,
                "name": name,
                "status": "ok",
                "value": value,
                "display_value": str(value),
                "percentiles": {"y10": {"pct": percentile}},
                "history": [],
            }

        metrics = [
            metric("VIX", 20.0, 90.0),
            metric("미국 하이일드 회사채 OAS", 3.5, 80.0),
            metric("코스피 PBR", 1.4, 90.0),
            metric("S&P 500 Shiller CAPE", 35.0, 95.0),
            metric("미국 10Y-3M 금리차", -0.2, 10.0),
            metric("Sahm Rule 침체 지표", 0.55, 90.0),
            metric("미국 CNN 공포탐욕지수", 62.0, 75.0),
            metric("코스피 공포탐욕지수", 38.0, 35.0),
        ]

        gauges = build_market_gauges(metrics)

        self.assertIn("thermometer", gauges)
        self.assertIn("recession", gauges)
        self.assertIn("fear_greed", gauges)
        self.assertGreaterEqual(len(gauges["thermometer"]["components"]), 3)
        self.assertEqual(gauges["recession"]["alert_count"], 2)
        self.assertEqual(gauges["fear_greed"]["items"][0]["label"], "탐욕")
        self.assertEqual(gauges["fear_greed"]["items"][1]["label"], "공포")

    def test_market_gauge_history_upserts_daily_snapshot(self):
        previous = {
            "version": 1,
            "snapshots": [
                {
                    "date": "2026-07-07",
                    "generated_at": "2026-07-07T08:00:00+09:00",
                    "thermometer": {"score": 40},
                },
                {
                    "date": "2026-07-08",
                    "generated_at": "2026-07-08T08:00:00+09:00",
                    "thermometer": {"score": 55},
                },
            ],
        }
        payload = {
            "generated_at": "2026-07-08T11:30:00+09:00",
            "market_gauges": {
                "thermometer": {
                    "score": 72.5,
                    "label": "주의",
                    "components": [
                        {
                            "name": "VIX",
                            "metric_id": "vix",
                            "value_label": "20.1",
                            "percentile": 80.0,
                            "heat": 80.0,
                            "basis": "최근 10년 백분위",
                        }
                    ],
                },
                "recession": {
                    "alert_count": 1,
                    "warn_count": 0,
                    "summary": "주의 신호가 있습니다.",
                    "signals": [
                        {
                            "name": "Sahm Rule",
                            "metric_id": "sahm",
                            "value_label": "0.6%p",
                            "status": "alert",
                            "description": "고용 둔화",
                        }
                    ],
                },
                "fear_greed": {
                    "comment": "0에 가까울수록 공포입니다.",
                    "items": [
                        {
                            "name": "미국 CNN",
                            "metric_id": "fg-us",
                            "metric_name": "미국 CNN 공포탐욕지수",
                            "score": 62.0,
                            "label": "탐욕",
                            "value_label": "62점",
                        }
                    ],
                },
            },
        }

        history = update_market_gauge_history(previous, payload, "Asia/Seoul")

        self.assertEqual(history["count"], 2)
        self.assertEqual(history["first_date"], "2026-07-07")
        self.assertEqual(history["last_date"], "2026-07-08")
        self.assertEqual(history["snapshots"][-1]["thermometer"]["score"], 72.5)
        self.assertEqual(history["snapshots"][-1]["recession"]["signals"][0]["status"], "alert")
        self.assertEqual(history["snapshots"][-1]["fear_greed"]["items"][0]["label"], "탐욕")

    def test_market_gauge_history_keeps_existing_when_current_gauges_empty(self):
        previous = {
            "version": 1,
            "snapshots": [{"date": "2026-07-07", "thermometer": {"score": 40}}],
        }

        history = update_market_gauge_history(
            previous,
            {"generated_at": "2026-07-08T08:00:00+09:00", "market_gauges": {}},
            "Asia/Seoul",
        )

        self.assertEqual(history["count"], 1)
        self.assertEqual(history["snapshots"][0]["date"], "2026-07-07")

    def test_alerts_send_only_on_new_threshold_crossing(self):
        config = {
            "alerts": {
                "enabled": True,
                "state_file": "",
                "weekly_digest": False,
                "rules": [{"metric": "VIX", "above": 40, "message": "공포 구간"}],
            }
        }
        payload = {
            "metrics": [
                {
                    "name": "VIX",
                    "status": "ok",
                    "value": 45.0,
                    "display_value": "45.0",
                    "observed_at": "2026-07-08",
                }
            ],
            "source_status": [],
        }

        with TemporaryDirectory() as tmp:
            config["alerts"]["state_file"] = str(Path(tmp, "alerts.json"))
            with patch("macro_telegram_report.alerts.send_telegram") as send:
                first = process_alerts(
                    config, payload, session=None, now=datetime(2026, 7, 8), include_weekly=False
                )
                second = process_alerts(
                    config, payload, session=None, now=datetime(2026, 7, 8), include_weekly=False
                )

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(send.call_count, 1)

    def test_alerts_append_signal_log_on_trigger_and_clear(self):
        config = {
            "alerts": {
                "enabled": True,
                "state_file": "",
                "signal_log_file": "",
                "weekly_digest": False,
                "rules": [{"metric": "VIX", "above": 40, "message": "공포 구간"}],
            }
        }
        payload = {
            "metrics": [
                {
                    "id": "vix",
                    "name": "VIX",
                    "status": "ok",
                    "value": 45.0,
                    "display_value": "45.0",
                    "observed_at": "2026-07-08",
                }
            ],
            "source_status": [],
        }

        with TemporaryDirectory() as tmp:
            config["alerts"]["state_file"] = str(Path(tmp, "alerts.json"))
            config["alerts"]["signal_log_file"] = str(Path(tmp, "signal_log.json"))
            with patch("macro_telegram_report.alerts.send_telegram"):
                process_alerts(config, payload, session=None, now=datetime(2026, 7, 8), include_weekly=False)
                process_alerts(config, payload, session=None, now=datetime(2026, 7, 8), include_weekly=False)
                payload["metrics"][0]["value"] = 35.0
                payload["metrics"][0]["display_value"] = "35.0"
                payload["metrics"][0]["observed_at"] = "2026-07-09"
                process_alerts(config, payload, session=None, now=datetime(2026, 7, 9), include_weekly=False)
            document = json.loads(Path(tmp, "signal_log.json").read_text(encoding="utf-8"))

        self.assertEqual([event["direction"] for event in document["events"]], ["triggered", "cleared"])
        self.assertEqual(document["events"][0]["metric_id"], "vix")

    def test_market_valuation_parsers(self):
        multpl_html = """
        <table id="datatable">
          <tr><td>Jul 01, 2026</td><td>38.2</td></tr>
          <tr><td>Jun 01, 2026</td><td>37.5</td></tr>
        </table>
        """
        finra_html = """
        <table>
          <tr><td>May-26</td><td>850,123</td></tr>
          <tr><td>Apr-26</td><td>840,000</td></tr>
        </table>
        """

        self.assertEqual(
            parse_multpl_table(multpl_html),
            [(date(2026, 6, 1), 37.5), (date(2026, 7, 1), 38.2)],
        )
        self.assertEqual(
            parse_finra_margin_table(finra_html),
            [(date(2026, 4, 1), 840.0), (date(2026, 5, 1), 850.123)],
        )

    def test_cnn_fear_greed_payload_parser_includes_current_score(self):
        first_timestamp = datetime(2026, 7, 6, tzinfo=timezone.utc).timestamp() * 1000
        current_timestamp = datetime(2026, 7, 7, tzinfo=timezone.utc).timestamp() * 1000
        payload = {
            "fear_and_greed": {
                "score": 43,
                "timestamp": "2026-07-07T23:59:45+00:00",
            },
            "fear_and_greed_historical": {
                "data": [
                    {"x": first_timestamp, "y": 40.2},
                    {"x": current_timestamp, "y": 42.7},
                ]
            },
        }

        points = parse_cnn_fear_greed_payload(payload)

        self.assertEqual(points[-1], (date(2026, 7, 7), 43.0))
        self.assertEqual(len(points), 2)

    def test_krx_openapi_error_response_is_not_treated_as_empty_market_day(self):
        session = FakeKrxSession({"respMsg": "Unauthorized API Call", "respCode": "401"})

        with self.assertRaisesRegex(ValueError, "Unauthorized API Call"):
            fetch_krx_openapi_rows(
                session,
                base_url="https://data-dbg.krx.co.kr/svc/apis",
                category="idx",
                api_id="kospi_dd_trd",
                auth_key="dummy",
                target_date=date(2026, 7, 7),
            )

        self.assertEqual(session.params["basDd"], "20260707")
        self.assertEqual(session.headers["AUTH_KEY"], "dummy")

    def test_korea_fear_greed_score_uses_breadth_high_low_and_volatility(self):
        start = date(2026, 1, 1)
        index_points = [
            (start + timedelta(days=index), 1000.0 + index)
            for index in range(150)
            if (start + timedelta(days=index)).weekday() < 5
        ]
        cursor = index_points[-1][0]
        while len(index_points) < 150:
            cursor += timedelta(days=1)
            if cursor.weekday() < 5:
                index_points.append((cursor, index_points[-1][1] + 1.0))

        snapshot_dates = [index_points[-3][0], index_points[-2][0], index_points[-1][0]]
        document = {
            "dates": {
                snapshot_dates[0].isoformat(): {"A": 10.0, "B": 10.0, "C": 10.0},
                snapshot_dates[1].isoformat(): {"A": 11.0, "B": 9.0, "C": 10.0},
                snapshot_dates[2].isoformat(): {"A": 12.0, "B": 8.0, "C": 10.5},
            },
            "breadth": {
                snapshot_dates[2].isoformat(): {
                    "advancers": 2,
                    "decliners": 1,
                    "unchanged": 0,
                    "total": 3,
                }
            },
        }
        vkospi_points = [
            (index_points[-30 + index][0], 30.0 - index * 0.2)
            for index in range(30)
        ]

        counts = high_low_counts(
            document,
            snapshot_dates[-1],
            window_days=10,
            min_points=3,
        )
        score = build_korea_fear_greed_score(
            market_label="코스피",
            index_points=index_points,
            snapshot_document=document,
            vkospi_points=vkospi_points,
            high_low_window_days=10,
            min_high_low_points=3,
        )

        self.assertEqual(counts["new_highs"], 2)
        self.assertEqual(counts["new_lows"], 1)
        self.assertAlmostEqual(high_low_score(counts), 66.7)
        self.assertIsNotNone(score)
        self.assertGreaterEqual(score["score"], 0)
        self.assertLessEqual(score["score"], 100)


if __name__ == "__main__":
    unittest.main()
