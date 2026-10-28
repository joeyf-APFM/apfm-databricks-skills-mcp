"""Read-only catalog over the curated skills directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import yaml


class SkillNotFound(KeyError):
    pass


class FileNotAllowed(ValueError):
    pass


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    fit: str
    files: tuple[str, ...]


def _frontmatter(text: str, skill_dir: str) -> dict:
    if not text.startswith("---\n"):
        raise CatalogError(f"{skill_dir}: SKILL.md has no frontmatter")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise CatalogError(f"{skill_dir}: SKILL.md frontmatter is not closed")
    try:
        data = yaml.safe_load(text[4 : end + 1])
    except yaml.YAMLError as e:
        raise CatalogError(f"{skill_dir}: invalid frontmatter YAML: {e}") from e
    if not isinstance(data, dict):
        raise CatalogError(f"{skill_dir}: frontmatter is not a mapping")
    return data


def _list_files(skill_dir: Path) -> tuple[str, ...]:
    files = []
    for p in skill_dir.rglob("*"):
        if p.is_symlink() or not p.is_file():
            continue
        files.append(p.relative_to(skill_dir).as_posix())
    return tuple(sorted(files))


class SkillCatalog:
    def __init__(self, root: Path, skills: dict[str, Skill], upstream_version: str):
        self._root = root
        self._skills = skills
        self.upstream_version = upstream_version

    @classmethod
    def from_dir(cls, root: Path) -> "SkillCatalog":
        root = Path(root).resolve()
        skills: dict[str, Skill] = {}
        for d in sorted(root.iterdir()):
            md = d / "SKILL.md"
            if d.is_symlink() or not d.is_dir() or md.is_symlink() or not md.is_file():
                continue
            fm = _frontmatter(md.read_text(encoding="utf-8"), d.name)
            name = d.name  # directory name is the canonical id (equals frontmatter name in curated output)
            description = " ".join(str(fm.get("description") or "").split())
            if not description:
                raise CatalogError(f"{d.name}: missing or empty description")
            fit = fm.get("apfm_fit")
            if fit not in ("works", "reference"):
                raise CatalogError(f"{d.name}: apfm_fit must be 'works' or 'reference', got {fit!r}")
            skills[name] = Skill(
                name=name,
                description=description,
                fit=fit,
                files=_list_files(d),
            )
        version_file = root / "UPSTREAM_VERSION"
        version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "unknown"
        return cls(root, skills, version)

    def names(self) -> list[str]:
        return sorted(self._skills)

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError:
            raise SkillNotFound(name) from None

    def list(self, query: str | None = None) -> list[Skill]:
        skills = [self._skills[n] for n in self.names()]
        if not query:
            return skills
        q = query.lower()
        return [s for s in skills if q in s.name.lower() or q in s.description.lower()]

    def read(self, name: str, path: str = "SKILL.md") -> str:
        skill = self.get(name)
        rel = unquote(path)
        if not rel or rel not in skill.files:
            raise FileNotAllowed(path)
        return (self._root / name / rel).read_text(encoding="utf-8")
