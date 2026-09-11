#!/usr/bin/env python3
"""報表 CLI —— 使用者手動跑，吃已累積的正規化事件，不碰原始儲存。

    report.py --since 2026-09-01 --until 2026-09-10
    report.py --since 2026-09-01 --bots rick,morty
    report.py --since 2026-09-01 --format md   -o report.md
    report.py --since 2026-09-01 --format html -o report.html

因為不碰原始儲存，所以可以重跑、可以改指標定義後重算歷史 —— 原始資料可能
已經被 CLI 清掉了（claude-code 有 cleanupPeriodDays，預設 30 天）。
"""
import argparse
import datetime as dt
import json
import os
import sys

import aggregate
from events import read_events

DEFAULT_CONFIG = {"channel_names": {}, "allowlist_bounds": {}, "pricebook": {}}

_TZ_NAME = "Asia/Taipei"


def load_config(path):
    """讀 JSON 設定並疊在預設值上。壞掉的設定檔要拋錯不可靜默用預設值。"""
    config = dict(DEFAULT_CONFIG)
    if not path:
        return config
    with open(path, encoding="utf-8") as fh:
        try:
            loaded = json.load(fh)
        except ValueError as exc:
            raise ValueError("設定檔 %s 解析失敗: %s" % (path, exc))
    config.update(loaded)
    return config


def _days_between(since, until):
    start = dt.date.fromisoformat(since)
    end = dt.date.fromisoformat(until)
    out = []
    while start <= end:
        out.append(start.isoformat())
        start += dt.timedelta(days=1)
    return out


def load_events(events_dir, since, until):
    """讀指定日期範圍的事件檔。unknown 桶一律納入 —— 絕不遺失。"""
    days = _days_between(since, until) + ["unknown"]
    task_paths = [os.path.join(events_dir, "task-%s.jsonl" % d) for d in days]
    usage_paths = [os.path.join(events_dir, "usage-%s.jsonl" % d) for d in days]
    return list(read_events(task_paths)), list(read_events(usage_paths))


def _thread_map_counts(data_dir):
    """收集階段留下的 thread_map 計數（失敗率代理用）。缺檔就是不知道。"""
    path = os.path.join(data_dir, "thread-map-counts.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def build_report(tasks, usages, config, since, until, collect_health,
                 thread_map_counts=None):
    token_rows = []
    for day, bots in sorted(aggregate.daily_tokens(usages).items()):
        for bot, models in sorted(bots.items()):
            for (model_id, variant), tokens in sorted(
                    models.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
                token_rows.append({"day": day, "bot": bot, "model_id": model_id,
                                   "model_variant": variant, "tokens": tokens})

    days_seen = sorted({r["day"] for r in token_rows}
                       | set(aggregate.daily_task_counts(tasks)))
    return {
        "since": since, "until": until, "timezone": _TZ_NAME,
        "coverage": aggregate.data_coverage(days_seen, collect_health),
        "daily_tasks": aggregate.daily_task_counts(tasks),
        "daily_conversations": aggregate.daily_conversations(tasks),
        "token_rows": token_rows,
        "daily_cost": aggregate.daily_cost(usages),
        "active_users": aggregate.active_users(tasks),
        "attribution": aggregate.session_attribution(tasks, usages),
        "friction": aggregate.friction_signals(tasks),
        "failure_proxy": aggregate.failure_proxy(thread_map_counts or {}, tasks),
        "allowlist_bounds": dict(config.get("allowlist_bounds") or {}),
        "channel_names": dict(config.get("channel_names") or {}),
    }


# --- 共同的敘述文字：兩個文字 renderer 與 HTML renderer 都用同一套措辭，
#     避免同一個限制在不同輸出裡講得不一樣。
CAVEATS = (
    "任務數**僅含成功的任務** —— 失敗的 turn 不會在 transcript 裡留下痕跡，"
    "錯誤只丟給聊天平台。",
    "對話數的「有活動」跨日會重複計入（session TTL 24 小時），"
    "所以**逐日加總會大於實際對話數**。",
    "摩擦指標**不是滿意度量測**，兩個訊號都弱，只能看趨勢不能當結論。",
    "「誰在燒量」歸因到 session 層；多人共用的 session 記為 shared 不強行拆分，"
    "覆蓋率請看歸因區塊。",
)


def _caveat_lines(report):
    lines = list(CAVEATS)
    bounds = report.get("allowlist_bounds") or {}
    if bounds:
        listed = "、".join("%s 上界 %d 人" % (bot, n)
                          for bot, n in sorted(bounds.items()))
        lines.append(
            "以下 bot 受 allowlist 限制，活躍人數的上界就是設定值（%s）——"
            "看到 1 不代表沒人想用。" % listed)
    missing = (report.get("coverage") or {}).get("missing_days") or []
    if missing:
        lines.append("**資料缺口**：%s 沒有任何事件，缺口不等於「那天沒人用」。"
                     % "、".join(missing))
    unparsable = (report.get("coverage") or {}).get("unparsable") or 0
    if unparsable:
        lines.append("收集時有 %d 筆紀錄無法解析（可能是 CLI 升版改了格式）。"
                     % unparsable)
    return lines


def render_text(report):
    out = []
    out.append("openab bot 使用統計  %s ~ %s  （時區 %s）"
               % (report["since"], report["until"], report["timezone"]))
    out.append("=" * 64)

    out.append("\n[每日任務數]  真人 / bot 互呼 / cron 排程")
    for day, bots in sorted(report["daily_tasks"].items()):
        for bot, counts in sorted(bots.items()):
            out.append("  %s  %-8s  %4d / %4d / %4d"
                       % (day, bot, counts["human"], counts["bot_relay"],
                          counts["cron"]))

    out.append("\n[每日對話數]  新開 / 延續")
    for day, bots in sorted(report["daily_conversations"].items()):
        for bot, counts in sorted(bots.items()):
            out.append("  %s  %-8s  %4d / %4d"
                       % (day, bot, counts["new"], counts["continued"]))

    out.append("\n[Token 用量]  bot / model (variant)")
    for row in report["token_rows"]:
        kinds = ", ".join("%s=%d" % (k, v) for k, v in sorted(row["tokens"].items()))
        model = row["model_id"] or "(未知)"
        if row["model_variant"]:
            model += " (%s)" % row["model_variant"]
        out.append("  %s  %-8s  %-36s %s" % (row["day"], row["bot"], model, kinds))

    out.append("\n[成本]  依來源分開，不可混加")
    for day, bots in sorted(report["daily_cost"].items()):
        for bot, sources in sorted(bots.items()):
            out.append("  %s  %-8s  CLI 自算 %.4f  價目表 %.4f  "
                       "訂閱制（不計金額）  無成本資料"
                       % (day, bot, sources["cli"], sources["pricebook"]))

    out.append("\n[活躍觸發者]  依 sender_id 聚合，名稱取最近一次")
    for bot, users in sorted(report["active_users"].items()):
        bound = report["allowlist_bounds"].get(bot)
        suffix = ("  ※ 受 allowlist 限制，上界 %d 人" % bound) if bound else ""
        out.append("  %-8s  %d 人%s" % (bot, len(users), suffix))
        for sender_id, info in sorted(users.items(),
                                      key=lambda kv: -kv[1]["tasks"]):
            out.append("      %-24s %4d 個任務"
                       % (info["display_name"] or sender_id, info["tasks"]))

    out.append("\n[Token 歸因]  誰在燒量（session 層，估計值）")
    for bot, info in sorted(report["attribution"].items()):
        out.append("  %-8s  無歧義歸因覆蓋率 %.0f%%" % (bot, info["coverage"] * 100))

    out.append("\n[摩擦指標]  不是滿意度")
    for bot, info in sorted(report["friction"].items()):
        median = info["followup_median_seconds"]
        out.append("  %-8s  追問間隔中位數 %s  每 session 任務數 %s  "
                   "只問一次就沒下文 %d"
                   % (bot,
                      ("%.0f 秒" % median) if median is not None else "n/a",
                      ("%.2f" % info["tasks_per_session"])
                      if info["tasks_per_session"] is not None else "n/a",
                      info["abandoned_sessions"]))

    out.append("\n[開了 session 沒產出]  紅旗指標，不是失敗率")
    for bot, info in sorted(report["failure_proxy"].items()):
        created = info["sessions_created"]
        out.append("  %-8s  建立 %s  產出 %d  落差 %s"
                   % (bot, created if created is not None else "未知",
                      info["sessions_with_output"],
                      info["gap"] if info["gap"] is not None else "未知"))

    out.append("\n[讀這份報表前必須知道]")
    for line in _caveat_lines(report):
        out.append("  - " + line.replace("**", ""))
    return "\n".join(out) + "\n"


def render_md(report):
    out = []
    out.append("# openab bot 使用統計")
    out.append("")
    out.append("- 範圍：%s ~ %s" % (report["since"], report["until"]))
    out.append("- 時區：%s" % report["timezone"])
    out.append("")
    out.append("## 讀這份報表前必須知道")
    out.append("")
    for line in _caveat_lines(report):
        out.append("- " + line)

    out.append("")
    out.append("## 每日任務數")
    out.append("")
    out.append("| 日期 | bot | 真人 | bot 互呼 | cron 排程 |")
    out.append("| --- | --- | --- | --- | --- |")
    for day, bots in sorted(report["daily_tasks"].items()):
        for bot, c in sorted(bots.items()):
            out.append("| %s | %s | %d | %d | %d |"
                       % (day, bot, c["human"], c["bot_relay"], c["cron"]))

    out.append("")
    out.append("## 每日對話數")
    out.append("")
    out.append("| 日期 | bot | 新開 | 延續 |")
    out.append("| --- | --- | --- | --- |")
    for day, bots in sorted(report["daily_conversations"].items()):
        for bot, c in sorted(bots.items()):
            out.append("| %s | %s | %d | %d |" % (day, bot, c["new"], c["continued"]))

    out.append("")
    out.append("## Token 用量")
    out.append("")
    out.append("| 日期 | bot | model | variant | 明細 |")
    out.append("| --- | --- | --- | --- | --- |")
    for row in report["token_rows"]:
        kinds = ", ".join("%s=%d" % (k, v) for k, v in sorted(row["tokens"].items()))
        out.append("| %s | %s | %s | %s | %s |"
                   % (row["day"], row["bot"], row["model_id"] or "(未知)",
                      row["model_variant"] or "—", kinds))

    out.append("")
    out.append("## 成本")
    out.append("")
    out.append("依來源分開列示，**不可混加**：`cli` 是 opencode 自算的實際費用、"
               "`pricebook` 是價目表推算、**訂閱制的 token 數不等於帳單金額**、"
               "`unavailable` 是有 token 但拿不到成本。")
    out.append("")
    out.append("| 日期 | bot | CLI 自算 | 價目表 |")
    out.append("| --- | --- | --- | --- |")
    for day, bots in sorted(report["daily_cost"].items()):
        for bot, s in sorted(bots.items()):
            out.append("| %s | %s | %.4f | %.4f |"
                       % (day, bot, s["cli"], s["pricebook"]))

    out.append("")
    out.append("## 活躍觸發者")
    out.append("")
    out.append("| bot | 人數 | 備註 |")
    out.append("| --- | --- | --- |")
    for bot, users in sorted(report["active_users"].items()):
        bound = report["allowlist_bounds"].get(bot)
        note = ("受 allowlist 限制，上界 %d 人" % bound) if bound else "—"
        out.append("| %s | %d | %s |" % (bot, len(users), note))

    out.append("")
    out.append("## 摩擦指標（不是滿意度）")
    out.append("")
    out.append("| bot | 追問間隔中位數（秒） | 每 session 任務數 | 只問一次就沒下文 |")
    out.append("| --- | --- | --- | --- |")
    for bot, info in sorted(report["friction"].items()):
        median = info["followup_median_seconds"]
        per = info["tasks_per_session"]
        out.append("| %s | %s | %s | %d |"
                   % (bot, ("%.0f" % median) if median is not None else "n/a",
                      ("%.2f" % per) if per is not None else "n/a",
                      info["abandoned_sessions"]))
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="openab 使用統計報表")
    parser.add_argument("--data", required=True,
                        help="collect.py 的輸出目錄（內含 events/）")
    parser.add_argument("--since", required=True, help="起日 YYYY-MM-DD")
    parser.add_argument("--until", required=True, help="迄日 YYYY-MM-DD")
    parser.add_argument("--bots", default="", help="只看這些 bot（逗號分隔）")
    parser.add_argument("--format", default="text",
                        choices=("text", "md", "html"))
    parser.add_argument("--config", default=None, help="config.json 路徑")
    parser.add_argument("-o", "--output", default=None, help="輸出檔，預設 stdout")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.data):
        print("錯誤：%s 不存在" % args.data, file=sys.stderr)
        return 1
    try:
        if dt.date.fromisoformat(args.since) > dt.date.fromisoformat(args.until):
            print("錯誤：--since 晚於 --until", file=sys.stderr)
            return 1
    except ValueError as exc:
        print("錯誤：日期格式不對 —— %s" % exc, file=sys.stderr)
        return 1

    config = load_config(args.config)
    tasks, usages = load_events(os.path.join(args.data, "events"),
                                args.since, args.until)
    wanted = [b.strip() for b in args.bots.split(",") if b.strip()]
    if wanted:
        tasks = [t for t in tasks if t.get("bot") in wanted]
        usages = [u for u in usages if u.get("bot") in wanted]

    health = {}
    health_path = os.path.join(args.data, "collect-health.json")
    if os.path.isfile(health_path):
        with open(health_path, encoding="utf-8") as fh:
            try:
                health = json.load(fh)
            except ValueError:
                health = {}

    report = build_report(tasks, usages, config, args.since, args.until,
                          health, _thread_map_counts(args.data))

    if args.format == "html":
        import render_html
        body = render_html.render(report)
    elif args.format == "md":
        body = render_md(report)
    else:
        body = render_text(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(body)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
