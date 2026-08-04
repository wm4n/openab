# genie 切換 GitHub 帳號設計（cac-william → 104cac）

- 日期：2026-08-04
- 分支：docs/three-bot-pipeline
- 狀態：設計定案，待執行

## 背景

genie 是四隻 bot 中的「獨立型」（見 `K3S.md`「未來加 agent」章節），不跟 Rick/Morty/Summer 接力，單獨包辦 104corp 專案的需求分析 → 開發 → 自我審查 → 開 PR 全流程。因為只服務單一 owner（104corp）、範圍固定，genie 從一開始就走**單帳號模式**，不像 Rick/Morty/Summer 用雙帳號 + `gh auth switch` + `repo-identity` skill（見 2026-07-09 雙身份設計 `2026-07-09-bot-dual-github-identity-design.md`）。

`deployment-guides/Genie-CLAUDE_v2.md` 第 32 行明訂：「104corp 專案固定使用單一 GitHub 帳號（cac-william）」。GitHub 憑證透過 `kubectl exec` 互動式 `gh auth login` 存進 genie pod 的 PVC（`~/.config/gh/hosts.yml`），token 本身從未進任何 committed 檔案（`values-secret-claude.yaml` 沒有 genie 的 `GH_TOKEN` 欄位；`K3S.md`「未來加 agent」步驟 5 只說「登入那個帳號」，沒點名是誰）。

現在要把這個「單一帳號」從 `cac-william`（使用者個人的公司帳號）換成 `104cac`（團隊共用帳號）。順帶處理同一份 persona 檔（`Genie-CLAUDE_v2.md`）裡另一個獨立的署名問題（見下方「JIRA/GitHub 留言署名調整」）。

## 目標與非目標

**目標**

- 把 genie 在 GitHub 上的操作身份（gh 登入）從 `cac-william` 換成 `104cac`。
- 把 genie 每次在 JIRA/GitHub 留言最後附的署名，從固定文字「— By Genie」改成動態模板，改標示「誰指示這個 bot 做這件事」而非「這是 genie 做的」（bot 身份已經能從 commit 的 GitHub 帳號與頭像看出來，不需要留言再說一次）。
- 更新對應文件，讓帳號歸屬清楚可查、之後接手的人不用猜。

**非目標**

- 不改變 genie 的單帳號模式（不導入 secretEnv/K8s Secret 正式化、不導入 `repo-identity` skill 雙帳號機制）。
- 不擴大或調整 genie 碰的 repo 範圍（仍是現有那些 104corp repo）。
- 不撤銷 `cac-william` 的 PAT 本身（只登出 genie pod 上的登入狀態，token 在 GitHub 上繼續有效，供其他用途使用）。
- **不設定/不變更 `git config user.name`／`user.email`**：commit 的身份已經由「用哪個 GitHub 帳號 push」（104cac）+ 該帳號頭像呈現，不需要額外用 git commit author 再標示一次「這是 genie」。

## 前提

- `104cac` 帳號已存在，且已有現成的 fine-grained PAT 可用（涵蓋 genie 需要的 104corp repo 範圍）。
- 使用者已持有該 PAT 字串，將自行於互動式指令中貼入，不寫入本文件或任何 committed 檔案。

## 執行步驟（操作者於 k3s host 透過 `kubectl exec` 執行）

1. 確認 genie pod 存在（deployment 名稱慣例為 `<release>-<agentKey>`，即 `openab-claude-genie`，namespace `cac`）：

   ```bash
   kubectl get pods -n cac -l app.kubernetes.io/instance=openab-claude | grep genie
   ```

2. 互動式切換 gh 帳號（以 `node` user 執行；PAT 用互動輸入，不要用 `echo "$TOKEN" | gh auth login` 寫法把 token 留在 shell history/指令列裡）：

   ```bash
   kubectl exec -it deployment/openab-claude-genie -n cac -- sh -c '
     gh auth logout --hostname github.com --user cac-william || true
     gh auth login --hostname github.com
     gh auth setup-git'
   ```

   > `gh auth login`（不加 `--with-token`）會走互動流程，其中一個選項是貼上既有 PAT（Paste an authentication token）；照畫面選這個選項貼上 104cac 的 PAT 字串即可。

3. 驗證：

   ```bash
   kubectl exec -it deployment/openab-claude-genie -n cac -- gh auth status
   # 應只看到 104cac 一個帳號，cac-william 已登出

   kubectl exec -it deployment/openab-claude-genie -n cac -- git ls-remote https://github.com/104corp/<既有 repo>.git
   # 確認無 403 / 無需帳密提示
   ```

4. 建議另外實測一次既有 104corp repo 的 clone/fetch + 一個 test commit，確認 push 順利、無 403（commit author 沿用 pod 現有 `git config`，本次不變更，見上「非目標」）。

## JIRA/GitHub 留言署名調整

現行 `Genie-CLAUDE_v2.md` 第 28、42 行要求每次在 JIRA/GitHub 留言最後附上固定文字「— By Genie」。這個資訊其實冗餘——GitHub 上的 commit/comment 本來就會顯示是哪個帳號（104cac）+ 頭像做的，不需要留言內容再說一次「這是 genie」。

真正有用、目前留言裡看不到的資訊，是「這次任務是誰在 Discord 指示 genie 做的」。因此把署名從固定文字改成動態模板：

- 舊：`— By Genie`
- 新：`— Instructed by <本次指派任務的 Discord 使用者顯示名稱> (<你當下使用的模型名稱>)`（例：`— Instructed by William (Opus 5)`）

這是**動態模板**，每次留言依當次實際情況代入，不是寫死某一個人名。

## 文件更新

- `deployment-guides/Genie-CLAUDE_v2.md` 第 32 行：
  - 舊：「104corp 專案固定使用單一 GitHub 帳號（cac-william）」
  - 新：「104corp 專案固定使用單一 GitHub 帳號（104cac，團隊共用帳號）」
- `deployment-guides/Genie-CLAUDE_v2.md` 第 28 行（資訊同步規則）與第 42 行（SOP 結尾規則）：署名由固定文字「— By Genie」改為上述動態模板「— Instructed by \<Discord 發話者\> (\<當下模型\>)」。
- `deployment-guides/K3S.md`「未來加 agent」步驟 5（第 375 行）補一句實例備註：genie 目前使用團隊共用帳號，換帳號走 `gh auth logout` + `gh auth login`（互動貼 PAT）+ `gh auth setup-git`，不走 secretEnv／K8s Secret。

## 驗證清單

- [ ] `gh auth status` 只剩 `104cac`
- [ ] 對既有 104corp repo `ls-remote`/fetch 無 403
- [ ] `Genie-CLAUDE_v2.md` 第 32 行帳號名稱已更新
- [ ] `Genie-CLAUDE_v2.md` 第 28、42 行署名規則已改為動態模板
- [ ] `K3S.md` 已補上備註
- [ ] 以上文件變更已 commit

## 未解 / 待執行時確認

- genie pod 目前實際的 deployment 名稱、pod 內既有 repo 路徑，需操作者在 k3s host 上以 `kubectl get pods -n cac` 現場確認後代入指令（本文件假設慣例名稱 `openab-claude-genie`，未經現場驗證）。
- 若 pod 內已有用 `cac-william` 身份 clone 過的 base clone（`/home/node/repos/104corp/...`），換帳號後其 remote URL 通常不綁 token（走 gh credential helper 的通用 HTTPS URL），理論上不需重新 clone；但仍建議照步驟 3-4 實測一次確認無殘留認證問題。
