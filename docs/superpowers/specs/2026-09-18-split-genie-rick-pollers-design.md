# genie 與 rick 的自動化觸發完全分開（grill / agent-dev 各自一組 poller）：設計文件

- 日期：2026-09-18
- 狀態：設計已定案（brainstorming 對話中逐段確認），待使用者複審 spec 全文
- 範圍：把現行「單一實例、目標 bot 二選一」的兩支 poller，改成 **2 支來源中立的
  腳本 × 2 個目標 bot ＝ 4 個 CronJob**；並把 `jira-grill` skill 擴充成也能對
  GitHub issue 作業。跨兩個 repo（本 repo 的 poller 層 + `wm4n/skill-registry`
  的 skill 層）。
- 語言：繁體中文
- 前置事實來源：`deployment-guides/k3s/jira-grill-poller/`、
  `deployment-guides/k3s/agent-dev-poller/` 的現行 `poller.sh` 與 `cronjob.yaml`
  （本文件所有「現在怎麼運作」的敘述都來自讀取這兩份實際部署工件，不是推測）。
  相關既有設計：`2026-08-25-jira-grill-poller-design.md`、
  `2026-09-08-genie-jira-grill-routing-design.md`。

## 背景與目標

genie 與 rick 現在服務不同的產品線、位於不同的 Discord server，但兩者的自動化
觸發共用同一組 poller：

| 現況 | 說明 |
| --- | --- |
| `jira-grill-poller` | 單一實例，`GRILL_TARGET_BOT` 在 rick／genie 之間二選一。**純 Jira 來源**（兩條查詢都是 JQL、認領靠 Jira label、判斷新回覆靠讀 Jira 留言）。目前 `suspend: true`，**沒有任何 grill 實例在服務** |
| `agent-dev-poller` | 單一實例，觸發對象寫死 genie（`GENIE_DISCORD_USER_ID`、`trigger_genie()`）。**已經是雙來源**（掃 Jira 白名單 + GitHub 白名單），GitHub 那半已支援依 repo owner 選 token。目前運行中 |

目標狀態：

| 實例 | 目標 bot | Jira 白名單 | GitHub 白名單 | 觸發頻道 |
| --- | --- | --- | --- | --- |
| `grill-poller-genie` | Genie | `CACJOB,CACVIP,CACATS,ITGD` | `104corp/104cac-product-registry,104corp/interview-ai-summary` | cac-notify |
| `grill-poller-rick` | Rick | *(空)* | `wm4n/chainbreak,wm4n/hangman` | bot-notify |
| `agent-dev-poller-genie` | Genie | `CACJOB,CACVIP,CACATS,ITGD` | `104corp/interview-ai-summary` | cac-notify |
| `agent-dev-poller-rick` | Rick | *(空)* | `wm4n/chainbreak,wm4n/hangman` | bot-notify |

> **一併修正的既有不一致**：genie 的 grill 現行白名單只有 3 個 Jira 專案（無
> `ITGD`），agent-dev 卻是 4 個。複審時確認這是漏的，**本次對齊成 4 個**——
> 也就是 `ITGD` 的票從此也會被 grill 掃到。這是本設計唯一一處刻意改變現行行為
> 的地方，其餘都是結構重組。

## 設計決策（brainstorming 逐項確認）

| # | 決策 | 理由 |
| --- | --- | --- |
| 1 | rick 的 grill 逼問**發生在 GitHub issue 留言** | rick 的產品只有 GitHub 管理，沒有 Jira |
| 2 | **沿用同一顆 `jira-grill-trigger` bot**，邀進兩個 server | 一把 token、一個 Secret；Rick 的 `trusted_bot_ids` 已信任它，不用改 config |
| 3 | spec **同時涵蓋 poller 層與 skill 層** | 只做 poller 會產出「觸發得了、bot 做不了事」的半套 |
| 4 | **共用腳本、分批上線** | 單一事實來源；但先只部署 rick 的新實例，驗證後才把 genie 切過去 |
| 5 | grill poller 改成**雙來源**（比照 agent-dev） | genie 的產品 Jira／GitHub 都有；白名單留空即跳過該來源 |
| 6 | `jira-grill` skill **維持原名**，擴充成來源中立 | 改名要同時動兩隻 persona、plugin 版本、poller 的簽名比對字串，churn 大於收益 |

### 捨棄的方案

- **合併成單一「label 驅動觸發器」**：用設定描述 `(ready-label, active-label,
  skill, target, sources)` 產生全部四種行為。最 DRY，但 grill 的「讀最新留言比對
  簽名」與 agent-dev 的「查 blocker 依賴」本質不同，硬塞同一個抽象會長出大量分支。
  為了消除表面重複而犧牲可讀性，不採用。
- **rick 另寫一套獨立腳本**：零風險但兩份必然漂移，日後修 bug 要改兩邊。

## 元件與 env 契約

兩份 ConfigMap（`grill-poller-script`、`agent-dev-poller-script`），四個 CronJob
各自掛 env。兩支腳本共用同一組變數名稱：

```
TARGET_BOT_ID        Discord user ID（要 @ 誰）
TARGET_BOT_NAME      Rick | Genie      ← 留言簽名比對要用
TRIGGER_CHANNEL      Discord channel ID
TRIGGER_BOT_TOKEN    jira-grill-trigger 的 token（四支共用同一個 Secret）

JIRA_PROJECTS        逗號分隔；留空＝完全跳過 Jira 來源
GITHUB_REPOS         逗號分隔 owner/repo；留空＝完全跳過 GitHub 來源
JIRA_TOKEN / JIRA_EMAIL / JIRA_BASE_URL    僅 JIRA_PROJECTS 非空時必填
GH_TOKEN_WM4N / GH_TOKEN_CAC               依 repo owner 分流，缺哪把只跳過該 owner
```

**兩處沿革命名，這次一併對齊：**

- 現行 `agent-dev-poller` 用的是 `GH_AGENT_DEV_TOKEN_CAC`。這些變數現在兩個
  poller 家族都會用，`AGENT_DEV` 這個前綴變成誤導，故改名為 `GH_TOKEN_<OWNER>`。
  （這是 poller 容器內的變數，不是 bot 容器；bot 那邊「不得出現裸 `GH_TOKEN`」的
  鐵則與此無關，`GH_TOKEN_CAC` 這種帶後綴的名稱本來就不會被 gh 誤用。）
- K8s Secret 名稱 `github-agent-dev-poller-cac`／`-wm4n` 與
  `jira-grill-trigger-discord` **維持不改**。名字同樣帶著沿革（現在是兩個家族共用），
  但改 Secret 名稱要同時改所有引用處、且對正在跑的 genie 實例有風險，收益不值得。
  **在 `cronjob.yaml` 註解裡標明「名稱是沿革，實際為四支 poller 共用」即可。**

**捨棄現行 `GRILL_TARGET_BOT=rick|genie` 的 case 寫法。** 那個寫法把 bot 名單寫死
在腳本裡（加第三隻要改程式），且同時要求 `RICK_DISCORD_USER_ID` 與
`GENIE_DISCORD_USER_ID` 兩個 env 都存在。改成直接傳 ID 與 NAME 之後，腳本完全
不需要知道系統裡有哪些 bot。

**連帶必改**：兩支腳本開頭現在是無條件的 `: "${JIRA_TOKEN:?missing}"` 這類檢查。
改成雙來源後，這些檢查必須**移進各自的來源分支**，否則 rick 那組（沒有 Jira）
會在第一行就 abort。

## 資料流：grill 在兩種來源上的對應

| 步驟 | Jira（現行，不變） | GitHub（新增） |
| --- | --- | --- |
| 找新目標 | JQL `project IN (…) AND labels = "grill-me"` | `GET /repos/{o}/{r}/issues?labels=grill-me&state=open` |
| 認領 | 單一 `PUT` 同時 remove `grill-me` + add `grill-me-active`（原子） | 兩個請求，見下方 |
| 找有新回覆的進行中目標 | JQL `labels = "grill-me-active" AND updated >= "-25m"` | 同上但 `labels=grill-me-active&since=<25 分鐘前 ISO8601>` |
| 判斷要不要再觸發 | 讀最新一則留言，**不含** `— By <Bot> (jira-grill)` 簽名就觸發 | 完全相同，改讀 `GET …/issues/{n}/comments?sort=created&direction=desc&per_page=1` |
| 觸發 | `POST` Discord 訊息到 `TRIGGER_CHANNEL` | 相同 |

**簽名比對維持一模一樣**，不改成「比對留言作者的 GitHub login」——後者在 GitHub
上確實更可靠，但會讓兩種來源的判斷邏輯分岔（Jira 端分不出是哪隻 bot，因為共用
`morty-jira` 服務帳號）。跨來源一致性的價值大於這點可靠度差異。

### GitHub 特有的認領競態

GitHub 沒有「一個請求同時 add + remove label」的 API，必須兩步：

```
POST   /repos/{o}/{r}/issues/{n}/labels          → 加 grill-me-active
DELETE /repos/{o}/{r}/issues/{n}/labels/grill-me → 移除 grill-me
```

**順序刻意是「先加 active、再移除 ready」**：中間若失敗，issue 會同時帶兩個
label（狀態看得出來、人工可修）；反過來寫的話失敗會變成兩個 label 都沒有——任務
憑空消失且沒人會發現。`agent-dev-poller` 現行就是這個順序，grill 沿用。

**查詢端要容忍殘留狀態**：Query 1 查到的 issue 若已帶 `grill-me-active`，代表上
一輪認領做到一半失敗，補做 `DELETE` 後直接觸發即可，不要當成全新目標重跑整套。

### label 必須預先建立

GitHub 的「加 label 到 issue」API **不會自動建立不存在的 label**（`agent-dev-poller`
上線時踩過）。每個進白名單的 repo 都要先建好所需 label。

## skill 層契約（`wm4n/skill-registry`）

### 觸發訊息格式：沿用 agent-dev 已在用的兩種形狀，不發明新格式

```
<@ID> 執行 jira-grill skill，參數：ticket CACJOB-123
<@ID> 執行 jira-grill skill，參數：github-issue wm4n/chainbreak#42
```

skill 依參數前綴分流。**genie 的 Jira 行為必須完全不變**（純追加第二種形狀）——
skill 是兩隻共用的，這是向後相容的硬要求。

### 分階段提問機制原樣轉移

`jira-grill` 的「規格問題先、工程問題後」是靠**留言串裡的里程碑留言重新推導階段
狀態、不存外部狀態**。這個設計在 GitHub issue 留言上原樣成立，不需修改——是當初
那個設計選擇現在收到的紅利。

### 憑證分層（容易搞混，明確寫下）

- **poller 的 token**：只需要讀 issue + 改 label。104corp 沿用現有 classic token
  + **Triage** 角色（不含 code 讀寫）；wm4n 用 fine-grained PAT 只開該 repo 的
  Issues 讀寫。
- **貼逼問留言的不是 poller，是 bot 自己**：skill 那層用 bot 已登入的 gh 帳號發
  comment（Rick 走 `repo-identity` 依 owner 選 wm4n／cac-william，genie 固定
  `104cac`）。**poller 的 token 不需要留言權限。**

### ✅ PAT 留言權限（原本擔心會擋住上線，實測不需要改）

`deployment-guides/BOT_SETUP.md` Part B2 明寫 fine-grained PAT 的
`Issues → Read and write`「**只有 Morty 需要**；Rick/Summer 用不到可留 No
access」——那是接力時代的判斷，當時 Rick 不需要在 issue 上留言。本設計原本據此
把「Rick 兩把 PAT 都要補 Issues RW」列為必做前置。

**2026-09-18 實測推翻**：Rick 用 `wm4n` 帳號對 `wm4n/chainbreak` 的 issue 貼
留言**直接成功，不需要改任何 PAT**。原因推測是 B2 那段描述的是 fine-grained
PAT 的建議值，而實際在用的是 **classic PAT**（`repo` scope 本來就涵蓋 issue
寫入）。

**教訓是「先驗證再動手」**：照原本的 spec 會去改兩把正在服務中的 token，
完全沒有必要，而改壞的話影響的是 bot 全部的 GitHub 操作，不只 grill。

⚠️ **仍未驗證的部分**：genie 的 `104cac` 帳號對它那兩個 104corp repo 的留言
權限（104corp 的 org 政策與個人帳號不同）。Phase 1 驗證 genie 時會一併確認。

> skill 那邊的執行前權限檢查**仍然保留**——它防的是「換了 repo／換了帳號」的
> 未來情境，不是只為這次上線。

## 前置設定（人工，與程式碼無關）

| # | 項目 | 備註 |
| --- | --- | --- |
| 1 | `jira-grill-trigger` bot 邀進 william workspace | 要能在 bot-notify（`1526283579309690990`）發言 |
| 2 | ~~改 Rick 的 config~~ | **不用改、不用 restart**：Rick 的 `trusted_bot_ids` 已含該 bot（`1541617131442147438`）、`allowed_channels` 已含 bot-notify，2026-09-15 搬家時原樣帶過來 |
| 3 | ~~Rick 兩把 PAT 補 `Issues: Read and write`~~ | ✅ **2026-09-18 實測不需要改**（現用 classic PAT 已涵蓋）。genie 的 `104cac` 仍待 Phase 1 一併驗證。見上節 |
| 4 | 新建 K8s Secret `github-agent-dev-poller-wm4n`（wm4n 的 PAT） | rick 的 repo 目前都是 wm4n owner；`-cac` 沿用現有那個、也一併掛到 rick 的兩支上先備著（之後若加 104corp repo 只要改白名單、不用動 Secret）。⚠️ Secret 名稱裡的 `agent-dev` 是沿革，實際為四支 poller 共用 |
| 5 | 建 label | ✅ **2026-09-18 完成（共 20 個，全新建）**：rick 的兩個 repo 各 7 個（grill 的 `grill-me`／`grill-me-active`／`grill-me-done` **加上** agent-dev 的 `ready-for-agent-dev`／`agent-dev-active`／`agent-dev-done`／`agent-dev-failed`）；genie 的兩個 GitHub repo 各 3 個 grill label。⚠️ 原本這格漏了 **`grill-me-done`**——skill 收斂/中止時要把 label 換成它，沒先建會在最後一步失敗 |

## 上線順序與退路

### Phase 1：skill 層先

先改 skill 的理由：poller 先上的話，觸發了 bot 也做不了事。

**這一步完全不需要 poller 就能驗證**——人工在 Discord 對 Rick 打一句
「執行 jira-grill skill，參數：github-issue `wm4n/chainbreak#<測試 issue>`」即可。

發佈路徑：改 `plugins/solo-bot-skills/skills/jira-grill/` → bump
`plugin.json`／`marketplace.json` → push → Rick 跑
`deployment-guides/mac/update-skills.sh`、genie 跑
`deployment-guides/k3s/update-skills.sh`。

**退路**：plugin 版本回退。

### Phase 2：grill poller（零服務中斷風險）

舊的 `jira-grill-poller` 本來就 `suspend: true`、沒有東西在服務，所以這個 Phase
不可能造成中斷。

1. 建新 ConfigMap `grill-poller-script`（雙來源版腳本）
2. 部署 `grill-poller-rick`，**先以 `suspend: true`**
3. `kubectl create job --from=cronjob/grill-poller-rick grill-rick-manual -n cac`
   手動觸發一次，確認認領與觸發都正確
4. 驗證過才 `kubectl patch` 取消 suspend
5. 同樣方式上 `grill-poller-genie`（Jira + GitHub 雙白名單）
6. 刪除舊的 `jira-grill-poller` 與其 ConfigMap

**退路**：把新實例 suspend 回去。

### Phase 3：agent-dev poller（唯一會碰到運行中服務的一步）

1. 腳本參數化（移除寫死的 `GENIE_DISCORD_USER_ID`／`trigger_genie()`）
2. 部署 `agent-dev-poller-rick`（**全新實例，完全不動 genie 的舊實例**）→ 手動
   觸發驗證 → 取消 suspend

> ⚠️ **新 ConfigMap 必須換名為 `agent-dev-poller-script-v2`，不可沿用
> `agent-dev-poller-script`。** 舊的 `cronjob.yaml` 內嵌了一個同名 ConfigMap，
> 那正是服務 genie 的那份；而新舊 script 的 env 契約**不相容**（新版要求
> `TARGET_BOT_ID` 等變數，舊 CronJob 沒設）。若沿用同名重建，**genie 的實例
> 下一輪就會因缺變數直接 abort**——在還沒要動它的第一步就打爆它。
>
> `grill-poller` 沒有這個問題（`grill-poller-script` 是全新名稱，舊的叫
> `jira-grill-poller-script`）。genie 切換完、舊 `cronjob.yaml` 刪除之後，
> `-v2` 只是無害的歷史包袱，要清掉得同時改兩份 yaml 並重建 ConfigMap，非必要。
3. 驗證穩定後才切 genie：
   **`kubectl patch` 把舊的 `agent-dev-poller` suspend → 部署
   `agent-dev-poller-genie` → 驗證 → 刪除舊的**

> ⚠️ **切換 genie 那一刻絕不能讓新舊並存**：兩個實例會掃同一份白名單、都 @genie，
> 造成雙重觸發（兩個 Genie 開發同一張票）。必須先 suspend 舊的再啟用新的。

**退路**：刪掉新實例、把舊的 unsuspend，數秒可逆。

## 排程

| 實例 | 排程 | 理由 |
| --- | --- | --- |
| `grill-poller-*` | `*/10 * * * *`（全天） | 逼問是對話性質，PM 回覆後要儘快接上；壓到離峰會讓一輪問答拖到隔天 |
| `agent-dev-poller-*` | `*/10 21-23,0-6 * * *`（離峰） | 會真的開始寫 code、開 PR，白天跑會跟人工開發撞車（現行 genie 實例即為此改的） |

`concurrencyPolicy: Forbid`、`backoffLimit: 0` 四支沿用現行設定。

## 錯誤處理

沿用兩支現行腳本已驗證的原則，不新增機制：

- **查詢失敗保守跳過**：JQL／GitHub API 非 200 時印錯誤到 stderr 並跳過該目標，
  等下一輪重試，不冒進觸發。
- **認領失敗不觸發**：label 操作失敗就 `continue`，下一輪重試。
- **缺 token 只跳過該 owner**：`GH_TOKEN_*` 缺哪把就跳過哪個 owner 的 repo，不讓
  整個 CronJob 失敗（現行 `agent-dev-poller` 已是此行為）。
- **Discord 觸發失敗**：印錯誤但不回滾 label。已知取捨——該目標會停在 active 狀態
  等人工處理，勝過回滾造成的重複觸發。

## 測試

poller 是 shell + curl，沒有既有的自動化測試，沿用現行的人工驗證方式：

1. **手動 Job 驗證**：`kubectl create job --from=cronjob/<name>` 對每個新實例各跑
   一次，看 log 的「已觸發 …」與 label 實際變化。
2. **空白名單路徑**：rick 的兩支（`JIRA_PROJECTS` 留空）要確認**完全跳過 Jira
   區段、不因缺 `JIRA_TOKEN` 而 abort**——這是本次改動最容易寫錯的地方。
3. **skill 端對端**：人工 @bot 帶 `github-issue` 參數，確認它讀得到 issue、貼得出
   留言、簽名格式正確（poller 的再觸發判斷完全依賴這個簽名）。
4. **再觸發迴圈**：在測試 issue 上以人類身分回一則留言，等下一輪確認 poller 有
   再次觸發；bot 回完後確認**不會**重複觸發。
5. **隔離驗證**：確認 rick 那組不會碰到 genie 的白名單目標，反之亦然。

## 已知限制（沿用現行設計的取捨）

- `agent-dev-active`／`grill-me-active` 沒有逾時自動復原：bot 中途被殺需要人工把
  label 改回 ready 狀態。
- GitHub 的 `since` 與 Jira 的 `updated` 都只是粗篩，`updated_at` 會因 label 變更
  等非留言事件更新；最終判斷仍靠簽名比對，粗篩只為減少 API 呼叫。
- 四支 poller 共用一把 trigger bot token：任一邊需要撤銷時會同時影響兩邊。已知
  取捨，換取設定成本最低。
