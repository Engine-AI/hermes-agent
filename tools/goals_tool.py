#!/usr/bin/env python3
"""Lightweight GOALS.md manager.

Persists long-term user intent ("build a half-marathon program", "learn Rust
via side projects") in the same file-backed style as PROFESSIONS.md — one
entry per goal separated by the section delimiter. Goals are human-editable
plain text with key/value headers:

    Goal: Build half-marathon program
    Slug: build-half-marathon-program
    Status: active
    Created At: 2026-04-23T10:15:00Z
    Updated At: 2026-04-23T12:02:33Z
    Description: 12-week program, sub-2:10.
    Linked Professions: fitness-coach, nutrition-advisor
    Linked Routines: cron-0f38a1
    Recent Progress: [fitness-coach] Long run set | [nutrition-advisor] 310g carbs
    Notes: Morning runs preferred.

A goal's role in the brain:
  - ``summarize_active()`` is fed to the router so routing honors long-term
    intent (e.g., "cardio training plan" is a weak match for active
    profession `fitness-coach` but a strong match once the goal's linked
    professions include it).
  - ``solve_profession`` fans out progress entries to any active goal that
    links the solved profession.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home

ENTRY_DELIMITER = "\n§\n"
RECENT_PROGRESS_LIMIT = 5
_VALID_STATUSES = {"active", "paused", "done"}
_DEFAULT_MAX_ACTIVE_GOALS = 5
_DEFAULT_MAX_SUMMARY_CHARS = 800


def get_goals_path() -> Path:
    return get_hermes_home() / "memories" / "GOALS.md"


def _read_entries() -> List[str]:
    path = get_goals_path()
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    return [part.strip() for part in raw.split(ENTRY_DELIMITER) if part.strip()]


def _write_entries(entries: List[str]) -> None:
    path = get_goals_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ENTRY_DELIMITER.join(entries), encoding="utf-8")


def slugify_goal(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "goal"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_goal_entry(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "title": "",
        "slug": "",
        "status": "active",
        "created_at": "",
        "updated_at": "",
        "description": "",
        "linked_professions": [],
        "linked_routines": [],
        "recent_progress": [],
        "notes": "",
        "raw": text,
    }
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "goal":
            result["title"] = value
        elif key == "slug":
            result["slug"] = value
        elif key == "status":
            status = value.lower()
            if status in _VALID_STATUSES:
                result["status"] = status
        elif key == "created at":
            result["created_at"] = value
        elif key == "updated at":
            result["updated_at"] = value
        elif key == "description":
            result["description"] = value
        elif key == "linked professions":
            result["linked_professions"] = [v.strip() for v in value.split(",") if v.strip()]
        elif key == "linked routines":
            result["linked_routines"] = [v.strip() for v in value.split(",") if v.strip()]
        elif key == "recent progress":
            result["recent_progress"] = [v.strip() for v in value.split(" | ") if v.strip()]
        elif key == "notes":
            result["notes"] = value
    if not result["slug"] and result["title"]:
        result["slug"] = slugify_goal(result["title"])
    return result


def render_goal_entry(entry: Dict[str, Any]) -> str:
    linked_profs = ", ".join(sorted(dict.fromkeys(entry.get("linked_professions", []))))
    linked_routines = ", ".join(sorted(dict.fromkeys(entry.get("linked_routines", []))))
    recent_progress = " | ".join((entry.get("recent_progress") or [])[:RECENT_PROGRESS_LIMIT])
    status = entry.get("status", "active")
    if status not in _VALID_STATUSES:
        status = "active"
    return "\n".join(
        [
            f"Goal: {entry.get('title', '').strip()}",
            f"Slug: {entry.get('slug', '').strip()}",
            f"Status: {status}",
            f"Created At: {entry.get('created_at', '').strip()}",
            f"Updated At: {entry.get('updated_at', '').strip()}",
            f"Description: {entry.get('description', '').strip()}",
            f"Linked Professions: {linked_profs}",
            f"Linked Routines: {linked_routines}",
            f"Recent Progress: {recent_progress}",
            f"Notes: {entry.get('notes', '').strip()}",
        ]
    ).strip()


def _compact_progress(values: List[str], *, limit: int = RECENT_PROGRESS_LIMIT) -> List[str]:
    seen: set = set()
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


def _save_entries(entries: List[Dict[str, Any]]) -> None:
    rendered = [render_goal_entry(entry) for entry in sorted(entries, key=lambda item: item["slug"])]
    _write_entries(rendered)


def list_goals() -> List[Dict[str, Any]]:
    return [parse_goal_entry(entry) for entry in _read_entries()]


def get_goal(slug_or_title: str) -> Optional[Dict[str, Any]]:
    needle = slugify_goal(slug_or_title)
    for entry in list_goals():
        if entry.get("slug") == needle or slugify_goal(entry.get("title", "")) == needle:
            return entry
    return None


def save_goal(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert a goal by slug. Preserves created_at, refreshes updated_at."""
    entry = dict(entry)
    entry.setdefault("status", "active")
    if entry["status"] not in _VALID_STATUSES:
        entry["status"] = "active"
    slug = entry.get("slug") or slugify_goal(entry.get("title", ""))
    entry["slug"] = slug

    entries = list_goals()
    now = _utcnow_iso()
    for idx, existing in enumerate(entries):
        if existing.get("slug") == slug:
            existing.update({k: v for k, v in entry.items() if k != "created_at"})
            existing.setdefault("created_at", entry.get("created_at") or now)
            existing["updated_at"] = now
            entries[idx] = existing
            _save_entries(entries)
            return existing
    # new
    entry.setdefault("created_at", now)
    entry["updated_at"] = now
    entry.setdefault("linked_professions", [])
    entry.setdefault("linked_routines", [])
    entry.setdefault("recent_progress", [])
    entry.setdefault("description", "")
    entry.setdefault("notes", "")
    entries.append(entry)
    _save_entries(entries)
    return entry


def create_goal(
    title: str,
    description: str = "",
    linked_professions: Optional[List[str]] = None,
    linked_routines: Optional[List[str]] = None,
    status: str = "active",
    notes: str = "",
) -> Dict[str, Any]:
    title = (title or "").strip()
    if not title:
        return {"success": False, "error": "title is required"}
    slug = slugify_goal(title)
    if get_goal(slug):
        return {"success": False, "error": f"Goal already exists: {title}", "slug": slug, "existed": True}
    now = _utcnow_iso()
    entry = {
        "title": title,
        "slug": slug,
        "status": status if status in _VALID_STATUSES else "active",
        "created_at": now,
        "updated_at": now,
        "description": description.strip(),
        "linked_professions": sorted(
            dict.fromkeys(str(p).strip() for p in (linked_professions or []) if str(p).strip())
        ),
        "linked_routines": sorted(
            dict.fromkeys(str(r).strip() for r in (linked_routines or []) if str(r).strip())
        ),
        "recent_progress": [],
        "notes": notes.strip(),
    }
    entries = list_goals()
    entries.append(entry)
    _save_entries(entries)
    return {"success": True, **entry}


def update_goal(slug: str, **fields: Any) -> Dict[str, Any]:
    """Update arbitrary fields on a goal. Slug cannot be changed here."""
    target = slugify_goal(slug)
    entries = list_goals()
    for item in entries:
        if item.get("slug") != target:
            continue
        for key, value in fields.items():
            if key == "slug" or key == "created_at":
                continue
            if key == "status":
                value = str(value or "").lower()
                if value not in _VALID_STATUSES:
                    return {"success": False, "error": f"invalid status: {value}"}
            item[key] = value
        item["updated_at"] = _utcnow_iso()
        _save_entries(entries)
        return {"success": True, **item}
    return {"success": False, "error": f"Goal not found: {slug}"}


def add_progress(slug: str, entry: str, *, source: str = "") -> Dict[str, Any]:
    entry = (entry or "").strip()
    if not entry:
        return {"success": False, "error": "entry is required"}
    target = slugify_goal(slug)
    entries = list_goals()
    for item in entries:
        if item.get("slug") != target:
            continue
        label = f"[{source}] {entry}" if source else entry
        existing = list(item.get("recent_progress") or [])
        item["recent_progress"] = _compact_progress([label] + existing)
        item["updated_at"] = _utcnow_iso()
        _save_entries(entries)
        return {
            "success": True,
            "slug": item["slug"],
            "title": item.get("title", ""),
            "recent_progress": item["recent_progress"],
        }
    return {"success": False, "error": f"Goal not found: {slug}"}


def set_status(slug: str, status: str) -> Dict[str, Any]:
    status = str(status or "").lower().strip()
    if status not in _VALID_STATUSES:
        return {"success": False, "error": f"invalid status: {status}"}
    return update_goal(slug, status=status)


def link_profession(goal_slug: str, profession_slug: str) -> Dict[str, Any]:
    profession_slug = (profession_slug or "").strip()
    if not profession_slug:
        return {"success": False, "error": "profession_slug is required"}
    target = slugify_goal(goal_slug)
    entries = list_goals()
    for item in entries:
        if item.get("slug") != target:
            continue
        linked = list(item.get("linked_professions") or [])
        if profession_slug not in linked:
            linked.append(profession_slug)
            item["linked_professions"] = sorted(dict.fromkeys(linked))
            item["updated_at"] = _utcnow_iso()
            _save_entries(entries)
        return {"success": True, "slug": item["slug"], "linked_professions": item["linked_professions"]}
    return {"success": False, "error": f"Goal not found: {goal_slug}"}


def unlink_profession(goal_slug: str, profession_slug: str) -> Dict[str, Any]:
    target = slugify_goal(goal_slug)
    entries = list_goals()
    for item in entries:
        if item.get("slug") != target:
            continue
        linked = [p for p in item.get("linked_professions") or [] if p != profession_slug]
        if len(linked) == len(item.get("linked_professions") or []):
            return {"success": False, "error": f"Profession '{profession_slug}' not linked"}
        item["linked_professions"] = linked
        item["updated_at"] = _utcnow_iso()
        _save_entries(entries)
        return {"success": True, "slug": item["slug"], "linked_professions": linked}
    return {"success": False, "error": f"Goal not found: {goal_slug}"}


def link_routine(goal_slug: str, cron_id: str) -> Dict[str, Any]:
    cron_id = (cron_id or "").strip()
    if not cron_id:
        return {"success": False, "error": "cron_id is required"}
    target = slugify_goal(goal_slug)
    entries = list_goals()
    for item in entries:
        if item.get("slug") != target:
            continue
        linked = list(item.get("linked_routines") or [])
        if cron_id not in linked:
            linked.append(cron_id)
            item["linked_routines"] = sorted(dict.fromkeys(linked))
            item["updated_at"] = _utcnow_iso()
            _save_entries(entries)
        return {"success": True, "slug": item["slug"], "linked_routines": item["linked_routines"]}
    return {"success": False, "error": f"Goal not found: {goal_slug}"}


def unlink_routine(goal_slug: str, cron_id: str) -> Dict[str, Any]:
    target = slugify_goal(goal_slug)
    entries = list_goals()
    for item in entries:
        if item.get("slug") != target:
            continue
        linked = [r for r in item.get("linked_routines") or [] if r != cron_id]
        if len(linked) == len(item.get("linked_routines") or []):
            return {"success": False, "error": f"Routine '{cron_id}' not linked"}
        item["linked_routines"] = linked
        item["updated_at"] = _utcnow_iso()
        _save_entries(entries)
        return {"success": True, "slug": item["slug"], "linked_routines": linked}
    return {"success": False, "error": f"Goal not found: {goal_slug}"}


def delete_goal(slug: str) -> Dict[str, Any]:
    target = slugify_goal(slug)
    entries = list_goals()
    remaining = [e for e in entries if e.get("slug") != target]
    if len(remaining) == len(entries):
        return {"success": False, "error": f"Goal not found: {slug}"}
    _save_entries(remaining)
    return {"success": True, "slug": target}


def _load_goals_cfg() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
        goals_cfg = cfg.get("goals", {}) if isinstance(cfg, dict) else {}
        return goals_cfg if isinstance(goals_cfg, dict) else {}
    except Exception:
        return {}


# Env var used by `hermes chat --goal` and the in-REPL `/goal` command to pin
# a goal for the duration of a single session without touching config.yaml.
# Precedence: env var > goals.active in config > nothing.
_SESSION_GOAL_ENV = "HERMES_SESSION_GOAL"


def get_active_goal_slug() -> str:
    """Return the currently-pinned active goal slug, or ``""`` if none.

    Precedence: ``HERMES_SESSION_GOAL`` env var > ``goals.active`` config.
    Session override (env) wins so ``hermes chat --goal X`` and ``/goal X``
    never mutate persistent state.
    """
    env = (os.environ.get(_SESSION_GOAL_ENV) or "").strip()
    if env:
        return slugify_goal(env)
    cfg = _load_goals_cfg()
    value = cfg.get("active") if isinstance(cfg, dict) else ""
    return slugify_goal(str(value or "")) if value else ""


def set_active_goal(slug_or_title: str) -> Dict[str, Any]:
    """Pin a goal persistently via ``goals.active`` in config.yaml."""
    entry = get_goal(slug_or_title)
    if not entry:
        return {"success": False, "error": f"Goal not found: {slug_or_title}"}
    if entry.get("status") != "active":
        return {
            "success": False,
            "error": f"Goal '{entry.get('title') or entry.get('slug')}' is {entry.get('status')}, not active. Resume it first.",
        }
    try:
        from hermes_cli.config import load_config, save_config

        cfg = load_config() or {}
        cfg.setdefault("goals", {})
        if not isinstance(cfg["goals"], dict):
            cfg["goals"] = {}
        cfg["goals"]["active"] = entry["slug"]
        save_config(cfg)
    except Exception as e:
        return {"success": False, "error": f"config write failed: {e}"}
    return {"success": True, "slug": entry["slug"], "title": entry.get("title", "")}


def clear_active_goal() -> Dict[str, Any]:
    """Clear the persistent active-goal pin."""
    try:
        from hermes_cli.config import load_config, save_config

        cfg = load_config() or {}
        goals_cfg = cfg.get("goals") if isinstance(cfg, dict) else {}
        if isinstance(goals_cfg, dict) and goals_cfg.get("active"):
            goals_cfg["active"] = ""
            save_config(cfg)
    except Exception as e:
        return {"success": False, "error": f"config write failed: {e}"}
    return {"success": True}


def summarize_active(
    max_goals: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> str:
    """Compact text block of active goals suitable for the router prompt.

    If an active-goal pin is set (``hermes goals use`` or session env), it is
    rendered first with full detail and explicitly labelled, while the other
    active goals are demoted to terse one-liners so brain focus follows the
    user's pin without losing cross-context awareness.

    Returns an empty string when no active goals exist. Respects config
    (``goals.max_active_goals``, ``goals.max_summary_chars``) as defaults.
    """
    cfg = _load_goals_cfg()
    if not cfg.get("enabled", True):
        return ""
    if max_goals is None:
        max_goals = int(cfg.get("max_active_goals") or _DEFAULT_MAX_ACTIVE_GOALS)
    if max_chars is None:
        max_chars = int(cfg.get("max_summary_chars") or _DEFAULT_MAX_SUMMARY_CHARS)

    active = [g for g in list_goals() if g.get("status") == "active"]
    if not active:
        return ""

    pinned_slug = get_active_goal_slug()
    pinned: Optional[Dict[str, Any]] = None
    others: List[Dict[str, Any]] = []
    if pinned_slug:
        for g in active:
            if g.get("slug") == pinned_slug and pinned is None:
                pinned = g
            else:
                others.append(g)
    else:
        others = list(active)

    # Newest updated_at first for the non-pinned tail.
    others.sort(key=lambda g: g.get("updated_at", ""), reverse=True)

    def _render_full(goal: Dict[str, Any], *, pinned: bool = False) -> str:
        title = goal.get("title", "").strip() or goal.get("slug", "")
        desc = goal.get("description", "").strip()
        linked = goal.get("linked_professions") or []
        prefix = "★" if pinned else "-"
        parts = [f"{prefix} {title}" + ("  [focus for this conversation]" if pinned else "")]
        if desc:
            parts.append(f"  desc: {desc[:200]}")
        if linked:
            parts.append(f"  linked: {', '.join(linked[:5])}")
        recent = (goal.get("recent_progress") or [])[:3 if pinned else 2]
        if recent:
            parts.append(f"  recent: {' | '.join(r[:120] for r in recent)}")
        return "\n".join(parts)

    def _render_terse(goal: Dict[str, Any]) -> str:
        title = goal.get("title", "").strip() or goal.get("slug", "")
        linked = (goal.get("linked_professions") or [])[:2]
        tail = f" (linked: {', '.join(linked)})" if linked else ""
        return f"- {title}{tail}"

    blocks: List[str] = []
    if pinned is not None:
        blocks.append(_render_full(pinned, pinned=True))
        room = max(0, int(max_goals) - 1)
        for goal in others[:room]:
            blocks.append(_render_terse(goal))
    else:
        cap = max(1, int(max_goals))
        for goal in others[:cap]:
            blocks.append(_render_full(goal, pinned=False))

    text = "\n".join(blocks)
    if len(text) > max_chars:
        text = text[: max(0, int(max_chars) - 3)] + "..."
    return text


def goals_enabled() -> bool:
    cfg = _load_goals_cfg()
    return bool(cfg.get("enabled", True))


def inject_into_brain() -> bool:
    cfg = _load_goals_cfg()
    return bool(cfg.get("inject_into_brain", True))


def inject_into_prompt() -> bool:
    cfg = _load_goals_cfg()
    return bool(cfg.get("inject_into_prompt", False))


def goals_hash() -> str:
    """Hash of the active-goals summary. Used in prompt_builder cache key."""
    if not inject_into_prompt():
        return ""
    try:
        import hashlib

        return hashlib.sha256(summarize_active().encode("utf-8")).hexdigest()[:16]
    except Exception:
        return ""
