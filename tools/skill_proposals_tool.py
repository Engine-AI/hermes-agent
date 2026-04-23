#!/usr/bin/env python3
"""Skill proposal queue — brain detects gaps, user reviews.

When the router identifies a skill gap (either LLM-emitted ``skill_gap`` or
the retry-based heuristic), we write a markdown proposal under
``~/.hermes/skill-requests/``. Users list/review/accept/reject via
``hermes skills proposals``; accepted proposals move to an ``accepted/``
subdirectory for manual follow-through (authoring the skill, or feeding the
proposal to ``agent.skill_generator`` in a later version).

Proposals have two ``kind``s:

  - ``skill``: a missing capability ("can't do X with the current skill set")
  - ``split``: a bloated profession should be split into smaller ones

Both use the same frontmatter + markdown body shape. The file path encodes
the status (open → ``<slug>.md``, accepted → ``accepted/<slug>.md``, etc).

Deduplication is intent-based (SequenceMatcher on normalized strings) — good
enough for the scale we expect. When a near-identical intent already has an
open proposal, we bump its ``failed_attempts`` counter rather than creating a
duplicate file.
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_constants import get_hermes_home

SKILL_REQUESTS_DIRNAME = "skill-requests"
ACCEPTED_SUBDIR = "accepted"
REJECTED_SUBDIR = "rejected"
FULFILLED_SUBDIR = "fulfilled"

_DEFAULT_DEDUP_THRESHOLD = 0.75
_STATUS_TO_SUBDIR = {
    "open": "",
    "accepted": ACCEPTED_SUBDIR,
    "rejected": REJECTED_SUBDIR,
    "fulfilled": FULFILLED_SUBDIR,
}


def proposals_dir() -> Path:
    path = get_hermes_home() / SKILL_REQUESTS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _status_dir(status: str) -> Path:
    sub = _STATUS_TO_SUBDIR.get(status, "")
    base = proposals_dir()
    if sub:
        target = base / sub
        target.mkdir(parents=True, exist_ok=True)
        return target
    return base


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "proposal"


def _atomic_text_write(path: Path, text: str) -> None:
    """Write *text* to *path* atomically (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_brain_cfg() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
        brain_cfg = cfg.get("brain", {}) if isinstance(cfg, dict) else {}
        return brain_cfg if isinstance(brain_cfg, dict) else {}
    except Exception:
        return {}


def _normalize_intent(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _render_proposal(meta: Dict[str, Any], body: str) -> str:
    """Render a proposal as ``---\n<yaml>\n---\n<body>\n``.

    We hand-write the frontmatter instead of pulling in PyYAML to avoid a
    new import here; proposals are simple enough for key: value lines.
    """
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            inner = ", ".join(str(v) for v in value)
            lines.append(f"{key}: [{inner}]" if value else f"{key}: []")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        elif value is None:
            lines.append(f"{key}: ''")
        else:
            svalue = str(value)
            if "\n" in svalue or ":" in svalue or "#" in svalue:
                svalue = svalue.replace('"', '\\"')
                lines.append(f'{key}: "{svalue}"')
            else:
                lines.append(f"{key}: {svalue}")
    lines.append("---")
    if body and not body.endswith("\n"):
        body = body + "\n"
    return "\n".join(lines) + "\n" + (body or "")


def _parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines:
        return {}, text
    end_idx = -1
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = idx
            break
    if end_idx < 0:
        return {}, text
    meta: Dict[str, Any] = {}
    for line in lines[1:end_idx]:
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            if not inner:
                meta[key] = []
            else:
                meta[key] = [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
        elif raw.lower() in {"true", "false"}:
            meta[key] = raw.lower() == "true"
        elif raw.startswith(('"', "'")) and raw.endswith(('"', "'")) and len(raw) >= 2:
            meta[key] = raw[1:-1]
        else:
            try:
                meta[key] = int(raw)
            except ValueError:
                try:
                    meta[key] = float(raw)
                except ValueError:
                    meta[key] = raw
    body = "\n".join(lines[end_idx + 1 :])
    return meta, body


def _iter_files_all_statuses() -> List[tuple[str, Path]]:
    out: List[tuple[str, Path]] = []
    for status, sub in _STATUS_TO_SUBDIR.items():
        base = proposals_dir() / sub if sub else proposals_dir()
        if not base.exists():
            continue
        for p in sorted(base.glob("*.md")):
            if p.name.startswith("."):
                continue
            out.append((status, p))
    return out


def load_proposal(slug: str) -> Optional[Dict[str, Any]]:
    slug = _slugify(slug)
    for status, path in _iter_files_all_statuses():
        if path.stem == slug:
            text = path.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            meta["_path"] = str(path)
            meta["_status_from_path"] = status
            meta["body"] = body
            return meta
    return None


def list_proposals(status: str = "open") -> List[Dict[str, Any]]:
    """Return proposals filtered by status (``open``, ``accepted``, etc.).

    Pass ``status="all"`` to get every proposal in every state. Sorted by
    ``created_at`` descending (newest first).
    """
    want_all = status == "all"
    out: List[Dict[str, Any]] = []
    for s, path in _iter_files_all_statuses():
        if not want_all and s != status:
            continue
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        meta["_path"] = str(path)
        meta["_status_from_path"] = s
        meta["body"] = body
        out.append(meta)
    out.sort(key=lambda m: str(m.get("created_at", "")), reverse=True)
    return out


def dedupe_by_intent_similarity(
    intent: str,
    *,
    threshold: Optional[float] = None,
    status: str = "open",
) -> Optional[str]:
    """Return the slug of an existing proposal with a near-identical intent.

    Only compares against proposals of ``kind: skill`` in the given status.
    """
    if threshold is None:
        threshold = float(_load_brain_cfg().get("proposal_dedup_threshold") or _DEFAULT_DEDUP_THRESHOLD)
    normalized = _normalize_intent(intent)
    if not normalized:
        return None
    best_slug: Optional[str] = None
    best_ratio = 0.0
    for meta in list_proposals(status=status):
        if meta.get("kind") != "skill":
            continue
        candidate = _normalize_intent(str(meta.get("typical_intent") or ""))
        if not candidate:
            continue
        ratio = SequenceMatcher(None, normalized, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_slug = str(meta.get("slug") or "")
    if best_ratio >= threshold and best_slug:
        return best_slug
    return None


def _generate_unique_slug(seed: str, *, existing: set) -> str:
    base = _slugify(seed)
    if base not in existing:
        return base
    for idx in range(2, 100):
        candidate = f"{base}-{idx}"
        if candidate not in existing:
            return candidate
    return f"{base}-{_utcnow_iso().replace(':', '').replace('-', '')}"


def _all_slugs() -> set:
    return {path.stem for _, path in _iter_files_all_statuses()}


def create_proposal(
    intent: str,
    requesting_profession: str,
    *,
    created_by: str = "brain",
    failed_attempts: int = 1,
    suggested_interface: str = "",
    examples: Optional[List[str]] = None,
    context: str = "",
) -> Dict[str, Any]:
    """Create (or bump) a skill proposal.

    If a near-identical open proposal already exists, we increment its
    ``failed_attempts`` counter and append any new examples — no new file.
    """
    intent = (intent or "").strip()
    if not intent:
        return {"success": False, "error": "intent is required"}

    # Dedup check
    existing_slug = dedupe_by_intent_similarity(intent, status="open")
    if existing_slug:
        existing = load_proposal(existing_slug)
        if existing:
            path = Path(existing["_path"])
            meta = {k: v for k, v in existing.items() if not k.startswith("_") and k != "body"}
            meta["failed_attempts"] = int(meta.get("failed_attempts", 0) or 0) + int(failed_attempts or 1)
            meta["updated_at"] = _utcnow_iso()
            body = existing.get("body", "") or ""
            if examples:
                append_lines = ["", "## Additional examples"]
                append_lines.extend(f"- {e}" for e in examples if e)
                body = body.rstrip() + "\n" + "\n".join(append_lines) + "\n"
            rendered = _render_proposal(meta, body)
            _atomic_text_write(path, rendered)
            return {
                "success": True,
                "slug": meta.get("slug"),
                "deduped": True,
                "failed_attempts": meta["failed_attempts"],
            }

    slug = _generate_unique_slug(intent[:40] or "skill-request", existing=_all_slugs())
    now = _utcnow_iso()
    meta: Dict[str, Any] = {
        "slug": slug,
        "created_at": now,
        "updated_at": now,
        "created_by": created_by,
        "requesting_profession": (requesting_profession or "").strip(),
        "status": "open",
        "kind": "skill",
        "typical_intent": intent[:500],
        "failed_attempts": int(failed_attempts or 1),
        "suggested_interface": (suggested_interface or "").strip(),
    }
    examples = [e for e in (examples or []) if e]
    body_parts = []
    if context:
        body_parts.extend(["# Context", context.strip(), ""])
    if examples:
        body_parts.extend(["# Example usages"])
        body_parts.extend(f"- {e}" for e in examples)
        body_parts.append("")
    body = "\n".join(body_parts) or "# Context\n(auto-generated by brain)\n"
    path = _status_dir("open") / f"{slug}.md"
    _atomic_text_write(path, _render_proposal(meta, body))
    return {"success": True, "slug": slug, "deduped": False, "path": str(path)}


def create_split_proposal(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a bloat-split proposal. Debounced by source_slug (24h)."""
    source_slug = (payload.get("source_slug") or "").strip()
    if not source_slug:
        return {"success": False, "error": "source_slug is required"}
    # Debounce: if we already have an open split proposal for this source within
    # the last 24h, skip.
    for meta in list_proposals(status="open"):
        if meta.get("kind") != "split":
            continue
        if (meta.get("source_slug") or "") != source_slug:
            continue
        created = str(meta.get("created_at") or "")
        if not created:
            continue
        try:
            ts = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
        except Exception:
            age_hours = 0
        if age_hours < 24:
            return {"success": False, "error": "debounced", "existing_slug": meta.get("slug")}

    suggestions = payload.get("suggested_splits") or []
    skill_count = int(payload.get("skill_count") or 0)
    slug = _generate_unique_slug(f"split-{source_slug}", existing=_all_slugs())
    now = _utcnow_iso()
    meta = {
        "slug": slug,
        "created_at": now,
        "updated_at": now,
        "created_by": "brain",
        "status": "open",
        "kind": "split",
        "source_slug": source_slug,
        "skill_count": skill_count,
    }
    body_parts = [
        "# Context",
        f"Profession `{source_slug}` has {skill_count} skills (over soft cap).",
        "",
    ]
    if suggestions:
        body_parts.append("# Suggested splits")
        for s in suggestions:
            name = str(s.get("name") or "?")
            skills = ", ".join(s.get("skills") or [])
            body_parts.append(f"- **{name}**: {skills}")
    body = "\n".join(body_parts) + "\n"
    path = _status_dir("open") / f"{slug}.md"
    _atomic_text_write(path, _render_proposal(meta, body))
    return {"success": True, "slug": slug, "path": str(path)}


def _move_to_status(slug: str, target_status: str) -> Dict[str, Any]:
    proposal = load_proposal(slug)
    if not proposal:
        return {"success": False, "error": f"Proposal not found: {slug}"}
    source_path = Path(proposal["_path"])
    if proposal.get("_status_from_path") == target_status:
        return {"success": True, "slug": slug, "noop": True}

    meta = {k: v for k, v in proposal.items() if not k.startswith("_") and k != "body"}
    meta["status"] = target_status
    meta["updated_at"] = _utcnow_iso()
    body = proposal.get("body", "") or ""

    target_path = _status_dir(target_status) / f"{slug}.md"
    _atomic_text_write(target_path, _render_proposal(meta, body))
    try:
        if source_path.exists() and source_path.resolve() != target_path.resolve():
            source_path.unlink()
    except OSError:
        pass
    return {"success": True, "slug": slug, "status": target_status, "path": str(target_path)}


def mark_accepted(slug: str) -> Dict[str, Any]:
    return _move_to_status(slug, "accepted")


def mark_rejected(slug: str) -> Dict[str, Any]:
    return _move_to_status(slug, "rejected")


def mark_fulfilled(slug: str) -> Dict[str, Any]:
    return _move_to_status(slug, "fulfilled")
