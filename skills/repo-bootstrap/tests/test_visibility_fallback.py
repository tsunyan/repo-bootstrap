"""T08/T09/T10/T16: personal Free public vs private decisions and input rules."""

import unittest

import helpers
import policy
from policy import PolicyError, decision


class VisibilityFallback(unittest.TestCase):
    def test_public_free(self):
        req, d, _ = helpers.make(visibility="public", project_type="rust")
        for fid in (
            "codeql",
            "secret_scanning",
            "push_protection",
            "ruleset.main",
            "private_vulnerability_reporting",
            "dependabot.alerts",
        ):
            self.assertEqual(decision(d, fid).action, "apply", fid)
        self.assertEqual(decision(d, "gitleaks").action, "skipped_by_policy")
        self.assertEqual(req.docs_locale, "ja-en")
        self.assertEqual(req.license, "MIT")

    def test_private_free_never_claims_hosted_features(self):
        """T09: CodeQL, rulesets, native secret scanning are unsupported; Gitleaks is the fallback."""
        req, d, _ = helpers.make(visibility="private", project_type="python")
        for fid in ("codeql", "secret_scanning", "push_protection", "ruleset.main"):
            self.assertEqual(decision(d, fid).action, "unsupported", fid)
        self.assertEqual(decision(d, "gitleaks").action, "apply")
        self.assertIn("not equivalent", decision(d, "codeql").detail)
        self.assertEqual(req.docs_locale, "ja")
        self.assertEqual(req.license, "none")
        self.assertEqual(req.security_contact, "existing-channel")
        _, _, files = helpers.plan_files(visibility="private", project_type="python")
        security = {f.path: f.content for f in files}["SECURITY.md"]
        self.assertNotIn("Report a vulnerability", security)

    def test_coderabbit_is_never_installed(self):
        """T10: a config file is not the same as a working review."""
        _, d, _ = helpers.make(visibility="public")
        self.assertEqual(decision(d, "coderabbit").action, "manual_action")
        _, d, _ = helpers.make(visibility="private", coderabbit="on")
        self.assertEqual(decision(d, "coderabbit").action, "manual_action")
        req = policy.resolve(policy.BootstrapRequest(mode="plan", name="x"), authenticated_login="u")
        self.assertEqual(
            decision(policy.feature_plan(req, coderabbit_app_installed=True), "coderabbit").action, "apply"
        )

    def test_license_refused(self):
        """T16: license=none renders no LICENSE file and no license grant."""
        _, _, files = helpers.plan_files(visibility="public", license="none", project_type="rust")
        by = {f.path: f.content for f in files}
        self.assertNotIn("LICENSE", by)
        self.assertNotIn('license = "MIT"', by["Cargo.toml"])
        self.assertIn("ライセンスは付与していません", by["README.md"])
        self.assertNotIn("license", policy.required_approvals(helpers.make(license="none")[0]))

    def test_contradictions_are_rejected(self):
        with self.assertRaises(PolicyError):
            helpers.make(visibility="private", security_contact="private-reporting")
        with self.assertRaises(PolicyError):
            helpers.make(visibility="public", security_contact="existing-channel")
        with self.assertRaises(PolicyError):
            helpers.make(security_contact="email")  # no address
        with self.assertRaises(PolicyError):
            helpers.make(license="Apache-2.0")

    def test_email_contact(self):
        _, _, files = helpers.plan_files(
            security_contact="email", security_email="security@example.com", docs_locale="en"
        )
        self.assertIn("**security@example.com**", {f.path: f.content for f in files}["SECURITY.md"])

    def test_bad_names_rejected_not_rewritten(self):
        for bad in ("../x", "a b", "a;rm", ".", "x.git", "", "a" * 101):
            with self.assertRaises(PolicyError, msg=bad):
                helpers.make(name=bad)

    def test_partial_translation_is_an_error(self):
        with self.assertRaises(PolicyError):
            helpers.make(docs_locale="both", description_ja="説明だけ")

    def test_approvals(self):
        self.assertEqual(
            policy.required_approvals(helpers.make(visibility="public")[0]), ["create", "public", "license"]
        )
        self.assertEqual(policy.required_approvals(helpers.make(visibility="private")[0]), ["create"])

    def test_strict_ruleset_detail(self):
        _, d, _ = helpers.make(ruleset="strict")
        self.assertIn("0 approvals", decision(d, "ruleset.main").detail)


if __name__ == "__main__":
    unittest.main()
