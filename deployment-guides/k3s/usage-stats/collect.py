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


def count_thread_map(home):
    """thread_map.json 的 entry 數 —— 失敗率代理的分母。

    這個計數必須在收集階段記下來：報表階段只讀事件檔、碰不到 agent 的
    HOME。讀不到時回 None 而不是 0 —— 「不知道」與「沒有落差」必須可區分。
    """
    path = os.path.join(home, ".openab", "thread_map.json")
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None
    inner = raw if isinstance(raw, dict) else {}
    for wrapper in ("persisted", "threads", "mapping"):
        if isinstance(inner.get(wrapper), dict):
            inner = inner[wrapper]
            break
    return len(inner)


# --- 從 archive/mirror 回填已被清掉的歷史資料 -----------------------------
#
# openab-archive.sh（見 K3S.md「transcript 保留期限」）把各 bot 的原始檔案
# rsync 進鏡像，但用重新命名過的子目錄，跟這裡三個 parser 認得的活資料佈局
# 不同名。與其改 parser，這裡用符號連結把鏡像佈局「偽裝」成活資料佈局。
_MIRROR_LAYOUT = (
    (".claude/projects", "claude-projects"),
    (".codex/sessions", "codex-sessions"),
    (".local/share/opencode", "opencode"),
    (".openab", "openab"),
)


def mirror_shim_home(mirror_bot_dir, shim_home):
    """在 shim_home 建符號連結，把鏡像的重新命名子目錄接回活資料佈局。

    shim_home 每次呼叫都要是同一個路徑（同一個 bot 對應同一個 shim_home）——
    claude-code／codex 的 usage_key 內嵌檔案路徑，路徑不穩定的話重跑會被當成
    新資料重複計算。鏡像沒有的子目錄（例如這隻 bot 不是 opencode）就不建連結，
    不製造斷掉的符號連結。
    """
    for live_rel, mirror_name in _MIRROR_LAYOUT:
        src = os.path.join(mirror_bot_dir, mirror_name)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(shim_home, live_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.islink(dst):
            os.symlink(src, dst)
    return shim_home


def _iter_archive_bots(archive_root):
    for entry in sorted(os.listdir(archive_root)):
        if os.path.isdir(os.path.join(archive_root, entry)):
            yield entry


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
    parser.add_argument("--archive-root", default=None,
                        help="openab-archive.sh 鏡像的路徑（回填已被保留期限"
                             "清掉的歷史資料，一次性用，非每日 CronJob 步驟）")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.root):
        print("錯誤：%s 不存在" % args.root, file=sys.stderr)
        return 1
    if args.archive_root and not os.path.isdir(args.archive_root):
        print("錯誤：%s 不存在" % args.archive_root, file=sys.stderr)
        return 1

    wanted = [b.strip() for b in args.bots.split(",") if b.strip()]
    marks_path = os.path.join(args.out, "watermark.json")
    try:
        with open(marks_path, encoding="utf-8") as fh:
            marks = json.load(fh)
    except (OSError, ValueError):
        marks = {}

    health = {"bots": {}, "unrecognised": [], "errors": {}}
    tm_counts = {}
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
        count = count_thread_map(home)
        if count is not None:
            tm_counts[bot] = count
        health["bots"][bot] = {
            "tasks": len(result.tasks), "usages": len(result.usages),
            "records": result.health["records"],
            "unparsable": result.health["unparsable"],
            "notes": result.health["notes"],
        }
        print("%-8s 任務 %4d  用量 %4d  紀錄 %6d  不可解析 %d"
              % (bot, len(result.tasks), len(result.usages),
                 result.health["records"], result.health["unparsable"]))

    if args.archive_root:
        shim_base = os.path.join(args.out, ".mirror-shim")
        for bot in _iter_archive_bots(args.archive_root):
            if wanted and bot not in wanted:
                continue
            mirror_bot_dir = os.path.join(args.archive_root, bot)
            shim_home = mirror_shim_home(mirror_bot_dir,
                                         os.path.join(shim_base, bot))
            watermark_key = "archive:%s" % bot
            if not detect_cli(shim_home):
                # 不可靜默跳過：認不出的鏡像也要出現在健康度報告裡。
                health["unrecognised"].append(watermark_key)
                print("警告：認不出 %s 的鏡像格式，略過" % bot, file=sys.stderr)
                continue
            try:
                result = collect_one(shim_home, bot, args.out,
                                     marks.get(watermark_key, {}))
            except Exception as exc:  # noqa: BLE001
                health["errors"][watermark_key] = (
                    "%s: %s" % (type(exc).__name__, exc))
                print("錯誤：%s 鏡像回填失敗 —— %s" % (bot, exc), file=sys.stderr)
                continue
            marks[watermark_key] = result.watermark
            # 刻意不寫 tm_counts：鏡像的 thread_map 只是舊快照，混進「現在」
            # 的失敗率代理只會誤導，見 test_collect_archive.py 的說明。
            health["bots"][watermark_key] = {
                "tasks": len(result.tasks), "usages": len(result.usages),
                "records": result.health["records"],
                "unparsable": result.health["unparsable"],
                "notes": result.health["notes"],
            }
            print("%-8s(鏡像) 任務 %4d  用量 %4d  紀錄 %6d  不可解析 %d"
                  % (bot, len(result.tasks), len(result.usages),
                     result.health["records"], result.health["unparsable"]))

    os.makedirs(args.out, exist_ok=True)
    with open(marks_path, "w", encoding="utf-8") as fh:
        json.dump(marks, fh, ensure_ascii=False, indent=2, sort_keys=True)
    with open(os.path.join(args.out, "collect-health.json"), "w",
              encoding="utf-8") as fh:
        json.dump(health, fh, ensure_ascii=False, indent=2, sort_keys=True)
    with open(os.path.join(args.out, "thread-map-counts.json"), "w",
              encoding="utf-8") as fh:
        json.dump(tm_counts, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
