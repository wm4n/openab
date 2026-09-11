"""aggregate.py 用量側指標的測試。

成本三段不可混加、token 的 model 維度是 (id, variant)、歸因到 session 層。
"""
import unittest

from aggregate import (
    TOKEN_KINDS, daily_cost, daily_tokens, dedupe_usages, session_attribution,
)


def usage(usage_key, tokens=None, bot="rick", model="claude-opus-5",
          variant=None, ts="2026-09-10T06:33:00Z", cost=None,
          cost_source="subscription", session_id="s1", origin="main"):
    return {"bot": bot, "usage_key": usage_key,
            "tokens": {"input": 100, "output": 200} if tokens is None else tokens,
            "model_id": model, "model_variant": variant, "occurred_at": ts,
            "cost": cost, "cost_source": cost_source,
            "session_id": session_id, "origin": origin}


def task(dedup_key, sender_id="824", session_id="s1", bot="rick",
         source="human", ts="2026-09-10T06:32:10Z"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "sender_id": sender_id, "session_id": session_id,
            "occurred_at": ts, "display_name": "william"}


class TestDedupeUsages(unittest.TestCase):
    def test_rerun_of_collector_does_not_double_count(self):
        rows = dedupe_usages([usage("f#1#main"), usage("f#1#main")])
        self.assertEqual(len(rows), 1)

    def test_different_origin_on_same_offset_is_distinct(self):
        # claude-code 一筆紀錄可能同時有 main 與 subagent 用量
        rows = dedupe_usages([usage("f#1#main"), usage("f#1#subagent")])
        self.assertEqual(len(rows), 2)


class TestDailyTokens(unittest.TestCase):
    def test_groups_by_model_and_variant_tuple(self):
        rows = [usage("k1", model="deepseek/x", variant="low"),
                usage("k2", model="deepseek/x", variant="default")]
        got = daily_tokens(rows)["2026-09-10"]["rick"]
        self.assertEqual(sorted(got), [("deepseek/x", "default"),
                                       ("deepseek/x", "low")])

    def test_sums_each_kind_separately_never_totalling(self):
        rows = [usage("k1", {"input": 10, "output": 20, "cache_read": 30}),
                usage("k2", {"input": 1, "output": 2, "cache_read": 3})]
        got = daily_tokens(rows)["2026-09-10"]["rick"][("claude-opus-5", None)]
        self.assertEqual(got["input"], 11)
        self.assertEqual(got["cache_read"], 33)

    def test_absent_kind_is_omitted_not_zeroed(self):
        # 「不支援」與 0 必須可區分
        got = daily_tokens([usage("k1", {"input": 5})])
        bucket = got["2026-09-10"]["rick"][("claude-opus-5", None)]
        self.assertNotIn("cache_write", bucket)

    def test_session_cost_events_contribute_no_tokens(self):
        # opencode 的成本事件 tokens 是空 dict —— 結構上不可能重複計算
        rows = [usage("m1", {"input": 10}),
                usage("sc1", {}, cost=1.5, cost_source="cli",
                      origin="session_cost")]
        got = daily_tokens(rows)["2026-09-10"]["rick"]
        self.assertEqual(sum(v.get("input", 0) for v in got.values()), 10)

    def test_all_five_kinds_are_recognised(self):
        full = dict.fromkeys(TOKEN_KINDS, 7)
        got = daily_tokens([usage("k1", full)])["2026-09-10"]["rick"]
        self.assertEqual(got[("claude-opus-5", None)], full)


class TestDailyCost(unittest.TestCase):
    def test_keeps_cost_sources_separate(self):
        rows = [usage("k1", cost=1.5, cost_source="cli"),
                usage("k2", cost=None, cost_source="subscription")]
        got = daily_cost(rows)["2026-09-10"]["rick"]
        self.assertAlmostEqual(got["cli"], 1.5)
        self.assertEqual(got["subscription"], 0.0)

    def test_subscription_never_accumulates_money(self):
        # Claude 家族走訂閱制，token 數不等於帳單金額
        rows = [usage("k1", cost=99.0, cost_source="subscription")]
        self.assertEqual(daily_cost(rows)["2026-09-10"]["rick"]["subscription"],
                         0.0)

    def test_unavailable_is_reported_as_a_category(self):
        rows = [usage("k1", cost=None, cost_source="unavailable")]
        self.assertIn("unavailable", daily_cost(rows)["2026-09-10"]["rick"])


class TestSessionAttribution(unittest.TestCase):
    def test_single_human_session_is_attributed_unambiguously(self):
        tasks = [task("d:1", sender_id="824", session_id="sA")]
        usages = [usage("k1", {"input": 100}, session_id="sA")]
        got = session_attribution(tasks, usages)["rick"]
        self.assertEqual(got["attributed"]["824"]["input"], 100)
        self.assertEqual(got["coverage"], 1.0)

    def test_multi_human_session_goes_to_shared_not_split(self):
        tasks = [task("d:1", sender_id="824", session_id="sA"),
                 task("d:2", sender_id="999", session_id="sA")]
        usages = [usage("k1", {"input": 100}, session_id="sA")]
        got = session_attribution(tasks, usages)["rick"]
        self.assertEqual(got["shared"]["input"], 100)
        self.assertEqual(got["attributed"], {})
        self.assertEqual(got["coverage"], 0.0)

    def test_session_with_no_human_task_is_unattributed(self):
        # 例如純 cron 開的 session
        tasks = [task("d:1", source="cron", sender_id="openab-cron",
                      session_id="sA")]
        usages = [usage("k1", {"input": 100}, session_id="sA")]
        got = session_attribution(tasks, usages)["rick"]
        self.assertEqual(got["unattributed"]["input"], 100)

    def test_coverage_is_the_unambiguous_share_of_total_tokens(self):
        tasks = [task("d:1", sender_id="824", session_id="sA"),
                 task("d:2", sender_id="824", session_id="sB"),
                 task("d:3", sender_id="999", session_id="sB")]
        usages = [usage("k1", {"input": 300}, session_id="sA"),
                  usage("k2", {"input": 100}, session_id="sB")]
        got = session_attribution(tasks, usages)["rick"]
        self.assertAlmostEqual(got["coverage"], 0.75)

    def test_coverage_is_zero_when_there_is_nothing_to_attribute(self):
        self.assertEqual(session_attribution([], []), {})


if __name__ == "__main__":
    unittest.main()
