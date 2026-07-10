from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

FUTURE_DATA_VERSION = 1
DEFAULT_FUTURE_DIR = Path("data/future")
DEFAULT_CATEGORIES = ["전체", "AI", "로봇·모빌리티", "바이오", "에너지", "우주"]
TECH_REQUIRED_FIELDS = ("id", "name", "category", "status", "what", "why", "now", "as_of")
PREDICTION_REQUIRED_FIELDS = ("year", "source_label", "source")
TRACK_REQUIRED_FIELDS = (
    "id",
    "name",
    "predicted_by",
    "by_id",
    "predicted_in",
    "predicted_for",
    "predicted_for_year",
    "actual_label",
    "what",
    "outcome",
    "lesson",
    "source",
)
TRACK_JUDGED_STATUSES = {"early", "on_time", "late", "missed"}
TRACK_SCORE_MIN_JUDGED = 5
GLOSSARY_REQUIRED_FIELDS = ("id", "term", "short", "source")
READING_REQUIRED_FIELDS = (
    "title",
    "url",
    "type",
    "level",
    "lang",
    "effort",
    "why",
    "checked_at",
    "curated_by",
)
READING_LEVELS = ("입문", "중급", "심화")
READING_LEVELS_EN = {"입문": "Beginner", "중급": "Intermediate", "심화": "Advanced"}
READING_TYPES_EN = {
    "공식문서": "Official",
    "리포트": "Report",
    "데이터": "Data",
    "뉴스레터": "Newsletter",
    "책": "Book",
    "강의": "Course",
    "글": "Article",
}
COMMON_READING_IDS = {"_common", "common", "all", "공통"}
MAX_READINGS_PER_LEVEL = 8
STALE_DAYS = 180
LINK_FAILURE_WARNING_COUNT = 2
LADDER_REQUIRED_FIELDS = ("id", "name", "source", "rungs")
BREAKDOWN_REQUIREMENT_REQUIRED_FIELDS = ("id", "name", "what", "gap", "confidence", "as_of", "source")
BREAKDOWN_CONFIDENCE_LEVELS = {"high", "medium", "low"}
DEFAULT_TRUSTED_DOMAINS = {
    "ai.gov",
    "aiindex.stanford.edu",
    "bostondynamics.com",
    "brycetech.com",
    "cancer.gov",
    "clinicaltrials.gov",
    "dmv.ca.gov",
    "energy.gov",
    "epoch.ai",
    "fda.gov",
    "fusionindustryassociation.org",
    "hai.stanford.edu",
    "ibm.com",
    "ifr.org",
    "kurzweilai.net",
    "nasa.gov",
    "nature.com",
    "open.fda.gov",
    "ourworldindata.org",
    "payloadspace.com",
    "penguinrandomhouse.com",
    "tesla.com",
    "thespacedevs.com",
    "unitree.com",
    "waymo.com",
}
DEFAULT_BLOCKED_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "reddit.com",
    "t.me",
    "telegram.me",
    "threads.net",
    "tiktok.com",
    "twitter.com",
    "x.com",
}


def load_future_yaml(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(loaded, list):
        return []
    return [item for item in loaded if isinstance(item, dict)]


def load_future_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def parse_future_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def future_data_dir(config: dict[str, Any]) -> Path:
    future_config = config.get("future", {}) if isinstance(config.get("future"), dict) else {}
    return Path(str(future_config.get("dir") or DEFAULT_FUTURE_DIR))


def warning_record(kind: str, item_id: str, message: str) -> dict[str, str]:
    return {"kind": kind, "id": item_id, "message": message}


def url_domain(url: Any) -> str:
    host = urlparse(str(url or "")).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def domain_matches(domain: str, domains: set[str]) -> bool:
    domain = domain.lower().removeprefix("www.")
    return any(domain == item or domain.endswith(f".{item}") for item in domains)


def load_domain_policy(base_dir: Path) -> tuple[set[str], set[str]]:
    policy = load_future_mapping(base_dir / "trusted_domains.yaml")
    trusted = {
        str(item).lower().removeprefix("www.")
        for item in (policy.get("trusted_domains") or [])
        if str(item or "").strip()
    } or set(DEFAULT_TRUSTED_DOMAINS)
    blocked = {
        str(item).lower().removeprefix("www.")
        for item in (policy.get("blocked_domains") or [])
        if str(item or "").strip()
    } or set(DEFAULT_BLOCKED_DOMAINS)
    return trusted, blocked


def load_removed_urls(base_dir: Path) -> set[str]:
    loaded = yaml.safe_load((base_dir / "removed.yaml").read_text(encoding="utf-8")) if (base_dir / "removed.yaml").exists() else {}
    if isinstance(loaded, list):
        values = loaded
    elif isinstance(loaded, dict):
        values = loaded.get("removed") or loaded.get("removed_urls") or []
    else:
        values = []
    return {str(item).strip() for item in values if str(item or "").strip()}


def reading_level_en(level: str) -> str:
    return READING_LEVELS_EN.get(level, level)


def reading_type_en(reading_type: str) -> str:
    return READING_TYPES_EN.get(reading_type, reading_type)


def is_agent_curated(value: Any) -> bool:
    return str(value or "").strip().lower() in {"agent", "readings_agent", "future_readings_agent", "auto"}


def reading_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    level = str(item.get("level") or "")
    level_order = READING_LEVELS.index(level) if level in READING_LEVELS else len(READING_LEVELS)
    trusted_order = 0 if item.get("trusted") else 1
    return (level_order, trusted_order, str(item.get("title") or ""))


def normalize_lookup_text(value: Any) -> str:
    return re.sub(r"[\s._·:/()-]+", "", str(value or "").lower())


def metric_symbol(metric: dict[str, Any]) -> str:
    history_key = str(metric.get("history_key") or "")
    if history_key.startswith("equity-"):
        return history_key.removeprefix("equity-").upper()
    match = re.search(r"\(([A-Za-z0-9.^=-]+)\)\s*$", str(metric.get("name") or ""))
    return match.group(1).upper() if match else ""


def metric_indexes(metrics: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_key: dict[str, dict[str, Any]] = {}
    by_symbol: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        for raw_key in (
            metric.get("id"),
            metric.get("history_key"),
            metric.get("name"),
            metric.get("name_en"),
        ):
            key = normalize_lookup_text(raw_key)
            if key and key not in by_key:
                by_key[key] = metric
        symbol = metric_symbol(metric)
        if symbol and symbol not in by_symbol:
            by_symbol[symbol] = metric
    return by_key, by_symbol


def resolve_metric_ref(ref: Any, by_key: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if isinstance(ref, dict):
        candidates = [ref.get("id"), ref.get("history_key"), ref.get("name")]
    else:
        candidates = [ref]
    metric = None
    for candidate in candidates:
        key = normalize_lookup_text(candidate)
        if key and key in by_key:
            metric = by_key[key]
            break
        if key:
            for lookup_key, lookup_metric in by_key.items():
                if key in lookup_key or lookup_key in key:
                    metric = lookup_metric
                    break
        if metric:
            break
    if not metric:
        return None
    return {
        "id": metric.get("id"),
        "history_key": metric.get("history_key"),
        "name": metric.get("name"),
        "name_en": metric.get("name_en"),
        "display_value": metric.get("display_value"),
        "change_pct": metric.get("change_pct"),
        "change_pct_label": metric.get("change_pct_label"),
        "change_abs_label": metric.get("change_abs_label"),
        "unit": metric.get("unit"),
        "history": metric.get("history") or [],
    }


def resolve_company_ref(ref: Any, by_symbol: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if isinstance(ref, dict):
        symbol = str(ref.get("symbol") or "").upper()
        label = str(ref.get("label") or ref.get("name") or symbol)
        label_en = str(ref.get("label_en") or ref.get("name_en") or label)
    else:
        symbol = str(ref or "").upper()
        label = symbol
        label_en = symbol
    metric = by_symbol.get(symbol)
    if metric:
        label = str(metric.get("name") or label)
        label_en = str(metric.get("name_en") or label_en or label)
    return {
        "symbol": symbol,
        "label": label,
        "label_en": label_en,
        "metric_id": metric.get("id") if metric else "",
        "display_value": metric.get("display_value") if metric else "",
        "change_pct": metric.get("change_pct") if metric else None,
        "change_pct_label": metric.get("change_pct_label") if metric else "",
    }


def parse_company_like_ref(ref: Any) -> dict[str, str]:
    if isinstance(ref, dict):
        symbol = str(ref.get("symbol") or "").strip().upper()
        label = str(ref.get("label") or ref.get("name") or symbol).strip()
        label_en = str(ref.get("label_en") or ref.get("name_en") or label).strip()
        return {"symbol": symbol, "label": label, "label_en": label_en}
    text = str(ref or "").strip()
    match = re.match(r"^(?P<label>.+?)\((?P<symbol>[A-Za-z0-9.^=_-]+)\)$", text)
    if match:
        label = match.group("label").strip()
        symbol = match.group("symbol").strip().upper()
        return {"symbol": symbol, "label": label, "label_en": label}
    return {"symbol": "", "label": text, "label_en": text}


def resolve_breakdown_party(ref: Any, by_symbol: dict[str, dict[str, Any]]) -> dict[str, Any]:
    parsed = parse_company_like_ref(ref)
    if parsed["symbol"]:
        resolved = resolve_company_ref(parsed, by_symbol)
        if resolved.get("label") == resolved.get("symbol") and parsed["label"]:
            resolved["label"] = parsed["label"]
        if resolved.get("label_en") == resolved.get("symbol") and parsed["label_en"]:
            resolved["label_en"] = parsed["label_en"]
        return resolved
    return {
        "symbol": "",
        "label": parsed["label"],
        "label_en": parsed["label_en"],
        "metric_id": "",
        "display_value": "",
        "change_pct": None,
        "change_pct_label": "",
    }


def normalize_ladder_level(value: Any) -> str:
    return normalize_lookup_text(value)


def normalize_ladder(raw: dict[str, Any], warnings: list[dict[str, str]]) -> dict[str, Any] | None:
    ladder_id = str(raw.get("id") or raw.get("name") or "ladder")
    for field in LADDER_REQUIRED_FIELDS:
        if not raw.get(field):
            warnings.append(warning_record("future_ladder", ladder_id, f"{field} 필드가 비어 있습니다."))
    rungs_raw = raw.get("rungs") if isinstance(raw.get("rungs"), list) else []
    if not raw.get("id") or not rungs_raw:
        return None
    rungs: list[dict[str, Any]] = []
    index_by_level: dict[str, int] = {}
    for index, rung in enumerate(item for item in rungs_raw if isinstance(item, dict)):
        level = str(rung.get("level") or "").strip()
        if not level:
            warnings.append(warning_record("future_ladder", ladder_id, "level이 비어 있는 단계가 있습니다."))
            continue
        normalized = {
            "level": level,
            "label": str(rung.get("label") or level),
            "label_en": str(rung.get("label_en") or rung.get("label") or level),
            "desc": str(rung.get("desc") or ""),
            "desc_en": str(rung.get("desc_en") or rung.get("desc") or ""),
            "index": len(rungs),
        }
        index_by_level[normalize_ladder_level(level)] = normalized["index"]
        index_by_level[normalize_ladder_level(normalized["label"])] = normalized["index"]
        index_by_level[normalize_ladder_level(normalized["label_en"])] = normalized["index"]
        rungs.append(normalized)
    if not rungs:
        return None
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or ""),
        "name_en": str(raw.get("name_en") or raw.get("name") or ""),
        "source": str(raw.get("source") or ""),
        "source_label": str(raw.get("source_label") or ""),
        "source_label_en": str(raw.get("source_label_en") or raw.get("source_label") or ""),
        "rungs": rungs,
        "_index_by_level": index_by_level,
    }


def load_ladder_definitions(base_dir: Path, warnings: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    ladders: dict[str, dict[str, Any]] = {}
    for raw in load_future_yaml(base_dir / "ladders.yaml"):
        normalized = normalize_ladder(raw, warnings)
        if normalized:
            ladders[str(normalized["id"])] = normalized
    return ladders


def compact_ladder(ladder: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ladder.get("id"),
        "name": ladder.get("name"),
        "name_en": ladder.get("name_en"),
        "source": ladder.get("source"),
        "source_label": ladder.get("source_label"),
        "source_label_en": ladder.get("source_label_en"),
        "rungs": [
            {
                "level": rung.get("level"),
                "label": rung.get("label"),
                "label_en": rung.get("label_en"),
                "desc": rung.get("desc"),
                "desc_en": rung.get("desc_en"),
                "index": rung.get("index"),
            }
            for rung in ladder.get("rungs", [])
        ],
    }


def ladder_rung(ladder: dict[str, Any], value: Any) -> dict[str, Any] | None:
    index = ladder.get("_index_by_level", {}).get(normalize_ladder_level(value))
    if isinstance(index, int):
        rungs = ladder.get("rungs", [])
        if 0 <= index < len(rungs):
            return rungs[index]
    return None


def requirement_bottleneck_tokens(requirement: dict[str, Any]) -> set[str]:
    text = " ".join(
        str(requirement.get(field) or "")
        for field in ("id", "name", "name_en", "what", "what_en", "gap", "gap_en")
    )
    raw_tokens = re.split(r"[\s,./·:;|()\[\]_-]+", text.lower())
    stopwords = {
        "bottleneck",
        "future",
        "level",
        "stage",
        "current",
        "target",
        "and",
        "the",
        "병목",
        "현재",
        "필요",
        "단계",
    }
    return {
        normalize_lookup_text(token)
        for token in raw_tokens
        if len(normalize_lookup_text(token)) >= 2 and normalize_lookup_text(token) not in stopwords
    }


def bottleneck_matches_requirement(bottleneck_text: str, requirement: dict[str, Any]) -> bool:
    lookup = normalize_lookup_text(bottleneck_text)
    if not lookup:
        return True
    return any(token and token in lookup for token in requirement_bottleneck_tokens(requirement))


def normalize_breakdown_requirement(
    raw: dict[str, Any],
    *,
    tech_id: str,
    ladders: dict[str, dict[str, Any]],
    by_key: dict[str, dict[str, Any]],
    by_symbol: dict[str, dict[str, Any]],
    today: date,
    warnings: list[dict[str, str]],
) -> dict[str, Any] | None:
    requirement_id = str(raw.get("id") or raw.get("name") or "requirement")
    item_id = f"{tech_id}:{requirement_id}"
    for field in BREAKDOWN_REQUIREMENT_REQUIRED_FIELDS:
        if not raw.get(field):
            warnings.append(warning_record("future_breakdown", item_id, f"{field} 필드가 비어 있습니다."))
    if not raw.get("id") or not raw.get("name"):
        return None

    as_of = parse_future_date(raw.get("as_of"))
    stale = False
    if not as_of:
        warnings.append(warning_record("future_breakdown", item_id, "as_of 날짜를 읽을 수 없습니다."))
    else:
        stale = (today - as_of).days > STALE_DAYS
        if stale:
            warnings.append(warning_record("future_breakdown", item_id, f"as_of가 {STALE_DAYS}일을 넘었습니다."))

    confidence = str(raw.get("confidence") or "").strip().lower()
    if confidence and confidence not in BREAKDOWN_CONFIDENCE_LEVELS:
        warnings.append(warning_record("future_breakdown", item_id, f"confidence={confidence} 값을 알 수 없습니다."))
    confidence = confidence if confidence in BREAKDOWN_CONFIDENCE_LEVELS else "medium"

    metric = resolve_metric_ref(raw.get("metric_ref") or raw.get("metric"), by_key)
    manual_score = int_or_none(raw.get("gap_score"))
    target_label = str(raw.get("target_label") or "").strip()
    target_label_en = str(raw.get("target_label_en") or target_label).strip()
    current_label = str(raw.get("current_label") or "").strip()
    current_label_en = str(raw.get("current_label_en") or current_label).strip()
    ladder_payload: dict[str, Any] | None = None
    required_rung: dict[str, Any] | None = None
    current_rung: dict[str, Any] | None = None
    required_index: int | None = None
    current_index: int | None = None
    gap_steps: int | None = None
    kind = "continuous"

    ladder_id = str(raw.get("ladder") or "").strip()
    if ladder_id:
        kind = "ladder"
        ladder = ladders.get(ladder_id)
        if not ladder:
            warnings.append(warning_record("future_breakdown", item_id, f"ladder={ladder_id} 정의를 찾을 수 없습니다."))
        else:
            ladder_payload = compact_ladder(ladder)
            required_rung = ladder_rung(ladder, raw.get("required_rung"))
            current_rung = ladder_rung(ladder, raw.get("current_rung"))
            if not required_rung:
                warnings.append(warning_record("future_breakdown", item_id, f"required_rung={raw.get('required_rung')} 단계를 찾을 수 없습니다."))
            if not current_rung:
                warnings.append(warning_record("future_breakdown", item_id, f"current_rung={raw.get('current_rung')} 단계를 찾을 수 없습니다."))
            if required_rung and current_rung:
                required_index = int(required_rung.get("index") or 0)
                current_index = int(current_rung.get("index") or 0)
                gap_steps = max(required_index - current_index, 0)
                target_label = target_label or str(required_rung.get("label") or raw.get("required_rung") or "")
                target_label_en = target_label_en or str(required_rung.get("label_en") or target_label)
                current_label = current_label or str(current_rung.get("label") or raw.get("current_rung") or "")
                current_label_en = current_label_en or str(current_rung.get("label_en") or current_label)

    bottleneck_score = max(int(gap_steps or 0), int(manual_score or 0))
    metric_label = str(raw.get("metric") or raw.get("metric_ref") or "").strip()
    metric_label_en = str(raw.get("metric_en") or metric_label).strip()
    return {
        "id": requirement_id,
        "flow_id": f"{tech_id}:{requirement_id}",
        "name": str(raw.get("name") or ""),
        "name_en": str(raw.get("name_en") or raw.get("name") or ""),
        "kind": kind,
        "what": str(raw.get("what") or ""),
        "what_en": str(raw.get("what_en") or raw.get("what") or ""),
        "gap": str(raw.get("gap") or ""),
        "gap_en": str(raw.get("gap_en") or raw.get("gap") or ""),
        "target_label": target_label,
        "target_label_en": target_label_en,
        "current_label": current_label,
        "current_label_en": current_label_en,
        "ladder": ladder_payload,
        "required_rung": str(raw.get("required_rung") or ""),
        "current_rung": str(raw.get("current_rung") or ""),
        "required_index": required_index,
        "current_index": current_index,
        "gap_steps": gap_steps,
        "bottleneck_score": bottleneck_score,
        "is_bottleneck": False,
        "satisfied": bottleneck_score <= 0,
        "confidence": confidence,
        "stale": stale,
        "as_of": str(raw.get("as_of") or ""),
        "source": str(raw.get("source") or ""),
        "source_label": str(raw.get("source_label") or ""),
        "source_label_en": str(raw.get("source_label_en") or raw.get("source_label") or ""),
        "metric_label": metric_label,
        "metric_label_en": metric_label_en,
        "metric": metric,
        "achieved_by": [resolve_breakdown_party(item, by_symbol) for item in (raw.get("achieved_by") or [])],
        "pursuing": [resolve_breakdown_party(item, by_symbol) for item in (raw.get("pursuing") or [])],
    }


def build_future_breakdown(
    base_dir: Path,
    technologies_raw: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    *,
    today: date,
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    by_key, by_symbol = metric_indexes(metrics)
    ladders = load_ladder_definitions(base_dir, warnings)
    known_tech = {str(item.get("id") or ""): item for item in technologies_raw if item.get("id")}
    by_tech: dict[str, dict[str, Any]] = {}
    requirement_count = 0
    bottleneck_count = 0

    for block in load_future_yaml(base_dir / "breakdown.yaml"):
        tech_id = str(block.get("tech") or block.get("technology") or "").strip()
        if not tech_id:
            warnings.append(warning_record("future_breakdown", "unknown", "tech 필드가 비어 있습니다."))
            continue
        tech_raw = known_tech.get(tech_id)
        if not tech_raw:
            warnings.append(warning_record("future_breakdown", tech_id, "technologies.yaml에서 기술을 찾을 수 없습니다."))
            continue
        requirements_raw = block.get("requirements") if isinstance(block.get("requirements"), list) else []
        requirements = [
            normalized
            for raw in requirements_raw
            if isinstance(raw, dict)
            if (
                normalized := normalize_breakdown_requirement(
                    raw,
                    tech_id=tech_id,
                    ladders=ladders,
                    by_key=by_key,
                    by_symbol=by_symbol,
                    today=today,
                    warnings=warnings,
                )
            )
        ]
        max_score = max([int(item.get("bottleneck_score") or 0) for item in requirements], default=0)
        for item in requirements:
            if max_score > 0 and int(item.get("bottleneck_score") or 0) == max_score:
                item["is_bottleneck"] = True
                bottleneck_count += 1
        bottleneck_text = " ".join(str(tech_raw.get(key) or "") for key in ("bottleneck", "bottleneck_en"))
        if bottleneck_text and requirements and not any(
            item.get("is_bottleneck") and bottleneck_matches_requirement(bottleneck_text, item)
            for item in requirements
        ):
            warnings.append(
                warning_record(
                    "future_breakdown_bottleneck",
                    tech_id,
                    "technologies.yaml의 병목 문구와 breakdown 자동 병목이 다릅니다.",
                )
            )
        requirement_count += len(requirements)
        by_tech[tech_id] = {
            "tech": tech_id,
            "requirements": requirements,
            "bottleneck_ids": [str(item.get("id") or "") for item in requirements if item.get("is_bottleneck")],
            "updated_at": max([str(item.get("as_of") or "") for item in requirements], default=""),
        }

    return {
        "by_tech": by_tech,
        "ladders": [compact_ladder(ladder) for ladder in ladders.values()],
        "summary": {
            "technology_count": len(by_tech),
            "requirement_count": requirement_count,
            "bottleneck_count": bottleneck_count,
        },
    }


def compact_prediction(raw: dict[str, Any]) -> dict[str, Any]:
    predicted = raw.get("predicted") if isinstance(raw.get("predicted"), dict) else {}
    year = predicted.get("year")
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = None
    return {
        "year": year,
        "label": str(predicted.get("label") or (f"{year}" if year else "")),
        "label_en": str(predicted.get("label_en") or predicted.get("label") or (f"{year}" if year else "")),
        "source_label": str(predicted.get("source_label") or ""),
        "source_label_en": str(predicted.get("source_label_en") or predicted.get("source_label") or ""),
        "source": str(predicted.get("source") or ""),
    }


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def slug_key(value: Any, fallback: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9가-힣]+", "-", text).strip("-")
    return text or fallback


def future_band_for_year(year: int | None, today: date) -> str:
    if not year:
        return "미정"
    if year < today.year:
        return "과거"
    if year < 2030:
        return str(year)
    if year < 2040:
        return "2030년대"
    if year < 2050:
        return "2040년대"
    return "먼 미래"


def sort_key_for_technology(item: dict[str, Any]) -> tuple[int, int, str]:
    status_order = {"achieved": 0, "upcoming": 1, "distant": 2}
    year = item.get("predicted", {}).get("year")
    return (status_order.get(str(item.get("status") or ""), 1), int(year or 9999), str(item.get("name") or ""))


def track_record_status(predicted_for_year: int | None, actual_year: int | None, today: date) -> str:
    if predicted_for_year is None:
        return "pending"
    if actual_year is not None:
        error = actual_year - predicted_for_year
        if error < -2:
            return "early"
        if error <= 2:
            return "on_time"
        return "late"
    if today.year - predicted_for_year >= 10:
        return "missed"
    return "pending"


def track_record_error_years(predicted_for_year: int | None, actual_year: int | None, status: str, today: date) -> int | None:
    if predicted_for_year is None:
        return None
    if actual_year is not None:
        return actual_year - predicted_for_year
    if status == "missed":
        return today.year - predicted_for_year
    return None


def subject_id_for_prediction(predicted: dict[str, Any]) -> str:
    text = " ".join(
        str(predicted.get(key) or "")
        for key in ("source_label", "source_label_en", "source")
    ).lower()
    if "kurzweil" in text or "커즈와일" in text:
        return "kurzweil"
    if "clarke" in text or "클라크" in text:
        return "clarke"
    if "kennedy" in text or "케네디" in text:
        return "kennedy"
    if "at&t" in text or "picturephone" in text:
        return "att"
    return slug_key(predicted.get("source_label_en") or predicted.get("source_label") or predicted.get("source"))


def normalize_track_record_item(
    raw: dict[str, Any],
    *,
    today: date,
    warnings: list[dict[str, str]],
    auto_included: bool = False,
) -> dict[str, Any] | None:
    item_id = str(raw.get("id") or raw.get("name") or "track-record")
    for field in TRACK_REQUIRED_FIELDS:
        if not raw.get(field):
            warnings.append(warning_record("track_record", item_id, f"{field} 필드가 비어 있습니다."))
    if not raw.get("id") or not raw.get("name"):
        return None

    predicted_for_year = int_or_none(raw.get("predicted_for_year"))
    actual_year = int_or_none(raw.get("actual_year"))
    calculated_status = track_record_status(predicted_for_year, actual_year, today)
    manual_status = str(raw.get("status") or "").strip()
    if manual_status and manual_status != calculated_status:
        warnings.append(
            warning_record(
                "track_record_status",
                item_id,
                f"수기 status={manual_status}와 계산 status={calculated_status}가 다릅니다.",
            )
        )
    status = calculated_status
    error_years = track_record_error_years(predicted_for_year, actual_year, status, today)
    by_id = str(raw.get("by_id") or slug_key(raw.get("predicted_by"))).strip()
    predicted_by = str(raw.get("predicted_by") or by_id)
    predicted_by_en = str(raw.get("predicted_by_en") or predicted_by)
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or ""),
        "name_en": str(raw.get("name_en") or raw.get("name") or ""),
        "predicted_by": predicted_by,
        "predicted_by_en": predicted_by_en,
        "by_id": by_id,
        "predicted_in": int_or_none(raw.get("predicted_in")),
        "predicted_for": str(raw.get("predicted_for") or ""),
        "predicted_for_en": str(raw.get("predicted_for_en") or raw.get("predicted_for") or ""),
        "predicted_for_year": predicted_for_year,
        "actual_year": actual_year,
        "actual_label": str(raw.get("actual_label") or ""),
        "actual_label_en": str(raw.get("actual_label_en") or raw.get("actual_label") or ""),
        "display_actual_year": actual_year or today.year,
        "status": status,
        "manual_status": manual_status,
        "error_years": error_years,
        "absolute_error_years": abs(error_years) if error_years is not None else None,
        "judged": status in TRACK_JUDGED_STATUSES,
        "open_ended": actual_year is None,
        "what": str(raw.get("what") or ""),
        "what_en": str(raw.get("what_en") or raw.get("what") or ""),
        "outcome": str(raw.get("outcome") or ""),
        "outcome_en": str(raw.get("outcome_en") or raw.get("outcome") or ""),
        "lesson": str(raw.get("lesson") or ""),
        "lesson_en": str(raw.get("lesson_en") or raw.get("lesson") or ""),
        "source": str(raw.get("source") or ""),
        "source_label": str(raw.get("source_label") or ""),
        "source_label_en": str(raw.get("source_label_en") or raw.get("source_label") or ""),
        "actual_source": str(raw.get("actual_source") or ""),
        "actual_source_label": str(raw.get("actual_source_label") or ""),
        "actual_source_label_en": str(raw.get("actual_source_label_en") or raw.get("actual_source_label") or ""),
        "auto_included": auto_included,
    }


def auto_track_record_rows(technologies: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in technologies:
        if str(raw.get("status") or "") != "achieved":
            continue
        predicted = compact_prediction(raw)
        year = predicted.get("year")
        if not isinstance(year, int):
            continue
        subject_id = subject_id_for_prediction(predicted)
        source_label = predicted.get("source_label") or "미래 타임라인"
        source_label_en = predicted.get("source_label_en") or source_label
        rows.append(
            {
                "id": f"future-{raw.get('id')}",
                "name": raw.get("name") or "",
                "name_en": raw.get("name_en") or raw.get("name") or "",
                "predicted_by": source_label,
                "predicted_by_en": source_label_en,
                "by_id": subject_id,
                "predicted_in": int_or_none(str(raw.get("as_of") or "")[:4]),
                "predicted_for": predicted.get("label") or str(year),
                "predicted_for_en": predicted.get("label_en") or predicted.get("label") or str(year),
                "predicted_for_year": year,
                "actual_year": today.year,
                "actual_label": raw.get("now") or "미래 타임라인에서 달성 상태로 분류했습니다.",
                "actual_label_en": raw.get("now_en") or raw.get("now") or "Marked achieved in the future timeline.",
                "what": raw.get("what") or "",
                "what_en": raw.get("what_en") or raw.get("what") or "",
                "outcome": raw.get("now") or "",
                "outcome_en": raw.get("now_en") or raw.get("now") or "",
                "lesson": "이 페이지가 추적하던 예측이 달성 상태가 되면 성적표에도 자동으로 남깁니다.",
                "lesson_en": "When a tracked timeline item becomes achieved, this page records it automatically.",
                "source": predicted.get("source") or "",
                "source_label": source_label,
                "source_label_en": source_label_en,
            }
        )
    return rows


def average_year_error(items: list[dict[str, Any]]) -> float | None:
    errors = [item.get("error_years") for item in items if isinstance(item.get("error_years"), int)]
    if not errors:
        return None
    return round(sum(errors) / len(errors), 1)


def track_bias_label(avg_error: float | None, *, english: bool = False) -> str:
    if avg_error is None:
        return "not enough data" if english else "판정 부족"
    if avg_error > 0.2:
        return "optimistic" if english else "낙관"
    if avg_error < -0.2:
        return "conservative" if english else "보수"
    return "balanced" if english else "중립"


def build_track_record_subjects(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item.get("by_id") or "unknown"), []).append(item)

    subjects: list[dict[str, Any]] = []
    for subject_id, subject_items in grouped.items():
        judged = [item for item in subject_items if item.get("judged")]
        on_time_count = sum(1 for item in judged if item.get("status") == "on_time")
        early_count = sum(1 for item in judged if item.get("status") == "early")
        late_count = sum(1 for item in judged if item.get("status") == "late")
        missed_count = sum(1 for item in judged if item.get("status") == "missed")
        pending_count = sum(1 for item in subject_items if item.get("status") == "pending")
        avg_error = average_year_error(judged)
        expose_score = len(judged) >= TRACK_SCORE_MIN_JUDGED
        name = str(subject_items[0].get("predicted_by") or subject_id)
        name_en = str(subject_items[0].get("predicted_by_en") or name)
        score_label = f"과거 적중 {on_time_count}/{len(judged)}" if expose_score else f"수록 {len(subject_items)}건"
        score_label_en = f"Past hits {on_time_count}/{len(judged)}" if expose_score else f"{len(subject_items)} archived"
        avg_abs = abs(avg_error) if avg_error is not None else None
        summary = (
            f"판정 완료 {len(judged)}건: ±2년 적중 {on_time_count}건 · 평균 {avg_abs:g}년 {track_bias_label(avg_error)}"
            if expose_score and avg_abs is not None
            else f"수록 {len(subject_items)}건 · 판정 완료 {len(judged)}건"
        )
        summary_en = (
            f"{len(judged)} judged: {on_time_count} within ±2 years · {avg_abs:g}y {track_bias_label(avg_error, english=True)} on average"
            if expose_score and avg_abs is not None
            else f"{len(subject_items)} archived · {len(judged)} judged"
        )
        subjects.append(
            {
                "id": subject_id,
                "name": name,
                "name_en": name_en,
                "item_count": len(subject_items),
                "judged_count": len(judged),
                "on_time_count": on_time_count,
                "early_count": early_count,
                "late_count": late_count,
                "missed_count": missed_count,
                "pending_count": pending_count,
                "avg_error_years": avg_error,
                "hit_rate": round(on_time_count / len(judged), 3) if judged else None,
                "expose_score": expose_score,
                "score_label": score_label,
                "score_label_en": score_label_en,
                "summary": summary,
                "summary_en": summary_en,
            }
        )
    return sorted(subjects, key=lambda item: (-int(item.get("judged_count") or 0), str(item.get("name") or "")))


def build_future_track_record(
    base_dir: Path,
    technologies_raw: list[dict[str, Any]],
    *,
    today: date,
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    curated_raw = load_future_yaml(base_dir / "track_record.yaml")
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for raw in curated_raw:
        normalized = normalize_track_record_item(raw, today=today, warnings=warnings)
        if not normalized:
            continue
        seen_ids.add(str(normalized.get("id") or ""))
        items.append(normalized)

    for raw in auto_track_record_rows(technologies_raw, today):
        if str(raw.get("id") or "") in seen_ids:
            continue
        normalized = normalize_track_record_item(raw, today=today, warnings=warnings, auto_included=True)
        if normalized:
            items.append(normalized)

    items.sort(
        key=lambda item: (
            int(item.get("predicted_for_year") or 9999),
            int(item.get("actual_year") or 9999),
            str(item.get("name") or ""),
        )
    )
    subjects = build_track_record_subjects(items)
    judged = [item for item in items if item.get("judged")]
    return {
        "items": items,
        "subjects": subjects,
        "summary": {
            "item_count": len(items),
            "judged_count": len(judged),
            "on_time_count": sum(1 for item in judged if item.get("status") == "on_time"),
            "early_count": sum(1 for item in judged if item.get("status") == "early"),
            "late_count": sum(1 for item in judged if item.get("status") == "late"),
            "missed_count": sum(1 for item in judged if item.get("status") == "missed"),
            "pending_count": sum(1 for item in items if item.get("status") == "pending"),
            "avg_error_years": average_year_error(judged),
        },
    }


def validate_future_content(
    technologies: list[dict[str, Any]],
    glossary: list[dict[str, Any]],
    *,
    today: date,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []

    def add_warning(kind: str, item_id: str, message: str) -> None:
        warnings.append({"kind": kind, "id": item_id, "message": message})

    for tech in technologies:
        tech_id = str(tech.get("id") or tech.get("name") or "technology")
        for field in TECH_REQUIRED_FIELDS:
            if not tech.get(field):
                add_warning("technology", tech_id, f"{field} 필드가 비어 있습니다.")
        predicted = tech.get("predicted") if isinstance(tech.get("predicted"), dict) else {}
        for field in PREDICTION_REQUIRED_FIELDS:
            if not predicted.get(field):
                add_warning("prediction", tech_id, f"predicted.{field} 필드가 비어 있습니다.")
        as_of = parse_future_date(tech.get("as_of"))
        if not as_of:
            add_warning("technology", tech_id, "as_of 날짜를 읽을 수 없습니다.")
        elif (today - as_of).days > STALE_DAYS:
            add_warning("technology", tech_id, f"as_of가 {STALE_DAYS}일을 넘었습니다.")

    for item in glossary:
        glossary_id = str(item.get("id") or item.get("term") or "glossary")
        for field in GLOSSARY_REQUIRED_FIELDS:
            if not item.get(field):
                add_warning("glossary", glossary_id, f"{field} 필드가 비어 있습니다.")
    return warnings


def normalize_reading(
    raw: dict[str, Any],
    *,
    tech_id: str,
    today: date,
    trusted_domains: set[str],
    blocked_domains: set[str],
    removed_urls: set[str],
    warnings: list[dict[str, str]],
) -> dict[str, Any] | None:
    url = str(raw.get("url") or "").strip()
    title = str(raw.get("title") or "").strip()
    item_id = url or f"{tech_id}:{title or 'reading'}"
    domain = url_domain(url)

    for field in READING_REQUIRED_FIELDS:
        if not raw.get(field):
            warnings.append(warning_record("reading", item_id, f"{field} 필드가 비어 있습니다."))
    if not url or not title:
        return None
    if url in removed_urls:
        warnings.append(warning_record("reading", item_id, "removed.yaml에 등록된 URL이라 제외했습니다."))
        return None
    if domain and domain_matches(domain, blocked_domains):
        warnings.append(warning_record("reading", item_id, f"차단 도메인({domain})이라 제외했습니다."))
        return None

    checked_at = parse_future_date(raw.get("checked_at"))
    if not checked_at:
        warnings.append(warning_record("reading", item_id, "checked_at 날짜를 읽을 수 없습니다."))
    elif (today - checked_at).days > STALE_DAYS:
        warnings.append(warning_record("reading", item_id, f"checked_at이 {STALE_DAYS}일을 넘었습니다."))

    level = str(raw.get("level") or "").strip()
    reading_type = str(raw.get("type") or "").strip()
    cadence = str(raw.get("cadence") or "").strip()
    curated_by = str(raw.get("curated_by") or "").strip()
    return {
        "title": title,
        "title_en": str(raw.get("title_en") or title),
        "url": url,
        "domain": domain,
        "type": reading_type,
        "type_en": str(raw.get("type_en") or reading_type_en(reading_type)),
        "level": level,
        "level_en": str(raw.get("level_en") or reading_level_en(level)),
        "lang": str(raw.get("lang") or "").strip(),
        "effort": str(raw.get("effort") or "").strip(),
        "effort_en": str(raw.get("effort_en") or raw.get("effort") or "").strip(),
        "cadence": cadence,
        "cadence_en": str(raw.get("cadence_en") or cadence).strip(),
        "why": str(raw.get("why") or "").strip(),
        "why_en": str(raw.get("why_en") or raw.get("why") or "").strip(),
        "checked_at": str(raw.get("checked_at") or "").strip(),
        "curated_by": curated_by,
        "trusted": bool(domain and domain_matches(domain, trusted_domains)),
        "auto_collected": is_agent_curated(curated_by),
        "subscription": str(reading_type).lower() in {"newsletter", "뉴스레터"},
    }


def iter_reading_rows(readings_raw: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for block in readings_raw:
        if isinstance(block.get("items"), list):
            tech_id = str(block.get("technology") or block.get("tech_id") or "").strip()
            for item in block.get("items") or []:
                if isinstance(item, dict):
                    rows.append((tech_id, item))
            continue
        tech_id = str(block.get("technology") or block.get("tech_id") or "").strip()
        rows.append((tech_id, block))
    return rows


def load_readings_by_technology(
    base_dir: Path,
    technologies: list[dict[str, Any]],
    *,
    today: date,
    warnings: list[dict[str, str]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    readings_raw = load_future_yaml(base_dir / "readings.yaml")
    trusted_domains, blocked_domains = load_domain_policy(base_dir)
    removed_urls = load_removed_urls(base_dir)
    by_tech: dict[str, list[dict[str, Any]]] = {}
    common: list[dict[str, Any]] = []

    for tech_id, raw in iter_reading_rows(readings_raw):
        tech_key = tech_id or str(raw.get("technology") or "").strip()
        if not tech_key:
            warnings.append(warning_record("reading", str(raw.get("url") or raw.get("title") or "reading"), "technology가 비어 있습니다."))
            continue
        normalized = normalize_reading(
            raw,
            tech_id=tech_key,
            today=today,
            trusted_domains=trusted_domains,
            blocked_domains=blocked_domains,
            removed_urls=removed_urls,
            warnings=warnings,
        )
        if not normalized:
            continue
        if tech_key in COMMON_READING_IDS:
            common.append(normalized)
        else:
            by_tech.setdefault(tech_key, []).append(normalized)

    for tech_id, items in list(by_tech.items()):
        by_level: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_level.setdefault(str(item.get("level") or ""), []).append(item)
        capped: list[dict[str, Any]] = []
        for level, level_items in by_level.items():
            ordered = sorted(level_items, key=reading_sort_key)
            if len(ordered) > MAX_READINGS_PER_LEVEL:
                warnings.append(
                    warning_record(
                        "reading",
                        tech_id,
                        f"{level or '미분류'} 읽을거리가 {MAX_READINGS_PER_LEVEL}개를 넘어 초과분을 제외했습니다.",
                    )
                )
            capped.extend(ordered[:MAX_READINGS_PER_LEVEL])
        by_tech[tech_id] = sorted(capped, key=reading_sort_key)

    common = sorted(common, key=reading_sort_key)
    known_tech_ids = {str(item.get("id") or "") for item in technologies if item.get("id")}
    for tech_id in known_tech_ids:
        if not any(str(item.get("level") or "") == "입문" for item in by_tech.get(tech_id, [])):
            warnings.append(warning_record("reading", tech_id, "입문 읽을거리가 없습니다."))
    return by_tech, common


def load_link_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "links": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "links": {}}
    if not isinstance(loaded, dict):
        return {"version": 1, "links": {}}
    links = loaded.get("links")
    if not isinstance(links, dict):
        loaded["links"] = {}
    loaded.setdefault("version", 1)
    return loaded


def write_link_status(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def should_check_reading_links(config: dict[str, Any], today: date) -> bool:
    future_config = config.get("future", {}) if isinstance(config.get("future"), dict) else {}
    if future_config.get("link_check_enabled") is False:
        return False
    if future_config.get("force_link_check") is True:
        return True
    try:
        weekday = int(future_config.get("link_check_weekday", 0))
    except (TypeError, ValueError):
        weekday = 0
    return today.weekday() == weekday


def link_is_alive(session: Any, url: str) -> tuple[bool, int | None]:
    try:
        response = session.head(url, allow_redirects=True, timeout=12)
        if response.status_code in {403, 405} or response.status_code >= 500:
            response = session.get(url, allow_redirects=True, timeout=12, stream=True)
        status_code = int(response.status_code)
        return 200 <= status_code < 400, status_code
    except Exception:  # noqa: BLE001 - 링크 점검 실패가 빌드를 막으면 안 됩니다.
        return False, None


def check_reading_links(
    readings: list[dict[str, Any]],
    *,
    session: Any,
    status_path: Path,
    today: date,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    status_doc = load_link_status(status_path)
    links = status_doc.setdefault("links", {})
    for item in readings:
        url = str(item.get("url") or "")
        if not url:
            continue
        alive, status_code = link_is_alive(session, url)
        record = links.get(url) if isinstance(links.get(url), dict) else {}
        if alive:
            record = {
                "last_checked": today.isoformat(),
                "last_status": status_code,
                "consecutive_failures": 0,
            }
        else:
            failures = int(record.get("consecutive_failures") or 0) + 1
            record = {
                "last_checked": today.isoformat(),
                "last_status": status_code,
                "consecutive_failures": failures,
            }
            if failures >= LINK_FAILURE_WARNING_COUNT:
                warnings.append(warning_record("reading_link", url, "링크 점검이 2회 연속 실패했습니다."))
        links[url] = record
    write_link_status(status_path, status_doc)
    return warnings


def build_future_timeline(
    config: dict[str, Any],
    metrics: list[dict[str, Any]],
    *,
    today: date | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    base_dir = future_data_dir(config)
    technologies_raw = load_future_yaml(base_dir / "technologies.yaml")
    glossary_raw = load_future_yaml(base_dir / "glossary.yaml")
    warnings = validate_future_content(technologies_raw, glossary_raw, today=today)
    readings_by_tech, common_readings = load_readings_by_technology(
        base_dir,
        technologies_raw,
        today=today,
        warnings=warnings,
    )
    track_record = build_future_track_record(
        base_dir,
        technologies_raw,
        today=today,
        warnings=warnings,
    )
    future_breakdown = build_future_breakdown(
        base_dir,
        technologies_raw,
        metrics,
        today=today,
        warnings=warnings,
    )
    track_subjects = {
        str(subject.get("id") or ""): subject
        for subject in track_record.get("subjects", [])
        if subject.get("id")
    }
    by_key, by_symbol = metric_indexes(metrics)

    glossary = {
        str(item.get("id") or ""): {
            "id": str(item.get("id") or ""),
            "term": str(item.get("term") or ""),
            "term_en": str(item.get("term_en") or item.get("term") or ""),
            "short": str(item.get("short") or ""),
            "short_en": str(item.get("short_en") or item.get("short") or ""),
            "source": str(item.get("source") or ""),
            "learn_more": str(item.get("learn_more") or ""),
        }
        for item in glossary_raw
        if item.get("id")
    }

    technologies: list[dict[str, Any]] = []
    categories = [category for category in DEFAULT_CATEGORIES]
    for raw in technologies_raw:
        category = str(raw.get("category") or "")
        if category and category not in categories:
            categories.append(category)
        predicted = compact_prediction(raw)
        metric_refs = [
            resolved
            for ref in (raw.get("metrics") or [])[:3]
            if (resolved := resolve_metric_ref(ref, by_key))
        ]
        company_refs = [resolve_company_ref(ref, by_symbol) for ref in (raw.get("companies") or [])]
        year = predicted.get("year")
        track_subject_id = subject_id_for_prediction(predicted)
        track_subject = track_subjects.get(track_subject_id)
        track_subject_payload = (
            {
                "id": track_subject.get("id"),
                "name": track_subject.get("name"),
                "name_en": track_subject.get("name_en"),
                "score_label": track_subject.get("score_label"),
                "score_label_en": track_subject.get("score_label_en"),
                "judged_count": track_subject.get("judged_count"),
                "on_time_count": track_subject.get("on_time_count"),
            }
            if track_subject and track_subject.get("expose_score")
            else None
        )
        technologies.append(
            {
                "id": str(raw.get("id") or ""),
                "name": str(raw.get("name") or ""),
                "name_en": str(raw.get("name_en") or raw.get("name") or ""),
                "category": category,
                "category_en": str(raw.get("category_en") or category),
                "status": str(raw.get("status") or "upcoming"),
                "predicted": predicted,
                "band": future_band_for_year(year if isinstance(year, int) else None, today),
                "what": str(raw.get("what") or ""),
                "what_en": str(raw.get("what_en") or raw.get("what") or ""),
                "why": str(raw.get("why") or ""),
                "why_en": str(raw.get("why_en") or raw.get("why") or ""),
                "now": str(raw.get("now") or ""),
                "now_en": str(raw.get("now_en") or raw.get("now") or ""),
                "image": str(raw.get("image") or ""),
                "bottleneck": str(raw.get("bottleneck") or ""),
                "bottleneck_en": str(raw.get("bottleneck_en") or raw.get("bottleneck") or ""),
                "glossary": [str(item) for item in (raw.get("glossary") or []) if str(item) in glossary][:3],
                "metrics": metric_refs,
                "companies": company_refs,
                "breakdown": future_breakdown.get("by_tech", {}).get(str(raw.get("id") or ""), {"requirements": []}),
                "readings": readings_by_tech.get(str(raw.get("id") or ""), []),
                "track_record_subject_id": track_subject_id,
                "track_record_subject": track_subject_payload,
                "as_of": str(raw.get("as_of") or ""),
            }
        )

    technologies.sort(key=sort_key_for_technology)
    all_readings = [
        reading
        for technology in technologies
        for reading in (technology.get("readings") or [])
        if isinstance(reading, dict)
    ] + common_readings
    if session is not None and should_check_reading_links(config, today):
        warnings.extend(
            check_reading_links(
                all_readings,
                session=session,
                status_path=base_dir / "link_status.json",
                today=today,
            )
        )
    achieved_count = sum(1 for item in technologies if item["status"] == "achieved")
    upcoming_count = sum(1 for item in technologies if item["status"] != "achieved")
    years = [
        int(item["predicted"]["year"])
        for item in technologies
        if isinstance(item.get("predicted", {}).get("year"), int)
    ]
    return {
        "version": FUTURE_DATA_VERSION,
        "updated_at": today.isoformat(),
        "categories": categories,
        "glossary": glossary,
        "common_readings": common_readings,
        "track_record": track_record,
        "breakdown": {
            "ladders": future_breakdown.get("ladders", []),
            "summary": future_breakdown.get("summary", {}),
        },
        "technologies": technologies,
        "summary": {
            "technology_count": len(technologies),
            "reading_count": len(all_readings),
            "achieved_count": achieved_count,
            "upcoming_count": upcoming_count,
            "breakdown_requirement_count": future_breakdown.get("summary", {}).get("requirement_count", 0),
            "timeline_start": min([today.year, *years], default=today.year),
            "timeline_end": max([2045, *years], default=2045),
        },
        "warnings": warnings,
    }


def write_future_timeline(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
