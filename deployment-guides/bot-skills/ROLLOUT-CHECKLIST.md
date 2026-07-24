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
- [ ] Rick 容器 `openspec config list` 確認 workflows 同時含 `propose` 與 `new`/`ff`（見 K3S.md Phase B3-⑥ 的一次性 profile 切換；沒切過的話 `/opsx:new` 會不存在，feature-development 第一步就卡住）。
- [ ] Morty 分析→人工閘門→@Rick→Rick openspec 開 PR→Morty+Summer change-review→clean→人類 merge，全程 mention 只在 handoff 行、無 bot 互 @ 迴圈。
- [ ] 承上，分別驗證 Rick 的兩條 openspec 分支都能跑：(a) 收到 Morty 交棒的 spec → new→ff→apply→archive；(b) 人類跳過 Morty 直接口頭交代需求 → propose→apply→archive。
- [ ] 隨手問答不觸發任何 handoff。
