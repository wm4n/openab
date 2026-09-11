"""collect.py 要把 thread_map 的 entry 數存下來給失敗率代理用。

報表階段只讀事件檔、碰不到 agent 的 HOME，所以這個計數必須在收集時記錄。
"""
import json
import os
import tempfile
import unittest

from collect import count_thread_map, main
from tests.test_collect import make_claude_home, user_record


class TestCountThreadMap(unittest.TestCase):
    def test_counts_persisted_entries(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".openab"))
            with open(os.path.join(d, ".openab", "thread_map.json"), "w") as fh:
                json.dump({"persisted": {"discord:a": "1", "discord:b": "2"}}, fh)
            self.assertEqual(count_thread_map(d), 2)

    def test_missing_file_returns_none_not_zero(self):
        # 「不知道」與「沒有落差」必須可區分
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(count_thread_map(d))

    def test_broken_json_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".openab"))
            with open(os.path.join(d, ".openab", "thread_map.json"), "w") as fh:
                fh.write("{broken")
            self.assertIsNone(count_thread_map(d))

    def test_flat_mapping_without_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".openab"))
            with open(os.path.join(d, ".openab", "thread_map.json"), "w") as fh:
                json.dump({"discord:a": "1"}, fh)
            self.assertEqual(count_thread_map(d), 1)


class TestMainWritesCounts(unittest.TestCase):
    def test_writes_thread_map_counts_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            make_claude_home(root, "rick",
                             [user_record("m1", "2026-09-10T06:32:10Z")])
            out = os.path.join(tmp, "out")
            self.assertEqual(main(["--root", root, "--out", out]), 0)
            with open(os.path.join(out, "thread-map-counts.json")) as fh:
                counts = json.load(fh)
            self.assertEqual(counts["rick"], 1)


if __name__ == "__main__":
    unittest.main()
