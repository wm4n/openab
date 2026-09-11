"""claude-code（Rick／Morty／Genie）的 transcript parser。

資料在 ~/.claude/projects/**/*.jsonl，一行一筆 JSON。

這支的全部難度都在「哪些數字不能加」。實測 message.usage 底下有兩層明細
（cache_creation 是 TTL 拆解、iterations[] 是每次 iteration），欄位名跟外層
一模一樣；另外還混了診斷與 compaction 統計。天真地用鍵名比對撈 token 會
虛報數倍。所以這裡一律用**明確的白名單**取頂層四欄。
"""
import hashlib
import json
import os

import sender_context as sc_mod
from events import TASK_SCHEMA, USAGE_SCHEMA, ParseResult

TRANSCRIPT_GLOB_ROOT = ".claude/projects"

# message.usage 的權威欄位 → 正規化名稱。**只取這四個**。
_USAGE_FIELDS = (
    ("input_tokens", "input"),
    ("output_tokens", "output"),
    ("cache_creation_input_tokens", "cache_write"),
    ("cache_read_input_tokens", "cache_read"),
)

# CLI 內部合成訊息，沒有實際 API 呼叫。
_SYNTHETIC_MODEL = "<synthetic>"

# 前綴指紋的取樣長度：compaction 會重寫檔案，用它判斷能不能沿用 offset。
_PREFIX_BYTES = 4096


def _tokens_from_usage(usage):
    """只取白名單的頂層四欄；子物件（cache_creation／iterations）一律不看。"""
    out = {}
    for raw, name in _USAGE_FIELDS:
        value = usage.get(raw)
        if isinstance(value, int) and not isinstance(value, bool):
            out[name] = value
    return out


def usage_from_record(record):
    """一筆紀錄可能帶兩處獨立用量：主 agent 與 subagent。"""
    rows = []
    message = record.get("message") or {}

    usage = message.get("usage")
    if isinstance(usage, dict):
        model = message.get("model")
        tokens = _tokens_from_usage(usage)
        # model 只信 message.model；<synthetic> 沒有實際 API 呼叫。
        if tokens and model and model != _SYNTHETIC_MODEL:
            rows.append({"origin": "main", "tokens": tokens, "model": model})

    # toolUseResult.usage 是 Task tool 呼叫 subagent 的真實 API 用量。實測
    # isSidechain 全為 false，代表 subagent 自己的訊息不在 transcript 裡，
    # 所以這是唯一來源、必須加。它底下的 iterations[] 仍是明細不可加。
    tool_result = record.get("toolUseResult")
    if isinstance(tool_result, dict) and isinstance(tool_result.get("usage"), dict):
        tokens = _tokens_from_usage(tool_result["usage"])
        if tokens:
            rows.append({"origin": "subagent", "tokens": tokens,
                         "model": message.get("model") or None})
    return rows


def _iter_transcripts(home):
    root = os.path.join(home, TRANSCRIPT_GLOB_ROOT)
    for dirpath, _dirs, names in os.walk(root):
        for name in sorted(names):
            if name.endswith(".jsonl"):
                yield os.path.join(dirpath, name)


def _prefix_fingerprint(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read(_PREFIX_BYTES)).hexdigest()


def parse(home, bot, ctx, watermark):
    """掃這隻 bot 的全部 transcript，回傳 ParseResult。

    watermark 形如 {檔案路徑: {"offset": int, "prefix": str}}。前綴指紋不同
    表示檔案被重寫（compaction），整檔重讀。
    """
    result = ParseResult()
    for path in _iter_transcripts(home):
        mark = watermark.get(path) or {}
        try:
            prefix = _prefix_fingerprint(path)
        except OSError as exc:
            result.health["notes"].append("讀不到 %s: %s" % (path, exc))
            continue
        start = mark.get("offset", 0) if mark.get("prefix") == prefix else 0

        with open(path, encoding="utf-8", errors="replace") as fh:
            fh.seek(start)
            while True:
                offset = fh.tell()
                line = fh.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                result.health["records"] += 1
                try:
                    record = json.loads(stripped)
                except ValueError:
                    result.health["unparsable"] += 1
                    continue
                _emit(result, record, path, offset, bot, ctx)
            result.watermark[path] = {"offset": fh.tell(), "prefix": prefix}
    return result


def _emit(result, record, path, offset, bot, ctx):
    session_id = record.get("sessionId")
    for json_path, sc in sc_mod.extract(record):
        platform = ctx.platform_for(sc.get("thread_id") or sc.get("channel_id") or "")
        result.tasks.append({
            "schema": TASK_SCHEMA, "bot": bot, "cli": "claude-code",
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
            "source_file": path, "source_offset": offset,
            "source_ref": json_path,
        })
    for row in usage_from_record(record):
        result.usages.append({
            "schema": USAGE_SCHEMA, "bot": bot, "cli": "claude-code",
            "session_id": session_id,
            "model_id": row["model"], "model_variant": None,
            "occurred_at": record.get("timestamp"),
            "tokens": row["tokens"],
            # Claude 家族走訂閱制：token 數不等於帳單金額，不可套價目表算錢。
            "cost": None, "cost_source": "subscription",
            "origin": row["origin"],
            # usage_key 讓收集具備幂等性：CronJob 重跑或整檔重讀時，
            # aggregator 用 (bot, usage_key) 去重，不會重複計算。
            "usage_key": "%s#%d#%s" % (path, offset, row["origin"]),
            "source_file": path, "source_offset": offset,
        })
