"""Tests for agent/prompt_builder.py — two-layer skill index filtering."""

from pathlib import Path

from hermes_constants import get_hermes_home
from hermes_cli.config import load_config, save_config
from tools.professions_tool import auto_create_profession, set_active_profession
from agent.prompt_builder import build_skills_system_prompt


def _write_skill(name: str, description: str, category: str = "misc") -> Path:
    skill_dir = get_hermes_home() / "skills" / category / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n",
        encoding="utf-8",
    )
    return skill_dir


def _reset_cache():
    from agent.prompt_builder import _SKILLS_PROMPT_CACHE, _SKILLS_PROMPT_CACHE_LOCK

    with _SKILLS_PROMPT_CACHE_LOCK:
        _SKILLS_PROMPT_CACHE.clear()


class TestTwoLayerSkillIndex:
    def test_legacy_behavior_when_auto_route_off(self):
        _write_skill("tax-filing", "File taxes accurately", category="finance")
        _write_skill("prune-tree", "Prune fruit trees", category="gardening")
        auto_create_profession(
            "Accountant", problem_domains=["tax"], suggested_skills=["tax-filing"]
        )
        set_active_profession("accountant")
        _reset_cache()

        prompt = build_skills_system_prompt(available_tools={"skill_view"})
        # Full descriptions for both — no two-layer split.
        assert "tax-filing: File taxes accurately" in prompt
        assert "prune-tree: Prune fruit trees" in prompt
        assert "<other_skills_index>" not in prompt

    def test_two_layer_split_when_auto_route_on(self):
        _write_skill("tax-filing", "File taxes accurately", category="finance")
        _write_skill("prune-tree", "Prune fruit trees", category="gardening")
        auto_create_profession(
            "Accountant", problem_domains=["tax"], suggested_skills=["tax-filing"]
        )
        set_active_profession("accountant")

        cfg = load_config()
        cfg.setdefault("professions", {})["auto_route"] = True
        save_config(cfg)
        _reset_cache()

        prompt = build_skills_system_prompt(available_tools={"skill_view"})
        # Profession skill still has full description.
        assert "tax-filing: File taxes accurately" in prompt
        # Non-profession skill appears by name only in the other-skills block.
        assert "<other_skills_index>" in prompt
        assert "prune-tree" in prompt
        assert "Prune fruit trees" not in prompt

    def test_cache_key_segregates_profession(self):
        _write_skill("tax-filing", "File taxes accurately", category="finance")
        auto_create_profession(
            "Accountant", problem_domains=["tax"], suggested_skills=["tax-filing"]
        )
        auto_create_profession(
            "Writer", problem_domains=["writing"], suggested_skills=[]
        )

        cfg = load_config()
        cfg.setdefault("professions", {})["auto_route"] = True
        save_config(cfg)

        set_active_profession("accountant")
        _reset_cache()
        prompt_a = build_skills_system_prompt(available_tools={"skill_view"})
        set_active_profession("writer")
        prompt_b = build_skills_system_prompt(available_tools={"skill_view"})
        # Two different professions must produce two different prompts
        # (regression for the missing cache-key slug).
        assert prompt_a != prompt_b
