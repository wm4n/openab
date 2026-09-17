# Mac(OrbStack) 維運腳本

Mac mini `CAC@2771`（hostname `2771-Z411210004.local`）上三隻 bot —— **Rick / Morty / Summer** —— 的維運腳本。

完整部署脈絡見 [`../BOT_SETUP.md`](../BOT_SETUP.md)，逐字的 config.toml 與建置步驟見 [`../ORBSTACK-ROLLBACK.md`](../ORBSTACK-ROLLBACK.md)。

> **為什麼跟 [`../k3s/`](../k3s/) 的同名腳本分開？** 兩套 bot 跑在兩台不同的機器上：Mac 這邊要 `docker -c orbstack exec`、k3s 那邊要 `kubectl exec`，而 Mac 沒有 kubeconfig、k3s VM 沒有 OrbStack，互相碰不到對方的容器。刻意不做成一支「自動偵測環境」的腳本——那只會讓「在哪台機器上跑」變得不明確。
>
> 2026-09-15 三隻從 k3s 搬回 Mac 之後，`../k3s/` 那兩支腳本曾一度還列著已刪除的 `openab-claude-rick`／`-morty`／`openab-codex-summer`，又是 `set -euo pipefail`，導致第一隻就中止、連 genie 都更新不到。現在已拆乾淨：k3s 版只管 k3s 上的 bot，本目錄只管 Mac 上的三隻。

## 腳本

| 檔案 | 用途 | 多久跑一次 |
| --- | --- | --- |
| `update-context.sh` | `git pull` openab repo，重新 `cat` persona（`Rick-CLAUDE_v2.md` 等）進容器的 `CLAUDE.md`／`AGENTS.md` | persona 改版後 |
| `update-skills.sh` | 刷新 marketplace 快照 + install/update 各 plugin。三隻的組合一致：`solo-bot-skills`／`openab-bot-skills`／`skill-registry`／`superpowers`／`team-bot`／`mattpocock-skills` | skill 改版後 |
| `openab-archive.sh` | 把三隻的 transcript 累積鏡像到 `~/openab-archive/mirror`（**不刪任何東西**） | **每週**（見下方） |

```bash
bash update-context.sh
bash update-skills.sh
bash openab-archive.sh
```

> 前兩支跑完都要**到 Discord 對三隻各開一條新 thread** 才生效——context 檔與 skill 都在 session 啟動時載入，舊 thread 不會重讀，但**不需要重啟容器**。

> ⚠️ **`mattpocock-skills` 在 Summer 上是未驗證路徑**：它來自 `anthropics/claude-plugins-official`，而 Codex 端當初就是因為這個 marketplace 沒驗證通過，superpowers 才改用 `obra/superpowers-marketplace`（見 [`../BOT_SETUP.md`](../BOT_SETUP.md) K2a）。腳本把 Summer 這段包成「失敗不中斷、只印警告」，跑完請看有沒有 ⚠️ 並用 `codex plugin list` 確認，別以為它靜悄悄裝好了。

## 🔴 transcript 保留期限：兩件事都要做

claude-code 會自動刪除超過 `cleanupPeriodDays`（**預設 30 天**）的 transcript，而那是使用統計唯一的資料來源。三隻 2026-09-15 搬回 Mac 時是全新 bootstrap，**k3s 節點上那套保護（`cleanupPeriodDays: 365` + 每週 rsync 鏡像）完全沒有跟過來**。背景見 [`../K3S.md`](../K3S.md)「transcript 保留期限」。

### 1. 調高保留期限（一次性，每個容器各做一次）

用 `node -e` 合併寫入（不要用 `jq`——映像沒裝；`node` 是 base image 本來就有的）：

```bash
for c in openab-rick openab-morty; do
  echo "--- $c ---"
  docker -c orbstack exec -i -u node "$c" node -e '
const fs = require("fs");
const path = "/home/node/.claude/settings.json";
let settings = {};
try { settings = JSON.parse(fs.readFileSync(path, "utf8")); } catch (e) {}
settings.cleanupPeriodDays = 365;
fs.writeFileSync(path, JSON.stringify(settings, null, 2));
console.log(JSON.stringify(settings));
'
done
```

- **只對 Claude 家族（Rick/Morty）有意義**；Summer 是 codex，不吃這個鍵（實測 codex 端的保留期限比 claude-code 長很多，但沒有對應設定可調）。
- **為什麼是 365 不是更大**：實測 genie 30 天長了 141MB（約 4.7MB/日、1.7GB/年）。一年夠所有分析用途，無上限地留會有一天把磁碟塞爆而沒人發現。
- ⚠️ **`cleanupPeriodDays` 是推定的鍵名**。Claude Code 對不認識的鍵是**靜默忽略**——設錯不會報錯、也不會壞掉，但也不會生效。真正的驗證要等 30 天後回頭看最舊的 transcript 有沒有繼續往前推。**在那之前，第 2 步的鏡像才是可靠的保護。**

### 2. 掛上每週鏡像（這步不依賴任何推論，先做這個）

```bash
cp openab-archive.sh ~/openab-archive.sh && chmod +x ~/openab-archive.sh
crontab -l 2>/dev/null | { cat; echo "0 2 * * 0 $HOME/openab-archive.sh >> $HOME/openab-archive.log 2>&1"; } | crontab -
crontab -l | tail -2
```

**判斷準則是「間隔 < 保留期限」，不是固定頻率**：保留期限 30 天的話，今天同步一次就涵蓋過去 30 天，29 天後再同步兩次會重疊、不會有缺口。**每週一次有 4 倍餘裕**。

⚠️ macOS 的 `cron` 需要「完全取用磁碟」權限，且**睡眠中不會補跑**。機器常闔蓋的話改用 launchd（`StartCalendarInterval`）比較可靠。

### 3. 之後要把這三隻納入使用統計

鏡像的輸出佈局（`<bot>/{claude-projects,codex-sessions,openab}`）**刻意對齊 k3s 那份**，所以 [`../k3s/usage-stats/collect.py`](../k3s/usage-stats/README.md) 不用改就吃得到：

```bash
python3 ../k3s/usage-stats/collect.py --root <不存在的目錄> \
  --out <輸出目錄> --archive-root ~/openab-archive/mirror
```

⚠️ 目前 usage-stats 的 CronJob **整個還沒部署**，而且它跑在 k3s 節點、讀的是那台的 `hostPath`，**結構上永遠收不到 Mac 這三隻**。要納入就得走上面這條手動路徑，或在 Mac 上另外排一支。
