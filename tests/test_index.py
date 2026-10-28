from pathlib import Path

import pytest

from skills_mcp.catalog import SkillCatalog
from skills_mcp.index import build_index
from tools.curate import curate

FIXTURE = Path(__file__).parent / "fixtures" / "upstream"
REAL_SKILLS = Path(__file__).resolve().parent.parent / "app" / "skills"


def make_catalog(root: Path, skills: dict[str, tuple[str, str]]) -> SkillCatalog:
    """skills: name -> (description, fit)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "UPSTREAM_VERSION").write_text("0.0.0\n")
    for name, (desc, fit) in skills.items():
        d = root / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: '{desc}'\napfm_fit: {fit}\n---\n\nbody\n"
        )
    return SkillCatalog.from_dir(root)


def rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("| ")][1:]


def test_one_row_per_skill_sorted(tmp_path):
    out = tmp_path / "out"
    curate(FIXTURE, FIXTURE / "curation.yaml", out)
    cat = SkillCatalog.from_dir(out)
    text = build_index(cat)
    assert text.startswith("# APFM Databricks skills\n")
    assert "| Skill | Use when | Fit |\n|---|---|---|\n" in text
    r = rows(text)
    assert [line.split(" | ")[0] for line in r] == ["| alpha", "| beta"]
    assert r[0].endswith(" | works |")


def test_use_when_is_first_sentence_capped_at_120(tmp_path):
    long = "x" * 200
    cat = make_catalog(
        tmp_path,
        {
            "a": ("First one. Second sentence.", "works"),
            "b": (long, "reference"),
            "c": ("y" * 119 + "!", "works"),
        },
    )
    r = rows(build_index(cat))
    assert r[0] == "| a | First one. | works |"
    use_b = r[1].split(" | ")[1]
    assert use_b == "x" * 119 + "…" and len(use_b) == 120
    assert r[2].split(" | ")[1] == "y" * 119 + "!"


def test_pipe_in_description_is_escaped(tmp_path):
    cat = make_catalog(tmp_path, {"a": ("Use a|b here", "works")})
    assert "| a | Use a\\|b here | works |" in build_index(cat)


def test_raises_when_over_max_chars(tmp_path):
    cat = make_catalog(tmp_path, {f"skill-{i:02}": ("Does a thing.", "works") for i in range(40)})
    with pytest.raises(ValueError):
        build_index(cat, max_chars=500)


@pytest.mark.skipif(not REAL_SKILLS.is_dir(), reason="app/skills missing")
def test_real_skills_fit_in_8000_chars():
    assert len(build_index(SkillCatalog.from_dir(REAL_SKILLS))) <= 8000
