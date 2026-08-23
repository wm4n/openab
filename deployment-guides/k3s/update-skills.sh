#!/usr/bin/env bash
# 更新四隻 bot 已安裝的 plugin/skill 內容到最新版本（marketplace 快照刷新 + plugin 更新）。
#
# 用法：在 k3s 機器上直接執行 `bash update-skills.sh`。
#
# ⚠️ 只更新「plugin 安裝」的 skill（openab-bot-skills、solo-bot-skills、superpowers、skill-registry）。
# ⚠️ 2026-07-24 決定：skill-registry plugin（jira-fetch/learn-from-repo/self-evolution）
#    四隻都裝，不再只給 Morty——起因是發現四隻都沒裝上這個 plugin（含 Morty，代表這支腳本
#    當初補裝 Morty 那段其實從沒真的跑過）；順便決定讓 self-evolution 對全部 bot 都可用。
#    三個 skill 綁同一個 plugin、沒辦法只挑 self-evolution 裝，**已知且接受的 tradeoff**：
#    Rick/Summer/Genie 的能力清單會多出用不到的 jira-fetch/learn-from-repo。
# ⚠️ 全部用 install 而非 update：這隻 plugin 目前四隻都是第一次裝，第一次要用 install
#    才裝得上；用 `|| true` 讓「已安裝」情況下的非零結束碼不會中斷腳本，之後重跑這支
#    腳本也能藉由 install 撿漏。同樣道理套用在 genie 的 solo-bot-skills 上（它是全新
#    bot，第一次跑這支腳本時還沒裝過）。
# ⚠️ genie 裝的是 solo-bot-skills，不是 openab-bot-skills——刻意分開兩個 plugin，避免
#    genie 連帶裝到 feature-development/requirement-analysis/change-review 這些接力
#    pipeline 專用 skill（結構上隔開，不是靠 persona 文件叫它不要用）。
# ⚠️ Claude 端 `claude plugin update` 官方說明是「restart 才生效」；ACP 每次 Discord
#    新 thread 都會起一個全新 session（新的 claude 行程），理論上開新 thread 就夠，
#    不需要重啟 pod。如果新 thread 驗證後發現沒吃到新版，才需要
#    `kubectl rollout restart deployment/<name> -n cac` 保險。
# ⚠️ Codex 沒有 `plugin update` 子指令，用 remove+add 重裝到最新版本；remove 跟 add
#    一樣要帶 <plugin>@<marketplace>（光寫裸名會報 "requires --marketplace" 錯誤）。
#    remove 在從未裝過時也會失敗，用 `|| true` 讓腳本繼續跑，不代表真的有錯。
# ⚠️ marketplace update/upgrade 不指名（更新全部）時，若剛好有一個 marketplace git clone
#    逾時／網路不穩，在 set -e 下會讓整支腳本中斷、後面的 bot 都更新不到。一律指名
#    只更新真正用到的 marketplace，並加 `|| true`：暫時性網路問題不該卡死整支腳本，
#    頂多這次沒刷新到最新 snapshot，下次重跑就好。
# ⚠️ 2026-08-05 新增 `team-bot@cac-plugins`（來源 104corp/104cac-claude-marketplace，
#    marketplace 名稱是 marketplace.json 裡的 "cac-plugins"，跟 repo 名不同，同
#    wm4n/skill-registry → wm4n-skill-registry 的既有慣例）：四隻 bot 都裝，提供
#    product-context skill（產品登錄表脈絡解析）。這個 repo 是 **104corp 私有 repo**，
#    `claude/codex plugin marketplace add` 走 git clone，需要當下 pod 內生效的 gh
#    帳號對這個 repo 有讀權限——Rick/Morty/Summer 是雙帳號（wm4n + cac-william），
#    genie 現在是單帳號 104cac。因此每隻 bot 的 block 開頭都先跑
#    `gh auth switch --hostname github.com --user <該用的帳號>`（Rick/Morty/Summer
#    切 cac-william，genie 切 104cac），確保後面所有 marketplace/plugin 指令都
#    在正確帳號底下執行，不靠操作者手動切、也不靠上一個任務留下的 active 帳號
#    （2026-08-05 實測：Rick 的 active 帳號被上一個任務留在 wm4n，導致
#    `marketplace add` 回 404 "Repository not found"，才補上這步）。這行沒加
#    `|| true`：帳號真的不存在／未登入時應該讓腳本立刻停下來，而不是悶著頭
#    往下跑到更難懂的 "Repository not found"。
# ⚠️ marketplace add 用 `|| true`：四隻都是第一次加這個 marketplace，之後重跑腳本
#    「已加過」會回非零結束碼，忽略即可（跟既有 skill-registry 的加法一致）。
# ⚠️ marketplace add **必須用完整 https:// URL**，不能用 `owner/repo` 簡寫：簡寫會被
#    解析成 SSH URL（git@github.com:...）去 clone，但這批容器映像沒裝 `ssh` 指令
#    （`ssh: not found`），一律失敗並回報「SSH authentication failed」。用完整
#    `https://github.com/104corp/104cac-claude-marketplace` 才會走 gh 已設定好的
#    HTTPS credential helper（`gh auth setup-git`），不會嘗試 SSH。實測踩過（2026-08-05）。
# ⚠️ 2026-08-24 只給 Rick 新增 `mattpocock-skills@claude-plugins-official`：jira-grill
#    skill 的 design-tree/frontier 連續提問方法論引用這個 plugin 裡的 `grilling` skill，
#    單一事實來源留在那邊、jira-grill 本身不重複實作。marketplace `claude-plugins-official`
#    已因 superpowers 而加過，不需要再 `marketplace add`。跟 skill-registry 同樣的
#    tradeoff：這個 plugin 沒辦法只挑 grilling 裝，Rick 會多出 diagnosing-bugs/tdd/
#    prototype/wizard 等用不到的 skill，**已知且接受**。只給 Rick，不給
#    Morty/Summer/Genie——目前只有 jira-grill 需要它。

set -euo pipefail

NS=cac

echo "=== Rick (openab-claude-rick) ==="
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- gh auth switch --hostname github.com --user cac-william
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin marketplace update wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin marketplace update claude-plugins-official || true
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin update openab-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin update superpowers@claude-plugins-official
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin install mattpocock-skills@claude-plugins-official || true
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin update mattpocock-skills@claude-plugins-official
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin install skill-registry@wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin update skill-registry@wm4n-skill-registry
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin marketplace add https://github.com/104corp/104cac-claude-marketplace || true
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin marketplace update cac-plugins || true
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin install team-bot@cac-plugins || true
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin update team-bot@cac-plugins
echo

echo "=== Morty (openab-claude-morty) ==="
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- gh auth switch --hostname github.com --user cac-william
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin marketplace update wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin marketplace update claude-plugins-official || true
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin update openab-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin update superpowers@claude-plugins-official
# skill-registry（jira-fetch）：marketplace 理論上已因 openab-bot-skills 而註冊過，
# 這行只是防呆；install 補裝漏裝的部分，已裝過時 install 會失敗、忽略即可
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin marketplace add wm4n/skill-registry || true
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin install skill-registry@wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin update skill-registry@wm4n-skill-registry
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin marketplace add https://github.com/104corp/104cac-claude-marketplace || true
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin marketplace update cac-plugins || true
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin install team-bot@cac-plugins || true
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin update team-bot@cac-plugins
echo

echo "=== Genie (openab-claude-genie) ==="
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- gh auth switch --hostname github.com --user 104cac
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin marketplace add wm4n/skill-registry || true
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin marketplace update wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin install solo-bot-skills@wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin update solo-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin install skill-registry@wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin update skill-registry@wm4n-skill-registry
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin marketplace add https://github.com/104corp/104cac-claude-marketplace || true
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin marketplace update cac-plugins || true
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin install team-bot@cac-plugins || true
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin update team-bot@cac-plugins
echo

echo "=== Summer (openab-codex-summer) ==="
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- gh auth switch --hostname github.com --user cac-william
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin marketplace upgrade wm4n-skill-registry || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin marketplace upgrade superpowers-marketplace || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin remove openab-bot-skills@wm4n-skill-registry || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin add openab-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin remove superpowers@superpowers-marketplace || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin add superpowers@superpowers-marketplace
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin remove skill-registry@wm4n-skill-registry || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin add skill-registry@wm4n-skill-registry
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin marketplace add https://github.com/104corp/104cac-claude-marketplace || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin marketplace upgrade cac-plugins || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin remove team-bot@cac-plugins || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin add team-bot@cac-plugins
echo

echo "全部更新完成。到 Discord 對 Rick / Morty / Summer / Genie 各開一條新 thread 再驗證；"
echo "若新 thread 驗證後發現還是舊版，才需要 kubectl rollout restart deployment/<name> -n cac。"
