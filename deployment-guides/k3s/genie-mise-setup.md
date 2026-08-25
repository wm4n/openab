# Genie 裝 mise + Flutter + Python（Phase 1）

## 為什麼這樣裝

- Genie 的 pod 是唯讀根檔案系統，只有 `/home/node`（PVC）可寫。mise 預設就裝在 home 目錄下，不需要 root，天生跟這個限制相容。
- mise 有兩種啟用模式：`activate`（shell hook，需要持續存在的 shell session）跟 `shims`（在 `~/.local/share/mise/shims/` 產生假執行檔，每次執行時才讀當前目錄的版本宣告檔）。Genie 每次工具呼叫都是全新、非互動的 process，`activate` 的 hook 不會生效，**只能用 `shims` 模式**。
- 這次先裝 Flutter + Python（Phase 1）。PHP、Android CLI 之後再補（Android SDK 涉及授權接受跟龐大的 build-tools，另外處理）。
- 只裝 mise 本體，實際 runtime 版本一律「隨用隨裝」：Genie 進 repo 前會自己跑 `mise install`（已寫進 `Genie-CLAUDE_v2.md`），mise 讀 repo 自己的 `.mise.toml`/`.tool-versions` 決定裝哪個版本，裝過的版本留在 PVC 上永久快取。沒有宣告版本的 repo 會落回這裡設的全域預設版本。

## Step 1：values.yaml 加 PATH，helm upgrade

`values-openab-claude.yaml` 的 genie 區塊已經改好（`env.PATH` 加了 `/home/node/.local/bin` 跟 `/home/node/.local/share/mise/shims`），commit 也已經推上去了。跑:

```bash
cd ~/william/github/openab/deployment-guides/k3s
git pull
helm upgrade openab-claude oci://ghcr.io/openabdev/charts/openab --version 0.9.0-beta.1 -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml
kubectl rollout status deployment/openab-claude-genie -n cac
```

驗證 PATH 有生效:

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c 'echo $PATH'
```

預期看到 `/home/node/.local/bin` 跟 `/home/node/.local/share/mise/shims` 都在裡面。

## Step 2：安裝 mise 本體

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c '
  curl -fsSL https://mise.run | sh
  ~/.local/bin/mise --version
'
```

## Step 3：裝 Python（mise 內建 core backend，不用額外掛 plugin）

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c '
  mise use -g python@3.12
  mise exec -- python --version
'
```

版本號如果要換，改 `python@3.12` 這裡即可。

## Step 4：裝 Flutter（需要額外掛 plugin，指令可能要微調）

Flutter 不是 mise 的 core backend，要透過 asdf 相容 plugin 機制掛。先試:

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c '
  mise plugin add flutter
  mise use -g flutter@stable
  mise exec -- flutter --version
'
```

如果 `mise plugin add flutter` 找不到 plugin(mise 內建的 plugin 捷徑清單可能沒收錄,或名稱不是這個),先查可用的名稱:

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c 'mise plugin ls-remote | grep -i flutter'
```

找到正確名稱後改成:

```bash
mise plugin add flutter <上面查到的 git url>
```

再重跑 Step 4 剩下的指令。

## Step 5：驗證 shims 生效、確認會自動吃到 PATH

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c '
  which python
  which flutter
  python --version
  flutter --version
'
```

`which` 的結果應該指向 `/home/node/.local/share/mise/shims/python`、`.../flutter`，不是系統路徑——這代表 shim 生效了，而不是巧合裝到系統既有的版本。

## Step 6：驗證 per-repo 版本切換

找一個(或建一個測試用)帶 `.tool-versions` 或 `.mise.toml` 宣告 python/flutter 版本的 repo：

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c '
  cd /home/node/repos/<owner>/<repo>
  cat .tool-versions 2>/dev/null || cat .mise.toml 2>/dev/null
  mise install
  python --version
  flutter --version
'
```

`python --version`/`flutter --version` 應該吻合這個 repo 宣告的版本，不是 Step 3/4 設的全域預設版本。換一個沒有宣告檔的目錄再跑一次，這次應該落回全域預設版本，不出錯。

## Step 7：確認 Genie 會自己執行

部署新版 `Genie-CLAUDE_v2.md`（已經加了「開工前先跑 `mise install`」這條）：

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c '
  git -C /home/node/github-repo/openab pull
  cp /home/node/github-repo/openab/deployment-guides/Genie-CLAUDE_v2.md /home/node/CLAUDE.md'
kubectl exec deployment/openab-claude-genie -n cac -- grep -c "mise install" /home/node/CLAUDE.md
```

預期輸出 `>= 1`。之後讓 Genie 實際處理一個真實 repo，確認它會自己跑 `mise install`，不用人類提醒。

## 已知限制（Phase 1）

- 這階段裝的 Flutter 只能做不需要 Android/iOS 工具鏈的事（`flutter analyze`/`dart analyze`/純 dart 邏輯的 `flutter test`）。要真的 `flutter build apk` 出安裝檔，需要 Android SDK，留給之後的 Android CLI phase。
- PHP、Android CLI 尚未安裝，之後補上時沿用同一套 shims 機制，不用重新設計。
- Flutter 的 mise plugin 確切來源在寫這份文件時未實測，Step 4 附了查詢備援指令。
