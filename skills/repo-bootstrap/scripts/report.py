"""Machine-readable and human-readable reports.

Statuses (design §11):
  applied            the operation succeeded; not read back yet
  verified           confirmed by read-back or by an actual run
  pending            asynchronous work has not finished
  unsupported        not available for this plan, permission, or visibility
  manual_action      needs OAuth, an App install, billing, or a user decision
  skipped_by_policy  deliberately not used
  failed             an unexpected failure; detail says how to retry
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

STATUSES = ("applied", "verified", "pending", "unsupported", "manual_action", "skipped_by_policy", "failed")


@dataclass
class Check:
    id: str
    status: str
    detail: str

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")


@dataclass
class Report:
    mode: str
    repository: str
    visibility: str
    docs_locale: str
    project_type: str
    github_plan_assumption: str = "personal-free"
    checks: list[Check] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    features: list[dict] = field(default_factory=list)
    manual_actions: list[str] = field(default_factory=list)
    approvals_required: list[str] = field(default_factory=list)
    choices_required: list[dict] = field(default_factory=list)
    verified_at: str | None = None
    notes: list[str] = field(default_factory=list)

    def add(self, cid: str, status: str, detail: str) -> Check:
        # A later result for the same id replaces the earlier one (e.g. applied -> verified).
        self.checks = [c for c in self.checks if c.id != cid]
        c = Check(cid, status, detail)
        self.checks.append(c)
        if status == "manual_action" and detail not in self.manual_actions:
            self.manual_actions.append(detail)
        return c

    def extend(self, checks: list[Check]) -> None:
        for c in checks:
            self.add(c.id, c.status, c.detail)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == "failed"]

    @property
    def outcome(self) -> str:
        if self.failures:
            return "failed"
        if self.choices_required:
            return "choice_required"
        if self.approvals_required:
            return "approval_required"
        if any(c.status in ("unsupported", "manual_action", "pending") for c in self.checks):
            return "complete_with_constraints"
        return "complete"

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "mode": self.mode,
            "outcome": self.outcome,
            "repository": self.repository,
            "visibility": self.visibility,
            "docs_locale": self.docs_locale,
            "project_type": self.project_type,
            "github_plan_assumption": self.github_plan_assumption,
            "verified_at": self.verified_at,
            "checks": [asdict(c) for c in self.checks],
            "features": self.features,
            "files": self.files,
            "failures": [asdict(c) for c in self.failures],
            "manual_actions": self.manual_actions,
            "choices_required": self.choices_required,
            "approvals_required": self.approvals_required,
            "notes": self.notes,
        }

    def to_markdown(self) -> str:
        label = {
            "complete": "完了",
            "complete_with_constraints": "制約付き完了（下の unsupported / manual_action / pending を確認）",
            "choice_required": "入力の選択待ち（下の入力を利用者に選んでもらう。GitHub にはまだ何も作っていません）",
            "approval_required": "承認待ち（GitHub にはまだ何も作っていません）",
            "failed": "失敗",
        }[self.outcome]
        lines = [
            f"# repo-bootstrap report: {self.repository}",
            "",
            f"- mode: `{self.mode}`",
            f"- outcome: **{self.outcome}** — {label}",
            f"- visibility: `{self.visibility}` / docs_locale: `{self.docs_locale}`"
            f" / project_type: `{self.project_type}`",
            f"- plan assumption: `{self.github_plan_assumption}`",
        ]
        if self.verified_at:
            lines.append(f"- verified_at: {self.verified_at}")
        if self.choices_required:
            lines += ["", "## 利用者に選んでもらう入力", ""]
            lines += [
                f"- `{c['input']}`: {' / '.join(c['options'])}（おすすめ: `{c['default']}`）"
                for c in self.choices_required
            ]
        if self.approvals_required:
            lines += ["", "## 必要な承認", ""] + [f"- `{a}`" for a in self.approvals_required]
        lines += ["", "## Checks", "", "| id | status | detail |", "|---|---|---|"]
        for c in self.checks:
            detail = c.detail.replace("|", "\\|")  # no backslash inside f-strings: Python 3.11
            lines.append(f"| `{c.id}` | {c.status} | {detail} |")
        if self.features:
            lines += ["", "## Planned GitHub features", "", "| id | decision | detail |", "|---|---|---|"]
            lines += [f"| `{x['id']}` | {x['action']} | {x['detail']} |" for x in self.features]
        if self.files:
            lines += ["", "## Files", "", "| path | status |", "|---|---|"]
            lines += [f"| `{f['path']}` | {f['status']} |" for f in self.files]
        if self.manual_actions:
            lines += ["", "## Manual actions", ""] + [f"- {m}" for m in self.manual_actions]
        if self.notes:
            lines += ["", "## Notes", ""] + [f"- {n}" for n in self.notes]
        return "\n".join(lines) + "\n"

    def stamp(self) -> None:
        self.verified_at = _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()

    def write(self, directory: Path) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        j = directory / "bootstrap-report.json"
        m = directory / "bootstrap-report.md"
        j.write_bytes((json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        m.write_bytes(self.to_markdown().encode("utf-8"))
        return j, m
