from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account


SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


def report(property_id: str, token: str, body: dict) -> dict:
    response = requests.post(
        f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def rows(payload: dict) -> list[dict]:
    dimensions = [item["name"] for item in payload.get("dimensionHeaders", [])]
    metrics = [item["name"] for item in payload.get("metricHeaders", [])]
    result = []
    for row in payload.get("rows", []):
        item = {name: value.get("value", "") for name, value in zip(dimensions, row.get("dimensionValues", []))}
        item.update({name: float(value.get("value", 0)) for name, value in zip(metrics, row.get("metricValues", []))})
        result.append(item)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a safe GA4 aggregate snapshot for the static admin page.")
    parser.add_argument("--out", default="site/data/analytics.json")
    args = parser.parse_args()
    property_id = os.environ["GA_PROPERTY_ID"]
    credentials_info = json.loads(os.environ["GA_SERVICE_ACCOUNT_JSON"])
    credentials = service_account.Credentials.from_service_account_info(credentials_info, scopes=[SCOPE])
    credentials.refresh(Request())
    common = {"dateRanges": [{"startDate": "30daysAgo", "endDate": "today"}], "limit": "20"}
    summary = report(property_id, credentials.token, {
        **common,
        "metrics": [{"name": name} for name in ("screenPageViews", "totalUsers", "sessions", "eventCount")],
    })
    daily = report(property_id, credentials.token, {
        **common,
        "dimensions": [{"name": "date"}],
        "metrics": [{"name": "screenPageViews"}, {"name": "totalUsers"}],
        "orderBys": [{"dimension": {"dimensionName": "date"}}],
        "limit": "31",
    })
    pages = report(property_id, credentials.token, {
        **common,
        "dimensions": [{"name": "pagePath"}],
        "metrics": [{"name": "screenPageViews"}, {"name": "totalUsers"}],
        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
    })
    clicks = report(property_id, credentials.token, {
        **common,
        "dimensions": [{"name": "customEvent:element_label"}],
        "metrics": [{"name": "eventCount"}],
        "dimensionFilter": {"filter": {"fieldName": "eventName", "stringFilter": {"value": "ui_click"}}},
        "orderBys": [{"metric": {"metricName": "eventCount"}, "desc": True}],
    })
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": "최근 30일",
        "summary": (rows(summary) or [{}])[0],
        "daily": rows(daily),
        "pages": rows(pages),
        "clicks": rows(clicks),
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
