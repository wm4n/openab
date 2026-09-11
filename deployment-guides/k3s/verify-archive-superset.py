#!/usr/bin/env python3
"""確認新的累積鏡像是舊日期快照的內容超集，再決定能不能刪舊的。

用內容雜湊比對、完全忽略路徑 —— 兩者的目錄結構不同（舊的把 opencode.db 和
thread_map.json 放在 bot 根目錄，新的放在 opencode/ 與 openab/ 子目錄），
按路徑比會得到一堆假差異。

用法：
    sudo python3 verify-archive-superset.py \
        /data/william/openab-archive/20260911 \
        /data/william/openab-archive/mirror
"""
import hashlib
import os
import sys


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def index(root):
    """{sha256: [相對路徑, ...]}"""
    out = {}
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            p = os.path.join(dirpath, name)
            try:
                out.setdefault(digest(p), []).append(os.path.relpath(p, root))
            except OSError as exc:
                print("  讀不到 %s: %s" % (p, exc), file=sys.stderr)
    return out


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    old_root, new_root = sys.argv[1], sys.argv[2]
    for root, label in ((old_root, "舊快照"), (new_root, "新鏡像")):
        if not os.path.isdir(root):
            print("✗ %s 不存在：%s" % (label, root))
            print("  → 先跑 openab-archive.sh 建鏡像，不要刪任何東西。")
            return 1

    old = index(old_root)
    new = index(new_root)
    print("舊快照 %d 個不重複內容（%d 檔）" % (len(old), sum(len(v) for v in old.values())))
    print("新鏡像 %d 個不重複內容（%d 檔）" % (len(new), sum(len(v) for v in new.values())))

    missing = {h: paths for h, paths in old.items() if h not in new}
    if not missing:
        print("\n✓ 新鏡像完整包含舊快照的所有內容 —— 可以安全刪除舊快照。")
        return 0

    print("\n✗ 有 %d 個內容只存在於舊快照，**不要刪**：" % len(missing))
    mutable = []
    for _h, paths in sorted(missing.items(), key=lambda kv: kv[1][0]):
        base = os.path.basename(paths[0])
        tag = ""
        if base.startswith("opencode.db") or base == "thread_map.json":
            tag = "  （會變動的檔案，新舊版本不同屬正常）"
            mutable.append(paths[0])
        print("    %s%s" % (paths[0], tag))
    if len(mutable) == len(missing):
        print("\n  全部都是會變動的檔案（SQLite／thread_map）。那些是不同時間點的")
        print("  快照，不是遺失的歷史。若要省空間可以只留這幾個檔、刪掉其餘；")
        print("  但整份也才 200MB 左右，留著最省事。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
