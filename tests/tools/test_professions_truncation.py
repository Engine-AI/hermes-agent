"""Tests for tools/professions_tool.py recent_cases cost guard."""

from tools.professions_tool import (
    _MAX_CASE_CHARS,
    _MAX_RECENT_CASES,
    _save_entries,
    _truncate_recent_cases,
    auto_create_profession,
    list_professions,
    render_profession_entry,
    solve_profession,
)


class TestTruncateHelper:
    def test_caps_count(self):
        cases = [f"case-{i}" for i in range(10)]
        out = _truncate_recent_cases(cases)
        assert len(out) == _MAX_RECENT_CASES

    def test_caps_each_size(self):
        big = "x" * (_MAX_CASE_CHARS + 100)
        out = _truncate_recent_cases([big, "y"])
        assert len(out[0]) == _MAX_CASE_CHARS
        assert out[0].endswith("...")
        assert out[1] == "y"

    def test_empty_safe(self):
        assert _truncate_recent_cases([]) == []
        assert _truncate_recent_cases(["", " ", None]) == []


class TestSolveProfessionTruncation:
    def test_recent_cases_never_exceed_cap(self):
        auto_create_profession("Tax Helper", problem_domains=["tax"])
        for i in range(10):
            solve_profession(
                "tax-helper",
                problem=f"problem number {i}",
                user=f"user{i}",
                summary=f"summary {i}",
            )
        entries = [e for e in list_professions() if e["slug"] == "tax-helper"]
        assert entries
        assert len(entries[0]["recent_cases"]) <= _MAX_RECENT_CASES
        for case in entries[0]["recent_cases"]:
            assert len(case) <= _MAX_CASE_CHARS

    def test_render_defensively_truncates_bloat(self):
        auto_create_profession("Bloat Fix", problem_domains=["d"])
        entries = list_professions()
        for e in entries:
            if e["slug"] == "bloat-fix":
                # Synthesize a bloated recent_cases beyond limits.
                e["recent_cases"] = [f"case-{i}" for i in range(10)]
        _save_entries(entries)

        # Render of any goal-linked profession trims it back.
        for e in list_professions():
            if e["slug"] == "bloat-fix":
                rendered = render_profession_entry(e)
                # Count pipes to approximate the case count; max 3 → ≤2 pipes.
                line = next(
                    (l for l in rendered.splitlines() if l.startswith("Recent Cases:")),
                    "",
                )
                case_part = line.split(":", 1)[1].strip() if ":" in line else ""
                if not case_part:
                    continue
                assert case_part.count(" | ") <= _MAX_RECENT_CASES - 1
