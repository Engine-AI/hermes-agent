"""CLI helpers for the skill-requests queue."""

from __future__ import annotations

from hermes_cli.colors import Colors, color
from tools.skill_proposals_tool import (
    list_proposals,
    load_proposal,
    mark_accepted,
    mark_fulfilled,
    mark_rejected,
    proposals_dir,
)


def proposals_command(args) -> None:
    action = getattr(args, "proposals_action", None)

    if action == "list":
        status = getattr(args, "status", "open") or "open"
        items = list_proposals(status=status)
        if not items:
            print(color(f"  No {status} proposals.", Colors.DIM))
            print(color(f"  Directory: {proposals_dir()}", Colors.DIM))
            return
        print()
        print(color(f"  Skill proposals ({status})", Colors.BOLD))
        for idx, meta in enumerate(items, 1):
            slug = meta.get("slug", "?")
            kind = meta.get("kind", "skill")
            intent_or_source = (
                meta.get("typical_intent") if kind == "skill" else meta.get("source_slug")
            )
            attempts = meta.get("failed_attempts") or 1
            created = meta.get("created_at", "")
            line = f"  {idx}. [{kind}] {slug}"
            if intent_or_source:
                line += f" — {str(intent_or_source)[:80]}"
            if kind == "skill":
                line += f"  (attempts: {attempts})"
            print(line)
            if created:
                print(color(f"     {created}", Colors.DIM))
        print()
        return

    if action == "show":
        item = load_proposal(args.slug)
        if not item:
            print(color(f"  Proposal not found: {args.slug}", Colors.YELLOW))
            return
        print()
        print(color(f"  {item.get('slug', '')}  [{item.get('kind', 'skill')}]", Colors.BOLD))
        meta_keys = (
            "status",
            "created_by",
            "created_at",
            "updated_at",
            "requesting_profession",
            "source_slug",
            "typical_intent",
            "failed_attempts",
            "suggested_interface",
            "skill_count",
        )
        for key in meta_keys:
            if key in item and not str(key).startswith("_"):
                value = item[key]
                if value not in (None, "", [], {}):
                    print(f"  {key}: {value}")
        body = item.get("body") or ""
        if body.strip():
            print()
            print(body.rstrip())
        return

    if action == "accept":
        result = mark_accepted(args.slug)
        if not result.get("success"):
            print(color(f"  {result.get('error', 'accept failed')}", Colors.YELLOW))
            return
        print(color(f"  Accepted: {result.get('slug')}", Colors.GREEN))
        return

    if action == "reject":
        result = mark_rejected(args.slug)
        if not result.get("success"):
            print(color(f"  {result.get('error', 'reject failed')}", Colors.YELLOW))
            return
        print(color(f"  Rejected: {result.get('slug')}", Colors.GREEN))
        return

    if action == "fulfill":
        result = mark_fulfilled(args.slug)
        if not result.get("success"):
            print(color(f"  {result.get('error', 'fulfill failed')}", Colors.YELLOW))
            return
        print(color(f"  Marked fulfilled: {result.get('slug')}", Colors.GREEN))
        return

    if action == "path":
        print(str(proposals_dir()))
        return

    print("Usage: hermes skills proposals [list|show|accept|reject|fulfill|path]")
