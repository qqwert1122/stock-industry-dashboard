from __future__ import annotations

from macro_telegram_report.storage import load_json, write_json


def test_load_json_returns_fallback_for_missing_and_invalid_files(tmp_path):
    fallback = {"items": []}
    assert load_json(tmp_path / "missing.json", fallback) is fallback

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{broken", encoding="utf-8")
    assert load_json(invalid, fallback) is fallback


def test_write_json_preserves_pretty_and_compact_formats(tmp_path):
    value = {"한글": [1, 2]}
    pretty = tmp_path / "pretty.json"
    compact = tmp_path / "compact.json"

    write_json(pretty, value)
    write_json(compact, value, compact=True)

    assert pretty.read_text(encoding="utf-8") == '{\n  "한글": [\n    1,\n    2\n  ]\n}\n'
    assert compact.read_text(encoding="utf-8") == '{"한글":[1,2]}\n'
    assert load_json(pretty, None) == value
    assert load_json(compact, None) == value
