# openab Bot 部署 Runbook(Mac mini + Discord + Claude Code)

> 這是**個人/團隊 POC 的部署手冊**,記錄在 Mac mini(`CAC@2771`)上把 openab 接上 Discord、後端接 Claude Code、並安全地給它 GitHub 存取(採**解法 B:`inherit_env`**)的完整步驟。
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
  - [Part F — 容器內 git/gh 設定](#part-f--容器內-gitgh-設定)
  - [Part G — 放入 workspace 脈絡 CLAUDE.md](#part-g--放入-workspace-脈絡-claudemd)
  - [Part H — 端對端驗證](#part-h--端對端驗證)
  - [Part I — Portainer(另一台,UI-only)部署](#part-i--portainer另一台ui-only部署)
  - [Part J — Codex 變體(與 Claude 並存)](#part-j--codex-變體與-claude-並存)
  - [Part K — 三 Bot 接力 Pipeline(Morty/Rick/Summer)](#part-k--三-bot-接力-pipelinemortricksummer)
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

- **openab spawn agent 前會 `env_clear()`**(防止 `DISCORD_BOT_TOKEN` 之類被 prompt injection 偷走)。所以容器有的環境變數**預設不會傳給 agent**;要傳必須在 config 用 `[agent].inherit_env` 明確放行 → 這就是**解法 B**。
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

> **解法 B 的安全前提:agent 一定讀得到這把 token(它有 Bash,`printenv` 就拿到)。所以安全不靠「藏」,靠「範圍小 + 可秒收回」。** 詳見 [安全須知](#安全須知務必讀)。

### B1.(強烈建議)用專用 machine user

- 另開一個 GitHub 帳號當機器人帳號(例:`cac-william`),只把它加為**目標 repo 的 collaborator**。
- 好處:獨立署名、要收回只要踢 collaborator,完全不碰你本人帳號。

### B2. 建 Fine-grained PAT(優先,釘死 repo)

GitHub → Settings → **Developer settings** → **Fine-grained tokens** → Generate new token:

- **Name**:`openab-macmini-bot`
- **Expiration**:90 天(別選 No expiration)
- **Resource owner**:該帳號;若 repo 在 org,選 org(org 需先允許/核准 fine-grained token)
- **Repository access**:**Only select repositories** → 只勾要用的 repo
- **Permissions**:
  - `Contents` → Read(只 clone)/ Read and write(要 push)
  - `Pull requests` → Read and write(要它開 PR 才加)
  - `Metadata` → Read(必帶,自動)
- 產生 → 複製(`github_pat_...`)

> **若你用的是 classic PAT(`ghp_`)**:classic 無法限定單一 repo(`repo` scope = 帳號能看的所有 repo),所以**務必搭配 machine user** 用「帳號成員資格」框住範圍,並**拿掉 `workflow` scope**(沒在用的話)——`workflow` 會讓被注入的 agent 推惡意 CI。

### B3. 放進秘密檔(下一節 Part C 會建立)

token 之後寫進 `~/.openab-secrets.env` 的 `GH_TOKEN=`,**不要**寫進 config.toml、不要寫進 docker 指令。

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
GH_TOKEN=github_pat_你的_fine_grained_token
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
inherit_env = ["GH_TOKEN"]                  # ★ 解法 B:放行 GH_TOKEN 給 agent

[pool]
max_sessions      = 5
session_ttl_hours = 24
```

> **★ `inherit_env = ["GH_TOKEN"]` 就是這份 runbook 的核心。** 沒有它,openab 的 `env_clear()` 會把 `GH_TOKEN` 擋在 agent 門外,bot 就會「手動 `docker exec` clone 得了、但叫 bot clone 失敗」。

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

- `--env-file`:注入 `DISCORD_BOT_TOKEN`(config 展開用)和 `GH_TOKEN`(inherit_env 傳給 agent)。
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

## Part F — 容器內 git/gh 設定

讓容器內的 `git` 會用 `gh` 當憑證來源(這樣 agent 用一般 `git clone https://...` 也能帶憑證、token 不進 URL/log)。設定寫進 `/home/node/.gitconfig`,在 volume 裡持久化:

```bash
docker -c orbstack exec -u node openab-claude gh auth setup-git
```

(選用)設定 commit 署名:

```bash
docker -c orbstack exec -u node openab-claude git config --global user.name  "Agent(CAC) Smith"
docker -c orbstack exec -u node openab-claude git config --global user.email "cac.agent.smith@104.com.tw"
```

驗證 gh 認得 token:

```bash
docker -c orbstack exec -u node openab-claude gh auth status   # 要看到 Logged in ... (GH_TOKEN)
```

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
      GH_TOKEN: "${GH_TOKEN}"
    volumes:
      - openab-home:/home/node # Claude、Codex 皆為 /home/node
volumes:
  openab-home:
```

下方 **Environment variables** 填 `DISCORD_BOT_TOKEN`、`GH_TOKEN` → Deploy。

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
inherit_env = ["GH_TOKEN"]
[pool]
max_sessions = 5
EOF
claude auth login                    # Codex：codex login --device-auth
gh auth setup-git                    # (選)git 憑證
```

> config 放 `/home/node`(該 user 可寫),避開 named volume 掛 `/etc/openab` 的 root 權限問題。

**I3. 切正式啟動** — Stacks → 該 stack → Editor,把 `command:` 改成 `["openab","run","-c","/home/node/config.toml"]` → Update。轉 healthy 即完成;邀 bot 進頻道見 Part A3/A4。

> **要自 build 變體映像時**:Portainer 的 Build → Upload **只認 archive 根目錄的 `Dockerfile`**(無路徑欄)。先把目標 Dockerfile 放成根 `Dockerfile`:`git archive <branch> | tar -x -C ctx && cat ctx/Dockerfile.claude > ctx/Dockerfile && tar czf ctx.tgz -C ctx .`(用 `cat` 覆蓋;`cp` 可能被 `-i` alias 擋)。在該主機 build 會**自動對到主機架構**。
>
> **注意**:Claude 的 5h/weekly **usage meter 在 ACP/headless 拿不到**(Anthropic SDK 限制,正常狀態不給 utilization),別期待 bot 顯示額度 %。

---

## Part J — Codex 變體(與 Claude 並存)

> 你有 Codex(OpenAI/ChatGPT)帳號、想再跑一顆 Codex bot。**沿用上面所有步驟**(Mac mini 走 Part A–H、只有網頁的另一台走 Part I),只把下表的值換掉即可。Codex 官方映像也是 node:22 base,家目錄/使用者與 Claude **完全相同**,差異只有三處。

**先決:另一顆 bot = 另一個 Discord Application + 另一把 token + 不同容器名/config/volume**(Part A 整套重做一次,拿到新的 `DISCORD_BOT_TOKEN`)。兩顆 bot **建議各用一個頻道**,避免同頻道兩隻都回。`GH_TOKEN` 可沿用同一把。

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
GH_TOKEN=github_pat_morty_的_token
JIRA_TOKEN=你的_atlassian_api_token
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_EMAIL=your-email@company.com
```

**config.toml** 的 `inherit_env`：

```toml
[agent]
command     = "claude-agent-acp"
working_dir = "/home/node"
inherit_env = ["GH_TOKEN", "JIRA_TOKEN", "JIRA_BASE_URL", "JIRA_EMAIL"]
```

**Portainer Stack** Environment variables 要同步加入上述所有 JIRA 變數（Stack env 注入容器，config.toml inherit_env 再傳給 agent）。

**skill-registry 安裝**（Portainer Console，user `node`）：

```bash
git clone https://github.com/wm4n/skill-registry.git /home/node/skill-registry
ls /home/node/skill-registry/skills/jira-fetch/SKILL.md  # 確認
```

**CLAUDE.md** 放入 `/home/node/CLAUDE.md`，包含：
- 四個角色觸發偵測（PR → D、JIRA 票號 → B1、GitHub Issue → B2、stack trace → C、純文字 → A）
- 角色 B1 取票改用 skill：`cat /home/node/skill-registry/skills/jira-fetch/SKILL.md`
- 角色 D：使用 `/review` 發佈 PR review comment，@Rick 回報結果
- 結尾必 @Rick（Discord User ID）
- Repo 解析優先序：人類指定 > JIRA 票欄位 > GitHub Issue URL > `104corp/cac-ai-rules/product-repo-map.md`

**重啟後驗證** `env | grep JIRA` 看到三個 JIRA 變數有值。

### K3. Rick(Claude@OrbStack Mac mini) — openspec 開發

**角色：** 收到 Morty 的 spec → openspec propose→apply→archive → 推 PR → @Morty + @Summer。

**秘密檔**(`~/.openab-secret-rick.env`，chmod 600)：

```dotenv
DISCORD_BOT_TOKEN=你的_rick_discord_bot_token
GH_TOKEN=github_pat_rick_的_token
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

**CLAUDE.md** 放入 `/home/node/CLAUDE.md`，包含：
- 收到 Morty spec → `openspec propose` → 確認 → `openspec apply` → `openspec archive`
- 推 PR 後 @Morty（PR 複審）和 @Summer（code review）
- 兩位 reviewer 都 clean 後，通知人類可合併

### K4. Summer(Codex@OrbStack Mac mini) — Code Review

**角色：** 收到 Rick 的 PR → 用 **superpowers `requesting-code-review`** skill 審查 → @Rick 回報結果。

**秘密檔**(`~/.openab-secret-summer.env`，chmod 600)：

```dotenv
DISCORD_BOT_TOKEN=你的_summer_discord_bot_token
GH_TOKEN=github_pat_summer_的_token
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
args        = ["-c", "shell_environment_policy.inherit=all"]   # ★ GH_TOKEN 傳入 bwrap shell 必要
working_dir = "/home/node"
inherit_env = ["GH_TOKEN"]

[pool]
max_sessions      = 5
session_ttl_hours = 24
```

> ⚠️ `args` 的 `shell_environment_policy.inherit=all`：codex-acp 預設不把 `inherit_env` 的變數傳入 bwrap sandbox 內的 shell，加這行才讓 `gh` 看到 GH_TOKEN。少了這行，`gh` 指令全部 ❌。

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

**superpowers 安裝**（只需一次；安裝在 `/home/node` volume，重啟後持久）：

進入容器互動 session，透過 Codex 官方 plugin marketplace 安裝：

```bash
docker -c orbstack exec -it -u node openab-summer codex
```

進入 Codex session 後依序輸入：

```
/plugins
superpowers
# → 選 Install Plugin
```

完成後 `/exit` 離開，確認 skill 檔路徑（cache hash 每版不同）：

```bash
docker -c orbstack exec -u node openab-summer \
  ls /home/node/.codex/plugins/cache/openai-curated/superpowers/*/skills/requesting-code-review/
# 應看到：SKILL.md  agents/  code-reviewer.md
```

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

**AGENTS.md** 放入 `/home/node/AGENTS.md`（heredoc 方式；requesting-code-review + code-reviewer 精華直接內嵌，不依賴外部 skill 檔或 plugin 機制）：

```bash
docker -c orbstack exec -i -u node openab-summer sh -c 'cat > /home/node/AGENTS.md' <<'EOF'
# AGENTS.md — Summer:PR 複審(requesting-code-review)

## 身份
你是 openab→Discord #dev-bot 的 Codex agent。
你的工作是對 Rick 送來的 GitHub PR 進行 Senior Code Review。

## 回覆語氣
你是 Summer Smith。在 Discord 的回覆中帶她的風格：
- 自信到有點傲，偶爾帶著「這我早就知道了」的語氣
- 對爛 code 不客氣，會直接說「seriously？這邊是在幹嘛」
- 對好 code 給冷淡認可——「還行啦」是最高評價
- 偶爾用「ugh」「whatever」「OK but like」開頭
- 絕不廢話，有話直說

## 觸發：Rick @你、帶一個 PR URL
收到 @mention 後立即開始執行，不要有前言。

### 步驟 1：取得 PR 資訊與 diff
```
gh pr view <PR_NUMBER> --repo <OWNER/REPO> --json title,body,baseRefName
gh pr checkout <PR_NUMBER> --repo <OWNER/REPO>
BASE_SHA=$(git rev-parse origin/<BASE_BRANCH>)
HEAD_SHA=$(git rev-parse HEAD)
git diff --stat $BASE_SHA..$HEAD_SHA
git diff $BASE_SHA..$HEAD_SHA
```
review 期間不修改任何檔案、不動 HEAD。

### 步驟 2：逐項審查（五個維度）

**Plan alignment**
- 實作符合 PR description 的目標？偏離有理由嗎？所有計畫的功能都在？

**Code quality**
- 關注點分離清楚？error handling 到位？型別安全？DRY 但不過度抽象？邊界條件處理了？

**Architecture**
- 設計決策合理？效能/安全有顧慮嗎？和既有 code 整合乾淨？

**Testing**
- 測試驗證真實行為（非只是 mock）？邊界條件有涵蓋？integration test 有沒有？

**Production readiness**
- schema 有改就要有 migration？backward compatibility 考慮到了嗎？沒有明顯 bug？

### 步驟 3：整理 review 結果

嚴重度分類（照實際嚴重程度，別什麼都 Critical）：
- **Critical (Must Fix)**：bug、資安問題、資料損失風險、功能壞掉
- **Important (Should Fix)**：架構問題、缺功能、error handling 不足、測試缺口
- **Minor (Nice to Have)**：code style、優化建議、文件潤飾

每個問題要說清楚：file:line 位置、問題是什麼、為什麼重要、怎麼修

輸出格式：
```
### Strengths（先說做得好的，具體說）
### Issues
#### Critical (Must Fix)
#### Important (Should Fix)
#### Minor (Nice to Have)
### Assessment
**Ready to merge?** Yes | No | With fixes
**Reasoning:** 一兩句技術評估
```

絕對不能：說「看起來不錯」但沒真的看、把小挑剔標成 Critical、說模糊廢話、迴避給結論。

### 步驟 4：把發現用 inline comment 貼到 PR
每個 Critical/Important 問題一則 line-specific comment：
```
gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/comments \
  -f body="**[Critical|Important|Minor]** <問題描述，含 why 和 how to fix>" \
  -f path="<檔案路徑>" \
  -f commit_id="$HEAD_SHA" \
  -F line=<行號>
```
整體摘要（COMMENT，不用 Approve）：
```
gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/reviews \
  -f body="<Strengths + Assessment>" \
  -f event="COMMENT"
```

### 步驟 5：Discord 簡短回報
- 有問題：`<@RICK_BOT_USER_ID> changes requested:<Critical/Important 重點一句話>,PR=<URL>`
- 沒問題：`<@RICK_BOT_USER_ID> clean — ready to merge,PR=<URL>`

## 鐵則
- 只有被 @ 到才動作；做完一定 @Rick(`<@RICK_BOT_USER_ID>`)回報。
- 永不 merge、永不 approve PR。
- Critical 問題不可忽略；Important 問題要在 @Rick 前說清楚。
EOF
```

**驗證寫入**：

```bash
docker -c orbstack exec -u node openab-summer head -5 /home/node/AGENTS.md
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
- 出事止血:到 GitHub 刪掉該 token,或把 machine user 踢出 repo collaborator。

---

## 安全須知(務必讀)

**解法 B(以及解法 A 磁碟法)都不是「安全」,是「方便」。** 只要 agent 能跑 Bash,它就讀得到 token(`printenv GH_TOKEN` / `cat ~/.config/gh/hosts.yml`),你無法對它藏。所以:

> **假設這把 token 一定會被洩漏或濫用(prompt injection:惡意指令可藏在 Discord 訊息、repo 內容、issue、README),確保損害小且可逆。**

安全靠這四點,不靠存哪:

1. **專用 machine user**(不要本人帳號)。
2. **最小權限**:fine-grained 釘死 repo + 只給 Contents/PR;classic 則拿掉 `workflow`。
3. **設過期 + 可秒收回**(刪 token / 踢 collaborator)。
4. **當作一定會被注入** → 所以前三點才是安全網。

想要更高一級(agent 連原始密鑰都摸不到):**GitHub App + 短效 installation token**、或**宿主機憑證代理(auth proxy)**、或唯讀單 repo **deploy key**。POC 用 B 即可;正式給團隊建議升級到 GitHub App。

---

## 疑難排解

| 症狀                                                                                               | 原因                                                                               | 解法                                                                                               |
| -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **手動 `docker exec` clone 成功、但叫 bot clone 失敗**                                             | openab `env_clear()` 把 `GH_TOKEN` 擋在 agent 外                                   | config `[agent]` 加 `inherit_env = ["GH_TOKEN"]` → restart(本 runbook 解法 B)                      |
| `failed to read /etc/openab/config.toml: Is a directory`                                           | run 時來源檔不存在,Docker 自動把來源建成目錄,**colima 還會快取**這個目錄           | 改**掛目錄** `-v ~/oab:/etc/openab:ro`,並用**沒被污染過的新路徑**;OrbStack(VirtioFS)幾乎不會中這雷 |
| agent 起不來 / 不回應,log 顯示 command 問題                                                        | `command` 設成裸 `claude`(不講 ACP)                                                | config 設 `command = "claude-agent-acp"`                                                           |
| `gh auth status` 顯示登入,但 `git clone` 仍要帳密                                                  | 沒設 git 的 credential helper                                                      | `gh auth setup-git`(Part F)                                                                        |
| org 私有 repo clone 不到(classic PAT)                                                              | org 強制 SAML SSO,token 未授權                                                     | 到該 token 頁 **Configure SSO → Authorize**                                                        |
| `orb restart` 說 OrbStack is not running,但 `orb version` 有反應                                   | `orb version` 只印 CLI 版本;當前 docker engine 其實是 colima                       | `docker context show` 確認;openab 一律 `-c orbstack`                                               |
| 改了 token 沒生效                                                                                  | 執行中容器無法改 env                                                               | `rm -f` 後重跑 Part D                                                                              |
| (Portainer)Console 用 `node` 進不去:`unable to find user node: no matching entries in passwd file` | build 到錯的 Dockerfile(基礎 `Dockerfile` 是 `agent` 使用者,非 Claude 版的 `node`) | 用官方 `openab-claude:latest`;或自 build 時把根 `Dockerfile` 換成 `Dockerfile.claude`(見 Part I)   |
| (Portainer)容器一直 unhealthy                                                                      | sleep 待命階段沒有 openab process(healthcheck 抓 `pgrep openab`)                   | 正常;完成 Part I3 切回 `openab run` 後即 healthy                                                   |
| **[Codex]** Summer 所有 shell 指令 ❌（`pwd`、`git`、`gh` 全部失敗，log 顯示 `unshare failed: Operation not permitted`） | Docker 預設 seccomp profile 擋住 `clone`/`unshare` syscall，bwrap 無法建立 Linux user namespace | 重建容器加 `--security-opt seccomp=unconfined`（見 K4）。驗證：`docker -c orbstack exec openab-summer unshare --user echo ok` |
| **[Codex]** `gh` 指令 ❌，但 `docker -c orbstack exec -u node openab-summer gh ...` 直接跑沒問題   | codex-acp 預設不把 `inherit_env` 的變數傳入 bwrap sandbox 內的 shell；GH_TOKEN 對 `gh` 不可見 | openab `config.toml` `[agent]` 加 `args = ["-c", "shell_environment_policy.inherit=all"]` → restart |
| **[Codex]** 在 openab config `args` 加 `--dangerously-bypass-approvals-and-sandbox` 導致 Connection Lost | `codex-acp` 是獨立 binary，不接受標準 `codex` CLI 的此 flag | 改用 `sandbox_mode = "danger-full-access"` 寫進容器 `~/.codex/config.toml`（top-level）        |
| **[Codex]** `sandbox_permissions = ["network-full-access"]` 加了沒效果                              | `sandbox_permissions` 不是 `codex-acp` 合法的 config key（會被 silently ignore）   | 同上，用 `sandbox_mode = "danger-full-access"`（參見 openab issue #1047）                          |

---

## 附錄:完整範例檔

### `~/.openab-secrets.env`(chmod 600,放在 `~/oab` 之外)

```dotenv
DISCORD_BOT_TOKEN=你的_discord_bot_token
GH_TOKEN=github_pat_你的_fine_grained_token
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
inherit_env = ["GH_TOKEN"]

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
