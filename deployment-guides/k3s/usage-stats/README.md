# openab bot 使用統計

從各 agent CLI 自己的儲存挖出使用統計。**不改 openab 本體**，資料源已在 k3s
節點實機驗證（工具與結果見 `../verify-stats-sources.py` 與 `../README.md`）。

設計依據：`docs/superpowers/specs/2026-09-10-bot-usage-stats-design.md`
實作計畫：`docs/superpowers/plans/2026-09-11-bot-usage-stats.md`

## 元件

四段管線，各自職責分開：

| 檔案 | 職責 |
| --- | --- |
| `events.py` | 正規化事件的共同型別與 I/O（task／usage schema、台北日界線、JSONL 讀寫） |
| `sender_context.py` | 從轉義 JSON 字串抽出 `<sender_context>`、三分類（human／bot_relay／cron）、去重鍵 |
| `parse_claude_code.py`／`parse_codex.py`／`parse_opencode.py` | 三個 CLI 各自的 transcript／SQLite parser，各自處理自家格式的「哪些數字不能加」 |
| `collect.py` | CronJob 入口：偵測 CLI、跑對應 parser、按台北日界線切檔、水位持久化 |
| `aggregate.py` | 純函數：正規化事件 → 每日指標（任務數、token、成本、摩擦指標、失敗率代理、覆蓋率） |
| `report.py` | 使用者 CLI：吃已累積的事件，產 text／md／html 報表 |
| `render_html.py` | 把報表資料模型算成自帶資源的單一 HTML（inline SVG，零外部請求） |

## 收集與報表是兩件事

- **收集**（`collect.py`，CronJob 每天跑）：把原始儲存轉成正規化事件並累積。
  **必須定期跑** —— claude-code 有 transcript 保留期限（`cleanupPeriodDays`，
  預設 30 天），錯過即永久遺失。
- **報表**（`report.py`，你想看就跑）：吃已累積的事件，不碰原始儲存。所以可以
  重跑、可以改指標定義後重算歷史、可以指定任意日期範圍。

## 產報表

    python3 report.py --data <收集輸出目錄> --since 2026-09-01 --until 2026-09-10
    python3 report.py --data … --since … --until … --bots rick,morty
    python3 report.py --data … --since … --until … --format md   -o report.md
    python3 report.py --data … --since … --until … --format html -o report.html

HTML 是自帶所有資源的單一檔案（零外部請求），`open report.html` 就能看，
不需要 nginx 或任何靜態檔服務。

## 部署 CronJob

前置步驟、`cronjob.yaml` 內容與靜態 PV 見 `cronjob.yaml` 檔頭註解與
`../../K3S.md`「使用統計 CronJob」一節。

## 跑測試

    python3 -m unittest discover -s tests -t . -v

只用標準庫，沒有 pip 依賴。

## 讀數字前必須知道的限制

報表本身會印出這些，但先讀一次：任務數僅含成功的任務、對話數逐日加總會大於
實際、摩擦指標不是滿意度、token 歸因是 session 層估計值、`allowedUsers` 非空的
bot 活躍人數有上界。細節與資料契約的七條重點見 spec。
