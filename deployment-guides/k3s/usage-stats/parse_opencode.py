"""opencode（Kimi／Wall-E／Eve）的 SQLite parser。

資料在 ~/.local/share/opencode/opencode.db（WAL 模式），不是 JSONL。注意
.config/opencode 目錄同時存在但裡面只有幾百 bytes 的設定檔 —— 先比對目錄
會誤判成「沒有資料」。

20 張表裡統計相關的四張，而同一筆 token 在四處重複出現：

  session  權威加總 + cost:REAL（opencode 自己算好實際費用）
  message  per-turn，data:TEXT 的 JSON 有 tokens.* 與 modelID
  part     sender_context 在這裡，但 data 也帶 tokens，與 message 層同值
  event    event sourcing log，data.info.tokens 與 data.part.tokens 又各一份

所以 token 只從 message 取、成本只從 session 取，part／event 只用來抓
sender_context。成本與 token 刻意放在不同事件上（session_cost 事件的
tokens 是空 dict），讓重複計算在結構上不可能發生。
"""
import datetime as dt
import json
import os
import shutil
import sqlite3
import tempfile

import sender_context as sc_mod
from events import TASK_SCHEMA, USAGE_SCHEMA, ParseResult

_DB_CANDIDATES = (
    ".local/share/opencode/opencode.db",
    ".local/state/opencode/opencode.db",
)

# message.data.tokens 的權威欄位 → 正規化名稱。total 是加總欄位，排除。
# reasoning 在 opencode 是加法項（與 codex 相反，見計畫的算術證據），
# 所以進互斥的 tokens。
_FLAT_FIELDS = (("input", "input"), ("output", "output"),
                ("reasoning", "reasoning"))
_CACHE_FIELDS = (("read", "cache_read"), ("write", "cache_write"))


def find_db(home):
    for rel in _DB_CANDIDATES:
        path = os.path.join(home, rel)
        if os.path.isfile(path):
            return path
    return None


def parse_model_field(value):
    """session.model 是 JSON 物件、message.data.modelID 是字串，兩種都要吃。

    回傳 (model_id, variant)。variant（實測 walle 有 low／default）可能影響
    計價，所以 model 維度是 (id, variant) 而不只是 id。
    """
    if not value:
        return (None, None)
    text = value.strip() if isinstance(value, str) else value
    if isinstance(text, str) and text.startswith("{"):
        try:
            obj = json.loads(text)
        except ValueError:
            return (text, None)
        return (obj.get("id"), obj.get("variant"))
    return (text, None)


def _iso_from_millis(millis):
    if not isinstance(millis, int) or millis <= 0:
        return None
    return dt.datetime.fromtimestamp(millis / 1000.0,
                                     tz=dt.timezone.utc).isoformat()


def _tokens_from_message_data(data):
    raw = data.get("tokens")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for src, name in _FLAT_FIELDS:
        value = raw.get(src)
        if isinstance(value, int) and not isinstance(value, bool):
            out[name] = value
    cache = raw.get("cache")
    if isinstance(cache, dict):
        for src, name in _CACHE_FIELDS:
            value = cache.get(src)
            if isinstance(value, int) and not isinstance(value, bool):
                out[name] = value
    return out


def _snapshot(db_path, tmpdir):
    """複製 db/-wal/-shm 到暫存目錄再讀複本。

    DB 正被跑著的 pod 寫入。WAL 模式下連唯讀開啟都可能需要建 -shm 檔，
    所以絕不直接開原檔。複本可能有一點不一致，對統計無妨。
    """
    dst = os.path.join(tmpdir, "snapshot.db")
    shutil.copy2(db_path, dst)
    for ext in ("-wal", "-shm"):
        src = db_path + ext
        if os.path.isfile(src):
            shutil.copy2(src, dst + ext)
    return dst


def _tables(cur):
    return {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def parse(home, bot, ctx, watermark):
    result = ParseResult()
    db_path = find_db(home)
    if not db_path:
        result.health["notes"].append("找不到 opencode.db")
        return result

    since = watermark.get("time_updated", 0)
    high_water = since

    with tempfile.TemporaryDirectory() as tmpdir:
        con = sqlite3.connect(_snapshot(db_path, tmpdir))
        con.text_factory = lambda b: b.decode("utf-8", "replace")
        cur = con.cursor()
        have = _tables(cur)

        if "message" in have:
            high_water = max(high_water,
                             _emit_messages(cur, result, bot, db_path, since))
        if "session" in have:
            high_water = max(high_water,
                             _emit_sessions(cur, result, bot, db_path, since))
        for table in ("part", "event"):
            if table in have:
                high_water = max(high_water,
                                 _emit_tasks(cur, result, table, bot, ctx,
                                             db_path, since))
        con.close()

    result.watermark = {"time_updated": high_water}
    return result


def _emit_messages(cur, result, bot, db_path, since):
    """per-message usage：token 與 model，沒有成本。"""
    high = since
    for msg_id, session_id, created, updated, raw in cur.execute(
            "SELECT id, session_id, time_created, time_updated, data FROM message"
            " WHERE COALESCE(time_updated, 0) > ?", (since,)):
        result.health["records"] += 1
        high = max(high, updated or 0)
        if not isinstance(raw, str):
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            result.health["unparsable"] += 1
            continue
        tokens = _tokens_from_message_data(data)
        if not tokens:
            continue
        model_id, variant = parse_model_field(data.get("modelID"))
        result.usages.append({
            "schema": USAGE_SCHEMA, "bot": bot, "cli": "opencode",
            "session_id": session_id,
            "model_id": model_id, "model_variant": variant,
            "occurred_at": _iso_from_millis(created),
            "tokens": tokens,
            # 成本只在 session 層拿得到，所以這裡明確標成 unavailable，
            # 不可退化成 0（那會被讀成「這些 token 不花錢」）。
            "cost": None, "cost_source": "unavailable",
            "origin": "main",
            "usage_key": "message:%s" % msg_id,
            "source_file": db_path, "source_ref": "message:%s" % msg_id,
        })
    return high


def _emit_sessions(cur, result, bot, db_path, since):
    """per-session 成本事件：tokens 刻意留空，與 message 層不重疊。"""
    high = since
    children = 0
    for (session_id, parent_id, created, updated, model, cost) in cur.execute(
            "SELECT id, parent_id, time_created, time_updated, model, cost"
            " FROM session WHERE COALESCE(time_updated, 0) > ?", (since,)):
        high = max(high, updated or 0)
        if parent_id:
            children += 1
        if not isinstance(cost, (int, float)):
            continue
        model_id, variant = parse_model_field(model)
        result.usages.append({
            "schema": USAGE_SCHEMA, "bot": bot, "cli": "opencode",
            "session_id": session_id,
            "model_id": model_id, "model_variant": variant,
            "occurred_at": _iso_from_millis(created),
            # 空 dict：成本事件不帶 token，這樣不管怎麼加總都不會重複計算。
            "tokens": {},
            "cost": float(cost), "cost_source": "cli",
            "origin": "session_cost",
            "usage_key": "session_cost:%s" % session_id,
            "source_file": db_path, "source_ref": "session:%s" % session_id,
            "parent_session_id": parent_id or None,
        })
    if children:
        result.health["notes"].append(
            "session 表有 %d 列帶 parent_id（subagent 子 session），"
            "聚合時不可與 parent 重複計算" % children)
    return high


def _emit_tasks(cur, result, table, bot, ctx, db_path, since):
    """sender_context 在 part.data（持久）與 event.data（event log）。"""
    high = since
    if table == "part":
        rows = cur.execute(
            "SELECT id, session_id, time_updated, data FROM part"
            " WHERE COALESCE(time_updated, 0) > ? AND CAST(data AS TEXT) LIKE ?",
            (since, "%sender_context%"))
    else:
        # event 表沒有時間欄位，只能靠 dedup_key 去重（全表掃）。
        rows = ((r[0], r[1], 0, r[2]) for r in cur.execute(
            "SELECT id, aggregate_id, data FROM event"
            " WHERE CAST(data AS TEXT) LIKE ?", ("%sender_context%",)))

    for row_id, session_id, updated, raw in rows:
        result.health["records"] += 1
        high = max(high, updated or 0)
        if not isinstance(raw, str):
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            result.health["unparsable"] += 1
            continue
        for json_path, sc in sc_mod.extract(data):
            platform = ctx.platform_for(
                sc.get("thread_id") or sc.get("channel_id") or "")
            result.tasks.append({
                "schema": TASK_SCHEMA, "bot": bot, "cli": "opencode",
                "platform": platform,
                "dedup_key": sc_mod.dedup_key(platform, sc),
                "channel_id": sc.get("channel_id"),
                "thread_id": sc.get("thread_id"),
                "session_id": session_id,
                "sender_id": sc.get("sender_id"),
                "sender_name": sc.get("sender_name"),
                "display_name": sc.get("display_name"),
                "source": sc_mod.classify_source(sc),
                "occurred_at": sc.get("timestamp"),
                "source_file": db_path,
                "source_ref": "%s:%s:%s" % (table, row_id, json_path),
            })
    return high
