# Bot Build 感知 + 互動式驗收能力設計

> 讓三隻 pipeline bot（Morty / Rick / Summer）具備「取得 build 產物 + 互動式操控模擬器/瀏覽器做驗收」的能力。
>
> 本文只**描述方法**（runbook 風格），不含逐步實作計畫，不寫程式。實作前另行 plan。
>
> 前置脈絡：`deployment-guides/BOT_SETUP.md`（三 bot 部署、gh 雙帳號、雙模式 persona）。

---

## 1. 背景與目標

三隻 bot 目前能讀寫 repo、開 PR、做 spec/review，但**看不到「app 實際跑起來的樣子」**。目標是補上：

1. **Build 感知**：能取得某 branch/PR 的可執行產物（APK / 模擬器 `.app` / web bundle）。
2. **互動式驗收**：能把產物裝進模擬器/瀏覽器，**agent 主導、探索式**地操控（點按鈕、填表單、導覽），逐步截圖佐證，對照驗收清單，把結果貼回 PR/Discord。

平台範圍：**Web、Android、Flutter、iOS 全做**。

**非目標**：bot 不自己編譯 native、不簽署、不部署上架（這些沿用既有 Jenkins，且 bot 對 Jenkins 只有唯讀）。

---

## 2. 硬限制與關鍵決策

| 決策點 | 結論 | 理由 |
|---|---|---|
| iOS build / 模擬器 | 只能在 macOS + Xcode | Apple 工具鏈限制，Linux 容器做不到 |
| 執行模型 | **混合**：web 留容器內、native 委派 Mac host | 模擬器需原生 macOS/虛擬化，容器（Linux VM）不可靠 |
| Build 誰做 | **沿用既有 Jenkins**（bot 唯讀取件） | 已有可運作的 build/簽署/上架 pipeline，導入 Fastlane/self-hosted runner 是重工（YAGNI） |
| 驗收操控介面 | **mobile-mcp**（native）+ **chrome-devtools-mcp**（web） | 業界成品、agent-native（MCP）、直呼 `xcrun`/`adb`，免自刻 verb API、免 Appium |
| Bot ↔ Jenkins | **唯讀**：抓 PR/branch 已自動 build 的 artifact | 無觸發/無部署 → 被注入也上不了架、動不了 pipeline |
| 驗收深度 | **agent 主導探索式** | 對照驗收清單逐條操作 + 截圖佐證 |
| 能力歸屬 | **三隻共用同一份能力**（skill + 共享 mobile-mcp） | 誰需要誰用；mobile-mcp 是共享 host 服務 |

**為什麼用現成元件而非自刻**：mobile-mcp 就是「有界動詞 API」的成品版，而且說 MCP——與 web 端的 chrome-devtools-mcp 同一套心智模型；Jenkins 是既有的 build 事實來源。整個設計「新增的程式」趨近於零，主要是**接線 + 權限 + 一份 skill**。

---

## 3. 拓撲：3 台機器與各層落點

三台都在**公司網路內**、彼此網路可達。

```
公司網路
├─ 機器1 = Mac mini (CAC@2771)
│   ├─ OrbStack(Linux VM)
│   │    └─ 容器: Rick + Summer         ← bot 本體(client)，已存在
│   ├─ Android Jenkins                  ← 既有，PR 自動 build APK；bot 唯讀取件
│   ├─【新增】mobile-mcp daemon          ← native macOS、被動 server、SSE+token
│   │    └─ 驅動 → iOS 模擬器 / Android emulator（原生、on-demand）
│   ├─【新增】Xcode + iOS 模擬器 + Android SDK + arm emulator   ← 只為驗收，不做 build
│   └─【新增】共享目錄 /shared（bind mount 進容器）  ← artifact 落地、供 mobile-mcp 讀取
│
├─ 機器2 = 獨立 iOS Jenkins（專用 Mac，有 Xcode）  ← 既有，PR 自動 build；bot 唯讀取件
│                                                    （build-only，本設計不在此裝任何東西 — 見 §11 開放決策）
└─ 機器3 = Portainer host：Morty 容器            ← bot 本體，已存在（非 Mac）
```

**關鍵事實**：
- 抓 artifact 是**跨機 HTTP 唯讀下載**，與模擬器在哪台無關 → mobile-mcp **不需**因為 iOS Jenkins 在機器2 而裝到機器2。
- 整個系統**只有一份 mobile-mcp**（機器1），三隻 bot 共享。Morty（機器3）跨公司網路連機器1 的 mobile-mcp。
- iOS 模擬器需要 Xcode；機器1 目前無 Xcode，主線設計為**在機器1 補裝 Xcode**（見 §11）。

---

## 4. 角色區分：bot vs MCP server vs Jenkins

⚠️ **rollout 最常見誤會**：以為機器1 要「再部署一顆 bot」。**不用**。要在機器1「接收訊息」的是 mobile-mcp，它**不是 bot**——沒有 Discord、沒有 LLM、不決策，只是被動工具端點。真正的 bot（Rick/Summer）本來就在容器裡。

| 元件 | 角色 | 有 LLM/Discord？ | 位置 |
|---|---|---|---|
| **Rick / Summer / Morty**（agent） | **Client**，發起所有請求、做決策 | ✅ 有（bot 本體） | 各自容器內（**已存在**） |
| **mobile-mcp** | **Server**，被動回應有界動詞 | ❌ 純工具端點 | 機器1 原生 macOS（**新增**） |
| **Jenkins**（Android/iOS） | **Server**，被動被讀 | ❌ | 機器1 / 機器2（**已存在**） |

在 §5 的循序圖裡，**bot 永遠是發起所有箭頭的那一方**；mobile-mcp 與 Jenkins 只回應。

---

## 5. 端對端流程

### 5.1 循序圖（以 Android 為例；iOS/Web 差異見 §7）

```
  人類            Bot(agent)             Jenkins              mobile-mcp
 @Discord         容器內·機器1/3         唯讀·公司網          機器1(驅動模擬器/emulator)
    │                 │                     │                      │
    │ ①@bot「驗收       │                     │                      │
    │  PR#123 android」│                     │                      │
    │────────────────►│                     │                      │
    │                 │ ② 解析 branch/commit │                      │
    │                 │    + 平台            │                      │
    │                 │                     │                      │
    │                 │ ③ GET 該 branch      │                      │
    │                 │   最新成功 build      │                      │
    │                 │   (Bearer token,唯讀) │                     │
    │                 │────────────────────►│                      │
    │                 │ ④ build#、SUCCESS、   │                      │
    │                 │   artifact 相對路徑   │                      │
    │                 │◄────────────────────│                      │
    │                 │ ⑤ GET artifact       │                      │
    │                 │   (app-debug.apk)    │                      │
    │                 │────────────────────►│                      │
    │                 │ ⑥ APK bytes          │                      │
    │                 │◄────────────────────│                      │
    │                 │  存到機器1            │                      │
    │                 │  /shared/PR123.apk   │                      │
    │                 │                     │                      │
    │                 │ ⑦ boot sim/emulator (SSE + Bearer token)     │
    │                 │─────────────────────────────────────────────►│  ⇢ on-demand 啟動模擬器
    │                 │ ⑧ installApp("/shared/PR123.apk")            │
    │                 │─────────────────────────────────────────────►│  ⇢ adb/xcrun 安裝
    │                 │                                              │
    │           ┌─────┤ ⑨ 探索式驗收迴圈（一次一個有界動詞）           │
    │           │     │   screenshot / listElements / tap / type…    │
    │           │     │─────────────────────────────────────────────►│  ⇢ 操控模擬器
    │           │     │   截圖 / UI tree / log                        │
    │           │     │◄─────────────────────────────────────────────│
    │           └────►│  (bot 看畫面決定下一步 → 重複⑨直到清單跑完)     │
    │                 │                     │                      │
    │                 │ ⑩ shutdown 模擬器（釋放資源）                 │
    │                 │─────────────────────────────────────────────►│
    │ ⑪ 驗收報告        │                     │                      │
    │  +截圖佐證        │  貼回 PR / Discord   │                      │
    │◄────────────────│                     │                      │
```

### 5.2 Bot ↔ Jenkins 訊息（資料來回具體長怎樣）

| # | 方向 | 呼叫 / 資料 | 認證與權限 |
|---|---|---|---|
| ③ | Bot→Jenkins | `GET /job/<job>/lastSuccessfulBuild/api/json?tree=number,result,artifacts[relativePath]`（必要時先用 multibranch/參數定位到該 branch 的 job） | Bearer / API token；**唯讀** |
| ④ | Jenkins→Bot | JSON：`{number, result:"SUCCESS", artifacts:[{relativePath:"app-debug.apk"}]}` | — |
| ⑤ | Bot→Jenkins | `GET /job/<job>/<build#>/artifact/<relativePath>` | 同 token；唯讀下載 |
| ⑥ | Jenkins→Bot | binary bytes → 落地 `機器1:/shared/acceptance/PR123.apk`（透過 bind mount，見 §6.3） | — |

### 5.3 安全就長在流程上

- **③⑤ 全是 GET**：bot 對 Jenkins 只讀，無 POST/觸發/deploy → 被注入也推不上架、動不了 pipeline。
- **⑦⑧⑨⑩ 每個箭頭都是 mobile-mcp 的有界動詞**（`boot`/`installApp`/`tap`/`screenshot`…），不是 host shell；token 只換到「操控模擬器」，換不到機器控制權。
- **⑥ 產物落在機器1 共享路徑**，正是 mobile-mcp（同機）install 的來源；跨信任邊界的只有「一個檔案 + 一組有界動詞」。

---

## 6. 元件與職責

### 6.1 Jenkins（既有，唯讀取件）

- **權限模型**：專用 Jenkins user，權限釘死「**只讀特定 build job 狀態 + 下載 artifact**」，**無** trigger / configure / admin / deploy。
- **憑證**：API token 放各 bot 的 secrets env（同 GH token 威脅模型；但唯讀 + scoped → blast radius 極小）。
- **bot 動作**：REST API 找該 branch 最新成功 build → 取 artifact 相對路徑 → 下載到 `/shared`。
- **鐵則**：bot 觸發不了任何 job，尤其**永遠碰不到「上架 App Store」**。

### 6.2 mobile-mcp（機器1，新增的被動 server）

- 套件：`mobile-next/mobile-mcp`，**版本 ≥ 1.3.3**（修過 command-injection）。
- 底層直呼 `xcrun` / `adb` / `uiautomator`，**不依賴 Appium**；支援 iOS 模擬器/實機 + Android emulator/實機，統一 API。
- 傳輸：**SSE 模式**（`--listen` + `MOBILEMCP_AUTH` Bearer token），綁公司網路可達介面。
- 執行身份：**專用低權限 macOS 使用者**、**不在 docker group**（碰不到 colima/OrbStack 團隊服務）、`launchd` 開機自啟。
- 能力（節錄）：list/boot/shutdown device、install/launch/terminate app、screenshot、listElements（含座標/無障礙樹）、tap/swipe/longpress、type text、press button、open URL。

### 6.3 chrome-devtools-mcp / Playwright（容器內，web 驗收）

- web 驗收整段**不碰 Jenkins、不碰 host**：容器內 `npm run build` 起本地服務，agent 用 **chrome-devtools-mcp**（退路：Playwright CLI）探索式驅動 headless Chromium。
- 這層沿用容器既有 Bash 能力，**不新增跨機信任邊界**。

### 6.4 共享目錄（bind mount）

- **問題**：bot 在容器內下載 artifact（步驟⑥），mobile-mcp 在 host 上 `installApp(路徑)`——兩者要看到同一個檔案。
- **做法**：把 host 目錄 bind mount 進容器（例 host `~/oab-shared` ↔ 容器 `/shared`）。bot 寫 `/shared/PR123.apk`，mobile-mcp 從 host 對應路徑讀。
- 註：改 mount 需重建容器（比照 BOT_SETUP.md「改 env/mount 要 rm+重建」規則）。

### 6.5 新共用 skill `wm4n.build-and-verify`

- 流程：偵測平台 → 取得可執行物（web=容器 build；native=Jenkins 唯讀取件到 `/shared`）→ boot 模擬器 → install → **探索式驗收迴圈**（下 MCP 動詞 → 讀截圖/UI tree → 決定下一步）→ shutdown → 佐證貼回 PR/Discord。
- 與既有 `acceptance-checklist` skill **搭配**：後者依 PR/diff 產驗收清單，本 skill 負責**執行清單並蒐證**。
- 安裝：三隻 bot symlink 進各自 skill 目錄（Claude→`~/.claude/skills/`、Codex→`~/.codex/skills/`），沿用 BOT_SETUP.md §K 的 `wm4n.` 前綴慣例。

### 6.6 persona 雙模式指路

- 三份 CLAUDE.md/AGENTS.md 的「何時進入流程模式」各加一條：
  > 正式要把 app 跑起來驗收 / 操控模擬器 / 操控瀏覽器 → `wm4n.build-and-verify` skill。
- 預設資深工程師模式**不自動驗收**；被明確要求才觸發。

---

## 7. 各平台對應

| 平台 | 取得可執行物 | 驗收路徑 |
|---|---|---|
| **Web** | 容器內 `npm run build` 起本地服務 | 容器內 chrome-devtools-mcp（退路 Playwright），agent 探索式 |
| **Android** | 唯讀抓 **機器1** Jenkins 該 branch 最新成功 build 的 APK → `/shared` | mobile-mcp 裝進 arm emulator（機器1） |
| **iOS** | 唯讀抓 **機器2** Jenkins 該 branch 的**模擬器 build（`.app`）** → `/shared`（見 §10 caveat 1） | mobile-mcp 裝進 iOS 模擬器（機器1，需 Xcode，見 §11） |
| **Flutter** | android/ios 走對應 Jenkins；web target 走容器內 | 同對應平台 |

---

## 8. 資源生命週期

| 元件 | 常駐？ | 說明 |
|---|---|---|
| **mobile-mcp daemon** | ✅ 常駐 | 輕量 listener，`launchd` 開機自啟，讓 bot 隨時連得到 |
| **模擬器 / emulator** | ❌ **不常駐** | 驗收開始才 **on-demand boot**、跑完 **shutdown** |

- **為何 on-demand 而非常駐**：機器1 已負載重（Rick/Summer 容器 + Android Jenkins），每個 emulator 約 1–2GB RAM。
- **代價**：冷開機延遲（Android ~30–60s、iOS sim ~10–20s）每次驗收。
- **替代**：若延遲惱人，可保留一台 warm device（吃常駐資源換啟動速度）。
- **boot/shutdown 也是有界動作**（mobile-mcp device 管理 verb 或白名單 boot helper），**不是 host shell**。
- **rollout 確認**：mobile-mcp 是否自帶「啟動 emulator 程序」能力；若只能 attach 到已跑的 device，需補一個白名單 boot helper（同樣以低權限使用者執行）。

---

## 9. 安全模型

注入 blast radius 被限死在三個有界面上，碰不到團隊服務、砍不了東西、也上不了架：

1. **Jenkins 唯讀 + 絕不碰 deploy job**：bot 永遠不會把東西推上 App Store 或動 pipeline。
2. **mobile-mcp 有界工具集 + Bearer token + 專用低權限使用者 + 與 colima/OrbStack 隔離**（不在 docker group）。
3. **web 留容器內**：本就有的能力，無新增信任邊界。
4. **全部可秒收回**：停 mobile-mcp daemon / 撤 Jenkins token / 撤 mobile-mcp token / 踢使用者。

沿用 BOT_SETUP.md 的核心假設：**假設憑證一定會被 prompt injection 取用 → 確保損害小且可逆**。此處 Jenkins token 唯讀、mobile-mcp token 只能操控模擬器，皆符合。

---

## 10. Caveat / rollout 未知與檢查點

1. ⚠️ **iOS 模擬器需要「模擬器 build」而非上架 IPA**（最大技術雷）：iOS 模擬器裝不了簽章的 device `.ipa`，需要 simulator slice 的 `.app`。對策二選一：
   - (a) 在 iOS Jenkins **加一個「模擬器 build」artifact** 供 bot 取；或
   - (b) iOS 驗收改用**實機**（mobile-mcp 支援實機；但實機自動化通常仍需 Xcode 建 WebDriverAgent）。
2. ⚠️ **MCP 透傳未實測**：`claude-agent-acp`（Rick/Morty）與 `codex-acp`（Summer）是否把 SSE MCP 設定透傳給 agent，屬未知（比照 BOT_SETUP.md 中「Codex 吃不吃 filesystem skill」）。rollout 必測；Summer 若不行，退回只做非-MCP 部分（Summer 本職是 code review，native 驗收非其核心）。
3. ⚠️ **網路可達性**：容器（機器1 OrbStack、機器3 Portainer）→ 兩台公司 Jenkins；Morty（機器3）→ 機器1 mobile-mcp。rollout 確認路由/防火牆。
4. ⚠️ **機器1 負載**：已背 Rick/Summer 容器 + Android Jenkins，再加 Xcode/模擬器/emulator/mobile-mcp，資源吃緊；on-demand 生命週期（§8）是主要緩解。
5. ⚠️ **共用模擬器併發**：多 bot 共用單一 mobile-mcp/模擬器池要序列化或分身，比照 BOT_SETUP.md 的 `gh auth switch` 併發註記。
6. ⚠️ **供應鏈**：mobile-mcp 是第三方且能驅動裝置 → 釘版本（≥1.3.3）、低權限使用者、token 網段限縮。

---

## 11. 開放決策（待拍板）

**iOS 驗收主機：Option A（推薦）vs Option B**

| | Option A（推薦） | Option B |
|---|---|---|
| iOS 驗收主機 | **機器1 補裝 Xcode** | 用機器2（已有 Xcode） |
| mobile-mcp 份數 | **1 份**（機器1 管 Android+iOS） | 2 份（機器1 管 Android、機器2 管 iOS） |
| 機器2 | 不動、只 build | 在共用 iOS CI build 機上跑 bot 驅動的模擬器 |
| 顧慮 | 機器1 多背 Xcode(~40GB)+模擬器，負載更重 | 共用 build 機跑 bot 模擬器：資源競爭、安全面變大、可能非你可控的公司 infra |

推薦 **A**：單一 mobile-mcp、機器2 保持乾淨的 build-only、驗收與 bot 同機。本文其餘章節以 A 為主線撰寫。

---

## 附錄：參考來源

- [mobile-next/mobile-mcp](https://github.com/mobile-next/mobile-mcp)（本設計的驗收操控核心）
- [ios-simulator-mcp (npm)](https://www.npmjs.com/package/ios-simulator-mcp)、[appium/appium-mcp](https://github.com/appium/appium-mcp)（替代品）
- [Maestro vs Appium (2026)](https://pie.inc/blog/maestro-vs-appium/)（若改走確定性腳本而非探索式）
- 既有：`deployment-guides/BOT_SETUP.md`、`deployment-guides/bot-skills/`、`skills/acceptance-checklist`
