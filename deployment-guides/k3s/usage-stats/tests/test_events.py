"""events.py 的測試：日界線、JSONL 讀寫、ParseContext 的平台查詢。"""
import json
import os
import tempfile
import unittest

from events import (
    TAIPEI, TASK_SCHEMA, USAGE_SCHEMA,
    ParseContext, ParseResult, day_key, read_events, write_events,
)


class TestDayKey(unittest.TestCase):
    def test_utc_afternoon_stays_same_day_in_taipei(self):
        self.assertEqual(day_key("2026-09-10T06:32:10Z"), "2026-09-10")

    def test_utc_late_evening_rolls_to_next_taipei_day(self):
        # 2026-09-10T17:00Z = 2026-09-11 01:00 台北
        self.assertEqual(day_key("2026-09-10T17:00:00Z"), "2026-09-11")

    def test_offset_timestamp_is_converted_not_truncated(self):
        # rfc3339 帶 offset（cron.rs 用 Utc::now().to_rfc3339()）
        self.assertEqual(day_key("2026-09-10T23:30:00+00:00"), "2026-09-11")

    def test_naive_timestamp_is_treated_as_utc(self):
        self.assertEqual(day_key("2026-09-10T17:00:00"), "2026-09-11")


class TestEventIO(unittest.TestCase):
    def test_roundtrip_appends_and_reads_back(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "task-2026-09-10.jsonl")
            n1 = write_events(p, [{"schema": TASK_SCHEMA, "bot": "rick"}])
            n2 = write_events(p, [{"schema": TASK_SCHEMA, "bot": "morty"}])
            self.assertEqual((n1, n2), (1, 1))
            rows = list(read_events([p]))
            self.assertEqual([r["bot"] for r in rows], ["rick", "morty"])

    def test_read_skips_blank_lines_and_counts_nothing_extra(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "u.jsonl")
            with open(p, "w") as fh:
                fh.write(json.dumps({"schema": USAGE_SCHEMA}) + "\n\n")
            self.assertEqual(len(list(read_events([p]))), 1)

    def test_missing_file_yields_nothing_rather_than_raising(self):
        self.assertEqual(list(read_events(["/nonexistent/x.jsonl"])), [])


class TestParseResult(unittest.TestCase):
    def test_starts_empty_with_zeroed_health(self):
        r = ParseResult()
        self.assertEqual((r.tasks, r.usages), ([], []))
        self.assertEqual(r.health["records"], 0)
        self.assertEqual(r.health["unparsable"], 0)
        self.assertEqual(r.health["notes"], [])


class TestParseContext(unittest.TestCase):
    def _home_with_thread_map(self, tmp, mapping):
        os.makedirs(os.path.join(tmp, ".openab"))
        with open(os.path.join(tmp, ".openab", "thread_map.json"), "w") as fh:
            json.dump(mapping, fh)
        return tmp

    def test_reads_platform_prefix_from_persisted_keys(self):
        with tempfile.TemporaryDirectory() as d:
            home = self._home_with_thread_map(d, {"persisted": {
                "discord:154749": "ses_1", "slack:C0123": "ses_2"}})
            ctx = ParseContext.from_agent_home(home)
            self.assertEqual(ctx.platform_for("154749"), "discord")
            self.assertEqual(ctx.platform_for("C0123"), "slack")

    def test_unknown_thread_is_unknown_never_guessed(self):
        with tempfile.TemporaryDirectory() as d:
            home = self._home_with_thread_map(d, {"persisted": {}})
            ctx = ParseContext.from_agent_home(home)
            self.assertEqual(ctx.platform_for("999"), "unknown")

    def test_missing_thread_map_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = ParseContext.from_agent_home(d)
            self.assertEqual(ctx.platform_for("1"), "unknown")

    def test_flat_mapping_without_persisted_wrapper_also_works(self):
        with tempfile.TemporaryDirectory() as d:
            home = self._home_with_thread_map(d, {"discord:777": "ses_9"})
            ctx = ParseContext.from_agent_home(home)
            self.assertEqual(ctx.platform_for("777"), "discord")


if __name__ == "__main__":
    unittest.main()
