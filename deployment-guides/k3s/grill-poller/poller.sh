#!/bin/bash
#
# grill-poller: deterministic 前置判斷，不經過 LLM。
#
# 掃 Jira 專案白名單與 GitHub repo 白名單裡貼了 grill-me 的票/issue，原子性
# 認領（label 換成 grill-me-active）後，用 trigger bot @mention 目標 bot 觸發
# jira-grill skill；另外掃已經在進行中、但人類有新回覆的目標，再次觸發。
#
# 設計依據：docs/superpowers/specs/2026-09-18-split-genie-rick-pollers-design.md
# （前身：2026-08-25-jira-grill-poller-design.md、
#   2026-09-08-genie-jira-grill-routing-design.md）
#
# 一支腳本、多個實例：目標 bot 與來源白名單全部由 env 決定，腳本本身不知道
# 系統裡有哪些 bot。**白名單留空＝完全跳過該來源**，所以只有 GitHub 產品的
# 實例（rick）不需要任何 Jira 設定。
#
# 刻意不 set -e：單一目標處理失敗不該讓整輪中止，後面的目標仍要照掃。

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

READY_LABEL="grill-me"
ACTIVE_LABEL="grill-me-active"
# 留言簽名：兩種來源共用同一格式，所以「有沒有新回覆」的判斷邏輯完全一致。
SIGNATURE="— By ${TARGET_BOT_NAME} (jira-grill)"
# 「最近有更新」的粗篩窗口。只為減少 API 呼叫，真正的判斷靠上面的簽名。
WINDOW_MINUTES=25

# 本輪 Query 1 已經認領並觸發的目標。Query 2 必須跳過它們——剛認領的目標
# label 已是 active、updated 就是現在、而且 bot 還來不及留言，不跳過的話
# 同一輪會對同一個目標觸發兩次。（現行 jira-grill-poller 沒有這個防護，
# 只是靠 Jira 搜尋索引的幾秒延遲偶然擋住；GitHub 沒有那層延遲。）
CLAIMED_THIS_RUN=""

mark_claimed() { CLAIMED_THIS_RUN="${CLAIMED_THIS_RUN}${1}"$'\n'; }
already_claimed() { printf '%s' "$CLAIMED_THIS_RUN" | grep -qxF "$1"; }

# $1 = 貼在觸發訊息裡的參數文字（"ticket CACJOB-123" 或
#      "github-issue wm4n/chainbreak#42"）
trigger_discord() {
  ARG_TEXT="$1"
  BODY=$(node -e '
    process.stdout.write(JSON.stringify({
      content: "<@" + process.argv[1] + "> 執行 jira-grill skill，參數：" + process.argv[2]
    }));
  ' "$TARGET_BOT_ID" "$ARG_TEXT")
  STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bot ${TRIGGER_BOT_TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST "https://discord.com/api/v10/channels/${TRIGGER_CHANNEL}/messages" \
    -d "$BODY")
  if [ "$STATUS" != "200" ]; then
    # 刻意不回滾 label：回滾會造成下一輪重複觸發，停在 active 狀態等人工
    # 處理是較小的代價（已知取捨，見 spec「錯誤處理」）。
    echo "ERROR: 觸發失敗（${ARG_TEXT}，Discord HTTP ${STATUS}）"
  else
    echo "已觸發：${ARG_TEXT}"
  fi
}

# ======================== Jira 來源 ========================
if [ -n "$JIRA_PROJECTS" ]; then
  # 這三個只有走 Jira 來源時才必要——所以檢查放在分支內，不能提到檔案開頭，
  # 否則只有 GitHub 的實例會在第一行就 abort。
  : "${JIRA_TOKEN:?missing JIRA_TOKEN（JIRA_PROJECTS 非空時必填）}"
  : "${JIRA_EMAIL:?missing JIRA_EMAIL（JIRA_PROJECTS 非空時必填）}"
  : "${JIRA_BASE_URL:?missing JIRA_BASE_URL（JIRA_PROJECTS 非空時必填）}"

  PROJECTS_CLAUSE=$(node -e '
    const keys = process.env.JIRA_PROJECTS.split(",").map(s => s.trim()).filter(Boolean);
    console.log("project IN (" + keys.map(k => JSON.stringify(k)).join(",") + ")");
  ')

  # $1 = JQL；印出符合的 ticket key，一行一個。
  # 舊的 GET /rest/api/2/search 已被 Atlassian 下架（HTTP 410），改用
  # POST /rest/api/3/search/jql。本 poller 查詢範圍窄（專案白名單 + 特定
  # label），單頁 50 筆已足夠，不做分頁跟進。
  jira_search() {
    SEARCH_BODY=$(node -e '
      process.stdout.write(JSON.stringify({ jql: process.argv[1], fields: ["key"], maxResults: 50 }));
    ' "$1")
    RESPONSE=$(curl -s -u "${JIRA_EMAIL}:${JIRA_TOKEN}" -w '\n%{http_code}' \
      -X POST "${JIRA_BASE_URL}/rest/api/3/search/jql" \
      -H "Content-Type: application/json" \
      -d "$SEARCH_BODY")
    printf '%s' "$RESPONSE" | node -e '
      const raw = require("fs").readFileSync(0, "utf8");
      const nl = raw.lastIndexOf("\n");
      const status = raw.slice(nl + 1).trim();
      if (status !== "200") {
        console.error("ERROR: JQL 搜尋失敗（HTTP " + status + "）");
        process.exit(0);
      }
      const issues = (JSON.parse(raw.slice(0, nl)).issues) || [];
      for (const i of issues) console.log(i.key);
    '
  }

  echo "== Jira Query 1: 找新票（無時間窗口）=="
  NEW_TICKETS=$(jira_search "${PROJECTS_CLAUSE} AND labels = \"${READY_LABEL}\"")
  if [ -n "$NEW_TICKETS" ]; then
    while IFS= read -r TICKET_ID; do
      [ -z "$TICKET_ID" ] && continue
      # Jira 的 update API 能在單一請求裡同時 remove + add，是原子的——
      # 不像 GitHub 要拆成兩步（見下方）。
      CLAIM_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -u "${JIRA_EMAIL}:${JIRA_TOKEN}" \
        -X PUT "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}" \
        -H "Content-Type: application/json" \
        -d "{\"update\":{\"labels\":[{\"remove\":\"${READY_LABEL}\"},{\"add\":\"${ACTIVE_LABEL}\"}]}}")
      if [ "$CLAIM_STATUS" != "204" ]; then
        echo "ERROR: 認領 ${TICKET_ID} 失敗（改 label HTTP ${CLAIM_STATUS}），跳過，下一輪重試"
        continue
      fi
      trigger_discord "ticket ${TICKET_ID}"
      mark_claimed "jira:${TICKET_ID}"
    done <<< "$NEW_TICKETS"
  else
    echo "(無新票)"
  fi

  echo "== Jira Query 2: 找進行中的票有沒有新回覆（updated >= -${WINDOW_MINUTES}m 粗篩）=="
  ACTIVE_TICKETS=$(jira_search "${PROJECTS_CLAUSE} AND labels = \"${ACTIVE_LABEL}\" AND updated >= \"-${WINDOW_MINUTES}m\"")
  if [ -n "$ACTIVE_TICKETS" ]; then
    while IFS= read -r TICKET_ID; do
      [ -z "$TICKET_ID" ] && continue
      if already_claimed "jira:${TICKET_ID}"; then
        echo "(${TICKET_ID} 本輪剛認領過，跳過)"
        continue
      fi
      RESPONSE=$(curl -s -u "${JIRA_EMAIL}:${JIRA_TOKEN}" -w '\n%{http_code}' \
        "${JIRA_BASE_URL}/rest/api/2/issue/${TICKET_ID}/comment?orderBy=-created&maxResults=1")
      NEEDS_TRIGGER=$(printf '%s' "$RESPONSE" | node -e '
        const raw = require("fs").readFileSync(0, "utf8");
        const nl = raw.lastIndexOf("\n");
        const status = raw.slice(nl + 1).trim();
        if (status !== "200") {
          console.error("ERROR: 抓最新留言失敗（" + process.argv[1] + "，HTTP " + status + "）");
          console.log("skip");
          process.exit(0);
        }
        const comments = (JSON.parse(raw.slice(0, nl)).comments) || [];
        if (comments.length === 0) { console.log("trigger"); process.exit(0); }
        console.log(comments[0].body.includes(process.argv[2]) ? "skip" : "trigger");
      ' "$TICKET_ID" "$SIGNATURE")
      [ "$NEEDS_TRIGGER" = "trigger" ] && trigger_discord "ticket ${TICKET_ID}"
    done <<< "$ACTIVE_TICKETS"
  else
    echo "(無需要處理的既有票)"
  fi
fi

# ======================== GitHub 來源 ========================
if [ -n "$GITHUB_REPOS" ]; then
  SINCE=$(node -e "console.log(new Date(Date.now() - ${WINDOW_MINUTES} * 60000).toISOString())")

  # $1 = owner/repo；印出該 repo 要用的 token（找不到就印空字串）
  token_for_repo() {
    case "${1%%/*}" in
      wm4n) printf '%s' "${GH_TOKEN_WM4N:-}" ;;
      *)    printf '%s' "${GH_TOKEN_CAC:-}" ;;
    esac
  }

  # $1 = owner/repo，$2 = label，$3 = token，$4 = 額外 query（可空）
  # 印出符合的 issue number，一行一個。
  gh_list_issues() {
    RESPONSE=$(curl -s -w '\n%{http_code}' \
      -H "Authorization: Bearer ${3}" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${1}/issues?labels=${2}&state=open${4}")
    printf '%s' "$RESPONSE" | node -e '
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
    ' "$1"
  }

  IFS=',' read -ra REPO_LIST <<< "$GITHUB_REPOS"
  for REPO_FULL_RAW in "${REPO_LIST[@]}"; do
    REPO_FULL=$(echo "$REPO_FULL_RAW" | xargs)
    [ -z "$REPO_FULL" ] && continue
    GH_TOKEN_FOR_REPO=$(token_for_repo "$REPO_FULL")
    if [ -z "$GH_TOKEN_FOR_REPO" ]; then
      # 只跳過這個 owner 的 repo，不讓整支 CronJob 失敗——白名單可能只涵蓋
      # 單一 owner，沒必要逼沒用到的 owner 也生一把 token。
      echo "ERROR: ${REPO_FULL} 需要 owner=${REPO_FULL%%/*} 對應的 GitHub token，但未設定，跳過"
      continue
    fi

    echo "== GitHub Query 1: ${REPO_FULL} 找新 issue =="
    NEW_ISSUES=$(gh_list_issues "$REPO_FULL" "$READY_LABEL" "$GH_TOKEN_FOR_REPO" "")
    if [ -n "$NEW_ISSUES" ]; then
      while IFS= read -r ISSUE_NUMBER; do
        [ -z "$ISSUE_NUMBER" ] && continue
        # GitHub 沒有「一個請求同時 add + remove」的 API，必須兩步。
        # 順序刻意是「先加 active、再移除 ready」：中間失敗會留下同時帶兩個
        # label 的可偵測狀態；反過來寫則會變成兩個 label 都沒有，任務憑空
        # 消失且沒人發現。加 label 本身是 idempotent，重試安全。
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
        trigger_discord "github-issue ${REPO_FULL}#${ISSUE_NUMBER}"
        mark_claimed "gh:${REPO_FULL}#${ISSUE_NUMBER}"
      done <<< "$NEW_ISSUES"
    else
      echo "(${REPO_FULL} 無新 issue)"
    fi

    echo "== GitHub Query 2: ${REPO_FULL} 找進行中的 issue 有沒有新回覆（since=${SINCE}）=="
    ACTIVE_ISSUES=$(gh_list_issues "$REPO_FULL" "$ACTIVE_LABEL" "$GH_TOKEN_FOR_REPO" "&since=${SINCE}")
    if [ -n "$ACTIVE_ISSUES" ]; then
      while IFS= read -r ISSUE_NUMBER; do
        [ -z "$ISSUE_NUMBER" ] && continue
        if already_claimed "gh:${REPO_FULL}#${ISSUE_NUMBER}"; then
          echo "(${REPO_FULL}#${ISSUE_NUMBER} 本輪剛認領過，跳過)"
          continue
        fi
        RESPONSE=$(curl -s -w '\n%{http_code}' \
          -H "Authorization: Bearer ${GH_TOKEN_FOR_REPO}" \
          -H "Accept: application/vnd.github+json" \
          -H "X-GitHub-Api-Version: 2022-11-28" \
          "https://api.github.com/repos/${REPO_FULL}/issues/${ISSUE_NUMBER}/comments?sort=created&direction=desc&per_page=1")
        NEEDS_TRIGGER=$(printf '%s' "$RESPONSE" | node -e '
          const raw = require("fs").readFileSync(0, "utf8");
          const nl = raw.lastIndexOf("\n");
          const status = raw.slice(nl + 1).trim();
          if (status !== "200") {
            console.error("ERROR: 抓最新留言失敗（" + process.argv[1] + "，HTTP " + status + "）");
            console.log("skip");
            process.exit(0);
          }
          const comments = JSON.parse(raw.slice(0, nl)) || [];
          if (comments.length === 0) { console.log("trigger"); process.exit(0); }
          console.log((comments[0].body || "").includes(process.argv[2]) ? "skip" : "trigger");
        ' "${REPO_FULL}#${ISSUE_NUMBER}" "$SIGNATURE")
        [ "$NEEDS_TRIGGER" = "trigger" ] && trigger_discord "github-issue ${REPO_FULL}#${ISSUE_NUMBER}"
      done <<< "$ACTIVE_ISSUES"
    else
      echo "(${REPO_FULL} 無需要處理的既有 issue)"
    fi
  done
fi
