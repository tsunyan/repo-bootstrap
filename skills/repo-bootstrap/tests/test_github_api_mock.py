"""T13/T15/T20 and design §12.1: plan never writes; errors are told apart; push waits for PVR."""

import argparse
import contextlib
import io
import json
import unittest
from unittest import mock

import actions
import bootstrap
import github_api as gh
import policy
import validator
from helpers import FakeGitHub, http

bootstrap.SETTLE_DELAY = 0


class Client(unittest.TestCase):
    def test_include_parsing(self):
        r = gh.parse_include_output(http(200, {"a": 1}, {"Retry-After": "3"}))
        self.assertEqual((r.status, r.data, r.headers["retry-after"]), (200, {"a": 1}, "3"))
        self.assertEqual(gh.parse_include_output(http(204)).data, None)

    def test_retry_then_success(self):
        fake = FakeGitHub()
        fake.queue["user"] = [http(503, {"message": "busy"}), http(429, {"message": "slow"}, {"Retry-After": "1"})]
        slept = []
        client = gh.GitHubClient(fake, sleep=slept.append)
        self.assertEqual(client.login(), "tsunyan")
        self.assertEqual(len(slept), 2)
        self.assertEqual(slept[1], 1.0)

    def test_error_kinds_are_distinct(self):
        for status, kind in ((401, "auth"), (403, "forbidden"), (404, "not_found"), (422, "validation")):
            fake = FakeGitHub()
            fake.queue["user"] = [http(status, {"message": "m"})]
            with self.assertRaises(gh.GitHubError) as cm:
                gh.GitHubClient(fake, sleep=lambda s: None).login()
            self.assertEqual(cm.exception.kind, kind)

    def test_read_only_blocks_writes(self):
        client = gh.GitHubClient(FakeGitHub(), read_only=True)
        with self.assertRaises(gh.WriteBlocked):
            client.put("repos/x/y/vulnerability-alerts")


class ActionPins(unittest.TestCase):
    def test_annotated_tag_is_dereferenced(self):
        fake = FakeGitHub()
        fake.queue["repos/actions/checkout/git/ref/tags/v9.9.9"] = [
            http(200, {"object": {"type": "tag", "sha": "a" * 40}})
        ]
        fake.queue["repos/actions/checkout/git/tags/" + "a" * 40] = [
            http(200, {"object": {"type": "commit", "sha": "b" * 40}})
        ]
        pin = actions.resolve_one(gh.GitHubClient(fake), "ACTION_CHECKOUT")
        self.assertEqual(pin, {"repository": "actions/checkout", "tag": "v9.9.9", "sha": "b" * 40})

    def test_fail_closed(self):
        fake = FakeGitHub()
        fake.queue["repos/actions/checkout/releases/latest"] = [http(200, {"tag_name": "main"})]
        with self.assertRaises(actions.ActionResolutionError):
            actions.resolve_one(gh.GitHubClient(fake), "ACTION_CHECKOUT")
        with self.assertRaises(actions.ActionResolutionError):
            actions.resolve_one(gh.GitHubClient(fake), "ACTION_SOMETHING_ELSE")

    def test_lock_pins_are_reused(self):
        prev = {"ACTION_CHECKOUT": {"repository": "actions/checkout", "tag": "v1.0.0", "sha": "d" * 40}}
        fake = FakeGitHub()
        out = actions.resolve(gh.GitHubClient(fake), ["ACTION_CHECKOUT"], previous=prev)
        self.assertEqual(out, prev)
        self.assertEqual(fake.calls, [])


class Commands(unittest.TestCase):
    def run_cli(self, fake, argv):
        original = bootstrap.make_client
        bootstrap.make_client = lambda read_only=False: gh.GitHubClient(fake, read_only=read_only, sleep=lambda s: None)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = bootstrap.main(argv + ["--format", "json"])
            return code, json.loads(out.getvalue())
        finally:
            bootstrap.make_client = original

    def test_plan_makes_no_writes(self):
        fake = FakeGitHub()
        with mock.patch.object(validator, "gitleaks_path", return_value=None):
            code, rep = self.run_cli(fake, ["plan", "--name", "demo-cli", "--type", "node"])
        self.assertEqual(fake.writes, [])
        self.assertEqual(rep["approvals_required"], ["create", "public", "license"])
        # Without gitleaks a public repository must not pass the local gate.
        failed = {c["id"] for c in rep["failures"]}
        self.assertEqual(failed, {"secrets.scan"})
        self.assertEqual((rep["outcome"], code), ("failed", 1))

    def test_plan_without_findings_waits_for_approval(self):
        fake = FakeGitHub()
        clean = validator.Check("secrets.scan", "verified", "stubbed")
        argv = ["plan", "--name", "demo-cli", "--type", "node", "--docs-locale", "en-ja", "--visibility", "public"]
        with mock.patch.object(validator, "scan_secrets", return_value=clean):
            code, rep = self.run_cli(fake, argv)
        self.assertEqual(fake.writes, [])
        self.assertEqual(rep["choices_required"], [])
        self.assertEqual((rep["outcome"], code), ("approval_required", 0))

    def test_plan_lists_unchosen_primary_inputs(self):
        # Language and visibility are the user's choice: plan shows the defaults
        # as options instead of settling them silently.
        fake = FakeGitHub()
        clean = validator.Check("secrets.scan", "verified", "stubbed")
        with mock.patch.object(validator, "scan_secrets", return_value=clean):
            code, rep = self.run_cli(fake, ["plan", "--name", "demo-cli", "--type", "node"])
        self.assertEqual(
            rep["choices_required"],
            [
                {"input": "docs_locale", "default": "ja-en", "options": ["ja", "en", "ja-en", "en-ja"]},
                {"input": "visibility", "default": "public", "options": ["public", "private"]},
            ],
        )
        self.assertEqual((rep["outcome"], code), ("choice_required", 0))

    def test_create_refuses_unchosen_language(self):
        fake = FakeGitHub()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = bootstrap.main(["create", "--name", "demo-cli", "--visibility", "public", "--approve", "create"])
        self.assertEqual(code, bootstrap.EXIT_USAGE)
        self.assertIn("--docs-locale", err.getvalue())
        self.assertEqual(fake.writes, [])

    def test_verify_makes_no_writes(self):
        fake = FakeGitHub(repo_exists=True)
        _, rep = self.run_cli(fake, ["verify", "--repo", "tsunyan/demo-cli"])
        self.assertEqual(fake.writes, [])
        self.assertEqual(rep["outcome"], "failed")  # nothing was configured on the fake repo
        statuses = {c["id"]: c["status"] for c in rep["checks"]}
        self.assertEqual(statuses["files.present"], "failed")

    def _ctx(self, fake, **kw):
        req = policy.resolve(
            policy.BootstrapRequest(mode="create", name="demo-cli", **kw), authenticated_login="tsunyan"
        )
        args = argparse.Namespace(wait_ci=0, report_dir=None)
        ctx = bootstrap.Ctx(
            args, gh.GitHubClient(fake, sleep=lambda s: None), req=req, decisions=policy.feature_plan(req)
        )
        ctx.report = bootstrap.Report("create", "tsunyan/demo-cli", req.visibility, req.docs_locale, req.project_type)
        return ctx

    def test_push_is_held_until_pvr_reads_back(self):
        fake = FakeGitHub(pvr_sticks=False)
        ctx = self._ctx(fake, visibility="public")
        pushed = []
        original = bootstrap.push
        bootstrap.push = lambda c: pushed.append(True) or True
        try:
            bootstrap.remote_phase(ctx, create_repo=True, do_push=True)
        finally:
            bootstrap.push = original
        statuses = {c.id: c.status for c in ctx.report.checks}
        self.assertEqual(pushed, [])
        self.assertEqual(statuses["git.push"], "failed")
        self.assertEqual(statuses["private_vulnerability_reporting"], "failed")
        self.assertEqual(statuses["repo.create"], "applied")
        self.assertTrue(any("Private vulnerability reporting" in m for m in ctx.report.manual_actions))

    def test_settings_are_read_back(self):
        fake = FakeGitHub()
        ctx = self._ctx(fake, visibility="public", project_type="generic")
        ctx.target = None
        bootstrap.remote_phase(ctx, create_repo=True, do_push=False)
        statuses = {c.id: c.status for c in ctx.report.checks}
        for fid in (
            "repo.merge_settings",
            "actions.token_permissions",
            "dependabot.alerts",
            "dependabot.security_updates",
            "secret_scanning",
            "push_protection",
            "private_vulnerability_reporting",
            "codeql",
            "ruleset.main",
        ):
            self.assertEqual(statuses[fid], "verified", fid)
        self.assertEqual(statuses["coderabbit"], "manual_action")
        self.assertEqual(fake.rulesets[0]["rules"], [{"type": "deletion"}, {"type": "non_fast_forward"}])

    def test_private_skips_unsupported_apis(self):
        fake = FakeGitHub()
        ctx = self._ctx(fake, visibility="private")
        bootstrap.remote_phase(ctx, create_repo=True, do_push=False)
        touched = " ".join(p for _, p in fake.writes)
        for forbidden in ("code-scanning", "rulesets", "private-vulnerability-reporting"):
            self.assertNotIn(forbidden, touched)
        self.assertNotIn("security_and_analysis", json.dumps([b for _, _, b in fake.calls]))
        statuses = {c.id: c.status for c in ctx.report.checks}
        self.assertEqual(statuses["codeql"], "unsupported")
        self.assertEqual(statuses["ruleset.main"], "unsupported")

    def test_codeql_languages_come_from_the_files(self):
        langs, uncovered = gh.codeql_languages_for(
            [
                ".github/workflows/checks.yml",
                "skills/x/scripts/a.py",
                "src/index.ts",
                "assets/templates/starter/java-maven/App.java.tpl",
                "assets/templates/common/.gitignore.java",
                "web/.eslintrc.cjs",
                "src/main.rs",
                "README.md",
            ]
        )
        self.assertEqual(langs, ["actions", "javascript-typescript", "python"])
        self.assertEqual(uncovered, ["Rust"])

    def test_codeql_names_languages_and_retries(self):
        """Default setup made before language detection must not stay at actions only."""
        fake = FakeGitHub(repo_exists=True)
        fake.codeql, fake.codeql_languages = "configured", ["actions"]
        fake.tree = [".github/workflows/checks.yml", "scripts/bootstrap.py", "src/main.rs"]
        fake.queue["repos/tsunyan/demo-cli/code-scanning/default-setup"] = [
            http(200, {"state": "configured", "languages": ["actions"]}),  # first read
            http(422, {"message": "not in the required state"}),  # first PATCH
        ]
        ctx = self._ctx(fake, visibility="public", project_type="generic")
        bootstrap.CODEQL_RETRY_DELAY = 0
        bootstrap.codeql_step(ctx, bootstrap.pushed_paths(ctx, "c" * 40))
        check = next(c for c in ctx.report.checks if c.id == "codeql")
        self.assertEqual(check.status, "verified", check.detail)
        self.assertIn("python", check.detail)
        self.assertIn("Not covered by CodeQL default setup: Rust", check.detail)
        patches = [b for m, p, b in fake.calls if m == "PATCH" and p.endswith("default-setup")]
        self.assertEqual(len(patches), 2)
        self.assertEqual(patches[-1]["languages"], ["actions", "python"])

    def test_verify_flags_missing_codeql_language(self):
        fake = FakeGitHub()
        fake.codeql, fake.codeql_languages = "configured", ["actions"]
        client = gh.GitHubClient(fake)
        fake.repo = fake._new_repo("demo-cli", False)
        status, detail = gh.read_codeql(client, "tsunyan", "demo-cli", ["actions", "python"])
        self.assertEqual(status, "failed")
        self.assertIn("not for python", detail)

    def test_visibility_is_never_switched(self):
        """T17: repair does not turn a private repository public."""
        fake = FakeGitHub(repo_exists=True, private=True)
        ctx = self._ctx(fake, visibility="public")
        bootstrap.remote_phase(ctx, create_repo=False, do_push=False)
        self.assertEqual({c.id: c.status for c in ctx.report.checks}["repo.visibility"], "failed")
        self.assertFalse(any(p == "repos/tsunyan/demo-cli" and m == "PATCH" for m, p in fake.writes))

    def test_forbidden_is_not_reported_as_plan_limit(self):
        """T20: a 403 on a feature we expected to work is a failure with the real reason."""
        fake = FakeGitHub()
        fake.queue["repos/tsunyan/demo-cli/vulnerability-alerts"] = [
            http(404, {"message": "Not Found"}),
            http(403, {"message": "Must have admin rights"}),
        ]
        ctx = self._ctx(fake, visibility="private")
        bootstrap.remote_phase(ctx, create_repo=True, do_push=False)
        check = next(c for c in ctx.report.checks if c.id == "dependabot.alerts")
        self.assertEqual(check.status, "failed")
        self.assertIn("403", check.detail)
        self.assertIn("admin rights", check.detail)


if __name__ == "__main__":
    unittest.main()
