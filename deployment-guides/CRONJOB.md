# openab 定時排程設定教學（Usercron / cronjob.toml）

> 一份可獨立閱讀的 `cronjob.toml` 參考。openab **內建**排程，不需外部 cron：到點時把一句 prompt 當成「使用者輸入」丟給 agent，agent 跑完**回覆到指定 channel/thread**（＝定時執行任務 + 回報狀態）。
>
> 權威來源：repo 內 `docs/cronjob.md`、`docs/slash-commands.md`。部署脈絡見 `deployment-guides/BOT_SETUP.md` Part L。

---

## 目錄

- [0. 三種排程機制](#0-三種排程機制)
- [1. 快速上手（TL;DR）](#1-快速上手tldr)
- [2. 啟用 usercron（config.toml）](#2-啟用-usercronconfigtoml)
- [3. cronjob.toml 位置與熱重載](#3-cronjobtoml-位置與熱重載)
- [4. 欄位完整參考](#4-欄位完整參考)
- [5. cron 運算式格式](#5-cron-運算式格式)
- [6. 常用排程範例](#6-常用排程範例)
- [7. 進階 A：agent 自管排程](#7-進階-aagent-自管排程)
- [8. 進階 B：disable_on_success 目標達成自停](#8-進階-bdisable_on_success-目標達成自停)
- [9. 行為特性](#9-行為特性)
- [10. 已知限制](#10-已知限制)
- [11. 實作步驟（Morty / Mac mini）](#11-實作步驟morty--mac-mini)
- [12. 疑難排解](#12-疑難排解)
- [13. 何時改用外部排程](#13-何時改用外部排程)

---

## 0. 三種排程機制

| 機制                            | 用途                     | 重複      | 誰管理排程       | 改了要重啟?                |
| ------------------------------- | ------------------------ | --------- | ---------------- | -------------------------- |
| `[[cron.jobs]]`（config.toml）  | 定時丟 prompt 給 agent   | ✅        | 手改 config      | 要（config 掛載/redeploy） |
| **Usercron**（`cronjob.toml`）  | 同上，但**熱重載**       | ✅        | **agent 可自寫** | 不用（每分鐘偵測 mtime）   |
| `/remind`（Discord slash）      | 延遲後 @ 提醒某人        | ❌ 一次性 | 使用者           | —                          |

- 「定時執行任務並回報」用 **cron / usercron**；`/remind` 只到點 tag 人、**不會**叫 agent 做事。
- 本文件聚焦 **usercron（`cronjob.toml`）**，因為它熱重載、agent 可自管，最實用。
- `config.toml` 的 `[[cron.jobs]]` 是**不可變 baseline**；`cronjob.toml` 的 `[[jobs]]` 是**動態疊加層**。兩者可並存。

---

## 1. 快速上手（TL;DR）

```
① config.toml 加 [cron] 段（啟用 usercron）→ restart 一次
② 寫 /home/node/.openab/cronjob.toml（放 [[jobs]]）→ 1 分鐘內熱重載生效
③ 到點 → agent 收到 message → 回覆到 channel
```

最小可用範例：

```toml
# config.toml（加這段，要 restart）
[cron]
usercron_enabled = true
usercron_path    = "cronjob.toml"
```

```toml
# /home/node/.openab/cronjob.toml（改這個不用 restart）
[[jobs]]
schedule    = "0 9 * * 1-5"
channel     = "你的_channel_id"
message     = "總結昨天 merged 的 PR 並回報"
sender_name = "DailyOps"
timezone    = "Asia/Taipei"
```

---

## 2. 啟用 usercron（config.toml）

usercron **預設關閉**，兩個欄位都要填才啟用：

```toml
[cron]
usercron_enabled = true
usercron_path    = "cronjob.toml"   # 相對 $HOME/.openab/ → /home/node/.openab/cronjob.toml
```

- 路徑相對於 `$HOME/.openab/`（node 的 `$HOME` = `/home/node`）；填絕對路徑則照用。
- ⚠️ **v0.8.2 breaking change**：`usercron_path` 相對基準從 `$HOME` 改成 `$HOME/.openab/`。舊版升級要搬檔：`mkdir -p ~/.openab && mv ~/cronjob.toml ~/.openab/cronjob.toml`。
- 加 `[cron]` 這步是改 config.toml → **要 restart 一次**才生效（config 只在啟動時讀）。之後改 `cronjob.toml` 本身**不用** restart。
- `~/.openab/` 不存在也沒關係，scheduler 會靜默略過、之後檔案出現就自動撿起來。

---

## 3. cronjob.toml 位置與熱重載

- 檔案路徑：`/home/node/.openab/cronjob.toml`（在持久化 volume，restart / 更新映像都不掉）。
- 格式跟 `[[cron.jobs]]` 一樣，但用 **`[[jobs]]`**（不是 `[[cron.jobs]]`）。
- 熱重載機制：

```
每個 scheduler tick（約 1 分鐘）
  → 檢查 cronjob.toml 的 mtime
  → 有變 → 重新 parse、替換動態 job 清單（log: "usercron file changed, reloading"）
  → 該 fire 的 job → 送 message → 建 thread → agent 處理 → 回覆 channel
```

- TOML 壞掉或某筆 entry 無效 → 記 log 並略過，**不影響 baseline job**。
- 刪掉整個檔 = 移除所有動態 job（baseline `[[cron.jobs]]` 繼續跑）。

---

## 4. 欄位完整參考

`[[jobs]]`（usercron）／`[[cron.jobs]]`（baseline）共用欄位：

| 欄位          | 必填 | 預設           | 說明                                                    |
| ------------- | ---- | -------------- | ------------------------------------------------------- |
| `schedule`    | ✅   | —              | 5 欄位 POSIX cron 運算式                                |
| `channel`     | ✅   | —              | Discord 頻道/thread ID 或 Slack 頻道 ID                 |
| `message`     | ✅   | —              | 送給 agent 當 prompt 的訊息                             |
| `enabled`     |      | `true`         | 設 `false` 可保留 entry 但停用                          |
| `platform`    |      | `"discord"`    | `"discord"` 或 `"slack"`                                |
| `sender_name` |      | `"openab-cron"`| 顯示在 prompt 脈絡/thread 標題，用來區分不同排程        |
| `timezone`    |      | `"UTC"`        | IANA 時區，如 `"Asia/Taipei"`；⚠️ 不設會用 UTC，差 8 小時 |
| `thread_id`   |      | —              | post 進既有 thread 而非 channel                         |

**僅 usercron `[[jobs]]` 支援**（用於目標達成自停，見 §8）：

| 欄位                             | 說明                                             |
| -------------------------------- | ------------------------------------------------ |
| `id`                             | scheduler writeback 需要（enabled 回寫、goal 自停）|
| `disable_on_success`             | fire 前先跑的檢查指令                            |
| `disable_on_success_match`       | 指令輸出需包含的字串                            |
| `disable_on_success_timeout_secs`| 檢查指令逾時秒數                                |
| `disable_on_success_working_dir` | 檢查指令的工作目錄                              |

> **Sender 身份**：job fire 時 agent 看到的脈絡長這樣 —— `🕐 [DailyOps]: 總結昨天 merged 的 PR 並回報`。用 `sender_name` 讓 agent 能分辨是哪個排程在叫它。

---

## 5. cron 運算式格式

標準 5 欄位 POSIX cron，跟 Linux crontab / K8s CronJob / GitHub Actions 一樣：

```
┌───────────── 分   (0-59)
│ ┌───────────── 時   (0-23)
│ │ ┌───────────── 日   (1-31)
│ │ │ ┌───────────── 月   (1-12)
│ │ │ │ ┌───────────── 週   (0-7，0 和 7 都是週日)
│ │ │ │ │
* * * * *
```

| 運算式          | 意義                 |
| --------------- | -------------------- |
| `0 9 * * 1-5`   | 平日 09:00           |
| `0 0 * * 0`     | 週日午夜             |
| `*/30 * * * *`  | 每 30 分鐘           |
| `0 18 * * 1-5`  | 平日 18:00           |
| `0 9 1 * *`     | 每月 1 號 09:00      |
| `* * * * *`     | 每分鐘（測試用，會洗頻道）|

> 週幾也可用名稱：`Mon-Fri`、`Sun`、`Mon,Wed,Fri`（但別跟數字混用，見 §10）。

---

## 6. 常用排程範例

```toml
# 平日早上總結 PR
[[jobs]]
schedule    = "0 9 * * 1-5"
channel     = "你的_channel_id"
message     = "總結昨天 merged 的 PR 並回報"
sender_name = "DailyOps"
timezone    = "Asia/Taipei"

# 每週日產週報
[[jobs]]
schedule    = "0 0 * * 0"
channel     = "你的_channel_id"
message     = "產生本週狀態週報"
sender_name = "WeeklyReport"
timezone    = "Asia/Taipei"

# 每 30 分鐘掃一次告警
[[jobs]]
schedule    = "*/30 * * * *"
channel     = "你的_channel_id"
message     = "檢查最近 30 分鐘有沒有 critical 告警"
sender_name = "OpsBot"
timezone    = "Asia/Taipei"
```

---

## 7. 進階 A：agent 自管排程

`cronjob.toml` 是純檔案，agent 有 Bash/檔案工具就能自己寫。所以可以直接對 bot 講：

```
你：幫我設一個每天早上 9 點總結 PR 的排程
bot：✅ 已寫入 cronjob.toml，1 分鐘內生效
```

好處：手機上跟 bot 聊天就能改排程，不用進主機。

---

## 8. 進階 B：disable_on_success 目標達成自停

usercron 專屬。每次 fire **之前**先跑 `disable_on_success` 檢查指令，**exit 0 且輸出含 `disable_on_success_match`** → 回報 `✅ Goal achieved`、把該 job 寫回 `enabled = false`、跳過該次 prompt；否則照送 `message` 讓 agent 繼續。

```toml
[[jobs]]
id = "fix-unit-tests"                        # ⚠️ writeback 需要 id
enabled = true
schedule = "*/10 * * * *"
channel  = "你的_channel_id"
message  = "Unit tests 還是紅的，繼續修並回報進度"

disable_on_success = "npm test && echo OPENAB_GOAL_SUCCESS"
disable_on_success_match = "OPENAB_GOAL_SUCCESS"
disable_on_success_timeout_secs = 120
disable_on_success_working_dir = "/home/node/<repo>"
```

執行流程：

1. 排程時間到。
2. scheduler 跑 `disable_on_success`。
3. 若 exit 0 且輸出含 `disable_on_success_match` → post `✅ Goal achieved`、回寫 `enabled = false`、**跳過** prompt。
4. 否則 → 照送 `message`，agent 繼續做。

> `disable_on_success` 只支援 usercron `[[jobs]]`，baseline `[[cron.jobs]]` 不支援（限制 writeback 只動使用者管的檔）。
>
> **重新啟用**：改 `$HOME/.openab/cronjob.toml` 把 `enabled = true` 翻回來（手動，或叫 agent「re-enable the fix-unit-tests cron job」）。

---

## 9. 行為特性

- **對齊整分**：scheduler 對齊分鐘邊界（`:00`），`0 9 * * *` 會在 09:00:00 準時 fire，不是啟動當下那個秒數。
- **Overlap 保護**：同一個 job 上一輪還在跑 → 下一個 tick 直接跳過（log: `skipping cronjob, previous execution still running`）。
- **隔離**：cron 失敗只記 log，**不會**卡到互動聊天。
- **Usercron 持久化**：scheduler 可能把 `thread_id` 和 `enabled = false` 回寫進 `cronjob.toml`。
- **優雅關閉**：關機時等進行中的 cron 任務最多 30 秒。

---

## 10. 已知限制

| 限制                     | 說明                                                                 |
| ------------------------ | -------------------------------------------------------------------- |
| 週幾數字/名稱混用        | `1,Mon`、`Mon,3` 不支援，會被拒。要嘛全數字（`1-5`）要嘛全名稱（`Mon-Fri`）|
| 週幾繞回範圍             | `5-2`（週五到週二）不支援，改用明列 `5,6,0,1,2`                       |

---

## 11. 實作步驟（Morty / Mac mini）

> 共通鐵則：一律 `-u node`、heredoc 寫檔，**絕不 `docker cp`**（會變 root 擁有 → agent 讀不到 → Discord `Connection Lost`）。cronjob.toml 一律在 `/home/node/.openab/`。先備好一個 **bot 已在裡面的頻道 ID**（cron 輸出是伺服器端注入，post 到 `channel` 就會發，**不需要**該頻道在 `allowed_channels`）。

### A. Morty（Portainer，只有網頁 Console）

Containers → Morty 容器 → **Console**（Command `/bin/sh`、User `node`）：

```bash
# 1) 確認 config 路徑 + 有沒有既有 cron（Portainer 版 config 在 /home/node/config.toml）
ls -l /home/node/config.toml
grep -ni cron /home/node/config.toml            # 沒輸出 = 乾淨可加

# 2) 加 [cron] 段（沒有 cron 才加，避免 TOML 重複表格）
grep -qi cron /home/node/config.toml \
  && echo "⚠️ 已有 cron 設定，先看內容別亂加" \
  || printf '\n[cron]\nusercron_enabled = true\nusercron_path    = "cronjob.toml"\n' >> /home/node/config.toml

# 3) 寫排程（測試用每分鐘，channel 換成你的 ID）
mkdir -p /home/node/.openab
cat > /home/node/.openab/cronjob.toml <<'EOF'
[[jobs]]
schedule    = "* * * * *"
channel     = "你的_channel_id"
message     = "usercron 測試，回一句 pong 就好"
sender_name = "usercron-test"
timezone    = "Asia/Taipei"
EOF

# 4) 確認寫好
grep -n cron /home/node/config.toml             # 要看到 [cron] 三行
cat /home/node/.openab/cronjob.toml
```

然後 **Portainer → Containers → Morty 容器 → Restart**（config 改過要重讀；之後改 cronjob.toml 不用）。
驗證：Portainer → 該容器 → **Logs** 找 `usercron file changed, reloading`；Discord 頻道每分鐘冒出一則回覆。

### B. Mac mini（Rick / Summer，走 `docker -c orbstack`）

以 `openab-summer` 為例，Rick 換成 `openab-rick`。**差別只在 config 在哪**：

```bash
# 0) 先查 config 位置（Summer 掛在 host、Rick 未定案）
docker -c orbstack inspect openab-summer --format 'Args: {{.Args}}'
docker -c orbstack inspect openab-summer \
  --format '{{range .Mounts}}{{.Source}} => {{.Destination}} ({{if .RW}}rw{{else}}ro{{end}}){{"\n"}}{{end}}'
```

- **config 從 host 唯讀掛載**（Summer 應是 `~/openab-summer => /etc/openab (ro)`）→ 改 host 檔：
  ```bash
  grep -qi cron ~/openab-summer/config.toml \
    && echo "⚠️ 已有 cron 設定，先看別亂加" \
    || printf '\n[cron]\nusercron_enabled = true\nusercron_path    = "cronjob.toml"\n' >> ~/openab-summer/config.toml
  ```
- **config 在容器 volume**（Rick 若是 `/home/node/config.toml`）→ 容器內加：
  ```bash
  docker -c orbstack exec -u node openab-rick sh -c \
    'grep -qi cron /home/node/config.toml && echo "⚠️ 已有 cron" || printf "\n[cron]\nusercron_enabled = true\nusercron_path    = \"cronjob.toml\"\n" >> /home/node/config.toml'
  ```

restart + 寫排程 + 驗證：

```bash
# 重啟讓 [cron] 生效
docker -c orbstack restart openab-summer

# 寫測試排程
docker -c orbstack exec -i -u node openab-summer sh -c \
  'mkdir -p /home/node/.openab && cat > /home/node/.openab/cronjob.toml' <<'EOF'
[[jobs]]
schedule    = "* * * * *"
channel     = "你的_channel_id"
message     = "usercron 測試，回一句 pong 就好"
sender_name = "usercron-test"
timezone    = "Asia/Taipei"
EOF

# 驗證
docker -c orbstack logs --tail 80 openab-summer 2>&1 | grep -iE "cron|schedul"
```

### 驗證 OK 後：換真排程或清空測試

`* * * * *` 每分鐘會洗頻道，測完務必換掉。重寫 `cronjob.toml` 成真排程，或清空停用：

```bash
# 清空（= 移除所有動態 job，不用 restart）
cat > /home/node/.openab/cronjob.toml <<'EOF'
# 無 job；或貼上你的真排程
EOF
```

---

## 12. 疑難排解

| 症狀                         | 原因                                    | 解法 / log 關鍵字                                    |
| ---------------------------- | --------------------------------------- | ---------------------------------------------------- |
| job 不 fire                  | cron 運算式無效                         | log `invalid cron expression, skipping`              |
| job fire 但沒回覆            | agent 出錯                              | log `cron handle_message error`                      |
| 時間不對                     | 時區沒設（預設 UTC）                    | 明確設 `timezone = "Asia/Taipei"`                    |
| job 被跳過                   | 上一輪還在跑                            | log `skipping cronjob, previous execution still running` |
| `Channel not found`          | bot 不在該頻道                          | 把 bot 邀進 `channel` 指的頻道                        |
| usercron 沒重載              | 檔沒存好 / 路徑錯                       | log `usercron file changed, reloading`；確認在 `~/.openab/` |
| usercron parse error         | TOML 語法錯                             | log `failed to parse usercron file`                  |
| goal job 沒自動停            | 指令沒 exit 0，或輸出不含 match         | 手動跑 `disable_on_success` 指令確認兩條件都滿足     |

---

## 13. 何時改用外部排程

config-driven cron 覆蓋 80%「到點送一句話」的情境。進階需求改用外部排程：

| 需求                    | 建議                                    |
| ----------------------- | --------------------------------------- |
| 簡單週期性 prompt       | ✅ usercron / `[[cron.jobs]]`（本文件） |
| 長任務（>5 分鐘）       | K8s CronJob                             |
| 條件邏輯 / 重試         | GitHub Actions / Step Functions         |
| 多步驟 workflow / DAG   | GitHub Actions / Step Functions         |
| 每次執行獨立隔離        | K8s CronJob（每次一個 Pod）             |

> openspec 開發那種可能跑很久的任務，別用 usercron 排太密（有 overlap 保護會跳過，但單次 >5 分鐘官方建議走外部排程）。
