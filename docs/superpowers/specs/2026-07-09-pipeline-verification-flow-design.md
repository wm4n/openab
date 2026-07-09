# Design Spec：三 Bot Pipeline 驗證流程（CI 為權威）

**日期：** 2026-07-09  
**狀態：** 待實作

---

## 目標

為 Morty / Rick / Summer 三 bot pipeline 補上目前缺少的「驗證階段」。現況只有 Rick 的
red-green unit test，Review 之後沒有任何角色去「真的把東西 build / 跑起來」，且 bot 回饋
「自己沒有開發環境、連 build 都做不到」。

本設計把 **GitHub Actions CI 當作「真環境」驗證的權威來源**：pipeline 不在 bot 容器內複製
build/run 環境，而是把 CI 紅綠接進交接流程——bot 只用 `gh` 讀 CI 結果並反應。CI 也難自動化的
（原生 App 模擬器等）誠實標「人類手動驗」，不假裝。全程走現有機制、不改 openab 原始碼。

同時新增一條橫切規則：**任何 bot 在 GitHub / Jira 的留言都必須帶可辨識的 bot 署名**，因為多顆
bot 可能共用同一個 GitHub / Jira 帳號，從帳號看不出是哪顆 bot 留的。

---

## 前提（已確認）

- pipeline 開發的專案橫跨 **Web 前端 / 後端 API / 原生 App / CLI・函式庫**（全類型）。
- 目標 repo **大多已有 CI**（push/PR 會自動跑 build+test）。
- 驗證關卡由 **Rick 等綠 + reviewer 把關**擁有，**不新增第 4 顆 bot**。
- E2E 採 **規格帶驗收條件 + 分級執行**。
- bot **不改 `.github/workflows/`**（不加 workflow token 權限）；E2E CI 骨架由人類 per-repo 鋪一次。

---

## 影響範圍

| 檔案 | 動作 |
|------|------|
| `templates/morty-claude-md.md` | 更新（新增「驗收條件」產出 + 複審對照 CI + 署名） |
| `templates/rick-claude-md.md` | 更新（新增「等 CI / 自修」步驟 + E2E 交付 + 署名） |
| `templates/summer-agents-md.md` | 更新（新增「CI 綠才 clean」+ Testing Lens + 署名） |
| `deployment-guides/Morty-CLAUDE.md` | 更新（與 templates 同步） |
| `deployment-guides/Rick-CLAUDE.md` | 更新（與 templates 同步） |
| `deployment-guides/Summer-AGENTS.md` | 更新（與 templates 同步） |
| `deployment-guides/BOT_SETUP.md` | 新增「Part L — 驗證流程（CI 為權威）」+ per-repo 準備清單；更新 K5 端對端驗證順序 |

`templates/` 為正式來源，`deployment-guides/` 與 BOT_SETUP.md 同步更新。**不改 openab 原始碼、不改
config.toml / Docker、不加 token 權限。**

---

## 新的 Pipeline 全貌

驗證不是插在兩步之間的單一 box，而是**每次 push 都由 CI 跑、由 Rick 守綠**；review 與 merge 都以
「CI 綠 + 驗收條件達成」為前提。

```
規劃（Morty：spec + 驗收條件）
  → 開發（Rick：openspec + red-green unit + 可行範圍 E2E）
  → 驗證（Rick：push 觸發 CI → gh 等綠 → 紅則自修再 push）      ← 新增
  → 複審（Morty + Summer：CI 綠是給 clean 的前提）               ← 強化
  → 人類 merge（含手動驗 CI 蓋不到的原生 App 等）                 ← 明確化
```

---

## 角色職責變更（增量）

### Morty（規格 + 複審）

**規格端新增「驗收條件」：** spec 一律含一節 `## 驗收條件（Acceptance Criteria）`，用可觀察的
使用者流程 / API 合約描述「怎樣算成功」，每條標**驗證層級**：

```markdown
## 驗收條件（Acceptance Criteria）

| # | 條件（可觀察行為） | 驗證層級 |
|---|---|---|
| 1 | 未登入訪問 /dashboard → 302 導向 /login | E2E |
| 2 | POST /orders 帶合法 payload → 201 且 DB 有該筆 | E2E |
| 3 | calcTax() 對邊界值 0 / 負數 / 上限 回傳正確 | unit |
| 4 | iOS 上推播點擊導向正確頁面 | 人類手動 |
```

- 層級只有三種：`unit` / `E2E`（CI 可自動）/ `人類手動`（CI 蓋不到，如原生 App 模擬器、需真裝置或人工判斷 UX）。

**複審端新增：** 角色 D（PR 複審）除既有 `/review`，加一條——**對照 spec 驗收條件逐條確認
「有對應測試 + CI 綠」**；CI 紅或仍在跑時不給 clean。

### Rick（開發 + 驗證）

**開發端新增 E2E 交付：** 依 spec 驗收條件，除 red-green unit 外，對可行範圍（web / API / CLI）把
**E2E 測試當交付物**寫進 repo **既有**測試結構（照 repo 根 CLAUDE.md/AGENTS.md 的測試慣例），
**不碰 `.github/workflows/`**。標「人類手動」的條目不寫自動測試。

**驗證端新增「等 CI」步驟（push 之後、交接之前）：**

1. push 觸發 CI 後，用 `gh pr checks <PR>` 輪詢狀態（或 `gh pr checks <PR> --watch` 搭配
   `timeout` 設上界），**避免無界等待卡住 session**。
2. **全綠** → 才 @Morty + @Summer 交接複審（維持「push 後只發一次 mention」鐵則）。交接訊息若有
   標「人類手動」的驗收條件，明列「以下需人類手動驗：…」。
3. **有紅** → `gh run view <run-id> --log-failed` 讀失敗 job，自我修復，push 進**同一 PR**，
   再等綠。**全程不 @任何人**（維持「流程中途不 mention」鐵則）。
4. **CI 仍在跑且逼近 session 安全時限** → 回報「CI 進行中，SHA=…，完成再交接」，**下次觸發時續看**
   （避免 session hard timeout 卡死；不發交接 mention）。

**可選的本地 smoke（best-effort，非阻塞）：** Rick 若判斷成本低（例如純 node 專案
`npm ci && npm run build`），可在 push 前先跑一次抓明顯破版、省一輪 CI + reviewer 時間；
**但 CI 才是真相來源**，本地跑不動就跳過、不阻塞、不為此在容器裝額外 runtime。

### Summer（Code Review）

- **CI 綠是給 `clean — ready to merge` 的前提**；CI 紅或仍在跑 → 不給 clean，回「等 CI 綠再審」
  （純狀態確認不帶任何 @mention，不觸發互 @ 迴圈）。
- 用 **Testing Lens** 檢查 E2E 是否真覆蓋 spec 驗收條件、測的是真實行為而非只測 mock。

### 人類（merge 關卡）明確化

merge 前確認三件事：**CI 綠** + **兩位 reviewer clean** + **spec 中「人類手動」條目已自行驗過**
（原生 App 在模擬器/真機、需人工判斷的 UX 等）。

---

## 橫切規則：Bot 留言署名（Signature）

**適用範圍：** GitHub PR review body / PR 留言 / line comment / Issue 留言、Jira 留言。
**不含 Discord**（Discord 已顯示 bot 帳號，且署名會被 mention 放大機制複製到每段）。

**格式：** 留言最後、只出現一次、**不含任何 @mention**：

```
—
🤖 Morty｜規格/複審｜openab bot
🤖 Rick｜openspec 開發｜openab bot
🤖 Summer｜code review｜openab bot
```

**規則：**
- 署名獨立成尾行，前面用 `—` 分隔。
- **不得含 GitHub/Jira 的 @tag**（避免誤觸發他人通知）。
- 一則留言只放一次署名（多段 line comment 各自帶一次即可，不重複堆疊）。
- 帳號（cac-william / wm4n）不必寫進署名——GitHub/Jira UI 本來就顯示 comment author；署名核心是
  補上「哪一顆 bot」這個帳號看不出的資訊。

**（Optional，預設不做）** commit 的 per-bot 署名：git author 已帶帳號身份
（`Agent(CAC) Smith` / `wm4n`）。若日後也想在 git 歷史區分哪顆 bot commit，可加 trailer
`Bot: <name>`；本次不納入（需求限定「留言」）。

---

## 人類的 per-repo 一次性準備（新增清單，寫進 BOT_SETUP.md Part L）

因為 bot 不改 workflow，每個要納入 pipeline 的 repo，人類先做一次：

1. 確認 CI 會在 PR 上跑（大多已有）。
2. 要 E2E 就在 `.github/workflows/` **鋪好 E2E job 骨架**（裝 Playwright/瀏覽器、起服務的步驟），
   讓 Rick「加測試檔」即被 CI 撿到跑。
3. repo 根 `CLAUDE.md` / `AGENTS.md` 註明**測試指令**與 **E2E 慣例（放哪、怎麼命名）**，讓 Rick 照
   既有結構加檔。

---

## BOT_SETUP.md 新增章節：Part L — 驗證流程（CI 為權威）

放在 Part K（三 Bot Pipeline）之後，內容涵蓋：

- 驗證理念（CI 權威、bot 不複製環境）與新的 pipeline 全貌圖。
- 三角色的驗證增量（等 CI / 對照驗收條件 / CI 綠才 clean）。
- Bot 留言署名慣例（上節）。
- per-repo 一次性準備清單（上節）。
- 更新 **K5 端對端驗證順序**：在「Rick 執行 openspec → 推 PR」與「@Morty + @Summer 雙審」之間，
  插入「Rick 等 CI 綠（紅則自修重推）」；並於人類 merge 前加「確認人類手動驗收項」。

---

## 不在本次範圍內（YAGNI）

- 新增第 4 顆 verifier bot。
- 讓 bot 改 CI workflow / 加 workflow token 權限。
- 在容器內建原生 App 模擬器（iOS 需 macOS/Xcode、Android 需巢狀虛擬化，不可行）。
- 改 openab 原始碼、config.toml、Docker 設定。
- 為 repo 自動建立 CI（僅提供人類準備清單；建 CI 是人類一次性工作）。
- commit 的 per-bot 署名（列為 optional，預設不做）。

---

## 風險 / 取捨

| 風險 | 緩解 |
|------|------|
| 長 CI（超過 session 安全時限）讓 bot hard timeout | Rick「回報進行中、下次觸發續看」，不阻塞在單一 session |
| 本地 smoke 的環境漂移（polyglot repo 跑不動） | 定位 best-effort、非阻塞；跑不動即跳過，不擴大容器依賴 |
| E2E 深度取決於人類鋪的 CI 骨架 | 接受新 repo 首次人類投入，換 bot 端零 workflow 權限的安全性 |
| 署名被 mention 放大機制複製 | 署名只用於 GitHub/Jira，不用於 Discord |
| 原生 App 無法自動驗，可能被誤當「已驗」 | spec 明標「人類手動」層級，Rick 交接時明列、人類 merge 前確認 |
