#!/usr/bin/env bash
# 更新 Mac(OrbStack) 上三隻 bot 的 context 檔（CLAUDE.md / AGENTS.md）：
# git pull openab repo 最新內容，重新 cat 對應的 *_v2.md 進容器內的 CLAUDE.md／AGENTS.md。
#
# 用法：在 **Mac mini(CAC@2771，hostname 2771-Z411210004.local)** 上執行 `bash update-context.sh`。
#
# ⚠️ 這支只管 Mac 上的 Rick/Morty/Summer。k3s 上的 genie/kimi/walle/eve 用
#    ../k3s/update-context.sh（那台機器沒有 OrbStack，兩邊碰不到對方的容器，
#    所以刻意拆成兩支腳本，不做成一支「自動偵測環境」的）。
# ⚠️ 只更新 context 檔本身；不裝/不更新 skill plugin（那是 update-skills.sh）。
# ⚠️ 執行完後，三隻都要在 Discord 各開一條「新 thread」才會重讀 context 檔——
#    舊 thread 不會重讀（見 ../BOT_SETUP.md Part N）。
# ⚠️ 一律 `-u node`：/home/node 底下的檔案必須是 node:node 擁有，用 root 寫進去
#    agent 會讀不到，Discord 端只看得到 Connection Lost。

set -euo pipefail

DOCKER="docker -c orbstack"
BRANCH=docs/three-bot-pipeline
REPO_URL=https://github.com/wm4n/openab.git
CHECKOUT=/home/node/github-repo/openab

# name:容器:persona 來源檔:容器內目標檔
BOTS=(
  "Rick:openab-rick:Rick-CLAUDE_v2.md:CLAUDE.md"
  "Morty:openab-morty:Morty-CLAUDE_v2.md:CLAUDE.md"
  "Summer:openab-summer:Summer-AGENTS_v2.md:AGENTS.md"
)

for entry in "${BOTS[@]}"; do
  IFS=: read -r NAME CONTAINER SRC DST <<< "$entry"
  echo "=== $NAME ($CONTAINER) ==="

  $DOCKER exec -i -u node "$CONTAINER" sh -c "
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

echo "全部更新完成。記得到 Discord 對 Rick / Morty / Summer 各開一條新 thread 才會重讀 context 檔。"
