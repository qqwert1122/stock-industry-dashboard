"""지표별 장기 히스토리를 repo 내 JSON 파일로 축적/조회하는 저장소.

- 매 실행에서 수집기가 가져온 포인트를 기존 캐시와 병합해 전체 기간을 보존합니다.
- 최초 1회 백필 이후에는 수집기가 최근 구간만 요청해도 장기 시계열이 유지되므로
  API 호출량을 늘리지 않고 히스토리를 확보할 수 있습니다.
- 백분위 통계(전체 기간/최근 10년)와 다운샘플링된 장기 시리즈를 payload에 제공합니다.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

STORE_VERSION = 1
SNAPSHOT_MODE = "latest"
FULL_MODE = "full"
SKIP_MODE = "none"


def safe_history_key(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣_.-]+", "-", value.strip())
    return cleaned.strip("-") or "metric"


class HistoryStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._cache: dict[str, dict[str, Any]] = {}

    def path_for(self, key: str) -> Path:
        return self.root / f"{safe_history_key(key)}.json"

    def load(self, key: str) -> dict[str, Any]:
        safe_key = safe_history_key(key)
        if safe_key in self._cache:
            return self._cache[safe_key]
        path = self.path_for(safe_key)
        document: dict[str, Any] = {"version": STORE_VERSION, "key": safe_key, "points": []}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("points"), list):
                    document = loaded
            except (json.JSONDecodeError, OSError):
                pass
        self._cache[safe_key] = document
        return document

    def series(self, key: str) -> list[tuple[date, float]]:
        return parse_stored_points(self.load(key).get("points", []))

    def merge(
        self,
        key: str,
        points: list[tuple[date, float]],
        *,
        name: str = "",
        unit: str = "",
        source: str = "",
        mode: str = FULL_MODE,
    ) -> list[tuple[date, float]]:
        """포인트를 캐시에 병합하고 전체 시리즈를 반환합니다.

        mode="latest"는 스냅샷형 소스용으로 최신 포인트만 축적합니다(과거 합성
        포인트가 캐시를 오염시키지 않도록).
        """
        if mode == SKIP_MODE:
            return sorted(points, key=lambda item: item[0])

        document = self.load(key)
        merged: dict[str, float] = {}
        for point_date, value in parse_stored_points(document.get("points", [])):
            merged[point_date.isoformat()] = value

        incoming = sorted(points, key=lambda item: item[0])
        if mode == SNAPSHOT_MODE and incoming:
            incoming = incoming[-1:]
        for point_date, value in incoming:
            if value is None:
                continue
            merged[point_date.isoformat()] = float(value)

        stored_points = [[key_text, merged[key_text]] for key_text in sorted(merged)]
        document["points"] = stored_points
        document["version"] = STORE_VERSION
        if name:
            document["name"] = name
        if unit:
            document["unit"] = unit
        if source:
            document["source"] = source
        if stored_points:
            document["first_date"] = stored_points[0][0]
            document["last_date"] = stored_points[-1][0]

        self._cache[safe_history_key(key)] = document
        return parse_stored_points(stored_points)

    def save(self, key: str) -> None:
        safe_key = safe_history_key(key)
        document = self._cache.get(safe_key)
        if document is None:
            return
        path = self.path_for(safe_key)
        if not parse_stored_points(document.get("points", [])):
            if path.exists():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def save_all(self) -> None:
        for key in list(self._cache):
            self.save(key)


def parse_stored_points(raw: Any) -> list[tuple[date, float]]:
    points: list[tuple[date, float]] = []
    if not isinstance(raw, list):
        return points
    for item in raw:
        try:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                point_date = date.fromisoformat(str(item[0]))
                value = float(item[1])
            elif isinstance(item, dict):
                point_date = date.fromisoformat(str(item.get("date")))
                value = float(item.get("value"))
            else:
                continue
        except (TypeError, ValueError):
            continue
        points.append((point_date, value))
    points.sort(key=lambda point: point[0])
    return points


def percentile_of(values: list[float], target: float) -> float | None:
    if not values:
        return None
    below = sum(1 for value in values if value < target)
    equal = sum(1 for value in values if value == target)
    return round(100.0 * (below + 0.5 * equal) / len(values), 1)


def quantile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def window_stats(points: list[tuple[date, float]], current: float | None) -> dict[str, Any] | None:
    if len(points) < 8 or current is None:
        return None
    values = [value for _, value in points]
    ordered = sorted(values)
    return {
        "count": len(values),
        "from": points[0][0].isoformat(),
        "to": points[-1][0].isoformat(),
        "pct": percentile_of(values, current),
        "min": ordered[0],
        "p20": quantile(ordered, 0.2),
        "median": quantile(ordered, 0.5),
        "p80": quantile(ordered, 0.8),
        "max": ordered[-1],
    }


def percentile_stats(
    points: list[tuple[date, float]], current: float | None
) -> dict[str, Any] | None:
    """전체 기간과 최근 10년 창의 백분위 통계를 계산합니다."""
    if not points or current is None:
        return None
    stats_all = window_stats(points, current)
    if stats_all is None:
        return None
    cutoff = points[-1][0] - timedelta(days=3652)
    recent = [point for point in points if point[0] >= cutoff]
    stats_10y = window_stats(recent, current)
    span_days = (points[-1][0] - points[0][0]).days
    return {
        "span_years": round(span_days / 365.25, 1),
        "all": stats_all,
        "y10": stats_10y if stats_10y and len(recent) < len(points) else stats_all,
    }


def downsample_history(
    points: list[tuple[date, float]], max_points: int = 480
) -> list[tuple[date, float]]:
    """장기 차트용 다운샘플링. 최근 1년은 원본, 1~3년은 주간, 그 이전은 월간 마지막 값."""
    if len(points) <= max_points:
        return points

    latest = points[-1][0]
    one_year = latest - timedelta(days=366)
    three_years = latest - timedelta(days=1096)

    monthly: dict[str, tuple[date, float]] = {}
    weekly: dict[str, tuple[date, float]] = {}
    recent: list[tuple[date, float]] = []
    for point in points:
        point_date = point[0]
        if point_date >= one_year:
            recent.append(point)
        elif point_date >= three_years:
            weekly[f"{point_date.isocalendar()[0]}-{point_date.isocalendar()[1]}"] = point
        else:
            monthly[f"{point_date.year}-{point_date.month:02d}"] = point

    sampled = sorted(monthly.values()) + sorted(weekly.values()) + recent
    if len(sampled) > max_points:
        # 여전히 많으면(수십 년 일간 시계열) 오래된 구간을 균등 간격으로 솎아냅니다.
        keep_tail_count = max_points // 2
        overflow = sampled[:-keep_tail_count]
        keep_tail = sampled[-keep_tail_count:]
        budget = max(1, max_points - keep_tail_count)
        stride = -(-len(overflow) // budget)
        sampled = overflow[::stride] + keep_tail
    return sampled
