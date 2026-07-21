# 三 Bot 遷移到 k3s — 設計 spec

> **日期**：2026-07-20
> **範圍**：把現行三隻 openab bot（Morty/Rick/Summer）從 Mac mini(OrbStack) + 另一台(Portainer) 遷移到團隊單節點 Ubuntu VM 上的 k3s。
> **前置閱讀**：`deployment-guides/BOT_SETUP.md`（現行部署）、`charts/openab`（官方 Helm chart）。

## 1. 背景與現況

現行三隻 bot：

| Bot | 引擎 | 現在的家 | 角色 |
| --- | --- | --- | --- |
| Morty | Claude(`claude-agent-acp`) | 另一台 · Portainer | 分析 + PR 複審 |
| Rick | Claude(`claude-agent-acp`) | Mac mini · OrbStack | openspec 開發 |
| Summer | Codex(`codex-acp`) | Mac mini · OrbStack | code review |

現行安全/運行模型（要在 k3s 上保留）：

- **GitHub 走 gh 雙帳號**（wm4n / cac-william）存在持久 volume 的 `~/.config/gh`，每任務 `gh auth switch`；GitHub token **不進 agent env**。
- **Discord token** 經 env 注入供 openab 展開，但**不進** `inherit_env`（agent 讀不到）。
- **Morty 的 JIRA_\*** 經 `inherit_env` 給 agent。
- **Summer(Codex)** 需要放寬 seccomp 讓內部 bwrap 建 namespace（Mac mini 上是 `--security-opt seccomp=unconfined`；openab issue #1047）。
- context 檔（CLAUDE.md/AGENTS.md）為 **v2 單檔版**，skill 以 symlink 指向容器內 git checkout（BOT_SETUP Part K/N）。
- pipeline 以**角色 mention** 接力：Analyst(Morty)、Builder(Rick)、Reviewer(Morty+Summer)（BOT_SETUP Part M）。

## 2. 決策彙整

| 決策 | 選擇 | 理由 |
| --- | --- | --- |
| 遷移模式 | **直接切換 (cutover)** | 停機短、最單純；用 sleep 隔離 bootstrap 把停機壓到近零（見 §7）。 |
| 部署策略 | **混合**：chart 當骨架 + Discord token 走 K8s Secret + 憑證/context/skill 走 exec bootstrap | 前期工小、風險低、與現行 runbook 幾乎無縫；chart 幫忙處理 k8s 的坑（seccomp/uid/PVC）。 |
| release 佈局 | **兩個 release**（`openab-claude`：Rick+Morty；`openab-codex`：Summer），同一 namespace `cac` | chart 的 securityContext 只能 chart-global、不能 per-agent；把放寬 seccomp 的範圍限在只需要的 Codex 家族。 |
| namespace | `cac`（團隊共用；rollout 實測時修正，見下方附註） | 原定案 `openab` 過於通用；rollout 實測發現同一 cluster 已有另一組 openab 部署（`mis-ai`，跑在 `default`），改用團隊名稱 `cac` 避免與軟體名混淆，並供未來其他 CAC 專案共用。 |
| image | 官方 `ghcr.io/openabdev/openab-claude`、`openab-codex`（公開、免 imagePullSecret） | 與現行同一套 image。 |

## 3. 架構與拓撲

```
Ubuntu VM ── k3s (單節點)
└── namespace: cac
    ├── release: openab-claude   (seccompProfile: RuntimeDefault, 硬化)
    │   ├── agent "rick"   → Deployment + PVC + ConfigMap + Secret
    │   └── agent "morty"  → Deployment + PVC + ConfigMap + Secret
    └── release: openab-codex    (seccompProfile: Unconfined, 為 bwrap)
        └── agent "summer" → Deployment + PVC + ConfigMap + Secret
```

每隻 bot 的 pod：

```
Pod (replicas=1, strategy=Recreate)
├── container: openab  (image: openab-claude 或 openab-codex)
│   ├── HOME=/home/node          ← workingDir 設 /home/node（非 chart 預設 /home/agent）
│   ├── /home/node   ← PVC（持久：.claude/.codex 憑證、.config/gh、CLAUDE.md、clone 的 repo、.openab/cronjob.toml）
│   ├── /etc/openab  ← ConfigMap（chart 從 values 生成的 config.toml，唯讀）
│   └── /tmp         ← emptyDir（readonly rootfs 下的可寫暫存）
└── env: DISCORD_BOT_TOKEN ← 從 K8s Secret 注入（不進 inherit_env）
```

設計要點：

1. 一個 release = 一組 seccomp → Claude/Codex 家族分兩 release。
2. 每隻 agent 一個獨立 PVC（k3s 內建 `local-path`，單節點免煩惱 storageClass）。
3. `replicas=1` + `Recreate`（chart 寫死）：RWO PVC 不可多 pod 共享，也避免同一 token 同時兩 pod 連線。
4. 三隻各自獨立 Discord application/token（cutover 沿用現有正式 token）。

### 3.1 待驗事實（rollout 時確認，勿預設為真）

- Claude/Codex image 的使用者 `node` 是否 = uid 1000（對上 `podSecurityContext.runAsUser: 1000`）。
- `containerSecurityContext.readOnlyRootFilesystem: true` 下，Claude Code / codex-acp 是否只寫 HOME(PVC) 與 /tmp(emptyDir)；若寫別處要加 `extraVolumeMounts` 或放寬。
- Rick 的 openspec：`npm i -g` 需寫 root fs（被 readonly 擋）→ 改 image 預裝或裝到 HOME(PVC)。

## 4. 設定對應（BOT_SETUP → chart values）

chart 從 `values.yaml` 生成 config.toml（掛成 ConfigMap → `/etc/openab/config.toml`）。改 values，不是改 config.toml。

| BOT_SETUP | chart values | 備註 |
| --- | --- | --- |
| `[agent] command` | `agents.<name>.command` | Rick/Morty=`claude-agent-acp`、Summer=`codex-acp` |
| `[agent] args` | `agents.<name>.args` | Summer 保留 `["-c","shell_environment_policy.inherit=all"]` |
| `working_dir` | `agents.<name>.workingDir` | 設 `/home/node`（HOME 跟著它） |
| `allowed_channels` | `discord.allowedChannels` | ⚠️ 一律 `--set-string`／values 檔（雪花 ID 浮點精度；chart 有防呆會 fail） |
| `allowed_users` | `discord.allowedUsers` | 同上 |
| `allow_bot_messages` | `discord.allowBotMessages` | `"mentions"` |
| `trusted_bot_ids` | `discord.trustedBotIds` | 另兩隻 bot ID |
| `allowed_role_ids`(Part M) | `discord.allowedRoleIds` | Analyst/Builder/Reviewer/團隊角色 ID |
| `[cron]`+`cronjob.toml`(Part L) | `cron.usercronEnabled`/`cron.usercronPath`/`cronjobs[]` | usercron 開關與 baseline job |
| Morty `JIRA_*`(`inherit_env`) | `secretEnv` | 自動加進 inherit_env |

### 4.1 三種秘密，三種處理

1. **Discord token → K8s Secret，agent 不可見**
   chart 從 `discord.botToken` 生 Secret（key `discord-bot-token`），deployment 以 `secretKeyRef` 注入 `DISCORD_BOT_TOKEN` env（供 openab 展開 `${DISCORD_BOT_TOKEN}`）。**不進 `inherit_env`**。為避免 token 進 git/shell history：放進 gitignore 的 `values-secret-claude.yaml`，`helm install -f values.yaml -f values-secret-claude.yaml`。

2. **Morty JIRA 憑證 → `secretEnv`（agent 需讀）**
   `kubectl create secret generic morty-jira --from-literal=...`，再 `agents.morty.secretEnv: [{name: JIRA_TOKEN, secretName: morty-jira, secretKey: JIRA_TOKEN}, ...]`。chart 自動把這些 key 加進 `inherit_env`。

3. **GitHub 雙帳號 token → 不進 k8s 任何地方**
   bootstrap 時 `echo "$GH_TOKEN_WM4N" | kubectl exec -i <pod> -- gh auth login --with-token`，token 從本機 shell 餵入、登入狀態寫進 PVC 的 `~/.config/gh`。cluster 內無裸 GH token。
   ⚠️ **絕不**用 secretEnv 帶 GH token（會進 env+inherit_env，讓 agent 看到裸 token，且裸 `GH_TOKEN` 會使 `gh auth switch` 失效）。

**CLAUDE.md/AGENTS.md**：不用 chart 的 `agentsMd`（靜態 configMap、會遮蔽 PVC 檔、失去 Part N 的 git pull+重 cat 流程）。改走 exec bootstrap 把 v2 檔 cat 進 PVC 的 `/home/node/CLAUDE.md`（§5）。

## 5. exec bootstrap（每隻 pod 一次性設定）

`helm install` 只拉起 pod + PVC；接著每隻 pod 做 bootstrap（＝ BOT_SETUP Part E/F/K/N 的 k8s 版，`docker exec`→`kubectl exec`，全部 `-n cac`）。

共同步驟：

1. **Claude/Codex 登入**（OAuth，需 TTY）
   - Rick/Morty：`kubectl exec -it <pod> -- claude auth login`
   - Summer：`kubectl exec -it <pod> -- codex login --device-auth`
2. **gh 雙帳號登入**（token 從本機 shell 餵入）
   ```
   echo "$GH_TOKEN_WM4N" | kubectl exec -i <pod> -- gh auth login --hostname github.com --with-token
   echo "$GH_TOKEN_CAC"  | kubectl exec -i <pod> -- gh auth login --hostname github.com --with-token
   kubectl exec -i <pod> -- gh auth setup-git
   ```
3. **clone openab repo**（skill 本體 + context 來源）到 `/home/node/github-repo/openab`，checkout `docs/three-bot-pipeline`。
4. **symlink skills**（Rick/Morty → `~/.claude/skills`；Summer → `~/.codex/skills`）。
5. **cat v2 context**（Rick/Morty → `CLAUDE.md`；Summer → `AGENTS.md`）。
6. **重啟**載入憑證與 context：`kubectl rollout restart deploy/<name> -n cac`。

各自專屬：

- **Morty**：skills = `wm4n.requirement-analysis`/`wm4n.change-review`/`wm4n.repo-identity`/`wm4n.schedule-management` + `jira-fetch` + `superpowers.*`；`superpowers` 需互動 `/plugins` 裝一次。
- **Rick**：skill = `wm4n.feature-development`；openspec（image 預裝或裝到 HOME，見 §3.1）。
- **Summer**：skill = `wm4n.change-review-codex`；寫 `~/.codex/config.toml`（issue #1047 三 key：`sandbox_mode`/`approvals_reviewer`/`multi_agent`）。

好處：`kubectl exec` 以 pod 使用者（uid 1000/node）執行，寫入檔天生 node 擁有，無 Mac mini 的「docker cp 變 root」坑。仍用 `-i` + heredoc 寫檔。

## 6. seccomp / release 佈局的依據

chart 的 `podSecurityContext`/`containerSecurityContext` **只能 chart-global，不能 per-agent**（已核 `charts/openab/templates/deployment.yaml`）。

- Summer(Codex) 需 `seccompProfile: Unconfined`（bwrap 靠 `unshare`/`clone` 建 user namespace；預設 `RuntimeDefault` 會擋 → 所有 shell 指令死在 `unshare failed: Operation not permitted`）。
- Rick/Morty(Claude) 不需要，維持 `RuntimeDefault` 較安全。

seccomp Unconfined 只移除 syscall 過濾層，不給 root/不加 capabilities/不 privileged；容器仍被非 root(uid 1000)、drop ALL caps、readonly rootfs、各種 namespace 隔離。三隻同屬「人類把關、container 即沙箱」的信任等級，但兩 release 把不必要的放寬限在 Codex 家族，符合最小權限。

## 7. cutover 順序 + 驗證 + rollback

**Phase A — 前置（Mac mini 照常，無衝突）**
1. k3s 準備：namespace、確認 `local-path` storageClass、預拉 image。
2. 寫兩 release 的 `values.yaml` + gitignore 的 `values-secret-claude.yaml`。
3. 建 Discord 角色拿 ID 填 values；`kubectl create secret morty-jira`。
4. `helm install` 兩 release，pod 以 **bootstrap 模式**啟動（不連 Discord；沿用 Part I 的 `sleep infinity` 覆蓋）。

**Phase B — 隔離 bootstrap（無衝突）**
5. 每隻 pod 跑 §5。
6. 本機驗證（不碰 Discord）：`gh auth status` 兩帳號、`ls ~/.claude`/`~/.codex`、skill symlink、`head -1 CLAUDE.md`。

**Phase C — 翻轉（唯一停機點，短窗口）**
7. 停 Mac mini/Portainer 三隻（token 釋出）。
8. `helm upgrade` 把 pod 從 sleep 切成正常 `openab run`（連 Discord、正式 token）。
9. pod 轉 healthy、Discord 上線。

**Phase D — 端對端驗證**（沿用 `bot-skills/ROLLOUT-CHECKLIST.md` + BOT_SETUP K5）
10. 三隻 healthy；`@Analyst`→Morty、`@Builder`→Rick、`@Reviewer`→Morty+Summer 同 thread；跑一條完整 pipeline（Issue→spec→PR→review→clean）；usercron ping 測一次。

**Rollback**
- Mac mini 容器**只停不刪**、volume 保留。k3s 翻車 → 停 k3s pod（`kubectl scale --replicas=0` 或 `helm uninstall`）→ `docker start` Mac mini 三隻。幾分鐘可逆。
- k3s 穩定運行數天後才退役 Mac mini。

**待實作確認**：pod「起來但不連 Discord」的最可靠做法是 Part I 的 `sleep infinity` 命令覆蓋；chart 是否直接支援 `command` override，或用 `kubectl patch deployment` 暫改，於 writing-plans 階段對 image entrypoint 確認。備案：`discord.enabled=false` 裝、bootstrap 後再 upgrade 開啟（前提 openab 允許無 adapter 待命）。

## 8. 擴充與維運

**加 agent**：Claude 家族 → `openab-claude` values 加 `agents.<name>`；Codex 家族 → `openab-codex`（自動繼承 Unconfined）。`helm upgrade` → 新 pod+PVC → 對新 pod 跑 §5 bootstrap（含自己的 Discord app/token）。

**維運對照（全 `-n cac`）**：

| 動作 | Mac mini | k3s |
| --- | --- | --- |
| 看狀態 | `docker ps` | `kubectl get pods -n cac` |
| 看 log | `docker logs -f openab-rick` | `kubectl logs -f deploy/openab-claude-rick -n cac` |
| 進容器 | `docker exec -it ... bash` | `kubectl exec -it <pod> -n cac -- bash` |
| 重啟 | `docker restart` | `kubectl rollout restart deploy/<name> -n cac` |
| 改 context/skill(Part N) | `docker exec … git pull + cat` | `kubectl exec … git pull + cat` → 開新 thread |

**改動 → 動作**：

| 改什麼 | 動作 | 重啟 |
| --- | --- | --- |
| openab 設定（channel/role/cron/互呼） | 改 values → `helm upgrade` | chart config checksum 自動滾動重啟 |
| Discord/JIRA token | 改 Secret / `values-secret-claude.yaml` → upgrade | 要 |
| CLAUDE.md/AGENTS.md、skill | `kubectl exec` git pull + 重 cat（Part N） | 不用，開新 thread |
| `cronjob.toml` 排程（Part L） | `kubectl exec` 改 PVC 上的檔 | 不用，熱重載 |

## 9. 交付物（供 writing-plans 展開）

1. `openab-claude` 的 `values.yaml`（Rick + Morty；Morty 帶 JIRA secretEnv、cron；RuntimeDefault）。
2. `openab-codex` 的 `values.yaml`（Summer；Unconfined、Codex args）。
3. gitignore 的 `values-secret-claude.yaml` 樣板（Discord token）。
4. bootstrap runbook（§5 的逐 pod 指令），並回寫 `BOT_SETUP.md` 成一個 k3s 章節。
5. cutover checklist（§7）。

## 10. 非目標（YAGNI）

- 不做 multi-node / HA（單節點 VM）。
- 不做 GitOps/ArgoCD、不把憑證改成全宣告式（維持 exec bootstrap）。
- 不動 pipeline 邏輯（角色 mention、skill 內容）——本次純部署遷移。
- 不引入 gateway/其他平台 adapter。
