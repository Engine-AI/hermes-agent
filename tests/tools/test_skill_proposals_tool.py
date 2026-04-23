"""Tests for tools/skill_proposals_tool.py — create + dedupe + status moves."""

from tools.skill_proposals_tool import (
    create_proposal,
    create_split_proposal,
    dedupe_by_intent_similarity,
    list_proposals,
    load_proposal,
    mark_accepted,
    mark_fulfilled,
    mark_rejected,
    proposals_dir,
)


class TestCreate:
    def test_create_basic(self):
        result = create_proposal(
            intent="Pre-fill Schedule C from receipts",
            requesting_profession="accountant",
            examples=["fill Schedule C"],
        )
        assert result["success"] is True
        assert result["deduped"] is False
        proposal = load_proposal(result["slug"])
        assert proposal is not None
        assert proposal["kind"] == "skill"
        assert proposal["requesting_profession"] == "accountant"
        assert proposal["status"] == "open"

    def test_create_requires_intent(self):
        result = create_proposal(intent="", requesting_profession="x")
        assert result["success"] is False

    def test_list_open_returns_new(self):
        create_proposal(intent="unique intent alpha", requesting_profession="alpha")
        items = list_proposals(status="open")
        assert any(m.get("typical_intent", "").startswith("unique intent alpha") for m in items)


class TestDedupe:
    def test_dedupe_bumps_attempts(self):
        first = create_proposal(
            intent="Pre-fill Schedule C from receipts",
            requesting_profession="accountant",
        )
        second = create_proposal(
            intent="Pre-fill Schedule C from receipts",
            requesting_profession="accountant",
        )
        assert second["deduped"] is True
        assert second["slug"] == first["slug"]
        assert second["failed_attempts"] >= 2

    def test_dedupe_similarity(self):
        create_proposal(
            intent="Fetch the latest stock price for a ticker",
            requesting_profession="stocks",
        )
        match = dedupe_by_intent_similarity("fetch the latest stock price for ticker AAPL")
        assert match is not None  # SequenceMatcher above 0.75 for near-identical

    def test_dedupe_unrelated_does_not_match(self):
        create_proposal(
            intent="Generate a weekly running plan",
            requesting_profession="fitness",
        )
        assert dedupe_by_intent_similarity("file Schedule C with receipts") is None


class TestStatusMoves:
    def test_accept_moves_file(self):
        r = create_proposal(intent="move me please", requesting_profession="x")
        slug = r["slug"]
        accepted = mark_accepted(slug)
        assert accepted["success"] is True
        proposal = load_proposal(slug)
        assert proposal is not None
        assert proposal["status"] == "accepted"
        assert proposal["_status_from_path"] == "accepted"

    def test_reject_moves_file(self):
        r = create_proposal(intent="reject me", requesting_profession="x")
        mark_rejected(r["slug"])
        p = load_proposal(r["slug"])
        assert p["status"] == "rejected"
        assert p["_status_from_path"] == "rejected"

    def test_fulfill_moves_file(self):
        r = create_proposal(intent="fulfill me", requesting_profession="x")
        mark_fulfilled(r["slug"])
        p = load_proposal(r["slug"])
        assert p["status"] == "fulfilled"

    def test_missing_slug(self):
        assert mark_accepted("not-a-real-slug")["success"] is False


class TestSplitProposal:
    def test_split_proposal_created(self):
        out = create_split_proposal(
            {
                "source_slug": "generalist",
                "skill_count": 20,
                "suggested_splits": [
                    {"name": "content-creator", "skills": ["write-blog", "proofread"]},
                    {"name": "data-wrangler", "skills": ["csv-clean", "csv-merge"]},
                ],
            }
        )
        assert out["success"] is True
        proposal = load_proposal(out["slug"])
        assert proposal["kind"] == "split"
        assert proposal["source_slug"] == "generalist"

    def test_split_debounces_within_24h(self):
        create_split_proposal(
            {"source_slug": "debounce-src", "skill_count": 18, "suggested_splits": []}
        )
        again = create_split_proposal(
            {"source_slug": "debounce-src", "skill_count": 18, "suggested_splits": []}
        )
        assert again["success"] is False
        assert again.get("error") == "debounced"


class TestDirectory:
    def test_proposals_dir_exists(self):
        d = proposals_dir()
        assert d.exists()
        assert d.is_dir()
