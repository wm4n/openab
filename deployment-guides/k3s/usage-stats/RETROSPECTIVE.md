# bot 使用統計報表／圖表層 —— 製作記錄

**範圍：** 只記錄 `report.py`／`render_html.py`／`aggregate.py` 這一層（報表產生與
圖表呈現）的最終結果與關鍵經驗，不含收集端三個 parser 的資料格式細節（那些已記在
`docs/superpowers/specs/2026-09-10-bot-usage-stats-design.md` 與
`deployment-guides/k3s/README.md`「統計資料源診斷」一節）。也不記錄過程中的討論
往返，只記結論。

**時間：** 2026-09-11（Task 1-13 依計畫實作）～ 2026-09-14（依實際使用回饋擴充）。

## 最終結果

- 19 個 commit，全部走 TDD（先寫會失敗的測試 → 確認失敗 → 最小實作 → 確認通過），
  最終 **251 個 unittest 全過**，只用標準庫。
- 四段管線：`events.py`（正規化事件型別）→ 三個 parser（`parse_claude_code.py`／
  `parse_codex.py`／`parse_opencode.py`）→ `collect.py`（CronJob 入口，含
  `--archive-root` 回填）→ `aggregate.py`（純函數指標）→ `report.py`（CLI，
  text／md 輸出）→ `render_html.py`（自帶資源單一 HTML，inline SVG 圖表）。
- 報表涵蓋：每日／每週任務數與對話數、token 用量（依 model）、成本（四來源分離）、
  活躍觸發者與逐使用者任務數、session 層 token／花費歸因（「誰在燒量」）、摩擦
  指標、失敗率代理、各頻道使用量、尖峰時段（小時／星期幾）分布。
- 設定檔支援 `channel_names`／`user_names`／`allowlist_bounds`，讓報表可以顯示
  真人姓名與頻道名稱而不是原始 Discord 數字 ID。
- **尚未完成**：CronJob 還沒實際部署到 k3s 節點（ConfigMap／PVC／apply 都還沒
  做），也還沒做過人工對照 Discord 訊息數的端對端驗收。

## 關鍵設計決策

### 1. 一份資料模型、三種 renderer 共用

`build_report()` 產生一個純 dict，`render_text`／`render_md`／`render_html` 各自
消費同一份 dict，不各自重算指標。理由是三種格式的「限制說明」（caveats）、
數字定義必須完全一致，讓同一件事在不同格式裡講得不一樣是最容易讓人失去信任的
錯誤。

### 2. 圖表用程式產生的 inline SVG，不用 JS 圖表庫

`render_html.py` 的 `stack_geometry`／`hbar_geometry` 是純函數，回傳座標，
`svg_stacked`／`svg_hbars` 只是把座標轉成 SVG 字串。好處：

- 幾何可以直接單元測試斷言座標（JS 圖表庫渲染的結果測不到）。
- 零外部依賴：`open report.html` 就能看，不需要 CDN、不需要任何 JS。
- 互動層（hover 顯示數值）用 SVG 原生 `<title>`（瀏覽器內建 tooltip），完全
  不需要 JavaScript。

### 3. 「日」和「週」共用同一套堆疊柱狀邏輯

`weekly_task_counts()`／`weekly_cost()` 把逐日指標捲成 ISO 週（`YYYY-Www`），
然後**直接餵給跟每日圖表一樣的 `svg_stacked`**——這兩支函數的輸入本來就只是
「一串類別標籤 + 每個標籤底下的數值」，標籤是不是日期字串無所謂。連 x 軸標籤
截字（`day[5:]`，原本是為了把 `"2026-09-10"` 截成 `"09-10"`）都因為
`"2026-W37"` 的前綴 `"2026-"` 剛好也是 5 個字元而直接沿用，沒有另外寫程式碼。

### 4. 成本三來源絕不可混加，`None` 與 `0` 必須可區分

`cost_source` 分 `cli`／`pricebook`／`subscription`／`unavailable` 四類，只有
前兩者代表真金額；`subscription` 是 Claude 訂閱制（token 數不等於帳單金額）、
`unavailable` 是有 token 但沒拿到成本。凡是「這個桶完全沒有可信金額來源」的
情況一律回傳 `None`（渲染成 `—`），不可填 `0`——那會被讀成「花了 0 元」。這個
原則貫穿 `daily_cost`／`cost_attribution`／`weekly_cost` 全部同一套。

### 5. session 層歸因用「一人無歧義／多人 shared／無真人 unattributed」三分類

token 與成本都歸因到 session 的真人 sender，但只到 session 層（把用量對應到
「某一個具體任務」需要一個三種 CLI 格式都不保證的順序假設）。一個 session 只有
一位真人時無歧義；多人共用一律記進 `shared` 不強行拆分；沒有真人（例如純 cron
開的 session）記進 `unattributed`。三個桶都要在報表裡明確列出來，不能只顯示
`coverage` 這個彙總百分比——早期版本就是只顯示了覆蓋率，逐使用者的實際明細
反而沒有渲染出來，是這次擴充才補上的。

### 6. 設定檔（真名／頻道名稱）本地維護，不進版控

`config.example.json` 是進版控的範本；真的填了 Discord ID → 真人姓名對照的
`config.json` 加進 `.gitignore`，只在目標機器上本機維護，理由跟
`values-secret-*.yaml` 一樣——這類會把識別碼對回真人身份的檔案不該進 git。

### 7. 回填舊資料用符號連結「偽裝」佈局，不改任何 parser

`collect.py` 的 `mirror_shim_home()` 把 archive/mirror 重新命名過的子目錄
（`claude-projects`／`codex-sessions`／`opencode`／`openab`）用符號連結接回
三個 parser 原本認得的活資料佈局（`.claude/projects` 等），讓已經測試過的
parser 原封不動被重用。唯一要注意：shim 路徑必須是**同一個 bot 每次都產生
一樣的路徑**，否則 claude-code／codex 的 `usage_key`（內嵌檔案路徑）會在
重跑時被當成新資料重複計算——所以 shim 路徑是 `<out>/.mirror-shim/<bot>`，
不是隨機產生的暫存目錄。

## 經驗教訓

### 三種輸出格式很容易「顧此失彼」

每次新增一個指標，都要同時改 `build_report()` + 三個 renderer + 各自的測試，
漏一個不會馬上報錯（`report.get(key) or {}` 這種防禦性讀取會讓程式正常跑完，
只是那個格式安靜地少了一塊）。實測發生過兩次：`render_html.py` 一度完全沒有
「成本」區塊；`session_attribution()` 早就算出逐使用者明細，但三種格式一度都
只顯示 `coverage` 百分比、沒有把明細印出來。**教訓：新增報表欄位時，先
`grep` 三個 renderer 函式確認都要改，而不是改完一個先收工。**

### 測試斷言太寬鬆會「碰巧通過」，等於沒測到

有一次寫了 `self.assertIn("共用", out)` 想確認「多人共用 session」的桶有被
渲染出來，結果這個測試在功能還沒實作前就已經通過——因為報表頁首固定的限制
說明文字裡剛好也有「共用」兩個字（"多人共用的 session 記為 shared 不強行
拆分"）。改成斷言更具體的字串（實際的 token 數字 + 完整的桶名稱）才真正鎖住
行為。**教訓：substring 斷言要檢查是否會被頁面上其他固定文案意外命中。**

### 純測試綠燈不夠，HTML 一定要真的用瀏覽器看過

單元測試能鎖住座標與數字，鎖不住「兩個標籤重疊」「窄視窗表格把頁面撐寬」
「深色模式某個顏色看不清楚」這類版面問題。每次改完 `render_html.py`，都用
headless 瀏覽器截圖（light／dark 各一次）實際看過才算完成，這條規則抓到過
成本標色、週趨勢圖排版等測試綠燈但視覺有問題的情況。

### fixture 會跟資料模型漂移

`tests/test_render_html.py` 的 `report_fixture()` 是手寫的 dict，`build_report()`
每加一個新欄位，這份 fixture 就要跟著補上，不然要嘛直接 `KeyError`（還算
好抓），要嘛被 `render_html.py` 裡的防禦性讀取（`report.get(...) or {}`）
悄悄吃掉，測試看起來過了但其實沒真的測到新欄位的渲染路徑。

## 尚待完成

- CronJob 部署到 k3s 節點（步驟已寫在 `deployment-guides/K3S.md`「使用統計
  CronJob」一節）。
- 端對端驗收：人工對照 Discord 頻道當天實際訊息數，確認「真人任務數」對得上
  ——計畫裡特別強調這步不能省。
