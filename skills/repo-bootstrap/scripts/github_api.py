"""GitHub access through the ``gh`` CLI.

All REST calls go through :class:`GitHubClient`. It records every write, can
be put in read-only mode (``plan`` and ``verify`` use this), retries 429 and
5xx a limited number of times, and keeps 401/403/404/422 apart instead of
treating them all as "not on your plan".
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field

API_VERSION = "2022-11-28"
RETRY_STATUSES = {429, 500, 502, 503, 504}

Runner = Callable[[list[str], str | None], tuple[int, str, str]]


def default_runner(args: list[str], stdin: str | None) -> tuple[int, str, str]:
    proc = subprocess.run(args, input=stdin, capture_output=True, text=True, encoding="utf-8", check=False)
    return proc.returncode, proc.stdout, proc.stderr


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str, method: str = "", path: str = ""):
        self.status = status
        self.method = method
        self.path = path
        self.message = message
        super().__init__(f"{method} {path}: HTTP {status} {message}".strip())

    @property
    def kind(self) -> str:
        return {
            401: "auth",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "validation",
            429: "rate_limited",
        }.get(self.status, "server" if self.status >= 500 else "transport" if self.status <= 0 else "http")


class WriteBlocked(RuntimeError):
    """A write was attempted while the client is read-only."""


@dataclass
class Response:
    status: int
    data: object
    headers: dict[str, str] = field(default_factory=dict)


def parse_include_output(stdout: str) -> Response:
    """Split ``gh api --include`` output into status, headers, and JSON body."""
    text = stdout.lstrip()
    status = 0
    headers: dict[str, str] = {}
    body = ""
    # gh prints one header block per response; take the last status block.
    while text.startswith("HTTP/"):
        sep = "\r\n\r\n" if "\r\n\r\n" in text else "\n\n"
        head, _, rest = text.partition(sep)
        lines = head.splitlines()
        status = int(lines[0].split()[1])
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, _, val = line.partition(":")
                headers[k.strip().lower()] = val.strip()
        text = rest
        body = rest
    body = body.strip()
    data: object = None
    if body:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = body
    return Response(status, data, headers)


class GitHubClient:
    def __init__(
        self,
        runner: Runner = default_runner,
        *,
        read_only: bool = False,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 4,
    ):
        self.runner = runner
        self.read_only = read_only
        self.sleep = sleep
        self.max_attempts = max_attempts
        self.writes: list[tuple[str, str]] = []

    # ------------------------------------------------------------ low level
    def request(
        self, method: str, path: str, body: dict | None = None, *, accept: str = "application/vnd.github+json"
    ) -> Response:
        method = method.upper()
        if method != "GET":
            if self.read_only:
                raise WriteBlocked(f"{method} {path} attempted in read-only mode")
            self.writes.append((method, path))
        args = [
            "gh",
            "api",
            "--include",
            "-X",
            method,
            path,
            "-H",
            f"Accept: {accept}",
            "-H",
            f"X-GitHub-Api-Version: {API_VERSION}",
        ]
        stdin = None
        if body is not None:
            args += ["--input", "-"]
            stdin = json.dumps(body)
        last: Response | None = None
        for attempt in range(1, self.max_attempts + 1):
            _code, out, err = self.runner(args, stdin)
            resp = parse_include_output(out) if out.strip().startswith("HTTP/") else Response(0, None)
            if resp.status == 0:
                raise GitHubError(0, (err or out or "gh produced no HTTP response").strip()[:300], method, path)
            last = resp
            secondary = resp.status == 403 and "secondary rate limit" in json.dumps(resp.data or "").lower()
            if (resp.status in RETRY_STATUSES or secondary) and attempt < self.max_attempts:
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2.0**attempt
                self.sleep(min(delay, 60.0))
                continue
            break
        assert last is not None
        if last.status >= 400:
            msg = last.data.get("message", "") if isinstance(last.data, dict) else str(last.data or "")
            raise GitHubError(last.status, msg, method, path)
        return last

    def get(self, path: str, **kw) -> object:
        return self.request("GET", path, **kw).data

    def status_of(self, path: str) -> int:
        """GET returning the status; 404 becomes 404 instead of an exception."""
        try:
            return self.request("GET", path).status
        except GitHubError as exc:
            if exc.status == 404:
                return 404
            raise

    # ------------------------------------------------------------ identity
    def login(self) -> str:
        return self.get("user")["login"]

    def repo(self, owner: str, name: str) -> dict | None:
        try:
            return self.get(f"repos/{owner}/{name}")
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise

    # ------------------------------------------------------------ writes
    def create_user_repo(self, name: str, *, private: bool, description: str) -> dict:
        return self.request(
            "POST",
            "user/repos",
            {
                "name": name,
                "private": private,
                "description": description,
                "auto_init": False,
                "has_wiki": False,
            },
        ).data

    def patch_repo(self, owner: str, name: str, fields: dict) -> dict:
        return self.request("PATCH", f"repos/{owner}/{name}", fields).data

    def put(self, path: str, body: dict | None = None) -> Response:
        return self.request("PUT", path, body)

    def patch(self, path: str, body: dict) -> Response:
        return self.request("PATCH", path, body)

    def post(self, path: str, body: dict) -> Response:
        return self.request("POST", path, body)


# ====================================================================
# Settings: each feature has apply_* (write) and read_* (read-back).
# read_* never writes and returns (status, detail) using report statuses.
# ====================================================================

RULESET_NAME = "repo-bootstrap: default branch"
MERGE_SETTINGS = {"allow_squash_merge": True, "allow_merge_commit": False, "delete_branch_on_merge": True}


def describe_error(exc: GitHubError) -> str:
    hint = {
        "auth": "authentication failed; run `gh auth login`",
        "forbidden": "permission denied or feature not available for this account/plan",
        "not_found": "not found, or the token cannot see it",
        "validation": "GitHub rejected the request body",
        "rate_limited": "rate limited; retry later",
        "server": "GitHub server error; retry later",
        "conflict": "conflicting state on GitHub",
    }.get(exc.kind, "request failed")
    return f"HTTP {exc.status} ({hint}): {exc.message}".strip()


def read_merge_settings(client: GitHubClient, o: str, n: str) -> tuple[str, str]:
    repo = client.get(f"repos/{o}/{n}")
    wrong = [k for k, want in MERGE_SETTINGS.items() if repo.get(k) is not want]
    if wrong:
        return "failed", "Differs from policy: " + ", ".join(f"{k}={repo.get(k)}" for k in wrong)
    return "verified", "Squash merge only; head branches deleted on merge"


def apply_merge_settings(client: GitHubClient, o: str, n: str) -> None:
    client.patch_repo(o, n, dict(MERGE_SETTINGS))


def read_token_permissions(client: GitHubClient, o: str, n: str) -> tuple[str, str]:
    data = client.get(f"repos/{o}/{n}/actions/permissions/workflow")
    if data.get("default_workflow_permissions") == "read" and not data.get("can_approve_pull_request_reviews"):
        return "verified", "GITHUB_TOKEN defaults to read; Actions cannot approve PRs"
    return "failed", f"default_workflow_permissions={data.get('default_workflow_permissions')}"


def apply_token_permissions(client: GitHubClient, o: str, n: str) -> None:
    client.put(
        f"repos/{o}/{n}/actions/permissions/workflow",
        {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
    )


def read_dependabot_alerts(client: GitHubClient, o: str, n: str) -> tuple[str, str]:
    status = client.status_of(f"repos/{o}/{n}/vulnerability-alerts")
    return ("verified", "Dependabot alerts enabled") if status == 204 else ("failed", "Dependabot alerts are disabled")


def apply_dependabot_alerts(client: GitHubClient, o: str, n: str) -> None:
    client.put(f"repos/{o}/{n}/vulnerability-alerts")


def read_security_updates(client: GitHubClient, o: str, n: str) -> tuple[str, str]:
    try:
        data = client.get(f"repos/{o}/{n}/automated-security-fixes")
    except GitHubError as exc:
        if exc.status == 404:
            return "failed", "Dependabot security updates are disabled"
        raise
    if data.get("enabled") and not data.get("paused"):
        return "verified", "Dependabot security updates enabled"
    return "failed", f"Dependabot security updates enabled={data.get('enabled')} paused={data.get('paused')}"


def apply_security_updates(client: GitHubClient, o: str, n: str) -> None:
    client.put(f"repos/{o}/{n}/automated-security-fixes")


def _sa_status(client: GitHubClient, o: str, n: str, key: str) -> str | None:
    repo = client.get(f"repos/{o}/{n}")
    return ((repo.get("security_and_analysis") or {}).get(key) or {}).get("status")


def read_secret_scanning(client: GitHubClient, o: str, n: str) -> tuple[str, str]:
    st = _sa_status(client, o, n, "secret_scanning")
    return ("verified", "GitHub secret scanning enabled") if st == "enabled" else ("failed", f"secret_scanning={st}")


def read_push_protection(client: GitHubClient, o: str, n: str) -> tuple[str, str]:
    st = _sa_status(client, o, n, "secret_scanning_push_protection")
    return ("verified", "Push protection enabled") if st == "enabled" else ("failed", f"push_protection={st}")


def apply_secret_scanning(client: GitHubClient, o: str, n: str, *, push_protection: bool) -> None:
    sa = {"secret_scanning": {"status": "enabled"}}
    if push_protection:
        sa["secret_scanning_push_protection"] = {"status": "enabled"}
    client.patch_repo(o, n, {"security_and_analysis": sa})


def read_pvr(client: GitHubClient, o: str, n: str) -> tuple[str, str]:
    data = client.get(f"repos/{o}/{n}/private-vulnerability-reporting")
    if data.get("enabled"):
        return "verified", "Private vulnerability reporting enabled (Security > Advisories > Report a vulnerability)"
    return "failed", "Private vulnerability reporting is disabled"


def apply_pvr(client: GitHubClient, o: str, n: str) -> None:
    client.put(f"repos/{o}/{n}/private-vulnerability-reporting")


def read_codeql(client: GitHubClient, o: str, n: str) -> tuple[str, str]:
    data = client.get(f"repos/{o}/{n}/code-scanning/default-setup")
    state = data.get("state")
    langs = ", ".join(data.get("languages") or []) or "none detected yet"
    if state == "configured":
        return "verified", f"CodeQL default setup configured (languages: {langs})"
    return "failed", f"CodeQL default setup state={state}"


def apply_codeql(client: GitHubClient, o: str, n: str) -> None:
    client.patch(f"repos/{o}/{n}/code-scanning/default-setup", {"state": "configured", "query_suite": "default"})


def find_managed_ruleset(client: GitHubClient, o: str, n: str) -> tuple[dict | None, list[str]]:
    """Return the ruleset this skill manages and the names of other rulesets."""
    items = client.get(f"repos/{o}/{n}/rulesets?includes_parents=false") or []
    mine = None
    others = []
    for item in items:
        if item.get("name") == RULESET_NAME:
            mine = item
        else:
            others.append(item.get("name", "?"))
    return mine, others


def ruleset_body(level: str, status_checks: list[str]) -> dict:
    rules: list[dict] = [{"type": "deletion"}, {"type": "non_fast_forward"}]
    if level == "strict":
        rules.append(
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                },
            }
        )
        if status_checks:
            rules.append(
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": False,
                        "required_status_checks": [{"context": c} for c in status_checks],
                    },
                }
            )
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": rules,
    }


def apply_ruleset(client: GitHubClient, o: str, n: str, level: str, status_checks: list[str]) -> None:
    mine, _ = find_managed_ruleset(client, o, n)
    body = ruleset_body(level, status_checks)
    if mine:
        client.put(f"repos/{o}/{n}/rulesets/{mine['id']}", body)
    else:
        client.post(f"repos/{o}/{n}/rulesets", body)


def read_ruleset(client: GitHubClient, o: str, n: str, level: str) -> tuple[str, str]:
    mine, others = find_managed_ruleset(client, o, n)
    note = f"; other rulesets left untouched: {', '.join(others)}" if others else ""
    if not mine:
        return "failed", "Managed ruleset not found" + note
    full = client.get(f"repos/{o}/{n}/rulesets/{mine['id']}")
    types = {r["type"] for r in full.get("rules", [])}
    want = {"deletion", "non_fast_forward"} | ({"pull_request"} if level == "strict" else set())
    if full.get("enforcement") != "active" or not want <= types:
        return "failed", f"enforcement={full.get('enforcement')} rules={sorted(types)}" + note
    checks = [
        c["context"]
        for r in full.get("rules", [])
        if r["type"] == "required_status_checks"
        for c in r["parameters"]["required_status_checks"]
    ]
    extra = f"; required checks: {', '.join(checks)}" if checks else ""
    return "verified", f"Active on the default branch: {', '.join(sorted(types))}{extra}{note}"


def coderabbit_installed(client: GitHubClient) -> bool | None:
    """True/False when GitHub tells us; None when this token cannot list App installations."""
    try:
        data = client.get("user/installations?per_page=100")
    except GitHubError:
        return None
    for inst in (data or {}).get("installations", []):
        if inst.get("app_slug") in ("coderabbitai", "coderabbit-ai"):
            return True
    return False


def runs_for_sha(client: GitHubClient, o: str, n: str, sha: str) -> list[dict]:
    data = client.get(f"repos/{o}/{n}/actions/runs?head_sha={sha}&per_page=50")
    return (data or {}).get("workflow_runs", [])


def successful_check_names(client: GitHubClient, o: str, n: str, sha: str, workflow_path: str) -> list[str]:
    """Names of jobs that passed for one workflow file on a commit."""
    names = []
    for run in runs_for_sha(client, o, n, sha):
        if run.get("path", "").split("@")[0] != workflow_path or run.get("conclusion") != "success":
            continue
        jobs = client.get(f"repos/{o}/{n}/actions/runs/{run['id']}/jobs").get("jobs", [])
        names += [j["name"] for j in jobs if j.get("conclusion") == "success"]
    return sorted(set(names))


def file_content(client: GitHubClient, o: str, n: str, path: str, ref: str) -> str | None:
    import base64

    try:
        data = client.get(f"repos/{o}/{n}/contents/{path}?ref={ref}")
    except GitHubError as exc:
        if exc.status == 404:
            return None
        raise
    if isinstance(data, dict) and data.get("encoding") == "base64":
        return base64.b64decode(data["content"]).decode("utf-8")
    return None


def tree_paths(client: GitHubClient, o: str, n: str, ref: str) -> list[str]:
    data = client.get(f"repos/{o}/{n}/git/trees/{ref}?recursive=1")
    return [t["path"] for t in data.get("tree", []) if t.get("type") == "blob"]
