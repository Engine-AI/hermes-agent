"""Tests for agent/profession_router.py extensions:
fast-path, borrow, skill_gap, bloat guard, brain budget."""

from types import SimpleNamespace
from unittest.mock import patch

from agent.profession_router import (
    RoutingDecision,
    _keyword_fast_match,
    apply_decision,
    record_turn_for_gap_detection,
    reset_brain_budget,
    route,
)
from tools.professions_tool import (
    auto_create_profession,
    bind_skill_to_profession,
    set_active_profession,
)


def _fake_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _enable_auto_route():
    from hermes_cli.config import load_config, save_config

    cfg = load_config()
    cfg.setdefault("professions", {})["auto_route"] = True
    save_config(cfg)


class TestKeywordFastPath:
    def test_returns_stay_without_calling_llm(self):
        _enable_auto_route()
        auto_create_profession("Stocks", problem_domains=["stock quote", "earnings"])
        set_active_profession("stocks")

        call_count = {"n": 0}

        def _fake_llm(**kw):
            call_count["n"] += 1
            return _fake_response('{"action":"switch","target_slug":"x"}')

        with patch("agent.auxiliary_client.call_llm", side_effect=_fake_llm):
            decision = route("show me the latest stock quote for AAPL earnings")
        assert decision.action == "stay"
        assert decision.reason == "keyword fast-path"
        assert call_count["n"] == 0

    def test_unit_keyword_match(self):
        active = {
            "problem_domains": ["tax filing", "bookkeeping"],
            "skills": ["reconcile"],
        }
        assert _keyword_fast_match("help me with tax filing and bookkeeping", active) is True
        assert _keyword_fast_match("what's the weather today?", active) is False
        # Single hit below threshold
        assert _keyword_fast_match("just tax stuff", active) is False


class TestBorrowAction:
    def test_borrow_parsed_and_capped(self):
        _enable_auto_route()
        auto_create_profession("Primary", problem_domains=["primary"])
        auto_create_profession("Helper", problem_domains=["helper"])
        set_active_profession("primary")

        payload = (
            '{"action":"borrow","target_slug":"primary",'
            '"borrow_from":["helper"],"borrow_skills":["a","b"],'
            '"reason":"need 2 skills"}'
        )
        with patch(
            "agent.auxiliary_client.call_llm",
            return_value=_fake_response(payload),
        ):
            decision = route("some primary task needing helper's skills")
        assert decision.action == "borrow"
        assert decision.target_slug == "primary"
        assert decision.borrow_from == ["helper"]
        assert decision.borrow_skills == ["a", "b"]

    def test_borrow_oversized_downgrades(self):
        _enable_auto_route()
        auto_create_profession("P", problem_domains=["p"])
        auto_create_profession("H", problem_domains=["h"])
        set_active_profession("p")

        payload = (
            '{"action":"borrow","target_slug":"p","borrow_from":["h"],'
            '"borrow_skills":["a","b","c","d","e"],"reason":"too many"}'
        )
        with patch(
            "agent.auxiliary_client.call_llm",
            return_value=_fake_response(payload),
        ):
            decision = route("query that shouldn't match keyword fast-path")
        assert decision.action == "stay"
        assert "downgrade" in (decision.reason or "").lower()

    def test_borrow_without_valid_target_falls_back(self):
        _enable_auto_route()
        auto_create_profession("Alpha", problem_domains=["a"])
        set_active_profession("alpha")
        payload = (
            '{"action":"borrow","target_slug":"nonexistent","borrow_from":["alpha"],'
            '"borrow_skills":["s"]}'
        )
        with patch(
            "agent.auxiliary_client.call_llm",
            return_value=_fake_response(payload),
        ):
            decision = route("something")
        assert decision.action == "stay"


class TestSkillGapEmission:
    def test_apply_decision_creates_proposal(self):
        _enable_auto_route()
        auto_create_profession("Accountant", problem_domains=["tax"])
        set_active_profession("accountant")

        decision = RoutingDecision(
            action="stay",
            skill_gap={"intent": "Fill Schedule C from receipts CSV", "confidence": 0.9},
        )
        apply_decision(decision)

        from tools.skill_proposals_tool import list_proposals

        open_items = list_proposals(status="open")
        assert any(
            "Schedule C" in (m.get("typical_intent") or "") for m in open_items
        )


class TestRetryGapDetection:
    def test_retry_triggers_gap(self):
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        cfg.setdefault("brain", {})["retry_gap_threshold"] = 3
        save_config(cfg)

        reset_brain_budget("sess-retry")
        # First two: no gap yet.
        assert record_turn_for_gap_detection("slug-x", "same repeated intent") is None
        assert record_turn_for_gap_detection("slug-x", "same repeated intent") is None
        # Third fires.
        out = record_turn_for_gap_detection("slug-x", "same repeated intent")
        assert out is not None
        assert out.get("intent")
        assert out.get("source") == "retry_heuristic"


class TestBloatGuard:
    def test_bloat_emits_split_proposal(self):
        _enable_auto_route()
        # Override soft cap low so we don't need 15 skills.
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        cfg.setdefault("brain", {})["bloat_soft_cap"] = 2
        save_config(cfg)

        auto_create_profession("Bloaty", problem_domains=["x"])
        set_active_profession("bloaty")
        # Fake three skills bound directly to the entry.
        from tools.professions_tool import list_professions, _save_entries

        entries = list_professions()
        for e in entries:
            if e["slug"] == "bloaty":
                e["skills"] = ["s1", "s2", "s3"]
        _save_entries(entries)

        apply_decision(RoutingDecision(action="stay"))

        from tools.skill_proposals_tool import list_proposals

        open_items = list_proposals(status="open")
        assert any(
            m.get("kind") == "split" and m.get("source_slug") == "bloaty" for m in open_items
        )


class TestBrainBudget:
    def test_budget_exhausts(self):
        _enable_auto_route()
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        cfg.setdefault("brain", {})["budget_per_session"] = 2
        save_config(cfg)

        auto_create_profession("Budgeted", problem_domains=["unique-budget-domain"])
        set_active_profession("budgeted")
        reset_brain_budget("sess-budget")

        call_count = {"n": 0}

        def _fake_llm(**kw):
            call_count["n"] += 1
            return _fake_response('{"action":"stay","reason":"fine"}')

        with patch("agent.auxiliary_client.call_llm", side_effect=_fake_llm):
            for _ in range(4):
                route("some totally off-topic xyzzy request", session_id="sess-budget")
        # With budget=2, we must not exceed 2 LLM calls.
        assert call_count["n"] <= 2
