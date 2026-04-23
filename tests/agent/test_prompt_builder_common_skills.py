"""Tests for common-skills + borrowed-skills rendering in prompt_builder."""

from pathlib import Path
from unittest.mock import patch

from agent import prompt_builder
from agent.prompt_builder import (
    _display_category,
    _is_common_category,
    build_skills_system_prompt,
    clear_skills_system_prompt_cache,
)


def _write_skill(base: Path, category: str, name: str, desc: str = "") -> None:
    skill_dir = base / category / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = "---\n" f"name: {name}\n" f"description: {desc or name}\n" "---\n"
    (skill_dir / "SKILL.md").write_text(frontmatter + f"\n# {name}\n", encoding="utf-8")


def _enable_auto_route():
    from hermes_cli.config import load_config, save_config

    cfg = load_config()
    cfg.setdefault("professions", {})["auto_route"] = True
    save_config(cfg)


def _set_active_profession(slug: str, skills: list):
    from tools.professions_tool import (
        _save_entries,
        auto_create_profession,
        list_professions,
        set_active_profession,
    )

    auto_create_profession(slug.replace("-", " ").title(), problem_domains=[slug])
    entries = list_professions()
    for e in entries:
        if e["slug"] == slug:
            e["skills"] = skills
    _save_entries(entries)
    set_active_profession(slug)


class TestCategoryHelpers:
    def test_is_common(self):
        assert _is_common_category("_common") is True
        assert _is_common_category("_common/foo") is True
        assert _is_common_category("general") is False
        assert _is_common_category("") is False

    def test_display_category(self):
        assert _display_category("_common") == "common"
        assert _display_category("_common/io") == "common/io"
        assert _display_category("finance") == "finance"


class TestCommonSkillsRendering:
    def test_common_skills_always_visible(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        _write_skill(skills_dir, "_common", "alpha", desc="alpha desc")
        _write_skill(skills_dir, "software-development", "beta", desc="beta desc")

        monkeypatch.setattr(prompt_builder, "get_skills_dir", lambda: skills_dir)
        monkeypatch.setattr(prompt_builder, "get_all_skills_dirs", lambda: [skills_dir])
        clear_skills_system_prompt_cache(clear_snapshot=True)

        _enable_auto_route()
        _set_active_profession("software-development", ["beta"])

        result = build_skills_system_prompt()

        # Common block appears with alpha
        assert "<common_skills>" in result
        assert "alpha" in result
        # Active profession block contains beta
        assert "beta" in result
        # alpha should not be demoted to the compact index
        # (other_skills_index never lists it since it's in _common).
        other_part = result.split("<other_skills_index>")[-1] if "<other_skills_index>" in result else ""
        assert "alpha" not in other_part


class TestBorrowedSkills:
    def test_borrowed_section_rendered(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        _write_skill(skills_dir, "primary", "p_skill", desc="primary skill")
        _write_skill(skills_dir, "helper", "h_skill", desc="helper skill")

        monkeypatch.setattr(prompt_builder, "get_skills_dir", lambda: skills_dir)
        monkeypatch.setattr(prompt_builder, "get_all_skills_dirs", lambda: [skills_dir])
        clear_skills_system_prompt_cache(clear_snapshot=True)

        _enable_auto_route()
        _set_active_profession("primary", ["p_skill"])

        base = build_skills_system_prompt()
        with_borrow = build_skills_system_prompt(borrowed_skills=["h_skill"])

        assert "<borrowed_skills>" in with_borrow
        assert "h_skill" in with_borrow
        # borrowed section absent in base
        assert "<borrowed_skills>" not in base

    def test_cache_key_differs_for_borrow(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        _write_skill(skills_dir, "primary", "p_skill")
        _write_skill(skills_dir, "helper", "h_skill")

        monkeypatch.setattr(prompt_builder, "get_skills_dir", lambda: skills_dir)
        monkeypatch.setattr(prompt_builder, "get_all_skills_dirs", lambda: [skills_dir])
        clear_skills_system_prompt_cache(clear_snapshot=True)

        _enable_auto_route()
        _set_active_profession("primary", ["p_skill"])

        r1 = build_skills_system_prompt()
        r2 = build_skills_system_prompt(borrowed_skills=["h_skill"])
        r3 = build_skills_system_prompt(borrowed_skills=None)
        # r1 and r3 identical (cache hit), r2 different.
        assert r1 == r3
        assert r1 != r2
