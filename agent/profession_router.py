"""Brain: profession routing + skill gap detection + goals context.

Decides — given a user query, the active profession, and the user's active
goals — whether to stay, switch to an existing profession, create a new one,
or borrow a handful of skills from a sibling. Backed by the main model via
``agent.auxiliary_client.call_llm(task="profession_routing", ...)``.

Also:
  - Detects skill gaps (both LLM-emitted and retry-based heuristics) and
    emits markdown proposals via ``tools/skill_proposals_tool``.
  - Detects profession bloat (skill count > soft cap) and emits split
    proposals with 24h debounce.
  - Enforces a per-session LLM call budget to cap router cost.

Gated by ``professions.auto_route`` in the user config. When the flag is
off, ``should_route()`` returns False and ``route()`` is never called, so
the feature is completely passive for existing users.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_DRIFT_CHECK_INTERVAL = 5
_DEFAULT_BRAIN_BUDGET = 3
_DEFAULT_BLOAT_SOFT_CAP = 15
_DEFAULT_RETRY_GAP_THRESHOLD = 3
_BORROW_MAX_SKILLS = 3
_BORROW_MAX_SOURCES = 2
_RETRY_INTENT_WINDOW = 20  # Keep at most N recent intents in brain_state.json
_BLOAT_DEBOUNCE_HOURS = 24


@dataclass
class RoutingDecision:
    action: str  # "stay" | "switch" | "create" | "borrow"
    target_slug: str = ""
    new_profession: Dict[str, Any] = field(default_factory=dict)
    borrow_from: List[str] = field(default_factory=list)
    borrow_skills: List[str] = field(default_factory=list)
    skill_gap: Dict[str, Any] = field(default_factory=dict)
    split_proposal: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    @classmethod
    def stay(cls, reason: str = "") -> "RoutingDecision":
        return cls(action="stay", reason=reason)


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------


def _load_professions_cfg() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
        prof_cfg = cfg.get("professions", {}) if isinstance(cfg, dict) else {}
        return prof_cfg if isinstance(prof_cfg, dict) else {}
    except Exception:
        return {}


def _load_brain_cfg() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
        brain_cfg = cfg.get("brain", {}) if isinstance(cfg, dict) else {}
        return brain_cfg if isinstance(brain_cfg, dict) else {}
    except Exception:
        return {}


def _brain_state_path() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "brain_state.json"


def _load_brain_state() -> Dict[str, Any]:
    path = _brain_state_path()
    if not path.exists():
        return {"sessions": {}, "last_intents": []}
    try:
        import json as _json

        data = _json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"sessions": {}, "last_intents": []}
        data.setdefault("sessions", {})
        data.setdefault("last_intents", [])
        return data
    except Exception:
        return {"sessions": {}, "last_intents": []}


def _save_brain_state(state: Dict[str, Any]) -> None:
    try:
        from utils import atomic_json_write

        atomic_json_write(_brain_state_path(), state)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Should-route gate
# ---------------------------------------------------------------------------


def should_route(user_turn_idx: int, active_profession_slug: str) -> bool:
    """True when the router should run for this turn.

    Rules:
      - ``professions.auto_route`` must be on.
      - Always run on the first user turn (``user_turn_idx == 1``).
      - Otherwise run every ``drift_check_interval`` turns (default 5).
    """
    cfg = _load_professions_cfg()
    if not cfg.get("auto_route"):
        return False
    if user_turn_idx <= 0:
        return False
    if user_turn_idx == 1:
        return True
    interval = cfg.get("drift_check_interval") or DEFAULT_DRIFT_CHECK_INTERVAL
    try:
        interval = max(1, int(interval))
    except Exception:
        interval = DEFAULT_DRIFT_CHECK_INTERVAL
    return user_turn_idx % interval == 0


# ---------------------------------------------------------------------------
# Cheap fast path (no LLM)
# ---------------------------------------------------------------------------


def _keyword_fast_match(query: str, active_entry: Optional[Dict[str, Any]]) -> bool:
    """True when the query plainly belongs to the active profession.

    Cheap pre-filter to skip the LLM router call. We require ≥2 keyword hits
    (across the profession's domains and skills) to be conservative.
    """
    if not active_entry:
        return False
    domains = active_entry.get("problem_domains") or []
    skills = active_entry.get("skills") or []
    q = (query or "").lower()
    if not q:
        return False
    hits = 0
    for d in domains:
        if d and str(d).lower() in q:
            hits += 1
    for s in skills:
        if s and str(s).lower() in q:
            hits += 1
    return hits >= 2


# ---------------------------------------------------------------------------
# Retry-based skill gap detection (no LLM)
# ---------------------------------------------------------------------------


def _hash_intent(text: str) -> str:
    return hashlib.sha256((text or "").strip().lower()[:120].encode("utf-8")).hexdigest()[:16]


def record_turn_for_gap_detection(
    active_slug: str, user_query: str
) -> Optional[Dict[str, Any]]:
    """Detect repeat intents in the same profession. Returns a skill_gap dict
    when the same intent has been retried ``retry_gap_threshold`` times
    (default 3) within the recent window.

    Never raises — any failure returns ``None``.
    """
    try:
        query = (user_query or "").strip()
        if not query:
            return None
        threshold = int(
            _load_brain_cfg().get("retry_gap_threshold") or _DEFAULT_RETRY_GAP_THRESHOLD
        )
        state = _load_brain_state()
        intents = list(state.get("last_intents") or [])
        h = _hash_intent(query)
        now = _utcnow_iso()
        matched_idx = -1
        for idx, item in enumerate(intents):
            if (
                item.get("slug") == (active_slug or "")
                and item.get("query_hash") == h
            ):
                matched_idx = idx
                break
        if matched_idx >= 0:
            intents[matched_idx]["count"] = int(intents[matched_idx].get("count", 0) or 0) + 1
            intents[matched_idx]["ts"] = now
            intents[matched_idx]["last_query"] = query[:200]
            count = intents[matched_idx]["count"]
        else:
            intents.append(
                {
                    "slug": active_slug or "",
                    "query_hash": h,
                    "count": 1,
                    "ts": now,
                    "last_query": query[:200],
                }
            )
            count = 1
        # Bound the window.
        if len(intents) > _RETRY_INTENT_WINDOW:
            intents = intents[-_RETRY_INTENT_WINDOW:]
        state["last_intents"] = intents
        _save_brain_state(state)
        if count >= threshold:
            # Reset the counter so we only fire once per threshold crossing.
            for item in intents:
                if item.get("query_hash") == h and item.get("slug") == (active_slug or ""):
                    item["count"] = 0
            state["last_intents"] = intents
            _save_brain_state(state)
            return {
                "intent": query[:300],
                "confidence": 0.7,
                "source": "retry_heuristic",
            }
        return None
    except Exception as e:
        logger.debug("record_turn_for_gap_detection failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Brain call budget
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _brain_budget_remaining(session_id: str) -> int:
    if not session_id:
        return _DEFAULT_BRAIN_BUDGET
    cfg = _load_brain_cfg()
    total = int(cfg.get("budget_per_session") or _DEFAULT_BRAIN_BUDGET)
    state = _load_brain_state()
    sessions = state.get("sessions") or {}
    used = int((sessions.get(session_id) or {}).get("router_calls", 0))
    return max(0, total - used)


def _consume_brain_call(session_id: str) -> None:
    if not session_id:
        return
    try:
        state = _load_brain_state()
        sessions = state.setdefault("sessions", {})
        slot = sessions.setdefault(session_id, {})
        slot["router_calls"] = int(slot.get("router_calls", 0) or 0) + 1
        slot["last_call_at"] = _utcnow_iso()
        _save_brain_state(state)
    except Exception:
        pass


def reset_brain_budget(session_id: str) -> None:
    """Clear the per-session counter (called on profession switch if
    ``brain.reset_on_profession_switch`` is True)."""
    if not session_id:
        return
    try:
        state = _load_brain_state()
        sessions = state.get("sessions") or {}
        if session_id in sessions:
            sessions.pop(session_id, None)
            state["sessions"] = sessions
            _save_brain_state(state)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Router LLM call
# ---------------------------------------------------------------------------


def _build_router_messages(
    query: str,
    active_slug: str,
    active_entry: Optional[Dict[str, Any]],
    professions_summary: List[Dict[str, Any]],
    recent_turns: List[Dict[str, Any]],
    goals_context: str = "",
) -> List[Dict[str, str]]:
    active_block = "none"
    if active_entry:
        active_block = json.dumps(
            {
                "slug": active_entry.get("slug", active_slug),
                "name": active_entry.get("profession", ""),
                "problem_domains": active_entry.get("problem_domains", []),
                "skills_count": len(active_entry.get("skills") or []),
            },
            ensure_ascii=False,
        )

    recent_snippet = ""
    if recent_turns:
        lines = []
        for turn in recent_turns[-3:]:
            role = str(turn.get("role", "")).strip() or "user"
            content = str(turn.get("content", "") or "")[:300]
            if content:
                lines.append(f"{role}: {content}")
        recent_snippet = "\n".join(lines)

    system = (
        "You route Hermes agent conversations to the right profession. "
        "Given the user query, the user's active goals, and existing "
        "professions, decide ONE action:\n"
        "  - \"stay\": the active profession still fits.\n"
        "  - \"switch\": a different existing profession fits better.\n"
        "  - \"create\": no existing profession fits; describe a new one.\n"
        "  - \"borrow\": active profession is primary but needs ≤3 skills "
        "from a sibling profession (e.g., cross-domain task).\n"
        "\n"
        "Return ONLY JSON with these exact keys:\n"
        "{\n"
        "  \"action\": \"stay\" | \"switch\" | \"create\" | \"borrow\",\n"
        "  \"target_slug\": string (required for switch/borrow; otherwise \"\"),\n"
        "  \"new_profession\": {\n"
        "    \"name\": string, \"problem_domains\": [string], \"suggested_skills\": [string]\n"
        "  } (required when action=\"create\"; otherwise {}),\n"
        "  \"borrow_from\":   [slug, ...]     (≤2 source slugs; required when action=\"borrow\"),\n"
        "  \"borrow_skills\": [skill_name, ...] (≤3 total; required when action=\"borrow\"),\n"
        "  \"skill_gap\":     {\"intent\": string, \"confidence\": 0.0..1.0} (OPTIONAL; emit when no skill covers the request),\n"
        "  \"split_proposal\":{\"source_slug\": string, \"suggested_splits\": [{\"name\": string, \"skills\": [string]}, ...]} (OPTIONAL; emit when active profession has >15 skills),\n"
        "  \"reason\": short string\n"
        "}\n"
        "Prefer \"stay\" unless there is a clear mismatch. Prefer \"borrow\" "
        "over \"switch\" when the active profession is still primary. Prefer "
        "\"switch\" over \"create\" when any existing profession plausibly "
        "covers the task."
    )
    goals_block = goals_context.strip()
    user_content_parts = [f"Active profession: {active_block}"]
    if goals_block:
        user_content_parts.append(f"\nActive goals:\n{goals_block}")
    user_content_parts.extend(
        [
            f"\nExisting professions:\n{json.dumps(professions_summary, ensure_ascii=False)}",
            f"\nRecent conversation:\n{recent_snippet or '(none)'}",
            f"\nNew user query:\n{query}",
        ]
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_content_parts)},
    ]


def _parse_skill_gap(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    intent = str(raw.get("intent") or "").strip()
    if not intent:
        return {}
    try:
        confidence = float(raw.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    return {"intent": intent[:500], "confidence": max(0.0, min(1.0, confidence))}


def _parse_split_proposal(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    source_slug = str(raw.get("source_slug") or "").strip()
    if not source_slug:
        return {}
    suggestions = raw.get("suggested_splits") or []
    cleaned: List[Dict[str, Any]] = []
    if isinstance(suggestions, list):
        for item in suggestions[:6]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            skills = item.get("skills") or []
            if isinstance(skills, str):
                skills = [skills]
            skills = [str(s).strip() for s in skills if str(s).strip()]
            if name or skills:
                cleaned.append({"name": name, "skills": skills})
    return {"source_slug": source_slug, "suggested_splits": cleaned}


def route(
    query: str,
    recent_turns: Optional[List[Dict[str, Any]]] = None,
    *,
    reason: str = "",
    goals_context: str = "",
    session_id: str = "",
) -> RoutingDecision:
    """Produce a routing decision for *query*.

    Never raises — any failure (empty query, LLM error, bad JSON) returns
    ``RoutingDecision.stay()`` so the main conversation is never blocked.
    """
    query = (query or "").strip()
    if not query:
        return RoutingDecision.stay(reason="empty query")

    try:
        from tools.professions_tool import (
            _summarize_professions_for_prompt,
            _extract_first_json_object,
            get_active_profession_slug,
            get_profession,
        )

        active_slug = get_active_profession_slug()
        active_entry = get_profession(active_slug) if active_slug else None
        professions_summary = _summarize_professions_for_prompt()

        # Fast path: cheap keyword match → stay without LLM.
        if _keyword_fast_match(query, active_entry):
            return RoutingDecision.stay(reason="keyword fast-path")

        # Budget guard.
        if session_id and _brain_budget_remaining(session_id) <= 0:
            return RoutingDecision.stay(reason="brain budget exhausted")

        messages = _build_router_messages(
            query,
            active_slug,
            active_entry,
            professions_summary,
            recent_turns or [],
            goals_context=goals_context,
        )

        from agent.auxiliary_client import call_llm

        _consume_brain_call(session_id)
        response = call_llm(
            task="profession_routing",
            messages=messages,
            max_tokens=400,
            temperature=0.0,
        )
        content = (
            response.choices[0].message.content
            if hasattr(response, "choices")
            else str(response or "")
        )
        decision_dict = _extract_first_json_object(content or "") or {}
    except Exception as e:
        logger.debug("profession_router.route failed: %s", e)
        return RoutingDecision.stay(reason=f"router error: {e}")

    action = str(decision_dict.get("action") or "stay").lower().strip()
    if action not in {"stay", "switch", "create", "borrow"}:
        return RoutingDecision.stay(reason="invalid action")

    skill_gap = _parse_skill_gap(decision_dict.get("skill_gap"))
    split_proposal = _parse_split_proposal(decision_dict.get("split_proposal"))

    valid_slugs = {p.get("slug") for p in professions_summary if p.get("slug")}

    # Validate switch target exists; fall back to stay if not.
    if action == "switch":
        target_slug = str(decision_dict.get("target_slug") or "").strip()
        if not target_slug:
            return RoutingDecision.stay(reason="switch without target_slug")
        if target_slug not in valid_slugs:
            return RoutingDecision.stay(reason=f"unknown target_slug {target_slug}")
        return RoutingDecision(
            action="switch",
            target_slug=target_slug,
            skill_gap=skill_gap,
            split_proposal=split_proposal,
            reason=str(decision_dict.get("reason") or ""),
        )

    if action == "create":
        new_prof = decision_dict.get("new_profession") or {}
        if not isinstance(new_prof, dict):
            return RoutingDecision.stay(reason="new_profession not a dict")
        name = str(new_prof.get("name") or "").strip()
        if not name:
            return RoutingDecision.stay(reason="create without name")
        domains = new_prof.get("problem_domains") or []
        skills = new_prof.get("suggested_skills") or []
        if isinstance(domains, str):
            domains = [domains]
        if isinstance(skills, str):
            skills = [skills]
        return RoutingDecision(
            action="create",
            new_profession={
                "name": name,
                "problem_domains": [str(d).strip() for d in domains if str(d).strip()],
                "suggested_skills": [str(s).strip() for s in skills if str(s).strip()],
            },
            skill_gap=skill_gap,
            split_proposal=split_proposal,
            reason=str(decision_dict.get("reason") or ""),
        )

    if action == "borrow":
        borrow_from = decision_dict.get("borrow_from") or []
        borrow_skills = decision_dict.get("borrow_skills") or []
        if isinstance(borrow_from, str):
            borrow_from = [borrow_from]
        if isinstance(borrow_skills, str):
            borrow_skills = [borrow_skills]
        borrow_from = [str(s).strip() for s in borrow_from if str(s).strip() and str(s).strip() in valid_slugs]
        borrow_from = borrow_from[:_BORROW_MAX_SOURCES]
        borrow_skills = [str(s).strip() for s in borrow_skills if str(s).strip()]
        if len(borrow_skills) > _BORROW_MAX_SKILLS:
            logger.info(
                "router: borrow oversized (%d skills) → downgrading to stay",
                len(borrow_skills),
            )
            return RoutingDecision.stay(reason="borrow oversized; downgrade")
        target = str(decision_dict.get("target_slug") or active_slug).strip()
        if target not in valid_slugs:
            return RoutingDecision.stay(reason="borrow without valid target")
        if not borrow_from or not borrow_skills:
            return RoutingDecision.stay(reason="borrow without sources or skills")
        return RoutingDecision(
            action="borrow",
            target_slug=target,
            borrow_from=borrow_from,
            borrow_skills=borrow_skills,
            skill_gap=skill_gap,
            split_proposal=split_proposal,
            reason=str(decision_dict.get("reason") or ""),
        )

    return RoutingDecision(
        action="stay",
        skill_gap=skill_gap,
        split_proposal=split_proposal,
        reason=str(decision_dict.get("reason") or ""),
    )


# ---------------------------------------------------------------------------
# Bloat guard (check active profession's skill count)
# ---------------------------------------------------------------------------


def _bloat_check(active_entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not active_entry:
        return None
    try:
        cfg = _load_brain_cfg()
        soft_cap = int(cfg.get("bloat_soft_cap") or _DEFAULT_BLOAT_SOFT_CAP)
    except Exception:
        soft_cap = _DEFAULT_BLOAT_SOFT_CAP
    skills = active_entry.get("skills") or []
    if len(skills) <= soft_cap:
        return None
    # Debounce via brain_state.json instead of touching profession entry
    # (avoids schema change in PROFESSIONS.md).
    try:
        state = _load_brain_state()
        bloat_emitted = state.setdefault("bloat_emitted", {})
        slug = active_entry.get("slug") or ""
        last_ts = str(bloat_emitted.get(slug) or "")
        if last_ts:
            try:
                ts = datetime.strptime(last_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
                if age_hours < _BLOAT_DEBOUNCE_HOURS:
                    return None
            except Exception:
                pass
    except Exception:
        pass
    return {
        "source_slug": active_entry.get("slug") or "",
        "skills": list(skills),
        "soft_cap": soft_cap,
        "skill_count": len(skills),
    }


def _mark_bloat_emitted(slug: str) -> None:
    if not slug:
        return
    try:
        state = _load_brain_state()
        bloat_emitted = state.setdefault("bloat_emitted", {})
        bloat_emitted[slug] = _utcnow_iso()
        _save_brain_state(state)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Apply decision + side effects
# ---------------------------------------------------------------------------


def apply_decision(decision: RoutingDecision) -> Dict[str, Any]:
    """Apply a routing decision. Returns {action, changed, slug, ...}.

    - stay: no-op on professions, but still emits skill_gap / split_proposal
      if they were attached.
    - switch: set_active_profession(target_slug)
    - create: auto_create_profession then set_active_profession
    - borrow: keep active, record borrow_from/borrow_skills in result for
      callers to inject into the prompt builder.
    Always returns a dict (never raises).
    """
    result: Dict[str, Any] = {"action": decision.action, "changed": False}
    try:
        from tools.professions_tool import (
            auto_create_profession,
            set_active_profession,
            get_active_profession_slug,
            get_profession,
        )

        prior_slug = get_active_profession_slug()
        result["prior_slug"] = prior_slug

        if decision.action == "switch":
            if decision.target_slug != prior_slug:
                outcome = set_active_profession(decision.target_slug)
                if outcome.get("success"):
                    result.update(changed=True, slug=decision.target_slug)
                else:
                    result["error"] = outcome.get("error", "switch failed")

        elif decision.action == "create":
            outcome = auto_create_profession(
                name=decision.new_profession.get("name", ""),
                problem_domains=decision.new_profession.get("problem_domains") or [],
                suggested_skills=decision.new_profession.get("suggested_skills") or [],
            )
            if outcome.get("success"):
                new_slug = outcome["slug"]
                set_active_profession(new_slug)
                result.update(changed=True, slug=new_slug, created=True)
            elif outcome.get("existed"):
                new_slug = outcome["slug"]
                if new_slug != prior_slug:
                    set_active_profession(new_slug)
                    result.update(changed=True, slug=new_slug, created=False)
            else:
                result["error"] = outcome.get("error", "create failed")

        elif decision.action == "borrow":
            # No profession change. Surface the borrow parameters to the caller.
            result.update(
                slug=decision.target_slug or prior_slug,
                borrow_from=list(decision.borrow_from),
                borrow_skills=list(decision.borrow_skills),
            )

        # Skill-gap proposal (shared across all actions).
        if decision.skill_gap and decision.skill_gap.get("intent"):
            try:
                from tools.skill_proposals_tool import create_proposal

                create_proposal(
                    intent=str(decision.skill_gap.get("intent"))[:300],
                    requesting_profession=(result.get("slug") or decision.target_slug or prior_slug or ""),
                    created_by="brain",
                    failed_attempts=1,
                    examples=[],
                )
            except Exception as e:
                logger.debug("skill proposal emit failed: %s", e)

        # LLM-suggested split proposal.
        if decision.split_proposal and decision.split_proposal.get("source_slug"):
            try:
                from tools.skill_proposals_tool import create_split_proposal

                payload = dict(decision.split_proposal)
                # Fill in skill_count if we can look it up.
                src = get_profession(payload.get("source_slug") or "")
                if src is not None and "skill_count" not in payload:
                    payload["skill_count"] = len(src.get("skills") or [])
                create_split_proposal(payload)
                _mark_bloat_emitted(payload.get("source_slug") or "")
            except Exception as e:
                logger.debug("split proposal emit failed: %s", e)

        # Heuristic bloat guard — runs after switch/create so it checks the
        # now-active profession.
        try:
            active_after = get_profession(get_active_profession_slug())
            bloat = _bloat_check(active_after)
            if bloat:
                from tools.skill_proposals_tool import create_split_proposal

                create_split_proposal(bloat)
                _mark_bloat_emitted(bloat.get("source_slug") or "")
        except Exception as e:
            logger.debug("bloat check failed: %s", e)

    except Exception as e:
        logger.debug("profession_router.apply_decision failed: %s", e)
        result["error"] = str(e)
    return result
