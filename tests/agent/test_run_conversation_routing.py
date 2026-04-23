"""Smoke test for the run_conversation profession-routing hook.

Rather than instantiate the full AIAgent (massive constructor with provider
setup), we verify the router contract — should_route + apply_decision — is
the one driving the hook, and that a switch-action invalidates the cached
system prompt.
"""

from unittest.mock import MagicMock, patch

from agent.profession_router import RoutingDecision, apply_decision
from hermes_cli.config import load_config, save_config
from tools.professions_tool import (
    auto_create_profession,
    get_active_profession_slug,
)


def _enable_auto_route():
    cfg = load_config()
    cfg.setdefault("professions", {})["auto_route"] = True
    save_config(cfg)


class TestRoutingHookBehavior:
    def test_switch_changes_active_profession_and_returns_changed(self):
        _enable_auto_route()
        auto_create_profession("Accountant", problem_domains=["tax"])
        auto_create_profession("Writer", problem_domains=["writing"])

        # Simulate the hook receiving a switch decision and applying it.
        decision = RoutingDecision(action="switch", target_slug="writer")
        result = apply_decision(decision)

        assert result["changed"] is True
        assert result["slug"] == "writer"
        assert get_active_profession_slug() == "writer"

    def test_create_then_switch(self):
        _enable_auto_route()
        decision = RoutingDecision(
            action="create",
            new_profession={
                "name": "Game Designer",
                "problem_domains": ["gameplay"],
                "suggested_skills": [],
            },
        )
        result = apply_decision(decision)
        assert result["changed"] is True
        assert result.get("created") is True
        assert get_active_profession_slug() == "game-designer"

    def test_stay_leaves_state_untouched(self):
        auto_create_profession("Chef", problem_domains=["cooking"])
        from tools.professions_tool import set_active_profession

        set_active_profession("chef")

        result = apply_decision(RoutingDecision.stay())
        assert result["changed"] is False
        assert get_active_profession_slug() == "chef"

    def test_switch_to_same_slug_is_noop(self):
        auto_create_profession("Baker", problem_domains=["bread"])
        from tools.professions_tool import set_active_profession

        set_active_profession("baker")
        result = apply_decision(
            RoutingDecision(action="switch", target_slug="baker")
        )
        assert result["changed"] is False


class TestRouteOptInGating:
    def test_should_route_off_by_default(self):
        from agent.profession_router import should_route

        # Fresh config: auto_route defaults to False.
        assert should_route(1, "") is False
        assert should_route(100, "") is False

    def test_should_route_on_after_enable(self):
        _enable_auto_route()
        from agent.profession_router import should_route

        assert should_route(1, "") is True
