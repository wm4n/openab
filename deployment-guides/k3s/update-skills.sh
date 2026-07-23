#!/usr/bin/env bash
# 更新三隻 bot 已安裝的 plugin/skill 內容到最新版本（marketplace 快照刷新 + plugin 更新）。
#
# 用法：在 k3s 機器上直接執行 `bash update-skills.sh`。
#
# ⚠️ 只更新「plugin 安裝」的 skill（openab-bot-skills、superpowers、skill-registry）。
# ⚠️ Morty 的 skill-registry（jira-fetch 所在的 plugin）用 install 而非 update：
#    這隻 plugin 之前漏裝，第一次跑要用 install 才裝得上；用 `|| true` 讓「已安裝」
#    情況下的非零結束碼不會中斷腳本，之後重跑這支腳本也能藉由 install 撿漏。
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

echo "=== Summer (openab-codex-summer) ==="
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin marketplace upgrade wm4n-skill-registry || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin marketplace upgrade superpowers-marketplace || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin remove openab-bot-skills@wm4n-skill-registry || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin add openab-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin remove superpowers@superpowers-marketplace || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin add superpowers@superpowers-marketplace
echo

echo "全部更新完成。到 Discord 對 Rick / Morty / Summer 各開一條新 thread 再驗證；"
echo "若新 thread 驗證後發現還是舊版，才需要 kubectl rollout restart deployment/<name> -n cac。"
