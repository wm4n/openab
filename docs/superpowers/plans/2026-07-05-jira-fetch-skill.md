# jira-fetch Skill 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `wm4n/ai-skill` public repo,實作 `jira-fetch` skill,並部署到 Morty 容器取代現有 Bearer token 寫法。

**Architecture:** 純 SKILL.md 設計,無外部腳本依賴。agent 依照 skill 指示自行執行 curl/jq 組 Basic Auth 並抓取 JIRA issue,輸出結構化 markdown。Morty 透過 `cat` 讀取本地 skill 檔後遵循指示執行。

**Tech Stack:** GitHub CLI(`gh`)、curl、jq、base64(GNU/BSD 雙版本相容)、Portainer Console。

## Global Constraints

- Public repo `wm4n/ai-skill`,任何人可 clone 無需 token
- Skill 檔案絕不含硬編碼 token 或 email
- 環境變數:JIRA_TOKEN、JIRA_EMAIL、JIRA_BASE_URL 由容器 inherit_env 注入
- Morty 在 Portainer(無法用 Mac mini docker 指令),操作走 Portainer Console
- 繁體中文輸出

---

### Task 1: 建立 `wm4n/ai-skill` repo 並寫 SKILL.md

**Files:**
- Create: `skills/jira-fetch/SKILL.md`(在 `wm4n/ai-skill` repo)

**Interfaces:**
- Consumes: 無
- Produces: `https://github.com/wm4n/ai-skill` 可 clone;`skills/jira-fetch/SKILL.md` 可讀取

- [ ] **Step 1: 建立 GitHub repo**

```bash
gh repo create wm4n/ai-skill --public --description "Reusable AI agent skills" --clone
cd ai-skill
```

Expected:本地出現 `ai-skill/` 目錄,已 clone。

- [ ] **Step 2: 建立目錄結構**

```bash
mkdir -p skills/jira-fetch
```

- [ ] **Step 3: 寫 SKILL.md**

```bash
cat > skills/jira-fetch/SKILL.md <<'EOF'
---
name: jira-fetch
argument-hint: "[JIRA-ticket-id] [--comments N]"
description: >-
  從 JIRA 抓取 issue 內容並輸出結構化 markdown。
  支援 Atlassian Cloud Basic Auth(JIRA_EMAIL + JIRA_TOKEN)。
  輸出包含標題、描述、驗收條件、sprint、fixVersion 及最新 N 則留言。
  所需環境變數：JIRA_TOKEN、JIRA_EMAIL、JIRA_BASE_URL。
allowed-tools:
  - Bash(curl *)
  - Bash(printf *)
  - Bash(echo *)
  - Bash(jq *)
---

# JIRA Issue Fetch

從 JIRA 抓取 issue 內容,輸出結構化 markdown 供 agent 繼續處理。

## 參數解析

- TICKET_ID:從 $ARGUMENTS 取第一個 token(如 CACJOB-12345)
- COMMENTS_COUNT:若 $ARGUMENTS 含 `--comments N` 則取 N,否則預設 5;若為 0 則不抓留言

## 步驟 1:確認環境變數

執行以下指令確認三個變數是否都存在:

```bash
echo "JIRA_TOKEN=${JIRA_TOKEN:+已設定}${JIRA_TOKEN:-[未設定]}"
echo "JIRA_EMAIL=${JIRA_EMAIL:+已設定}${JIRA_EMAIL:-[未設定]}"
echo "JIRA_BASE_URL=${JIRA_BASE_URL:+已設定}${JIRA_BASE_URL:-[未設定]}"
```

若任一變數顯示 `[未設定]`:
說明缺少哪個環境變數並停止,提示:
「請手動提供 {TICKET_ID} 的內容(標題、描述、驗收條件)以便繼續處理。」

## 步驟 2:組 Basic Auth header

```bash
JIRA_AUTH=$(printf "%s:%s" "${JIRA_EMAIL}" "${JIRA_TOKEN}" | base64 -w 0 2>/dev/null \
  || printf "%s:%s" "${JIRA_EMAIL}" "${JIRA_TOKEN}" | base64 | tr -d '\n')
```

(相容 GNU base64 `-w 0` 與 macOS BSD `base64 | tr -d '\n'`)

## 步驟 3:抓 issue 內容

```bash
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET \
  "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}?fields=summary,status,priority,assignee,reporter,labels,fixVersions,description,customfield_10016,customfield_10020,customfield_10014" \
  -H "Authorization: Basic ${JIRA_AUTH}" \
  -H "Content-Type: application/json")

HTTP_CODE=$(echo "${RESPONSE}" | tail -1)
ISSUE_BODY=$(echo "${RESPONSE}" | head -n -1)
```

HTTP status 處理:
- 200 → 繼續
- 401 / 403 → 說明「JIRA 認證失敗(HTTP ${HTTP_CODE})。請確認 JIRA_TOKEN 是有效的 Atlassian API token、JIRA_EMAIL 是對應帳號 email。」並停止
- 404 → 說明「找不到票號 ${TICKET_ID}(HTTP 404)。請確認票號格式正確且有存取權限。」並停止
- 其他 → 說明「JIRA API 回傳錯誤(HTTP ${HTTP_CODE})。」並停止

## 步驟 4:抓最新留言(若 COMMENTS_COUNT > 0)

```bash
COMMENTS_RESPONSE=$(curl -s -X GET \
  "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}/comment?maxResults=${COMMENTS_COUNT}&orderBy=-created" \
  -H "Authorization: Basic ${JIRA_AUTH}" \
  -H "Content-Type: application/json")
```

## 步驟 5:輸出結構化 markdown

用 jq 從 ISSUE_BODY 取出各欄位,組成以下格式輸出。
ADF(Atlassian Document Format)格式的欄位取 `.content[].content[].text` 拼接純文字;
若欄位為純字串直接輸出;若為 null 則依欄位輸出預設值。

```
## JIRA Issue: {TICKET_ID}

**標題:** {fields.summary}
**狀態:** {fields.status.name}  **優先級:** {fields.priority.name}
**Assignee:** {fields.assignee.displayName 或 "未指派"}
**Reporter:** {fields.reporter.displayName}
**Labels:** [{fields.labels[] 逗號分隔,無則 "無"}]
**Fix Version:** {fields.fixVersions[0].name 或 "未設定"}
**Sprint:** {fields.customfield_10020[0].name 或 fields.customfield_10014 或 "未設定"}
**Base Branch Hint:** {Fix Version 名稱優先 > Sprint 名稱次之 > "未知,請人類確認 base branch"}

### 描述
{fields.description 純文字;null 則 "(無描述)"}

### 驗收條件
{fields.customfield_10016 純文字;null 則 "(未填寫驗收條件)"}

### 最新 {COMMENTS_COUNT} 則留言
{若 COMMENTS_COUNT = 0 則略過此整個區塊}

**[{comment.created 取 yyyy-mm-dd}] {comment.author.displayName}**
{comment.body 純文字}

---
{重複至 COMMENTS_COUNT 則或全部留言為止}
```
EOF
```

- [ ] **Step 4: commit + push**

```bash
git add skills/jira-fetch/SKILL.md
git commit -m "feat: add jira-fetch skill

Fetch JIRA issue content with Basic Auth, structured markdown output.
Supports configurable comment count (default 5), graceful fallback
on missing env vars or API errors."
git push origin main
```

Expected:
```
https://github.com/wm4n/ai-skill 可公開存取
```

- [ ] **Step 5: 驗證 repo 可公開存取**

```bash
curl -s https://raw.githubusercontent.com/wm4n/ai-skill/main/skills/jira-fetch/SKILL.md | head -5
```

Expected:印出 SKILL.md 的前幾行(frontmatter)。

---

### Task 2: 部署到 Morty 容器 + 更新 CLAUDE.md

**Files:**
- Create: `/home/node/ai-skill/`(Morty 容器,git clone)
- Modify: Morty 容器 `/home/node/config.toml`(加 JIRA_EMAIL 到 inherit_env)
- Modify: Morty 容器 `/home/node/CLAUDE.md`(角色 B1 改用 skill)
- Modify: Portainer Stack Environment variables(加 JIRA_EMAIL)

**Interfaces:**
- Consumes: Task 1 的 `wm4n/ai-skill` repo
- Produces: Morty 能成功執行 jira-fetch skill 抓到票的內容

- [ ] **Step 1: 在 Portainer Stack 加入 JIRA_EMAIL 環境變數**

Portainer → Stacks → 該 Stack → Editor → Environment variables,新增:
```
JIRA_EMAIL=william.chao@104.com.tw
```
點 **Update the stack**。

> ⚠️ 這步改的是 Stack env,容器重啟後才生效。先做這步再重啟。

- [ ] **Step 2: 更新 config.toml 加入 JIRA_EMAIL**

Portainer Console(user `node`):
```bash
sed -i 's/inherit_env = \["GH_TOKEN", "JIRA_TOKEN", "JIRA_BASE_URL"\]/inherit_env = ["GH_TOKEN", "JIRA_TOKEN", "JIRA_BASE_URL", "JIRA_EMAIL"]/' /home/node/config.toml
grep inherit_env /home/node/config.toml
```

Expected:
```
inherit_env = ["GH_TOKEN", "JIRA_TOKEN", "JIRA_BASE_URL", "JIRA_EMAIL"]
```

- [ ] **Step 3: Clone ai-skill repo 到 Morty 容器**

Portainer Console:
```bash
git clone https://github.com/wm4n/ai-skill.git /home/node/ai-skill
ls /home/node/ai-skill/skills/jira-fetch/SKILL.md
```

Expected:印出檔案路徑確認存在。

- [ ] **Step 4: 更新 CLAUDE.md 的角色 B1 改用 skill**

角色 B1 的步驟 1 原本是直接呼叫 curl,改為讀取並遵循 skill。
用 sed 找到「取票內容」那段並替換,或直接重新寫入角色 B1 區塊。

最直接的做法是對 CLAUDE.md 中角色 B1 的步驟 1 做 in-place 替換:

```bash
# 確認目前寫法(找到要換掉的行)
grep -n "JIRA REST API\|Bearer\|JIRA_AUTH" /home/node/CLAUDE.md | head -10
```

若找到相關行,用以下方式替換整個「取票內容」步驟為 skill 呼叫:

```bash
# 在角色 B1 步驟 1 的開頭加入 skill 呼叫說明
# 使用 Python(容器有 python3)做多行替換
python3 - <<'PYEOF'
import re

with open('/home/node/CLAUDE.md', 'r') as f:
    content = f.read()

old = """1. 取票內容:
   - 若環境有 JIRA_TOKEN 和 JIRA_BASE_URL:
     呼叫 JIRA REST API:GET ${JIRA_BASE_URL}/rest/api/2/issue/<ticket-id>
     Header: Authorization: Bearer ${JIRA_TOKEN}
     取出 fields.summary(標題)、fields.description(描述)、fields.customfield(AC)
   - 若無 JIRA_TOKEN:讀使用者貼在訊息裡的描述內容。"""

new = """1. 取票內容:
   讀取並遵循 jira-fetch skill 的指示:
   cat /home/node/ai-skill/skills/jira-fetch/SKILL.md
   執行時帶入票號:TICKET_ID={JIRA-ID},COMMENTS_COUNT=5
   - 若 skill 執行成功 → 取得結構化 markdown,繼續步驟 2
   - 若 skill 回報環境變數缺失 → 請使用者手動貼票的內容"""

content = content.replace(old, new)

with open('/home/node/CLAUDE.md', 'w') as f:
    f.write(content)

print("Done" if new in content else "ERROR: replacement not found")
PYEOF
```

Expected:印出 `Done`。

若印出 `ERROR`:用 `grep -n "取票內容" /home/node/CLAUDE.md` 找到實際行數,手動在 Portainer Console 確認文字差異後調整 old 字串。

- [ ] **Step 5: 確認 CLAUDE.md 更新正確**

```bash
grep -A 8 "取票內容" /home/node/CLAUDE.md
```

Expected:看到 `cat /home/node/ai-skill/skills/jira-fetch/SKILL.md` 那幾行。

- [ ] **Step 6: 重啟 Morty**

Portainer → Containers → 該容器 → Restart。等待 healthy。

- [ ] **Step 7: 驗證 JIRA_EMAIL 環境變數已注入**

Portainer Console:
```bash
env | grep JIRA
```

Expected:
```
JIRA_TOKEN=<已設定>
JIRA_BASE_URL=https://...atlassian.net
JIRA_EMAIL=william.chao@104.com.tw
```

- [ ] **Step 8: 端對端驗證**

在 Discord #dev-bot @Morty 發:「我想處理 CACJOB-1(或任何真實票號)」

觀察 Morty:
1. 偵測 JIRA 票號 → 進角色 B1
2. 執行 `cat /home/node/ai-skill/skills/jira-fetch/SKILL.md`
3. 組 Basic Auth:`printf "william.chao@104.com.tw:${JIRA_TOKEN}" | base64 -w 0`
4. curl 打 JIRA API 成功(HTTP 200)
5. 輸出結構化 markdown(含標題、描述、AC、Sprint、Base Branch Hint)
6. 進入 brainstorming

Expected:Morty 成功取到票的內容並開始問答,不再說「認證失敗」。

---

## Self-Review(對照 spec)

| Spec 需求 | 對應 Task |
|-----------|-----------|
| public repo `wm4n/ai-skill` | Task 1 Step 1 |
| `skills/jira-fetch/SKILL.md` | Task 1 Step 3 |
| Basic Auth(`JIRA_EMAIL:JIRA_TOKEN` base64) | Task 1 Step 3 步驟 2 |
| 結構化 markdown 輸出 | Task 1 Step 3 步驟 5 |
| `--comments N` 參數,預設 5 | Task 1 Step 3 參數解析 |
| 錯誤處理(401/403/404/缺 env var) | Task 1 Step 3 步驟 1+3 |
| base64 GNU/BSD 相容 | Task 1 Step 3 步驟 2 |
| Sprint customfield 多版本嘗試 | Task 1 Step 3 步驟 5 |
| Clone 到 Morty 容器 | Task 2 Step 3 |
| JIRA_EMAIL 加入 inherit_env | Task 2 Step 1+2 |
| CLAUDE.md 改用 skill | Task 2 Step 4 |
| 端對端驗證 | Task 2 Step 8 |
