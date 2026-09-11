"""claude-code parser 的測試。

重點全部是「哪些數字不能加」—— 真實 message.usage 底下有兩層明細，
欄位名跟外層一模一樣，天真加總會虛報數倍。
"""
import json
import os
import tempfile
import unittest

from events import ParseContext
from parse_claude_code import parse, usage_from_record


def assistant_record(**usage_overrides):
    """重現實測 genie 的 message.usage 結構：外層 + 兩層明細 + 非計費欄位。"""
    usage = {
        "input_tokens": 100,
        "output_tokens": 200,
        "cache_creation_input_tokens": 300,
        "cache_read_input_tokens": 400,
        # 明細一：TTL 拆解，數值等於外層 cache_creation_input_tokens
        "cache_creation": {"ephemeral_1h_input_tokens": 300,
                           "ephemeral_5m_input_tokens": 0},
        # 明細二：每次 iteration，欄位名與外層相同
        "iterations": [{"input_tokens": 99, "output_tokens": 199,
                        "cache_creation_input_tokens": 299,
                        "cache_read_input_tokens": 399}],
        # 非 token：請求次數
        "server_tool_use": {"web_fetch_requests": 0, "web_search_requests": 0},
    }
    usage.update(usage_overrides)
    return {
        "type": "assistant", "sessionId": "s1", "isSidechain": False,
        "timestamp": "2026-09-10T06:33:01Z",
        "message": {"model": "claude-opus-5", "role": "assistant", "usage": usage},
    }


class TestUsageFromRecord(unittest.TestCase):
    def test_takes_only_top_level_four_fields(self):
        rows = usage_from_record(assistant_record())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tokens"], {
            "input": 100, "output": 200, "cache_write": 300, "cache_read": 400})

    def test_ignores_cache_creation_ttl_breakdown(self):
        # 300 只能出現一次；若明細被加進去會變 600
        rows = usage_from_record(assistant_record())
        self.assertEqual(rows[0]["tokens"]["cache_write"], 300)

    def test_ignores_iterations_breakdown(self):
        rows = usage_from_record(assistant_record())
        self.assertEqual(rows[0]["tokens"]["input"], 100)  # 不是 100+99

    def test_ignores_server_tool_use_request_counts(self):
        rows = usage_from_record(assistant_record())
        self.assertNotIn("web_fetch_requests", rows[0]["tokens"])

    def test_ignores_diagnostics_and_compaction_non_billing_fields(self):
        rec = assistant_record()
        rec["message"]["diagnostics"] = {
            "cache_miss_reason": {"cache_missed_input_tokens": 3633171}}
        rec["compactMetadata"] = {"preTokens": 1000899, "postTokens": 7794,
                                  "cumulativeDroppedTokens": 993105}
        rows = usage_from_record(rec)
        self.assertEqual(sum(rows[0]["tokens"].values()), 1000)

    def test_includes_tool_use_result_usage_as_subagent_origin(self):
        rec = {
            "type": "user", "sessionId": "s1",
            "timestamp": "2026-09-10T06:40:00Z",
            "toolUseResult": {
                "totalTokens": 3676107,   # 加總欄位，不可用
                "usage": {"input_tokens": 52, "output_tokens": 154585,
                          "cache_creation_input_tokens": 74929,
                          "cache_read_input_tokens": 3446541,
                          "iterations": [{"input_tokens": 52}]},
            },
        }
        rows = usage_from_record(rec)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["origin"], "subagent")
        self.assertEqual(rows[0]["tokens"]["output"], 154585)
        self.assertEqual(rows[0]["tokens"]["input"], 52)  # 不是 52+52

    def test_does_not_use_tool_use_result_total_tokens(self):
        rec = {"toolUseResult": {"totalTokens": 999999}}
        self.assertEqual(usage_from_record(rec), [])

    def test_synthetic_model_is_dropped(self):
        rec = assistant_record()
        rec["message"]["model"] = "<synthetic>"
        self.assertEqual(usage_from_record(rec), [])

    def test_task_tool_input_model_is_not_treated_as_model(self):
        # message.content[].input.model 是傳給 subagent 的參數，值如 "opus"
        rec = {"type": "assistant", "sessionId": "s1",
               "timestamp": "2026-09-10T06:33:01Z",
               "message": {"content": [{"type": "tool_use",
                                        "input": {"model": "opus"}}]}}
        self.assertEqual(usage_from_record(rec), [])

    def test_record_without_usage_yields_nothing(self):
        self.assertEqual(usage_from_record({"type": "system"}), [])


class TestParse(unittest.TestCase):
    def _home(self, tmp, records, thread_map=None):
        d = os.path.join(tmp, ".claude", "projects", "-home-node")
        os.makedirs(d)
        with open(os.path.join(d, "s1.jsonl"), "w") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.makedirs(os.path.join(tmp, ".openab"))
        with open(os.path.join(tmp, ".openab", "thread_map.json"), "w") as fh:
            json.dump({"persisted": thread_map or {"discord:t1": "s1"}}, fh)
        return tmp

    def test_emits_task_and_usage_events(self):
        sc = ('<sender_context>\n{"schema":"openab.sender.v1","sender_id":"824",'
              '"sender_name":"wm4n","display_name":"william","channel":"discord",'
              '"channel_id":"c1","thread_id":"t1","is_bot":false,'
              '"timestamp":"2026-09-10T06:32:10Z","message_id":"m1"}\n'
              '</sender_context>')
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, [
                {"type": "user", "sessionId": "s1",
                 "message": {"role": "user",
                             "content": [{"type": "text", "text": sc}]}},
                assistant_record(),
            ])
            res = parse(home, "rick", ParseContext.from_agent_home(home), {})
            self.assertEqual(len(res.tasks), 1)
            self.assertEqual(res.tasks[0]["platform"], "discord")
            self.assertEqual(res.tasks[0]["source"], "human")
            self.assertEqual(res.tasks[0]["dedup_key"], "discord:m1")
            self.assertEqual(res.tasks[0]["sender_name"], "wm4n")
            self.assertEqual(res.tasks[0]["display_name"], "william")
            self.assertEqual(len(res.usages), 1)
            self.assertEqual(res.usages[0]["model_id"], "claude-opus-5")
            self.assertIsNone(res.usages[0]["model_variant"])
            self.assertEqual(res.usages[0]["cost_source"], "subscription")
            # 幂等性：同一筆用量的 usage_key 必須穩定
            self.assertTrue(res.usages[0]["usage_key"].endswith("#main"))
            self.assertEqual(res.health["unparsable"], 0)

    def test_unparsable_line_is_counted_not_skipped_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, [])
            path = os.path.join(home, ".claude", "projects", "-home-node", "s1.jsonl")
            with open(path, "w") as fh:
                fh.write("{broken\n")
            res = parse(home, "rick", ParseContext.from_agent_home(home), {})
            self.assertEqual(res.health["unparsable"], 1)

    def test_watermark_lets_second_run_skip_already_read_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, [assistant_record()])
            ctx = ParseContext.from_agent_home(home)
            first = parse(home, "rick", ctx, {})
            self.assertEqual(len(first.usages), 1)
            second = parse(home, "rick", ctx, first.watermark)
            self.assertEqual(len(second.usages), 0)

    def test_rewritten_file_is_reread_from_scratch(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, [assistant_record()])
            ctx = ParseContext.from_agent_home(home)
            first = parse(home, "rick", ctx, {})
            # compaction 重寫檔案：內容變短、前綴不同
            path = os.path.join(home, ".claude", "projects", "-home-node", "s1.jsonl")
            with open(path, "w") as fh:
                fh.write(json.dumps(assistant_record(input_tokens=7)) + "\n")
            second = parse(home, "rick", ctx, first.watermark)
            self.assertEqual(len(second.usages), 1)


if __name__ == "__main__":
    unittest.main()
