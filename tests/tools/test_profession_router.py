"""Tests for agent/profession_router.py — decision parsing + fallback."""

from types import SimpleNamespace
from unittest.mock import patch

from agent.profession_router import (
    RoutingDecision,
    route,
    should_route,
    apply_decision,
)
from tools.professions_tool import (
    auto_create_profession,
    get_active_profession_slug,
)


def _fake_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class TestShouldRoute:
    def test_off_when_auto_route_disabled(self):
        # Fresh config has auto_route=False.
        assert should_route(1, "") is False
        assert should_route(5, "") is False

    def test_on_for_first_turn_when_enabled(self):
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        cfg.setdefault("professions", {})["auto_route"] = True
        save_config(cfg)
        assert should_route(1, "") is True

    def test_interval_check(self):
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        cfg.setdefault("professions", {})["auto_route"] = True
        cfg["professions"]["drift_check_interval"] = 3
        save_config(cfg)
        assert should_route(2, "") is False
        assert should_route(3, "") is True
        assert should_route(4, "") is False
        assert should_route(6, "") is True


class TestRouteParsing:
    def _enable_auto_route(self):
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        cfg.setdefault("professions", {})["auto_route"] = True
        save_config(cfg)

    def test_stay_on_explicit_response(self):
        self._enable_auto_route()
        with patch(
            "agent.auxiliary_client.call_llm",
            return_value=_fake_response('{"action":"stay","reason":"fine"}'),
        ):
            decision = route("anything")
        assert decision.action == "stay"

    def test_switch_validates_target(self):
        self._enable_auto_route()
        auto_create_profession("Accountant", problem_domains=["tax"])
        payload = '{"action":"switch","target_slug":"accountant","reason":"fits"}'
        with patch(
            "agent.auxiliary_client.call_llm",
            return_value=_fake_response(payload),
        ):
            decision = route("help me file taxes")
        assert decision.action == "switch"
        assert decision.target_slug == "accountant"

    def test_switch_unknown_target_falls_back_to_stay(self):
        self._enable_auto_route()
        payload = '{"action":"switch","target_slug":"does-not-exist"}'
        with patch(
            "agent.auxiliary_client.call_llm",
            return_value=_fake_response(payload),
        ):
            decision = route("help")
        assert decision.action == "stay"

    def test_create_requires_name(self):
        self._enable_auto_route()
        with patch(
            "agent.auxiliary_client.call_llm",
            return_value=_fake_response('{"action":"create","new_profession":{}}'),
        ):
            decision = route("help")
        assert decision.action == "stay"

    def test_create_with_full_payload(self):
        self._enable_auto_route()
        payload = (
            '{"action":"create",'
            '"new_profession":{"name":"Gardener","problem_domains":["plants"],'
            '"suggested_skills":["prune"]},'
            '"reason":"novel topic"}'
        )
        with patch(
            "agent.auxiliary_client.call_llm",
            return_value=_fake_response(payload),
        ):
            decision = route("how do I prune a tomato plant")
        assert decision.action == "create"
        assert decision.new_profession["name"] == "Gardener"
        assert decision.new_profession["problem_domains"] == ["plants"]

    def test_llm_failure_falls_back_to_stay(self):
        self._enable_auto_route()
        with patch(
            "agent.auxiliary_client.call_llm",
            side_effect=RuntimeError("provider down"),
        ):
            decision = route("something")
        assert decision.action == "stay"
        assert "router error" in decision.reason

    def test_empty_query_is_stay(self):
        assert route("").action == "stay"
        assert route("   ").action == "stay"


class TestApplyDecision:
    def test_stay_is_noop(self):
        result = apply_decision(RoutingDecision.stay())
        assert result["changed"] is False

    def test_switch_sets_active(self):
        auto_create_profession("Writer", problem_domains=["writing"])
        result = apply_decision(
            RoutingDecision(action="switch", target_slug="writer")
        )
        assert result["changed"] is True
        assert get_active_profession_slug() == "writer"

    def test_create_then_set_active(self):
        decision = RoutingDecision(
            action="create",
            new_profession={
                "name": "Music Producer",
                "problem_domains": ["mixing"],
                "suggested_skills": [],
            },
        )
        result = apply_decision(decision)
        assert result["changed"] is True
        assert result.get("created") is True
        assert get_active_profession_slug() == "music-producer"

    def test_create_falls_back_to_switch_if_exists(self):
        auto_create_profession("Chef", problem_domains=["cooking"])
        decision = RoutingDecision(
            action="create",
            new_profession={
                "name": "Chef",
                "problem_domains": ["baking"],
                "suggested_skills": [],
            },
        )
        result = apply_decision(decision)
        # Profession already exists → auto_create returns existed=True, then
        # apply_decision switches to it.
        assert result["changed"] is True
        assert result.get("created") is False
        assert get_active_profession_slug() == "chef"
