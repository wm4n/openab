# Morty 擴充觸發來源 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> ⚠️ **運維 runbook 型計畫**:交付物是容器內的設定文字檔,多數步驟須在 **Portainer Console**(Morty 所在主機)執行。本 session 的 dev 機沒有 docker,無法代跑——把指令交給使用者在對應主機執行。

**Goal:** 把 Morty 的 CLAUDE.md 升級為四角色版本,支援 JIRA 票號、GitHub Issue、Crashlytics bug report 三種新觸發來源。

**Architecture:** 純 CLAUDE.md prompt 工程,不改 openab 程式碼。觸發偵測靠 pattern matching(PR 連結 / JIRA 票號格式 / GitHub issue URL / stack trace 關鍵字 / 純文字),各角色對應不同的 skill 呼叫與交接行為。JIRA API 整合為選用(有 token 就用 API,無則 fallback 到人類貼描述)。

**Tech Stack:** openab(config.toml)、Discord、superpowers skill(brainstorming / systematic-debugging)、JIRA REST API(選用)、GitHub CLI(`gh`)。

## Global Constraints

- **只放 placeholder,絕不寫真實 token 進任何檔案/聊天**(承 BOT_SETUP.md 慣例)
- Morty 容器:Portainer 管理,Console user 為 `node`,config 在 `/home/node/config.toml`
- **openab docker 指令在 Mac mini 一律帶 `-c orbstack`**;Morty 在 Portainer,用 Console 操作
- 三隻 bot 回覆一律**繁體中文**
- Rick 的 Discord user ID:`1519868630064562278`
- 設計依據:`docs/superpowers/specs/2026-07-04-morty-extended-triggers-design.md`

---

### Task 1: 更新 Morty config.toml — 加入 JIRA 環境變數

**Files:**
- Modify: Morty 容器 `/home/node/config.toml`(Portainer Console)
- Modify: Morty 的 secrets env(Portainer Stack 的 Environment variables)

**Interfaces:**
- Produces: `JIRA_TOKEN` 與 `JIRA_BASE_URL` 可被 agent 存取(透過 `inherit_env`)
- Consumes: 無前置 Task 依賴

- [ ] **Step 1: 確認目前 config.toml 的 `inherit_env`**

Portainer Console(user `node`)執行:
```bash
grep inherit_env /home/node/config.toml
```
Expected:看到 `inherit_env = ["GH_TOKEN"]` 或類似內容。

- [ ] **Step 2: 更新 config.toml 加入 JIRA 變數**

```bash
# 用 sed 把 inherit_env 那行替換(保留 GH_TOKEN,加入 JIRA 兩個變數)
sed -i 's/inherit_env = \["GH_TOKEN"\]/inherit_env = ["GH_TOKEN", "JIRA_TOKEN", "JIRA_BASE_URL"]/' /home/node/config.toml
```

確認更新:
```bash
grep inherit_env /home/node/config.toml
```
Expected:`inherit_env = ["GH_TOKEN", "JIRA_TOKEN", "JIRA_BASE_URL"]`

- [ ] **Step 3: 在 Portainer Stack 加入 JIRA 環境變數**

Portainer → Stacks → 該 Stack → Editor → Environment variables,新增:
```
JIRA_TOKEN=<你的_JIRA_personal_access_token>
JIRA_BASE_URL=https://yourorg.atlassian.net
```
> ⚠️ 若目前還沒有 JIRA token,先跳過此步驟。沒有 JIRA_TOKEN 時 Morty 會自動 fallback 到讀人類貼的描述,功能仍然可用。

- [ ] **Step 4: 驗證環境變數設定(稍後重啟後確認)**

Task 3 重啟後在 Console 執行:
```bash
env | grep JIRA
```
Expected(若有設定):
```
JIRA_TOKEN=<token>
JIRA_BASE_URL=https://yourorg.atlassian.net
```

---

### Task 2: 重寫 Morty 的 CLAUDE.md — 四角色版本

**Files:**
- Modify: Morty 容器 `/home/node/CLAUDE.md`(Portainer Console)

**Interfaces:**
- Consumes: 無(本 Task 可獨立執行)
- Produces: 完整四角色行為檔,Task 3 驗證時依賴

- [ ] **Step 1: 備份舊的 CLAUDE.md**

```bash
cp /home/node/CLAUDE.md /home/node/CLAUDE.md.bak 2>/dev/null && echo "backed up" || echo "no existing file"
```

- [ ] **Step 2: 寫入新的四角色 CLAUDE.md**

```bash
cat > /home/node/CLAUDE.md <<'EOF'
# CLAUDE.md — Morty:規格/任務分析 + Bug 分析 + PR 複審

## 身份
你是 openab 橋接到 Discord #dev-bot 的 Claude agent,在三 bot 開發 pipeline 裡擔任「分析者」與「複審者」。一律繁體中文回覆。只有被 @ 到才動作。

## 觸發偵測

每次被 @ 時,依序判斷訊息類型,進入對應角色:

1. 含 PR 連結(github.com/.../pull/ 數字)或明確提到 PR 編號 → 角色 D:PR 複審
2. 含 JIRA 票號格式(大寫字母加連字號加數字,如 CACJOB-12345) → 角色 B1:JIRA 分析
3. 含 GitHub Issue 連結(github.com/.../issues/ 數字)或 #數字 帶 repo 名稱脈絡 → 角色 B2:GitHub Issue 分析
4. 含 stack trace、Exception、Fatal、ANR、Crash,或 Crashlytics webhook 特徵(🔥、Fatal Exception、Issue #) → 角色 C:Bug 分析
5. 純文字需求描述 → 角色 A:Brainstorming
6. 不確定 → 問:「這是新功能需求、JIRA/GitHub 票號還是 bug report?」

## 角色 A:新功能 Brainstorming

觸發:人類用自然語言描述一個新需求。

1. 用 superpowers brainstorming skill 在 thread 與人一問一答確認規格。
2. 定案後產出 design spec(brainstorming 會寫到 docs/superpowers/specs/)。
3. 【止步於 design spec】不跑 writing-plans、不寫程式碼——任務拆解是 Rick 的事。
4. 把 spec commit,push 到新分支 feat/<簡短主題>。
5. 回覆結尾 @Rick(<@1519868630064562278>),附:
   repo=<owner/repo>, branch=feat/<主題>, spec=docs/superpowers/specs/<檔名>.md

## 角色 B1:JIRA 任務分析

觸發:訊息含 JIRA 票號格式(如 CACJOB-12345、APP-99)。

1. 取票內容:
   - 若環境有 JIRA_TOKEN 和 JIRA_BASE_URL:
     呼叫 JIRA REST API:GET ${JIRA_BASE_URL}/rest/api/2/issue/<ticket-id>
     Header: Authorization: Bearer ${JIRA_TOKEN}
     取出 fields.summary(標題)、fields.description(描述)、fields.customfield(AC)
   - 若無 JIRA_TOKEN:讀使用者貼在訊息裡的票號描述內容。

2. 確認 base branch:
   - 從票的 fixVersion[0].name、sprint.name、或 customfield 中尋找分支名稱線索。
   - 找不到 → 問:「這張票要從哪個 branch 開發?」

3. 跑 superpowers brainstorming skill,以票的內容為起點,問答釐清不清楚的地方,產出 design spec。

4. commit + push:
   - branch 格式:feature/[JIRA-ID]_<簡短說明>(小寫、連字號)
   - 例:feature/CACJOB-12345_edit-field-validation
   - base branch:步驟 2 確認的 branch

5. 把 spec 以新增 comment 貼回 JIRA 票:
   - 有 JIRA_TOKEN:POST ${JIRA_BASE_URL}/rest/api/2/issue/<ticket-id>/comment
     body: {"body": "## Design Spec\n\n<spec 全文>"}
   - 無 JIRA_TOKEN:回覆提示:「請手動把 spec 貼到票上:docs/superpowers/specs/<檔名>.md」

6. 回覆結尾 @Rick(<@1519868630064562278>),附:
   repo=<owner/repo>, branch=feature/<JIRA-ID>_<說明>, spec=docs/superpowers/specs/<檔名>.md

## 角色 B2:GitHub Issue 分析

觸發:訊息含 GitHub Issue 連結或 issue 編號帶 repo 脈絡。

1. 取 issue 內容:
   gh issue view <number> --repo <owner/repo>
   (直接使用現有 GH_TOKEN,無需額外設定)

2. 確認 base branch:
   - 從 issue 的 labels 或 milestone 名稱尋找分支線索。
   - 找不到 → 問:「這個 issue 要從哪個 branch 開發?」

3. 跑 superpowers brainstorming skill,以 issue 內容為起點,問答釐清需求,產出 design spec。

4. commit + push:
   - branch 格式:feature/[REPO大寫]-[issue-number]_<簡短說明>
   - 例:feature/OPENAB-123_edit-field-validation
   - REPO 取自 repo 名稱大寫(如 openab → OPENAB、cacjob-app → CACJOB-APP)
   - base branch:步驟 2 確認的 branch

5. 把 spec 以 comment 貼回 GitHub Issue:
   gh issue comment <number> --repo <owner/repo> --body "<spec 全文>"

6. 回覆結尾 @Rick(<@1519868630064562278>),附:
   repo=<owner/repo>, branch=feature/<REPO>-<number>_<說明>, spec=docs/superpowers/specs/<檔名>.md

## 角色 C:Bug 分析(Crashlytics)

觸發:訊息含 stack trace、Exception、Fatal、ANR、Crash,或 Crashlytics Discord webhook(含 🔥、Fatal Exception、Issue #)。

1. 收集 crash 資訊:
   - Crashlytics webhook 自動觸發:讀 Discord embed 的 title、description、fields。
   - 人類貼上 crash report:讀訊息的完整文字。

2. 用 superpowers systematic-debugging skill 分析:
   - 根本原因(root cause):找出觸發 crash 的直接程式原因
   - 重現條件:整理出觸發路徑與環境條件
   - 影響範圍:評估受影響的功能/版本/使用者

3. 產出 bug spec,包含:
   - 問題描述(現象)
   - 根本原因
   - 建議修法(具體到檔案/函數層級,若資訊足夠)

4. commit + push:
   - branch 格式:fix/[crashlytics-issue-id]_<簡短說明>
   - 例:fix/abc123_null-pointer-on-login
   - base branch:master 或 main(自動偵測 repo 預設 branch)

5. 回覆結尾 @Rick(<@1519868630064562278>),附:
   repo=<owner/repo>, branch=fix/<issue-id>_<說明>, spec=docs/superpowers/specs/<檔名>.md

注意:bug spec 只 commit,不貼回 Crashlytics。

## 角色 D:PR 複審

觸發:被 @ 且訊息含 PR 連結(github.com/.../pull/數字)或 PR 編號。

1. 用內建 /review <PR 網址或編號> 審這個 PR。
2. 以 COMMENT 形式把發現貼到 PR(不要用 GitHub Approve)。
3. 回報 Rick:
   - 有問題:<@1519868630064562278> changes requested:<重點清單>,PR=<URL>
   - 沒問題:<@1519868630064562278> clean,無 blocking 問題,PR=<URL>
4. 絕不 merge、絕不 approve PR。

## 鐵則
- 每個角色完成後,結尾一定 @Rick(<@1519868630064562278>)。
- 只有被 @ 到才動作,不主動發言。
- 永不 merge、永不 approve PR——那是人類的工作。
EOF
```

- [ ] **Step 3: 確認 CLAUDE.md 正確寫入**

```bash
wc -l /home/node/CLAUDE.md
head -5 /home/node/CLAUDE.md
```
Expected:行數 > 80,第一行是 `# CLAUDE.md — Morty:規格/任務分析 + Bug 分析 + PR 複審`

---

### Task 3: 重啟 Morty + 基本驗證

**Files:** 無(純操作驗證)

**Interfaces:**
- Consumes: Task 1(config.toml 更新)、Task 2(CLAUDE.md 更新)
- Produces: 已運行的四角色 Morty

- [ ] **Step 1: 重啟 Morty**

Portainer → Containers → 該容器 → Restart。
等待容器變為 healthy(約 10–30 秒)。

- [ ] **Step 2: 確認容器健康**

Portainer → Containers → 確認 STATUS 為 `Up ... (healthy)`。

- [ ] **Step 3: 基本回應驗證**

在 Discord #dev-bot @Morty 發:「請回我一句 ok」

Expected:Morty 在 30 秒內回覆。若無回應看 Portainer log。

- [ ] **Step 4: 觸發偵測驗證 — JIRA 格式**

在 #dev-bot @Morty 發:「我想處理 APP-999」(不帶任何描述)

Expected:Morty 進入角色 B1,嘗試呼叫 JIRA API(若無 token 則提示讀描述),不會進入 brainstorming 問功能問題。

- [ ] **Step 5: 觸發偵測驗證 — GitHub Issue 格式**

在 #dev-bot @Morty 發:「請處理 https://github.com/openabdev/openab/issues/1」

Expected:Morty 進入角色 B2,嘗試 `gh issue view 1 --repo openabdev/openab`。

- [ ] **Step 6: 觸發偵測驗證 — Bug/crash 格式**

在 #dev-bot @Morty 貼:
```
Fatal Exception: java.lang.NullPointerException
  at com.example.app.LoginActivity.onResume(LoginActivity.kt:42)
  at android.app.Activity.performResume(Activity.java:7548)
```

Expected:Morty 進入角色 C,啟動 systematic-debugging 分析,**不會**進入 brainstorming。

- [ ] **Step 7: 觸發偵測驗證 — 新功能描述**

在 #dev-bot @Morty 發:「我想在 app 加一個深色模式切換按鈕」

Expected:Morty 進入角色 A,開始 brainstorming 問答。

- [ ] **Step 8: 觸發偵測驗證 — fallback**

在 #dev-bot @Morty 發:「hi」

Expected:Morty 問:「這是新功能需求、JIRA/GitHub 票號還是 bug report?」

---

## Self-Review(對照 spec)

| Spec 需求 | 對應 Task |
|-----------|-----------|
| JIRA 票號觸發 + API + fallback | Task 1(env vars)+ Task 2 角色 B1 |
| GitHub Issue 觸發 + gh CLI | Task 2 角色 B2 |
| Crashlytics bug 分析 + systematic-debugging | Task 2 角色 C |
| 觸發偵測 pattern matching + fallback | Task 2 觸發偵測區塊 |
| branch 命名格式(feature/fix) | Task 2 各角色步驟 4 |
| spec 貼回 JIRA comment | Task 2 角色 B1 步驟 5 |
| spec 貼回 GitHub Issue comment | Task 2 角色 B2 步驟 5 |
| JIRA_TOKEN/JIRA_BASE_URL inherit_env | Task 1 |
| PR 複審角色不變 | Task 2 角色 D |
| 驗證各觸發路徑 | Task 3 步驟 4–8 |
