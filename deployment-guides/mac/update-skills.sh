#!/usr/bin/env bash
# 更新 Mac(OrbStack) 上三隻 bot 已安裝的 plugin/skill 到最新版本
# （marketplace 快照刷新 + plugin install/update）。
#
# 用法：在 **Mac mini(CAC@2771，hostname 2771-Z411210004.local)** 上執行 `bash update-skills.sh`。
#
# ⚠️ 這支只管 Mac 上的 Rick/Morty/Summer；k3s 上的 genie 用 ../k3s/update-skills.sh。
#    kimi/walle/eve（opencode）目前沒裝任何 skill，兩支腳本都不涵蓋。
#
# 三隻現行的 plugin 組合（2026-09-15 獨狼化後一致）：
#   - solo-bot-skills@wm4n-skill-registry   solo-feature-pipeline / jira-grill / openab-schedule
#   - openab-bot-skills@wm4n-skill-registry 現在只為了 change-review(-codex)
#   - skill-registry@wm4n-skill-registry    jira-fetch / figma-fetch / learn-from-repo / self-evolution
#   - superpowers                           Claude 走 claude-plugins-official，Codex 走 obra/superpowers-marketplace
#   - team-bot@cac-plugins                  product-context（104corp 私有 marketplace）
#   - mattpocock-skills@claude-plugins-official  grilling（jira-grill 的連續提問方法論來源）
#                                           + diagnosing-bugs / tdd / prototype / code-review 等
#
# ⚠️ mattpocock-skills 從「只給 Rick」改成 **Rick/Morty/Summer 三隻都裝**（2026-09-17）。
#    原本只給 Rick 是因為當時只有它跑 jira-grill；獨狼化後三隻能力對等，沒有理由厚此薄彼。
#    k3s 上的 genie 不在此列（維持原樣）。
# ⚠️ **Summer 這隻是未驗證的路徑**：Codex 端的 superpowers 當初就是因為
#    `anthropics/claude-plugins-official` 對 Codex 沒驗證通過，才改用
#    `obra/superpowers-marketplace`（見 BOT_SETUP.md K2a）。Summer 的 mattpocock 區塊
#    因此刻意設成**失敗不中斷腳本、只印警告**——裝不上時請看警告、到 Discord 用
#    `codex plugin list` 確認，別以為它靜悄悄裝好了。
#
# ⚠️ 每隻開頭先 `gh auth switch --user cac-william`：`cac-plugins` 這個 marketplace 是
#    104corp 私有 repo，`marketplace add` 走 git clone，要用有讀權限的帳號。三隻都是
#    wm4n + cac-william 雙帳號，active 帳號可能被上一個任務留在 wm4n（實測踩過，會回
#    404 Repository not found）。這行不加 `|| true`：帳號沒登入就該立刻停，不要悶著頭
#    往下跑到更難懂的錯誤。
# ⚠️ `marketplace add` **一律用完整 https:// URL**，不能用 owner/repo 簡寫：簡寫會被解析
#    成 SSH URL，但映像沒裝 ssh client（`ssh: not found`），一律失敗。
# ⚠️ install 一律配 `|| true` 再接 update：第一次要 install、之後 install 會回非零，
#    這樣同一支腳本既能補漏也能更新。
# ⚠️ Codex 沒有 `plugin update` 子指令，用 remove+add 重裝；remove/add 都要帶
#    <plugin>@<marketplace>（光寫裸名會報 "requires --marketplace"）。
# ⚠️ marketplace update/upgrade 一律指名、且加 `|| true`：不指名會更新全部，其中一個
#    網路不穩就會在 set -e 下中斷整支腳本。
# ⚠️ 更新完開新 thread 即可生效（ACP 每條新 thread 都是全新 CLI 行程），不需要重啟容器；
#    新 thread 驗證後還是舊版才需要 `docker -c orbstack restart <容器>`。

set -euo pipefail

DOCKER="docker -c orbstack"

echo "=== Rick (openab-rick) ==="
$DOCKER exec -u node openab-rick gh auth switch --hostname github.com --user cac-william
$DOCKER exec -u node openab-rick claude plugin marketplace add https://github.com/wm4n/skill-registry || true
$DOCKER exec -u node openab-rick claude plugin marketplace add https://github.com/anthropics/claude-plugins-official || true
$DOCKER exec -u node openab-rick claude plugin marketplace add https://github.com/104corp/104cac-claude-marketplace || true
$DOCKER exec -u node openab-rick claude plugin marketplace update wm4n-skill-registry || true
$DOCKER exec -u node openab-rick claude plugin marketplace update claude-plugins-official || true
$DOCKER exec -u node openab-rick claude plugin marketplace update cac-plugins || true
$DOCKER exec -u node openab-rick claude plugin install solo-bot-skills@wm4n-skill-registry || true
$DOCKER exec -u node openab-rick claude plugin update  solo-bot-skills@wm4n-skill-registry
$DOCKER exec -u node openab-rick claude plugin install openab-bot-skills@wm4n-skill-registry || true
$DOCKER exec -u node openab-rick claude plugin update  openab-bot-skills@wm4n-skill-registry
$DOCKER exec -u node openab-rick claude plugin install skill-registry@wm4n-skill-registry || true
$DOCKER exec -u node openab-rick claude plugin update  skill-registry@wm4n-skill-registry
$DOCKER exec -u node openab-rick claude plugin install superpowers@claude-plugins-official || true
$DOCKER exec -u node openab-rick claude plugin update  superpowers@claude-plugins-official
$DOCKER exec -u node openab-rick claude plugin install mattpocock-skills@claude-plugins-official || true
$DOCKER exec -u node openab-rick claude plugin update  mattpocock-skills@claude-plugins-official
$DOCKER exec -u node openab-rick claude plugin install team-bot@cac-plugins || true
$DOCKER exec -u node openab-rick claude plugin update  team-bot@cac-plugins
$DOCKER exec -u node openab-rick claude plugin list
echo

echo "=== Morty (openab-morty) ==="
$DOCKER exec -u node openab-morty gh auth switch --hostname github.com --user cac-william
$DOCKER exec -u node openab-morty claude plugin marketplace add https://github.com/wm4n/skill-registry || true
$DOCKER exec -u node openab-morty claude plugin marketplace add https://github.com/anthropics/claude-plugins-official || true
$DOCKER exec -u node openab-morty claude plugin marketplace add https://github.com/104corp/104cac-claude-marketplace || true
$DOCKER exec -u node openab-morty claude plugin marketplace update wm4n-skill-registry || true
$DOCKER exec -u node openab-morty claude plugin marketplace update claude-plugins-official || true
$DOCKER exec -u node openab-morty claude plugin marketplace update cac-plugins || true
$DOCKER exec -u node openab-morty claude plugin install solo-bot-skills@wm4n-skill-registry || true
$DOCKER exec -u node openab-morty claude plugin update  solo-bot-skills@wm4n-skill-registry
$DOCKER exec -u node openab-morty claude plugin install openab-bot-skills@wm4n-skill-registry || true
$DOCKER exec -u node openab-morty claude plugin update  openab-bot-skills@wm4n-skill-registry
$DOCKER exec -u node openab-morty claude plugin install skill-registry@wm4n-skill-registry || true
$DOCKER exec -u node openab-morty claude plugin update  skill-registry@wm4n-skill-registry
$DOCKER exec -u node openab-morty claude plugin install superpowers@claude-plugins-official || true
$DOCKER exec -u node openab-morty claude plugin update  superpowers@claude-plugins-official
$DOCKER exec -u node openab-morty claude plugin install mattpocock-skills@claude-plugins-official || true
$DOCKER exec -u node openab-morty claude plugin update  mattpocock-skills@claude-plugins-official
$DOCKER exec -u node openab-morty claude plugin install team-bot@cac-plugins || true
$DOCKER exec -u node openab-morty claude plugin update  team-bot@cac-plugins
$DOCKER exec -u node openab-morty claude plugin list
echo

echo "=== Summer (openab-summer) ==="
$DOCKER exec -u node openab-summer gh auth switch --hostname github.com --user cac-william
$DOCKER exec -u node openab-summer codex plugin marketplace add https://github.com/wm4n/skill-registry || true
$DOCKER exec -u node openab-summer codex plugin marketplace add https://github.com/obra/superpowers-marketplace || true
$DOCKER exec -u node openab-summer codex plugin marketplace add https://github.com/104corp/104cac-claude-marketplace || true
$DOCKER exec -u node openab-summer codex plugin marketplace upgrade wm4n-skill-registry || true
$DOCKER exec -u node openab-summer codex plugin marketplace upgrade superpowers-marketplace || true
$DOCKER exec -u node openab-summer codex plugin marketplace upgrade cac-plugins || true
$DOCKER exec -u node openab-summer codex plugin remove solo-bot-skills@wm4n-skill-registry || true
$DOCKER exec -u node openab-summer codex plugin add    solo-bot-skills@wm4n-skill-registry
$DOCKER exec -u node openab-summer codex plugin remove openab-bot-skills@wm4n-skill-registry || true
$DOCKER exec -u node openab-summer codex plugin add    openab-bot-skills@wm4n-skill-registry
$DOCKER exec -u node openab-summer codex plugin remove skill-registry@wm4n-skill-registry || true
$DOCKER exec -u node openab-summer codex plugin add    skill-registry@wm4n-skill-registry
$DOCKER exec -u node openab-summer codex plugin remove superpowers@superpowers-marketplace || true
$DOCKER exec -u node openab-summer codex plugin add    superpowers@superpowers-marketplace
$DOCKER exec -u node openab-summer codex plugin remove team-bot@cac-plugins || true
$DOCKER exec -u node openab-summer codex plugin add    team-bot@cac-plugins

# mattpocock-skills（2026-09-17 起三隻都裝）。Codex 對 claude-plugins-official 這個
# marketplace 是未驗證路徑，整段包成失敗不中斷、只印警告——見檔頭說明。
if $DOCKER exec -u node openab-summer codex plugin marketplace add https://github.com/anthropics/claude-plugins-official 2>/dev/null ||
   $DOCKER exec -u node openab-summer codex plugin marketplace upgrade claude-plugins-official 2>/dev/null; then
  $DOCKER exec -u node openab-summer codex plugin remove mattpocock-skills@claude-plugins-official 2>/dev/null || true
  if ! $DOCKER exec -u node openab-summer codex plugin add mattpocock-skills@claude-plugins-official; then
    echo "⚠️  Summer 的 mattpocock-skills 裝不起來（codex plugin add 失敗）——跳過，其餘 plugin 不受影響。"
    echo "    請人工確認：docker -c orbstack exec -u node openab-summer codex plugin list"
  fi
else
  echo "⚠️  Summer 加不了 claude-plugins-official 這個 marketplace（Codex 對它是未驗證路徑）。"
  echo "    mattpocock-skills 這次跳過；要它的 grilling skill 的話得另尋 Codex 端來源。"
fi

$DOCKER exec -u node openab-summer codex plugin list
echo

echo "全部更新完成。到 Discord 對 Rick / Morty / Summer 各開一條新 thread 再驗證；"
echo "若新 thread 驗證後發現還是舊版，才需要 docker -c orbstack restart <容器>。"
