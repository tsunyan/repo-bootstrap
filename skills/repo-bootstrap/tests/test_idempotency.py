"""T12/T14: second runs change nothing; human edits are never overwritten."""

import tempfile
import unittest
from pathlib import Path

import helpers
import scaffold
import state


def generate(target: Path, **kw):
    req, decisions, pins = helpers.make(**kw)
    lock = state.load_lock(target)
    files = scaffold.build_plan(req, decisions, pins, target=target)
    results = state.classify(target, files, lock)
    state.apply(target, files, results)
    new_lock = state.build_lock(files, results, lock, pins, {d.id: d.action for d in decisions})
    lock_status = state.write_lock(target, new_lock)
    return results, lock_status


class Idempotency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.target = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_run_is_a_no_op(self):
        first, lock1 = generate(self.target, project_type="node")
        self.assertTrue(all(r.status == "created" for r in first))
        self.assertEqual(lock1, "created")
        second, lock2 = generate(self.target, project_type="node")
        self.assertEqual({r.status for r in second}, {"unchanged"})
        self.assertEqual(lock2, "unchanged")

    def test_human_edit_is_a_conflict(self):
        generate(self.target, project_type="rust")
        readme = self.target / "README.md"
        readme.write_text("# My own README\n", encoding="utf-8")
        results, _ = generate(
            self.target, project_type="rust", description_ja="新しい説明", description_en="New description"
        )
        by = {r.path: r for r in results}
        self.assertEqual(by["README.md"].status, "conflict")
        self.assertIn("+> 新しい説明", by["README.md"].diff)
        self.assertEqual(readme.read_text(encoding="utf-8"), "# My own README\n")

    def test_untouched_generated_file_is_updated(self):
        generate(self.target, project_type="rust")
        results, _ = generate(
            self.target, project_type="rust", description_ja="新しい説明", description_en="New description"
        )
        self.assertEqual({r.path: r.status for r in results}["README.md"], "updated")
        self.assertIn("新しい説明", (self.target / "README.md").read_text(encoding="utf-8"))

    def test_existing_unknown_file_is_not_overwritten(self):
        (self.target / "CONTRIBUTING.md").write_text("ours\n", encoding="utf-8")
        results, _ = generate(self.target)
        self.assertEqual({r.path: r.status for r in results}["CONTRIBUTING.md"], "conflict")
        self.assertEqual((self.target / "CONTRIBUTING.md").read_text(encoding="utf-8"), "ours\n")

    def test_gitignore_keeps_existing_lines(self):
        (self.target / ".gitignore").write_text("my-local-dir/\n.env\n", encoding="utf-8")
        generate(self.target, project_type="python")
        text = (self.target / ".gitignore").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("my-local-dir/\n.env\n"))
        self.assertIn("__pycache__/", text)
        self.assertEqual(text.count(".env\n"), 1)
        _, _ = generate(self.target, project_type="python")
        self.assertEqual((self.target / ".gitignore").read_text(encoding="utf-8"), text)

    def test_files_are_written_with_lf(self):
        generate(self.target)
        self.assertNotIn(b"\r\n", (self.target / "README.md").read_bytes())

    def test_paths_cannot_escape(self):
        with self.assertRaises(ValueError):
            state.safe_path(self.target, "../outside.txt")


if __name__ == "__main__":
    unittest.main()
