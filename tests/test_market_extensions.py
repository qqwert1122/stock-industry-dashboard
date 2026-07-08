import json
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from macro_telegram_report.alerts import process_alerts
from macro_telegram_report.dashboard import make_metric, visible_dashboard_metrics
from macro_telegram_report.history_store import HistoryStore, percentile_stats
from macro_telegram_report.http_client import parse_retry_after
from macro_telegram_report.market_gauges import build_market_gauges
from macro_telegram_report.market_valuation import (
    parse_finra_margin_table,
    parse_multpl_table,
)


class MarketExtensionsTest(unittest.TestCase):
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
        ]

        gauges = build_market_gauges(metrics)

        self.assertIn("thermometer", gauges)
        self.assertIn("recession", gauges)
        self.assertGreaterEqual(len(gauges["thermometer"]["components"]), 3)
        self.assertEqual(gauges["recession"]["alert_count"], 2)

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


if __name__ == "__main__":
    unittest.main()
