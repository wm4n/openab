#!/usr/bin/env python3
"""探查 opencode 的 SQLite schema —— 找出統計要用的欄位在哪張表、哪個欄位。

opencode 把 session 存在 ~/.local/share/opencode/opencode.db（SQLite + WAL），
不是 JSON 檔，所以 verify-stats-sources.py 掃不到。這支先把 schema 挖出來，
之後才能正確實作 parser。

**安全性**：DB 正在被跑著的 pod 寫入。這支腳本會先把 db/-wal/-shm 複製到
暫存目錄再讀複本，絕不碰原檔（連唯讀開啟都不做，因為 WAL 模式下唯讀開啟
可能要建 -shm 檔）。複本可能有一點不一致，對 schema 探查無妨。

用法：
    sudo python3 probe-opencode-db.py /data/william/openab/agent-kimi
    sudo python3 probe-opencode-db.py /path/to/opencode.db
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile

SC_RE = re.compile(r"<sender_context>\s*(\{.*?\})\s*</sender_context>", re.S)
INTERESTING_COL = re.compile(r"token|cost|model|usage|time|created|role|session", re.I)


def find_db(target):
    if os.path.isfile(target):
        return target
    for cand in (
        os.path.join(target, ".local/share/opencode/opencode.db"),
        os.path.join(target, ".local/state/opencode/opencode.db"),
        os.path.join(target, "opencode.db"),
    ):
        if os.path.isfile(cand):
            return cand
    return None


def snapshot(db_path, tmpdir):
    """複製 db 三兄弟到暫存目錄，回傳複本路徑。不動原檔。"""
    dst = os.path.join(tmpdir, "snapshot.db")
    shutil.copy2(db_path, dst)
    for suffix, ext in ((".db-wal", "-wal"), (".db-shm", "-shm")):
        src = db_path[: -len(".db")] + suffix if db_path.endswith(".db") else db_path + suffix
        if os.path.isfile(src):
            shutil.copy2(src, dst + ext)
    return dst


def walk_json(node, path, tokens, models, senders):
    """跟 verify-stats-sources.py 同一套邏輯：找 sender_context / token / model。"""
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            if re.match(r"^(model|model_?id|modelID)$", k, re.I) and isinstance(v, str):
                models[p] = models.get(p, set())
                models[p].add(v)
                continue
            # cost 是浮點數，要一起收 —— 如果 opencode 自己就算好了成本，
            # 那這幾隻 bot 根本不需要我們自備價目表。
            if isinstance(v, (int, float)) and not isinstance(v, bool) \
                    and re.search(r"token|cost", path + "." + k, re.I):
                tokens[p] = tokens.get(p, 0) + v
                continue
            walk_json(v, p, tokens, models, senders)
    elif isinstance(node, list):
        for item in node:
            walk_json(item, path + "[]", tokens, models, senders)
    elif isinstance(node, str):
        for m in SC_RE.finditer(node):
            try:
                senders.append(json.loads(m.group(1)))
            except Exception:
                pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    db = find_db(sys.argv[1])
    if not db:
        print(f"找不到 opencode.db（試過 {sys.argv[1]} 底下的 .local/share|state/opencode/）")
        return 1
    print(f"=== DB: {db} ({os.path.getsize(db)} bytes) ===")

    with tempfile.TemporaryDirectory() as tmp:
        snap = snapshot(db, tmp)
        con = sqlite3.connect(snap)
        con.text_factory = lambda b: b.decode("utf-8", "replace")
        cur = con.cursor()

        cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cur.fetchall()
        print(f"\n--- {len(tables)} 張表 ---")

        sc_hits = []
        for name, ddl in tables:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{name}"')
                n = cur.fetchone()[0]
            except sqlite3.Error as e:
                print(f"  {name}: 讀取失敗 {e}")
                continue
            cur.execute(f'PRAGMA table_info("{name}")')
            cols = [(r[1], r[2]) for r in cur.fetchall()]
            hot = [c for c, _t in cols if INTERESTING_COL.search(c)]
            print(f"\n  [{name}]  {n} 列")
            desc = ", ".join("%s:%s" % (c, t or "?") for c, t in cols)
            print("    欄位: " + desc)
            if hot:
                print(f"    ⭐ 名字相關的欄位: {', '.join(hot)}")

            # 在每個可能是文字的欄位裡找 sender_context
            for col, _t in cols:
                try:
                    cur.execute(
                        f'SELECT COUNT(*) FROM "{name}" WHERE CAST("{col}" AS TEXT) LIKE ?',
                        ("%sender_context%",),
                    )
                    hits = cur.fetchone()[0]
                except sqlite3.Error:
                    continue
                if hits:
                    print(f"    ✅ sender_context 命中: {name}.{col} = {hits} 列")
                    sc_hits.append((name, col, hits))

        # 對命中的表抽樣，解析出實際欄位
        print("\n--- 抽樣解析 ---")
        if not sc_hits:
            print("  ✗ 全表掃過都沒有 sender_context")
            print("    → opencode 沒把 openab 注入的內容存進 DB，或存成壓縮/二進位格式")
        for name, col, _n in sc_hits[:3]:
            print(f"\n  [{name}.{col}]")
            cur.execute(
                f'SELECT * FROM "{name}" WHERE CAST("{col}" AS TEXT) LIKE ? LIMIT 3',
                ("%sender_context%",),
            )
            colnames = [d[0] for d in cur.description]
            senders, tokens, models = [], {}, {}
            for row in cur.fetchall():
                for cn, val in zip(colnames, row):
                    if not isinstance(val, str):
                        continue
                    s = val.strip()
                    if s[:1] in ("{", "["):
                        try:
                            walk_json(json.loads(s), cn, tokens, models, senders)
                            continue
                        except Exception:
                            pass
                    walk_json(val, cn, tokens, models, senders)
            if senders:
                keys = sorted({k for s in senders for k in s})
                print(f"    sender_context 欄位: {', '.join(keys)}")
                miss = [k for k in ("sender_id", "channel_id", "is_bot", "timestamp", "message_id") if k not in keys]
                print(f"    統計必要欄位: {'全齊' if not miss else '缺 ' + ', '.join(miss)}")
                print(f"    樣本: {json.dumps(senders[0], ensure_ascii=False)[:200]}")
            else:
                print("    (抽樣的列裡解不出 sender_context JSON)")

        # 全 DB 找 token / model：掃所有表的所有文字欄位
        print("\n--- 全 DB 掃 token / model 欄位 ---")
        tokens, models, senders = {}, {}, []
        for name, _ddl in tables:
            cur.execute(f'PRAGMA table_info("{name}")')
            cols = [r[1] for r in cur.fetchall()]
            try:
                cur.execute(f'SELECT * FROM "{name}" LIMIT 200')
                rows = cur.fetchall()
            except sqlite3.Error:
                continue
            for row in rows:
                for cn, val in zip(cols, row):
                    if isinstance(val, int) and INTERESTING_COL.search(cn):
                        key = f"{name}.{cn}"
                        tokens[key] = tokens.get(key, 0) + val
                    elif isinstance(val, str) and val.strip()[:1] in ("{", "["):
                        try:
                            walk_json(json.loads(val), f"{name}.{cn}", tokens, models, senders)
                        except Exception:
                            pass
        if tokens:
            print("    token/cost 候選（前 25）:")
            for k, v in sorted(tokens.items(), key=lambda kv: -abs(kv[1]))[:25]:
                print(f"      {k} = {v}")
        else:
            print("    ✗ 找不到 token 數字")
        if models:
            print("    model 候選:")
            for k, vs in models.items():
                print(f"      {k} = {', '.join(sorted(vs))[:120]}")
        else:
            print("    ✗ 找不到 model 欄位")
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
