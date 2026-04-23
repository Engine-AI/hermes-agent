# Common skills

Skills under this directory are **always surfaced** to every profession's
system prompt, bypassing the profession-scoped filter. This is for shared
infrastructure capabilities that any profession might reasonably need:
file I/O, web search, shell, note-taking, general-purpose memory, etc.

The leading underscore in `_common` tells the skill discovery and
profession-binding code to treat this tier specially:

- `agent/prompt_builder.py::build_skills_system_prompt` renders these in
  a dedicated `<common_skills>` section that appears for all active
  professions.
- `agent/profession_router.py` does not consider common skills when
  checking profession bloat (soft cap applies to profession-exclusive
  skills only).
- `tools/professions_tool.py::bind_skill_to_professions` should skip
  skills under `_common/` (they don't belong to any specific profession).

## What to put here

Rule of thumb: if it's infrastructure that you wouldn't think of as
"belonging to a domain", put it here. Examples of skills that *might*
belong in `_common/` (verify per-skill — don't migrate blindly):

- `file-read`, `file-edit`, `file-glob`
- `web-search`, `url-fetch`
- `shell`, `terminal`
- `write-to-notes`, `memory-get`, `memory-put`
- Generic `skill-view`, `skill-list` helpers

## What NOT to put here

- Domain-specific skills (tax-filing, stock-quote, note-extract). Those
  belong under a profession-scoped category like `finance/`, `reading/`.
- Skills that require expensive credentials or quotas the default user
  won't have configured.
- Experimental skills — keep them under a scoped category until
  validated.

## How to move a skill here

There is **no automatic migration**. Moving a skill is a deliberate
decision because it widens its blast radius (it gets loaded in every
conversation). Options:

1. Copy the skill's directory under `skills/_common/` and delete the
   original (or vice versa).
2. Use a symlink if you want the file to live in two places:
   `ln -s ../<category>/<skill> skills/_common/<skill>`.

After either, run your usual skill index refresh (`hermes skills sync`
or restart the agent) so the snapshot picks up the change.
