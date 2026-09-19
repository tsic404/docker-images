"""Unit tests for sync.py pure logic (payload parsing, classification, convergence)."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sync  # noqa: E402


class TestTouchedPaths(unittest.TestCase):
    def test_nets_added_modified_removed(self):
        payload = {
            "commits": [
                {
                    "added": ["agents/a.md"],
                    "modified": ["skills/x/SKILL.md"],
                    "removed": ["squads/old.md"],
                },
                {
                    "added": ["skills/x/extra.md"],
                    "modified": ["agents/a.md"],
                    "removed": [],
                },
            ]
        }
        present, removed = sync.touched_paths(payload)
        self.assertEqual(
            present, {"agents/a.md", "skills/x/SKILL.md", "skills/x/extra.md"}
        )
        self.assertEqual(removed, {"squads/old.md"})

    def test_removed_and_readded_nets_present(self):
        payload = {"commits": [{"added": ["agents/a.md"], "removed": ["agents/a.md"]}]}
        present, removed = sync.touched_paths(payload)
        self.assertEqual(present, {"agents/a.md"})
        self.assertEqual(removed, set())


class TestClassification(unittest.TestCase):
    def test_md_stem(self):
        self.assertEqual(sync._md_stem("agents/foo.md"), "foo")
        self.assertEqual(sync._md_stem("agents/foo.txt"), "")
        self.assertEqual(sync._md_stem("agents/.md"), "")

    def test_autopilot_stem(self):
        self.assertEqual(
            sync.split_autopilot_stem("eap-coordinator-676a5673"),
            ("eap-coordinator", "676a5673"),
        )
        self.assertEqual(sync.split_autopilot_stem("plain-title"), ("plain-title", ""))

    def test_files_by_name(self):
        present = {"agents/foo.md", "agents/deep/bar.md", "skills/x/SKILL.md"}
        removed = {"agents/old.md"}
        out = sync._files_by_name(present, removed, "agents/")
        self.assertEqual(out, {"foo": "present", "old": "removed"})

    def test_skill_changes(self):
        present = {"skills/x/SKILL.md", "skills/x/ref/a.md"}
        removed = {"skills/x/ref/b.md", "skills/y/SKILL.md"}
        changes = sync._skill_changes(present, removed)
        self.assertEqual(changes["x"]["content"], "present")
        self.assertEqual(
            changes["x"]["files"], {"ref/a.md": "present", "ref/b.md": "removed"}
        )
        self.assertEqual(changes["y"]["content"], "removed")

    def test_is_entity_path(self):
        self.assertTrue(sync._is_entity_path("agents/a.md"))
        self.assertFalse(sync._is_entity_path("README.md"))


class TestResolveAction(unittest.TestCase):
    def test_create(self):
        self.assertEqual(sync.resolve_action(None, "new", None), "create")

    def test_skip_identical(self):
        self.assertEqual(sync.resolve_action("same", "same", "same"), "skip")

    def test_update_when_live_matches_before(self):
        self.assertEqual(sync.resolve_action("old", "new", "old"), "update")

    def test_block_when_live_drifted(self):
        self.assertEqual(sync.resolve_action("manual edit", "new", "old"), "block")

    def test_block_when_no_before(self):
        self.assertEqual(sync.resolve_action("manual edit", "new", None), "block")


class TestReport(unittest.TestCase):
    def test_summary_counts(self):
        report = sync.Report()
        report.record("create", "agent", "foo")
        report.record("skip", "skill", "bar")
        self.assertEqual(report.counts["create"], 1)
        self.assertEqual(report.lines, ["CREATE agent/foo", "SKIP skill/bar"])
        self.assertEqual(
            report.summary(),
            "== done: update=0 create=1 archive=0 skip=1 block=0 fail=0 ==",
        )


class TestLoadPayload(unittest.TestCase):
    def test_from_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"ref": "refs/heads/main"}, fh)
            path = fh.name
        try:
            self.assertEqual(sync.load_payload([path]), {"ref": "refs/heads/main"})
        finally:
            os.unlink(path)

    def test_from_arg_json(self):
        self.assertEqual(
            sync.load_payload(['{"ref": "refs/heads/main"}']),
            {"ref": "refs/heads/main"},
        )

    def test_empty_raises(self):
        with self.assertRaises(sync.SyncError):
            sync.load_payload(["  "])

    def test_invalid_json_raises(self):
        with self.assertRaises(sync.SyncError):
            sync.load_payload(["not json"])


if __name__ == "__main__":
    unittest.main()
