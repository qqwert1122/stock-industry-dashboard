#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from macro_telegram_report.future_timeline import (  # noqa: E402
    READING_LEVELS,
    domain_matches,
    load_domain_policy,
    load_future_yaml,
    load_removed_urls,
    url_domain,
)
from macro_telegram_report.http_client import build_session  # noqa: E402

GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
GEMINI_DEFAULT_MODEL = "gemini-3.1-flash-lite"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ALLOWED_EXACT_PATHS = {"data/future/readings.yaml"}
ALLOWED_PREFIXES = ("data/future/audits/",)
INVESTMENT_PITCH_RE = re.compile(
    r"(buy now|strong buy|sell now|price target|multibagger|tenbagger|stock pick|"
    r"투자\s*추천|매수\s*추천|목표가|급등주|상한가|무료\s*리딩)",
    re.IGNORECASE,
)
PROMPT_INJECTION_RE = re.compile(
    r"(ignore previous instructions|disregard prior instructions|system prompt|developer message|"
    r"이전 지시를 무시|시스템 프롬프트)",
    re.IGNORECASE,
)
SPAM_RE = re.compile(
    r"(casino|sportsbook|adult dating|limited time offer|click here to claim|"
    r"카지노|도박|성인\s*광고|지금\s*클릭)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candidate:
    technology_id: str
    url: str
    title: str
    snippet: str = ""
    source: str = "search"


@dataclass(frozen=True)
class Evaluation:
    accepted: bool
    reason: str
    why: str = ""
    reading_type: str = "글"
    level: str = "입문"
    lang: str = "EN"
    effort: str = "15분"


def today_key() -> str:
    return date.today().isoformat()


def load_yaml_document(path: Path) -> Any:
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def dump_yaml_document(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=110),
        encoding="utf-8",
    )


def readings_by_technology(readings_doc: Any) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for block in readings_doc if isinstance(readings_doc, list) else []:
        if not isinstance(block, dict):
            continue
        tech_id = str(block.get("technology") or block.get("tech_id") or "").strip()
        if isinstance(block.get("items"), list):
            grouped.setdefault(tech_id, []).extend([item for item in block["items"] if isinstance(item, dict)])
        elif tech_id:
            grouped.setdefault(tech_id, []).append(block)
    return grouped


def existing_reading_urls(readings_doc: Any) -> set[str]:
    return {
        str(item.get("url") or "").strip()
        for items in readings_by_technology(readings_doc).values()
        for item in items
        if str(item.get("url") or "").strip()
    }


def analyze_gaps(
    technologies: list[dict[str, Any]],
    readings_doc: Any,
    *,
    today: date,
) -> list[dict[str, str]]:
    grouped = readings_by_technology(readings_doc)
    gaps: list[dict[str, str]] = []
    for tech in technologies:
        tech_id = str(tech.get("id") or "").strip()
        if not tech_id:
            continue
        items = grouped.get(tech_id, [])
        if not any(str(item.get("level") or "") == "입문" for item in items):
            gaps.append({"technology_id": tech_id, "kind": "missing_beginner", "query_level": "입문"})
        for level in READING_LEVELS:
            if len([item for item in items if str(item.get("level") or "") == level]) < 2:
                gaps.append({"technology_id": tech_id, "kind": f"thin_{level}", "query_level": level})
    return gaps


def build_search_queries(technology: dict[str, Any], gap: dict[str, str]) -> list[str]:
    name = str(technology.get("name_en") or technology.get("name") or technology.get("id") or "").strip()
    category = str(technology.get("category_en") or technology.get("category") or "").strip()
    level = gap.get("query_level") or "입문"
    if level == "입문":
        suffixes = ["official introduction", "explainer", "101"]
    elif level == "중급":
        suffixes = ["official report", "data", "industry report"]
    else:
        suffixes = ["technical report", "research data", "advanced analysis"]
    return [f"{name} {suffix}".strip() for suffix in suffixes] + [f"{category} {name} report".strip()]


def google_cse_candidates(
    session: requests.Session,
    *,
    query: str,
    technology_id: str,
    api_key: str,
    cx: str,
    max_results: int,
) -> list[Candidate]:
    response = session.get(
        GOOGLE_CSE_URL,
        params={"key": api_key, "cx": cx, "q": query, "num": max(1, min(max_results, 10))},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else []
    candidates: list[Candidate] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("link") or "").strip()
        title = str(item.get("title") or "").strip()
        if url and title:
            candidates.append(
                Candidate(
                    technology_id=technology_id,
                    url=url,
                    title=title,
                    snippet=str(item.get("snippet") or ""),
                    source="google_cse",
                )
            )
    return candidates


def trusted_seed_candidates(technologies: list[dict[str, Any]], gaps: list[dict[str, str]]) -> list[Candidate]:
    tech_by_id = {str(item.get("id") or ""): item for item in technologies}
    candidates: list[Candidate] = []
    for gap in gaps:
        tech = tech_by_id.get(gap["technology_id"]) or {}
        predicted = tech.get("predicted") if isinstance(tech.get("predicted"), dict) else {}
        source = str(predicted.get("source") or "").strip()
        title = str(predicted.get("source_label_en") or predicted.get("source_label") or tech.get("name_en") or tech.get("name") or "")
        if source and title:
            candidates.append(
                Candidate(
                    technology_id=gap["technology_id"],
                    url=source,
                    title=title,
                    snippet=str(tech.get("why_en") or tech.get("why") or ""),
                    source="trusted_seed",
                )
            )
    return candidates


def candidate_hard_reject_reason(
    candidate: Candidate,
    *,
    existing_urls: set[str],
    removed_urls: set[str],
    trusted_domains: set[str],
    blocked_domains: set[str],
) -> str:
    if not candidate.url.startswith(("http://", "https://")):
        return "not_http_url"
    if candidate.url in existing_urls:
        return "already_exists"
    if candidate.url in removed_urls:
        return "removed_url"
    domain = url_domain(candidate.url)
    if domain and domain_matches(domain, blocked_domains):
        return "blocked_domain"
    if not domain or not domain_matches(domain, trusted_domains):
        return "untrusted_domain"
    return ""


def fetch_candidate_text(session: requests.Session, candidate: Candidate) -> tuple[bool, str, str]:
    try:
        response = session.get(candidate.url, allow_redirects=True, timeout=20)
    except Exception as exc:  # noqa: BLE001
        return False, "unavailable", str(exc)
    if response.status_code >= 400:
        return False, "unavailable", f"HTTP {response.status_code}"
    content_type = response.headers.get("Content-Type", "")
    if "pdf" in content_type.lower():
        return True, candidate.snippet, "pdf"
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else candidate.title
    text = " ".join(soup.get_text(" ", strip=True).split())
    combined = f"{title}. {candidate.snippet}. {text[:5000]}".strip()
    return bool(combined), combined, "html"


def keyword_relevance(candidate: Candidate, content: str, technology: dict[str, Any]) -> bool:
    haystack = f"{candidate.title} {candidate.snippet} {content}".lower()
    tokens = [
        str(technology.get("id") or ""),
        str(technology.get("name") or ""),
        str(technology.get("name_en") or ""),
        str(technology.get("category") or ""),
        str(technology.get("category_en") or ""),
    ]
    normalized_tokens = {
        token.lower()
        for raw in tokens
        for token in re.split(r"[\s·/()_-]+", raw)
        if len(token) >= 3
    }
    return any(token in haystack for token in normalized_tokens)


def infer_reading_type(candidate: Candidate, content_kind: str) -> str:
    text = f"{candidate.title} {candidate.url}".lower()
    if "newsletter" in text:
        return "뉴스레터"
    if "book" in text or "penguinrandomhouse" in text:
        return "책"
    if "data" in text or "api" in text:
        return "데이터"
    if "report" in text or content_kind == "pdf":
        return "리포트"
    if "gov" in url_domain(candidate.url) or "official" in text:
        return "공식문서"
    return "글"


def heuristic_evaluate_candidate(
    candidate: Candidate,
    content: str,
    technology: dict[str, Any],
    *,
    content_kind: str,
) -> Evaluation:
    if PROMPT_INJECTION_RE.search(content):
        return Evaluation(False, "prompt_injection")
    if INVESTMENT_PITCH_RE.search(content):
        return Evaluation(False, "investment_pitch")
    if SPAM_RE.search(content):
        return Evaluation(False, "spam")
    if not keyword_relevance(candidate, content, technology):
        return Evaluation(False, "irrelevant")
    level = "입문"
    if any(word in content.lower() for word in ("technical", "research", "dataset", "methodology", "api")):
        level = "심화"
    elif any(word in content.lower() for word in ("report", "industry", "annual", "data")):
        level = "중급"
    why = f"{technology.get('name') or technology.get('name_en') or '해당 기술'} 흐름을 원문 자료로 확인할 수 있습니다."
    return Evaluation(
        True,
        "accepted",
        why=why,
        reading_type=infer_reading_type(candidate, content_kind),
        level=level,
        lang="EN",
        effort="15분",
    )


def parse_gemini_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        loaded = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def gemini_evaluate_candidate(
    session: requests.Session,
    candidate: Candidate,
    content: str,
    technology: dict[str, Any],
    *,
    api_key: str,
    model: str,
) -> Evaluation | None:
    prompt = (
        "You evaluate whether a public link is a useful educational reading for a technology dashboard. "
        "Do not invent URLs. The URL has already been fixed by search and must not be changed. "
        "Reject unavailable pages, spam, investment pitches, or irrelevant content. "
        "Return JSON only with accepted, reason, why, type, level, lang, effort. "
        f"Technology: {technology.get('name_en') or technology.get('name')} / {technology.get('name')}. "
        f"Fixed URL: {candidate.url}. Title: {candidate.title}. Content: {content[:6000]}"
    )
    try:
        response = session.post(
            GEMINI_URL.format(model=model),
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
    except Exception:  # noqa: BLE001
        return None
    parsed = parse_gemini_json(text)
    if not parsed:
        return None
    return Evaluation(
        accepted=bool(parsed.get("accepted")),
        reason=str(parsed.get("reason") or ("accepted" if parsed.get("accepted") else "rejected")),
        why=str(parsed.get("why") or ""),
        reading_type=str(parsed.get("type") or "글"),
        level=str(parsed.get("level") or "입문"),
        lang=str(parsed.get("lang") or "EN"),
        effort=str(parsed.get("effort") or "15분"),
    )


def draft_reading_entry(candidate: Candidate, evaluation: Evaluation, *, checked_at: str) -> dict[str, Any]:
    level = evaluation.level if evaluation.level in READING_LEVELS else "입문"
    return {
        "title": candidate.title,
        "url": candidate.url,
        "type": evaluation.reading_type or "글",
        "level": level,
        "lang": evaluation.lang or "EN",
        "effort": evaluation.effort or "15분",
        "why": evaluation.why or "해당 기술 흐름을 원문 자료로 확인할 수 있습니다.",
        "checked_at": checked_at,
        "curated_by": "agent",
    }


def append_reading_entries(readings_path: Path, entries: list[tuple[str, dict[str, Any]]]) -> None:
    if not entries:
        return
    document = load_yaml_document(readings_path)
    if not isinstance(document, list):
        document = []
    blocks_by_tech = {
        str(block.get("technology") or ""): block
        for block in document
        if isinstance(block, dict) and str(block.get("technology") or "")
    }
    for technology_id, entry in entries:
        block = blocks_by_tech.get(technology_id)
        if block is None:
            block = {"technology": technology_id, "items": []}
            document.append(block)
            blocks_by_tech[technology_id] = block
        if not isinstance(block.get("items"), list):
            block["items"] = []
        block["items"].append(entry)
    dump_yaml_document(readings_path, document)


def validate_changed_paths(paths: list[str]) -> None:
    invalid = [
        path
        for path in paths
        if path
        and path not in ALLOWED_EXACT_PATHS
        and not any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES)
    ]
    if invalid:
        raise SystemExit(f"Unexpected changed paths: {', '.join(invalid)}")


def write_audit_report(
    audit_dir: Path,
    *,
    gaps: list[dict[str, str]],
    accepted: list[tuple[str, dict[str, Any]]],
    rejected: list[tuple[str, str]],
    search_mode: str,
) -> Path:
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"readings-agent-{today_key()}.md"
    lines = [
        f"# Future Readings Agent Audit - {today_key()}",
        "",
        f"- Search mode: {search_mode}",
        f"- Gaps checked: {len(gaps)}",
        f"- Accepted entries: {len(accepted)}",
        f"- Rejected candidates: {len(rejected)}",
        "",
        "## Accepted",
    ]
    if accepted:
        for tech_id, entry in accepted:
            lines.append(f"- `{tech_id}`: [{entry['title']}]({entry['url']})")
    else:
        lines.append("- None")
    lines.extend(["", "## Rejected"])
    if rejected:
        for url, reason in rejected[:50]:
            lines.append(f"- `{reason}`: {url}")
    else:
        lines.append("- None")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_agent(args: argparse.Namespace) -> int:
    future_dir = Path(args.future_dir)
    readings_path = future_dir / "readings.yaml"
    technologies = load_future_yaml(future_dir / "technologies.yaml")
    readings_doc = load_yaml_document(readings_path)
    gaps = analyze_gaps(technologies, readings_doc, today=date.today())
    tech_by_id = {str(item.get("id") or ""): item for item in technologies}
    existing_urls = existing_reading_urls(readings_doc)
    removed_urls = load_removed_urls(future_dir)
    trusted_domains, blocked_domains = load_domain_policy(future_dir)
    session = build_session()

    api_key = os.getenv("GOOGLE_CSE_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    cx = os.getenv("GOOGLE_CSE_CX") or ""
    gemini_key = os.getenv("GEMINI_API_KEY") or ""
    gemini_model = os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL)
    search_mode = "trusted_seed"
    candidates: list[Candidate] = []
    if api_key and cx:
        search_mode = "google_cse"
        seen_queries: set[str] = set()
        for gap in gaps:
            tech = tech_by_id.get(gap["technology_id"]) or {}
            for query in build_search_queries(tech, gap):
                if query in seen_queries:
                    continue
                seen_queries.add(query)
                try:
                    candidates.extend(
                        google_cse_candidates(
                            session,
                            query=query,
                            technology_id=gap["technology_id"],
                            api_key=api_key,
                            cx=cx,
                            max_results=args.max_results,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    candidates.append(Candidate(gap["technology_id"], f"error://{query}", "search_error", str(exc)))
    else:
        candidates.extend(trusted_seed_candidates(technologies, gaps))

    accepted: list[tuple[str, dict[str, Any]]] = []
    rejected: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        if candidate.url in seen_urls:
            continue
        seen_urls.add(candidate.url)
        if candidate.url.startswith("error://"):
            rejected.append((candidate.url, candidate.snippet or "search_error"))
            continue
        reject_reason = candidate_hard_reject_reason(
            candidate,
            existing_urls=existing_urls,
            removed_urls=removed_urls,
            trusted_domains=trusted_domains,
            blocked_domains=blocked_domains,
        )
        if reject_reason:
            rejected.append((candidate.url, reject_reason))
            continue
        ok, content, content_kind = fetch_candidate_text(session, candidate)
        if not ok:
            rejected.append((candidate.url, content_kind))
            continue
        tech = tech_by_id.get(candidate.technology_id) or {}
        evaluation = None
        if gemini_key:
            evaluation = gemini_evaluate_candidate(
                session,
                candidate,
                content,
                tech,
                api_key=gemini_key,
                model=gemini_model,
            )
        evaluation = evaluation or heuristic_evaluate_candidate(candidate, content, tech, content_kind=content_kind)
        if not evaluation.accepted:
            rejected.append((candidate.url, evaluation.reason))
            continue
        entry = draft_reading_entry(candidate, evaluation, checked_at=today_key())
        accepted.append((candidate.technology_id, entry))
        existing_urls.add(candidate.url)
        if len(accepted) >= args.max_accepted:
            break

    if accepted and not args.dry_run:
        append_reading_entries(readings_path, accepted)
    audit_path = write_audit_report(
        Path(args.audit_dir),
        gaps=gaps,
        accepted=accepted,
        rejected=rejected,
        search_mode=search_mode,
    )
    print(f"gaps={len(gaps)} accepted={len(accepted)} rejected={len(rejected)} audit={audit_path}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover and curate future readings.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--future-dir", default="data/future")
    parser.add_argument("--audit-dir", default="data/future/audits")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--max-accepted", type=int, default=12)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--guard-diff", nargs="*")
    args = parser.parse_args(argv)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.guard_diff is not None:
        validate_changed_paths(args.guard_diff)
        return 0
    return run_agent(args)


if __name__ == "__main__":
    raise SystemExit(main())
