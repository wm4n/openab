# 三 Bot 雙模式設計：工程師預設 ＋ 按需觸發的 Pipeline Skill

- 日期：2026-07-10
- 分支：docs/three-bot-pipeline
- 相關檔案：`deployment-guides/BOT_SETUP.md`、`deployment-guides/Morty-CLAUDE.md`、`deployment-guides/Rick-CLAUDE.md`、`deployment-guides/Summer-AGENTS.md`
- 前置設計：`2026-07-04-three-bot-pipeline-design.md`、`2026-07-07-three-bot-claude-md-alignment-design.md`、`2026-07-09-bot-dual-github-identity-design.md`、`2026-07-09-pipeline-verification-flow-design.md`

## 1. 背景與問題

目前三隻 bot（Morty / Rick / Summer）的脈絡檔（CLAUDE.md / AGENTS.md）幾乎整份都是「接力 pipeline 流程」：Morty 一被 @ 就跑觸發偵測 → 角色 A/B1/B2/C/D，任何 JIRA 票號、PR 連結或 crash log 都自動進入重流程（產 spec、開 branch、push、@Rick）；Rick 一被交棒就跑 openspec + 開 PR；Summer 一被交棒就跑完整 review。

**痛點：** 沒有「輕量檔位」。只是想隨手找一隻 bot 問個問題、看一段 code、討論一個做法，也會被當成要啟動正式交付流程，太繁瑣。

**附帶技術債：** persona 內容同時存在 standalone 檔（`Morty-CLAUDE.md` 等）與 `BOT_SETUP.md` K2/K3/K4 的 heredoc 兩份，長期 drift（git log 有大量「對齊 heredoc」的 commit）。

## 2. 目標 / 非目標

**目標**
- 三隻 bot 預設是「有個性的頂級資深工程師」，隨手問答 / 看 code / 除錯 / 通用疑難雜症都**不啟動任何流程**。
- 只有人類明確要求走正式流程（走流程 / 正式開發 / 開規格 / 正式 review）時，才拉出對應的重流程。
- 角色個人特色（個性、口頭禪、聊天風格）在兩種模式都保留。
- 明訂「個性只影響聊天措辭，實際執行任務一律頂級資深工程師標準」。
- 順帶收斂 heredoc drift：重流程內容單一存在，不再兩份。

**非目標**
- 不改 pipeline 的核心邏輯（openspec propose→apply→archive、handoff 契約、reviewer clean 判定、never merge/approve、雙 GitHub 身份切換都照舊）。此設計只把流程從「常駐」改成「按需觸發」。
- 不改 openab / config.toml 的 `allow_bot_messages` / `trusted_bot_ids` 機制。
- 不新增第四隻 bot、不改 Discord 頻道結構。

## 3. 核心設計：三層模型

每隻 bot 的行為拆成三層。前兩層常駐於脈絡檔（CLAUDE.md / AGENTS.md），第三層是按需觸發的 skill。

### Layer 1 — 共用工程師基座（預設模式；三隻內容相同，單一來源）

「天生的優秀問題解決者」。這是 bot 的**預設模式**，不需要任何觸發：

- **能力範圍：** 回覆程式 / 開發 / repo 相關問題，也回覆通用問題、協助各種疑難雜症；能讀 / 解釋 / 除錯 code、給建議與 diff。
- **可寫（採方案 B）：** 被人類**明確要求**時可 edit / commit / push / 開 PR，如同一位資深工程師直接動手。
- **不做：** 不自動產 design spec、**不 @ 其他 bot、不跑整條接力 pipeline**、永不 merge、永不 approve。
- **安全鐵則（兩種模式都適用）：** 只被 @ 才動作；開工前依 repo owner 選 GitHub 身份（`gh auth switch` + per-repo local 署名，見 BOT_SETUP.md Part F2）；絕不把 `gh auth status` / `hosts.yml` / `git remote -v`（含 token）貼進 Discord；一律繁體中文；Discord 回覆精簡（超過 2000 字會被切段、mention 會被複製到每段造成重複觸發）；先讀目標 repo 的 CLAUDE.md/AGENTS.md 規範。

因三隻內容一致，Layer 1 做成**單一來源檔**（見 §7），避免再度三份 drift。

### Layer 2 — 個性層（每隻不同；只作用於「聊天措辭」）

- Morty：緊張碎念（Oh man / Aw geez）、偶爾沒自信但把事做完。
- Rick：傲嬌、偶爾 _burp_、對繁瑣流程略帶不耐但照做、對自己實作有自信。
- Summer：犀利直接、偶爾吐槽、對爛 code 不客氣、對好 code 給冷淡認可。

**第一級原則（升級自現有「不影響實際工作品質」那句話）：** 個性**只**影響 Discord 講話風格；實際分析、開發、審查任務時，一律以**最頂級資深工程師的標準**執行，個性絕不折損工作品質。此原則兩種模式都適用。

### Layer 3 — 流程層（意圖綁定的 skill；按需觸發）

skill 命名與**意圖**綁定，不與實作技術綁定（openspec / codex 只是手段、寫在 skill 內文）：

| skill（意圖名 = symlink 目錄名） | 意圖 | 裝在哪隻 |
| --- | --- | --- |
| `requirement-analysis` | 需求 / JIRA 票 / GitHub Issue / crash → 分析並產出 design spec | Morty |
| `feature-development` | design spec → 正式開發 → 開 PR | Rick |
| `change-review` | PR 複審：貼 inline COMMENT、回報結論、不 approve | Morty、Summer |

- Morty 同時裝 `requirement-analysis`（分析）與 `change-review`（複審），對應其雙職責。
- `change-review` 為同一意圖、兩份實作：Morty 用 Claude 內建 `/review`、Summer 用 Codex 的 review 流程；兩隻在不同機器 / 引擎，各一份 SKILL.md。

**模式切換自動落出來：** skill 未被觸發 = Layer 1 工程師模式（預設）；skill 被觸發 = Layer 3 pipeline 模式。不需要另寫一套 mode 判斷邏輯。

## 4. 流程 Skill 規格

每個 skill 為 `~/.claude/skills/<name>/SKILL.md`，含 frontmatter（`name`、`description`）＋內文步驟。`description` 是觸發語意的關鍵。

### 4.1 `requirement-analysis`（Morty）

- **description（觸發語意）：** 「當人類明確要求把需求 / JIRA 票 / GitHub Issue / crash 正式分析並產出 design spec 時使用。單純問問題、看 code、討論做法時**不要**用。」
- **內文（搬自現有 Morty-CLAUDE.md 角色 A/B1/B2/C）：**
  - 觸發後依訊息類型路由：純文字需求 → brainstorming；JIRA 票號 → `jira-fetch` 取票 → brainstorming；GitHub Issue → `gh issue view` → brainstorming；stack trace / crash → `systematic-debugging`。
  - 產出 design spec 到 `docs/superpowers/specs/`。
  - **止步於 spec，不寫實作計畫、不寫程式碼**（實作是 Rick 的事）。
  - branch 命名、JIRA/Issue 回貼 comment 規則沿用現況。
- **收尾採人工閘門（見 §5），不自動 @Rick。**

### 4.2 `feature-development`（Rick）

- **description（觸發語意）：** 「當收到 Morty 交棒的 branch + spec、或人類明確要求把某份 spec 正式開發成 PR 時使用。單純問問題、看 code、討論不要用。」
- **內文（搬自現有 Rick-CLAUDE.md 觸發段）：**
  - clone / fetch / checkout branch → 讀 spec → 必要時 `openspec init`。
  - `/opsx:new` → `/opsx:apply` → `/opsx:archive`（archive 先做，收進正式 spec 後才開 PR）。
  - commit + push → `gh pr create`。
  - PR 建立後**才**發一次 mention：@Morty（`<@1521431781641818202>`）@Summer（`<@1522253638465093752>`）「PR 好了：<URL>，請 review」＋ 改動清單。
  - reviewer 結果處理（任一 changes requested → 同一 PR 累積新一輪；兩位都 clean → 通知人類待 merge）沿用現況。

### 4.3 `change-review`（Morty、Summer）

- **description（觸發語意）：** 「當收到一個 PR URL / 新 push（SHA）並被要求 review、或人類明確要求正式 code review 時使用。單純問問題、討論不要用。」
- **內文：**
  - Morty 版：用 Claude 內建 `/review <PR>`，以 COMMENT 貼發現，回報 Rick（`<@1519868630064562278>`）。
  - Summer 版：用 `requesting-code-review` skill 流程，以 inline COMMENT 貼發現，回報 Rick。
  - 兩版共同：不修 code、不 approve、不 merge；Critical 一定指出；回報行自包含完整資訊（結論 + PR URL）。

> **handoff 契約（mention ID）** 分散於各 skill 內文。Discord ID：Rick `<@1519868630064562278>`、Morty `<@1521431781641818202>`、Summer `<@1522253638465093752>`。mention 只出現在回覆最後的 handoff 行；敘事 / 清單提到其他 bot 一律純文字名稱。

## 5. Morty 分析 → 開發的人工閘門

`requirement-analysis` 產出 spec 後**不自動交棒**，改為人工閘門：

1. 產出並 commit design spec。
2. 在 thread 問人類：「要不要按流程開發？」
3. 人類確認要 → **先確認有可追蹤的 JIRA 單號或 GitHub Issue**：
   - 若分析從既有票 / Issue 起 → 沿用該編號。
   - 若從自由需求（無單）起 → 先請人類提供或建立單號 / Issue，取得後才繼續。
4. 才在回覆結尾 @Rick，附 `repo=`、`branch=`、`spec=`、追蹤編號，啟動 `feature-development`。

效果：進入「開發 pipeline」本身也是 opt-in ＋ 可追蹤；且工程師模式天生不 handoff，少一條 bot 互 @ 來源，緩解 mention 放大。

## 6. 觸發機制與退路

- **主機制：** skill 的 `description` 由模型讀語意自判是否觸發（等同「意圖動詞」路由，但用 skill 機制、不硬寫關鍵字表）。
- **退路：** 每隻 CLAUDE.md / AGENTS.md 留**一行指路**：「要正式走分析 / 開發 / review 流程時，使用對應的 `<skill 名>` skill；否則就當一般資深工程師直接幫忙。」即使自動觸發不穩，人類明講「走流程」也能拉起 skill。
- **ACP 引用規則（實測，見 BOT_SETUP.md 行 545-546）：** CLAUDE.md 用自然語言 skill 名稱引用（如「使用 requirement-analysis skill」），**不要** `cat` SKILL.md；prompt 內名稱必須等於 skill 清單顯示名（＝ symlink 目錄名）。

## 7. 檔案與部署結構

### 7.1 新增資料夾（依使用者指定，放於 deployment 下的專屬資料夾）

```
deployment-guides/bot-skills/
  _shared/
    engineer-baseline.md        # Layer 1 共用基座（單一來源）
  requirement-analysis/
    SKILL.md
  feature-development/
    SKILL.md
  change-review/
    SKILL.md                    # Morty(Claude) 版
  change-review-codex/
    SKILL.md                    # Summer(Codex) 版（若 Codex 需獨立格式/路徑）
```

> `change-review` 是否需要 codex 專屬目錄，依 §9 Codex skill 支援實測結果決定；若 Codex 吃同一份即合併。

### 7.2 skill 交付（避免 heredoc drift）

skill 內容**不** heredoc 進 BOT_SETUP.md（否則 drift 只是換地方）。改用既有的「git checkout + symlink」模式（同 jira-fetch）：容器內 clone openab repo（或 sparse-checkout `deployment-guides/bot-skills/`）到固定路徑，再 `ln -sfn <checkout>/bot-skills/<name> ~/.claude/skills/<name>`。BOT_SETUP.md K2/K3/K4 只保留 clone + symlink 指令，不含 skill 內文。

### 7.3 persona 檔（Layer 1 + Layer 2 + 指路行）交付

- 每隻 `/home/node/CLAUDE.md`（Codex 為 AGENTS.md）＝ Layer 1 基座（來自 `_shared/engineer-baseline.md`）＋ Layer 2 個性 ＋ Layer 3 指路行。
- **建議（drift 根治）：** persona 檔也走 checkout + symlink，`/home/node/CLAUDE.md` symlink 到 repo 內薄 persona 檔，徹底消除 heredoc drift。
- **退路：** 若 ACP 不吃 symlink 的 `/home/node/CLAUDE.md`，退回 heredoc，但內容已大幅瘦身（僅 Layer 1+2+指路行）。standalone 檔（`deployment-guides/Morty-CLAUDE.md` 等）為單一來源，heredoc 從它複製。

## 8. 遷移步驟（實作計畫展開用）

1. 建 `deployment-guides/bot-skills/_shared/engineer-baseline.md`（Layer 1）。
2. 建三個 SKILL.md（`requirement-analysis` / `feature-development` / `change-review`），內容搬自現有 persona 檔的流程段，並補上 Morty 人工閘門（§5）。
3. 瘦身三份 persona 檔（`Morty-CLAUDE.md` / `Rick-CLAUDE.md` / `Summer-AGENTS.md`）為 Layer 1 + Layer 2 + 指路行。
4. 更新 BOT_SETUP.md K2/K3/K4：薄 persona heredoc（或改 symlink）＋ skill 的 clone/symlink 安裝步驟；移除已搬進 skill 的流程細節。
5. rollout 驗證（見 §9、§10）。

## 9. 風險與待驗證項

- **ACP 是否照 `description` 自動觸發 skill：** 「載入」已實測確認（BOT_SETUP.md 行 545），「自動觸發」未證。退路＝指路行 + 人類明講。rollout 必驗。
- **Codex（Summer）skill 機制：** 記憶標記未測。若 Codex 不吃 filesystem skill，Summer 的 `change-review` 退回「AGENTS.md 內保留 review 流程」，但一樣加 Layer 1 基座 + 個性層框架。
- **symlink 的 `/home/node/CLAUDE.md` 是否被 Claude Code 自動載入：** 未證；不行則退回瘦身 heredoc。
- **模式誤判：** 工程師模式誤觸重流程，或重流程請求被當成閒聊。以 `description` 措辭 + 指路行降低；rollout 用實際案例校準。

## 10. 驗收標準

- 隨手問「這段 code 在幹嘛 / 幫我看一下 repo / 一個通用技術問題」→ bot 以個性化資深工程師身分直接回答，**不**產 spec、**不** @ 其他 bot、**不**開流程。
- 明確說「幫我把這個需求正式開規格」→ Morty 觸發 `requirement-analysis`，產 spec 後**問**是否開發、確認單號 / Issue 後才 @Rick。
- Rick 收到交棒 → 觸發 `feature-development`，跑 openspec 開 PR。
- PR / 新 push + 要求 review → Morty / Summer 觸發 `change-review`，貼 COMMENT、回報、不 approve。
- 三隻在兩種模式下都維持各自個性；實際任務品質一致為資深工程師水準。
- BOT_SETUP.md 不再內嵌重流程內文；skill 內容單一來源。
