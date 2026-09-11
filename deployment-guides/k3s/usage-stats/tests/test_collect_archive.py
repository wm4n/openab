"""从 archive/mirror 回填已被 claude-code 保留期限清掉的歷史資料。

openab-archive.sh（見 K3S.md「transcript 保留期限」）把各 bot 的原始檔案
rsync 進鏡像，但用重新命名過的子目錄（claude-projects/codex-sessions/
opencode/openab），跟 parser 認得的活資料佈局（.claude/projects 等）不同名。
這裡的測試鎖住：符號連結佈局要對得上、watermark 要跟活資料分開命名空間
（避免同名 bot 互相覆蓋)、以及重跑要幂等（不重複計算）。
"""
import json
import os
import tempfile
import unittest

from collect import main, mirror_shim_home
from tests.test_collect import make_claude_home, sc_text, user_record


def make_mirror(archive_root, bot, records, thread_map=None,
                subdir="claude-projects"):
    """建一個假的 archive/mirror bot 目錄（claude-projects 佈局）。"""
    d = os.path.join(archive_root, bot, subdir, "-home-node")
    os.makedirs(d)
    with open(os.path.join(d, "s1.jsonl"), "w") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    openab_dir = os.path.join(archive_root, bot, "openab")
    os.makedirs(openab_dir)
    with open(os.path.join(openab_dir, "thread_map.json"), "w") as fh:
        json.dump({"persisted": thread_map or {"discord:t1": "s1"}}, fh)
    return os.path.join(archive_root, bot)


class TestMirrorShimHome(unittest.TestCase):
    def test_creates_symlinks_for_present_layout_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror_bot_dir = make_mirror(os.path.join(tmp, "archive"), "rick", [])
            shim_home = os.path.join(tmp, "shim", "rick")
            mirror_shim_home(mirror_bot_dir, shim_home)
            self.assertTrue(os.path.islink(os.path.join(shim_home, ".claude",
                                                         "projects")))
            self.assertTrue(os.path.islink(os.path.join(shim_home, ".openab")))
            # 鏡像沒有 codex-sessions／opencode 子目錄，不該生出斷掉的連結
            self.assertFalse(os.path.exists(os.path.join(shim_home, ".codex")))

    def test_calling_twice_for_same_bot_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror_bot_dir = make_mirror(os.path.join(tmp, "archive"), "rick", [])
            shim_home = os.path.join(tmp, "shim", "rick")
            first = mirror_shim_home(mirror_bot_dir, shim_home)
            second = mirror_shim_home(mirror_bot_dir, shim_home)
            self.assertEqual(first, second)
            self.assertTrue(os.path.islink(os.path.join(shim_home, ".claude",
                                                         "projects")))

    def test_shimmed_home_is_readable_by_the_normal_parser(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror_bot_dir = make_mirror(
                os.path.join(tmp, "archive"), "rick",
                [user_record("m1", "2026-08-05T06:32:10Z")])
            shim_home = os.path.join(tmp, "shim", "rick")
            mirror_shim_home(mirror_bot_dir, shim_home)
            from events import ParseContext
            import parse_claude_code
            res = parse_claude_code.parse(
                shim_home, "rick", ParseContext.from_agent_home(shim_home), {})
            self.assertEqual(len(res.tasks), 1)
            self.assertEqual(res.tasks[0]["dedup_key"], "discord:m1")


class TestMainWithArchiveRoot(unittest.TestCase):
    def test_backfills_tasks_from_mirror_into_the_same_event_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            archive = os.path.join(tmp, "archive")
            make_mirror(archive, "rick",
                       [user_record("m-old", "2026-08-05T06:00:00Z")])
            out = os.path.join(tmp, "out")
            rc = main(["--root", root, "--out", out, "--archive-root", archive])
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "events", "task-2026-08-05.jsonl")) as fh:
                rows = [json.loads(l) for l in fh]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["dedup_key"], "discord:m-old")
            self.assertEqual(rows[0]["bot"], "rick")

    def test_archive_watermark_is_namespaced_separately_from_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            make_claude_home(root, "rick",
                             [user_record("m-live", "2026-09-10T06:00:00Z")])
            archive = os.path.join(tmp, "archive")
            make_mirror(archive, "rick",
                       [user_record("m-old", "2026-08-05T06:00:00Z")])
            out = os.path.join(tmp, "out")
            main(["--root", root, "--out", out, "--archive-root", archive])
            with open(os.path.join(out, "watermark.json")) as fh:
                marks = json.load(fh)
            self.assertIn("rick", marks)
            self.assertIn("archive:rick", marks)
            self.assertNotEqual(marks["rick"], marks["archive:rick"])
            # 兩邊各自的事件都要在，互不覆蓋
            with open(os.path.join(out, "events", "task-2026-09-10.jsonl")) as fh:
                self.assertEqual(len(fh.readlines()), 1)
            with open(os.path.join(out, "events", "task-2026-08-05.jsonl")) as fh:
                self.assertEqual(len(fh.readlines()), 1)

    def test_second_run_does_not_double_count_archive_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            archive = os.path.join(tmp, "archive")
            make_mirror(archive, "rick",
                       [user_record("m-old", "2026-08-05T06:00:00Z")])
            out = os.path.join(tmp, "out")
            main(["--root", root, "--out", out, "--archive-root", archive])
            main(["--root", root, "--out", out, "--archive-root", archive])
            with open(os.path.join(out, "events", "task-2026-08-05.jsonl")) as fh:
                rows = [json.loads(l) for l in fh]
            self.assertEqual(len(rows), 1)

    def test_bots_filter_applies_to_archive_pass_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            archive = os.path.join(tmp, "archive")
            make_mirror(archive, "rick",
                       [user_record("m1", "2026-08-05T06:00:00Z")])
            make_mirror(archive, "morty",
                       [user_record("m2", "2026-08-05T07:00:00Z")])
            out = os.path.join(tmp, "out")
            main(["--root", root, "--out", out, "--archive-root", archive,
                  "--bots", "rick"])
            with open(os.path.join(out, "watermark.json")) as fh:
                marks = json.load(fh)
            self.assertIn("archive:rick", marks)
            self.assertNotIn("archive:morty", marks)

    def test_unrecognised_archive_bot_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            archive = os.path.join(tmp, "archive")
            os.makedirs(os.path.join(archive, "ghost"))  # 空目錄，認不出格式
            out = os.path.join(tmp, "out")
            rc = main(["--root", root, "--out", out, "--archive-root", archive])
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "collect-health.json")) as fh:
                health = json.load(fh)
            self.assertIn("archive:ghost", health["unrecognised"])

    def test_missing_archive_root_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            out = os.path.join(tmp, "out")
            rc = main(["--root", root, "--out", out,
                      "--archive-root", "/nonexistent"])
            self.assertNotEqual(rc, 0)

    def test_archive_bots_do_not_pollute_thread_map_counts(self):
        # thread_map_counts 是「現在」的快照，鏡像裡的舊快照混進去只會誤導
        # failure_proxy 的紅旗判斷，所以回填不寫 thread-map-counts.json。
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            archive = os.path.join(tmp, "archive")
            make_mirror(archive, "rick",
                       [user_record("m1", "2026-08-05T06:00:00Z")])
            out = os.path.join(tmp, "out")
            main(["--root", root, "--out", out, "--archive-root", archive])
            with open(os.path.join(out, "thread-map-counts.json")) as fh:
                counts = json.load(fh)
            self.assertEqual(counts, {})


if __name__ == "__main__":
    unittest.main()
