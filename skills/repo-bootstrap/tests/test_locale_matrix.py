"""T01/T02/T03/T18/T19: every docs_locale x visibility x project_type renders cleanly."""

import itertools
import unittest

import helpers
import policy
import validator

TYPES = ("rust", "python", "node", "java-maven", "generic")

STARTER_FILES = {
    "rust": {"Cargo.toml", "Cargo.lock", "src/main.rs"},
    "python": {"pyproject.toml", "src/demo_cli/__init__.py", "src/demo_cli/__main__.py", "tests/test_smoke.py"},
    "node": {"package.json", "package-lock.json", "src/index.js", "test/index.test.js"},
    "java-maven": {
        "pom.xml",
        "src/main/java/io/github/tsunyan/demo_cli/App.java",
        "src/test/java/io/github/tsunyan/demo_cli/AppTest.java",
    },
    "generic": set(),
}


class LocaleMatrix(unittest.TestCase):
    def test_all_patterns(self):
        count = 0
        for locale, vis, ptype in itertools.product(policy.LOCALES, policy.VISIBILITIES, TYPES):
            with self.subTest(locale=locale, visibility=vis, type=ptype):
                _, _, files = helpers.plan_files(docs_locale=locale, visibility=vis, project_type=ptype)
                paths = {f.path for f in files}
                for check in (
                    validator.check_placeholders(files),
                    validator.check_structured(files),
                    validator.check_links(files, None),
                    validator.check_locale(files, locale),
                ):
                    self.assertEqual(check.status, "verified", f"{check.id}: {check.detail}")
                for check in validator.check_workflows(validator.workflow_texts(files, None)):
                    self.assertIn(check.status, ("verified", "skipped_by_policy", "pending"), check.detail)
                self.assertTrue(STARTER_FILES[ptype] <= paths, STARTER_FILES[ptype] - paths)
                for doc in (
                    "README.md",
                    "AGENTS.md",
                    "SECURITY.md",
                    "CONTRIBUTING.md",
                    ".github/PULL_REQUEST_TEMPLATE.md",
                    ".gitignore",
                    ".editorconfig",
                    ".gitattributes",
                    ".repo-bootstrap.yml",
                    ".github/ISSUE_TEMPLATE/bug_report.yml",
                ):
                    self.assertIn(doc, paths)
                self.assertEqual("README.en.md" in paths, locale == "both")
                self.assertEqual(".github/workflows/ci.yml" in paths, ptype != "generic")
                self.assertEqual(".github/workflows/secret-scan.yml" in paths, vis == "private")
                self.assertEqual("LICENSE" in paths, vis == "public")
                count += 1
        self.assertEqual(count, 30)  # 24 runnable patterns + 6 generic

    def test_english_request_keeps_identifiers(self):
        """T18: en documents contain no Japanese, but commands and paths stay as they are."""
        _, _, files = helpers.plan_files(docs_locale="en", visibility="public", project_type="python")
        by = {f.path: f.content for f in files}
        self.assertNotRegex(by["README.md"], validator.JA_CHARS_RE.pattern)
        self.assertIn("python -m demo_cli", by["README.md"])
        self.assertIn("pytest -q", by["AGENTS.md"])

    def test_both_has_cross_links_and_sections(self):
        """T19."""
        _, _, files = helpers.plan_files(docs_locale="both", visibility="public", project_type="node")
        by = {f.path: f.content for f in files}
        self.assertIn("[English](README.en.md)", by["README.md"])
        self.assertIn("[日本語](README.md)", by["README.en.md"])
        for p in validator.BILINGUAL:
            self.assertIn("## 日本語", by[p])
            self.assertIn("\n## English\n", by[p])

    def test_generic_writes_no_command_fences(self):
        """design 9.5: generic has no shell fences for commands that do not exist."""
        for locale in policy.LOCALES:
            _, _, files = helpers.plan_files(docs_locale=locale, project_type="generic")
            for f in files:
                if f.path.endswith(".md"):
                    self.assertNotIn("```sh", f.content, f.path)
            readme = {f.path: f.content for f in files}["README.md"]
            self.assertTrue(
                "この段階で定義されたコマンドはありません" in readme
                or "No commands are defined at this stage" in readme
            )

    def test_commands_in_docs_match_ci(self):
        """T02: README commands are the ones the generated CI runs."""
        for ptype, needle in (
            ("rust", "cargo test --all-targets --all-features --locked"),
            ("python", "pytest -q"),
            ("node", "npm test"),
            ("java-maven", "mvn --batch-mode --no-transfer-progress verify"),
        ):
            _, _, files = helpers.plan_files(project_type=ptype, docs_locale="en")
            by = {f.path: f.content for f in files}
            self.assertIn(needle, by["README.md"])
            self.assertIn(needle, by[".github/workflows/ci.yml"])


if __name__ == "__main__":
    unittest.main()
