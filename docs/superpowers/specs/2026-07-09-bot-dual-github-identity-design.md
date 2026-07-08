# 三 Bot 雙 GitHub 身份設計（wm4n + cac-william）

- 日期：2026-07-09
- 分支：docs/three-bot-pipeline
- 狀態：設計定案，待實作

## 背景與問題

現有三顆 bot（Morty / Rick / Summer）組成開發 pipeline，各自容器內只持有**單一** `GH_TOKEN`，commit 署名以 Part F 的 `git config --global user.name/email` 一次設死。

使用者有兩個 GitHub 帳號：

- 個人：`wm4n`
- 公司：`cac-william`

兩者是**不同的 GitHub 帳號**，但共用**同一個 LLM 帳號**、**同一套 skill**。既有規則（見使用者記憶 feedback）：

- `wm4n/*` → 以 wm4n 帳號 commit/push
- `104corp/*`、`openabdev/*` → 以 cac-william 帳號 commit/push
- 帳號與 repo 錯配 → push 403 + commit author 錯誤

目前的單 token 設定無法同時服務兩個身份。目標是讓三顆 bot 都能**依目標 repo 的 owner 自動切換 GitHub token 與 commit 署名**。

## 目標與非目標

**目標**

- 沿用現有 **3 顆 bot、一個頻道、一套 skill、同一 LLM 帳號**，不新增 bot、不新增頻道。
- 每顆 bot 依 `owner/repo` 自動切換 GitHub 身份（token + 署名）。
- 個人（wm4n）情境不帶 JIRA、不查公司產品對照表。
- 擴充成本低：加一個帳號 = 加一把 token + 一條 owner→帳號對照。

**非目標**

- 不處理 GitHub App / 短效 installation token（列為未來升級路徑，POC 不做）。
- 不改變 pipeline 的接力邏輯、mention 規則、角色分工。
- 不處理 upstream-only repo（如 `openabdev/openab` cac-william 只有 READ）的 fork 流程——維持既有限制，超出本設計範圍。

## 決策：方案 B（單一 pipeline + 雙身份）

評估過三個方案：

- **A. 兩條 pipeline（6 顆 bot，硬隔離）**：token 不共置、署名天然正確，但 6 容器 / 6 Discord App / 6 套設定要維護，Mac mini RAM 吃緊，擴充帳號要再 +3。
- **B. 單一 pipeline + 雙身份（3 顆 bot）✅ 採用**：每顆 bot 持兩把 token，依 owner 切換。最省資源、最有彈性；代價是兩把 token 共置於同一容器，用 fine-grained 釘死 repo 控管風險。
- **C. GitHub App + 短效 token（未來升級）**：最乾淨的多帳號 + 最小 blast radius，但設定較重，POC 先不上，日後從 B 升級。

採用 **B**：符合「簡單有彈性」，在同一 LLM 帳號、同一套 skill 前提下用 3 顆 bot 吃下兩個身份。

## Owner → 帳號對照

| owner | 帳號 | 身份 |
| --- | --- | --- |
| `wm4n` | wm4n | 個人 |
| `104corp`、`openabdev`、其餘一律 | cac-william | 公司 |
| 無法判斷 | —— | 問人類 |

## 身份切換機制（核心）

### Secrets（每顆 bot 的 env 檔）

從單把改雙把，且**不再有裸 `GH_TOKEN`**：

```dotenv
GH_TOKEN_WM4N=github_pat_個人_fine_grained   # 釘死要給 bot 碰的 wm4n repo
GH_TOKEN_CAC=github_pat_公司_fine_grained    # 釘死要碰的 104corp/… repo
```

（Morty 另保留 `JIRA_TOKEN` / `JIRA_BASE_URL` / `JIRA_EMAIL`。）

### 一次性設定（每顆容器做一次）

把兩把 token 都登入進 gh（存進 `~/.config/gh/hosts.yml`），並接上 git credential helper：

```bash
echo "$GH_TOKEN_WM4N" | gh auth login --hostname github.com --with-token
echo "$GH_TOKEN_CAC"  | gh auth login --hostname github.com --with-token
gh auth setup-git
```

> 前提：env 中**不能有裸 `GH_TOKEN`**，否則 gh 會忽略儲存的帳號而改用該環境變數，`gh auth login`/`switch` 會拒絕。命名為 `GH_TOKEN_WM4N`/`GH_TOKEN_CAC` 即可避開。

### 每個任務開工前的固定步驟（寫進各 bot context 檔）

依 owner 選帳號，先於任何 git/gh 操作：

```
1. 從任務確定 owner/repo。
2. owner=wm4n → 帳號=wm4n；owner=104corp/openabdev/其餘 → 帳號=cac-william；無法判斷 → 問人類。
3. gh auth switch --hostname github.com --user <wm4n | cac-william>
4. clone 後：git -C <repo> config user.name "<該帳號 name>"；user.email "<該帳號 email>"
```

`gh auth switch` 會同時讓 `gh` 指令與 `git push`（透過 gh credential helper）跟著切，且狀態寫在 hosts.yml（磁碟），跨多次工具呼叫都持續有效。

### 併發取捨（重要）

`gh auth switch` 是**整個容器全域**的。若同一顆 bot 同時跑兩個不同帳號的 thread（openab pool 併發），會互相搶身份。以單人主導、一次一個 feature 的用法幾乎不會遇到。

**Fallback（併發安全版，日後需要再上）**：改為「per-repo 綁 token（clone 時或 `git remote set-url` 把 token 綁進該 repo）+ 所有 gh 指令逐條加 `GH_TOKEN=$GH_TOKEN_XXX` 前綴」。此版需把兩把 token 放回 `inherit_env` 供逐條引用；token-in-URL 有進 log 風險，須配合「不得把 remote/hosts 貼進 Discord」鐵則。

### config.toml 變更（三顆共通）

- 移除 `inherit_env = ["GH_TOKEN"]`（改用 gh 儲存的雙帳號，agent 不需 token 在 env）。
- Morty 保留 JIRA 的 `inherit_env`（`JIRA_TOKEN` / `JIRA_BASE_URL` / `JIRA_EMAIL`）。
- Summer（Codex）維持 `args = ["-c", "shell_environment_policy.inherit=all"]` 與 `--security-opt seccomp=unconfined`（bwrap 需求，與 token 無關，不動）。
- `--env-file` 仍帶兩把 token（一次性登入用）；登入後 agent 端已不依賴。

**額外好處**：token 只在一次性登入時用到，之後存在 hosts.yml；agent 的 `printenv` 看不到 token（可從 `inherit_env` 拿掉裸 token），blast radius 比現況更小。

## 三顆 bot 模板改動

### 共通：新增「選帳號」開場步驟

放在每個模板工作流程最前面（內容見上「每個任務開工前的固定步驟」）。三顆共用同一段，維持一致。

### Morty 專屬

- 「Repo 解析優先序」第 4 步（讀 `104corp/cac-ai-rules` 產品對照表）加分支：**只有公司任務才查**；個人（wm4n）任務靠明確 owner/repo 或 GitHub Issue URL，不查公司對照表。
- 查對照表本身需公司身份 → 查表前先 `gh auth switch --user cac-william`。
- 角色 B1（JIRA）只會被公司票觸發，個人任務自然不走到，無需改。

### Rick / Summer 專屬

- 邏輯不變，只在既有 clone / push / `gh pr create` / `gh pr` review 之前先跑「選帳號」步驟。
- Summer 從 PR URL 取 owner 決定身份。

## 一次性 rollout（三顆各做一次）

每顆 bot：

1. **改 secrets 檔** → 雙 token、移除裸 `GH_TOKEN`。改 env 需 `rm -f` 容器後重建（runbook 維運規則）。
2. **雙帳號登入**（operator exec）：`gh auth login --with-token` ×2 + `gh auth setup-git`。
3. **改 config**：拿掉 `inherit_env=["GH_TOKEN"]`（Morty 保留 JIRA）→ 依該 bot config 掛載方式重啟或重建。
4. **改 context 檔**（heredoc 重寫 CLAUDE.md／AGENTS.md）加入「選帳號」步驟。

## 驗證

- 每顆：`gh auth status` 要看到**兩個帳號都 logged in**。
- 切 wm4n → clone+push 一個 wm4n 測試 repo → 確認 author=wm4n、無 403；再切 cac-william → 對一個公司 repo 同樣測 → author=cac-william、無 403。
- 端對端：跑**一條個人 GitHub Issue** 與 **一條公司任務** 各一次，確認兩邊 PR 的 commit 署名都正確。

## 安全

- 兩把都用 **fine-grained + 釘死 repo + 90 天到期 + 可秒收回**；wm4n 是**個人**帳號，只釘要給 bot 碰的那幾個個人 repo，別給帳號級全開。
- env 裡不再有裸 token；token 落在 hosts.yml（node 擁有、在 volume 內），agent 讀得到但 `printenv` 看不到。
- 鐵則：**絕不把 `hosts.yml` / `git remote -v` 內容貼進 Discord**（避免 token 進聊天記錄）。
- 單次事故 blast radius = 該 bot 兩把 token 釘死 repo 的聯集 = 它本來就會碰的範圍。

## 實作範圍（要改哪些檔）

- `deployment-guides/BOT_SETUP.md`：
  - Part B：兩帳號各建一把 fine-grained PAT。
  - Part C + 附錄：secrets 範例改雙 token、拿掉裸 `GH_TOKEN`。
  - Part F：gh 設定改「雙帳號 login + setup-git」，加「選帳號」說明。
  - 新增「多帳號身份切換」小節（機制 + 選帳號 routine 範本 + 併發 fallback）。
  - Part K：K2/K3/K4 三個 heredoc 加入「選帳號」開場；Morty 加對照表 personal 分支；config `inherit_env` 調整。
  - 疑難排解：加「push 403 / 署名錯 → 忘了切帳號」條目。
- `deployment-guides/Morty-CLAUDE.md`、`Rick-CLAUDE.md`、`Summer-AGENTS.md`：各加「選帳號」開場；Morty 加對照表 personal 分支——並與 BOT_SETUP.md 內嵌 heredoc **保持同步**（bot-setup-md-sync 慣例）。

## 未解 / 待實作時確認

- 各 bot 實際 config 位置不一（Mac mini 掛 `/etc/openab`、Portainer/volume 版放 `/home/node/config.toml`）；移除 `inherit_env` 時依各自位置修改。
- wm4n 的 commit 署名 name/email 值待填（個人身份）；cac-william 沿用 Part F 既有範例（`Agent(CAC) Smith` / `cac.agent.smith@104.com.tw`）或另訂。
- `gh auth switch` 多帳號需 gh 版本支援（≥2.40）；rollout 時確認映像內 gh 版本。
