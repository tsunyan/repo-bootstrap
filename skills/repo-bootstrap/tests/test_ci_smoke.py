"""T07: the generated starters pass their own lint/test/build.

Runs each toolchain that is installed; the others are skipped. The Python
starter installs packages from PyPI, so it runs only with REPO_BOOTSTRAP_SLOW=1.
"""

import os
import shutil
import unittest

import helpers
import validator


class StarterSmoke(unittest.TestCase):
    def run_type(self, ptype, tools):
        missing = [t for t in tools if shutil.which(t) is None]
        if missing:
            self.skipTest(f"{', '.join(missing)} not installed")
        _, _, files = helpers.plan_files(project_type=ptype, docs_locale="en")
        check = validator.run_local_ci(files, ptype)
        self.assertEqual(check.status, "verified", check.detail)

    def test_node(self):
        self.run_type("node", ["node", "npm"])

    def test_rust(self):
        self.run_type("rust", ["cargo"])

    def test_java(self):
        self.run_type("java-maven", ["mvn", "java"])

    @unittest.skipUnless(os.environ.get("REPO_BOOTSTRAP_SLOW") == "1", "set REPO_BOOTSTRAP_SLOW=1 (needs PyPI)")
    def test_python(self):
        self.run_type("python", [])


if __name__ == "__main__":
    unittest.main()
