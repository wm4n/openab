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

## Step 3.5：裝 `make`（genie 主 image 沒有這個指令）

**2026-09-01 實測踩過**：genie 主 container 的 image 沒裝 `make`，而多數 PHP repo 的 Makefile（`build`/`run`/`composer`/`bash` 這類 target）是設計成在**主 container 自己的 shell**執行（負責下 `docker build`/`docker run`/`docker exec`），不是進 container 裡面才需要，所以這一步是必要的，跟目標 repo 用哪種架構的 image 無關。

用剛裝好的 docker，抓一份跟主 image 同一個 distro（Debian 13/trixie）的 `make`，避開 glibc 版本不相容的風險：

```bash
kubectl exec deployment/openab-claude-genie -n cac -c openab -- sh -c '
  docker run --rm -v /home/node/.local/bin:/out debian:trixie \
    sh -c "apt-get update -qq && apt-get install -y -qq make && cp /usr/bin/make /out/make"
  chmod +x ~/.local/bin/make
  which make
  make --version
'
```

> ⚠️ 這個手法可以延伸用在之後任何「genie 主 image 缺什麼指令」的情況——用 dind 抓一個同 distro 的公開 image、`apt-get install` 裝好、複製二進位檔到共用 PVC 上的 `~/.local/bin`，不用等 image 本身重新 build。
>
> ⚠️ **實測踩過**：這樣複製出來的檔案擁有者是 root（dind daemon 本身是 privileged/root 在跑該容器），主 container 是 UID 1000 非 root，`chmod`/`chown` 這個檔案會報 `Operation not permitted`。不影響使用——只要來源檔案本來就有執行權限位元，UID 1000 讀取/執行都沒問題，只是不能再對它做權限異動，遇到報錯不用當成失敗。

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

## Step 5：先用自建的最小 fixture 驗證機制本身（推薦，跟目標 repo 分開）

不用一開始就挑戰真實 repo（可能會遇到私有 image 架構、composer 私有套件庫等額外變數），先用一份原生 amd64、公開、無需任何私有憑證的最小 Dockerfile+Makefile，驗證「DinD、bind mount（兩個 container 掛同一顆 PVC 同路徑）、docker exec、`make`」這條鏈路本身是通的：

```bash
kubectl exec -it deployment/openab-claude-genie -n cac -c openab -- sh -c '
mkdir -p /home/node/docker-verify && cd /home/node/docker-verify
cat > Dockerfile <<EOF
FROM php:8.2-cli
WORKDIR /var/www/html
CMD ["sleep", "infinity"]
EOF
printf "build:\n\tdocker build -t genie-docker-verify .\nrun:\n\tdocker run --name genie-docker-verify-c -d -v \$(CURDIR):/var/www/html genie-docker-verify\ntest:\n\tdocker exec genie-docker-verify-c php test.php\nclean:\n\tdocker rm -f genie-docker-verify-c\n" > Makefile
printf "<?php echo \"genie docker pipeline OK\\n\";\n" > test.php
make build && make run && make test && make clean
'
```
應該印出 `genie docker pipeline OK`。**2026-09-01 實測通過**——這一步跟目標 repo 是不是私有／什麼架構完全無關，先確認這個過再去查真實 repo 的問題會比較好排查。

## Step 6：拿真實 repo 實測（可能會遇到 repo 自己的環境問題，跟本文件的機制無關）

```bash
kubectl exec -it deployment/openab-claude-genie -n cac -c openab -- sh -c '
  mkdir -p /home/node/repos/104corp && cd /home/node/repos/104corp
  git clone https://github.com/104corp/104cac-appapi-m104-facade.git 2>/dev/null \
    || git -C 104cac-appapi-m104-facade pull
  cd 104cac-appapi-m104-facade
  cd docker/local && docker build -t appapi-image-8.2 . && cd ../.. \
  && make run \
  && GITHUB_ACCESS_TOKEN=$(gh auth token) make composer \
  && docker exec appapi-m104-dev-8.2 make unit
'
```
`make unit` 應該能正常跑完 phpunit（不是連線失敗或 command not found）。測完記得清掉：

```bash
kubectl exec deployment/openab-claude-genie -n cac -c openab -- docker rm -f appapi-m104-dev-8.2
```

> ⚠️ **2026-09-01 實測踩過**：`104cac-appapi-m104-facade` 這個範例 repo 的私有 base image（`ghcr.io/104corp/104cac-php-docker-image:mac-m104-appapi-20240316`）**只發布過 arm64 版本**，在這台 amd64 節點上 `docker build` 會在第一個非 FROM 的 RUN 就報 `exec format error`。這是這顆 image 本身的限制，不是 Step 1～5 這套 DinD 機制的問題（Step 5 的 fixture 已經證明機制本身沒問題）。要跑這個特定 repo，還沒實測過的兩條路：
> 1. 裝 QEMU 模擬層：`docker run --rm --privileged tonistiigi/binfmt --install arm64`（dind 本身 privileged、跟節點共用 kernel，註冊後對整個節點生效一次），`docker build` 時加 `--platform=linux/arm64`。
> 2. 請 104corp 團隊補發一個 amd64 版本的 base image tag（沒有模擬開銷，長期較乾淨，但不是這邊能決定的事）。

## Step 7：部署新版 persona

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
- 透過 dind 執行 `docker run`/`docker exec` 建立出來的檔案擁有者是 root，genie 主 container 是 UID 1000，能讀/執行但不能再 `chmod`/`chown`（見 Step 3.5）。
- **2026-09-01 實測踩過**：genie 這顆 PVC 檔案量很大（40 萬+），每次 pod 重建（`helm upgrade`、node 重開機等）kubelet 都要重新設定一次 `fsGroup` 權限，實測耗時約 6～9 分鐘，這是既有特性、跟這次 docker 改動無關，之後 genie pod 常態性要重啟的話會是個煩人的等待，可考慮之後另外評估 `fsGroupChangePolicy: OnRootMismatch`。
- `104cac-appapi-m104-facade` 這個範例 repo 卡在私有 base image 只有 arm64 版本，QEMU 模擬或請 104corp 補 amd64 tag 這兩條路都還沒實測驗證，是待辦（見 Step 6 註記）。
