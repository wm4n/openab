#!/usr/bin/env bash
# Mac(OrbStack) 上三隻 bot 的 transcript 累積鏡像。
#
# 為什麼需要：claude-code 會自動刪除超過 cleanupPeriodDays（預設 30 天）的
# transcript，而那是使用統計唯一的資料來源。三隻 2026-09-15 從 k3s 搬回 Mac 時
# 是全新 bootstrap，k3s 節點上那套 /usr/local/bin/openab-archive.sh 週鏡像**完全
# 沒有跟過來**。這支是 Mac 版的等價物。
#
# 用法：在 **Mac mini(CAC@2771)** 上執行 `bash openab-archive.sh`。
#   掛上 crontab（每週日凌晨 2 點；保留期限 30 天，每週跑有 4 倍餘裕）：
#     crontab -l 2>/dev/null | { cat; echo "0 2 * * 0 $HOME/openab-archive.sh >> $HOME/openab-archive.log 2>&1"; } | crontab -
#   ⚠️ macOS 的 cron 需要「完全取用磁碟」權限才讀得到部分目錄，且睡眠中不會補跑；
#      機器常闔蓋的話改用 launchd（StartCalendarInterval）比較可靠。
#
# 設計要點（跟 k3s 版一致）：
#   - **不刪任何東西**：來源被 pruning 刪掉的檔案要留在鏡像裡，那正是這支存在的理由。
#     所以 rsync **不加 --delete**，體積是「所有曾經存在過的資料」而非 N 份完整快照。
#   - **輸出佈局刻意對齊 k3s 的鏡像**：<bot>/{claude-projects,codex-sessions,openab}，
#     這樣 usage-stats 的 collect.py --archive-root 不用改就吃得到
#     （見 ../k3s/usage-stats/collect.py 的 _MIRROR_LAYOUT）。
#   - **用 docker cp + host 端 rsync**，不在容器裡跑 rsync：那批映像沒裝 rsync。
#     docker cp 走 tar，會保留 mtime——統計的日期維度完全靠 mtime，不能用會重設
#     時間的複製方式。
#   - k3s 版有 --backup-dir（檔案被 compaction 改短時保留前一版），這裡拿掉：
#     macOS 15 起 /usr/bin/rsync 換成 openrsync，對 --backup-dir 的支援不確定，
#     而 --backup-dir 只是加分項，不是這支的核心目的。

set -euo pipefail

DOCKER="docker -c orbstack"
MIRROR="${OPENAB_MIRROR:-$HOME/openab-archive/mirror}"

# 容器:鏡像 bot 名
BOTS=(
  "openab-rick:rick"
  "openab-morty:morty"
  "openab-summer:summer"
)

# 容器內來源路徑:鏡像子目錄名（對齊 collect.py 的 _MIRROR_LAYOUT）
PAIRS=(
  ".claude/projects:claude-projects"
  ".codex/sessions:codex-sessions"
  ".openab:openab"
)

command -v rsync >/dev/null || { echo "錯誤：找不到 rsync" >&2; exit 1; }

for entry in "${BOTS[@]}"; do
  IFS=: read -r CONTAINER BOT <<< "$entry"

  if ! $DOCKER inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "!! 略過 $BOT：找不到容器 $CONTAINER"
    continue
  fi
  echo "=== $BOT ($CONTAINER) ==="

  TMP=$(mktemp -d)
  # shellcheck disable=SC2064
  trap "rm -rf '$TMP'" EXIT

  for pair in "${PAIRS[@]}"; do
    SUB=${pair%%:*}; NAME=${pair##*:}

    # 該 bot 沒有這個目錄很正常（Claude 家族沒有 .codex/sessions，反之亦然）
    if ! $DOCKER exec -u node "$CONTAINER" test -d "/home/node/$SUB" 2>/dev/null; then
      continue
    fi

    rm -rf "${TMP:?}/stage"
    mkdir -p "$TMP/stage"
    $DOCKER cp "$CONTAINER:/home/node/$SUB" "$TMP/stage/"

    # docker cp 會把來源目錄名帶進去（例如 .claude/projects → stage/projects）
    SRC=$(find "$TMP/stage" -mindepth 1 -maxdepth 1 -type d | head -1)
    [ -n "$SRC" ] || continue

    mkdir -p "$MIRROR/$BOT/$NAME"
    rsync -a "$SRC/" "$MIRROR/$BOT/$NAME/"
    echo "  $SUB -> $MIRROR/$BOT/$NAME"
  done

  rm -rf "$TMP"
  trap - EXIT
done

echo
du -sh "$MIRROR" 2>/dev/null || true
echo "完成。這份原始鏡像比正規化事件更值得長期留——日後 parser 有 bug，有原始檔才能重跑。"
