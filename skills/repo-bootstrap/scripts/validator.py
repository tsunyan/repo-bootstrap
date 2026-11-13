"""Local validation gates that run before anything reaches GitHub."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import policy
import renderer
from report import Check
from scaffold import PlannedFile

USES_RE = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+)", re.MULTILINE)
PINNED_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
JA_CHARS_RE = re.compile(r"[぀-ヿ㐀-鿿！-｠]")
MD_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
HEADING_RE = re.compile(r"^#{1,3} ", re.MULTILINE)

DOC_PATHS = (
    "README.md",
    "README.en.md",
    "README.ja.md",
    "AGENTS.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
)
BILINGUAL = ("AGENTS.md", "SECURITY.md", "CONTRIBUTING.md", ".github/PULL_REQUEST_TEMPLATE.md")
FORBIDDEN_NAMES = re.compile(
    r"(^|/)(\.env(\..+)?|id_rsa|id_ed25519|id_ecdsa|.*\.pem|.*\.key|.*\.p12|.*\.pfx|credentials\.json)$"
)
ALLOWED_FORBIDDEN = re.compile(r"(^|/)\.env\.example$")


def _yaml_load(text: str):
    """Parse YAML without YAML 1.1 booleans, so the ``on:`` key stays ``on``."""
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    return yaml.load(text, Loader=yaml.BaseLoader)


def check_placeholders(files: list[PlannedFile]) -> Check:
    bad = []
    for f in files:
        left = renderer.find_unresolved(f.content)
        if left or renderer.NO_COMMAND in f.content:
            bad.append(f"{f.path}: {', '.join(left) or 'command marker'}")
    if bad:
        return Check("render.placeholders", "failed", "Unresolved placeholders: " + "; ".join(bad))
    return Check("render.placeholders", "verified", f"{len(files)} files have no unresolved {{{{...}}}} variables")


def workflow_texts(files: list[PlannedFile], target: Path | None) -> dict[str, str]:
    out = {f.path: f.content for f in files if f.path.startswith(".github/workflows/")}
    if target is not None:
        wf = target / ".github" / "workflows"
        for p in sorted(wf.glob("*.y*ml")) if wf.is_dir() else []:
            rel = p.relative_to(target).as_posix()
            out.setdefault(rel, p.read_bytes().decode("utf-8"))
    return out


def check_workflows(workflows: dict[str, str]) -> list[Check]:
    checks = []
    unpinned, problems = [], []
    have_yaml = _yaml_load("a: 1") is not None
    for path, text in sorted(workflows.items()):
        for ref in USES_RE.findall(text):
            if ref.startswith(("./", "docker://")):
                continue
            if not PINNED_RE.match(ref):
                unpinned.append(f"{path}: {ref}")
        if "pull_request_target" in text:
            problems.append(f"{path}: uses pull_request_target")
        if have_yaml:
            try:
                doc = _yaml_load(text)
            except Exception as exc:  # noqa: BLE001 - yaml.YAMLError without importing yaml
                problems.append(f"{path}: YAML error {exc}")
                continue
            if not isinstance(doc, dict) or "on" not in doc or "jobs" not in doc:
                problems.append(f"{path}: missing top-level 'on' or 'jobs'")
            elif "permissions" not in doc:
                problems.append(f"{path}: no top-level permissions (least privilege)")
    if not workflows:
        checks.append(Check("actions.pinned", "skipped_by_policy", "No workflows"))
    elif unpinned:
        checks.append(Check("actions.pinned", "failed", "Not pinned to a 40-character SHA: " + "; ".join(unpinned)))
    else:
        checks.append(Check("actions.pinned", "verified", f"All `uses:` in {len(workflows)} workflow(s) are full SHAs"))
    if problems:
        checks.append(Check("workflows.syntax", "failed", "; ".join(problems)))
    elif workflows and not have_yaml:
        checks.append(
            Check(
                "workflows.syntax",
                "pending",
                "PyYAML is not installed; workflow structure was not parsed (pip install pyyaml)",
            )
        )
    elif workflows:
        checks.append(Check("workflows.syntax", "verified", "Workflows parse; 'on', 'jobs', 'permissions' present"))
    return checks


def check_structured(files: list[PlannedFile]) -> Check:
    errors = []
    have_yaml = _yaml_load("a: 1") is not None
    for f in files:
        p = f.path.lower()
        try:
            if p.endswith(".json"):
                json.loads(f.content)
            elif p.endswith(".toml"):
                tomllib.loads(f.content)
            elif p.endswith(".xml"):
                ET.fromstring(f.content.encode("utf-8"))
            elif p.endswith((".yml", ".yaml")) and have_yaml:
                _yaml_load(f.content)
        except Exception as exc:  # noqa: BLE001 - report any parser error
            errors.append(f"{f.path}: {exc}")
    if errors:
        return Check("files.syntax", "failed", "; ".join(errors))
    return Check("files.syntax", "verified", "JSON/TOML/XML" + ("/YAML" if have_yaml else "") + " files parse")


def check_links(files: list[PlannedFile], target: Path | None) -> Check:
    paths = {f.path for f in files}
    broken = []
    for f in files:
        if not f.path.endswith(".md"):
            continue
        base = Path(f.path).parent
        for link in MD_LINK_RE.findall(f.content):
            if re.match(r"^[a-z]+:", link) or link.startswith("#"):
                continue
            rel = (base / link.split("#", 1)[0]).as_posix()
            rel = rel.removeprefix("./")
            if rel in paths or (target is not None and (target / rel).exists()):
                continue
            broken.append(f"{f.path} -> {link}")
    if broken:
        return Check("files.links", "failed", "Broken relative links: " + "; ".join(broken))
    return Check("files.links", "verified", "Relative links in Markdown files resolve")


LANG_HEADING_RE = re.compile(r"^## (日本語|English)$", re.MULTILINE)


def _sections(text: str) -> tuple[str, str, str]:
    """(Japanese section, English section, order) of a bilingual document.

    Each section starts at its language heading. order is "ja-en", "en-ja", or
    "" when the two headings are not both present exactly once.
    """
    marks = [(m.start(), m.group(1)) for m in LANG_HEADING_RE.finditer(text)]
    if sorted(lang for _, lang in marks) != ["English", "日本語"]:
        return "", "", ""
    (p1, l1), (p2, _) = marks
    first, second = text[p1:p2], text[p2:]
    if l1 == "日本語":
        return first, second, "ja-en"
    return second, first, "en-ja"


def check_locale(files: list[PlannedFile], locale: str) -> Check:
    by = {f.path: f.content for f in files}
    problems = []
    docs = {p: by[p] for p in DOC_PATHS if p in by}
    if locale in ("ja", "en"):
        for extra in ("README.en.md", "README.ja.md"):
            if extra in by:
                problems.append(f"{extra} exists in {locale} mode")
        for p, t in docs.items():
            if locale == "en" and JA_CHARS_RE.search(t):
                problems.append(f"{p}: contains Japanese text")
            if locale == "ja" and not JA_CHARS_RE.search(t):
                problems.append(f"{p}: has no Japanese text")
            if locale == "ja" and "\n## English\n" in t:
                problems.append(f"{p}: has an English section in ja mode")
    else:
        paths = policy.readme_paths(locale)
        ja_path, en_path = paths["ja"], paths["en"]
        stray = "README.ja.md" if locale == "ja-en" else "README.en.md"
        if stray in by:
            problems.append(f"{stray} exists in {locale} mode")
        if ja_path not in by or en_path not in by:
            problems.append(f"{locale} needs {ja_path} (Japanese) and {en_path} (English)")
        else:
            if f"({en_path})" not in by[ja_path]:
                problems.append(f"{ja_path} does not link to {en_path}")
            if f"({ja_path})" not in by[en_path]:
                problems.append(f"{en_path} does not link to {ja_path}")
            if not JA_CHARS_RE.search(by[ja_path]):
                problems.append(f"{ja_path}: has no Japanese text")
            if JA_CHARS_RE.search(by[en_path].replace(f"[日本語]({ja_path})", "")):
                problems.append(f"{en_path} contains Japanese text besides the language link")
        for p in BILINGUAL:
            if p not in by:
                continue
            ja, en, order = _sections(by[p])
            if not order:
                problems.append(f"{p}: needs one '## 日本語' and one '## English' section")
                continue
            if order != locale:
                problems.append(f"{p}: sections are in {order} order, expected {locale}")
            if not JA_CHARS_RE.search(ja):
                problems.append(f"{p}: Japanese section has no Japanese text")
            if JA_CHARS_RE.search(en):
                problems.append(f"{p}: English section contains Japanese text")
            if len(HEADING_RE.findall(ja)) != len(HEADING_RE.findall(en)):
                problems.append(f"{p}: Japanese and English sections have different heading counts")
        bug = by.get(".github/ISSUE_TEMPLATE/bug_report.yml", "")
        first = "English" if locale == "en-ja" else "日本語"
        if bug and " / " not in bug:
            problems.append("bug_report.yml labels are not bilingual")
        elif bug:
            name = next((ln for ln in bug.splitlines() if ln.startswith("name:")), "")
            if bool(JA_CHARS_RE.search(name.split(" / ")[0])) != (first == "日本語"):
                problems.append(f"bug_report.yml labels should start with {first}")
    if problems:
        return Check("files.locale", "failed", "; ".join(problems))
    return Check("files.locale", "verified", f"Documents follow docs_locale={locale}")


def candidate_files(target: Path) -> list[str]:
    """Files that a commit would contain: tracked + untracked, minus .gitignore'd."""
    if (target / ".git").exists():
        out = subprocess.run(
            ["git", "-C", str(target), "ls-files", "-co", "--exclude-standard", "-z"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
        return sorted({p for p in out.split("\0") if p})
    return sorted(
        p.relative_to(target).as_posix()
        for p in target.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(target).parts
    )


def check_forbidden_files(paths: list[str]) -> Check:
    bad = [p for p in paths if FORBIDDEN_NAMES.search(p) and not ALLOWED_FORBIDDEN.search(p)]
    if bad:
        return Check("secrets.files", "failed", "Files that usually hold secrets would be committed: " + ", ".join(bad))
    return Check("secrets.files", "verified", "No .env, private key, or credential files in the commit set")


def gitleaks_path() -> str | None:
    return shutil.which("gitleaks")


def scan_secrets(files: dict[str, str], *, required: bool) -> Check:
    """Run ``gitleaks dir`` over exactly the content that would be committed."""
    exe = gitleaks_path()
    if not exe:
        status = "failed" if required else "pending"
        return Check(
            "secrets.scan",
            status,
            "gitleaks is not installed; a public repository is not published without a local secret scan"
            if required
            else "gitleaks is not installed; local secret scan not run (CI scan still applies)",
        )
    with tempfile.TemporaryDirectory(prefix="repo-bootstrap-scan-") as tmp:
        root = Path(tmp)
        for rel, text in files.items():
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(text.encode("utf-8"))
        report = root.parent / (root.name + "-report.json")
        proc = subprocess.run(
            [
                exe,
                "dir",
                str(root),
                "--no-banner",
                "--redact",
                "--exit-code",
                "2",
                "--report-format",
                "json",
                "--report-path",
                str(report),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        findings = []
        if report.exists():
            try:
                findings = json.loads(report.read_text(encoding="utf-8") or "[]")
            finally:
                report.unlink()
    if proc.returncode == 0:
        return Check("secrets.scan", "verified", f"gitleaks found no secrets in {len(files)} files")
    if proc.returncode == 2:
        where = sorted(
            {
                f"{Path(x['File']).relative_to(root).as_posix()}:{x.get('StartLine')} ({x.get('RuleID')})"
                for x in findings
            }
        )
        return Check("secrets.scan", "failed", "gitleaks found possible secrets: " + ", ".join(where))
    return Check("secrets.scan", "failed", f"gitleaks exited {proc.returncode}: {proc.stderr.strip()[:300]}")


def scan_git_history(target: Path) -> Check:
    exe = gitleaks_path()
    if not exe:
        return Check("secrets.history", "failed", "gitleaks is not installed; history scan before push not run")
    proc = subprocess.run(
        [exe, "git", str(target), "--no-banner", "--redact", "--exit-code", "2"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode == 0:
        return Check("secrets.history", "verified", "gitleaks found no secrets in the commits to be pushed")
    return Check(
        "secrets.history",
        "failed",
        f"gitleaks reported findings or failed (exit {proc.returncode}); nothing was pushed",
    )


# ---------------------------------------------------------------- local CI


def _run(cmd: list[str], cwd: Path, timeout: int = 900) -> tuple[bool, str]:
    exe = shutil.which(cmd[0])
    if exe is None:
        return False, f"{cmd[0]} not found"
    try:
        proc = subprocess.run(
            [exe, *cmd[1:]],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"{' '.join(cmd)} timed out"
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-15:]
    return proc.returncode == 0, "\n".join(tail)


LOCAL_TOOLS = {"rust": ["cargo"], "python": [], "node": ["npm", "node"], "java-maven": ["mvn", "java"]}


def run_local_ci(files: list[PlannedFile], project_type: str, *, extra: dict[str, str] | None = None) -> Check:
    """Run the starter's lint/test/build in a throwaway copy of the generated tree."""
    if project_type == "generic":
        return Check("local_ci", "skipped_by_policy", "generic project: no commands to run")
    missing = [t for t in LOCAL_TOOLS[project_type] if shutil.which(t) is None]
    if missing:
        return Check(
            "local_ci",
            "pending",
            f"{', '.join(missing)} not installed locally; the first GitHub Actions run will verify",
        )
    with tempfile.TemporaryDirectory(prefix="repo-bootstrap-ci-") as tmp:
        root = Path(tmp)
        for f in files:
            dest = root / f.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f.content.encode("utf-8"))
        for rel, text in (extra or {}).items():
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(text.encode("utf-8"))
        if project_type == "rust":
            steps = [
                ["cargo", "fmt", "--all", "--", "--check"],
                ["cargo", "clippy", "--all-targets", "--all-features", "--locked", "--", "-D", "warnings"],
                ["cargo", "test", "--all-targets", "--all-features", "--locked"],
                ["cargo", "build", "--locked"],
            ]
        elif project_type == "node":
            steps = [["npm", "ci"], ["npm", "run", "lint"], ["npm", "test"], ["npm", "run", "build"]]
        elif project_type == "java-maven":
            steps = [["mvn", "--batch-mode", "--no-transfer-progress", "verify"]]
        else:
            ok, out = _run([sys.executable, "-m", "venv", ".venv"], root)
            if not ok:
                return Check("local_ci", "failed", f"python -m venv failed: {out}")
            py = root / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / "python"
            steps = [
                [str(py), "-m", "pip", "install", "--quiet", "-e", ".[dev]"],
                [str(py), "-m", "ruff", "check", "."],
                [str(py), "-m", "ruff", "format", "--check", "."],
                [str(py), "-m", "pytest", "-q"],
                [str(py), "-m", "build"],
            ]
        for step in steps:
            ok, out = _run(step, root)
            if not ok:
                return Check(
                    "local_ci",
                    "failed",
                    f"`{' '.join(Path(step[0]).name if i == 0 else s for i, s in enumerate(step))}` failed:\n{out}",
                )
    return Check("local_ci", "verified", f"{project_type} lint/test/build passed in a clean copy")
