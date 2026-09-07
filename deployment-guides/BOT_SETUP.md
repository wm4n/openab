# openab Bot 部署 Runbook(Mac mini + Discord + Claude Code)

> 這是**個人/團隊 POC 的部署手冊**,記錄在 Mac mini(`CAC@2771`)上把 openab 接上 Discord、後端接 Claude Code、並安全地給它 GitHub 存取(採 **gh 雙帳號 + `gh auth switch`**,同時服務 wm4n/cac-william 兩身份)的完整步驟。
>
> ⚠️ 本檔**只放 placeholder,絕不寫入真實 token**。所有秘密一律放在 `~/.openab-secrets.env`。
>
> 這份是放在開發機 repo 裡的筆記,可自行搬到 Mac mini 或 gitignore。

---

## 目錄

- [openab Bot 部署 Runbook(Mac mini + Discord + Claude Code)](#openab-bot-部署-runbookmac-mini--discord--claude-code)
  - [目錄](#目錄)
  - [1. 架構速覽](#1-架構速覽)
  - [2. 前置需求](#2-前置需求)
  - [Part A — 建立 Discord Bot](#part-a--建立-discord-bot)
    - [A1. 建立 Application 與 Bot](#a1-建立-application-與-bot)
    - [A2. 開啟必要 Intent](#a2-開啟必要-intent)
    - [A3. 邀請 Bot 進伺服器](#a3-邀請-bot-進伺服器)
    - [A4. 取得 Channel ID / User ID](#a4-取得-channel-id--user-id)
  - [Part B — 建立 GitHub Token(最小權限)](#part-b--建立-github-token最小權限)
    - [B1.(強烈建議)用專用 machine user](#b1強烈建議用專用-machine-user)
    - [B2. 建 Fine-grained PAT(優先,釘死 repo)](#b2-建-fine-grained-pat優先釘死-repo)
    - [B3. 放進秘密檔(下一節 Part C 會建立)](#b3-放進秘密檔下一節-part-c-會建立)
  - [Part C — Mac mini 主機準備](#part-c--mac-mini-主機準備)
    - [C1. 建立 config 目錄與秘密檔](#c1-建立-config-目錄與秘密檔)
    - [C2. 建立 config.toml](#c2-建立-configtoml)
  - [Part D — 啟動容器](#part-d--啟動容器)
  - [Part E — Claude Code 登入](#part-e--claude-code-登入)
  - [Part F — 容器內 git/gh 設定(雙帳號)](#part-f--容器內-gitgh-設定雙帳號)
  - [Part F2 — 多帳號身份切換](#part-f2--多帳號身份切換)
  - [Part F3 — 雙身份 rollout 清單](#part-f3--雙身份-rollout-清單)
  - [Part G — 放入 workspace 脈絡 CLAUDE.md](#part-g--放入-workspace-脈絡-claudemd)
  - [Part H — 端對端驗證](#part-h--端對端驗證)
  - [Part I — Portainer(另一台,UI-only)部署](#part-i--portainer另一台ui-only部署)
  - [Part J — Codex 變體(與 Claude 並存)](#part-j--codex-變體與-claude-並存)
  - [Part K — 三 Bot 接力 Pipeline(Morty/Rick/Summer)](#part-k--三-bot-接力-pipelinemortricksummer)
  - [Part L — 定時排程（Cron / Usercron）](#part-l--定時排程cron--usercron)
  - [Part M — 角色觸發（個人別名 / 團隊 mention）](#part-m--角色觸發個人別名--團隊-mention)
  - [Part N — 更新既有部署的 context 檔與 skill](#part-n--更新既有部署的-context-檔與-skill)
  - [Part O — 遷移到 k3s](#part-o--遷移到-k3s)
  - [維運](#維運)
  - [安全須知(務必讀)](#安全須知務必讀)
  - [疑難排解](#疑難排解)
  - [附錄:完整範例檔](#附錄完整範例檔)
    - [`~/.openab-secrets.env`(chmod 600,放在 `~/oab` 之外)](#openab-secretsenvchmod-600放在-oab-之外)
    - [`~/oab/config.toml`](#oabconfigtoml)
    - [啟動指令](#啟動指令)
  - [附錄:完整範例檔](#附錄完整範例檔-1)
    - [`~/.openab-secrets.env`(chmod 600,放在 `~/oab` 之外)](#openab-secretsenvchmod-600放在-oab-之外-1)
    - [`~/oab/config.toml`](#oabconfigtoml-1)
    - [啟動指令](#啟動指令-1)

---

## 1. 架構速覽

```
Discord 訊息 ──> openab(容器內 PID1) ──spawn──> claude-agent-acp ──> claude(Claude Code)
                     │                                                    │
                 讀 /etc/openab/config.toml                         在 /home/node 工作
                 從 env 拿 DISCORD_BOT_TOKEN                          讀 ~/.claude(已登入)
                                                                     讀 ~/.config/gh(GitHub)
```

**三 Bot Pipeline 實際部署位置：**

| Bot    | 身份                 | 主機              | 容器管理   | 映像                       |
| ------ | -------------------- | ----------------- | ---------- | -------------------------- |
| Morty  | Claude(規格+PR複審)  | 另一台機器        | Portainer  | openab-claude:latest       |
| Rick   | Claude(openspec 開發)| Mac mini(CAC@2771)| OrbStack   | openab-claude:latest       |
| Summer | Codex(Code Review)   | Mac mini(CAC@2771)| OrbStack   | openab-codex:latest        |

> Mac mini 上同時有 **colima**（團隊服務）和 **OrbStack**（openab）。Rick/Summer 操作一律加 `-c orbstack`，**別動 colima**。Morty 在 Portainer 上，用網頁 Console 操作（無 vi/nano，改設定用 `sed` 或 heredoc）。

關鍵觀念:

- **openab spawn agent 前會 `env_clear()`**(防止 `DISCORD_BOT_TOKEN` 之類被 prompt injection 偷走)。容器環境變數**預設不會傳給 agent**;要傳才在 `[agent].inherit_env` 放行。
- **GitHub 憑證不走 env**:改把 `wm4n`、`cac-william` 兩個帳號登入進 gh(存 `~/.config/gh/hosts.yml`),每個任務用 `gh auth switch` 選帳號(見 [Part F2](#part-f2--多帳號身份切換))。好處:agent 的 `printenv` 看不到 token。`inherit_env` 只留給非 GitHub 的 secret(如 Morty 的 `JIRA_*`)。
- agent 的 `command` 必須是 **`claude-agent-acp`**(不是裸 `claude`,裸 `claude` 不講 ACP)。
- 這台 Mac mini 同時跑 **colima**(團隊服務 wekan/mongo/jenkins)和 **OrbStack**(openab)。**openab 所有 docker 指令都要帶 `-c orbstack`**,別動到 colima。

---

## 2. 前置需求

- Mac mini M3(arm64)、已安裝 **OrbStack**,且 `orb start` 只勾 **docker**(不要 kubernetes/linux,省 RAM)。
- OrbStack 設定開「**Start at login**」,開機後 openab 會自動回來。
- 一個 Discord 伺服器(你有管理權限)。
- 一個 GitHub 帳號 —— **建議用專用 machine user**,而不是你本人帳號(見 Part B 說明)。

> OrbStack 啟動會搶走預設 docker context。啟動後執行 `docker context use colima` 切回給團隊服務用,openab 指令一律顯式 `-c orbstack`。

---

## Part A — 建立 Discord Bot

### A1. 建立 Application 與 Bot

1. 進 <https://discord.com/developers/applications> → **New Application** → 命名(例:`Rick & Morty Dev Team`)。
2. 左側 **Bot** 分頁 → **Reset Token** → 複製 token(這就是 `DISCORD_BOT_TOKEN`,**等下放進秘密檔,不要貼到任何聊天/文件**)。

> 名詞釐清:**Application 名稱**(General Information)≠ **Bot 顯示名**(Bot 分頁 Username)≠ **伺服器暱稱**。聊天室裡顯示的是 Bot Username 或伺服器暱稱,改名要改 Bot 分頁的 Username。

### A2. 開啟必要 Intent

- Bot 分頁 → **Privileged Gateway Intents** → 開啟 **MESSAGE CONTENT INTENT**(openab 要讀訊息內容,必開)。

### A3. 邀請 Bot 進伺服器

1. **OAuth2 → URL Generator** → Scopes 勾 `bot`。
2. Bot Permissions 至少勾:`View Channels`、`Send Messages`、`Read Message History`、`Create Public Threads`、`Send Messages in Threads`。
3. 複製產生的 URL → 瀏覽器開啟 → 選你的伺服器 → 授權。

### A4. 取得 Channel ID / User ID

1. Discord App → 設定 → **進階 → 開發者模式** 開啟。
2. 右鍵你要讓 bot 服務的**頻道** → **複製頻道 ID** → 這是 `allowed_channels`。
3. 右鍵**你自己** → **複製使用者 ID** → 這是 `allowed_users`(限制只有你能用,建議設)。

---

## Part B — 建立 GitHub Token(最小權限)

> **安全前提:就算 token 不進 agent env(改走 gh 儲存的雙帳號),agent 仍讀得到憑證(有 Bash,`cat ~/.config/gh/hosts.yml` 就拿到)。所以安全不靠「藏」,靠「範圍小 + 可秒收回」。** 詳見 [安全須知](#安全須知務必讀)。

### B1. 兩個帳號、兩把 token

本 runbook 讓 bot 同時服務兩個 GitHub 身份,各建一把 fine-grained PAT:

- **公司**:`cac-william`(建議當專用 machine user,只加為目標 repo collaborator;要收回只要踢 collaborator)。→ `GH_TOKEN_CAC`
- **個人**:`wm4n`。→ `GH_TOKEN_WM4N`

兩把都照 B2 建 fine-grained、**各自只釘死要給 bot 碰的 repo**。個人帳號尤其別給帳號級全開(見[安全須知](#安全須知務必讀))。

### B2. 建 Fine-grained PAT(優先,釘死 repo)

GitHub → Settings → **Developer settings** → **Fine-grained tokens** → Generate new token:

- **Name**:`openab-macmini-bot`
- **Expiration**:90 天(別選 No expiration)
- **Resource owner**:該帳號;若 repo 在 org,選 org(org 需先允許/核准 fine-grained token)
- **Repository access**:**Only select repositories** → 只勾要用的 repo
- **Permissions → Repository permissions**(只開這幾項,其餘全部 No access):
  - `Contents` → **Read and write**(clone/fetch + push commit/branch)
  - `Pull requests` → **Read and write**(開 PR、貼 review comment、讀 diff)
  - `Issues` → **Read and write**(**只有 Morty 需要**:`gh issue comment` 回貼 spec;Rick/Summer 用不到可留 No access)
  - `Metadata` → **Read**(勾上面任一項就會自動帶上、拿不掉,正常)
- **Account permissions**:全部 No access(bot 只碰 repo)。
- 產生 → 複製(`github_pat_...`)

> **絕對別開的權限**(這些才是被 prompt injection 時出事的來源):
> - `Workflows` ❌ ── 開了 = token 能改 `.github/workflows/`、能推惡意 CI。bot 不改 workflow。
> - `Administration` ❌ ── repo 設定、collaborator、刪 repo。
> - `Actions` / `Secrets` / `Webhooks` / `Environments` / `Deployments` ❌ ── 全用不到。

> **org repo 的雷:**
> 1. **一把 fine-grained PAT 只綁一個 resource owner**。公司 repo 若橫跨 `104corp` 與 `openabdev` 兩個 org,`GH_TOKEN_CAC` 一把不夠 ── 每個 org 各建一把。
> 2. **org 要先放行**:org Settings → Personal access tokens 要允許 fine-grained token;送出後 token 可能卡 **pending approval**,org admin 核准前對該 org repo 無效(「token 建好卻 clone 不到」最常見主因)。
> 3. Morty 的 CAC token 記得**多勾 `104corp/cac-ai-rules`**(讀產品對照表要 `Contents` read)。

> **若你用的是 classic PAT(`ghp_`)**:classic 無法限定單一 repo(`repo` scope = 帳號能看的所有 repo),所以**務必搭配 machine user** 用「帳號成員資格」框住範圍,並**拿掉 `workflow` scope**(沒在用的話)——`workflow` 會讓被注入的 agent 推惡意 CI。

### B3. 放進秘密檔(下一節 Part C 會建立)

兩把 token 之後寫進 `~/.openab-secrets.env` 的 `GH_TOKEN_WM4N=`/`GH_TOKEN_CAC=`,**不要**寫進 config.toml、不要寫進 docker 指令。

---

## Part C — Mac mini 主機準備

### C1. 建立 config 目錄與秘密檔

```bash
# config 目錄(會掛進容器當 /etc/openab)
mkdir -p ~/oab

# 秘密檔放在「掛載目錄之外」,避免又被掛進容器;並鎖權限
:> ~/.openab-secrets.env
chmod 600 ~/.openab-secrets.env
```

編輯 `~/.openab-secrets.env`,填入兩把 token(用你 Part A、B 拿到的):

```dotenv
DISCORD_BOT_TOKEN=你的_discord_bot_token
GH_TOKEN_WM4N=github_pat_wm4n_個人_fine_grained     # 釘死要給 bot 碰的 wm4n repo
GH_TOKEN_CAC=github_pat_cac-william_公司_fine_grained # 釘死要碰的 104corp/… repo
```

> 為什麼用 `--env-file` 而不是 `-e`?避免 token 出現在 shell history 和 `docker run` 指令裡。

### C2. 建立 config.toml

編輯 `~/oab/config.toml`(完整版見[附錄](#附錄完整範例檔)):

```toml
[discord]
bot_token = "${DISCORD_BOT_TOKEN}"          # openab 從環境變數展開
allowed_channels = ["你的_CHANNEL_ID"]
allowed_users    = ["你的_USER_ID"]          # 限制只有你能用

[agent]
command     = "claude-agent-acp"            # 必須是這個,不是 "claude"
args        = []
working_dir = "/home/node"
# GitHub token 不走 env:兩帳號登入 gh、任務內 gh auth switch 選帳號(見 Part F2)。
# inherit_env 只放非 GitHub 的 secret(此基本版無;Morty 版見 Part K2 保留 JIRA_*)。

[pool]
max_sessions      = 5
session_ttl_hours = 24
```

> **★ 本 runbook 的核心已改為 gh 雙帳號 + `gh auth switch`(見 Part F2)。** GitHub token 不再經 `inherit_env` 進 agent env;而是在 Part F 一次性登入 gh 後,由每個任務的「選帳號」步驟切換。這樣 agent 讀不到裸 token,且能依 repo owner 用對身份。

---

## Part D — 啟動容器

```bash
docker -c orbstack run -d \
  --name openab-claude \
  --restart unless-stopped \
  --env-file ~/.openab-secrets.env \
  -v openab-claude-home:/home/node \
  -v ~/oab:/etc/openab:ro \
  ghcr.io/openabdev/openab-claude:latest
```

說明:

- `--env-file`:注入 `DISCORD_BOT_TOKEN`(config 展開用)、`GH_TOKEN_WM4N`/`GH_TOKEN_CAC`(供 Part F 一次性 gh 登入用;登入後 agent 端不再依賴)。
- `-v openab-claude-home:/home/node`:**持久化** volume,放 `~/.claude` 憑證、`~/.config/gh`、git 設定、clone 下來的專案。容器重啟/更新映像都不會掉。
- `-v ~/oab:/etc/openab:ro`:把 config 目錄唯讀掛進去(openab 預設讀 `/etc/openab/config.toml`)。
- 用**掛目錄**而非掛單檔,避開 colima 的單檔 bind mount 快取雷(見[疑難排解](#疑難排解))。

確認啟動:

```bash
docker -c orbstack ps                 # STATUS 要是 Up ... (healthy)
docker -c orbstack logs openab-claude # 應看到 discord 連線成功
```

---

## Part E — Claude Code 登入

容器第一次跑時 Claude Code 還沒登入,要互動式登入一次(憑證會存進 volume,之後不用再登):

```bash
docker -c orbstack exec -it openab-claude claude auth login
```

依畫面完成 OAuth,然後重啟讓 bot 程序載入新憑證:

```bash
docker -c orbstack restart openab-claude
```

驗證憑證已落地:

```bash
docker -c orbstack exec -u node openab-claude ls -la /home/node/.claude
```

---

## Part F — 容器內 git/gh 設定(雙帳號)

把兩個帳號都登入進 gh(存進 volume 內的 `~/.config/gh/hosts.yml`),並讓 git 用 gh 當 credential helper:

```bash
docker -c orbstack exec -i -u node openab-claude sh -c '
  echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token &&
  echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token &&
  gh auth setup-git'
```

> 前提:env 內**不能有裸 `GH_TOKEN`**,否則 gh 會改用該環境變數並拒絕 `gh auth login`/`switch`。本 runbook 用 `GH_TOKEN_WM4N`/`GH_TOKEN_CAC`,故無此問題。

驗證兩個帳號都登入:

```bash
docker -c orbstack exec -u node openab-claude gh auth status   # 要看到 wm4n 與 cac-william 兩個 Logged in
```

> 署名不在此用 `--global` 設死;改由每個任務的「選帳號」步驟對該 repo 設 local `user.name/email`(見 Part F2)。

---

## Part F2 — 多帳號身份切換

一個 bot 服務兩個 GitHub 身份，由每個任務開工前的 `wm4n.repo-identity` skill 統一處理。三顆 bot 的 context 檔（CLAUDE.md／AGENTS.md）都必須在任何 `git`／`gh` 操作前呼叫它（見 Part K）。

owner 分流、帳號選擇與該帳號的 repo-local Git 署名，由已安裝 skill 的版本化 `deployment-guides/bot-skills/repo-identity/config.toml` 管理。該設定檔不存 token；無法判斷 owner 時 skill 會停止並詢問人類。

> **併發取捨:** `gh auth switch` 是整個容器全域。同一顆 bot 若同時跑兩個不同帳號的 thread(pool 併發)會互搶身份。單人主導、一次一個 feature 幾乎不會遇到。
>
> **Fallback(需跨帳號併發時再上):** 改「clone 時把 token 綁進該 repo remote + 每條 gh 指令加 `GH_TOKEN=$GH_TOKEN_XXX` 前綴」。此版需把兩把 token 放回 `inherit_env` 供逐條引用;`git remote -v` 含 token,務必守「不得貼進 Discord」鐵則。

---

## Part F3 — 雙身份 rollout 清單

把一顆原本用單一 `GH_TOKEN` 的 bot 升級成雙身份,每顆各做一遍(Mac mini 用 `docker -c orbstack exec`,Portainer 用網頁 Console;一律 user `node`):

1. **建兩把 fine-grained PAT**:`wm4n` 釘個人 repo、`cac-william` 釘公司 repo(權限見 [Part B2](#b2-建-fine-grained-pat優先釘死-repo))。
2. **改 secrets**:env 檔改成 `GH_TOKEN_WM4N`/`GH_TOKEN_CAC`,**移除裸 `GH_TOKEN`**。改 env 動不了執行中容器 → Mac mini `docker ... rm -f` 後**重建**;Portainer 改 Stack env 後 **redeploy**。
3. **gh 雙帳號登入**(容器內,user `node`):
   ```bash
   echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token
   echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token
   gh auth setup-git
   gh auth status                              # 應看到 wm4n + cac-william 兩個
   ls -la /home/node/.config/gh/hosts.yml      # 檔案在了
   ```
4. **改 config**:`[agent].inherit_env` 移除 `GH_TOKEN`(**Morty 保留 `JIRA_*`**)→ 重啟(config 掛載)或重建。
5. **寫入更新後的完整 v2 context 檔**（含「選帳號」開場；見 [Part K](#part-k--三-bot-接力-pipelinemortricksummer)）。
6. **煙霧測試**:`gh auth switch --user wm4n` → clone+push 一個個人 repo(署名=wm4n、無 403);再 `gh auth switch --user cac-william` → 對一個公司 repo 同樣測。
7. **端對端**:在 #dev-bot 各跑一條個人 GitHub Issue 與一條公司任務,確認兩邊 PR 的 commit 署名正確、無 403。

> **gh 登入為何「restart 就消失」?** 登入狀態存在 `$HOME/.config/gh/hosts.yml`。只要 (a) 以 **node**(`HOME=/home/node`)登入、(b) `/home/node` 掛**持久化 volume**、(c) env 沒有**裸 `GH_TOKEN`** 蓋掉,它就會跟 `~/.claude` 一樣留著。三個常見「消失」原因:登入時是 **root**(寫到 `/root`、非持久且 agent 讀不到)、volume 沒持久化、或 env 還有**裸 `GH_TOKEN`**(gh 改用 env、根本不寫 hosts.yml)。快速定位:`whoami`、`ls -la /home/node/.config/gh/hosts.yml`、`env | grep -i gh_token`、`ls -la /home/node/.claude`(若 .claude 也不見 → volume 問題)。
>
> **Portainer restart-proof 保險做法:** 常 restart 的 bot 可把 gh 登入做進開機——Stack `command` 改成先登入再 `exec openab run`,token 由 Stack env 提供,每次啟動重建 hosts.yml、不靠 volume 持久化:
> ```yaml
>     command:
>       - sh
>       - -lc
>       - >
>         echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token &&
>         echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token &&
>         gh auth setup-git &&
>         exec openab run -c /home/node/config.toml
> ```
> (前提:PID1 以 `node`、`HOME=/home/node` 執行才會寫對位置;若 PID1 是 root,改用 `su node -c '...'` 或 service 設 `user: node`。)

---

## Part G — 放入 workspace 脈絡 CLAUDE.md

agent 的工作目錄 `/home/node` 預設是空的。放一份 `CLAUDE.md` 在根目錄,Claude Code 會自動載入當環境脈絡:

```bash
docker -c orbstack exec -i -u node openab-claude sh -c 'cat > /home/node/CLAUDE.md' <<'EOF'
# CLAUDE.md — openab @ Mac mini 工作環境

## 你是誰 / 在哪
- 你是透過 openab 橋接到 Discord 的 Claude Code agent。
- 執行環境:Mac mini 的 Docker 容器(OrbStack),映像 ghcr.io/openabdev/openab-claude。
- 使用者在 Discord @你 來派工;每個 thread 對應一個 session。

## 溝通語言
- 一律使用繁體中文(台灣正體)回覆。

## 工作目錄與持久化
- 工作目錄(= $HOME):/home/node,掛在 docker volume,容器重啟不會掉。
- Claude Code 憑證在 /home/node/.claude;GitHub 憑證在 /home/node/.config/gh。

## 可用工具
- git、gh(GitHub CLI)、node 22、npm、rg(ripgrep)。

## 目前狀態
- 要開始工作時,把目標 repo git clone 到 /home/node/<repo> 底下再進行。
EOF
```

> 改完 workspace 內容後,要在 Discord **開新 thread** 才會重讀。

---

## Part H — 端對端驗證

1. **容器健康**:`docker -c orbstack ps` → `Up (healthy)`。
2. **Discord 連線**:`docker -c orbstack logs openab-claude` → 看到 bot 連上、帳號名稱正確。
3. **GitHub(模擬 agent 條件)**:
   ```bash
   docker -c orbstack exec -u node openab-claude \
     git clone https://github.com/OWNER/REPO.git /tmp/verify && echo CLONE_OK
   ```
4. **Discord 實測**:在允許的頻道 @bot,請它 `clone <你的 repo> 並列出檔案`,確認它真的拉得到。

全部過 → 部署完成 ✅

---

## Part I — Portainer(另一台,UI-only)部署

> 適用:另一台你**只有 Portainer 網頁、沒有 shell** 的主機。與 Mac mini 差異:用 **Stack(compose)** 取代 `docker run`、用 **Console(網頁 exec)** 做登入/設定;**直接用官方 image,不必自 build**。並存時**每顆 bot 用不同 Discord token**(見 Part A)。

**I1. 建 Stack(先 sleep 待命)** — Stacks → Add stack → Web editor:

```yaml
services:
  openab:
    image: ghcr.io/openabdev/openab-claude:latest # Codex：openab-codex:latest
    restart: unless-stopped
    command: ["sleep", "infinity"] # 階段1:待命,方便進 Console
    environment:
      DISCORD_BOT_TOKEN: "${DISCORD_BOT_TOKEN}"
      GH_TOKEN_WM4N: "${GH_TOKEN_WM4N}"
      GH_TOKEN_CAC: "${GH_TOKEN_CAC}"
    volumes:
      - openab-home:/home/node # Claude、Codex 皆為 /home/node
volumes:
  openab-home:
```

下方 **Environment variables** 填 `DISCORD_BOT_TOKEN`、`GH_TOKEN_WM4N`、`GH_TOKEN_CAC` → Deploy。

> 沒 config 時 `openab run` 會 crash-loop、進不去 Console,故先用 sleep。此時顯示 **unhealthy 是正常的**(healthcheck 找不到 openab process)。

**I2. Console 設定**(取代 Part C/E/F)— Containers → 該容器 → **Console** → user `node`(Claude、Codex 皆為 node):

```bash
cat > /home/node/config.toml <<'EOF'
[discord]
bot_token        = "${DISCORD_BOT_TOKEN}"
allowed_channels = ["你的_CHANNEL_ID"]
allowed_users    = ["你的_USER_ID"]
[agent]
command     = "claude-agent-acp"     # Codex：codex-acp
working_dir = "/home/node"            # Claude、Codex 皆為 /home/node
# GitHub token 不走 env：兩帳號登入 gh、任務內 gh auth switch 選帳號(見 Part F2)
[pool]
max_sessions = 5
EOF
claude auth login                    # Codex：codex login --device-auth
echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token   # 兩帳號登入(Codex 同)
echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token
gh auth setup-git                    # git 憑證(選帳號見 Part F2)
```

> config 放 `/home/node`(該 user 可寫),避開 named volume 掛 `/etc/openab` 的 root 權限問題。

**I3. 切正式啟動** — Stacks → 該 stack → Editor,把 `command:` 改成 `["openab","run","-c","/home/node/config.toml"]` → Update。轉 healthy 即完成;邀 bot 進頻道見 Part A3/A4。

> **要自 build 變體映像時**:Portainer 的 Build → Upload **只認 archive 根目錄的 `Dockerfile`**(無路徑欄)。先把目標 Dockerfile 放成根 `Dockerfile`:`git archive <branch> | tar -x -C ctx && cat ctx/Dockerfile.claude > ctx/Dockerfile && tar czf ctx.tgz -C ctx .`(用 `cat` 覆蓋;`cp` 可能被 `-i` alias 擋)。在該主機 build 會**自動對到主機架構**。
>
> **注意**:Claude 的 5h/weekly **usage meter 在 ACP/headless 拿不到**(Anthropic SDK 限制,正常狀態不給 utilization),別期待 bot 顯示額度 %。

---

## Part J — Codex 變體(與 Claude 並存)

> 你有 Codex(OpenAI/ChatGPT)帳號、想再跑一顆 Codex bot。**沿用上面所有步驟**(Mac mini 走 Part A–H、只有網頁的另一台走 Part I),只把下表的值換掉即可。Codex 官方映像也是 node:22 base,家目錄/使用者與 Claude **完全相同**,差異只有三處。

**先決:另一顆 bot = 另一個 Discord Application + 另一把 token + 不同容器名/config/volume**(Part A 整套重做一次,拿到新的 `DISCORD_BOT_TOKEN`)。兩顆 bot **建議各用一個頻道**,避免同頻道兩隻都回。兩把 GitHub token(`GH_TOKEN_WM4N`/`GH_TOKEN_CAC`)可沿用同一組。

| 項目                      | Claude                                   | Codex                                                                     |
| ------------------------- | ---------------------------------------- | ------------------------------------------------------------------------- |
| 映像                      | `ghcr.io/openabdev/openab-claude:latest` | `ghcr.io/openabdev/openab-codex:latest`                                   |
| config `[agent].command`  | `claude-agent-acp`                       | `codex-acp`                                                               |
| 登入                      | `claude auth login`                      | `codex login --device-auth`(裝置碼:拿 URL+code 到瀏覽器用 Codex 帳號授權) |
| 憑證位置                  | `/home/node/.claude`                     | `/home/node/.codex`                                                       |
| 脈絡檔(Part G)            | `CLAUDE.md`                              | `AGENTS.md`(Codex 慣例)                                                   |
| HOME / user / working_dir | `/home/node` / `node`                    | **相同**                                                                  |

Mac mini 上為避免撞名,整組用獨立名稱(容器 `openab-codex`、config `~/oab-codex`、秘密檔 `~/.openab-codex-secrets.env`、volume `openab-codex-home`)。啟動指令(取代 Part D):

```bash
docker -c orbstack run -d \
  --name openab-codex \
  --restart unless-stopped \
  --env-file ~/.openab-codex-secrets.env \
  -v openab-codex-home:/home/node \
  -v ~/oab-codex:/etc/openab:ro \
  ghcr.io/openabdev/openab-codex:latest
```

登入(取代 Part E):

```bash
docker -c orbstack exec -it openab-codex codex login --device-auth    # 依畫面拿 URL+code 授權
docker -c orbstack restart openab-codex
docker -c orbstack exec -u node openab-codex ls -la /home/node/.codex # 驗證憑證落地
```

其餘與 Claude 相同:git/gh 見 Part F(容器名改 `openab-codex`)、脈絡檔見 Part G(檔名改 `AGENTS.md`)、端對端驗證見 Part H。

---

## Part K — 三 Bot 接力 Pipeline(Morty/Rick/Summer)

> 三顆 bot 分工：**Morty**(Claude@Portainer)負責規格分析與 PR 複審、**Rick**(Claude@OrbStack Mac mini)負責 openspec 開發、**Summer**(Codex@OrbStack Mac mini)負責程式碼 review。靠 openab 的 `allow_bot_messages="mentions"` + `trusted_bot_ids` 讓 bot 互相 @呼叫。
>
> **雙模式**：三隻 bot 預設為資深工程師模式（隨手問答/看 code 不開流程）；被明確要求走流程時才觸發對應 pipeline skill。

### K1. Bot 互呼設定(config.toml)

每顆 bot 的 config.toml 都要加：

```toml
[discord]
allow_bot_messages = "mentions"       # 收到其他 bot @mention 才動作
trusted_bot_ids    = ["BOT_A_ID", "BOT_B_ID"]  # 填另外兩顆 bot 的 Discord User ID
```

三顆 bot 的 Discord User ID 取得方式：Discord 開發者模式 → 右鍵 bot 帳號 → 複製使用者 ID。

### K2. Morty(Claude@Portainer) — 規格分析 + PR 複審

**角色：** 分析 JIRA 票、GitHub Issue、Crashlytics bug；產 design spec；PR 複審。

**秘密檔**(`~/.openab-secret-morty.env`，chmod 600)：

```dotenv
DISCORD_BOT_TOKEN=你的_morty_discord_bot_token
GH_TOKEN_WM4N=github_pat_wm4n_個人_fine_grained
GH_TOKEN_CAC=github_pat_cac-william_公司_fine_grained
JIRA_TOKEN=你的_atlassian_api_token
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_EMAIL=your-email@company.com
```

**config.toml** 的 `inherit_env`：

```toml
[agent]
command     = "claude-agent-acp"
working_dir = "/home/node"
inherit_env = ["JIRA_TOKEN", "JIRA_BASE_URL", "JIRA_EMAIL"]   # GitHub 走 gh 雙帳號,不放 GH_TOKEN
```

**Portainer Stack** Environment variables 要同步加入上述所有 JIRA 變數（Stack env 注入容器，config.toml inherit_env 再傳給 agent）。

**skill 安裝**（Portainer Console，user `node`）：

```bash
# 1) jira-fetch：clone skill-registry 到無版本號路徑，再 symlink 進 ~/.claude/skills/
git clone https://github.com/wm4n/skill-registry.git /home/node/github-repo/skill-registry
mkdir -p /home/node/.claude/skills
ln -sfn /home/node/github-repo/skill-registry/skills/jira-fetch /home/node/.claude/skills/jira-fetch

# 2) superpowers：互動 session 內 /plugins 裝好後，把要用的 skill symlink 進 ~/.claude/skills/
#    （claude → /plugins → 選 superpowers → Install Plugin → /exit）
ln -sfn /home/node/.claude/plugins/superpowers/skills/brainstorming        /home/node/.claude/skills/superpowers.brainstorming
ln -sfn /home/node/.claude/plugins/superpowers/skills/systematic-debugging /home/node/.claude/skills/superpowers.systematic-debugging
ls -la /home/node/.claude/skills/   # 三條 symlink（jira-fetch/superpowers.brainstorming/superpowers.systematic-debugging）都在、owner 為 node

# 3) pipeline skill：clone openab repo（或 sparse-checkout bot-skills/）後 symlink 進 ~/.claude/skills/
#    <owner> 依 spec §7.2 rollout 決定（openab repo 來源）；同一份 checkout 同時供下方 CLAUDE.md 組合與此處 symlink 使用
git clone https://github.com/<owner>/openab.git /home/node/github-repo/openab 2>/dev/null || git -C /home/node/github-repo/openab pull
ln -sfn /home/node/github-repo/openab/deployment-guides/bot-skills/requirement-analysis /home/node/.claude/skills/wm4n.requirement-analysis
ln -sfn /home/node/github-repo/openab/deployment-guides/bot-skills/change-review        /home/node/.claude/skills/wm4n.change-review
ln -sfn /home/node/github-repo/openab/deployment-guides/bot-skills/repo-identity        /home/node/.claude/skills/wm4n.repo-identity
ls -la /home/node/.claude/skills/   # wm4n.requirement-analysis / wm4n.change-review / wm4n.repo-identity symlink 都在
```

> ⚠️ **ACP skill 載入規則（舊版實測，Mac mini/Portainer 這批版本適用）**：claude-agent-acp 只掃描 `~/.claude/skills/<name>/SKILL.md`；marketplace（`/plugins`）裝在 `~/.claude/plugins/cache/` 的**不會**被載入，所以裝完一定要 symlink 進 `~/.claude/skills/`。symlink 指 git checkout／plugin 目錄，**別指** cache 版本目錄（`.../1.0.0/`，更新就斷鏈）。
> **2026-07-22 於 k3s 較新版本推翻此結論**：見下方 [K2a](#k2a--superpowers-純-cli-安裝法2026-07-22-起k3s-驗證)（superpowers）與 [K2b](#k2b--openab-bot-skills-也改走同一套-plugin-安裝法2026-07-22)（`wm4n.*` pipeline skill），純 CLI 裝好後**不用**手動 symlink 也讀得到。本節（Mac mini 部署）維持原始文件，供對照歷史沿革。
> ⚠️ **skill 名稱一致 + 不要用 cat**：CLAUDE.md 直接用自然語言講 skill 名稱（如「使用 superpowers.brainstorming skill」），**不要**寫成 `cat <路徑>/SKILL.md` 把內容印出來；prompt 裡的名稱必須等於 skill 清單顯示名（＝ symlink 目錄名）。superpowers 系列統一用 `superpowers.` prefix（`superpowers.brainstorming`、`superpowers.systematic-debugging`）；`jira-fetch` 非 superpowers、維持原名；wm4n/openab repo 內建 skill 的 symlink 目錄名與 context 檔引用名統一加 `wm4n.` prefix（`wm4n.requirement-analysis`、`wm4n.change-review`、`wm4n.repo-identity`），SKILL.md frontmatter `name` 維持裸名（同 superpowers 前例，ACP 以 symlink 目錄名為準）。

**gh 雙帳號登入**（Console，user `node`；`GH_TOKEN_WM4N/CAC` 已由 Stack env 注入）：

```bash
echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token
echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token
gh auth setup-git
gh auth status   # 要看到 wm4n 與 cac-william 兩個 Logged in
```

> Portainer Stack 的 Environment variables 要把 `GH_TOKEN` 改成 `GH_TOKEN_WM4N`、`GH_TOKEN_CAC` 兩筆。

**CLAUDE.md**：直接部署完整的 Morty v2 context 檔 `Morty-CLAUDE_v2.md`。

```bash
CK=/home/node/github-repo/openab/deployment-guides
cp "$CK/Morty-CLAUDE_v2.md" /home/node/CLAUDE.md
```

Morty persona 內指路的正式流程 skill：
- 正式分析需求/JIRA/Issue/crash 並產 spec → `wm4n.requirement-analysis` skill（內含四角色觸發偵測、`jira-fetch` 取票、`superpowers.brainstorming`/`superpowers.systematic-debugging` 產 spec 等細節）
- 正式複審 PR → `wm4n.change-review` skill（內含 `/review` 發佈 PR review comment、@Rick 回報結果等細節）
- 其餘（問問題、看 code、討論、隨手幫忙）維持資深工程師模式，不 @ 其他 bot、不開流程

**驗證寫入**：

```bash
head -5 /home/node/CLAUDE.md   # 應看到「Agent Morty 核心運行指南」
```

**重啟後驗證** `env | grep JIRA` 看到三個 JIRA 變數有值。

### K2a — superpowers 純 CLI 安裝法（2026-07-22 起，k3s 驗證）

> 取代上面 K2 的「互動 `/plugins` → 手動 symlink」流程。`jira-fetch` 目前仍走 Part K 原本的 clone + symlink 方式（技術上也能透過 `wm4n/skill-registry` 既有的 `skill-registry` plugin 純 CLI 裝，但尚未切換、不影響現況）；`wm4n.*` pipeline skill（`requirement-analysis`/`change-review`/`feature-development`/`repo-identity`/`openab-schedule`/`change-review-codex`）已改走純 CLI，見下方 [K2b](#k2b--openab-bot-skills-也改走同一套-plugin-安裝法2026-07-22)。

**Claude 家族（Rick、Morty；`kubectl exec` 換成對應 pod/deployment 即可）：**

```bash
kubectl exec deployment/openab-claude-morty -n cac -- claude plugin marketplace add anthropics/claude-plugins-official
kubectl exec deployment/openab-claude-morty -n cac -- claude plugin install superpowers@claude-plugins-official

# 驗證裝上（不用再手動 symlink 進 ~/.claude/skills/）
kubectl exec deployment/openab-claude-morty -n cac -- cat /home/node/.claude/plugins/installed_plugins.json
```

✅ **已於 Morty、Rick 兩隻實測**：裝完直接在 Discord mention 該 bot、請它**實際呼叫**一個 superpowers skill（例如「請用 Skill 工具呼叫 superpowers:brainstorming」），能成功載入內容——證實 ACP 現在（本批 image 版本）能直接讀到 marketplace 裝的 plugin，不需要手動 symlink。

**Codex 家族（Summer）：指令平行但語法不同，且 marketplace 來源不同**

`codex` CLI 有獨立但語法對應的 plugin 系統。⚠️ 用 Claude 那個 `anthropics/claude-plugins-official` marketplace 對 Codex **未驗證能不能通**；改用 superpowers 作者自己的 marketplace repo 才裝成功：

```bash
kubectl exec deployment/openab-codex-summer -n cac -- codex plugin marketplace add obra/superpowers-marketplace
kubectl exec deployment/openab-codex-summer -n cac -- codex plugin add superpowers@superpowers-marketplace

# 驗證裝上
kubectl exec deployment/openab-codex-summer -n cac -- codex plugin list
```

✅ **已確認安裝成功且執行期讀得到**（版本 6.1.1，與 Claude 端一致，裝在 `~/.codex/plugins/cache/superpowers-marketplace/superpowers/6.1.1`）。2026-07-22 已在 Discord 對 Summer 實測呼叫 superpowers skill 成功——codex-acp 確實掃得到這個 plugin cache 路徑，跟 `~/.codex/skills/` 的手動 symlink 是各自獨立、互不影響的兩條路徑，並存不衝突。

### K2b — openab bot-skills 也改走同一套 plugin 安裝法（2026-07-22）

> `wm4n/skill-registry` 這個 repo 本身就是一個 marketplace（`.claude-plugin/marketplace.json`，marketplace 名稱 `wm4n-skill-registry`），除了原本的 `skill-registry` plugin（jira-fetch/learn-from-repo/self-evolution）之外，新增了 **`openab-bot-skills`** plugin，把 `requirement-analysis`/`change-review`/`feature-development`/`repo-identity`/`openab-schedule`/`change-review-codex` 這 6 個 pipeline skill 都包進去了。**推翻上面 K2/K2a 說「wm4n.\* 沒有 marketplace 來源、仍要 clone+symlink」的說法**——現在也走純 CLI：

```bash
# Claude 家族（Rick、Morty）
kubectl exec deployment/openab-claude-rick -n cac -- claude plugin marketplace add wm4n/skill-registry
kubectl exec deployment/openab-claude-rick -n cac -- claude plugin install openab-bot-skills@wm4n-skill-registry

kubectl exec deployment/openab-claude-morty -n cac -- claude plugin marketplace add wm4n/skill-registry
kubectl exec deployment/openab-claude-morty -n cac -- claude plugin install openab-bot-skills@wm4n-skill-registry

# Codex 家族（Summer）
kubectl exec deployment/openab-codex-summer -n cac -- codex plugin marketplace add wm4n/skill-registry
kubectl exec deployment/openab-codex-summer -n cac -- codex plugin add openab-bot-skills@wm4n-skill-registry
```

✅ **已於 Rick、Morty、Summer 三隻全數實測成功**。裝好後 skill 清單顯示名是 `openab-bot-skills:feature-development` 這種 `plugin:skill` 格式（跟 `superpowers:brainstorming` 一樣），**但 Rick 實測用裸名 `requirement-analysis`（不加任何前綴）一樣能成功呼叫**——Claude 自己會把自然語言提到的裸名對應到清單裡的完整名稱。因此 **persona 檔（CLAUDE.md/AGENTS.md）裡引用 skill 一律寫裸名即可**（如「使用 feature-development skill」），不用寫 `openab-bot-skills:` 前綴，寫法與既有 `superpowers.*`／舊 `wm4n.*` 慣例保持一致的簡潔度。

⚠️ **重複 skill 的收尾**：這批 bot 原本用 K3S.md／Part K 的方式手動 symlink 了 `wm4n.feature-development`、`wm4n.repo-identity`、`wm4n.schedule-management`（Rick/Morty，plugin 版已改名 `openab-schedule`，symlink 檔名歷史上維持原樣）、`wm4n.change-review-codex`（Summer）。改用 plugin 安裝後，同一個 skill 會同時存在兩份（`wm4n.xxx` 手動版 + `openab-bot-skills:xxx` plugin 版）——不會衝突報錯，但兩份內容之後會各自維護、容易漂移不同步。確認 persona 檔已全部改用裸名（見上）後，**應刪除舊的手動 symlink**：

```bash
# Rick / Morty
kubectl exec deployment/openab-claude-rick  -n cac -- rm -f /home/node/.claude/skills/wm4n.feature-development /home/node/.claude/skills/wm4n.repo-identity /home/node/.claude/skills/wm4n.schedule-management
kubectl exec deployment/openab-claude-morty -n cac -- rm -f /home/node/.claude/skills/wm4n.requirement-analysis /home/node/.claude/skills/wm4n.change-review /home/node/.claude/skills/wm4n.repo-identity /home/node/.claude/skills/wm4n.schedule-management

# Summer
kubectl exec deployment/openab-codex-summer -n cac -- rm -f /home/node/.codex/skills/wm4n.change-review-codex /home/node/.codex/skills/wm4n.repo-identity
```

之後要更新 skill 內容，改 `deployment-guides/bot-skills/` 裡的檔案不再有作用（那份 clone 已經不是真相來源），要同步更新 `wm4n/skill-registry` repo 裡 `plugins/openab-bot-skills/skills/` 對應檔案、bump `plugin.json`/`marketplace.json` 版本號、push，再對每隻 bot 跑 `claude plugin marketplace update` / `codex plugin marketplace upgrade` + 重裝。

⚠️ **2026-07-24 新增 `solo-bot-skills` plugin，別跟 `openab-bot-skills` 混裝**：`openab-bot-skills` 只給**接力型** bot（Rick/Morty/Summer，會互相 `@mention` 交棒）；獨立、不接力、自己一手包辦全流程的 bot（如 genie，見 K3S.md「未來加 agent」）要裝的是同一個 marketplace 底下**另一個**獨立 plugin `solo-bot-skills`（含 `solo-feature-pipeline`、`openab-schedule`）。兩者結構上分開維護，故意不共用同一包——避免接力型 bot 誤觸發「不假手其他 bot」的 solo 流程，或獨立型 bot 誤裝到只在多 bot 交棒情境才有意義的 `feature-development`/`requirement-analysis`/`change-review` 等 skill。裝法一樣是 `claude plugin install solo-bot-skills@wm4n-skill-registry`。

**Genie 的 polyglot runtime（mise，2026-08-25 新增，Phase 1 = Flutter + Python）**：Genie 的 pod 是唯讀根檔案系統，只有 PVC 可寫，所以用 mise 的 `shims` 模式（不是 `activate`，Genie 每次工具呼叫都是全新 process，shell hook 不會生效）管理 Flutter/Python（之後會擴充 PHP/Android CLI），依 repo 自己的 `.mise.toml`/`.tool-versions` 自動切版本。完整安裝步驟見 `deployment-guides/k3s/genie-mise-setup.md`。

### K2c — Genie：Auto Dev Pipeline 安裝步驟（`agent-dev-poller`，2026-09-06 新增）

Jira 票或 GitHub issue 貼上 `ready-for-agent-dev` label 後，一個獨立部署的
`agent-dev-poller`（K8s CronJob，不含 LLM，見
`deployment-guides/k3s/agent-dev-poller/`）偵測到後，用既有的
`jira-grill-trigger` bot @mention Genie，觸發 `auto-dev-pipeline` skill
直接進全自動開發（跳過人類確認閘門）。跟 `jira-grill` 是完全獨立的兩條
poller/label 機制，互不影響。

**1. Skill 已經隨 `solo-bot-skills` plugin 一起裝好，只需要更新版本**
（Genie 本來就裝了這個 plugin，這次是內容更新到 1.1.0，不用額外
`plugin install`）：

```bash
kubectl exec deployment/openab-claude-genie -n cac -- claude plugin marketplace update wm4n-skill-registry
kubectl exec deployment/openab-claude-genie -n cac -- claude plugin update solo-bot-skills@wm4n-skill-registry
```

**2. 更新 Genie 的 CLAUDE.md**（本次在 `Genie-CLAUDE_v2.md` 新增了「4a.
Auto Dev Pipeline」小節，指向這支新 skill）：先確認這個 branch 已經
push，再跑既有的 `update-context.sh`（見 Part N；四隻 bot 都會重新
`git pull` + 覆寫 `CLAUDE.md`/`AGENTS.md`，不是只有 Genie）：

```bash
bash /path/to/update-context.sh
```

跑完後記得到 Discord 對 Genie 開一條新 thread 才會重讀 CLAUDE.md（舊
thread 不會重讀）。

**3. 確認 Genie 的 Discord 設定已經涵蓋，不用改 Helm values**：`values-openab-claude.yaml`
裡 Genie 的 `discord.trustedBotIds` 已含 `jira-grill-trigger`（`1541617131442147438`），
`discord.allowedChannels` 已含 `cac-notify`（`1528965173761802420`）——這兩項
`jira-grill-poller` 上線時就加過了，這次不用再 `helm upgrade`。

**4. 申請 cac-william 這把 GitHub 憑證**——⚠️ **2026-09-07 更正**：
`104corp` 這個 org 沒有開放 fine-grained PAT 存取 org repo（GitHub 要求
org owner 先在 Organization Settings → Personal access tokens 明確
開放，目前未開放，且不是我們能自己改的設定），改用**帳號角色限縮**取代
「token 權限限縮」：

1. 請有 repo admin 權限的人，把 `cac-william` 加為
   `104corp/interview-ai-summary` 的 collaborator，權限選
   **Triage**（不是 Write/Admin）——Triage 能管理 issue/label（含新增、
   移除），但沒有 code 的讀寫權限，就算 token 外洩也 push 不了 code、
   merge 不了 PR。
2. 用 `cac-william` 帳號申請一把 **classic token**（GitHub → Settings →
   Developer settings → Personal access tokens → Tokens (classic) →
   Generate new token (classic)），勾 `repo`（private repo 沒有更細的
   scope，只能整個勾，防線在上一步的 Triage 角色，不是 token 本身）。
3. 之後若白名單加入 `wm4n/*` 的 repo（目前沒有，見
   `GITHUB_AGENT_DEV_REPOS` 白名單），`wm4n` 是個人帳號沒有 org 那條
   限制，可以照原計畫申請 **fine-grained PAT**（Resource owner=`wm4n`，
   只勾該 repo，Permissions → Issues: Read and write）。

**5. 建對應的 K8s Secret**（在 k3s 機器上執行；目前白名單只有 104corp 的
repo，先只建 `-cac` 這把即可，`-wm4n` 等真的加入 wm4n repo 才需要，見
`cronjob.yaml` 裡的註解）：

```bash
kubectl create secret generic github-agent-dev-poller-cac --from-literal=token=<步驟 4 申請的 cac-william classic token> -n cac
```

**6. 在白名單的 GitHub repo 先建好四個 label**（GitHub 的「加 label 到
issue」API 不會自動建立不存在的 label，要先手動建，或用 `gh label
create` 批次建）：

```bash
for REPO in 104corp/interview-ai-summary; do
  gh label create ready-for-agent-dev --repo "$REPO" --color BFD4F2 --description "已完整分析，交給 Genie 全自動開發" 2>/dev/null
  gh label create agent-dev-active    --repo "$REPO" --color FBCA04 --description "Genie 正在處理中" 2>/dev/null
  gh label create agent-dev-done      --repo "$REPO" --color 0E8A16 --description "Genie 已開 PR" 2>/dev/null
  gh label create agent-dev-failed    --repo "$REPO" --color D93F0B --description "Genie 停手，需要人類介入" 2>/dev/null
done
```

Jira 側不用預先定義 label，貼 `ready-for-agent-dev` 文字上去就算數。

**7. 白名單與 Genie 的 Discord user ID 已經填進 `cronjob.yaml`**
（`JIRA_AGENT_DEV_PROJECTS=CACJOB,CACVIP,CACATS`、
`GITHUB_AGENT_DEV_REPOS=104corp/interview-ai-summary`、
`GENIE_DISCORD_USER_ID=1530106874613989406`），沒有 `CHANGE_ME` 佔位值
了，直接套用：

```bash
kubectl apply -f deployment-guides/k3s/agent-dev-poller/cronjob.yaml
```

**8. 驗證**：手動觸發一次 Job 跑 poller（不用等 10 分鐘排程）：

```bash
kubectl create job --from=cronjob/agent-dev-poller agent-dev-poller-manual-test -n cac
kubectl logs -n cac job/agent-dev-poller-manual-test -f
```

- 先在一個白名單 repo/project 裡對一張測試 issue/票貼 `ready-for-agent-dev`，
  確認 log 印出「已觸發：...」、label 換成 `agent-dev-active`、Discord
  `cac-notify` 頻道出現 @mention Genie 的觸發訊息。
- 確認 Genie 收到後依 `auto-dev-pipeline` skill 開始動作（讀 issue/票 →
  `openspec new` → …）。
- 測試完 `kubectl delete job agent-dev-poller-manual-test -n cac` 清掉。

**已知限制**（沿用設計討論的結論，未來要再解的話另外評估）：`agent-dev-active`
沒有逾時自動復原，Genie pod 中途被殺需要人類手動把 label 改回
`ready-for-agent-dev`。

### K3. Rick(Claude@OrbStack Mac mini) — openspec 開發

**角色：** 收到 Morty 的 spec → openspec propose→apply→archive → 推 PR → @Morty + @Summer。

**秘密檔**(`~/.openab-secret-rick.env`，chmod 600)：

```dotenv
DISCORD_BOT_TOKEN=你的_rick_discord_bot_token
GH_TOKEN_WM4N=github_pat_wm4n_個人_fine_grained
GH_TOKEN_CAC=github_pat_cac-william_公司_fine_grained
```

**Docker 啟動**（OrbStack，使用獨立 volume `openab-rick-home`）：

```bash
docker -c orbstack run -d \
  --name openab-rick \
  --restart unless-stopped \
  --env-file ~/.openab-secret-rick.env \
  -v openab-rick-home:/home/node \
  ghcr.io/openabdev/openab-claude:latest
```

**OpenSpec 安裝**（root 權限）：

```bash
docker -c orbstack exec -u root openab-rick npm install -g @fission-ai/openspec@latest
docker -c orbstack exec -u node openab-rick openspec --version  # 確認印出版本
```

**gh 雙帳號登入**（`GH_TOKEN_WM4N/CAC` 由 `--env-file` 注入）：

```bash
docker -c orbstack exec -i -u node openab-rick sh -c '
  echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token &&
  echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token &&
  gh auth setup-git'
docker -c orbstack exec -u node openab-rick gh auth status   # wm4n + cac-william 兩個
```

> ⚠️ K3 未列出 Rick 的 config.toml。rollout 時確認 Rick 的 config 位置（掛載或 volume 內），若 `inherit_env` 仍含 `"GH_TOKEN"` 一併移除（GitHub 改走 gh 雙帳號）。

**skill 安裝**（clone openab repo 後 symlink 進 `~/.claude/skills/`；同一份 checkout 也供下方 CLAUDE.md 組合使用）：

```bash
docker -c orbstack exec -i -u node openab-rick sh -c '
  git clone https://github.com/<owner>/openab.git /home/node/github-repo/openab 2>/dev/null || git -C /home/node/github-repo/openab pull
  mkdir -p /home/node/.claude/skills
  ln -sfn /home/node/github-repo/openab/deployment-guides/bot-skills/feature-development /home/node/.claude/skills/wm4n.feature-development
  ln -sfn /home/node/github-repo/openab/deployment-guides/bot-skills/repo-identity        /home/node/.claude/skills/wm4n.repo-identity
  ls -la /home/node/.claude/skills/'   # wm4n.feature-development / wm4n.repo-identity symlink 都在
```

> `<owner>` 依 spec §7.2 rollout 決定（openab repo 來源）。

**CLAUDE.md**：直接部署完整的 Rick v2 context 檔 `Rick-CLAUDE_v2.md`。

```bash
docker -c orbstack exec -i -u node openab-rick sh -c '
  CK=/home/node/github-repo/openab/deployment-guides
  cp "$CK/Rick-CLAUDE_v2.md" /home/node/CLAUDE.md'
```

Rick persona 內指路的正式流程 skill：
- 收到 Morty 交棒的 branch+spec，或人類明確要求把 spec 正式開發成 PR → `wm4n.feature-development` skill（內含 openspec propose→apply→archive、`gh pr create`、@Morty + @Summer handoff、reviewer 結果處理等細節，取代原本寫在 heredoc 裡的完整流程步驟）
- 其餘（問問題、看 code、討論、隨手幫忙）維持資深工程師模式，不 @ 其他 bot、不開流程

**jira-grill（獨立能力，2026-08-24 新增，2026-08-25 改用 deterministic
poller 觸發）**：掛在 Rick 已裝的 `openab-bot-skills` plugin 裡（來源
`wm4n/skill-registry` repo，`plugins/openab-bot-skills/skills/jira-grill/`），
不需要額外 `plugin install`，`plugin marketplace update` +
`plugin update openab-bot-skills@wm4n-skill-registry` 就會拉到。需要
額外在 Rick 的 `values-openab-claude.yaml`（k3s，見 Part O）補
`secretEnv`（`JIRA_TOKEN`/`JIRA_BASE_URL`/`JIRA_EMAIL`，複用
`morty-jira` Secret）與 `discord.trustedBotIds` 裡加入
`jira-grill-trigger` bot 的 User ID，`helm upgrade` 後才會生效。

觸發機制**不是**掛在 Rick 自己身上的 cron 輪詢，而是一個獨立部署的
`jira-grill-poller`（K8s CronJob，見
`deployment-guides/k3s/jira-grill-poller/`，跟 openab 的 Helm release
分開部署）：這個 poller 全程不經過 LLM，只有偵測到新的 `grill-me` 票
或既有票的新回覆，才用一個新註冊的 `jira-grill-trigger` Discord bot
@mention Rick 觸發，觸發後才會消耗一次 LLM turn。部署/更新 poller 見
`deployment-guides/k3s/jira-grill-poller/cronjob.yaml`。

設計依據見
`docs/superpowers/specs/2026-08-24-rick-jira-grill-design.md`（grilling
方法論本身）與
`docs/superpowers/specs/2026-08-25-jira-grill-poller-design.md`（觸發
機制重寫）；實作計畫見
`docs/superpowers/plans/2026-08-24-rick-jira-grill.md`與
`docs/superpowers/plans/2026-08-25-jira-grill-poller.md`。

**驗證寫入**：

```bash
docker -c orbstack exec -u node openab-rick head -5 /home/node/CLAUDE.md
```

### K4. Summer(Codex@OrbStack Mac mini) — Code Review

**角色：** 收到 Rick 的 PR → 用 `wm4n.change-review-codex` skill 審查 → @Rick 回報結果。

**秘密檔**(`~/.openab-secret-summer.env`，chmod 600)：

```dotenv
DISCORD_BOT_TOKEN=你的_summer_discord_bot_token
GH_TOKEN_WM4N=github_pat_wm4n_個人_fine_grained
GH_TOKEN_CAC=github_pat_cac-william_公司_fine_grained
```

**Mac mini 主機 openab config**（`~/openab-summer/config.toml`，掛載為容器 `/etc/openab:ro`）：

```toml
[discord]
bot_token        = "${DISCORD_BOT_TOKEN}"
allowed_channels = ["頻道_ID"]
allowed_users    = ["你的_USER_ID"]
allow_bot_messages = "mentions"
trusted_bot_ids    = ["Rick_Bot_ID"]   # Rick 的 Discord User ID

[agent]
command     = "codex-acp"
args        = ["-c", "shell_environment_policy.inherit=all"]
working_dir = "/home/node"
inherit_env = []   # GitHub 走 gh 雙帳號(hosts.yml),不放 GH_TOKEN

[pool]
max_sessions      = 5
session_ttl_hours = 24
```

> ⚠️ `args` 的 `shell_environment_policy.inherit=all`：保留即可。GitHub 憑證已改走 gh 儲存的雙帳號(`~/.config/gh/hosts.yml`)、不靠 env,故此旗標對 GitHub 不再必要;但留著不影響其他 env 傳遞。

**Docker 啟動**（`--security-opt seccomp=unconfined` 必要，讓 bwrap 建 Linux namespace）：

```bash
docker -c orbstack run -d \
  --name openab-summer \
  --restart unless-stopped \
  --security-opt seccomp=unconfined \
  --env-file ~/.openab-secret-summer.env \
  -v openab-summer-home:/home/node \
  -v ~/openab-summer:/etc/openab:ro \
  ghcr.io/openabdev/openab-codex:latest
```

> ⚠️ `--security-opt seccomp=unconfined`：Docker 預設 seccomp profile 擋住 `clone`/`unshare` syscall，導致 bwrap 無法建 namespace，所有 shell 指令都 ❌。加這個旗標放行；Docker container 本身已是沙箱，不會有安全疑慮。驗證：`docker -c orbstack exec openab-summer unshare --user echo ok` 應回 `ok`。

> ⚠️ Rick 和 Summer **必須各用不同 volume**（`openab-rick-home` vs `openab-summer-home`），否則 AGENTS.md 和憑證會互蓋。

> ⚠️ `/home/node` 下所有檔案必須維持 `node:node` 擁有：進容器一律帶 `-u node`；**不要用 `docker cp` 塞檔案**（進去會變 root 擁有），一律用 heredoc（`docker exec -i -u node ... sh -c 'cat > 檔案'`）。agent（codex-acp/claude-agent-acp）以 node 執行，讀不到 root 擁有的 config/憑證會直接退出，Discord 端只看得到 `Connection Lost`。誤生 root 檔案的修復：`docker -c orbstack exec -u root <容器> chown -R node:node /home/node`。

**superpowers 安裝**（只需一次；安裝在 `/home/node` volume，重啟後持久）：

進入容器互動 session，透過 Codex 官方 plugin marketplace 安裝：

```bash
docker -c orbstack exec -it -u node openab-summer codex
```

進入 Codex session 後依序輸入 `/plugins` → `superpowers` → 選 Install Plugin，完成後 `/exit`。

**pipeline skill 安裝**（`wm4n.change-review-codex`；clone openab repo 後 symlink 進 codex-acp 掃描的 skill 目錄 `~/.codex/skills/`，同一份 checkout 也供下方 AGENTS.md 組合使用）：

```bash
docker -c orbstack exec -i -u node openab-summer sh -c '
  git clone https://github.com/<owner>/openab.git /home/node/github-repo/openab 2>/dev/null || git -C /home/node/github-repo/openab pull
  mkdir -p /home/node/.codex/skills
  ln -sfn /home/node/github-repo/openab/deployment-guides/bot-skills/change-review-codex /home/node/.codex/skills/wm4n.change-review-codex
  ln -sfn /home/node/github-repo/openab/deployment-guides/bot-skills/repo-identity          /home/node/.codex/skills/wm4n.repo-identity
  ls -la /home/node/.codex/skills/'   # wm4n.change-review-codex / wm4n.repo-identity symlink 都在
```

> `<owner>` 依 spec §7.2 rollout 決定（openab repo 來源）；rollout 時確認 Codex skill 掃描路徑是否真的是 `~/.codex/skills/`（尚未如 claude-agent-acp 那樣實測確認，見下方 ⚠️）。

> ⚠️ **Codex skill 未完整驗證 + embed 退路**：codex-acp 是否穩定掃描 `~/.codex/skills/` 尚未像 claude-agent-acp 那樣實測確認。部署後務必在 Discord 實測 Summer 是否真的載入 `wm4n.change-review-codex` skill；若找不到（Codex 不吃 filesystem skill），退回把 `change-review-codex` 的 SKILL.md 內文直接 embed 進 `Summer-AGENTS_v2.md`，再重新部署該完整 v2 檔，不依賴 filesystem skill 載入。

**gh 雙帳號登入**（`GH_TOKEN_WM4N/CAC` 由 `--env-file` 注入；bwrap 內 gh 用 hosts.yml，不需 env token）：

```bash
docker -c orbstack exec -i -u node openab-summer sh -c '
  echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token &&
  echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token &&
  gh auth setup-git'
docker -c orbstack exec -u node openab-summer gh auth status   # wm4n + cac-william 兩個
```

> 一次性登入用 `-i`（互動）讓 stdin 帶 token；`GH_TOKEN_WM4N/CAC` 由 `--env-file` 注入容器，故 exec 內可見。

**⚠️ Codex 內部 config**（`/home/node/.codex/config.toml`，存在 volume 持久化）：

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

> ⚠️ 三個 top-level key 缺一不可（openab issue #1047）：
> - `sandbox_mode = "danger-full-access"`：停用 bwrap 內層 sandbox，適合外層已有 Docker 隔離的場景。**必須 top-level，不能放在任何 section 內。**
> - `approvals_reviewer = "auto_review"`：bot 無人值守時自動核准工具呼叫；若設 `"user"` 會讓 tool call 掛住 30 分鐘。
> - `multi_agent = true`：啟用 subagent dispatch（`spawn_agent`/`wait_agent`）。

**AGENTS.md**：直接部署完整的 Summer v2 context 檔 `Summer-AGENTS_v2.md`。

```bash
docker -c orbstack exec -i -u node openab-summer sh -c '
  CK=/home/node/github-repo/openab/deployment-guides
  cp "$CK/Summer-AGENTS_v2.md" /home/node/AGENTS.md'
```

Summer persona 內指路的正式流程 skill：
- 收到 Rick 交棒的 PR URL/新 push，或人類明確要求正式 code review → `wm4n.change-review-codex` skill（內含觸發判斷、review 步驟、`<@ID>` 回報格式等細節，取代原本寫在 heredoc 裡的步驟 1-3）
- 其餘（問問題、看 code、討論、隨手幫忙）維持資深工程師模式，不 @ 其他 bot、不開流程
- 若 Codex 吃不到 filesystem skill（見上方 ⚠️ embed 退路），改把 `change-review-codex` 的 SKILL.md 內文直接寫進 `Summer-AGENTS_v2.md` 本文（取代「使用 wm4n.change-review-codex skill」這一句指路），再重新部署該完整 v2 檔

**驗證寫入**：

```bash
docker -c orbstack exec -u node openab-summer head -5 /home/node/AGENTS.md   # 應看到「Agent Summer 核心運行指南」
```

> ⚠️ 注意：Rick 在 openspec 流程中可能多次 @Summer，每次 @mention 都會觸發一個新 session。若 session 累積過多導致 Codex 初始化慢（超過 1800s hard timeout），可讓 Rick 只在**推 PR 後**才 @Summer 一次。

### K5. 端對端驗證順序

1. 三顆 bot 都 healthy
2. 在 #dev-bot @Morty 發 GitHub Issue URL → Morty 分析 → @Rick
3. Rick 執行 openspec → 推 PR → @Morty + @Summer
4. Morty 和 Summer 各自 review → @Rick 回報
5. Rick 通知人類：「兩位 reviewer 都 clean，可以 merge」
6. 人類手動 merge

---

## Part L — 定時排程（Cron / Usercron）

> openab **內建**排程，不需外部 cron。到點時把一句 prompt 當成「使用者輸入」丟給 agent，agent 跑完**回覆到指定 channel/thread**（＝定時執行任務 + 回報狀態）。權威文件見 repo 內 `docs/cronjob.md`、`docs/slash-commands.md`。

三種機制：

| 機制                            | 用途                     | 重複      | 誰管理排程       | 改了要重啟?                   |
| ------------------------------- | ------------------------ | --------- | ---------------- | ----------------------------- |
| `[[cron.jobs]]`（config.toml）  | 定時丟 prompt 給 agent   | ✅        | 手改 config      | 要（config 掛載/redeploy）    |
| **Usercron**（`cronjob.toml`）  | 同上，但**熱重載**       | ✅        | **agent 可自寫** | 不用（每分鐘偵測 mtime）      |
| `/remind`（slash command）      | 延遲後 @ 提醒某人        | ❌ 一次性 | 使用者           | —                             |

> 「定時執行任務並回報」用 **cron / usercron**；`/remind` 只到點 tag 人、**不會**叫 agent 做事。

### L1. 啟用 usercron（建議：熱重載 + agent 可自管）

在該 bot 的 config.toml 加一段（預設**關閉**，兩欄都要填才啟用）：

```toml
[cron]
usercron_enabled = true
usercron_path    = "cronjob.toml"   # 相對 $HOME/.openab/ → /home/node/.openab/cronjob.toml
```

- `cronjob.toml` 落在 `/home/node/.openab/`（持久化 volume，restart 不掉）。
- 加 `[cron]` 這步是改 config.toml → 要重啟一次：**Mac mini** 改 host config 後 `docker -c orbstack restart <容器>`；**Portainer** 改 Console/Stack config 後 redeploy。**之後改 `cronjob.toml` 本身不用 restart。**

### L2. 寫一個排程（`/home/node/.openab/cronjob.toml`）

容器內、user `node`、heredoc 寫入（**勿 `docker cp`**，會變 root 擁有）：

```bash
docker -c orbstack exec -i -u node openab-rick sh -c \
  'mkdir -p /home/node/.openab && cat > /home/node/.openab/cronjob.toml' <<'EOF'
[[jobs]]
schedule    = "0 9 * * 1-5"          # 5 欄位 POSIX cron（分 時 日 月 週）
channel     = "你的_channel_id"
message     = "總結昨天 merged 的 PR 並回報"
sender_name = "DailyOps"
timezone    = "Asia/Taipei"          # ⚠️ 預設 UTC，不設會差 8 小時
EOF
```

1 分鐘內生效，log 出現 `usercron file changed, reloading`。fire 時 agent 看到的是 `🕐 [DailyOps]: 總結昨天 merged 的 PR 並回報`。

### L3. agent 自管排程（手機也能排）

`cronjob.toml` 是純檔案，agent 有 Bash/檔案工具就能自己寫。直接對 bot 說：

```
你：幫我設一個每天早上 9 點總結 PR 的排程
bot：✅ 已寫入 cronjob.toml，1 分鐘內生效
```

### L4. 跑到目標達成就自停（goal-driven，適合催修 test/bug）

usercron 專屬 `disable_on_success`：每次 fire 前先跑檢查指令，**exit 0 且輸出含指定字串** → 回報 `✅ Goal achieved`、把該 job 寫回 `enabled = false`、跳過該次 prompt；否則照送 `message` 讓 agent 繼續。

```toml
[[jobs]]
id = "fix-unit-tests"                        # ⚠️ writeback 需要 id
schedule = "*/10 * * * *"
channel  = "你的_channel_id"
message  = "Unit tests 還是紅的，繼續修並回報進度"
disable_on_success = "npm test && echo OPENAB_GOAL_SUCCESS"
disable_on_success_match = "OPENAB_GOAL_SUCCESS"
disable_on_success_working_dir = "/home/node/<repo>"
```

> `disable_on_success` 只支援 usercron `[[jobs]]`，baseline `[[cron.jobs]]` 不支援。

### L5. 注意事項

- **長任務**：官方建議單次 >5 分鐘改用外部排程（K8s CronJob）；openspec 開發那種別排太密。
- **overlap 保護**：上一輪還在跑就跳過這輪（log：`skipping cronjob, previous execution still running`）。
- **每顆 bot 各自 config**：Rick/Summer/Morty 各排各的，cron 只 fire 進你設的 channel；跨 bot 接力仍靠 @mention。
- **bot 要在該 channel**：`channel` 指到的頻道要先邀 bot 進去，否則 `Channel not found`。
- **cron 週期限制**：day-of-week 別混用數字與名稱（`1,Mon` ❌）、別用繞回範圍（`5-2` ❌）。完整疑難排解見 `docs/cronjob.md`。

### L6. 三顆 bot 的啟用位置

| bot                       | 改 config 的位置                                                     | 寫 `cronjob.toml`                                        |
| ------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------- |
| **Rick**（OrbStack）      | 見 [K3](#k3-rickclaudeorbstack-mac-mini--openspec-開發) 註記（config 位置未定案）→ 改後 `restart` | `docker -c orbstack exec -i -u node openab-rick ...`     |
| **Summer**（OrbStack）    | host `~/openab-summer/config.toml`（掛 `/etc/openab:ro`）→ `restart` | `docker -c orbstack exec -i -u node openab-summer ...`   |
| **Morty**（Portainer）    | Console 改 `/home/node/config.toml`（或 Stack）→ redeploy            | Console heredoc 寫 `/home/node/.openab/cronjob.toml`     |

---

## Part M — 角色觸發（個人別名 / 團隊 mention）

> openab 的 `allowed_role_ids` 讓「@某個 Discord 角色」等同「@ 這隻 bot」。用來做**個人別名**（`@Developer` 也能叫動 Rick）或**團隊暱稱**（`@Team Alpha` 一次叫動整隊）。
>
> 觸發原理（`crates/openab-core/src/discord.rs:455`）：openab 比對「訊息 mention 到的角色 ID」對不對得上該 bot config 的 `allowed_role_ids`。所以 **bot 不需要真的被指派該角色**——只要 (a) 角色存在且**可被 @**、(b) 角色 ID 有寫進該 bot 的 `allowed_role_ids`。被 mention 的角色文字在丟給 agent 前會被剝掉，prompt 乾淨。
>
> ⚠️ openab **只認真正的 @mention**（user ID 或角色 ID），**不會**因為訊息裡出現某個名字的「文字」就觸發。純文字別名沒有這種功能。

### M1. 個人別名（`@Developer` → 只叫 Rick）

1. Discord 建角色 `Developer`，開「**允許任何人 @提及此角色**」（否則 @ 不出來）。
2. 取角色 ID（開發者模式 → 右鍵角色 → 複製角色 ID）。
3. 寫進 **Rick** 的 config.toml：
   ```toml
   [discord]
   allowed_role_ids = ["Developer_角色_ID"]
   ```
4. Rick restart / redeploy。

結果：`@Developer` 觸發 Rick，`@Rick` 本人照樣有效。

### M2. 團隊暱稱（`@Team Alpha` → 叫動整隊）

1. Discord 建角色 `Team Alpha`，同樣開「允許任何人 @提及」。
2. 取角色 ID。
3. **同一個角色 ID 寫進「每一隻」要入隊的 bot** 的 config.toml（`allowed_role_ids` 是清單，可與個人別名並列）：
   ```toml
   [discord]
   allowed_role_ids = ["TeamAlpha_角色_ID", "Developer_角色_ID"]   # Rick：團隊 + 個人別名
   ```
4. 每隻入隊的 bot 各自 restart / redeploy。

結果：`@Team Alpha` → 每隻入隊 bot **各開自己的 session、各回一則**（＝同時派工給整隊）。想讓誰入隊，就把角色 ID 加進誰的 config；不想要就別加。

### M3. 注意事項

- **角色必須可被 @**：Discord 角色設定要允許 @提及，否則使用者打不出這個 mention。
- **不用把角色指派給 bot**：openab 比對的是「被 mention 的角色 ID」，與 bot 有沒有這個角色無關。
- **別讓 bot 自己去 mention 團隊角色**：搭配 `allow_bot_messages = "mentions"/"all"` 會造成 bot 互相觸發的迴圈；人類手動 @Team Alpha 沒問題。
- **改 config 要重讀**：`allowed_role_ids` 在 config.toml，改完要 restart / redeploy（各 bot 的 config 位置見 [Part L L6](#l6-三顆-bot-的啟用位置) / Part K）。
- **多個團隊角色可並存**：`@Reviewers`、`@Team Alpha`… 各自的角色 ID 放進對應 bot 即可。

---

## Part N — 更新既有部署的 context 檔與 skill

> repo 的 persona（`*_v2.md`）或 pipeline skill 改版後，用這組步驟把變更推進已在跑的 bot。前提：容器內已 clone `/home/node/github-repo/openab`（見 Part K）、gh 已登入（私有 repo `git pull` 要認證）。
>
> 交付方式＝**v2 單檔版**：`git pull` 刷新 checkout（同時更新 v2 persona 與 skill 本體）→ 重新 `cat` v2 進 context 檔 → **開新 thread** 生效（context 檔與 skill 都在 session 啟動時載入，舊 thread 不會重讀，**不需** restart 容器）。

### N1. 更新指令（各 bot）

**Morty**（Portainer Console，user `node`）：

```bash
cd /home/node/github-repo/openab
git fetch origin docs/three-bot-pipeline && git checkout docs/three-bot-pipeline && git pull
cat deployment-guides/Morty-CLAUDE_v2.md > /home/node/CLAUDE.md
head -1 /home/node/CLAUDE.md      # 確認：# CLAUDE.md — Agent Morty 核心運行指南
```

**Rick**（Mac mini）：

```bash
docker -c orbstack exec -i -u node openab-rick sh -c '
  cd /home/node/github-repo/openab &&
  git fetch origin docs/three-bot-pipeline &&
  git checkout docs/three-bot-pipeline && git pull &&
  cat deployment-guides/Rick-CLAUDE_v2.md > /home/node/CLAUDE.md &&
  head -1 /home/node/CLAUDE.md'
```

**Summer**（Mac mini；目標檔是 `AGENTS.md`）：

```bash
docker -c orbstack exec -i -u node openab-summer sh -c '
  cd /home/node/github-repo/openab &&
  git fetch origin docs/three-bot-pipeline &&
  git checkout docs/three-bot-pipeline && git pull &&
  cat deployment-guides/Summer-AGENTS_v2.md > /home/node/AGENTS.md &&
  head -1 /home/node/AGENTS.md'
```

### N2. 生效與相依項

- **開新 thread**：在 Discord 開一條新 thread 才會重讀 context 檔與 skill；舊 thread 維持舊脈絡。
- **skill symlink**：`git pull` 只更新 checkout 內容；`~/.claude/skills/wm4n.*`（Summer 為 `~/.codex/skills/`）的 symlink 指向 checkout，內容自動跟著新。但**新增**的 skill 目錄要**補建 symlink**（見 Part K）——pull 不會自動建。
- **角色 handoff 相依**：若這次更新改了 skill 的 handoff 目標（如改 @角色），對應 Discord 角色要已建好且填進各 bot `allowed_role_ids`（見 Part M），否則 handoff 沒有 bot 接。
- **rollout 驗證**：對照 `bot-skills/ROLLOUT-CHECKLIST.md` 做端對端實測。

---

## Part O — 遷移到 k3s

> 把三隻 bot 從 Mac mini(OrbStack) / Portainer 搬到單節點 k3s 的**完整步驟另見 [`K3S.md`](K3S.md)**。
>
> 策略摘要：官方 `charts/openab` Helm chart 當骨架，分兩個 release（`openab-claude`：Rick+Morty，RuntimeDefault；`openab-codex`：Summer，seccomp Unconfined），同一 namespace `cac`（團隊共用 namespace）。Discord token 走 K8s Secret、Morty JIRA 走 secretEnv、**GitHub 雙帳號與 context/skill 沿用 `kubectl exec` bootstrap**（＝ Part E/F/K/N 的 k8s 版）。cutover 用 sleep 隔離 bootstrap 達近零停機。
>
> values 檔在 `k3s/`；設計依據見 `docs/superpowers/specs/2026-07-20-k3s-migration-design.md`、實作計畫見 `docs/superpowers/plans/2026-07-20-k3s-migration.md`。

---

## 維運

| 動作     | 指令                                                                                     |
| -------- | ---------------------------------------------------------------------------------------- |
| 看狀態   | `docker -c orbstack ps`                                                                  |
| 看 log   | `docker -c orbstack logs -f openab-claude`                                               |
| 重啟     | `docker -c orbstack restart openab-claude`                                               |
| 進容器   | `docker -c orbstack exec -it -u node openab-claude bash`                                 |
| 更新映像 | `docker -c orbstack pull ghcr.io/openabdev/openab-claude:latest` → `rm -f` → 重跑 Part D |

**改設定的規則(重要):**

- 只改 `config.toml`(含 `inherit_env`)→ `docker -c orbstack restart openab-claude` 即可(config 是掛載的)。
- 改 `~/.openab-secrets.env`(新增/換 token)→ **執行中容器無法改 env**,必須 `docker -c orbstack rm -f openab-claude` 後**重跑 Part D**。

**Token 輪替/撤銷:**

- 換 token:更新 `~/.openab-secrets.env` → `rm -f` + 重跑。
- 換某帳號 token:更新 `~/.openab-secret-*.env` 對應的 `GH_TOKEN_WM4N`/`GH_TOKEN_CAC` → `rm -f` 重建容器 → 重跑該容器的 gh 雙帳號登入(Part F / K)。
- 出事止血:到 GitHub 刪掉該 token,或把 machine user 踢出 repo collaborator。

---

## 安全須知(務必讀)

**把兩把 token 登入 gh、每任務 `gh auth switch`,不是「安全」,是「方便」。** 只要 agent 能跑 Bash,它就讀得到憑證(token 不進 env,但 `cat ~/.config/gh/hosts.yml` 仍讀得到),你無法對它藏。所以:

> **假設這把 token 一定會被洩漏或濫用(prompt injection:惡意指令可藏在 Discord 訊息、repo 內容、issue、README),確保損害小且可逆。**

安全靠這四點,不靠存哪:

1. **專用 machine user**(不要本人帳號)。
2. **最小權限**:fine-grained 釘死 repo + 只給 Contents/PR;classic 則拿掉 `workflow`。
3. **設過期 + 可秒收回**(刪 token / 踢 collaborator)。
4. **當作一定會被注入** → 所以前三點才是安全網。

想要更高一級(agent 連原始密鑰都摸不到):**GitHub App + 短效 installation token**、或**宿主機憑證代理(auth proxy)**、或唯讀單 repo **deploy key**。POC 用這套(gh 雙帳號)即可;正式給團隊建議升級到 GitHub App。

---

## 疑難排解

| 症狀                                                                                               | 原因                                                                               | 解法                                                                                               |
| -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **手動 `docker exec` clone/push 成功、但叫 bot 失敗**                                              | bot 忘了先 `gh auth switch` 選帳號,或該帳號沒登入 gh                               | 確認 context 檔有「選帳號」開場(Part F2);`gh auth status` 確認兩帳號都在                           |
| `failed to read /etc/openab/config.toml: Is a directory`                                           | run 時來源檔不存在,Docker 自動把來源建成目錄,**colima 還會快取**這個目錄           | 改**掛目錄** `-v ~/oab:/etc/openab:ro`,並用**沒被污染過的新路徑**;OrbStack(VirtioFS)幾乎不會中這雷 |
| agent 起不來 / 不回應,log 顯示 command 問題                                                        | `command` 設成裸 `claude`(不講 ACP)                                                | config 設 `command = "claude-agent-acp"`                                                           |
| `gh auth status` 顯示登入,但 `git clone` 仍要帳密                                                  | 沒設 git 的 credential helper                                                      | `gh auth setup-git`(Part F)                                                                        |
| org 私有 repo clone 不到(classic PAT)                                                              | org 強制 SAML SSO,token 未授權                                                     | 到該 token 頁 **Configure SSO → Authorize**                                                        |
| `orb restart` 說 OrbStack is not running,但 `orb version` 有反應                                   | `orb version` 只印 CLI 版本;當前 docker engine 其實是 colima                       | `docker context show` 確認;openab 一律 `-c orbstack`                                               |
| 改了 token 沒生效                                                                                  | 執行中容器無法改 env                                                               | `rm -f` 後重跑 Part D                                                                              |
| **restart 後 `gh auth status` 變空 / `hosts.yml` 不見**                                            | 登入時是 root(寫到 `/root`)、`/home/node` 沒持久化、或 env 還有裸 `GH_TOKEN` 蓋掉 | 以 **node** 重登;確認 `/home/node` 掛 volume(`ls ~/.claude` 還在);移除裸 `GH_TOKEN`;常 restart 用 [Part F3](#part-f3--雙身份-rollout-清單) 開機自動重登 |
| (Portainer)Console 用 `node` 進不去:`unable to find user node: no matching entries in passwd file` | build 到錯的 Dockerfile(基礎 `Dockerfile` 是 `agent` 使用者,非 Claude 版的 `node`) | 用官方 `openab-claude:latest`;或自 build 時把根 `Dockerfile` 換成 `Dockerfile.claude`(見 Part I)   |
| (Portainer)容器一直 unhealthy                                                                      | sleep 待命階段沒有 openab process(healthcheck 抓 `pgrep openab`)                   | 正常;完成 Part I3 切回 `openab run` 後即 healthy                                                   |
| **[Codex]** Summer 所有 shell 指令 ❌（`pwd`、`git`、`gh` 全部失敗，log 顯示 `unshare failed: Operation not permitted`） | Docker 預設 seccomp profile 擋住 `clone`/`unshare` syscall，bwrap 無法建立 Linux user namespace | 重建容器加 `--security-opt seccomp=unconfined`（見 K4）。驗證：`docker -c orbstack exec openab-summer unshare --user echo ok` |
| **[Codex]**(僅用 env-based fallback 時)`gh` 指令 ❌、直接 `docker exec` 沒問題                    | fallback 把 token 放 env 時,codex-acp 預設不把 env 傳入 bwrap sandbox shell        | `config.toml` `[agent]` 加 `args = ["-c", "shell_environment_policy.inherit=all"]` → restart。主線走 gh 雙帳號(hosts.yml)不受此影響 |
| **push 403 或 commit author 錯**                                                                   | 切錯帳號或忘了切(wm4n repo 用到 cac-william、反之亦然)                             | 開工前 `gh auth switch --user <對的帳號>` + per-repo 設 local 署名(Part F2)                         |
| **`gh auth login`/`switch` 拒絕、說 GH_TOKEN 環境變數存在**                                       | env 有裸 `GH_TOKEN`                                                                | 改用 `GH_TOKEN_WM4N`/`GH_TOKEN_CAC`,別設裸 `GH_TOKEN`                                              |
| **[Codex]** 在 openab config `args` 加 `--dangerously-bypass-approvals-and-sandbox` 導致 Connection Lost | `codex-acp` 是獨立 binary，不接受標準 `codex` CLI 的此 flag | 改用 `sandbox_mode = "danger-full-access"` 寫進容器 `~/.codex/config.toml`（top-level）        |
| **[Codex]** `sandbox_permissions = ["network-full-access"]` 加了沒效果                              | `sandbox_permissions` 不是 `codex-acp` 合法的 config key（會被 silently ignore）   | 同上，用 `sandbox_mode = "danger-full-access"`（參見 openab issue #1047）                          |

---

## 附錄:完整範例檔

### `~/.openab-secrets.env`(chmod 600,放在 `~/oab` 之外)

```dotenv
DISCORD_BOT_TOKEN=你的_discord_bot_token
GH_TOKEN_WM4N=github_pat_wm4n_個人_fine_grained     # 釘死要給 bot 碰的 wm4n repo
GH_TOKEN_CAC=github_pat_cac-william_公司_fine_grained # 釘死要碰的 104corp/… repo
```

### `~/oab/config.toml`

```toml
[discord]
bot_token        = "${DISCORD_BOT_TOKEN}"
allowed_channels = ["你的_CHANNEL_ID"]
allowed_users    = ["你的_USER_ID"]

[agent]
command     = "claude-agent-acp"
args        = []
working_dir = "/home/node"
# GitHub token 不走 env:兩帳號登入 gh、任務內 gh auth switch 選帳號(見 Part F2)。
# inherit_env 只放非 GitHub 的 secret(此基本版無;Morty 版見 Part K2 保留 JIRA_*)。

[pool]
max_sessions      = 5
session_ttl_hours = 24
```

### 啟動指令

```bash
docker -c orbstack run -d \
  --name openab-claude \
  --restart unless-stopped \
  --env-file ~/.openab-secrets.env \
  -v openab-claude-home:/home/node \
  -v ~/oab:/etc/openab:ro \
  ghcr.io/openabdev/openab-claude:latest
```
