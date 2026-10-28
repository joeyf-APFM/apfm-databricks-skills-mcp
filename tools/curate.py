"""Turn a pinned upstream databricks-agent-skills checkout into app/skills."""

import argparse
import filecmp
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

MAX_FILE_BYTES = 10 * 1024 * 1024
COPY_SUFFIXES = {".md", ".py"}
OVERLAY = Path(__file__).resolve().parent.parent / "overlay"


class CurationError(Exception):
    pass


@dataclass
class CurationResult:
    included: list[str]
    excluded: list[str]
    upstream_version: str


def _load_config(config: Path) -> tuple[dict[str, list[str]], list[str]]:
    data = yaml.safe_load(config.read_text()) or {}
    inc = data.get("include") or {}
    fit = {"works": list(inc.get("works") or []), "reference": list(inc.get("reference") or [])}
    return fit, list(data.get("exclude") or [])


def _split_frontmatter(text: str, name: str) -> tuple[str, str]:
    """Return (frontmatter lines incl. opening '---\\n', rest starting at closing '---')."""
    if not text.startswith("---\n"):
        raise CurationError(f"{name}: SKILL.md has no YAML frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise CurationError(f"{name}: SKILL.md frontmatter is not closed")
    return text[: end + 1], text[end + 1 :]


def _build(upstream: Path, config: Path, dest: Path) -> CurationResult:
    fit_by_skill: dict[str, str] = {}
    fits, excluded = _load_config(config)
    for fit, names in fits.items():
        for n in names:
            fit_by_skill[n] = fit
    both = sorted(set(fit_by_skill) & set(excluded))
    if both:
        raise CurationError(f"skills listed in both include and exclude: {', '.join(both)}")

    skills_root = upstream / "skills"
    upstream_skills = sorted(p.name for p in skills_root.iterdir() if p.is_dir())
    listed = set(fit_by_skill) | set(excluded)
    unlisted = [s for s in upstream_skills if s not in listed]
    if unlisted:
        raise CurationError(f"upstream skills not in curation config: {', '.join(unlisted)}")
    missing = sorted(listed - set(upstream_skills))
    if missing:
        raise CurationError(f"skills in curation config missing upstream: {', '.join(missing)}")

    note_works = (OVERLAY / "note-works.md").read_text().rstrip("\n")
    note_ref = (OVERLAY / "note-reference.md").read_text().rstrip("\n")
    version_file = upstream / "metaplugin" / "version.meta.json"
    try:
        version = str(json.loads(version_file.read_text())["current_version"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise CurationError(f"cannot read current_version from metaplugin/version.meta.json: {e!r}") from e

    included = []
    for skill in upstream_skills:
        if skill in excluded:
            continue
        fit = fit_by_skill[skill]
        src = skills_root / skill
        for f in sorted(p for p in src.rglob("*") if p.is_file() and p.suffix in COPY_SUFFIXES):
            if f.stat().st_size > MAX_FILE_BYTES:
                raise CurationError(f"{f.relative_to(upstream)} exceeds 10 MB")
            target = dest / skill / f.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            if f == src / "SKILL.md":
                text = f.read_text()
                front, rest = _split_frontmatter(text, skill)
                yaml.safe_load(front[4:])  # validate
                note = note_works + ("\n" + note_ref if fit == "reference" else "") + "\n"
                target.write_text(f"{front}apfm_fit: {fit}\n{rest[:4]}\n{note}{rest[4:]}")
            else:
                shutil.copyfile(f, target)
        if not (src / "SKILL.md").is_file():
            raise CurationError(f"{skill}: missing SKILL.md")
        included.append(skill)

    for name in ("LICENSE", "NOTICE"):
        shutil.copyfile(upstream / name, dest / name)
    (dest / "UPSTREAM_VERSION").write_text(version + "\n")
    return CurationResult(included=included, excluded=sorted(excluded), upstream_version=version)


def curate(upstream: Path, config: Path, out: Path) -> CurationResult:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".curate-", dir=out.parent))
    try:
        result = _build(Path(upstream), Path(config), tmp)
        if out.exists():
            shutil.rmtree(out)
        tmp.rename(out)
        return result
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _diff(a: Path, b: Path) -> list[str]:
    """Relative paths that differ between expected tree a and actual tree b."""
    diffs: list[str] = []
    cmp = filecmp.dircmp(a, b)

    def walk(c: filecmp.dircmp, prefix: str) -> None:
        diffs.extend(prefix + n for n in c.left_only + c.right_only + c.diff_files + c.funny_files)
        for sub, sc in c.subdirs.items():
            walk(sc, f"{prefix}{sub}/")

    walk(cmp, "")
    return sorted(diffs)


def check(upstream: Path, config: Path, out: Path) -> list[str]:
    with tempfile.TemporaryDirectory() as t:
        expected = Path(t) / "out"
        expected.mkdir()
        _build(Path(upstream), Path(config), expected)
        if not Path(out).exists():
            return ["<output directory missing>"]
        return _diff(expected, Path(out))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.curate")
    ap.add_argument("--upstream", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true", help="exit 1 if output would change")
    args = ap.parse_args(argv)
    try:
        if args.check:
            diffs = check(args.upstream, args.config, args.out)
            if diffs:
                print("Curated output differs:", *diffs, sep="\n  ")
                return 1
            return 0
        r = curate(args.upstream, args.config, args.out)
    except CurationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"curated {len(r.included)} skills from upstream {r.upstream_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
