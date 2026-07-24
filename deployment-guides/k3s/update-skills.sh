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

set -euo pipefail

NS=cac

echo "=== Rick (openab-claude-rick) ==="
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin marketplace update wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin marketplace update claude-plugins-official || true
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin update openab-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin update superpowers@claude-plugins-official
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin install skill-registry@wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin update skill-registry@wm4n-skill-registry
echo

echo "=== Morty (openab-claude-morty) ==="
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin marketplace update wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin marketplace update claude-plugins-official || true
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin update openab-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin update superpowers@claude-plugins-official
# skill-registry（jira-fetch）：marketplace 理論上已因 openab-bot-skills 而註冊過，
# 這行只是防呆；install 補裝漏裝的部分，已裝過時 install 會失敗、忽略即可
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin marketplace add wm4n/skill-registry || true
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin install skill-registry@wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin update skill-registry@wm4n-skill-registry
echo

echo "=== Genie (openab-claude-genie) ==="
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin marketplace add wm4n/skill-registry || true
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin marketplace update wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin install solo-bot-skills@wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin update solo-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin install skill-registry@wm4n-skill-registry || true
kubectl exec "deployment/openab-claude-genie" -n "$NS" -- claude plugin update skill-registry@wm4n-skill-registry
echo

echo "=== Summer (openab-codex-summer) ==="
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin marketplace upgrade wm4n-skill-registry || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin marketplace upgrade superpowers-marketplace || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin remove openab-bot-skills@wm4n-skill-registry || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin add openab-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin remove superpowers@superpowers-marketplace || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin add superpowers@superpowers-marketplace
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin remove skill-registry@wm4n-skill-registry || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin add skill-registry@wm4n-skill-registry
echo

echo "全部更新完成。到 Discord 對 Rick / Morty / Summer / Genie 各開一條新 thread 再驗證；"
echo "若新 thread 驗證後發現還是舊版，才需要 kubectl rollout restart deployment/<name> -n cac。"
