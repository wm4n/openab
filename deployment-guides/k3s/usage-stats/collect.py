#!/usr/bin/env python3
"""收集器：把各 agent CLI 的原始儲存轉成正規化事件。CronJob 跑的就是這支。

**只收集，不產報表。** 報表由 report.py 手動產生。分開的理由是原始資料會被
CLI 清掉（claude-code 有 cleanupPeriodDays，預設 30 天），錯過即永久遺失，
所以收集必須定期跑；而報表隨時可以重跑。

唯讀：絕不寫入 agent 的 HOME。
"""
import argparse
import json
import os
import sys

import parse_claude_code
import parse_codex
import parse_opencode
from events import ParseContext, day_key, write_events

_PARSERS = {
    "claude-code": parse_claude_code.parse,
    "codex": parse_codex.parse,
    "opencode": parse_opencode.parse,
}


def detect_cli(home):
    """判斷這個 agent home 用哪個 CLI。

    opencode 必須先判 —— 它的資料在 SQLite，而 .config/opencode 目錄同時
    存在（裡面只有幾百 bytes 的設定檔）。先比對目錄會把三隻 opencode bot
    誤判成「沒有資料」。
    """
    if parse_opencode.find_db(home):
        return "opencode"
    if os.path.isdir(os.path.join(home, ".claude", "projects")):
        return "claude-code"
    if os.path.isdir(os.path.join(home, ".codex")):
        return "codex"
    return None


def _bucket(event):
    """事件按台北日界線分桶。沒有時間戳的進 unknown —— 不可丟掉。"""
    ts = event.get("occurred_at")
    if not ts:
        return "unknown"
    try:
        return day_key(ts)
    except (ValueError, TypeError):
        return "unknown"


def _write_by_day(out_dir, prefix, items):
    buckets = {}
    for item in items:
        buckets.setdefault(_bucket(item), []).append(item)
    events_dir = os.path.join(out_dir, "events")
    for day, rows in sorted(buckets.items()):
        write_events(os.path.join(events_dir, "%s-%s.jsonl" % (prefix, day)), rows)


def collect_one(home, bot, out_dir, watermark):
    """跑一隻 bot，寫出事件，回傳 ParseResult（含新水位）。"""
    cli = detect_cli(home)
    if not cli:
        raise ValueError("認不出 %s 的 CLI" % bot)
    result = _PARSERS[cli](home, bot, ParseContext.from_agent_home(home),
                           watermark or {})
    _write_by_day(out_dir, "task", result.tasks)
    _write_by_day(out_dir, "usage", result.usages)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="openab 使用統計收集器")
    parser.add_argument("--root", default="/data/william/openab",
                        help="agent-* 目錄的父路徑")
    parser.add_argument("--out", required=True, help="事件與水位的輸出目錄")
    parser.add_argument("--bots", default="",
                        help="只處理這些 bot（逗號分隔），預設全部")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.root):
        print("錯誤：%s 不存在" % args.root, file=sys.stderr)
        return 1

    wanted = [b.strip() for b in args.bots.split(",") if b.strip()]
    marks_path = os.path.join(args.out, "watermark.json")
    try:
        with open(marks_path, encoding="utf-8") as fh:
            marks = json.load(fh)
    except (OSError, ValueError):
        marks = {}

    health = {"bots": {}, "unrecognised": [], "errors": {}}
    for entry in sorted(os.listdir(args.root)):
        if not entry.startswith("agent-"):
            continue
        bot = entry[len("agent-"):]
        if wanted and bot not in wanted:
            continue
        home = os.path.join(args.root, entry)
        if not detect_cli(home):
            # 不可靜默跳過：認不出的 bot 要出現在健康度報告裡。
            health["unrecognised"].append(bot)
            print("警告：認不出 %s 的 CLI，略過" % bot, file=sys.stderr)
            continue
        try:
            result = collect_one(home, bot, args.out, marks.get(bot, {}))
        except Exception as exc:  # noqa: BLE001 —— 一隻壞掉不該讓其他隻收不到
            health["errors"][bot] = "%s: %s" % (type(exc).__name__, exc)
            print("錯誤：%s 收集失敗 —— %s" % (bot, exc), file=sys.stderr)
            continue
        marks[bot] = result.watermark
        health["bots"][bot] = {
            "tasks": len(result.tasks), "usages": len(result.usages),
            "records": result.health["records"],
            "unparsable": result.health["unparsable"],
            "notes": result.health["notes"],
        }
        print("%-8s 任務 %4d  用量 %4d  紀錄 %6d  不可解析 %d"
              % (bot, len(result.tasks), len(result.usages),
                 result.health["records"], result.health["unparsable"]))

    os.makedirs(args.out, exist_ok=True)
    with open(marks_path, "w", encoding="utf-8") as fh:
        json.dump(marks, fh, ensure_ascii=False, indent=2, sort_keys=True)
    with open(os.path.join(args.out, "collect-health.json"), "w",
              encoding="utf-8") as fh:
        json.dump(health, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
