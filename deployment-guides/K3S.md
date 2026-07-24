# 三 Bot 遷移到 k3s Runbook

> 把三隻 openab bot（Rick/Morty/Summer）從 Mac mini(OrbStack) + Portainer 搬到**單節點 Ubuntu VM 上的 k3s**。
>
> **策略**：混合——用官方 `charts/openab` Helm chart 當骨架，分兩個 release（`openab-claude`：Rick+Morty；`openab-codex`：Summer），同一 namespace `cac`（團隊共用 namespace，未來其他 CAC 專案也可共用；與這台 cluster 上既有的另一組 openab 部署 `mis-ai`〔跑在 `default`〕區隔開）。Discord token 走 K8s Secret、Morty JIRA 走 secretEnv、**GitHub 雙帳號與 context/skill 走 `kubectl exec` bootstrap**（＝ BOT_SETUP Part E/F/K/N 的 k8s 版）。cutover 用 sleep 隔離 bootstrap 把停機壓到近零。
>
> 設計依據：`docs/superpowers/specs/2026-07-20-k3s-migration-design.md`。values 檔在 `deployment-guides/k3s/`。
>
> **2026-07-24 更新**：已加入第 4 隻 bot（genie，`openab-claude` release，104corp 專案專用、獨立不接力）。本文標題與 Phase A-D 仍是原始三隻的遷移記錄；新增 agent 一律照 [未來加 agent](#未來加-agent) 章節走（該章節已按 genie 實測結果改寫）。

---

## 目錄

- [0. 為什麼這樣設計（速覽）](#0-為什麼這樣設計速覽)
- [1. 前置需求](#1-前置需求)
- [2. 鐵則](#2-鐵則)
- [Phase A — 前置準備（Mac mini 照常）](#phase-a--前置準備mac-mini-照常)
- [Phase B — helm install（sleep 隔離）+ 逐 pod bootstrap](#phase-b--helm-installsleep-隔離--逐-pod-bootstrap)
- [Phase C — 翻轉（唯一停機點）](#phase-c--翻轉唯一停機點)
- [Phase D — 端對端驗證 + 收尾](#phase-d--端對端驗證--收尾)
- [Rollback](#rollback)
- [維運對照](#維運對照)
- [未來加 agent](#未來加-agent)
- [疑難排解](#疑難排解)

---

## 0. 為什麼這樣設計（速覽）

| 決策 | 選擇 | 理由 |
| --- | --- | --- |
| 部署 | Helm chart 骨架 + exec bootstrap | chart 處理 pod/PVC/seccomp 的坑；憑證/context 沿用現行 runbook |
| release | 兩個（claude / codex） | chart 的 securityContext 只能全域；把 Summer 的 seccomp Unconfined 隔離在自己 release |
| Discord token | K8s Secret（不進 inherit_env） | agent 讀不到裸 token |
| JIRA（Morty） | secretEnv | 自動進 inherit_env，agent 讀得到 |
| GitHub token | 只走 exec 餵入，不進 k8s | 維持 gh 雙帳號策略；cluster 無裸 token |

---

## 1. 前置需求

- 單節點 k3s（本 runbook 假設單節點；PVC 用 k3s 內建 `local-path`）。
- `kubectl`、`helm` 已裝且指向該 cluster。
- 你本機 shell 有 `GH_TOKEN_WM4N` / `GH_TOKEN_CAC` 兩把 fine-grained PAT（bootstrap 時餵入，不進 cluster）。
- 三隻 bot 各自的正式 Discord token（cutover 沿用現有）。
- Discord 角色（Part M）：Builder=`1519881066448683201`、Reviewer=`1522274368590184601` 已建；`Analyst`（給 Morty）與團隊角色若還沒建要先建、開「允許任何人 @提及」、取 ID。

---

## 2. 鐵則

- **雪花 ID 一律字串**（channel/user/role/bot）；chart 有浮點精度防呆會 fail。
- **GitHub token 絕不**進 values / Secret / secretEnv / env——只在 bootstrap 用 `echo "$GH_TOKEN_x" | kubectl exec -i ... gh auth login --with-token` 餵入。
- **Discord token 只在** `values-secret*.yaml`（gitignored），`-f` 疊加；不進 git / shell history。
- **檔案擁有權**：`kubectl exec` 以 pod 使用者（uid 1000/node）執行，寫入檔天生 node 擁有——沒有 Mac mini 那個 `docker cp` 變 root 的坑。仍用 `-i` + heredoc 寫檔。

---

## Phase A — 前置準備（Mac mini 照常）

> 此階段不影響 Mac mini/Portainer 上正在服務的三隻。

```bash
# A1. namespace
kubectl create namespace cac

# A2. 確認 local-path storageClass（k3s 內建）
kubectl get storageclass          # 應看到 local-path (default)

# A3. 預拉 image（公開、免 imagePullSecret）
sudo k3s ctr images pull ghcr.io/openabdev/openab-claude:latest
sudo k3s ctr images pull ghcr.io/openabdev/openab-codex:latest

# A4. Morty 的 JIRA secret
kubectl create secret generic morty-jira -n cac \
  --from-literal=JIRA_TOKEN='<你的_atlassian_token>' \
  --from-literal=JIRA_BASE_URL='https://yourorg.atlassian.net' \
  --from-literal=JIRA_EMAIL='<your-email@company.com>'
```

**A5. 填 values 與秘密檔**（在 `deployment-guides/k3s/`）：
- 把 `values-openab-claude.yaml` / `values-openab-codex.yaml` 裡的 `<CHANNEL_ID>`、`<YOUR_USER_ID>`、`<ANALYST_ROLE_ID>` 填上。
- 複製秘密範本並填 Discord token：
  ```bash
  cd deployment-guides/k3s
  cp values-secret-claude.example.yaml       values-secret-claude.yaml
  cp values-secret-codex.example.yaml values-secret-codex.yaml
  # 編輯兩檔填入真實 Discord token（已被 .gitignore）
  ```

**A6. render 驗證**（不碰 cluster；在 `deployment-guides/k3s/` 下執行）：

> ⚠️ `helm lint` **只吃本機 chart 路徑或 .tgz，不接受 `oci://`**。用本機 chart
> `../../charts/openab`（repo 已 clone）——也保證 values 對得上你手上的 chart 版本，
> 避免 OCI 發佈版較舊、缺 `allowedRoleIds`/`cron`/`secretEnv` 欄位。

```bash
helm lint ../../charts/openab \
  -f values-openab-claude.yaml -f values-secret-claude.yaml
helm template openab-claude ../../charts/openab \
  -f values-openab-claude.yaml -f values-secret-claude.yaml \
  | grep -E 'command|allowed_role_ids|inherit_env|working_dir'
```
確認：兩隻 `command = "claude-agent-acp"`、Morty 有 `allowed_role_ids` 與 `inherit_env=[JIRA_*]`、`working_dir = "/home/node"`。codex 同理（換 values-openab-codex.yaml / values-secret-codex.yaml）確認 `type: Unconfined`、`codex-acp`、`shell_environment_policy.inherit=all`。

---

## Phase B — helm install（sleep 隔離）+ 逐 pod bootstrap

> 目標：pod 起來但 openab **不連 Discord**，才能在 Mac mini 仍運行時安全 bootstrap（同一 token 不能兩處連線）。

**B1. install 兩個 release**（在 `deployment-guides/k3s/` 下）：
```bash
# 用本機 chart（推薦，與 A6 驗證同一份、欄位保證對得上）
helm install openab-claude ../../charts/openab -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml
helm install openab-codex  ../../charts/openab -n cac \
  -f values-openab-codex.yaml -f values-secret-codex.yaml
```
> `helm install` 也接受 OCI（`oci://ghcr.io/openabdev/charts/openab`）或 GitHub Pages repo；
> 但若 A6 驗證顯示 OCI 版缺欄位，就用本機 chart 或 `--version` 指定較新版。

**B2. 若 pod 因未登入 openab 而 crashloop → 用 sleep 覆蓋暫停連線**（bootstrap 期間不連 Discord）：
```bash
for d in openab-claude-rick openab-claude-morty openab-codex-summer; do
  kubectl -n cac patch deploy "$d" --type=json \
    -p='[{"op":"add","path":"/spec/template/spec/containers/0/command","value":["sleep","infinity"]}]'
done
kubectl get pods -n cac       # 三個 pod 應為 Running（sleep）
```
> 這是 BOT_SETUP Part I「sleep 待命再切正式」在 k8s 的等價做法。

**B3. 逐 pod bootstrap**（取實際 pod 名 `kubectl get pods -n cac`；以下用 `$POD`）

① Claude/Codex 登入（需 TTY）：
```bash
kubectl exec -it <rick-pod>   -n cac -- claude auth login
kubectl exec -it <morty-pod>  -n cac -- claude auth login
kubectl exec -it <summer-pod> -n cac -- codex login --device-auth
```

② gh 雙帳號登入（token 從你本機 shell 餵入，不進 cluster）——對三隻各做：
```bash
echo "$GH_TOKEN_WM4N" | kubectl exec -i $POD -n cac -- gh auth login --hostname github.com --with-token
echo "$GH_TOKEN_CAC"  | kubectl exec -i $POD -n cac -- gh auth login --hostname github.com --with-token
kubectl exec -i $POD -n cac -- gh auth setup-git
kubectl exec $POD -n cac -- gh auth status     # 應看到 wm4n + cac-william
```

③ clone repo + checkout（skill 本體 + context 來源）——對三隻各做：
```bash
kubectl exec -i $POD -n cac -- sh -c '
  git clone https://github.com/wm4n/openab.git /home/node/github-repo/openab 2>/dev/null \
    || git -C /home/node/github-repo/openab pull
  cd /home/node/github-repo/openab && git checkout docs/three-bot-pipeline && git pull'
```

④ cat v2 context + 裝 plugin skill（依角色；標準已改為純 CLI plugin 安裝，見 BOT_SETUP Part K2a/K2b。skill 清單見 Part K）：

> 2026-07-22 起：`feature-development`/`repo-identity`/`openab-schedule`/`requirement-analysis`/`change-review`/`change-review-codex` 已不再手動 symlink，改由 `wm4n/skill-registry` 這個 marketplace 的 `openab-bot-skills` plugin 統一安裝；persona 檔（Rick/Morty-CLAUDE_v2.md、Summer-AGENTS_v2.md）已改為引用裸名（如 `feature-development`，不帶 `openab-bot-skills:` 前綴），三隻皆已實測確認可用。

Rick：
```bash
kubectl exec -i <rick-pod> -n cac -- sh -c '
  CK=/home/node/github-repo/openab/deployment-guides
  cat $CK/Rick-CLAUDE_v2.md > /home/node/CLAUDE.md'
kubectl exec <rick-pod> -n cac -- claude plugin marketplace add wm4n/skill-registry
kubectl exec <rick-pod> -n cac -- claude plugin install openab-bot-skills@wm4n-skill-registry
```

Morty（多 requirement-analysis / change-review + jira-fetch + superpowers）：
```bash
kubectl exec -i <morty-pod> -n cac -- sh -c '
  CK=/home/node/github-repo/openab/deployment-guides
  cat $CK/Morty-CLAUDE_v2.md > /home/node/CLAUDE.md'
kubectl exec <morty-pod> -n cac -- claude plugin marketplace add wm4n/skill-registry
kubectl exec <morty-pod> -n cac -- claude plugin install openab-bot-skills@wm4n-skill-registry
# jira-fetch 依 BOT_SETUP Part K2 另裝（clone + symlink，尚未切換成 plugin）
# superpowers 純 CLI（見 BOT_SETUP Part K2a）：
kubectl exec <morty-pod> -n cac -- claude plugin marketplace add anthropics/claude-plugins-official
kubectl exec <morty-pod> -n cac -- claude plugin install superpowers@claude-plugins-official
```

Summer（Codex → `codex plugin`，見 BOT_SETUP Part K2a/K2b）：
```bash
kubectl exec -i <summer-pod> -n cac -- sh -c '
  CK=/home/node/github-repo/openab/deployment-guides
  cat $CK/Summer-AGENTS_v2.md > /home/node/AGENTS.md'
kubectl exec <summer-pod> -n cac -- codex plugin marketplace add wm4n/skill-registry
kubectl exec <summer-pod> -n cac -- codex plugin add openab-bot-skills@wm4n-skill-registry
# superpowers（Codex 版，marketplace 來源與 Claude 端不同）：
kubectl exec <summer-pod> -n cac -- codex plugin marketplace add obra/superpowers-marketplace
kubectl exec <summer-pod> -n cac -- codex plugin add superpowers@superpowers-marketplace
```

⑤ Summer 專屬 — 寫 `~/.codex/config.toml`（issue #1047）：
```bash
kubectl exec -i <summer-pod> -n cac -- sh -c 'cat > /home/node/.codex/config.toml' <<'EOF'
sandbox_mode = "danger-full-access"
approval_policy = "on-request"
approvals_reviewer = "auto_review"
[projects."/home/node"]
trust_level = "trusted"
[features]
multi_agent = true
EOF
```

⑥ Rick 專屬 — openspec：確認可用。`npm i -g` 會被 readonly rootfs 擋 → 建議 image 預裝，或裝到 HOME(PVC) 下。rollout 時確認（見疑難排解）。

> **openspec profile 切換（一次性，Rick 專屬）**：`feature-development` skill 依規格明確程度分別會用到 `new`/`ff`（expanded workflow，不在預設 `core` profile 裡）與 `propose`（在 `core` 裡）。custom profile **不會自動繼承** core 的 `propose`/`apply`/`archive`，兩組要一起勾，否則切了 custom 反而失去 `propose`：
> ```bash
> kubectl exec -it <rick-pod> -n cac -- openspec config profile
> # Workflows only → 勾選 propose, explore, new, continue, apply, ff, archive → 確認
> ```
> 這是每個容器一次性的全域設定（`~/.config/openspec`），設完後日後對任何新 repo 跑 `openspec init` 都會自動套用該 profile，不用每個 repo 重做。`kubectl exec <rick-pod> -n cac -- openspec config list` 可確認 workflows 同時含 `propose` 與 `new`/`ff`。

**B4. 本機驗證（不碰 Discord）**——逐 pod：
```bash
kubectl exec $POD -n cac -- sh -c '
  gh auth status;
  ls ~/.claude/skills 2>/dev/null || ls ~/.codex/skills;
  cat ~/.claude/plugins/installed_plugins.json 2>/dev/null || cat ~/.codex/plugins.json 2>/dev/null;
  head -1 ~/CLAUDE.md 2>/dev/null || head -1 ~/AGENTS.md'
```
確認：兩帳號、`openab-bot-skills`/`superpowers` plugin 都已安裝（`~/.claude/skills`／`~/.codex/skills` 目前只剩 `jira-fetch` 這類仍走手動 symlink 的 skill）、persona 標題都在。

---

## Phase C — 翻轉（唯一停機點）

```bash
# C1. 停 Mac mini / Portainer 三隻（釋出 Discord token）
#   Mac mini: docker -c orbstack stop openab-rick openab-summer
#   Portainer: 網頁 Stop Morty 容器

# C2. 移除 sleep 覆蓋，讓 openab 正常啟動、連 Discord（用正式 token）
for d in openab-claude-rick openab-claude-morty openab-codex-summer; do
  kubectl -n cac patch deploy "$d" --type=json \
    -p='[{"op":"remove","path":"/spec/template/spec/containers/0/command"}]'
done

# C3. 驗證上線
kubectl get pods -n cac
kubectl logs deploy/openab-claude-rick -n cac | grep -i discord   # 連線成功
```
> 若 B 階段沒用 patch、而是別的方式暫停連線，C2 改用對應方式恢復。

---

## Phase D — 端對端驗證 + 收尾

沿用 `bot-skills/ROLLOUT-CHECKLIST.md` + BOT_SETUP K5：

1. 三 pod healthy；Discord 上三隻上線。
2. **角色觸發**（Part M）：`@Analyst`→Morty、`@Builder`→Rick、`@Reviewer`→Morty+Summer 同 thread。
3. **完整 pipeline 一輪**：@Analyst 給 Issue→產 spec→人工閘門→@Builder→Rick 開 PR→@Reviewer→Morty+Summer review→clean→人類 merge。全程 mention 只在 handoff 行、無 bot 互 @ 迴圈。
4. **usercron 冒煙測**（Part L）：對一隻寫每分鐘 ping 的 `~/.openab/cronjob.toml`，確認頻道 1 分鐘內收到，然後移除。

穩定運行數天無誤後，才退役 Mac mini（見 Rollback）。

---

## Rollback

- Mac mini/Portainer 容器**只停不刪**、volume 保留。
- k3s 翻車 → 停 k3s（`kubectl scale deploy --all --replicas=0 -n cac` 或 `helm uninstall openab-claude openab-codex -n cac`）→ 到 Mac mini/Portainer `docker start` / Start 三隻 → token 回舊環境。**幾分鐘可逆。**
- 確認 k3s 穩定數天後，才 `docker rm` Mac mini 容器與 volume。

---

## 維運對照（全 `-n cac`）

| 動作 | Mac mini | k3s |
| --- | --- | --- |
| 看狀態 | `docker ps` | `kubectl get pods -n cac` |
| 看 log | `docker logs -f openab-rick` | `kubectl logs -f deploy/openab-claude-rick -n cac` |
| 進容器 | `docker exec -it ... bash` | `kubectl exec -it <pod> -n cac -- bash` |
| 重啟 | `docker restart` | `kubectl rollout restart deploy/<name> -n cac` |
| 改 context/skill（Part N） | `docker exec … git pull + cat` | `kubectl exec … git pull + cat` → 開新 thread |

**改動 → 動作：**

| 改什麼 | 動作 | 重啟 |
| --- | --- | --- |
| openab 設定（channel/role/cron/互呼） | 改 values → `helm upgrade <release> ... -f ...` | chart config checksum 自動滾動重啟該 pod |
| Discord/JIRA token | 改 `values-secret*.yaml` / secret → upgrade / 重啟 | 要 |
| CLAUDE.md/AGENTS.md、skill | `kubectl exec` git pull + 重 cat（Part N） | 不用，開新 thread |
| `cronjob.toml` 排程（Part L） | `kubectl exec` 改 PVC 上的檔 | 不用，熱重載 |

> 部署名慣例：`<release>-<agentKey>` → `openab-claude-rick`、`openab-claude-morty`、`openab-codex-summer`。

---

## 未來加 agent

> 2026-07-24 實際加過第 4 隻（Claude 家族，代號 genie，104corp 專案專用、不跟其他 bot 接力）驗證過一輪，下面已按實測結果改寫；舊版「PVC 自動生成」的說法已經過時（那時還沒把 Rick/Morty/Summer 從 `local-path` 遷到靜態 `cac-local`，見 Phase A 的 storage 決策）。

依 seccomp 家族塞進對應 release，新 agent key 全小寫、可含 `-`（不能開頭/結尾是 `-`）：

- **Claude 家族** → `values-openab-claude.yaml` 加 `agents.<name>`。
- **Codex 家族** → `values-openab-codex.yaml` 加 `agents.<name>`（自動繼承 Unconfined）。

### 1. Discord Application

新建 Application（Bot 分頁拿 token、開 **MESSAGE CONTENT INTENT**——忘記開這個會在 pod log 看到 `Discord rejected privileged intents`）、OAuth2 URL Generator 邀進 workspace、記下 bot user ID；要限制誰能 `@` 的話先建對應 Discord 角色拿 role ID（Part M）。

### 2. 靜態 PV（`cac-local` 用 `no-provisioner`，PVC 不會自動長出 PV）

**這步最容易漏，漏了 PVC 會卡 `Pending` 或（更糟）悄悄落到 `local-path` 佔用根碟。** 每個 agent 一顆，`claimRef` 精準指定 PVC 名稱（`<release>-<agentKey>`，見上方「維運對照」的部署名慣例）：

```bash
mkdir -p /data/william/openab/agent-<name>
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: pv-cac-<name>
spec:
  capacity:
    storage: <跟 values 的 persistence.size 一致，例如 60Gi>
  accessModes: ["ReadWriteOnce"]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: cac-local
  local:
    path: /data/william/openab/agent-<name>
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values: ["openab"]
  claimRef:
    namespace: cac
    name: <release>-<name>   # 例如 openab-claude-genie
EOF
```

### 3. values 檔加 agent 區塊 + 秘密檔加 token

`persistence.storageClass` 一定要寫 `cac-local`（留空會退回叢集 default `local-path`，落根碟）。`values-secret-claude.yaml`（或 codex 版）的 `agents.<name>.discord.botToken` 也要加，這兩者是分開的檔案，漏了任一邊都會造成「pod 起得來但 Discord adapter 沒接上」（log 印 `discord=false`、`Error: no adapter configured`，即使另一邊看起來設對了）。

若要跟 Rick/Morty/Summer 互相 `@mention` 接力，`env.HANDOFF_*` 也要在這步加（見 Part K2b）；完全獨立、不接力的 bot（如 genie）不需要。

### 4. `helm upgrade`（不是 install，加進既有 release）

```bash
helm upgrade <openab-claude 或 openab-codex> ../../charts/openab -n cac -f <values 檔> -f <secret 檔>
```

**重啟互相獨立，已實測確認**：chart 的 `deployment.yaml` 對每個 agent 各自算自己的 `checksum/config`（`{{- range $name, $cfg := .Values.agents }}`），只要這次改動沒動到 Rick/Morty/Summer 自己的區塊，它們的 Deployment manifest 不會變、不會被連帶重啟。

### 5. Bootstrap（比照 Phase B3，只跑在新 pod）

- `kubectl exec -it ... -- claude`（或 `codex`）互動登入。
- gh 登入：只服務單一帳號的 repo（如 genie 只碰 104corp）就只登入那個帳號，不用比照 Rick/Morty/Summer 走雙帳號 + `repo-identity` skill。
- 若該 agent 要用 openspec：`npm config set prefix /home/node/.npm-global && npm install -g @fission-ai/openspec@latest`，`values` 加 `env.PATH` 指到 `~/.npm-global/bin`（見疑難排解）；要 `/opsx:new`/`/opsx:ff` 這類 expanded workflow 指令，另外 `openspec config profile` 切換 + `openspec update`。
- 裝 skill plugin：**先決定這隻 bot 是「接力型」還是「獨立型」，兩者裝不同 plugin，不要混裝**：
  - 接力型（會跟其他 bot `@mention` 交棒）→ `claude plugin install openab-bot-skills@wm4n-skill-registry`。
  - 獨立型（自己一手包辦，不跟其他 bot 互動）→ `claude plugin install solo-bot-skills@wm4n-skill-registry`。
  - 兩個 plugin 刻意分開維護（`wm4n/skill-registry`），不是同一包裝好靠 persona 文件叫它「不要用」——結構上隔開，ACP 的語意比對才不會選錯（例如獨立型 bot 誤觸發 `feature-development`，或接力型 bot 誤觸發 `solo-feature-pipeline`）。
- 寫 persona：新建 `<Name>-CLAUDE_v2.md`（或 Codex 用 AGENTS.md），`cat` 進 `/home/node/CLAUDE.md`。
- 全部裝完後跑一次 `deployment-guides/k3s/update-context.sh` / `update-skills.sh`，把新 bot 也納入固定的更新腳本。

---

## 疑難排解

| 症狀 | 原因 | 解法 |
| --- | --- | --- |
| Summer 所有 shell 指令 ❌（`unshare failed: Operation not permitted`） | seccomp 沒放寬，bwrap 建不了 namespace | 確認 `values-openab-codex.yaml` 的 `podSecurityContext.seccompProfile.type: Unconfined` 有生效；`kubectl exec <summer-pod> -n cac -- unshare --user echo ok` 應回 `ok` |
| pod crashloop、log 說沒登入 / 沒 config | openab 啟動時 Claude/Codex 未登入 | 用 Phase B2 的 sleep 覆蓋，bootstrap 完再移除 |
| 雪花 ID 被 chart 拒（`mangled ID`） | values 用了數字而非字串 | 所有 ID 用引號字串，或 `--set-string` |
| gh `restart 後消失` | 登入時非 node / PVC 沒持久 / env 有裸 `GH_TOKEN` | 以 node 登入；確認 PVC 掛 `/home/node`；別設裸 `GH_TOKEN` |
| Rick `npm i -g openspec` 失敗（readonly rootfs） | `containerSecurityContext.readOnlyRootFilesystem: true` 擋寫 `/usr/lib` | 改 image 預裝 openspec，或 `npm config set prefix /home/node/.npm-global` 裝到 PVC 並把 `~/.npm-global/bin` 加進 PATH |
| PVC Pending（新 bot，用 `cac-local`） | 忘記手動建對應的靜態 PV（`cac-local` 是 `no-provisioner`，不會自動生成） | 見「未來加 agent」步驟 2，先建 PV 且 `claimRef` 指到正確 PVC 名稱 |
| PVC Pending（舊 default storageClass） | `local-path`（k3s 內建 dynamic）名不符或未設 | 這台叢集慣例已改用 `cac-local`（見 Phase A），非本 runbook 情境才用內建 default |
| `helm upgrade` 報 PVC spec immutable（`cannot patch ... StorageClassName`） | 這個 PVC 當初用了錯的 storageClass 建立（如誤落 `local-path`），PVC spec 綁定後除容量外都不可變 | 沒有原地修正的辦法：`kubectl delete pvc <name> -n cac`（沒有寶貴資料就直接刪，新 bot 通常沒有）→ 重新 `helm upgrade` 讓它用正確 storageClass 重建 |
| 靜態 PV 一直 `Pending`、`kubectl get pv` 顯示該 PV 是 `Released` 不是 `Available` | PV 曾經綁定過又被解除（例如上一步刪掉了誤建的 PVC），`Retain` policy 不會自動變回 `Available` | `kubectl patch pv <pv名> -p '{"spec":{"claimRef": null}}'`，清掉舊 claimRef 讓它變 `Available`，會自動被等待中的 PVC 綁走 |
| `kubectl delete pvc` 指令卡住不動 | PVC 有 `pvc-protection` finalizer，還有 pod 在用它 | Ctrl+C 中斷（不影響，已標記 Terminating）→ `kubectl delete pod <pod> -n cac --force --grace-period=0` 斷開 → PVC 幾秒內自動真的刪除 |
| pod crash，`kubectl logs --previous` 抓不到（`unable to retrieve container logs`） | crash 太快，containerd 已經清掉該次 container 的 log | 改用 `kubectl logs deploy/<name> -n cac -c openab --tail=200`（不加 `--previous`，可能還沒被清）；還是抓不到就 `kubectl logs -f` 即時盯著看下次崩潰，或看 `kubectl describe pod ... \| grep -A15 "Last State:"` 的 Exit Code |
| Discord adapter 沒接上（log `discord=false`、`Error: no adapter configured`），即使 secret 看起來設對了 | `values-secret*.yaml` 的 `botToken` 沒接上、或 `discord.enabled` 實際沒生效——直接查 `kubectl get configmap <name> -n cac -o yaml` 確認渲染出的 `config.toml` 真的有 `[discord]` 區塊，比猜測可靠 | 確認兩個檔案（agent values + secret values）都對這個 agent 名字設對，`helm upgrade` 兩個 `-f` 都要帶到 |
| pod 連上 Discord 但立刻報 `Discord rejected privileged intents` | Discord Developer Portal 忘記開 **MESSAGE CONTENT INTENT** | Bot 分頁 → Privileged Gateway Intents → 開啟 → `kubectl rollout restart deploy/<name> -n cac`（不用 helm upgrade）|
| 兩隻 bot 同一 token 都回應/互踢 | Mac mini 與 k3s 同 token 同時連線 | cutover 時先停 Mac mini（Phase C1）再移除 k3s sleep（C2） |
