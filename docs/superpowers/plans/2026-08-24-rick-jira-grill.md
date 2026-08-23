# Rick 裝載 grill-me、透過 Jira 觸發 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> ⚠️ **運維 runbook 型計畫,橫跨兩個 repo**:Task 1 動 `wm4n/skill-registry`
> (本機已有 clone:`/Users/william.chao/workspace/github/skill-registry`),
> Task 2–3 動這個 `openab` repo(`docs/three-bot-pipeline` branch)。Task
> 1–3 本 session 可直接執行(本機有 wm4n 與 cac-william 兩個 gh 帳號)。
> Task 4(`helm upgrade` / `kubectl exec`)**本機沒有 k3s 叢集存取權**
> (`kubectl get nodes` 連不上),必須交給有叢集存取權的人類/session 執行。
> Task 5(端對端驗證)需要一張真實可拋棄的 Jira 測試票,同樣需要人類配合。

**Goal:** 讓 Rick 能被 Jira `grill-me` label 觸發,用 grilling 方法論對需求
連續提問、問答走 Jira comment,同一張票的往返靠 usercron 落在同一個 ACP
session,收斂或人類喊停後貼共識並通知人類,不自動進開發。

**Architecture:** 純設定/skill 層改動,不改 openab 核心程式碼。新增
`jira-grill` skill(掛進 Rick 已裝的 `openab-bot-skills` plugin,來源在
`wm4n/skill-registry` repo)提供 discovery(`$ARGUMENTS=discover`)與
per-ticket(`$ARGUMENTS=ticket <KEY>`)兩個流程;discovery 用一個固定
cron job 周期性 JQL 搜尋新貼標籤的票,每偵測到一張就動態建立一個該票
專屬的 cron job(獨立 thread_id → 獨立 ACP session);per-ticket job 每次
觸發都重新從 Jira 撈完整內容判斷進度(Jira 是唯一真相來源),沒有新留言就
no-op,有新留言就推進下一輪或收斂。

**Tech Stack:** openab usercron(`~/.openab/cronjob.toml`)、Jira REST API
v2(Basic Auth)、Claude Code Skill(`jira-fetch`/`openab-schedule`/
`mattpocock-skills:grilling`)、Helm(`charts/openab`)、`kubectl exec`。

**Spec:** `docs/superpowers/specs/2026-08-24-rick-jira-grill-design.md`
(含 2026-08-24 對基礎設施現況的複查更正,執行本計畫前務必先讀那次更正)

## Global Constraints

- 所有文件/comment/commit message 一律繁體中文。
- `wm4n/skill-registry`、`wm4n/openab`(這個 repo 的 origin,fork)commit/
  push 一律用 **wm4n** GitHub 帳號,不用 cac-william(既有慣例)。
- **本機沒有 k3s 叢集存取權**(`kubectl get nodes` 會連線失敗)——任何
  `kubectl exec`/`helm upgrade` 步驟只能寫成交給人類執行的指令,不能在本
  session 直接跑。
- **`deployment-guides/bot-skills/` 不是 skill 的真相來源**——只改這個
  openab repo 不會讓 Rick 的能力真的改變,真相來源是
  `wm4n/skill-registry` repo 的 `plugins/openab-bot-skills/skills/`。
- Rick 已有 `usercronEnabled: true`、已裝 `jira-fetch`(`skill-registry`
  plugin)與 `openab-schedule`(`openab-bot-skills` plugin)——**不要**重複
  加這些步驟。
- `jira-grill` 貼的每則 Jira comment 結尾簽名固定為
  `— By Rick (jira-grill)`(不是 persona 其他情境用的 `— By Rick`),這是
  no-op 判斷的機器可辨識依據,不可更動格式。
- Jira label 狀態機:`grill-me` → `grill-me-active` → `grill-me-done`。
- discovery/per-ticket 自動建立、刪除 cron job entry 時**直接讀寫**
  `~/.openab/cronjob.toml`,不套用 `openab-schedule` 文件裡「先跟人類
  確認卡片」那段互動流程(人類已透過核准 spec 一次性授權)。
- 不寫真實 token 進任何檔案/聊天記錄(既有 `BOT_SETUP.md` 慣例)。

---

### Task 1: `wm4n/skill-registry` — 新增 `jira-grill` skill,bump 版本,push

**Files:**
- Create: `plugins/openab-bot-skills/skills/jira-grill/SKILL.md`
  (repo:`/Users/william.chao/workspace/github/skill-registry`)
- Modify: `plugins/openab-bot-skills/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

**Interfaces:**
- Consumes:無前置 Task。
- Produces:`wm4n/skill-registry` 上有可被 `claude plugin marketplace
  update` 拉到的新版 `openab-bot-skills`(version `1.4.0`),內含
  `jira-grill` skill,可被 Rick 用裸名 `jira-grill` 呼叫(比照
  `feature-development`/`repo-identity` 的既有慣例)。

- [ ] **Step 1: 確認 gh 帳號、repo 是最新**

```bash
cd /Users/william.chao/workspace/github/skill-registry
gh auth switch --hostname github.com --user wm4n
git status --short   # 應為空,若有未預期的變更先處理,不要覆蓋
git pull
```

Expected:`git status --short` 空白(或只有既有未追蹤檔案,不要動它們);
`git pull` 顯示 `Already up to date.` 或成功 fast-forward。

- [ ] **Step 2: 建立 skill 目錄與 SKILL.md**

```bash
mkdir -p plugins/openab-bot-skills/skills/jira-grill
cat > plugins/openab-bot-skills/skills/jira-grill/SKILL.md <<'SKILLEOF'
---
name: jira-grill
argument-hint: "discover | ticket <JIRA-ticket-id>"
description: >-
  Rick 專屬、獨立於三 bot 接力 pipeline 之外的 Jira 需求審視能力。Jira 票貼上
  grill-me label 後，套用 mattpocock-skills:grilling 的 design-tree/frontier
  方法論對需求連續提問；提問與回答都透過 Jira comment 進行。靠 openab 的
  usercron（同一個 cron job 重複觸發永遠落在同一個 Discord thread、延續同一個
  ACP session）讓每張票的問答自成一條可長期接續的對話。收斂或人類喊停後貼出
  結論、通知人類，不自動進入開發、不自動交棒給任何 bot。
---

# Jira Grill

Jira 是唯一真相來源：每次執行都重新從 Jira 撈完整內容與留言判斷目前進度，
不依賴 session 記憶本身的正確性。Session 延續只是效率紅利。

## 兩種觸發模式（`$ARGUMENTS`）

- `discover`：由固定的 discovery cron job 呼叫，找出新貼 `grill-me` label
  的票並啟動它們。
- `ticket <TICKET_ID>`：由該票專屬的 cron job 呼叫，檢查這張票是否有新回覆
  並推進下一輪。

## 環境變數

- `JIRA_TOKEN` / `JIRA_EMAIL` / `JIRA_BASE_URL`：同 `jira-fetch` skill。
- `JIRA_GRILL_CHANNEL`：discovery job 建立 per-ticket cron job 時要用的
  Discord channel ID（Rick 既有頻道）。

執行前用與 `jira-fetch` 相同的方式確認三個 Jira 變數存在（`${VAR:+set}`
寫法，不要用 skill frontmatter 的 load-time inline shell 檢查，會被權限層
擋下）：

```bash
echo "JIRA_TOKEN: ${JIRA_TOKEN:+set}"
echo "JIRA_EMAIL: ${JIRA_EMAIL:+set}"
echo "JIRA_BASE_URL: ${JIRA_BASE_URL:+set}"
echo "JIRA_GRILL_CHANNEL: ${JIRA_GRILL_CHANNEL:+set}"
```

任一缺少：說明缺什麼變數並停止，不繼續嘗試。

## Jira API 慣例

沿用 `jira-fetch` 的寫法：`curl -u "${JIRA_EMAIL}:${JIRA_TOKEN}"` 做 Basic
Auth，一律用 `node -e` 解析/組 JSON，不假設 `jq`／`python3`／GNU-only
coreutils 存在。讀票內容與留言一律呼叫 `jira-fetch` skill（`jira-fetch
<TICKET_ID> --comments 50`），不要自己重寫一份讀取邏輯。

以下三個動作是 `jira-fetch` 沒有的，本 skill 自己實作：

### 改 label

```bash
# 範例：把 grill-me 換成 grill-me-active（收斂/中止時把 grill-me-active
# 換成 grill-me-done，remove/add 的值換掉即可）
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
  -X PUT "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}" \
  -H "Content-Type: application/json" \
  -d '{"update":{"labels":[{"remove":"grill-me"},{"add":"grill-me-active"}]}}')
if [ "$STATUS" != "204" ]; then
  echo "ERROR: 改 label 失敗（HTTP ${STATUS}），停止處理這張票，留給下次 discovery/poll 重試。"
fi
```

### 貼 comment

```bash
# COMMENT_BODY 是要貼的完整文字（含結尾簽名，見下方「Grilling 提問格式」）
node -e '
const body = process.argv[1];
process.stdout.write(JSON.stringify({ body }));
' "$COMMENT_BODY" > /tmp/jira-grill-comment.json

STATUS=$(curl -s -o /dev/null -w '%{http_code}' -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
  -X POST "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}/comment" \
  -H "Content-Type: application/json" \
  -d @/tmp/jira-grill-comment.json)
if [ "$STATUS" != "201" ]; then
  echo "ERROR: 貼 comment 失敗（HTTP ${STATUS}）。"
fi
```

### JQL 搜尋（只有 discovery 流程用）

```bash
JQL='labels = "grill-me" AND labels != "grill-me-active"'
ENCODED_JQL=$(node -e 'console.log(encodeURIComponent(process.argv[1]))' "$JQL")
RESPONSE=$(curl -s -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
  -w '\n%{http_code}' \
  "${JIRA_BASE_URL}/rest/api/2/search?jql=${ENCODED_JQL}&fields=key")

printf '%s' "$RESPONSE" | node -e '
const raw = require("fs").readFileSync(0, "utf8");
const nl = raw.lastIndexOf("\n");
const status = raw.slice(nl + 1).trim();
const body = raw.slice(0, nl);
if (status !== "200") { console.log("ERROR: JQL 搜尋失敗（HTTP " + status + "）"); process.exit(0); }
const issues = (JSON.parse(body).issues) || [];
if (!issues.length) { console.log("(no new tickets)"); process.exit(0); }
for (const i of issues) console.log(i.key);
'
```

沒有搜到任何票 → 印出 `(no new tickets)` 後直接結束，不做任何其他動作
（no-op，控制成本）。

## 流程一：Discovery（`$ARGUMENTS = discover`）

1. 確認環境變數（含 `JIRA_GRILL_CHANNEL`）。
2. 執行上面的 JQL 搜尋，取得所有符合的 `TICKET_ID` 清單。清單為空就結束。
3. 對每個 `TICKET_ID` 依序：
   a. 呼叫 `jira-fetch ${TICKET_ID} --comments 50` 取得標題/描述/驗收條件/
      現有留言。
   b. 把 label 從 `grill-me` 換成 `grill-me-active`（改 label 失敗 → 跳過
      這張票，印出錯誤，繼續下一張，不建立 cron job，留給下次 discovery
      重試）。
   c. 用 grilling 方法論，以描述+驗收條件為輸入，產出第一輪 frontier
      問題（見下方「Grilling 提問格式」），貼成第一則 comment。
   d. 用 `openab-schedule` skill 的 `[[jobs]]` TOML 語法（**不要**套用它
      文件裡「先跟人類確認卡片」那段流程——discovery 是無人在場的自動
      觸發，人類已經透過核准這份 spec 一次性授權這套自動建立/清理 job
      的行為），在 `~/.openab/cronjob.toml` 新增：
      ```toml
      [[jobs]]
      id = "jira-grill-<TICKET_ID>"
      enabled = true
      schedule = "*/10 * * * *"
      channel = "<JIRA_GRILL_CHANNEL 的值>"
      message = "執行 jira-grill skill，參數：ticket <TICKET_ID>"
      sender_name = "jira-grill-<TICKET_ID>"
      timezone = "Asia/Taipei"
      ```
      讀取既有檔案內容、保留其他 job，只新增這一筆（絕不覆蓋整個檔案）。
4. 全部處理完，不需要額外摘要輸出（discovery thread 本身沒有人在看）。

## 流程二：Per-ticket（`$ARGUMENTS = ticket <TICKET_ID>`）

1. 確認環境變數。
2. 呼叫 `jira-fetch ${TICKET_ID} --comments 50`，取得完整內容（含
   labels、全部留言，留言依 `jira-fetch` 慣例新到舊排序）。
3. **中止訊號 1（label 被人類改掉）**：若回傳的 labels 不含
   `grill-me-active`，視為人類已手動中止 → 跳到步驟 6b。
4. **判斷有沒有新回覆**：看留言區塊最上面（最新）那一則，若內容包含
   Rick 自己的簽名標記 `— By Rick (jira-grill)` → 目前最新一則是 Rick
   自己貼的，代表還沒有新回覆 → 直接結束（no-op，不做任何 Jira 呼叫以外
   的動作，這是最常見的情況，要盡量精簡輸出以控制成本）。若最新一則不含
   這個標記 → 有新回覆，繼續步驟 5。
5. **中止訊號 2（人類文字喊停）**：若步驟 4 判定的新回覆內容明確表達停止
   意圖（例如「先這樣」「夠了」「不用再問了」「停止」「stop」「that's
   enough」「no more questions」等同義表達，靠語意判斷、不是精確關鍵字
   比對）→ 跳到步驟 6b（人類中止，非自然收斂）。否則視為對上一輪 frontier
   的回答，依 grilling 方法論用完整留言串重新計算 design tree：
   - 還有未決分支 → 產出下一輪 frontier 問題，貼成新 comment（格式見下），
     結尾附「目前還有 N 個分支未決」的進度摘要 → 結束（label、cron job
     都不動）。
   - Frontier 已清空（雙方對需求達成共識）→ 跳到步驟 6a。
6. **收斂/中止收尾**（6a 自然收斂 / 6b 人類中止，兩者都要做完下面全部）：
   a. 自然收斂：貼一則「✅ 需求共識」comment，把整輪問答蒸餾成結構化的
      最終需求描述（背景、確認的需求範圍、驗收條件），附簽名。
      人類中止：貼一則「🛑 已中止 grill-me（人類要求停止）」comment，
      簡述目前已釐清到哪裡、還有哪些分支未決，附簽名。
      兩者都在文末加一行 plain-text 提及
      `@{reporter 的 displayName} @{assignee 的 displayName}`（純文字，
      不是真正會觸發通知的 Jira `[~accountId]` mention——見「已知限制」）。
   b. 把 label 從 `grill-me-active` 換成 `grill-me-done`。
   c. 讀 `~/.openab/cronjob.toml`，移除 `id = "jira-grill-<TICKET_ID>"`
      這個 `[[jobs]]` 區塊（保留其他 job），寫回檔案——這張票不再需要
      輪詢。

## Grilling 提問格式

沿用 `mattpocock-skills:grilling` 的格式，每一輪的所有 frontier 問題合併
成同一則 comment：

```
❓ **Q1** - **<問題標題>**：<問題內容，可多段、可列選項>

➡️ <你的建議答案>

❓ **Q2** - **<問題標題>**：<問題內容>

➡️ <你的建議答案>

---
目前還有 {N} 個分支未決。

— By Rick (jira-grill)
```

第一輪（`grill-me` 剛被偵測到、還沒有任何人類回覆）以 Jira 票本身的標題、
描述、驗收條件為輸入直接產出 frontier；不要等留言。

**簽名規則**：本 skill 貼的每一則 comment（提問、收斂、中止）結尾都必須是
`— By Rick (jira-grill)`（注意：不是 persona 檔裡其他情境用的
`— By Rick`，多了 `(jira-grill)` 是本 skill 判斷「新回覆 vs 自己的舊留言」
的機器可辨識依據，改了會讓 no-op 判斷失效，造成同一輪問題重複問或漏判新
回覆）。

## 已知限制

- **收斂/中止通知不是真正的 Jira @mention**：只是純文字寫 reporter/
  assignee 的 displayName，不是會觸發 Jira 通知的 `[~accountId]` 語法。
  實務上 Jira 預設會對「有新留言」通知 reporter/assignee/watcher，這則
  純文字提及只是方便人類在畫面上找到自己，不是通知機制本身。
- **中止訊號辨識靠語意判斷**，不是精確關鍵字比對，極端措辭可能誤判——但
  收斂/中止都會留下明確的 comment 記錄，人類事後可查、可用 label 手動
  介入（把 label 改回 `grill-me` 會被下次 discovery 當成全新票重新處理，
  這是可接受的行為，不是 bug）。
- **成本隨並行票數線性增加**：每張正在 grill 的票每 10 分鐘觸發一次
  agent 推理（多數是「沒有新留言→no-op」的低成本輸出），票數一多會累積
  明顯的 Claude 用量。
- **`--comments 50` 是硬上限**：單張票的往返超過 50 則留言會讓最早的
  歷史看不到；純粹靠 Jira 留言串本身作為真相來源，理論上仍可能因為超過
  這個上限而遺漏極早期的脈絡，但一輪 grilling 通常遠低於 50 則留言，
  接受此限制。
- **JQL/label 慣例依賴 Jira 實例設定**：若組織的 label 使用慣例、Jira
  帳號權限範圍與本設計假設不同，discovery 的 JQL 需要對應調整。
SKILLEOF
```

Expected:`ls plugins/openab-bot-skills/skills/jira-grill/SKILL.md` 印出
該檔案路徑。

- [ ] **Step 3: bump `plugin.json` 版本**

```bash
node -e '
const fs = require("fs");
const p = "plugins/openab-bot-skills/.claude-plugin/plugin.json";
const j = JSON.parse(fs.readFileSync(p, "utf8"));
if (j.version !== "1.3.6") { console.error("ERROR: 版本不是預期的 1.3.6，現在是 " + j.version + "，先確認是否有其他人已經改過再繼續"); process.exit(1); }
j.version = "1.4.0";
fs.writeFileSync(p, JSON.stringify(j, null, 2) + "\n");
'
cat plugins/openab-bot-skills/.claude-plugin/plugin.json
```

Expected:`version` 欄位變成 `"1.4.0"`,其他欄位不變。

- [ ] **Step 4: 同步 bump `marketplace.json` 裡 `openab-bot-skills` 條目版本**

```bash
node -e '
const fs = require("fs");
const p = ".claude-plugin/marketplace.json";
const j = JSON.parse(fs.readFileSync(p, "utf8"));
const entry = j.plugins.find(x => x.name === "openab-bot-skills");
if (!entry) { console.error("ERROR: 找不到 openab-bot-skills 條目"); process.exit(1); }
if (entry.version !== "1.3.6") { console.error("ERROR: 版本不是預期的 1.3.6，現在是 " + entry.version); process.exit(1); }
entry.version = "1.4.0";
fs.writeFileSync(p, JSON.stringify(j, null, 2) + "\n");
'
cat .claude-plugin/marketplace.json
```

Expected:`plugins` 陣列裡 `name: "openab-bot-skills"` 條目的 `version`
變成 `"1.4.0"`,`skill-registry`/`solo-bot-skills`/`mac-disk-cleanup`
三個條目不變。

- [ ] **Step 5: commit + push**

```bash
git add plugins/openab-bot-skills/skills/jira-grill/SKILL.md \
        plugins/openab-bot-skills/.claude-plugin/plugin.json \
        .claude-plugin/marketplace.json
git commit -m "feat(openab-bot-skills): 新增 jira-grill skill

Rick 專屬、獨立於三 bot pipeline 之外：Jira 票貼 grill-me label 後，用
grilling 方法論連續提問，問答走 Jira comment，靠 usercron 讓同一張票
接續同一個 ACP session。bump 至 1.4.0。"
git push origin main
```

Expected:push 成功,無 conflict。

- [ ] **Step 6: 驗證 push 內容可公開讀到**

```bash
curl -s https://raw.githubusercontent.com/wm4n/skill-registry/main/plugins/openab-bot-skills/skills/jira-grill/SKILL.md | head -5
curl -s https://raw.githubusercontent.com/wm4n/skill-registry/main/.claude-plugin/marketplace.json | node -e '
const j = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(j.plugins.find(x => x.name === "openab-bot-skills").version);
'
```

Expected:第一個指令印出 SKILL.md frontmatter 前幾行;第二個指令印出
`1.4.0`。

---

### Task 2: `openab` repo — Rick 的 `values-openab-claude.yaml` 加 JIRA 認證與 channel 設定

**Files:**
- Modify: `deployment-guides/k3s/values-openab-claude.yaml`(Rick 區塊,
  第 23–53 行)

**Interfaces:**
- Consumes:無(可與 Task 1 平行進行,兩者互不依賴)。
- Produces:Rick 的 Helm values 具備 `JIRA_TOKEN`/`JIRA_BASE_URL`/
  `JIRA_EMAIL`/`JIRA_GRILL_CHANNEL`,供 Task 4 `helm upgrade` 使用。

- [ ] **Step 1: 確認目前分支與 Rick 區塊現況**

```bash
cd /Users/william.chao/workspace/ai/openab
git status --short
git branch --show-current   # 應為 docs/three-bot-pipeline
sed -n '23,53p' deployment-guides/k3s/values-openab-claude.yaml
```

Expected:目前分支是 `docs/three-bot-pipeline`;Rick 區塊目前沒有
`secretEnv`,`env:` 只有 `PATH`/`HANDOFF_REVIEWER_MORTY`/
`HANDOFF_REVIEWER_SUMMER` 三筆。

- [ ] **Step 2: 加入 `JIRA_GRILL_CHANNEL` 到 `env:`,加入 `secretEnv:`**

用 Edit 工具(或等效的精準字串替換)修改 Rick 區塊,把:

```yaml
    env:
      PATH: "/home/node/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      HANDOFF_REVIEWER_MORTY: "<@1521431781641818202>"
      HANDOFF_REVIEWER_SUMMER: "<@1522253638465093752>"
    discord:
```

改成:

```yaml
    env:
      PATH: "/home/node/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      HANDOFF_REVIEWER_MORTY: "<@1521431781641818202>"
      HANDOFF_REVIEWER_SUMMER: "<@1522253638465093752>"
      # jira-grill skill 用：discovery job 建立 per-ticket cron job 時要指定的頻道。
      JIRA_GRILL_CHANNEL: "1528965074562191420" # cac-dev-team
    discord:
```

再把 `secretEnv:` 插在 Rick `discord:` 區塊之後、`cron:` 之前(與 Morty
區塊的欄位順序一致:`discord` → `secretEnv` → `cron` → `pool` →
`persistence`),複用同一個 `morty-jira` K8s Secret:

```yaml
    discord:
      enabled: true
      allowedChannels: ["1528965074562191420", "1528965173761802420"] # cac-dev-team, cac-notify
      allowedUsers: ["824092654060830770"] # 空=允許頻道內任何人
      allowBotMessages: "mentions" # bot 互呼（Part K）
      trustedBotIds: ["1521431781641818202", "1522253638465093752"] # Morty, Summer
      allowedRoleIds: ["1528997914049777764"] # CAC-Builder（Part M）
    # Rick 的 JIRA 認證（jira-grill skill 用）：複用既有 morty-jira K8s
    # Secret，不新建。secretEnv 會 valueFrom.secretKeyRef 注入，並自動把
    # 這些 key 加進 config 的 inherit_env。
    secretEnv:
      - { name: JIRA_TOKEN, secretName: morty-jira, secretKey: JIRA_TOKEN }
      - {
          name: JIRA_BASE_URL,
          secretName: morty-jira,
          secretKey: JIRA_BASE_URL,
        }
      - { name: JIRA_EMAIL, secretName: morty-jira, secretKey: JIRA_EMAIL }
    # usercron：cronjob.toml 熱重載排程（openab-schedule skill 用）；
    # 路徑相對 $HOME/.openab/，落在下面的 PVC 上，pod 重啟不會丟。
    cron:
      usercronEnabled: true
      usercronPath: "cronjob.toml"
    pool:
      maxSessions: 5
      sessionTtlHours: 24
```

- [ ] **Step 3: 驗證改動**

```bash
sed -n '23,60p' deployment-guides/k3s/values-openab-claude.yaml
```

Expected:看到 `JIRA_GRILL_CHANNEL` 在 `env:` 下、`secretEnv:` 三筆
`JIRA_*` 在 `cron:` 之後、`pool:` 之前;YAML 縮排與 Morty 區塊風格一致
(2 space)。

- [ ] **Step 4: commit**

```bash
git add deployment-guides/k3s/values-openab-claude.yaml
git commit -m "feat(k3s): Rick 加上 jira-grill 用的 JIRA 認證與頻道設定

複用既有 morty-jira K8s Secret，不新建；JIRA_GRILL_CHANNEL 供
discovery job 建立 per-ticket cron job 時指定頻道用。"
```

Expected:commit 成功。

---

### Task 3: `openab` repo — `Rick-CLAUDE_v2.md` 指路 + `BOT_SETUP.md` 同步

**Files:**
- Modify: `deployment-guides/Rick-CLAUDE_v2.md`
- Modify: `deployment-guides/BOT_SETUP.md`

**Interfaces:**
- Consumes:無(可與 Task 1、Task 2 平行進行)。
- Produces:Rick 的 persona 檔知道有這個新能力;`BOT_SETUP.md` runbook
  反映最新建置步驟,供之後重建/troubleshoot 對照。

- [ ] **Step 1: 在 `Rick-CLAUDE_v2.md` 加入 jira-grill 說明段落**

在檔案「## 4. 技能模式切換 (Mode & Skills)」段落之後、「## 5. 工程實踐
原則」之前插入新的一節:

```markdown
## 4a. Jira Grill(獨立能力,與三 bot pipeline 無關)

Jira 票被貼上 `grill-me` label 時,會有 `jira-grill` skill 的
discovery/per-ticket cron job 自動觸發你去審視這張票的需求——這**不是**
被人類 @mention,而是排程觸發,執行時依 `jira-grill` skill 的指示行動
(`discover` 或 `ticket <TICKET_ID>` 兩種參數)。

- 這條能力完全獨立於本檔其他章節描述的三 bot 接力 pipeline,不取代、不
  影響 Morty 既有的 JIRA 需求分析角色。
- 提問與回答都透過 Jira comment 進行,不在 Discord 對話。
- 達成需求共識或人類喊停後,只貼 comment 通知人類,**不**自動開始開發、
  不自動 @ 任何 bot——後續要不要進 PR 開發模式,由人類另外明確要求。
- 本節不影響第 2 節「絕對鐵則」的任何規定(worktree 隔離不適用,因為
  這條能力完全不碰程式碼/repo)。

詳細流程見 `jira-grill` skill。
```

- [ ] **Step 2: 驗證 `Rick-CLAUDE_v2.md` 改動**

```bash
grep -n "^## 4a\|^## 5\." deployment-guides/Rick-CLAUDE_v2.md
```

Expected:`## 4a. Jira Grill` 出現在 `## 5. 工程實踐原則` 之前。

- [ ] **Step 3: 更新 `BOT_SETUP.md`**

在 Part K3(Rick 的建置步驟)裡「**skill 安裝**」那個 code block 之後,
「**CLAUDE.md**」那段之前,插入:

```markdown
**jira-grill(獨立能力,2026-08-24 新增)**:掛在 Rick 已裝的
`openab-bot-skills` plugin 裡(來源 `wm4n/skill-registry`
repo,`plugins/openab-bot-skills/skills/jira-grill/`),不需要額外
`plugin install`,`plugin marketplace update` +
`plugin update openab-bot-skills@wm4n-skill-registry` 就會拉到。需要
額外在 Rick 的 `values-openab-claude.yaml` 補 `secretEnv`
(`JIRA_TOKEN`/`JIRA_BASE_URL`/`JIRA_EMAIL`,複用 `morty-jira` Secret)
與 `env.JIRA_GRILL_CHANNEL`,`helm upgrade` 後才會生效。設計依據見
`docs/superpowers/specs/2026-08-24-rick-jira-grill-design.md`、實作
計畫見 `docs/superpowers/plans/2026-08-24-rick-jira-grill.md`。
```

- [ ] **Step 4: 驗證 `BOT_SETUP.md` 改動**

```bash
grep -n "jira-grill" deployment-guides/BOT_SETUP.md
```

Expected:至少一行命中,在 Part K3 區塊內。

- [ ] **Step 5: commit**

```bash
git add deployment-guides/Rick-CLAUDE_v2.md deployment-guides/BOT_SETUP.md
git commit -m "docs: Rick 加入 jira-grill 指路說明，同步 BOT_SETUP.md runbook"
```

Expected:commit 成功。

---

### Task 4: 部署(需要人類/有 k3s 存取權的 session 執行)

**Files:** 無(純操作,在 k3s 主機或有 `kubectl` context 的機器上執行)

**Interfaces:**
- Consumes:Task 1(skill-registry 已 push 新版)、Task 2(values.yaml 已
  改)、Task 3(persona/runbook 已同步)。
- Produces:Rick 的 pod 讀得到 `JIRA_TOKEN`/`JIRA_BASE_URL`/`JIRA_EMAIL`/
  `JIRA_GRILL_CHANNEL`,且 skill 清單裡有 `jira-grill`。

> ⚠️ 本 session 的開發機沒有這個 k3s 叢集的 `kubectl` 存取權
> (`kubectl get nodes` 連線失敗),以下步驟寫給人類或另一個有叢集存取權
> 的 session 執行,無法在本 session 代跑。

- [ ] **Step 1: 確認 `morty-jira` Secret 存在(在 `cac` namespace)**

```bash
kubectl get secret morty-jira -n cac
```

Expected:看到該 Secret 存在。若不存在,參考 `K3S.md` A4 節重建。

- [ ] **Step 2: `helm upgrade` 讓 Task 2 的 values 改動生效**

```bash
cd <k3s values 檔所在目錄，通常是 deployment-guides/k3s/>
helm upgrade openab-claude oci://ghcr.io/openabdev/charts/openab -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml
kubectl rollout status deployment/openab-claude-rick -n cac
```

Expected:`rollout status` 顯示 `successfully rolled out`。

- [ ] **Step 3: 驗證 Rick pod 讀得到新環境變數**

```bash
kubectl exec deployment/openab-claude-rick -n cac -- env | grep -E "JIRA_TOKEN|JIRA_BASE_URL|JIRA_EMAIL|JIRA_GRILL_CHANNEL"
```

Expected:四個變數都印出且有值(`JIRA_TOKEN` 只需看到有值,不用核對內容)。

- [ ] **Step 4: 更新 Rick 的 plugin,拉到 Task 1 的新版 `jira-grill`,並裝上
  `mattpocock-skills`(jira-grill 引用它的 `grilling` skill 做連續提問,
  不是重複實作)**

```bash
kubectl exec deployment/openab-claude-rick -n cac -- gh auth switch --hostname github.com --user cac-william
kubectl exec deployment/openab-claude-rick -n cac -- claude plugin marketplace update wm4n-skill-registry
kubectl exec deployment/openab-claude-rick -n cac -- claude plugin update openab-bot-skills@wm4n-skill-registry
kubectl exec deployment/openab-claude-rick -n cac -- claude plugin install mattpocock-skills@claude-plugins-official || true
kubectl exec deployment/openab-claude-rick -n cac -- claude plugin update mattpocock-skills@claude-plugins-official
kubectl exec deployment/openab-claude-rick -n cac -- cat /home/node/.claude/plugins/installed_plugins.json | grep -A3 openab-bot-skills
kubectl exec deployment/openab-claude-rick -n cac -- cat /home/node/.claude/plugins/installed_plugins.json | grep -A3 mattpocock-skills
```

Expected:`openab-bot-skills` 印出的版本是 `1.4.1`(Task 1 產出
`1.4.0`,之後依 `superpowers:writing-for-agents` review 精煉內容、修正
「引用未安裝的 mattpocock-skills」問題,bump 到 `1.4.1`,見
`wm4n/skill-registry` commit `04bce5e`);`mattpocock-skills` 有安裝紀錄
(版本不拘,只要存在)。

- [ ] **Step 5: 更新 Rick 的 persona 檔(Task 3 的 `Rick-CLAUDE_v2.md` 改動)**

```bash
kubectl exec deployment/openab-claude-rick -n cac -- sh -c '
  cd /home/node/github-repo/openab &&
  git fetch origin docs/three-bot-pipeline &&
  git checkout docs/three-bot-pipeline && git pull &&
  cat deployment-guides/Rick-CLAUDE_v2.md > /home/node/CLAUDE.md &&
  grep -c "jira-grill" /home/node/CLAUDE.md'
```

Expected:最後一行 grep 印出 `>= 1`(確認新段落真的寫進去了)。

- [ ] **Step 6: 建立 discovery cron job**

Discord 對 Rick 開一條新 thread(讓新 CLAUDE.md/skill 生效),請 Rick
直接把 discovery job 寫進 `~/.openab/cronjob.toml`(比照 Task 1
SKILL.md「流程一」的 TOML 範例,`id = "jira-grill-discovery"`,
`schedule = "*/10 * * * *"`,`message = "執行 jira-grill skill，參數：
discover"`),或由人類直接 `kubectl exec` 寫入:

```bash
kubectl exec deployment/openab-claude-rick -n cac -- sh -c '
cat >> ~/.openab/cronjob.toml <<TOMLEOF

[[jobs]]
id = "jira-grill-discovery"
enabled = true
schedule = "*/10 * * * *"
channel = "1528965074562191420"
message = "執行 jira-grill skill，參數：discover"
sender_name = "jira-grill-discovery"
timezone = "Asia/Taipei"
TOMLEOF
cat ~/.openab/cronjob.toml'
```

Expected:輸出可看到新增的 `[[jobs]]` 區塊,且沒有覆蓋掉原本已存在的其他
job(先前若有其他 job,输出裡應該還在)。

---

### Task 5: 端對端驗證(需要一張真實可拋棄的 Jira 測試票)

**Files:** 無(純操作驗證)

**Interfaces:**
- Consumes:Task 4 全部完成。
- Produces:確認整條 discovery → 第一輪提問 → 回覆 → 下一輪 → 收斂 →
  自我清理 的流程真的能跑通。

- [ ] **Step 1: 準備一張測試票**

在 Jira 上建立(或挑一張可拋棄的)測試票,標題與描述隨意但要有明確的
模糊點(方便觀察 grilling 提出追問),記下票號 `TEST-KEY`。

- [ ] **Step 2: 貼上 `grill-me` label,等待 discovery 撿到**

手動在該票貼上 `grill-me` label。等待最多 10 分鐘(discovery job 排程
間隔)。

Expected:
1. 票的 label 變成 `grill-me-active`。
2. 票上出現一則結尾 `— By Rick (jira-grill)` 的 comment,含至少一個
   `❓ Q1` 格式的問題。
3. `kubectl exec deployment/openab-claude-rick -n cac -- grep -A6
   "jira-grill-TEST-KEY" ~/.openab/cronjob.toml` 能看到該票專屬的
   cron job entry。

- [ ] **Step 3: 回覆其中一個問題,等待下一輪觸發**

在該 Jira 票下方用真人帳號回覆 Rick 提出的其中一個問題。等待最多 10
分鐘(per-ticket job 排程間隔)。

Expected:票上出現 Rick 的下一則 comment——如果剛回答的問題有解鎖後續
分支,看到新一輪 `❓` 提問;如果沒有更多分支,直接看到「✅ 需求共識」
comment。

- [ ] **Step 4: 把剩下問題都回答完,驗證收斂與自我清理**

持續回覆,直到看到「✅ 需求共識」comment。

Expected:
1. 該 comment 結構化整理了需求,結尾附簽名與 reporter/assignee 的純
   文字提及。
2. 票的 label 變成 `grill-me-done`。
3. `kubectl exec deployment/openab-claude-rick -n cac -- grep
   "jira-grill-TEST-KEY" ~/.openab/cronjob.toml` **找不到**該行(entry
   已被移除)。

- [ ] **Step 5: 驗證中止路徑(可選,建議至少跑一次)**

另開一張測試票,重複 Step 1–2,收到第一輪提問後直接回覆「先這樣,夠了」
之類的喊停語句。

Expected:票上出現「🛑 已中止 grill-me」comment,label 變成
`grill-me-done`,cron job entry 被移除——行為與自然收斂一致,只是
comment 內容註明是人類中止。

- [ ] **Step 6: 回報結果**

把 Step 2–5 的實際觀察結果(截圖或文字紀錄皆可)整理成一則訊息回報給
人類,明確指出哪些步驟符合預期、哪些不符合,不要只說「測試通過」。

---

## Self-Review(對照 spec)

| Spec 需求 | 對應 Task |
|-----------|-----------|
| Discovery job(JQL 找新票、label 換 active、建 per-ticket job) | Task 1 SKILL.md「流程一」、Task 4 Step 6 |
| Per-ticket job(no-op / 下一輪 / 收斂 / 中止) | Task 1 SKILL.md「流程二」 |
| 每張票獨立 cron job + 獨立 thread(使用者選定架構) | Task 1 SKILL.md 流程一 Step 3d、Task 4 Step 6 |
| Grilling 提問格式 + 進度摘要 | Task 1 SKILL.md「Grilling 提問格式」 |
| 簽名機制作為 no-op 判斷依據 | Task 1 SKILL.md「簽名規則」 |
| 中止訊號(文字喊停 / label 改掉) | Task 1 SKILL.md 流程二 Step 3、5 |
| 收斂後只通知、不自動進開發 | Task 1 SKILL.md 流程二 Step 6a;`Rick-CLAUDE_v2.md` 新增段落 |
| label 狀態機 grill-me→active→done | Task 1 SKILL.md 全篇;Task 5 驗證 |
| Rick 加裝 JIRA 認證(secretEnv) | Task 2 |
| `JIRA_GRILL_CHANNEL` | Task 1 SKILL.md「環境變數」;Task 2 |
| skill 真相來源在 wm4n/skill-registry | Task 1 |
| Rick persona 指路 + BOT_SETUP.md 同步 | Task 3 |
| `helm upgrade` + plugin 更新生效 | Task 4 |
| openab-schedule 確認卡流程不適用 | Task 1 SKILL.md 流程一 Step 3d(明文寫死不套用) |
| 端對端驗證(discovery→提問→回覆→收斂/中止→清理) | Task 5 |
