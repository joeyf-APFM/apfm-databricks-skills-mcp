import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools.curate import CurationError, curate

FIXTURE = Path(__file__).parent / "fixtures" / "upstream"
CONFIG = FIXTURE / "curation.yaml"
ROOT = Path(__file__).parent.parent


def split_frontmatter(text: str) -> tuple[str, str]:
    assert text.startswith("---\n")
    end = text.index("\n---\n", 3)
    return text[4 : end + 1], text[end + 5 :]


def upstream_body_of(skill: str) -> str:
    return split_frontmatter((FIXTURE / "skills" / skill / "SKILL.md").read_text())[1]


@pytest.fixture
def upstream(tmp_path):
    dst = tmp_path / "upstream"
    shutil.copytree(FIXTURE, dst)
    return dst


def run(upstream, tmp_path, config=None):
    out = tmp_path / "out"
    return out, curate(upstream, config or CONFIG, out)


def test_copies_md_and_py_only(upstream, tmp_path):
    out, res = run(upstream, tmp_path)
    assert (out / "alpha/references/one.md").is_file()
    assert (out / "alpha/examples/ex.py").is_file()
    assert not (out / "alpha/assets/icon.png").exists()
    assert not (out / "alpha/agents/openai.yaml").exists()
    assert not (out / "gamma").exists()
    assert res.included == ["alpha", "beta"] and res.excluded == ["gamma"]


def test_inserts_fit_and_note_after_frontmatter(upstream, tmp_path):
    out, _ = run(upstream, tmp_path)
    front, body = split_frontmatter((out / "alpha/SKILL.md").read_text())
    meta = yaml.safe_load(front)
    assert meta["apfm_fit"] == "works"
    assert meta["description"] == "Alpha skill used for testing with a folded description."
    assert body.lstrip().startswith("> **APFM note.**")
    assert upstream_body_of("alpha") in body
    assert "reference-only" not in body


def test_reference_skill_gets_reference_paragraph(upstream, tmp_path):
    out, _ = run(upstream, tmp_path)
    text = (out / "beta/SKILL.md").read_text()
    assert "reference-only through Platform MCP" in text
    assert yaml.safe_load(split_frontmatter(text)[0])["apfm_fit"] == "reference"


def test_writes_license_notice_and_version(upstream, tmp_path):
    out, res = run(upstream, tmp_path)
    assert (out / "LICENSE").read_text() == (FIXTURE / "LICENSE").read_text()
    assert (out / "NOTICE").read_text() == (FIXTURE / "NOTICE").read_text()
    assert (out / "UPSTREAM_VERSION").read_text().strip() == "0.0.1" == res.upstream_version


def test_unlisted_upstream_skill_fails(upstream, tmp_path):
    shutil.copytree(upstream / "skills/beta", upstream / "skills/delta")
    with pytest.raises(CurationError, match="delta"):
        run(upstream, tmp_path)


def test_experimental_is_ignored(upstream, tmp_path):
    (upstream / "experimental/zeta").mkdir(parents=True)
    (upstream / "experimental/zeta/SKILL.md").write_text("---\nname: zeta\n---\n")
    out, _ = run(upstream, tmp_path)
    assert not (out / "zeta").exists()


def test_listed_skill_missing_upstream_fails(upstream, tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("include:\n  works: [alpha, omega]\n  reference: [beta]\nexclude: [gamma]\n")
    with pytest.raises(CurationError, match="omega"):
        run(upstream, tmp_path, cfg)


def test_removes_stale_output(upstream, tmp_path):
    out = tmp_path / "out"
    (out / "old-skill").mkdir(parents=True)
    (out / "old-skill/SKILL.md").write_text("x")
    run(upstream, tmp_path)
    assert not (out / "old-skill").exists()


def test_failure_keeps_existing_output(upstream, tmp_path):
    out = tmp_path / "out"
    (out / "old-skill").mkdir(parents=True)
    shutil.copytree(upstream / "skills/beta", upstream / "skills/delta")
    with pytest.raises(CurationError):
        run(upstream, tmp_path)
    assert (out / "old-skill").exists()


def test_rejects_file_over_10mb(upstream, tmp_path):
    (upstream / "skills/alpha/references/big.md").write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    with pytest.raises(CurationError, match="big.md"):
        run(upstream, tmp_path)


def test_skill_in_both_include_and_exclude_fails(upstream, tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("include:\n  works: [alpha]\n  reference: [beta]\nexclude: [gamma, alpha]\n")
    with pytest.raises(CurationError, match="alpha"):
        run(upstream, tmp_path, cfg)


def cli(upstream, out, *extra):
    return subprocess.run(
        [sys.executable, "-m", "tools.curate", "--upstream", str(upstream), "--config", str(CONFIG),
         "--out", str(out), *extra],
        cwd=ROOT, capture_output=True, text=True,
    )


def test_check_mode_reports_drift(upstream, tmp_path):
    out = tmp_path / "out"
    assert cli(upstream, out).returncode == 0
    assert cli(upstream, out, "--check").returncode == 0
    (out / "alpha/references/one.md").write_text("edited")
    r = cli(upstream, out, "--check")
    assert r.returncode == 1
    assert "alpha/references/one.md" in r.stdout
