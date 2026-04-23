"""Skill generation — reserved interface (NOT YET IMPLEMENTED).

Accepted skill proposals currently require a human to author the SKILL.md.
This module reserves the call shape so a future sandbox + candidate-pool
implementation can slot in without churning call sites.

See the skill-requests queue in ``tools/skill_proposals_tool.py`` for where
proposals come from. For now, accept a proposal via
``hermes skills proposals accept <slug>`` and write the skill manually.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class SkillDraft:
    slug: str
    frontmatter: Dict[str, Any]
    body: str


def generate_from_proposal(proposal_slug: str) -> SkillDraft:
    raise NotImplementedError(
        "Skill generation is not yet enabled. Accept proposals with "
        "`hermes skills proposals accept <slug>` and author SKILL.md "
        "manually. See agent/skill_generator.py for the reserved interface."
    )
