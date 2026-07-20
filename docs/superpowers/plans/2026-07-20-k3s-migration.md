# 三 Bot 遷移到 k3s 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 產出把三隻 openab bot（Rick/Morty/Summer）遷移到單節點 k3s 所需的部署工件與 runbook，讓遷移可在團隊 Ubuntu VM 上照步驟執行。

**Architecture:** 混合策略——用官方 `charts/openab` Helm chart 當骨架，分兩個 release（`openab-claude`：Rick+Morty，RuntimeDefault；`openab-codex`：Summer，Unconfined），同一 namespace `openab`。Discord token 走 K8s Secret（不進 inherit_env）、Morty JIRA 走 secretEnv、GitHub 雙帳號與 context/skill 走 kubectl exec bootstrap。cutover 用 sleep 隔離 bootstrap 把停機壓到近零。

**Tech Stack:** k3s（單節點）、Helm、官方 openab-claude/openab-codex image、local-path PVC。

**設計依據**：`docs/superpowers/specs/2026-07-20-k3s-migration-design.md`。

## 兩階段

- **Group A（Task 1–4，本 repo）**：可 commit、可審的工件。驗證＝`helm lint` / `helm template | grep`（在有 helm 的機器執行；本機可 `brew install helm`，或在 VM 上）。
- **Group B（Task 5–9，團隊 VM）**：實際遷移操作，全寫在 Task 4 的 K3S.md，由操作者在 VM 執行。這些 task 的「驗證」在 VM 上完成。

## Global Constraints（每個 task 隱含適用）

- namespace 一律 `openab`；兩 release 名 `openab-claude`、`openab-codex`。
- 所有 Discord 雪花 ID（channel/user/role/bot）在 values 一律用**字串**（引號），或 `--set-string`；chart 對浮點精度損毀有防呆會 fail。
- `workingDir: /home/node`（三隻都是；HOME 跟著它）。
- GitHub token **絕不**進 values / Secret / secretEnv / env —— 只在 bootstrap 時從操作者 shell 經 `kubectl exec -i` 餵入 `gh auth login --with-token`。
- Discord token **不進** `inherit_env`（agent 不可見）。
- 操作者填入的值以 `<...>` 標記：`<CHANNEL_ID>`、`<YOUR_USER_ID>`、`<ANALYST_ROLE_ID>`、`<TEAM_ROLE_ID>`。已知固定 ID 直接寫死。
- 已知固定 ID：Builder 角色 `1519881066448683201`、Reviewer 角色 `1522274368590184601`；bot user ID：Rick `1519868630064562278`、Morty `1521431781641818202`、Summer `1522253638465093752`。
- 秘密檔 `values-secret.yaml` 必須被 gitignore，永不 commit。

---

## Task 1: k3s 工件目錄與秘密防護

**Files:**
- Create: `deployment-guides/k3s/.gitignore`
- Create: `deployment-guides/k3s/values-secret.example.yaml`
- Create: `deployment-guides/k3s/README.md`

**Interfaces:**
- Produces: `deployment-guides/k3s/` 目錄；`values-secret.yaml` 檔名約定（Task 2/3/6 引用）。

- [ ] **Step 1: 建 .gitignore 擋真實秘密檔**

`deployment-guides/k3s/.gitignore`：
```
values-secret.yaml
```

- [ ] **Step 2: 建 secret 範本**

`deployment-guides/k3s/values-secret.example.yaml`：
```yaml
# 複製成 values-secret.yaml（已被 .gitignore，永不 commit）填入真實值。
# helm install/upgrade 時以 -f values-secret.yaml 疊加，讓 Discord token 不進 git/shell history。
agents:
  rick:
    discord:
      botToken: "<RICK_DISCORD_BOT_TOKEN>"
  morty:
    discord:
      botToken: "<MORTY_DISCORD_BOT_TOKEN>"
```
> Summer 的 token 放在 codex release 專屬的 values-secret（Task 3 說明），此檔僅 claude release 用。

- [ ] **Step 3: 建 README 說明目錄用途**

`deployment-guides/k3s/README.md`：
```markdown
# k3s 部署工件

三隻 bot 遷移到 k3s 的 Helm values 與秘密範本。完整步驟見 `../K3S.md`。

- `values-openab-claude.yaml` — Rick + Morty（RuntimeDefault）
- `values-openab-codex.yaml`  — Summer（Unconfined）
- `values-secret.example.yaml` — 複製成 `values-secret.yaml`（gitignored）填 Discord token

安裝：`helm install openab-claude oci://ghcr.io/openabdev/charts/openab -f values-openab-claude.yaml -f values-secret.yaml -n openab`
（chart 來源以實際發佈位置為準，見 K3S.md）
```

- [ ] **Step 4: 驗證 gitignore 生效**

Run: `cd deployment-guides/k3s && touch values-secret.yaml && git status --porcelain values-secret.yaml && rm values-secret.yaml`
Expected: 無輸出（表示 values-secret.yaml 被忽略、不會被 git 追蹤）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/.gitignore deployment-guides/k3s/values-secret.example.yaml deployment-guides/k3s/README.md
git commit -m "docs(k3s): k3s 工件目錄骨架與秘密防護"
```

---

## Task 2: openab-claude values（Rick + Morty）

**Files:**
- Create: `deployment-guides/k3s/values-openab-claude.yaml`

**Interfaces:**
- Consumes: `values-secret.yaml`（botToken，Task 1 約定）。
- Produces: `openab-claude` release 的 values；agent key `rick`、`morty`（deployment 名 `openab-claude-rick`/`openab-claude-morty`）。

- [ ] **Step 1: 寫 values（Rick + Morty，RuntimeDefault、chart 預設 podSecurityContext 不覆蓋）**

`deployment-guides/k3s/values-openab-claude.yaml`：
```yaml
# openab-claude release：Rick + Morty（Claude 家族，維持預設 seccomp RuntimeDefault）
# 秘密（Discord token）由 -f values-secret.yaml 疊加；不要寫在這裡。
image:
  repository: ghcr.io/openabdev/openab-claude

agents:
  rick:
    command: claude-agent-acp
    args: []
    workingDir: /home/node
    discord:
      enabled: true
      allowedChannels: ["<CHANNEL_ID>"]
      allowedUsers: ["<YOUR_USER_ID>"]
      allowBotMessages: "mentions"
      trustedBotIds: ["1521431781641818202", "1522253638465093752"]  # Morty, Summer
      allowedRoleIds: ["1519881066448683201"]  # Builder
    pool: { maxSessions: 5, sessionTtlHours: 24 }
    persistence: { enabled: true, size: 2Gi }

  morty:
    command: claude-agent-acp
    args: []
    workingDir: /home/node
    discord:
      enabled: true
      allowedChannels: ["<CHANNEL_ID>"]
      allowedUsers: ["<YOUR_USER_ID>"]
      allowBotMessages: "mentions"
      trustedBotIds: ["1519868630064562278", "1522253638465093752"]  # Rick, Summer
      allowedRoleIds: ["<ANALYST_ROLE_ID>", "1522274368590184601"]  # Analyst, Reviewer
    # JIRA 憑證：先 kubectl create secret generic morty-jira --from-literal=...（見 K3S.md）
    secretEnv:
      - { name: JIRA_TOKEN,    secretName: morty-jira, secretKey: JIRA_TOKEN }
      - { name: JIRA_BASE_URL, secretName: morty-jira, secretKey: JIRA_BASE_URL }
      - { name: JIRA_EMAIL,    secretName: morty-jira, secretKey: JIRA_EMAIL }
    pool: { maxSessions: 5, sessionTtlHours: 24 }
    persistence: { enabled: true, size: 2Gi }
```
> `allowBotMessages: "mentions"`＋`trustedBotIds` 對應 BOT_SETUP Part K 的 bot 互呼。`allowedRoleIds` 對應 Part M 角色觸發。`<ANALYST_ROLE_ID>` 與 channel/user 由操作者填。

- [ ] **Step 2: 驗證 render 成功且無 lint 錯**

Run: `helm lint charts/openab -f deployment-guides/k3s/values-openab-claude.yaml --set agents.rick.discord.botToken=x --set agents.morty.discord.botToken=y`
Expected: `1 chart(s) linted, 0 chart(s) failed`
> 給假 botToken 只為通過 render（真值走 values-secret.yaml）。若本機無 helm：`brew install helm` 或在 VM 執行。

- [ ] **Step 3: 驗證生成的 config.toml 內容正確**

Run:
```bash
helm template openab-claude charts/openab \
  -f deployment-guides/k3s/values-openab-claude.yaml \
  --set agents.rick.discord.botToken=x --set agents.morty.discord.botToken=y \
  | grep -E 'command = "claude-agent-acp"|allowed_role_ids|inherit_env|working_dir = "/home/node"'
```
Expected: 看到兩隻 `command = "claude-agent-acp"`、Morty 的 `allowed_role_ids`、`inherit_env = ["JIRA_TOKEN","JIRA_BASE_URL","JIRA_EMAIL"]`、`working_dir = "/home/node"`。

- [ ] **Step 4: 驗證未覆蓋 podSecurityContext（維持 RuntimeDefault）**

Run: `grep -c 'seccompProfile\|Unconfined' deployment-guides/k3s/values-openab-claude.yaml`
Expected: `0`（此 release 不動 seccomp，沿用 chart 預設 RuntimeDefault）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/values-openab-claude.yaml
git commit -m "docs(k3s): openab-claude release values（Rick+Morty）"
```

---

## Task 3: openab-codex values（Summer）

**Files:**
- Create: `deployment-guides/k3s/values-openab-codex.yaml`
- Create: `deployment-guides/k3s/values-secret-codex.example.yaml`

**Interfaces:**
- Consumes: `values-secret-codex.yaml`（Summer botToken）。
- Produces: `openab-codex` release 的 values；agent key `summer`（deployment 名 `openab-codex-summer`）。

- [ ] **Step 1: 寫 codex 秘密範本**

`deployment-guides/k3s/values-secret-codex.example.yaml`：
```yaml
# 複製成 values-secret-codex.yaml（gitignore 已含 values-secret*.yaml? 見下步）填 Summer token。
agents:
  summer:
    discord:
      botToken: "<SUMMER_DISCORD_BOT_TOKEN>"
```

- [ ] **Step 2: 擴充 .gitignore 也擋 codex 秘密檔**

Modify: `deployment-guides/k3s/.gitignore`，改為：
```
values-secret.yaml
values-secret-codex.yaml
```

- [ ] **Step 3: 寫 codex values（Unconfined 覆蓋 podSecurityContext）**

`deployment-guides/k3s/values-openab-codex.yaml`：
```yaml
# openab-codex release：Summer（Codex 家族）。
# ⚠️ seccomp 放寬到 Unconfined，讓 codex-acp 內部 bwrap 能建 user namespace（openab issue #1047）。
# 此覆蓋 chart-global podSecurityContext，套用到本 release 所有 agent（目前只有 Summer）。
image:
  repository: ghcr.io/openabdev/openab-codex

podSecurityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  seccompProfile:
    type: Unconfined

agents:
  summer:
    command: codex-acp
    args: ["-c", "shell_environment_policy.inherit=all"]
    workingDir: /home/node
    discord:
      enabled: true
      allowedChannels: ["<CHANNEL_ID>"]
      allowedUsers: ["<YOUR_USER_ID>"]
      allowBotMessages: "mentions"
      trustedBotIds: ["1519868630064562278", "1521431781641818202"]  # Rick, Morty
      allowedRoleIds: ["1522274368590184601"]  # Reviewer
    pool: { maxSessions: 5, sessionTtlHours: 24 }
    persistence: { enabled: true, size: 2Gi }
```
> Codex 內部 `~/.codex/config.toml`（issue #1047 三 key）不在 values——由 bootstrap 寫進 PVC（K3S.md）。

- [ ] **Step 4: 驗證 render 且 seccomp 為 Unconfined**

Run:
```bash
helm template openab-codex charts/openab \
  -f deployment-guides/k3s/values-openab-codex.yaml \
  --set agents.summer.discord.botToken=x \
  | grep -E 'seccompProfile|type: Unconfined|command = "codex-acp"|shell_environment_policy'
```
Expected: 看到 `type: Unconfined`、`command = "codex-acp"`、`shell_environment_policy.inherit=all`。

- [ ] **Step 5: 驗證 gitignore 擋住兩個秘密檔**

Run: `cd deployment-guides/k3s && touch values-secret.yaml values-secret-codex.yaml && git status --porcelain | grep -c values-secret && rm values-secret.yaml values-secret-codex.yaml`
Expected: `0`

- [ ] **Step 6: Commit**

```bash
git add deployment-guides/k3s/values-openab-codex.yaml deployment-guides/k3s/values-secret-codex.example.yaml deployment-guides/k3s/.gitignore
git commit -m "docs(k3s): openab-codex release values（Summer, Unconfined）"
```

---

## Task 4: K3S.md 遷移 runbook + BOT_SETUP 指路

**Files:**
- Create: `deployment-guides/K3S.md`
- Modify: `deployment-guides/BOT_SETUP.md`（TOC + 新增指路小節，指向 K3S.md）

**Interfaces:**
- Consumes: Task 1–3 的 values 檔。
- Produces: 操作者在 VM 執行的完整步驟（Group B 的 task 5–9 內容以此為準）。

- [ ] **Step 1: 寫 K3S.md**（章節：前置、Phase A 前置、Phase B 隔離 bootstrap、Phase C 翻轉、Phase D 驗證、rollback、維運對照、加 agent）。內容照 spec §5/§7/§8，指令用本計畫 Task 5–9 的確切指令。含開頭警語：GitHub token 只走 exec 餵入、Discord token 只在 values-secret、雪花 ID 用字串。

- [ ] **Step 2: BOT_SETUP 加指路**

Modify `deployment-guides/BOT_SETUP.md`：TOC 在 Part N 後加一行，並在 Part N 之後、維運之前加一小節：
```markdown
## Part O — 遷移到 k3s

> 把三隻 bot 從 Mac mini/Portainer 搬到單節點 k3s 的完整步驟另見 `deployment-guides/K3S.md`（Helm chart 骨架 + exec bootstrap 混合、兩 release 分 seccomp、近零停機 cutover）。設計依據見 `docs/superpowers/specs/2026-07-20-k3s-migration-design.md`。
```

- [ ] **Step 3: 驗證連結與結構**

Run: `grep -n 'K3S.md' deployment-guides/BOT_SETUP.md && test -f deployment-guides/K3S.md && grep -c '^## ' deployment-guides/K3S.md`
Expected: BOT_SETUP 有指向 K3S.md 的行；K3S.md 存在且有多個 `##` 章節。

- [ ] **Step 4: Commit**

```bash
git add deployment-guides/K3S.md deployment-guides/BOT_SETUP.md
git commit -m "docs(k3s): 新增 K3S.md 遷移 runbook 與 BOT_SETUP Part O 指路"
```

---

## Task 5:（VM）Phase A — 前置準備

> 在團隊 Ubuntu VM 上執行。Mac mini 三隻**照常運行**、不受影響。

- [ ] **Step 1: 建 namespace**

Run: `kubectl create namespace openab`
Expected: `namespace/openab created`

- [ ] **Step 2: 確認 local-path storageClass**

Run: `kubectl get storageclass`
Expected: 看到 `local-path (default)`（k3s 內建 Rancher local-path-provisioner）。

- [ ] **Step 3: 預拉 image 並確認可取得**

Run: `sudo k3s ctr images pull ghcr.io/openabdev/openab-claude:latest && sudo k3s ctr images pull ghcr.io/openabdev/openab-codex:latest`
Expected: 兩個 image 都 `done`（公開、免 imagePullSecret）。

- [ ] **Step 4: 建 Discord 角色並取得 ID**

在 Discord 建 `Analyst`（給 Morty）與需要的團隊角色，開「允許任何人 @提及」，複製角色 ID（Builder/Reviewer 已知，見 Global Constraints）。把 `<ANALYST_ROLE_ID>` 等填進 Task 2/3 的 values 檔。

- [ ] **Step 5: 建 morty-jira secret**

Run:
```bash
kubectl create secret generic morty-jira -n openab \
  --from-literal=JIRA_TOKEN='<你的_atlassian_token>' \
  --from-literal=JIRA_BASE_URL='https://yourorg.atlassian.net' \
  --from-literal=JIRA_EMAIL='<your-email@company.com>'
```
Expected: `secret/morty-jira created`

- [ ] **Step 6: 複製並填秘密檔**

Run:
```bash
cp deployment-guides/k3s/values-secret.example.yaml deployment-guides/k3s/values-secret.yaml
cp deployment-guides/k3s/values-secret-codex.example.yaml deployment-guides/k3s/values-secret-codex.yaml
# 編輯兩檔填入真實 Discord token
```
Expected: 兩個 values-secret*.yaml 存在且已填 token（git 忽略）。

---

## Task 6:（VM）Phase B — helm install（bootstrap 模式，不連 Discord）

> 目標：pod 起來但 openab 不連 Discord，才能在 Mac mini 仍運行時安全 bootstrap（避免同 token 雙連線）。

- [ ] **Step 1: 以 sleep 覆蓋安裝 openab-claude**

先確認 chart 是否支援 command override；若無，安裝後用 `kubectl patch` 暫時把 deployment command 改為 sleep。安裝：
```bash
helm install openab-claude charts/openab -n openab \
  -f deployment-guides/k3s/values-openab-claude.yaml \
  -f deployment-guides/k3s/values-secret.yaml
```
若 pod 因未登入而 crashloop → 立即暫停連線：
```bash
kubectl -n openab patch deploy openab-claude-rick  --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/command","value":["sleep","infinity"]}]'
kubectl -n openab patch deploy openab-claude-morty --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/command","value":["sleep","infinity"]}]'
```
Expected: `openab-claude-rick`、`openab-claude-morty` pod 進入 Running（sleep）。

- [ ] **Step 2: 同法安裝 openab-codex（Summer）**

```bash
helm install openab-codex charts/openab -n openab \
  -f deployment-guides/k3s/values-openab-codex.yaml \
  -f deployment-guides/k3s/values-secret-codex.yaml
kubectl -n openab patch deploy openab-codex-summer --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/command","value":["sleep","infinity"]}]'
```
Expected: `openab-codex-summer` pod Running（sleep）。

- [ ] **Step 3: 驗證三 pod 都 Running 且未連 Discord**

Run: `kubectl get pods -n openab`
Expected: 三個 pod `Running`；Discord 上三隻仍是 Mac mini 版本在服務（k3s 版未上線）。

---

## Task 7:（VM）Phase B — 逐 pod bootstrap

> 對三隻各做一次（`RICK=openab-claude-rick` 之類，取實際 pod 名 `kubectl get pods -n openab`）。全部 `-n openab`。

- [ ] **Step 1: Claude/Codex 登入**

```bash
kubectl exec -it <rick-pod>   -n openab -- claude auth login
kubectl exec -it <morty-pod>  -n openab -- claude auth login
kubectl exec -it <summer-pod> -n openab -- codex login --device-auth
```
Expected: 三隻憑證落在各自 PVC（`ls ~/.claude` / `~/.codex` 有東西）。

- [ ] **Step 2: gh 雙帳號登入（token 從本機 shell 餵入）**

對每隻：
```bash
echo "$GH_TOKEN_WM4N" | kubectl exec -i <pod> -n openab -- gh auth login --hostname github.com --with-token
echo "$GH_TOKEN_CAC"  | kubectl exec -i <pod> -n openab -- gh auth login --hostname github.com --with-token
kubectl exec -i <pod> -n openab -- gh auth setup-git
```
Expected: `kubectl exec <pod> -n openab -- gh auth status` 顯示 wm4n + cac-william 兩帳號。

- [ ] **Step 3: clone repo + symlink skills + cat context**

對每隻（skill 清單依角色，見 BOT_SETUP Part K）：
```bash
kubectl exec -i <pod> -n openab -- sh -c '
  git clone https://github.com/wm4n/openab.git /home/node/github-repo/openab 2>/dev/null || git -C /home/node/github-repo/openab pull
  cd /home/node/github-repo/openab && git checkout docs/three-bot-pipeline && git pull
  mkdir -p /home/node/.claude/skills'   # Summer 改 ~/.codex/skills
```
接著各自 symlink 對應 skill、`cat <persona>_v2.md > CLAUDE.md`（Summer→AGENTS.md）。
Expected: `ls ~/.claude/skills`（或 `~/.codex/skills`）看到對應 symlink；`head -1 CLAUDE.md/AGENTS.md` 為對應 persona 標題。

- [ ] **Step 4: Summer 專屬 — 寫 ~/.codex/config.toml + 裝 superpowers**

```bash
kubectl exec -i <summer-pod> -n openab -- sh -c 'cat > /home/node/.codex/config.toml' <<'EOF'
sandbox_mode = "danger-full-access"
approval_policy = "on-request"
approvals_reviewer = "auto_review"
[projects."/home/node"]
trust_level = "trusted"
[features]
multi_agent = true
EOF
```
Rick 專屬：確認 openspec 可用（image 預裝或裝到 HOME，見 spec §3.1）。
Expected: `kubectl exec <summer-pod> -n openab -- cat ~/.codex/config.toml` 有三個 key。

- [ ] **Step 5: 本機驗證（不碰 Discord）**

Run（逐 pod）: `kubectl exec <pod> -n openab -- sh -c 'gh auth status; ls ~/.claude/skills 2>/dev/null || ls ~/.codex/skills; head -1 ~/CLAUDE.md 2>/dev/null || head -1 ~/AGENTS.md'`
Expected: 兩帳號、skill symlink、persona 標題都在。

---

## Task 8:（VM）Phase C — 翻轉（唯一停機點）

- [ ] **Step 1: 停 Mac mini/Portainer 三隻（釋出 token）**

在 Mac mini：`docker -c orbstack stop openab-rick openab-summer`；Portainer 上 Stop Morty 容器。
Expected: Discord 上三隻離線。

- [ ] **Step 2: 移除 sleep 覆蓋，讓 openab 正常啟動**

```bash
kubectl -n openab patch deploy openab-claude-rick  --type=json -p='[{"op":"remove","path":"/spec/template/spec/containers/0/command"}]'
kubectl -n openab patch deploy openab-claude-morty --type=json -p='[{"op":"remove","path":"/spec/template/spec/containers/0/command"}]'
kubectl -n openab patch deploy openab-codex-summer --type=json -p='[{"op":"remove","path":"/spec/template/spec/containers/0/command"}]'
```
> 若 Task 6 是用 chart 原生 command override（非 patch），改為 `helm upgrade` 移除該 override。
Expected: 三 pod 重建、openab 正常啟動、連上 Discord（用正式 token）。

- [ ] **Step 3: 驗證上線**

Run: `kubectl get pods -n openab && kubectl logs deploy/openab-claude-rick -n openab | grep -i discord`
Expected: 三 pod Running/healthy；log 顯示 Discord 連線成功；Discord 上三隻上線。

---

## Task 9:（VM）Phase D — 端對端驗證 + 收尾

- [ ] **Step 1: 角色觸發**

在 Discord：`@Analyst`→Morty 回、`@Builder`→Rick 回、`@Reviewer`→Morty+Summer 同 thread 回。
Expected: 對照 BOT_SETUP Part M 行為。

- [ ] **Step 2: 完整 pipeline 一輪**

依 BOT_SETUP K5：@Analyst 給 Issue→產 spec→人工閘門→@Builder→Rick 開 PR→@Reviewer→Morty+Summer review→clean→人類 merge。
Expected: 全程 handoff 只在 handoff 行 @、無 bot 互 @ 迴圈。

- [ ] **Step 3: usercron 冒煙測（Part L）**

對一隻寫每分鐘 ping 的 `~/.openab/cronjob.toml`，確認頻道 1 分鐘內收到，然後移除。
Expected: 熱重載生效、收到 ping。

- [ ] **Step 4: 穩定期後退役 Mac mini**

k3s 穩定運行數天無誤後，才 `docker rm` Mac mini 容器與 volume。此前 Mac mini 只停不刪，作為 rollback（停 k3s pod → `docker start` Mac mini）。
Expected: 遷移完成。

---

## Self-Review

**Spec coverage：**
- §2 決策 → Task 1–4 values/runbook 全涵蓋 ✓
- §3 架構/§3.1 待驗 → Task 2/3 values（workingDir、PVC、seccomp）+ Task 7 openspec/rootfs 待驗註記 ✓
- §4 設定對應/§4.1 三種秘密 → Task 2（JIRA secretEnv）、Task 1/3（Discord token values-secret）、Task 7 Step 2（GitHub exec）✓
- §5 bootstrap → Task 7 ✓
- §6 seccomp → Task 3（Unconfined 覆蓋）✓
- §7 cutover → Task 6（sleep 隔離）/8（翻轉）/9（驗證+rollback）✓
- §8 擴充/維運 → Task 4 K3S.md 內含 ✓

**Placeholder scan：** `<CHANNEL_ID>`/`<YOUR_USER_ID>`/`<ANALYST_ROLE_ID>`/`<TEAM_ROLE_ID>`/`<...TOKEN>` 皆為 operator 必填的環境值（同 BOT_SETUP 慣例），非實作空洞；已知固定 ID 已寫死。Task 4 K3S.md 的內文為文件產出，內容綱要與指令來源已在 Task 5–9 給出具體指令。

**Type/名稱一致：** release 名 `openab-claude`/`openab-codex`、deployment 名 `openab-claude-rick`/`-morty`/`openab-codex-summer`、角色/bot ID 全計畫一致 ✓

**已知待驗（spec §3.1/§7 已載明，執行時確認，非計畫缺口）：** uid 1000、readonly rootfs 寫入點、openspec 安裝位置、chart 是否原生支援 command override（否則用 kubectl patch，Task 6/8 已給 patch 備援）。
