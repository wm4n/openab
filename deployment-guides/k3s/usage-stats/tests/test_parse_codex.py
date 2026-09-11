"""codex parser 的測試。

最大陷阱：payload.info.total_token_usage 是 session 累積值，每個 token_count
event 都重報一次。實測加總所有 event 的 total_token_usage 會比正確值大 19.4 倍。
"""
import json
import os
import tempfile
import unittest

from events import ParseContext
from parse_codex import CumulativeMismatch, parse, tokens_from_last_usage

SC = ('<sender_context>\n{"schema":"openab.sender.v1","sender_id":"824",'
      '"sender_name":"wm4n","display_name":"william","channel":"discord",'
      '"channel_id":"c1","thread_id":"t1","is_bot":false,'
      '"timestamp":"2026-09-10T06:32:10Z","message_id":"m1"}\n</sender_context>')


def token_count_event(last, total, model="gpt-5.5", ts="2026-09-10T06:33:00Z"):
    return {"timestamp": ts, "type": "event_msg",
            "payload": {"type": "token_count", "model": model,
                        "info": {"last_token_usage": last,
                                 "total_token_usage": total}}}


def usage(inp, out, cached=0, reasoning=0):
    return {"input_tokens": inp, "output_tokens": out,
            "cached_input_tokens": cached,
            "reasoning_output_tokens": reasoning,
            "total_tokens": inp + out}


class TestTokensFromLastUsage(unittest.TestCase):
    def test_cached_is_subtracted_from_input_because_it_is_a_subset(self):
        # 實測 codex：total = input + output，所以 cached ⊂ input
        got = tokens_from_last_usage(usage(100, 20, cached=90))
        self.assertEqual(got["tokens"], {"input": 10, "output": 20,
                                         "cache_read": 90, "cache_write": 0})

    def test_disjoint_fields_sum_to_billable_total(self):
        got = tokens_from_last_usage(usage(100, 20, cached=90))
        self.assertEqual(sum(got["tokens"].values()), 120)  # = total_tokens

    def test_reasoning_goes_to_tokens_info_not_tokens(self):
        got = tokens_from_last_usage(usage(100, 20, cached=90, reasoning=5))
        self.assertNotIn("reasoning", got["tokens"])
        self.assertEqual(got["tokens_info"], {"reasoning": 5})

    def test_total_tokens_field_is_never_copied_into_tokens(self):
        got = tokens_from_last_usage(usage(100, 20))
        self.assertNotIn("total_tokens", got["tokens"])
        self.assertNotIn("total", got["tokens"])

    def test_cached_exceeding_input_clamps_to_zero_rather_than_going_negative(self):
        got = tokens_from_last_usage(usage(50, 10, cached=80))
        self.assertEqual(got["tokens"]["input"], 0)
        self.assertEqual(got["tokens"]["cache_read"], 80)


class TestParse(unittest.TestCase):
    def _home(self, tmp, records):
        d = os.path.join(tmp, ".codex", "sessions", "2026", "09", "10")
        os.makedirs(d)
        with open(os.path.join(d, "rollout-s1.jsonl"), "w") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.makedirs(os.path.join(tmp, ".openab"))
        with open(os.path.join(tmp, ".openab", "thread_map.json"), "w") as fh:
            json.dump({"persisted": {"discord:t1": "s1"}}, fh)
        return tmp

    def test_sums_last_usage_not_cumulative_total(self):
        # 三次呼叫，各 100 input；total_token_usage 是累積 100/200/300
        records = [
            token_count_event(usage(100, 10), usage(100, 10)),
            token_count_event(usage(100, 10), usage(200, 20)),
            token_count_event(usage(100, 10), usage(300, 30)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual(len(res.usages), 3)
            total_input = sum(u["tokens"]["input"] for u in res.usages)
            self.assertEqual(total_input, 300)   # 不是 600（累積值加總）

    def test_cross_check_passes_when_last_sums_to_final_cumulative(self):
        records = [
            token_count_event(usage(100, 10), usage(100, 10)),
            token_count_event(usage(100, 10), usage(200, 20)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual(res.health["unparsable"], 0)
            self.assertTrue(any("交叉驗證通過" in n for n in res.health["notes"]))

    def test_cross_check_raises_when_semantics_do_not_hold(self):
        # 刻意讓 last 加總不等於最後一筆 total —— 代表對 event 語意理解有誤
        records = [
            token_count_event(usage(100, 10), usage(100, 10)),
            token_count_event(usage(100, 10), usage(999, 99)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            with self.assertRaises(CumulativeMismatch):
                parse(home, "summer", ParseContext.from_agent_home(home), {})

    def test_emits_task_from_payload_content_text(self):
        records = [{"timestamp": "2026-09-10T06:32:11Z", "type": "response_item",
                    "payload": {"type": "message", "role": "user",
                                "content": [{"type": "input_text", "text": SC}]}}]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual(len(res.tasks), 1)
            self.assertEqual(res.tasks[0]["dedup_key"], "discord:m1")
            self.assertEqual(res.tasks[0]["cli"], "codex")

    def test_same_task_in_both_paths_produces_two_events_with_one_dedup_key(self):
        # 實測 summer：74 筆 sender_context 只有 37 個 distinct message_id
        records = [
            {"timestamp": "2026-09-10T06:32:11Z", "type": "response_item",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": SC}]}},
            {"timestamp": "2026-09-10T06:32:11Z", "type": "event_msg",
             "payload": {"type": "user_message", "message": SC}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual(len(res.tasks), 2)
            self.assertEqual({t["dedup_key"] for t in res.tasks}, {"discord:m1"})
            self.assertEqual({t["source_ref"] for t in res.tasks},
                             {"payload.content[].text", "payload.message"})

    def test_model_comes_from_payload_model_not_collaboration_settings(self):
        records = [{"timestamp": "2026-09-10T06:33:00Z", "type": "event_msg",
                    "payload": {"type": "token_count", "model": "gpt-5.5",
                                "collaboration_mode": {
                                    "settings": {"model": "should-be-ignored"}},
                                "info": {"last_token_usage": usage(10, 1),
                                         "total_token_usage": usage(10, 1)}}}]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual([u["model_id"] for u in res.usages], ["gpt-5.5"])
            self.assertEqual(len({u["usage_key"] for u in res.usages}), 1)

    def test_unparsable_line_is_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, [])
            path = os.path.join(home, ".codex", "sessions", "2026", "09", "10",
                                "rollout-s1.jsonl")
            with open(path, "w") as fh:
                fh.write("{nope\n")
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual(res.health["unparsable"], 1)


if __name__ == "__main__":
    unittest.main()
