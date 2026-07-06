# openab Codex Bot 部署(Mac mini,與 Claude bot 並存)

> 在 Mac mini(`CAC@2771`,OrbStack)上再跑一顆 **Codex** bot,與現有 Claude bot 並存。
> 共用觀念/安全須知/維運見 [`BOT_SETUP.md`](./BOT_SETUP.md);這裡只列可直接照做的步驟 1–8。
>
> ⚠️ 只放 placeholder,**絕不寫入真實 token**。秘密一律放 `~/.openab-codex-secrets.env`(chmod 600)。

**核心:這是「另一顆 bot」** —— 新的 Discord Application + 新 token + 獨立容器/config/volume。
跟 Claude 版真正不同的只有 3 個:**映像**、**agent 指令**、**登入方式**。家目錄/使用者相同(皆 node:22 base → `/home/node` / `node`)。

| 項目 | Claude | Codex |
|---|---|---|
| 映像 | `openab-claude:latest` | `openab-codex:latest` |
| `[agent].command` | `claude-agent-acp` | `codex-acp` |
| 登入 | `claude auth login` | `codex login --device-auth` |
| 憑證位置 | `/home/node/.claude` | `/home/node/.codex` |
| 脈絡檔 | `CLAUDE.md` | `AGENTS.md` |

---

## 步驟 1 — 建「新的」Discord bot
<https://discord.com/developers/applications> → **New Application**(例:`Codex Dev`)→ **Bot** 分頁 → **Reset Token** 拿 token(**跟 Claude bot 那把不同**)。
- 開 **MESSAGE CONTENT INTENT**;用 **OAuth2 → URL Generator**(scope `bot`,權限:View Channels / Send Messages / Read Message History / Create Public Threads / Send Messages in Threads)邀進伺服器。
- ⚠️ 給 Codex bot **另開一個頻道**,拿新的 Channel ID。與 Claude 共用頻道會兩隻同時回。

## 步驟 2 — 秘密檔(獨立一份)
```bash
:> ~/.openab-codex-secrets.env
chmod 600 ~/.openab-codex-secrets.env
```
編輯 `~/.openab-codex-secrets.env`(`GH_TOKEN` 可沿用 Claude 那把):
```dotenv
DISCORD_BOT_TOKEN=你的_Codex_bot_的_token
GH_TOKEN=github_pat_你原本那把
```

## 步驟 3 — config(獨立目錄 `~/oab-codex`)
```bash
mkdir -p ~/oab-codex
```
`~/oab-codex/config.toml`:
```toml
[discord]
bot_token        = "${DISCORD_BOT_TOKEN}"
allowed_channels = ["Codex_bot_專用的_CHANNEL_ID"]
allowed_users    = ["你的_USER_ID"]

[agent]
command     = "codex-acp"          # ★ Claude 是 claude-agent-acp
args        = []
working_dir = "/home/node"
inherit_env = ["GH_TOKEN"]         # 解法 B:放行 GH_TOKEN 給 agent

[pool]
max_sessions      = 5
session_ttl_hours = 24
```

## 步驟 4 — 啟動容器(獨立名稱/volume/映像)
```bash
docker -c orbstack run -d \
  --name openab-codex \
  --restart unless-stopped \
  --env-file ~/.openab-codex-secrets.env \
  -v openab-codex-home:/home/node \
  -v ~/oab-codex:/etc/openab:ro \
  ghcr.io/openabdev/openab-codex:latest

docker -c orbstack ps                  # 看到 openab-codex Up
docker -c orbstack logs openab-codex   # 看到 Discord 連上
```

## 步驟 5 — 登入 Codex(裝置碼流程)
```bash
docker -c orbstack exec -it openab-codex codex login --device-auth
```
畫面給一組 **URL + code** → 在你電腦瀏覽器打開、用 **Codex(OpenAI/ChatGPT)帳號**授權。完成後:
```bash
docker -c orbstack restart openab-codex
docker -c orbstack exec -u node openab-codex ls -la /home/node/.codex   # 確認憑證落地
```

## 步驟 6 — git/gh 設定
```bash
docker -c orbstack exec -u node openab-codex gh auth setup-git
docker -c orbstack exec -u node openab-codex gh auth status   # 看到 Logged in ... (GH_TOKEN)
```

## 步驟 7 —(選)工作脈絡檔:Codex 用 `AGENTS.md`
```bash
docker -c orbstack exec -i -u node openab-codex sh -c 'cat > /home/node/AGENTS.md' <<'EOF'
# AGENTS.md — openab Codex @ Mac mini

## 你是誰 / 在哪
- 你是透過 openab 橋接到 Discord 的 Codex agent,跑在 Mac mini 的 Docker 容器(OrbStack)。
- 使用者在 Discord @你 派工;每個 thread 對應一個 session。

## 溝通語言
- 一律使用繁體中文(台灣正體)回覆。

## 工作目錄與持久化
- 工作目錄(= $HOME):/home/node,掛在 docker volume,容器重啟不會掉。
- Codex 憑證在 /home/node/.codex;GitHub 憑證在 /home/node/.config/gh。

## 可用工具
- git、gh、node 22、npm、rg(ripgrep)。

## 目前狀態
- 要開始工作時,把目標 repo git clone 到 /home/node/<repo> 底下再進行。
EOF
```
> 改完後在 Discord **開新 thread** 才會重讀。

## 步驟 8 — 端對端驗證
1. `docker -c orbstack ps` → `openab-codex` Up (healthy)。
2. `docker -c orbstack logs openab-codex` → Discord 連上、帳號正確。
3. 模擬 agent 條件 clone:
   ```bash
   docker -c orbstack exec -u node openab-codex \
     git clone https://github.com/OWNER/REPO.git /tmp/verify && echo CLONE_OK
   ```
4. 在 Codex 專用頻道 @它:`clone <你的 repo> 並列出檔案`,確認能動。

全部過 → 部署完成 ✅

---

## 提醒
- Claude bot 不受影響:不同容器、volume、token,並存無虞。
- Codex 一樣**拿不到 usage meter**(ACP 路共通限制),別期待顯示額度。
- 維運(看 log / 重啟 / 換 token / 更新映像)比照 `BOT_SETUP.md` 的「維運」章,容器名換成 `openab-codex`、映像換成 `openab-codex:latest`。
