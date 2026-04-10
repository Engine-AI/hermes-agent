"""CLI helpers for PROFESSIONS.md."""

from __future__ import annotations

from hermes_cli.colors import Colors, color
from tools.professions_tool import (
    bind_skill_to_profession,
    feedback_profession,
    get_active_profession_slug,
    get_profession,
    get_professions_path,
    list_professions,
    rate_profession,
    rebuild_professions_from_skills,
    set_active_profession,
    solve_profession,
    unbind_skill_from_profession,
)


def professions_command(args) -> None:
    action = getattr(args, "professions_action", None)

    if action == "list":
        professions = list_professions()
        if not professions:
            print(color("  No professions defined.", Colors.DIM))
            print(color("  Run 'hermes professions rebuild' after installing or creating skills.", Colors.DIM))
            return
        ranked = sorted(
            professions,
            key=lambda item: (
                float(item.get("score", 0.0)),
                float(item.get("rating", 0.0)),
                int(item.get("solved_count", 0)),
            ),
            reverse=True,
        )
        print()
        print(color("  Profession Leaderboard", Colors.BOLD))
        for idx, item in enumerate(ranked, 1):
            active = " *" if item.get("slug") == get_active_profession_slug() else ""
            print(
                f"  {idx}. {item.get('profession') or item.get('slug')}{active}  "
                f"(score {item.get('score', 0.0):.2f}, rating {item.get('rating', 0.0):.1f}, solved {item.get('solved_count', 0)}, "
                f"skills {len(item.get('skills', []))})"
            )
        print()
        print(color(f"  Source: {get_professions_path()}", Colors.DIM))
        return

    if action == "show":
        item = get_profession(args.name)
        if not item:
            print(color(f"  Profession not found: {args.name}", Colors.YELLOW))
            return
        print()
        print(color(f"  {item.get('profession') or item.get('slug')}", Colors.BOLD))
        print(f"  Slug: {item.get('slug', '')}")
        print(f"  Skills: {', '.join(item.get('skills', [])) or '(none)'}")
        print(f"  Problem Domains: {', '.join(item.get('problem_domains', [])) or '(none)'}")
        print(f"  Solved Count: {item.get('solved_count', 0)}")
        print(f"  Users Helped: {item.get('users_helped', 0)}")
        print(f"  Rating: {item.get('rating', 0.0):.1f}")
        print(f"  Score: {item.get('score', 0.0):.2f}")
        print(f"  Review Count: {item.get('review_count', 0)}")
        print(f"  Positive Feedback: {item.get('positive_feedback_count', 0)}")
        print(f"  Negative Feedback: {item.get('negative_feedback_count', 0)}")
        print(f"  Feedback Summary: {item.get('feedback_summary') or '(none)'}")
        print(f"  Recent Solutions: {' | '.join(item.get('recent_solutions', [])) or '(none)'}")
        print(f"  Recent Users: {', '.join(item.get('recent_users', [])) or '(none)'}")
        print(f"  Recent Cases: {' | '.join(item.get('recent_cases', [])) or '(none)'}")
        print(f"  Optimization Notes: {item.get('optimization_notes') or '(none)'}")
        print(f"  Description: {item.get('description') or '(none)'}")
        return

    if action == "use":
        result = set_active_profession(args.name)
        if not result["success"]:
            print(color(f"  {result['error']}", Colors.YELLOW))
            return
        print(color(f"  Active profession: {result['profession']} ({result['active']})", Colors.GREEN))
        return

    if action == "rate":
        result = rate_profession(args.name, args.stars, getattr(args, "review", ""))
        if not result["success"]:
            print(color(f"  {result['error']}", Colors.YELLOW))
            return
        print(
            color(
                f"  Rated {result['profession']}: {result['rating']:.1f} "
                f"({result['review_count']} reviews)",
                Colors.GREEN,
            )
        )
        return

    if action == "feedback":
        result = feedback_profession(args.name, args.sentiment, args.text)
        if not result["success"]:
            print(color(f"  {result['error']}", Colors.YELLOW))
            return
        print(color(f"  Recorded {result['sentiment']} feedback for {result['profession']}.", Colors.GREEN))
        return

    if action == "solve":
        result = solve_profession(
            args.name,
            args.problem,
            user=getattr(args, "user", ""),
            summary=getattr(args, "summary", ""),
            increment_user=not getattr(args, "no_user_count", False),
        )
        if not result["success"]:
            print(color(f"  {result['error']}", Colors.YELLOW))
            return
        print(
            color(
                f"  Recorded solved problem for {result['profession']} "
                f"(solved {result['solved_count']}, users {result['users_helped']}).",
                Colors.GREEN,
            )
        )
        return

    if action == "bind":
        result = bind_skill_to_profession(args.name, args.skill)
        if not result["success"]:
            print(color(f"  {result['error']}", Colors.YELLOW))
            return
        status = "created" if result.get("created") else "updated"
        print(
            color(
                f"  Profession {status}: {result['profession']} "
                f"(skills: {', '.join(result.get('skills', [])) or '(none)'})",
                Colors.GREEN,
            )
        )
        return

    if action == "unbind":
        result = unbind_skill_from_profession(args.name, args.skill)
        if not result["success"]:
            print(color(f"  {result['error']}", Colors.YELLOW))
            return
        print(
            color(
                f"  Unbound skill from {result['profession']} "
                f"(skills: {', '.join(result.get('skills', [])) or '(none)'})",
                Colors.GREEN,
            )
        )
        return

    if action == "rebuild":
        bound = rebuild_professions_from_skills()
        print()
        print(color("  Rebuilt PROFESSIONS.md from installed skills.", Colors.GREEN))
        print(f"  Professions: {len(bound)}")
        print(f"  File: {get_professions_path()}")
        return

    if action == "path":
        print(str(get_professions_path()))
        return

    print("Usage: hermes professions [list|show|use|rate|feedback|solve|bind|unbind|rebuild|path]")
