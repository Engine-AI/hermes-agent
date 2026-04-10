#!/usr/bin/env python3
"""Lightweight PROFESSIONS.md manager.

Keeps profession definitions in the same file-backed style as MEMORY.md / USER.md:
one entry per profession, separated by the standard section delimiter.

Each entry is human-editable plain text with simple key/value headers, for example:

    Profession: Accountant
    Slug: accountant
    Skills: tax-filing, reconciliation
    Problem Domains: tax filing, bookkeeping
    Solved Count: 0
    Users Helped: 0
    Rating: 0
    Score: 0
    Feedback Summary:
    Recent Solutions:
    Recent Users:
    Recent Cases:
    Optimization Notes:
    Description: Helps with accounting workflows.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home
from agent.skill_utils import get_all_skills_dirs, parse_frontmatter
from hermes_cli.config import load_config, save_config

ENTRY_DELIMITER = "\n§\n"
RECENT_ITEMS_LIMIT = 5


def get_professions_path() -> Path:
    return get_hermes_home() / "memories" / "PROFESSIONS.md"


def _read_entries() -> List[str]:
    path = get_professions_path()
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    return [part.strip() for part in raw.split(ENTRY_DELIMITER) if part.strip()]


def _write_entries(entries: List[str]) -> None:
    path = get_professions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ENTRY_DELIMITER.join(entries), encoding="utf-8")


def slugify_profession(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "generalist"


def parse_profession_entry(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "profession": "",
        "slug": "",
        "skills": [],
        "problem_domains": [],
        "solved_count": 0,
        "users_helped": 0,
        "rating": 0.0,
        "score": 0.0,
        "review_count": 0,
        "positive_feedback_count": 0,
        "negative_feedback_count": 0,
        "feedback_summary": "",
        "recent_solutions": [],
        "recent_users": [],
        "recent_cases": [],
        "optimization_notes": "",
        "description": "",
        "raw": text,
    }
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "profession":
            result["profession"] = value
        elif key == "slug":
            result["slug"] = value
        elif key == "skills":
            result["skills"] = [v.strip() for v in value.split(",") if v.strip()]
        elif key == "problem domains":
            result["problem_domains"] = [v.strip() for v in value.split(",") if v.strip()]
        elif key == "solved count":
            try:
                result["solved_count"] = int(value)
            except ValueError:
                pass
        elif key == "users helped":
            try:
                result["users_helped"] = int(value)
            except ValueError:
                pass
        elif key == "rating":
            try:
                result["rating"] = float(value)
            except ValueError:
                pass
        elif key == "score":
            try:
                result["score"] = float(value)
            except ValueError:
                pass
        elif key == "review count":
            try:
                result["review_count"] = int(value)
            except ValueError:
                pass
        elif key == "positive feedback":
            try:
                result["positive_feedback_count"] = int(value)
            except ValueError:
                pass
        elif key == "negative feedback":
            try:
                result["negative_feedback_count"] = int(value)
            except ValueError:
                pass
        elif key == "feedback summary":
            result["feedback_summary"] = value
        elif key == "recent solutions":
            result["recent_solutions"] = [v.strip() for v in value.split(" | ") if v.strip()]
        elif key == "recent users":
            result["recent_users"] = [v.strip() for v in value.split(",") if v.strip()]
        elif key == "recent cases":
            result["recent_cases"] = [v.strip() for v in value.split(" | ") if v.strip()]
        elif key == "optimization notes":
            result["optimization_notes"] = value
        elif key == "description":
            result["description"] = value
    if not result["slug"] and result["profession"]:
        result["slug"] = slugify_profession(result["profession"])
    return result


def render_profession_entry(entry: Dict[str, Any]) -> str:
    score = calculate_profession_score(entry)
    skills = ", ".join(sorted(dict.fromkeys(entry.get("skills", []))))
    domains = ", ".join(sorted(dict.fromkeys(entry.get("problem_domains", []))))
    recent_solutions = " | ".join((entry.get("recent_solutions") or [])[:RECENT_ITEMS_LIMIT])
    recent_users = ", ".join((entry.get("recent_users") or [])[:RECENT_ITEMS_LIMIT])
    recent_cases = " | ".join((entry.get("recent_cases") or [])[:RECENT_ITEMS_LIMIT])
    optimization_notes = entry.get("optimization_notes", "").strip() or build_optimization_notes(entry)
    return "\n".join(
        [
            f"Profession: {entry.get('profession', '').strip()}",
            f"Slug: {entry.get('slug', '').strip()}",
            f"Skills: {skills}",
            f"Problem Domains: {domains}",
            f"Solved Count: {int(entry.get('solved_count', 0) or 0)}",
            f"Users Helped: {int(entry.get('users_helped', 0) or 0)}",
            f"Rating: {float(entry.get('rating', 0.0) or 0.0):.1f}",
            f"Score: {score:.2f}",
            f"Review Count: {int(entry.get('review_count', 0) or 0)}",
            f"Positive Feedback: {int(entry.get('positive_feedback_count', 0) or 0)}",
            f"Negative Feedback: {int(entry.get('negative_feedback_count', 0) or 0)}",
            f"Feedback Summary: {entry.get('feedback_summary', '').strip()}",
            f"Recent Solutions: {recent_solutions}",
            f"Recent Users: {recent_users}",
            f"Recent Cases: {recent_cases}",
            f"Optimization Notes: {optimization_notes}",
            f"Description: {entry.get('description', '').strip()}",
        ]
    ).strip()


def list_professions() -> List[Dict[str, Any]]:
    parsed = [parse_profession_entry(entry) for entry in _read_entries()]
    for item in parsed:
        item["score"] = calculate_profession_score(item)
    return parsed


def get_profession(slug_or_name: str) -> Optional[Dict[str, Any]]:
    needle = slugify_profession(slug_or_name)
    for entry in list_professions():
        if entry.get("slug") == needle or slugify_profession(entry.get("profession", "")) == needle:
            return entry
    return None


def build_optimization_notes(entry: Dict[str, Any]) -> str:
    domains = ", ".join((entry.get("problem_domains") or [])[:3]) or "general problem solving"
    positive = int(entry.get("positive_feedback_count", 0) or 0)
    negative = int(entry.get("negative_feedback_count", 0) or 0)
    solved = int(entry.get("solved_count", 0) or 0)
    recent_case = next(iter(entry.get("recent_cases") or []), "")
    feedback_summary = str(entry.get("feedback_summary", "") or "").strip()

    quality_signal = "neutral feedback trend"
    if positive > negative:
        quality_signal = "positive feedback trend"
    elif negative > positive:
        quality_signal = "needs service improvement"

    notes = [f"Prioritize {domains}. Maintain a {quality_signal}."]
    if solved:
        notes.append(f"Reuse patterns from {solved} solved cases.")
    if recent_case:
        notes.append(f"Latest case: {recent_case}.")
    if feedback_summary:
        notes.append(f"Latest feedback focus: {feedback_summary}.")
    return " ".join(notes).strip()


def _find_skill_dir(skill_name: str) -> Optional[Path]:
    needle = skill_name.strip()
    if not needle:
        return None
    for skills_dir in get_all_skills_dirs():
        if not skills_dir.exists():
            continue
        for skill_md in skills_dir.rglob("SKILL.md"):
            if skill_md.parent.name == needle:
                return skill_md.parent
    return None


def _collect_problem_domains_for_skills(skill_names: List[str]) -> List[str]:
    domains: List[str] = []
    for skill_name in skill_names:
        skill_dir = _find_skill_dir(skill_name)
        if skill_dir is None:
            continue
        inferred = infer_professions_for_skill(skill_dir)
        for item in inferred:
            domains.extend(item.get("problem_domains") or [])
    return sorted(dict.fromkeys(domain for domain in domains if str(domain).strip()))


def _extract_problem_domains(frontmatter: Dict[str, Any], description: str) -> List[str]:
    metadata = frontmatter.get("metadata") or {}
    hermes = metadata.get("hermes") if isinstance(metadata, dict) else {}
    if not isinstance(hermes, dict):
        hermes = {}
    domains = hermes.get("problem_domains") or frontmatter.get("problem_domains") or []
    if isinstance(domains, str):
        domains = [domains]
    cleaned = [str(item).strip() for item in domains if str(item).strip()]
    if cleaned:
        return cleaned
    if description:
        # Very light fallback: use short comma-style clauses as domains.
        return [part.strip() for part in re.split(r"[;,/]", description)[:3] if part.strip()]
    return []


def infer_professions_for_skill(skill_dir: Path) -> List[Dict[str, Any]]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return []
    raw = skill_md.read_text(encoding="utf-8")[:4000]
    frontmatter, _ = parse_frontmatter(raw)
    metadata = frontmatter.get("metadata") or {}
    hermes = metadata.get("hermes") if isinstance(metadata, dict) else {}
    if not isinstance(hermes, dict):
        hermes = {}

    explicit = hermes.get("professions") or frontmatter.get("professions") or []
    if isinstance(explicit, str):
        explicit = [explicit]
    explicit = [str(item).strip() for item in explicit if str(item).strip()]

    description = str(frontmatter.get("description") or "").strip()
    problem_domains = _extract_problem_domains(frontmatter, description)
    skill_name = skill_dir.name

    if explicit:
        return [
            {
                "profession": item,
                "slug": slugify_profession(item),
                "skills": [skill_name],
                "problem_domains": problem_domains,
                "solved_count": 0,
                "users_helped": 0,
                "rating": 0.0,
                "score": 0.0,
                "review_count": 0,
                "positive_feedback_count": 0,
                "negative_feedback_count": 0,
                "feedback_summary": "",
                "recent_solutions": [],
                "recent_users": [],
                "recent_cases": [],
                "optimization_notes": "",
                "description": description,
            }
            for item in explicit
        ]

    # Simple fallback: map the first path segment/category to a profession.
    rel_parts = skill_dir.relative_to(get_hermes_home() / "skills").parts
    category = rel_parts[0] if len(rel_parts) > 1 else "generalist"
    profession = category.replace("-", " ").replace("_", " ").title()
    return [
        {
            "profession": profession,
            "slug": slugify_profession(profession),
            "skills": [skill_name],
            "problem_domains": problem_domains,
            "solved_count": 0,
            "users_helped": 0,
            "rating": 0.0,
            "score": 0.0,
            "review_count": 0,
            "positive_feedback_count": 0,
            "negative_feedback_count": 0,
            "feedback_summary": "",
            "recent_solutions": [],
            "recent_users": [],
            "recent_cases": [],
            "optimization_notes": "",
            "description": description or f"Uses skills in the {category} category.",
        }
    ]


def bind_skill_to_professions(skill_dir: Path) -> List[str]:
    inferred = infer_professions_for_skill(skill_dir)
    if not inferred:
        return []

    existing_entries = [parse_profession_entry(entry) for entry in _read_entries()]
    by_slug = {entry["slug"]: entry for entry in existing_entries if entry.get("slug")}

    updated_slugs: List[str] = []
    for new_entry in inferred:
        slug = new_entry["slug"]
        current = by_slug.get(slug)
        if current is None:
            by_slug[slug] = new_entry
            updated_slugs.append(slug)
            continue
        current["profession"] = current.get("profession") or new_entry["profession"]
        current["skills"] = sorted(dict.fromkeys((current.get("skills") or []) + new_entry["skills"]))
        current["problem_domains"] = sorted(
            dict.fromkeys((current.get("problem_domains") or []) + new_entry["problem_domains"])
        )
        if not current.get("description"):
            current["description"] = new_entry.get("description", "")
        updated_slugs.append(slug)

    rendered = [render_profession_entry(entry) for entry in sorted(by_slug.values(), key=lambda item: item["slug"])]
    _write_entries(rendered)
    return updated_slugs


def rebuild_professions_from_skills(skills_root: Optional[Path] = None) -> List[str]:
    root = skills_root or (get_hermes_home() / "skills")
    if not root.exists():
        _write_entries([])
        return []
    _write_entries([])
    bound: List[str] = []
    for skill_md in root.rglob("SKILL.md"):
        bound.extend(bind_skill_to_professions(skill_md.parent))
    return sorted(dict.fromkeys(bound))


def calculate_profession_score(entry: Dict[str, Any]) -> float:
    rating = float(entry.get("rating", 0.0) or 0.0)
    solved = int(entry.get("solved_count", 0) or 0)
    users_helped = int(entry.get("users_helped", 0) or 0)
    positive = int(entry.get("positive_feedback_count", 0) or 0)
    negative = int(entry.get("negative_feedback_count", 0) or 0)
    skills = len(entry.get("skills", []) or [])
    feedback_total = positive + negative
    feedback_ratio = (positive / feedback_total) if feedback_total else 0.0
    score = (
        rating * 0.45
        + min(solved, 100) * 0.02
        + min(users_helped, 100) * 0.01
        + feedback_ratio * 2.0
        + min(skills, 20) * 0.03
    )
    return round(score, 2)


def _save_entries(entries: List[Dict[str, Any]]) -> None:
    for entry in entries:
        entry["optimization_notes"] = build_optimization_notes(entry)
    rendered = [render_profession_entry(entry) for entry in sorted(entries, key=lambda item: item["slug"])]
    _write_entries(rendered)


def _compact_recent_items(values: List[str], *, limit: int = RECENT_ITEMS_LIMIT) -> List[str]:
    seen = set()
    compacted: List[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        compacted.append(cleaned)
        if len(compacted) >= limit:
            break
    return compacted


def set_active_profession(slug_or_name: str) -> Dict[str, Any]:
    entry = get_profession(slug_or_name)
    if not entry:
        return {"success": False, "error": f"Profession not found: {slug_or_name}"}
    cfg = load_config()
    cfg.setdefault("professions", {})
    cfg["professions"]["active"] = entry["slug"]
    save_config(cfg)
    return {"success": True, "active": entry["slug"], "profession": entry["profession"]}


def get_active_profession_slug() -> str:
    cfg = load_config()
    professions_cfg = cfg.get("professions", {})
    if not isinstance(professions_cfg, dict):
        return ""
    return str(professions_cfg.get("active", "") or "").strip()


def rate_profession(slug_or_name: str, stars: int, review_text: str = "") -> Dict[str, Any]:
    entry = get_profession(slug_or_name)
    if not entry:
        return {"success": False, "error": f"Profession not found: {slug_or_name}"}
    stars = max(1, min(5, int(stars)))
    entries = list_professions()
    for item in entries:
        if item["slug"] != entry["slug"]:
            continue
        count = int(item.get("review_count", 0) or 0)
        current = float(item.get("rating", 0.0) or 0.0)
        new_rating = ((current * count) + stars) / (count + 1)
        item["rating"] = round(new_rating, 2)
        item["review_count"] = count + 1
        if review_text.strip():
            item["feedback_summary"] = review_text.strip()
        _save_entries(entries)
        return {
            "success": True,
            "profession": item["profession"],
            "rating": item["rating"],
            "review_count": item["review_count"],
        }
    return {"success": False, "error": f"Profession not found: {slug_or_name}"}


def feedback_profession(slug_or_name: str, sentiment: str, text: str) -> Dict[str, Any]:
    entry = get_profession(slug_or_name)
    if not entry:
        return {"success": False, "error": f"Profession not found: {slug_or_name}"}
    sentiment = sentiment.strip().lower()
    if sentiment not in {"positive", "negative"}:
        return {"success": False, "error": "sentiment must be 'positive' or 'negative'"}
    entries = list_professions()
    for item in entries:
        if item["slug"] != entry["slug"]:
            continue
        if sentiment == "positive":
            item["positive_feedback_count"] = int(item.get("positive_feedback_count", 0) or 0) + 1
        else:
            item["negative_feedback_count"] = int(item.get("negative_feedback_count", 0) or 0) + 1
        if text.strip():
            item["feedback_summary"] = text.strip()
        _save_entries(entries)
        return {
            "success": True,
            "profession": item["profession"],
            "sentiment": sentiment,
            "feedback_summary": item.get("feedback_summary", ""),
        }
    return {"success": False, "error": f"Profession not found: {slug_or_name}"}


def bind_skill_to_profession(slug_or_name: str, skill_name: str) -> Dict[str, Any]:
    skill_dir = _find_skill_dir(skill_name)
    if skill_dir is None:
        return {"success": False, "error": f"Skill not found: {skill_name}"}

    entry = get_profession(slug_or_name)
    entries = list_professions()
    if entry is None:
        slug = slugify_profession(slug_or_name)
        profession_name = slug_or_name.strip() or slug
        new_entry = {
            "profession": profession_name,
            "slug": slug,
            "skills": [skill_dir.name],
            "problem_domains": [],
            "solved_count": 0,
            "users_helped": 0,
            "rating": 0.0,
            "score": 0.0,
            "review_count": 0,
            "positive_feedback_count": 0,
            "negative_feedback_count": 0,
            "feedback_summary": "",
            "recent_solutions": [],
            "recent_users": [],
            "recent_cases": [],
            "optimization_notes": "",
            "description": f"Profession manually created for skill binding with {skill_dir.name}.",
        }
        inferred = infer_professions_for_skill(skill_dir)
        if inferred:
            new_entry["problem_domains"] = inferred[0].get("problem_domains", [])
            new_entry["description"] = inferred[0].get("description") or new_entry["description"]
        entries.append(new_entry)
        _save_entries(entries)
        return {
            "success": True,
            "profession": profession_name,
            "slug": slug,
            "skills": [skill_dir.name],
            "created": True,
        }

    for item in entries:
        if item["slug"] != entry["slug"]:
            continue
        item["skills"] = sorted(dict.fromkeys((item.get("skills") or []) + [skill_dir.name]))
        item["problem_domains"] = _collect_problem_domains_for_skills(item["skills"])
        inferred = infer_professions_for_skill(skill_dir)
        if inferred and not item.get("description"):
            item["description"] = inferred[0].get("description", "")
        _save_entries(entries)
        return {
            "success": True,
            "profession": item["profession"],
            "slug": item["slug"],
            "skills": item["skills"],
            "created": False,
        }
    return {"success": False, "error": f"Profession not found: {slug_or_name}"}


def unbind_skill_from_profession(slug_or_name: str, skill_name: str) -> Dict[str, Any]:
    entry = get_profession(slug_or_name)
    if not entry:
        return {"success": False, "error": f"Profession not found: {slug_or_name}"}
    entries = list_professions()
    for item in entries:
        if item["slug"] != entry["slug"]:
            continue
        skills = [skill for skill in item.get("skills", []) if skill != skill_name]
        if len(skills) == len(item.get("skills", [])):
            return {
                "success": False,
                "error": f"Skill '{skill_name}' is not bound to profession '{item['profession']}'",
            }
        item["skills"] = skills
        item["problem_domains"] = _collect_problem_domains_for_skills(skills)
        _save_entries(entries)
        return {
            "success": True,
            "profession": item["profession"],
            "slug": item["slug"],
            "skills": item["skills"],
        }
    return {"success": False, "error": f"Profession not found: {slug_or_name}"}


def solve_profession(
    slug_or_name: str,
    problem: str,
    user: str = "",
    summary: str = "",
    increment_user: bool = True,
) -> Dict[str, Any]:
    entry = get_profession(slug_or_name)
    if not entry:
        return {"success": False, "error": f"Profession not found: {slug_or_name}"}

    problem = problem.strip()
    user = user.strip()
    summary = summary.strip()
    if not problem:
        return {"success": False, "error": "problem is required"}

    solution_label = summary or problem
    if user:
        solution_label = f"{user}: {solution_label}"
    case_label = f"{user or 'anonymous'} -> {problem}"

    entries = list_professions()
    for item in entries:
        if item["slug"] != entry["slug"]:
            continue

        item["solved_count"] = int(item.get("solved_count", 0) or 0) + 1

        recent_solutions = [solution_label] + list(item.get("recent_solutions") or [])
        item["recent_solutions"] = _compact_recent_items(recent_solutions)
        item["recent_cases"] = _compact_recent_items([case_label] + list(item.get("recent_cases") or []))

        if user:
            existing_users = list(item.get("recent_users") or [])
            normalized_existing = {value.strip().lower() for value in existing_users if value.strip()}
            if increment_user and user.lower() not in normalized_existing:
                item["users_helped"] = int(item.get("users_helped", 0) or 0) + 1
            item["recent_users"] = _compact_recent_items([user] + existing_users)

        if summary and not item.get("feedback_summary"):
            item["feedback_summary"] = summary

        _save_entries(entries)
        return {
            "success": True,
            "profession": item["profession"],
            "solved_count": item["solved_count"],
            "users_helped": item.get("users_helped", 0),
            "recent_solutions": item.get("recent_solutions", []),
            "recent_users": item.get("recent_users", []),
            "recent_cases": item.get("recent_cases", []),
        }

    return {"success": False, "error": f"Profession not found: {slug_or_name}"}
