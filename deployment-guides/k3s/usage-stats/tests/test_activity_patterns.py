"""尖峰時段（小時／星期幾）分布的測試。

只算真人任務：cron 的時間點是排程設定值不是使用行為，bot 互呼跟隨真人
任務發生，兩者都會扭曲「人類什麼時候在用」這個問題。
"""
import unittest

from aggregate import hourly_activity, weekday_activity


def task(dedup_key, ts, bot="rick", source="human"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "occurred_at": ts}


class TestHourlyActivity(unittest.TestCase):
    def test_converts_to_taipei_local_hour(self):
        # 06:32Z = 台北 14:32
        rows = [task("d:1", "2026-09-10T06:32:10Z")]
        self.assertEqual(hourly_activity(rows)["rick"][14], 1)

    def test_crosses_midnight_into_next_taipei_day_hour(self):
        # 17:00Z = 台北隔日 01:00
        rows = [task("d:1", "2026-09-10T17:00:00Z")]
        self.assertEqual(hourly_activity(rows)["rick"][1], 1)

    def test_all_24_hours_present_with_real_zero(self):
        rows = [task("d:1", "2026-09-10T06:32:10Z")]
        got = hourly_activity(rows)["rick"]
        self.assertEqual(len(got), 24)
        self.assertEqual(got[0], 0)

    def test_excludes_cron_and_bot_relay(self):
        rows = [task("d:1", "2026-09-10T06:32:10Z", source="cron"),
                task("d:2", "2026-09-10T06:32:10Z", source="bot_relay")]
        self.assertEqual(hourly_activity(rows), {})

    def test_deduplicates_before_counting(self):
        rows = [task("d:1", "2026-09-10T06:32:10Z"),
                task("d:1", "2026-09-10T06:32:10Z")]
        self.assertEqual(hourly_activity(rows)["rick"][14], 1)

    def test_task_without_timestamp_is_skipped_not_crashed(self):
        rows = [dict(task("d:1", "2026-09-10T06:32:10Z"), occurred_at=None)]
        self.assertEqual(hourly_activity(rows), {})


class TestWeekdayActivity(unittest.TestCase):
    def test_labels_are_traditional_chinese_weekday_names(self):
        # 2026-09-10 是星期四
        rows = [task("d:1", "2026-09-10T06:32:10Z")]
        self.assertEqual(weekday_activity(rows)["rick"]["四"], 1)

    def test_crosses_into_next_taipei_weekday(self):
        # 17:00Z = 台北隔日(星期五) 01:00
        rows = [task("d:1", "2026-09-10T17:00:00Z")]
        self.assertEqual(weekday_activity(rows)["rick"]["五"], 1)

    def test_all_seven_days_present_with_real_zero(self):
        rows = [task("d:1", "2026-09-10T06:32:10Z")]
        got = weekday_activity(rows)["rick"]
        self.assertEqual(len(got), 7)
        self.assertEqual(got["一"], 0)

    def test_excludes_cron_and_bot_relay(self):
        rows = [task("d:1", "2026-09-10T06:32:10Z", source="cron")]
        self.assertEqual(weekday_activity(rows), {})


if __name__ == "__main__":
    unittest.main()
