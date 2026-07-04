# jira-fetch Skill 設計文件

- 日期:2026-07-05
- 狀態:設計草案,待使用者複審
- 範圍:建立可重用的 JIRA issue fetch skill,供任何 Claude/Codex agent 呼叫
- 語言:繁體中文

## 目標

建立一個放在 public repo(`wm4n/ai-skill`)的可重用 skill,讓 Morty、Rick、Summer 或任何未來的 agent 都能用統一方式抓取 JIRA issue 內容,無需在各自的 CLAUDE.md/AGENTS.md 重複實作 auth 邏輯。

## 非目標(YAGNI)

- 不處理 JIRA 寫入(開票、更新狀態)——只讀取
- 不處理 Jira Server/Data Center(只支援 Atlassian Cloud Basic Auth)
- 不做 comment 貼回 JIRA(那是 Morty CLAUDE.md 的責任)
- 不建 bash 腳本(純 SKILL.md,不需外部依賴)

## 檔案結構

```
wm4n/ai-skill/
└── skills/
    └── jira-fetch/
        └── SKILL.md
```

## Skill 介面

**名稱:** `jira-fetch`
**參數:** `[JIRA-ticket-id] [--comments N]`
- `JIRA-ticket-id`:必填,如 `CACJOB-12345`
- `--comments N`:選填,抓最新 N 則留言,預設 5,傳 0 則不抓留言

**所需環境變數:**

| 變數 | 說明 | 必要性 |
|------|------|--------|
| `JIRA_TOKEN` | Atlassian API token | 必要 |
| `JIRA_EMAIL` | Atlassian 帳號 email | 必要 |
| `JIRA_BASE_URL` | JIRA 實例網址,如 `https://yourorg.atlassian.net` | 必要 |

## 執行步驟

### 步驟 1:確認環境變數

檢查三個變數是否都存在。任一缺少 → 說明缺什麼變數,請人類手動貼票的內容(標題、描述、AC),不繼續執行。

### 步驟 2:組 Basic Auth header

```bash
JIRA_AUTH=$(printf "${JIRA_EMAIL}:${JIRA_TOKEN}" | base64 -w 0)
```

### 步驟 3:抓 issue 內容

```bash
curl -s -X GET \
  "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}" \
  -H "Authorization: Basic ${JIRA_AUTH}" \
  -H "Content-Type: application/json"
```

從回應取出:
- `fields.summary` → 標題
- `fields.status.name` → 狀態
- `fields.priority.name` → 優先級
- `fields.assignee.displayName` → Assignee
- `fields.reporter.displayName` → Reporter
- `fields.labels` → Labels 陣列
- `fields.fixVersions[0].name` → Fix Version
- `fields.sprint.name` 或 `fields.customfield_10020[0].name` → Sprint
- `fields.description` → 描述(Atlassian Document Format 轉純文字)
- `fields.customfield_10016` 或其他 AC customfield → 驗收條件

### 步驟 4:抓最新 N 則留言

```bash
curl -s -X GET \
  "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}/comment?maxResults=${N}&orderBy=-created" \
  -H "Authorization: Basic ${JIRA_AUTH}" \
  -H "Content-Type: application/json"
```

取 `comments[]` 的 `author.displayName`、`created`、`body`。

### 步驟 5:輸出結構化 markdown

```
## JIRA Issue: {TICKET_ID}

**標題:** {summary}
**狀態:** {status}  **優先級:** {priority}
**Assignee:** {assignee}  **Reporter:** {reporter}
**Labels:** [{label1}, {label2}]
**Fix Version:** {fixVersion}
**Sprint:** {sprint}
**Base Branch Hint:** {fixVersion 或 sprint 名稱,供 bot 判斷 base branch 用}

### 描述
{description}

### 驗收條件
{acceptance_criteria}

### 最新 {N} 則留言
**[{date}] {author}**
{comment_body}

---
```

### 步驟 6:錯誤處理

- HTTP 401/403 → 說明「JIRA 認證失敗」,建議檢查 JIRA_TOKEN 與 JIRA_EMAIL
- HTTP 404 → 說明「找不到票號 {TICKET_ID}」
- jq/curl 不存在 → 說明環境缺少工具
- 任何錯誤 → 提示人類手動貼票的內容

## 在 Morty CLAUDE.md 的呼叫方式

Morty 的角色 B1 將 Bearer 改為呼叫此 skill:

```
在角色 B1 步驟 1 改為執行 skill:
/jira-fetch {TICKET_ID}
(若需要更多留言: /jira-fetch {TICKET_ID} --comments 10)
```

安裝方式:Morty 容器需先 clone `wm4n/ai-skill` 到 `/home/node/ai-skill`,
並在 CLAUDE.md 告知 skill 路徑。

## 安裝方式(任何 bot)

```bash
# 一次性 clone
git clone https://github.com/wm4n/ai-skill.git /home/node/ai-skill

# CLAUDE.md 或 AGENTS.md 加入:
# 讀取 jira-fetch skill:cat /home/node/ai-skill/skills/jira-fetch/SKILL.md
```

因為是 public repo,不需要任何 token 就能 clone。

## 已知限制

- Atlassian Document Format(ADF)是 JSON 結構,純文字轉換會損失部分格式(表格、code block)——接受此限制,夠用即可
- Sprint 的 customfield 編號(如 `customfield_10020`)在不同 JIRA 實例可能不同——skill 會嘗試幾個常見 customfield,找不到則略過
- `base64 -w 0` 是 GNU coreutils 的 flag,macOS 原生 base64 要用 `base64 | tr -d '\n'`——skill 需要偵測並處理兩種情況
