import unittest
from datetime import date, timedelta

from macro_telegram_report.dashboard import make_metric
from macro_telegram_report.history_store import percentile_stats
from macro_telegram_report.interpretation import build_interpretation, match_rule, percentile_zone


class InterpretationTest(unittest.TestCase):
    def test_percentile_zone_boundaries(self):
        self.assertEqual(percentile_zone(95), "hot")
        self.assertEqual(percentile_zone(75), "warm")
        self.assertEqual(percentile_zone(50), "neutral")
        self.assertEqual(percentile_zone(15), "cool")
        self.assertEqual(percentile_zone(5), "cold")

    def test_rule_priority_id_before_group(self):
        metric = {"id": "target", "group": "신용 스프레드", "name": "테스트"}
        rule = match_rule(
            metric,
            [
                {"match": {"group": "신용 스프레드"}, "polarity": "lower_is_better"},
                {"match": {"id": "target"}, "polarity": "context"},
            ],
        )

        self.assertEqual(rule["polarity"], "context")

    def test_build_interpretation_uses_percentile_and_polarity(self):
        points = [(date(2025, 1, 1) + timedelta(days=i), float(i)) for i in range(20)]
        metric = make_metric(
            industry="은행/금융",
            name="테스트 신용 스프레드",
            source="테스트",
            source_url="https://example.com",
            frequency="일간",
            automation="자동",
            status="ok",
            value=19.0,
            unit="%",
            observed_at=points[-1][0].isoformat(),
            previous_value=18.0,
            history=points,
            group="신용 스프레드",
            meaning="신용위험을 보여주는 스프레드입니다.",
        )
        metric["percentiles"] = percentile_stats(points, 19.0)

        interpretation = build_interpretation(metric, {})

        self.assertEqual(interpretation["zone"], "hot")
        self.assertIn("신용위험", interpretation["text"])
        self.assertIn("신용 위험", interpretation["text"])


if __name__ == "__main__":
    unittest.main()
