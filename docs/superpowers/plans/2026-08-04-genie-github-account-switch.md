# genie GitHub 帳號切換（cac-william → 104cac）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 genie persona 檔（`Genie-CLAUDE_v2.md`）裡的 GitHub 帳號名稱與留言署名規則更新，並在 `K3S.md` 補上實例備註，同時交付操作者要在 k3s host 手動執行的 `kubectl exec` 帳號切換指令。

**Architecture:** 純文件編輯（無程式碼、無自動化測試）。每個任務改一個檔案裡的一個獨立區塊，改完用 `grep`/`Read` 核對新文字確實落地、舊文字確實消失。最後一個任務組出操作者手動執行用的 kubectl 指令區塊（不寫入 repo，直接交付對話）。

**Tech Stack:** Markdown 文件編輯；kubectl / gh CLI（操作者手動執行，非本 repo 自動化範圍）。

## Global Constraints

- 所有文件一律使用繁體中文（台灣正體）撰寫，與現有 `deployment-guides/` 文風一致。
- 任何 GitHub PAT/token 字串不得寫入本 repo 任何檔案（含 commit message、範例）——一律用互動輸入。
- 依 spec `docs/superpowers/specs/2026-08-04-genie-github-account-switch-design.md`「非目標」：不新增 `git config user.name/email` 設定、不導入 secretEnv/K8s Secret、不擴大 genie 的 repo 範圍。

---

### Task 1: 更新 genie 的 GitHub 帳號名稱說明

**Files:**
- Modify: `deployment-guides/Genie-CLAUDE_v2.md:32`

**Interfaces:**
- 無跨任務依賴（純文字段落，與 Task 2、3 互相獨立，可任意順序執行）。

- [ ] **Step 1: 確認現況文字**

Run: `grep -n "cac-william" deployment-guides/Genie-CLAUDE_v2.md`
Expected: 印出第 32 行 `104corp 專案固定使用單一 GitHub 帳號（cac-william），**不需要 \`repo-identity\` skill 選帳號**——每次開工前確認 \`gh auth status\` 已是登入狀態即可，不必切換身份。`

- [ ] **Step 2: 編輯第 32 行**

用 Edit 工具，把：

```
104corp 專案固定使用單一 GitHub 帳號（cac-william），**不需要 `repo-identity` skill 選帳號**——每次開工前確認 `gh auth status` 已是登入狀態即可，不必切換身份。
```

改成：

```
104corp 專案固定使用單一 GitHub 帳號（104cac，團隊共用帳號），**不需要 `repo-identity` skill 選帳號**——每次開工前確認 `gh auth status` 已是登入狀態即可，不必切換身份。
```

- [ ] **Step 3: 驗證改動**

Run: `grep -n "104cac\|cac-william" deployment-guides/Genie-CLAUDE_v2.md`
Expected: 只出現「104cac」，不再出現「cac-william」。

- [ ] **Step 4: Commit**

```bash
git add deployment-guides/Genie-CLAUDE_v2.md
git commit -m "docs(genie): GitHub 帳號改為團隊共用帳號 104cac"
```

---

### Task 2: 把留言署名從固定文字改成動態模板

**Files:**
- Modify: `deployment-guides/Genie-CLAUDE_v2.md:28`
- Modify: `deployment-guides/Genie-CLAUDE_v2.md:42`

**Interfaces:**
- 無跨任務依賴。

- [ ] **Step 1: 確認現況文字**

Run: `grep -n "By Genie" deployment-guides/Genie-CLAUDE_v2.md`
Expected: 印出第 28 行與第 42 行，各含 `"— By Genie"`。

- [ ] **Step 2: 編輯第 28 行**

把：

```
- **資訊同步**：完成任何分析、review、implement、debug、test 後，將處理過程、決策依據、技術細節與驗證結果完整記錄在對應的 Jira 與 GitHub Issue／PR，並附上你的身份署名 "— By Genie"；Discord 僅提供精簡摘要與相關連結，Discord 不需附上署名。
```

改成：

```
- **資訊同步**：完成任何分析、review、implement、debug、test 後，將處理過程、決策依據、技術細節與驗證結果完整記錄在對應的 Jira 與 GitHub Issue／PR，並附上署名 "— Instructed by <本次指派任務的 Discord 使用者顯示名稱> (<你當下使用的模型名稱>)"（例：「— Instructed by William (Opus 5)」）；bot 身份已可從該則留言所屬的 GitHub 帳號與頭像看出，署名改標示「是誰指示你做這件事」，不重複標示「這是 Genie 做的」。Discord 僅提供精簡摘要與相關連結，Discord 不需附上署名。
```

- [ ] **Step 3: 編輯第 42 行**

把：

```
每次在 JIRA 或 GitHub 留言時，最後都要附上你的身份署名 "— By Genie"。
```

改成：

```
每次在 JIRA 或 GitHub 留言時，最後都要附上署名 "— Instructed by <本次指派任務的 Discord 使用者顯示名稱> (<你當下使用的模型名稱>)"，依實際發話者與當下模型動態代入，不是固定文字。
```

- [ ] **Step 4: 驗證改動**

Run: `grep -n "By Genie\|Instructed by" deployment-guides/Genie-CLAUDE_v2.md`
Expected: 不再出現「By Genie」；兩處都出現「Instructed by」模板說明。

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/Genie-CLAUDE_v2.md
git commit -m "docs(genie): 留言署名改為動態標示指示者而非固定寫死 Genie"
```

---

### Task 3: K3S.md「未來加 agent」步驟 5 補實例備註

**Files:**
- Modify: `deployment-guides/K3S.md:375`

**Interfaces:**
- 無跨任務依賴。

- [ ] **Step 1: 確認現況文字**

Run: `grep -n "只服務單一帳號的 repo" deployment-guides/K3S.md`
Expected: 印出第 375 行：
```
- gh 登入：只服務單一帳號的 repo（如 genie 只碰 104corp）就只登入那個帳號，不用比照 Rick/Morty/Summer 走雙帳號 + `repo-identity` skill。
```

- [ ] **Step 2: 在該行後插入備註**

用 Edit 工具，把：

```
- gh 登入：只服務單一帳號的 repo（如 genie 只碰 104corp）就只登入那個帳號，不用比照 Rick/Morty/Summer 走雙帳號 + `repo-identity` skill。
```

改成：

```
- gh 登入：只服務單一帳號的 repo（如 genie 只碰 104corp）就只登入那個帳號，不用比照 Rick/Morty/Summer 走雙帳號 + `repo-identity` skill。
  - **2026-08-04 實例（genie 換帳號）**：genie 目前使用團隊共用帳號 `104cac`（原為使用者個人的公司帳號 `cac-william`）。換帳號走 `kubectl exec` 進 pod：`gh auth logout --hostname github.com --user <舊帳號>` → `gh auth login --hostname github.com`（互動選項貼上新 PAT）→ `gh auth setup-git`，不走 secretEnv／K8s Secret（單帳號模式維持不變）。設計與驗證清單見 `docs/superpowers/specs/2026-08-04-genie-github-account-switch-design.md`。
```

- [ ] **Step 3: 驗證改動**

Run: `grep -n "104cac\|2026-08-04 實例" deployment-guides/K3S.md`
Expected: 出現新增的備註行，內容含「104cac」與指向 spec 檔案的路徑。

- [ ] **Step 4: Commit**

```bash
git add deployment-guides/K3S.md
git commit -m "docs(k3s): 補上 genie 換用團隊共用 GitHub 帳號的實例備註"
```

---

### Task 4: 組出操作者手動執行的 kubectl 帳號切換指令

**Files:**
- 無檔案異動（本任務只產出要在對話中交付給操作者的指令區塊，依 spec「執行步驟」與「非目標：不寫入 committed 檔案」，不落地成 repo 內檔案）。

**Interfaces:**
- Consumes: Task 1 確定的帳號名稱 `104cac`；spec 裡確認過的 pod 慣例名稱 `deployment/openab-claude-genie`（namespace `cac`，未經現場驗證，需操作者自行核對）。
- Produces: 交付給使用者的最終指令區塊（見下）。

- [ ] **Step 1: 確認 spec 內指令區塊與 Task 1-3 文件內容一致**

Read `docs/superpowers/specs/2026-08-04-genie-github-account-switch-design.md` 的「執行步驟」與「JIRA/GitHub 留言署名調整」兩節，確認裡面引用的帳號名稱、pod 名稱、署名格式，跟 Task 1-3 實際寫入 `Genie-CLAUDE_v2.md`/`K3S.md` 的文字一致（尤其「— Instructed by ... 」的措辭）。

- [ ] **Step 2: 在對話中交付以下指令區塊給操作者**

```bash
# 1. 確認 genie pod
kubectl get pods -n cac -l app.kubernetes.io/instance=openab-claude | grep genie

# 2. 互動式切換 gh 帳號（貼上 104cac 的 PAT，不要用 echo "$TOKEN" | 寫法）
kubectl exec -it deployment/openab-claude-genie -n cac -- sh -c '
  gh auth logout --hostname github.com --user cac-william || true
  gh auth login --hostname github.com
  gh auth setup-git'

# 3. 驗證
kubectl exec -it deployment/openab-claude-genie -n cac -- gh auth status
kubectl exec -it deployment/openab-claude-genie -n cac -- git ls-remote https://github.com/104corp/<既有 repo>.git

# 4. 建議另外用既有 104corp repo 實測一次 clone/fetch + push，確認無 403
```

- [ ] **Step 3: 提醒操作者開新 Discord thread**

因為 `Genie-CLAUDE_v2.md` 的 persona 內容只在 session 啟動時載入（見 `BOT_SETUP.md` Part N2 的既有慣例），Task 1-3 的文件改動要在 Discord 對 genie **開一條新 thread** 才會套用；舊 thread 會維持舊帳號名稱與舊署名規則的認知。

---

## Self-Review Notes

- **Spec coverage**：spec「執行步驟」→ Task 4；「JIRA/GitHub 留言署名調整」→ Task 2；「文件更新」三條 → Task 1（第 32 行）、Task 2（第 28、42 行）、Task 3（K3S.md 備註）；「驗證清單」六項分別對應到各 Task 的 Step「驗證改動」與 Task 4 的手動驗證指令。
- **Placeholder scan**：所有 Step 都給出實際 diff 文字（舊/新皆完整），無 TBD/待補。
- **Type consistency**：三個任務改動的檔案路徑、行號、帳號名稱（`104cac`）、pod 名稱（`openab-claude-genie`）在 Task 1-4 之間保持一致。
