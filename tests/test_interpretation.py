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
        self.assertIn("신용 위험", interpretation["text"])
        self.assertEqual(interpretation["source"], "percentile")

    def test_threshold_boundaries_are_explicit(self):
        config = {
            "interpretation": {
                "rules": [
                    {
                        "match": {"history_key": "fred-SAHMREALTIME"},
                        "thresholds": [
                            {"at_or_above": 0.5, "zone": "bad", "label": "침체 신호", "text": "기준 0.5 대비 침체 신호입니다."},
                            {"below": 0.5, "zone": "neutral", "label": "기준 아래", "text": "기준 0.5 대비 안전 구간입니다."},
                        ],
                    },
                    {
                        "match": {"history_key": "fred-T10Y3M"},
                        "thresholds": [
                            {"below": 0, "zone": "bad", "label": "역전", "text": "역전 기준 0 아래입니다."},
                            {"at_or_above": 0, "zone": "neutral", "label": "정상", "text": "역전 기준 0 이상입니다."},
                        ],
                    },
                    {
                        "match": {"history_key": "fred-BAMLH0A0HYM2"},
                        "thresholds": [
                            {"at_or_above": 5, "zone": "bad", "label": "신용경색", "text": "기준 5%p 이상입니다."},
                            {"at_or_below": 3, "zone": "watch", "label": "낙관 과열", "text": "기준 3%p 이하입니다."},
                            {"default": True, "zone": "neutral", "label": "중립", "text": "기준 3%p/5%p 사이입니다."},
                        ],
                    },
                    {
                        "match": {"name": "코스피 PBR"},
                        "thresholds": [
                            {"below": 0.9, "zone": "good", "label": "저평가", "text": "기준 0.9 미만입니다."},
                            {"above_strict": 1.3, "zone": "bad", "label": "고평가", "text": "기준 1.3 초과입니다."},
                            {"default": True, "zone": "neutral", "label": "중립", "text": "기준 0.9/1.3 사이입니다."},
                        ],
                    },
                ]
            }
        }

        self.assertEqual(self.interpret("Sahm Rule", 0.5, config, history_key="fred-SAHMREALTIME")["zone"], "bad")
        self.assertIn("기준 0.5", self.interpret("Sahm Rule", 0.5, config, history_key="fred-SAHMREALTIME")["headline"])
        self.assertEqual(self.interpret("Sahm Rule", 0.49, config, history_key="fred-SAHMREALTIME")["zone"], "neutral")
        self.assertEqual(self.interpret("10Y-3M", -0.01, config, history_key="fred-T10Y3M")["zone"], "bad")
        self.assertEqual(self.interpret("10Y-3M", 0.0, config, history_key="fred-T10Y3M")["zone"], "neutral")
        self.assertEqual(self.interpret("HY OAS", 5.0, config, history_key="fred-BAMLH0A0HYM2")["zone"], "bad")
        self.assertEqual(self.interpret("HY OAS", 3.0, config, history_key="fred-BAMLH0A0HYM2")["zone"], "watch")
        self.assertEqual(self.interpret("코스피 PBR", 0.89, config)["zone"], "good")
        self.assertEqual(self.interpret("코스피 PBR", 0.9, config)["zone"], "neutral")
        self.assertEqual(self.interpret("코스피 PBR", 1.3, config)["zone"], "neutral")
        self.assertEqual(self.interpret("코스피 PBR", 1.31, config)["zone"], "bad")

    def test_vix_threshold_boundaries(self):
        config = {
            "interpretation": {
                "rules": [
                    {
                        "match": {"name": "VIX"},
                        "thresholds": [
                            {"at_or_above": 40, "zone": "bad", "label": "패닉", "text": "기준 40 이상입니다."},
                            {"at_or_above": 30, "zone": "watch", "label": "공포", "text": "기준 30 이상입니다."},
                            {"below": 20, "zone": "good", "label": "안정", "text": "기준 20 미만입니다."},
                            {"default": True, "zone": "neutral", "label": "중립", "text": "기준 20/30 사이입니다."},
                        ],
                    }
                ]
            }
        }

        self.assertEqual(self.interpret("VIX", 40.0, config)["zone"], "bad")
        self.assertEqual(self.interpret("VIX", 30.0, config)["zone"], "watch")
        self.assertEqual(self.interpret("VIX", 20.0, config)["zone"], "neutral")
        self.assertEqual(self.interpret("VIX", 19.99, config)["zone"], "good")

    def test_unknown_neutral_rule_does_not_add_value_judgment(self):
        points = [(date(2025, 1, 1) + timedelta(days=i), float(i)) for i in range(20)]
        metric = make_metric(
            industry="테스트",
            name="판단 없는 지표",
            source="테스트",
            source_url="https://example.com",
            frequency="월간",
            automation="자동",
            status="ok",
            value=19.0,
            unit="지수",
            observed_at=points[-1][0].isoformat(),
            previous_value=18.0,
            history=points,
            group="기타",
            meaning="값의 위치와 추세를 확인하는 지표입니다.",
        )
        metric["percentiles"] = percentile_stats(points, 19.0)

        interpretation = build_interpretation(metric, {"interpretation": {"rules": []}})

        self.assertNotRegex(interpretation["text"], r"좋|나쁘|부담|우호|위험|과열|저평가|고평가")

    def test_cape_uses_1871_percentile_headline(self):
        points = [(date(2025, 1, 1) + timedelta(days=i), float(i)) for i in range(20)]
        metric = make_metric(
            industry="매크로",
            name="S&P 500 Shiller CAPE",
            source="Multpl",
            source_url="https://www.multpl.com/shiller-pe",
            frequency="일간",
            automation="자동",
            status="ok",
            value=19.0,
            unit="배",
            observed_at=points[-1][0].isoformat(),
            previous_value=18.0,
            history=points,
            group="밸류에이션",
            meaning="CAPE입니다.",
        )
        metric["percentiles"] = percentile_stats(points, 19.0)
        config = {
            "interpretation": {
                "rules": [
                    {
                        "match": {"name": "S&P 500 Shiller CAPE"},
                        "polarity": "lower_is_better",
                        "percentile_basis": "1871년 이후",
                        "percentile_zone_labels": {"hot": "역사적 극단 고평가"},
                    }
                ]
            }
        }

        interpretation = build_interpretation(metric, config)

        self.assertEqual(interpretation["headline"], "1871년 이후 상위 97.5% - 역사적 극단 고평가")
        self.assertIn("값이 높은 쪽", interpretation["detail_text"])

    def test_flow_interpretation_uses_dedicated_template(self):
        points = [
            (date(2026, 7, 1), -10.0),
            (date(2026, 7, 2), 100.0),
            (date(2026, 7, 3), 120.0),
            (date(2026, 7, 6), 130.0),
            (date(2026, 7, 7), 110.0),
            (date(2026, 7, 8), 140.0),
        ]
        metric = make_metric(
            industry="매크로",
            name="코스피 외국인 순매수",
            source="KRX",
            source_url="https://data.krx.co.kr/",
            frequency="일간",
            automation="자동",
            status="ok",
            value=140.0,
            unit="억원",
            observed_at=points[-1][0].isoformat(),
            previous_value=110.0,
            history=points,
            group="외국인",
            meaning="외국인 순매수입니다.",
            chart_style="flow_bars",
        )

        interpretation = build_interpretation(metric, {})

        self.assertEqual(interpretation["source"], "flow")
        self.assertEqual(interpretation["zone"], "good")
        self.assertIn("외국인 5거래일 연속 순매수", interpretation["headline"])
        self.assertIn("수급이 지수를 받치는 구간", interpretation["headline"])

    def interpret(self, name, value, config, *, history_key=""):
        points = [(date(2025, 1, 1) + timedelta(days=i), value) for i in range(3)]
        metric = make_metric(
            industry="매크로",
            name=name,
            source="테스트",
            source_url="https://example.com",
            frequency="일간",
            automation="자동",
            status="ok",
            value=value,
            unit="",
            observed_at=points[-1][0].isoformat(),
            previous_value=value,
            history=points,
            group="테스트",
            meaning="테스트 지표입니다.",
            history_key=history_key,
        )
        metric["percentiles"] = percentile_stats(points, value)
        return build_interpretation(metric, config)


if __name__ == "__main__":
    unittest.main()
