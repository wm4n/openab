"""aggregate.py 任務側指標的測試。

去重、三分類、以及「新開 vs 延續對話」的日界線判斷。
"""
import unittest

from aggregate import (
    active_users, daily_conversations, daily_per_user, daily_task_counts,
    dedupe_tasks,
)


def task(dedup_key, source="human", bot="rick", ts="2026-09-10T06:32:10Z",
         sender_id="824", display_name="william", session_id="s1"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "occurred_at": ts, "sender_id": sender_id,
            "display_name": display_name, "session_id": session_id}


class TestDedupeTasks(unittest.TestCase):
    def test_same_task_from_two_paths_collapses_to_one(self):
        rows = dedupe_tasks([task("discord:m1"), task("discord:m1")])
        self.assertEqual(len(rows), 1)

    def test_different_bots_with_same_message_id_are_kept_separate(self):
        # 同一則 Discord 訊息可能同時 @ 兩隻 bot —— 那是兩個任務
        rows = dedupe_tasks([task("discord:m1", bot="rick"),
                             task("discord:m1", bot="morty")])
        self.assertEqual(len(rows), 2)

    def test_keeps_first_occurrence_order_stable(self):
        rows = dedupe_tasks([task("discord:m1", display_name="first"),
                             task("discord:m1", display_name="second")])
        self.assertEqual(rows[0]["display_name"], "first")

    def test_empty_input(self):
        self.assertEqual(dedupe_tasks([]), [])


class TestDailyTaskCounts(unittest.TestCase):
    def test_splits_three_sources_and_never_merges_them(self):
        rows = [task("d:1", "human"), task("d:2", "human"),
                task("d:3", "bot_relay"), task("d:4", "cron"), task("d:5", "cron")]
        got = daily_task_counts(rows)
        self.assertEqual(got["2026-09-10"]["rick"],
                         {"human": 2, "bot_relay": 1, "cron": 2})

    def test_uses_taipei_day_boundary(self):
        # 17:30Z = 台北隔日 01:30
        rows = [task("d:1", ts="2026-09-10T17:30:00Z")]
        self.assertIn("2026-09-11", daily_task_counts(rows))

    def test_deduplicates_before_counting(self):
        got = daily_task_counts([task("d:1"), task("d:1")])
        self.assertEqual(got["2026-09-10"]["rick"]["human"], 1)

    def test_task_without_timestamp_lands_in_unknown_bucket(self):
        rows = [dict(task("d:1"), occurred_at=None)]
        self.assertEqual(daily_task_counts(rows)["unknown"]["rick"]["human"], 1)

    def test_zero_source_still_present_so_reader_sees_a_real_zero(self):
        got = daily_task_counts([task("d:1", "human")])
        self.assertEqual(got["2026-09-10"]["rick"]["cron"], 0)


class TestDailyPerUser(unittest.TestCase):
    def test_counts_only_human_tasks(self):
        rows = [task("d:1", "human", sender_id="824"),
                task("d:2", "human", sender_id="824"),
                task("d:3", "human", sender_id="999"),
                task("d:4", "cron", sender_id="openab-cron")]
        got = daily_per_user(rows)
        self.assertEqual(got["2026-09-10"]["rick"], {"824": 2, "999": 1})

    def test_cron_sender_never_appears(self):
        got = daily_per_user([task("d:1", "cron", sender_id="openab-cron")])
        self.assertEqual(got, {})


class TestActiveUsers(unittest.TestCase):
    def test_counts_distinct_humans_per_bot(self):
        rows = [task("d:1", sender_id="824", display_name="william"),
                task("d:2", sender_id="999", display_name="Alice")]
        got = active_users(rows)
        self.assertEqual(sorted(got["rick"]), ["824", "999"])
        self.assertEqual(got["rick"]["824"]["tasks"], 1)

    def test_display_name_takes_the_most_recent_occurrence(self):
        # 名稱會隨改名而變；聚合以 sender_id 為準，顯示取最近一次
        rows = [task("d:1", sender_id="824", display_name="old",
                     ts="2026-09-01T00:00:00Z"),
                task("d:2", sender_id="824", display_name="new",
                     ts="2026-09-10T00:00:00Z")]
        self.assertEqual(active_users(rows)["rick"]["824"]["display_name"], "new")


class TestDailyConversations(unittest.TestCase):
    def test_first_day_of_a_session_is_new(self):
        rows = [task("d:1", session_id="sA", ts="2026-09-10T06:00:00Z")]
        self.assertEqual(daily_conversations(rows)["2026-09-10"]["rick"],
                         {"new": 1, "continued": 0})

    def test_later_day_of_same_session_is_continued(self):
        rows = [task("d:1", session_id="sA", ts="2026-09-10T06:00:00Z"),
                task("d:2", session_id="sA", ts="2026-09-11T06:00:00Z")]
        got = daily_conversations(rows)
        self.assertEqual(got["2026-09-10"]["rick"], {"new": 1, "continued": 0})
        self.assertEqual(got["2026-09-11"]["rick"], {"new": 0, "continued": 1})

    def test_multiple_tasks_in_one_session_count_the_session_once(self):
        rows = [task("d:1", session_id="sA"), task("d:2", session_id="sA")]
        self.assertEqual(daily_conversations(rows)["2026-09-10"]["rick"]["new"], 1)

    def test_counts_all_sources_not_just_human(self):
        # 對話數是資源指標，cron 開的 session 也佔資源
        rows = [task("d:1", "cron", session_id="sA")]
        self.assertEqual(daily_conversations(rows)["2026-09-10"]["rick"]["new"], 1)

    def test_task_without_session_id_is_ignored_for_conversations(self):
        rows = [dict(task("d:1"), session_id=None)]
        self.assertEqual(daily_conversations(rows), {})


if __name__ == "__main__":
    unittest.main()
