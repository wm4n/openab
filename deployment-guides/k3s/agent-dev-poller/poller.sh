#!/bin/bash
#
# agent-dev-poller: deterministic 前置判斷，不經過 LLM。
#
# 掃 Jira 專案白名單與 GitHub repo 白名單裡貼了 ready-for-agent-dev 的票/issue，
# 確認沒有未解的 blocker 後原子性認領（label 換成 agent-dev-active），用 trigger
# bot @mention 目標 bot 觸發 auto-dev-pipeline skill。
#
# 刻意不做的事：repo 解析、規格是否完整、要不要真的開發——全部交給目標 bot
# （有 LLM 判斷能力）處理，這支 script 只回答「有沒有新目標該交給它」。
#
# 設計依據：docs/superpowers/specs/2026-09-18-split-genie-rick-pollers-design.md
#
# ⚠️ 2026-09-18 參數化：原本目標 bot 寫死 genie（GENIE_DISCORD_USER_ID、
#    trigger_genie()），現在改成一支腳本、多個實例，env 契約與 grill-poller
#    完全一致。**白名單留空＝完全跳過該來源**，所以只有 GitHub 產品的實例
#    （rick）不需要任何 Jira 設定。
#    舊的 cronjob.yaml（內嵌自己的 script 副本、只服務 genie）在 genie 切到
#    新實例之前維持不動，兩者互不影響。
#
# 刻意不 set -e：單一目標處理失敗不該讓整輪中止。

# 一律必填
: "${TARGET_BOT_ID:?missing TARGET_BOT_ID}"
: "${TARGET_BOT_NAME:?missing TARGET_BOT_NAME}"
: "${TRIGGER_CHANNEL:?missing TRIGGER_CHANNEL}"
: "${TRIGGER_BOT_TOKEN:?missing TRIGGER_BOT_TOKEN}"

# 兩個來源白名單，至少要有一個
JIRA_PROJECTS="${JIRA_PROJECTS:-}"
GITHUB_REPOS="${GITHUB_REPOS:-}"
if [ -z "$JIRA_PROJECTS" ] && [ -z "$GITHUB_REPOS" ]; then
  echo "ERROR: JIRA_PROJECTS 與 GITHUB_REPOS 不能同時為空" >&2
  exit 1
fi

READY_LABEL="ready-for-agent-dev"
ACTIVE_LABEL="agent-dev-active"

# 每輪只認領＋觸發一張（Jira 優先，沒有才輪到 GitHub），找到就結束，避免同一
# 時間派出多個開發工作互撞。沒撿到的候選留給下一輪繼續掃。
CLAIMED=""

# $1 = 貼在觸發訊息裡的參數文字（"jira-ticket CACJOB-123" 或
#      "github-issue wm4n/chainbreak#42"）
trigger_target() {
  ARG_TEXT="$1"
  BODY=$(node -e '
    process.stdout.write(JSON.stringify({
      content: "<@" + process.argv[1] + "> 執行 auto-dev-pipeline skill，參數：" + process.argv[2]
    }));
  ' "$TARGET_BOT_ID" "$ARG_TEXT")
  STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bot ${TRIGGER_BOT_TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST "https://discord.com/api/v10/channels/${TRIGGER_CHANNEL}/messages" \
    -d "$BODY")
  if [ "$STATUS" != "200" ]; then
    # 刻意不回滾 label：回滾會造成下一輪重複觸發，停在 active 狀態等人工處理
    # 是較小的代價。
    echo "ERROR: 觸發失敗（${ARG_TEXT} → ${TARGET_BOT_NAME}，Discord HTTP ${STATUS}）"
  else
    echo "已觸發：${ARG_TEXT} → ${TARGET_BOT_NAME}"
  fi
}

# ======================== Jira 來源 ========================
if [ -n "$JIRA_PROJECTS" ]; then
  # 這三個只有走 Jira 來源時才必要——檢查放在分支內，不能提到檔案開頭，否則
  # 只有 GitHub 的實例會在第一行就 abort。
  : "${JIRA_TOKEN:?missing JIRA_TOKEN（JIRA_PROJECTS 非空時必填）}"
  : "${JIRA_EMAIL:?missing JIRA_EMAIL（JIRA_PROJECTS 非空時必填）}"
  : "${JIRA_BASE_URL:?missing JIRA_BASE_URL（JIRA_PROJECTS 非空時必填）}"

  # $1 = TICKET_ID；印出 "blocked" 或 "clear"。查詢本身失敗時保守判定為
  # blocked（跳過、下一輪重試），不冒進觸發還沒解除依賴的票。
  check_jira_blocked() {
    RESPONSE=$(curl -s -u "${JIRA_EMAIL}:${JIRA_TOKEN}" -w '\n%{http_code}' \
      "${JIRA_BASE_URL}/rest/api/2/issue/${1}?fields=issuelinks")
    printf '%s' "$RESPONSE" | node -e '
      const raw = require("fs").readFileSync(0, "utf8");
      const nl = raw.lastIndexOf("\n");
      const status = raw.slice(nl + 1).trim();
      if (status !== "200") {
        console.error("ERROR: 查 " + process.argv[1] + " 的 issuelinks 失敗（HTTP " + status + "），保守判定為 blocked");
        console.log("blocked");
        process.exit(0);
      }
      const links = ((JSON.parse(raw.slice(0, nl)).fields) || {}).issuelinks || [];
      const openBlockers = links
        .filter(l => l.inwardIssue) // inwardIssue = 對這張票而言是「is blocked by」方向
        .filter(l => (((l.inwardIssue.fields || {}).status || {}).statusCategory || {}).key !== "done");
      console.log(openBlockers.length > 0 ? "blocked" : "clear");
    ' "$1"
  }

  echo "== Jira：找貼 ${READY_LABEL} 的票 =="
  PROJECTS_CLAUSE=$(node -e '
    const keys = process.env.JIRA_PROJECTS.split(",").map(s => s.trim()).filter(Boolean);
    console.log("project IN (" + keys.map(k => JSON.stringify(k)).join(",") + ")");
  ')
  SEARCH_BODY=$(node -e '
    process.stdout.write(JSON.stringify({ jql: process.argv[1], fields: ["key"], maxResults: 50 }));
  ' "${PROJECTS_CLAUSE} AND labels = \"${READY_LABEL}\"")
  RESPONSE=$(curl -s -u "${JIRA_EMAIL}:${JIRA_TOKEN}" -w '\n%{http_code}' \
    -X POST "${JIRA_BASE_URL}/rest/api/3/search/jql" \
    -H "Content-Type: application/json" \
    -d "$SEARCH_BODY")
  TICKETS=$(printf '%s' "$RESPONSE" | node -e '
    const raw = require("fs").readFileSync(0, "utf8");
    const nl = raw.lastIndexOf("\n");
    const status = raw.slice(nl + 1).trim();
    if (status !== "200") {
      console.error("ERROR: JQL 搜尋失敗（HTTP " + status + "）");
      process.exit(0);
    }
    const issues = (JSON.parse(raw.slice(0, nl)).issues) || [];
    for (const i of issues) console.log(i.key);
  ')

  if [ -n "$TICKETS" ]; then
    while IFS= read -r TICKET_ID; do
      [ -z "$TICKET_ID" ] && continue
      BLOCK_STATE=$(check_jira_blocked "$TICKET_ID")
      if [ "$BLOCK_STATE" = "blocked" ]; then
        echo "(${TICKET_ID} 仍被其他票 block 住，本輪跳過)"
        continue
      fi
      CLAIM_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
        -X PUT "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}" \
        -H "Content-Type: application/json" \
        -d "{\"update\":{\"labels\":[{\"remove\":\"${READY_LABEL}\"},{\"add\":\"${ACTIVE_LABEL}\"}]}}")
      if [ "$CLAIM_STATUS" != "204" ]; then
        echo "ERROR: 認領 ${TICKET_ID} 失敗（改 label HTTP ${CLAIM_STATUS}），跳過，下一輪重試"
        continue
      fi
      trigger_target "jira-ticket ${TICKET_ID}"
      CLAIMED=1
      break
    done <<< "$TICKETS"
  else
    echo "(無符合條件的 Jira 票)"
  fi
fi

# ======================== GitHub 來源 ========================
if [ -z "$CLAIMED" ] && [ -n "$GITHUB_REPOS" ]; then
  # $1 = owner/repo；印出該 repo 要用的 token（找不到就印空字串）
  token_for_repo() {
    case "${1%%/*}" in
      wm4n) printf '%s' "${GH_TOKEN_WM4N:-}" ;;
      *)    printf '%s' "${GH_TOKEN_CAC:-}" ;;
    esac
  }

  # $1 = owner/repo，$2 = issue number，$3 = token；印出 "blocked" 或 "clear"。
  # 查詢本身失敗時保守判定為 blocked。
  check_github_blocked() {
    QUERY=$(node -e '
      const owner = process.argv[1], name = process.argv[2], number = Number(process.argv[3]);
      const query = "query($owner:String!,$name:String!,$number:Int!){ repository(owner:$owner,name:$name){ issue(number:$number){ blockedBy(first:20){ nodes{ number state } } } } }";
      process.stdout.write(JSON.stringify({ query, variables: { owner, name, number } }));
    ' "${1%%/*}" "${1#*/}" "$2")
    RESPONSE=$(curl -s -w '\n%{http_code}' \
      -H "Authorization: Bearer ${3}" \
      -H "Content-Type: application/json" \
      -X POST "https://api.github.com/graphql" \
      -d "$QUERY")
    printf '%s' "$RESPONSE" | node -e '
      const raw = require("fs").readFileSync(0, "utf8");
      const nl = raw.lastIndexOf("\n");
      const status = raw.slice(nl + 1).trim();
      if (status !== "200") {
        console.error("ERROR: 查 " + process.argv[1] + " 的 blockedBy 失敗（HTTP " + status + "），保守判定為 blocked");
        console.log("blocked");
        process.exit(0);
      }
      const parsed = JSON.parse(raw.slice(0, nl));
      if (parsed.errors || !parsed.data || !parsed.data.repository || !parsed.data.repository.issue) {
        console.error("ERROR: " + process.argv[1] + " 的 blockedBy GraphQL 查詢錯誤，保守判定為 blocked：" + JSON.stringify(parsed.errors || parsed));
        console.log("blocked");
        process.exit(0);
      }
      const nodes = parsed.data.repository.issue.blockedBy.nodes || [];
      console.log(nodes.filter(n => n.state === "OPEN").length > 0 ? "blocked" : "clear");
    ' "${1}#${2}"
  }

  echo "== GitHub：找貼 ${READY_LABEL} 的 issue =="
  IFS=',' read -ra REPO_LIST <<< "$GITHUB_REPOS"
  for REPO_FULL_RAW in "${REPO_LIST[@]}"; do
    [ -n "$CLAIMED" ] && break
    REPO_FULL=$(echo "$REPO_FULL_RAW" | xargs)
    [ -z "$REPO_FULL" ] && continue
    GH_TOKEN_FOR_REPO=$(token_for_repo "$REPO_FULL")
    if [ -z "$GH_TOKEN_FOR_REPO" ]; then
      # 只跳過這個 owner 的 repo，不讓整支 CronJob 失敗。
      echo "ERROR: ${REPO_FULL} 需要 owner=${REPO_FULL%%/*} 對應的 GitHub token，但未設定，跳過"
      continue
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
      if (status !== "200") {
        console.error("ERROR: 列 issue 失敗（" + process.argv[1] + "，HTTP " + status + "）");
        process.exit(0);
      }
      for (const i of (JSON.parse(raw.slice(0, nl)) || [])) {
        if (i.pull_request) continue; // issues 端點會把 PR 也算進來，排除
        console.log(i.number);
      }
    ' "$REPO_FULL")
    if [ -z "$NUMBERS" ]; then
      echo "(${REPO_FULL} 無符合條件的 issue)"
      continue
    fi

    while IFS= read -r ISSUE_NUMBER; do
      [ -z "$ISSUE_NUMBER" ] && continue
      BLOCK_STATE=$(check_github_blocked "$REPO_FULL" "$ISSUE_NUMBER" "$GH_TOKEN_FOR_REPO")
      if [ "$BLOCK_STATE" = "blocked" ]; then
        echo "(${REPO_FULL}#${ISSUE_NUMBER} 仍被其他 issue block 住，本輪跳過)"
        continue
      fi
      # 先加 active（idempotent，重試安全），成功後才移除 ready——順序反過來
      # 的話，萬一移除成功但新增失敗，這張 issue 會兩個 label 都沒有，下一輪
      # 永遠撿不回來。
      ADD_STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
        -H "Authorization: Bearer ${GH_TOKEN_FOR_REPO}" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        -X POST "https://api.github.com/repos/${REPO_FULL}/issues/${ISSUE_NUMBER}/labels" \
        -d "{\"labels\":[\"${ACTIVE_LABEL}\"]}")
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
      trigger_target "github-issue ${REPO_FULL}#${ISSUE_NUMBER}"
      CLAIMED=1
      break
    done <<< "$NUMBERS"
  done
fi
