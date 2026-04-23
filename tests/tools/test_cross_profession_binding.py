"""Tests for tools/professions_tool.py — check_cross_profession_binding."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_constants import get_hermes_home
from tools.professions_tool import (
    auto_create_profession,
    check_cross_profession_binding,
    get_profession,
)


def _fake_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _make_skill(skill_name: str, description: str) -> Path:
    skills_dir = get_hermes_home() / "skills" / skill_name
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skills_dir / "SKILL.md"
    skill_md.write_text(
        f"---\nname: {skill_name}\ndescription: {description}\n---\n# {skill_name}\n",
        encoding="utf-8",
    )
    return skills_dir


class TestCheckCrossProfessionBinding:
    def _seed(self):
        auto_create_profession("Writer", problem_domains=["writing", "editing"])
        auto_create_profession("Researcher", problem_domains=["research", "citations"])
        auto_create_profession("Coder", problem_domains=["programming"])

    def test_returns_empty_when_no_professions(self):
        skill = _make_skill("orphan-skill", "standalone")
        result = check_cross_profession_binding(skill)
        assert result == []

    def test_adds_suggested_bindings(self):
        self._seed()
        skill = _make_skill("annotate-bibliography", "cite sources and annotate")
        with patch(
            "agent.auxiliary_client.call_llm",
            return_value=_fake_response('{"slugs":["writer","researcher"]}'),
        ):
            result = check_cross_profession_binding(skill)
        assert set(result) == {"writer", "researcher"}

        writer = get_profession("writer")
        researcher = get_profession("researcher")
        assert "annotate-bibliography" in writer["skills"]
        assert "annotate-bibliography" in researcher["skills"]

    def test_ignores_invalid_slugs(self):
        self._seed()
        skill = _make_skill("random-skill", "desc")
        with patch(
            "agent.auxiliary_client.call_llm",
            return_value=_fake_response('{"slugs":["nonsense-slug","writer"]}'),
        ):
            result = check_cross_profession_binding(skill)
        assert result == ["writer"]

    def test_caps_at_max_bindings(self):
        # Create 5 professions; cap should be 3.
        for name in ["A", "B", "C", "D", "E"]:
            auto_create_profession(name, problem_domains=[f"dom-{name.lower()}"])
        skill = _make_skill("multi-bind", "matches everything")
        with patch(
            "agent.auxiliary_client.call_llm",
            return_value=_fake_response('{"slugs":["a","b","c","d","e"]}'),
        ):
            result = check_cross_profession_binding(skill)
        assert len(result) == 3

    def test_llm_failure_is_silent(self):
        self._seed()
        skill = _make_skill("safe-fail", "desc")
        with patch(
            "agent.auxiliary_client.call_llm",
            side_effect=RuntimeError("no provider"),
        ):
            result = check_cross_profession_binding(skill)
        assert result == []
