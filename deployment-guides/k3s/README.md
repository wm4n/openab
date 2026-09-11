# k3s 部署工件

三隻 bot 遷移到單節點 k3s 的 Helm values 與秘密範本。**完整操作步驟見 [`../K3S.md`](../K3S.md)**；設計依據見 `docs/superpowers/specs/2026-07-20-k3s-migration-design.md`。

## 檔案

| 檔案 | 用途 |
| --- | --- |
| `values-openab-claude.yaml` | `openab-claude` release：Rick + Morty（RuntimeDefault） |
| `values-openab-codex.yaml` | `openab-codex` release：Summer（seccomp Unconfined） |
| `values-openab-kimi.yaml` | Kimi bot overlay（opencode + OpenRouter，模型 `moonshotai/kimi-k3`）：可併進 `openab-claude` release 或獨立 release。做法見 [`../bot-setup-opencode-kimi.md`](../bot-setup-opencode-kimi.md) 附錄 A |
| `values-openab-walle.yaml` | Wall-E bot overlay（opencode + OpenRouter，模型 `deepseek/deepseek-v4-pro-0813`）。跟 Kimi 同套，見附錄 C |
| `values-openab-eve.yaml` | Eve bot overlay（opencode + OpenRouter，模型 `z-ai/glm-5.2`）。跟 Kimi 同套，見附錄 C |
| `values-secret-claude.example.yaml` | 複製成 `values-secret-claude.yaml`（gitignored）填 Rick/Morty 的 Discord token |
| `values-secret-codex.example.yaml` | 複製成 `values-secret-codex.yaml`（gitignored）填 Summer 的 Discord token |
| `values-secret-kimi.example.yaml` | 複製成 `values-secret-kimi.yaml`（gitignored）填 Kimi bot 的 Discord token |
| `values-secret-walle.example.yaml` | 複製成 `values-secret-walle.yaml`（gitignored）填 Wall-E 的 Discord token |
| `values-secret-eve.example.yaml` | 複製成 `values-secret-eve.yaml`（gitignored）填 Eve 的 Discord token |
| `.gitignore` | 擋 `values-secret*.yaml` 被 commit |
| `verify-stats-sources.py` | 唯讀診斷：掃各 agent PVC 上的 transcript／SQLite，確認統計要用的欄位在不在（見下方「統計資料源診斷」） |
| `verify-archive-superset.py` | 唯讀診斷：用內容雜湊確認新的累積鏡像是否完整包含早期的日期快照，決定舊快照能不能刪（見 [`../K3S.md`](../K3S.md)「transcript 保留期限」） |
| `usage-stats/` | bot 使用統計：CronJob 收集 + 手動產報表。見 [`usage-stats/README.md`](usage-stats/README.md) |

## 快速驗證（在有 helm 的機器）

> ⚠️ `helm lint` **只吃本機 chart 路徑或 .tgz**，不接受 `oci://`。repo 已 clone
> 時直接指本機 chart `../../charts/openab`（也保證 values 對得上你手上的 chart 版本，
> 避免 OCI 發佈版較舊、缺 `allowedRoleIds`/`cron`/`secretEnv` 欄位）。

```bash
# 語法/模板檢查（給假 token 只為通過 render）
helm lint ../../charts/openab \
  -f values-openab-claude.yaml \
  --set agents.rick.discord.botToken=x --set agents.morty.discord.botToken=y

# 看生成的 config.toml 對不對
helm template openab-claude ../../charts/openab \
  -f values-openab-claude.yaml \
  --set agents.rick.discord.botToken=x --set agents.morty.discord.botToken=y \
  | grep -E 'command|allowed_role_ids|inherit_env|working_dir'
```

> `helm template` / `helm install` 則**可**用 OCI（`oci://ghcr.io/openabdev/charts/openab`）
> 或 GitHub Pages repo（`helm repo add openab https://openabdev.github.io/openab`）——
> 但若欄位對不上請改回本機 chart 或用 `--version` 指定較新版。

## 安裝（節錄，完整見 K3S.md）

```bash
kubectl create namespace cac
cp values-secret-claude.example.yaml values-secret-claude.yaml              # 填真值
cp values-secret-codex.example.yaml values-secret-codex.yaml # 填真值

helm install openab-claude oci://ghcr.io/openabdev/charts/openab -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml
helm install openab-codex  oci://ghcr.io/openabdev/charts/openab -n cac \
  -f values-openab-codex.yaml -f values-secret-codex.yaml
```

### Kimi bot（opencode + OpenRouter）

併進既有 `openab-claude` release（opencode 只需 RuntimeDefault，與 Rick/Morty 同 release）：

```bash
cp values-secret-kimi.example.yaml values-secret-kimi.yaml   # 填 Discord token

helm upgrade openab-claude ../../charts/openab -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml \
  -f values-openab-kimi.yaml   -f values-secret-kimi.yaml
```

之後還要：靜態 PV `pv-cac-kimi`（claimRef `openab-claude-kimi`）、`opencode auth login` 貼 OpenRouter key、寫全域 `~/.config/opencode/opencode.jsonc` 設模型（ACP 只讀全域，不讀 project `opencode.json`）。完整 bootstrap 見 [`../bot-setup-opencode-kimi.md`](../bot-setup-opencode-kimi.md) 附錄 A。

### Wall-E / Eve bot（同 Kimi 一套）

一樣 opencode + OpenRouter，只差 agent key、persona 檔、與全域 `opencode.jsonc` 的 model 字串（Wall-E＝`openrouter/deepseek/deepseek-v4-pro-0813`、Eve＝`openrouter/z-ai/glm-5.2`）。OpenRouter key 與 Kimi **共用同一把**。

**推薦：跑互動 wizard `deploy-walle-eve.sh`**（10 stage，自動步驟自己跑，Discord 開 App / `opencode auth login` / 貼 PAT 這些人做的事會停下來提示）：

```bash
bash deploy-walle-eve.sh
```

手動流程（wizard 背後做的事）：

```bash
cp values-secret-walle.example.yaml values-secret-walle.yaml   # 填 Discord token
cp values-secret-eve.example.yaml   values-secret-eve.yaml

helm upgrade openab-claude ../../charts/openab -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml \
  -f values-openab-kimi.yaml   -f values-secret-kimi.yaml \
  -f values-openab-walle.yaml  -f values-secret-walle.yaml \
  -f values-openab-eve.yaml    -f values-secret-eve.yaml
```

靜態 PV：`pv-cac-walle`（claimRef `openab-claude-walle`）、`pv-cac-eve`（claimRef `openab-claude-eve`）。bootstrap 見 [`../bot-setup-opencode-kimi.md`](../bot-setup-opencode-kimi.md) 附錄 C。

## 統計資料源診斷（`verify-stats-sources.py`）

要在 bot 頻道做使用統計（每日任務數／對話數／token 對應 model），資料不在 openab
本體——`crates/openab-core` 沒有任何 metrics 或 OTEL，而 ACP 層的
`classify_notification` 只認 6 種 `sessionUpdate`、其餘丟掉，所以 token 用量只能從
各 agent CLI 自己的 transcript 拿。

可行的關鍵在於 openab 會把 `SenderContext`（`crates/openab-core/src/adapter.rs`）以
JSON 注入**每一次** prompt，而 prompt 原文會被 CLI 寫進 transcript：

```
<sender_context>
{"schema":"openab.sender.v1","sender_id":…,"channel_id":…,"is_bot":false,"timestamp":…}
</sender_context>
```

`is_bot` 讓 bot 互呼（三 bot 接力）能跟真人任務分開算，不然採用率數字會被灌水。
四個生產者（`discord.rs` / `slack.rs` / `gateway.rs` / `cron.rs`）吐同一個 schema，
所以這條路跟平台無關——將來換 Slack 或 Google Chat 不用改統計側。

**這支腳本要驗的是：codex 與 opencode 到底有沒有把 `sender_context` 寫進它們自己的
transcript**（Claude Code 家族幾乎確定有，另兩家是推測）。沒有的話那幾隻只會有
token 數，拿不到頻道／發話者維度。

PV 是 `local` 型（`K3S.md` 第 2 步，路徑 `/data/william/openab/agent-<name>`），
所以直接讀檔就好，不需要 `kubectl exec`：

```bash
python3 verify-stats-sources.py | tee /tmp/openab-stats-verify.txt

# 資料根路徑不同時
OPENAB_DATA_ROOT=/your/path python3 verify-stats-sources.py
```

唯讀，不改任何東西，也不印任何對話內容——只印欄位結構與計數。輸出最後會有一張
判定表（每隻 bot 的 `sender_context` / token / cache 有無，以及可回溯起日）。

設計上是**探索格式而不是假設格式**：遞迴走整棵 JSON，自己找出 `sender_context`
在哪、token 數字在哪個路徑、model 欄位叫什麼。所以三家 CLI 共用一支，CLI 升版改
格式之後也還能用——可以拿來當偵測格式漂移的常備工具（`sender_context` 從「有」變
「無」就是上游改了注入方式或 CLI 改了存法）。

### 2026-09-10 首次實跑結果

**七隻全部可用**，四項統計（任務數／對話數／token 對應 model／摩擦指標）的資料都拿得到。

| bot | CLI | 資料形式 | sender_context | token | 成本 | 可回溯起日 |
| --- | --- | --- | --- | --- | --- | --- |
| rick / morty | claude-code | JSONL | 有（含 `thread_id`） | 區分 cache | 需價目表 | 2026-08-18 |
| genie | claude-code | JSONL | 有 | 區分 cache | 需價目表 | 2026-08-11 |
| summer | codex | JSONL | 有 | 區分 cache | 需價目表 | 2026-07-21 |
| kimi / walle / eve | opencode | **SQLite** | 有（在 `part.data`） | 區分 cache | **CLI 已算好** | 2026-09-10 |

Claude 家族走訂閱制，token 數不等於帳單金額；opencode 三隻走 OpenRouter，`session.cost`
是 opencode 自己算的實際費用，這幾隻不需要我們自備價目表。

七個要寫進 parser 的重點：

1. **`usage` 底下的嵌套是明細，不是額外用量。** `cache_creation`（ephemeral 1h/5m 的
   TTL 拆解）與 `iterations[]`（每次 iteration）的欄位名跟外層一模一樣，天真加總會
   虛報數倍。`server_tool_use` 是請求次數不是 token。`message.diagnostics.
   cache_miss_reason.cache_missed_input_tokens` 與 compaction 的 `preTokens`/
   `postTokens`/`cumulativeDroppedTokens` 是診斷資訊，完全不是 API 計費項目。

   但要區分**明細**與**巢狀的獨立用量**：`toolUseResult.usage` 是 Task tool 呼叫
   subagent 的用量（實測 genie 有完整子樹，加總正好等於 `toolUseResult.totalTokens`），
   那是**另一次真實的 API 呼叫**，性質跟 `iterations[]` 不同。是否要加取決於
   subagent 自己的訊息有沒有也在 transcript 裡（Claude Code 用 `isSidechain: true`
   標記）——有就會重複、要排除；沒有就是唯一來源、必須加。**此點待查證。**
2. **任務數要數 distinct `message_id`，不是數 `sender_context` 出現次數。** 同一次
   任務會同時出現在 `message.content[].text` 與 `attachment.prompt[].text`
   （codex 是 `payload.content[].text` 與 `payload.message`）。`sender_context` 裡的
   `message_id` 是平台訊息 ID，天然去重鍵。
3. **model 要走路徑白名單。** `message.content[].input.model` 是 Task tool 呼叫
   subagent 時傳的參數（值會是 `opus` 這種簡寫），`<synthetic>` 是 CLI 內部合成訊息
   沒有實際 API 呼叫；codex 的 `payload.collaboration_mode.settings.model` 是設定值。
   只有 `message.model`（codex 為 `payload.model`）是實際計費的 model。
4. **`channel` 欄位不是頻道名稱，而且三個 adapter 語意不一致。** `discord.rs` 硬寫
   `"discord"`、`slack.rs` 硬寫 `"slack"`、`gateway.rs` 放的是
   `event.channel.channel_type`（頻道**型別**）。所以頻道維度只能用 `channel_id`，
   名稱要另外查表（對照表就在本目錄的 values 檔註解裡）。**平台維度也不能靠它**
   ——Google Chat 走 gateway，拿到的會是 channel_type 而非平台名；可靠來源是
   `thread_map.json` 的 `platform:thread_id` key。另外在 thread 裡
   `channel_id` 是**父頻道**、`thread_id` 才是 thread 本身（`discord.rs:2140`）。
5. **opencode 的 token 在四處重複，只能挑一層。** 見下節。

6. **codex 的 `total_token_usage` 是 session 累積值，不是單次用量。** 每個
   `token_count` event 都重報一次到目前為止的累積，加總所有 event 就是把累積值再
   累積（實測 summer：`total_token_usage.total_tokens=418458730` 對
   `last_token_usage.total_tokens=21561974`，差 19.4 倍）。正確做法是每個 session
   取最後一筆 `total_token_usage`，或加總所有 `last_token_usage`。**整個
   `total_token_usage` 子樹都是累積值**，不只 `total_tokens` 那一欄。
7. **opencode 的 `session.model` 是 JSON 物件不是字串**，形如
   `{"id":"deepseek/deepseek-v4-pro-0813","providerID":"openrouter","variant":"low"}`。
   `variant`（實測有 `low`／`default`）是 reasoning effort 之類的變體，可能影響計價，
   所以 model 維度要是 `(id, variant)` 而不只是 id。字串形式的 model 在
   `message.data.modelID`。

### 任務來源要分三類，不是兩類

`cron.rs:714` 的 usercron SenderContext 是 `message_id: None`、`is_bot: true`、
`sender_id: "openab-cron"`。所以 `is_bot` 只能分出「非真人」，分不出「bot 互呼」與
「排程觸發」——後者要靠 `sender_id == "openab-cron"`（或 `message_id` 為空）判別。

實測 Rick 的 163 筆 `sender_context` 拆解如下，三個數字剛好閉合：

| 類別 | 筆數 | 判別 |
| --- | --- | --- |
| 真人 | 17 | `is_bot=false` |
| bot 互呼（三 bot 接力） | ~9 | `is_bot=true` 且有 `message_id` |
| **cron 自動觸發** | **137** | `is_bot=true` 且 `message_id` 為空 |

（17 + 9 = 26，正好等於帶 `message_id` 的筆數。）**Rick 的主要負載來自排程而非人或
接力**，只分「真人 vs bot」會把這件事藏起來。Summer 真人 30／bot 44、Genie 真人
360／bot 22。

另外 `message_id` 為空表示無法用它去重，cron 觸發的任務要改用
`(sender_id, timestamp)` 之類的鍵。

### opencode 的 SQLite 結構

opencode 不寫 JSONL，它把 session 存在 `~/.local/share/opencode/opencode.db`
（SQLite，WAL 模式）。20 張表，統計相關的四張，而**同一筆 token 在四處重複出現**：

| 表 | 用途 | token |
| --- | --- | --- |
| `session` | 每個 session 一列，**權威加總** | `tokens_input/output/reasoning/cache_read/cache_write` + `cost:REAL` |
| `message` | per-message，`data:TEXT` 是 JSON | `data.tokens.{input,output,total,reasoning,cache.{read,write}}` |
| `part` | message 的組成部分；`sender_context` 在這裡 | `data.tokens.*` —— **與 message 層數字相同**（實測 walle 兩者 `tokens.total` 皆 1201009） |
| `event` | event sourcing log | `data.info.tokens.*`、`data.part.tokens.*` —— 又一份 |

所以 parser 只能挑一層：**per-turn 用 `message`，per-session 用 `session`；絕不從
`part` 或 `event` 加總 token。** `sender_context` 走
`part.data` → `part.message_id` → `message.session_id` → `session`。

另外 `session.parent_id` 非空表示是 subagent 的子 session，加總時要處理否則重複。
`model` 也有同值重複路徑（`message.data.modelID` 與 `message.data.model.modelID`），
取前者。實測 kimi 的 DB 裡出現三個 model（`moonshotai/kimi-k3`、
`moonshotai/kimi-k2.7-code`、`google/gemini-3-pro-image-preview`）——一隻 bot 不只用
一個 model，所以資料結構不能假設 bot 與 model 一對一。

DB 正被跑著的 pod 寫入，所以腳本**先把 `db`/`-wal`/`-shm` 複製到暫存目錄再讀複本**，
完全不碰原檔（WAL 模式下連唯讀開啟都可能需要建 `-shm`）。
