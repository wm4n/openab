"""report.py 的測試：日期篩選、報表資料模型、兩種文字輸出。

報表最重要的責任不是好看，而是**不讓讀者誤解數字**：缺口不能偽裝成
「沒人用」、allowlist 上界要標出來、摩擦指標不能寫成滿意度。
"""
import json
import os
import re
import tempfile
import unittest

from report import (
    build_report, load_config, load_events, main, render_md, render_text,
)


def task_event(day, bot="rick", source="human", dedup_key=None,
               sender_id="824", session_id="s1"):
    return {"schema": "openab.stats.task.v1", "bot": bot, "source": source,
            "dedup_key": dedup_key or ("discord:%s-%s" % (bot, day)),
            "sender_id": sender_id, "display_name": "william",
            "session_id": session_id, "occurred_at": day + "T06:00:00Z"}


def usage_event(day, bot="rick", model="claude-opus-5", variant=None,
                tokens=None, cost=None, cost_source="subscription",
                key=None, session_id="s1"):
    return {"schema": "openab.stats.usage.v1", "bot": bot,
            "usage_key": key or ("k-%s-%s" % (bot, day)),
            "model_id": model, "model_variant": variant,
            "tokens": {"input": 10, "output": 20} if tokens is None else tokens,
            "cost": cost, "cost_source": cost_source,
            "session_id": session_id, "occurred_at": day + "T06:05:00Z"}


def write_events_dir(root, tasks_by_day, usages_by_day):
    ev = os.path.join(root, "events")
    os.makedirs(ev)
    for day, rows in tasks_by_day.items():
        with open(os.path.join(ev, "task-%s.jsonl" % day), "w") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for day, rows in usages_by_day.items():
        with open(os.path.join(ev, "usage-%s.jsonl" % day), "w") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return root


class TestLoadConfig(unittest.TestCase):
    def test_missing_path_returns_defaults(self):
        cfg = load_config(None)
        self.assertEqual(cfg["channel_names"], {})
        self.assertEqual(cfg["allowlist_bounds"], {})

    def test_reads_json_and_merges_over_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            with open(p, "w") as fh:
                json.dump({"channel_names": {"c1": "cac-dev-team"}}, fh)
            cfg = load_config(p)
            self.assertEqual(cfg["channel_names"]["c1"], "cac-dev-team")
            self.assertEqual(cfg["pricebook"], {})

    def test_unreadable_config_raises_rather_than_silently_defaulting(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.json")
            with open(p, "w") as fh:
                fh.write("{not json")
            with self.assertRaises(ValueError):
                load_config(p)


class TestLoadEvents(unittest.TestCase):
    def test_only_loads_days_in_range(self):
        with tempfile.TemporaryDirectory() as d:
            root = write_events_dir(
                d,
                {"2026-09-08": [task_event("2026-09-08")],
                 "2026-09-09": [task_event("2026-09-09")],
                 "2026-09-10": [task_event("2026-09-10")]},
                {})
            tasks, _ = load_events(os.path.join(root, "events"),
                                   "2026-09-09", "2026-09-10")
            self.assertEqual(len(tasks), 2)

    def test_includes_unknown_bucket_so_it_is_never_lost(self):
        with tempfile.TemporaryDirectory() as d:
            root = write_events_dir(d, {"unknown": [task_event("2026-09-09")]}, {})
            tasks, _ = load_events(os.path.join(root, "events"),
                                   "2026-09-01", "2026-09-30")
            self.assertEqual(len(tasks), 1)

    def test_empty_dir_returns_two_empty_lists(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_events(d, "2026-09-01", "2026-09-30"), ([], []))


class TestBuildReport(unittest.TestCase):
    def _report(self, tasks=None, usages=None, config=None, health=None):
        return build_report(tasks or [], usages or [], config or load_config(None),
                            "2026-09-09", "2026-09-10", health or {})

    def test_flattens_token_tuple_keys_into_rows(self):
        rep = self._report(usages=[usage_event("2026-09-10", model="x",
                                               variant="low")])
        self.assertEqual(len(rep["token_rows"]), 1)
        row = rep["token_rows"][0]
        self.assertEqual((row["model_id"], row["model_variant"]), ("x", "low"))
        self.assertEqual(row["day"], "2026-09-10")

    def test_states_timezone_explicitly(self):
        self.assertEqual(self._report()["timezone"], "Asia/Taipei")

    def test_carries_allowlist_bounds_from_config(self):
        cfg = load_config(None)
        cfg["allowlist_bounds"] = {"rick": 1}
        rep = self._report(tasks=[task_event("2026-09-10")], config=cfg)
        self.assertEqual(rep["allowlist_bounds"]["rick"], 1)

    def test_reports_missing_days_in_coverage(self):
        rep = self._report(tasks=[task_event("2026-09-08"),
                                  task_event("2026-09-10")])
        self.assertIn("2026-09-09", rep["coverage"]["missing_days"])

    def test_includes_all_six_metric_sections(self):
        rep = self._report()
        for key in ("daily_tasks", "daily_conversations", "token_rows",
                    "daily_cost", "active_users", "attribution", "friction",
                    "failure_proxy"):
            self.assertIn(key, rep)


class TestRenderText(unittest.TestCase):
    def _rendered(self, **kw):
        rep = build_report(kw.get("tasks", []), kw.get("usages", []),
                           kw.get("config", load_config(None)),
                           "2026-09-09", "2026-09-10", kw.get("health", {}))
        return render_text(rep)

    def test_never_labels_a_metric_as_satisfaction(self):
        # 章節標題「[摩擦指標] 不是滿意度」本身含「滿意度」，那是想要的否定
        # 語境。真正的需求是：每一次出現「滿意」都必須緊接在「不是」之後。
        out = self._rendered(tasks=[task_event("2026-09-10")])
        self.assertIn("摩擦指標", out)
        for match in re.finditer("滿意", out):
            self.assertEqual(out[max(0, match.start() - 2):match.start()],
                             "不是", "「滿意」出現在非否定語境")

    def test_states_that_task_counts_exclude_failures(self):
        out = self._rendered(tasks=[task_event("2026-09-10")])
        self.assertIn("僅含成功", out)

    def test_shows_timezone_in_header(self):
        self.assertIn("Asia/Taipei", self._rendered())

    def test_flags_allowlist_bound_so_one_user_is_not_read_as_low_adoption(self):
        cfg = load_config(None)
        cfg["allowlist_bounds"] = {"rick": 1}
        out = self._rendered(tasks=[task_event("2026-09-10")], config=cfg)
        self.assertIn("allowlist", out)

    def test_warns_about_missing_days(self):
        out = self._rendered(tasks=[task_event("2026-09-08"),
                                    task_event("2026-09-10")])
        self.assertIn("2026-09-09", out)

    def test_notes_that_daily_conversation_sums_exceed_reality(self):
        out = self._rendered(tasks=[task_event("2026-09-10")])
        self.assertIn("逐日加總", out)

    def test_resolves_channel_names_when_configured(self):
        cfg = load_config(None)
        cfg["channel_names"] = {"c1": "cac-dev-team"}
        rep = build_report([task_event("2026-09-10")], [], cfg,
                           "2026-09-09", "2026-09-10", {})
        self.assertEqual(rep["channel_names"]["c1"], "cac-dev-team")


class TestRenderMd(unittest.TestCase):
    def test_produces_markdown_tables(self):
        rep = build_report([task_event("2026-09-10")], [], load_config(None),
                           "2026-09-09", "2026-09-10", {})
        out = render_md(rep)
        self.assertIn("| ", out)
        self.assertIn("# ", out)

    def test_separates_cost_sources_and_marks_subscription(self):
        usages = [usage_event("2026-09-10", cost=1.5, cost_source="cli"),
                  usage_event("2026-09-10", cost=None,
                              cost_source="subscription", key="k2")]
        rep = build_report([], usages, load_config(None),
                           "2026-09-09", "2026-09-10", {})
        out = render_md(rep)
        self.assertIn("訂閱制", out)
        self.assertIn("1.5", out)


class TestMain(unittest.TestCase):
    def test_writes_markdown_to_output_path(self):
        with tempfile.TemporaryDirectory() as d:
            write_events_dir(d, {"2026-09-10": [task_event("2026-09-10")]}, {})
            out = os.path.join(d, "r.md")
            rc = main(["--data", d, "--since", "2026-09-10",
                       "--until", "2026-09-10", "--format", "md", "-o", out])
            self.assertEqual(rc, 0)
            with open(out) as fh:
                self.assertIn("# ", fh.read())

    def test_bots_filter_narrows_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            write_events_dir(d, {"2026-09-10": [
                task_event("2026-09-10", bot="rick"),
                task_event("2026-09-10", bot="morty")]}, {})
            out = os.path.join(d, "r.md")
            main(["--data", d, "--since", "2026-09-10", "--until", "2026-09-10",
                  "--bots", "rick", "--format", "md", "-o", out])
            with open(out) as fh:
                body = fh.read()
            self.assertIn("rick", body)
            self.assertNotIn("morty", body)

    def test_missing_data_dir_returns_nonzero(self):
        self.assertNotEqual(
            main(["--data", "/nonexistent", "--since", "2026-09-10",
                  "--until", "2026-09-10"]), 0)

    def test_since_after_until_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            write_events_dir(d, {}, {})
            self.assertNotEqual(
                main(["--data", d, "--since", "2026-09-10",
                      "--until", "2026-09-01"]), 0)


if __name__ == "__main__":
    unittest.main()
