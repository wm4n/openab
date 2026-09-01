# Genie 裝 Docker（給不用 mise 的 PHP repo 用）

## 為什麼這樣裝

- 有些 PHP repo（例如 `104corp/104cac-appapi-m104-facade`）不是用 `.mise.toml`/`.tool-versions` 宣告環境，而是自己一份 `Dockerfile`（`FROM ghcr.io/104corp/<私有 base image>`，微調設定）+ `Makefile`（`make build`/`make run`/`make composer`/`make bash`/`make unit` 這類 target）。要照著這份 Makefile 跑，Genie 需要有 `docker` 可以用。
- Genie 主 container 是 `readOnlyRootFilesystem: true`，裝不了 Docker daemon，也不能 `apt install`。解法是在**同一個 pod** 裡加一個獨立的 `dind`（docker-in-docker）sidecar container，只有這個 sidecar 開 `privileged: true`，Genie 自己的主 container 完全不變、也不影響 Rick/Morty（改動只在 genie 自己的 values 區塊）。
- 主 container 裝一支免安裝的 `docker` 靜態執行檔（放 `~/.local/bin`，PVC 上，已在 PATH），透過 `DOCKER_HOST=tcp://localhost:2375` 連到旁邊的 dind sidecar（同 pod 共用 network namespace，走 localhost）。
- 兩個 container 掛同一顆 PVC 到同一個路徑（`/home/node`），`docker run -v $(CURDIR):/var/www/html` 這種 bind mount 才能在 dind 裡解到正確路徑。
- Docker 的 image cache（`/var/lib/docker`）放獨立 `emptyDir`，不佔用/不需要新申請靜態 PV；代價是 pod 重啟後 base image 要重新拉一次。

## Step 1：values.yaml 已經改好，helm upgrade

`values-openab-claude.yaml` 的 genie 區塊已加上 `DOCKER_HOST` env、`extraContainers`（dind sidecar）、`extraVolumes`（image cache 用的 emptyDir），commit 已經推上去。跑（在有 helm/kubectl 存取權的機器）：

```bash
cd ~/william/github/openab/deployment-guides/k3s   # 換成你本機實際路徑
git pull
```

**先 render 驗證，不碰 cluster**：

```bash
helm lint ../../charts/openab -f values-openab-claude.yaml -f values-secret-claude.yaml
helm template openab-claude ../../charts/openab \
  -f values-openab-claude.yaml -f values-secret-claude.yaml \
  | grep -A20 'name: dind'
```
確認能看到 `image: docker:27-dind`、`privileged: true`、兩個 `volumeMounts`（`data` 掛 `/home/node`、`docker-data` 掛 `/var/lib/docker`）。

**套用**：

```bash
helm upgrade openab-claude oci://ghcr.io/openabdev/charts/openab --version 0.9.0-beta.1 -n cac \
  -f values-openab-claude.yaml -f values-secret-claude.yaml
kubectl rollout status deployment/openab-claude-genie -n cac
```
只有 genie 的 pod 會重啟（chart 對每個 agent 各自算 checksum，這次沒動 Rick/Morty 的區塊）。

## Step 2：確認 dind sidecar 起來

```bash
kubectl get pods -n cac -o wide | grep genie      # 應該看到 2/2 Ready（openab + dind 兩個 container）
kubectl logs deployment/openab-claude-genie -n cac -c dind --tail=30   # dind daemon 啟動 log，不該有 error
```

> ⚠️ genie pod 現在有兩個 container 了。之後對它下 `kubectl exec`，如果沒指定 `-c`，預設會用第一個 container（`openab`），跟以前行為一致；要進 dind 本身才需要加 `-c dind`。

## Step 3：主 container 裝 docker CLI（靜態執行檔，不需要 root）

先確認架構，再抓對應的靜態版本：

```bash
kubectl exec deployment/openab-claude-genie -n cac -c openab -- uname -m
```

```bash
kubectl exec deployment/openab-claude-genie -n cac -c openab -- sh -c '
  ARCH=$(uname -m)
  case "$ARCH" in
    x86_64)  DARCH=x86_64 ;;
    aarch64) DARCH=aarch64 ;;
    *) echo "unknown arch: $ARCH"; exit 1 ;;
  esac
  cd /tmp
  curl -fsSL "https://download.docker.com/linux/static/stable/${DARCH}/docker-27.3.1.tgz" -o docker.tgz
  tar xzf docker.tgz docker/docker
  mv docker/docker ~/.local/bin/docker
  chmod +x ~/.local/bin/docker
  rm -rf docker docker.tgz
  which docker
'
```

驗證能連到 dind daemon：

```bash
kubectl exec deployment/openab-claude-genie -n cac -c openab -- docker version
```
應該同時看到 Client 與 Server 兩段版本資訊（Server 就是隔壁 dind sidecar）。

## Step 4：登入私有 registry（複用既有憑證，不申請新的）

`ghcr.io/104corp/*` 的私有 base image需要登入。叢集已經有 `ghcr-104corp` 這個 k8s secret（給 openab 自己拉 image 用），直接借用同一組帳密：

```bash
kubectl get secret ghcr-104corp -n cac -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d
```
輸出會是類似 `{"auths":{"ghcr.io":{"username":"...","password":"...","auth":"..."}}}` 的 JSON，記下 `username`/`password`（這兩個值只在你本機終端機看到，不要貼到 Discord 或任何聊天記錄）。

```bash
kubectl exec -it deployment/openab-claude-genie -n cac -c openab -- \
  docker login ghcr.io -u '<上面抓到的 username>' -p '<上面抓到的 password>'
```
登入資訊會寫進 `~/.docker/config.json`（在 PVC 上），pod 重啟不會遺失，之後不用重登。

## Step 5：拿範例 repo 實測一輪全流程

```bash
kubectl exec -it deployment/openab-claude-genie -n cac -c openab -- sh -c '
  mkdir -p /home/node/repos/104corp && cd /home/node/repos/104corp
  git clone https://github.com/104corp/104cac-appapi-m104-facade.git 2>/dev/null \
    || git -C 104cac-appapi-m104-facade pull
  cd 104cac-appapi-m104-facade
  cd docker/local && docker build -t appapi-image-8.2 . ; cd ../..
  make run
  GITHUB_ACCESS_TOKEN=$(gh auth token) make composer
  docker exec appapi-m104-dev-8.2 make unit
'
```
`make unit` 應該能正常跑完 phpunit（不是連線失敗或 command not found）。測完記得清掉：

```bash
kubectl exec deployment/openab-claude-genie -n cac -c openab -- docker rm -f appapi-m104-dev-8.2
```

## Step 6：部署新版 persona

`Genie-CLAUDE_v2.md` 已經加了「沒有 mise 宣告檔、但有 Dockerfile+Makefile 時改走 Docker 流程、用完要 `docker rm -f` 清乾淨」這條規則，commit 也推了：

```bash
kubectl exec -i deployment/openab-claude-genie -n cac -- sh -c '
  git -C /home/node/github-repo/openab pull
  cat /home/node/github-repo/openab/deployment-guides/Genie-CLAUDE_v2.md > /home/node/CLAUDE.md'
```
不用重啟，跟改 CLAUDE.md 的既有慣例一樣，開新 thread 才會套用。

## 已知限制

- Docker image cache 用 `emptyDir`，pod 重啟後（例如 `helm upgrade`、node 重開機）要重新拉一次私有 base image，是分鐘等級的等待，不是壞掉。
- 目前只驗證單一 Dockerfile/image 這種模式（無 `docker-compose` 多服務）。之後若真的遇到 `docker-compose.yml` 的 repo，這套 dind sidecar 一樣能跑 `docker compose`（同一個 daemon），但還沒實測過，遇到再視情況調整 resource limit。
- dind sidecar 的 resource limit（`requests: 250m/256Mi`、`limits: 2/3Gi`）是保守預設值，這台是單節點共用叢集，建議之後用 `kubectl top pod -n cac` 看實際用量再調整。
- `GITHUB_ACCESS_TOKEN=$(gh auth token)` 這個寫法依賴 genie 當下的 gh 登入 session（104cac 帳號）；如果之後 gh 帳號被登出或換帳號，這個指令會失敗，需要先確認 `gh auth status` 正常。
