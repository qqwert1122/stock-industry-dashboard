import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from macro_telegram_report.dashboard import flow_metrics_from_raw_document
from macro_telegram_report.market_flows import (
    flow_row_value,
    investor_slug,
    load_raw_flow_snapshot,
    merge_raw_flow_rows,
    raw_flow_known_dates,
    raw_flow_investors,
    raw_flow_series,
    raw_flow_snapshot_path,
    row_investor_name,
    rolling_sum_series,
    store_raw_flow_rows,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class MarketFlowsRawSnapshotTest(unittest.TestCase):
    def test_stock_raw_snapshot_preserves_all_investors_and_fields(self):
        rows = load_fixture("krx_flow_stock_rows.json")
        document = load_raw_flow_snapshot(Path("missing.json"), "kospi")

        merge_raw_flow_rows(document, date(2026, 7, 8), rows)

        stored = document["dates"]["2026-07-08"]
        self.assertEqual(stored, rows)
        self.assertEqual(len(stored), 11)
        self.assertEqual(
            [row["INVST_TP_NM"] for row in stored],
            ["개인", "외국인", "기관합계", "금융투자", "보험", "투신", "기타금융", "은행", "연기금", "사모", "기타법인"],
        )
        for row in stored:
            self.assertIn("ASK_TRDVAL", row)
            self.assertIn("BID_TRDVAL", row)
            self.assertIn("NETBID_TRDVAL", row)
            self.assertIn("ASK_TRDVOL", row)
            self.assertIn("BID_TRDVOL", row)
            self.assertIn("NETBID_TRDVOL", row)
        self.assertEqual(stored[6]["UNEXPECTED_FIELD"], "must stay")

    def test_futures_raw_snapshot_preserves_full_response_rows(self):
        rows = load_fixture("krx_flow_futures_rows.json")
        document = load_raw_flow_snapshot(Path("missing.json"), "k200-futures")

        merge_raw_flow_rows(document, date(2026, 7, 8), rows)

        stored = document["dates"]["2026-07-08"]
        self.assertEqual(stored, rows)
        self.assertEqual([row["INVST_TP_NM"] for row in stored], ["개인", "외국인", "기관"])
        self.assertEqual(stored[1]["DERIVATIVE_ONLY_FIELD"], "basis payload survives")

    def test_store_raw_flow_rows_round_trips_and_tracks_empty_dates(self):
        rows = load_fixture("krx_flow_stock_rows.json")
        with TemporaryDirectory() as tmp:
            document = store_raw_flow_rows(
                history_dir=tmp,
                market="kosdaq",
                observed_at=date(2026, 7, 8),
                rows=rows,
                today=date(2026, 7, 9),
                keep_calendar_days=30,
            )
            store_raw_flow_rows(
                history_dir=tmp,
                market="kosdaq",
                observed_at=date(2026, 7, 9),
                rows=[],
                today=date(2026, 7, 9),
                keep_calendar_days=30,
            )

            path = raw_flow_snapshot_path(tmp, "kosdaq")
            loaded = load_raw_flow_snapshot(path, "kosdaq")

        self.assertEqual(document["dates"]["2026-07-08"], rows)
        self.assertEqual(loaded["dates"]["2026-07-08"], rows)
        self.assertEqual(loaded["empty_dates"], ["2026-07-09"])
        self.assertEqual(raw_flow_known_dates(loaded), {"2026-07-08", "2026-07-09"})

    def test_raw_rows_can_be_reprocessed_into_all_measures(self):
        rows = load_fixture("krx_flow_stock_rows.json")
        document = load_raw_flow_snapshot(Path("missing.json"), "kospi")
        merge_raw_flow_rows(document, date(2026, 7, 8), rows)

        self.assertIn("기타금융", raw_flow_investors(document))
        self.assertEqual(investor_slug("기타금융"), "other-finance")
        self.assertEqual(flow_row_value(rows[0], "sell"), 1100.0)
        self.assertEqual(raw_flow_series(document, investor="개인", measure="net"), [(date(2026, 7, 8), 150.0)])
        self.assertEqual(rolling_sum_series([(date(2026, 7, 7), 10.0), (date(2026, 7, 8), 20.0)], 20)[-1][1], 30.0)

    def test_main_widget_rows_strip_unit_and_convert_to_억원(self):
        row = {
            "TRD_DD": "20260709",
            "INVST_TP": "외국인(십억원)",
            "ACC_ASK_TRDVAL": "8,540",
            "ACC_BID_TRDVAL": "8,643",
            "NETBID_TRDVAL": "103",
        }

        self.assertEqual(row_investor_name(row), "외국인")
        self.assertEqual(flow_row_value(row, "sell"), 85400.0)
        self.assertEqual(flow_row_value(row, "buy"), 86430.0)
        self.assertEqual(flow_row_value(row, "net"), 1030.0)

    def test_raw_snapshot_round_trip_keeps_existing_metric_output_byte_identical(self):
        rows = load_fixture("krx_flow_stock_rows.json")
        document = load_raw_flow_snapshot(Path("missing.json"), "kospi")
        merge_raw_flow_rows(document, date(2026, 7, 8), rows)
        before = json.dumps(
            flow_metrics_from_raw_document("kospi", "KOSPI", document, "https://data.krx.co.kr/"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        with TemporaryDirectory() as tmp:
            store_raw_flow_rows(
                history_dir=tmp,
                market="kospi",
                observed_at=date(2026, 7, 8),
                rows=rows,
                today=date(2026, 7, 9),
                keep_calendar_days=30,
            )
            loaded = load_raw_flow_snapshot(raw_flow_snapshot_path(tmp, "kospi"), "kospi")

        after = json.dumps(
            flow_metrics_from_raw_document("kospi", "KOSPI", loaded, "https://data.krx.co.kr/"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
