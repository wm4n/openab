# Genie 具備 jira-grill 能力、依 Jira 票 label 決定開發模式：設計文件

- 日期：2026-09-08
- 狀態：設計已定案（brainstorming 對話中逐項確認），待使用者複審 spec 全文
- 範圍：讓 genie 也能執行 `jira-grill`（Rick 現有的規格 grilling 能力），
  並讓 genie 在被要求處理一張具體 Jira 票時，依這張票**目前的 label**
  決定要走哪條開發模式——不用再靠人類在對話裡明講「這次要不要全自動」。
  順帶把 `jira-grill` skill 本身兩處寫死給 Rick 用的邏輯（帳號選擇、
  簽名格式）改成可以讓多個 bot 共用。
- 語言：繁體中文
- 前置作業（已完成，不在本文件重複）：`jira-grill` 已從
  `openab-bot-skills` 搬到 `solo-bot-skills` plugin（`wm4n/skill-registry`
  commit `ebc6e8d`），讓 genie 不用連帶裝進只有接力型 bot 用得到的 relay
  skill 就能拿到這支 skill。
- 與「Rick/Morty/Summer 通用化」的關係：使用者同時提出把 Rick/Morty/
  Summer 也改造成像 genie 一樣的通用型 bot，但那牽涉到打散現行三 bot
  接力架構，範圍與本文件不同、且依賴本文件先把 genie 這邊的路由模型定
  案，**故意拆成獨立的下一輪 brainstorming**，不在本文件涵蓋。

## 背景與目標

Genie 目前的模式判斷（`Genie-CLAUDE_v2.md` 第 4 節）完全靠對話語氣：
人類沒特別說，就當「一般模式」（資深工程師模式，問答/除錯/隨手改
code）；人類明確要求「整個交給你」，才切換「全自動開發模式」
（`solo-feature-pipeline`）。另外還有一條完全獨立、只能被
`agent-dev-poller` 自動觸發的「Auto Dev Pipeline」（`ready-for-agent-dev`
label）。

這次要新增的是：當人類要求 genie 處理一張**具體 Jira 票**時，genie 應該
先看這張票**目前的 label**，而不是只靠對話語氣猜：

1. 有 `ready-for-agent-dev` → 視同已經被判斷「規格完整、可以直接動手」，
   不管是不是 poller 觸發的，都直接走「Auto Dev Pipeline」，跳過確認
   閘門。
2. 有 `grill-me`（或 `grill-me-active`）→ 這張票還在規格審視階段，走新
   增的「Jira Grill」模式（呼叫 `jira-grill` skill，跟 Rick 現行行為
   一致：先問規格類問題、達成共識才問工程類問題）。
3. 都沒有（或只有 `grill-me-done`/`agent-dev-active`/`agent-dev-done`/
   `agent-dev-failed` 這類收尾/在途 label）→ 維持現行行為不變，依對話
   語氣判斷一般模式或全自動模式。

## 非目標（YAGNI，brainstorming 過程中逐一排除）

- **不新增掃描「無 label」新票的 poller**：無 label 分支只發生在人類
  手動 @mention genie、明確提到某張票的時候，genie 才順便去看這張票
  現在的 label——不主動、批次地把整個 project 裡沒人管的票都吃下去。
- **不做 grill-me 的雙 bot 同時觸發**：`jira-grill-poller` 一次只
  mention 一個目標 bot（見下方），不是 Rick、genie 都 mention、誰先回
  應誰接手。
- **jira-grill 收斂邏輯本身不變**：使用者確認過，`grill-me-done` 之後
  要不要換成 `ready-for-agent-dev`，這一步**維持人類手動決定**，不新增
  自動改標的機制——這件事以為要新增，追問後發現其實就是現行行為
  （`grill-me-done` 本身就是「等人類決定」的意思）。
- **repo-identity 不搬家、不重複實作**：不把 `repo-identity` 複製一份
  到 `solo-bot-skills`，也不讓 genie 額外去裝 `openab-bot-skills`——用
  下方「帳號選擇改走 persona 優先」解決，維持單一真相來源。

## 架構總覽

```
人類在 Discord @mention genie，提到一張具體 Jira 票
   │
   ▼
genie：先用 jira-fetch 撈這張票目前的 labels
   │
   ├─ ready-for-agent-dev ──────────────▶ 4a. Auto Dev Pipeline（不變）
   ├─ grill-me / grill-me-active ───────▶ 4b. Jira Grill（新增，呼叫 jira-grill skill）
   └─ 其他（含空、grill-me-done、
           agent-dev-active/done/failed）▶ 現行「一般模式／全自動開發模式」判斷（不變）

獨立於上面這條之外：
jira-grill-poller（K8s CronJob）── 依 GRILL_TARGET_BOT 設定 mention Rick 或 genie（預設 Rick，本次不切換）
```

`jira-grill` skill 本身被 Rick 與 genie 共用，內部兩處寫死給 Rick 的邏輯
（帳號選擇、簽名）改成參數化，兩隻 bot 各自呼叫時代入自己的身份。

## 元件 1：Genie persona 路由規則（`deployment-guides/Genie-CLAUDE_v2.md`）

在第 4 節「技能模式切換」前面插入一段判斷邏輯：

> 當人類要求你處理的對象是一張具體 Jira 票（訊息裡明確提到票號）時，
> 先用 `jira-fetch <TICKET_ID>` 撈這張票目前的 labels，再決定模式：
> - 含 `ready-for-agent-dev` → 視同被自動觸發，直接進「4a. Auto Dev
>   Pipeline」，不需要人類額外確認（即使這次是人類手動提到票號，不是
>   `agent-dev-poller` 觸發）。
> - 含 `grill-me` 或 `grill-me-active` → 進「4b. Jira Grill」。
> - 其餘情況（無相關 label、或只有 `grill-me-done`/`agent-dev-active`/
>   `agent-dev-done`/`agent-dev-failed` 這類收尾/在途 label）→ 維持現行
>   判斷方式，依對話語氣決定一般模式或全自動開發模式。

新增「4b. Jira Grill」小節（結構比照 Rick-CLAUDE_v2.md 的「4a. Jira
Grill」），內容重點：

- 指向 `jira-grill` skill，說明用法與 `$ARGUMENTS = ticket <TICKET_ID>`
  格式一致。
- 明確註記目前的觸發現況：`jira-grill-poller` 預設仍只自動 mention
  Rick，genie 這條路目前**只能靠人類手動 @mention 明確要求**才會進入
  （例如「Genie，執行 jira-grill skill，參數：ticket CACJOB-123」，或
  依上方路由規則、人類提到一張帶 `grill-me` label 的票時）。若之後把
  `GRILL_TARGET_BOT` 切成 `genie`，這條路才會被 poller 自動觸發，屆時
  不需要再改這一節。
- 引用 104corp 固定帳號規則（見元件 2），說明 genie 執行 `jira-grill`
  時不需要、也不會呼叫 `repo-identity`。

## 元件 2：`jira-grill` SKILL.md 改動（`wm4n/skill-registry`，`plugins/solo-bot-skills/skills/jira-grill/SKILL.md`）

### 2a. 帳號選擇改走「persona 優先」

現行「Repo 解析與準備」段落的「repo 一旦確定，立刻準備」小節，第一步
「用 `repo-identity` skill 依 owner 選 GitHub 帳號」改寫為：

> 1. 先看目前執行的 persona（`{home}/CLAUDE.md`/`AGENTS.md`）有沒有為
>    這個 repo owner 定義**固定帳號規則**（例如 Genie 的「104corp 固定
>    用 104cac 帳號」）——有就直接套用、`gh auth switch` 到該帳號，不呼叫
>    `repo-identity`。
> 2. 沒有固定規則可套用 → 用 `repo-identity` skill 依 owner 選帳號（Rick/
>    Morty 現行方式不變）。

這樣 `jira-grill` 不必假設自己一定裝了 `repo-identity`，也不用複製一份
帳號選擇邏輯——固定帳號規則本來就已經寫在各 bot 自己的 persona 檔裡，
這裡只是「先問過 persona 有沒有現成答案」。

### 2b. 簽名參數化

所有出現 `— By Rick (jira-grill)` 字面值的地方（提問格式範例、階段轉換
里程碑格式、步驟 3「重複觸發防護」判斷邏輯、已知限制段落的說明文字），
改成 `— By {實際執行的 bot 名稱}（jira-grill）`——執行時代入當下 bot 的
名稱（Rick 執行時寫 `Rick`，genie 執行時寫 `Genie`）。

「重複觸發防護」（步驟 3）的判斷邏輯從「留言是否含 `— By Rick
(jira-grill)`」改成「留言是否含**自己**的簽名（當前執行 bot 的名稱）」
——判斷「這是不是我自己剛貼的」，不是寫死比對 Rick。

「已知限制」段落原本說「Rick 用人類帳號回覆 Jira，判斷是否自己剛貼的
一律靠文字簽名」，改寫為「各 bot 用各自的 GitHub 帳號回覆 Jira（Rick/
Morty 依 `repo-identity` 切換、genie 固定用 104cac），判斷是否自己剛
貼的一律靠文字簽名，不是帳號身份」。

### 2c. Frontmatter description

更新 description，拿掉隱含「只給 Rick 用」的措辭，改成中性描述（不指名
特定 bot）。

## 元件 3：`jira-grill-poller` 改成可設定目標 bot

`deployment-guides/k3s/jira-grill-poller/poller.sh` 與 `cronjob.yaml`：

- 新增環境變數 `GRILL_TARGET_BOT`（允許值 `rick` / `genie`），**預設
  `rick`**——這次上線後行為不變，之後想切換只改這個設定值。
- 新增環境變數 `GENIE_DISCORD_USER_ID`（沿用 `agent-dev-poller` 已經在
  用的同一個數值），跟既有 `RICK_DISCORD_USER_ID` 並列。
- `poller.sh` 依 `GRILL_TARGET_BOT` 決定兩件事：
  1. `trigger_discord()` 裡要 `<@...>` mention 的 Discord user ID
     （`rick` → `RICK_DISCORD_USER_ID`，`genie` → `GENIE_DISCORD_USER_ID`）。
  2. Query 2（既有進行中的票）判斷最新留言是否為「自己剛貼的」時，要
     比對的簽名字串（`— By Rick (jira-grill)` 或 `— By Genie
     (jira-grill)`）。
  不支援的 `GRILL_TARGET_BOT` 值 → 印錯誤訊息並以非 0 結束碼結束（不
  是靜默跳過，設定錯了要讓 CronJob 這次執行明確失敗）。
- `cronjob.yaml` 的 ConfigMap 內容跟著同步（沿用既有「script 內容嵌進
  ConfigMap」的部署慣例），新增對應的環境變數宣告區塊。

## 需要變更的檔案清單

| Repo | 檔案 | 變更內容 |
|------|------|----------|
| `wm4n/skill-registry` | `plugins/solo-bot-skills/skills/jira-grill/SKILL.md` | 帳號選擇改走 persona 優先、簽名參數化、description 中性化 |
| `wm4n/skill-registry` | `plugins/solo-bot-skills/.claude-plugin/plugin.json` | bump 版本號 |
| `wm4n/skill-registry` | `.claude-plugin/marketplace.json` | 同步 bump 版本號 |
| `openab` | `deployment-guides/Genie-CLAUDE_v2.md` | 新增路由判斷 + 「4b. Jira Grill」小節 |
| `openab` | `deployment-guides/k3s/jira-grill-poller/poller.sh` | `GRILL_TARGET_BOT` 分支邏輯 |
| `openab` | `deployment-guides/k3s/jira-grill-poller/cronjob.yaml` | 同步 ConfigMap 內容 + 新增環境變數 |
| `openab` | `deployment-guides/BOT_SETUP.md` | 補上 genie 的安裝/驗證步驟、`jira-grill-poller` 的新設定變數說明 |

**不需要變更**：genie 的 `values-openab-claude.yaml`（`trustedBotIds` 已
含 `jira-grill-trigger`、`secretEnv` 已含 `JIRA_TOKEN`/`JIRA_EMAIL`/
`JIRA_BASE_URL`，agent-dev-poller 上線時就設定好了）——這次**不需要
`helm upgrade`**。

## 部署與 rollout 步驟

1. `wm4n/skill-registry`：完成上方元件 2 的修改，bump `solo-bot-skills`
   版本號（`plugin.json` + `marketplace.json`），commit + push。
2. genie 的 plugin 更新：
   ```bash
   kubectl exec deployment/openab-claude-genie -n cac -- claude plugin marketplace update wm4n-skill-registry
   kubectl exec deployment/openab-claude-genie -n cac -- claude plugin update solo-bot-skills@wm4n-skill-registry
   ```
3. **保險步驟**（不管 genie 現在有沒有裝過，都明確跑一次，已裝過的話
   這條指令本身無害）：確保 genie 有 `jira-fetch` 可用（`jira-grill`
   跟既有的 `auto-dev-pipeline` 都靠它讀 Jira）：
   ```bash
   kubectl exec deployment/openab-claude-genie -n cac -- claude plugin marketplace add wm4n/skill-registry
   kubectl exec deployment/openab-claude-genie -n cac -- claude plugin install skill-registry@wm4n-skill-registry
   ```
4. 更新 `Genie-CLAUDE_v2.md`（元件 1），push 後跑既有的
   `update-context.sh`（四隻 bot 都會重新 `git pull` + 覆寫
   `CLAUDE.md`/`AGENTS.md`），跑完到 Discord 對 genie 開一條新 thread
   才會重讀。
5. Rick 這邊也要跑一次 `plugin marketplace update` +
   `plugin update solo-bot-skills@wm4n-skill-registry`（`jira-grill`
   搬家後掛在這個 plugin 底下，前一輪工作已經記錄在 `BOT_SETUP.md`，
   這裡只是提醒別漏掉，不是本次新增步驟）。
6. `jira-grill-poller` 的 `poller.sh`/`cronjob.yaml` 改完後
   `kubectl apply -f cronjob.yaml`（`GRILL_TARGET_BOT` 不設定或設
   `rick`，行為與現況相同）。

## 測試/驗收方式

1. **jira-grill skill 內容改動的迴歸驗證**（用 Rick，確認沒改壞現行
   行為）：找一張既有的 `grill-me-active` 測試票，確認 Rick 執行後：
   - 帳號選擇邏輯（103corp 系 repo）行為不變（走 `repo-identity`）。
   - 貼出的留言簽名仍是 `— By Rick (jira-grill)`。
2. **genie 執行 jira-grill 的手動驗證**：找一張 104corp 專案下、貼了
   `grill-me` label 的測試票，在 Discord 手動要求 genie 處理，確認：
   - genie 依路由規則進入「4b. Jira Grill」而非一般模式。
   - 帳號選擇套用 104cac 固定規則，未呼叫 `repo-identity`（可觀察
     genie 的操作紀錄/回報內容確認沒有 `gh auth switch` 到其他帳號）。
   - 貼出的留言簽名是 `— By Genie (jira-grill)`。
3. **genie 執行 ready-for-agent-dev 分支的手動驗證**：找一張已經貼了
   `ready-for-agent-dev` 的票，人類直接在對話裡提到票號要求 genie 處理
   （不透過 `agent-dev-poller` 觸發），確認 genie 直接進 Auto Dev
   Pipeline、沒有出現確認閘門。
4. **無 label 分支迴歸驗證**：確認人類提到一張完全沒有相關 label 的票
   時，genie 行為與改動前一致（依對話語氣判斷一般模式/全自動模式）。
5. **jira-grill-poller 設定驗證**：`GRILL_TARGET_BOT` 不設定時手動執行
   一次，確認行為與改動前完全一致（mention Rick、簽名比對 `Rick`）；
   另外用一次性的手動測試（例如本機執行改過的 `poller.sh`、設
   `GRILL_TARGET_BOT=genie` 環境變數）確認會改成 mention genie、簽名
   比對改成 `Genie`，不需要真的部署這個設定去驗證。

## 已知限制

- **genie 目前不會被 `jira-grill-poller` 自動觸發處理 `grill-me` 票**：
  `GRILL_TARGET_BOT` 預設仍是 `rick`，genie 只能透過人類手動 @mention
  進入「4b. Jira Grill」。這是本次刻意保留的範圍界線（見「非目標」），
  之後真的要讓 genie 接手自動觸發，只需要切換這個環境變數，不需要再
  改 skill 或 persona 內容。
- **一張票理論上可能被兩隻 bot 交錯處理**：如果人類先手動請 genie 對
  一張 `grill-me` 票跑一輪，之後這張票又被 `jira-grill-poller`（預設
  目標 Rick）偵測到有新回覆而觸發 Rick——兩隻 bot 各自依「自己的簽名」
  判斷要不要處理，不會互相衝突或重複回答同一輪，但留言串裡會混雜兩種
  簽名，人類閱讀時需要自己分辨是哪隻 bot 回的。這種情況預期只會發生在
  人類主動繞過慣例、手動指定另一隻 bot 處理時，不是常態路徑。
- **`repo-identity` 優先序判斷靠 persona 內容比對，沒有強制介面**：
  「先看 persona 有沒有固定帳號規則」這一步本質上是靠 LLM 讀自己的
  CLAUDE.md/AGENTS.md 內容判斷，不是呼叫一個定義嚴謹的 API——如果之後
  某隻 bot 的固定帳號規則寫得不夠明確，可能誤判成「沒有固定規則」而
  跑去呼叫用不到的 `repo-identity`（若沒裝會直接失敗、需要人類介入）。
  目前 Rick/Morty（呼叫 `repo-identity`）與 genie（明確固定 104cac）
  两邊寫法都夠清楚，這個風險目前是理論上的。
