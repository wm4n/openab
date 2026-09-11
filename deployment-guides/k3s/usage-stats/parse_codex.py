"""codex-acp（Summer）的 rollout parser。

資料在 ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl。

最大陷阱：payload.info.total_token_usage 是 session **累積值**，每個
token_count event 都重報一次到目前為止的總量。加總所有 event 的
total_token_usage 就是把累積值再累積 —— 實測 summer 這樣算會比正確值大
19.4 倍（418458730 對 21561974）。整個 total_token_usage 子樹都是累積值，
不只 total_tokens 那一欄。

所以權威用量是逐筆 last_token_usage，而 total_token_usage 只用來做交叉
驗證：Σ last_token_usage 應等於每個 session 最後一筆 total_token_usage。
"""
import hashlib
import json
import os

import sender_context as sc_mod
from events import TASK_SCHEMA, USAGE_SCHEMA, ParseResult

_PREFIX_BYTES = 4096


class CumulativeMismatch(Exception):
    """Σ last_token_usage 不等於最後一筆 total_token_usage。

    代表對 codex 的 event 語意理解有誤。寧可中止也不要產出可疑數字 ——
    這種錯誤不會有任何外觀跡象，混進報表就再也抓不出來。
    """


def _int(d, key):
    value = d.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def tokens_from_last_usage(info):
    """last_token_usage → {"tokens": 互斥四欄, "tokens_info": 非互斥項}。

    實測 codex 的 total_tokens = input_tokens + output_tokens，所以
    cached_input_tokens 是 input_tokens 的子集、reasoning_output_tokens 是
    output_tokens 的子集。正規化後的四欄必須互斥可加，因此 input 要扣掉
    cached，而 reasoning 移到 tokens_info（aggregator 算總量時不碰）。
    """
    cached = _int(info, "cached_input_tokens")
    raw_input = _int(info, "input_tokens")
    return {
        "tokens": {
            # 扣到負數只可能是資料異常；夾在 0 以免污染總量。
            "input": max(0, raw_input - cached),
            "output": _int(info, "output_tokens"),
            "cache_read": cached,
            "cache_write": 0,
        },
        "tokens_info": {"reasoning": _int(info, "reasoning_output_tokens")},
    }


def _iter_rollouts(home):
    root = os.path.join(home, ".codex", "sessions")
    for dirpath, _dirs, names in os.walk(root):
        for name in sorted(names):
            if name.endswith(".jsonl"):
                yield os.path.join(dirpath, name)


def _prefix_fingerprint(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read(_PREFIX_BYTES)).hexdigest()


def parse(home, bot, ctx, watermark):
    result = ParseResult()
    for path in _iter_rollouts(home):
        session_id = os.path.splitext(os.path.basename(path))[0]
        mark = watermark.get(path) or {}
        try:
            prefix = _prefix_fingerprint(path)
        except OSError as exc:
            result.health["notes"].append("讀不到 %s: %s" % (path, exc))
            continue
        start = mark.get("offset", 0) if mark.get("prefix") == prefix else 0
        # 交叉驗證只在整檔重讀時做得準（增量時看不到前面的 last_token_usage）。
        checking = start == 0
        last_sum = 0
        final_cumulative = None

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
                last_sum, final_cumulative = _emit(
                    result, record, path, offset, bot, ctx, session_id,
                    last_sum, final_cumulative)
            result.watermark[path] = {"offset": fh.tell(), "prefix": prefix}

        if checking and final_cumulative is not None:
            if last_sum != final_cumulative:
                raise CumulativeMismatch(
                    "%s：Σ last_token_usage=%d 不等於最後一筆 "
                    "total_token_usage=%d，codex event 語意可能已改變"
                    % (path, last_sum, final_cumulative))
            result.health["notes"].append(
                "%s 交叉驗證通過（Σ last = final total = %d）"
                % (os.path.basename(path), last_sum))
    return result


def _emit(result, record, path, offset, bot, ctx, session_id,
          last_sum, final_cumulative):
    payload = record.get("payload") or {}

    for json_path, sc in sc_mod.extract(record):
        platform = ctx.platform_for(sc.get("thread_id") or sc.get("channel_id") or "")
        result.tasks.append({
            "schema": TASK_SCHEMA, "bot": bot, "cli": "codex",
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

    if payload.get("type") != "token_count":
        return last_sum, final_cumulative

    info = payload.get("info") or {}
    last = info.get("last_token_usage")
    if isinstance(last, dict):
        parts = tokens_from_last_usage(last)
        result.usages.append({
            "schema": USAGE_SCHEMA, "bot": bot, "cli": "codex",
            "session_id": session_id,
            # model 只信 payload.model；collaboration_mode.settings.model 是設定值。
            "model_id": payload.get("model"), "model_variant": None,
            "occurred_at": record.get("timestamp"),
            "tokens": parts["tokens"], "tokens_info": parts["tokens_info"],
            "cost": None, "cost_source": "subscription",
            "origin": "main",
            # 見 Task 3：aggregator 用 (bot, usage_key) 去重，讓重跑幂等。
            "usage_key": "%s#%d" % (path, offset),
            "source_file": path, "source_offset": offset,
        })
        last_sum += _int(last, "input_tokens") + _int(last, "output_tokens")

    total = info.get("total_token_usage")
    if isinstance(total, dict):
        final_cumulative = _int(total, "input_tokens") + _int(total, "output_tokens")
    return last_sum, final_cumulative
