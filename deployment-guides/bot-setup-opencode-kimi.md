# openab Kimi Bot 部署(opencode + OpenRouter,與其他 bot 並存)

> 在 Mac mini(`CAC@2771`,OrbStack)上再跑一顆 **專用 Kimi** bot:後端用 **opencode**,
> 模型走 **OpenRouter** 的 `moonshotai/kimi-k3`(2.8T 參數,1M context,reasoning + agentic)。
> 與現有 Claude / Codex bot 並存 —— 新的 Discord Application + 新 token + 獨立容器/config/volume。
> 共用觀念 / 安全須知 / 維運見 [`BOT_SETUP.md`](./BOT_SETUP.md);這裡只列可直接照做的步驟 1–9。
>
> ⚠️ 只放 placeholder,**絕不寫入真實 token / API key**。秘密一律放 `~/.openab-kimi-secrets.env`(chmod 600)。
> ⚠️ `kimi-k3` 是 $3 / $15 每 1M tokens(約 k2.7-code 的 4 倍),OpenRouter 後台記得設 credit limit。

**為什麼是 opencode**:openab 自己不呼叫 LLM,是把對話透過 ACP 丟給 agent CLI。
opencode 原生支援 [75+ provider](https://opencode.ai/docs/providers/)(含 OpenRouter),
「換模型」只要 `opencode auth login` + 改一行全域 `opencode.jsonc`,不用改 openab 或寫 code。

| 項目 | Claude bot | 本 Kimi bot |
|---|---|---|
| 映像 | `openab-claude:latest` | `openab-opencode:latest` |
| `[agent].command` | `claude-agent-acp` | `opencode`(args `["acp"]`) |
| LLM 來源 | Anthropic 訂閱 | **OpenRouter API key** |
| 預設模型 | `claude-*` | `openrouter/moonshotai/kimi-k3` |
| 登入 | `claude auth login`(OAuth) | `opencode auth login`(貼 OpenRouter key) |
| 憑證位置 | `/home/node/.claude` | `/home/node/.local/share/opencode/auth.json` |
| 模型設定檔 | —(靠 CLI) | `~/.config/opencode/opencode.jsonc`(全域;ACP 只讀這份) |
| 脈絡檔 | `CLAUDE.md` | `AGENTS.md` |
| 工具授權 | 逐項確認 | 全自動(等同 `--trust-all-tools`,opencode 內部處理) |

---

## 步驟 1 — 建「新的」Discord bot

<https://discord.com/developers/applications> → **New Application**(例:`Kimi Dev`)→ **Bot** 分頁 → **Reset Token** 拿 token(**跟 Claude / Codex bot 那幾把都不同**)。

- 開 **MESSAGE CONTENT INTENT**;用 **OAuth2 → URL Generator**(scope `bot`,權限:View Channels / Send Messages / Read Message History / Create Public Threads / Send Messages in Threads)邀進伺服器。
- ⚠️ 給 Kimi bot **另開一個頻道**,拿新的 Channel ID。與別的 bot 共用頻道會多隻同時回。

## 步驟 2 — 取得 OpenRouter API key

<https://openrouter.ai/keys> → **Create Key**,拿 `sk-or-v1-...`。

- 建議在 OpenRouter 後台幫這把 key 設**用量上限**(Credit limit),避免爆量。
- 這把 key **不進 config.toml、也不進 env-file**(見步驟 5 說明),只在步驟 6 用 `opencode auth login` 貼一次,存進容器 volume。

## 步驟 3 — 秘密檔(獨立一份)

```bash
:> ~/.openab-kimi-secrets.env
chmod 600 ~/.openab-kimi-secrets.env
```

編輯 `~/.openab-kimi-secrets.env`(`GH_TOKEN` 可沿用你原本那把):

```dotenv
DISCORD_BOT_TOKEN=你的_Kimi_bot_的_token
GH_TOKEN=github_pat_你原本那把
```

## 步驟 4 — config(獨立目錄 `~/oab-kimi`)

```bash
mkdir -p ~/oab-kimi
```

`~/oab-kimi/config.toml`:

```toml
[discord]
bot_token        = "${DISCORD_BOT_TOKEN}"
allowed_channels = ["Kimi_bot_專用的_CHANNEL_ID"]
allowed_users    = ["你的_USER_ID"]

[agent]
command     = "opencode"           # ★ Claude 是 claude-agent-acp;Codex 是 codex-acp
args        = ["acp"]
working_dir = "/home/node"
inherit_env = ["GH_TOKEN"]         # 放行 GH_TOKEN 給 agent(GitHub 用)

[pool]
max_sessions      = 3
session_ttl_hours = 24
```

> `[agent]` 其實可省略 —— `Dockerfile.opencode` 已設 `OPENAB_AGENT_COMMAND="opencode acp"`。
> 這裡寫明確是為了可讀性 + 掛 `inherit_env`。

## 步驟 5 — 啟動容器(獨立名稱/volume/映像)

```bash
docker -c orbstack run -d \
  --name openab-kimi \
  --restart unless-stopped \
  --env-file ~/.openab-kimi-secrets.env \
  -v openab-kimi-home:/home/node \
  -v ~/oab-kimi:/etc/openab:ro \
  ghcr.io/openabdev/openab-opencode:latest

docker -c orbstack ps                # 看到 openab-kimi Up (healthy)
docker -c orbstack logs openab-kimi  # 看到 Discord 連上
```

> **為什麼 OpenRouter key 不走 env**:`config.toml.example` 的安全註記明講 ——
> `[agent].env` 或 `inherit_env` 裡的值,agent 讀得到,可能被 prompt injection 騙出來。
> opencode 支援 `opencode auth login` 把 key 存進 `auth.json`(volume 內,重啟不掉),
> agent 進程本身讀不到裸 key,比 `OPENROUTER_API_KEY` env 安全。

## 步驟 6 — 登入 OpenRouter(貼 key)

opencode 憑證放 `~/.local/share/opencode/auth.json`,目錄要先存在:

```bash
docker -c orbstack exec -u node openab-kimi mkdir -p /home/node/.local/share/opencode
```

互動式登入,選 **OpenRouter**,貼上步驟 2 的 `sk-or-v1-...`:

```bash
docker -c orbstack exec -it -u node openab-kimi opencode auth login
```

驗證:

```bash
docker -c orbstack exec -u node openab-kimi opencode auth list
docker -c orbstack exec -u node openab-kimi cat /home/node/.local/share/opencode/auth.json
# 應看到含 "openrouter" 的 JSON
```

## 步驟 7 — 設定預設模型(全域 `opencode.jsonc`)

⚠️ opencode 的 `acp` server 模式**只讀全域 config `~/.config/opencode/opencode.jsonc`**,
**不讀** working_dir 的 `opencode.json`(project config)。model 一定要寫全域這份 ——
否則 bot 會落回 opencode 內建 fallback(k3s 上實測會變成 `google/gemini-3-pro-image-preview`,
不支援 tool use,bot 完全不回話)。`~/.config/opencode/` 在 volume 上,重啟不掉。

```bash
docker -c orbstack exec -i -u node openab-kimi sh -c 'mkdir -p /home/node/.config/opencode && cat > /home/node/.config/opencode/opencode.jsonc' <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "model": "openrouter/moonshotai/kimi-k3"
}
EOF

# 若之前照舊版說明建過 project config，清掉 —— 它會蓋過全域這份
docker -c orbstack exec -u node openab-kimi rm -f /home/node/opencode.json

docker -c orbstack restart openab-kimi
```

驗證模型抓得到:

```bash
docker -c orbstack exec -u node openab-kimi opencode models | grep -i kimi
```

### 可選模型(OpenRouter,單價為每 1M tokens,2026-09 查詢)

| `opencode.jsonc` 的 `model` | in | out | 備註 |
|---|---|---|---|
| `openrouter/moonshotai/kimi-k3` | $3.00 | $15.00 | **本 bot 預設**;2.8T 參數,1M context,reasoning + agentic;最貴 |
| `openrouter/moonshotai/kimi-k2.7-code` | $0.71 | $3.50 | coding 取向,reasoning;CP 值比 k3 高很多 |
| `openrouter/moonshotai/kimi-k2.5` | $0.45 | $2.25 | reasoning 型 |
| `openrouter/moonshotai/kimi-k2-0905` | $0.60 | $2.50 | **非 reasoning、tool 強**,最穩,想避開 ACP reasoning 雷選這個 |
| `openrouter/moonshotai/kimi-k2` | $0.57 | $2.30 | 最便宜,非 reasoning |

> 換模型只要改 `~/.config/opencode/opencode.jsonc` 再 `docker -c orbstack restart openab-kimi`。

## 步驟 8 —(選)工作脈絡檔:opencode 用 `AGENTS.md`

context 檔的正式來源是 repo 裡的 [`Kimi-AGENTS_v2.md`](./Kimi-AGENTS_v2.md)(與 k3s 版共用同一份)。
Docker 版沒有 ConfigMap,直接 clone repo 後 `cat` 進容器:

```bash
docker -c orbstack exec -i -u node openab-kimi sh -c '
  set -e
  D=/home/node/github-repo/openab
  git clone https://github.com/wm4n/openab.git "$D" 2>/dev/null || (cd "$D" && git pull)
  cat "$D/deployment-guides/Kimi-AGENTS_v2.md" > /home/node/AGENTS.md
  head -3 /home/node/AGENTS.md
'
```

> opencode 在 session 開始時讀 working_dir 的 `AGENTS.md`;改完在 Discord **開新 thread** 才會重讀。
> 要改內容改 `Kimi-AGENTS_v2.md`、push,再重跑上面這段(k3s 版則跑 `update-context.sh`)。

## 步驟 9 — 端對端驗證

1. `docker -c orbstack ps` → `openab-kimi` Up (healthy)。
2. `docker -c orbstack logs openab-kimi` → Discord 連上。
3. `docker -c orbstack exec -u node openab-kimi opencode models | grep -i kimi` → 有列出。
4. 條件 clone:
   ```bash
   docker -c orbstack exec -u node openab-kimi \
     git clone https://github.com/OWNER/REPO.git /tmp/verify && echo CLONE_OK
   ```
5. 在 Kimi 專用頻道 @它:`clone <你的 repo> 並列出檔案`,確認能動 + 回中文。

全部過 → 部署完成 ✅

---

## 提醒

- **映像版本地板(Critical)**:`kimi-k3` 是 **reasoning 模型**。OpenRouter reasoning 模型在 opencode
  `< 1.17.3` 有 ACP 回傳 bug(內部存好 assistant text 卻不發 `agent_message_chunk`),bot 顯示
  `(no response)`。`Dockerfile.opencode` 目前 pin `opencode-ai@1.17.9`,k3s 上實測 pod 是 `1.17.3`
  (達標)。**別把映像降到 1.17.3 以下**。想完全避開這個雷就用非 reasoning 的 `kimi-k2-0905`。
- **`parallel_tool_calls`**:`kimi-k3` 是 `false`(`kimi-k2.7-code` 是 `true`)。目前實測 opencode 照跑
  沒事,工具呼叫異常時可往這邊查。
- **成本**:`kimi-k3` $3 / $15 每 1M tokens,約 `kimi-k2.7-code`($0.71 / $3.50)的 4 倍。務必在
  OpenRouter 後台設 credit limit。
- **拿不到 usage meter**:ACP 路共通限制,Discord 不會顯示額度 / 花費。用量請去 OpenRouter 後台看。
- **工具全自動**:opencode 內部處理工具授權,等同 `--trust-all-tools`,不會有逐步確認。
  要靠容器隔離當邊界(非 privileged container)。
- **維運**(看 log / 重啟 / 換映像):比照 `BOT_SETUP.md` 的「維運」章,容器名換 `openab-kimi`、映像換 `openab-opencode:latest`。
- **換 OpenRouter key**:重跑步驟 6 的 `opencode auth login` 覆蓋即可,再 `docker -c orbstack restart openab-kimi`。

---

## 附錄 A — k3s Helm values 版本

k3s 的操作骨架見 [`K3S.md`](./K3S.md) 的「未來加 agent」章;這裡只列 Kimi bot 的差異。
Helm values 工件在 [`k3s/`](./k3s/):`values-openab-kimi.yaml`(agent overlay)、`values-secret-kimi.example.yaml`(Discord token)。

**放哪個 release**:opencode 只需 `RuntimeDefault` seccomp(跟 Rick/Morty 同一家,不像 Codex 要 Unconfined),
所以照 K3S.md「未來加 agent」的做法**併進既有 `openab-claude` release**,不用另開 release。
部署名會是 `openab-claude-kimi`。

### A1. Discord Application

同步驟 1(新 Application + token + 專屬頻道 + 開 MESSAGE CONTENT INTENT + 記 bot user ID)。

### A2. 靜態 PV(`cac-local` 不會自動長 PV,要手動建)

```bash
mkdir -p /data/william/openab/agent-kimi
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: pv-cac-kimi
spec:
  capacity:
    storage: 20Gi                 # 跟 values 的 persistence.size 一致
  accessModes: ["ReadWriteOnce"]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: cac-local
  local:
    path: /data/william/openab/agent-kimi
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values: ["openab"]
  claimRef:
    namespace: cac
    name: openab-claude-kimi       # <release>-<agentKey>
EOF
```

### A3. 填秘密檔

```bash
cd deployment-guides/k3s
cp values-secret-kimi.example.yaml values-secret-kimi.yaml
# 編輯填入 Kimi bot 的 Discord bot token
```

`values-openab-kimi.yaml` 內的 `agents.kimi.discord.allowedChannels` 也要換成 Kimi 專用頻道 ID(字串引號)。

### A4. `helm upgrade`(加進既有 release,不是 install)

```bash
cd deployment-guides/k3s
helm upgrade openab-claude ../../charts/openab -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml \
  -f values-openab-kimi.yaml   -f values-secret-kimi.yaml
```

> chart 對每個 agent 各算自己的 `checksum/config`,這次只新增 `agents.kimi`,Rick/Morty 的 Deployment 不會變、不會被連帶重啟(K3S.md 已實測)。
> 先驗證:`helm template openab-claude ../../charts/openab -f values-openab-claude.yaml -f values-openab-kimi.yaml --set agents.rick.discord.botToken=x --set agents.morty.discord.botToken=y --set agents.kimi.discord.botToken=z | grep -E 'command|inherit_env|working_dir|opencode'`

### A5. Bootstrap(只跑在新 pod `openab-claude-kimi`)

```bash
POD=$(kubectl -n cac get pod -l app.kubernetes.io/instance=openab-claude -o name | grep kimi)

# 1) opencode 憑證目錄
kubectl -n cac exec -it "$POD" -- mkdir -p /home/node/.local/share/opencode

# 2) 登入 OpenRouter(選 OpenRouter,貼 sk-or-v1-...)—— key 存進 PVC,不進 pod env
kubectl -n cac exec -it "$POD" -- opencode auth login
kubectl -n cac exec "$POD" -- opencode auth list

# 3) 預設模型寫進「全域」config —— opencode 的 ACP server 只讀這份，
#    不讀 /home/node/opencode.json（project config）。寫錯地方 bot 會落回
#    內建 fallback（實測變成 google/gemini-3-pro-image-preview，不回話）。
kubectl -n cac exec "$POD" -- mkdir -p /home/node/.config/opencode
kubectl -n cac exec -i "$POD" -- sh -c 'cat > /home/node/.config/opencode/opencode.jsonc' <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "model": "openrouter/moonshotai/kimi-k3"
}
EOF

# 3b) 清掉 project config —— 舊版說明曾建 /home/node/opencode.json，它會「蓋過」
#     全域 config（`opencode run` from /home/node 會讀到它），造成換模型改了全域
#     卻沒生效。沒有就跳過。
kubectl -n cac exec "$POD" -- rm -f /home/node/opencode.json

# 4) gh 登入(單帳號即可,除非這隻要跨 wm4n / 104corp)
kubectl -n cac exec -it "$POD" -- gh auth login --hostname github.com
kubectl -n cac exec "$POD" -- gh auth setup-git

# 5) context 檔:跟 Rick/Morty/Summer/Genie 同一套 —— 跑 update-context.sh
#    （會 clone/pull openab repo 進 pod,cat deployment-guides/Kimi-AGENTS_v2.md
#    > /home/node/AGENTS.md）。前提:values-openab-kimi.yaml 沒設 agentsMd。
bash update-context.sh        # 或只跑 Kimi 那隻:見腳本 BOTS 陣列

# 6) 重啟讓 opencode 重讀設定
kubectl -n cac rollout restart deploy/openab-claude-kimi -n cac
```

> **context 檔不走 `agentsMd`**:`values-openab-kimi.yaml` 刻意不設 `agentsMd`,`/home/node/AGENTS.md`
> 由 `update-context.sh`（來源 `deployment-guides/Kimi-AGENTS_v2.md`）寫進 PVC,跟其他四隻一致、可被
> `update-context.sh` 一次更新。設了 `agentsMd` 會掛成唯讀 ConfigMap,`update-context.sh` 的
> `cat > AGENTS.md` 會 `Read-only file system` 而 `set -e` 中止。
> **skill 暫不接**(opencode 用 `~/.claude/skills/` 目錄,非 `claude plugin`;之後再處理,見正文「opencode 的 skill」段)。

### A6. 驗證

```bash
kubectl -n cac get pod -l app.kubernetes.io/instance=openab-claude | grep kimi   # Running
kubectl -n cac logs deploy/openab-claude-kimi | tail                            # discord 連上
kubectl -n cac exec deploy/openab-claude-kimi -- opencode models | grep -i kimi
```

在 Kimi 專用頻道 @它派工,確認能動 + 回中文。

### 差異對照(Docker 版 → k3s 版)

| 項目 | Docker(本文正文) | k3s(本附錄) |
|---|---|---|
| 部署單位 | `docker run --name openab-kimi` | 併進 `openab-claude` release,pod `openab-claude-kimi` |
| 映像指定 | `ghcr.io/openabdev/openab-opencode:latest` | `agents.kimi.image`(**不要**用 top-level `image:`,會蓋 Rick/Morty) |
| 持久化 | docker volume `openab-kimi-home` | 靜態 PV `pv-cac-kimi` + PVC `openab-claude-kimi` |
| config.toml | `~/oab-kimi/config.toml` 手寫 | chart 由 `values-openab-kimi.yaml` 生成 |
| OpenRouter key | `opencode auth login`(volume) | 同左(PVC);或 `secretEnv` 注入 `OPENROUTER_API_KEY`(宣告式,但 key 進 agent env) |
| model 設定 | `docker exec` 寫 `~/.config/opencode/opencode.jsonc` | `kubectl exec` 寫 `~/.config/opencode/opencode.jsonc`(PVC) —— ACP 只讀全域這份,不讀 project `opencode.json` |
| `AGENTS.md` | `docker exec` 寫檔(正文步驟 8) | `update-context.sh`(來源 `Kimi-AGENTS_v2.md`,寫進 PVC);**不設 `agentsMd`** |
| skill | 暫不接 | 暫不接(opencode 走 `~/.claude/skills/` 目錄,非 `claude plugin`) |

---

## 附錄 C — 其他 opencode bot(Wall-E / Eve)

跟 Kimi **完全同一套**(opencode + OpenRouter,併進 `openab-claude` release)。差別只有下表這幾格,
其餘照附錄 A 逐步做即可。

| 項目 | Kimi | **Wall-E** | **Eve** |
|---|---|---|---|
| agent key | `kimi` | `walle` | `eve` |
| deployment / pod | `openab-claude-kimi` | `openab-claude-walle` | `openab-claude-eve` |
| values overlay | `values-openab-kimi.yaml` | `values-openab-walle.yaml` | `values-openab-eve.yaml` |
| secret 範本 | `values-secret-kimi.example.yaml` | `values-secret-walle.example.yaml` | `values-secret-eve.example.yaml` |
| persona 源檔 | `Kimi-AGENTS_v2.md` | `Walle-AGENTS_v2.md` | `Eve-AGENTS_v2.md` |
| 靜態 PV / claimRef | `pv-cac-kimi` / `openab-claude-kimi` | `pv-cac-walle` / `openab-claude-walle` | `pv-cac-eve` / `openab-claude-eve` |
| 全域 `opencode.jsonc` 的 `model` | `openrouter/moonshotai/kimi-k3` | `openrouter/deepseek/deepseek-v4-pro-0813` | `openrouter/z-ai/glm-5.2` |
| Discord Application / token | 各自新建 | 各自新建 | 各自新建 |
| Discord 頻道 | 沿用同 3 個 channel ID | 同左 | 同左 |
| GitHub 帳號 | 單帳號 | 單帳號 `104cac`(PAT 登入) | 單帳號 `104cac`(PAT 登入) |
| OpenRouter key | — | **與 Kimi 共用同一把**(bootstrap `opencode auth login` 貼同一組) | 同左 |
| `update-context.sh` BOTS | 已含 | 已含(`Wall-E:openab-claude-walle:Walle-AGENTS_v2.md:AGENTS.md`) | 已含(`Eve:openab-claude-eve:Eve-AGENTS_v2.md:AGENTS.md`) |

### 一次上兩隻

```bash
cd deployment-guides/k3s
cp values-secret-walle.example.yaml values-secret-walle.yaml   # 填各自的 Discord token
cp values-secret-eve.example.yaml   values-secret-eve.yaml

# 靜態 PV（各一顆，claimRef 精準指定；容量對齊 values 的 persistence.size = 20Gi）
for n in walle eve; do
  mkdir -p /data/william/openab/agent-$n
  kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: pv-cac-$n
spec:
  capacity: { storage: 20Gi }
  accessModes: ["ReadWriteOnce"]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: cac-local
  local: { path: /data/william/openab/agent-$n }
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - { key: kubernetes.io/hostname, operator: In, values: ["openab"] }
  claimRef: { namespace: cac, name: openab-claude-$n }
EOF
done

helm upgrade openab-claude ../../charts/openab -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml \
  -f values-openab-kimi.yaml   -f values-secret-kimi.yaml \
  -f values-openab-walle.yaml  -f values-secret-walle.yaml \
  -f values-openab-eve.yaml    -f values-secret-eve.yaml
```

### 每隻各跑一次 bootstrap（比照附錄 A5，換 POD / model）

```bash
for n in walle eve; do
  POD=$(kubectl -n cac get pod -l app.kubernetes.io/instance=openab-claude -o name | grep "$n")
  case "$n" in
    walle) MODEL=openrouter/deepseek/deepseek-v4-pro-0813 ;;
    eve)   MODEL=openrouter/z-ai/glm-5.2 ;;
  esac

  kubectl -n cac exec "$POD" -- mkdir -p /home/node/.local/share/opencode /home/node/.config/opencode
  kubectl -n cac exec -it "$POD" -- opencode auth login          # 選 OpenRouter，貼「與 Kimi 同一把」sk-or-v1-...
  kubectl -n cac exec -i "$POD" -- sh -c "cat > /home/node/.config/opencode/opencode.jsonc" <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "model": "$MODEL"
}
EOF
  kubectl -n cac exec "$POD" -- rm -f /home/node/opencode.json   # 清掉會蓋過全域的 project config
  kubectl -n cac exec -it "$POD" -- gh auth login --hostname github.com   # 104cac PAT
  kubectl -n cac exec "$POD" -- gh auth setup-git
done

bash update-context.sh   # 會把 Walle-/Eve-AGENTS_v2.md 寫進各自 pod 的 /home/node/AGENTS.md
kubectl -n cac rollout restart deploy/openab-claude-walle deploy/openab-claude-eve -n cac
```

### 驗證

```bash
for n in walle eve; do
  echo "--- $n ---"
  kubectl -n cac get pod -l app.kubernetes.io/instance=openab-claude | grep "$n"
  kubectl -n cac exec "deploy/openab-claude-$n" -- sh -lc 'cd /home/node && opencode run "你用哪個 model？一句話"'
done
```

Wall-E 頻道 @它 → 應 `> build · deepseek/deepseek-v4-pro-0813`；Eve → `> build · z-ai/glm-5.2`。都回中文即完成。

### 注意

- `deepseek-v4-pro-0813` 與 `glm-5.2` 都是 **reasoning 模型** → 一樣要 opencode ≥ 1.17.3（image 已達標，別降版）。
- `glm-5.2` 的 `parallel_tool_calls` 支援;`deepseek-v4-pro-0813` 不支援（實測 opencode 照跑，工具呼叫異常時往這查）。
- 三隻共用一把 OpenRouter key → OpenRouter 後台看不出是哪隻花的，只能看 model 分佈。要分開記帳就得各給一把 key。
