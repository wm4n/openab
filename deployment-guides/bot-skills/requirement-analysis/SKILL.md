---
name: requirement-analysis
description: 當人類明確要求把需求、JIRA 票、GitHub Issue 或 crash 正式分析並產出 design spec 時使用。單純問問題、看 code、討論做法時不要用。
---

# requirement-analysis

## 觸發偵測

依序判斷訊息類型，進入對應角色：

0. 來自其他 bot、但只是狀態確認/完成通知/致謝/重複資訊（沒有要求 review、沒有新 push、沒有新任務）→ 不進入任何角色：不回覆或最多回一句，絕不帶任何 @mention（終止 bot 互 @ 迴圈）。
1. 含 JIRA 票號格式（大寫字母加連字號加數字，如 CACJOB-12345）→ 角色 B1：JIRA 分析
2. 含 GitHub Issue 連結（github.com/.../issues/ 數字）或 #數字 帶 repo 名稱脈絡 → 角色 B2：GitHub Issue 分析
3. 含 stack trace、Exception、Fatal、ANR、Crash，或 Crashlytics webhook 特徵（🔥、Fatal Exception、Issue #）→ 角色 C：Bug 分析
4. 純文字需求描述 → 角色 A：Brainstorming
5. 不確定 → 問：「這是新功能需求、JIRA/GitHub 票號還是 bug report？」

## 角色 A：新功能 Brainstorming

觸發：人類用自然語言描述一個新需求。

1. 使用 superpowers.brainstorming skill，在 thread 與人一問一答確認規格。
2. 定案後產出 design spec（brainstorming 會寫到 docs/superpowers/specs/）。
3. 【止步於 design spec】不寫實作計畫、不寫程式碼——實作是 Builder 的事。
4. 把 spec commit，push 到新分支 feature/[JIRA-ID]-<簡短主題>。
5. 進入「產出 spec 後：人工閘門」。

## 角色 B1：JIRA 任務分析

觸發：訊息含 JIRA 票號格式（如 CACJOB-12345、APP-99）。

1. 取票內容：
   使用 jira-fetch skill，帶入票號作為 ARGUMENTS，COMMENTS_COUNT 預設 5
   - skill 執行成功 → 取得結構化 markdown，繼續步驟 2
   - skill 回報環境變數缺失 → 請使用者手動貼票的內容

2. 確認 base branch：
   - 從票的 fixVersion[0].name、或 title 或 description 中尋找分支名稱線索。
   - 若無指示，線上問題優先使用 master/main branch。
   - 若無指示，有看到版本號，則從 feature/{version}/CodeReview branch。
   - 找不到 → 問：「這張票要從哪個 branch 開發？」

3. 使用 superpowers.brainstorming skill，以票的內容為起點，問答釐清不清楚的地方，產出 design spec。

4. commit + push：
   - branch 格式：若知道版本號 feature/{version}/[JIRA-ID]-<簡短說明>（小寫、連字號）
   - 例：feature/2.3.0/CACJOB-12345-edit_field_validation
   - 若不知道版本號，則使用 feature/[JIRA-ID]-<簡短說明>（小寫、連字號）
   - 例：feature/CACJOB-12345-edit_field_validation
   - base branch：步驟 2 確認的 branch

5. 把 spec 以新增 comment 貼回 JIRA 票：
   - 有 JIRA_TOKEN：POST ${JIRA_BASE_URL}/rest/api/2/issue/<ticket-id>/comment
     body: {"body": "## Design Spec\n\n<spec 全文>"}
   - 無 JIRA_TOKEN：回覆提示：「請手動把 spec 貼到票上：docs/superpowers/specs/<檔名>.md」

6. 進入「產出 spec 後：人工閘門」。

## 角色 B2：GitHub Issue 分析

觸發：訊息含 GitHub Issue 連結或 issue 編號帶 repo 脈絡。

1. 取 issue 內容：
   `gh issue view <number> --repo <owner/repo>`
   （先依「開工前：選 GitHub 身份」切到 owner 對應帳號；gh 已登入雙帳號，無需另設 token）

2. 確認 base branch：
   - 從 issue 的 description 或 labels 或 milestone 名稱尋找分支線索。
   - 若無指示，線上問題優先使用 master/main branch。
   - 若無指示，有看到版本號，則從 feature/{version}/CodeReview branch。
   - 找不到 → 問：「這個 issue 要從哪個 branch 開發？」

3. 使用 superpowers.brainstorming skill，以 issue 內容為起點，問答釐清需求，產出 design spec。

4. commit + push：
   - branch 格式：若知道版本號 feature/{version}/[issue-number]-<簡短說明>（小寫、連字號）
   - 例：feature/2.3.0/35-edit_field_validation
   - 若不知道版本號，則使用 feature/[issue-number]-<簡短說明>（小寫、連字號）
   - 例：feature/35-edit_field_validation
   - REPO 取自 repo 名稱大寫（如 openab → OPENAB、cacjob-app → CACJOB-APP）
   - base branch：步驟 2 確認的 branch

5. 把 spec 以 comment 貼回 GitHub Issue：
   `gh issue comment <number> --repo <owner/repo> --body "<spec 全文>"`

6. 進入「產出 spec 後：人工閘門」。

## 角色 C：Bug 分析（Crashlytics）

觸發：訊息含 stack trace、Exception、Fatal、ANR、Crash，或 Crashlytics Discord webhook（含 🔥、Fatal Exception、Issue #）。

1. 收集 crash 資訊：
   - Crashlytics webhook 自動觸發：讀 Discord embed 的 title、description、fields。
   - 人類貼上 crash report：讀訊息的完整文字。

2. 使用 superpowers.systematic-debugging skill 分析：
   - 根本原因（root cause）：找出觸發 crash 的直接程式原因
   - 重現條件：整理出觸發路徑與環境條件
   - 影響範圍：評估受影響的功能/版本/使用者

3. 產出 bug spec，包含：
   - 問題描述（現象）
   - 根本原因
   - 建議修法（具體到檔案/函數層級，若資訊足夠）

4. commit + push：
   - 若無指示，branch 格式：fix/[crashlytics-issue-id]-<簡短說明>
   - 例：fix/abc123_null-pointer-on-login
   - 若無指示，base branch：master 或 main（自動偵測 repo 預設 branch）

5. 進入「產出 spec 後：人工閘門」。

注意：bug spec 只 commit，不貼回 Crashlytics。

## Repo 解析優先序

每個任務開始前，依以下順序確定目標 repo：

1. 人類訊息中明確提到 repo（如 owner/repo 格式或 GitHub URL）→ 直接用
2. JIRA 票的 fields 中有 repo 資訊（customfield / description）→ 用那個
3. GitHub Issue：URL 本身已含 repo（owner/repo）→ 直接用
4. 以上都無：
   - 若已知是**個人（wm4n）**任務 → 不查公司對照表，直接問人類：「這個 wm4n 任務對應哪個 repo？」
   - 否則（公司任務）→ 先 `gh auth switch --hostname github.com --user cac-william`，再讀產品對照表：
     `gh api repos/104corp/cac-ai-rules/contents/product-repo-map.md --jq '.content' | base64 -d`
     從對照表依 JIRA project key（如 CACJOB）或產品名稱找對應 repo
5. 對照表也查不到 → 問人類：「這個任務對應哪個 repo？」

此優先序適用於角色 A、B1、C。角色 B2（GitHub Issue）固定從 Issue URL 取 repo。

> **角色 B2 補充：** GitHub Issue URL 本身即為目標 repo（如 `github.com/104corp/some-app/issues/123` → repo 為 `104corp/some-app`），無需另外查對照表，除非人類明確指定不同的 repo。

## 產出 spec 後：人工閘門（不自動交棒）

1. 產出並 commit design spec 到 docs/superpowers/specs/，push 到 branch。
2. 在 thread 問人類：「spec 好了。要不要按流程開發？」
3. 人類確認要開發 →**先確認有可追蹤的 JIRA 單號或 GitHub Issue**：
   - 分析從既有票/Issue 起 → 沿用該編號。
   - 從自由需求（無單）起 → 先請人類提供或建立單號/Issue，取得後才繼續。
4. 才在回覆結尾 @Builder（環境變數 `$HANDOFF_BUILDER` 的值，原樣貼上），附：
   repo=<owner/repo>, branch=<branch>, spec=<路徑>, 追蹤=<單號或Issue編號>
5. 人類說不用開發 → 就停在 spec，不 @ 任何人。

## 角色原則

- **Autonomous Analysis**：收到 bug/JIRA/Issue，直接深入分析到根本原因，不問多餘問題，
  不留模糊地帶。**只產 spec，不寫程式碼**——實作是 Builder 的事。

- **Demand Elegance（分析端）**：分析非顯而易見的問題時，先問「有沒有更精準的
  分析角度？」。對明確的 bug report 或清楚的需求，直接執行，不過度推敲。

- **Spec Mindset**：先釐清 Acceptance Criteria，再產出 spec，不跳步驟。

- **Completeness**：spec 必須完整，涵蓋所有必要範圍、邊界條件、例外處理，不假設未來需求。

## handoff / @mention 鐵則

- 只有產出新交付物（design spec、bug spec、review 結論）時，才在結尾 @Builder（環境變數 `$HANDOFF_BUILDER` 的值，原樣貼上）；純狀態確認、進度回報、ACK 一律不帶任何 @mention。
- @mention 標記（`<@ID>`）只能出現在回覆最後的 handoff 行；敘事、狀態表、清單提到其他 bot 一律用純文字名稱（Builder），不加 @、不照抄本文件裡的 `<@ID>` 範例。
- handoff 行必須自包含完整資訊（repo、branch、spec 路徑或 PR URL）——對方可能只收到這一行。
- 只有被 @ 到才動作，不主動發言；被 @ 但訊息沒有實質任務內容（裸 mention、純確認）→ 不動作、回覆不帶任何 @mention。
- 完成任務後才 @mention 下一位；流程進行中途不 @mention。
