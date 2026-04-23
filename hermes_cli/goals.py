"""CLI helpers for GOALS.md."""

from __future__ import annotations

from hermes_cli.colors import Colors, color
from tools.goals_tool import (
    add_progress,
    clear_active_goal,
    create_goal,
    delete_goal,
    get_active_goal_slug,
    get_goal,
    get_goals_path,
    link_profession,
    link_routine,
    list_goals,
    set_active_goal,
    set_status,
    summarize_active,
    unlink_profession,
    unlink_routine,
    update_goal,
)


def _print_goal(item: dict) -> None:
    print()
    print(color(f"  {item.get('title') or item.get('slug')}", Colors.BOLD))
    print(f"  Slug: {item.get('slug', '')}")
    print(f"  Status: {item.get('status', 'active')}")
    print(f"  Created At: {item.get('created_at', '')}")
    print(f"  Updated At: {item.get('updated_at', '')}")
    print(f"  Description: {item.get('description') or '(none)'}")
    print(f"  Linked Professions: {', '.join(item.get('linked_professions', [])) or '(none)'}")
    print(f"  Linked Routines: {', '.join(item.get('linked_routines', [])) or '(none)'}")
    print(f"  Recent Progress: {' | '.join(item.get('recent_progress', [])) or '(none)'}")
    print(f"  Notes: {item.get('notes') or '(none)'}")


def goals_command(args) -> None:
    action = getattr(args, "goals_action", None)

    if action == "list":
        goals = list_goals()
        if not goals:
            print(color("  No goals defined.", Colors.DIM))
            print(color("  Add one with: hermes goals add \"<title>\"", Colors.DIM))
            return
        status_order = {"active": 0, "paused": 1, "done": 2}
        ranked = sorted(
            goals,
            key=lambda g: (
                status_order.get(g.get("status", "active"), 3),
                -_epoch(g.get("updated_at", "")),
            ),
        )
        active_slug = get_active_goal_slug()
        print()
        print(color("  Goals", Colors.BOLD))
        for idx, item in enumerate(ranked, 1):
            status = item.get("status", "active")
            status_color = (
                Colors.GREEN if status == "active"
                else Colors.DIM if status == "done"
                else Colors.YELLOW
            )
            pin = " ★" if item.get("slug") == active_slug else ""
            print(
                f"  {idx}. {item.get('title') or item.get('slug')}{pin}  "
                + color(f"[{status}]", status_color)
                + f"  (professions: {len(item.get('linked_professions', []))}, "
                f"routines: {len(item.get('linked_routines', []))})"
            )
        print()
        print(color(f"  Source: {get_goals_path()}", Colors.DIM))
        return

    if action == "use":
        if getattr(args, "clear", False):
            clear_active_goal()
            print(color("  Cleared active goal pin.", Colors.GREEN))
            return
        slug = getattr(args, "name", None)
        if not slug:
            current = get_active_goal_slug()
            if current:
                g = get_goal(current)
                label = (g or {}).get("title") or current
                print(color(f"  Active goal: {label} ({current})", Colors.GREEN))
            else:
                print(color("  No active goal pinned.", Colors.DIM))
                print(color("  Set one with: hermes goals use <slug>", Colors.DIM))
            return
        result = set_active_goal(slug)
        if not result.get("success"):
            print(color(f"  {result.get('error', 'use failed')}", Colors.YELLOW))
            return
        print(color(f"  Active goal: {result.get('title') or result.get('slug')}", Colors.GREEN))
        return

    if action == "show":
        item = get_goal(args.name)
        if not item:
            print(color(f"  Goal not found: {args.name}", Colors.YELLOW))
            return
        _print_goal(item)
        return

    if action == "add":
        result = create_goal(
            args.title,
            description=getattr(args, "description", "") or "",
            linked_professions=[getattr(args, "link_profession", None)] if getattr(args, "link_profession", None) else None,
            notes=getattr(args, "notes", "") or "",
        )
        if not result.get("success"):
            if result.get("existed"):
                print(color(f"  Goal already exists: {args.title}", Colors.YELLOW))
            else:
                print(color(f"  {result.get('error', 'add failed')}", Colors.YELLOW))
            return
        print(color(f"  Added goal: {result.get('title')} ({result.get('slug')})", Colors.GREEN))
        return

    if action == "update":
        fields = {}
        if getattr(args, "title", None):
            fields["title"] = args.title
        if getattr(args, "description", None) is not None:
            fields["description"] = args.description
        if getattr(args, "notes", None) is not None:
            fields["notes"] = args.notes
        if not fields:
            print(color("  Nothing to update. Pass --title, --description, or --notes.", Colors.YELLOW))
            return
        result = update_goal(args.slug, **fields)
        if not result.get("success"):
            print(color(f"  {result.get('error', 'update failed')}", Colors.YELLOW))
            return
        print(color(f"  Updated goal: {result.get('title') or result.get('slug')}", Colors.GREEN))
        return

    if action == "progress":
        result = add_progress(args.slug, args.note, source=getattr(args, "source", "") or "")
        if not result.get("success"):
            print(color(f"  {result.get('error', 'progress add failed')}", Colors.YELLOW))
            return
        print(color(f"  Progress recorded for {result.get('title') or result.get('slug')}.", Colors.GREEN))
        return

    if action == "done":
        result = set_status(args.slug, "done")
        if not result.get("success"):
            print(color(f"  {result.get('error', 'status update failed')}", Colors.YELLOW))
            return
        print(color(f"  Goal marked done: {result.get('title') or result.get('slug')}", Colors.GREEN))
        return

    if action == "pause":
        result = set_status(args.slug, "paused")
        if not result.get("success"):
            print(color(f"  {result.get('error', 'status update failed')}", Colors.YELLOW))
            return
        print(color(f"  Goal paused: {result.get('title') or result.get('slug')}", Colors.GREEN))
        return

    if action == "resume":
        result = set_status(args.slug, "active")
        if not result.get("success"):
            print(color(f"  {result.get('error', 'status update failed')}", Colors.YELLOW))
            return
        print(color(f"  Goal resumed: {result.get('title') or result.get('slug')}", Colors.GREEN))
        return

    if action == "link-profession":
        result = link_profession(args.slug, args.profession)
        if not result.get("success"):
            print(color(f"  {result.get('error', 'link failed')}", Colors.YELLOW))
            return
        print(color(f"  Linked profession '{args.profession}' to {result.get('slug')}.", Colors.GREEN))
        return

    if action == "unlink-profession":
        result = unlink_profession(args.slug, args.profession)
        if not result.get("success"):
            print(color(f"  {result.get('error', 'unlink failed')}", Colors.YELLOW))
            return
        print(color(f"  Unlinked profession '{args.profession}' from {result.get('slug')}.", Colors.GREEN))
        return

    if action == "link-routine":
        result = link_routine(args.slug, args.cron_id)
        if not result.get("success"):
            print(color(f"  {result.get('error', 'link failed')}", Colors.YELLOW))
            return
        print(color(f"  Linked routine '{args.cron_id}' to {result.get('slug')}.", Colors.GREEN))
        return

    if action == "unlink-routine":
        result = unlink_routine(args.slug, args.cron_id)
        if not result.get("success"):
            print(color(f"  {result.get('error', 'unlink failed')}", Colors.YELLOW))
            return
        print(color(f"  Unlinked routine '{args.cron_id}' from {result.get('slug')}.", Colors.GREEN))
        return

    if action == "delete":
        result = delete_goal(args.slug)
        if not result.get("success"):
            print(color(f"  {result.get('error', 'delete failed')}", Colors.YELLOW))
            return
        print(color(f"  Deleted goal: {result.get('slug')}", Colors.GREEN))
        return

    if action == "summary":
        text = summarize_active()
        if not text:
            print(color("  (no active goals)", Colors.DIM))
            return
        print(text)
        return

    if action == "path":
        print(str(get_goals_path()))
        return

    print("Usage: hermes goals [list|show|use|add|update|progress|done|pause|resume|link-profession|unlink-profession|link-routine|unlink-routine|delete|summary|path]")


def _epoch(iso_ts: str) -> float:
    """Best-effort parse of ``2026-04-23T10:15:00Z`` to a sortable float."""
    if not iso_ts:
        return 0.0
    try:
        from datetime import datetime
        return datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").timestamp()
    except Exception:
        return 0.0
