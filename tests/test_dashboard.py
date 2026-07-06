import unittest
from datetime import date

from macro_telegram_report.dashboard import (
    DEFAULT_INDUSTRIES,
    collect_stablecoin_metrics,
    make_metric,
    render_dashboard_html,
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

    def get(self, url, timeout):
        self.url = url
        self.timeout = timeout
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

    def test_default_industries_include_new_categories(self):
        for industry in ["방산", "스테이블코인", "전력", "로봇", "우주", "바이오", "배터리"]:
            self.assertIn(industry, DEFAULT_INDUSTRIES)

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


if __name__ == "__main__":
    unittest.main()
