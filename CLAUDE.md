# CLAUDE.md

See [AGENTS.md](./AGENTS.md) — it is the canonical guide for AI coding assistants working on this repo (project structure, AIAgent class, CLI/TUI architecture, tool/skill/profession/goal systems, config & profiles, testing policy, and known pitfalls).

Keep both files in sync by editing `AGENTS.md` only. This file is a pointer so Claude Code auto-loads the same guidance.

## Quick orientation

- Entry points: `cli.py` (interactive REPL), `hermes_cli/main.py` (`hermes <subcommand>`), `run_agent.py` (`hermes-agent`).
- Always activate the venv before running anything: `source venv/bin/activate`.
- Tests: `scripts/run_tests.sh` (never call `pytest` directly — the wrapper enforces CI-parity env).
- User state lives under `~/.hermes/` (or per-profile `~/.hermes/profiles/<name>/`). Use `get_hermes_home()` / `display_hermes_home()` from `hermes_constants`, never hardcode `~/.hermes`.

## Professions & Goals (not yet documented in AGENTS.md)

This branch adds a three-layer intent stack: **goals** (what the user wants long-term) → **brain / profession router** (which role to use now) → **professions** (skill bundles that execute).

### Professions — `tools/professions_tool.py`, CLI `hermes professions …`

- Persisted as `~/.hermes/memories/PROFESSIONS.md`, one entry per profession, separated by `\n§\n`. Human-editable plain-text key/value blocks.
- Each entry tracks: `Slug`, `Skills`, `Problem Domains`, `Solved Count`, `Users Helped`, `Rating`, `Score`, `Recent Solutions`, `Recent Cases`, `Feedback Summary`, `Optimization Notes`, `Description`.
- Loaded into the system prompt via `agent/builtin_memory_provider.py` alongside `MEMORY.md` / `USER.md` — treat it as part of persistent memory, not ephemeral state.
- Cost guards in `tools/professions_tool.py`: `RECENT_ITEMS_LIMIT=5`, `_MAX_RECENT_CASES=3`, `_MAX_CASE_CHARS=600`. Don't let `solve_profession` append unbounded history.
- Can be auto-generated from installed skills: `hermes professions rebuild`. Manual curation is also fine — the file format is the contract.

### Goals — `tools/goals_tool.py`, CLI `hermes goals …`, REPL `/goal`

- Persisted as `~/.hermes/memories/GOALS.md`, same `\n§\n` format as PROFESSIONS.md.
- Fields: `Goal`, `Slug`, `Status` (`active`/`paused`/`done`), `Created At`, `Updated At`, `Description`, `Linked Professions`, `Linked Routines`, `Recent Progress`, `Notes`.
- Two pin scopes:
  - `hermes goals use <slug>` — **persistent** pin (survives across sessions).
  - `/goal <slug>` in the REPL — **session-scoped** pin via env var, not written to disk. Implemented in `cli.py::HermesCLI._handle_goal_command`.
- `summarize_active()` is fed to the router so long-term intent influences routing (e.g., "cardio plan" weakly matches `fitness-coach` until the goal links it).
- `solve_profession` fans progress entries out to every active goal that links that profession — goals accumulate evidence of work automatically.
- Tunables: `RECENT_PROGRESS_LIMIT=5`, `_DEFAULT_MAX_ACTIVE_GOALS=5`, `_DEFAULT_MAX_SUMMARY_CHARS=800`.
- Opt-in `goals.auto_create_profession` (default `False`): when true, `create_goal` and `link_profession` auto-create any linked profession that doesn't yet exist in PROFESSIONS.md (via `auto_create_profession`, description `"Auto-created from goal: <title>"`). Off by default — same opt-in posture as `professions.auto_route`.

### Brain / Profession router — `agent/profession_router.py`

- **Gated by config flag `professions.auto_route`** (off by default for existing users). When off, `should_route()` returns False and `route()` is never called — the feature is completely passive.
- Decides one of four actions given (user query, active profession, active goals):
  - `stay` — no change.
  - `switch` — change to an existing profession.
  - `create` — mint a new profession.
  - `borrow` — pull up to `_BORROW_MAX_SKILLS=3` skills from up to `_BORROW_MAX_SOURCES=2` sibling professions (cross-binding, no switch).
- Backed by the main LLM via `agent.auxiliary_client.call_llm(task="profession_routing", …)`.
- **Cost controls**: per-session budget `_DEFAULT_BRAIN_BUDGET=3` router calls; drift check interval `DEFAULT_DRIFT_CHECK_INTERVAL=5` turns.
- **Skill gap detection**: both LLM-emitted and retry-based heuristic (`_DEFAULT_RETRY_GAP_THRESHOLD=3`). Gaps become markdown proposals via `tools/skill_proposals_tool.py`.
- **Bloat detection**: professions above `_DEFAULT_BLOAT_SOFT_CAP=15` skills emit a split proposal, debounced for `_BLOAT_DEBOUNCE_HOURS=24`.
- State persists in `~/.hermes/brain_state.json`: `{sessions: {<sid>: {active_profession, drift_check_interval, last_intents}}, last_intents: [...] }` (last `_RETRY_INTENT_WINDOW=20` kept).

### Invariants to preserve when editing this area

- **Don't break prompt caching.** PROFESSIONS.md is part of the system prompt. Don't mutate it mid-conversation except through the normal memory-refresh path. Same rule as AGENTS.md "Prompt Caching Must Not Break".
- **Don't hardcode paths.** Use `get_goals_path()` / `get_professions_path()` / `_brain_state_path()` — they all resolve via `get_hermes_home()` and therefore respect profiles.
- **Keep the router opt-in.** Any new routing behavior must be reachable only when `professions.auto_route` is truthy. Guard with `should_route()` at the call site, not inside the router internals.
- **Respect cost guards.** If you add a new field to recent_* lists, add a cap; unbounded growth balloons the prompt.
