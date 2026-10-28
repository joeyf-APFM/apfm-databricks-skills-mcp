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


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    fit: str
    files: tuple[str, ...]


def _frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 3)
    if end == -1:
        return {}
    data = yaml.safe_load(text[4 : end + 1])
    return data if isinstance(data, dict) else {}


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
            fm = _frontmatter(md.read_text(encoding="utf-8"))
            name = d.name  # directory name is the canonical id (equals frontmatter name in curated output)
            skills[name] = Skill(
                name=name,
                description=" ".join(str(fm.get("description", "")).split()),
                fit=str(fm.get("apfm_fit", "reference")),
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
