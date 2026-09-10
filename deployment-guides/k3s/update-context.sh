#!/usr/bin/env bash
# 更新五隻 bot 的 context 檔（CLAUDE.md / AGENTS.md）：git pull openab repo 最新內容，
# 重新 cat 對應的 *_v2.md 進容器內的 CLAUDE.md／AGENTS.md。
#
# 用法：在 k3s 機器上直接執行 `bash update-context.sh`。
#
# ⚠️ 只更新 context 檔本身；不裝/不更新 skill plugin（見 BOT_SETUP.md K2a/K2b）。
# ⚠️ 執行完後，五隻 bot 都要在 Discord 各開一條「新 thread」才會重讀 context 檔——
#    舊 thread 不會重讀（見 BOT_SETUP.md Part N）。
# ⚠️ Kimi（opencode 後端）：values-openab-kimi.yaml 不可設 agentsMd，否則
#    /home/node/AGENTS.md 會是唯讀 ConfigMap，下面的 cat 會失敗（見 bot-setup-opencode-kimi.md 附錄 A）。

set -euo pipefail

NS=cac
BRANCH=docs/three-bot-pipeline
REPO_URL=https://github.com/wm4n/openab.git
CHECKOUT=/home/node/github-repo/openab

# name:deployment:persona 來源檔:容器內目標檔
BOTS=(
  "Rick:openab-claude-rick:Rick-CLAUDE_v2.md:CLAUDE.md"
  "Morty:openab-claude-morty:Morty-CLAUDE_v2.md:CLAUDE.md"
  "Summer:openab-codex-summer:Summer-AGENTS_v2.md:AGENTS.md"
  "Genie:openab-claude-genie:Genie-CLAUDE_v2.md:CLAUDE.md"
  "Kimi:openab-claude-kimi:Kimi-AGENTS_v2.md:AGENTS.md"
)

for entry in "${BOTS[@]}"; do
  IFS=: read -r NAME DEPLOY SRC DST <<< "$entry"
  echo "=== $NAME (deployment/$DEPLOY) ==="

  kubectl exec -i "deployment/$DEPLOY" -n "$NS" -- sh -c "
    set -e
    git clone $REPO_URL $CHECKOUT 2>/dev/null || true
    cd $CHECKOUT
    git fetch origin $BRANCH
    git checkout $BRANCH 2>/dev/null || git checkout -b $BRANCH origin/$BRANCH
    git pull origin $BRANCH
    cat deployment-guides/$SRC > /home/node/$DST
    echo '  -> /home/node/$DST 已更新，開頭：'
    head -3 /home/node/$DST
  "
  echo
done

echo "全部更新完成。記得到 Discord 對 Rick / Morty / Summer / Genie / Kimi 各開一條新 thread 才會重讀 context 檔。"
