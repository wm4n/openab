"""sender_context 抽取與分類的測試。

真實資料的關鍵特性：sender_context 是 JSON 字串裡的內容（引號被轉義），
而且同一筆任務會出現在多個路徑。
"""
import json
import unittest

from sender_context import CRON_SENDER_ID, classify_source, dedup_key, extract


def wrap(sc):
    return "<sender_context>\n%s\n</sender_context>" % json.dumps(sc, ensure_ascii=False)


HUMAN = {
    "schema": "openab.sender.v1", "sender_id": "824092654060830770",
    "sender_name": "wm4n", "display_name": "william", "channel": "discord",
    "channel_id": "1528965074562191420", "thread_id": "1540292484611969084",
    "is_bot": False, "timestamp": "2026-09-10T06:32:10Z",
    "message_id": "1600000000000000001", "receiver_id": "1519868630064562278",
}
BOT_RELAY = dict(HUMAN, sender_id="1521431781641818202", sender_name="morty",
                 is_bot=True, message_id="1600000000000000002")
CRON = {
    "schema": "openab.sender.v1", "sender_id": CRON_SENDER_ID,
    "sender_name": "nightly", "display_name": "nightly", "channel": "discord",
    "channel_id": "1528965074562191420", "thread_id": "1540292484611969084",
    "is_bot": True, "timestamp": "2026-09-10T02:00:00Z",
}


class TestExtract(unittest.TestCase):
    def test_finds_sender_context_inside_escaped_json_string(self):
        # 這是真實形狀：sender_context 在 message.content[].text 的字串裡
        record = {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": wrap(HUMAN)},
            {"type": "text", "text": "幫我看 PROJ-1234"}]}}
        found = extract(record)
        self.assertEqual(len(found), 1)
        path, sc = found[0]
        self.assertEqual(path, "message.content[].text")
        self.assertEqual(sc["sender_id"], "824092654060830770")

    def test_finds_all_occurrences_across_different_paths(self):
        # genie 的真實形狀：同一筆同時在 message.content[] 與 attachment.prompt[]
        record = {"message": {"content": [{"type": "text", "text": wrap(HUMAN)}]},
                  "attachment": {"prompt": [{"type": "text", "text": wrap(HUMAN)}]}}
        paths = [p for p, _ in extract(record)]
        self.assertEqual(sorted(paths),
                         ["attachment.prompt[].text", "message.content[].text"])

    def test_counts_multiple_senders_in_one_record_for_batching(self):
        # openab 的 batching：一筆紀錄可能帶多個 sender_context
        record = {"message": {"content": [
            {"type": "text", "text": wrap(HUMAN)},
            {"type": "text", "text": wrap(BOT_RELAY)}]}}
        self.assertEqual(len(extract(record)), 2)

    def test_codex_payload_message_string_path(self):
        record = {"payload": {"message": wrap(HUMAN)}}
        self.assertEqual([p for p, _ in extract(record)], ["payload.message"])

    def test_record_without_sender_context_yields_nothing(self):
        self.assertEqual(extract({"type": "assistant", "message": {"model": "x"}}), [])

    def test_malformed_sender_context_json_is_skipped_not_raised(self):
        record = {"text": "<sender_context>\n{not json}\n</sender_context>"}
        self.assertEqual(extract(record), [])


class TestClassifySource(unittest.TestCase):
    def test_human(self):
        self.assertEqual(classify_source(HUMAN), "human")

    def test_bot_relay_has_message_id(self):
        self.assertEqual(classify_source(BOT_RELAY), "bot_relay")

    def test_cron_identified_by_sender_id_sentinel(self):
        self.assertEqual(classify_source(CRON), "cron")

    def test_bot_without_message_id_is_cron_even_if_sender_id_differs(self):
        # cron.rs:714 是 message_id: None；用兩個條件互為保險
        odd = dict(BOT_RELAY, sender_id="something-else")
        odd.pop("message_id")
        self.assertEqual(classify_source(odd), "cron")


class TestDedupKey(unittest.TestCase):
    def test_uses_platform_and_message_id_when_present(self):
        self.assertEqual(dedup_key("discord", HUMAN),
                         "discord:1600000000000000001")

    def test_same_task_from_two_paths_produces_identical_key(self):
        self.assertEqual(dedup_key("discord", HUMAN), dedup_key("discord", dict(HUMAN)))

    def test_cron_falls_back_to_thread_and_timestamp(self):
        self.assertEqual(
            dedup_key("discord", CRON),
            "discord:openab-cron:1540292484611969084:2026-09-10T02:00:00Z")

    def test_two_cron_runs_in_same_thread_are_distinct(self):
        later = dict(CRON, timestamp="2026-09-10T03:00:00Z")
        self.assertNotEqual(dedup_key("discord", CRON), dedup_key("discord", later))


if __name__ == "__main__":
    unittest.main()
