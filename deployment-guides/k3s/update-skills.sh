#!/usr/bin/env bash
# 更新三隻 bot 已安裝的 plugin/skill 內容到最新版本（marketplace 快照刷新 + plugin 更新）。
#
# 用法：在 k3s 機器上直接執行 `bash update-skills.sh`。
#
# ⚠️ 只更新「plugin 安裝」的 skill（openab-bot-skills、superpowers）。
#    jira-fetch 目前仍是 clone + symlink（見 BOT_SETUP.md Part K2），不在此腳本範圍。
# ⚠️ Claude 端 `claude plugin update` 官方說明是「restart 才生效」；ACP 每次 Discord
#    新 thread 都會起一個全新 session（新的 claude 行程），理論上開新 thread 就夠，
#    不需要重啟 pod。如果新 thread 驗證後發現沒吃到新版，才需要
#    `kubectl rollout restart deployment/<name> -n cac` 保險。
# ⚠️ Codex 沒有 `plugin update` 子指令，用 remove+add 重裝到最新版本（remove 找不到
#    舊安裝時會失敗，用 `|| true` 讓腳本繼續跑，不代表真的有錯）。

set -euo pipefail

NS=cac

echo "=== Rick (openab-claude-rick) ==="
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin marketplace update
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin update openab-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-claude-rick" -n "$NS" -- claude plugin update superpowers@claude-plugins-official
echo

echo "=== Morty (openab-claude-morty) ==="
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin marketplace update
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin update openab-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-claude-morty" -n "$NS" -- claude plugin update superpowers@claude-plugins-official
echo

echo "=== Summer (openab-codex-summer) ==="
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin marketplace upgrade
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin remove openab-bot-skills || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin add openab-bot-skills@wm4n-skill-registry
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin remove superpowers || true
kubectl exec "deployment/openab-codex-summer" -n "$NS" -- codex plugin add superpowers@superpowers-marketplace
echo

echo "全部更新完成。到 Discord 對 Rick / Morty / Summer 各開一條新 thread 再驗證；"
echo "若新 thread 驗證後發現還是舊版，才需要 kubectl rollout restart deployment/<name> -n cac。"
