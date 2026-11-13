"""T04/T05/T06 and renderer rules."""

import random
import string
import unittest

import helpers
import renderer
import validator
from scaffold import PlannedFile


class Renderer(unittest.TestCase):
    def test_actions_expressions_untouched(self):
        text = "group: ci-${{ github.workflow }}-${{ github.ref }}\nname: {{PROJECT_NAME}}"
        out = renderer.render(text, {"PROJECT_NAME": "x"})
        self.assertIn("${{ github.workflow }}", out)
        self.assertEqual(renderer.find_unresolved(out), [])

    def test_missing_variable_is_error(self):
        with self.assertRaises(renderer.RenderError):
            renderer.render("{{NOT_DEFINED}}", {})

    def test_unresolved_detection(self):
        self.assertEqual(renderer.find_unresolved("a {{ x }} ${{ ok }}"), ["{{ x }}"])

    def test_user_text_is_escaped_per_format(self):
        _, _, files = helpers.plan_files(
            project_type="node", docs_locale="en", description_en='Say "hi" <b>&', overview_en="ok"
        )
        by = {f.path: f.content for f in files}
        self.assertIn("&lt;b&gt;&amp;", by["README.md"])
        self.assertIn('Say \\"hi\\" <b>&', by["package.json"])
        self.assertIn('description_en: "Say \\"hi\\" <b>&"', by[".repo-bootstrap.yml"])


class Workflows(unittest.TestCase):
    def test_unpinned_uses_fail(self):
        checks = validator.check_workflows(
            {
                ".github/workflows/x.yml": (
                    "on: push\npermissions:\n  contents: read\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
                    "    steps:\n      - uses: actions/checkout@v4\n"
                )
            }
        )
        self.assertEqual(checks[0].status, "failed")

    def test_on_key_is_parsed(self):
        """T04: 'on' must stay a key, not become boolean True."""
        if validator._yaml_load("a: 1") is None:
            self.skipTest("PyYAML not installed")
        _, _, files = helpers.plan_files(project_type="rust")
        ci = {f.path: f.content for f in files}[".github/workflows/ci.yml"]
        self.assertIn("on", validator._yaml_load(ci))
        statuses = {c.id: c.status for c in validator.check_workflows({"ci.yml": ci})}
        self.assertEqual(statuses, {"actions.pinned": "verified", "workflows.syntax": "verified"})

    def test_pull_request_target_rejected(self):
        checks = validator.check_workflows({"w.yml": "on: pull_request_target\npermissions: {}\njobs: {}\n"})
        self.assertIn("failed", [c.status for c in checks])

    def test_generated_uses_are_full_shas(self):
        """T05."""
        _, _, files = helpers.plan_files(project_type="java-maven", visibility="private")
        for f in files:
            if f.path.startswith(".github/workflows/"):
                for ref in validator.USES_RE.findall(f.content):
                    self.assertRegex(ref, validator.PINNED_RE.pattern)


class Secrets(unittest.TestCase):
    def test_forbidden_files(self):
        self.assertEqual(validator.check_forbidden_files(["README.md", ".env.example"]).status, "verified")
        for bad in (".env", "config/.env.production", "deploy/id_rsa", "certs/server.key"):
            self.assertEqual(validator.check_forbidden_files([bad]).status, "failed", bad)

    def test_token_stops_publication(self):
        """T06: a token in the commit set fails the gate (built at runtime, never stored)."""
        if validator.gitleaks_path() is None:
            self.skipTest("gitleaks not installed")
        rnd = random.Random(7)
        token = "ghp_" + "".join(rnd.choice(string.ascii_letters + string.digits) for _ in range(36))
        clean = validator.scan_secrets({"README.md": "# ok\n"}, required=True)
        self.assertEqual(clean.status, "verified")
        dirty = validator.scan_secrets({"src/config.py": f'TOKEN = "{token}"\n'}, required=True)
        self.assertEqual(dirty.status, "failed")
        self.assertIn("src/config.py", dirty.detail)
        self.assertNotIn(token, dirty.detail)

    def test_placeholder_gate(self):
        bad = [PlannedFile("README.md", "# {{PROJECT_NAME}}\n", "t", "doc")]
        self.assertEqual(validator.check_placeholders(bad).status, "failed")


if __name__ == "__main__":
    unittest.main()
