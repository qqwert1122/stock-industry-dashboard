import unittest

from macro_telegram_report.models import Section
from macro_telegram_report.report import format_report
from macro_telegram_report.telegram import split_message


class FormattingTest(unittest.TestCase):
    def test_format_report_contains_sections(self):
        text = format_report(
            "테스트 리포트",
            "2026-07-06 08:00 KST",
            [Section("FRED", ["- DGS10: 4.50%"])],
        )
        self.assertIn("[테스트 리포트]", text)
        self.assertIn("FRED", text)
        self.assertIn("DGS10", text)

    def test_split_message_keeps_all_text(self):
        text = "A" * 5000
        chunks = split_message(text, limit=4096)
        self.assertEqual("".join(chunks), text)
        self.assertEqual(len(chunks), 2)


if __name__ == "__main__":
    unittest.main()
