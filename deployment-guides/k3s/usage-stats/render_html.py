"""把報表資料模型算成自帶資源的單一 HTML。

**硬性限制：零外部請求。** 不連 CDN、不載外部字型、沒有 fetch 或 <script>。
`open report.html` 必須完全正常，也才能直接寄給人或發佈成網頁。

圖表是**程式產生的 inline SVG**，不用 JS 圖表庫：自帶資源的前提下 inline
一個庫動輒數百 KB，而這裡要的三種圖形產生 SVG 的程式碼更短，而且幾何是純
函數、可以斷言座標 —— JS 庫渲染的結果測不到。

互動層用 SVG 原生 <title>（瀏覽器內建 tooltip），所以零 JavaScript。

配色順序固定（categorical，不循環），已用 dataviz 的 validate_palette.js
在兩個 mode 驗過：light 最差相鄰 CVD ΔE 9.2／normal 27.6，dark 9.4／26.5。
light mode 的 aqua 對比 2.74 < 3:1 拿到 WARN，規則要求以「可見標籤或表格
檢視」補償 —— 所以**每張圖都附一份表格**，那是硬需求不是裝飾。
"""
import html as html_mod

# 前三個 categorical slot（blue／orange／aqua）。深色是各自選過的色階，
# 不是自動反轉。
SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a")
SERIES_DARK = ("#3987e5", "#d95926", "#199e70")

_PLOT_W = 640
_PLOT_H = 180
_PAD_L = 8
_PAD_B = 22
_GAP = 2          # 堆疊段之間的底色間隙
_RADIUS = 4       # 最上層段的頂端圓角
# 柱寬上限：日期數很少時（例如只查兩天）按比例算會得到接近 200px 的巨大
# 柱子，視覺上很怪。dataviz 程序第 7 步「render 出來看」抓到的。
_BAR_MAX = 48


def _esc(value):
    return html_mod.escape(str(value), quote=True)


def rounded_top_path(x, y, w, h, r):
    """頂端圓角、底端方角的 path d。用於堆疊的最上層段。"""
    r = max(0, min(r, w / 2.0, h / 2.0))
    return ("M %g,%g L %g,%g Q %g,%g %g,%g L %g,%g Q %g,%g %g,%g L %g,%g Z"
            % (x, y + h,              # 起點：左下角
               x, y + r,              # 左邊往上到圓角起點
               x, y, x + r, y,        # 左上圓角
               x + w - r, y,          # 頂邊
               x + w, y, x + w, y + r,  # 右上圓角
               x + w, y + h))         # 右邊往下回基線


def stack_geometry(days, series, width=_PLOT_W, height=_PLOT_H):
    """堆疊柱狀的幾何。回傳每一段的座標，y 越小越上面。

    值為 0 的段完全不畫（畫一條 0 高的色塊只會製造視覺雜訊），整日為 0
    也不會除以零。
    """
    if not days:
        return []
    totals = {d: sum((series[k].get(d) or 0) for k in series) for d in days}
    peak = max(totals.values()) if totals else 0
    if peak <= 0:
        return []

    plot_h = height - _PAD_B
    slot = (width - _PAD_L) / float(len(days))
    bar_w = min(_BAR_MAX, max(4.0, slot * 0.62))
    keys = list(series)

    out = []
    for index, day in enumerate(days):
        x = _PAD_L + index * slot + (slot - bar_w) / 2.0
        cursor = plot_h
        drawn = []
        for key in keys:
            value = series[key].get(day) or 0
            if value <= 0:
                continue
            h = (value / float(peak)) * (plot_h - _GAP * max(0, len(keys) - 1))
            cursor -= h
            drawn.append({"day": day, "key": key, "value": value,
                          "x": x, "y": cursor, "w": bar_w, "h": h,
                          "top": False})
            cursor -= _GAP
        if drawn:
            drawn[-1]["top"] = True
        out.extend(drawn)
    return out


def hbar_geometry(rows, width=_PLOT_W, height=_PLOT_H):
    """橫條的幾何。rows 是 [(label, value), ...]。類別名稱長時用這個形式。"""
    if not rows:
        return []
    peak = max((v for _l, v in rows), default=0)
    row_h = 22
    out = []
    for index, (label, value) in enumerate(rows):
        w = ((value / float(peak)) * (width - _PAD_L)) if peak > 0 else 0
        out.append({"label": label, "value": value, "x": _PAD_L,
                    "y": index * row_h, "w": w, "h": row_h - 6})
    return out


def _series_var(index):
    return "var(--series-%d)" % (index + 1)


def svg_stacked(days, series, labels, title):
    """堆疊柱狀。≥2 series 一定有圖例（識別絕不只靠顏色）。"""
    geo = stack_geometry(days, series)
    keys = list(series)
    colour_of = {k: _series_var(i) for i, k in enumerate(keys)}

    marks = []
    for seg in geo:
        tip = "%s ／ %s：%s" % (seg["day"], labels.get(seg["key"], seg["key"]),
                                seg["value"])
        shape = ('<path d="%s"' % rounded_top_path(
            seg["x"], seg["y"], seg["w"], seg["h"], _RADIUS)) if seg["top"] else (
            '<rect x="%g" y="%g" width="%g" height="%g"'
            % (seg["x"], seg["y"], seg["w"], seg["h"]))
        marks.append('%s fill="%s"><title>%s</title>%s'
                     % (shape, colour_of[seg["key"]], _esc(tip),
                        "</path>" if seg["top"] else "</rect>"))

    ticks = []
    slot = (_PLOT_W - _PAD_L) / float(len(days)) if days else 0
    for index, day in enumerate(days):
        ticks.append('<text class="tick" x="%g" y="%g" text-anchor="middle">%s</text>'
                     % (_PAD_L + index * slot + slot / 2.0, _PLOT_H - 6,
                        _esc(day[5:])))

    legend = ""
    if len(keys) >= 2:
        items = "".join(
            '<span class="key"><i style="background:%s"></i>%s</span>'
            % (colour_of[k], _esc(labels.get(k, k))) for k in keys)
        legend = '<div class="legend">%s</div>' % items

    return ('<figure><figcaption>%s</figcaption>%s'
            '<svg viewBox="0 0 %d %d" role="img" aria-label="%s">%s%s</svg>'
            '</figure>' % (_esc(title), legend, _PLOT_W, _PLOT_H,
                           _esc(title), "".join(marks), "".join(ticks)))


def svg_hbars(rows, title):
    """橫條。單一 series 不需要圖例 —— 標題已經說明它是什麼。"""
    geo = hbar_geometry(rows)
    height = max(_PLOT_H, len(geo) * 22)
    marks = []
    for bar in geo:
        marks.append(
            '<rect x="%g" y="%g" width="%g" height="%g" rx="%d" fill="%s">'
            '<title>%s：%s</title></rect>'
            % (bar["x"], bar["y"], bar["w"], bar["h"], _RADIUS,
               _series_var(0), _esc(bar["label"]), _esc(bar["value"])))
        marks.append('<text class="tick" x="%g" y="%g">%s</text>'
                     % (bar["x"] + 6, bar["y"] + bar["h"] - 5,
                        _esc(bar["label"])))
    return ('<figure><figcaption>%s</figcaption>'
            '<svg viewBox="0 0 %d %d" role="img" aria-label="%s">%s</svg>'
            '</figure>' % (_esc(title), _PLOT_W, height, _esc(title),
                           "".join(marks)))


def _table(headers, rows):
    head = "".join("<th>%s</th>" % _esc(h) for h in headers)
    body = "".join(
        "<tr>%s</tr>" % "".join("<td>%s</td>" % _esc(c) for c in row)
        for row in rows)
    return ('<div class="scroll"><table><thead><tr>%s</tr></thead>'
            "<tbody>%s</tbody></table></div>" % (head, body))


_CSS = """
:root {
  --surface: #fcfcfb; --panel: #ffffff; --ink: #1a1a19; --ink-2: #55534f;
  --ink-3: #86837d; --rule: #e6e4e0;
  --series-1: %s; --series-2: %s; --series-3: %s;
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface: #1a1a19; --panel: #232320; --ink: #f2f0ec; --ink-2: #b3afa8;
    --ink-3: #86837d; --rule: #33322e;
    --series-1: %s; --series-2: %s; --series-3: %s;
  }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 32px 20px; background: var(--surface);
       color: var(--ink); max-width: 900px; margin-inline: auto;
       font: 15px/1.65 ui-sans-serif, system-ui, "Helvetica Neue", sans-serif; }
h1 { font-size: 1.5rem; margin: 0 0 4px; }
h2 { font-size: 1.05rem; margin: 32px 0 10px; padding-top: 14px;
     border-top: 1px solid var(--rule); }
.meta { color: var(--ink-2); font-size: .9rem; margin: 0 0 20px; }
.caveats { background: var(--panel); border: 1px solid var(--rule);
           border-radius: 10px; padding: 14px 18px; margin: 0 0 8px; }
.caveats li { color: var(--ink-2); margin: 5px 0; }
figure { margin: 0 0 14px; }
figcaption { font-size: .85rem; color: var(--ink-2); margin-bottom: 6px; }
svg { width: 100%%; height: auto; display: block; }
.tick { font-size: 10px; fill: var(--ink-3); }
.legend { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 8px;
          font-size: .82rem; color: var(--ink-2); }
.key { display: inline-flex; align-items: center; gap: 6px; }
.key i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%%; font-size: .86rem; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--rule);
         white-space: nowrap; }
th { color: var(--ink-3); font-weight: 600; }
td { color: var(--ink); }
"""


def render(report):
    """完整 HTML。文字色一律用 ink token，不用 series 色。"""
    import report as report_mod   # 共用同一套限制措辭，避免兩邊講得不一樣

    days = sorted(set(report["daily_tasks"]) | set(report["daily_conversations"]))
    days = [d for d in days if d != "unknown"]

    task_series = {
        "human": {}, "bot_relay": {}, "cron": {},
    }
    for day, bots in report["daily_tasks"].items():
        for counts in bots.values():
            for key in task_series:
                task_series[key][day] = task_series[key].get(day, 0) + counts[key]

    conv_series = {"new": {}, "continued": {}}
    for day, bots in report["daily_conversations"].items():
        for counts in bots.values():
            for key in conv_series:
                conv_series[key][day] = conv_series[key].get(day, 0) + counts[key]

    model_totals = {}
    for row in report["token_rows"]:
        label = row["model_id"] or "(未知)"
        if row["model_variant"]:
            label += " (%s)" % row["model_variant"]
        model_totals[label] = model_totals.get(label, 0) + sum(row["tokens"].values())
    model_rows = sorted(model_totals.items(), key=lambda kv: -kv[1])

    parts = []
    parts.append("<title>openab bot 使用統計</title>")
    parts.append("<style>%s</style>" % (_CSS % (SERIES_LIGHT + SERIES_DARK)))
    parts.append("<h1>openab bot 使用統計</h1>")
    parts.append('<p class="meta">%s ~ %s ・ 時區 %s</p>'
                 % (_esc(report["since"]), _esc(report["until"]),
                    _esc(report["timezone"])))

    parts.append('<div class="caveats"><strong>讀這份報表前必須知道</strong><ul>')
    for line in report_mod._caveat_lines(report):
        parts.append("<li>%s</li>" % _esc(line.replace("**", "")))
    parts.append("</ul></div>")

    parts.append("<h2>每日任務數</h2>")
    parts.append(svg_stacked(days, task_series,
                             {"human": "真人", "bot_relay": "bot 互呼",
                              "cron": "cron 排程"}, "按來源分類的每日任務數"))
    parts.append(_table(
        ["日期", "bot", "真人", "bot 互呼", "cron 排程"],
        [[day, bot, c["human"], c["bot_relay"], c["cron"]]
         for day, bots in sorted(report["daily_tasks"].items())
         for bot, c in sorted(bots.items())]))

    parts.append("<h2>每日對話數</h2>")
    parts.append(svg_stacked(days, conv_series,
                             {"new": "新開", "continued": "延續"},
                             "每日有活動的 session"))
    parts.append(_table(
        ["日期", "bot", "新開", "延續"],
        [[day, bot, c["new"], c["continued"]]
         for day, bots in sorted(report["daily_conversations"].items())
         for bot, c in sorted(bots.items())]))

    parts.append("<h2>Token 用量（依 model）</h2>")
    parts.append(svg_hbars(model_rows, "各 model 的 token 總量"))
    parts.append(_table(
        ["日期", "bot", "model", "variant", "明細"],
        [[row["day"], row["bot"], row["model_id"] or "(未知)",
          row["model_variant"] or "—",
          ", ".join("%s=%d" % (k, v) for k, v in sorted(row["tokens"].items()))]
         for row in report["token_rows"]]))

    parts.append("<h2>活躍觸發者</h2>")
    parts.append(_table(
        ["bot", "人數", "備註"],
        [[bot, len(users),
          ("受 allowlist 限制，上界 %d 人" % report["allowlist_bounds"][bot])
          if report["allowlist_bounds"].get(bot) else "—"]
         for bot, users in sorted(report["active_users"].items())]))

    parts.append("<h2>摩擦指標（不是滿意度）</h2>")
    parts.append(_table(
        ["bot", "追問間隔中位數（秒）", "每 session 任務數", "只問一次就沒下文"],
        [[bot,
          "%.0f" % info["followup_median_seconds"]
          if info["followup_median_seconds"] is not None else "n/a",
          "%.2f" % info["tasks_per_session"]
          if info["tasks_per_session"] is not None else "n/a",
          info["abandoned_sessions"]]
         for bot, info in sorted(report["friction"].items())]))

    parts.append("<h2>開了 session 沒產出（紅旗，不是失敗率）</h2>")
    parts.append(_table(
        ["bot", "建立 session", "有產出", "落差"],
        [[bot,
          info["sessions_created"] if info["sessions_created"] is not None else "未知",
          info["sessions_with_output"],
          info["gap"] if info["gap"] is not None else "未知"]
         for bot, info in sorted(report["failure_proxy"].items())]))

    return "\n".join(parts)
