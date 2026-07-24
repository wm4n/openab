---
name: solo-feature-pipeline
description: 當人類要求把一個 104corp 專案的功能需求，從分析到開 PR 全部交給這隻 bot 一手包辦（不假手其他 bot 接力）時使用。單純問問題、看 code、討論做法時不要用；已有 handoff 交棒過來的 spec/branch 時改用 feature-development。
---

# solo-feature-pipeline

## 角色：從需求到 PR，一人全包

沒有其他 bot 接力（沒有 Analyst/Builder/Reviewer 分工），這隻 bot 自己走完需求分析、開發、審查、debug、收尾、開 PR 全部階段。104corp 專案固定用單一 GitHub 帳號（cac-william），**不需要 `repo-identity` skill 選帳號**。

## 步驟

### 1. 任務啟動：用 superpowers:brainstorming 釐清需求，人工閘門後才進開發

- 收到需求描述後，使用 `superpowers:brainstorming` 跟人類逐步確認範圍、驗收標準、邊界條件——不要一收到需求就動手寫 code。
- 確認清楚後，把理解到的規格**簡短講一次給人類確認**（repo、要改的行為、範圍），**明確問「要不要開始開發」**。
- 人類確認前不進入步驟 2；人類說不用開發，就停在這裡。

### 2. 開發：openspec `new → ff → apply`

1. 若目標 repo 尚無 `openspec/`，先跑 `openspec init`。
2. `/opsx:new "<依步驟 1 確認的規格濃縮描述>"` → `/opsx:ff` → `/opsx:apply`（全程不 @mention，這隻沒有其他 bot 可以交棒）。
   > ⚠️ `ff`/`new` 屬於 openspec 的 expanded workflow，需先 `openspec config profile` 切到有包含 `new`/`ff` 的 profile 再 `openspec update` 才會有這兩個指令——如果指令不存在，先確認這步有沒有做過（見部署 README）。
3. **archive 留到步驟 5 review 通過後才做**——不要提早 archive。

### 3. 自我審查：一定要派獨立 subagent，不能自己審自己

用 Task/Agent 工具開一個**全新、沒有共享目前開發 context** 的 subagent 去審查這次的 diff（可以用 `code-review`/`requesting-code-review` skill 的做法）。

> **鐵則：絕不在同一個對話 session 裡自己讀自己寫的 diff 評分。** 同一個 context 寫出來的假設，同一個 context 審不出來——這正是其他 pipeline 靠獨立 reviewer bot 互審的原因，這裡沒有第二隻 bot，就得用「全新 subagent」換取一樣的「新鮮視角」。

Subagent 回報時，除了 pass/fail，每個 finding 都要分類成以下兩種之一：
- **實作 bug**：程式碼沒有正確做到規格要求的事。
- **規格問題**：程式碼確實照做了，但這個規格本身跟需求對不起來、有遺漏、或矛盾。

### 4. 判斷結果與停損

```
review 結果？
├─ 全數 PASS → 進步驟 5（archive）
└─ 有 FAIL
    ├─ 任一 finding 是「規格問題」→ 停下，回步驟 1 找人類重新確認規格
    │                              （不要用 debug 手法硬修一個方向錯的東西）
    └─ 全部是「實作 bug」→ 用 systematic-debugging（或更適合的 skill）修
                          → 回步驟 3 重新審查，累計一輪
                          → 連續 3 輪都還是實作 bug 型失敗
                            → 停下，整理「試過什麼、為什麼還是不過」回報人類，
                              不要繼續無限迴圈
```

### 5. Archive

Review 真的全數通過後，才跑 `/opsx:archive`——收進正式 spec，這之後才代表這個 change 定案。

### 6. 建 PR + 通知

`gh pr create` 開 PR，然後在**發起這個任務的同一條 thread**回報最初提出需求的人類：PR 連結、這次改了什麼（簡短清單）、確認已通過自我審查。不需要 @mention 任何其他 bot。

## 目前刻意不做的事

- **不整合 Jenkins/Maestro 自動化驗收**（`docs/superpowers/specs/2026-07-12-bot-build-acceptance-capability-design.md` 描述的能力）。那份設計本身還沒 rollout（需要 Jenkins admin 加 acceptance stage、LLM 產 flow 的可靠度未驗證），現階段會讓核心迴圈卡在一個還沒穩的外部依賴上。等這條 pipeline 穩定跑過幾輪，才考慮接上去當作 PR 建立後的額外驗收步驟。

## 鐵則

- 開發前一定要人類明確確認「要不要開發」，不能自己判斷需求夠清楚就跳過確認。
- 審查永遠派全新 subagent，不自己審自己寫的東西。
- Review failure 先分類是實作 bug 還是規格問題，規格問題不要硬 debug、退回步驟 1。
- 連續 3 輪還是實作 bug 型失敗就停下回報人類，不要無限迴圈。
- Archive 只在 review 真正通過後做，不提早收尾。
- 全程不 @mention 其他 bot——這隻沒有交棒對象。
