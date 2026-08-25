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

## Step 4：補 `xz` 解壓能力（Flutter SDK 是 `.tar.xz`，這個 image 裡沒有 `xz`）

**2026-08-25 實測踩過**：這個 image（Debian 13/trixie）沒有 `xz` 執行檔，Flutter SDK 下載回來是 `.tar.xz`，解壓會直接失敗（`tar (child): xz: Cannot exec: No such file or directory`）。`apt`/`apt-get` 裝不了東西——`readOnlyRootFilesystem: true` 是 chart 裡真的寫死的 K8s 安全設定（`charts/openab/values.yaml`），連 `apt-get update` 都會因為要寫 `/var/lib/apt/lists/` 而報 `Read-only file system`。

用 mise 剛裝好的 Python（`lzma` 是標準庫，python-build-standalone 這種預編譯版本已經內建）寫一個最小的 `xz` shim，放進 PATH 上的 `~/.local/bin/`：

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c '
cat > ~/.local/bin/xz << '"'"'PYEOF'"'"'
#!/usr/bin/env python3
import sys, lzma

def main():
    args = sys.argv[1:]
    files = [a for a in args if not a.startswith("-")]
    if files:
        for f in files:
            with open(f, "rb") as fh:
                data = fh.read()
            sys.stdout.buffer.write(lzma.decompress(data))
    else:
        data = sys.stdin.buffer.read()
        sys.stdout.buffer.write(lzma.decompress(data))

if __name__ == "__main__":
    main()
PYEOF
chmod +x ~/.local/bin/xz
which xz
'
```

驗證能正確解壓（不是只放好檔案就當作成功）：

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c '
  printf "hello mise" | python3 -c "import sys,lzma; sys.stdout.buffer.write(lzma.compress(sys.stdin.buffer.read()))" > /tmp/test.xz
  xz -dc /tmp/test.xz
  echo
'
```

預期輸出 `hello mise`。這個 shim 只支援解壓（GNU tar 解壓縮時的呼叫方式），不支援壓縮/其他 `xz` flag——這裡只需要解壓，故意不做更多。

## Step 5：裝 Flutter

Flutter 不是 mise 的 core backend，要透過 asdf 相容 plugin 機制掛。實測 `mise plugin add flutter` 直接能解到正確的 plugin（`mise-plugins/mise-flutter.git`），不用另外查名稱：

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c '
  mise plugin add flutter
  mise use -g flutter@stable
  mise exec -- flutter --version
'
```

## Step 6：驗證 shims 生效、確認會自動吃到 PATH

```bash
kubectl exec deployment/openab-claude-genie -n cac -- sh -c '
  which python
  which flutter
  python --version
  flutter --version
'
```

`which` 的結果應該指向 `/home/node/.local/share/mise/shims/python`、`.../flutter`，不是系統路徑——這代表 shim 生效了，而不是巧合裝到系統既有的版本。

## Step 7：驗證 per-repo 版本切換

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

## Step 8：確認 Genie 會自己執行

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
- PHP、Android CLI 尚未安裝，之後補上時沿用同一套 shims 機制，不用重新設計；但如果它們的安裝套件也是 `.tar.xz`（很可能），Step 4 裝的 `xz` shim 要留著，別在之後清理環境時誤刪。
- `~/.local/bin/xz` 是自己寫的 shim，只支援解壓（GNU tar 呼叫時的用法），不是真正完整的 `xz` 工具——如果之後某個 mise plugin 需要用 `xz` 做壓縮（而不是解壓已下載好的檔案），這個 shim 不夠用，要再擴充。這個限制本質上是這個共用 image 沒有 `xz` 造成的環境缺口，不是 mise/Flutter/Python 本身的問題；如果未來 `ghcr.io/104corp/openab` 這個共用 image 補裝了 `xz`，這個 shim 可以直接拿掉，PATH 上 `~/.local/bin` 排在系統路徑前面所以會自動切換回真正的 `xz`。
