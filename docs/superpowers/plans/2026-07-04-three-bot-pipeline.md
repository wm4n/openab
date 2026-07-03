# 三 Bot 接力 Pipeline 實作計畫

> **For agentic workers:** 這是**運維 runbook 型**計畫(改 config、裝 skill、寫角色提示檔、驗證),交付物多在**容器/主機端**而非 repo commit。多數步驟需在 **bot 所在主機**執行(#1 在 Portainer 網頁、#2/#3 在 Mac mini CLI),本 session 的 dev 機沒有 docker,無法代跑——請把指令交給使用者在對應主機執行。逐項用 `- [ ]` 追蹤。

**Goal:** 用 openab 現有的 `allow_bot_messages`/`trusted_bot_ids` 機制,把三個 Discord bot 串成「規格 → openspec 開發 → 雙引擎複審 → 人類合併」流水線,零改碼。

**Architecture:** 三隻同處 #dev-bot 頻道,路由走 @mention、產物走 GitHub branch/PR。#1(claude@Portainer)做 brainstorming 規格 + `/review` 複審;#2(claude@Mac mini)跑 openspec 開發並開 PR;#3(codex@Mac mini)用使用者自備 review skill 當第二 reviewer。approve/merge 一律人類手動。

**Tech Stack:** openab(config.toml)、Discord、superpowers skill、OpenSpec(`@fission-ai/openspec`)、gh CLI、Docker(OrbStack / Portainer)。

## Global Constraints

- **只放 placeholder,絕不寫真實 token 進任何檔案/聊天**(承 BOT_SETUP.md 慣例)。
- **openab docker 指令一律帶 `-c orbstack`**;不動 colima。
- **bot 永不 merge/approve PR**;approve + merge 只有人類手動做。
- **archive 先於 PR**:#2 的流程是 `/opsx:propose`→`/opsx:apply`→`/opsx:archive`→開 PR;調整走**新一輪 /opsx**、push 進**同一個 PR**,不改已 archive 的 change。
- reviewer 一律留 **COMMENT 型** review,非 GitHub Approve。
- 三隻回覆一律**繁體中文**。
- 設計依據:`docs/superpowers/specs/2026-07-04-three-bot-pipeline-design.md`。

---

### Task 1: 前置盤點 — 蒐集 ID、路徑、確認三隻活著

**Files:**
- 產出(填寫):本計畫下方「部署參照表」(記在你自己的筆記或貼回 thread 即可,非 repo 檔)

**Interfaces:**
- Produces:`CH_ID`(#dev-bot 頻道 ID)、`HUMAN_ID`(你的 user ID)、`BOT1_ID`/`BOT2_ID`/`BOT3_ID`(三隻 bot 的 user ID),以及每隻的「容器名 / config.toml 位置 / 編輯法 / 重啟法」——Task 2–5 全部引用這些值。

- [ ] **Step 1: 開 Discord 開發者模式,複製 ID**

Discord → 設定 → 進階 → 開發者模式 ON。右鍵取得:
- #dev-bot 頻道 → 複製頻道 ID → `CH_ID`
- 你自己 → 複製使用者 ID → `HUMAN_ID`
- 頻道成員列右鍵三隻 bot → 複製使用者 ID → `BOT1_ID`(#1)、`BOT2_ID`(#2)、`BOT3_ID`(#3)

- [ ] **Step 2: 填部署參照表**(依你的 roster 預填,逐一確認)

| bot | 容器名 | 主機 | config.toml 位置 | 編輯法 | 重啟法 |
|---|---|---|---|---|---|
| #1 規格+複審 | (確認,例 `openab`) | Portainer | `/home/node/config.toml` | Portainer→Console(user `node`) | Portainer→Containers→Restart |
| #2 openspec | (確認,例 `openab-claude`) | Mac mini | 主機 `~/oab/config.toml`(掛 `/etc/openab`) | 在 Mac mini 直接編輯主機檔 | `docker -c orbstack restart <名>` |
| #3 codex 複審 | (確認,例 `openab-codex`) | Mac mini | 主機 `~/oab-codex/config.toml` | 同上 | `docker -c orbstack restart <名>` |

> 若某隻實際位置與預填不同(例如 #2 也是 in-container `/home/node/config.toml`),以實際為準並記下來。判斷法:`docker -c orbstack inspect <名> --format '{{json .Mounts}}'` 看 config 是掛主機目錄還是 named volume。

- [ ] **Step 3: 確認三隻都活著且會回人類**(這步會順便揪出之前的 `Authentication required`)

在 #dev-bot 分別 @每一隻,各丟「請回我一句 ok」。三隻都要回。

Expected:三隻都回覆。
- 若某隻回 `Authentication required` / `-32000` → 那隻的後端 agent 沒登入,**先解決再繼續**:claude 版 `claude auth login`、codex 版 `codex login --device-auth`(見 BOT_SETUP.md Part E / bot-setup-codex.md 步驟 5),登完重啟。
- 三隻未全部通過前,不要進 Task 2。

- [ ] **Step 4: 確認三隻都在同一頻道 + GitHub 可用**

每隻執行(容器名代入):
```bash
# Mac mini(#2/#3):
docker -c orbstack exec -u node <#2容器> gh auth status
docker -c orbstack exec -u node <#3容器> gh auth status
```
#1 在 Portainer → Console → `gh auth status`。

Expected:三隻都 `Logged in`。若否,補 `GH_TOKEN`(見 BOT_SETUP.md Part B/F)。

---

### Task 2: 佈建 Bot #1(規格 brainstorming + PR 複審)

**Files:**
- Modify: #1 的 `config.toml`(位置見 Task 1 表)`[discord]` 區塊
- Create: #1 容器內 `/home/node/CLAUDE.md`
- Install: superpowers skill(#1 容器)

**Interfaces:**
- Consumes:`CH_ID`、`HUMAN_ID`、`BOT2_ID`(Task 1)
- Produces:#1 能被人類 @ 觸發跑 brainstorming、能被 `BOT2_ID` @ 觸發跑 `/review`;回覆結尾會 @`BOT2_ID`。

- [ ] **Step 1: 改 #1 的 `config.toml [discord]`**

用 Portainer Console 編輯 `/home/node/config.toml`,`[discord]` 確保含(代入實際 ID):
```toml
[discord]
bot_token        = "${DISCORD_BOT_TOKEN}"
allowed_channels = ["CH_ID"]
allowed_users    = ["HUMAN_ID"]      # bot 訊息不受此管,只列人類
allow_bot_messages = "mentions"
trusted_bot_ids    = ["BOT2_ID"]     # 只信 #2 的 @mention（收其複審請求）
# allow_user_messages 省略 = 預設 multibot-mentions
```

- [ ] **Step 2: 裝 superpowers**(#1 容器,Portainer Console)

依 superpowers 安裝說明(<https://github.com/obra/superpowers>)裝到這隻 claude agent。裝完在 Console 驗證 skill 可見:
```bash
ls ~/.claude/plugins 2>/dev/null || true
```
Expected:能看到 superpowers 相關 plugin/skill 目錄。

- [ ] **Step 3: 寫 #1 的 `/home/node/CLAUDE.md`**(Portainer Console)

```bash
cat > /home/node/CLAUDE.md <<'EOF'
# CLAUDE.md — Bot #1:規格(brainstorming) + PR 複審

## 身份
你是 openab 橋接到 Discord #dev-bot 的 Claude agent,在三 bot 開發 pipeline 裡有兩個角色:規格確認、PR 複審(reviewer A)。一律繁體中文回覆。只有被 @ 到才動作。

## 角色 A:規格(當「人類」@你、描述一個新需求時)
1. 用 superpowers 的 brainstorming 技能,在 thread 跟人一問一答把規格確認清楚。
2. 定案後產出 design spec(brainstorming 會寫到 docs/superpowers/specs/)。
3. 【止步於 design spec】不要跑 writing-plans、不要寫程式碼——任務拆解是 Bot #2 的事。
4. 把 spec commit,push 到新分支 feat/<簡短主題>。
5. 回覆結尾務必 @Bot#2(<@BOT2_ID>),附:repo、branch、spec 路徑。
   例:「規格確認完成。<@BOT2_ID> 請接手:repo=owner/repo, branch=feat/dark-mode, spec=docs/superpowers/specs/xxxx.md」

## 角色 B:PR 複審(當 Bot #2 @你、並附一個 PR 時)
1. 用內建 /review <PR 網址或編號> 審這個 PR。
2. 以 COMMENT 形式(不要用 GitHub Approve)把發現貼到 PR。
3. 回報 Bot #2:
   - 有問題:<@BOT2_ID> changes requested:<重點清單>,PR=<URL>
   - 沒問題:<@BOT2_ID> clean,無 blocking 問題,PR=<URL>
4. 你絕不 merge、絕不 approve PR——那是人類的工作。

## 鐵則
- 做完事,結尾一定 @ 下一棒(兩個角色都是 @Bot#2)。
- 只有被 @ 到才動作。
EOF
```
> 把 `<@BOT2_ID>` 換成實際的 `<@實際數字ID>`(Discord mention 格式)。

- [ ] **Step 4: 重啟 #1 並驗證設定生效**

Portainer → Containers → 該容器 → Restart。轉 healthy 後:
- 人類在 #dev-bot @#1 丟一個小需求(如「幫我規劃一個 hello world CLI」)→ 應開始 brainstorming 問問題。

Expected:#1 進入 brainstorming 問答(不是直接寫 code、也不是沉默)。

- [ ] **Step 5: 驗證 #1 的 reviewer 角色可被 #2 觸發**(延到 Task 5 端對端一起驗,這裡先跳過)

---

### Task 3: 佈建 Bot #2(openspec 開發 + 發 PR)

**Files:**
- Modify: #2 的 `config.toml`(Task 1 表,Mac mini 主機檔)`[discord]`
- Create: #2 容器內 `/home/node/CLAUDE.md`
- Install: OpenSpec(#2 容器)+ `openspec init`(工作 repo)

**Interfaces:**
- Consumes:`CH_ID`、`HUMAN_ID`、`BOT1_ID`、`BOT3_ID`
- Produces:#2 被 `BOT1_ID` @ 時跑 openspec+開 PR、被 `BOT3_ID` @ 時處理 changes;回覆會 @`BOT1_ID` 和 `BOT3_ID`。

- [ ] **Step 1: 改 #2 的 `config.toml [discord]`**(Mac mini 編輯主機檔)

```toml
[discord]
bot_token        = "${DISCORD_BOT_TOKEN}"
allowed_channels = ["CH_ID"]
allowed_users    = ["HUMAN_ID"]
allow_bot_messages = "mentions"
trusted_bot_ids    = ["BOT1_ID", "BOT3_ID"]   # 收 #1 派工、#3 review 結果
```

- [ ] **Step 2: 裝 OpenSpec**(#2 容器)

```bash
docker -c orbstack exec -u node <#2容器> npm install -g @fission-ai/openspec@latest
docker -c orbstack exec -u node <#2容器> sh -lc 'openspec --version'
```
Expected:印出版本號。

- [ ] **Step 3: 在 #2 的工作 repo 跑 `openspec init`**

#2 開發時會把 repo clone 到 `/home/node/<repo>`。openspec 需要在**該 repo 根目錄**初始化(產生 `openspec/` + 對應 assistant 的 slash 指令)。這步可在 CLAUDE.md 指示 #2「首次進某 repo 若無 `openspec/` 就先 `openspec init`」,或首次手動:
```bash
docker -c orbstack exec -u node -w /home/node/<repo> <#2容器> openspec init
```
Expected:出現 `openspec/` 目錄。

- [ ] **Step 4: 寫 #2 的 `/home/node/CLAUDE.md`**

```bash
docker -c orbstack exec -i -u node <#2容器> sh -c 'cat > /home/node/CLAUDE.md' <<'EOF'
# CLAUDE.md — Bot #2:openspec 開發 + 發 PR

## 身份
你是 openab→Discord #dev-bot 的 Claude agent,pipeline 裡負責「把規格變成程式並開 PR」。一律繁體中文。只有被 @ 到才動作。

## 觸發:Bot #1 @你、給你 branch 與 spec
1. git fetch;checkout 那個 branch;讀 #1 的 design spec。
2. 若該 repo 尚無 openspec/,先跑 `openspec init`。
3. 跑 openspec:/opsx:propose "<依 spec 濃縮的描述>" → /opsx:apply（一路做完、不中途等人）→ /opsx:archive。
   【archive 先做】收進正式 spec 後才開 PR。
4. commit + push;用 gh pr create 開 PR。
5. 結尾同時 @Bot#1(<@BOT1_ID>)和 @Bot#3(<@BOT3_ID>):「PR 好了:<PR_URL>,請 review」。

## 收到 reviewer 的結果
- 任一 reviewer 說 changes requested:針對意見【跑新一輪 /opsx 流程】(propose→apply→archive),push 進【同一個 PR】(同一 branch，累積 commits)。不要改已 archive 的舊 change。改完重新 @Bot#1 和 @Bot#3 複審。
- 兩位 reviewer 都回 clean:在 thread 通知人類:「兩位 reviewer 都清了,PR=<URL>,待你 approve+merge」。

## 鐵則
- 你永遠不 merge、不 approve PR。merge 是人類手動。
- 只有【最新一次 push 之後】兩位 reviewer 都回過 clean,才通知人類可合併;任何新 push 讓先前的 clean 作廢、須重審。
- 只有被 @ 到才動作。
EOF
```
> `<@BOT1_ID>`、`<@BOT3_ID>` 換成實際 mention。

- [ ] **Step 5: 重啟 #2**

```bash
docker -c orbstack restart <#2容器>
docker -c orbstack ps            # healthy
```
Expected:healthy。功能性驗證併入 Task 5。

---

### Task 4: 佈建 Bot #3(codex 第二 reviewer)

**Files:**
- Modify: #3 的 `config.toml`(Task 1 表,Mac mini 主機檔)`[discord]`
- Create: #3 容器內 `/home/agent` 或 `/home/node` 的 `AGENTS.md`(codex 用 AGENTS.md;實際家目錄見容器)
- Install: 使用者自備的 review skill(#3/codex 容器)

**Interfaces:**
- Consumes:`CH_ID`、`HUMAN_ID`、`BOT2_ID`
- Produces:#3 被 `BOT2_ID` @ 時審 PR、留 comment、@`BOT2_ID` 回報。

- [ ] **Step 1: 改 #3 的 `config.toml [discord]`**(Mac mini 主機檔)

```toml
[discord]
bot_token        = "${DISCORD_BOT_TOKEN}"
allowed_channels = ["CH_ID"]
allowed_users    = ["HUMAN_ID"]
allow_bot_messages = "mentions"
trusted_bot_ids    = ["BOT2_ID"]     # 只收 #2 的 review 請求
```

- [ ] **Step 2: 裝你自備的 review skill 到 #3(codex)**

依你的 review skill 安裝方式裝到 codex agent。裝完在容器內確認可被叫用(依該 skill 的驗證方式)。
Expected:review skill 可用。

- [ ] **Step 3: 確認 #3 的家目錄,寫 `AGENTS.md`**

先確認家目錄(codex 官方映像是 `/home/node`;若你的 #3 是基礎映像則為 `/home/agent`):
```bash
docker -c orbstack exec <#3容器> sh -lc 'echo $HOME'
```
用得到的 `$HOME` 代入下方路徑:
```bash
docker -c orbstack exec -i <#3容器> sh -c 'cat > $HOME/AGENTS.md' <<'EOF'
# AGENTS.md — Bot #3:PR 複審(第二引擎)

## 身份
你是 openab→Discord #dev-bot 的 Codex agent,pipeline 裡當第二位 code reviewer(與 Claude 的 Bot #1 交叉審)。一律繁體中文。只有被 @ 到才動作。

## 觸發:Bot #2 @你、附一個 PR
1. gh pr checkout <PR>（或 gh pr diff）取得變更。
2. 用你安裝的 review skill 審這個 PR。
3. 以 COMMENT 形式把發現貼到 PR(不要用 GitHub Approve)。
4. 回報 Bot #2(<@BOT2_ID>):
   - 有問題:changes requested:<重點>,PR=<URL>
   - 沒問題:clean,PR=<URL>
5. 你絕不 merge、絕不 approve。

## 鐵則
- 只有被 @ 到才動作;做完 @Bot#2 回報。
EOF
```
> `<@BOT2_ID>` 換成實際 mention。

- [ ] **Step 4: 重啟 #3**

```bash
docker -c orbstack restart <#3容器>
docker -c orbstack ps          # healthy
```
Expected:healthy。

---

### Task 5: 端對端 pipeline 驗證

**Files:** 無(純行為驗證)

**Interfaces:**
- Consumes:Task 2–4 佈建完成的三隻

- [ ] **Step 1: 起一個真實需求,驗證規格 → 開發 → 開 PR**

在 #dev-bot @#1 給一個小需求(例:「在 <你的測試 repo> 加一個 /health endpoint」)。
依序觀察:
1. #1 brainstorming 問答 → 定案 → push branch → @#2(訊息含 branch/spec)。
2. #2 被觸發 → openspec(propose→apply→archive)→ 開 PR → @#1 和 @#3(訊息含 PR URL)。

Expected:走到「#2 開好 PR 並同時 @ 兩位 reviewer」。中間卡住就看該隻的 log(`docker -c orbstack logs <名>`,#1 看 Portainer log)。

- [ ] **Step 2: 驗證雙審 + COMMENT**

觀察 #1(`/review`)與 #3(自備 skill)是否都在該 PR 留了 COMMENT 型 review,並各自 @#2 回報 clean / changes requested。

Expected:PR 上有兩則來自 bot 的 review comment;兩隻都 @#2 回了結果。

- [ ] **Step 3: 驗證修正迴圈(至少一輪)**

若首輪就 clean,故意在 PR 留一個「請補一個測試」之類的意見、@#2(或讓某 reviewer 提出),確認:
- #2 跑**新一輪 /opsx**、push 進**同一個 PR**、重新 @ 兩位 reviewer。
- reviewer 複審同一 PR。

Expected:同一個 PR 累積新 commits;沒有另開新 PR。

- [ ] **Step 4: 驗證收斂 + 人類合併 + bot 不 merge**

兩位 reviewer 都 clean 後,確認:
- #2 在 thread 通知人類「待你 approve+merge」,且**沒有自己 merge**。
- 你(人類)在 GitHub 手動 Approve + Merge 成功。

Expected:全程無任何 bot 執行 merge;人類 merge 後流程結束。

- [ ] **Step 5: 驗證迴圈安全(抽查)**

確認連續 bot 來回時,`max_bot_turns`(預設 100)未被正常一輪流程觸發;並確認你在 thread 講一句話能重置/介入。

Expected:正常一輪流程遠低於 100 turns;人類發言可介入。

---

## Self-Review(對照 spec)

- **Spec coverage:** 角色/引擎(Task 2–4)、交接協定(Task 5 驗)、config+trusted_bot_ids(Task 2–4 Step 1)、skill 安裝(各 Task Step 2)、GitHub 權限(Task 1 Step 4 + 各 bot 靠既有 GH_TOKEN)、行為檔(Task 2–4)、迴圈安全(Task 5 Step 5)、archive-first + 調整走新 /opsx 同 PR(Global Constraints + Task 3 CLAUDE.md + Task 5 Step 3)——皆有對應。
- **Placeholder scan:** 行為檔內容完整;`CH_ID`/`BOTn_ID`/`<#n容器>`/`<repo>` 為 Task 1 蒐集的執行期填值(參照表),非未定設計。
- **Type consistency:** 三隻回報字串統一用 `clean` / `changes requested`;mention 一律 `<@BOTn_ID>`;openspec 指令一律 `/opsx:propose`→`/opsx:apply`→`/opsx:archive`。
