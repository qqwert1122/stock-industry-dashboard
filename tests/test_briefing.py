import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from macro_telegram_report.briefing import (
    build_briefing_card,
    update_intraday_track,
    write_briefing_outputs,
)


class BriefingCardTest(unittest.TestCase):
    def test_write_briefing_outputs_creates_day_file_and_index(self):
        with TemporaryDirectory() as tmp:
            data_path = Path(tmp)
            card = build_briefing_card(
                {"headline": "테스트", "summary": "요약", "bullets": []},
                card_type="close",
                generated_at="2026-07-09T06:15:00+09:00",
                generated_label="2026-07-09 06:15 KST",
            )

            index = write_briefing_outputs(data_path, card)

            day = json.loads((data_path / "briefings" / "2026-07-09.json").read_text(encoding="utf-8"))
            self.assertEqual(day["cards"][0]["card_type"], "close")
            self.assertEqual(index["cards"][0]["id"], card["id"])

    def test_intraday_track_flags_yen_carry_risk(self):
        payload1 = {
            "metrics": [
                {"name": "엔/달러 환율", "status": "ok", "value": 160.0, "display_value": "160엔", "observed_at": "2026-07-09"}
            ]
        }
        payload2 = {
            "metrics": [
                {"name": "엔/달러 환율", "status": "ok", "value": 156.0, "display_value": "156엔", "observed_at": "2026-07-09"}
            ]
        }
        with TemporaryDirectory() as tmp:
            data_path = Path(tmp)
            update_intraday_track(data_path, payload1, "2026-07-09T09:00:00+09:00")
            trajectory = update_intraday_track(data_path, payload2, "2026-07-09T10:00:00+09:00")

        self.assertTrue(trajectory["yen_carry_risk"])
        self.assertIn("엔캐리", trajectory["summary"])


if __name__ == "__main__":
    unittest.main()
