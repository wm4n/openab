# Morty 擴充觸發來源設計

- 日期:2026-07-04
- 狀態:設計草案,待使用者複審
- 範圍:**純 CLAUDE.md 行為檔修改**,不改 openab 程式碼
- 語言:繁體中文

## 目標

擴充 Morty(Bot #1)的觸發來源,除現有的「人類描述新需求」與「PR 複審」外,新增:
1. **JIRA 單號** → 分析需求、brainstorming、產 spec、貼回 JIRA comment、@Rick
2. **GitHub Issue** → 同 JIRA 流程,改從 GitHub 取內容、貼回 issue comment
3. **Crashlytics bug report** → systematic-debugging 分析、產 bug spec、@Rick

全部在 CLAUDE.md 層完成,zero 改碼。

## 非目標(YAGNI)

- 不建 webhook server:Crashlytics 走 Discord webhook → Morty 讀 Discord 訊息
- 不自動 merge/approve
- 不做跨平台狀態同步
- Crashlytics bug spec 不貼回 Crashlytics(只 commit)

## 角色架構

Morty 共有四個角色,每次被 @ 時先做觸發偵測再進對應角色:

```
收到訊息
    │
    ├─ 含 PR 連結 / PR 編號          → 角色 D:PR 複審
    │
    ├─ 含 [A-Z]+-\d+(如 CACJOB-123) → 角色 B:JIRA 分析
    │
    ├─ 含 github.com/.../issues/\d+
    │  或 #\d+ 帶 repo 脈絡          → 角色 B:GitHub Issue 分析
    │
    ├─ 含 stack trace / Exception /
    │  Fatal / Crashlytics webhook   → 角色 C:Bug 分析
    │
    ├─ 純文字需求描述                 → 角色 A:Brainstorming
    │
    └─ 不確定                         → 問人類:
         「這是新功能需求、JIRA/GitHub 票號還是 bug report?」
```

## 角色 A:新功能 Brainstorming(現有,不變)

觸發:人類描述新需求。

1. 用 superpowers brainstorming skill 與人問答確認規格
2. 產出 design spec(寫到 `docs/superpowers/specs/`)
3. **止步於 design spec**,不跑 writing-plans、不寫程式碼
4. commit + push `feat/<簡短主題>`
5. @Rick 附 repo/branch/spec 路徑

## 角色 B:任務分析(JIRA / GitHub Issue)

### B-1 JIRA

觸發:訊息含 `[A-Z]+-\d+` 格式(如 `CACJOB-12345`)。

1. **取票內容**
   - 有 `JIRA_TOKEN` + `JIRA_BASE_URL` → 呼叫 JIRA REST API 取標題、描述、AC
   - 無 → 讀使用者貼在訊息裡的描述內容
2. **確認 base branch**
   - 從票的 fixVersion / sprint / custom field 截取 branch 名稱
   - 找不到 → 問人類:「這張票要從哪個 branch 開?」
3. 跑 superpowers brainstorming skill 釐清需求,產出 design spec
4. commit + push
   - branch 格式:`feature/[JIRA-ID]_<簡短說明>`
   - 例:`feature/CACJOB-12345_edit-field-validation`
   - base:步驟 2 取得的 branch
5. 把 spec 以 **新增 comment** 貼回 JIRA 票
   - 有 `JIRA_TOKEN` → 呼叫 JIRA comment API
   - 無 → 提示人類:「請手動把 spec 貼到票上:docs/.../<spec>.md」
6. @Rick 附 repo/branch/spec 路徑

**所需環境變數(選用):**
- `JIRA_TOKEN`:JIRA Personal Access Token 或 API token
- `JIRA_BASE_URL`:如 `https://yourorg.atlassian.net`

### B-2 GitHub Issue

觸發:訊息含 `github.com/.../issues/\d+` 或 `#\d+` 帶 repo 脈絡。

1. **取 issue 內容**
   - 用 `gh issue view <number> --repo owner/repo` 取標題、描述、labels
   - 直接用現有 `GH_TOKEN`,不需額外設定
2. **確認 base branch**
   - 從 issue labels / milestone 截取 branch 名稱
   - 找不到 → 問人類:「這個 issue 要從哪個 branch 開?」
3. 跑 superpowers brainstorming skill 釐清需求,產出 design spec
4. commit + push
   - branch 格式:`feature/[REPO大寫]-[issue-number]_<簡短說明>`
   - 例:`feature/OPENAB-123_edit-field-validation`
   - base:步驟 2 取得的 branch
5. 把 spec 以 **新增 comment** 貼回 GitHub Issue
   - `gh issue comment <number> --repo owner/repo --body "<spec 內容>"`
6. @Rick 附 repo/branch/spec 路徑

## 角色 C:Bug 分析(Crashlytics)

觸發:訊息含 stack trace、`Exception`、`Fatal`、`ANR`、`Crash`,或來自 Crashlytics Discord webhook(含 `🔥`、`Fatal Exception`、`Issue #` 等 pattern)。

1. **收集 crash 資訊**
   - Webhook 自動觸發:讀 Discord 訊息的 embed 內容
   - 人類貼上:讀訊息的文字內容
2. 用 **superpowers systematic-debugging** skill 分析:
   - 根本原因(root cause)
   - 重現條件
   - 影響範圍
3. 產出 bug spec(包含:問題描述、根本原因、建議修法)
4. commit + push
   - branch 格式:`fix/[crashlytics-issue-id]_<簡短說明>`
   - 例:`fix/abc123_null-pointer-on-login`
   - base:master/main(預設)
5. @Rick 附 repo/branch/spec 路徑(走雙審 pipeline,同新功能流程)

**注意:** Bug spec 只 commit,不貼回 Crashlytics。

## 角色 D:PR 複審(現有,不變)

觸發:被 @ 且訊息含 PR 連結或 PR 編號。

1. 用內建 `/review <PR>` 審 PR
2. 以 COMMENT 形式貼到 PR(不用 GitHub Approve)
3. 回報 Rick:有問題 → changes requested + 清單;沒問題 → clean
4. **絕不 merge、絕不 approve**

## 環境變數彙整

| 變數 | 用途 | 必要性 |
|------|------|--------|
| `GH_TOKEN` | GitHub clone/PR/issue comment | 必要(現有) |
| `JIRA_TOKEN` | JIRA API 取票 + 貼 comment | 選用(無則退回手動貼) |
| `JIRA_BASE_URL` | JIRA 實例網址 | 選用(與 JIRA_TOKEN 並用) |

在 config.toml `[agent] inherit_env` 加入需要的變數名稱。

## 鐵則

- 做完任何角色,結尾一定 @Rick(`<@1519868630064562278>`)。
- 只有被 @ 到才動作。
- **永不 merge、永不 approve PR**——那是人類的工作。
- 只有兩位 reviewer 都 clean 後,Rick 才通知人類合併。

## 已知限制

- 觸發偵測靠 pattern matching,極端情況可能判錯 → 靠 fallback 問句兜底。
- JIRA base branch 截取依賴票的 custom field 命名規範;若組織慣例不同需調整 pattern。
- Crashlytics webhook 格式若日後變更,需同步更新偵測 pattern。
