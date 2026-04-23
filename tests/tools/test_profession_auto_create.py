"""Tests for tools/professions_tool.py — auto_create_profession."""

from tools.professions_tool import (
    auto_create_profession,
    get_profession,
    list_professions,
    slugify_profession,
)


class TestAutoCreateProfession:
    def test_creates_new_entry(self):
        result = auto_create_profession(
            "Tax Accountant",
            problem_domains=["tax filing", "bookkeeping"],
            suggested_skills=["tax-filing"],
            description="Helps with tax workflows.",
        )
        assert result["success"] is True
        assert result["slug"] == slugify_profession("Tax Accountant")
        assert result["created"] is True
        assert "tax filing" in result["problem_domains"]

        fetched = get_profession(result["slug"])
        assert fetched is not None
        assert fetched["profession"] == "Tax Accountant"
        assert "tax-filing" in fetched["skills"]

    def test_empty_name_rejected(self):
        assert auto_create_profession("")["success"] is False
        assert auto_create_profession("   ")["success"] is False

    def test_duplicate_rejected_with_existed_flag(self):
        auto_create_profession("Writer", problem_domains=["writing"])
        second = auto_create_profession("writer", problem_domains=["editing"])
        assert second["success"] is False
        assert second.get("existed") is True
        # Existing metrics / domains are NOT overwritten.
        entry = get_profession("writer")
        assert "writing" in entry["problem_domains"]
        assert "editing" not in entry["problem_domains"]

    def test_list_shows_newly_created(self):
        auto_create_profession("Dev Ops", problem_domains=["ci/cd"])
        slugs = [p["slug"] for p in list_professions()]
        assert "dev-ops" in slugs

    def test_default_description_when_omitted(self):
        result = auto_create_profession("Researcher")
        entry = get_profession(result["slug"])
        assert entry["description"]
        assert "researcher" in entry["description"].lower()
