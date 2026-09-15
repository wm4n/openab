# 三 Bot 從 k3s 搬回 Mac(OrbStack)Runbook

> 把 **Rick / Morty / Summer** 從 k3s(namespace `cac`)搬回**目標 Mac（OrbStack，Apple Silicon，會連 104corp 公司網路/VPN）**。
> **⚠️ 這份文件的操作記錄與實測（Phase B1 自建 image、config.toml 相容性等）是在另一台機器上做的，不是實際要部署的目標機器**——目標機器基本狀態（已裝 OrbStack、arm64、同一個公司網路）已確認相容，但沒有實際連過、沒做過「0. 前提盤點」那些機器現況檢查，執行前請先自己在目標機器上核對一次（見下方 0-1）。
> **genie 維持留在 k3s**（104corp 專案專用、獨立 pipeline，不隨這次遷移）。
>
> **範圍決策**（2026-09-15 確認）：
>
> | 決策 | 選擇 |
> | --- | --- |
> | 搬幾隻 | 只搬 Rick/Morty/Summer；genie 留在 k3s |
> | 性質 | **永久搬回**，k3s 上這三隻之後退役（genie 不受影響） |
> | 資料延續 | **全新 bootstrap**，不搬 k3s PVC 上的 transcript/GitHub 登入/openspec 設定 |
> | Morty 位置 | 跟 Rick/Summer 一樣走 **Mac mini OrbStack**（不再用 Portainer） |
> | Discord token | **沿用現有**（同一顆 Discord Application/token，只是換執行的 host；bot 身分綁 token 不綁 host） |
> | Image 來源 | **本機自建**（upstream/main 原始碼 + 最新 CLI 版本），三隻都是，不用 104corp 私有 image 也不用官方 `:latest` |
>
> 本文件是 `K3S.md`（去程）的反向操作，很多步驟直接沿用 `BOT_SETUP.md` Part C–N；差異只寫在這裡，重複的細節請跳去對應 Part 查。

---

## 目錄

- [0. 前提盤點](#0-前提盤點)
- [1. 鐵則](#1-鐵則)
- [Phase A — k3s 端取值（唯讀，不影響現有服務）](#phase-a--k3s-端取值唯讀不影響現有服務)
- [Phase B — Mac mini 端 bootstrap（sleep 隔離，不影響 k3s 現有服務）](#phase-b--mac-mini-端-bootstrapsleep-隔離不影響-k3s-現有服務)
- [Phase C — 翻轉（唯一停機點）](#phase-c--翻轉唯一停機點)
- [Phase D — 端對端驗證](#phase-d--端對端驗證)
- [Rollback（cutover 當下出包怎麼退）](#rollbackcutover-當下出包怎麼退)
- [事後待辦（穩定數天後才做）](#事後待辦穩定數天後才做)
- [疑難排解（本次特有的坑）](#疑難排解本次特有的坑)

---

## 0. 前提盤點

### 0-1. 目標機器現況檢查（在目標 Mac 上親自跑，開始 Phase B 前先做）

```bash
hostname
docker context ls                              # 確認 orbstack context 存在，若有 colima 別動它
docker -c orbstack ps -a --filter "name=openab" # 有沒有殘留的 openab-* 容器
docker -c orbstack volume ls | grep openab      # 有沒有殘留的 openab-* volume（若有，先搞清楚是不是還在用，不要直接蓋掉）
```

若這台機器上已經有 `openab-rick`/`openab-morty`/`openab-summer` 之類的容器或 volume（例如之前也手動試過），先跟自己確認那是不是可以蓋掉的舊嘗試，不要假設是空機器。

### 0-2. 下面這些是已經在別台機器上實測驗證過、跟機器身分無關的技術結論（供對照）
- **k3s 端 release 結構**：`openab-claude`（Rick + Morty + **genie**）、`openab-codex`（只有 Summer）。⚠️ **退役時絕不能 `helm uninstall openab-claude`**——那會把 genie 也一起殺掉。只能改 `values-openab-claude.yaml` 移除 rick/morty 的 `agents.*` 區塊、保留 `genie:` 區塊，再 `helm upgrade`。`openab-codex` release 只有 Summer，可以整個 `helm uninstall`。
- **Discord 身分不變**：三隻的 Discord bot user ID 是 Rick=`1519868630064562278`、Morty=`1521431781641818202`、Summer=`1522253638465093752`。這次搬家**不換 Discord Application**，`allowedChannels`/`allowedRoleIds`/`trustedBotIds` 沿用 k3s 現行值即可，不用重新申請角色或改頻道設定。
- **2026-09-15 獨狼化 redesign 後續更新**：三隻從接力 pipeline 改為各自獨立完成整個流程，`HANDOFF_*` 環境變數（原本用來讓 bot 之間自動 handoff）已整組拿掉、不用替代變數——人類要找另一隻 bot 給第二意見，直接在 Discord 自己 `@` 那隻 bot 即可，不需要 bot 幫忙組 mention 字串。下面 B3 的 config.toml 內容已反映這個異動；`trustedBotIds` 維持不動（見 `openab-three-bot-pipeline` 記憶）。
- **k3s 上的實際 image 跟 `BOT_SETUP.md` 原文不一樣**：Rick/Morty 現在用的是 **104corp 私有映像** `ghcr.io/104corp/openab:0.9.0-claude-cli2.1.220`（不是公版 `openab-claude:latest`）；Summer 用的是公版 `ghcr.io/openabdev/openab-codex:0.9.0-beta.1`。**這次搬回 Mac mini 決定不沿用任何一個，改成三隻都本機自建**（原因與過程見下）。
- **為什麼改成自建，過程完整記錄**：
  1. 起因是 Rick/Morty 當初要換 104corp 私有 image，是因為官方 `openab-claude:latest` 的 Claude Code CLI 太舊沒有 `claude-opus-5`——**這點已實測確認**：拉了官方 `:latest`（CLI 2.1.177），從編譯後二進位檔案抓出的 model id 清單最新只到 `claude-opus-4-8`，沒有 opus-5；104corp 私有版（CLI 2.1.220）才有。
  2. 104corp 私有 image 只有 **amd64 build，沒有 arm64**，Apple Silicon 機器要嘛全程 `--platform linux/amd64` 靠 Rosetta 模擬。
  3. 查證後發現 `Dockerfile.claude`/`Dockerfile.codex` 都是**完整從原始碼編譯**（Rust build stage），而這個 fork 對 `crates/`/`src/`/`Dockerfile` 完全沒有自己的改動（只加了 `charts/openab` 設定），upstream/main 領先 117 個 commit（新增 `openab-mcp`/`openab-cp` 兩個 crate），理論上可以直接拿 upstream 原始碼在本機原生編譯出 arm64 image，還能拿到比 0.9.0 新的一堆修正。
  4. **第一次嘗試建置失敗**：`docker build`（BuildKit）連 crates.io 報 SSL 憑證錯誤（`self-signed certificate in certificate chain`）——104corp 公司網路對外部連線做 TLS 攔截，`docker run` 測試連線正常，但 BuildKit 是獨立網路環境沒有拿到同一份信任鏈（診斷坑，見 CLAUDE.md 教訓 E010）。把公司根憑證加進 build 階段後 SSL 問題解掉，但 crates.io 又回 `403`。
  5. **後來查出真正原因是 VPN**：關掉 VPN 後，host 端與 container 內對 crates.io 的連線都恢復正常（issuer 變回正牌 `GlobalSign`，不再是 104 公司憑證），完整 `cargo build` 實測成功。**結論：開 VPN 時，公司網路會對外部連線做 TLS 攔截且擋掉直接對外的 cargo registry 存取；關掉 VPN 才能本機建置。** 目標機器一樣會連 104corp 網路，建置前一樣要先確認 VPN 是關的。
  6. **自建 image 已完整驗證**：原生 arm64、`openab 0.10.0`、`config.toml`（0.9.0 時代 chart 產生的內容）在 0.10.0 binary 上完全相容（實測 log 印出的 discord/cron/pool 設定與寫的完全一致，一路跑到嘗試連 Discord gateway 才因為假 token 失敗——代表設定解析完全沒問題）。CLI 版本可以自由選（`--build-arg`），**最終選用 npm 上當時最新的版本**（見下方 B0）。
- **自建的維護責任**：這些 image 只存在建置它的那台機器（`docker images` 裡看得到，沒有推到任何 registry）。之後要更新版本（跟進 upstream 修正、跟進更新的 CLI/codex 版本）都要重新在目標機器 `docker build`；Rust 編譯層有 Docker layer cache，只要 `crates/`/`src/` 沒變、只是換 CLI 版本，重建大約 30 秒～1 分鐘；`crates/`/`src/` 真的改了才需要重新跑完整的 Rust 編譯（約 10 分鐘）。
- **Rick 現在比舊版 `BOT_SETUP.md` 多一件事**：裝了 `solo-bot-skills` plugin（配合 `jira-grill`，跟 `openab-bot-skills` 同時裝，Rick 是刻意的例外，不算「接力型/獨立型混裝」的坑）。
- **JIRA/Figma 憑證範圍已刻意放寬（2026-09-15 決定，跟 k3s 現況不同）**：k3s 上是按角色分權限——Morty 只有 JIRA（`requirement-analysis` 用）、Rick 多了 Figma（`jira-grill`/`figma-fetch` 用）、**Summer 完全沒有**（角色只做 code review，沒有對應 skill）。這次搬回 Mac mini 時**改成三隻都給完整 JIRA + Figma 四項 `inherit_env`**，Morty/Summer 目前用不到 Figma、Summer 目前用不到 JIRA，是刻意預留給未來擴充，不是現在就有功能會用——下面 B2/B3 已經照這個新決定寫好。
- **本文件的 config.toml 不是憑印象寫的**：已用本機 `charts/openab`（跟 k3s 上真正在跑的同一份 chart 原始碼）+ `deployment-guides/k3s/values-openab-claude.yaml`/`values-openab-codex.yaml` 跑 `helm template`（本機 render，沒有連任何 cluster、沒有動到任何秘密），把 Rick/Morty/Summer 現在真正生效的 `config.toml` 完整印出來，下面 Phase B 直接照抄。

---

## 1. 鐵則

- **GitHub token 絕不進 config.toml / 不進裸 env**——只在 bootstrap 用 `echo "$GH_TOKEN_x" | docker exec -i ... gh auth login --with-token` 餵入（沿用 `BOT_SETUP.md` Part F）。
- **Discord token 只在 `~/.openab-secret-*.env`**（chmod 600），不進 git、不進 shell history、不貼進 Discord。
- **`marketplace add` 一律用完整 `https://github.com/owner/repo` URL**，不要用 `owner/repo` 簡寫——這批映像沒裝 ssh client，簡寫會被解析成 SSH URL 直接失敗（`K3S.md` 疑難排解表已踩過這個坑，這次一開始就避開）。
- **`/home/node` 下所有檔案必須是 `node:node` 擁有**：進容器一律帶 `-u node`；寫檔用 `docker exec -i -u node ... sh -c 'cat > 檔案'`（heredoc），不要用 `docker cp`（會變 root 擁有，agent 讀不到、Discord 端只看到 `Connection Lost`）。
- **同一顆 bot 的 token 不能兩處同時連線**——Phase B 全程用 `sleep` 隔離（容器起來但不跑 `openab run`），直到 Phase C 才真正切斷 k3s 那邊、換 Mac mini 連上。
- **Rick/Morty/genie 共用 k3s release**——退役 rick/morty 時操作 `values-openab-claude.yaml`/`helm upgrade`，不要 `helm uninstall`。

---

## Phase A — k3s 端取值（唯讀，不影響現有服務）

> ⚠️ 這些 `kubectl get secret` 都是唯讀操作，跑了不影響 k3s 上現在服務中的 rick/morty/summer/genie。**若目標機器沒有配置 kubectl context**——要在有該 cluster kubeconfig 的機器/session 上執行，把結果抄到 Phase B。

**A1. 三隻的 Discord bot token**（k8s Secret，key 固定叫 `discord-bot-token`）：

```bash
kubectl get secret openab-claude-rick   -n cac -o jsonpath='{.data.discord-bot-token}' | base64 -d; echo
kubectl get secret openab-claude-morty  -n cac -o jsonpath='{.data.discord-bot-token}' | base64 -d; echo
kubectl get secret openab-codex-summer  -n cac -o jsonpath='{.data.discord-bot-token}' | base64 -d; echo
```

> **退路**：找不到有 kubeconfig 的機器時，改到 Discord Developer Portal → 該 Bot 分頁 → **Reset Token**。但 Reset 會讓 k3s 那邊立刻斷線——等於直接觸發停機點，**不要在 Phase B 提前做**，壓到 Phase C 才 reset。

**A2. Morty/Rick 共用的 JIRA 憑證** + **Rick 的 Figma token**：

```bash
kubectl get secret morty-jira -n cac -o jsonpath='{.data.JIRA_TOKEN}'    | base64 -d; echo
kubectl get secret morty-jira -n cac -o jsonpath='{.data.JIRA_BASE_URL}' | base64 -d; echo
kubectl get secret morty-jira -n cac -o jsonpath='{.data.JIRA_EMAIL}'    | base64 -d; echo
kubectl get secret figma-token -n cac -o jsonpath='{.data.FIGMA_TOKEN}' | base64 -d; echo
```

**A3. 兩把 GitHub fine-grained PAT**（`GH_TOKEN_WM4N`/`GH_TOKEN_CAC`）：這兩把不是 k8s Secret（GitHub token 鐵則是不進 cluster，只在 bootstrap 當下用），若手上沒留副本要重新建，做法見 `BOT_SETUP.md` [Part B2](BOT_SETUP.md#b2-建-fine-grained-pat優先釘死-repo)。

---

## Phase B — Mac mini 端 bootstrap（sleep 隔離，不影響 k3s 現有服務）

> 這整個 Phase 都可以在 k3s 仍正常服務時先做完；容器啟動後先用 `sleep` 卡住、不連 Discord，跟 k3s 那邊不會搶 token。

### B1. 自建 image（原生 arm64，三隻都用這個）

> ⚠️ **前提：VPN 要關**。開 VPN 時 104corp 公司網路會攔截 TLS 連線並擋掉 crates.io，`cargo build` 會失敗（見上方「前提盤點」的完整診斷過程；目標機器一樣連這個公司網路）。開始前先確認 VPN 是關的，之後每次要重建/升級版本也一樣。

**B1-1. 準備乾淨的原始碼 build context**（直接從 upstream/main 抽，不動你目前的 branch/working tree）：

```bash
rm -rf /tmp/openab-build-ctx && mkdir -p /tmp/openab-build-ctx
cd /Users/william.chao/workspace/ai/openab
git fetch upstream main
git archive upstream/main | tar -x -C /tmp/openab-build-ctx
```

**B1-2. 查目前 npm 上最新的 CLI 版本**（要跟進更新版本時，之後也是跑這兩行）：

```bash
docker -c orbstack run --rm node:22-trixie-slim sh -c 'npm view @anthropic-ai/claude-code version'   # Rick/Morty 用
docker -c orbstack run --rm node:22-trixie-slim sh -c 'npm view @openai/codex version'                # Summer 用
docker -c orbstack run --rm node:22-trixie-slim sh -c 'npm view @agentclientprotocol/codex-acp version'
```

**B1-3. 建置**（2026-09-15 執行時查到的最新版本是 claude-code `2.1.272`、codex `0.154.0`、codex-acp `1.11.0`——之後執行請用 B1-2 查到的當下最新版本，不要照抄這幾個數字）：

```bash
cd /tmp/openab-build-ctx

# Rick/Morty 共用
docker -c orbstack build -f Dockerfile.claude \
  --build-arg CLAUDE_CODE_VERSION=2.1.272 \
  -t openab-claude-local:0.10.0-2.1.272 .

# Summer
docker -c orbstack build -f Dockerfile.codex \
  --build-arg CODEX_VERSION=0.154.0 \
  --build-arg CODEX_ACP_VERSION=1.11.0 \
  -t openab-codex-local:0.10.0-0.154.0 .
```

> 第一次建置 Rust 編譯階段約 10 分鐘（`cargo build --release`，兩個 Dockerfile 共用同一份 `crates/`/`src/`，第二個 build 會命中第一個的 layer cache，通常幾十秒就結束）。之後只換 CLI 版本重建，兩個 Dockerfile 都只需要幾十秒到 1 分鐘（Rust 層全部命中快取）。

**B1-4. 驗證**（架構、版本、opus-5、基本健康度都要過）：

```bash
docker -c orbstack inspect openab-claude-local:0.10.0-2.1.272 --format '{{.Architecture}}'   # 應為 arm64
docker -c orbstack run --rm --entrypoint openab openab-claude-local:0.10.0-2.1.272 --version  # openab 0.10.0
docker -c orbstack run --rm --entrypoint claude openab-claude-local:0.10.0-2.1.272 --version   # 2.1.272 (Claude Code)
docker -c orbstack run --rm --entrypoint sh openab-claude-local:0.10.0-2.1.272 -c '
  BIN=$(find / -xdev -path "*claude-code-linux*/claude" 2>/dev/null | head -1)
  grep -a -o "claude-opus-5[a-z0-9.-]*" "$BIN" 2>/dev/null | sort -u'   # 應印出 claude-opus-5

docker -c orbstack inspect openab-codex-local:0.10.0-0.154.0 --format '{{.Architecture}}'    # 應為 arm64
docker -c orbstack run --rm --entrypoint openab openab-codex-local:0.10.0-0.154.0 --version   # openab 0.10.0
docker -c orbstack run --rm --entrypoint codex openab-codex-local:0.10.0-0.154.0 --version    # 0.154.0
```

> **這些 image 只存在建置它的那台機器**，沒有推到任何 registry。之後想在別的機器用同一份、或這台機器重灌，要重跑這一整節（build context 從 upstream/main 抽，不依賴任何外部儲存）。已實測：0.9.0 時代 chart 產生的 `config.toml`（見下方 B3）在這個 0.10.0 binary 上完全相容，不用改格式。

### B2. 建三隻的 config 目錄與秘密檔

```bash
mkdir -p ~/oab-rick ~/oab-morty ~/oab-summer
for f in rick morty summer; do
  : > ~/.openab-secret-$f.env
  chmod 600 ~/.openab-secret-$f.env
done
```

> ⚠️ **2026-09-15 決定放寬**：k3s 現行設計是按角色分權限（Morty 只給 JIRA、Summer 兩者都不給，見「疑難排解」上方討論），但這次搬回 Mac mini 時**已確認要讓三隻都拿到完整 JIRA + Figma 憑證**（Summer 目前沒有任何 skill 會用到，是刻意預留給未來擴充，不是現在就有對應功能）。下面三個秘密檔與 B3 的 config.toml 都已經按這個決定寫好。

編輯三個秘密檔（`DISCORD_BOT_TOKEN` 用 Phase A1 抄回來的值；GH 兩把 PAT、JIRA、Figma 三隻都要）：

```dotenv
# ~/.openab-secret-rick.env
DISCORD_BOT_TOKEN=<Phase A1 的 Rick token>
GH_TOKEN_WM4N=<你的 wm4n fine-grained PAT>
GH_TOKEN_CAC=<你的 cac-william fine-grained PAT>
JIRA_TOKEN=<Phase A2>
JIRA_BASE_URL=<Phase A2>
JIRA_EMAIL=<Phase A2>
FIGMA_TOKEN=<Phase A2>
```

```dotenv
# ~/.openab-secret-morty.env
DISCORD_BOT_TOKEN=<Phase A1 的 Morty token>
GH_TOKEN_WM4N=<同上>
GH_TOKEN_CAC=<同上>
JIRA_TOKEN=<Phase A2>
JIRA_BASE_URL=<Phase A2>
JIRA_EMAIL=<Phase A2>
FIGMA_TOKEN=<Phase A2>
```

```dotenv
# ~/.openab-secret-summer.env
DISCORD_BOT_TOKEN=<Phase A1 的 Summer token>
GH_TOKEN_WM4N=<同上>
GH_TOKEN_CAC=<同上>
JIRA_TOKEN=<Phase A2>
JIRA_BASE_URL=<Phase A2>
JIRA_EMAIL=<Phase A2>
FIGMA_TOKEN=<Phase A2>
```

### B3. config.toml（直接照抄——已用本機 chart 對 k3s 現行 values 跑 `helm template` 印出來的真實內容）

```bash
cat > ~/oab-rick/config.toml <<'EOF'
[discord]
bot_token = "${DISCORD_BOT_TOKEN}"
allow_all_channels = false
allow_all_users = false
allowed_channels = ["1528965074562191420","1528965173761802420","1522271475552354394","1526283579309690990"]
allowed_users = ["824092654060830770"]
allow_bot_messages = "mentions"
trusted_bot_ids = ["1521431781641818202","1522253638465093752","1541617131442147438"]
allowed_role_ids = ["1528997914049777764"]

[agent]
command = "claude-agent-acp"
args = []
working_dir = "/home/node"
env = { PATH = "/home/node/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" }
inherit_env = ["JIRA_TOKEN","JIRA_BASE_URL","JIRA_EMAIL","FIGMA_TOKEN"]

[pool]
max_sessions = 5
session_ttl_hours = 24
prompt_hard_timeout_secs = 14400

[reactions]
enabled = true
remove_after_reply = false
tool_display = "compact"

[cron]
usercron_enabled = true
usercron_path = "cronjob.toml"
EOF
```

```bash
cat > ~/oab-morty/config.toml <<'EOF'
[discord]
bot_token = "${DISCORD_BOT_TOKEN}"
allow_all_channels = false
allow_all_users = false
allowed_channels = ["1528965074562191420","1528965173761802420","1522271475552354394","1526283579309690990"]
allowed_users = ["824092654060830770"]
allow_bot_messages = "mentions"
trusted_bot_ids = ["1519868630064562278","1522253638465093752"]
allowed_role_ids = ["1528997714879320134","1528997980714303640"]

[agent]
command = "claude-agent-acp"
args = []
working_dir = "/home/node"
inherit_env = ["JIRA_TOKEN","JIRA_BASE_URL","JIRA_EMAIL","FIGMA_TOKEN"]

[pool]
max_sessions = 5
session_ttl_hours = 24
prompt_hard_timeout_secs = 14400

[reactions]
enabled = true
remove_after_reply = false
tool_display = "compact"

[cron]
usercron_enabled = true
usercron_path = "cronjob.toml"
EOF
```

```bash
cat > ~/oab-summer/config.toml <<'EOF'
[discord]
bot_token = "${DISCORD_BOT_TOKEN}"
allow_all_channels = false
allow_all_users = true
allowed_channels = ["1528965074562191420","1528965173761802420","1522271475552354394","1526283579309690990"]
allowed_users = []
allow_bot_messages = "mentions"
trusted_bot_ids = ["1519868630064562278","1521431781641818202"]
allowed_role_ids = ["1528997980714303640"]

[agent]
command = "codex-acp"
args = ["-c","shell_environment_policy.inherit=all"]
working_dir = "/home/node"
inherit_env = ["JIRA_TOKEN","JIRA_BASE_URL","JIRA_EMAIL","FIGMA_TOKEN"]

[pool]
max_sessions = 5
session_ttl_hours = 24

[reactions]
enabled = true
remove_after_reply = false
tool_display = "compact"

[cron]
usercron_enabled = true
usercron_path = "cronjob.toml"
EOF
```

> Summer 沒有 `prompt_hard_timeout_secs`（維持預設 1800s）——這跟 k3s 現況一致，不是漏寫；要不要跟 Rick/Morty 一樣拉到 4hr 是這次可以順手決定的事，不影響搬家本身。

### B4. 啟動容器（sleep 隔離，先不連 Discord）

```bash
docker -c orbstack run -d --name openab-rick --restart unless-stopped \
  --entrypoint sleep \
  --env-file ~/.openab-secret-rick.env \
  -v openab-rick-home:/home/node \
  -v ~/oab-rick:/etc/openab:ro \
  openab-claude-local:0.10.0-2.1.272 infinity

docker -c orbstack run -d --name openab-morty --restart unless-stopped \
  --entrypoint sleep \
  --env-file ~/.openab-secret-morty.env \
  -v openab-morty-home:/home/node \
  -v ~/oab-morty:/etc/openab:ro \
  openab-claude-local:0.10.0-2.1.272 infinity

docker -c orbstack run -d --name openab-summer --restart unless-stopped \
  --security-opt seccomp=unconfined \
  --entrypoint sleep \
  --env-file ~/.openab-secret-summer.env \
  -v openab-summer-home:/home/node \
  -v ~/oab-summer:/etc/openab:ro \
  openab-codex-local:0.10.0-0.154.0 infinity

docker -c orbstack ps   # 三隻都 Up，PID1 是 sleep，不會連 Discord
```

> Summer 的 `--security-opt seccomp=unconfined` 對應 k3s 的 `seccompProfile.type: Unconfined`，讓 codex-acp 內部 bwrap 能建 namespace；起來後可先驗證：`docker -c orbstack exec openab-summer unshare --user echo ok` 應回 `ok`。

### B5. Claude / Codex 互動登入（憑證存進各自 volume）

```bash
docker -c orbstack exec -it openab-rick   claude auth login
docker -c orbstack exec -it openab-morty  claude auth login
docker -c orbstack exec -it openab-summer codex login --device-auth
```

### B6. gh 雙帳號登入（三隻各做一次）

```bash
for c in openab-rick openab-morty openab-summer; do
  docker -c orbstack exec -i -u node $c sh -c '
    echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token &&
    echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token &&
    gh auth setup-git'
  docker -c orbstack exec -u node $c gh auth status   # 應看到 wm4n + cac-william
done
```

### B7. clone repo + 部署 persona（v2 context 檔）

```bash
docker -c orbstack exec -i -u node openab-rick sh -c '
  git clone https://github.com/wm4n/openab.git /home/node/github-repo/openab 2>/dev/null || git -C /home/node/github-repo/openab pull
  git -C /home/node/github-repo/openab checkout docs/three-bot-pipeline && git -C /home/node/github-repo/openab pull
  cat /home/node/github-repo/openab/deployment-guides/Rick-CLAUDE_v2.md > /home/node/CLAUDE.md
  head -1 /home/node/CLAUDE.md'

docker -c orbstack exec -i -u node openab-morty sh -c '
  git clone https://github.com/wm4n/openab.git /home/node/github-repo/openab 2>/dev/null || git -C /home/node/github-repo/openab pull
  git -C /home/node/github-repo/openab checkout docs/three-bot-pipeline && git -C /home/node/github-repo/openab pull
  cat /home/node/github-repo/openab/deployment-guides/Morty-CLAUDE_v2.md > /home/node/CLAUDE.md
  head -1 /home/node/CLAUDE.md'

docker -c orbstack exec -i -u node openab-summer sh -c '
  git clone https://github.com/wm4n/openab.git /home/node/github-repo/openab 2>/dev/null || git -C /home/node/github-repo/openab pull
  git -C /home/node/github-repo/openab checkout docs/three-bot-pipeline && git -C /home/node/github-repo/openab pull
  cat /home/node/github-repo/openab/deployment-guides/Summer-AGENTS_v2.md > /home/node/AGENTS.md
  head -1 /home/node/AGENTS.md'
```

### B8. 裝 skill plugin（純 CLI，不用手動 symlink；`marketplace add` 一律用完整 URL）

> **2026-09-15 獨狼化 redesign 後**：三隻都要裝 `solo-bot-skills`（`solo-feature-pipeline` 現在是三隻共用的獨立開發流程，不再是 Rick 專屬例外）。`solo-bot-skills` 新增了 `.codex-plugin` manifest，Summer 也裝得到。

**Rick**：

```bash
docker -c orbstack exec -u node openab-rick claude plugin marketplace add https://github.com/anthropics/claude-plugins-official
docker -c orbstack exec -u node openab-rick claude plugin install superpowers@claude-plugins-official

docker -c orbstack exec -u node openab-rick claude plugin marketplace add https://github.com/wm4n/skill-registry
docker -c orbstack exec -u node openab-rick claude plugin install openab-bot-skills@wm4n-skill-registry
docker -c orbstack exec -u node openab-rick claude plugin install skill-registry@wm4n-skill-registry
docker -c orbstack exec -u node openab-rick claude plugin install solo-bot-skills@wm4n-skill-registry
```

**Morty**：

```bash
docker -c orbstack exec -u node openab-morty claude plugin marketplace add https://github.com/anthropics/claude-plugins-official
docker -c orbstack exec -u node openab-morty claude plugin install superpowers@claude-plugins-official

docker -c orbstack exec -u node openab-morty claude plugin marketplace add https://github.com/wm4n/skill-registry
docker -c orbstack exec -u node openab-morty claude plugin install openab-bot-skills@wm4n-skill-registry
docker -c orbstack exec -u node openab-morty claude plugin install skill-registry@wm4n-skill-registry
docker -c orbstack exec -u node openab-morty claude plugin install solo-bot-skills@wm4n-skill-registry
```

**Summer**（Codex 家族，marketplace 來源不同）：

```bash
docker -c orbstack exec -u node openab-summer codex plugin marketplace add https://github.com/obra/superpowers-marketplace
docker -c orbstack exec -u node openab-summer codex plugin add superpowers@superpowers-marketplace

docker -c orbstack exec -u node openab-summer codex plugin marketplace add https://github.com/wm4n/skill-registry
docker -c orbstack exec -u node openab-summer codex plugin add openab-bot-skills@wm4n-skill-registry
docker -c orbstack exec -u node openab-summer codex plugin add skill-registry@wm4n-skill-registry
docker -c orbstack exec -u node openab-summer codex plugin add solo-bot-skills@wm4n-skill-registry
```

**裝完務必確認乾淨**：

```bash
docker -c orbstack exec -u node openab-rick   claude plugin list   # 應看到 openab-bot-skills + skill-registry + solo-bot-skills + superpowers
docker -c orbstack exec -u node openab-morty  claude plugin list   # 應看到 openab-bot-skills + skill-registry + solo-bot-skills + superpowers
docker -c orbstack exec -u node openab-summer codex plugin list    # 應看到 openab-bot-skills + skill-registry + solo-bot-skills + superpowers
```

### B9. Rick 專屬 — openspec

自建的 `Dockerfile.claude` 沒有預裝 openspec（原本 104corp 私有 image 才有；這點已從 Dockerfile 內容確認，不用先 `which` 探測）。Mac mini 的容器預設可寫根碟，直接裝全域即可，不用像 k3s 那樣繞 PVC：

```bash
docker -c orbstack exec -u root openab-rick npm install -g @fission-ai/openspec@latest
docker -c orbstack exec -u node openab-rick openspec --version
```

openspec profile（一次性，這個容器沒做過）：

```bash
docker -c orbstack exec -it -u node openab-rick openspec config profile
# Workflows only → 勾選 propose, explore, new, continue, apply, ff, archive → 確認
docker -c orbstack exec -u node openab-rick openspec config list   # 確認同時含 propose 與 new/ff
```

### B10. Summer 專屬 — `~/.codex/config.toml`（issue #1047，用 `BOT_SETUP.md` 現行最完整版）

```bash
docker -c orbstack exec -i -u node openab-summer sh -c 'cat > /home/node/.codex/config.toml' <<'EOF'
personality = "pragmatic"
sandbox_mode = "danger-full-access"
approval_policy = "on-request"
approvals_reviewer = "auto_review"

[projects."/home/node"]
trust_level = "trusted"

[features]
multi_agent = true

[tui.model_availability_nux]
"gpt-5.5" = 1

[plugins."superpowers@openai-curated"]
enabled = false
EOF
```

### B11. 本機驗證（不碰 Discord，容器還在 sleep）

```bash
for c in openab-rick openab-morty openab-summer; do
  echo "--- $c ---"
  docker -c orbstack exec -u node $c gh auth status
  docker -c orbstack exec -u node $c head -1 /home/node/CLAUDE.md 2>/dev/null || docker -c orbstack exec -u node $c head -1 /home/node/AGENTS.md
done
```

到這裡為止，**k3s 上的 rick/morty/summer 完全沒被動到**，全程可以慢慢做、做錯也不影響現有服務。

---

## Phase C — 翻轉（唯一停機點）

> 執行順序：**先確保雙邊不會搶同一個 token**。如果 Phase A1 是用 `kubectl get secret` 讀現有 token（沒換新），就先關 k3s 那邊再開 Mac mini；如果 A1 走的是 Discord Reset Token 退路，reset 那一刻本身就已經斷了 k3s，接著直接開 Mac mini 即可。

**C1. 停 k3s 上的 rick/morty**（保留 genie，改 values 後 upgrade，不要 `helm uninstall`）：

```bash
cd deployment-guides/k3s
# 編輯 values-openab-claude.yaml：整段刪除 `rick:` 與 `morty:` 底下的 agents 區塊，
# 只保留 `kiro: enabled: false` 與 `genie:` 區塊
helm upgrade openab-claude ../../charts/openab -n cac -f values-openab-claude.yaml -f values-secret-claude.yaml
kubectl get pods -n cac   # 應只剩 openab-claude-genie，rick/morty 的 pod 消失
```

**C2. 整個退役 `openab-codex`**（只有 Summer，可以直接 uninstall）：

```bash
helm uninstall openab-codex -n cac
kubectl get pods -n cac   # openab-codex-summer 消失
```

**C3. Mac mini 端解除 sleep、正式啟動**：

```bash
for c in openab-rick openab-morty; do
  docker -c orbstack rm -f $c
done
docker -c orbstack run -d --name openab-rick --restart unless-stopped \
  --env-file ~/.openab-secret-rick.env \
  -v openab-rick-home:/home/node \
  -v ~/oab-rick:/etc/openab:ro \
  openab-claude-local:0.10.0-2.1.272

docker -c orbstack run -d --name openab-morty --restart unless-stopped \
  --env-file ~/.openab-secret-morty.env \
  -v openab-morty-home:/home/node \
  -v ~/oab-morty:/etc/openab:ro \
  openab-claude-local:0.10.0-2.1.272

docker -c orbstack rm -f openab-summer
docker -c orbstack run -d --name openab-summer --restart unless-stopped \
  --security-opt seccomp=unconfined \
  --env-file ~/.openab-secret-summer.env \
  -v openab-summer-home:/home/node \
  -v ~/oab-summer:/etc/openab:ro \
  openab-codex-local:0.10.0-0.154.0
```

> ⚠️ `docker rm -f` 重建會換一個新容器，但因為掛的是同一顆持久化 volume（`openab-*-home`），Phase B 裝好的 Claude/Codex 憑證、gh 登入、skill plugin、persona 都還在——**不需要重跑 B5–B10**。之所以要 `rm -f` 重建而不是 `docker update --entrypoint`，是因為 Docker 不支援事後改 `--entrypoint`；改用「先建 sleep 版、翻轉時砍掉重建成正式版」是 `BOT_SETUP.md`/`K3S.md` 一致的 sleep 隔離作法。

**C4. 驗證上線**：

```bash
docker -c orbstack ps                       # 三隻都 Up (healthy)
docker -c orbstack logs openab-rick   | grep -i discord
docker -c orbstack logs openab-morty  | grep -i discord
docker -c orbstack logs openab-summer | grep -i discord
```

---

## Phase D — 端對端驗證

沿用 `bot-skills/ROLLOUT-CHECKLIST.md`：

1. 三隻 healthy，Discord 上三隻上線、帳號名稱正確。
2. **角色觸發**（Part M，沿用現行 CAC-Analyst/CAC-Builder/CAC-Reviewer 三個角色 ID，不用重建角色）：`@CAC-Analyst`→Morty、`@CAC-Builder`→Rick、`@CAC-Reviewer`→Morty+Summer 同 thread。
3. **完整 pipeline 一輪**：對 Morty 提個需求 → 產 spec → 人工閘門 → @Rick → Rick 開 PR → @Morty + @Summer → review clean → 人類 merge。全程只在 handoff 行出現 mention，無 bot 互 @ 迴圈。
4. **Rick 的 jira-grill 能力**（若目前有掛 grill-me 票要驗）：手動 @Rick 觸發一次，確認能讀到 JIRA_TOKEN/FIGMA_TOKEN（`docker -c orbstack exec -u node openab-rick env | grep -E 'JIRA|FIGMA'` 應有值）。
5. **usercron 冒煙測**：對一隻寫 `~/.openab/cronjob.toml` 每分鐘 ping，確認 1 分鐘內收到，然後移除。

全部過 → 遷移完成 ✅

---

## Rollback（cutover 當下出包怎麼退）

Phase C 是唯一停機點，出包時：

1. Mac mini 端 `docker -c orbstack stop openab-rick openab-morty openab-summer`（釋出 token）。
2. k3s 端把 C1 刪掉的 `rick:`/`morty:` 區塊加回 `values-openab-claude.yaml`、`helm upgrade openab-claude`；`openab-codex` 用 C2 之前的 `helm install`（PVC 若還沒被刪，`helm.sh/resource-policy: keep` 會讓資料還在，重新 install 會接回同一顆 PVC）。
3. 幾分鐘內可退回 k3s 現狀。

---

## 事後待辦（穩定數天後才做）

> 這些是**破壞性/收尾動作**，Phase D 驗證穩定運行數天無誤後才做，不要在 cutover 當天一起做。

1. **刪 k3s 上 rick/morty/summer 的 PVC**（`helm.sh/resource-policy: keep` 不會自動刪）：
   ```bash
   kubectl delete pvc openab-claude-rick openab-claude-morty openab-codex-summer -n cac
   ```
2. **刪對應的靜態 PV**（先 `kubectl get pv` 依 `claimRef` 對到上面三個 PVC 名稱再刪，PV 名稱未實測確認，不要用猜的名字直接刪）。
3. **清理 Mac mini 上的舊 `openab-local-home` volume**（7月中殘留，跟這次新建的 `openab-rick-home`/`openab-morty-home`/`openab-summer-home` 不是同一份，確認沒有其他地方在用之後 `docker -c orbstack volume rm openab-local-home`）。
4. **更新 `BOT_SETUP.md`**：Part K2 的 Morty 段落改成 Mac mini/OrbStack 寫法（不再是 Portainer）、Part I 保留給「真的只有 Portainer 網頁」的情境當通用參考、Part O 補一段「後來從 k3s 搬回來」的記錄。
5. **`K3S.md` 加一段收尾說明**：rick/morty 已於 2026-09 retired、genie 繼續留在 k3s，文件本身當歷史保留。
6. **`jira-grill-poller`／`agent-dev-poller` 現況**：兩者都是獨立部署、走 Discord @mention 觸發，不受這次 Rick 換 host 影響；若之後要恢復 `jira-grill-poller`（目前是暫停狀態），跟這次遷移無關，各自處理即可。
7. **清掉建置暫存**：`rm -rf /tmp/openab-build-ctx`（B1 用的 build context，image 已經建好、不再需要這份原始碼副本）。
8. **考慮備份自建的 image**：這些 image 只存在目標機器（沒推到任何 registry），該機器若重灌/OrbStack 資料重置就會消失。備份選項：① 重新走一次 B1（最推薦，`git archive upstream/main` 隨時可重建，10 分鐘內完成）；② `docker save openab-claude-local:0.10.0-2.1.272 openab-codex-local:0.10.0-0.154.0 -o ~/openab-images-backup.tar` 存一份 tarball（每個約 500MB～1.8GB，注意磁碟空間）。

---

## 疑難排解（本次特有的坑）

| 症狀 | 原因 | 解法 |
| --- | --- | --- |
| `docker build`（BuildKit）在公司網路連 crates.io 報 SSL 憑證錯誤（`self-signed certificate in certificate chain`），或加了公司憑證後改回 `403` | **VPN 開著**：104corp 公司網路對外部連線做 TLS 攔截（`docker run` 測試連線正常不代表 BuildKit 也正常，是不同的網路環境，見 CLAUDE.md 教訓 E010）；VPN 開著時就算把公司根憑證加進 build 階段解掉憑證錯誤，crates.io 還是會回 `403` | **關掉 VPN 再 build**（已實測確認是唯一根因，關 VPN 後 host 與 container 對 crates.io 的連線都恢復正常、`cargo build` 完整成功）；如果工作上必須開 VPN 才能連公司內部資源，之後要重建 image 得先切到不需要 VPN 的網路 |
| 自建 image 重建時又花了完整 10 分鐘（預期應該幾十秒） | `crates/`/`src/` 內容跟上次不同（例如又重新 `git archive upstream/main` 抽到不同 commit），Docker layer cache 沒命中 | 正常現象，upstream 若在兩次建置之間有新 commit 就會這樣；只要 `crates/`/`src/` 沒變、只是換 `--build-arg CLAUDE_CODE_VERSION=...`，就會命中快取 |
| `claude`/`codex plugin marketplace add owner/repo` 失敗，log 顯示 `ssh: not found` | 簡寫被解析成 SSH URL，映像沒裝 ssh client | 一律用完整 `https://github.com/owner/repo`（見「鐵則」） |
| Summer 所有 shell 指令 ❌（`unshare failed: Operation not permitted`） | 忘了加 `--security-opt seccomp=unconfined` | 補上該旗標重建容器；驗證 `docker exec openab-summer unshare --user echo ok` 應回 `ok` |
| Rick 的 `npm install -g openspec` 失敗 | 不太可能發生在 Mac mini（根碟預設可寫，跟 k3s 的 `readOnlyRootFilesystem` 不同）；若真的失敗，可能是私有映像本身鎖了某層權限 | 先確認 `which openspec` 是不是本來就有；仍失敗才排查映像本身 |
| gh 登入「restart 就消失」 | 用 root 登入、或 volume 沒持久化、或 env 有裸 `GH_TOKEN` | 一律 `-u node`；確認 `-v openab-*-home:/home/node`；秘密檔只放 `GH_TOKEN_WM4N`/`GH_TOKEN_CAC`，不要有裸 `GH_TOKEN` |
| 兩邊都連上同一顆 Discord bot、互踢 | Phase C 順序顛倒，k3s 沒先停就開了 Mac mini | 嚴格照 Phase C1→C2→C3 順序，或反過來但同一時刻只能一邊連 |

---

**設計依據**：本文件是 `K3S.md`（去程遷移）與 `BOT_SETUP.md` Part C–N（Mac mini 原始 runbook）的反向組合，config.toml 內容由本機 `charts/openab` 對 `deployment-guides/k3s/values-openab-claude.yaml`/`values-openab-codex.yaml` 跑 `helm template` 實際渲染取得（2026-09-15）。
