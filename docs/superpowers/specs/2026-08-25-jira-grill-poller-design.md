# jira-grill 輪詢架構重寫:Deterministic Poller 設計文件

- 日期:2026-08-25
- 狀態:設計已定案,待使用者複審 spec 全文
- 範圍:重寫 `jira-grill` 的「怎麼知道該處理哪張票」機制,把現行「Rick 用
  openab usercron 每 10 分鐘觸發一次 LLM turn 檢查有沒有新留言」換成
  「一個獨立於 openab 之外、不經過 LLM 的 deterministic K8s CronJob,
  只有真的偵測到需要處理時才觸發 Rick」。
- 語言:繁體中文
- 與舊設計的關係:本文件**取代** `2026-08-24-rick-jira-grill-design.md`
  裡「Discovery 與 Per-ticket Job 的生命週期」這一節描述的輪詢/觸發機制,
  其餘部分(grilling 提問格式、簽名標記、中止訊號判斷、repo 解析優先序、
  label 狀態機 `grill-me`→`grill-me-active`→`grill-me-done`、Jira 是
  唯一真相來源的設計哲學)**維持不變**,不在本文件重複列出,細節見舊
  spec 與現行 `SKILL.md`。
- 與三 bot pipeline 的關係:不變,仍完全獨立。

## 觸發問題(為什麼要重寫)

現行設計實測後發現兩個成本問題:

1. **頻率乘數**:discovery job 固定每 10 分鐘觸發一次 LLM turn(即使
   完全沒有票),每張進入 grilling 的票再各自加一個每 10 分鐘的
   per-ticket job——並行票數一多,LLM 用量線性增加。
2. **Session 累積的複利效應**:per-ticket job 靠同一個 Discord thread
   延續同一個 ACP session,每一輪「沒有新留言→no-op」的 tool call 輸出
   (`jira-fetch --comments 50` 抓到的完整留言全文)都會留在該 session
   的歷史裡,越晚的輪次背的上下文越重。一張票掛著等人類回覆數天,就會
   累積數百輪絕大多數是 no-op 的紀錄。

兩者的根本原因相同:「判斷有沒有新留言」這件事目前完全發生在 LLM
agentic turn 裡,沒有語言模型之外的輕量前置判斷。

## 目標

1. 閒置時(沒有新票、沒有新回覆)LLM 使用量趨近於零。
2. 只有真的有新票或人類真的回覆時,才觸發一次 Rick 的 LLM turn。
3. 不引入需要自己維護的狀態儲存(state store)。
4. 不改變現行已經驗證過的 grilling 方法論、簽名標記、label 狀態機、
   repo 解析邏輯。

## 非目標(YAGNI)

- 不做 Jira webhook + 對外公開 endpoint(evaluated 過,見下方「考慮過但
  沒選的方案」)——目前規模不需要即時 push,分鐘級輪詢延遲對這個非同步
  Jira comment 對話場景無感。
- 不引入 AWS 或任何本專案原本沒有的雲端依賴。
- 不做告警/監控機制——錯誤處理策略是「跳過、留給下一輪自然重試」,
  細節見下方「錯誤處理」。

## 考慮過但沒選的方案

- **A. 維持現行機制,只拉長輪詢間隔**:改動最小,但沒解決「成本隨並行
  票數線性增加」與「session 隨時間累積」兩個根本問題,只是把曲線斜率
  壓低。
- **C. Jira webhook(需要對外可達的 endpoint,例如 AWS Lambda)**:能做到
  即時 push、且可以把「有沒有新留言」的判斷完全交給 Jira 自己的事件
  訂閱機制,理論上比本設計更精簡。但需要:(1) 新增 AWS 依賴,本專案
  目前完全自建在 k3s 上,沒有任何 AWS 服務;(2) 一個對外公開、需要自己
  顧驗證機制的 endpoint,攻擊面不是零;(3) Jira 管理員權限才能設定
  webhook,權限需求比現有的 API token 高。三者都超出目前規模所需,
  故未採用,但架構上是可行的替代方案,未來規模擴大時可重新評估。

## 架構總覽

```
Jira(唯一真相來源)
   ↑ 讀(JQL + label + 最新留言)
jira-grill-poller(新的 K8s CronJob,獨立於 openab 之外,全程不經過 LLM)
   │  判斷「這張票需不需要觸發 LLM」
   │  新票:label grill-me → grill-me-active(原子性「認領」)
   ↓  用新的 jira-grill-trigger bot 帳號,在 JIRA_GRILL_CHANNEL @mention Rick
Rick(openab bot,Discord 收訊:allowBotMessages=mentions +
     trustedBotIds 含 jira-grill-trigger)
   ↓  觸發一次 LLM turn,跑 jira-grill skill(合併後的單一流程)
   ↓  重新完整讀 Jira、做真正的 grilling 推理、貼留言/收斂
Jira(留言貼回,label 轉為 grill-me-done 或維持 grill-me-active)
```

閒置時只有 poller 在跑(零 LLM 成本);只有偵測到「新票」或「人類真的
回覆」才會觸發一次 LLM turn。

## 元件

### 1. `jira-grill-poller` script(deterministic,無狀態)

- 語言:bash + `node -e` 解析/組 JSON,沿用 `jira-fetch` 既有慣例——
  不假設 `jq`/`python3`/GNU-only coreutils 存在。
- 讀取的環境變數:
  - `JIRA_TOKEN` / `JIRA_EMAIL` / `JIRA_BASE_URL`(重用既有
    `morty-jira` K8s Secret)。
  - `JIRA_GRILL_PROJECTS`(逗號分隔的 project key 白名單,如
    `CACJOB,CACVIP,CACATS`)。
  - `JIRA_GRILL_CHANNEL`(觸發訊息要貼去的 Discord channel ID,沿用
    現有的 cac-notify:`1528965173761802420`)。
  - `JIRA_GRILL_TRIGGER_BOT_TOKEN`(新註冊的 `jira-grill-trigger` bot
    的 Discord token,新 Secret)。
  - `RICK_DISCORD_USER_ID`(組 mention 文字用,已知值
    `1519868630064562278`)。
- 完全無狀態、不掛任何 PVC,只對外打 Jira REST API + Discord REST API
  兩種 HTTPS 請求。

### 2. K8s CronJob

- 跟 openab 的 Helm release(`openab-claude`)完全分開部署,不透過
  openab chart。
- `schedule`:`*/10 * * * *`(跟現行輪詢間隔一致,可事後調整)。
- `concurrencyPolicy: Forbid`:避免上一輪還沒跑完時,下一輪又疊上來
  (poller 本身理論上跑得很快,但仍要防呆)。
- `image`:重用 Rick 現有的 `ghcr.io/104corp/openab:0.9.0-claude-cli2.1.220`
  (同一個 `ghcr-104corp` imagePullSecret),不另外 build/維護新 image。
  `command`/`args` override 掉,不跑 `claude-agent-acp`,改跑
  `poller.sh`。
- `poller.sh` 內容透過 ConfigMap 掛載進容器。
- Namespace:跟 Rick 同一個(`cac`),可直接引用既有的 `morty-jira`
  Secret。

### 3. `jira-grill-trigger` Discord bot application(新註冊)

- 在 Discord Developer Portal 新開一個 bot application,**只需要「送
  訊息到指定頻道」的最小權限**,不需要讀訊息、不需要其他 intent。
- 取得 bot token 後存成 K8s Secret,給上面的 CronJob 用。
- 拿到這個 bot 的 **user ID**,加進 Rick 的
  `values-openab-claude.yaml` 的 `trustedBotIds`(讓 Rick 的
  `allowBotMessages: "mentions"` 收訊規則接受它的 @mention,比照現行
  Morty/Summer 觸發 Rick 的既有機制)。

### 4. `jira-grill` SKILL.md(改版)

- `$ARGUMENTS` 收斂成單一形式:`ticket <TICKET_ID>`(拿掉 `discover`
  模式與 `repo=<owner/repo>` 傳遞)。
- 詳細流程見下方「SKILL.md 合併後的流程」。

## Poller 判斷邏輯(每次執行)

> **2026-08-25 rollout 實測更正**:實作時發現 Jira 的
> `GET /rest/api/2/search`(連同 v3 GET 版本)已被 Atlassian 下架
> (呼叫回傳 HTTP 410,錯誤訊息直接指向遷移指引),兩條 JQL 的實際實作
> 都改用 `POST /rest/api/3/search/jql`(request body
> `{jql, fields, maxResults}`,回應改用 `issues[].key` +
> `nextPageToken`/`isLast` 分頁,不再有 `startAt`/`total`)。下面描述的
> JQL 查詢邏輯本身不變,只是 wire format 換了;`maxResults: 50`、只取
> 第一頁不做分頁跟進,細節見 `poller.sh` 原始碼註解。

用**兩條獨立的 JQL**分別處理「新票」與「既有進行中的票」,不合併成一條
——原因見下方 Query 1 的說明。

1. **Query 1:找新票(無時間窗口限制)**
   ```
   project IN (<JIRA_GRILL_PROJECTS>) AND labels = "grill-me"
   ```
   刻意**不加** `updated >=` 時間限制:這條 query 只回傳「還沒認領」的
   票,正常情況下每個 cycle 應該只有 0~1 張(認領後就轉成
   `grill-me-active`,下個 cycle 就不會再出現在這個結果裡),所以無界
   查詢不會有效能問題。如果加了時間窗口,一張票被貼上 `grill-me` 後
   若超過窗口都沒有其他欄位變動去刷新 `updated`,會被永久漏掉——這是
   自我檢查時發現的邏輯漏洞,故意設計成無界查詢來避免。只需要 `key`
   欄位。
   對每個回傳的 `TICKET_ID`:
   1. 呼叫 `PUT /rest/api/2/issue/{key}`,把 label 從 `grill-me`
      換成 `grill-me-active`(原子性「認領」,語法同現行 SKILL.md
      的「改 label」段落)。
   2. 這個 PUT 失敗 → 記錄錯誤、跳過(label 仍是 `grill-me`,下一輪
      Query 1 還是會抓到,自然重試)。
   3. PUT 成功 → 觸發(見下方步驟 3)。
2. **Query 2:找既有進行中的票有沒有新回覆(用時間窗口做粗篩)**
   ```
   project IN (<JIRA_GRILL_PROJECTS>) AND labels = "grill-me-active"
     AND updated >= "-25m"
   ```
   這裡才需要時間窗口:`grill-me-active` 的票在穩定狀態下可能同時有
   多張並行,每一張都要多打一次「抓最新留言」的 API 才能判斷有沒有
   新回覆,用 `updated` 先粗篩能避免每個 cycle 對所有進行中的票都打
   這支 API。窗口(`-25m`)設成輪詢間隔(10 分鐘)的 2 倍以上,確保就算
   某一次執行失敗漏跑一輪,下一輪還是抓得到。只需要 `key` 欄位。
   對每個回傳的 `TICKET_ID`,只抓最新 1 則留言
   (`GET /rest/api/2/issue/{key}/comment?orderBy=-created&maxResults=1`):
   - 內容含簽名 `— By Rick (jira-grill)` → 這是 Rick 自己剛貼的
     (或先前改 label 動作造成 `updated` 跳動但沒有新留言)→ 真正
     no-op,跳過。
   - 內容不含簽名(含「完全沒有任何留言」的情況)→ 真的有人類新回覆,
     或是先前一輪觸發失敗、Rick 從未成功貼出留言 → 觸發。
   - 這一步的 API 呼叫失敗 → 記錄錯誤、跳過這張票,不影響其他票,
     下一輪自然重試。

任一條 JQL 搜尋本身失敗(網路/認證錯誤)→ 記錄錯誤、該條 query 這輪
結束,不影響另一條 query,下一輪自然重試。

3. **觸發**(兩條 query 共用同一段邏輯):呼叫 Discord API,用
   `jira-grill-trigger` bot 在
   `JIRA_GRILL_CHANNEL` 貼一則訊息:
   ```
   <@{RICK_DISCORD_USER_ID}> 執行 jira-grill skill,參數:ticket <TICKET_ID>
   ```
   這個 API 呼叫失敗 → 記錄錯誤。若失敗發生在「新票」分支且 label 已經
   換成 `grill-me-active`,不需要特別復原:下一輪的「粗篩」仍會抓到這張
   票(label 含 `grill-me-active`),而「逐票判斷」會發現它還沒有任何
   帶簽名的留言 → 視為需要處理 → 再次觸發,自我修復。
4. 全程無狀態,不寫入任何本地檔案或 K8s 物件記錄進度。

## SKILL.md 合併後的流程(唯一入口 `ticket <TICKET_ID>`)

1. **確認環境變數**:只需要 `JIRA_TOKEN`/`JIRA_EMAIL`/`JIRA_BASE_URL`
   (同 `jira-fetch`)。`JIRA_GRILL_CHANNEL`/`JIRA_GRILL_PROJECTS` 移出
   Rick 的設定,變成 poller 專屬的環境變數,SKILL 本身不再需要。
2. `jira-fetch ${TICKET_ID} --comments 50` 取得完整內容(labels、全部
   留言,新到舊排序)。
3. **重複觸發防護**:看留言區塊最上面(最新)那一則,若已含簽名
   `— By Rick (jira-grill)` → 代表這次觸發是 race 造成的重複觸發(poller
   偵測到變更、但 Rick 上一輪 turn 尚未完成前又被觸發一次)→ no-op
   結束。這個檢查只在真的被觸發時執行一次,不影響省成本的效果(不是
   每 10 分鐘都跑),純粹是正確性的安全網。
4. **防禦性 label 檢查**:
   - 不含 `grill-me-active` 也不含 `grill-me`(已收斂/已中止/人類手動
     改過)→ 理論上不該被觸發(poller 的 JQL 只抓這兩種 label),記錄
     警告、no-op 結束。
   - 只含 `grill-me`(poller 的「認領」PUT 失敗了)→ 補做 label 轉換
     (`grill-me` → `grill-me-active`),當首輪繼續處理。
   - 含 `grill-me-active` → 繼續步驟 5。
5. **判斷首輪/續輪**:整串留言裡有沒有任何一則帶 Rick 簽名的留言:
   - 沒有 → **首輪**:依「Repo 解析與準備」(沿用現行 SKILL.md 邏輯,
     不變)決定並準備目標 repo,以標題/描述/驗收條件與(若已解析)
     repo 裡查到的程式碼事實產出第一輪 frontier,貼成第一則 comment。
   - 有 → **續輪**:
     a. 中止訊號判斷(人類文字喊停的語意判斷、label 是否被人類手動
        改掉)——邏輯不變,沿用現行 SKILL.md。
     b. Repo 是否已知:**每輪都重新走一次**「Repo 解析與準備」優先序
        (不再像現行設計那樣把解析結果快取進 cron job 的 message 裡
        傳遞——沒有 per-ticket cron job 了,而且解析成本本身很低,
        重算比維護快取簡單)。
     c. 用完整留言串重新計算 design tree:有未決分支 → 貼下一輪
        frontier;frontier 清空 → 收斂。
6. **收斂/中止收尾**:貼結論留言、label 轉 `grill-me-done`——邏輯不變,
   沿用現行 SKILL.md。**拿掉**現行流程二步驟 8c(移除 cronjob.toml 裡
   的 job)——不再有動態建立的 job 可移除。

### 拿掉的部分

- 兩種觸發模式(`discover` / `ticket`)的分流 → 合併成單一入口。
- 「最新留言是否帶自己簽名」的 no-op 判斷 → 移到 poller,SKILL 只保留
  一個輕量防護版本(見上方步驟 3)。
- 所有 `~/.openab/cronjob.toml` 讀寫:建立 per-ticket job、把 `repo=`
  寫回 job 的 message、收斂/中止時移除 job——三處全部拿掉。

## cronjob.toml 的角色與遷移

新機制上線後,`~/.openab/cronjob.toml` 完全不再有任何 jira-grill 相關
entry——不再有 discovery job,也不再有 per-ticket job。jira-grill 改為
純粹靠 Discord bot mention 觸發,跟現行 Morty/Summer 觸發 Rick 的機制
一致。

**遷移步驟**(一次性):部署新機制的同時,手動清掉現行
`~/.openab/cronjob.toml` 裡的 `id = "jira-grill-discovery"` 與任何
殘留的 `id = "jira-grill-<TICKET_ID>"` entry,避免兩套機制並存、白白
空轉。

## Rick 的設定變更(`values-openab-claude.yaml`)

- **移除**:`env.JIRA_GRILL_CHANNEL`、`env.JIRA_GRILL_PROJECTS`——不再
  被 SKILL 使用,改成 poller CronJob 自己的環境變數。
- **新增**:`discord.trustedBotIds` 加入 `jira-grill-trigger` bot 的
  user ID(申請 bot 後才能拿到實際數值,先佔位)。
- **不變**:`secretEnv`(JIRA_TOKEN/EMAIL/BASE_URL)、
  `discord.allowedChannels`(cac-notify 已在清單內,poller 貼的觸發
  訊息會落在這個既有頻道,不需要新增頻道)。

## 環境變數彙整

| 變數 | 用途 | 歸屬 |
|------|------|------|
| `JIRA_TOKEN` / `JIRA_EMAIL` / `JIRA_BASE_URL` | Jira REST API 認證 | Rick(SKILL 用)+ poller(共用同一組值) |
| `JIRA_GRILL_PROJECTS` | 掃描的 Jira project key 白名單 | 只有 poller |
| `JIRA_GRILL_CHANNEL` | 觸發訊息要貼去的 Discord channel | 只有 poller |
| `JIRA_GRILL_TRIGGER_BOT_TOKEN` | `jira-grill-trigger` bot 的 Discord token | 只有 poller(新 Secret) |
| `RICK_DISCORD_USER_ID` | 組 @mention 文字用 | 只有 poller |

## 部署位置

```
deployment-guides/k3s/jira-grill-poller/
  poller.sh      # 主要邏輯(bash + node -e)
  cronjob.yaml   # K8s CronJob + ConfigMap(掛 poller.sh)+ Secret 參照
```

- 部署方式:純 `kubectl apply -f cronjob.yaml`,不進 Helm chart(比照
  本專案現有的 `kubectl create secret` 手動建置慣例)。
- 需要手動建立的 Secret:`jira-grill-trigger` bot 的 Discord token
  (`kubectl create secret generic jira-grill-trigger-discord
  --from-literal=token=...`)。

## 錯誤處理

原則:**跳過、留給下一輪自然重試**,不做重試迴圈、不做告警。

| 失敗點 | 處理方式 |
|--------|----------|
| Poller 的 JQL 搜尋失敗 | 記錄錯誤,整輪結束,下一輪重試(`-25m` 窗口涵蓋漏跑一輪的情況) |
| 單張票的最新留言抓取失敗 | 記錄錯誤,跳過這張票,不影響其他票 |
| 單張票的 label PUT(認領)失敗 | 記錄錯誤,跳過,label 仍是 `grill-me`,下一輪自然重試 |
| Discord 觸發訊息發送失敗 | 記錄錯誤;若 label 已認領成功,下一輪會因為「沒有帶簽名的留言」被判定需要處理,自我修復 |
| Rick 收到觸發後,Jira 資料本身抓取失敗(`jira-fetch` 失敗) | 沿用現行 SKILL.md 既有的錯誤處理(不在本文件重複) |

## 測試/驗收方式

1. **Poller 單獨驗證**(不牽涉 Rick):手動執行一次 `poller.sh`,分別
   驗證:
   - 無符合條件的票 → 不呼叫 Discord。
   - 新增一張測試票貼 `grill-me` → label 轉 `grill-me-active`,Discord
     頻道收到一則 @mention Rick 的觸發訊息。
   - 一張 `grill-me-active` 但最新留言已帶 Rick 簽名的票 → 不觸發。
   - 手動在 Jira 上對一張 `grill-me-active` 的票留言(模擬人類回覆)→
     觸發。
2. **端對端驗證**(牽涉 Rick,對應現行 plan 一直沒完成的 Task 5):一張
   可拋棄的測試票,走完整輪:poller 偵測新票 → 觸發 → Rick 首輪
   frontier → 人類回覆 → poller 偵測 → 再次觸發 → Rick 續輪 → 收斂或
   人類喊停 → label 轉 `grill-me-done`、貼結論留言。
3. **重複觸發防護驗證**:短時間內手動觸發同一張票兩次(例如直接呼叫
   兩次 Discord API 貼觸發訊息),確認第二次被 SKILL 的簽名檢查擋下,
   不會產生兩輪並行的處理結果。

## 已知限制

- **`-25m` 窗口只影響 Query 2(既有進行中的票有沒有新回覆),不影響新票
  偵測**:新票偵測(Query 1)刻意設計成無時間窗口,不會有這個問題。
  Query 2 如果 poller 連續兩輪以上都執行失敗(例如 CronJob 所在節點
  故障超過 20 分鐘),仍可能漏掉某張票的新回覆,直到下一次成功執行、
  且該票的 `updated` 仍落在窗口內——極端情況下(故障時間 > 窗口)需要
  人類手動重新觸發或等票再有新動作才會被抓到。
- **無獨立 Jira bot 身份,無法用留言作者判斷「是不是自己貼的」**:Rick
  用人類帳號回覆 Jira,所以判斷 no-op 一律靠文字簽名標記,不是帳號
  身份——這點沿用現行設計,不是本次重寫新增的限制,但因為是本文件
  poller 判斷邏輯的核心依據,特別在此重申。
- **重複觸發防護是機率性的,不是強一致性保證**:poller 沒有分散式鎖,
  理論上仍存在極窄的競態窗口(poller 判斷完、Discord 訊息送出前,
  Rick 剛好完成上一輪並貼出新留言),但 SKILL 側的簽名檢查會在絕大多數
  情況下擋下重複處理,殘留風險視為可接受。
- **新增 project 要改 poller 的部署設定,不是 skill 自己能決定**:
  `JIRA_GRILL_PROJECTS` 現在是 poller CronJob 的環境變數,要新增專案
  得改這個獨立元件的設定,跟 Rick 的部署脫鉤。
