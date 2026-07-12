#!/usr/bin/env python3
"""Print reviewed-ready market-cap points for company_arcs.yaml.

This is an authoring helper, not a build-time collector. Values from
CompaniesMarketCap are converted to nominal USD billions.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from typing import Any

import requests
import yaml


DATA_PATTERN = re.compile(r"data\s*=\s*(\[.*?\]);", re.DOTALL)


def market_cap_points(
    html: str,
    years: set[int] | None = None,
    anchors: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    match = DATA_PATTERN.search(html)
    if not match:
        raise ValueError("market-cap history was not found in the page")
    rows = json.loads(match.group(1))
    by_year: dict[int, list[tuple[str, float]]] = {}
    for row in rows:
        observed = datetime.fromtimestamp(int(row["d"]), tz=timezone.utc).date()
        if years and observed.year not in years:
            continue
        # The source encodes market cap in units of USD 100,000.
        value_billions = float(row["m"]) / 10_000
        by_year.setdefault(observed.year, []).append((observed.isoformat(), value_billions))

    points: list[dict[str, Any]] = []
    for year, observations in sorted(by_year.items()):
        kind = (anchors or {}).get(year, "year_end")
        if kind == "peak":
            observed_on, value = max(observations, key=lambda item: item[1])
        elif kind == "trough":
            observed_on, value = min(observations, key=lambda item: item[1])
        else:
            observed_on, value = observations[-1]
            kind = "year_end"
        point: dict[str, Any] = {"y": year, "v": round(value, 4)}
        if kind != "year_end":
            point.update({"kind": kind, "date": observed_on})
        points.append(point)
    return points


def fetch_market_caps(
    slug: str,
    years: set[int] | None = None,
    anchors: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    response = requests.get(
        f"https://companiesmarketcap.com/{slug}/marketcap/",
        headers={"User-Agent": "Mozilla/5.0 (compatible; luceforge-arc-authoring/1.0)"},
        timeout=30,
    )
    response.raise_for_status()
    return market_cap_points(response.text, years=years, anchors=anchors)


def main() -> None:
    parser = argparse.ArgumentParser(description="CompaniesMarketCap 이력을 USD 십억 단위 YAML로 변환")
    parser.add_argument("slug", help="CompaniesMarketCap URL slug, e.g. cisco")
    parser.add_argument("--years", help="comma-separated years to retain")
    parser.add_argument("--anchor", action="append", default=[], metavar="YEAR:KIND")
    args = parser.parse_args()
    years = {int(value) for value in args.years.split(",")} if args.years else None
    anchors: dict[int, str] = {}
    for raw_anchor in args.anchor:
        year_text, kind = raw_anchor.split(":", 1)
        if kind not in {"peak", "trough"}:
            raise SystemExit(f"Invalid anchor kind {kind!r}; use peak or trough")
        anchors[int(year_text)] = kind
    points = fetch_market_caps(args.slug, years=years, anchors=anchors)
    print(yaml.safe_dump({"series": points}, sort_keys=False, allow_unicode=True).strip())


if __name__ == "__main__":
    main()
