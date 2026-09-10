# openab bot 頻道使用統計（任務數／對話數／token 對應 model／摩擦指標）：設計文件

- 日期：2026-09-10
- 狀態：設計已定案（brainstorming 對話中逐項確認，資料源已在 k3s 節點實機驗證），
  待使用者複審 spec 全文
- 範圍：在不改動 openab 本體的前提下，從各 agent CLI 自己的儲存挖出使用統計，
  產出每日／每週報表。涵蓋現行七隻 bot（rick／morty／genie／summer／kimi／
  walle／eve）。
- 語言：繁體中文
- 前置作業（已完成）：資料源盤點與驗證工具
  `deployment-guides/k3s/verify-stats-sources.py`，實跑結果與資料契約重點記錄在
  `deployment-guides/k3s/README.md`（commit `4f25f103`、`b84937c2`、`c5fedcf3`、
  `6d6698c7`）。**本文件所有「資料在哪、長什麼樣」的敘述都來自該工具的實機輸出，
  不是推測。**

## 背景與目標

需求來自兩件事。一是 `deployment-guides/capacity-budget-estimate-2027.md` 裡的
容量／預算模型建立在主觀校準值上（每人 1.5 個並發 session、15%／25% 重疊率），
該文件第 10 節自己也標明「非統計量測」；二是需要對內證明採用率，以及日常看哪隻
bot 在卡、誰在燒量。

使用者選定的優先順序是「三個用途都要，先做最小可落地集合」。

要產出的四項：

| 指標 | 定義概要 |
| --- | --- |
| 每日任務數 | 當日觸發 agent 工作的平台訊息數，按來源分三類 |
| 每日對話數 | 當日有活動的 session 數，分新開／延續 |
| Token 用量 | 按 (bot, CLI, model, variant, token 類別) 分組，可換算成本 |
| 摩擦指標 | 從對話紀錄推論的弱訊號，**不是滿意度** |

## 非目標（YAGNI，brainstorming 過程中逐一排除）

- **不做長駐的儀表板服務。** 網頁報表**在範圍內**，但形式是「CLI 產出一個自帶資源
  的 HTML 檔，用瀏覽器開」，不是架一個會自己更新的服務。Grafana 那條要另外架
  Prometheus，第一版不碰；nginx／靜態檔服務也不需要（見「元件 4」）。
- **不改 openab 本體。** 已確認 openab 完全沒有 metrics／OTEL，ACP 層的
  `classify_notification`（`crates/openab-core/src/acp/protocol.rs:224`）只認 6 種
  `sessionUpdate`、其餘 `_ => None` 丟掉，所以 token 只能從 CLI 端拿；既然如此，
  改 Rust 對這四項指標沒有增益（唯一例外見「已知限制」的失敗率）。
- **不做明確的使用者滿意度收集。** 使用者確認第一版接受只有摩擦指標。reaction 在
  openab 的 Google Chat／LINE／WeCom／Teams adapter 都是靜默丟棄，而 Google Chat
  已在計畫內，所以 reaction 不能當主軸；文字評分會多燒一次 ACP turn。兩者都延後。
- **不做 per-task 的 token 歸因。** 見「元件 3」的歸因層級說明。
- **不量真實失敗率。** 見「已知限制」。

## 已驗證的資料源事實

這一節是整份設計的地基，全部來自實機輸出。

### 為什麼這條路可行

openab 把 `SenderContext`（`crates/openab-core/src/adapter.rs:176`）以 JSON 注入
**每一次** prompt（`pack_arrival_event`，同檔 `:417`），而 prompt 原文會被 CLI 寫進
自己的儲存。四個生產者——`discord.rs:2135`、`slack.rs:1447`、`gateway.rs:826`
（Google Chat／Teams／LINE／Telegram／WeCom／Feishu 全走這條）、`cron.rs:698`——
都吐同一個 `schema: "openab.sender.v1"`。**這是 openab 自己的抽象層，不是 Discord
的東西**，所以換平台不用改統計側。

實測七隻全部有完整欄位（`sender_id`／`sender_name`／`display_name`／`channel`／
`channel_id`／`thread_id`／`is_bot`／`timestamp`／`message_id`／`receiver_id`），
`不可解析 0`：

| bot | CLI | 形式 | 可回溯起日 | 成本 |
| --- | --- | --- | --- | --- |
| rick／morty | claude-code | JSONL | 2026-08-18 | 需價目表（訂閱制） |
| genie | claude-code | JSONL | 2026-08-11 | 需價目表（訂閱制） |
| summer | codex | JSONL | 2026-07-21 | 需價目表（訂閱制） |
| kimi／walle／eve | opencode | SQLite | 2026-09-10 | **CLI 已算好** |

### 每個 CLI 的權威路徑與陷阱

**共通：`channel` 欄位不可當維度。** `discord.rs:2139` 硬寫 `"discord"`、
`slack.rs:1451` 硬寫 `"slack"`、`gateway.rs:830` 放 `event.channel.channel_type`
（頻道**型別**）。頻道維度只能用 `channel_id`，名稱另外查表。平台維度也不能靠它
（Google Chat 走 gateway 會拿到 channel_type），可靠來源是 `thread_map.json` 的
`platform:thread_id` key。thread 裡 `channel_id` 是**父頻道**、`thread_id` 才是
thread 本身（`discord.rs:2140`）。

**claude-code**（`~/.claude/projects/**/*.jsonl`）

- 權威用量：每筆 assistant 紀錄的 `message.usage` 頂層四欄
  （`input_tokens`／`output_tokens`／`cache_creation_input_tokens`／
  `cache_read_input_tokens`）。
- 明細，**不可加**：`message.usage.cache_creation`（ephemeral 1h/5m 的 TTL 拆解，
  數值等於外層 `cache_creation_input_tokens`）、`message.usage.iterations[]`
  （每次 iteration 的明細，欄位名與外層相同）。
- 非計費，**不可加**：`message.usage.server_tool_use`（請求次數）、
  `message.diagnostics.cache_miss_reason.cache_missed_input_tokens`、
  `compactMetadata.{preTokens,postTokens,cumulativeDroppedTokens}`、
  `toolUseResult.totalTokens`。
- **巢狀的獨立用量，要加**：`toolUseResult.usage` 的頂層四欄，那是 Task tool 呼叫
  subagent 的真實 API 用量。實測 genie 的 `isSidechain` 全部是 `false`（32413 筆，
  零筆 `true`），代表 subagent 自己的訊息**不在** transcript 裡，所以這是唯一來源。
  它底下的 `iterations[]`／`cache_creation` 仍是明細不可加。量級約佔總量 0.1%
  （genie：`toolUseResult` cache_read 3.4M 對 `message.usage` cache_read 3.03B）。
- model：只信 `message.model`。排除 `message.content[].input.model`（Task tool 傳給
  subagent 的參數，值會是 `opus` 這種簡寫）與 `<synthetic>`（CLI 內部合成訊息，
  無實際 API 呼叫）。
- `sender_context` 出現在 `message.content[].text` 與 `attachment.prompt[].text`
  兩個路徑（實測 genie 382 筆中 362 個 distinct `message_id`）。

**codex**（`~/.codex/sessions/**/*.jsonl`）

- **最大陷阱：`payload.info.total_token_usage` 是 session 累積值。** 每個
  `token_count` event 都重報一次到目前為止的累積，加總所有 event 就是把累積值再
  累積。實測 summer：`total_token_usage.total_tokens=418458730` 對
  `last_token_usage.total_tokens=21561974`，差 19.4 倍。**整個
  `total_token_usage` 子樹都是累積值**，不只 `total_tokens` 那一欄。
- 權威用量：兩種等價做法——
  (a) 每個 session 取**最後一筆** `total_token_usage`；
  (b) 加總所有 `last_token_usage`。
  本設計採 (b)，因為它對「session 中途被截斷」較穩健，且與其他兩家「逐筆累加」的
  處理方式一致。
- **這兩種做法互為交叉驗證，parser 要同時算並斷言相等**：
  `Σ last_token_usage` 應等於 `Σ_sessions final(total_token_usage)`。實測 summer
  的 `Σ last_token_usage.total_tokens = 21561974`，而 `Σ 所有 event 的
  total_token_usage.total_tokens = 418458730`（累積值被重複加總的結果）。兩者不相等
  時代表對 codex 的 event 語意理解有誤，要中止而非產出可疑數字。
- model：`payload.model`。排除 `payload.collaboration_mode.settings.model`（設定值）。
- `sender_context` 出現在 `payload.content[].text` 與 `payload.message`
  （實測 summer 74 筆中 37 個 distinct `message_id`，正好一半，兩路徑各一份）。

**opencode**（`~/.local/share/opencode/opencode.db`，SQLite + WAL）

20 張表，統計相關四張，而**同一筆 token 在四處重複出現**：

| 表 | 角色 | 是否可加 token |
| --- | --- | --- |
| `session` | 每 session 一列，權威加總 + `cost:REAL` | 可（per-session 層） |
| `message` | per-turn，`data:TEXT` 為 JSON | 可（per-turn 層） |
| `part` | `sender_context` 在此 | **不可**，`data.tokens.*` 與 message 層同值（實測 walle 兩者 `tokens.total` 皆 1201009） |
| `event` | event sourcing log | **不可**，`data.info.tokens` 與 `data.part.tokens` 又各一份 |

- 權威用量：per-turn 用 `message.data.tokens` 的 `input`／`output`／`reasoning` 與
  `cache.read`／`cache.write`；`message.data.tokens.total` 是加總欄位，排除。
  per-session 用 `session.tokens_*` 與 `session.cost`。
- `session.parent_id` 非空 = subagent 子 session，加總時不可與 parent 重複計算
  （實測目前三隻皆為 0 列，但不能假設永遠如此）。
- model：字串形式在 `message.data.modelID`；`session.model` 是 **JSON 物件**，形如
  `{"id":"deepseek/deepseek-v4-pro-0813","providerID":"openrouter","variant":"low"}`。
  `variant`（實測 walle 有 `low`／`default`）可能影響計價，所以 model 維度是
  **`(id, variant)`** 而不只是 id。實測 kimi 一隻就用過三個 model
  （`kimi-k3`／`kimi-k2.7-code`／`gemini-3-pro-image-preview`），不可假設 bot 與
  model 一對一。
- 讀取方式：DB 正被跑著的 pod 寫入，必須先把 `db`／`-wal`／`-shm` 複製到暫存目錄
  再讀複本，不碰原檔（WAL 模式下連唯讀開啟都可能需要建 `-shm`）。

### 任務來源要分三類

`cron.rs:714` 的 usercron `SenderContext` 是 `message_id: None`、`is_bot: true`、
`sender_id: "openab-cron"`。所以 `is_bot` 只分得出「非真人」，分不出「bot 互呼」與
「排程觸發」。實測 Rick 的 163 筆拆解，三個數字閉合：

| 類別 | 筆數 | 判別 |
| --- | --- | --- |
| 真人 | 17 | `is_bot == false` |
| bot 互呼（三 bot 接力） | ~9 | `is_bot == true` 且 `message_id` 非空 |
| cron 自動觸發 | 137 | `sender_id == "openab-cron"`（等價於 `message_id` 為空） |

（17 + 9 = 26，正好等於帶 `message_id` 的筆數。）**Rick 的主要負載來自排程，真正的
三 bot 接力只佔約 5%。** 只分「真人 vs bot」會把這件事藏起來，也會讓採用率虛報。
Summer 真人 30／bot 44，Genie 真人 360／bot 22。

## 架構總覽

```
/data/william/openab/agent-*/          （k3s 節點 openab 上的 local PV）
   ├─ .claude/projects/**/*.jsonl
   ├─ .codex/sessions/**/*.jsonl
   ├─ .local/share/opencode/opencode.db
   └─ .openab/thread_map.json
                    │
                    ▼  collect.py — parser × 3（★ CronJob 每天跑這段，只收集）
        正規化事件 JSONL（task 流 + usage 流，按日切檔，存獨立 PVC）
                    │
                    ▼  aggregate.py（純函數）
              每日指標 SQLite
                    │
                    ▼  report.py — 使用者手動跑，可指定日期範圍與 bot
        ┌───────────┴───────────┐
   terminal / markdown      單一 HTML 檔
                            （自帶資源，瀏覽器直接開，不需服務器）
```

**分工的關鍵**：CronJob 只負責收集，因為原始資料會被 CLI 清掉（見元件 4 的
「保留期限」）、錯過就永久遺失。報表則是隨時手動產生，吃已累積的正規化事件，
所以可以重跑、可以改指標定義後重算歷史。這也是中間那層正規化事件存在的第二個
理由。

四個元件各自可獨立測試。中間「正規化事件」這一層是刻意加的：

- 三種 CLI 的格式差異被關在 parser 裡，CLI 升版只影響一個模組
- 指標定義改了可以**重算歷史**，不必重新解析原始檔
- aggregator 與 renderer 是純函數，好測

執行位置：k3s 節點 `openab` 上的 CronJob，用 `hostPath` 唯讀掛
`/data/william/openab`。PV 是 `local` 型、`nodeAffinity` 全部釘在該節點
（`deployment-guides/K3S.md` 第 2 步），所以一個 Pod 就能看到全部七隻，
不需要去搶 `ReadWriteOnce` 的 PVC。作法沿用既有的 `jira-grill-poller` 與
`agent-dev-poller`（同目錄 `cronjob.yaml` + 腳本）。

## 元件 1：正規化事件契約

刻意分成**兩條獨立的流**，不合併成單一 turn 事件。

理由：把 token 歸因到「某一個具體任務」需要一個「session 內 user 訊息與後續
assistant 用量的對應」假設，而三種格式都不保證這個順序關係（codex 的 usage 是
event 流、opencode 的 token 在另一張表）。硬做會產生看起來合理但無法驗證的數字。
三個用途實際需要的粒度是 (bot, 日期, model) 與 (bot, session, 日期)，不是 per-task。

**`task` 流**（一筆 = 一次觸發 agent 工作的平台訊息）

```json
{
  "schema": "openab.stats.task.v1",
  "bot": "rick",
  "cli": "claude-code",
  "platform": "discord",
  "dedup_key": "discord:1600000000000000001",
  "channel_id": "1528965074562191420",
  "thread_id": "1540292484611969084",
  "session_id": "28322078-f996-4db2-9541-5ef74f1a4a64",
  "sender_id": "824092654060830770",
  "sender_name": "wm4n",
  "display_name": "william",
  "source": "human",
  "occurred_at": "2026-09-10T06:32:10Z",
  "source_file": "…/-home-node/28322078-….jsonl",
  "source_offset": 12345
}
```

- `source` ∈ `human` | `bot_relay` | `cron`，依上節三分類。
- **觸發者維度**：`sender_id` 是穩定鍵，`sender_name`（Discord 全域帳號，實測
  `wm4n`）與 `display_name`（伺服器暱稱，實測 `william`）都會隨使用者改名而變，
  所以兩者都在事件發生當下存下來，聚合與去重一律以 `sender_id` 為準，名稱只用於
  顯示。報表顯示名稱時取該 `sender_id` **最近一次**出現的 `display_name`。
  `source == "cron"` 時 `sender_id` 固定為 `openab-cron`，不是真人。
- `dedup_key`：`message_id` 非空時用 `platform:message_id`；cron 觸發（`message_id`
  為空）時用 `platform:openab-cron:{thread_id}:{timestamp}`。**去重是必須的**——
  同一次任務會出現在多個路徑（實測 summer 74 筆只有 37 個 distinct）。
- `platform`：由 `thread_map.json` 的 key 前綴取得（`platform:thread_id`）；查不到
  時，`channel` 欄位值若為 `discord`／`slack` 則採用，否則記 `unknown`（**不可猜**）。
- `source_file` + `source_offset`：讓每個數字都能追回原始紀錄。統計被質疑時這是
  唯一的辯護方式。

**`usage` 流**（一筆 = 一次 API 呼叫的用量）

```json
{
  "schema": "openab.stats.usage.v1",
  "bot": "kimi",
  "cli": "opencode",
  "session_id": "ses_…",
  "model_id": "deepseek/deepseek-v4-pro-0813",
  "model_variant": "low",
  "occurred_at": "2026-09-10T06:33:01Z",
  "tokens": { "input": 120, "output": 45, "reasoning": 10,
              "cache_read": 8000, "cache_write": 300 },
  "cost": 0.0123,
  "cost_source": "cli",
  "origin": "main",
  "source_file": "…/opencode.db",
  "source_ref": "message:msg_a"
}
```

- `tokens` 五類**分開存，不加總**。單價差一個量級（cache read 通常是 input 的
  1/10），加總後就算不出錢。缺某一類時該欄位省略（**不可填 0**，見「資料完整性」）。
- `cost_source` ∈ `cli`（opencode 自己算好）| `pricebook`（我們用價目表算）|
  `subscription`（訂閱制，token 數不等於帳單）。Claude 家族是 `subscription`，
  這個標記不打上去，容量模型會算出假成本，比沒有數字更糟。
- `model_variant`：opencode 有；其他兩家記 `null`。
- `origin` ∈ `main` | `subagent`，後者對應 claude-code 的 `toolUseResult.usage`。
- `occurred_at` 的來源依 CLI 而異，parser 要寫明：claude-code 用該筆紀錄的
  `timestamp`；codex 用 `token_count` event 的 `timestamp`；opencode 用
  `message.time_created`（epoch millis，要轉 ISO 8601）。三者都是 CLI 端的本地時間，
  與 `task` 流的 `occurred_at`（平台時間，來自 `sender_context.timestamp`）**不是
  同一個時鐘**，跨流比對時只能到「日」的粒度，不可做秒級關聯。

價目表是**設定檔**，不寫死在程式裡。

## 元件 2：三個 parser

共同介面：吃一個 agent home 路徑 + 上次處理位置，吐 `task` 與 `usage` 兩串事件，
外加一份「解析健康度」（總紀錄數、不可解析數、遇到的未知欄位）。純函數化到可以
用固定樣本檔測試。

權威路徑與排除清單見「已驗證的資料源事實」，parser 必須把那些路徑**寫成明確的
白名單**，不可用鍵名比對（`re.search(r"token")` 這種做法會把診斷欄位和明細一起
撈進來——`verify-stats-sources.py` 就是刻意這樣做才發現這些坑的，但那是探查工具，
不是 parser）。

增量處理：以 (檔案路徑, offset) 記錄進度。transcript 是 append-only 但 CLI 可能
重寫（compaction），所以每次讀取前要驗證檔案前綴未變，變了就整檔重讀。opencode 的
SQLite 以 (表, 最大 `time_updated`) 當水位。

## 元件 3：aggregator — 四項指標定義

純函數：吃兩串正規化事件，吐每日指標。邊界條件才是重點。

**「每日」的定義**：一律以 **Asia/Taipei** 的日界線切分，兩條流都先轉成該時區再分
桶。`task` 流的時間是平台時間（Discord 給 UTC）、`usage` 流是 CLI 端本地時間，
兩者時鐘不同，若不明訂時區，兩份數字的日界線會不一致而無法對照。報表標頭要寫出
時區，否則跨時區的人會讀錯。

### 每日任務數

當日 distinct `dedup_key` 數，**按 `source` 分三欄**：`human` / `bot_relay` / `cron`。
三者不可合併成一個數字。

- 失敗的任務不在資料裡（見「已知限制」），所以這個數字是「成功任務數」，報表欄位
  名稱必須這樣寫。
- openab 有 batching（`dispatch.rs:300` 的 `BatchGrouping`），多則訊息可能併成一個
  turn、一筆紀錄裡帶多個 `sender_context`。實測目前七隻都是「單筆最多 1 個」
  （Rick/Morty 用 per-lane 模式），但 parser 仍必須逐個 `sender_context` 處理而非
  逐紀錄，否則改設定就會低估。

### 每日對話數

當日有活動的 distinct `session_id` 數，分「新開」（該 session 第一筆事件落在當日）
與「延續」兩欄。

`sessionTtlHours: 24`，跨日 session 會在兩天都被算進「有活動」——這是對的，但報表
必須註明「逐日加總會大於實際對話數」。

### Token 用量與成本

按 `(bot, cli, model_id, model_variant, token 類別)` 分組加總。

成本分三段呈現，依 `cost_source` 分開，**不可混加**：CLI 自算（opencode 三隻，
可直接信）、價目表推算（若有走 API 計費的 bot）、訂閱制（只呈現 token 量，明確標註
「非帳單金額」）。

**誰在燒量**：歸因到 **session 層**而非 task 層。一個 session 若只有一位真人
sender（實務上的常見情況），歸因無歧義；有多位時標為 `shared` 不強行拆分。報表要
顯示無歧義歸因的覆蓋率，否則讀者無法判斷這個數字可信到什麼程度。

### 每人任務數

按 `(bot, sender_id, 日期)` 分組計數，只算 `source == "human"`。這一項是精確的
（每筆任務都帶觸發者，無歧義），跟上面 token 的 session 層歸因不同——**任務數
by 誰是精確值，token by 誰是估計值**，報表不可讓兩者看起來同等可信。

同時輸出「每隻 bot 的活躍觸發者人數」（distinct `sender_id`），這是採用率報表的
核心數字之一。但要注意下面「已知限制」第 6 條：`allowedUsers` 非空的 bot，這個數字
的上界就是 allowlist 的長度，看到 1 不代表沒人想用。

### 摩擦指標（**不是滿意度**）

三個弱訊號，各自標明可信度，報表欄位名稱一律用「摩擦」不用「滿意」：

| 訊號 | 算法 | 可信度 |
| --- | --- | --- |
| 追問密度 | 同 session 同 sender 相鄰兩筆 `human` task 的時間差中位數，以及每 session 的 `human` task 數 | 中 |
| ~~否定詞命中~~ | ~~後續 `human` task 的訊息含「不對／重做」等~~ | **實作計畫已排除**：需要把使用者訊息內容擷取進事件檔（隱私成本），而它是三個訊號裡最弱的（「這段程式碼不對」是在講 code）。留下的兩個訊號只用時間戳與 session ID，事件檔完全不含對話內容。 |
| session 放棄 | session 有活動但無後續、且同 thread 短時間內另開新 session | 低 |

報表必須明寫「這不是滿意度量測」。要取得真正的滿意度需要明確評分機制（reaction 或
文字），已列為非目標；屆時明確評分的價值不只是它本身，而是能用來**校準**這些弱
訊號，讓它們取得代理資格。

### 失敗率的粗略代理

`thread_map.json` 的 entry 數（= 建立過 session 的 thread 數，`pool.rs:347-357` 在
`session/new` 成功後、送 prompt 之前就寫入）對比實際產出過 task 事件的 session 數。
落差 = 「開了 session 卻沒產出」的比例。

實測落差：morty 18 進 2 出、rick 33 進 26 出、genie 160 進 362 出（genie 超過是因為
一個 thread 多個任務，且 `persisted` entry 會在 eviction 時被移除）。

這只有 session 粒度、不是 turn 粒度，也無法區分「失敗」與「使用者只是 @ 了一下沒
下任務」。**定位是「揪出可疑 bot 的紅旗」，不是失敗率量測**，報表要這樣標。

## 元件 4：renderer 與交付形式

**收集與報表是兩件不同的事，時程也不同：**

- **收集必須自動定期跑**，因為原始資料會消失（見下節「保留期限」）。這是 CronJob
  的唯一職責——把原始儲存轉成正規化事件並累積起來。它不產報表。
- **報表隨時手動產生**，吃已累積的正規化事件，不碰原始儲存。所以報表可以重跑、
  可以改指標定義後重算歷史、可以指定任意日期範圍。

### 交付形式：一支 CLI，兩種輸出

使用者選定 CLI 工具 + 網頁儀表板。**兩者是同一支 CLI 的兩種輸出格式**，不是兩套
系統：

```bash
# 終端機直接看（預設）
report.py --since 2026-09-01 --until 2026-09-10

# 只看某幾隻
report.py --since 2026-09-01 --bots rick,morty

# 產 markdown（貼給人、進 git、或給 LLM 讀）
report.py --since 2026-09-01 --format md -o report.md

# 產網頁儀表板
report.py --since 2026-09-01 --format html -o report.html
```

HTML 輸出是**自帶所有資源的單一檔案**：inline CSS、圖表用程式直接產生的 inline
SVG，**零外部請求**（不連 CDN、不載外部字型、不 fetch）。所以：

- `open report.html` 就能看，**不需要 nginx 或任何靜態檔服務**
- 可以直接寄給人、丟進 Slack、或發佈成網頁而不會破圖
- 用 `prefers-color-scheme` 支援深淺色

圖表刻意用**程式產生 SVG** 而非 JS 圖表庫：自帶資源的要求下引入 JS 庫要整包 inline
（動輒數百 KB），而這裡需要的圖形（每日折線、堆疊柱狀、model 佔比）產生 SVG 的
程式碼比 inline 一個庫更短，而且**可以單元測試**（斷言 SVG 的 path 座標），
JS 庫渲染的結果測不到。

### 報表內容

每份報表開頭必須有「資料覆蓋率」區塊（見下節），以及一行標明時區
（Asia/Taipei）與資料保留期限警告。

頻道名稱查表：`channel_id` → 人類可讀名稱的對照表放設定檔，初始值取自
`deployment-guides/k3s/values-openab-*.yaml` 的註解。

`allowedUsers` 非空的 bot 必須標註人數上界（見「已知限制」第 6 條）。

### 保留期限：為什麼收集不能等到要報表時才做

原始資料不是永久的。Claude Code 有 transcript 保留期限設定
（`cleanupPeriodDays`，預設 30 天），compaction 也會重寫檔案。實測的可回溯起日
與這個推論一致：

| bot | CLI | 可回溯起日 | 距 2026-09-11 |
| --- | --- | --- | --- |
| genie | claude-code | 2026-08-11 | **31 天** |
| rick／morty | claude-code | 2026-08-18 | 24 天 |
| summer | codex | 2026-07-21 | 52 天 |

genie 卡在 31 天而 codex 那隻有 52 天，**符合「claude-code 在 30 天砍舊
transcript、codex 不砍」的模式**。若成立，現在看到的「1 個月歷史」是滾動窗口，
每過一天就少一天最舊的。

**待驗證**（實作第一步就要做，因為它決定要多快上線收集器）：

```bash
sudo grep -o '"cleanupPeriodDays":[0-9]*' /data/william/openab/agent-*/.claude/settings.json
```

有設定值就確認了；沒有設定則是走預設 30 天。不論結果如何，收集器都要定期跑——
差別只在「有多急」。**若 30 天成立，那容量模型能用的歷史上限就是 30 天，而不是
我先前說的「1 到 2 個月」**，那句話要在報表與 spec 裡修正。

## 資料完整性與錯誤處理

這節是統計系統成敗關鍵，四條都是硬要求：

1. **未知格式不可靜默跳過。** parser 遇到解析不了的紀錄要計數並顯示在報表上。CLI
   升版改格式是必然（image 現在釘 `claude-cli2.1.220`，總會升）。
   `verify-stats-sources.py` 保留為常備的格式漂移偵測工具。
2. **「不支援」與「0」必須可區分。** 每個指標都要能表達「此來源無此資料」，不可
   退化成 0。這是 Google Chat reaction 那個教訓的一般化——靜默回 `Ok(())` 會讓
   「0 票」被誤讀成「大家沒意見」。
3. **報表必須顯示資料覆蓋率。** pod 重建、PV 掛載失敗、CronJob 沒跑都會造成缺口，
   不能讓缺口偽裝成「那天沒人用」。
4. **增量處理要驗證檔案前綴**（見元件 2）。

寫入位置：正規化事件與指標 DB 寫**獨立的小 PVC**，不可寫回 agent 的 PVC——避免污染
agent 的 HOME，也避免統計程式持有 agent 家目錄的寫入權限。

## 需要變更的檔案清單

| 檔案 | 動作 |
| --- | --- |
| `deployment-guides/k3s/usage-stats/collect.py` | 新增：parser × 3 + 增量水位。**CronJob 跑的就是這支**，只收集不產報表 |
| `deployment-guides/k3s/usage-stats/aggregate.py` | 新增：指標計算（純函數） |
| `deployment-guides/k3s/usage-stats/report.py` | 新增：**使用者手動跑的 CLI**。`--since`／`--until`／`--bots`／`--format {text,md,html}`／`-o` |
| `deployment-guides/k3s/usage-stats/render_html.py` | 新增：自帶資源的單一 HTML（inline CSS + 程式產生的 inline SVG，零外部請求） |
| `deployment-guides/k3s/usage-stats/config.example.json` | 新增：價目表、頻道名對照、allowlist 人數上界。**JSON 不是 TOML** —— `tomllib` 要 Python 3.11+，而節點與容器版本未知 |
| `deployment-guides/k3s/usage-stats/cronjob.yaml` | 新增：CronJob + hostPath 唯讀掛 `/data/william/openab` + 獨立 PVC（沿用 `jira-grill-poller` 形式） |
| `deployment-guides/k3s/usage-stats/tests/` | 新增：三份去識別化樣本 fixture + 邊界案例 + SVG 座標斷言 |
| `deployment-guides/k3s/README.md` | 更新：檔案表與安裝節錄 |
| `deployment-guides/K3S.md` | 更新：新增 CronJob 的部署步驟與靜態 PV |

## 測試／驗收方式

- **parser**：三份真實樣本（從節點抓下來去識別化）當 fixture，逐欄位斷言。必須
  包含各家的陷阱案例：claude-code 的 `iterations[]`／`cache_creation`／
  `toolUseResult.usage`、codex 的 `total_token_usage` 累積、opencode 的 `part`／
  `event` 重複與 JSON 形式 `session.model`。
- **aggregator**：手工構造事件序列，涵蓋 batching 多 `sender_context`、跨日
  session、跨 model turn、cron 事件無 `message_id`、多 sender 的 session。
- **端對端**：拿一天真實資料跑，**人工對照 Discord 頻道實際訊息數**確認任務數
  對得上。這步不能省——統計系統最常見的失敗模式是「跑得很順、數字全錯」，而且
  錯了沒人發現。
- **回歸基準**：把 `verify-stats-sources.py` 對七隻的 token 加總當成上界檢查
  （parser 算出的絕不該超過探查工具看到的權威路徑總和）。

## 已知限制

1. **失敗的任務在 transcript 裡完全隱形，任務數系統性低估，而低估的正是最該被看見
   的部分。** 錯誤只丟給聊天平台（`error_display.rs` 的 docstring：`Format any error
   for user display in Discord`），不進結構化 log。使用者已確認第一版接受用
   `thread_map` 落差當粗略代理並明確標註限制。根治要嘛加 Discord 側資料源（那一項
   指標會變成平台相依，上 Google Chat 時要重做），要嘛上游 PR 讓 openab 記錄 turn
   結果（平台無關、對上游是通用功能，但時程拉長）。
2. **摩擦指標不是滿意度。** 三個訊號都弱，否定詞那項誤判率尤其高。
3. **平台維度依賴 `thread_map.json`。** `sender_context.channel` 在 gateway 平台
   （含 Google Chat）給的是 channel_type 而非平台名。若 `thread_map` 查不到就記
   `unknown`。
4. **可回溯的歷史比想像中短，而且是滾動窗口。** opencode 三隻只到 2026-09-10
   （剛部署）。claude-code 三隻疑似受 30 天保留期限限制（genie 卡在 31 天，見元件 4
   的「保留期限」），若成立則**歷史上限就是 30 天、每天少一天**，容量模型的校準
   樣本會比預期小很多；只有 codex（最早 2026-07-21，52 天）看起來不受限。這使得
   「盡快上線收集器」從優化變成**時效問題**——現在不收，最舊的資料每天在消失。
   實作第一步就要跑那條 `cleanupPeriodDays` 檢查確認。
5. **`toolUseResult.usage` 的判定基於 `isSidechain` 全為 `false` 的觀察。** 若
   Claude Code 未來改成把 subagent 訊息寫進同一份 transcript，這條會變成重複計算。
   量級約 0.1%，但格式漂移偵測要涵蓋這個欄位。
6. **rick／morty 目前只有一位真人能觸發，所以「活躍使用者數」在這兩隻身上會恆為
   1，不是採用率低。** `values-openab-claude.yaml:48` 與 `:100` 的
   `allowedUsers: ["824092654060830770"]` 是硬性閘門——`discord.rs:2194` 的
   `is_denied_user` 對非 bot 一律要求列在 allowlist 裡，而 `allowedRoleIds`
   （`discord.rs:453-459`）只影響「能不能用角色 mention 觸發」，**不會放寬准入**。
   所以有 CAC-Builder 角色的人 @ 該角色，rick 會認得是 mention，但仍會被 user
   allowlist 擋掉。genie／summer／kimi／walle／eve 的 `allowedUsers` 為空（= 頻道
   內任何人），這幾隻的人數維度才有意義。要對 rick／morty 取得有意義的 per-user
   統計，前提是先清空 `allowedUsers`——那是部署決策不是統計功能，故列為限制。
   報表在 allowlist 非空時必須標註「此 bot 受 allowlist 限制，人數上界為 N」，
   不可讓 1 被讀成「沒人用」。
7. **morty 的 18 進 2 出尚未確認根因。** 已知 `thread_map` 在 `session/new` 後即
   寫入，所以落差代表「開了 session 沒產出」，但究竟是 API 失敗（如 upstream 容量
   事件）、prompt 未送達、或使用者只是 @ 了一下，需要另外查 Discord 歷史或
   `kubectl logs` 才能區分。
