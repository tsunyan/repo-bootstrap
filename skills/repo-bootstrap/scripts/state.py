"""Lock file, content hashes, and non-destructive writes.

A file is overwritten only when it is missing, already identical, or still
exactly what this skill wrote last time (its hash matches the lock). Any
other difference is a conflict: the file is left alone and a diff is
reported.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from policy import SCHEMA_VERSION, SKILL_VERSION
from scaffold import TEMPLATES, PlannedFile

LOCK_PATH = ".repo-bootstrap.lock.json"
MERGEABLE = {".gitignore"}  # rendered as an append-only merge of the existing file


@dataclass
class FileResult:
    path: str
    status: str  # created | updated | unchanged | conflict
    diff: str | None = None


def normalise(text: str) -> str:
    return text.replace("\r\n", "\n")


def sha256(text: str) -> str:
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()


def safe_path(target: Path, rel: str) -> Path:
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise ValueError(f"Refusing to write outside the repository: {rel!r}")
    out = (target / Path(*p.parts)).resolve()
    if target.resolve() not in out.parents:
        raise ValueError(f"Refusing to write outside the repository: {rel!r}")
    return out


def read_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    return normalise(path.read_bytes().decode("utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(normalise(text).encode("utf-8"))  # always LF, never platform newlines


def load_lock(target: Path) -> dict | None:
    text = read_text(target / LOCK_PATH)
    return json.loads(text) if text else None


def template_version() -> str:
    h = hashlib.sha256()
    for p in sorted(TEMPLATES.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(TEMPLATES).as_posix().encode())
            h.update(b"\0")
            h.update(normalise(p.read_bytes().decode("utf-8")).encode())
    return h.hexdigest()[:16]


def classify(target: Path, files: list[PlannedFile], lock: dict | None) -> list[FileResult]:
    known = (lock or {}).get("files", {})
    results = []
    for f in files:
        current = read_text(safe_path(target, f.path))
        if current is None:
            results.append(FileResult(f.path, "created"))
        elif current == normalise(f.content):
            results.append(FileResult(f.path, "unchanged"))
        elif f.path in MERGEABLE or known.get(f.path, {}).get("sha256") == sha256(current):
            results.append(FileResult(f.path, "updated", _diff(f.path, current, f.content)))
        else:
            results.append(FileResult(f.path, "conflict", _diff(f.path, current, f.content)))
    return results


def _diff(path: str, old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            normalise(old).splitlines(True), normalise(new).splitlines(True), fromfile=f"a/{path}", tofile=f"b/{path}"
        )
    )


def apply(target: Path, files: list[PlannedFile], results: list[FileResult]) -> None:
    by_path = {f.path: f for f in files}
    for r in results:
        if r.status in ("created", "updated"):
            write_text(safe_path(target, r.path), by_path[r.path].content)


def build_lock(
    files: list[PlannedFile],
    results: list[FileResult],
    previous: dict | None,
    pins: dict[str, dict],
    expected: dict[str, str],
) -> dict:
    prev_files = (previous or {}).get("files", {})
    entries = {}
    for f, r in zip(files, results, strict=True):
        if r.status == "conflict":
            if f.path in prev_files:
                entries[f.path] = prev_files[f.path]
            continue
        entries[f.path] = {"sha256": sha256(f.content), "template": f.template}
    return {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "template_version": template_version(),
        "files": dict(sorted(entries.items())),
        "actions": {k: pins[k] for k in sorted(pins)},
        "github_expected": dict(sorted(expected.items())),
    }


def write_lock(target: Path, lock: dict) -> str:
    text = json.dumps(lock, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    current = read_text(target / LOCK_PATH)
    if current == text:
        return "unchanged"
    write_text(target / LOCK_PATH, text)
    return "created" if current is None else "updated"
