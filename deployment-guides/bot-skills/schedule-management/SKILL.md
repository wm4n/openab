---
name: schedule-management
description: 當人類要求 bot 定時／週期性執行某個任務並回報（每天總結 PR、每週報告、定期掃描告警…），或要求建立、修改、查看、停用排程時使用。一次性延遲提醒（那是 /remind）或單純問問題、看 code 時不要用。
---

# schedule-management

用 openab 內建的 **usercron** 幫人類建立週期排程：把 job 寫進 `~/.openab/cronjob.toml`，scheduler 每分鐘偵測檔案 mtime、自動熱重載。到點時 openab 把該 job 的 `message` 當成一個**新 prompt 丟進來**，你據此工作、把結果回報到指定 `channel`。

> ⚠️ **不要用 `CronCreate`／`CronList`／`CronDelete` 這類工具**——那是 Claude Code 內建、跟目前這個 session 綁定的排程機制（session 結束就消失，跟 `~/.openab/cronjob.toml` 無關，也不會真的把訊息送進 Discord 頻道）。這份 skill 講的 usercron，操作永遠是「讀寫 `~/.openab/cronjob.toml` 這個檔案」，不是呼叫任何排程工具。

## 分工：你能做什麼、不能做什麼（先懂，決定成敗）

- **你能做（不用重啟）**：建立／修改／查看／停用 `~/.openab/cronjob.toml` 裡的 job。改這個檔會被熱重載，1 分鐘內生效。
- **你不能做**：啟用 usercron 這個功能本身。它需要在 `config.toml` 加 `[cron]` 段並**重啟容器**；你在容器內改不到 runtime config、也不能重啟自己 → 那是容器外的人類的事。

> 唯一能證明「排程真的會 fire」的是 §4 的 ping 實測——不是這份文件、不是你讀到的 config。寫完檔就宣稱「設好了」是錯的。

## 步驟

### 1. 先向人類確認你無法自己可靠得知的事

- **channel ID**：`channel` 一定要填**真正的頻道 ID**，不能填 thread ID——openab 每次觸發都會在 `channel` 底下開一條新 thread，Discord 不允許 thread 底下再開 thread，填成 thread ID 會每次觸發都報 `failed to create thread: Cannot execute action on this channel type`。你在容器內沒有可靠管道把「當前頻道」解析成 ID，請對方在該頻道右鍵→「複製頻道 ID」（需開 Discord 開發者模式）貼給你。
  - 若對方只說「就這個頻道」，而 `cronjob.toml` 既有 job 已在用某個 channel ID → 可**推定**是同一個，但仍要跟對方確認一次再用。
  - 若對方想要 ping 貼進**現在這條既有 thread**而非開新的 → `channel` 仍填頻道 ID，另外加 `thread_id` 欄位填那條 thread 的 ID（兩個欄位一起設，不是二選一）。
- **時區**：`timezone` 不設預設是 **UTC**，會差 8 小時。跟對方確認（台灣多半是 `Asia/Taipei`）。
- **排程語意**：把你的理解講白讓對方確認——「每天」週幾欄用 `*`、「平日」才用 `1-5`（例：「你說每天 18:00 ＝ `0 18 * * *`（含週末），對嗎？」）。
- **任務範圍**：`message` 要能自足執行，先確認目標 repo、資料範圍、「成功／失敗」的定義（例：CI 檢查看哪個 repo、failing 是否含 cancelled／timed_out）。

### 2. usercron 是否已啟用？別為此流連——ping 才是判準

**預設就直接進 §3 寫檔**，用 §4 的 ping 當唯一判準：ping 有出現＝已啟用且整條鏈通；ping 沒出現＝多半沒啟用，再回頭請人開。runtime config 在容器內通常讀不到，不要為了確認它而逐一猜路徑空轉。

只有當你**剛好**讀得到 config（可試 `~/.openab/config.toml`、`/home/node/config.toml`、`/etc/openab/config.toml`）、且明確看到 `usercron_enabled = false` 或沒有 `[cron]` 段 → 才**提前**停下，請人類在 `config.toml` 加下面這段再 redeploy（你改不到 config、也不能重啟自己）：

```toml
[cron]
usercron_enabled = true
usercron_path = "cronjob.toml"
```

### 3. 寫 job——先讀既有檔，不要覆蓋別人的排程

```bash
mkdir -p ~/.openab
cat ~/.openab/cronjob.toml 2>/dev/null   # 先看有沒有既有 [[jobs]]，保留它們
```

多個排程＝檔案裡多個 `[[jobs]]` 區塊並排。用 Write 寫入**整份**（既有 job 原封不動 ＋ 你這筆），用 `id` 新增或替換你這一筆——不要只寫新那段把既有的洗掉：

```toml
[[jobs]]
id = "daily-merged-pr-summary"     # 有 id，scheduler writeback 才穩
enabled = true
schedule = "0 9 * * 1-5"
channel = "1490282656913559673"    # 字串包住 snowflake，避免數字精度問題
message = "總結昨天 merged 的 PR：用 gh 查出前一個日曆日內被 merge 的 PR，列出編號、標題、作者與一句話重點；若昨天沒有就直說。全部用繁體中文回報。"
sender_name = "DailyPR"
timezone = "Asia/Taipei"
```

- `message` 要寫成**自足的自然語言指令**——到點時它是一個新 turn 的 prompt，必須能自己判斷「昨天」怎麼算、沒資料怎麼講、用什麼語言。
- ⚠️ `message` 裡**不要**塞死 shell、`date -d`、或 crontab 式的 `%` 跳脫：`cronjob.toml` 是純 TOML（不是 crontab），且容器內 `date` 版本（BSD/GNU）不一定。把日期計算交給執行時的 agent。

### 4. 端對端實測（唯一可信的驗證）

你讀不到 `docker logs`，所以**用行為驗證**：暫時加一個每分鐘 ping job，看那個頻道 1–2 分鐘內有沒有冒出訊息。

```toml
[[jobs]]
id = "verify-ping"
enabled = true
schedule = "* * * * *"
channel = "1490282656913559673"
message = "usercron 自我測試 ping，收到請忽略"
sender_name = "verify"
timezone = "Asia/Taipei"
```

- **有冒出來** → 整條鏈通了（usercron 有開、路徑對、channel 對、bot 在該頻道）。**判斷是不是真訊號**：真的 ping 格式固定是 `🕐 [sender_name]: message`（獨立冒出的新訊息，不是回覆任何人）；如果看到的是自己編出來的一句話（例如現場跑 `date` 再回一句「看起來像 ping」的文字、或黏在對回覆裡），那不是真訊號，代表根本沒有走 usercron。確認是真訊號後，把 `verify-ping` 這段刪掉、只留正式 job，再存一次。
  - 之後同一個 job 每次觸發都會回到「第一次觸發時開的那條 thread」——scheduler 會自動把 `thread_id` 寫回 `cronjob.toml`，不用你自己管理，看到重複觸發都在同一條 thread 是正常行為。
- **沒冒出來** → 多半是 usercron 沒啟用（回 §2 請人加開關 + redeploy），或 channel ID 錯／bot 不在該頻道。

### 5. 回報人類

講清楚：正式 job 的時間／頻道／內容、你已用 ping 實測通過、以後要改時間或停用直接跟你說（你改 `cronjob.toml`、不用重啟）。

## 常用參考

- cron：`0 9 * * 1-5` 平日 9 點｜`0 18 * * *` **每天** 18 點｜`0 0 * * 0` 週日午夜｜`*/30 * * * *` 每 30 分｜`0 9 1 * *` 每月 1 號 9 點。
- 查看：`cat ~/.openab/cronjob.toml`。停用某 job：該段 `enabled = false`（或整段刪）。
- 其他欄位：`thread_id`（貼進既有 thread 而非開新頻道訊息，跟人類要這個 ID）、`platform`（預設 `"discord"`，只有要排 Slack 才需要指定 `"slack"`）。
- 進階：目標達成自停用 `disable_on_success`（需 `id`）；完整欄位／限制見 repo 的 `docs/cronjob.md` 或 `deployment-guides/CRONJOB.md`。
- ⚠️ 週幾別混用數字與名稱（`1,Mon` ❌）、別用繞回範圍（`5-2` ❌）；長任務（>5 分）別排太密（有 overlap 保護會跳過）。

## 鐵則

- 排程一律靠讀寫 `~/.openab/cronjob.toml`，**不使用 `CronCreate`／`CronList`／`CronDelete` 等工具**——那是另一套跟 openab usercron 無關的機制。
- 啟用 usercron（改 config + 重啟）不是你能做的——沒開就明講、請人類開，**絕不假裝已設好**。
- 沒用 §4 的 ping 實測通過前，不要對人類說「排程已生效」。
- 寫 `cronjob.toml` 前**先讀既有內容**，用 `id` 增改，別覆蓋別人的 job。
- `channel` 一定用人類確認過的數字 ID；`timezone` 一定明設。
- `message` 一定是自足的自然語言指令，不塞死 shell／日期邏輯。
