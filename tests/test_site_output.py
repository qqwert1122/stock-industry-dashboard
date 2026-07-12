from __future__ import annotations

from macro_telegram_report.site_output import (
    DASHBOARD_SCRIPT_PARTS,
    DASHBOARD_STYLE_PARTS,
    load_dashboard_template,
)


def test_dashboard_template_composes_all_partials_in_order():
    template = load_dashboard_template()

    assert len(DASHBOARD_STYLE_PARTS) == 5
    assert len(DASHBOARD_SCRIPT_PARTS) == 7
    assert "__DASHBOARD_CSS__" not in template
    assert "__DASHBOARD_SCRIPT__" not in template
    assert template.count("__DASHBOARD_JSON__") == 1
    assert template.count("<style>") == 1
    assert template.index(":root {") < template.index(".future-page")
    assert ".calendar-agenda-table-wrap" in template
    assert ".market-diagnosis" in template
    assert template.index("function metricById") < template.index("function futureData")
    assert template.index("function futureData") < template.index("function render()")


def test_industry_favorite_cards_rebind_after_industry_render():
    template = load_dashboard_template()
    industry_branch = template.split(
        "const favorites = renderFavoriteMetrics(favoriteMetrics().filter(isIndustryMetric)",
        1,
    )[1].split("function toggleMetricRow", 1)[0]

    assert "initFavoriteButtons(stack);" in industry_branch
    assert "initFavoritePager(stack);" in industry_branch
    assert "initDailyUpdateLinks();" in industry_branch
