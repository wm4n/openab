"""collect.py 的測試：CLI 偵測、按日切檔、水位持久化。"""
import json
import os
import sqlite3
import tempfile
import unittest

from collect import collect_one, detect_cli, main


def make_claude_home(root, bot, records):
    home = os.path.join(root, "agent-" + bot)
    d = os.path.join(home, ".claude", "projects", "-home-node")
    os.makedirs(d)
    with open(os.path.join(d, "s1.jsonl"), "w") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.makedirs(os.path.join(home, ".openab"))
    with open(os.path.join(home, ".openab", "thread_map.json"), "w") as fh:
        json.dump({"persisted": {"discord:t1": "s1"}}, fh)
    return home


def sc_text(message_id, ts):
    return ('<sender_context>\n{"schema":"openab.sender.v1","sender_id":"824",'
            '"sender_name":"wm4n","display_name":"william","channel":"discord",'
            '"channel_id":"c1","thread_id":"t1","is_bot":false,'
            '"timestamp":"%s","message_id":"%s"}\n</sender_context>'
            % (ts, message_id))


def user_record(message_id, ts):
    return {"type": "user", "sessionId": "s1", "message": {
        "role": "user", "content": [{"type": "text", "text": sc_text(message_id, ts)}]}}


class TestDetectCli(unittest.TestCase):
    def test_claude_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "h")
            os.makedirs(os.path.join(home, ".claude", "projects"))
            self.assertEqual(detect_cli(home), "claude-code")

    def test_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "h")
            os.makedirs(os.path.join(home, ".codex", "sessions"))
            self.assertEqual(detect_cli(home), "codex")

    def test_opencode_db_wins_over_config_dir(self):
        # 真實環境兩者同時存在；先比對目錄會誤判成「沒有資料」
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "h")
            share = os.path.join(home, ".local", "share", "opencode")
            os.makedirs(share)
            os.makedirs(os.path.join(home, ".config", "opencode"))
            sqlite3.connect(os.path.join(share, "opencode.db")).close()
            self.assertEqual(detect_cli(home), "opencode")

    def test_config_dir_alone_is_not_opencode_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "h")
            os.makedirs(os.path.join(home, ".config", "opencode"))
            self.assertIsNone(detect_cli(home))

    def test_empty_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(detect_cli(tmp))


class TestCollectOne(unittest.TestCase):
    def test_writes_events_split_by_taipei_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            # 06:32Z → 台北 9/10；17:30Z → 台北 9/11
            home = make_claude_home(root, "rick", [
                user_record("m1", "2026-09-10T06:32:10Z"),
                user_record("m2", "2026-09-10T17:30:00Z")])
            out = os.path.join(tmp, "out")
            collect_one(home, "rick", out, {})
            ev = os.path.join(out, "events")
            self.assertTrue(os.path.isfile(os.path.join(ev, "task-2026-09-10.jsonl")))
            self.assertTrue(os.path.isfile(os.path.join(ev, "task-2026-09-11.jsonl")))

    def test_event_without_timestamp_goes_to_unknown_bucket_not_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            bad = {"type": "user", "sessionId": "s1", "message": {
                "role": "user", "content": [{"type": "text", "text":
                    '<sender_context>\n{"schema":"openab.sender.v1",'
                    '"sender_id":"1","is_bot":false,"message_id":"m9"}\n'
                    '</sender_context>'}]}}
            home = make_claude_home(root, "rick", [bad])
            out = os.path.join(tmp, "out")
            collect_one(home, "rick", out, {})
            path = os.path.join(out, "events", "task-unknown.jsonl")
            self.assertTrue(os.path.isfile(path))
            with open(path) as fh:
                self.assertEqual(len(fh.readlines()), 1)

    def test_second_run_writes_nothing_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            home = make_claude_home(root, "rick",
                                    [user_record("m1", "2026-09-10T06:32:10Z")])
            out = os.path.join(tmp, "out")
            first = collect_one(home, "rick", out, {})
            second = collect_one(home, "rick", out, first.watermark)
            self.assertEqual(len(first.tasks), 1)
            self.assertEqual(len(second.tasks), 0)


class TestMain(unittest.TestCase):
    def test_processes_all_agent_dirs_and_persists_watermark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            make_claude_home(root, "rick", [user_record("m1", "2026-09-10T06:32:10Z")])
            make_claude_home(root, "morty", [user_record("m2", "2026-09-10T07:00:00Z")])
            out = os.path.join(tmp, "out")
            rc = main(["--root", root, "--out", out])
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "watermark.json")) as fh:
                marks = json.load(fh)
            self.assertEqual(sorted(marks), ["morty", "rick"])

    def test_bots_filter_limits_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            make_claude_home(root, "rick", [user_record("m1", "2026-09-10T06:32:10Z")])
            make_claude_home(root, "morty", [user_record("m2", "2026-09-10T07:00:00Z")])
            out = os.path.join(tmp, "out")
            main(["--root", root, "--out", out, "--bots", "rick"])
            with open(os.path.join(out, "watermark.json")) as fh:
                self.assertEqual(sorted(json.load(fh)), ["rick"])

    def test_missing_root_returns_nonzero(self):
        self.assertNotEqual(main(["--root", "/nonexistent", "--out", "/tmp/x"]), 0)

    def test_unrecognised_agent_is_reported_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(os.path.join(root, "agent-ghost"))
            out = os.path.join(tmp, "out")
            rc = main(["--root", root, "--out", out])
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "collect-health.json")) as fh:
                health = json.load(fh)
            self.assertIn("ghost", health["unrecognised"])


if __name__ == "__main__":
    unittest.main()
