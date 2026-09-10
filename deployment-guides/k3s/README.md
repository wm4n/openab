# k3s 部署工件

三隻 bot 遷移到單節點 k3s 的 Helm values 與秘密範本。**完整操作步驟見 [`../K3S.md`](../K3S.md)**；設計依據見 `docs/superpowers/specs/2026-07-20-k3s-migration-design.md`。

## 檔案

| 檔案 | 用途 |
| --- | --- |
| `values-openab-claude.yaml` | `openab-claude` release：Rick + Morty（RuntimeDefault） |
| `values-openab-codex.yaml` | `openab-codex` release：Summer（seccomp Unconfined） |
| `values-openab-kimi.yaml` | Kimi bot overlay（opencode + OpenRouter，模型 `moonshotai/kimi-k3`）：可併進 `openab-claude` release 或獨立 release。做法見 [`../bot-setup-opencode-kimi.md`](../bot-setup-opencode-kimi.md) 附錄 A |
| `values-openab-walle.yaml` | Wall-E bot overlay（opencode + OpenRouter，模型 `deepseek/deepseek-v4-pro-0813`）。跟 Kimi 同套，見附錄 C |
| `values-openab-eve.yaml` | Eve bot overlay（opencode + OpenRouter，模型 `z-ai/glm-5.2`）。跟 Kimi 同套，見附錄 C |
| `values-secret-claude.example.yaml` | 複製成 `values-secret-claude.yaml`（gitignored）填 Rick/Morty 的 Discord token |
| `values-secret-codex.example.yaml` | 複製成 `values-secret-codex.yaml`（gitignored）填 Summer 的 Discord token |
| `values-secret-kimi.example.yaml` | 複製成 `values-secret-kimi.yaml`（gitignored）填 Kimi bot 的 Discord token |
| `values-secret-walle.example.yaml` | 複製成 `values-secret-walle.yaml`（gitignored）填 Wall-E 的 Discord token |
| `values-secret-eve.example.yaml` | 複製成 `values-secret-eve.yaml`（gitignored）填 Eve 的 Discord token |
| `.gitignore` | 擋 `values-secret*.yaml` 被 commit |

## 快速驗證（在有 helm 的機器）

> ⚠️ `helm lint` **只吃本機 chart 路徑或 .tgz**，不接受 `oci://`。repo 已 clone
> 時直接指本機 chart `../../charts/openab`（也保證 values 對得上你手上的 chart 版本，
> 避免 OCI 發佈版較舊、缺 `allowedRoleIds`/`cron`/`secretEnv` 欄位）。

```bash
# 語法/模板檢查（給假 token 只為通過 render）
helm lint ../../charts/openab \
  -f values-openab-claude.yaml \
  --set agents.rick.discord.botToken=x --set agents.morty.discord.botToken=y

# 看生成的 config.toml 對不對
helm template openab-claude ../../charts/openab \
  -f values-openab-claude.yaml \
  --set agents.rick.discord.botToken=x --set agents.morty.discord.botToken=y \
  | grep -E 'command|allowed_role_ids|inherit_env|working_dir'
```

> `helm template` / `helm install` 則**可**用 OCI（`oci://ghcr.io/openabdev/charts/openab`）
> 或 GitHub Pages repo（`helm repo add openab https://openabdev.github.io/openab`）——
> 但若欄位對不上請改回本機 chart 或用 `--version` 指定較新版。

## 安裝（節錄，完整見 K3S.md）

```bash
kubectl create namespace cac
cp values-secret-claude.example.yaml values-secret-claude.yaml              # 填真值
cp values-secret-codex.example.yaml values-secret-codex.yaml # 填真值

helm install openab-claude oci://ghcr.io/openabdev/charts/openab -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml
helm install openab-codex  oci://ghcr.io/openabdev/charts/openab -n cac \
  -f values-openab-codex.yaml -f values-secret-codex.yaml
```

### Kimi bot（opencode + OpenRouter）

併進既有 `openab-claude` release（opencode 只需 RuntimeDefault，與 Rick/Morty 同 release）：

```bash
cp values-secret-kimi.example.yaml values-secret-kimi.yaml   # 填 Discord token

helm upgrade openab-claude ../../charts/openab -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml \
  -f values-openab-kimi.yaml   -f values-secret-kimi.yaml
```

之後還要：靜態 PV `pv-cac-kimi`（claimRef `openab-claude-kimi`）、`opencode auth login` 貼 OpenRouter key、寫全域 `~/.config/opencode/opencode.jsonc` 設模型（ACP 只讀全域，不讀 project `opencode.json`）。完整 bootstrap 見 [`../bot-setup-opencode-kimi.md`](../bot-setup-opencode-kimi.md) 附錄 A。

### Wall-E / Eve bot（同 Kimi 一套）

一樣 opencode + OpenRouter，只差 agent key、persona 檔、與全域 `opencode.jsonc` 的 model 字串（Wall-E＝`openrouter/deepseek/deepseek-v4-pro-0813`、Eve＝`openrouter/z-ai/glm-5.2`）。OpenRouter key 與 Kimi **共用同一把**。

**推薦：跑互動 wizard `deploy-walle-eve.sh`**（10 stage，自動步驟自己跑，Discord 開 App / `opencode auth login` / 貼 PAT 這些人做的事會停下來提示）：

```bash
bash deploy-walle-eve.sh
```

手動流程（wizard 背後做的事）：

```bash
cp values-secret-walle.example.yaml values-secret-walle.yaml   # 填 Discord token
cp values-secret-eve.example.yaml   values-secret-eve.yaml

helm upgrade openab-claude ../../charts/openab -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml \
  -f values-openab-kimi.yaml   -f values-secret-kimi.yaml \
  -f values-openab-walle.yaml  -f values-secret-walle.yaml \
  -f values-openab-eve.yaml    -f values-secret-eve.yaml
```

靜態 PV：`pv-cac-walle`（claimRef `openab-claude-walle`）、`pv-cac-eve`（claimRef `openab-claude-eve`）。bootstrap 見 [`../bot-setup-opencode-kimi.md`](../bot-setup-opencode-kimi.md) 附錄 C。
