"""opencode parser 的測試。

opencode 用 SQLite（不是 JSONL），而且同一筆 token 在 session／message／
part／event 四張表重複出現。這些測試的重點是「只從該取的那一層取」。
"""
import json
import os
import sqlite3
import tempfile
import unittest

from events import ParseContext
from parse_opencode import find_db, parse, parse_model_field

SENDER = {
    "schema": "openab.sender.v1", "sender_id": "824092654060830770",
    "sender_name": "wm4n", "display_name": "william", "channel": "discord",
    "channel_id": "c1", "thread_id": "t1", "is_bot": False,
    "timestamp": "2026-09-10T06:32:10Z", "message_id": "m1",
}
SC = "<sender_context>\n%s\n</sender_context>" % json.dumps(SENDER, ensure_ascii=False)

# 實測 kimi 的 message.data.tokens 形狀
TOKENS = {"input": 1530149, "output": 60999, "reasoning": 32445,
          "total": 10049081, "cache": {"read": 8425568, "write": 0}}
T_CREATED = 1789011069045   # epoch millis ≈ 2026-09-09


def build_db(path, sessions=None, messages=None, parts=None, events=None):
    """照實測 schema 建表（只建統計相關的四張）。"""
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("""CREATE TABLE session (id TEXT, project_id TEXT, parent_id TEXT,
      slug TEXT, directory TEXT, title TEXT, version TEXT, share_url TEXT,
      time_created INTEGER, time_updated INTEGER, workspace_id TEXT, path TEXT,
      agent TEXT, model TEXT, cost REAL, tokens_input INTEGER,
      tokens_output INTEGER, tokens_reasoning INTEGER, tokens_cache_read INTEGER,
      tokens_cache_write INTEGER, metadata TEXT)""")
    cur.execute("""CREATE TABLE message (id TEXT, session_id TEXT,
      time_created INTEGER, time_updated INTEGER, data TEXT)""")
    cur.execute("""CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT,
      time_created INTEGER, time_updated INTEGER, data TEXT)""")
    cur.execute("""CREATE TABLE event (id TEXT, aggregate_id TEXT, seq INTEGER,
      type TEXT, data TEXT)""")
    for row in sessions or []:
        cur.execute("INSERT INTO session (id, parent_id, time_created, time_updated,"
                    " model, cost, tokens_input, tokens_output, tokens_reasoning,"
                    " tokens_cache_read, tokens_cache_write)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
    for row in messages or []:
        cur.execute("INSERT INTO message VALUES (?,?,?,?,?)", row)
    for row in parts or []:
        cur.execute("INSERT INTO part VALUES (?,?,?,?,?,?)", row)
    for row in events or []:
        cur.execute("INSERT INTO event VALUES (?,?,?,?,?)", row)
    con.commit()
    con.close()


def make_home(tmp, **kw):
    d = os.path.join(tmp, ".local", "share", "opencode")
    os.makedirs(d)
    # 真實環境同時存在 .config/opencode（只有設定檔）—— 不可誤判成資料來源
    os.makedirs(os.path.join(tmp, ".config", "opencode"))
    with open(os.path.join(tmp, ".config", "opencode", "opencode.jsonc"), "w") as fh:
        fh.write('{"model":"x"}')
    build_db(os.path.join(d, "opencode.db"), **kw)
    os.makedirs(os.path.join(tmp, ".openab"))
    with open(os.path.join(tmp, ".openab", "thread_map.json"), "w") as fh:
        json.dump({"persisted": {"discord:t1": "ses_1"}}, fh)
    return tmp


class TestFindDb(unittest.TestCase):
    def test_finds_db_under_local_share(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp)
            self.assertTrue(find_db(home).endswith(".local/share/opencode/opencode.db"))

    def test_config_only_home_is_not_mistaken_for_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".config", "opencode"))
            self.assertIsNone(find_db(tmp))


class TestParseModelField(unittest.TestCase):
    def test_plain_string(self):
        self.assertEqual(parse_model_field("moonshotai/kimi-k3"),
                         ("moonshotai/kimi-k3", None))

    def test_json_object_with_variant(self):
        raw = ('{"id":"deepseek/deepseek-v4-pro-0813",'
               '"providerID":"openrouter","variant":"low"}')
        self.assertEqual(parse_model_field(raw),
                         ("deepseek/deepseek-v4-pro-0813", "low"))

    def test_json_object_without_variant(self):
        raw = '{"id":"z-ai/glm-5.2","providerID":"openrouter"}'
        self.assertEqual(parse_model_field(raw), ("z-ai/glm-5.2", None))

    def test_none_and_empty(self):
        self.assertEqual(parse_model_field(None), (None, None))
        self.assertEqual(parse_model_field(""), (None, None))


class TestParse(unittest.TestCase):
    def _ctx(self, home):
        return ParseContext.from_agent_home(home)

    def test_tokens_come_from_message_layer_with_reasoning_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"id": "msg_a", "role": "assistant",
                            "modelID": "moonshotai/kimi-k3", "tokens": TOKENS}))])
            res = parse(home, "kimi", self._ctx(home), {})
            main = [u for u in res.usages if u["origin"] == "main"]
            self.assertEqual(len(main), 1)
            self.assertEqual(main[0]["tokens"], {
                "input": 1530149, "output": 60999, "reasoning": 32445,
                "cache_read": 8425568, "cache_write": 0})

    def test_message_tokens_total_is_excluded_as_aggregate_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"modelID": "m", "tokens": TOKENS}))])
            res = parse(home, "kimi", self._ctx(home), {})
            main = [u for u in res.usages if u["origin"] == "main"][0]
            self.assertNotIn("total", main["tokens"])

    def test_never_sums_tokens_from_part_or_event_tables(self):
        # part 與 event 都帶跟 message 同值的 tokens —— 必須完全不看
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(
                tmp,
                messages=[("msg_a", "ses_1", T_CREATED, T_CREATED,
                           json.dumps({"modelID": "m", "tokens": TOKENS}))],
                parts=[("prt_1", "msg_a", "ses_1", T_CREATED, T_CREATED,
                        json.dumps({"type": "step-finish", "tokens": TOKENS}))],
                events=[("ev_1", "ses_1", 1, "message.part.updated",
                         json.dumps({"info": {"tokens": TOKENS},
                                     "part": {"tokens": TOKENS}}))])
            res = parse(home, "kimi", self._ctx(home), {})
            main = [u for u in res.usages if u["origin"] == "main"]
            self.assertEqual(len(main), 1)
            self.assertEqual(main[0]["tokens"]["input"], 1530149)

    def test_session_cost_event_carries_cost_but_no_tokens(self):
        # token 空間不重疊 —— 這是結構上防止重複計算的機制
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, sessions=[(
                "ses_1", None, T_CREATED, T_CREATED,
                '{"id":"moonshotai/kimi-k3","providerID":"openrouter"}',
                3.1967, 1530149, 60999, 32445, 8425568, 0)])
            res = parse(home, "kimi", self._ctx(home), {})
            cost_events = [u for u in res.usages if u["origin"] == "session_cost"]
            self.assertEqual(len(cost_events), 1)
            self.assertEqual(cost_events[0]["tokens"], {})
            self.assertAlmostEqual(cost_events[0]["cost"], 3.1967)
            self.assertEqual(cost_events[0]["cost_source"], "cli")
            self.assertEqual(cost_events[0]["model_id"], "moonshotai/kimi-k3")

    def test_message_usage_has_no_cost_and_says_so_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"modelID": "m", "tokens": TOKENS}))])
            res = parse(home, "kimi", self._ctx(home), {})
            main = [u for u in res.usages if u["origin"] == "main"][0]
            self.assertIsNone(main["cost"])
            self.assertEqual(main["cost_source"], "unavailable")

    def test_sender_context_read_from_part_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, parts=[(
                "prt_1", "msg_u", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"id": "prt_1", "type": "text", "text": SC}))])
            res = parse(home, "kimi", self._ctx(home), {})
            self.assertEqual(len(res.tasks), 1)
            self.assertEqual(res.tasks[0]["dedup_key"], "discord:m1")
            self.assertEqual(res.tasks[0]["cli"], "opencode")
            self.assertEqual(res.tasks[0]["session_id"], "ses_1")

    def test_same_task_in_part_and_event_shares_one_dedup_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(
                tmp,
                parts=[("prt_1", "msg_u", "ses_1", T_CREATED, T_CREATED,
                        json.dumps({"text": SC}))],
                events=[("ev_1", "ses_1", 1, "x", json.dumps({"part": {"text": SC}}))])
            res = parse(home, "kimi", self._ctx(home), {})
            self.assertEqual(len(res.tasks), 2)
            self.assertEqual({t["dedup_key"] for t in res.tasks}, {"discord:m1"})

    def test_subagent_child_session_is_flagged_in_health_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, sessions=[
                ("ses_1", None, T_CREATED, T_CREATED, "m", 1.0, 1, 1, 0, 0, 0),
                ("ses_2", "ses_1", T_CREATED, T_CREATED, "m", 0.5, 1, 1, 0, 0, 0)])
            res = parse(home, "kimi", self._ctx(home), {})
            self.assertTrue(any("parent_id" in n for n in res.health["notes"]))

    def test_usage_key_is_stable_so_rerun_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"modelID": "m", "tokens": TOKENS}))])
            ctx = self._ctx(home)
            first = parse(home, "kimi", ctx, {})
            second = parse(home, "kimi", ctx, {})
            self.assertEqual([u["usage_key"] for u in first.usages],
                             [u["usage_key"] for u in second.usages])
            self.assertEqual(first.usages[0]["usage_key"], "message:msg_a")

    def test_original_db_file_is_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"modelID": "m", "tokens": TOKENS}))])
            db = find_db(home)
            before = (os.path.getmtime(db), os.path.getsize(db))
            parse(home, "kimi", self._ctx(home), {})
            self.assertEqual((os.path.getmtime(db), os.path.getsize(db)), before)

    def test_occurred_at_converts_epoch_millis_to_iso(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"modelID": "m", "tokens": TOKENS}))])
            res = parse(home, "kimi", self._ctx(home), {})
            main = [u for u in res.usages if u["origin"] == "main"][0]
            self.assertTrue(main["occurred_at"].startswith("2026-09-"))
            self.assertTrue(main["occurred_at"].endswith("+00:00"))


if __name__ == "__main__":
    unittest.main()
