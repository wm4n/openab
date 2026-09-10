#!/usr/bin/env python3
"""openab 統計資料源驗證（唯讀，不改任何東西）。

要驗的單點風險：codex / opencode 到底有沒有把 openab 注入的
<sender_context> 寫進它們自己的 transcript。Claude Code 家族幾乎確定有，
另兩家是推測。如果沒有，那幾隻 bot 只會有 token 數，拿不到頻道／
發話者／真人-vs-bot 維度，第一版的涵蓋範圍就得縮。

在 k3s 節點 openab 上跑（PV 是 local 型，直接讀檔，不需要 kubectl exec）：

    python3 verify-stats-sources.py | tee /tmp/openab-stats-verify.txt

路徑不同的話：

    OPENAB_DATA_ROOT=/your/path python3 verify-stats-sources.py

不印任何對話內容，只印欄位結構與計數。
"""
import collections
import datetime as dt
import json
import os
import re
import sys

SC_RE = re.compile(r"<sender_context>\s*(\{.*?\})\s*</sender_context>", re.S)
TOKEN_KEY_RE = re.compile(r"token|usage", re.I)
MODEL_KEY_RE = re.compile(r"^(model|model_?id|modelID)$", re.I)

# 統計要用到的 sender_context 欄位
REQUIRED = ("sender_id", "sender_name", "channel_id", "is_bot", "timestamp")

# CLI 判定：(顯示名, 相對 HOME 的 transcript 目錄候選)
CLI_LAYOUTS = [
    ("claude-code", [".claude/projects"]),
    ("codex", [".codex/sessions", ".codex"]),
    ("opencode", [".local/share/opencode", ".config/opencode", ".opencode"]),
]

MAX_FILES_PER_AGENT = int(os.environ.get("OPENAB_MAX_FILES", "40"))


class Findings:
    def __init__(self):
        self.senders = []
        self.sc_paths = collections.Counter()
        self.max_sc_per_record = 0
        self.token_fields = collections.defaultdict(collections.Counter)
        self.token_sums = collections.Counter()
        self.model_paths = collections.Counter()
        self.model_values = collections.Counter()
        self.records = 0
        self.bad = 0
        self.files = 0
        self.total_files = 0
        # SQLite（opencode）用：日期範圍自己算，不靠檔案 mtime；
        # notes 放「同一筆 token 在哪些地方重複出現」這種給 parser 作者的警告。
        self.date_min = None
        self.date_max = None
        self.notes = []
        self.cost = 0.0


def walk(node, path, f, per_record, in_token=False):
    """遞迴走 JSON，就地累積發現。path 用 '.' 串接，陣列用 [] 表示。

    `in_token` 表示已經在某個 token 子樹裡。進到子樹之後**所有**整數都要收，
    不能再要求鍵名自己長得像 token —— 否則 tokens:{cache:{read:8000}} 這種
    嵌套會被漏掉，而 cache read 的單價跟 input 差一個量級，漏掉就算不出成本。

    token 一律以完整路徑為 key，天然去重。
    """
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            if MODEL_KEY_RE.match(k) and isinstance(v, str):
                f.model_paths[p] += 1
                f.model_values[v] += 1
                continue
            token_here = in_token or bool(TOKEN_KEY_RE.search(k))
            if isinstance(v, int):
                if token_here:
                    f.token_sums[p] += v
                    f.token_fields[path or "(root)"][k] += 1
                continue
            walk(v, p, f, per_record, token_here)
    elif isinstance(node, list):
        for item in node:
            walk(item, path + "[]", f, per_record, in_token)
    elif isinstance(node, str):
        for m in SC_RE.finditer(node):
            per_record[0] += 1
            f.sc_paths[path or "(root)"] += 1
            try:
                f.senders.append(json.loads(m.group(1)))
            except Exception:
                f.bad += 1


def scan_file(path, f):
    f.files += 1
    try:
        with open(path, errors="replace") as fh:
            raw = fh.read()
    except OSError as e:
        print(f"      (讀取失敗 {path}: {e})")
        return
    stripped = raw.lstrip()
    # 先試整檔 JSON（opencode 一檔一物件），失敗再按行試（JSONL）
    if stripped[:1] in ("{", "["):
        try:
            obj = json.loads(raw)
        except Exception:
            pass
        else:
            f.records += 1
            per = [0]
            walk(obj, "", f, per)
            f.max_sc_per_record = max(f.max_sc_per_record, per[0])
            return
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            f.bad += 1
            continue
        f.records += 1
        per = [0]
        walk(obj, "", f, per)
        f.max_sc_per_record = max(f.max_sc_per_record, per[0])


# --- opencode：SQLite，不是 JSON 檔 ---------------------------------------
#
# opencode 把 session 存在 ~/.local/share/opencode/opencode.db（WAL 模式）。
# 20 張表，統計相關的只有四張，而**同一筆 token 在四處重複出現**：
#
#   session  ← 權威加總。tokens_input/output/reasoning/cache_read/cache_write
#              + cost:REAL（opencode 自己算好成本，這幾隻不需要價目表）
#              parent_id 表示子 session（subagent），加總時要處理否則重複
#   message  ← per-message。data:TEXT 的 JSON 有 tokens.{input,output,total,
#              reasoning,cache.{read,write}} 與 modelID
#   part     ← message 的組成部分，但 data 裡**也帶 tokens**，數字與 message
#              層相同（實測 walle: part 與 message 的 tokens.total 皆 1201009）
#   event    ← event sourcing log，data 裡又有一份 info.tokens / part.tokens
#
# 所以 parser 只能挑一層：per-turn 用 message，per-session 用 session。
# 絕不從 part 或 event 加總 token。
#
# sender_context 落在 part.data（持久）與 event.data（event log，可能被裁剪），
# 所以走 part → part.message_id → message.session_id → session。

OPENCODE_DB_CANDIDATES = (
    ".local/share/opencode/opencode.db",
    ".local/state/opencode/opencode.db",
)


def find_opencode_db(home):
    for c in OPENCODE_DB_CANDIDATES:
        p = os.path.join(home, c)
        if os.path.isfile(p):
            return p
    return None


def scan_opencode_db(db_path, f):
    """讀 opencode 的 SQLite。

    DB 正被跑著的 pod 寫入，所以先把 db/-wal/-shm 複製到暫存目錄再讀複本，
    完全不碰原檔 —— WAL 模式下連唯讀開啟都可能需要建 -shm 檔。複本可能有
    一點不一致，對「欄位在不在」的驗證無妨。
    """
    import shutil
    import sqlite3
    import tempfile

    f.files = f.total_files = 1
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "snapshot.db")
        shutil.copy2(db_path, snap)
        for ext in ("-wal", "-shm"):
            src = db_path + ext
            if os.path.isfile(src):
                shutil.copy2(src, snap + ext)

        con = sqlite3.connect(snap)
        con.text_factory = lambda b: b.decode("utf-8", "replace")
        cur = con.cursor()
        have = {r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

        def table_cols(t):
            return {r[1] for r in cur.execute('PRAGMA table_info("%s")' % t)}

        # --- sender_context：part.data 是持久來源 ---
        for tbl in ("part", "event"):
            if tbl not in have:
                continue
            try:
                rows = cur.execute(
                    'SELECT data FROM "%s" WHERE CAST(data AS TEXT) LIKE ?' % tbl,
                    ("%sender_context%",),
                ).fetchall()
            except sqlite3.Error:
                continue
            for (blob,) in rows:
                if not isinstance(blob, str):
                    continue
                per = [0]
                try:
                    walk(json.loads(blob), tbl + ".data", f, per)
                except Exception:
                    walk(blob, tbl + ".data", f, per)
                f.max_sc_per_record = max(f.max_sc_per_record, per[0])
            if rows:
                f.notes.append("%s.data 有 %d 列含 sender_context" % (tbl, len(rows)))

        # --- token / cost / model：session 表是權威加總 ---
        if "session" in have:
            cols = table_cols("session")
            tok = [c for c in (
                "tokens_input", "tokens_output", "tokens_reasoning",
                "tokens_cache_read", "tokens_cache_write") if c in cols]
            sel = tok + [c for c in ("cost", "model", "time_created", "parent_id") if c in cols]
            if sel:
                for row in cur.execute('SELECT %s FROM session' % ", ".join(
                        '"%s"' % c for c in sel)):
                    rec = dict(zip(sel, row))
                    for c in tok:
                        v = rec.get(c)
                        if isinstance(v, int):
                            f.token_sums["session." + c] += v
                    if isinstance(rec.get("cost"), (int, float)):
                        f.cost += rec["cost"]
                    if rec.get("model"):
                        f.model_paths["session.model"] += 1
                        f.model_values[rec["model"]] += 1
                    t = rec.get("time_created")
                    if isinstance(t, int) and t > 0:
                        secs = t / 1000.0          # epoch millis
                        f.date_min = secs if f.date_min is None else min(f.date_min, secs)
                        f.date_max = secs if f.date_max is None else max(f.date_max, secs)
                nkids = cur.execute(
                    "SELECT COUNT(*) FROM session WHERE parent_id IS NOT NULL AND parent_id != ''"
                ).fetchone()[0] if "parent_id" in cols else 0
                nses = cur.execute("SELECT COUNT(*) FROM session").fetchone()[0]
                f.notes.append(
                    "session 表 %d 列（其中 %d 列有 parent_id = subagent 子 session，"
                    "加總要處理否則重複），cost 欄位已由 opencode 算好" % (nses, nkids))

        # --- message：per-turn 粒度，順便交叉核對 token ---
        if "message" in have:
            f.records = cur.execute("SELECT COUNT(*) FROM message").fetchone()[0]
            msg_tok = collections.Counter()
            msg_models = collections.Counter()
            for (blob,) in cur.execute("SELECT data FROM message"):
                if not isinstance(blob, str):
                    continue
                try:
                    obj = json.loads(blob)
                except Exception:
                    f.bad += 1
                    continue
                # 只信白名單路徑的 modelID：data.model.modelID 是同值重複
                mid = obj.get("modelID")
                if isinstance(mid, str):
                    msg_models[mid] += 1
                t = obj.get("tokens")
                if isinstance(t, dict):
                    for k, v in t.items():
                        if isinstance(v, int):
                            msg_tok["message.data.tokens." + k] += v
                        elif isinstance(v, dict):
                            for kk, vv in v.items():
                                if isinstance(vv, int):
                                    msg_tok["message.data.tokens.%s.%s" % (k, kk)] += vv
            f.token_sums.update(msg_tok)
            for m, n in msg_models.items():
                f.model_paths["message.data.modelID"] += n
                f.model_values[m] += n

        for tbl in ("part", "event", "session_message"):
            if tbl in have:
                n = cur.execute('SELECT COUNT(*) FROM "%s"' % tbl).fetchone()[0]
                f.notes.append("%s 表 %d 列（token 不可從此加總，與 message 層重複）" % (tbl, n))
        con.close()


def collect_files(root):
    out = []
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            if n.endswith((".jsonl", ".json")):
                p = os.path.join(dirpath, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out.append((st.st_size, st.st_mtime, p))
    return out


def pad(s, width):
    """靠左補齊到「顯示寬度」width。中文是全角，佔兩格，
    用 str 的 %-Ns 會歪掉（它數字元數不是顯示寬度）。"""
    import unicodedata
    s = str(s)
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)
    return s + " " * max(0, width - w)


def fmt_ts(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "-"


def human(n):
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0


def detect_cli(home):
    for name, cands in CLI_LAYOUTS:
        for c in cands:
            d = os.path.join(home, c)
            if os.path.isdir(d):
                return name, d
    return None, None


def scan_agent(home):
    """回傳 (cli, findings, files_meta)。cli 為 None 表示認不出。"""
    # opencode 先判：它的資料在 SQLite，而 .config/opencode 目錄同時存在
    # （裡面只有幾百 bytes 的設定檔），先比對目錄會誤判成「沒有資料」。
    db = find_opencode_db(home)
    if db:
        f = Findings()
        try:
            scan_opencode_db(db, f)
        except Exception as e:
            f.notes.append("SQLite 讀取失敗: %s" % e)
        st = os.stat(db)
        return "opencode(db)", f, [(st.st_size, st.st_mtime, db)]

    cli, tdir = detect_cli(home)
    if not cli:
        return None, None, []
    files = collect_files(tdir)
    f = Findings()
    f.total_files = len(files)
    # 挑最大的幾個檔：內容最多，最可能涵蓋所有欄位型態
    for _sz, _mt, p in sorted(files, reverse=True)[:MAX_FILES_PER_AGENT]:
        scan_file(p, f)
    return cli, f, files


def report_agent(name, cli, f, files):
    print(f"  --- {name} ({cli}) ---")
    if not files:
        print("      transcript 目錄存在但沒有任何 .json/.jsonl 檔")
        return
    mts = [m for _s, m, _p in files]
    total = sum(s for s, _m, _p in files)
    print(f"      檔數 {f.total_files}（掃了 {f.files}）  總大小 {human(total)}")
    # SQLite 有自己的時間欄位（session.time_created）；檔案 mtime 對 DB 沒意義
    lo = f.date_min if f.date_min is not None else min(mts)
    hi = f.date_max if f.date_max is not None else max(mts)
    src = "session.time_created" if f.date_min is not None else "檔案 mtime"
    print(f"      可回溯範圍 : {fmt_ts(lo)}  ~  {fmt_ts(hi)}   （依據 {src}）")
    print(f"      紀錄數 {f.records}  不可解析 {f.bad}")
    for n in f.notes:
        print(f"      · {n}")

    print("      [1] sender_context")
    if f.senders:
        keys = sorted({k for s in f.senders for k in s})
        missing = [k for k in REQUIRED if k not in keys]
        human_n = sum(1 for s in f.senders if s.get("is_bot") is False)
        bot_n = sum(1 for s in f.senders if s.get("is_bot") is True)
        print(f"          筆數 {len(f.senders)}   位置 {', '.join(p for p, _ in f.sc_paths.most_common(2))}")
        print(f"          欄位 : {', '.join(keys)}")
        print(f"          統計必要欄位 : {'全齊' if not missing else '缺 ' + ', '.join(missing)}")
        print(f"          is_bot 分佈 : 真人={human_n} bot={bot_n} 未知={len(f.senders)-human_n-bot_n}")
        # channel 欄位是平台名（discord.rs/slack.rs 硬寫）或 channel_type
        # （gateway.rs），**不是頻道名稱**；頻道維度只能用 channel_id。
        chans = collections.Counter(s.get("channel", "(無)") for s in f.senders)
        print(f"          channel 欄位值 : {', '.join(f'{k}×{v}' for k, v in chans.most_common(4))}"
              "   ← 這是平台名/型別，不是頻道名，頻道維度要用 channel_id")
        nthread = sum(1 for s in f.senders if s.get("thread_id"))
        print(f"          在 thread 裡 : {nthread}/{len(f.senders)}"
              "   （thread 中 channel_id=父頻道、thread_id=thread 本身）")
        tag = "有 batching，任務數要數 sender_context 不是數 turn" if f.max_sc_per_record > 1 else "此樣本無 batching 跡象"
        print(f"          單筆紀錄最多 {f.max_sc_per_record} 個  ({tag})")
        ids = [s.get("message_id") for s in f.senders if s.get("message_id")]
        print(f"          distinct message_id : {len(set(ids))}/{len(ids)}"
              "   ← 任務數要數這個（同一任務會重複出現在多個路徑）")
        schemas = collections.Counter(s.get("schema", "(無)") for s in f.senders)
        print(f"          schema : {', '.join(f'{k}×{v}' for k, v in schemas.most_common())}")
    else:
        print("          ✗ 完全找不到 —— 此 CLI 沒把 openab 注入的 sender_context 寫進 transcript")
        print("            → 這隻只會有 token 數，沒有頻道／發話者／真人-vs-bot 維度")

    print("      [2] token 欄位")
    if f.token_sums:
        # 按父路徑分組列出。**不要**只印路徑最後一段：Claude Code 的
        # message.usage 底下同時有 iterations[] 與 cache_creation 兩層明細，
        # 欄位名跟外層一模一樣，只印末段會折疊成同名、看起來像重複計數，
        # 而且會讓人看不出「哪個是權威值、哪個是明細」——那正是 parser
        # 最容易 double count 的地方。
        # （原本這裡另外列了一份 token_fields 的路徑清單，跟下面的分組
        #   輸出重複且只顯示前 4 條，已移除。）
        groups = collections.defaultdict(list)
        for k, v in f.token_sums.items():
            parent, _, leaf = k.rpartition(".")
            groups[parent or "(root)"].append((leaf, v))
        print("          加總（按路徑分組，同名不同路徑是不同東西）:")
        for parent in sorted(groups, key=lambda p: (p.count("."), p)):
            items = ", ".join(f"{leaf}={v}" for leaf, v in sorted(groups[parent]))
            print(f"            {parent}: {items}")
        cache = [k for k in f.token_sums if re.search(r"cache|cached", k, re.I)]
        print(f"          有區分 cache 嗎 : {'有' if cache else '沒有 —— 無法精算成本，只能算用量'}")
        if f.cost:
            print(f"          💰 CLI 自己算好的成本合計 : {f.cost:.4f}"
                  "   ← 有這個就不用自備價目表")
        agg = [k for k in f.token_sums if re.search(r"total", k.rsplit(".", 1)[-1], re.I)]
        if agg:
            print(f"          ⚠ 疑似加總欄位（parser 要排除避免重複計算）: {', '.join(agg)}")
    else:
        print("          ✗ 找不到任何 token 數字")

    print("      [3] model 識別")
    if f.model_values:
        print(f"          路徑 : {', '.join(p for p, _ in f.model_paths.most_common(2))}")
        print("          值   : " + ", ".join(f"{k}×{v}" for k, v in f.model_values.most_common(8)))
    else:
        print("          ✗ 找不到 model 欄位 —— token 無法對應到模型")


def report_thread_map(root, homes):
    print("\n=== thread_map.json（thread_key → ACP sessionId）===")
    for name, home in homes:
        p = os.path.join(home, ".openab", "thread_map.json")
        if not os.path.isfile(p):
            print(f"  {name:<16} 不存在")
            continue
        try:
            with open(p, errors="replace") as fh:
                obj = json.load(fh)
        except Exception as e:
            print(f"  {name:<16} 解析失敗: {e}")
            continue
        inner = obj if isinstance(obj, dict) else {}
        for k in ("threads", "mapping", "persisted"):
            if isinstance(inner.get(k), dict):
                inner = inner[k]
                break
        ks = list(inner.keys())
        platforms = collections.Counter(k.split(":", 1)[0] for k in ks if isinstance(k, str))
        pf = ", ".join(f"{k}×{v}" for k, v in platforms.most_common()) or "(無)"
        print(f"  {name:<16} {len(ks):>4} 筆   platform 分佈: {pf}")
        if ks:
            print(f"  {'':<16}      樣本 key: {ks[0]}")


def main():
    root = os.environ.get("OPENAB_DATA_ROOT", "/data/william/openab")
    print("=== 0. 環境 ===")
    print(f"  host : {os.uname().nodename}")
    print(f"  time : {dt.datetime.now().isoformat(timespec='seconds')}")
    print(f"  root : {root}")
    if not os.path.isdir(root):
        print(f"  !! {root} 不存在。用 OPENAB_DATA_ROOT=/your/path 重跑。")
        return 1

    homes = []
    for entry in sorted(os.listdir(root)):
        p = os.path.join(root, entry)
        if os.path.isdir(p) and entry.startswith("agent-"):
            homes.append((entry[len("agent-"):], p))
    if not homes:
        print(f"  !! {root} 底下沒有 agent-* 目錄")
        return 1
    print(f"  找到 {len(homes)} 個 agent 目錄: {', '.join(n for n, _ in homes)}")

    print("\n=== 1. 逐 agent 掃描 ===")
    summary = []
    for name, home in homes:
        try:
            cli, f, files = scan_agent(home)
        except PermissionError as e:
            print(f"  --- {name} --- 權限不足: {e}")
            summary.append((name, "權限不足", "?", "?", "?", "?", "-"))
            continue
        if not cli:
            print(f"  --- {name} --- 認不出 CLI（沒有 .claude/.codex/opencode 目錄）")
            summary.append((name, "認不出", "-", "-", "-", "-", "-"))
            continue
        report_agent(name, cli, f, files)
        mts = [m for _s, m, _p in files]
        lo = f.date_min if f.date_min is not None else (min(mts) if mts else None)
        summary.append((
            name, cli,
            "有" if f.senders else "✗ 無",
            "有" if f.token_sums else "✗ 無",
            "有" if any(re.search(r"cache", k, re.I) for k in f.token_sums) else "無",
            "有" if f.cost else "無",
            fmt_ts(lo).split()[0] if lo else "-",
        ))

    report_thread_map(root, homes)

    print("\n=== 2. 判定摘要 ===")
    cols = (12, 15, 11, 7, 6, 6)
    head = ("AGENT", "CLI", "sender_ctx", "token", "cache", "cost")
    print("  " + "".join(pad(h, w) for h, w in zip(head, cols)) + "可回溯起日")
    for row in summary:
        print("  " + "".join(pad(c, w) for c, w in zip(row[:6], cols)) + str(row[6]))

    full = [r[0] for r in summary if r[2] == "有" and r[3] == "有"]
    token_only = [r[0] for r in summary if r[2] != "有" and r[3] == "有"]
    print("\n  全維度可統計（任務數／對話數／token／摩擦指標）:")
    print(f"    {', '.join(full) if full else '（無）'}")
    if token_only:
        print("  只能算 token（缺頻道／發話者維度）:")
        print(f"    {', '.join(token_only)}")
        print("    → 這幾隻要嘛接受降級統計，要嘛改用別的資料源補維度")
    return 0


if __name__ == "__main__":
    sys.exit(main())
