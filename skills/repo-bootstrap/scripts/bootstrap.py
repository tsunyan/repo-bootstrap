#!/usr/bin/env python3
"""repo-bootstrap: plan / create / adopt / verify / repair a GitHub repository.

Exit codes: 0 complete (possibly with constraints), 1 failed, 2 invalid input,
3 approval required (nothing was sent to GitHub).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions
import github_api as gh
import policy
import scaffold
import state
import validator
from report import Report

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_APPROVAL = 0, 1, 2, 3
COMMIT_MESSAGE = "chore: bootstrap repository with repo-bootstrap"
APPROVALS = ("create", "public", "license", "settings", "push")
SETTLE_DELAY = 2.0  # seconds between read-backs of eventually consistent settings
CI_POLL_INTERVAL = 15


def make_client(*, read_only: bool = False) -> gh.GitHubClient:
    """Factory so tests can inject a fake gh runner."""
    return gh.GitHubClient(read_only=read_only)


MANIFESTS = ("Cargo.toml", "pyproject.toml", "setup.py", "package.json", "pom.xml", "build.gradle")


# ====================================================================== CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bootstrap.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="mode", required=True)

    def common(sp, *, needs_name: bool):
        sp.add_argument("--name", required=needs_name, help="Repository name (required)")
        sp.add_argument("--repo", help="OWNER/REPO of an existing repository")
        sp.add_argument("--owner", help="GitHub user (default: the authenticated user)")
        sp.add_argument("--path", help="Local directory (default: ./NAME)")
        sp.add_argument("--type", dest="project_type", choices=policy.PROJECT_TYPES)
        sp.add_argument("--docs-locale", choices=policy.LOCALES)
        sp.add_argument("--visibility", choices=policy.VISIBILITIES)
        sp.add_argument("--repo-kind", choices=policy.REPO_KINDS)
        sp.add_argument("--license", help="MIT or none (Apache-2.0 is Phase 3)")
        sp.add_argument("--description-ja")
        sp.add_argument("--description-en")
        sp.add_argument("--overview-ja")
        sp.add_argument("--overview-en")
        sp.add_argument("--copyright-holder")
        sp.add_argument("--default-branch")
        sp.add_argument("--coderabbit", choices=policy.TRISTATE)
        sp.add_argument("--codeql", choices=policy.TRISTATE)
        sp.add_argument("--secret-scan", choices=policy.TRISTATE)
        sp.add_argument("--ruleset", choices=policy.RULESETS)
        sp.add_argument("--security-contact", choices=policy.SECURITY_CONTACTS)
        sp.add_argument("--security-email")
        sp.add_argument("--ci", choices=policy.TRISTATE)
        sp.add_argument("--secret", action="append", default=[], help="Secret NAME to register later (no values)")
        sp.add_argument("--node-version")
        sp.add_argument("--python-version")
        sp.add_argument("--java-version")
        sp.add_argument("--package-name", help="Override the derived package/module name")
        sp.add_argument("--approve", default="", help=f"Comma list of approvals: {', '.join(APPROVALS)}")
        sp.add_argument(
            "--refresh-actions", action="store_true", help="Re-resolve action SHAs instead of reusing the lock"
        )
        sp.add_argument("--skip-local-ci", action="store_true")
        sp.add_argument("--local-ci", action="store_true", help="plan: also run the starter's lint/test/build locally")
        sp.add_argument(
            "--wait-ci", type=int, default=900, help="Seconds to wait for the first CI run (0: do not wait)"
        )
        sp.add_argument("--report-dir")
        sp.add_argument("--format", choices=("text", "json"), default="text")

    common(sub.add_parser("plan", help="Show what would happen. Never writes to GitHub or disk."), needs_name=True)
    common(
        sub.add_parser("create", help="Generate locally, validate, then create the GitHub repository."), needs_name=True
    )
    for mode, text in (
        ("adopt", "Apply the standard files to an existing local clone without overwriting edits."),
        ("verify", "Read back files and GitHub settings. Read-only."),
        ("repair", "Re-apply settings and finish a partly completed create."),
    ):
        common(sub.add_parser(mode, help=text), needs_name=False)
    return p


@dataclass
class Ctx:
    args: argparse.Namespace
    client: gh.GitHubClient
    report: Report | None = None
    req: policy.BootstrapRequest | None = None
    decisions: list[policy.FeatureDecision] = field(default_factory=list)
    pins: dict[str, dict] = field(default_factory=dict)
    files: list[scaffold.PlannedFile] = field(default_factory=list)
    target: Path | None = None
    lock: dict | None = None


PROFILE_FIELDS = {
    "owner": "owner",
    "project_name": "name",
    "visibility": "visibility",
    "docs_locale": "docs_locale",
    "project_type": "project_type",
    "repo_kind": "repo_kind",
    "license": "license",
    "copyright_holder": "copyright_holder",
    "copyright_year": "copyright_year",
    "default_branch": "default_branch",
    "description_ja": "description_ja",
    "description_en": "description_en",
    "overview_ja": "overview_ja",
    "overview_en": "overview_en",
    "security_contact": "security_contact",
    "security_email": "security_email",
    "codeql": "codeql",
    "coderabbit": "coderabbit",
    "ruleset": "ruleset",
    "secret_scan": "secret_scan",
    "ci": "ci",
}
ARG_FIELDS = (
    "owner",
    "name",
    "project_type",
    "docs_locale",
    "visibility",
    "repo_kind",
    "license",
    "description_ja",
    "description_en",
    "overview_ja",
    "overview_en",
    "copyright_holder",
    "default_branch",
    "coderabbit",
    "codeql",
    "secret_scan",
    "ruleset",
    "security_contact",
    "security_email",
    "ci",
    "node_version",
    "python_version",
    "java_version",
    "package_name",
)


def request_from(args, mode: str, profile: dict | None = None) -> policy.BootstrapRequest:
    values: dict = {}
    for key, fld in PROFILE_FIELDS.items():
        if profile and profile.get(key) is not None:
            values[fld] = profile[key]
    for fld in ARG_FIELDS:
        v = getattr(args, fld, None)
        if v is not None:
            values[fld] = v
    if getattr(args, "repo", None):
        owner, _, name = args.repo.partition("/")
        values.setdefault("owner", owner)
        values.setdefault("name", name)
    if "name" not in values:
        raise policy.PolicyError("Pass --name, or --repo OWNER/REPO.")
    values["secrets"] = list(getattr(args, "secret", []) or [])
    values["mode"] = mode
    return policy.BootstrapRequest(**values)


def approvals_of(args) -> set[str]:
    given = {a.strip() for a in (args.approve or "").split(",") if a.strip()}
    unknown = given - set(APPROVALS)
    if unknown:
        raise policy.PolicyError(f"Unknown approval(s): {', '.join(sorted(unknown))}")
    return given


# ====================================================================== git


def git(target: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(target), *args], capture_output=True, text=True, encoding="utf-8", check=check
    )


def is_git_repo(target: Path) -> bool:
    return (
        target.is_dir()
        and git(target, "rev-parse", "--is-inside-work-tree", check=False).stdout.strip() == "true"
        and Path(git(target, "rev-parse", "--show-toplevel").stdout.strip()).resolve() == target.resolve()
    )


def dirty_paths(target: Path) -> list[str]:
    out = git(target, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    return sorted({entry[3:] for entry in out.split("\0") if len(entry) > 3})


def head_sha(target: Path) -> str | None:
    r = git(target, "rev-parse", "HEAD", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


# ====================================================================== preparation


def prepare(
    ctx: Ctx, mode: str, *, profile: dict | None = None, include_starter: bool = True, login: str | None = None
) -> None:
    args = ctx.args
    ctx.req = policy.resolve(request_from(args, mode, profile), authenticated_login=login)
    r = ctx.req
    ctx.report = Report(mode, f"{r.owner}/{r.name}", r.visibility, r.docs_locale, r.project_type)
    app = gh.coderabbit_installed(ctx.client) if login and r.coderabbit != "off" else None
    ctx.decisions = policy.feature_plan(r, coderabbit_app_installed=app)
    ctx.report.features = [{"id": d.id, "action": d.action, "detail": d.detail} for d in ctx.decisions]
    ctx.lock = state.load_lock(ctx.target) if ctx.target and ctx.target.is_dir() else None

    keys = scaffold.needed_actions(r, ctx.decisions)
    try:
        ctx.pins = actions.resolve(
            ctx.client, keys, previous=(ctx.lock or {}).get("actions"), refresh=args.refresh_actions
        )
        if keys:
            ctx.report.add(
                "actions.resolve",
                "verified",
                ", ".join(f"{p['repository']}@{p['tag']}={p['sha'][:12]}" for p in ctx.pins.values()),
            )
    except (actions.ActionResolutionError, gh.GitHubError) as exc:
        ctx.report.add("actions.resolve", "failed", f"Could not pin actions (fail closed): {exc}")
        ctx.pins = {k: {"repository": actions.ACTIONS[k][0], "tag": "unresolved", "sha": "<unresolved>"} for k in keys}
    ctx.files = scaffold.build_plan(r, ctx.decisions, ctx.pins, target=ctx.target, include_starter=include_starter)


def existing_contents(target: Path | None, skip: set[str]) -> dict[str, str]:
    """Text of files already in the commit set that the skill does not render."""
    out: dict[str, str] = {}
    if target is None or not target.is_dir():
        return out
    for rel in validator.candidate_files(target):
        if rel in skip:
            continue
        try:
            out[rel] = (target / rel).read_bytes().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary files are not scanned as text
    return out


def validate_local(ctx: Ctx, *, run_ci: bool) -> None:
    rep, files, r = ctx.report, ctx.files, ctx.req
    rep.add(*_c(validator.check_placeholders(files)))
    rep.extend(validator.check_workflows(validator.workflow_texts(files, ctx.target)))
    rep.add(*_c(validator.check_structured(files)))
    rep.add(*_c(validator.check_links(files, ctx.target)))
    rep.add(*_c(validator.check_locale(files, r.docs_locale)))
    planned = {f.path: f.content for f in files}
    others = existing_contents(ctx.target, set(planned) | {state.LOCK_PATH})
    commit_set = {**others, **planned}
    rep.add(*_c(validator.check_forbidden_files(sorted(commit_set))))
    rep.add(*_c(validator.scan_secrets(commit_set, required=r.visibility == "public")))
    if run_ci:
        rep.add(*_c(validator.run_local_ci(files, r.project_type)))
    elif r.project_type != "generic":
        rep.add("local_ci", "pending", "Not run in this mode")


def _c(check):
    return check.id, check.status, check.detail


def classify_into_report(ctx: Ctx) -> list[state.FileResult]:
    results = (
        state.classify(ctx.target, ctx.files, ctx.lock)
        if ctx.target
        else [state.FileResult(f.path, "created") for f in ctx.files]
    )
    ctx.report.files = [{"path": x.path, "status": x.status} for x in results]
    return results


def write_conflict_diffs(ctx: Ctx, results: list[state.FileResult], report_dir: Path | None) -> None:
    conflicts = [x for x in results if x.status == "conflict"]
    if not conflicts:
        return
    where = ""
    if report_dir:
        d = report_dir / "conflicts"
        d.mkdir(parents=True, exist_ok=True)
        for x in conflicts:
            (d / (x.path.replace("/", "__") + ".diff")).write_bytes((x.diff or "").encode("utf-8"))
        where = f" Diffs: {d}"
    ctx.report.add(
        "files.conflicts",
        "manual_action",
        f"Left unchanged because they differ from what the skill last wrote: "
        f"{', '.join(x.path for x in conflicts)}.{where}",
    )


def expected_state(ctx: Ctx) -> dict[str, str]:
    return {d.id: d.action for d in ctx.decisions}


def write_files(ctx: Ctx, results: list[state.FileResult]) -> None:
    state.apply(ctx.target, ctx.files, results)
    lock = state.build_lock(ctx.files, results, ctx.lock, ctx.pins, expected_state(ctx))
    state.write_lock(ctx.target, lock)
    ctx.lock = lock


def default_report_dir(ctx: Ctx) -> Path | None:
    if ctx.args.report_dir:
        return Path(ctx.args.report_dir)
    if ctx.target and (ctx.target / ".git").is_dir():
        return ctx.target / ".git" / "repo-bootstrap"
    return None


# ====================================================================== remote phase


def _settle(read, attempts: int = 4, delay: float | None = None):
    delay = SETTLE_DELAY if delay is None else delay
    status, detail = read()
    for _ in range(attempts - 1):
        if status == "verified":
            break
        time.sleep(delay)
        status, detail = read()
    return status, detail


def apply_setting(ctx: Ctx, fid: str, apply_fn, read_fn) -> str:
    o, n = ctx.req.owner, ctx.req.name
    try:
        status, detail = read_fn(ctx.client, o, n)
        if status == "verified":
            ctx.report.add(fid, "verified", detail + " (already set)")
            return "verified"
        apply_fn(ctx.client, o, n)
        status, detail = _settle(lambda: read_fn(ctx.client, o, n))
        if status != "verified":
            detail = "Write accepted, but read-back disagrees: " + detail
        ctx.report.add(fid, status, detail)
        return status
    except gh.GitHubError as exc:
        ctx.report.add(fid, "failed", gh.describe_error(exc) + f". Retry with `bootstrap.py repair --repo {o}/{n}`")
        return "failed"


SETTINGS = [
    ("repo.merge_settings", gh.apply_merge_settings, gh.read_merge_settings),
    ("actions.token_permissions", gh.apply_token_permissions, gh.read_token_permissions),
    ("dependabot.alerts", gh.apply_dependabot_alerts, gh.read_dependabot_alerts),
    ("dependabot.security_updates", gh.apply_security_updates, gh.read_security_updates),
    (
        "secret_scanning",
        lambda c, o, n: gh.apply_secret_scanning(c, o, n, push_protection=False),
        gh.read_secret_scanning,
    ),
    (
        "push_protection",
        lambda c, o, n: gh.apply_secret_scanning(c, o, n, push_protection=True),
        gh.read_push_protection,
    ),
    ("private_vulnerability_reporting", gh.apply_pvr, gh.read_pvr),
]


def record_non_applied(ctx: Ctx) -> None:
    for d in ctx.decisions:
        if d.action != "apply":
            ctx.report.add(d.id, d.action, d.detail)


def push(ctx: Ctx) -> bool:
    r, target = ctx.req, ctx.target
    url = f"https://github.com/{r.owner}/{r.name}.git"
    remote = git(target, "remote", "get-url", "origin", check=False)
    if remote.returncode != 0:
        git(target, "remote", "add", "origin", url)
    elif remote.stdout.strip().removesuffix(".git").lower() != url.removesuffix(".git").lower():
        ctx.report.add("git.push", "failed", f"origin points to {remote.stdout.strip()}, not {url}; nothing pushed")
        return False
    local = head_sha(target)
    ls = git(target, "ls-remote", "origin", f"refs/heads/{r.default_branch}", check=False)
    remote_sha = ls.stdout.split()[0] if ls.returncode == 0 and ls.stdout.strip() else None
    if remote_sha == local:
        ctx.report.add("git.push", "verified", f"{r.default_branch} is already at {local[:12]} on GitHub")
        return True
    if remote_sha and git(target, "merge-base", "--is-ancestor", remote_sha, local, check=False).returncode != 0:
        ctx.report.add("git.push", "failed", "Remote branch has commits that are not local; not force-pushing")
        return False
    res = git(target, "push", "-u", "origin", f"HEAD:refs/heads/{r.default_branch}", check=False)
    if res.returncode != 0:
        ctx.report.add(
            "git.push",
            "failed",
            f"git push failed (run `gh auth setup-git` if HTTPS credentials are missing): {res.stderr.strip()[-300:]}",
        )
        return False
    ls = git(target, "ls-remote", "origin", f"refs/heads/{r.default_branch}", check=False)
    if ls.stdout.split()[:1] == [local]:
        ctx.report.add("git.push", "verified", f"Pushed {local[:12]} to {r.default_branch}")
        return True
    ctx.report.add("git.push", "failed", "Push reported success but the remote branch does not match")
    return False


def wait_for_runs(ctx: Ctx, sha: str, workflow_paths: list[str]) -> dict[str, dict]:
    o, n = ctx.req.owner, ctx.req.name
    deadline = time.monotonic() + max(ctx.args.wait_ci, 0)
    latest: dict[str, dict] = {}
    while True:
        try:
            runs = gh.runs_for_sha(ctx.client, o, n, sha)
        except gh.GitHubError:
            runs = []
        latest = {}
        for run in sorted(runs, key=lambda x: x.get("id", 0)):
            latest[run.get("path", "").split("@")[0]] = run
        done = all(p in latest and latest[p].get("status") == "completed" for p in workflow_paths)
        if done or time.monotonic() >= deadline:
            return latest
        time.sleep(CI_POLL_INTERVAL)


def report_runs(ctx: Ctx, workflow_paths: list[str], latest: dict[str, dict]) -> dict[str, str]:
    out = {}
    for path in workflow_paths:
        fid = {".github/workflows/ci.yml": "ci", ".github/workflows/secret-scan.yml": "gitleaks"}.get(
            path, f"workflow:{Path(path).name}"
        )
        run = latest.get(path)
        if not run:
            status, detail = "pending", f"{path}: no run has been reported yet"
        elif run.get("status") != "completed":
            status, detail = "pending", f"{path}: run {run['id']} is {run.get('status')}"
        elif run.get("conclusion") == "success":
            status, detail = "verified", f"{path}: run {run['id']} succeeded"
        else:
            status, detail = (
                "failed",
                f"{path}: run {run['id']} concluded {run.get('conclusion')} ({run.get('html_url')})",
            )
        ctx.report.add(fid, status, detail)
        out[path] = status
    return out


def remote_phase(ctx: Ctx, *, create_repo: bool, do_push: bool) -> None:
    r, client, rep = ctx.req, ctx.client, ctx.report
    o, n = r.owner, r.name
    record_non_applied(ctx)
    try:
        repo = client.repo(o, n)
        if repo is None:
            if not create_repo:
                rep.add("repo.exists", "failed", f"{o}/{n} does not exist on GitHub")
                return
            desc = r.description_en if r.docs_locale == "en" else r.description_ja
            desc = desc or scaffold.default_texts(r)["PROJECT_DESCRIPTION_" + ("EN" if r.docs_locale == "en" else "JA")]
            client.create_user_repo(n, private=r.visibility == "private", description=desc)
            rep.add("repo.create", "applied", f"Created empty {r.visibility} repository {o}/{n}")
            repo = client.repo(o, n)
        want_private = r.visibility == "private"
        if repo is None or bool(repo.get("private")) != want_private:
            rep.add(
                "repo.visibility",
                "failed",
                f"GitHub says {'private' if repo and repo.get('private') else 'public'}, profile says "
                f"{r.visibility}. Visibility is never changed automatically; change it yourself after "
                "re-confirming what becomes public.",
            )
            return
        rep.add("repo.visibility", "verified", f"{o}/{n} is {r.visibility}")
    except gh.GitHubError as exc:
        rep.add("repo.create" if create_repo else "repo.exists", "failed", gh.describe_error(exc))
        return

    applies = {d.id for d in ctx.decisions if d.action == "apply"}
    for fid, apply_fn, read_fn in SETTINGS:
        if fid in applies:
            apply_setting(ctx, fid, apply_fn, read_fn)

    pvr = next((c for c in rep.checks if c.id == "private_vulnerability_reporting"), None)
    if "private_vulnerability_reporting" in applies and (pvr is None or pvr.status != "verified"):
        rep.add(
            "git.push",
            "failed",
            "Push held: SECURITY.md points to private vulnerability reporting, "
            "which is not enabled. Nothing public was pushed.",
        )
        rep.add(
            "pvr.manual",
            "manual_action",
            f"Enable Settings > Security > Private vulnerability reporting for {o}/{n}, "
            f"then run `bootstrap.py repair --repo {o}/{n} --path <clone> --approve settings,push`",
        )
        return

    sha = None
    if do_push and ctx.target:
        if not push(ctx):
            return
        sha = head_sha(ctx.target)
    else:
        try:
            sha = client.get(f"repos/{o}/{n}/commits/{r.default_branch}")["sha"]
        except gh.GitHubError:
            sha = None

    if "codeql" in applies and sha:
        apply_setting(ctx, "codeql", gh.apply_codeql, gh.read_codeql)

    verify_secret_names(ctx)

    workflow_paths = sorted({p for p in validator.workflow_texts(ctx.files, ctx.target)})
    if sha and workflow_paths and ctx.args.wait_ci > 0:
        latest = wait_for_runs(ctx, sha, workflow_paths)
        statuses = report_runs(ctx, workflow_paths, latest)
    elif workflow_paths:
        statuses = {}
        for p in workflow_paths:
            fid = {".github/workflows/ci.yml": "ci", ".github/workflows/secret-scan.yml": "gitleaks"}.get(
                p, f"workflow:{Path(p).name}"
            )
            rep.add(fid, "pending" if sha else "applied", f"{p}: first run not checked (--wait-ci 0)")
    else:
        statuses = {}

    if "ruleset.main" in applies and sha:
        checks: list[str] = []
        if r.ruleset == "strict":
            if statuses.get(".github/workflows/ci.yml") == "verified":
                checks = gh.successful_check_names(client, o, n, sha, ".github/workflows/ci.yml")
            else:
                rep.add(
                    "ruleset.required_checks",
                    "pending",
                    "Required status checks are added only after CI has passed once; run repair later",
                )
        try:
            gh.apply_ruleset(client, o, n, r.ruleset, checks)
            status, detail = _settle(lambda: gh.read_ruleset(client, o, n, r.ruleset))
            rep.add("ruleset.main", status, detail)
        except gh.GitHubError as exc:
            rep.add("ruleset.main", "failed", gh.describe_error(exc))

    if "coderabbit" in applies:
        rep.add(
            "coderabbit", "applied", "App is installed and .coderabbit.yaml is present; no review has been observed yet"
        )


def verify_secret_names(ctx: Ctx) -> None:
    r = ctx.req
    if not r.secrets:
        return
    try:
        data = ctx.client.get(f"repos/{r.owner}/{r.name}/actions/secrets?per_page=100")
        have = {s["name"] for s in data.get("secrets", [])}
    except gh.GitHubError as exc:
        ctx.report.add("secrets", "failed", gh.describe_error(exc))
        return
    for name in r.secrets:
        if name in have:
            ctx.report.add(f"secret:{name}", "verified", f"Secret {name} exists (value is never read)")
        else:
            ctx.report.add(
                f"secret:{name}",
                "manual_action",
                f"Set it yourself: `gh secret set {name} --repo {r.owner}/{r.name}` (type the value at the prompt)",
            )


# ====================================================================== commands


def cmd_plan(args) -> tuple[Report, int]:
    client = make_client(read_only=True)
    login = _try_login(client)
    ctx = Ctx(args, client, target=Path(args.path).resolve() if args.path else None)
    prepare(ctx, "plan", login=login)
    rep = ctx.report
    validate_local(ctx, run_ci=args.local_ci)
    if ctx.target and ctx.target.exists():
        results = classify_into_report(ctx)
        if any(x.status == "conflict" for x in results):
            rep.add(
                "files.conflicts",
                "manual_action",
                "Some files differ from the rendered version and would not be overwritten",
            )
    else:
        rep.files = [{"path": f.path, "status": "created"} for f in ctx.files]
    if login:
        exists = client.repo(ctx.req.owner, ctx.req.name)
        rep.add(
            "repo.exists",
            "manual_action" if exists else "verified",
            f"{ctx.req.owner}/{ctx.req.name} already exists: use adopt"
            if exists
            else f"{ctx.req.owner}/{ctx.req.name} does not exist yet",
        )
    else:
        rep.add("github.auth", "pending", "gh is not authenticated; GitHub state was not read")
    rep.approvals_required = policy.required_approvals(ctx.req)
    rep.notes.append(f"plan made {len(client.writes)} GitHub writes and wrote no files")
    return rep, EXIT_FAILED if rep.failures else EXIT_OK


def _try_login(client: gh.GitHubClient) -> str | None:
    try:
        return client.login()
    except (gh.GitHubError, OSError):
        return None


def preflight_tools(rep: Report, needs: tuple[str, ...]) -> bool:
    missing = [t for t in needs if shutil.which(t) is None]
    if missing:
        rep.add("preflight.tools", "failed", f"Missing: {', '.join(missing)}")
        return False
    rep.add("preflight.tools", "verified", "Found " + ", ".join(needs) + f"; Python {sys.version.split()[0]}")
    return True


def cmd_create(args) -> tuple[Report, int]:
    client = make_client()
    login = client.login()
    target = Path(args.path or Path.cwd() / args.name).resolve()
    ctx = Ctx(args, client, target=target)
    prepare(ctx, "create", login=login)
    r, rep = ctx.req, ctx.report
    if not preflight_tools(rep, ("git", "gh")):
        return rep, EXIT_FAILED
    if r.owner.lower() != login.lower():
        rep.add(
            "preflight.owner",
            "failed",
            f"Only repositories owned by the authenticated user ({login}) are supported in v1",
        )
        return rep, EXIT_FAILED
    rep.add("preflight.owner", "verified", f"Authenticated as {login}")
    if client.repo(r.owner, r.name) is not None:
        rep.add("repo.exists", "failed", f"{r.owner}/{r.name} already exists. Use `adopt` instead; nothing was changed")
        return rep, EXIT_FAILED

    if target.exists() and any(target.iterdir()) and not is_git_repo(target):
        rep.add("preflight.path", "failed", f"{target} is not empty and is not the top of a Git work tree")
        return rep, EXIT_FAILED

    validate_local(ctx, run_ci=not args.skip_local_ci)
    results = classify_into_report(ctx)
    if any(x.status == "conflict" for x in results):
        write_conflict_diffs(ctx, results, default_report_dir(ctx))
        rep.add("files.conflicts", "failed", "Existing files differ from the rendered ones; nothing was written")
    if is_git_repo(target):
        status_by = {x.path: x.status for x in results}
        stray = [p for p in dirty_paths(target) if p != state.LOCK_PATH and status_by.get(p) not in ("unchanged",)]
        if stray:
            rep.add(
                "preflight.worktree",
                "failed",
                "Commit or stash these changes first (the skill commits only what it generates): "
                + ", ".join(stray[:20]),
            )
    if rep.failures:
        return rep, EXIT_FAILED
    rep.add("preflight.path", "verified", f"Local tree: {target}")

    target.mkdir(parents=True, exist_ok=True)
    if not is_git_repo(target):
        git(target, "init", "-b", r.default_branch)
    write_files(ctx, results)

    missing = [a for a in policy.required_approvals(r) if a not in approvals_of(args)]
    if missing:
        rep.approvals_required = missing
        record_non_applied(ctx)
        rep.notes.append(
            f"Files were generated in {target}. Nothing was committed, created, or pushed. "
            f"Re-run with --approve {','.join(policy.required_approvals(r))} after the user agrees."
        )
        return rep, EXIT_APPROVAL

    # Commit exactly the generated files.
    paths = [f.path for f in ctx.files] + [state.LOCK_PATH]
    git(target, "add", "--", *paths)
    if git(target, "diff", "--cached", "--quiet", check=False).returncode != 0:
        if not git(target, "config", "user.email", check=False).stdout.strip():
            rep.add("git.commit", "failed", "git user.email is not configured")
            return rep, EXIT_FAILED
        git(target, "commit", "-m", COMMIT_MESSAGE)
        rep.add("git.commit", "verified", f"Committed {len(paths)} generated files as {head_sha(target)[:12]}")
    else:
        rep.add("git.commit", "verified", "Generated files were already committed")

    hist = validator.scan_git_history(target)
    if hist.status != "verified" and r.visibility == "public":
        rep.add(*_c(hist))
        return rep, EXIT_FAILED
    rep.add(hist.id, hist.status if hist.status == "verified" else "pending", hist.detail)

    remote_phase(ctx, create_repo=True, do_push=True)
    return finish(ctx)


def finish(ctx: Ctx) -> tuple[Report, int]:
    ctx.report.stamp()
    return ctx.report, EXIT_FAILED if ctx.report.failures else EXIT_OK


def load_profile_for(args, client: gh.GitHubClient, target: Path | None) -> tuple[dict | None, str | None]:
    """Profile from the local clone, else from the default branch on GitHub."""
    if target and (target / ".repo-bootstrap.yml").is_file():
        return scaffold.read_profile(target / ".repo-bootstrap.yml"), "local"
    if args.repo:
        o, _, n = args.repo.partition("/")
        repo = client.repo(o, n)
        if repo:
            text = gh.file_content(client, o, n, ".repo-bootstrap.yml", repo.get("default_branch", "main"))
            if text:
                return scaffold.parse_profile(text), "remote"
            return {"visibility": "private" if repo.get("private") else "public"}, "inferred"
    return None, None


def repo_from_origin(target: Path) -> str | None:
    r = git(target, "remote", "get-url", "origin", check=False)
    url = r.stdout.strip().removesuffix(".git")
    for prefix in ("https://github.com/", "git@github.com:"):
        if url.startswith(prefix):
            return url[len(prefix) :]
    return None


def cmd_verify(args) -> tuple[Report, int]:
    client = make_client(read_only=True)
    login = client.login()
    target = Path(args.path).resolve() if args.path else None
    if not args.repo and target:
        args.repo = repo_from_origin(target)
    if not args.repo:
        raise policy.PolicyError("verify needs --repo OWNER/REPO (or --path to a clone with an origin)")
    profile, source = load_profile_for(args, client, None)
    o, _, n = args.repo.partition("/")
    repo = client.repo(o, n)
    ctx = Ctx(args, client, target=None)
    if repo is None:
        rep = Report("verify", args.repo, "?", "?", "?")
        rep.add("repo.exists", "failed", f"{args.repo} not found or not visible to this token")
        return rep, EXIT_FAILED
    profile = profile or {}
    profile.setdefault("visibility", "private" if repo.get("private") else "public")
    prepare(ctx, "verify", profile=profile, login=login)
    rep, r = ctx.report, ctx.req
    rep.add(
        "profile.source",
        "verified" if source in ("local", "remote") else "pending",
        {
            "remote": ".repo-bootstrap.yml read from the default branch",
            "local": ".repo-bootstrap.yml read from the local clone",
        }.get(source, "No .repo-bootstrap.yml; defaults inferred from visibility"),
    )
    branch = repo.get("default_branch") or "main"
    actual = "private" if repo.get("private") else "public"
    rep.add(
        "repo.visibility",
        "verified" if actual == r.visibility else "failed",
        f"GitHub: {actual}; profile: {r.visibility}",
    )

    try:
        present = set(gh.tree_paths(client, o, n, branch))
    except gh.GitHubError as exc:
        rep.add("files.present", "failed", gh.describe_error(exc))
        present = set()
    expected = [f.path for f in ctx.files if f.kind != "starter"] + [state.LOCK_PATH]
    missing = [p for p in expected if p not in present]
    rep.add(
        "files.present",
        "failed" if missing else "verified",
        ("Missing on " + branch + ": " + ", ".join(missing)) if missing else f"{len(expected)} standard files present",
    )

    fetched = []
    for f in ctx.files:
        if f.path in present and (f.path.endswith(".md") or f.path.startswith(".github/")):
            text = gh.file_content(client, o, n, f.path, branch)
            if text is not None:
                fetched.append(scaffold.PlannedFile(f.path, text, f.template, f.kind))
    workflows = {
        p: gh.file_content(client, o, n, p, branch) or ""
        for p in present
        if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
    }
    rep.add(*_c(validator.check_placeholders(fetched)))
    rep.extend(validator.check_workflows(workflows))
    if source in ("local", "remote"):
        rep.add(*_c(validator.check_locale(fetched, r.docs_locale)))

    applies = {d.id for d in ctx.decisions if d.action == "apply"}
    record_non_applied(ctx)
    for fid, _apply, read_fn in SETTINGS:
        if fid in applies:
            _read_only(ctx, fid, lambda read_fn=read_fn: read_fn(client, o, n))
    if "codeql" in applies:
        _read_only(ctx, "codeql", lambda: gh.read_codeql(client, o, n))
    if "ruleset.main" in applies:
        _read_only(ctx, "ruleset.main", lambda: gh.read_ruleset(client, o, n, r.ruleset))
    if "coderabbit" in applies:
        rep.add("coderabbit", "applied", "App installed; review activity is not checked by verify")

    try:
        sha = client.get(f"repos/{o}/{n}/commits/{branch}")["sha"]
        runs = {}
        for run in sorted(gh.runs_for_sha(client, o, n, sha), key=lambda x: x.get("id", 0)):
            runs[run.get("path", "").split("@")[0]] = run
        report_runs(ctx, sorted(workflows), runs)
    except gh.GitHubError as exc:
        rep.add("ci", "failed", gh.describe_error(exc))
    verify_secret_names(ctx)
    rep.notes.append(f"verify made {len(client.writes)} GitHub writes")
    return finish(ctx)


def _read_only(ctx: Ctx, fid: str, read) -> None:
    try:
        status, detail = read()
    except gh.GitHubError as exc:
        status, detail = "failed", gh.describe_error(exc)
    ctx.report.add(fid, status, detail)


def cmd_repair(args) -> tuple[Report, int]:
    client = make_client()
    login = client.login()
    target = Path(args.path).resolve() if args.path else None
    if target and not args.repo:
        args.repo = repo_from_origin(target)
    profile, _ = load_profile_for(args, client, target)
    if profile is None:
        raise policy.PolicyError("repair needs --repo OWNER/REPO or --path to a clone with .repo-bootstrap.yml")
    ctx = Ctx(args, client, target=target)
    prepare(ctx, "repair", profile=profile, login=login)
    given = approvals_of(args)
    needed = ["settings"] + (["push"] if target else [])
    missing = [a for a in needed if a not in given]
    if missing:
        ctx.report.approvals_required = missing
        record_non_applied(ctx)
        ctx.report.notes.append(
            "repair re-applies GitHub settings"
            + (" and pushes local commits" if target else "")
            + ". Nothing was changed."
        )
        return ctx.report, EXIT_APPROVAL
    remote_phase(ctx, create_repo=False, do_push=bool(target))
    return finish(ctx)


def cmd_adopt(args) -> tuple[Report, int]:
    client = make_client()
    login = client.login()
    if not args.path:
        raise policy.PolicyError("adopt needs --path to an existing local clone")
    target = Path(args.path).resolve()
    if not is_git_repo(target):
        raise policy.PolicyError(f"{target} is not the top of a Git work tree")
    if not args.repo:
        args.repo = repo_from_origin(target)
    profile, _ = load_profile_for(args, client, target)
    profile = dict(profile or {})
    if args.repo and "visibility" not in profile:
        o, _, n = args.repo.partition("/")
        repo = client.repo(o, n)
        if repo:
            profile["visibility"] = "private" if repo.get("private") else "public"
    has_manifest = any((target / m).exists() for m in MANIFESTS)
    ctx = Ctx(args, client, target=target)
    prepare(ctx, "adopt", profile=profile, login=login, include_starter=not has_manifest)
    r, rep = ctx.req, ctx.report
    if has_manifest and r.project_type != "generic" and r.ci == "auto":
        ctx.decisions = [
            d
            if d.id != "ci"
            else policy.FeatureDecision(
                "ci",
                "manual_action",
                "Existing project: CI was not generated because its commands were not "
                "verified. Check them and re-run with --ci on",
            )
            for d in ctx.decisions
        ]
        ctx.files = scaffold.build_plan(r, ctx.decisions, ctx.pins, target=target, include_starter=False)
    if has_manifest and r.project_type == "node" and r.ci == "on":
        scripts = json.loads((target / "package.json").read_text(encoding="utf-8")).get("scripts", {})
        lacking = [s for s in ("lint", "test", "build") if s not in scripts]
        if lacking:
            raise policy.PolicyError(f"package.json has no {', '.join(lacking)} script(s); CI would call them")
    validate_local(ctx, run_ci=not has_manifest and not args.skip_local_ci)
    results = classify_into_report(ctx)
    if rep.failures:
        return rep, EXIT_FAILED
    write_conflict_diffs(ctx, results, default_report_dir(ctx))
    write_files(ctx, results)
    rep.notes.append("adopt wrote files locally and did not commit or push. Review `git status`.")
    if "settings" in approvals_of(args) and client.repo(r.owner, r.name):
        remote_phase(ctx, create_repo=False, do_push=False)
    else:
        record_non_applied(ctx)
        rep.notes.append("GitHub settings were not changed (pass --approve settings to apply them).")
    return finish(ctx)


COMMANDS = {"plan": cmd_plan, "create": cmd_create, "adopt": cmd_adopt, "verify": cmd_verify, "repair": cmd_repair}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        rep, code = COMMANDS[args.mode](args)
    except (policy.PolicyError, scaffold.ScaffoldError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except gh.WriteBlocked as exc:  # a bug, not a user error
        print(f"internal error: {exc}", file=sys.stderr)
        return EXIT_FAILED
    except gh.GitHubError as exc:
        print(f"error: {gh.describe_error(exc)}", file=sys.stderr)
        return EXIT_FAILED
    ctx_dir = Path(args.report_dir) if args.report_dir else None
    if ctx_dir is None and args.mode in ("create", "adopt", "repair"):
        base = Path(args.path).resolve() if args.path else (Path.cwd() / (args.name or "")).resolve()
        if (base / ".git").is_dir():
            ctx_dir = base / ".git" / "repo-bootstrap"
    if ctx_dir:
        rep.notes.append(f"Report: {ctx_dir / 'bootstrap-report.json'} (and .md)")
        rep.write(ctx_dir)
    print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False) if args.format == "json" else rep.to_markdown())
    return code


if __name__ == "__main__":
    sys.exit(main())
