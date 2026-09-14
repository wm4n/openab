"""尖峰時段與週對週趨勢在三種報表格式裡的呈現。

aggregate.py 已經算出 hourly_activity／weekday_activity／weekly_task_counts／
weekly_cost，這裡鎖住 build_report 有把它們接進去、三種格式都看得到。
"""
import unittest

from report import build_report, load_config, render_md, render_text


def task(dedup_key, ts, bot="rick", source="human"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "occurred_at": ts}


def usage(usage_key, ts, bot="rick", cost=2.5, cost_source="cli"):
    return {"bot": bot, "usage_key": usage_key, "tokens": {},
            "model_id": "m", "model_variant": None, "occurred_at": ts,
            "cost": cost, "cost_source": cost_source, "session_id": "s1",
            "origin": "session_cost"}


def report_for(tasks=None, usages=None):
    return build_report(tasks or [], usages or [], load_config(None),
                        "2026-09-08", "2026-09-14", {})


class TestReportCarriesTimePatterns(unittest.TestCase):
    def test_build_report_includes_all_four_new_sections(self):
        rep = report_for()
        for key in ("hourly_activity", "weekday_activity", "weekly_tasks",
                    "weekly_cost"):
            self.assertIn(key, rep)


class TestPeakHoursInRenderers(unittest.TestCase):
    def _report(self):
        # 06:32Z = 台北 14:32、星期四
        return report_for(tasks=[task("d:1", "2026-09-10T06:32:10Z")])

    def test_text_report_shows_hour_and_weekday(self):
        out = render_text(self._report())
        self.assertIn("尖峰時段", out)
        self.assertIn("14=1", out)
        self.assertIn("四=1", out)

    def test_markdown_report_has_a_peak_hours_table(self):
        out = render_md(self._report())
        self.assertIn("尖峰時段", out)
        self.assertIn("14=1", out)
        self.assertIn("四=1", out)


class TestWeeklyTrendInRenderers(unittest.TestCase):
    def _report(self):
        tasks = [task("d:1", "2026-09-10T06:00:00Z"),   # 2026-W37
                 task("d:2", "2026-09-14T06:00:00Z")]   # 2026-W38
        usages = [usage("k1", "2026-09-10T06:00:00Z", cost=2.5),
                  usage("k2", "2026-09-14T06:00:00Z", cost=1.0)]
        return report_for(tasks, usages)

    def test_text_report_shows_both_weeks(self):
        out = render_text(self._report())
        self.assertIn("週對週趨勢", out)
        self.assertIn("2026-W37", out)
        self.assertIn("2026-W38", out)

    def test_markdown_report_has_a_weekly_trend_table(self):
        out = render_md(self._report())
        self.assertIn("2026-W37", out)
        self.assertIn("2.5000", out)
        self.assertIn("2026-W38", out)
        self.assertIn("1.0000", out)


if __name__ == "__main__":
    unittest.main()
