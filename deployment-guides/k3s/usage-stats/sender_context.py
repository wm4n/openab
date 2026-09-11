"""從任意 CLI 紀錄裡抽出 openab 注入的 sender_context，並分類任務來源。

三個 parser 共用這一支 —— sender_context 的格式由 openab 定義
（schema openab.sender.v1，見 crates/openab-core/src/adapter.rs），
跟哪一家 CLI 無關。
"""
import json
import re

# sender_context 是 JSON 字串裡的內容，引號被轉義成 \"，所以不能直接對原始
# 行做字串比對 —— 必須先 json.loads 整筆紀錄，再從文字欄位裡用這個 regex 取。
_SC_RE = re.compile(r"<sender_context>\s*(\{.*?\})\s*</sender_context>", re.S)

# cron.rs:714 的固定值：usercron 觸發的 SenderContext 是
# sender_id: "openab-cron"、is_bot: true、message_id: None。
CRON_SENDER_ID = "openab-cron"


def extract(obj, path=""):
    """遞迴走任意 JSON，回傳 [(json_path, sender_context_dict), ...]。

    path 用 '.' 串接，陣列以 '[]' 表示（例如 message.content[].text），
    這樣不同來源路徑可以被區分 —— 同一筆任務會同時出現在多個路徑。
    解析不了的 sender_context 直接略過（由呼叫端計入 unparsable）。
    """
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = "%s.%s" % (path, key) if path else key
            found.extend(extract(value, child))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(extract(item, path + "[]"))
    elif isinstance(obj, str):
        for match in _SC_RE.finditer(obj):
            try:
                found.append((path, json.loads(match.group(1))))
            except ValueError:
                continue
    return found


def classify_source(sc):
    """"human" | "bot_relay" | "cron"。

    is_bot 只分得出「非真人」；要再分出 bot 互呼與排程觸發，得看
    sender_id 是不是 cron 的哨兵值，或 message_id 是不是空的。
    """
    if not sc.get("is_bot"):
        return "human"
    if sc.get("sender_id") == CRON_SENDER_ID or not sc.get("message_id"):
        return "cron"
    return "bot_relay"


def dedup_key(platform, sc):
    """同一任務在多路徑重複出現時的去重鍵。

    有 message_id（平台訊息 ID）就用它 —— 那是天然唯一鍵。cron 觸發沒有
    message_id，退回 (哨兵, thread, 時間戳)。
    """
    message_id = sc.get("message_id")
    if message_id:
        return "%s:%s" % (platform, message_id)
    return "%s:%s:%s:%s" % (platform, CRON_SENDER_ID,
                            sc.get("thread_id") or sc.get("channel_id") or "?",
                            sc.get("timestamp") or "?")
