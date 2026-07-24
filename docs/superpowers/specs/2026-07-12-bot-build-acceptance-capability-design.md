# Bot Build 感知 + 互動式驗收能力設計

> 讓三隻 pipeline bot（Morty / Rick / Summer）具備「取得 build 產物 + 對照驗收清單驗收 app」的能力。
>
> 本文只**描述方法**（runbook 風格），不含逐步實作計畫，不寫程式。實作前另行 plan。
>
> **v2 修訂 2026-07-23**：主線從「mobile-mcp 互動驅動」轉為「**Jenkins-native 下游 stage + LLM 外圈產 Maestro flow 檔**」；bot 對 Jenkins 維持**唯讀、零觸發**；**mobile-mcp 降為 Tier-2 未來互動式延伸**。轉向理由見 §2。
>
> 前置脈絡：`deployment-guides/BOT_SETUP.md`（三 bot 部署、gh 雙帳號、雙模式 persona）。

---

## 1. 背景與目標

三隻 bot 目前能讀寫 repo、開 PR、做 spec/review，但**看不到「app 實際跑起來的樣子」**。目標補上：

1. **Build 感知**：能取得某 PR 的可執行產物（APK / 模擬器 `.app` / web bundle）。
2. **驗收**：把產物裝進模擬器/瀏覽器、對照驗收清單跑過關鍵流程、截圖佐證、把結果貼回 PR/Discord。

平台範圍：**Web、Android、Flutter、iOS 全做**。

**非目標**：bot 不簽署、不部署上架（沿用既有 Jenkins，且對 Jenkins 只有唯讀 + 不觸發任何 job）。

---

## 2. 設計演進：為何從 mobile-mcp 主線轉向 Jenkins-native

v1（已 commit `cabab64`）以 **mobile-mcp** 為主線——agent 逐步 `dump→tap→dump→tap` 互動驅動模擬器。討論後改向，理由：

1. **逐步互動無法放進任何 CI substrate**：GitHub Actions / Jenkins 的 job 都是「**run 之內有狀態、run 之間沒狀態**」。想把 `open→dump→act→dump→act` 拆成「每步一個 trigger」，模擬器/app 狀態會在 job 之間全丟、每步得重開機重導航——不可行。逐步互動**只能靠常駐 session（＝mobile-mcp）**，這點與選 gh 或 Jenkins 無關。
2. **但驗收的九成需求是「確認 PR 的規格行為過不過」，不是即興探索**。這用「**LLM 外圈**」就夠：LLM 讀 PR + 驗收清單 + 原始碼 → 產一支 Maestro flow → CI 一個 job 內跑完 → 吐回 hierarchy/截圖/pass-fail → LLM 事後讀、卡住就改 flow 重跑。LLM 的智能在「**寫/改流程**」出腦，不在逐個 tap。
3. **Jenkins-native 最貼合現況**：build 本來就在 Jenkins、**產物就在 agent 本地免搬**、iOS 的模擬器 build 變成同一條 pipeline 的中間產物（解掉 v1 §10 caveat1 與 §11 的 Xcode-on-機器1 難題）、且 **bot 可維持唯讀零觸發**（控制靠「commit flow 檔 + 讀結果」，git 本來就會）。
4. **mobile-mcp 仍有唯一價值**：真正要「Rick 本人即時逐步即興操控探索」時，只有它能做。故**保留為 Tier-2 未來延伸**（§12），不進主線。

---

## 3. 三種執行模型與界線

判斷點：**LLM 夾在迴圈的哪一圈？狀態要活多久？**

| 模型 | 迴圈 | 狀態活在哪 | Substrate | 本設計 |
|---|---|---|---|---|
| **① 外圈** | LLM 先寫整支 flow → 1 個 job 內 `open→act→act→assert`，沿途 dump/截圖 → LLM 事後讀、要改再跑 | job 內（一次 run 走完） | **Jenkins pipeline stage** | ✅ **主線** |
| **② 內圈** | bot 逐步 `dump→決定→act→dump…`，device 全程開著 | 跨步驟的常駐 session | mobile-mcp（SSE 長連線） | Tier-2（§12）|
| **③ agent-in-job** | job 內部自跑 `dump→呼 LLM API→act…` | job 內 | CI job 內嵌無頭 agent | 未採用（agent≠Discord bot、runner 要放模型 key）|

> **心法**：`open→dump→act→dump→act` 這種**逐步、LLM 夾在中間決定**的迴圈，狀態要跨「LLM 的決策」存活 → 那是常駐 session 的活（mobile-mcp）；CI（Jenkins/gh）只在「整迴圈塞進同一 job、LLM 在 job 之外前寫後讀」時才對。**「每步一個 trigger」是反模式。**

---

## 4. 硬限制與關鍵決策

| 決策點 | 結論 | 理由 |
|---|---|---|
| iOS build / 模擬器 | 只能在 macOS + Xcode | Apple 工具鏈限制 |
| Build 誰做 | **沿用既有 Jenkins**（PR 自動 build） | 已有可運作的 build/簽署/上架 pipeline（YAGNI）|
| 驗收 substrate | **既有 Jenkins pipeline 的下游 stage** | 產物本地、iOS 順手解、bot 可唯讀 |
| 驗收如何被驅動 | **LLM 外圈**：產/改 **Maestro flow 檔（放 repo）** | flow 是 code、bot 用既有 git 就能改；CI 跑確定性流程 |
| Bot ↔ Jenkins | **唯讀 + 零觸發**（讀結果 artifact / PR check） | 控制靠 commit flow 檔，不需觸發權；被注入也動不了 pipeline、上不了架 |
| 判成敗 | flow 內 `assertVisible` + 必要時 `assertWithAI`（視覺判斷）；每 run 吐 hierarchy+截圖供事後判 | 非互動 ≠ 看不到結果，只是回饋顆粒度是「每 run」而非「每 tap」|
| 互動式探索 | **mobile-mcp，Tier-2 未來延伸** | 唯一能做逐步 bot-in-loop 的機制，但非驗收剛需 |

---

## 5. 拓撲

三台都在**公司網路內**、彼此可達。**驗收在「有對應工具鏈 + 產物」的 Jenkins agent 上執行**。

```
公司網路
├─ 機器1 = Mac mini (CAC@2771)
│   ├─ OrbStack 容器: Rick + Summer          ← bot(client)，已存在
│   └─ Android Jenkins                       ← 既有 build；【新增】下游 acceptance stage
│        └─ arm emulator（on-demand，boot→跑→拆）
├─ 機器2 = 獨立 iOS Jenkins（專用 Mac，有 Xcode）
│   └─ 既有 build；【新增】下游 acceptance stage
│        └─ iOS 模擬器 + 模擬器 build(.app) 為 pipeline 中間產物
└─ 機器3 = Portainer: Morty 容器             ← bot，已存在
```

**v1 難題自動解掉**：
- iOS 驗收落在**機器2（本就有 Xcode）**，**機器1 不必裝 Xcode**（v1 §11 A/B 開放決策消失）。
- iOS 模擬器 `.app` 是同 pipeline 的中間產物，**不必另建 sim artifact**（v1 §10 caveat1 化解）。
- 產物在本地 → **不必跨機搬檔、不必 bind-mount、bot 不必拿 Jenkins token 去 fetch**。

---

## 6. 角色區分

⚠️ **不需要再部署任何 bot**。驗收的「執行者」是既有 Jenkins pipeline；bot（Rick/Summer/Morty）本來就在各自容器裡。

| 元件 | 角色 | 位置 |
|---|---|---|
| **Rick / Summer / Morty** | **Client**：讀 PR/清單/source → 產 flow 檔（git）→ 讀結果 → 自我修復 | 各自容器（已存在）|
| **Jenkins pipeline（+ acceptance stage）** | **執行者**：build → boot device → install → 跑 flow → archive 結果 | 機器1(Android) / 機器2(iOS)（既有，新增 stage）|
| **repo 內的 Maestro flow 檔** | 驗收流程「原始碼」，LLM 讀寫、CI 執行 | repo（如 `.maestro/`）|
| **mobile-mcp** | Tier-2 未來：互動式驅動 / flow authoring 輔助 | 機器1/2 host（未來才裝，§12）|

---

## 7. 端對端流程

```
  人類          Bot(Rick/Summer)     Repo(git)        Jenkins pipeline         驗收結果
 @Discord       容器內               flow 檔          機器1/2 agent            artifact+PR check
    │ ①@bot「驗收        │                │                   │                      │
    │  PR#123 android」  │                │                   │                      │
    │──────────────────►│                │                   │                      │
    │                   │② 讀 PR+驗收清單+source                │                      │
    │                   │  產/改 Maestro flow                  │                      │
    │                   │──commit+push──►│                   │                      │
    │                   │                │③ 既有 per-PR pipeline 自動觸發             │
    │                   │                │──────────────────►│                      │
    │                   │                │                   │④ build→boot sim→install│
    │                   │                │                   │  →跑 flow→archive     │
    │                   │                │                   │─────────────────────►│
    │                   │                │                   │  hierarchy/截圖/pass  │
    │                   │⑤ 唯讀讀結果 artifact + PR check                            │
    │                   │◄─────────────────────────────────────────────────────────│
    │             ┌─────┤⑥ 過了→報告；卡住→讀 hierarchy→改 flow 檔→push→重跑(回②)     │
    │             └────►│                │                   │                      │
    │⑦ 驗收報告+截圖佐證  │                │                   │                      │
    │◄──────────────────│                │                   │                      │
```

**Bot 的「控制」全靠既有能力**：②commit flow 檔（git）、⑤讀 Jenkins 結果（唯讀 API）+ 讀 PR check（gh）。**對 Jenkins 零觸發權**（pipeline 由既有 per-PR 機制自動跑）。

---

## 8. 元件與職責

### 8.1 既有 Jenkins（唯讀 + 新增 acceptance stage）

- **新增下游 stage**（需 Jenkins admin 加，bot 不能改）：`build → boot sim/emulator（on-demand）→ install → maestro test <flow> → archiveArtifacts {view hierarchy, 截圖, 錄影, junit/pass-fail} → 回報 GitHub commit status`。
- **產物**：iOS 的模擬器 `.app` 為 stage 中間產物；acceptance 讀 repo 內 flow 檔執行。
- **bot 權限**：唯讀讀 build 狀態 + 下載 artifact；**無 trigger/configure/admin/deploy**。API token 放 bot secrets env（唯讀 + scoped → blast radius 極小）。

### 8.2 Maestro flow 檔（repo 內，LLM 產）

**什麼是 Maestro**：mobile.dev 出的開源 **mobile UI 測試框架**（iOS + Android；近期亦支援 web/桌面）。測試以簡單 YAML「flow」撰寫（非寫程式）、內建自動等待/抗 flaky、黑箱驅動**已 build 的 app**（不用把測試碼編進 app）、單一 CLI（`maestro test flow.yaml`）好塞進 CI。典型 flow：

```yaml
appId: com.example.app
---
- launchApp
- tapOn: "登入"
- inputText: "user@example.com"
- tapOn: "送出"
- assertVisible: "歡迎回來"        # 明確 pass/fail
- takeScreenshot: after-login
```

（對照：**Appium** 老牌、程式碼寫、要自管等待、較重；**Espresso/XCUITest** 平台原生、要編進 app。Web 端本設計用 **Playwright**，因 Maestro 的 web 支援較新。）

- 放 repo（如 `.maestro/<feature>.yaml`），YAML、淺、適合 LLM 生成。
- LLM 寫 flow 的先驗來自**原始碼**：`testID`/accessibility label/文字字串、導覽結構（宣告式 UI 尤其可預測）。
- 判成敗：`assertVisible "…"` 給明確 pass/fail；難以精準 selector 判斷處用 `assertWithAI: "登入成功了"`（視覺模型判斷）。
- 選 Maestro 而非 Appium：單一 CLI、YAML、內建等待/抗 flaky、`hierarchy` dump、Studio 互動檢視、AI 指令。

### 8.3 GitHub 狀態整合

- Jenkins → GitHub commit status（Jenkins 的 GitHub plugin），讓 PR 直接看得到 acceptance 結果；bot 亦可經唯讀 API 讀結果後自行貼回 PR/Discord。

### 8.4 新共用 skill `wm4n.build-and-verify`

- 流程：偵測平台 → 讀 PR + `acceptance-checklist` 產的清單 + source → 產/改 flow 檔 → push → **讀 CI 結果**（過→報告；失敗→讀 hierarchy/截圖 → 修 flow → 重推，外圈自我修復）→ 佐證貼回 PR/Discord。
- 與既有 `acceptance-checklist` skill 搭配（後者產清單、本 skill 產可執行 flow 並蒐證）。
- 三隻 bot symlink 進各自 skill 目錄（沿用 `wm4n.` 前綴慣例）。

### 8.5 persona 雙模式指路

- 三份 CLAUDE.md/AGENTS.md 的「何時進入流程模式」加：**正式要驗收某 PR → `wm4n.build-and-verify` skill**。預設工程師模式不自動驗收。

---

## 9. 各平台對應

| 平台 | build | 驗收 stage 落點 | flow 工具 |
|---|---|---|---|
| **Android** | 機器1 Jenkins | 機器1（arm emulator）| Maestro |
| **iOS** | 機器2 Jenkins（Xcode）| 機器2（iOS 模擬器；`.app` 為中間產物）| Maestro |
| **Flutter** | 對應平台 Jenkins | 同 android/ios | Maestro |
| **Web** | 容器內 `npm build` 或既有 web CI | 可留**容器內**（自足、低風險）或 CI stage | Playwright（flow 檔亦放 repo）|

> Web 是唯一可整段留容器內的平台（headless Chromium 跑 Playwright flow），不必進 Jenkins；Tier-2 互動則用 chrome-devtools-mcp。

---

## 10. 資源生命週期

- **模擬器/emulator 不常駐**：acceptance stage 內 **on-demand boot → 跑 → teardown**（CI job 天然如此）。省 RAM、乾淨。
- **冷開機延遲**：每次驗收數分鐘（已確認可接受）。
- **併發**：多 PR 平行 build → 多個模擬器實例，由 Jenkins executor/agent 數控管；必要時序列化。
- **mobile-mcp（Tier-2）才需常駐 daemon**，主線無常駐元件。

---

## 11. 安全模型

1. **Bot 對 Jenkins 唯讀 + 零觸發 + 絕不碰 deploy**：控制僅靠「commit 受信任的 flow 檔 + 讀結果」→ 被注入也動不了 pipeline、上不了架。
2. **acceptance 跑的是 repo 內受信任的 flow 檔**（非任意指令），對已 build 的 app 操作。
3. **RCE 面＝既有 Jenkins build**：build PR 原始碼本就在你既有 Jenkins 內發生、已被你接受；本設計未新增「在別處跑不受信任程式碼」的面（不引入 self-hosted runner 這層新面）。
4. **憑證最小**：bot 僅需 gh（既有）+ Jenkins 唯讀 token；**無 mobile-mcp token（Tier-2 才有）**。
5. **可秒收回**：撤 Jenkins 唯讀 token / 移除 acceptance stage。

---

## 12. Tier-2：mobile-mcp 互動式驗收延伸（未來）

**保留、暫不實作**。當「確定性 flow 不夠、需要 Rick 本人即時逐步即興操控探索」時才啟用——這是**唯一能做逐步 bot-in-loop** 的機制（CI substrate 做不到，見 §3）。

- **用途**：(a) 互動探索式驗收；(b) flow authoring 輔助（互動觀察真實 UI tree，加速寫/修 flow）。
- **部署（啟用時）**：`mobile-next/mobile-mcp` ≥ 1.3.3，SSE + `MOBILEMCP_AUTH` Bearer token，跑在對應工具鏈機器（Android→機器1、iOS→機器2）的**專用低權限使用者 / 不在 docker group / launchd**；直呼 `xcrun`/`adb`/`uiautomator`、免 Appium。bot 經 `host.orb.internal`（同機）或公司網路（跨機）連。
- **Web 對應 Tier-2**：容器內 chrome-devtools-mcp。
- **啟用前未知**（屆時驗）：`claude-agent-acp`/`codex-acp` 是否透傳 SSE MCP 設定；供應鏈（釘版本、低權限、token 網段限縮）；常駐資源。

---

## 13. Caveat / rollout 檢查點

1. ⚠️ **Jenkins pipeline 要改**：加 acceptance stage（build debug/sim + boot device + 跑 flow + archive + 回報 status）。需 Jenkins admin，非 bot 能改——rollout 主要工作面。
2. ⚠️ **LLM 盲寫 flow 的可靠度**（核心風險）：selector 猜錯會讓「測試錯」被誤判成「功能壞」。緩解＝讀 source 拿 testID/label 先驗 + 每 run 吐 hierarchy/截圖 + 外圈自我修復 + `assertWithAI` 判斷；必要時用 Tier-2 mobile-mcp/Maestro Studio 互動看一次真實 UI tree 來 authoring。
3. ⚠️ **GitHub 狀態整合**：Jenkins→GitHub commit status 的 plugin/credential 設定；或 bot 唯讀讀結果後自行貼 PR。
4. ⚠️ **flow 檔慣例與維護**：位置（`.maestro/`）、命名、隨 app 演進的維護責任。
5. ⚠️ **模擬器在 CI 的併發/延遲**（§10）：executor 數、冷啟延遲（數分鐘可接受）。
6. ⚠️ **多帳號/多 repo**：flow 檔隨 PR 走，跨 wm4n 個人 / 104corp / openabdev repo 都適用；Jenkins 唯讀 token 依 repo/org 對應（沿用 BOT_SETUP.md 帳號規則）。

---

## 14. 已從 v1 解掉 / 移除的項目

- ~~§11 iOS 驗收主機 A/B 開放決策~~ → 解掉：iOS 驗收落機器2（既有 Xcode）。
- ~~§10 caveat1 iOS 模擬器 `.app` gap~~ → 解掉：同 pipeline 中間產物。
- ~~bind-mount 共享目錄 / bot 拿 Jenkins token fetch artifact~~ → 移除：產物本地、bot 唯讀。
- ~~mobile-mcp 為主線~~ → 降為 Tier-2（§12）。
- ~~self-hosted GitHub Actions runner 方案~~ → 未採用（Jenkins-native 產物本地、少一套系統、bot 可唯讀；gh 的 PR-check 原生優勢較小且 flow-檔-in-repo 同樣適用）。

---

## 附錄：參考來源

- Maestro（LLM 產 flow 的驗收執行）：[maestro.dev](https://maestro.dev/)、[Maestro vs Appium (2026)](https://pie.inc/blog/maestro-vs-appium/)
- Tier-2 互動：[mobile-next/mobile-mcp](https://github.com/mobile-next/mobile-mcp)、容器內 web 用 chrome-devtools-mcp
- 既有：`deployment-guides/BOT_SETUP.md`、`deployment-guides/bot-skills/`、`skills/acceptance-checklist`
