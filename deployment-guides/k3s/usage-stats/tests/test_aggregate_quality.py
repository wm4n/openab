"""摩擦指標、失敗率代理、資料覆蓋率的測試。

這三項都是弱訊號或粗略代理，測試同時鎖住「它們算得對」與「它們不會假裝精確」。
"""
import unittest

from aggregate import data_coverage, failure_proxy, friction_signals


def task(dedup_key, ts, session_id="sA", bot="rick", sender_id="824",
         source="human"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "sender_id": sender_id, "session_id": session_id,
            "occurred_at": ts}


class TestFrictionSignals(unittest.TestCase):
    def test_followup_median_uses_gaps_between_same_sender_tasks(self):
        rows = [task("d:1", "2026-09-10T06:00:00Z"),
                task("d:2", "2026-09-10T06:01:00Z"),   # +60s
                task("d:3", "2026-09-10T06:04:00Z")]   # +180s
        got = friction_signals(rows)["rick"]
        self.assertEqual(got["followup_median_seconds"], 120.0)

    def test_single_task_session_has_no_followup_median(self):
        got = friction_signals([task("d:1", "2026-09-10T06:00:00Z")])["rick"]
        self.assertIsNone(got["followup_median_seconds"])

    def test_tasks_per_session_averages_human_tasks(self):
        rows = [task("d:1", "2026-09-10T06:00:00Z", session_id="sA"),
                task("d:2", "2026-09-10T06:01:00Z", session_id="sA"),
                task("d:3", "2026-09-10T06:02:00Z", session_id="sB")]
        self.assertEqual(friction_signals(rows)["rick"]["tasks_per_session"], 1.5)

    def test_no_message_content_is_needed_or_reported(self):
        # 第一版刻意不擷取對話內容：留下的兩個訊號只需要時間戳與 session ID
        rows = [task("d:1", "2026-09-10T06:00:00Z")]
        self.assertEqual(set(rows[0]) & {"prompt", "prompt_excerpt", "text"},
                         set())
        self.assertNotIn("negative_hits", friction_signals(rows)["rick"])

    def test_abandoned_session_is_one_that_only_ever_had_one_task(self):
        rows = [task("d:1", "2026-09-10T06:00:00Z", session_id="sA"),
                task("d:2", "2026-09-10T06:01:00Z", session_id="sA"),
                task("d:3", "2026-09-10T07:00:00Z", session_id="sB")]
        self.assertEqual(friction_signals(rows)["rick"]["abandoned_sessions"], 1)

    def test_cron_and_bot_tasks_are_excluded_from_friction(self):
        # 摩擦是人的感受，排程與 bot 互呼不算
        rows = [task("d:1", "2026-09-10T06:00:00Z", source="cron"),
                task("d:2", "2026-09-10T06:01:00Z", source="bot_relay")]
        self.assertEqual(friction_signals(rows), {})


class TestFailureProxy(unittest.TestCase):
    def test_gap_is_sessions_created_minus_sessions_with_output(self):
        # 實測 morty：thread_map 18 筆，只有 2 個 session 產出過 task
        counts = {"morty": 18}
        tasks = [task("d:1", "2026-09-10T06:00:00Z", session_id="s1", bot="morty"),
                 task("d:2", "2026-09-10T06:01:00Z", session_id="s2", bot="morty")]
        got = failure_proxy(counts, tasks)["morty"]
        self.assertEqual(got, {"sessions_created": 18,
                               "sessions_with_output": 2, "gap": 16})

    def test_more_output_sessions_than_thread_map_gives_negative_clamped_to_zero(self):
        # genie 實測 160 進 362 出（一 thread 多任務 + entry 會被移除）
        counts = {"genie": 2}
        # dedup_key 必須各不相同 —— 共用同一個會被 dedupe_tasks 收斂成一筆
        tasks = [task("d:%d" % i, "2026-09-10T06:00:00Z",
                      session_id="s%d" % i, bot="genie") for i in range(5)]
        self.assertEqual(failure_proxy(counts, tasks)["genie"]["gap"], 0)

    def test_bot_with_no_thread_map_entry_reports_none_not_zero(self):
        tasks = [task("d:1", "2026-09-10T06:00:00Z", bot="rick")]
        got = failure_proxy({}, tasks)["rick"]
        self.assertIsNone(got["sessions_created"])
        self.assertIsNone(got["gap"])


class TestDataCoverage(unittest.TestCase):
    def test_reports_missing_days_so_gaps_do_not_look_like_no_usage(self):
        got = data_coverage(["2026-09-08", "2026-09-10"], {})
        self.assertEqual(got["missing_days"], ["2026-09-09"])
        self.assertEqual(got["days_expected"], 3)
        self.assertEqual(got["days_present"], 2)

    def test_single_day_has_no_gap(self):
        got = data_coverage(["2026-09-10"], {})
        self.assertEqual(got["missing_days"], [])

    def test_surfaces_unparsable_count_from_collect_health(self):
        health = {"bots": {"rick": {"unparsable": 3}, "morty": {"unparsable": 1}}}
        self.assertEqual(data_coverage(["2026-09-10"], health)["unparsable"], 4)

    def test_surfaces_unrecognised_bots(self):
        health = {"unrecognised": ["ghost"]}
        self.assertEqual(data_coverage(["2026-09-10"], health)["unrecognised"],
                         ["ghost"])

    def test_no_days_at_all_is_reported_not_crashed(self):
        got = data_coverage([], {})
        self.assertEqual((got["days_expected"], got["days_present"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
