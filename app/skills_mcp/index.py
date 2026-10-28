"""Skill index rendered into the server's startup instructions."""

from __future__ import annotations

import re

from skills_mcp.catalog import SkillCatalog

HEADER = """# APFM Databricks skills

Before doing Databricks work a skill below covers, load it with `load_skill(name)` and follow it. Load reference files it mentions with `get_skill_file(name, path)`. "reference" skills explain concepts and code, but their deploy and write steps aren't available here.

| Skill | Use when | Fit |
|---|---|---|
"""

USE_WHEN_MAX = 120
_SENTENCE_END = re.compile(r"[.!?] ")


def _use_when(description: str) -> str:
    m = _SENTENCE_END.search(description)
    text = description[: m.start() + 1] if m else description
    if len(text) > USE_WHEN_MAX:
        text = text[: USE_WHEN_MAX - 1] + "…"
    return text.replace("|", "\\|")


def build_index(catalog: SkillCatalog, max_chars: int = 8000) -> str:
    rows = [
        f"| {s.name} | {_use_when(s.description)} | {s.fit} |\n"
        for s in catalog.list()
    ]
    text = HEADER + "".join(rows)
    if len(text) > max_chars:
        raise ValueError(f"skill index is {len(text)} chars, exceeds max_chars={max_chars}")
    return text
