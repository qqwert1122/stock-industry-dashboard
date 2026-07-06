import unittest
from datetime import date

from macro_telegram_report.dashboard import make_metric, render_dashboard_html


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


if __name__ == "__main__":
    unittest.main()
