# jira-grill 輪詢架構重寫:Deterministic Poller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 jira-grill 現行「Rick 每 10 分鐘用 LLM turn 檢查 Jira 有沒有新留言」的輪詢機制,換成一個獨立於 openab 之外、不經過 LLM 的 deterministic K8s CronJob 前置判斷,只有真的偵測到新票或人類新回覆才觸發 Rick。

**Architecture:** 新增一個獨立部署的 `jira-grill-poller`(K8s CronJob,重用 Rick 現有 image,無狀態,靠兩條獨立 JQL 判斷)+ 一個新註冊的 `jira-grill-trigger` Discord bot 負責觸發。Rick 的 `jira-grill` SKILL.md 合併成單一入口 `ticket <TICKET_ID>`,拿掉所有 `cronjob.toml` 讀寫與 no-op 輪詢判斷(移到 poller),保留 grilling 方法論本身不變。

**Tech Stack:** Bash + `node -e`(JSON 解析,沿用專案既有慣例)、K8s CronJob/ConfigMap/Secret、Jira REST API v2、Discord REST API v10。

**Spec:** `docs/superpowers/specs/2026-08-25-jira-grill-poller-design.md`

## Global Constraints

- Poller 完全無狀態:不寫本地檔案、不掛 PVC、不建立任何額外的 K8s 物件記錄進度。
- 不假設 `jq`/`python3`/GNU-only coreutils 存在;JSON 一律用 `node -e` 解析/組裝(沿用 `jira-fetch`/`jira-grill` 既有慣例)。
- Poller CronJob 重用 Rick 現有 image `ghcr.io/104corp/openab:0.9.0-claude-cli2.1.220` 與 `ghcr-104corp` imagePullSecret,不另外 build/維護新 image。
- Poller 部署在 `cac` namespace,跟 Rick 同一個,可直接引用既有 `morty-jira` Secret。
- `jira-grill-trigger` Discord bot 只需要「送訊息到指定頻道」的最小權限。
- 失敗處理原則:跳過、記錄、留給下一輪自然重試,不做重試迴圈、不做告警。
- SKILL.md 的合併流程只保留一個輕量簽名檢查作為重複觸發防護,不重新加回「每次都自己判斷有沒有新留言」的完整輪詢邏輯(那是 poller 的職責)。

---

### Task 1: `jira-grill-trigger` Discord bot + poller script + K8s 部署

**Files:**
- Create: `deployment-guides/k3s/jira-grill-poller/poller.sh`
- Create: `deployment-guides/k3s/jira-grill-poller/cronjob.yaml`

**Interfaces:**
- Produces:`poller.sh` 讀取的環境變數 `JIRA_TOKEN`/`JIRA_EMAIL`/`JIRA_BASE_URL`/`JIRA_GRILL_PROJECTS`/`JIRA_GRILL_CHANNEL`/`JIRA_GRILL_TRIGGER_BOT_TOKEN`/`RICK_DISCORD_USER_ID`(全部由 `cronjob.yaml` 注入)。Discord 觸發訊息格式:`<@{RICK_DISCORD_USER_ID}> 執行 jira-grill skill，參數：ticket <TICKET_ID>`——Task 3 改寫 SKILL.md 時要沿用這個字串格式當作觸發指令的解析依據。

- [ ] **Step 1: 人類操作——註冊 `jira-grill-trigger` Discord bot**

到 Discord Developer Portal(https://discord.com/developers/applications)開一個新的 bot application:
1. 建立新 Application,命名 `jira-grill-trigger`。
2. 進 Bot 頁籤,不需要打開任何 Privileged Gateway Intent(這個 bot 只送訊息,不讀訊息)。
3. 複製 Bot Token(等一下 Step 3 建 Secret 要用)。
4. 複製 Application 頁籤(或 Bot 頁籤)上的 **Application ID / User ID**(等一下 Task 2 要加進 Rick 的 `trustedBotIds`)。
5. 用 OAuth2 → URL Generator 產生邀請連結(勾 `bot` scope,權限只勾 `Send Messages`),把這個 bot 邀請進 Rick 所在的 Discord 伺服器。

記下 Bot Token 與 User ID,下面步驟會用到。

- [ ] **Step 2: 寫 `poller.sh`**

```bash
#!/bin/bash
#
# jira-grill-poller: deterministic 前置判斷，不經過 LLM。
# 用兩條獨立 JQL 分別找「新票」（無時間窗口）跟「進行中的票有沒有新回覆」
# （用 updated 時間窗口粗篩），只有真的需要處理才用 jira-grill-trigger
# bot 觸發 Rick。細節見 docs/superpowers/specs/2026-08-25-jira-grill-poller-design.md。

: "${JIRA_TOKEN:?missing JIRA_TOKEN}"
: "${JIRA_EMAIL:?missing JIRA_EMAIL}"
: "${JIRA_BASE_URL:?missing JIRA_BASE_URL}"
: "${JIRA_GRILL_PROJECTS:?missing JIRA_GRILL_PROJECTS}"
: "${JIRA_GRILL_CHANNEL:?missing JIRA_GRILL_CHANNEL}"
: "${JIRA_GRILL_TRIGGER_BOT_TOKEN:?missing JIRA_GRILL_TRIGGER_BOT_TOKEN}"
: "${RICK_DISCORD_USER_ID:?missing RICK_DISCORD_USER_ID}"

PROJECTS_CLAUSE=$(node -e '
const keys = process.env.JIRA_GRILL_PROJECTS.split(",").map(s => s.trim()).filter(Boolean);
console.log("project IN (" + keys.map(k => JSON.stringify(k)).join(",") + ")");
')

# $1 = JQL；印出符合的 ticket key，一行一個。搜尋失敗印錯誤到 stderr、成功但無結果不印任何東西。
jira_search() {
  ENCODED_JQL=$(node -e 'console.log(encodeURIComponent(process.argv[1]))' "$1")
  RESPONSE=$(curl -s -u "${JIRA_EMAIL}:${JIRA_TOKEN}" -w '\n%{http_code}' \
    "${JIRA_BASE_URL}/rest/api/2/search?jql=${ENCODED_JQL}&fields=key")
  printf '%s' "$RESPONSE" | node -e '
    const raw = require("fs").readFileSync(0, "utf8");
    const nl = raw.lastIndexOf("\n");
    const status = raw.slice(nl + 1).trim();
    const body = raw.slice(0, nl);
    if (status !== "200") {
      console.error("ERROR: JQL 搜尋失敗（HTTP " + status + "）");
      process.exit(0);
    }
    const issues = (JSON.parse(body).issues) || [];
    for (const i of issues) console.log(i.key);
  '
}

# $1 = TICKET_ID；在 JIRA_GRILL_CHANNEL 貼觸發訊息。
trigger_discord() {
  TICKET_ID="$1"
  BODY=$(node -e '
    const rickId = process.env.RICK_DISCORD_USER_ID;
    const ticket = process.argv[1];
    process.stdout.write(JSON.stringify({
      content: "<@" + rickId + "> 執行 jira-grill skill，參數：ticket " + ticket
    }));
  ' "$TICKET_ID")
  STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bot ${JIRA_GRILL_TRIGGER_BOT_TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST "https://discord.com/api/v10/channels/${JIRA_GRILL_CHANNEL}/messages" \
    -d "$BODY")
  if [ "$STATUS" != "200" ]; then
    echo "ERROR: 觸發 ${TICKET_ID} 失敗（Discord HTTP ${STATUS}）"
  else
    echo "已觸發 ${TICKET_ID}"
  fi
}

echo "== Query 1: 找新票（無時間窗口）=="
NEW_JQL="${PROJECTS_CLAUSE} AND labels = \"grill-me\""
NEW_TICKETS=$(jira_search "$NEW_JQL")
if [ -n "$NEW_TICKETS" ]; then
  echo "$NEW_TICKETS" | while IFS= read -r TICKET_ID; do
    [ -z "$TICKET_ID" ] && continue
    CLAIM_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
      -X PUT "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}" \
      -H "Content-Type: application/json" \
      -d '{"update":{"labels":[{"remove":"grill-me"},{"add":"grill-me-active"}]}}')
    if [ "$CLAIM_STATUS" != "204" ]; then
      echo "ERROR: 認領 ${TICKET_ID} 失敗（改 label HTTP ${CLAIM_STATUS}），跳過，下一輪重試"
      continue
    fi
    trigger_discord "$TICKET_ID"
  done
else
  echo "(無新票)"
fi

echo "== Query 2: 找進行中的票有沒有新回覆（updated >= -25m 粗篩）=="
ACTIVE_JQL="${PROJECTS_CLAUSE} AND labels = \"grill-me-active\" AND updated >= \"-25m\""
ACTIVE_TICKETS=$(jira_search "$ACTIVE_JQL")
if [ -n "$ACTIVE_TICKETS" ]; then
  echo "$ACTIVE_TICKETS" | while IFS= read -r TICKET_ID; do
    [ -z "$TICKET_ID" ] && continue
    RESPONSE=$(curl -s -u "${JIRA_EMAIL}:${JIRA_TOKEN}" -w '\n%{http_code}' \
      "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}/comment?orderBy=-created&maxResults=1")
    NEEDS_TRIGGER=$(printf '%s' "$RESPONSE" | node -e '
      const raw = require("fs").readFileSync(0, "utf8");
      const nl = raw.lastIndexOf("\n");
      const status = raw.slice(nl + 1).trim();
      const body = raw.slice(0, nl);
      if (status !== "200") {
        console.error("ERROR: 抓最新留言失敗（" + process.argv[1] + "，HTTP " + status + "）");
        console.log("skip");
        process.exit(0);
      }
      const comments = (JSON.parse(body).comments) || [];
      if (comments.length === 0) { console.log("trigger"); process.exit(0); }
      console.log(comments[0].body.includes("— By Rick (jira-grill)") ? "skip" : "trigger");
    ' "$TICKET_ID")
    if [ "$NEEDS_TRIGGER" = "trigger" ]; then
      trigger_discord "$TICKET_ID"
    fi
  done
else
  echo "(無需要處理的既有票)"
fi
```

- [ ] **Step 3: 人類操作——建立 K8s Secret**

```bash
kubectl create secret generic jira-grill-trigger-discord \
  -n cac \
  --from-literal=token='<Step 1 拿到的 Bot Token>'
```

- [ ] **Step 4: 寫 `cronjob.yaml`**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: jira-grill-poller-script
  namespace: cac
data:
  poller.sh: |
    # 內容貼上 Step 2 完整的 poller.sh（含開頭 #!/bin/bash）
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: jira-grill-poller
  namespace: cac
spec:
  schedule: "*/10 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 0
      template:
        spec:
          restartPolicy: Never
          imagePullSecrets:
            - name: ghcr-104corp
          containers:
            - name: poller
              image: "ghcr.io/104corp/openab:0.9.0-claude-cli2.1.220"
              command: ["/bin/bash", "/scripts/poller.sh"]
              env:
                - name: JIRA_TOKEN
                  valueFrom:
                    secretKeyRef:
                      name: morty-jira
                      key: JIRA_TOKEN
                - name: JIRA_EMAIL
                  valueFrom:
                    secretKeyRef:
                      name: morty-jira
                      key: JIRA_EMAIL
                - name: JIRA_BASE_URL
                  valueFrom:
                    secretKeyRef:
                      name: morty-jira
                      key: JIRA_BASE_URL
                - name: JIRA_GRILL_TRIGGER_BOT_TOKEN
                  valueFrom:
                    secretKeyRef:
                      name: jira-grill-trigger-discord
                      key: token
                - name: JIRA_GRILL_PROJECTS
                  value: "CACJOB,CACVIP,CACATS"
                - name: JIRA_GRILL_CHANNEL
                  value: "1528965173761802420" # cac-notify
                - name: RICK_DISCORD_USER_ID
                  value: "1519868630064562278" # Rick
              volumeMounts:
                - name: script
                  mountPath: /scripts
          volumes:
            - name: script
              configMap:
                name: jira-grill-poller-script
                defaultMode: 0755
```

把 `data.poller.sh` 的內容換成 Step 2 完整腳本(含開頭的 `#!/bin/bash` 那行、逐行縮排對齊 YAML block scalar)。

- [ ] **Step 5: 部署並手動觸發一次驗證**

```bash
cd deployment-guides/k3s/jira-grill-poller
kubectl apply -f cronjob.yaml
kubectl create job --from=cronjob/jira-grill-poller jira-grill-poller-manual-test -n cac
kubectl logs -n cac -l job-name=jira-grill-poller-manual-test --follow
```

Expected(此時尚未有任何 `grill-me`/`grill-me-active` 票):兩段都印
`(無新票)`/`(無需要處理的既有票)`,結尾正常結束(exit code 0),沒有
ERROR 訊息。

- [ ] **Step 6: 用測試票驗證四種情境**

在 Jira 上建一張(或重用一張既有的)測試票,依序驗證(每次驗證後重跑
Step 5 的 `kubectl create job --from=cronjob/...`,job name 要換一個
新名字避免衝突):

1. 貼上 `grill-me` label → 重跑 poller → 預期:log 印出「已觸發
   `<TICKET_ID>`」,Jira 上該票 label 變成 `grill-me-active`,
   `JIRA_GRILL_CHANNEL` 頻道出現一則 `jira-grill-trigger` bot 貼的
   `<@1519868630064562278> 執行 jira-grill skill，參數：ticket
   <TICKET_ID>` 訊息(因為 Task 2 還沒把這個 bot 加進 Rick 的
   `trustedBotIds`,Rick 這時不會真的處理,只驗證訊息有沒有正確送達)。
2. 手動在該票貼一則測試留言(內容含 `— By Rick (jira-grill)` 字樣,
   模擬 Rick 自己剛貼過)→ 重跑 poller → 預期:log 印
   `(無需要處理的既有票)` 或該票不出現在觸發清單裡(no-op)。
3. 手動在該票再貼一則**不含**簽名的留言(模擬人類新回覆)→ 重跑
   poller → 預期:再次觸發,頻道出現新一則觸發訊息。
4. 把該票 label 改回中性狀態(移除 `grill-me-active`,例如改成
   `grill-me-done`)→ 重跑 poller → 預期:兩段都不再處理這張票。

驗證完後清掉手動建立的 `jira-grill-poller-manual-test-*` job:
```bash
kubectl delete job -n cac -l job-name --field-selector 'status.successful=1' 2>/dev/null || true
```
(或直接 `kubectl get jobs -n cac | grep jira-grill-poller-manual-test` 逐一 `kubectl delete job <name> -n cac`)

- [ ] **Step 7: Commit**

```bash
git add deployment-guides/k3s/jira-grill-poller/
git commit -m "$(cat <<'EOF'
feat(k3s): 新增 jira-grill-poller deterministic CronJob

閒置時零 LLM 成本，只有偵測到新 grill-me 票或既有票的新回覆才觸發
Rick，取代原本每 10 分鐘用 LLM turn 輪詢的機制。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Rick 設定變更(`trustedBotIds` + 移除舊 env var)

**Files:**
- Modify: `deployment-guides/k3s/values-openab-claude.yaml:45-55`

**Interfaces:**
- Consumes:Task 1 Step 1 拿到的 `jira-grill-trigger` bot User ID。

- [ ] **Step 1: 移除 `JIRA_GRILL_CHANNEL`/`JIRA_GRILL_PROJECTS`,加入 `trustedBotIds`**

目前(`values-openab-claude.yaml:41-55`):

```yaml
    env:
      PATH: "/home/node/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      HANDOFF_REVIEWER_MORTY: "<@1521431781641818202>"
      HANDOFF_REVIEWER_SUMMER: "<@1522253638465093752>"
      # jira-grill skill 用：discovery job 建立 per-ticket cron job 時要指定的頻道。
      JIRA_GRILL_CHANNEL: "1528965173761802420" # cac-notify
      # jira-grill skill 用：discovery 只掃這些 project 的 grill-me label，
      # 避免跨專案誤觸發；要新增專案改這裡即可，不用改 skill 內容。
      JIRA_GRILL_PROJECTS: "CACJOB,CACVIP,CACATS"
    discord:
      enabled: true
      allowedChannels: ["1528965074562191420", "1528965173761802420", "1522271475552354394", "1526283579309690990"] # cac-dev-team, cac-notify, dev-bot(william workspace), bot-notify(william workspace)
      allowedUsers: ["824092654060830770"] # 空=允許頻道內任何人
      allowBotMessages: "mentions" # bot 互呼（Part K）
      trustedBotIds: ["1521431781641818202", "1522253638465093752"] # Morty, Summer
```

改成:

```yaml
    env:
      PATH: "/home/node/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      HANDOFF_REVIEWER_MORTY: "<@1521431781641818202>"
      HANDOFF_REVIEWER_SUMMER: "<@1522253638465093752>"
    discord:
      enabled: true
      allowedChannels: ["1528965074562191420", "1528965173761802420", "1522271475552354394", "1526283579309690990"] # cac-dev-team, cac-notify, dev-bot(william workspace), bot-notify(william workspace)
      allowedUsers: ["824092654060830770"] # 空=允許頻道內任何人
      allowBotMessages: "mentions" # bot 互呼（Part K）
      # jira-grill-poller（K8s CronJob，見 deployment-guides/k3s/jira-grill-poller/）
      # 判斷需要處理某張票時，用這個 bot 帳號 @mention Rick 觸發，取代舊的
      # cron 輪詢機制。
      trustedBotIds: ["1521431781641818202", "1522253638465093752", "<jira-grill-trigger 的 bot User ID>"] # Morty, Summer, jira-grill-trigger
```

`JIRA_GRILL_CHANNEL`/`JIRA_GRILL_PROJECTS` 不再被 SKILL 使用(移到
Task 1 的 `cronjob.yaml` 環境變數),整段刪除。`<jira-grill-trigger 的
bot User ID>` 換成 Task 1 Step 1 實際拿到的數值。

- [ ] **Step 2: Helm upgrade 並驗證**

```bash
cd deployment-guides/k3s
helm upgrade openab-claude oci://ghcr.io/openabdev/charts/openab --version 0.9.0-beta.1 -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml
kubectl rollout status deployment/openab-claude-rick -n cac
kubectl exec deployment/openab-claude-rick -n cac -- env | grep -c JIRA_GRILL
```

Expected:最後一行輸出 `0`(確認 `JIRA_GRILL_CHANNEL`/`JIRA_GRILL_PROJECTS`
已經不在 Rick 的環境變數裡了)。

- [ ] **Step 3: Commit**

```bash
git add deployment-guides/k3s/values-openab-claude.yaml
git commit -m "$(cat <<'EOF'
feat(k3s): Rick 信任 jira-grill-trigger bot，移除輪詢用的 env var

觸發機制改由 jira-grill-poller 驅動，JIRA_GRILL_CHANNEL/
JIRA_GRILL_PROJECTS 移到 poller 自己的 K8s manifest。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 改寫 `jira-grill` SKILL.md 為合併後的單一流程

**Files:**
- Modify: `plugins/openab-bot-skills/skills/jira-grill/SKILL.md`(repo `wm4n/skill-registry`,本機路徑 `/Users/william.chao/workspace/github/skill-registry/plugins/openab-bot-skills/skills/jira-grill/SKILL.md`)
- Modify: `plugins/openab-bot-skills/.claude-plugin/plugin.json`(同 repo)
- Modify: `.claude-plugin/marketplace.json`(同 repo)

**Interfaces:**
- Consumes:Task 1 定義的觸發訊息格式 `<@{RICK_DISCORD_USER_ID}> 執行 jira-grill skill，參數：ticket <TICKET_ID>`。
- Produces:`$ARGUMENTS` 只剩 `ticket <TICKET_ID>` 一種形式,`repo=<owner/repo>` 參數整個拿掉。

- [ ] **Step 1: 全文改寫 `SKILL.md`**

```markdown
---
name: jira-grill
argument-hint: "ticket <JIRA-ticket-id>"
description: >-
  Jira grill-me 需求審視。由獨立部署的 jira-grill-poller（K8s CronJob，
  不含 LLM）偵測到新票或人類新回覆後，用專用的 jira-grill-trigger bot
  @mention 觸發（不是人類 @mention、不在一般 Discord 對話）：先解析並準備
  好對應的 GitHub repo，再在 Jira comment 上用 grilling 式連續追問（design
  tree/frontier，見 mattpocock-skills:grilling），收斂或人類喊停後只貼
  結論通知人類，不自動開發、不交棒。獨立於三 bot 接力 pipeline。
---

# Jira Grill

Jira 是唯一真相來源：每次執行都重新從 Jira 撈完整內容與留言判斷目前進度，
不依賴 session 記憶本身的正確性。

## 觸發方式（`$ARGUMENTS`）

`ticket <TICKET_ID>`：由獨立部署的 `jira-grill-poller`（deterministic
K8s CronJob，見 `deployment-guides/k3s/jira-grill-poller/`）判斷這張票
需要處理後，用 `jira-grill-trigger` bot 貼出這個指令觸發。poller 已經
確認過這是真的新票或真的有新回覆，這裡不用再自己判斷要不要處理——只有
一個輕量防護例外，見下方流程步驟 3「重複觸發防護」。

## Repo 解析與準備

產出第一輪問題前，先確定這個需求要動到哪個 repo、把它準備好——grilling
要根據實際程式碼提問，不是憑空對需求文字發問。

**解析優先序**（比照 `requirement-analysis` skill，少了即時人類對話這個
管道）：

1. Jira 票的欄位（描述、custom field）裡有明確的 `owner/repo` 或 GitHub
   URL → 直接用。
2. 用 `product-context` skill 背後的登錄表解析：即時抓取（不 clone、不
   落地）：
   ```bash
   gh auth switch --hostname github.com --user cac-william
   gh api repos/104corp/104cac-product-registry/contents/products.yaml \
     -H "Accept: application/vnd.github.raw+json"
   ```
   以票號的 project key（`TICKET_ID` 連字號前的部分，如 `CACJOB-123` →
   `CACJOB`）比對各產品的 `jira.project`——這裡輸入是已知的 project
   key，不是 `product-context` 原本設計吃的「使用者自由語句比對
   name/aliases」，比對邏輯換掉，登錄表這個單一真相來源不換：
   - 命中單一產品、且該產品只有一個 repo → 直接用。
   - 命中單一產品但 `repos[]` 有多個（依 role，如 android/ios/backend）
     → 把「這個需求對應哪個 repo/平台」併入第一輪 frontier。
   - 命中多個產品共用同一個 project key、完全沒命中、或 `gh api` 抓取
     失敗（比照 `product-context` 自己的 edge case：不臆測、不中斷任務）
     → 都視為未解析，繼續步驟 3。
3. 都無法決定 → **repo 未定**。把「這個需求要動到哪個 repo？」併入第一輪
   frontier（跟其他問題貼在同一則 comment），當成一般 frontier 問題處理，
   不是特殊流程，等 Jira 回覆。

**repo 一旦確定，立刻準備**（比照 Rick 的「開工前準備」SOP）：

1. 用 `repo-identity` skill 依 owner 選 GitHub 帳號、`gh auth switch`。
2. Base clone 固定在 `/home/node/repos/<owner>/<repo>`：不存在就 clone，
   存在就 `git fetch`/`pull` 到最新。**只在 base clone 上讀，不建
   worktree**——這裡不改檔案、不切分支，不落入「repo 相關工作一律用
   worktree」那條鐵則要管的範圍。
3. 讀該 repo 的 `CLAUDE.md`/`AGENTS.md`、相關程式碼與既有實作，把查得到
   的事實（檔案結構、既有慣例、技術限制）寫進問題內容。你自己查得到的
   事實不該變成丟給人類的問題，只有真正的決策才問人類。

**每一輪都重新走一次這個優先序**（不快取解析結果）：解析成本本身很低，
重算比維護快取簡單——沒有 per-ticket cron job 的 message 可以拿來存
`repo=` 這種狀態了。

## 提問格式與簽名標記

沿用 `mattpocock-skills:grilling` 的 design tree/frontier 方法論：每輪只
問前提已經 settled 的問題（frontier），問完就等下一則留言；新留言到了才
重算下一輪 frontier；frontier 真正清空——每個分支都有明確答案，不是「問到
差不多就好」——才算收斂。

一輪的所有 frontier 問題合併成同一則 comment：

```
❓ **Q1** - **<問題標題>**：<問題內容，可多段、可列選項>

➡️ <你的建議答案>
```

多題就重複這組 `❓`/`➡️`，最後只收尾一次：

```
---
目前還有 {N} 個分支未決。

— By Rick (jira-grill)
```

第一輪（剛偵測到 `grill-me`、還沒有任何回覆）以票的標題、描述、驗收條件
與「Repo 解析與準備」查到的程式碼事實為輸入直接產出 frontier，不要等
留言。

**簽名是機器可辨識標記，不是裝飾**：結尾固定 `— By Rick (jira-grill)`
（不是 persona 其他情境用的 `— By Rick`）。`jira-grill-poller` 跟下方
流程步驟 3 都靠這串文字判斷「留言區塊最上面那則是不是自己剛貼的」。改了
格式，兩邊的判斷都會失效，導致同一輪問題重複問或漏判新回覆。

## 環境變數

- `JIRA_TOKEN` / `JIRA_EMAIL` / `JIRA_BASE_URL`：同 `jira-fetch` skill。

執行前用與 `jira-fetch` 相同的方式確認三個變數存在（`${VAR:+set}`
寫法，不要用 skill frontmatter 的 load-time inline shell 檢查，會被權限層
擋下）：

```bash
echo "JIRA_TOKEN: ${JIRA_TOKEN:+set}"
echo "JIRA_EMAIL: ${JIRA_EMAIL:+set}"
echo "JIRA_BASE_URL: ${JIRA_BASE_URL:+set}"
```

任一缺少：說明缺什麼變數並停止，不繼續嘗試。

## Jira API 慣例

沿用 `jira-fetch` 的寫法：`curl -u "${JIRA_EMAIL}:${JIRA_TOKEN}"` 做 Basic
Auth，一律用 `node -e` 解析/組 JSON，不假設 `jq`／`python3`／GNU-only
coreutils 存在。讀票內容與留言一律呼叫 `jira-fetch` skill（`jira-fetch
<TICKET_ID> --comments 50`），不要自己重寫一份讀取邏輯。

以下兩個動作是 `jira-fetch` 沒有的，本 skill 自己實作：

### 改 label

```bash
# 範例：把 grill-me-active 換成 grill-me-done（防禦性補做 grill-me →
# grill-me-active 的認領時，remove/add 的值換掉即可）
STATUS=$(curl -s -o /dev/null -w '%{http_code}' -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
  -X PUT "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}" \
  -H "Content-Type: application/json" \
  -d '{"update":{"labels":[{"remove":"grill-me-active"},{"add":"grill-me-done"}]}}')
if [ "$STATUS" != "204" ]; then
  echo "ERROR: 改 label 失敗（HTTP ${STATUS}）。"
fi
```

### 貼 comment

```bash
# COMMENT_BODY 是要貼的完整文字（含結尾簽名，見上方「提問格式與簽名標記」）
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

## 流程（`$ARGUMENTS = ticket <TICKET_ID>`）

1. 確認環境變數。
2. 呼叫 `jira-fetch ${TICKET_ID} --comments 50`，取得完整內容（含
   labels、全部留言，留言依 `jira-fetch` 慣例新到舊排序）。
3. **重複觸發防護**：看留言區塊最上面（最新）那一則，若含簽名標記
   `— By Rick (jira-grill)` → 代表這次觸發是 race 造成的重複觸發
   （`jira-grill-poller` 偵測到變更、但上一輪 turn 尚未完成前又被觸發
   一次）→ no-op 結束，輸出盡量精簡以控制成本。否則繼續步驟 4。
4. **防禦性 label 檢查**：
   - 不含 `grill-me-active` 也不含 `grill-me`（已收斂/已中止/人類手動
     改過）→ 理論上不該被觸發（poller 的 JQL 只抓這兩種 label），印出
     警告並結束。
   - 只含 `grill-me`（poller 的認領 PUT 失敗了）→ 補做 label 轉換
     （`grill-me` → `grill-me-active`），當首輪繼續處理。
   - 含 `grill-me-active` → 繼續步驟 5。
5. **判斷首輪／續輪**：整串留言裡有沒有任何一則帶 Rick 簽名的留言：
   - 沒有 → **首輪**：依「Repo 解析與準備」決定並準備目標 repo（可能
     成功解析並 clone/fetch，也可能未定、留給第一輪 frontier 去問），
     以票的標題、描述、驗收條件與（若已知）repo 裡查到的程式碼事實
     為輸入，產出第一輪 frontier 問題（格式見上文「提問格式與簽名
     標記」；repo 未定時把「哪個 repo」併入這一輪一起問），貼成第一則
     comment。
   - 有 → **續輪**：
     a. **中止訊號 1（label 被人類改掉）**：若目前 labels 不含
        `grill-me-active`，視為人類已手動中止 → 跳到步驟 6b。
     b. **中止訊號 2（人類文字喊停）**：若最新那則非自己簽名的留言
        明確表達停止意圖（例如「先這樣」「夠了」「不用再問了」
        「停止」「stop」「that's enough」「no more questions」等同義
        表達，靠語意判斷、不是精確關鍵字比對）→ 跳到步驟 6b（人類
        中止，非自然收斂）。否則繼續。
     c. 依「Repo 解析與準備」重新走一次優先序，確認/更新目標 repo。
     d. 依 grilling 方法論，用完整留言串（含新回覆、含 repo 裡查到的
        事實）重新計算 design tree：
        - 還有未決分支（可能包含還沒回答的「哪個 repo」）→ 產出下一輪
          frontier 問題，貼成新 comment（格式見上文），結尾附「目前
          還有 N 個分支未決」的進度摘要 → 結束。
        - Frontier 已清空（雙方對需求達成共識）→ 跳到步驟 6a。
6. **收斂／中止收尾**（6a 自然收斂／6b 人類中止，兩者都要做完下面全部）：
   a. 自然收斂：貼一則「✅ 需求共識」comment，把整輪問答蒸餾成結構化的
      最終需求描述（背景、確認的需求範圍、驗收條件、目標 repo），附簽名。
      人類中止：貼一則「🛑 已中止 grill-me（人類要求停止）」comment，
      簡述目前已釐清到哪裡、還有哪些分支未決，附簽名。
      兩者都在文末加一行 plain-text 提及
      `@{reporter 的 displayName} @{assignee 的 displayName}`（純文字，
      不是真正會觸發通知的 Jira `[~accountId]` mention——見「已知限制」）。
   b. 把 label 從 `grill-me-active` 換成 `grill-me-done`。

## 已知限制

- **repo 解析只涵蓋現有慣例**：104corp 任務靠 `104cac-product-registry`
  的登錄表（以 project key 比對 `jira.project`）；wm4n 個人任務沒有登錄
  表可查，公司任務查不到對應項目、或一個產品對到多個 repo/平台時也一
  樣——一律把「哪個 repo」併入 frontier 問人類，這是設計上的正常路徑，
  不是失敗。
- **沒有獨立 Jira bot 身份**：Rick 用人類帳號回覆 Jira，判斷「這則留言
  是不是自己剛貼的」一律靠文字簽名標記，不是帳號身份——`jira-grill-poller`
  跟這裡的重複觸發防護都是靠這個機制，改了簽名格式兩邊都會失效。
- **重複觸發防護是機率性的**：`jira-grill-poller` 沒有分散式鎖，理論上
  仍存在極窄的競態窗口（poller 判斷完、Discord 訊息送出前，Rick 剛好
  完成上一輪並貼出新留言），但本 skill 步驟 3 的簽名檢查會在絕大多數
  情況下擋下重複處理。
- **收斂/中止通知不是真正的 Jira @mention**：只是純文字寫 reporter/
  assignee 的 displayName，不是會觸發 Jira 通知的 `[~accountId]` 語法。
  實務上 Jira 預設會對「有新留言」通知 reporter/assignee/watcher，這則
  純文字提及只是方便人類在畫面上找到自己，不是通知機制本身。
- **中止/收斂路徑沒有回頭鍵，但這是可接受的**：把 label 改回 `grill-me`
  會被下次 `jira-grill-poller` 的 Query 1 當成全新票重新處理——這是
  設計上允許的行為，不是 bug。
- **`--comments 50` 是硬上限**：單張票的往返超過 50 則留言會讓最早的
  歷史看不到；純粹靠 Jira 留言串本身作為真相來源，理論上仍可能因為超過
  這個上限而遺漏極早期的脈絡，但一輪 grilling 通常遠低於 50 則留言，
  接受此限制。
- **輪詢頻率、掃描的 project 範圍不是本 skill 能決定**：由
  `jira-grill-poller` 的 K8s CronJob 設定（`schedule`、
  `JIRA_GRILL_PROJECTS`）決定，見
  `deployment-guides/k3s/jira-grill-poller/`。
```

- [ ] **Step 2: Bump plugin 版本**

`plugins/openab-bot-skills/.claude-plugin/plugin.json`,`version` 從
`1.5.2` 改成 `1.6.0`(觸發介面整個重寫,`discover` 模式拿掉,值得一個
minor bump,不是 patch)。

`.claude-plugin/marketplace.json` 裡 `openab-bot-skills` 對應的
`version` 欄位(目前是 `1.5.2` 那一行)同步改成 `1.6.0`。

- [ ] **Step 3: Commit 並 push(`wm4n` 帳號)**

```bash
cd /Users/william.chao/workspace/github/skill-registry
git add plugins/openab-bot-skills/skills/jira-grill/SKILL.md \
        plugins/openab-bot-skills/.claude-plugin/plugin.json \
        .claude-plugin/marketplace.json
git commit -m "$(cat <<'EOF'
feat(jira-grill): 合併流程改由 jira-grill-poller 觸發，拿掉輪詢邏輯

觸發改由外部 deterministic K8s CronJob 判斷後用專用 bot @mention，
SKILL 不再需要 discover 模式、cronjob.toml 讀寫、每輪的完整 no-op
輪詢判斷（只留一個輕量簽名檢查當重複觸發防護）。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
git push origin main
```

- [ ] **Step 4: Rick 的 pod 拉取新版本**

```bash
kubectl exec deployment/openab-claude-rick -n cac -- claude plugin marketplace update wm4n-skill-registry
kubectl exec deployment/openab-claude-rick -n cac -- claude plugin update openab-bot-skills@wm4n-skill-registry
kubectl exec deployment/openab-claude-rick -n cac -- cat /home/node/.claude/plugins/installed_plugins.json | grep -A3 openab-bot-skills
```

Expected:輸出的 `version` 是 `1.6.0`。

---

### Task 4: 清理 `cronjob.toml` 裡的舊 jira-grill job

**Files:**
- 無 repo 內檔案改動,直接操作 Rick live pod 的 `~/.openab/cronjob.toml`。

**Interfaces:**
- 無(純清理動作)。

- [ ] **Step 1: 檢查現有內容**

```bash
kubectl exec deployment/openab-claude-rick -n cac -- cat /home/node/.openab/cronjob.toml
```

記下所有 `id` 以 `jira-grill-` 開頭的 `[[jobs]]` 區塊(應該有
`jira-grill-discovery`,可能還有殘留的 `jira-grill-<TICKET_ID>`),以及
所有**不是** jira-grill 的其他 job(要保留)。

- [ ] **Step 2: 整檔覆寫,拿掉所有 jira-grill 相關 job**

把 Step 1 看到的內容,扣掉所有 `id` 以 `jira-grill-` 開頭的區塊,其餘
原樣保留,用 `cat >`(整檔覆蓋,不要 `cat >>`)寫回:

```bash
kubectl exec deployment/openab-claude-rick -n cac -- sh -c 'cat > ~/.openab/cronjob.toml << '"'"'TOMLEOF'"'"'
<Step 1 看到的內容，扣掉所有 jira-grill- 開頭的 [[jobs]] 區塊>
TOMLEOF
cat ~/.openab/cronjob.toml'
```

- [ ] **Step 3: 驗證**

```bash
kubectl exec deployment/openab-claude-rick -n cac -- grep -c jira-grill /home/node/.openab/cronjob.toml
```

Expected:輸出 `0`(或指令因為完全沒有 match 而回傳非零 exit code、無
輸出——兩者都代表清乾淨了)。

---

### Task 5: 更新文件(`BOT_SETUP.md` / `Rick-CLAUDE_v2.md`)

**Files:**
- Modify: `deployment-guides/BOT_SETUP.md:717-727`
- Modify: `deployment-guides/Rick-CLAUDE_v2.md:58-71`

**Interfaces:**
- 無(純文件更新)。

- [ ] **Step 1: 改 `BOT_SETUP.md`**

目前(`BOT_SETUP.md:717-727`):

```markdown
**jira-grill（獨立能力，2026-08-24 新增）**：掛在 Rick 已裝的
`openab-bot-skills` plugin 裡（來源 `wm4n/skill-registry`
repo，`plugins/openab-bot-skills/skills/jira-grill/`），不需要額外
`plugin install`，`plugin marketplace update` +
`plugin update openab-bot-skills@wm4n-skill-registry` 就會拉到。需要
額外在 Rick 的 `values-openab-claude.yaml`（k3s，見 Part O）補
`secretEnv`（`JIRA_TOKEN`/`JIRA_BASE_URL`/`JIRA_EMAIL`，複用
`morty-jira` Secret）與 `env.JIRA_GRILL_CHANNEL`，`helm upgrade` 後才
會生效。設計依據見
`docs/superpowers/specs/2026-08-24-rick-jira-grill-design.md`、實作
計畫見 `docs/superpowers/plans/2026-08-24-rick-jira-grill.md`。
```

改成:

```markdown
**jira-grill（獨立能力，2026-08-24 新增，2026-08-25 改用 deterministic
poller 觸發）**：掛在 Rick 已裝的 `openab-bot-skills` plugin 裡（來源
`wm4n/skill-registry` repo，`plugins/openab-bot-skills/skills/jira-grill/`），
不需要額外 `plugin install`，`plugin marketplace update` +
`plugin update openab-bot-skills@wm4n-skill-registry` 就會拉到。需要
額外在 Rick 的 `values-openab-claude.yaml`（k3s，見 Part O）補
`secretEnv`（`JIRA_TOKEN`/`JIRA_BASE_URL`/`JIRA_EMAIL`，複用
`morty-jira` Secret）與 `discord.trustedBotIds` 裡加入
`jira-grill-trigger` bot 的 User ID，`helm upgrade` 後才會生效。

觸發機制**不是**掛在 Rick 自己身上的 cron 輪詢，而是一個獨立部署的
`jira-grill-poller`（K8s CronJob，見
`deployment-guides/k3s/jira-grill-poller/`，跟 openab 的 Helm release
分開部署）：這個 poller 全程不經過 LLM，只有偵測到新的 `grill-me` 票
或既有票的新回覆，才用一個新註冊的 `jira-grill-trigger` Discord bot
@mention Rick 觸發，觸發後才會消耗一次 LLM turn。部署/更新 poller 見
`deployment-guides/k3s/jira-grill-poller/cronjob.yaml`。

設計依據見
`docs/superpowers/specs/2026-08-24-rick-jira-grill-design.md`（grilling
方法論本身）與
`docs/superpowers/specs/2026-08-25-jira-grill-poller-design.md`（觸發
機制重寫）；實作計畫見
`docs/superpowers/plans/2026-08-24-rick-jira-grill.md`與
`docs/superpowers/plans/2026-08-25-jira-grill-poller.md`。
```

- [ ] **Step 2: 改 `Rick-CLAUDE_v2.md`**

目前(`Rick-CLAUDE_v2.md:58-71`):

```markdown
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

改成:

```markdown
Jira 票被貼上 `grill-me` label 時,一個獨立部署的 `jira-grill-poller`
(K8s CronJob,不含 LLM,見 `deployment-guides/k3s/jira-grill-poller/`)
偵測到後,會用專用的 `jira-grill-trigger` bot @mention 你,觸發你去審視
這張票的需求——這**是**一則 bot @mention(跟 Morty/Summer 觸發你的機制
一樣,靠 `trustedBotIds`),但發起方不是人類,而是這個自動化 poller。
收到觸發後依 `jira-grill` skill 的指示行動(`ticket <TICKET_ID>` 參數)。

- 這條能力完全獨立於本檔其他章節描述的三 bot 接力 pipeline,不取代、不
  影響 Morty 既有的 JIRA 需求分析角色。
- 提問與回答都透過 Jira comment 進行,不在 Discord 對話。
- 達成需求共識或人類喊停後,只貼 comment 通知人類,**不**自動開始開發、
  不自動 @ 任何 bot——後續要不要進 PR 開發模式,由人類另外明確要求。
- 本節不影響第 2 節「絕對鐵則」worktree 隔離規定的核心精神:這條能力會
  clone/fetch repo 讀程式碼(見 `jira-grill` skill 的「Repo 解析與
  準備」),但只在 base clone 上讀、不建 worktree、不改檔案、不切分支,
  不落入「repo 相關工作一律用 worktree」那條鐵則要管的範圍。

詳細流程見 `jira-grill` skill。
```

- [ ] **Step 3: 驗證**

```bash
kubectl exec deployment/openab-claude-rick -n cac -- sh -c '
  CK=/home/node/github-repo/openab/deployment-guides
  cp "$CK/Rick-CLAUDE_v2.md" /home/node/CLAUDE.md'
kubectl exec deployment/openab-claude-rick -n cac -- grep -c "jira-grill-poller" /home/node/CLAUDE.md
```

Expected:輸出 `>= 1`。

- [ ] **Step 4: Commit**

```bash
git add deployment-guides/BOT_SETUP.md deployment-guides/Rick-CLAUDE_v2.md
git commit -m "$(cat <<'EOF'
docs: 同步 jira-grill 改用 deterministic poller 觸發的文件說明

BOT_SETUP.md、Rick-CLAUDE_v2.md 原本描述的是 cron 輪詢機制，現在
改成 jira-grill-poller + 專用 bot @mention 觸發，順便修正
Rick-CLAUDE_v2.md 一句過時敘述（這條能力其實會 clone/fetch repo）。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 端對端驗證 + 重複觸發防護驗證

**Files:**
- 無檔案改動,純驗證。

**Interfaces:**
- 無。

- [ ] **Step 1: 挑一張可拋棄的測試票**

在 `JIRA_GRILL_PROJECTS` 白名單裡的其中一個 project(如 CACJOB)建一張
測試票,標題/描述寫清楚是測試用,方便事後辨識與刪除。

- [ ] **Step 2: 貼上 `grill-me` label,等 poller 偵測**

貼上 label 後,在 10 分鐘內(poller 的 `schedule`)觀察:
1. Jira 上該票 label 是否自動變成 `grill-me-active`。
2. `JIRA_GRILL_CHANNEL`(cac-notify)是否出現 `jira-grill-trigger` bot
   貼的觸發訊息。
3. Rick 是否在幾分鐘內於 Jira 該票貼出第一輪 `❓`/`➡️` frontier
   comment(可能含「哪個 repo」的提問,視 `104cac-product-registry` PR
   #1 當時是否已合併而定)。

- [ ] **Step 3: 模擬人類回覆,驗證續輪**

在 Jira 上對該票留言回答問題(或明確表示要停止:「先這樣，謝謝」)。
10 分鐘內觀察:
1. poller 的下一次執行是否偵測到這則新留言並再次觸發。
2. Rick 是否貼出下一輪 frontier(或依「中止」路徑貼出「🛑 已中止」
   comment、label 轉 `grill-me-done`)。

- [ ] **Step 4: 走到收斂或反覆驗證直到收斂**

持續回答,直到 Rick 貼出「✅ 需求共識」comment、label 自動轉
`grill-me-done`。確認:
1. 結論 comment 內容完整(背景、確認的需求範圍、驗收條件、目標 repo)。
2. label 確實是 `grill-me-done`。
3. 之後 poller 不再對這張票有任何動作(Query 1/2 都不會再抓到它)。

- [ ] **Step 5: 重複觸發防護驗證**

另建一張測試票,貼 `grill-me` label 觸發首輪 frontier 完成後,短時間內
手動呼叫兩次 Discord API(或用 `kubectl create job` 手動跑兩次 poller,
中間不要間隔太久)針對同一張 `grill-me-active` 票送出觸發訊息。確認
Rick 只會實際處理一次——第二次因為讀到已經有自己簽名的留言(SKILL.md
流程步驟 3)而 no-op,不會產生兩輪並行的重複提問。

- [ ] **Step 6: 清理測試票**

把測試票的 label 清掉或轉成不會被任何 JQL 掃到的狀態,依團隊慣例決定是
否要刪除或關閉這張票。
