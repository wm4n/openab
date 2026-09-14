"""週對週趨勢：把逐日指標捲成 ISO 週，長區間報表才看得出走勢。

2026-09-10 是星期四，屬於 ISO 2026-W37；2026-09-14 是星期一，屬於下一週
2026-W38——用來確認捲週時日期正確落在對的週。
"""
import unittest

from aggregate import weekly_cost, weekly_task_counts


def task(dedup_key, day, bot="rick", source="human"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "occurred_at": day + "T06:00:00Z"}


def usage(usage_key, day, bot="rick", cost=1.0, cost_source="cli"):
    return {"bot": bot, "usage_key": usage_key, "tokens": {},
            "model_id": "m", "model_variant": None,
            "occurred_at": day + "T06:00:00Z",
            "cost": cost, "cost_source": cost_source, "session_id": "s1",
            "origin": "session_cost"}


class TestWeeklyTaskCounts(unittest.TestCase):
    def test_groups_days_into_the_same_iso_week(self):
        rows = [task("d:1", "2026-09-08"), task("d:2", "2026-09-10")]
        got = weekly_task_counts(rows)
        self.assertEqual(sorted(got), ["2026-W37"])
        self.assertEqual(got["2026-W37"]["rick"]["human"], 2)

    def test_splits_across_week_boundary(self):
        rows = [task("d:1", "2026-09-10"),   # 2026-W37
                task("d:2", "2026-09-14")]   # 2026-W38（星期一）
        got = weekly_task_counts(rows)
        self.assertEqual(sorted(got), ["2026-W37", "2026-W38"])

    def test_deduplicates_before_rolling_up(self):
        rows = [task("d:1", "2026-09-10"), task("d:1", "2026-09-10")]
        self.assertEqual(weekly_task_counts(rows)["2026-W37"]["rick"]["human"], 1)

    def test_unknown_day_bucket_is_preserved_not_dropped(self):
        rows = [dict(task("d:1", "2026-09-10"), occurred_at=None)]
        self.assertIn("unknown", weekly_task_counts(rows))


class TestWeeklyCost(unittest.TestCase):
    def test_sums_cost_within_the_same_week(self):
        rows = [usage("k1", "2026-09-08", cost=1.5),
                usage("k2", "2026-09-10", cost=0.5)]
        got = weekly_cost(rows)
        self.assertAlmostEqual(got["2026-W37"]["rick"]["cli"], 2.0)

    def test_splits_across_week_boundary(self):
        rows = [usage("k1", "2026-09-10", cost=1.0),
                usage("k2", "2026-09-14", cost=2.0)]
        got = weekly_cost(rows)
        self.assertAlmostEqual(got["2026-W37"]["rick"]["cli"], 1.0)
        self.assertAlmostEqual(got["2026-W38"]["rick"]["cli"], 2.0)

    def test_subscription_never_accumulates_money(self):
        rows = [usage("k1", "2026-09-10", cost=None, cost_source="subscription")]
        self.assertEqual(weekly_cost(rows)["2026-W37"]["rick"]["subscription"], 0.0)


if __name__ == "__main__":
    unittest.main()
