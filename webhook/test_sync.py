"""Unit tests for sync.py (v3)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sync  # noqa: E402


class TestTouchedPaths(unittest.TestCase):
    def test_nets(self):
        payload = {
            "commits": [
                {
                    "added": ["agents/a/agent.md"],
                    "modified": ["skills/x/SKILL.md"],
                    "removed": ["squads/o/squad.md"],
                },
                {
                    "added": ["skills/x/ref.md"],
                    "modified": ["agents/a/agent.md"],
                    "removed": [],
                },
            ]
        }
        added, modified, removed = sync.touched_paths(payload)
        self.assertEqual(added, {"agents/a/agent.md", "skills/x/ref.md"})
        self.assertEqual(modified, {"skills/x/SKILL.md", "agents/a/agent.md"})
        self.assertEqual(removed, {"squads/o/squad.md"})


class TestClassify(unittest.TestCase):
    def test_agent_files(self):
        self.assertEqual(
            sync.classify_path("agents/foo/agent.md"),
            sync.ChangeRef("agent", "foo", "agent.md"),
        )
        self.assertEqual(
            sync.classify_path("agents/foo/agent.yaml"),
            sync.ChangeRef("agent", "foo", "agent.yaml"),
        )
        self.assertEqual(
            sync.classify_path("agents/foo/env.yaml"),
            sync.ChangeRef("agent", "foo", "env.yaml"),
        )
        self.assertEqual(
            sync.classify_path("agents/foo/skills.yaml"),
            sync.ChangeRef("agent", "foo", "skills.yaml"),
        )

    def test_skill_attachment(self):
        self.assertEqual(
            sync.classify_path("skills/x/references/a.md"),
            sync.ChangeRef("skill", "x", "references/a.md"),
        )

    def test_squad_members(self):
        self.assertEqual(
            sync.classify_path("squads/dev/members.yaml"),
            sync.ChangeRef("squad", "dev", "members.yaml"),
        )

    def test_ignores_unrelated(self):
        self.assertIsNone(sync.classify_path("README.md"))


class TestFileRole(unittest.TestCase):
    def test_roles(self):
        self.assertEqual(sync.file_role("agent", "agent.md"), "content")
        self.assertEqual(sync.file_role("agent", "agent.yaml"), "attr")
        self.assertEqual(sync.file_role("agent", "env.yaml"), "env")
        self.assertEqual(sync.file_role("agent", "skills.yaml"), "skills")
        self.assertEqual(sync.file_role("skill", "references/a.md"), "attachment")
        self.assertEqual(sync.file_role("squad", "members.yaml"), "members")
        self.assertEqual(sync.file_role("autopilot", "triggers.yaml"), "triggers")
        self.assertIsNone(sync.file_role("agent", "unknown.txt"))


class TestCollectChanges(unittest.TestCase):
    def test_group_by_dir(self):
        added = {"agents/foo/agent.md", "agents/foo/agent.yaml"}
        removed = {"skills/x/SKILL.md"}
        changes = sync.collect_changes(added, set(), removed)
        self.assertEqual(
            changes[("agent", "foo")].files,
            {"agent.md": "added", "agent.yaml": "added"},
        )
        self.assertEqual(changes[("skill", "x")].files, {"SKILL.md": "removed"})


class TestResolveAction(unittest.TestCase):
    def test_create(self):
        self.assertEqual(sync.resolve_action(None, "new", None), "create")

    def test_skip(self):
        self.assertEqual(sync.resolve_action("same", "same", "same"), "skip")

    def test_update(self):
        self.assertEqual(sync.resolve_action("old", "new", "old"), "update")

    def test_block_drift(self):
        self.assertEqual(sync.resolve_action("manual", "new", "old"), "block")

    def test_force(self):
        self.assertEqual(
            sync.resolve_action("manual", "new", "old", force=True), "update"
        )


class TestResolveLiveName(unittest.TestCase):
    def setUp(self):
        self.by_name = {"Lynx": {"name": "Lynx", "id": "1"}}
        self.by_lower = {"lynx": [{"name": "Lynx", "id": "1"}]}

    def test_exact(self):
        self.assertEqual(
            sync.resolve_live_name(self.by_name, self.by_lower, "Lynx")[1], "exact"
        )

    def test_casefold(self):
        self.assertEqual(
            sync.resolve_live_name(self.by_name, self.by_lower, "lynx")[1], "casefold"
        )

    def test_none(self):
        self.assertEqual(
            sync.resolve_live_name(self.by_name, self.by_lower, "foo")[1], "none"
        )

    def test_ambiguous(self):
        by_lower = {"lynx": [{"name": "Lynx", "id": "1"}, {"name": "LYNX", "id": "2"}]}
        self.assertEqual(
            sync.resolve_live_name(self.by_name, by_lower, "lynx")[1], "ambiguous"
        )


class TestLoadYaml(unittest.TestCase):
    def test_yaml(self):
        class G:
            def raw(self, path, ref):
                return "model: gpt-4\nservice_tier: priority\n"

        self.assertEqual(
            sync.load_yaml(G(), "agent", "foo", "agent.yaml", "after"),
            {"model": "gpt-4", "service_tier": "priority"},
        )

    def test_missing(self):
        class G:
            def raw(self, path, ref):
                return None

        self.assertIsNone(sync.load_yaml(G(), "agent", "foo", "agent.yaml", "after"))


class TestStripFields(unittest.TestCase):
    def test_strips_readonly(self):
        body = {"model": "gpt-4", "id": "x", "id_prefix": "abc", "created_at": "t"}
        self.assertEqual(sync.strip_fields(body), {"model": "gpt-4"})


class TestReport(unittest.TestCase):
    def test_per_file_and_summary(self):
        r = sync.Report()
        r.record("update", "agent", "foo", "agent.yaml")
        r.record_rename("agent", "Lynx", "lynx")
        self.assertEqual(
            r.lines, ["UPDATE agent/foo/agent.yaml", "RENAME agent/Lynx -> lynx"]
        )
        self.assertEqual(
            r.summary(),
            "== done: update=1 create=0 archive=0 skip=0 block=0 fail=0 rename=1 ==",
        )


class TestSquadMembers(unittest.TestCase):
    class FakeMultica:
        def __init__(self, current):
            self.current = current
            self.calls = []

        def list_squad_members(self, sid):
            return list(self.current)

        def add_squad_member(self, sid, mid, mtype, role):
            self.calls.append(("add", mid, role))

        def remove_squad_member(self, sid, mid, mtype):
            self.calls.append(("remove", mid))

        def set_squad_member_role(self, sid, mid, mtype, role):
            self.calls.append(("set_role", mid, role))

    def test_converges(self):
        agents = {"Lynx": {"id": "a1"}, "Aureus": {"id": "a2"}, "Verity": {"id": "a3"}}
        m = self.FakeMultica(
            [
                {"member_type": "agent", "member_id": "a1", "role": "leader"},
                {"member_type": "agent", "member_id": "a2", "role": "PM"},
                {"member_type": "agent", "member_id": "a9", "role": "Old"},
            ]
        )
        data = {
            "members": [
                {"role": "leader", "agent": "Lynx"},
                {"role": "Reviewer", "agent": "Aureus"},
                {"role": "QA", "agent": "Verity"},
            ]
        }
        self.assertTrue(sync._apply_squad_members(m, "s1", data, agents))
        self.assertIn(("set_role", "a2", "Reviewer"), m.calls)
        self.assertIn(("add", "a3", "QA"), m.calls)
        self.assertIn(("remove", "a9"), m.calls)


class TestTriggerConvergence(unittest.TestCase):
    class FakeMultica:
        def __init__(self, live):
            self.live = live
            self.calls = []

        def get_autopilot(self, aid):
            return {"triggers": list(self.live)}

        def add_autopilot_trigger(self, aid, body):
            self.calls.append(("add", body))

        def update_autopilot_trigger(self, aid, tid, body):
            self.calls.append(("update", tid, body))

        def delete_autopilot_trigger(self, aid, tid):
            self.calls.append(("delete", tid))

    def test_adds_missing_removes_extra(self):
        m = self.FakeMultica(
            [
                {
                    "id": "t1",
                    "kind": "schedule",
                    "cron_expression": "0 9 * * *",
                    "timezone": "UTC",
                }
            ]
        )
        raw = (
            "- kind: schedule\n  cron_expression: '0 9 * * *'\n  timezone: UTC\n"
            "- kind: schedule\n  cron_expression: '*/20 * * * *'\n  timezone: Asia/Shanghai\n"
        )
        self.assertTrue(sync._apply_triggers(m, "ap1", raw))
        self.assertIn(
            (
                "add",
                {
                    "kind": "schedule",
                    "cron_expression": "*/20 * * * *",
                    "timezone": "Asia/Shanghai",
                },
            ),
            m.calls,
        )
        self.assertNotIn(("delete", "t1"), m.calls)

    def test_repeat_is_idempotent(self):
        m = self.FakeMultica(
            [
                {
                    "id": "t1",
                    "kind": "schedule",
                    "cron_expression": "*/20 * * * *",
                    "timezone": "Asia/Shanghai",
                }
            ]
        )
        raw = "- kind: schedule\n  cron_expression: '*/20 * * * *'\n  timezone: Asia/Shanghai\n"
        self.assertFalse(sync._apply_triggers(m, "ap1", raw))
        self.assertEqual(m.calls, [])

    def test_updates_changed_removes_extra(self):
        m = self.FakeMultica(
            [
                {
                    "id": "t1",
                    "kind": "schedule",
                    "cron_expression": "0 9 * * *",
                    "timezone": "UTC",
                },
                {
                    "id": "t2",
                    "kind": "schedule",
                    "cron_expression": "0 1 * * *",
                    "timezone": "UTC",
                },
            ]
        )
        raw = "- kind: schedule\n  cron_expression: '0 9 * * *'\n  timezone: Asia/Shanghai\n"
        self.assertTrue(sync._apply_triggers(m, "ap1", raw))
        self.assertIn(("update", "t1", {"timezone": "Asia/Shanghai"}), m.calls)
        self.assertIn(("delete", "t2"), m.calls)


class TestRenamePairing(unittest.TestCase):
    def test_content_different_config_same_pairs(self):
        class G:
            def raw(self, path, ref):
                return {
                    "agents/foo/agent.md": "old",
                    "agents/bar/agent.md": "new",
                    "agents/foo/agent.yaml": "cfg",
                    "agents/bar/agent.yaml": "cfg",
                }.get(path)

        changes = {
            ("agent", "foo"): sync.EntityChanges(
                "agent", "foo", files={"agent.md": "removed"}
            ),
            ("agent", "bar"): sync.EntityChanges(
                "agent", "bar", files={"agent.md": "added"}
            ),
        }
        self.assertEqual(
            sync.detect_renames(G(), changes, "before", "after"),
            {("agent", "foo"): "bar"},
        )

    def test_both_different_is_not_paired(self):
        class G:
            def raw(self, path, ref):
                return {
                    "agents/A/agent.md": "old",
                    "agents/B/agent.md": "new",
                    "agents/A/agent.yaml": "cfgA",
                    "agents/B/agent.yaml": "cfgB",
                }.get(path)

        changes = {
            ("agent", "A"): sync.EntityChanges(
                "agent", "A", files={"agent.md": "removed"}
            ),
            ("agent", "B"): sync.EntityChanges(
                "agent", "B", files={"agent.md": "added"}
            ),
        }
        self.assertEqual(sync.detect_renames(G(), changes, "before", "after"), {})


if __name__ == "__main__":
    unittest.main()
