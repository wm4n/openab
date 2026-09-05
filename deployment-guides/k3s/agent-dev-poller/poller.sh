#!/bin/bash
#
# agent-dev-poller: deterministic 前置判斷，不經過 LLM。
# 分別掃描 Jira 專案白名單、GitHub repo 白名單裡貼了 ready-for-agent-dev
# label 的票/issue，原子性認領（label 換成 agent-dev-active）後，用既有的
# jira-grill-trigger bot @mention Genie 觸發 auto-dev-pipeline skill。
#
# 刻意不做的事：repo 解析、規格是否完整、要不要真的開發——全部交給 Genie
# （有 LLM 判斷能力）處理，這支 script 只回答「有沒有新目標該交給它」。

: "${JIRA_TOKEN:?missing JIRA_TOKEN}"
: "${JIRA_EMAIL:?missing JIRA_EMAIL}"
: "${JIRA_BASE_URL:?missing JIRA_BASE_URL}"
: "${JIRA_AGENT_DEV_PROJECTS:?missing JIRA_AGENT_DEV_PROJECTS}"
: "${GITHUB_AGENT_DEV_REPOS:?missing GITHUB_AGENT_DEV_REPOS}"
: "${GH_AGENT_DEV_TOKEN_WM4N:?missing GH_AGENT_DEV_TOKEN_WM4N}"
: "${GH_AGENT_DEV_TOKEN_CAC:?missing GH_AGENT_DEV_TOKEN_CAC}"
: "${AGENT_DEV_CHANNEL:?missing AGENT_DEV_CHANNEL}"
: "${JIRA_GRILL_TRIGGER_BOT_TOKEN:?missing JIRA_GRILL_TRIGGER_BOT_TOKEN}"
: "${GENIE_DISCORD_USER_ID:?missing GENIE_DISCORD_USER_ID}"

READY_LABEL="ready-for-agent-dev"
ACTIVE_LABEL="agent-dev-active"

# $1 = 要貼在觸發訊息裡的參數文字（例如 "github-issue 104corp/xxx#123"
# 或 "jira-ticket CACJOB-123"）。
trigger_genie() {
  ARG_TEXT="$1"
  BODY=$(node -e '
    const genieId = process.env.GENIE_DISCORD_USER_ID;
    const argText = process.argv[1];
    process.stdout.write(JSON.stringify({
      content: "<@" + genieId + "> 執行 auto-dev-pipeline skill，參數：" + argText
    }));
  ' "$ARG_TEXT")
  STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bot ${JIRA_GRILL_TRIGGER_BOT_TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST "https://discord.com/api/v10/channels/${AGENT_DEV_CHANNEL}/messages" \
    -d "$BODY")
  if [ "$STATUS" != "200" ]; then
    echo "ERROR: 觸發失敗（${ARG_TEXT}，Discord HTTP ${STATUS}）"
  else
    echo "已觸發：${ARG_TEXT}"
  fi
}

echo "== Jira：找貼 ${READY_LABEL} 的票 =="
PROJECTS_CLAUSE=$(node -e '
const keys = process.env.JIRA_AGENT_DEV_PROJECTS.split(",").map(s => s.trim()).filter(Boolean);
console.log("project IN (" + keys.map(k => JSON.stringify(k)).join(",") + ")");
')
JQL="${PROJECTS_CLAUSE} AND labels = \"${READY_LABEL}\""
SEARCH_BODY=$(node -e '
  const body = { jql: process.argv[1], fields: ["key"], maxResults: 50 };
  process.stdout.write(JSON.stringify(body));
' "$JQL")
RESPONSE=$(curl -s -u "${JIRA_EMAIL}:${JIRA_TOKEN}" -w '\n%{http_code}' \
  -X POST "${JIRA_BASE_URL}/rest/api/3/search/jql" \
  -H "Content-Type: application/json" \
  -d "$SEARCH_BODY")
TICKETS=$(printf '%s' "$RESPONSE" | node -e '
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
')
if [ -n "$TICKETS" ]; then
  echo "$TICKETS" | while IFS= read -r TICKET_ID; do
    [ -z "$TICKET_ID" ] && continue
    CLAIM_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
      -X PUT "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}" \
      -H "Content-Type: application/json" \
      -d '{"update":{"labels":[{"remove":"ready-for-agent-dev"},{"add":"agent-dev-active"}]}}')
    if [ "$CLAIM_STATUS" != "204" ]; then
      echo "ERROR: 認領 ${TICKET_ID} 失敗（改 label HTTP ${CLAIM_STATUS}），跳過，下一輪重試"
      continue
    fi
    trigger_genie "jira-ticket ${TICKET_ID}"
  done
else
  echo "(無符合條件的 Jira 票)"
fi

echo "== GitHub：找貼 ${READY_LABEL} 的 issue =="
IFS=',' read -ra REPO_LIST <<< "$GITHUB_AGENT_DEV_REPOS"
for REPO_FULL_RAW in "${REPO_LIST[@]}"; do
  REPO_FULL=$(echo "$REPO_FULL_RAW" | xargs)
  [ -z "$REPO_FULL" ] && continue
  OWNER="${REPO_FULL%%/*}"
  if [ "$OWNER" = "wm4n" ]; then
    GH_TOKEN_FOR_REPO="$GH_AGENT_DEV_TOKEN_WM4N"
  else
    GH_TOKEN_FOR_REPO="$GH_AGENT_DEV_TOKEN_CAC"
  fi

  RESPONSE=$(curl -s -w '\n%{http_code}' \
    -H "Authorization: Bearer ${GH_TOKEN_FOR_REPO}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/${REPO_FULL}/issues?labels=${READY_LABEL}&state=open")
  NUMBERS=$(printf '%s' "$RESPONSE" | node -e '
    const raw = require("fs").readFileSync(0, "utf8");
    const nl = raw.lastIndexOf("\n");
    const status = raw.slice(nl + 1).trim();
    const body = raw.slice(0, nl);
    if (status !== "200") {
      console.error("ERROR: 列 issue 失敗（" + process.argv[1] + "，HTTP " + status + "）");
      process.exit(0);
    }
    const items = JSON.parse(body) || [];
    for (const i of items) {
      if (i.pull_request) continue; // GitHub issues 端點連 PR 都算進去，排除
      console.log(i.number);
    }
  ' "$REPO_FULL")
  if [ -z "$NUMBERS" ]; then
    echo "(${REPO_FULL} 無符合條件的 issue)"
    continue
  fi
  echo "$NUMBERS" | while IFS= read -r ISSUE_NUMBER; do
    [ -z "$ISSUE_NUMBER" ] && continue
    # 先加 agent-dev-active（idempotent，重試安全），成功後才移除
    # ready-for-agent-dev——順序反過來的話，萬一移除成功但新增失敗，這張
    # issue 會兩個 label 都沒有，下一輪永遠撿不回來。
    ADD_STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
      -H "Authorization: Bearer ${GH_TOKEN_FOR_REPO}" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      -X POST "https://api.github.com/repos/${REPO_FULL}/issues/${ISSUE_NUMBER}/labels" \
      -d '{"labels":["agent-dev-active"]}')
    if [ "$ADD_STATUS" != "200" ]; then
      echo "ERROR: 認領 ${REPO_FULL}#${ISSUE_NUMBER} 失敗（加 label HTTP ${ADD_STATUS}），跳過，下一輪重試"
      continue
    fi
    REMOVE_STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
      -H "Authorization: Bearer ${GH_TOKEN_FOR_REPO}" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      -X DELETE "https://api.github.com/repos/${REPO_FULL}/issues/${ISSUE_NUMBER}/labels/${READY_LABEL}")
    if [ "$REMOVE_STATUS" != "200" ]; then
      echo "ERROR: 移除 ${REPO_FULL}#${ISSUE_NUMBER} 的 ${READY_LABEL} 失敗（HTTP ${REMOVE_STATUS}），下一輪會自動補做"
    fi
    trigger_genie "github-issue ${REPO_FULL}#${ISSUE_NUMBER}"
  done
done
