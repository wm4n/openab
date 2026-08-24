# Rick 裝載 grill-me、透過 Jira 觸發 設計文件

- 日期:2026-08-24
- 狀態:設計已定案,待使用者複審 spec 全文
- 範圍:在 Rick 身上新增一條獨立能力——Jira 票貼上特定 label 後,Rick 用
  `mattpocock-skills:grilling` 的方法論審視需求,把提問/回答的媒介換成
  Jira comment,並靠 openab 既有的 usercron + Discord thread↔ACP session
  機制做到「同一張票的問答落在同一個 session」。
- 語言:繁體中文
- 與三 bot pipeline(Morty 規格 → Rick 開發 → Summer 複審)的關係:**完全獨立**,
  不取代、不整合 Morty 現有的 JIRA 需求分析角色(`requirement-analysis`
  skill 角色 B1)。兩者並存,依觸發方式各自運作。

## 目標

讓 Rick 能夠:

1. 偵測到 Jira 票被貼上 `grill-me` label。
2. 讀取票的內容,用 grilling 方法論(design tree / frontier / 分輪提問)
   對需求提出連續追問。
3. 把每一輪問題貼回該 Jira 票的 comment(而不是問活著的使用者)。
4. 之後只要該票有新留言,就在**同一個 session**(同一個 Discord thread、
   同一個 ACP session)接續處理這則回覆、判斷是否需要下一輪提問。
5. Design tree 的 frontier 清空(雙方達成需求共識)後,貼一則結構化的
   「需求共識」comment、通知人類,然後停手——不自動進開發、不自動交棒
   給任何 bot。

## 非目標(YAGNI)

- 不建原生 Jira webhook gateway adapter(`crates/openab-gateway` 的
  Rust 新 adapter)。純 polling(usercron)已足夠滿足「新留言接續同一
  session」的需求,且零核心程式碼改動。這條路留給 ADR
  `docs/adr/custom-gateway.md` 所規劃的 v3+(該 ADR 與
  `docs/github-webhook-integration.md` 都已把 Jira 列為未來候選)。
- 不做 Jira 帳號 → Discord 帳號的身份對應與跨平台 @ 通知;通知一律走
  Jira comment 內的 @ 提及。
- 不取代/修改 Morty 既有的 JIRA 需求分析角色(`requirement-analysis`
  skill 角色 B1),兩套流程各自獨立、互不干擾。
- Frontier 清空後不自動進 Rick 的 PR 開發模式,也不自動 @ Morty——停在
  「達成共識、通知人類」為止,下一步交給人類決定。
- 不設計輪數/逾時上限——每輪附進度摘要,人類隨時可用文字或改 label
  中止。

## 架構總覽

```
[Jira] --貼上 grill-me label-->
                                  │
                    ┌─────────────▼─────────────────────────┐
                    │  Discovery cron job(單一、固定 thread)  │
                    │  排程:每 10 分鐘                        │
                    │  動作:JQL 找「新貼 grill-me 且尚未       │
                    │        grill-me-active」的票            │
                    └─────────────┬─────────────────────────┘
                                  │ 找到新票
                                  ▼
                    label: grill-me → grill-me-active
                    建立「該票專屬」cron job
                    (獨一無二的 id/thread_id → 獨一無二的 ACP session)
                                  │
                    ┌─────────────▼─────────────────────────┐
                    │  Per-ticket cron job                    │
                    │  排程:每 10 分鐘                        │
                    │  動作:                                  │
                    │   1. jira-fetch 抓最新內容 + 全部留言    │
                    │   2. 比對「Rick 上次留言」之後有沒有      │
                    │      新留言(或人類喊停 / label 被改掉) │
                    │   3a. 沒有 → no-op                       │
                    │   3b. 有 → 依 grilling 方法論算下一輪     │
                    │       frontier,貼 comment 提問+進度摘要  │
                    │   3c. frontier 清空 → 貼「需求共識」      │
                    │       comment、@ 通知人類、label 改成     │
                    │       grill-me-done、停用/刪除本 job      │
                    └─────────────────────────────────────────┘
```

**關鍵技術事實**(已在 codebase 查證,非推測):

- `crates/openab-core/src/adapter.rs`:`thread_key = "{platform}:{thread_id
  or channel_id}"`,`self.pool.get_or_create(&thread_key, ...)` 決定
  ACP session 歸屬;同一 `thread_key` = 同一個 session。
- `crates/openab-core/src/acp/pool.rs`:session 會持久化到
  `~/.openab/thread_map.json`,連 process 重啟都能靠 `session/load` 復原。
- `crates/openab-core/src/cron.rs:726`:cron 觸發時呼叫的是
  `AdapterRouter::handle_message`,帶入 `job.thread_id`——與人類發訊息
  走**同一條路徑**,所以同一個 cron job 重複觸發必然落在同一個
  thread、延續同一個 session。`deployment-guides/bot-skills/
  openab-schedule/SKILL.md` 也證實「repeated fires of the same job land
  in the same thread」。
- 因此「每張 Jira 票一個獨立 cron job」= 「每張 Jira 票一個獨立、可長期
  接續的 ACP session」,不需要任何核心程式碼改動,純粹是 `cronjob.toml`
  的設定資料。

**設計原則:Jira 是唯一真相來源**。每次觸發都重新從 Jira 撈完整 ticket +
留言串來判斷目前進度與 frontier 狀態,不依賴 session 記憶本身的正確性。
Session 延續只是效率上的紅利(model 不用每次都重新從零推導已經問過什麼),
即使某次 session 因壓縮或其他原因遺失早期上下文,重新讀一次 Jira comment
串仍然能正確接續,不會產生錯誤行為。

## Grilling 方法論的媒介轉換

`mattpocock-skills:grilling` 原始設計是「對活著的使用者連續發問,一輪一輪
問答,frontier 清空才結束」。本設計把提問/回答的媒介從即時對話換成 Jira
comment:

- **提問格式**:沿用 grilling 的 `❓ **Q1** - **<標題>**: <內容>` +
  `➡️ <建議答案>` 格式,貼在同一則 Jira comment 裡(一輪的所有 frontier
  問題合併成一則 comment,而不是分開多則)。
- **進度摘要**:每則提問 comment 結尾附上「目前還有 N 個分支未決」,對應
  使用者選擇的「不設死上限,但每輪摘要進度」。
- **判斷新回覆**:比對留言串中 Rick 自己最後一則 comment 之後,是否有
  其他作者的新 comment。沒有 → 本次觸發 no-op(不呼叫任何 LLM 推理以外的
  動作,輸出盡量精簡以控制成本)。有 → 視為對上一輪 frontier 的回答,重新
  計算 design tree、決定下一輪 frontier。
- **中止訊號**:人類在 comment 內用文字明確喊停(例如「先這樣」「夠了」
  「stop」等意思相近的表達),或把 `grill-me-active` label 拿掉/改掉,
  Rick 都要辨識為中止訊號,優雅收尾(比照「收斂」流程處理,但註明是
  「人類中止」而非「自然收斂」)。
- **收斂**:frontier 真的清空(每個分支都有明確答案,沒有懸而未決的追問)
  時,貼一則「✅ 需求共識」comment,把整輪問答蒸餾成結構化的最終需求
  描述,簽署「— By Rick」,@ 提及該票的 reporter 與 assignee,並把 label
  從 `grill-me-active` 改成 `grill-me-done`。
- **收斂後動作**:僅止於上述通知,不自動進 PR 開發模式、不自動 @ Morty。
  同時停用(或直接刪除)該票專屬的 cron job entry,避免無意義的持續輪詢。

## Discovery 與 Per-ticket Job 的生命週期

### Discovery job(單一、常駐)

- `id`:固定,例如 `jira-grill-discovery`。
- `schedule`:每 10 分鐘(`*/10 * * * *`)。
- `channel`/`thread_id`:固定在 Rick 既有的工作頻道,第一次觸發自動開新
  thread,之後每次都落在同一 thread——這個 thread 純粹是 discovery
  job 自己的容器,人類不需要去看它。
- `message`(自包含指令,因為每次觸發都是全新 prompt):用 JQL 搜尋
  `project IN (CACJOB,CACVIP,CACATS) AND labels = grill-me AND labels !=
  grill-me-active`(2026-08-24 更正:範圍限定在
  `JIRA_GRILL_PROJECTS` 環境變數指定的 project key 白名單,不掃 Jira
  帳號能存取的其他專案,避免跨專案的 grill-me label 誤觸發)。找到的每
  一張票:
  1. 把 label 從 `grill-me` 換成 `grill-me-active`(避免下次 discovery
     重複撿到)。
  2. 立刻讀該票內容,跑第一輪 grilling,直接貼出第一輪提問 comment
     (不用等 per-ticket job 的第一次觸發)。
  3. 在 `~/.openab/cronjob.toml` 新增一個該票專屬的 `[[jobs]]` entry
     (見下)。

### Per-ticket job(動態建立/刪除,每票一個)

- `id`:`jira-grill-<TICKET_KEY>`(例如 `jira-grill-CACJOB-12345`),
  確保唯一、可被 discovery job 或 Rick 本人依 id 找到並管理。
- `schedule`:每 10 分鐘。
- `channel`:同 discovery job 的固定頻道;`thread_id` 留給 scheduler 在
  第一次觸發時自動建立新 thread 並回寫,之後每次觸發都落在該 thread、
  延續同一個 ACP session。
- `message`(自包含指令):「去查 Jira 票 `<TICKET_KEY>`,抓最新內容與
  全部留言,依 grill-me 規則判斷:(a) 沒有新留言 → 不動作;(b) 有新留言
  → 依 grilling 方法論計算下一輪 frontier 並貼 comment 提問;(c) 偵測到
  人類中止訊號或 frontier 已清空 → 貼收斂/中止 comment、改 label、然後
  把 `~/.openab/cronjob.toml` 裡 id 為 `jira-grill-<TICKET_KEY>` 的
  job 刪除或 `enabled = false`。」
- 收斂/中止後即自我清理,不留下常駐但用不到的 job。

## 需要的基礎設施/設定變更

> **2026-08-24 複查更正**:寫作當下直接讀取現行 `values-openab-claude.yaml`
> 與 `deployment-guides/k3s/update-skills.sh`,發現先前(由 subagent 回報)
> 認定「Rick 沒有 cron、沒有 jira-fetch/openab-schedule」的說法有誤,已在
> 下方修正為實際查證結果,並補上「skill 真正的真相來源在哪」這個先前完全
> 沒發現的關鍵事實。

1. **Rick 加裝 JIRA 認證**:`deployment-guides/k3s/values-openab-claude.yaml`
   的 Rick 區塊(第 23–53 行)目前確實沒有任何 `secretEnv`,需比照
   Morty/Genie 加上:
   ```yaml
   secretEnv:
     - { name: JIRA_TOKEN, secretName: morty-jira, secretKey: JIRA_TOKEN }
     - { name: JIRA_BASE_URL, secretName: morty-jira, secretKey: JIRA_BASE_URL }
     - { name: JIRA_EMAIL, secretName: morty-jira, secretKey: JIRA_EMAIL }
   ```
   直接複用既有 `morty-jira` K8s Secret(namespace `cac` 內任何 Deployment
   都能引用同一個 Secret,不受名稱裡的「morty」字樣限制),不新建 Secret。
2. ~~Rick 開通 usercron~~ **已不需要**:直接讀檔確認 Rick 的 values 區塊
   (第 44–46 行)**已經有** `cron: usercronEnabled: true` /
   `usercronPath: "cronjob.toml"`,無需任何變更。
3. ~~裝 jira-fetch skill 給 Rick~~ **已不需要**:`deployment-guides/k3s/
   update-skills.sh` 的註解明確記載「2026-07-24 決定:skill-registry
   plugin(jira-fetch/learn-from-repo/self-evolution)四隻都裝,不再只給
   Morty」,腳本第 62–63 行也對 Rick 執行
   `claude plugin install/update skill-registry@wm4n-skill-registry`。
   Rick 已經能用 `jira-fetch` skill。
4. ~~裝 openab-schedule skill 給 Rick~~ **已不需要**:`openab-schedule`
   實際上被打包在 **`openab-bot-skills`** plugin(`wm4n/skill-registry`
   repo,`plugins/openab-bot-skills/skills/openab-schedule/`)裡。
   `update-skills.sh` 第 60 行對 Rick 執行
   `claude plugin update openab-bot-skills@wm4n-skill-registry`——這是
   **update** 不是 **install**,代表 Rick 早就裝好這個 plugin 了。
5. **⚠️ 關鍵事實(先前完全遺漏)：skill 內容的真相來源不在這個
   `openab` repo**。`deployment-guides/bot-skills/openab-schedule/
   SKILL.md` 這份檔案只是歷史沿革下的參考副本,`BOT_SETUP.md` Part K2b
   已白紙黑字寫明「改 `deployment-guides/bot-skills/` 裡的檔案不再有
   作用(那份 clone 已經不是真相來源)」。真正生效的內容在本機已有
   clone 的 **`wm4n/skill-registry`** repo(路徑
   `/Users/william.chao/workspace/github/skill-registry`)裡的
   `plugins/openab-bot-skills/skills/`,新 skill 要寫在這裡、bump
   `plugins/openab-bot-skills/.claude-plugin/plugin.json` 與根目錄
   `.claude-plugin/marketplace.json` 對應 plugin 條目的 `version`、
   push 後,再對 Rick 的 pod 執行 `claude plugin marketplace update` +
   `claude plugin update openab-bot-skills@wm4n-skill-registry` 才會
   生效。**這個 repo 屬於 `wm4n/*`,commit/push 一律用 wm4n GitHub 帳號**
   (現有慣例,見 `[[feedback-github-account-per-repo]]`)。
6. **新增 `jira-grill` skill**:寫在 `wm4n/skill-registry` repo 的
   `plugins/openab-bot-skills/skills/jira-grill/SKILL.md`(加入既有的
   `openab-bot-skills` plugin,不另開新 plugin——Rick 已裝這個 plugin,
   不需要多一道 `plugin install`),把上面 discovery job 建立、
   per-ticket job 動態建立/刪除、grilling 提問邏輯、收斂/中止處理、
   label 狀態機,寫成可執行的 SOP,格式比照同目錄下現有
   `openab-schedule`/`jira-fetch`(`skills/jira-fetch/SKILL.md`,
   `skill-registry` plugin)兩支 skill 的寫法慣例(node 解析 JSON、
   `curl -u email:token` Basic Auth,不假設 `jq`/`python3`/GNU-only
   coreutils 存在)。
7. **`Rick-CLAUDE_v2.md`** 加一段指向這支新 skill 的入口說明,並註明
   這是獨立於三 bot pipeline 之外的用途,鐵則(worktree 隔離、絕不
   merge/approve 等)不受影響、原樣適用。此檔在 `openab` repo,屬於
   `wm4n/openab`(fork),commit/push 沿用目前這個 repo 既有的帳號慣例。
8. 依既有慣例(見 `[[memory]] BOT_SETUP.md 同步指令`)同步更新
   `deployment-guides/BOT_SETUP.md` runbook,把上述 1、5–7 步驟(2–4
   已確認不需要)納入 Rick 的建置流程。
9. **`openab-schedule` 的「先跟人類確認卡片」流程不適用於本設計的自動
   建 job**:discovery job 是無人在場的自動觸發,`jira-grill` skill 建立
   /刪除 per-ticket cron job entry 時直接讀寫 `~/.openab/cronjob.toml`
   (語法沿用 `openab-schedule` 的 `[[jobs]]` 慣例),**不**套用該 skill
   文件裡「resolve 每個欄位→貼摘要卡→等人類確認」那段流程——那是給
   人類即時對話請求排程時的 UX,人類已透過本 spec 的核准,等同一次性
   授權這套自動建立/清理 job 的行為。

## 環境變數彙整(Rick 新增)

| 變數 | 用途 | 必要性 |
|------|------|--------|
| `JIRA_TOKEN` | Jira REST API 認證(讀票、貼 comment、改 label) | 必要 |
| `JIRA_BASE_URL` | Jira 實例網址 | 必要 |
| `JIRA_EMAIL` | Jira 帳號 email(Basic Auth 用) | 必要 |
| `JIRA_GRILL_CHANNEL` | discovery job 建立 per-ticket cron job 時要指定的 Discord channel ID(Rick 既有頻道,非 secret,走 `env` 不走 `secretEnv`) | 必要 |
| `JIRA_GRILL_PROJECTS` | discovery 只掃這些 Jira project key(逗號分隔,如 `CACJOB,CACVIP,CACATS`),非 secret,走 `env` | 必要 |

## 預設細節(可 override)

- 觸發 label 名稱:`grill-me` → 進行中 `grill-me-active` → 完成
  `grill-me-done`。
- Discovery JQL 掃描範圍:**2026-08-24 更正**,限定
  `JIRA_GRILL_PROJECTS` 指定的 project key 白名單(目前
  `CACJOB,CACVIP,CACATS`),不掃 Jira 帳號能存取的其他專案——原始設計
  「不限定特定 project key」已改掉,避免跨專案的 grill-me label 誤觸發。
- 輪詢間隔:discovery job 與各票的 per-ticket job 皆為 10 分鐘。
- 通知方式:僅透過 Jira comment 內 @ 提及 reporter/assignee,不額外發
  Discord 通知(Discord thread 在此設計中純粹是 session 容器,人類不需
  要去看)。

## 已知限制

- **成本隨並行票數線性增加**:每張正在 grill 的票都各自每 10 分鐘觸發
  一次 LLM 推理(即使多數時候是「沒有新留言→no-op」),若同時有大量票在
  跑,累積的 Claude 用量會明顯增加。目前無自動節流機制,仰賴輪詢間隔
  本身與 label 狀態機把「不再需要輪詢的票」盡快踢出清單。
- **中止訊號辨識靠語意判斷**,不是精確的關鍵字比對,極端措辭可能誤判
  ——但收斂/中止都會留下明確的 Jira comment 記錄,人類事後可查、可
  用 label 手動介入。
- **JQL/label 慣例依賴 Jira 實例設定**:若組織的 label 使用慣例、
  Jira 帳號權限範圍與本設計假設不同,discovery 的 JQL 需要對應調整。
- **cron 觸發有 overlap protection**:若某次 per-ticket 觸發耗時超過下
  一次排程間隔,scheduler 會跳過重疊的那一次,不會並行執行同一個 job
  ——這是既有機制的限制,非本設計新增。
- **沒有 Jira 帳號 → Discord 帳號的通知對應**:v1 刻意不做(YAGNI),
  收斂通知完全走 Jira 端。
