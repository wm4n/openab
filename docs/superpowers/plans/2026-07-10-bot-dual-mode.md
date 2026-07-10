# 三 Bot 雙模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把三隻 bot 從「常駐重流程」改成「預設工程師模式 + 按需觸發的 pipeline skill」，並收斂 heredoc drift，同時保留每隻角色個性。

**Architecture:** 三層模型——Layer 1 共用工程師基座（單一來源檔）、Layer 2 每隻個性（沿用現有語氣段）、Layer 3 意圖綁定的 pipeline skill（`requirement-analysis` / `feature-development` / `change-review`，按需觸發）。所有內容從現有 `Morty-CLAUDE.md` / `Rick-CLAUDE.md` / `Summer-AGENTS.md` 截取搬移，不重寫；skill 以 `superpowers:writing-skills` 產出。

**Tech Stack:** Markdown 文件 / openab ACP bot 部署（Claude + Codex）/ `~/.claude/skills/` filesystem skill / git checkout + symlink 交付。

## Global Constraints

- **沿用既有內容、不重寫：** skill 內文與瘦身 persona 一律從現有三份檔截取已驗證有效的描述，保留原措辭，只做搬移與明列的必要調整。
- **skill 以 writing-skills 產出：** 三個 SKILL.md 用 `superpowers:writing-skills` 建立，確保 frontmatter（`name` / `description`）與結構品質。
- **skill 命名意圖綁定、非技術綁定：** `requirement-analysis` / `feature-development` / `change-review`（不得出現 openspec / codex 於名稱）。
- **ACP 引用規則：** CLAUDE.md/AGENTS.md 用自然語言 skill 名稱引用（如「使用 requirement-analysis skill」），名稱＝ symlink 目錄名；**不要** `cat` SKILL.md。
- **Discord mention ID：** Rick `<@1519868630064562278>`、Morty `<@1521431781641818202>`、Summer `<@1522253638465093752>`。mention 只出現在回覆最後的 handoff 行。
- **繁體中文** 為 bot 回覆語言；本計畫文件亦以繁體中文撰寫。
- **skill 資料夾：** `deployment-guides/bot-skills/`。
- **不可改動：** pipeline 核心邏輯（openspec propose→apply→archive、reviewer clean 判定、never merge/approve、雙 GitHub 身份切換）與 openab config.toml 的 `allow_bot_messages`/`trusted_bot_ids` 機制。

---

## 內容來源對照矩陣（所有任務共用的搬移依據）

| 目的地 | 來源（檔案 §段落，行號） |
| --- | --- |
| `_shared/engineer-baseline.md`（Layer 1） | 三檔共用段：「開工前：依 repo owner 選 GitHub 身份」（Morty 11–27 / Rick 18–34 / Summer 19–35，三份 verbatim 相同）、「目標 Repo 規範」（Morty 173–183 / Rick 89–99 / Summer 66–76，相同）、「工作習慣與核心原則」內共用項（繁中、Self-Improvement Loop、No Laziness、Minimal Impact、Simplicity First）、各檔「鐵則」中的**通用**條（只被 @ 才動作、永不 merge/approve、不貼 token、Discord 精簡&mention 防護）。**新增**：工程師模式定義（見 Task 1）。 |
| Morty persona（Layer 2） | Morty 3–5（身份）、7–9（回覆語氣）、185 段內 Morty 專屬工程立場（Demand Elegance 分析端、Completeness、Spec Mindset）。 |
| Rick persona（Layer 2） | Rick 3–5、7–16、101 段內 Rick 專屬（Demand Elegance、TDD Mindset）。 |
| Summer persona（Layer 2） | Summer 3–5、7–17、78 段內 Summer 專屬（Demand Elegance review 端、Testing Lens）。 |
| `requirement-analysis`（skill） | Morty 29–39（觸發偵測，**移除**角色 D/PR 那條）、41–50（角色 A）、52–78（B1）、80–104（B2）、106–132（角色 C）、155–171（Repo 解析優先序）、145–153 鐵則中**handoff/mention** 條、185 段內 Autonomous Analysis（只產 spec）。**新增**：人工閘門（見 Task 2 / spec §5）。 |
| `feature-development`（skill） | Rick 36–40（每次開始前 lesson-learnt）、42–58（觸發：openspec 流程 + PR 建立後 mention）、60–71（收到 reviewer 結果）、73–75（完成後 lesson-learnt）、77–87 鐵則中 handoff/mention 條、101 段內 Autonomous Bug Fixing。 |
| `change-review`（Morty/Claude skill） | Morty 134–143（角色 D：`/review` + 回報 Rick）、鐵則中不 approve/不 merge 條。 |
| `change-review-codex`（Summer/Codex skill） | Summer 37–41（觸發）、43–54（步驟 1–3：`requesting-code-review` + inline COMMENT + 回報 Rick）、56–64 鐵則中 review 專屬條、78 段內 Autonomous Review（不修 code）、Testing Lens。 |

> **驗證原則（呼應 E002 教訓）：** 每個搬移任務結尾以 `grep` 核對關鍵句「有搬到目的地」且「已從瘦身 persona 移除」，避免只靠肉眼抽查。

---

## File Structure

- Create `deployment-guides/bot-skills/_shared/engineer-baseline.md` — Layer 1 共用工程師基座（**單一來源，不內嵌進 persona**；部署時由 setup 以 `cat baseline + persona > CLAUDE.md` 組合，方案 B）。
- Create `deployment-guides/bot-skills/requirement-analysis/SKILL.md` — Morty 分析→spec 流程 + 人工閘門。
- Create `deployment-guides/bot-skills/feature-development/SKILL.md` — Rick openspec 開發→PR 流程。
- Create `deployment-guides/bot-skills/change-review/SKILL.md` — Morty(Claude) PR 複審。
- Create `deployment-guides/bot-skills/change-review-codex/SKILL.md` — Summer(Codex) PR 複審。
- Modify `deployment-guides/Morty-CLAUDE.md` — 瘦身為 Layer 1+2+指路。
- Modify `deployment-guides/Rick-CLAUDE.md` — 同上。
- Modify `deployment-guides/Summer-AGENTS.md` — 同上。
- Modify `deployment-guides/BOT_SETUP.md` — K2/K3/K4 薄 heredoc + skill clone/symlink 安裝步驟 + Part K 導言。
- Create `deployment-guides/bot-skills/ROLLOUT-CHECKLIST.md` — 需 live bots 的人工驗證清單（本地無法自動跑）。

---

### Task 1: Layer 1 共用工程師基座 `_shared/engineer-baseline.md`

**Files:**
- Create: `deployment-guides/bot-skills/_shared/engineer-baseline.md`
- Source: `deployment-guides/Morty-CLAUDE.md:11-27,145-153,173-203`、`Rick-CLAUDE.md:105-108`、三檔共用段

**Interfaces:**
- Produces: 一份**獨立** Markdown 檔（Layer 1 共用基座），部署時由 setup script 以 `cat engineer-baseline.md <persona>.md > /home/node/CLAUDE.md` 組合成各 bot 完整脈絡（方案 B）。**不**內嵌進 persona 檔，repo 內只此一份。內含「本 bot 署名見 persona 署名表」的引用，實際 name/email 由各 persona 提供（Task 5）。

- [ ] **Step 1: 建立檔案骨架**

建立 `deployment-guides/bot-skills/_shared/engineer-baseline.md`，為一份可獨立閱讀的共用基座檔（部署時 cat 在各 persona 之前）。內含以下小節（順序如下）。

- [ ] **Step 2: 寫入「工程師模式（預設）」小節（新增內容，全文如下）**

```markdown
## 預設模式：資深工程師

你天生是一位頂級資深工程師，也是優秀的問題解決者。**只被 @ 到才動作**；被 @ 到但沒有實質任務（裸 mention、純確認/ACK）→ 不動作、回覆不帶任何 @mention。

未被要求走正式流程時，你就處於此模式：

- 回答程式、開發、repo 相關問題，也回答通用問題、協助各種疑難雜症。
- 讀 / 解釋 / 除錯 code、給建議與 diff。
- 被人類**明確要求**時，可 edit / commit / push / 開 PR（如同資深工程師直接動手）。
- **不**自動產出 design spec、**不** @ 其他 bot、**不**啟動任何接力流程。
- 永不 merge、永不 approve PR——那是人類的工作。

只有人類明確要求走正式流程（走流程 / 正式開發 / 開規格 / 正式 review），才改用對應的 pipeline skill。
```

- [ ] **Step 3: 搬入「開工前：依 repo owner 選 GitHub 身份」（自 Morty-CLAUDE.md:11-27，僅共用機制）**

自 `Morty-CLAUDE.md` 第 11–27 行搬入**共用機制**：從任務確定 owner/repo；owner→帳號規則（`wm4n`→wm4n 個人；`104corp`/`openabdev`/其餘→cac-william 公司；不明→問人類）；`gh auth switch --hostname github.com --user <帳號>`；clone 後對該 repo 設 **local** 署名（非 --global）；絕不把 `gh auth status`/`hosts.yml`/`git remote -v`（含 token）貼進 Discord。**署名的實際 name/email 值不放這裡**——本節表格的 name/email 欄寫「**見本 bot persona 的署名表**」，並註記「per-repo local 署名的 name/email 由各 bot persona 檔（Morty/Rick/Summer）提供」。細節部署步驟引用 BOT_SETUP.md Part F2。

- [ ] **Step 4: 搬入「目標 Repo 規範」（verbatim 自 Morty-CLAUDE.md:173-183）**

逐字複製「先讀 repo 的 CLAUDE.md/AGENTS.md」與優先序「本 bot 鐵則 > 角色職責 > Repo 規範 > 通用慣例」。

- [ ] **Step 5: 搬入共用「工作習慣與核心原則」**

自三檔 185/101/78 段取**共用**項：繁體中文、Self-Improvement Loop（lesson-learnt.md / user-preferences.md）、核心原則中的 No Laziness、Minimal Impact、Simplicity First。角色專屬項（Spec Mindset / TDD / Testing Lens / Autonomous X）**不放這裡**（歸各自 skill 或 persona）。

- [ ] **Step 6: 搬入共用「鐵則」**

自三檔鐵則取通用條：只被 @ 才動作、永不 merge/approve、不貼 gh status/token 進 Discord、Discord 回覆精簡（>2000 字會切段、mention 會複製到每段造成重複觸發）。handoff/@mention 相關條**不放這裡**（歸 skill）。

- [ ] **Step 7: 驗證關鍵句都在**

Run:
```bash
cd /Users/william.chao/workspace/ai/openab/deployment-guides
grep -c "依 repo owner 選 GitHub 身份\|目標 Repo 規範\|只被 @\|永不 merge\|Self-Improvement\|資深工程師" bot-skills/_shared/engineer-baseline.md
```
Expected: 數字 ≥ 6（六個關鍵句都出現）。

- [ ] **Step 8: Commit**

```bash
cd /Users/william.chao/workspace/ai/openab
git add deployment-guides/bot-skills/_shared/engineer-baseline.md
git commit -m "docs(bots): 新增 Layer 1 共用工程師基座 engineer-baseline.md"
```

---

### Task 2: `requirement-analysis` skill（Morty 分析→spec + 人工閘門）

**Files:**
- Create: `deployment-guides/bot-skills/requirement-analysis/SKILL.md`
- Source: `deployment-guides/Morty-CLAUDE.md:29-132,155-171,145-153,185-203`

**Interfaces:**
- Consumes: 由 Morty persona 以自然語言「使用 requirement-analysis skill」觸發。
- Produces: handoff 行格式 `<@1519868630064562278> repo=<owner/repo>, branch=feature/<ID>-<主題>, spec=docs/superpowers/specs/<檔名>.md, 追蹤=<JIRA單號或Issue編號>`（供 `feature-development` 接手）。

- [ ] **Step 1: 用 writing-skills 起 skill 骨架**

以 `superpowers:writing-skills` 建立 `requirement-analysis` skill，frontmatter：
```yaml
---
name: requirement-analysis
description: 當人類明確要求把需求、JIRA 票、GitHub Issue 或 crash 正式分析並產出 design spec 時使用。單純問問題、看 code、討論做法時不要用。
---
```

- [ ] **Step 2: 搬入觸發路由（自 Morty 29-39，移除角色 D）**

複製觸發偵測，保留：JIRA 票號 → JIRA 分析；GitHub Issue → Issue 分析；stack trace/crash → Bug 分析；純文字需求 → Brainstorming。**移除**「含 PR 連結 → 角色 D」那條（PR 複審已獨立為 `change-review` skill）。

- [ ] **Step 3: 搬入角色 A/B1/B2/C 步驟（verbatim 自 Morty 41-132）**

四個角色的執行步驟逐字搬入（含 `jira-fetch` 取票、`gh issue view`、`superpowers.brainstorming`、`superpowers.systematic-debugging`、branch 命名、spec 回貼 JIRA/Issue comment）。每個角色原本結尾的「@Rick handoff」步驟改為指向 Step 5 的人工閘門。

- [ ] **Step 4: 搬入 Repo 解析優先序（verbatim 自 Morty 155-171）**

整段複製（人類指定 > JIRA 欄位 > Issue URL > `104corp/cac-ai-rules/product-repo-map.md`；wm4n 任務不查公司對照表）。

- [ ] **Step 5: 寫入人工閘門（新增，取代自動 @Rick；全文如下）**

```markdown
## 產出 spec 後：人工閘門（不自動交棒）

1. 產出並 commit design spec 到 docs/superpowers/specs/，push 到 branch。
2. 在 thread 問人類：「spec 好了。要不要按流程開發？」
3. 人類確認要開發 →**先確認有可追蹤的 JIRA 單號或 GitHub Issue**：
   - 分析從既有票/Issue 起 → 沿用該編號。
   - 從自由需求（無單）起 → 先請人類提供或建立單號/Issue，取得後才繼續。
4. 才在回覆結尾 @Rick（`<@1519868630064562278>`），附：
   repo=<owner/repo>, branch=<branch>, spec=<路徑>, 追蹤=<單號或Issue編號>
5. 人類說不用開發 → 就停在 spec，不 @ 任何人。
```

- [ ] **Step 6: 搬入角色原則與 handoff 鐵則**

自 Morty 185 段搬入 Autonomous Analysis（只產 spec、不寫 code）、Spec Mindset、Completeness、Demand Elegance（分析端）；自 145-153 鐵則搬入 handoff/@mention 條（mention 只在最後 handoff 行、handoff 行自包含、完成才 @下一位、bot 互 @ 迴圈終止）。

- [ ] **Step 7: 驗證 skill 結構與內容**

Run:
```bash
cd /Users/william.chao/workspace/ai/openab/deployment-guides/bot-skills/requirement-analysis
head -4 SKILL.md | grep -q "name: requirement-analysis" && echo "frontmatter OK"
grep -c "jira-fetch\|systematic-debugging\|人工閘門\|要不要按流程開發\|追蹤=" SKILL.md
grep -q "github.com/.*pull/" SKILL.md && echo "警告：仍含 PR 複審內容（應已移除）" || echo "PR 複審已排除 OK"
```
Expected: `frontmatter OK`；第二個數字 ≥ 4；`PR 複審已排除 OK`。

- [ ] **Step 8: Commit**

```bash
cd /Users/william.chao/workspace/ai/openab
git add deployment-guides/bot-skills/requirement-analysis/SKILL.md
git commit -m "docs(bots): 新增 requirement-analysis skill（Morty 分析→spec + 人工閘門）"
```

---

### Task 3: `feature-development` skill（Rick openspec 開發→PR）

**Files:**
- Create: `deployment-guides/bot-skills/feature-development/SKILL.md`
- Source: `deployment-guides/Rick-CLAUDE.md:36-87,101-120`

**Interfaces:**
- Consumes: `requirement-analysis` 的 handoff 行（repo/branch/spec/追蹤）；或人類明確要求開發某 spec。
- Produces: PR 建立後 mention 行 `<@1521431781641818202> <@1522253638465093752> PR 好了：<URL>，請 review` + 改動清單；reviewer clean 後通知人類。

- [ ] **Step 1: 用 writing-skills 起 skill 骨架**

以 `superpowers:writing-skills` 建立，frontmatter：
```yaml
---
name: feature-development
description: 當收到 Morty 交棒的 branch 與 spec、或人類明確要求把某份 design spec 正式開發成 PR 時使用。單純問問題、看 code、討論做法時不要用。
---
```

- [ ] **Step 2: 搬入開發流程（verbatim 自 Rick 36-58）**

逐字搬入：每次開始前讀 `~/lesson-learnt.md`；clone/fetch/checkout branch、讀 spec；必要時 `openspec init`；`/opsx:new`→`/opsx:apply`→`/opsx:archive`（archive 先做）；commit+push；`gh pr create`；PR 建立後**才**發一次 mention（@Morty + @Summer）+ 六項改動清單。

- [ ] **Step 3: 搬入 reviewer 結果處理（verbatim 自 Rick 60-71）**

逐字搬入：任一 reviewer changes requested → 同一 PR 跑新一輪 opsx、累積 commits、push 後 @兩位重審；兩位都 clean → 通知人類待 approve+merge；純 ACK → 不重跑、不帶 mention。

- [ ] **Step 4: 搬入完成後 lesson-learnt + 角色原則 + handoff 鐵則**

自 Rick 73-75 搬入「完成後更新 lesson-learnt.md」；自 101 段搬入 Demand Elegance、Autonomous Bug Fixing、TDD Mindset（Red-green-refactor）；自 77-87 鐵則搬入 handoff/@mention 條（只在 PR 建立/新 push 後 @ 一次、handoff 行自包含、clean 作廢規則）。

- [ ] **Step 5: 驗證**

Run:
```bash
cd /Users/william.chao/workspace/ai/openab/deployment-guides/bot-skills/feature-development
head -4 SKILL.md | grep -q "name: feature-development" && echo "frontmatter OK"
grep -c "opsx:new\|opsx:apply\|opsx:archive\|lesson-learnt\|changes requested\|1521431781641818202" SKILL.md
grep -qi "openspec\|codex" <(head -4 SKILL.md) && echo "警告：技術名混入 frontmatter" || echo "frontmatter 意圖綁定 OK"
```
Expected: `frontmatter OK`；第二個數字 ≥ 5；`frontmatter 意圖綁定 OK`。

- [ ] **Step 6: Commit**

```bash
cd /Users/william.chao/workspace/ai/openab
git add deployment-guides/bot-skills/feature-development/SKILL.md
git commit -m "docs(bots): 新增 feature-development skill（Rick openspec 開發→PR）"
```

---

### Task 4: `change-review` skill（Morty/Claude 與 Summer/Codex 兩份）

**Files:**
- Create: `deployment-guides/bot-skills/change-review/SKILL.md`（Morty/Claude）
- Create: `deployment-guides/bot-skills/change-review-codex/SKILL.md`（Summer/Codex）
- Source: `deployment-guides/Morty-CLAUDE.md:134-143`、`Summer-AGENTS.md:37-64,78-99`

**Interfaces:**
- Consumes: `feature-development` 的 PR mention（PR URL / 新 push SHA）；或人類明確要求 review。
- Produces: 回報 Rick 行——有問題 `<@1519868630064562278> changes requested:<清單>,PR=<URL>`；沒問題 Morty 版 `<@1519868630064562278> clean，無 blocking，PR=<URL>` / Summer 版 `<@1519868630064562278> clean — ready to merge,PR=<URL>`。

- [ ] **Step 1: 用 writing-skills 起 Morty/Claude 版骨架**

以 `superpowers:writing-skills` 建立 `change-review`，frontmatter：
```yaml
---
name: change-review
description: 當收到一個 PR URL 或新 push（SHA）並被要求 review、或人類明確要求正式 code review 時使用。單純問問題、討論做法時不要用。
---
```

- [ ] **Step 2: 寫入 Morty/Claude 版內文（自 Morty 134-143）**

逐字搬入角色 D：用內建 `/review <PR 網址或編號>` 審 PR；以 COMMENT（非 Approve）貼發現；回報 Rick（有問題/clean 兩種格式）；絕不 merge、絕不 approve。

- [ ] **Step 3: 用 writing-skills 起 Summer/Codex 版骨架**

以 `superpowers:writing-skills` 建立 `change-review-codex`，frontmatter：
```yaml
---
name: change-review-codex
description: 當收到 Rick 交棒的 PR URL 或新 push，或人類明確要求正式 code review 時使用。單純問問題、討論做法時不要用。
---
```
> 註：`change-review-codex` 目錄名暫分開，待 Task 8 rollout 確認 Codex skill 載入格式後，可合併回單一 `change-review`（見 spec §7.1、§9）。

- [ ] **Step 4: 寫入 Summer/Codex 版內文（自 Summer 37-64,78-99）**

逐字搬入：步驟 1 用 `requesting-code-review` skill 取 diff；步驟 2 完整審查、inline COMMENT（非 Approve）；步驟 3 回報 Rick（有問題/clean 兩種格式）；Autonomous Review（不修 code、只指出問題）、Testing Lens、Critical 不可忽略。

- [ ] **Step 5: 驗證兩份**

Run:
```bash
cd /Users/william.chao/workspace/ai/openab/deployment-guides/bot-skills
head -4 change-review/SKILL.md | grep -q "name: change-review$" && echo "Morty 版 frontmatter OK"
grep -q "/review" change-review/SKILL.md && echo "Morty 用內建 /review OK"
head -4 change-review-codex/SKILL.md | grep -q "name: change-review-codex" && echo "Summer 版 frontmatter OK"
grep -q "requesting-code-review" change-review-codex/SKILL.md && echo "Summer 用 requesting-code-review OK"
grep -L "approve" change-review/SKILL.md change-review-codex/SKILL.md; echo "(上面若列出檔名代表該檔沒提 approve——需確認有寫『不 approve』)"
```
Expected: 四個 OK 都印出；兩檔都含「不 approve/不 merge」語句。

- [ ] **Step 6: Commit**

```bash
cd /Users/william.chao/workspace/ai/openab
git add deployment-guides/bot-skills/change-review/SKILL.md deployment-guides/bot-skills/change-review-codex/SKILL.md
git commit -m "docs(bots): 新增 change-review skill（Morty/Claude + Summer/Codex 兩份）"
```

---

### Task 5: 瘦身三份 persona 檔（Layer 2 個性 + 署名表 + 指路；**不含** baseline）

**Files:**
- Modify: `deployment-guides/Morty-CLAUDE.md`
- Modify: `deployment-guides/Rick-CLAUDE.md`
- Modify: `deployment-guides/Summer-AGENTS.md`

**Interfaces:**
- Consumes: 四個 skill 名稱（Task 2-4）。**不**內嵌 `engineer-baseline.md`（方案 B：部署時 cat 組合）。
- Produces: 三份薄 persona 檔（個性 + 本 bot 署名表 + 指路），供 Task 6 部署時與 baseline 組合。每份含各自的**署名表**（供 baseline 的「見 persona 署名表」引用）。

- [ ] **Step 1: 重寫 Morty-CLAUDE.md**

新結構（由上而下）：
1. 標題 + 身份（保留原 3-5 行文字）。
2. 回覆語氣（保留原 7-9 行 verbatim）。
3. 個人工程立場（自原 185 段擷取 Morty 專屬：分析端 Demand Elegance、Completeness、Spec Mindset，濃縮為 2-3 行）。
4. **本 bot 署名表**（供 baseline 的「見 persona 署名表」引用）：
```markdown
## 本 bot 署名（per-repo local git config 用）
| owner | git user.name | git user.email |
| --- | --- | --- |
| `wm4n`（個人） | `wm4n` | `<你的 wm4n GitHub 個人 email>` |
| `104corp`/`openabdev`/其餘 | `Agent(CAC) Morty` | `cac.agent.morty@104.com.tw` |
```
5. **指路段（全文如下）：**
```markdown
## 何時進入流程模式

預設就是上面的資深工程師模式。只有人類明確要求時才用對應 skill：
- 要求正式分析需求/JIRA/Issue/crash 並產 spec → 使用 requirement-analysis skill
- 要求正式複審某個 PR → 使用 change-review skill
其餘（問問題、看 code、討論、隨手幫忙）一律用預設模式，不 @ 其他 bot、不開流程。
```
移除原 29-171 的所有流程細節（已搬進 skill）。

- [ ] **Step 2: 重寫 Rick-CLAUDE.md**

同結構。個人工程立場取 Rick 專屬（Demand Elegance、TDD）。帳號表填 `Agent(CAC) Rick` / `cac.agent.rick@104.com.tw`。指路段：
```markdown
## 何時進入流程模式

預設就是上面的資深工程師模式。只有人類明確要求、或 Morty 交棒 branch+spec 時：
- 把 spec 正式開發成 PR → 使用 feature-development skill
其餘（問問題、看 code、討論、隨手幫忙）一律用預設模式，不 @ 其他 bot、不開流程。
```
移除原 36-87 流程細節。

- [ ] **Step 3: 重寫 Summer-AGENTS.md**

同結構。個人工程立場取 Summer 專屬（Demand Elegance review 端、Testing Lens）。帳號表填 `Agent(CAC) Summer` / `cac.agent.summer@104.com.tw`。指路段：
```markdown
## 何時進入流程模式

預設就是上面的資深工程師模式。只有人類明確要求、或 Rick 交棒 PR 時：
- 正式 code review 一個 PR → 使用 change-review-codex skill
其餘（問問題、看 code、討論、隨手幫忙）一律用預設模式，不 @ 其他 bot、不開流程。
```
移除原 37-64 流程細節。

- [ ] **Step 4: 驗證瘦身結果（流程移除、指路在、署名表在、baseline 不重複）**

Run:
```bash
cd /Users/william.chao/workspace/ai/openab/deployment-guides
for f in Morty-CLAUDE.md Rick-CLAUDE.md Summer-AGENTS.md; do
  echo "=== $f ==="
  grep -q "何時進入流程模式" $f && echo "指路段 OK"
  grep -q "本 bot 署名" $f && echo "署名表 OK"
  grep -q "gh auth switch\|目標 Repo 規範\|Self-Improvement" $f && echo "警告：baseline 內容不該出現在 persona（方案 B）" || echo "無 baseline 重複 OK"
  grep -c "opsx:\|角色 A\|角色 B1\|/opsx" $f | sed 's/^/流程殘留計數(應為0): /'
done
wc -l Morty-CLAUDE.md Rick-CLAUDE.md Summer-AGENTS.md
```
Expected: 每檔「指路段 OK」「署名表 OK」「無 baseline 重複 OK」；流程殘留計數為 0；行數明顯小於原始（各檔約 25–40 行內）。

- [ ] **Step 5: Commit**

```bash
cd /Users/william.chao/workspace/ai/openab
git add deployment-guides/Morty-CLAUDE.md deployment-guides/Rick-CLAUDE.md deployment-guides/Summer-AGENTS.md
git commit -m "docs(bots): 瘦身三份 persona 檔為 Layer 1+2+指路（流程移入 skill）"
```

---

### Task 6: 更新 BOT_SETUP.md（K2/K3/K4 + skill 安裝 + Part K 導言）

**Files:**
- Modify: `deployment-guides/BOT_SETUP.md`（K2 504-570、K3 572-745、K4 747-975、Part K 導言 488-490、附錄範例檔）

**Interfaces:**
- Consumes: `_shared/engineer-baseline.md`（Task 1）、瘦身後三份 persona 檔（Task 5）、四個 skill（Task 2-4）。
- Produces: 可據以部署的 runbook。部署時 `/home/node/CLAUDE.md`（Summer 為 AGENTS.md）由 **baseline + persona 兩檔組合**產生（方案 B），非單一 heredoc；新增 skill clone+symlink 步驟。

- [ ] **Step 1: 更新 Part K 導言（488-490）**

補一句雙模式說明：「三隻 bot 預設為資深工程師模式（隨手問答/看 code 不開流程）；被明確要求走流程時才觸發對應 pipeline skill。」

- [ ] **Step 2: 更新 K2（Morty）——CLAUDE.md 組合 + skill 安裝**

- 把 K2 內描述 CLAUDE.md 內容的條列（559-568）改為：CLAUDE.md ＝ `engineer-baseline.md`（共用基座）＋ 瘦身後 Morty persona（個性 + 署名表 + 指路），部署時組合。
- 原 heredoc 段改為**組合指令**（clone 後從 repo 兩檔 cat）：
```bash
# CLAUDE.md = baseline + persona（方案 B：部署時組合，repo 內單一來源）
CK=/home/node/github-repo/openab/deployment-guides
cat "$CK/bot-skills/_shared/engineer-baseline.md" "$CK/Morty-CLAUDE.md" > /home/node/CLAUDE.md
```
- 在既有 skill 安裝區塊（530-546）**新增** pipeline skill 的 clone+symlink：
```bash
# pipeline skill：clone openab repo（或 sparse-checkout bot-skills/）後 symlink 進 ~/.claude/skills/
git clone https://github.com/<owner>/openab.git /home/node/github-repo/openab 2>/dev/null || git -C /home/node/github-repo/openab pull
ln -sfn /home/node/github-repo/openab/deployment-guides/bot-skills/requirement-analysis /home/node/.claude/skills/requirement-analysis
ln -sfn /home/node/github-repo/openab/deployment-guides/bot-skills/change-review        /home/node/.claude/skills/change-review
ls -la /home/node/.claude/skills/   # requirement-analysis / change-review symlink 都在
```
> `<owner>` 依 spec §7.2 rollout 決定（openab repo 來源）。同一份 openab checkout 同時供 CLAUDE.md 組合與 skill symlink 使用。

- [ ] **Step 3: 更新 K3（Rick）——CLAUDE.md 組合 + skill 安裝**

- 原 heredoc 改為組合指令：`cat "$CK/bot-skills/_shared/engineer-baseline.md" "$CK/Rick-CLAUDE.md" > /home/node/CLAUDE.md`。
- 新增 symlink：`feature-development`。

- [ ] **Step 4: 更新 K4（Summer）——AGENTS.md 組合 + skill 安裝**

- 原 heredoc 改為組合指令：`cat "$CK/bot-skills/_shared/engineer-baseline.md" "$CK/Summer-AGENTS.md" > /home/node/AGENTS.md`。
- 新增 Codex skill 安裝（依 Codex 機制；若未定則標注「rollout 時確認 Codex skill 路徑」並先放 `change-review-codex` symlink 指令佔位）。
- 註：Codex 若不吃 filesystem skill（spec §9），退回把 `change-review-codex` 內文 embed 進 Summer-AGENTS.md（沿用既有 Summer 「skill 精華 embed」前例），此時組合後 AGENTS.md 仍＝ baseline + persona(含 review 流程)。

- [ ] **Step 5: 驗證 BOT_SETUP.md 一致性**

Run:
```bash
cd /Users/william.chao/workspace/ai/openab/deployment-guides
grep -c "requirement-analysis\|feature-development\|change-review" BOT_SETUP.md   # skill 安裝步驟都在
grep -c "資深工程師模式\|pipeline skill" BOT_SETUP.md                              # 雙模式導言在
grep -c "engineer-baseline.md" BOT_SETUP.md                                        # baseline+persona 組合指令在
# heredoc 內若仍有大段流程（角色 A/opsx 詳細步驟）代表沒瘦成功：
grep -n "角色 B1：JIRA 任務分析\|/opsx:apply.*一路做完" BOT_SETUP.md || echo "已無重流程內文 OK"
```
Expected: 第一個數字 ≥ 4；第二、三個 ≥ 1（Summer 若走 embed 退路，engineer-baseline 組合仍在）；`已無重流程內文 OK`。

- [ ] **Step 6: Commit**

```bash
cd /Users/william.chao/workspace/ai/openab
git add deployment-guides/BOT_SETUP.md
git commit -m "docs(bots): BOT_SETUP.md 改雙模式——薄 persona heredoc + pipeline skill 安裝步驟"
```

---

### Task 7: Rollout 驗證清單（需 live bots；本地產出文件）

**Files:**
- Create: `deployment-guides/bot-skills/ROLLOUT-CHECKLIST.md`
- Source: spec §9 風險、§10 驗收標準

**Interfaces:**
- Consumes: 全部前置任務產物。
- Produces: 部署到 Mac mini/Portainer 後由人類逐項打勾的驗證清單。

- [ ] **Step 1: 寫入清單（全文如下）**

```markdown
# 雙模式 Rollout 驗證清單（需 live bots）

## A. skill 載入
- [ ] 三隻容器 `ls -la ~/.claude/skills/` 都看到對應 pipeline skill 的 symlink（owner 正確、未斷鏈）。
- [ ] Morty：requirement-analysis + change-review；Rick：feature-development；Summer：change-review(-codex)。

## B. 自動觸發（spec §9 待驗）
- [ ] 對 Morty 說「幫我把這個需求正式開規格：…」→ 有觸發 requirement-analysis（產 spec + 問是否開發）。
- [ ] 對 Morty 說「這段 code 在幹嘛」→ **不**觸發 skill，直接以工程師模式回答。
- [ ] 若自動觸發不穩：確認 persona 指路行 + 人類明講「走流程」可拉起 skill。

## C. Codex（Summer）skill 支援（spec §9 待驗）
- [ ] Summer 容器能載入 change-review(-codex)；若不吃 filesystem skill，退回 AGENTS.md 內保留 review 流程（仍加 Layer 1+個性框架）。

## D. 脈絡檔交付（方案 B：baseline + persona 組合）
- [ ] 各容器 /home/node/CLAUDE.md（Summer 為 AGENTS.md）＝ engineer-baseline.md + 該 bot persona 組合結果；確認組合後含「共用基座 + 個性 + 署名表(該 bot 值) + 指路」且無重複、Claude Code 有載入。

## E. 端對端（沿用既有 K5 順序）
- [ ] Morty 分析→人工閘門→@Rick→Rick openspec 開 PR→Morty+Summer change-review→clean→人類 merge，全程 mention 只在 handoff 行、無 bot 互 @ 迴圈。
- [ ] 隨手問答不觸發任何 handoff。
```

- [ ] **Step 2: Commit**

```bash
cd /Users/william.chao/workspace/ai/openab
git add deployment-guides/bot-skills/ROLLOUT-CHECKLIST.md
git commit -m "docs(bots): 新增雙模式 rollout 驗證清單（需 live bots）"
```

---

## Self-Review（撰寫者自查，已完成）

**1. Spec coverage：**
- spec §3 三層模型 → Task 1（L1）、Task 5（L2 persona + 指路）、Task 2-4（L3 skill）。✓
- spec §4 三 skill 規格 → Task 2/3/4，description 逐字對應。✓
- spec §5 Morty 人工閘門 → Task 2 Step 5。✓
- spec §6 觸發機制 + 指路退路 → Task 2-4 description + Task 5 指路段。✓
- spec §7 檔案/部署結構 → File Structure + Task 6（clone+symlink）。✓
- spec §8 實作原則（沿用既有 + writing-skills）→ Global Constraints + 內容來源對照矩陣 + Task 2-4 明用 writing-skills。✓
- spec §9 風險 / §10 驗收 → Task 7 ROLLOUT-CHECKLIST。✓

**2. Placeholder scan：** `<owner>`（openab repo 來源）與 Codex skill 路徑為 spec §7.2/§9 明列的 rollout 決策點，非遺漏；已於步驟就地標注決策依據。無 TBD/TODO。

**3. 一致性：** skill 名稱（requirement-analysis / feature-development / change-review / change-review-codex）、mention ID、handoff 行格式在 Task 2↔3↔4 的 Interfaces 間對齊；baseline 的 `START/END` 標記在 Task 1 產出、Task 5 消費、Task 6 驗證，名稱一致。
