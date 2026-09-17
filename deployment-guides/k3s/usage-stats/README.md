# openab bot 使用統計

從各 agent CLI 自己的儲存挖出使用統計。**不改 openab 本體**，資料源已在 k3s
節點實機驗證（工具與結果見 `../verify-stats-sources.py` 與 `../README.md`）。

> ## ⚡ 狀態（2026-09-17）
>
> **❌ 尚未部署。** 程式碼（13 個 task、203 個 unittest）已完成並 push 在
> `docs/three-bot-pipeline` branch，但：
>
> - 靜態 PV／`usage-stats-scripts` ConfigMap／`cronjob.yaml` **都還沒 apply**（步驟見 `../../K3S.md`「使用統計 CronJob」）。
> - 「端對端驗收」（人工對照 Discord 當天實際訊息數，確認真人任務數對得上）**還沒做**。這步不能省——統計系統最常見的失敗模式是「跑得很順、數字全錯」，而且錯了沒人發現。
>
> ### 🔴 涵蓋範圍已經變了，部署前先讀這段
>
> `cronjob.yaml` 用 `hostPath: /data/william/openab` 讀 **k3s 節點上**的 agent
> PVC。**2026-09-15 起 Rick / Morty / Summer 已搬到 Mac mini OrbStack**，資料在
> 那台機器的 docker volume（`openab-rick-home` 等）裡，這支 CronJob **永遠收不到
> 那三隻**。所以：
>
> | bot | 活資料在哪 | 這支 CronJob 收得到嗎 |
> | --- | --- | --- |
> | genie / kimi / walle / eve | k3s 節點 `/data/william/openab/agent-*` | ✅ |
> | rick / morty / summer | Mac mini 的 docker volume | ❌ 完全收不到 |
>
> 而且**那三隻在 k3s 上的歷史資料已經沒了**——PVC 於搬家當天刪除。唯一可能的
> 來源是 `openab-archive.sh` 建的鏡像（`/data/william/openab-archive/mirror`，
> 每週日 02:00，最後一次應是 09-14），要用下面的 `--archive-root` 回填；動手前
> 先確認鏡像真的有跑到：
>
> ```bash
> sudo ls -l /data/william/openab-archive/mirror/{rick,morty,summer} 2>/dev/null
> sudo tail -5 /var/log/openab-archive.log
> ```
>
> **要把 Mac 那三隻納入統計**，2026-09-17 已備妥一條路徑：
> [`../../mac/openab-archive.sh`](../../mac/README.md) 會把三隻的 transcript 鏡像成
> **與本目錄 `collect.py` 的 `_MIRROR_LAYOUT` 相同的佈局**
> （`<bot>/{claude-projects,codex-sessions,openab}`），所以直接餵給 `--archive-root`
> 就能吃：
>
> ```bash
> python3 collect.py --root <不存在的目錄> --out <輸出目錄> \
>   --archive-root ~/openab-archive/mirror
> ```
>
> ⚠️ 但那支腳本**還沒在目標 Mac 上掛起來**，`cleanupPeriodDays` 也還沒調高——在那
> 之前，那三隻的 transcript 仍在以 30 天為期滾動消失。兩個步驟見
> [`../../mac/README.md`](../../mac/README.md)。

設計依據：`docs/superpowers/specs/2026-09-10-bot-usage-stats-design.md`
實作計畫：`docs/superpowers/plans/2026-09-11-bot-usage-stats.md`
建置記錄與經驗教訓：[`RETROSPECTIVE.md`](RETROSPECTIVE.md)

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

## 從 archive/mirror 回填歷史資料（一次性，非每日步驟）

`collect.py` 的 CronJob 只讀**活的**（CLI 還在維護的）transcript／SQLite，
在 `../K3S.md`「⚠️ transcript 保留期限」建的 archive/mirror（`openab-archive.sh`
產生）不在它的掃描範圍內——mirror 用重新命名過的子目錄
（`claude-projects`／`codex-sessions`／`opencode`／`openab`），跟收集器認得的
活資料佈局不同名，兩者本來就是獨立的機制：mirror 是保留期限清資料前的緊急
措施，收集器上線後才是正規的持久紀錄。

CronJob 上線之前，有些 bot 已經因為保留期限被清掉一段歷史（例如 genie
2026-08-04~08-11），那段資料**只存在於 mirror**，活目錄已經沒有。要把它補回
報表，用 `--archive-root` 指到 mirror 路徑：

    python3 collect.py --root /data/william/openab --out <輸出目錄> \
      --archive-root /data/william/openab-archive/mirror

做法是幫每隻 bot 建一組符號連結，把 mirror 的重新命名子目錄接回 parser 認得的
活資料佈局（`.claude/projects` 等），不用改任何 parser。水位另外用
`archive:<bot>` 命名空間存，跟活資料的水位分開，重跑不會重複計算，也不會
互相覆蓋。

**這是一次性（或偶爾）的回填操作，不是每日 CronJob 的一部分**——mirror 內容
變動很慢（週期性 rsync），沒有必要每天跑。回填出來的事件跟 CronJob 收集的
事件寫進同一批日期分桶檔案，`report.py` 不用改就看得到。

注意：mirror 的 `thread_map.json` 只是某個時間點的舊快照，回填時**刻意不**
拿它更新 `thread-map-counts.json`——混進「現在」的失敗率代理只會誤導判讀。

## 設定檔（頻道名稱／使用者真名）

`sender_context` 帶的只有 Discord 的 `channel_id`／`sender_id`（數字 ID）和當下
的 `display_name`（可能是暱稱、可能缺漏）。想在報表看到人看得懂的頻道名稱或
真人姓名，複製 `config.example.json` 成 `config.json`（已加進 `.gitignore`，
真人姓名不可進版控）填對照表，跑 `report.py` 時加 `--config config.json`：

```json
{
  "channel_names": {"1528965074562191420": "cac-dev-team"},
  "user_names": {"824092654060830770": "王小明"}
}
```

`user_names` 的優先序是：設定檔對照 > `sender_context` 的 `display_name` >
原始 `sender_id`，三種報表格式（text／md／html）都會套用，也都會列出「逐使用者
任務數」明細（不只是人數彙總）。

## 跑測試

    python3 -m unittest discover -s tests -t . -v

只用標準庫，沒有 pip 依賴。

## 讀數字前必須知道的限制

報表本身會印出這些，但先讀一次：任務數僅含成功的任務、對話數逐日加總會大於
實際、摩擦指標不是滿意度、token 歸因是 session 層估計值、`allowedUsers` 非空的
bot 活躍人數有上界。細節與資料契約的七條重點見 spec。
