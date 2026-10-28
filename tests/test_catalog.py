import shutil
from pathlib import Path

import pytest

from skills_mcp.catalog import FileNotAllowed, SkillCatalog, SkillNotFound
from tools.curate import curate

FIXTURE = Path(__file__).parent / "fixtures" / "upstream"


@pytest.fixture(scope="module")
def curated(tmp_path_factory):
    out = tmp_path_factory.mktemp("curated") / "out"
    curate(FIXTURE, FIXTURE / "curation.yaml", out)
    return out


@pytest.fixture
def cat(curated):
    return SkillCatalog.from_dir(curated)


def test_loads_name_description_fit(cat):
    assert cat.names() == ["alpha", "beta"]
    assert cat.get("alpha").fit == "works"
    assert cat.get("alpha").description.startswith("Alpha skill")


def test_folded_description_is_one_line(cat):
    assert "\n" not in cat.get("alpha").description


def test_files_sorted_posix(cat):
    files = cat.get("alpha").files
    assert files == tuple(sorted(files))
    assert "SKILL.md" in files and "references/one.md" in files


def test_list_query_matches_name_or_description_case_insensitive(cat):
    assert [s.name for s in cat.list("ALPHA")] == ["alpha"]
    assert [s.name for s in cat.list("folded")] == ["alpha"]
    assert cat.list("zzz-nothing") == []
    assert len(cat.list()) == 2


def test_read_default_is_skill_md(cat):
    assert cat.read("alpha").startswith("---")


def test_read_reference_file(cat):
    assert cat.read("alpha", "references/one.md")


def test_unknown_skill_raises(cat):
    with pytest.raises(SkillNotFound):
        cat.read("nope")
    with pytest.raises(SkillNotFound):
        cat.get("nope")


@pytest.mark.parametrize(
    "bad",
    [
        "../beta/SKILL.md",
        "../../app.py",
        "/etc/passwd",
        "references/../../beta/SKILL.md",
        "references/../../x",
        "%2e%2e/beta/SKILL.md",
        "references/missing.md",
        "",
    ],
)
def test_rejects_paths_outside_skill_or_unlisted(cat, bad):
    with pytest.raises(FileNotAllowed):
        cat.read("alpha", bad)


def test_rejects_unlisted_file_that_exists_on_disk(curated, tmp_path):
    root = tmp_path / "c"
    shutil.copytree(curated, root)
    (root / "alpha" / "late.md").write_text("late")
    cat = SkillCatalog.from_dir(root)
    (root / "alpha" / "later.md").write_text("later")  # added after load
    with pytest.raises(FileNotAllowed):
        cat.read("alpha", "later.md")
    assert cat.read("alpha", "late.md") == "late"


def test_rejects_symlink_escaping_skill(curated, tmp_path):
    root = tmp_path / "c"
    shutil.copytree(curated, root)
    (root / "alpha" / "link.md").symlink_to("../beta/SKILL.md")
    cat = SkillCatalog.from_dir(root)
    assert "link.md" not in cat.get("alpha").files
    with pytest.raises(FileNotAllowed):
        cat.read("alpha", "link.md")


def test_upstream_version_read(cat):
    assert cat.upstream_version == "0.0.1"
