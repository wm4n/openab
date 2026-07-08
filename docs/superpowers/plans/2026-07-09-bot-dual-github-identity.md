# 三 Bot 雙 GitHub 身份 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓現有三顆 bot（Morty/Rick/Summer）依目標 repo 的 owner 自動切換 GitHub 身份（token + 署名），支援個人 `wm4n` 與公司 `cac-william` 兩帳號。

**Architecture:** 文件變更，不含程式碼。改寫 `deployment-guides/` 下的部署 runbook 與三個 bot context 模板：把「單一 `GH_TOKEN` 走 `inherit_env`（解法 B）」的主敘事，換成「兩帳號登入 gh、每個任務用 `gh auth switch` 選帳號、per-repo 設 local 署名」。三個 standalone 模板是 source of truth；`BOT_SETUP.md` Part K 的內嵌 heredoc 必須與其逐字同步。

**Tech Stack:** Markdown、`gh` CLI（≥2.40，多帳號 `auth switch`）、`git`、Docker（OrbStack / Portainer）、openab config.toml。

## Global Constraints

- 全程繁體中文（台灣正體）。
- `deployment-guides/BOT_SETUP.md` 是「只放 placeholder、絕不寫真實 token」的 runbook；內容中的 `<...>` 尖括號值是**刻意保留的部署時填入項**，不是待辦缺口。
- gh CLI 需 ≥ 2.40（多帳號 `gh auth switch`）；rollout 時確認映像內版本。
- 每次改 `BOT_SETUP.md` 內嵌 heredoc，**必須與對應 standalone 模板逐字一致**（bot-setup-md-sync 慣例）。驗證用全文 diff，不可只用關鍵字抽查（教訓 E002）。
- commit 訊息用 `docs(...)` 型別，結尾附：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- 分支：`docs/three-bot-pipeline`（現有分支，不另開）。

### 共用內容 A：「選帳號」開場區塊（三個模板與三個 heredoc 都貼這段，逐字一致）

```markdown
## 開工前：依 repo owner 選 GitHub 身份（每個任務必做，先於任何 git/gh 操作）

1. 從任務確定目標 `owner/repo`。
2. 依 owner 決定帳號並記住對應署名：

   | owner | 帳號 | git user.name | git user.email |
   | --- | --- | --- | --- |
   | `wm4n` | `wm4n`（個人） | `wm4n` | `<你的 wm4n GitHub 個人 email>` |
   | `104corp` / `openabdev` / 其餘一律 | `cac-william`（公司） | `Agent(CAC) Smith` | `cac.agent.smith@104.com.tw` |
   | 無法判斷 | —— 問人類，別猜 | | |

3. 切換身份（`gh` 與 `git push` 都會跟著這個帳號走）：
   `gh auth switch --hostname github.com --user <wm4n 或 cac-william>`
4. clone 完該 repo 後，對它設 **local** 署名（不要用 --global）：
   `git -C <repo> config user.name "<上表 name>"` 、 `git -C <repo> config user.email "<上表 email>"`

鐵則：絕不把 `gh auth status`、`~/.config/gh/hosts.yml`、`git remote -v` 的內容貼進 Discord（含 token，會進聊天記錄）。
```

> `<你的 wm4n GitHub 個人 email>` 是部署時由使用者填入的個人 email（本 repo 內不寫死）。

---

## Task 1：三個 standalone 模板加「選帳號」開場（source of truth）

**Files:**
- Modify: `deployment-guides/Rick-CLAUDE.md`（在「## 身份」段之後、「## 每次開始前」之前插入共用內容 A）
- Modify: `deployment-guides/Summer-AGENTS.md`（在「## 身份」段之後、「## 觸發」之前插入共用內容 A）
- Modify: `deployment-guides/Morty-CLAUDE.md`（在「## 身份」段之後、「## 觸發偵測」之前插入共用內容 A；並改「## Repo 解析優先序」第 4 步加 personal 分支）

**Interfaces:**
- Produces: 三個模板頂部的「選帳號」區塊文字（= 共用內容 A，逐字），供 Task 3 的 heredoc 同步比對。

- [ ] **Step 1：Rick-CLAUDE.md 插入共用內容 A**

在 `## 身份` 段落結束後、`## 每次開始前` 前，插入共用內容 A 全文。

- [ ] **Step 2：Summer-AGENTS.md 插入共用內容 A**

在 `## 身份` 段落結束後、`## 觸發：Rick @你` 前，插入共用內容 A 全文。

- [ ] **Step 3：Morty-CLAUDE.md 插入共用內容 A**

在 `## 身份` 段落結束後、`## 觸發偵測` 前，插入共用內容 A 全文。

- [ ] **Step 4：Morty-CLAUDE.md 改 Repo 解析優先序第 4 步（personal 分支）**

把目前這段（`deployment-guides/Morty-CLAUDE.md`，約 144-147 行）：

```markdown
4. 以上都無 → 讀產品對照表：
   `gh api repos/104corp/cac-ai-rules/contents/product-repo-map.md --jq '.content' | base64 -d`
   從對照表依 JIRA project key（如 CACJOB）或產品名稱找對應 repo
5. 對照表也查不到 → 問人類：「這個任務對應哪個 repo？」
```

改成：

```markdown
4. 以上都無：
   - 若已知是**個人（wm4n）**任務 → 不查公司對照表，直接問人類：「這個 wm4n 任務對應哪個 repo？」
   - 否則（公司任務）→ 先 `gh auth switch --hostname github.com --user cac-william`，再讀產品對照表：
     `gh api repos/104corp/cac-ai-rules/contents/product-repo-map.md --jq '.content' | base64 -d`
     從對照表依 JIRA project key（如 CACJOB）或產品名稱找對應 repo
5. 對照表也查不到 → 問人類：「這個任務對應哪個 repo？」
```

- [ ] **Step 5：驗證三個模板都有選帳號區塊、Morty 有 personal 分支**

Run:
```bash
grep -c "開工前：依 repo owner 選 GitHub 身份" deployment-guides/Rick-CLAUDE.md deployment-guides/Summer-AGENTS.md deployment-guides/Morty-CLAUDE.md
grep -n "gh auth switch --hostname github.com --user <wm4n 或 cac-william>" deployment-guides/Rick-CLAUDE.md deployment-guides/Summer-AGENTS.md deployment-guides/Morty-CLAUDE.md
grep -n "若已知是\*\*個人（wm4n）\*\*任務" deployment-guides/Morty-CLAUDE.md
```
Expected: 前一條每檔都 `1`；中間一條三檔各一行；最後一條 Morty 命中一行。

- [ ] **Step 6：Commit**

```bash
git add deployment-guides/Rick-CLAUDE.md deployment-guides/Summer-AGENTS.md deployment-guides/Morty-CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(bots): 三個模板加「依 owner 選 GitHub 身份」開場 + Morty 個人任務略過公司對照表

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2：BOT_SETUP.md 主敘事改寫（token / gh / 機制骨幹 + 附錄）

把 runbook 從「解法 B：`inherit_env` `GH_TOKEN`」改寫成「gh 雙帳號 + `gh auth switch`」。

**Files:**
- Modify: `deployment-guides/BOT_SETUP.md`（L3 副標、L73 關鍵觀念、Part B、Part C1/C2、Part D 說明、Part F 重寫、新增 Part F2、附錄 dotenv/config）

**Interfaces:**
- Produces: 新的 `## Part F2 — 多帳號身份切換` 小節（Task 3 的疑難排解、Part K 註解會引用它）；`GH_TOKEN_WM4N` / `GH_TOKEN_CAC` 命名慣例。

- [ ] **Step 1：改 L3 副標**

把：
```markdown
並安全地給它 GitHub 存取(採**解法 B:`inherit_env`**)的完整步驟。
```
改成：
```markdown
並安全地給它 GitHub 存取(採 **gh 雙帳號 + `gh auth switch`**,同時服務 wm4n/cac-william 兩身份)的完整步驟。
```

- [ ] **Step 2：改 L73 關鍵觀念 bullet**

把：
```markdown
- **openab spawn agent 前會 `env_clear()`**(防止 `DISCORD_BOT_TOKEN` 之類被 prompt injection 偷走)。所以容器有的環境變數**預設不會傳給 agent**;要傳必須在 config 用 `[agent].inherit_env` 明確放行 → 這就是**解法 B**。
```
改成：
```markdown
- **openab spawn agent 前會 `env_clear()`**(防止 `DISCORD_BOT_TOKEN` 之類被 prompt injection 偷走)。容器環境變數**預設不會傳給 agent**;要傳才在 `[agent].inherit_env` 放行。
- **GitHub 憑證不走 env**:改把 `wm4n`、`cac-william` 兩個帳號登入進 gh(存 `~/.config/gh/hosts.yml`),每個任務用 `gh auth switch` 選帳號(見 [Part F2](#part-f2--多帳號身份切換))。好處:agent 的 `printenv` 看不到 token。`inherit_env` 只留給非 GitHub 的 secret(如 Morty 的 `JIRA_*`)。
```

- [ ] **Step 3：改 Part B — 兩帳號各一把 fine-grained PAT**

在 Part B 的 `### B1` 之前或之內，補一段說明「本 runbook 需要兩把 token」。把 B1 開頭改為說明兩帳號並存：

把 B1 目前：
```markdown
### B1.(強烈建議)用專用 machine user

- 另開一個 GitHub 帳號當機器人帳號(例:`cac-william`),只把它加為**目標 repo 的 collaborator**。
- 好處:獨立署名、要收回只要踢 collaborator,完全不碰你本人帳號。
```
改成：
```markdown
### B1. 兩個帳號、兩把 token

本 runbook 讓 bot 同時服務兩個 GitHub 身份,各建一把 fine-grained PAT:

- **公司**:`cac-william`(建議當專用 machine user,只加為目標 repo collaborator;要收回只要踢 collaborator)。→ `GH_TOKEN_CAC`
- **個人**:`wm4n`。→ `GH_TOKEN_WM4N`

兩把都照 B2 建 fine-grained、**各自只釘死要給 bot 碰的 repo**。個人帳號尤其別給帳號級全開(見[安全須知](#安全須知務必讀))。
```

並把 Part B3（約 144 行）那句提到寫入 `GH_TOKEN=` 的 prose：

```markdown
token 之後寫進 `~/.openab-secrets.env` 的 `GH_TOKEN=`,**不要**寫進 config.toml、不要寫進 docker 指令。
```
改成：
```markdown
兩把 token 之後寫進 `~/.openab-secrets.env` 的 `GH_TOKEN_WM4N=`/`GH_TOKEN_CAC=`,**不要**寫進 config.toml、不要寫進 docker 指令。
```

- [ ] **Step 4：改 Part C1 秘密檔 dotenv**

把（約 163-166 行）：
```dotenv
DISCORD_BOT_TOKEN=你的_discord_bot_token
GH_TOKEN=github_pat_你的_fine_grained_token
```
改成：
```dotenv
DISCORD_BOT_TOKEN=你的_discord_bot_token
GH_TOKEN_WM4N=github_pat_wm4n_個人_fine_grained     # 釘死要給 bot 碰的 wm4n repo
GH_TOKEN_CAC=github_pat_cac-william_公司_fine_grained # 釘死要碰的 104corp/… repo
```

- [ ] **Step 5：改 Part C2 config 的 `[agent]` 與 ★ 註記**

把（約 180-189 行）：
```toml
[agent]
command     = "claude-agent-acp"            # 必須是這個,不是 "claude"
args        = []
working_dir = "/home/node"
inherit_env = ["GH_TOKEN"]                  # ★ 解法 B:放行 GH_TOKEN 給 agent
```
改成：
```toml
[agent]
command     = "claude-agent-acp"            # 必須是這個,不是 "claude"
args        = []
working_dir = "/home/node"
# GitHub token 不走 env:兩帳號登入 gh、任務內 gh auth switch 選帳號(見 Part F2)。
# inherit_env 只放非 GitHub 的 secret(此基本版無;Morty 版見 Part K2 保留 JIRA_*)。
```

把 L191 的 ★ 註記：
```markdown
> **★ `inherit_env = ["GH_TOKEN"]` 就是這份 runbook 的核心。** 沒有它,openab 的 `env_clear()` 會把 `GH_TOKEN` 擋在 agent 門外,bot 就會「手動 `docker exec` clone 得了、但叫 bot clone 失敗」。
```
改成：
```markdown
> **★ 本 runbook 的核心已改為 gh 雙帳號 + `gh auth switch`(見 Part F2)。** GitHub token 不再經 `inherit_env` 進 agent env;而是在 Part F 一次性登入 gh 後,由每個任務的「選帳號」步驟切換。這樣 agent 讀不到裸 token,且能依 repo owner 用對身份。
```

- [ ] **Step 6：改 Part D `--env-file` 說明**

把 L209：
```markdown
- `--env-file`:注入 `DISCORD_BOT_TOKEN`(config 展開用)和 `GH_TOKEN`(inherit_env 傳給 agent)。
```
改成：
```markdown
- `--env-file`:注入 `DISCORD_BOT_TOKEN`(config 展開用)、`GH_TOKEN_WM4N`/`GH_TOKEN_CAC`(供 Part F 一次性 gh 登入用;登入後 agent 端不再依賴)。
```

- [ ] **Step 7：重寫 Part F（雙帳號 gh 登入）**

把整個 Part F（L245-264）替換成：
```markdown
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
```

- [ ] **Step 8：新增 Part F2（多帳號身份切換）**

在 Part F 之後、Part G 之前插入新小節：
```markdown
## Part F2 — 多帳號身份切換

一個 bot 服務兩個 GitHub 身份,靠「每個任務開工前依 repo owner 選帳號」。三顆 bot 的 context 檔(CLAUDE.md/AGENTS.md)都放同一段「選帳號」開場(見 Part K)。

**Owner → 帳號對照:**

| owner | 帳號 | git user.name | git user.email |
| --- | --- | --- | --- |
| `wm4n` | `wm4n`(個人) | `wm4n` | `<你的 wm4n 個人 email>` |
| `104corp`、`openabdev`、其餘一律 | `cac-william`(公司) | `Agent(CAC) Smith` | `cac.agent.smith@104.com.tw` |
| 無法判斷 | 問人類,別猜 | | |

**每個任務開工步驟:** 判斷 owner → `gh auth switch --hostname github.com --user <帳號>` → clone 後 `git -C <repo> config user.name/email`(local)。切換後 `gh` 與 `git push` 都用該帳號。

> **併發取捨:** `gh auth switch` 是整個容器全域。同一顆 bot 若同時跑兩個不同帳號的 thread(pool 併發)會互搶身份。單人主導、一次一個 feature 幾乎不會遇到。
>
> **Fallback(需跨帳號併發時再上):** 改「clone 時把 token 綁進該 repo remote + 每條 gh 指令加 `GH_TOKEN=$GH_TOKEN_XXX` 前綴」。此版需把兩把 token 放回 `inherit_env` 供逐條引用;`git remote -v` 含 token,務必守「不得貼進 Discord」鐵則。
```

- [ ] **Step 9：改附錄的 dotenv 與 config（單一附錄，約 L894 起）**

`BOT_SETUP.md` 只有一組附錄。把附錄裡的 dotenv（約 L900）：
```dotenv
DISCORD_BOT_TOKEN=你的_discord_bot_token
GH_TOKEN=github_pat_你的_fine_grained_token
```
改成 Step 4 的雙 token 版；把附錄裡 config 的：
```toml
inherit_env = ["GH_TOKEN"]
```
改成 Step 5 的註解版（移除該行，換成兩行說明註解）。

- [ ] **Step 10：驗證主敘事已改**

Run:
```bash
grep -n "GH_TOKEN_WM4N\|GH_TOKEN_CAC" deployment-guides/BOT_SETUP.md | head
grep -n "Part F2 — 多帳號身份切換" deployment-guides/BOT_SETUP.md
grep -n 'inherit_env = \["GH_TOKEN"\]' deployment-guides/BOT_SETUP.md   # 應只剩 Part K 待 Task 3 處理(此步後仍會有 L654 Summer、L444 Morty 混在其他 token)
grep -rn "解法 B" deployment-guides/BOT_SETUP.md                        # 主敘事(L3/L73/L191)不應再以「解法 B」為核心
```
Expected: 前兩條命中；第三條僅剩 Part K 區段內的殘留（Task 3 收尾）；第四條 L3/L73/L191 不再出現「解法 B」當核心（Part D `env_clear` 提及可留）。

- [ ] **Step 11：Commit**

```bash
git add deployment-guides/BOT_SETUP.md
git commit -m "$(cat <<'EOF'
docs(bot-setup): 主敘事改寫為 gh 雙帳號 + gh auth switch，新增 Part F2 身份切換

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3：BOT_SETUP.md Part K heredoc 同步 + inherit_env 調整 + 維運/疑難排解

讓 Part K 三個內嵌 heredoc 與 Task 1 的 standalone 模板逐字一致，並清掉 Part K/維運/疑難排解殘留的 `GH_TOKEN` 敘事。

**Files:**
- Modify: `deployment-guides/BOT_SETUP.md`（K2 Morty secrets/config/bullets/heredoc、K3 Rick secrets/heredoc、K4 Summer secrets/config/gh 登入/heredoc、維運表、疑難排解表）

**Interfaces:**
- Consumes: Task 1 三個模板頂部的「選帳號」區塊（逐字同步來源）；Task 2 的 `Part F2` 與 `GH_TOKEN_WM4N/CAC` 命名。

- [ ] **Step 1：K2 Morty secrets 改雙 token**

把 K2 秘密檔（約 431-436 行）的：
```dotenv
GH_TOKEN=github_pat_morty_的_token
```
改成：
```dotenv
GH_TOKEN_WM4N=github_pat_wm4n_個人_fine_grained
GH_TOKEN_CAC=github_pat_cac-william_公司_fine_grained
```

- [ ] **Step 2：K2 Morty config inherit_env 去掉 GH_TOKEN（保留 JIRA）**

把 L444：
```toml
inherit_env = ["GH_TOKEN", "JIRA_TOKEN", "JIRA_BASE_URL", "JIRA_EMAIL"]
```
改成：
```toml
inherit_env = ["JIRA_TOKEN", "JIRA_BASE_URL", "JIRA_EMAIL"]   # GitHub 走 gh 雙帳號,不放 GH_TOKEN
```

- [ ] **Step 3：K2 CLAUDE.md 內容 bullet 補「選帳號」與 personal 分支**

在 K2 描述 CLAUDE.md 內容的 bullet list（約 467-475 行）補兩點：
```markdown
- 開工前依 repo owner 選 GitHub 身份（`gh auth switch` + per-repo 署名，見 Part F2）——這段開場與 Rick/Summer 共用同一份「選帳號」區塊
- Repo 解析優先序第 4 步：個人（wm4n）任務不查公司對照表；公司任務查表前先切 `cac-william`
```

- [ ] **Step 4：K2 Morty 一次性 gh 雙帳號登入（Portainer Console）**

在 K2 skill 安裝段落之後補一步（Morty 在 Portainer，用 Console，user `node`）：
```markdown
**gh 雙帳號登入**（Console，user `node`；`GH_TOKEN_WM4N/CAC` 已由 Stack env 注入）：

```bash
echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token
echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token
gh auth setup-git
gh auth status   # 要看到 wm4n 與 cac-william 兩個 Logged in
```
```
並提醒：Portainer Stack 的 Environment variables 要把 `GH_TOKEN` 改成 `GH_TOKEN_WM4N`、`GH_TOKEN_CAC` 兩筆。

- [ ] **Step 5：K3 Rick secrets 改雙 token**

把 K3 秘密檔（約 484-487 行）的：
```dotenv
GH_TOKEN=github_pat_rick_的_token
```
改成：
```dotenv
GH_TOKEN_WM4N=github_pat_wm4n_個人_fine_grained
GH_TOKEN_CAC=github_pat_cac-william_公司_fine_grained
```

- [ ] **Step 6：K3 Rick 補一次性 gh 雙帳號登入 + config 檢查註記**

在 K3「OpenSpec 安裝」附近補一步：
```bash
docker -c orbstack exec -i -u node openab-rick sh -c '
  echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token &&
  echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token &&
  gh auth setup-git'
docker -c orbstack exec -u node openab-rick gh auth status   # wm4n + cac-william 兩個
```
並補註記：
```markdown
> ⚠️ K3 未列出 Rick 的 config.toml。rollout 時確認 Rick 的 config 位置（掛載或 volume 內），若含 `inherit_env = ["GH_TOKEN"]` 一併移除（GitHub 改走 gh 雙帳號）。
```

- [ ] **Step 7：K3 Rick heredoc 插入「選帳號」區塊（與 Rick-CLAUDE.md 同步）**

在 K3 的 CLAUDE.md heredoc 內，`## 身份` 段之後、`## 每次開始前` 之前，插入共用內容 A 全文（與 `deployment-guides/Rick-CLAUDE.md` Task 1 插入的完全一致）。

- [ ] **Step 8：K4 Summer secrets 改雙 token**

把 K4 秘密檔（約 636-638 行）的：
```dotenv
GH_TOKEN=github_pat_summer_的_token
```
改成：
```dotenv
GH_TOKEN_WM4N=github_pat_wm4n_個人_fine_grained
GH_TOKEN_CAC=github_pat_cac-william_公司_fine_grained
```

- [ ] **Step 9：K4 Summer openab config inherit_env 去掉 GH_TOKEN + 更新註記**

把 L654：
```toml
inherit_env = ["GH_TOKEN"]
```
改成：
```toml
inherit_env = []   # GitHub 走 gh 雙帳號(hosts.yml),不放 GH_TOKEN
```
並把 L661 的 ⚠️ 註記：
```markdown
> ⚠️ `args` 的 `shell_environment_policy.inherit=all`：codex-acp 預設不把 `inherit_env` 的變數傳入 bwrap sandbox 內的 shell，加這行才讓 `gh` 看到 GH_TOKEN。少了這行，`gh` 指令全部 ❌。
```
改成：
```markdown
> ⚠️ `args` 的 `shell_environment_policy.inherit=all`：保留即可。GitHub 憑證已改走 gh 儲存的雙帳號(`~/.config/gh/hosts.yml`)、不靠 env,故此旗標對 GitHub 不再必要;但留著不影響其他 env 傳遞。
```

- [ ] **Step 10：K4 Summer 補一次性 gh 雙帳號登入**

在 K4 superpowers 安裝之後補一步（bwrap 內 gh 用 hosts.yml，不需 env token）：
```bash
docker -c orbstack exec -i -u node openab-summer sh -c '
  echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token &&
  echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token &&
  gh auth setup-git'
docker -c orbstack exec -u node openab-summer gh auth status   # wm4n + cac-william 兩個
```
> 一次性登入用 `-i`（互動）讓 stdin 帶 token；`GH_TOKEN_WM4N/CAC` 由 `--env-file` 注入容器，故 exec 內可見。

- [ ] **Step 11：K4 Summer heredoc 插入「選帳號」區塊（與 Summer-AGENTS.md 同步）**

在 K4 的 AGENTS.md heredoc 內，`## 身份` 段之後、`## 觸發：Rick @你` 之前，插入共用內容 A 全文（與 `deployment-guides/Summer-AGENTS.md` Task 1 插入的完全一致）。

- [ ] **Step 12：維運表補「換 token / 換 gh 帳號」列**

在維運的「Token 輪替/撤銷」段補一句：
```markdown
- 換某帳號 token:更新 `~/.openab-secret-*.env` 對應的 `GH_TOKEN_WM4N`/`GH_TOKEN_CAC` → `rm -f` 重建容器 → 重跑該容器的 gh 雙帳號登入(Part F / K)。
```

- [ ] **Step 13：疑難排解表更新/新增列**

把 L878 這列（已過時的 inherit_env 解法）：
```markdown
| **手動 `docker exec` clone 成功、但叫 bot clone 失敗**  | openab `env_clear()` 把 `GH_TOKEN` 擋在 agent 外  | config `[agent]` 加 `inherit_env = ["GH_TOKEN"]` → restart(本 runbook 解法 B) |
```
改成：
```markdown
| **手動 `docker exec` clone/push 成功、但叫 bot 失敗**  | bot 忘了先 `gh auth switch` 選帳號,或該帳號沒登入 gh  | 確認 context 檔有「選帳號」開場(Part F2);`gh auth status` 確認兩帳號都在 |
```
並在表尾新增兩列：
```markdown
| **push 403 或 commit author 錯**  | 切錯帳號或忘了切(wm4n repo 用到 cac-william、反之亦然)  | 開工前 `gh auth switch --user <對的帳號>` + per-repo 設 local 署名(Part F2) |
| **`gh auth login`/`switch` 拒絕、說 GH_TOKEN 環境變數存在**  | env 有裸 `GH_TOKEN`  | 改用 `GH_TOKEN_WM4N`/`GH_TOKEN_CAC`,別設裸 `GH_TOKEN` |
```

- [ ] **Step 14：驗證 heredoc 與模板逐字同步（E002：全文 diff）**

Run（抽出 heredoc 內選帳號區塊與 standalone 模板比對；區塊以「## 開工前」開頭、到「鐵則：絕不把」該行結束）：
```bash
# Rick：heredoc(K3) 的選帳號區塊 vs 模板
diff <(awk '/## 開工前：依 repo owner 選 GitHub 身份/,/鐵則：絕不把/' deployment-guides/Rick-CLAUDE.md) \
     <(awk '/## 開工前：依 repo owner 選 GitHub 身份/,/鐵則：絕不把/' deployment-guides/BOT_SETUP.md | head -n $(awk '/## 開工前：依 repo owner 選 GitHub 身份/,/鐵則：絕不把/' deployment-guides/Rick-CLAUDE.md | wc -l))
# Summer 同理（用 Summer-AGENTS.md 比對 BOT_SETUP 第二處出現）
grep -c "## 開工前：依 repo owner 選 GitHub 身份" deployment-guides/BOT_SETUP.md   # 期望 2（K3、K4 兩個 heredoc；Part F2 只引用、不含整段）
grep -nE 'GH_TOKEN=github_pat' deployment-guides/BOT_SETUP.md                       # 期望無輸出（裸 GH_TOKEN 秘密全數改名）
grep -n '的 `GH_TOKEN=`' deployment-guides/BOT_SETUP.md                             # 期望無輸出（Part B3 prose 已改）
grep -n 'inherit_env = \["GH_TOKEN"\]' deployment-guides/BOT_SETUP.md               # 期望無輸出
```
Expected: diff 無差異（或僅 heredoc 縮排差異——若有，手動對齊到逐字一致）；`GH_TOKEN=github_pat` 無輸出；Part B3 prose 已改；`inherit_env = ["GH_TOKEN"]` 無輸出。

> 注意：Part F2 fallback 與疑難排解列**刻意**保留 inline 前綴示例 `GH_TOKEN=$GH_TOKEN_XXX`（不是裸秘密），故不用 `grep "GH_TOKEN="` 當通過條件。

> 若 diff 有差異：以 standalone 模板為準，改 heredoc。逐字一致是驗收條件。

- [ ] **Step 15：Commit**

```bash
git add deployment-guides/BOT_SETUP.md
git commit -m "$(cat <<'EOF'
docs(bot-setup): Part K heredoc 同步選帳號區塊、清掉 GH_TOKEN env 敘事、補疑難排解

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4：Rollout 與端對端驗證（operational，手動在主機執行）

> 本 Task **不是**本 repo 的實作 agent 能跑的:牽涉真實 token、真實容器、Mac mini/Portainer 與 Discord。由使用者依更新後的 runbook 在各主機執行。列在此讓計畫端到端完整。

- [ ] **Step 1：建兩把 fine-grained PAT**：`wm4n`(釘死個人 repo)、`cac-william`(釘死公司 repo);90 天到期。
- [ ] **Step 2：三顆 bot 各更新 secrets 檔**（`GH_TOKEN_WM4N`/`GH_TOKEN_CAC`、移除裸 `GH_TOKEN`）→ `rm -f` + 重建容器（改 env 必重建）。
- [ ] **Step 3：三顆 bot 各跑一次性 gh 雙帳號登入**（Part F / K4 / K2 Portainer）→ `gh auth status` 兩帳號都在。
- [ ] **Step 4：三顆 bot 各更新 config**（移除 `inherit_env` 的 `GH_TOKEN`;Morty 保留 JIRA;確認 Rick config 位置）→ 依掛載方式 restart 或重建。
- [ ] **Step 5：三顆 bot 各寫入更新後的 context 檔**（heredoc，含選帳號開場）→ `head` 驗證寫入、owner 為 node。
- [ ] **Step 6：單帳號煙霧測試**（在任一容器）：
  ```bash
  gh auth switch --user wm4n && git clone https://github.com/wm4n/<測試repo>.git /tmp/t1 && \
    git -C /tmp/t1 config user.email "<wm4n email>" && echo x >> /tmp/t1/README && \
    git -C /tmp/t1 commit -am "test" && git -C /tmp/t1 push   # 應成功、author=wm4n、無 403
  gh auth switch --user cac-william && git clone https://github.com/104corp/<測試repo>.git /tmp/t2  # 應成功
  ```
- [ ] **Step 7：端對端**：在 #dev-bot 跑一條 `wm4n` GitHub Issue 與一條公司任務,確認兩邊 PR 的 commit 署名正確、無 403。

---

## Self-Review（本計畫對照 spec）

- **Spec coverage:** owner→帳號對照(Task1 共用內容A/Task2 F2)、secrets 雙 token(T2S4/T3S1,5,8)、一次性 gh 登入(T2S7/T3S4,6,10)、選帳號 routine(T1/T2S8)、config 去 inherit_env GH_TOKEN(T2S5/T3S2,9)、Morty personal 分支(T1S4/T3S3)、三模板+heredoc 同步(T1/T3)、驗證(T4)、安全(既有安全須知沿用;裸 token 退場於 T2/T3)、要改哪些檔(全覆蓋)。無缺口。
- **Placeholder scan:** `<你的 wm4n email>` 等尖括號為 runbook 刻意 placeholder(Global Constraints 已聲明),非計畫缺口。無 TBD/TODO。
- **一致性:** 「選帳號」區塊為共用內容 A,三處逐字引用;Task 3 Step 14 以全文 diff 驗證一致(E002)。`gh auth switch --hostname github.com --user` 措辭全計畫一致。
- **已知開放項:** Rick config 位置(K3 未列)於 T3S6 與 T4S4 明確標記待 rollout 確認;gh ≥2.40 於 Global Constraints 標記。
