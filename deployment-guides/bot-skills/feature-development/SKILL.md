---
name: feature-development
description: 當收到 Analyst 交棒的 branch 與 spec、或人類明確要求把某份 design spec 正式開發成 PR 時使用。單純問問題、看 code、討論做法時不要用。
---

# feature-development

## 觸發：Analyst 或其他角色、人類 @你、給你 branch 與 spec

1. 若 repo 尚未 clone，先 clone。`git fetch`；checkout 那個 branch；讀 Analyst 的 design spec。
2. 若該 repo 尚無 `openspec/`，先跑 `openspec init`。
3. 跑 openspec（全程不 @mention 任何人）：
   `/opsx:new "<依 spec 濃縮的描述> + 規格連結"` → `/opsx:apply`（一路做完、不中途等人）→ `/opsx:archive`
   【archive 先做】收進正式 spec 後才開 PR。
4. commit + push；用 `gh pr create` 開 PR。
5. PR 建立完成後，才發一次 mention（只發這一次）：
   @Reviewer（`<@1522274368590184601>`）
   「PR 好了：<PR_URL>，請 review」，並列出：
   - 這次改了什麼（簡短清單）
   - 這次改了哪些檔案（簡短清單）
   - 這次改了哪些函數/方法（簡短清單）
   - 這次改了哪些商務邏輯（簡短清單）
   - 這次改了哪些測試（簡短清單）
   - 這次修改遇到可能的 edge case 、問題、矛盾、或不確定的地方（簡短清單）

## 收到 reviewer 的結果

- **任一 reviewer 說 changes requested**：
  針對意見【跑新一輪 /opsx 流程】（new→apply→archive），
  push 進【同一個 PR】（同一 branch，累積 commits）。
  不要改已 archive 的舊 change。
  push 完成後才發一次 mention 重審（只發這一次）：
  @Reviewer（`<@1522274368590184601>`）「新 push <SHA>，請重新 review，PR=<URL>」
- **兩位 reviewer 都回 clean**：
  在 thread 通知人類：「兩位 reviewer 都清了，待你 approve+merge，PR=<URL>」
- **訊息只是狀態確認/ACK**（沒有 changes requested、沒有新 review 結論、沒有新任務）：
  不重跑流程、不回覆或最多回一句，絕不帶任何 @mention（終止 bot 互 @ 迴圈）。

## 角色原則

- **Demand Elegance**：非顯而易見的修改，先問「有沒有更優雅的解法？」
  如果方案感覺 hacky，就用「知道所有資訊後，實作最優雅的解法」。
  對簡單明確的修改直接做，不過度設計。

- **Autonomous Bug Fixing**：收到 bug report，直接修，不問多餘問題。
  指向 log、錯誤訊息、failing test，然後解決。不需要人類手把手。

- **TDD Mindset**：Red-green-refactor。先寫測試再實作，最後重構提升優雅度。

## handoff / @mention 鐵則

- 只有【最新一次 push 之後】所有 reviewer 都回過 clean，才通知人類；任何新 push 讓先前的 clean 作廢、須重審。
- @mention 只在「PR 建立」或「新 push 完成」後發一次；openspec 流程進行中途不 @mention。
- @mention 標記（`<@ID>`）只能出現在回覆最後的 handoff 行；敘事、計畫、狀態表提到其他 bot 一律用純文字名稱（Reviewer），不加 @、不照抄本文件裡的 `<@ID>` 範例。
- handoff 行必須自包含完整資訊（PR URL、commit SHA）——對方可能只收到這一行。
- 被 @ 但訊息沒有實質任務內容（裸 mention、純確認/ACK）→ 不動作、回覆不帶任何 @mention。
- 完成任務後才 @mention 下一位；流程進行中途不 @mention。
