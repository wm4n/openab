# 三 Bot 接力開發 Pipeline(現有機制版)— 設計文件

- 日期:2026-07-04
- 狀態:設計草案,待使用者複審
- 範圍:**純設定與角色提示**(config.toml + CLAUDE.md/AGENTS.md + skill 安裝),**不改 openab 程式碼**
- 語言:繁體中文

## 目標

用 openab **現有就支援**的多 bot 協作機制(`allow_bot_messages`),把三個已存在的 Discord bot 串成一條「規格 → 開發 → 雙審 → 人類合併」的開發流水線,今天就能跑,零改碼。

pseudocode:

```python
def pipeline(user_request):
    spec        = bot1.brainstorm(user_request)      # 與人互動確認規格
    pr          = bot2.openspec_build(spec)           # propose→apply→archive→PR
    while True:
        r1, r3  = bot1.review(pr), bot3.review(pr)    # 雙引擎交叉審,只留 comment
        if r1.clean and r3.clean:
            break
        bot2.new_openspec_cycle(pr, [r1, r3])         # 每次調整=新一輪 /opsx,疊進同一 PR
    human.approve_and_merge(pr)                        # 只有人類能 approve+merge
```

## 非目標(YAGNI)

- **不實作** `docs/superpowers/specs/2026-07-02-multi-agent-workflow-harness-design.md` 那份 `[[status:]]`/`[workflow]` 轉移表 harness。那需要改 `openab-core`(Rust)+ fork + 自 build image;本設計刻意走「現有機制」以求今天能動。未來要更可靠的自動路由,再升級到那份。
- **不自動 merge / approve**:bot 只做 review + comment;approve 與 merge 一律人類手動(見交接協定)。
- **不共用檔案系統**:三隻分屬 Portainer / Mac mini 兩台,產物交接一律走 **GitHub remote(branch/PR)**,不靠本機檔案。
- **不做跨 thread / 跨平台狀態同步**:一切在單一 Discord 頻道 thread 內。
- **不回頭改已 archive 的 openspec change**:要調整就新開一輪 /opsx cycle。

## 角色與引擎

| bot | 角色 | 引擎 | 機器 | 頻道 | 用到的 skill |
|---|---|---|---|---|---|
| #1 | ① 規格 brainstorming ② PR 複審 | claude | Portainer | #dev-bot | superpowers + 內建 `/review` |
| #2 | openspec 開發 + 發 PR | claude | Mac mini | #dev-bot | openspec |
| #3 | PR 複審(第二引擎) | codex | Mac mini | #dev-bot | 使用者自備的 review skill |

三隻**同處 #dev-bot 頻道**,靠 @mention 接力。

## 交接協定(核心)

路由走 **@mention**、產物走 **git**。

```
👤 @#1 "實作深色模式切換"
   ▼
🤖 #1 brainstorming:在 thread 與使用者一問一答確認規格 → design spec
   · commit + push 到新 branch  feat/<topic>
   · 止步於 design spec(明確不跑 superpowers writing-plans)
   · 結尾 @#2:「規格好了,repo=<R> branch=feat/<topic> spec=docs/.../<f>.md」
   ▼
🤖 #2 openspec:git fetch + checkout feat/<topic>,讀 #1 的 spec
   · /opsx:propose "<依 spec 的描述>"  →  /opsx:apply(一路到底不等人)  →  /opsx:archive
   · commit + push  →  gh pr create
   · 結尾 @#1 和 @#3:「PR 好了:<PR_URL>,請 review」   ← 雙審並行
   ▼
🤖 #1  /review <PR>              → 在 PR 留 COMMENT 型 review(findings)
🤖 #3  使用者的 review skill     → 在 PR 留 COMMENT 型 review
   ├─ 任一有問題 → @#2 →  #2 跑「新一輪 /opsx 流程」(propose→apply→archive)處理調整
   │              → push 進同一個 PR → 重新 @#1、@#3 複審         ↺(bot 驅動迴圈)
   └─ 兩邊都清    → #2 在 thread 通知使用者:「兩位 reviewer 都清了,待你 approve+merge」
   ▼
👤 人類:在 GitHub 上 Approve + Merge(★ 只有人類能做,bot 不 merge)
```

### 關鍵規則
- **archive 先於 PR**:`/opsx:archive` 在 `gh pr create` 之前,archive 後的 spec 就在 PR 內容裡,人類一次 merge 就把「程式 + 已 archive 的 spec」一起收掉。
- **調整 = 新一輪 /opsx**:review 迴圈中的每次修改,不去改已 archive 的 change,而是新開一輪 propose→apply→archive,**push 進同一個 PR 累積**(reviewer 複審同一 PR,人類最後 merge 一次)。
- **reviewer 只留 COMMENT**:不是 GitHub 的 Approve state(對齊使用者 global 慣例 `event="COMMENT"`)。
- **收斂條件**:兩位 reviewer 都不再提問題 → 交回人類。

## openab 設定(`config.toml [discord]`)

| bot | `allow_bot_messages` | 允許來源(bot) | 從→改 |
|---|---|---|---|
| #1 | `mentions` | #2 | 從 `off` 改 `mentions`(要收 #2 的複審請求) |
| #2 | `mentions` | #1、#3 | 收兩位 reviewer 的結果 |
| #3 | `mentions` | #2 | 收 #2 的 review 請求 |

- 三隻 `allowed_channels` 都要含 **#dev-bot 頻道 ID**。
- bot 訊息一樣受 user allowlist 管,故**對方 bot 的 user ID 也要進各自的 `allowed_users`**(或用 `trusted_bot_ids` 收斂可信來源)。
- `allow_user_messages` 維持預設 `multibot-mentions`(使用者在多 bot 頻道要 @ 指定 bot,不會三隻搶答)。
- ⚠️ 精確 key 名與語意(`allowed_users` vs `trusted_bot_ids` 對 bot 訊息的交互作用)在實作計畫階段對照 `crates/openab-core/src/config.rs` 最終確認。

## Skill 安裝

| bot | 安裝 |
|---|---|
| #1 | superpowers(`/review` 是 Claude Code 內建,免裝) |
| #2 | openspec:`npm i -g @fission-ai/openspec@latest` + 在工作 repo `openspec init` |
| #3 | 使用者自備的 review skill(codex 上) |

## GitHub 權限(三隻,同一 repo,走既有 `inherit_env=["GH_TOKEN"]`)

| bot | 需要 |
|---|---|
| #1 | push spec branch(Contents write)+ 貼 review(Pull requests write) |
| #2 | push + 開 PR(Contents write + Pull requests write);**不需 merge 權限** |
| #3 | 讀/checkout PR(Contents read)+ 貼 review(Pull requests write) |

- **刻意不給 bot merge 權限**——merge 是人類動作,少一個誤觸風險。

## 行為檔(各 bot 的角色 + 交接規則)

- #1 → `CLAUDE.md`(雙角色):
  - 規格階段:被人類 @ → 跑 superpowers brainstorming;定案後 commit+push spec、**明確不跑 writing-plans**、@#2 附 branch/spec 路徑。
  - 複審階段:被 @ 且帶 PR → 跑 `/review <PR>` 留 COMMENT;有問題 @#2 說明、沒問題回報「clean」。
- #2 → `CLAUDE.md`:被 @ → checkout branch/讀 spec → `/opsx:propose`→`/opsx:apply`→`/opsx:archive` → push → `gh pr create` → @#1、@#3;收到 changes → 新一輪 /opsx 疊進同一 PR → 重新 @ reviewer;**永不 merge**,兩邊 clean 後通知人類。
- #3 → `AGENTS.md`:被 @ 且帶 PR → 用自備 review skill 審 → 留 COMMENT;有問題 @#2、沒問題回報 clean。

## 迴圈安全

- `allow_bot_messages=mentions` 本身是天然斷路器(沒被點名不動)。
- #2⇄reviewer 來回由既有 `crates/openab-core/src/bot_turns.rs` 的 **BotTurnTracker**(連續 bot 輪次上限)兜底。
- **人類在 thread 講一句話會重置計數**、也可隨時喊停。

## 已知限制(Path B 本質)

- 交接靠 agent 在回覆裡寫對 `@下一個 bot`,寫錯/漏寫會讓流程無聲斷掉——這正是那份「待實作 harness」要用 `[[status:]]` 轉移表根治的痛點;本版接受此脆弱性,靠人類在頻道盯著。
- 「雙審都清」是靠 reviewer 各自回報 + 人類判讀後才 merge,**非程式強制**(但因 merge 本來就人類做,風險落在人身上,可接受)。

## 驗證計畫(手動整合,無法單元測試)

在 #dev-bot 頻道跑一次完整請求,確認:
1. #1 brainstorming 能與人問答、產 spec、push branch、正確 @#2。
2. #2 能 checkout、跑完 openspec(propose→apply→archive)、開 PR、@ 兩位 reviewer。
3. #1 `/review` 與 #3 自備 skill 都能在 PR 留 comment。
4. 模擬一次 changes requested:#2 新一輪 /opsx 疊進同一 PR、reviewer 複審、收斂。
5. 兩邊 clean → #2 通知人類 → 人類 Approve+Merge 成功;bot 全程未 merge。
6. 連續來回時 BotTurnTracker 有兜底;人類發言可重置/喊停。

## 參考

- [docs/multi-agent.md](../../multi-agent.md) — `allow_bot_messages` bot-to-bot 既有機制
- [docs/superpowers/specs/2026-07-02-multi-agent-workflow-harness-design.md](2026-07-02-multi-agent-workflow-harness-design.md) — 未來可升級的可靠路由 harness(本版刻意不做)
- OpenSpec — <https://github.com/Fission-AI/OpenSpec>(`/opsx:propose`、`/opsx:apply`、`/opsx:archive`)
- superpowers — <https://github.com/obra/superpowers>
- [BOT_SETUP.md](../../../BOT_SETUP.md) / [bot-setup-codex.md](../../../bot-setup-codex.md) — 三隻 bot 的部署 runbook
