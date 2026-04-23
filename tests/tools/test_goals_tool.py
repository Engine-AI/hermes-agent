"""Tests for tools/goals_tool.py — GOALS.md CRUD + summarize."""

import os

from hermes_cli.config import load_config, save_config
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
    slugify_goal,
    summarize_active,
    unlink_profession,
    unlink_routine,
    update_goal,
)


class TestCRUD:
    def test_slugify(self):
        assert slugify_goal("Learn Rust via side projects") == "learn-rust-via-side-projects"
        assert slugify_goal("  ") == "goal"
        assert slugify_goal("foo!!bar__baz") == "foo-bar-baz"

    def test_create_and_get(self):
        result = create_goal("Finish thesis", description="Chapter by chapter")
        assert result["success"] is True
        assert result["slug"] == "finish-thesis"

        fetched = get_goal("finish-thesis")
        assert fetched is not None
        assert fetched["title"] == "Finish thesis"
        assert fetched["status"] == "active"
        assert fetched["created_at"]

    def test_create_duplicate_rejected(self):
        create_goal("One")
        again = create_goal("One")
        assert again["success"] is False
        assert again.get("existed") is True

    def test_list_and_file_exists(self):
        create_goal("Foo")
        create_goal("Bar")
        goals = list_goals()
        assert {g["slug"] for g in goals} >= {"foo", "bar"}
        assert get_goals_path().exists()

    def test_update_fields(self):
        create_goal("Goal A")
        out = update_goal("goal-a", description="updated desc", notes="a note")
        assert out["success"] is True
        g = get_goal("goal-a")
        assert g["description"] == "updated desc"
        assert g["notes"] == "a note"

    def test_update_touches_timestamps(self):
        create_goal("Stable")
        before = get_goal("stable")["updated_at"]
        out = update_goal("stable", notes="something new")
        assert out["success"] is True
        g = get_goal("stable")
        assert g["slug"] == "stable"
        # updated_at should have been refreshed
        assert g["updated_at"] >= before

    def test_status_transitions(self):
        create_goal("Transition")
        assert set_status("transition", "paused")["success"] is True
        assert get_goal("transition")["status"] == "paused"
        assert set_status("transition", "done")["success"] is True
        assert get_goal("transition")["status"] == "done"
        assert set_status("transition", "garbage")["success"] is False

    def test_delete(self):
        create_goal("Removable")
        assert delete_goal("removable")["success"] is True
        assert get_goal("removable") is None
        assert delete_goal("removable")["success"] is False


class TestLinks:
    def test_link_profession_dedupe(self):
        create_goal("Linked")
        link_profession("linked", "accountant")
        link_profession("linked", "accountant")  # dedupe
        g = get_goal("linked")
        assert g["linked_professions"] == ["accountant"]

        link_profession("linked", "fitness")
        g = get_goal("linked")
        assert sorted(g["linked_professions"]) == ["accountant", "fitness"]

    def test_unlink_profession(self):
        create_goal("Unlink")
        link_profession("unlink", "a")
        assert unlink_profession("unlink", "a")["success"] is True
        assert get_goal("unlink")["linked_professions"] == []
        # Unlinking absent profession fails cleanly.
        assert unlink_profession("unlink", "a")["success"] is False

    def test_link_routine(self):
        create_goal("Routine goal")
        link_routine("routine-goal", "cron-abc")
        link_routine("routine-goal", "cron-def")
        g = get_goal("routine-goal")
        assert sorted(g["linked_routines"]) == ["cron-abc", "cron-def"]
        assert unlink_routine("routine-goal", "cron-abc")["success"] is True
        assert get_goal("routine-goal")["linked_routines"] == ["cron-def"]


class TestProgress:
    def test_add_progress_caps_window(self):
        create_goal("Progress goal")
        for i in range(10):
            add_progress("progress-goal", f"entry-{i}")
        g = get_goal("progress-goal")
        # RECENT_PROGRESS_LIMIT is 5
        assert len(g["recent_progress"]) <= 5
        # newest-first
        assert g["recent_progress"][0].startswith("entry-9")

    def test_progress_source_prefix(self):
        create_goal("Sourced")
        add_progress("sourced", "did the thing", source="accountant")
        g = get_goal("sourced")
        assert any("[accountant]" in p for p in g["recent_progress"])


class TestSummarizeActive:
    def _enable(self):
        cfg = load_config()
        cfg.setdefault("goals", {})
        cfg["goals"]["enabled"] = True
        cfg["goals"]["max_active_goals"] = 3
        cfg["goals"]["max_summary_chars"] = 300
        save_config(cfg)

    def test_empty_when_no_goals(self):
        self._enable()
        assert summarize_active() == ""

    def test_disabled_returns_empty(self):
        cfg = load_config()
        cfg.setdefault("goals", {})["enabled"] = False
        save_config(cfg)
        create_goal("Present")
        assert summarize_active() == ""

    def test_excludes_done_and_paused(self):
        self._enable()
        create_goal("Active one")
        create_goal("Finished")
        set_status("finished", "done")
        create_goal("On hold")
        set_status("on-hold", "paused")
        text = summarize_active()
        assert "Active one" in text
        assert "Finished" not in text
        assert "On hold" not in text

    def test_respects_max_chars(self):
        self._enable()
        long_desc = "x" * 2000
        create_goal("Long goal", description=long_desc)
        text = summarize_active()
        # Hard cap is 300 in this test's config.
        assert len(text) <= 300

    def test_caps_goal_count(self):
        self._enable()
        for i in range(8):
            create_goal(f"Goal number {i}")
        text = summarize_active(max_goals=3)
        # At most 3 goals rendered.
        assert text.count("\n- ") <= 2  # leading "- " + 2 more


class TestActiveGoalPin:
    def _clear_pin(self):
        os.environ.pop("HERMES_SESSION_GOAL", None)
        clear_active_goal()

    def test_persistent_pin(self):
        self._clear_pin()
        create_goal("Pinned one", description="a")
        create_goal("Other one", description="b")
        result = set_active_goal("pinned-one")
        assert result["success"] is True
        assert get_active_goal_slug() == "pinned-one"

    def test_pin_rejects_paused(self):
        self._clear_pin()
        create_goal("Sleepy")
        set_status("sleepy", "paused")
        result = set_active_goal("sleepy")
        assert result["success"] is False

    def test_pin_rejects_missing(self):
        self._clear_pin()
        result = set_active_goal("does-not-exist")
        assert result["success"] is False

    def test_env_overrides_config(self):
        self._clear_pin()
        create_goal("Config pin")
        create_goal("Env pin")
        set_active_goal("config-pin")
        os.environ["HERMES_SESSION_GOAL"] = "env-pin"
        try:
            assert get_active_goal_slug() == "env-pin"
        finally:
            os.environ.pop("HERMES_SESSION_GOAL", None)
        # When env is cleared, fall back to config.
        assert get_active_goal_slug() == "config-pin"

    def test_clear_active_goal(self):
        self._clear_pin()
        create_goal("Ephemeral")
        set_active_goal("ephemeral")
        assert get_active_goal_slug() == "ephemeral"
        clear_active_goal()
        assert get_active_goal_slug() == ""


class TestSummarizeWithPin:
    def _setup(self):
        cfg = load_config()
        cfg.setdefault("goals", {})["enabled"] = True
        cfg["goals"]["max_active_goals"] = 3
        cfg["goals"]["max_summary_chars"] = 2000
        cfg["goals"]["active"] = ""
        save_config(cfg)
        os.environ.pop("HERMES_SESSION_GOAL", None)

    def test_pin_appears_first_with_full_detail(self):
        self._setup()
        create_goal("Alpha goal", description="alpha description")
        create_goal("Beta goal", description="beta description")
        create_goal("Gamma goal", description="gamma description")
        set_active_goal("beta-goal")
        text = summarize_active()
        # Pinned goal leads with ★ marker and focus label
        first_block = text.split("\n\n")[0] if "\n\n" in text else text.splitlines()[0]
        assert text.startswith("★")
        assert "focus for this conversation" in text.splitlines()[0]
        # Non-pinned goals appear as terse one-liners below
        assert "beta description" in text
        # Non-pinned should not include full descriptions (terse = no 'desc:' line for them)
        lines = text.splitlines()
        terse_lines = [l for l in lines if l.startswith("- ")]
        assert len(terse_lines) >= 2
        # Terse lines are single-line entries only (no 'desc:'/'recent:' follow-ups).
        for l in terse_lines:
            # They should be simple "- Title" maybe with "(linked: X)"
            assert "desc:" not in l
            assert "recent:" not in l

    def test_no_pin_renders_everyone_full(self):
        self._setup()
        create_goal("One", description="desc one")
        create_goal("Two", description="desc two")
        text = summarize_active()
        assert "★" not in text
        assert "focus for this conversation" not in text
        assert "desc one" in text
        assert "desc two" in text
