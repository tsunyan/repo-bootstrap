"""Shared test helpers: import path, fake pins, and a stateful fake ``gh api``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import policy  # noqa: E402
import scaffold  # noqa: E402

FAKE_SHA = "0123456789abcdef0123456789abcdef01234567"


def fake_pins(keys):
    return {k: {"repository": "example/action", "tag": "v1.2.3", "sha": FAKE_SHA} for k in keys}


def make(name="demo-cli", login="tsunyan", **kw):
    """Resolve a request and build its file plan without any network access."""
    req = policy.resolve(policy.BootstrapRequest(mode="plan", name=name, **kw), authenticated_login=login)
    decisions = policy.feature_plan(req)
    pins = fake_pins(scaffold.needed_actions(req, decisions))
    return req, decisions, pins


def plan_files(target=None, include_starter=True, **kw):
    req, decisions, pins = make(**kw)
    return req, decisions, scaffold.build_plan(req, decisions, pins, target=target, include_starter=include_starter)


def http(status, body=None, headers=None):
    reason = {
        200: "OK",
        201: "Created",
        202: "Accepted",
        204: "No Content",
        403: "Forbidden",
        404: "Not Found",
        422: "Unprocessable Entity",
        429: "Too Many Requests",
        503: "Service Unavailable",
    }.get(status, "X")
    head = [f"HTTP/2.0 {status} {reason}"] + [f"{k}: {v}" for k, v in (headers or {}).items()]
    return "\r\n".join(head) + "\r\n\r\n" + (json.dumps(body) if body is not None else "")


class FakeGitHub:
    """Answers the subset of the REST API that the skill uses, with mutable state."""

    def __init__(self, login="tsunyan", *, pvr_sticks=True, repo_exists=False, private=False):
        self.login = login
        self.calls: list[tuple[str, str, dict | None]] = []
        self.repo = None
        if repo_exists:
            self.repo = self._new_repo("demo-cli", private)
        self.pvr = False
        self.pvr_sticks = pvr_sticks
        self.alerts = False
        self.fixes = False
        self.token = {"default_workflow_permissions": "write", "can_approve_pull_request_reviews": True}
        self.codeql = "not-configured"
        self.rulesets: list[dict] = []
        self.queue: dict[str, list[str]] = {}

    def _new_repo(self, name, private):
        return {
            "name": name,
            "private": private,
            "default_branch": "main",
            "allow_squash_merge": True,
            "allow_merge_commit": True,
            "delete_branch_on_merge": False,
            "security_and_analysis": {
                "secret_scanning": {"status": "disabled"},
                "secret_scanning_push_protection": {"status": "disabled"},
            },
        }

    def __call__(self, args, stdin):
        method = args[args.index("-X") + 1]
        path = args[args.index("-X") + 2]
        body = json.loads(stdin) if stdin else None
        self.calls.append((method, path, body))
        if self.queue.get(path):
            return 0, self.queue[path].pop(0), ""
        return 0, self.route(method, path.split("?")[0], body), ""

    @property
    def writes(self):
        return [(m, p) for m, p, _ in self.calls if m != "GET"]

    def route(self, method, path, body):
        o_n = f"repos/{self.login}/demo-cli"
        if path == "user":
            return http(200, {"login": self.login})
        if path == "user/installations":
            return http(403, {"message": "You must authenticate with an access token authorized to a GitHub App"})
        if path.startswith(("repos/actions/", "repos/dtolnay/")):
            if path.endswith("releases/latest"):
                return http(200, {"tag_name": "v9.9.9", "draft": False, "prerelease": False})
            if "/branches/" in path:
                return http(200, {"commit": {"sha": "f" * 40}})
            return http(200, {"object": {"type": "commit", "sha": "e" * 40}})
        if path == "user/repos" and method == "POST":
            self.repo = self._new_repo(body["name"], body["private"])
            return http(201, self.repo)
        if path == o_n:
            if self.repo is None:
                return http(404, {"message": "Not Found"})
            if method == "PATCH":
                sa = body.pop("security_and_analysis", None)
                self.repo.update(body)
                if sa:
                    self.repo["security_and_analysis"].update(sa)
            return http(200, self.repo)
        if path == f"{o_n}/actions/permissions/workflow":
            if method == "PUT":
                self.token = dict(body)
                return http(204)
            return http(200, self.token)
        if path == f"{o_n}/vulnerability-alerts":
            if method == "PUT":
                self.alerts = True
                return http(204)
            return http(204) if self.alerts else http(404, {"message": "Not Found"})
        if path == f"{o_n}/automated-security-fixes":
            if method == "PUT":
                self.fixes = True
                return http(204)
            return http(200, {"enabled": self.fixes, "paused": False})
        if path == f"{o_n}/private-vulnerability-reporting":
            if method == "PUT":
                self.pvr = self.pvr_sticks
                return http(204)
            return http(200, {"enabled": self.pvr})
        if path == f"{o_n}/code-scanning/default-setup":
            if method == "PATCH":
                self.codeql = "configured"
                return http(202, {"run_id": 1})
            return http(200, {"state": self.codeql, "languages": ["actions"]})
        if path == f"{o_n}/rulesets":
            if method == "POST":
                rs = dict(body, id=len(self.rulesets) + 1)
                self.rulesets.append(rs)
                return http(201, rs)
            return http(200, [{"id": r["id"], "name": r["name"]} for r in self.rulesets])
        if path.startswith(f"{o_n}/rulesets/"):
            rid = int(path.rsplit("/", 1)[1])
            return http(200, next(r for r in self.rulesets if r["id"] == rid))
        if path.startswith(f"{o_n}/commits/"):
            return http(200, {"sha": "c" * 40})
        if path == f"{o_n}/actions/runs":
            return http(200, {"workflow_runs": []})
        return http(404, {"message": f"fake: no route for {method} {path}"})
