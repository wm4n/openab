# openab bot 使用統計 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 從各 agent CLI 自己的儲存挖出七隻 openab bot 的使用統計（任務數／對話數／token 對應 model／摩擦指標），CronJob 定期收集，使用者手動跑 CLI 產出終端機／markdown／單一 HTML 報表。

**Architecture:** 四段管線。`collect.py`（CronJob 跑）用三個 parser 把 claude-code JSONL、codex JSONL、opencode SQLite 轉成兩條正規化事件流（task／usage）存進獨立 PVC；`aggregate.py` 是純函數把事件算成每日指標；`report.py` 是使用者手動跑的 CLI，吃已累積的事件產報表。收集與報表分開的理由是原始資料會被 CLI 清掉（claude-code 疑似 30 天保留期限），錯過即永久遺失。

**Tech Stack:** Python 3.8+ **僅用標準庫**（`json`／`sqlite3`／`re`／`datetime`／`unittest`）。無 pip 依賴——CronJob 容器與 k3s 節點都不保證有 pip。測試用 stdlib `unittest`。

**Spec:** `docs/superpowers/specs/2026-09-10-bot-usage-stats-design.md`

## Global Constraints

- **僅標準庫。** 不得 `pip install` 任何東西。JSON 圖表庫、pytest、pandas 全部禁止。
- **Python 3.8+ 語法。** 不用 `match`、不用 f-string 內嵌同款引號（`f'{x or '?'}'` 在 3.12 前是語法錯誤）、不用 `tomllib`（3.11+ 才有，所以設定檔用 **JSON 不是 TOML**——這是對 spec 檔案清單的刻意偏離，理由是零依賴）。
- **原始資料唯讀。** 永不寫入 `/data/william/openab/agent-*/`。opencode 的 SQLite 必須先把 `db`／`-wal`／`-shm` 複製到暫存目錄再讀複本。
- **時區一律 `Asia/Taipei`**，日界線以此切分。不得用系統預設時區。
- **「不支援」與 `0` 必須可區分。** 缺資料時省略欄位或填 `None`，**永不填 `0`**。
- **解析失敗不得靜默跳過。** 一律計數並出現在報表的健康度區塊。
- **註解與使用者可見輸出用繁體中文**（repo 慣例）。
- **每個數字可追溯**：事件必須帶 `source_file` 與 `source_ref`／`source_offset`。
- 測試指令（已實測可用）：
  ```bash
  cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
  ```

---

### Task 1: 專案骨架與 `events.py`

**Files:**
- Create: `deployment-guides/k3s/usage-stats/events.py`
- Create: `deployment-guides/k3s/usage-stats/tests/__init__.py`
- Test: `deployment-guides/k3s/usage-stats/tests/test_events.py`

**Interfaces:**
- Consumes: 無（第一個 task）
- Produces:
  - `TASK_SCHEMA = "openab.stats.task.v1"`、`USAGE_SCHEMA = "openab.stats.usage.v1"`
  - `TAIPEI` — `datetime.timezone`，UTC+8
  - `day_key(iso_ts: str) -> str` — ISO 8601 字串轉 `"YYYY-MM-DD"`（Asia/Taipei）
  - `write_events(path: str, events: list) -> int` — 附加寫 JSONL，回傳寫入筆數
  - `read_events(paths: list) -> iterator` — 逐筆 yield dict
  - `class ParseResult` — `.tasks: list`、`.usages: list`、`.watermark: dict`、`.health: dict`
  - `class ParseContext` — `.platform_for(thread_id: str) -> str`，`ParseContext.from_agent_home(home: str)`

- [ ] **Step 1: 寫失敗的測試**

建立 `deployment-guides/k3s/usage-stats/tests/__init__.py`（空檔案），然後寫
`tests/test_events.py`：

```python
"""events.py 的測試：日界線、JSONL 讀寫、ParseContext 的平台查詢。"""
import json
import os
import tempfile
import unittest

from events import (
    TAIPEI, TASK_SCHEMA, USAGE_SCHEMA,
    ParseContext, ParseResult, day_key, read_events, write_events,
)


class TestDayKey(unittest.TestCase):
    def test_utc_afternoon_stays_same_day_in_taipei(self):
        self.assertEqual(day_key("2026-09-10T06:32:10Z"), "2026-09-10")

    def test_utc_late_evening_rolls_to_next_taipei_day(self):
        # 2026-09-10T17:00Z = 2026-09-11 01:00 台北
        self.assertEqual(day_key("2026-09-10T17:00:00Z"), "2026-09-11")

    def test_offset_timestamp_is_converted_not_truncated(self):
        # rfc3339 帶 offset（cron.rs 用 Utc::now().to_rfc3339()）
        self.assertEqual(day_key("2026-09-10T23:30:00+00:00"), "2026-09-11")

    def test_naive_timestamp_is_treated_as_utc(self):
        self.assertEqual(day_key("2026-09-10T17:00:00"), "2026-09-11")


class TestEventIO(unittest.TestCase):
    def test_roundtrip_appends_and_reads_back(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "task-2026-09-10.jsonl")
            n1 = write_events(p, [{"schema": TASK_SCHEMA, "bot": "rick"}])
            n2 = write_events(p, [{"schema": TASK_SCHEMA, "bot": "morty"}])
            self.assertEqual((n1, n2), (1, 1))
            rows = list(read_events([p]))
            self.assertEqual([r["bot"] for r in rows], ["rick", "morty"])

    def test_read_skips_blank_lines_and_counts_nothing_extra(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "u.jsonl")
            with open(p, "w") as fh:
                fh.write(json.dumps({"schema": USAGE_SCHEMA}) + "\n\n")
            self.assertEqual(len(list(read_events([p]))), 1)

    def test_missing_file_yields_nothing_rather_than_raising(self):
        self.assertEqual(list(read_events(["/nonexistent/x.jsonl"])), [])


class TestParseResult(unittest.TestCase):
    def test_starts_empty_with_zeroed_health(self):
        r = ParseResult()
        self.assertEqual((r.tasks, r.usages), ([], []))
        self.assertEqual(r.health["records"], 0)
        self.assertEqual(r.health["unparsable"], 0)
        self.assertEqual(r.health["notes"], [])


class TestParseContext(unittest.TestCase):
    def _home_with_thread_map(self, tmp, mapping):
        os.makedirs(os.path.join(tmp, ".openab"))
        with open(os.path.join(tmp, ".openab", "thread_map.json"), "w") as fh:
            json.dump(mapping, fh)
        return tmp

    def test_reads_platform_prefix_from_persisted_keys(self):
        with tempfile.TemporaryDirectory() as d:
            home = self._home_with_thread_map(d, {"persisted": {
                "discord:154749": "ses_1", "slack:C0123": "ses_2"}})
            ctx = ParseContext.from_agent_home(home)
            self.assertEqual(ctx.platform_for("154749"), "discord")
            self.assertEqual(ctx.platform_for("C0123"), "slack")

    def test_unknown_thread_is_unknown_never_guessed(self):
        with tempfile.TemporaryDirectory() as d:
            home = self._home_with_thread_map(d, {"persisted": {}})
            ctx = ParseContext.from_agent_home(home)
            self.assertEqual(ctx.platform_for("999"), "unknown")

    def test_missing_thread_map_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = ParseContext.from_agent_home(d)
            self.assertEqual(ctx.platform_for("1"), "unknown")

    def test_flat_mapping_without_persisted_wrapper_also_works(self):
        with tempfile.TemporaryDirectory() as d:
            home = self._home_with_thread_map(d, {"discord:777": "ses_9"})
            ctx = ParseContext.from_agent_home(home)
            self.assertEqual(ctx.platform_for("777"), "discord")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'events'`

- [ ] **Step 3: 寫最小實作**

建立 `deployment-guides/k3s/usage-stats/events.py`：

```python
"""正規化事件的共同型別與 I/O。

三個 parser 與 aggregator 都依賴這一層，它刻意不認識任何 CLI 的格式 ——
格式差異全部關在各自的 parse_*.py 裡。
"""
import datetime as dt
import json
import os

TASK_SCHEMA = "openab.stats.task.v1"
USAGE_SCHEMA = "openab.stats.usage.v1"

# 日界線一律用台北時間切。task 流的時間來自平台（Discord 給 UTC）、
# usage 流來自 CLI 本地時鐘，不明訂時區的話兩份數字的日界線會不一致。
TAIPEI = dt.timezone(dt.timedelta(hours=8))


def _parse_iso(ts):
    """容忍 Z 結尾、帶 offset、以及無時區（視為 UTC）三種形式。"""
    s = ts.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(s)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def day_key(iso_ts):
    """ISO 8601 字串 → 台北時間的 'YYYY-MM-DD'。"""
    return _parse_iso(iso_ts).astimezone(TAIPEI).strftime("%Y-%m-%d")


def write_events(path, events):
    """附加寫 JSONL，回傳寫入筆數。目錄不存在時自動建立。"""
    events = list(events)
    if not events:
        return 0
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    return len(events)


def read_events(paths):
    """逐筆 yield 事件。不存在的檔案直接略過（缺口由覆蓋率指標呈現）。"""
    for p in paths:
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


class ParseResult:
    """一個 parser 對一隻 bot 跑一輪的產出。"""

    def __init__(self):
        self.tasks = []
        self.usages = []
        self.watermark = {}
        self.health = {"records": 0, "unparsable": 0, "notes": []}


class ParseContext:
    """parser 需要但不在 transcript 裡的資訊。

    目前只有平台維度 —— sender_context.channel 在 gateway 平台（含 Google
    Chat）給的是 channel_type 而非平台名，所以唯一可靠來源是 thread_map.json
    的 'platform:thread_id' key 前綴。
    """

    def __init__(self, thread_platforms=None):
        self._thread_platforms = thread_platforms or {}

    @classmethod
    def from_agent_home(cls, home):
        path = os.path.join(home, ".openab", "thread_map.json")
        mapping = {}
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return cls(mapping)
        inner = raw if isinstance(raw, dict) else {}
        for wrapper in ("persisted", "threads", "mapping"):
            if isinstance(inner.get(wrapper), dict):
                inner = inner[wrapper]
                break
        for key in inner:
            if isinstance(key, str) and ":" in key:
                platform, _, thread_id = key.partition(":")
                mapping[thread_id] = platform
        return cls(mapping)

    def platform_for(self, thread_id):
        """查不到一律回 'unknown' —— 不猜。"""
        return self._thread_platforms.get(thread_id, "unknown")
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，12 個測試全過（`Ran 12 tests`）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/usage-stats/events.py \
        deployment-guides/k3s/usage-stats/tests/__init__.py \
        deployment-guides/k3s/usage-stats/tests/test_events.py
git commit -m "feat(usage-stats): events.py —— 正規化事件型別、JSONL I/O、台北日界線"
```

---

### Task 2: `sender_context.py` —— 抽取、三分類、去重鍵

**Files:**
- Create: `deployment-guides/k3s/usage-stats/sender_context.py`
- Test: `deployment-guides/k3s/usage-stats/tests/test_sender_context.py`

**Interfaces:**
- Consumes: 無（不依賴 `events.py`）
- Produces:
  - `extract(obj, path="") -> list` — 回傳 `[(json_path, sc_dict), ...]`，遞迴走任意
    JSON 找出所有 `<sender_context>` 區塊
  - `classify_source(sc: dict) -> str` — `"human"` | `"bot_relay"` | `"cron"`
  - `dedup_key(platform: str, sc: dict) -> str`
  - `CRON_SENDER_ID = "openab-cron"`

**設計依據（來自 spec 的實測事實）：**`sender_context` 是 JSON 字串裡的內容，引號被
轉義，不能用 `grep`／字串比對抓，必須先 `json.loads` 整筆再從文字欄位裡取。同一次
任務會出現在多個路徑（claude-code 的 `message.content[].text` 與
`attachment.prompt[].text`、codex 的 `payload.content[].text` 與 `payload.message`），
所以去重是必須的。cron 觸發的 `message_id` 為 `None`，不能用它當鍵。

- [ ] **Step 1: 寫失敗的測試**

`tests/test_sender_context.py`：

```python
"""sender_context 抽取與分類的測試。

真實資料的關鍵特性：sender_context 是 JSON 字串裡的內容（引號被轉義），
而且同一筆任務會出現在多個路徑。
"""
import json
import unittest

from sender_context import CRON_SENDER_ID, classify_source, dedup_key, extract


def wrap(sc):
    return "<sender_context>\n%s\n</sender_context>" % json.dumps(sc, ensure_ascii=False)


HUMAN = {
    "schema": "openab.sender.v1", "sender_id": "824092654060830770",
    "sender_name": "wm4n", "display_name": "william", "channel": "discord",
    "channel_id": "1528965074562191420", "thread_id": "1540292484611969084",
    "is_bot": False, "timestamp": "2026-09-10T06:32:10Z",
    "message_id": "1600000000000000001", "receiver_id": "1519868630064562278",
}
BOT_RELAY = dict(HUMAN, sender_id="1521431781641818202", sender_name="morty",
                 is_bot=True, message_id="1600000000000000002")
CRON = {
    "schema": "openab.sender.v1", "sender_id": CRON_SENDER_ID,
    "sender_name": "nightly", "display_name": "nightly", "channel": "discord",
    "channel_id": "1528965074562191420", "thread_id": "1540292484611969084",
    "is_bot": True, "timestamp": "2026-09-10T02:00:00Z",
}


class TestExtract(unittest.TestCase):
    def test_finds_sender_context_inside_escaped_json_string(self):
        # 這是真實形狀：sender_context 在 message.content[].text 的字串裡
        record = {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": wrap(HUMAN)},
            {"type": "text", "text": "幫我看 PROJ-1234"}]}}
        found = extract(record)
        self.assertEqual(len(found), 1)
        path, sc = found[0]
        self.assertEqual(path, "message.content[].text")
        self.assertEqual(sc["sender_id"], "824092654060830770")

    def test_finds_all_occurrences_across_different_paths(self):
        # genie 的真實形狀：同一筆同時在 message.content[] 與 attachment.prompt[]
        record = {"message": {"content": [{"type": "text", "text": wrap(HUMAN)}]},
                  "attachment": {"prompt": [{"type": "text", "text": wrap(HUMAN)}]}}
        paths = [p for p, _ in extract(record)]
        self.assertEqual(sorted(paths),
                         ["attachment.prompt[].text", "message.content[].text"])

    def test_counts_multiple_senders_in_one_record_for_batching(self):
        # openab 的 batching：一筆紀錄可能帶多個 sender_context
        record = {"message": {"content": [
            {"type": "text", "text": wrap(HUMAN)},
            {"type": "text", "text": wrap(BOT_RELAY)}]}}
        self.assertEqual(len(extract(record)), 2)

    def test_codex_payload_message_string_path(self):
        record = {"payload": {"message": wrap(HUMAN)}}
        self.assertEqual([p for p, _ in extract(record)], ["payload.message"])

    def test_record_without_sender_context_yields_nothing(self):
        self.assertEqual(extract({"type": "assistant", "message": {"model": "x"}}), [])

    def test_malformed_sender_context_json_is_skipped_not_raised(self):
        record = {"text": "<sender_context>\n{not json}\n</sender_context>"}
        self.assertEqual(extract(record), [])


class TestClassifySource(unittest.TestCase):
    def test_human(self):
        self.assertEqual(classify_source(HUMAN), "human")

    def test_bot_relay_has_message_id(self):
        self.assertEqual(classify_source(BOT_RELAY), "bot_relay")

    def test_cron_identified_by_sender_id_sentinel(self):
        self.assertEqual(classify_source(CRON), "cron")

    def test_bot_without_message_id_is_cron_even_if_sender_id_differs(self):
        # cron.rs:714 是 message_id: None；用兩個條件互為保險
        odd = dict(BOT_RELAY, sender_id="something-else")
        odd.pop("message_id")
        self.assertEqual(classify_source(odd), "cron")


class TestDedupKey(unittest.TestCase):
    def test_uses_platform_and_message_id_when_present(self):
        self.assertEqual(dedup_key("discord", HUMAN),
                         "discord:1600000000000000001")

    def test_same_task_from_two_paths_produces_identical_key(self):
        self.assertEqual(dedup_key("discord", HUMAN), dedup_key("discord", dict(HUMAN)))

    def test_cron_falls_back_to_thread_and_timestamp(self):
        self.assertEqual(
            dedup_key("discord", CRON),
            "discord:openab-cron:1540292484611969084:2026-09-10T02:00:00Z")

    def test_two_cron_runs_in_same_thread_are_distinct(self):
        later = dict(CRON, timestamp="2026-09-10T03:00:00Z")
        self.assertNotEqual(dedup_key("discord", CRON), dedup_key("discord", later))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_sender_context -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'sender_context'`

- [ ] **Step 3: 寫最小實作**

`deployment-guides/k3s/usage-stats/sender_context.py`：

```python
"""從任意 CLI 紀錄裡抽出 openab 注入的 sender_context，並分類任務來源。

三個 parser 共用這一支 —— sender_context 的格式由 openab 定義
（schema openab.sender.v1，見 crates/openab-core/src/adapter.rs），
跟哪一家 CLI 無關。
"""
import json
import re

# sender_context 是 JSON 字串裡的內容，引號被轉義成 \"，所以不能直接對原始
# 行做字串比對 —— 必須先 json.loads 整筆紀錄，再從文字欄位裡用這個 regex 取。
_SC_RE = re.compile(r"<sender_context>\s*(\{.*?\})\s*</sender_context>", re.S)

# cron.rs:714 的固定值：usercron 觸發的 SenderContext 是
# sender_id: "openab-cron"、is_bot: true、message_id: None。
CRON_SENDER_ID = "openab-cron"


def extract(obj, path=""):
    """遞迴走任意 JSON，回傳 [(json_path, sender_context_dict), ...]。

    path 用 '.' 串接，陣列以 '[]' 表示（例如 message.content[].text），
    這樣不同來源路徑可以被區分 —— 同一筆任務會同時出現在多個路徑。
    解析不了的 sender_context 直接略過（由呼叫端計入 unparsable）。
    """
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = "%s.%s" % (path, key) if path else key
            found.extend(extract(value, child))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(extract(item, path + "[]"))
    elif isinstance(obj, str):
        for match in _SC_RE.finditer(obj):
            try:
                found.append((path, json.loads(match.group(1))))
            except ValueError:
                continue
    return found


def classify_source(sc):
    """"human" | "bot_relay" | "cron"。

    is_bot 只分得出「非真人」；要再分出 bot 互呼與排程觸發，得看
    sender_id 是不是 cron 的哨兵值，或 message_id 是不是空的。
    """
    if not sc.get("is_bot"):
        return "human"
    if sc.get("sender_id") == CRON_SENDER_ID or not sc.get("message_id"):
        return "cron"
    return "bot_relay"


def dedup_key(platform, sc):
    """同一任務在多路徑重複出現時的去重鍵。

    有 message_id（平台訊息 ID）就用它 —— 那是天然唯一鍵。cron 觸發沒有
    message_id，退回 (哨兵, thread, 時間戳)。
    """
    message_id = sc.get("message_id")
    if message_id:
        return "%s:%s" % (platform, message_id)
    return "%s:%s:%s:%s" % (platform, CRON_SENDER_ID,
                            sc.get("thread_id") or sc.get("channel_id") or "?",
                            sc.get("timestamp") or "?")
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 26 個測試（`Ran 26 tests`）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/usage-stats/sender_context.py \
        deployment-guides/k3s/usage-stats/tests/test_sender_context.py
git commit -m "feat(usage-stats): sender_context 抽取、任務來源三分類、去重鍵"
```

---

### Task 3: `parse_claude_code.py`

**Files:**
- Create: `deployment-guides/k3s/usage-stats/parse_claude_code.py`
- Test: `deployment-guides/k3s/usage-stats/tests/test_parse_claude_code.py`

**Interfaces:**
- Consumes: `events.ParseResult`、`events.ParseContext`、`sender_context.extract`／
  `classify_source`／`dedup_key`
- Produces:
  - `TRANSCRIPT_GLOB_ROOT = ".claude/projects"`
  - `parse(home: str, bot: str, ctx: ParseContext, watermark: dict) -> ParseResult`
  - `usage_from_record(record: dict) -> list` — 回傳
    `[{"origin": "main"|"subagent", "tokens": {...}, "model": str|None}, ...]`
  - 每筆 usage 事件都帶 `usage_key`（幂等去重鍵，格式
    `"<檔案>#<offset>#<origin>"`）

**設計依據（spec「claude-code」小節，全部實測）：**
- 權威用量是 `message.usage` 的頂層四欄
- **不可加**的明細：`message.usage.cache_creation`（TTL 拆解，數值等於外層
  `cache_creation_input_tokens`）、`message.usage.iterations[]`（欄位名與外層相同）
- **不可加**的非計費項：`message.usage.server_tool_use`（請求次數）、
  `message.diagnostics.cache_miss_reason.cache_missed_input_tokens`、
  `compactMetadata.*`、`toolUseResult.totalTokens`
- **要加**的巢狀獨立用量：`toolUseResult.usage` 的頂層四欄（subagent 的真實 API
  呼叫；實測 `isSidechain` 全為 `false`，代表 subagent 訊息不在 transcript 裡）
- model 只信 `message.model`，排除 `message.content[].input.model` 與 `<synthetic>`

- [ ] **Step 1: 寫失敗的測試**

`tests/test_parse_claude_code.py`：

```python
"""claude-code parser 的測試。

重點全部是「哪些數字不能加」—— 真實 message.usage 底下有兩層明細，
欄位名跟外層一模一樣，天真加總會虛報數倍。
"""
import json
import os
import tempfile
import unittest

from events import ParseContext
from parse_claude_code import parse, usage_from_record


def assistant_record(**usage_overrides):
    """重現實測 genie 的 message.usage 結構：外層 + 兩層明細 + 非計費欄位。"""
    usage = {
        "input_tokens": 100,
        "output_tokens": 200,
        "cache_creation_input_tokens": 300,
        "cache_read_input_tokens": 400,
        # 明細一：TTL 拆解，數值等於外層 cache_creation_input_tokens
        "cache_creation": {"ephemeral_1h_input_tokens": 300,
                           "ephemeral_5m_input_tokens": 0},
        # 明細二：每次 iteration，欄位名與外層相同
        "iterations": [{"input_tokens": 99, "output_tokens": 199,
                        "cache_creation_input_tokens": 299,
                        "cache_read_input_tokens": 399}],
        # 非 token：請求次數
        "server_tool_use": {"web_fetch_requests": 0, "web_search_requests": 0},
    }
    usage.update(usage_overrides)
    return {
        "type": "assistant", "sessionId": "s1", "isSidechain": False,
        "timestamp": "2026-09-10T06:33:01Z",
        "message": {"model": "claude-opus-5", "role": "assistant", "usage": usage},
    }


class TestUsageFromRecord(unittest.TestCase):
    def test_takes_only_top_level_four_fields(self):
        rows = usage_from_record(assistant_record())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tokens"], {
            "input": 100, "output": 200, "cache_write": 300, "cache_read": 400})

    def test_ignores_cache_creation_ttl_breakdown(self):
        # 300 只能出現一次；若明細被加進去會變 600
        rows = usage_from_record(assistant_record())
        self.assertEqual(rows[0]["tokens"]["cache_write"], 300)

    def test_ignores_iterations_breakdown(self):
        rows = usage_from_record(assistant_record())
        self.assertEqual(rows[0]["tokens"]["input"], 100)  # 不是 100+99

    def test_ignores_server_tool_use_request_counts(self):
        rows = usage_from_record(assistant_record())
        self.assertNotIn("web_fetch_requests", rows[0]["tokens"])

    def test_ignores_diagnostics_and_compaction_non_billing_fields(self):
        rec = assistant_record()
        rec["message"]["diagnostics"] = {
            "cache_miss_reason": {"cache_missed_input_tokens": 3633171}}
        rec["compactMetadata"] = {"preTokens": 1000899, "postTokens": 7794,
                                  "cumulativeDroppedTokens": 993105}
        rows = usage_from_record(rec)
        self.assertEqual(sum(rows[0]["tokens"].values()), 1000)

    def test_includes_tool_use_result_usage_as_subagent_origin(self):
        rec = {
            "type": "user", "sessionId": "s1",
            "timestamp": "2026-09-10T06:40:00Z",
            "toolUseResult": {
                "totalTokens": 3676107,   # 加總欄位，不可用
                "usage": {"input_tokens": 52, "output_tokens": 154585,
                          "cache_creation_input_tokens": 74929,
                          "cache_read_input_tokens": 3446541,
                          "iterations": [{"input_tokens": 52}]},
            },
        }
        rows = usage_from_record(rec)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["origin"], "subagent")
        self.assertEqual(rows[0]["tokens"]["output"], 154585)
        self.assertEqual(rows[0]["tokens"]["input"], 52)  # 不是 52+52

    def test_does_not_use_tool_use_result_total_tokens(self):
        rec = {"toolUseResult": {"totalTokens": 999999}}
        self.assertEqual(usage_from_record(rec), [])

    def test_synthetic_model_is_dropped(self):
        rec = assistant_record()
        rec["message"]["model"] = "<synthetic>"
        self.assertEqual(usage_from_record(rec), [])

    def test_task_tool_input_model_is_not_treated_as_model(self):
        # message.content[].input.model 是傳給 subagent 的參數，值如 "opus"
        rec = {"type": "assistant", "sessionId": "s1",
               "timestamp": "2026-09-10T06:33:01Z",
               "message": {"content": [{"type": "tool_use",
                                        "input": {"model": "opus"}}]}}
        self.assertEqual(usage_from_record(rec), [])

    def test_record_without_usage_yields_nothing(self):
        self.assertEqual(usage_from_record({"type": "system"}), [])


class TestParse(unittest.TestCase):
    def _home(self, tmp, records, thread_map=None):
        d = os.path.join(tmp, ".claude", "projects", "-home-node")
        os.makedirs(d)
        with open(os.path.join(d, "s1.jsonl"), "w") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.makedirs(os.path.join(tmp, ".openab"))
        with open(os.path.join(tmp, ".openab", "thread_map.json"), "w") as fh:
            json.dump({"persisted": thread_map or {"discord:t1": "s1"}}, fh)
        return tmp

    def test_emits_task_and_usage_events(self):
        sc = ('<sender_context>\n{"schema":"openab.sender.v1","sender_id":"824",'
              '"sender_name":"wm4n","display_name":"william","channel":"discord",'
              '"channel_id":"c1","thread_id":"t1","is_bot":false,'
              '"timestamp":"2026-09-10T06:32:10Z","message_id":"m1"}\n'
              '</sender_context>')
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, [
                {"type": "user", "sessionId": "s1",
                 "message": {"role": "user",
                             "content": [{"type": "text", "text": sc}]}},
                assistant_record(),
            ])
            res = parse(home, "rick", ParseContext.from_agent_home(home), {})
            self.assertEqual(len(res.tasks), 1)
            self.assertEqual(res.tasks[0]["platform"], "discord")
            self.assertEqual(res.tasks[0]["source"], "human")
            self.assertEqual(res.tasks[0]["dedup_key"], "discord:m1")
            self.assertEqual(res.tasks[0]["sender_name"], "wm4n")
            self.assertEqual(res.tasks[0]["display_name"], "william")
            self.assertEqual(len(res.usages), 1)
            self.assertEqual(res.usages[0]["model_id"], "claude-opus-5")
            self.assertIsNone(res.usages[0]["model_variant"])
            self.assertEqual(res.usages[0]["cost_source"], "subscription")
            # 幂等性：同一筆用量的 usage_key 必須穩定
            self.assertTrue(res.usages[0]["usage_key"].endswith("#main"))
            self.assertEqual(res.health["unparsable"], 0)

    def test_unparsable_line_is_counted_not_skipped_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, [])
            path = os.path.join(home, ".claude", "projects", "-home-node", "s1.jsonl")
            with open(path, "w") as fh:
                fh.write("{broken\n")
            res = parse(home, "rick", ParseContext.from_agent_home(home), {})
            self.assertEqual(res.health["unparsable"], 1)

    def test_watermark_lets_second_run_skip_already_read_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, [assistant_record()])
            ctx = ParseContext.from_agent_home(home)
            first = parse(home, "rick", ctx, {})
            self.assertEqual(len(first.usages), 1)
            second = parse(home, "rick", ctx, first.watermark)
            self.assertEqual(len(second.usages), 0)

    def test_rewritten_file_is_reread_from_scratch(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, [assistant_record()])
            ctx = ParseContext.from_agent_home(home)
            first = parse(home, "rick", ctx, {})
            # compaction 重寫檔案：內容變短、前綴不同
            path = os.path.join(home, ".claude", "projects", "-home-node", "s1.jsonl")
            with open(path, "w") as fh:
                fh.write(json.dumps(assistant_record(input_tokens=7)) + "\n")
            second = parse(home, "rick", ctx, first.watermark)
            self.assertEqual(len(second.usages), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_parse_claude_code -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'parse_claude_code'`

- [ ] **Step 3: 寫最小實作**

`deployment-guides/k3s/usage-stats/parse_claude_code.py`：

```python
"""claude-code（Rick／Morty／Genie）的 transcript parser。

資料在 ~/.claude/projects/**/*.jsonl，一行一筆 JSON。

這支的全部難度都在「哪些數字不能加」。實測 message.usage 底下有兩層明細
（cache_creation 是 TTL 拆解、iterations[] 是每次 iteration），欄位名跟外層
一模一樣；另外還混了診斷與 compaction 統計。天真地用鍵名比對撈 token 會
虛報數倍。所以這裡一律用**明確的白名單**取頂層四欄。
"""
import hashlib
import json
import os

import sender_context as sc_mod
from events import TASK_SCHEMA, USAGE_SCHEMA, ParseResult

TRANSCRIPT_GLOB_ROOT = ".claude/projects"

# message.usage 的權威欄位 → 正規化名稱。**只取這四個**。
_USAGE_FIELDS = (
    ("input_tokens", "input"),
    ("output_tokens", "output"),
    ("cache_creation_input_tokens", "cache_write"),
    ("cache_read_input_tokens", "cache_read"),
)

# CLI 內部合成訊息，沒有實際 API 呼叫。
_SYNTHETIC_MODEL = "<synthetic>"

# 前綴指紋的取樣長度：compaction 會重寫檔案，用它判斷能不能沿用 offset。
_PREFIX_BYTES = 4096


def _tokens_from_usage(usage):
    """只取白名單的頂層四欄；子物件（cache_creation／iterations）一律不看。"""
    out = {}
    for raw, name in _USAGE_FIELDS:
        value = usage.get(raw)
        if isinstance(value, int) and not isinstance(value, bool):
            out[name] = value
    return out


def usage_from_record(record):
    """一筆紀錄可能帶兩處獨立用量：主 agent 與 subagent。"""
    rows = []
    message = record.get("message") or {}

    usage = message.get("usage")
    if isinstance(usage, dict):
        model = message.get("model")
        tokens = _tokens_from_usage(usage)
        # model 只信 message.model；<synthetic> 沒有實際 API 呼叫。
        if tokens and model and model != _SYNTHETIC_MODEL:
            rows.append({"origin": "main", "tokens": tokens, "model": model})

    # toolUseResult.usage 是 Task tool 呼叫 subagent 的真實 API 用量。實測
    # isSidechain 全為 false，代表 subagent 自己的訊息不在 transcript 裡，
    # 所以這是唯一來源、必須加。它底下的 iterations[] 仍是明細不可加。
    tool_result = record.get("toolUseResult")
    if isinstance(tool_result, dict) and isinstance(tool_result.get("usage"), dict):
        tokens = _tokens_from_usage(tool_result["usage"])
        if tokens:
            rows.append({"origin": "subagent", "tokens": tokens,
                         "model": message.get("model") or None})
    return rows


def _iter_transcripts(home):
    root = os.path.join(home, TRANSCRIPT_GLOB_ROOT)
    for dirpath, _dirs, names in os.walk(root):
        for name in sorted(names):
            if name.endswith(".jsonl"):
                yield os.path.join(dirpath, name)


def _prefix_fingerprint(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read(_PREFIX_BYTES)).hexdigest()


def parse(home, bot, ctx, watermark):
    """掃這隻 bot 的全部 transcript，回傳 ParseResult。

    watermark 形如 {檔案路徑: {"offset": int, "prefix": str}}。前綴指紋不同
    表示檔案被重寫（compaction），整檔重讀。
    """
    result = ParseResult()
    for path in _iter_transcripts(home):
        mark = watermark.get(path) or {}
        try:
            prefix = _prefix_fingerprint(path)
        except OSError as exc:
            result.health["notes"].append("讀不到 %s: %s" % (path, exc))
            continue
        start = mark.get("offset", 0) if mark.get("prefix") == prefix else 0

        with open(path, encoding="utf-8", errors="replace") as fh:
            fh.seek(start)
            while True:
                offset = fh.tell()
                line = fh.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                result.health["records"] += 1
                try:
                    record = json.loads(stripped)
                except ValueError:
                    result.health["unparsable"] += 1
                    continue
                _emit(result, record, path, offset, bot, ctx)
            result.watermark[path] = {"offset": fh.tell(), "prefix": prefix}
    return result


def _emit(result, record, path, offset, bot, ctx):
    session_id = record.get("sessionId")
    for json_path, sc in sc_mod.extract(record):
        platform = ctx.platform_for(sc.get("thread_id") or sc.get("channel_id") or "")
        result.tasks.append({
            "schema": TASK_SCHEMA, "bot": bot, "cli": "claude-code",
            "platform": platform,
            "dedup_key": sc_mod.dedup_key(platform, sc),
            "channel_id": sc.get("channel_id"),
            "thread_id": sc.get("thread_id"),
            "session_id": session_id,
            "sender_id": sc.get("sender_id"),
            "sender_name": sc.get("sender_name"),
            "display_name": sc.get("display_name"),
            "source": sc_mod.classify_source(sc),
            "occurred_at": sc.get("timestamp"),
            "source_file": path, "source_offset": offset,
            "source_ref": json_path,
        })
    for row in usage_from_record(record):
        result.usages.append({
            "schema": USAGE_SCHEMA, "bot": bot, "cli": "claude-code",
            "session_id": session_id,
            "model_id": row["model"], "model_variant": None,
            "occurred_at": record.get("timestamp"),
            "tokens": row["tokens"],
            # Claude 家族走訂閱制：token 數不等於帳單金額，不可套價目表算錢。
            "cost": None, "cost_source": "subscription",
            "origin": row["origin"],
            # usage_key 讓收集具備幂等性：CronJob 重跑或整檔重讀時，
            # aggregator 用 (bot, usage_key) 去重，不會重複計算。
            "usage_key": "%s#%d#%s" % (path, offset, row["origin"]),
            "source_file": path, "source_offset": offset,
        })
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 40 個測試（`Ran 40 tests`）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/usage-stats/parse_claude_code.py \
        deployment-guides/k3s/usage-stats/tests/test_parse_claude_code.py
git commit -m "feat(usage-stats): claude-code parser —— 白名單取 usage、納入 subagent 用量"
```

---

### Task 4: `parse_codex.py`

**Files:**
- Create: `deployment-guides/k3s/usage-stats/parse_codex.py`
- Test: `deployment-guides/k3s/usage-stats/tests/test_parse_codex.py`

**Interfaces:**
- Consumes: `events.ParseResult`／`ParseContext`、`sender_context` 全部三個函式
- Produces:
  - `parse(home: str, bot: str, ctx: ParseContext, watermark: dict) -> ParseResult`
  - `tokens_from_last_usage(info: dict) -> dict` — `last_token_usage` → 正規化 tokens
  - `class CumulativeMismatch(Exception)` — 交叉驗證失敗時拋出

**`tokens` 欄位的不變式（三個 parser 共同遵守，這裡第一次寫明）：**

`tokens` 裡的 `input`／`output`／`cache_read`／`cache_write` **必須互斥可加**，四者相加
等於該次呼叫的計費單位總量。**不互斥的欄位一律放 `tokens_info`**，aggregator 算總量時
不碰它。理由是各家語意不同，實測算術證據如下：

- **codex**：`total_tokens = input_tokens + output_tokens`（實測 21485360 + 76614 =
  21561974，完全相等）。所以 `cached_input_tokens`（19841664）是 `input_tokens` 的
  **子集**，`reasoning_output_tokens` 是 `output_tokens` 的子集。因此正規化時
  `input = input_tokens − cached_input_tokens`、`cache_read = cached_input_tokens`，
  而 `reasoning` 進 `tokens_info`。**直接把 cached 加上 input 會重複計算。**
- **claude-code**：`cache_read_input_tokens` 與 `input_tokens` 是**分離**的，直接對應
  （Task 3 已如此實作，四欄互斥）。
- **opencode**：`reasoning` 是**加法項**不是子集（Task 5 會驗證），進 `tokens`。

- [ ] **Step 1: 寫失敗的測試**

`tests/test_parse_codex.py`：

```python
"""codex parser 的測試。

最大陷阱：payload.info.total_token_usage 是 session 累積值，每個 token_count
event 都重報一次。實測加總所有 event 的 total_token_usage 會比正確值大 19.4 倍。
"""
import json
import os
import tempfile
import unittest

from events import ParseContext
from parse_codex import CumulativeMismatch, parse, tokens_from_last_usage

SC = ('<sender_context>\n{"schema":"openab.sender.v1","sender_id":"824",'
      '"sender_name":"wm4n","display_name":"william","channel":"discord",'
      '"channel_id":"c1","thread_id":"t1","is_bot":false,'
      '"timestamp":"2026-09-10T06:32:10Z","message_id":"m1"}\n</sender_context>')


def token_count_event(last, total, model="gpt-5.5", ts="2026-09-10T06:33:00Z"):
    return {"timestamp": ts, "type": "event_msg",
            "payload": {"type": "token_count", "model": model,
                        "info": {"last_token_usage": last,
                                 "total_token_usage": total}}}


def usage(inp, out, cached=0, reasoning=0):
    return {"input_tokens": inp, "output_tokens": out,
            "cached_input_tokens": cached,
            "reasoning_output_tokens": reasoning,
            "total_tokens": inp + out}


class TestTokensFromLastUsage(unittest.TestCase):
    def test_cached_is_subtracted_from_input_because_it_is_a_subset(self):
        # 實測 codex：total = input + output，所以 cached ⊂ input
        got = tokens_from_last_usage(usage(100, 20, cached=90))
        self.assertEqual(got["tokens"], {"input": 10, "output": 20,
                                         "cache_read": 90, "cache_write": 0})

    def test_disjoint_fields_sum_to_billable_total(self):
        got = tokens_from_last_usage(usage(100, 20, cached=90))
        self.assertEqual(sum(got["tokens"].values()), 120)  # = total_tokens

    def test_reasoning_goes_to_tokens_info_not_tokens(self):
        got = tokens_from_last_usage(usage(100, 20, cached=90, reasoning=5))
        self.assertNotIn("reasoning", got["tokens"])
        self.assertEqual(got["tokens_info"], {"reasoning": 5})

    def test_total_tokens_field_is_never_copied_into_tokens(self):
        got = tokens_from_last_usage(usage(100, 20))
        self.assertNotIn("total_tokens", got["tokens"])
        self.assertNotIn("total", got["tokens"])

    def test_cached_exceeding_input_clamps_to_zero_rather_than_going_negative(self):
        got = tokens_from_last_usage(usage(50, 10, cached=80))
        self.assertEqual(got["tokens"]["input"], 0)
        self.assertEqual(got["tokens"]["cache_read"], 80)


class TestParse(unittest.TestCase):
    def _home(self, tmp, records):
        d = os.path.join(tmp, ".codex", "sessions", "2026", "09", "10")
        os.makedirs(d)
        with open(os.path.join(d, "rollout-s1.jsonl"), "w") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.makedirs(os.path.join(tmp, ".openab"))
        with open(os.path.join(tmp, ".openab", "thread_map.json"), "w") as fh:
            json.dump({"persisted": {"discord:t1": "s1"}}, fh)
        return tmp

    def test_sums_last_usage_not_cumulative_total(self):
        # 三次呼叫，各 100 input；total_token_usage 是累積 100/200/300
        records = [
            token_count_event(usage(100, 10), usage(100, 10)),
            token_count_event(usage(100, 10), usage(200, 20)),
            token_count_event(usage(100, 10), usage(300, 30)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual(len(res.usages), 3)
            total_input = sum(u["tokens"]["input"] for u in res.usages)
            self.assertEqual(total_input, 300)   # 不是 600（累積值加總）

    def test_cross_check_passes_when_last_sums_to_final_cumulative(self):
        records = [
            token_count_event(usage(100, 10), usage(100, 10)),
            token_count_event(usage(100, 10), usage(200, 20)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual(res.health["unparsable"], 0)
            self.assertTrue(any("交叉驗證通過" in n for n in res.health["notes"]))

    def test_cross_check_raises_when_semantics_do_not_hold(self):
        # 刻意讓 last 加總不等於最後一筆 total —— 代表對 event 語意理解有誤
        records = [
            token_count_event(usage(100, 10), usage(100, 10)),
            token_count_event(usage(100, 10), usage(999, 99)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            with self.assertRaises(CumulativeMismatch):
                parse(home, "summer", ParseContext.from_agent_home(home), {})

    def test_emits_task_from_payload_content_text(self):
        records = [{"timestamp": "2026-09-10T06:32:11Z", "type": "response_item",
                    "payload": {"type": "message", "role": "user",
                                "content": [{"type": "input_text", "text": SC}]}}]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual(len(res.tasks), 1)
            self.assertEqual(res.tasks[0]["dedup_key"], "discord:m1")
            self.assertEqual(res.tasks[0]["cli"], "codex")

    def test_same_task_in_both_paths_produces_two_events_with_one_dedup_key(self):
        # 實測 summer：74 筆 sender_context 只有 37 個 distinct message_id
        records = [
            {"timestamp": "2026-09-10T06:32:11Z", "type": "response_item",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": SC}]}},
            {"timestamp": "2026-09-10T06:32:11Z", "type": "event_msg",
             "payload": {"type": "user_message", "message": SC}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual(len(res.tasks), 2)
            self.assertEqual({t["dedup_key"] for t in res.tasks}, {"discord:m1"})
            self.assertEqual({t["source_ref"] for t in res.tasks},
                             {"payload.content[].text", "payload.message"})

    def test_model_comes_from_payload_model_not_collaboration_settings(self):
        records = [{"timestamp": "2026-09-10T06:33:00Z", "type": "event_msg",
                    "payload": {"type": "token_count", "model": "gpt-5.5",
                                "collaboration_mode": {
                                    "settings": {"model": "should-be-ignored"}},
                                "info": {"last_token_usage": usage(10, 1),
                                         "total_token_usage": usage(10, 1)}}}]
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, records)
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual([u["model_id"] for u in res.usages], ["gpt-5.5"])
            self.assertEqual(len({u["usage_key"] for u in res.usages}), 1)

    def test_unparsable_line_is_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp, [])
            path = os.path.join(home, ".codex", "sessions", "2026", "09", "10",
                                "rollout-s1.jsonl")
            with open(path, "w") as fh:
                fh.write("{nope\n")
            res = parse(home, "summer", ParseContext.from_agent_home(home), {})
            self.assertEqual(res.health["unparsable"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_parse_codex -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'parse_codex'`

- [ ] **Step 3: 寫最小實作**

`deployment-guides/k3s/usage-stats/parse_codex.py`：

```python
"""codex-acp（Summer）的 rollout parser。

資料在 ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl。

最大陷阱：payload.info.total_token_usage 是 session **累積值**，每個
token_count event 都重報一次到目前為止的總量。加總所有 event 的
total_token_usage 就是把累積值再累積 —— 實測 summer 這樣算會比正確值大
19.4 倍（418458730 對 21561974）。整個 total_token_usage 子樹都是累積值，
不只 total_tokens 那一欄。

所以權威用量是逐筆 last_token_usage，而 total_token_usage 只用來做交叉
驗證：Σ last_token_usage 應等於每個 session 最後一筆 total_token_usage。
"""
import hashlib
import json
import os

import sender_context as sc_mod
from events import TASK_SCHEMA, USAGE_SCHEMA, ParseResult

_PREFIX_BYTES = 4096


class CumulativeMismatch(Exception):
    """Σ last_token_usage 不等於最後一筆 total_token_usage。

    代表對 codex 的 event 語意理解有誤。寧可中止也不要產出可疑數字 ——
    這種錯誤不會有任何外觀跡象，混進報表就再也抓不出來。
    """


def _int(d, key):
    value = d.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def tokens_from_last_usage(info):
    """last_token_usage → {"tokens": 互斥四欄, "tokens_info": 非互斥項}。

    實測 codex 的 total_tokens = input_tokens + output_tokens，所以
    cached_input_tokens 是 input_tokens 的子集、reasoning_output_tokens 是
    output_tokens 的子集。正規化後的四欄必須互斥可加，因此 input 要扣掉
    cached，而 reasoning 移到 tokens_info（aggregator 算總量時不碰）。
    """
    cached = _int(info, "cached_input_tokens")
    raw_input = _int(info, "input_tokens")
    return {
        "tokens": {
            # 扣到負數只可能是資料異常；夾在 0 以免污染總量。
            "input": max(0, raw_input - cached),
            "output": _int(info, "output_tokens"),
            "cache_read": cached,
            "cache_write": 0,
        },
        "tokens_info": {"reasoning": _int(info, "reasoning_output_tokens")},
    }


def _iter_rollouts(home):
    root = os.path.join(home, ".codex", "sessions")
    for dirpath, _dirs, names in os.walk(root):
        for name in sorted(names):
            if name.endswith(".jsonl"):
                yield os.path.join(dirpath, name)


def _prefix_fingerprint(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read(_PREFIX_BYTES)).hexdigest()


def parse(home, bot, ctx, watermark):
    result = ParseResult()
    for path in _iter_rollouts(home):
        session_id = os.path.splitext(os.path.basename(path))[0]
        mark = watermark.get(path) or {}
        try:
            prefix = _prefix_fingerprint(path)
        except OSError as exc:
            result.health["notes"].append("讀不到 %s: %s" % (path, exc))
            continue
        start = mark.get("offset", 0) if mark.get("prefix") == prefix else 0
        # 交叉驗證只在整檔重讀時做得準（增量時看不到前面的 last_token_usage）。
        checking = start == 0
        last_sum = 0
        final_cumulative = None

        with open(path, encoding="utf-8", errors="replace") as fh:
            fh.seek(start)
            while True:
                offset = fh.tell()
                line = fh.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                result.health["records"] += 1
                try:
                    record = json.loads(stripped)
                except ValueError:
                    result.health["unparsable"] += 1
                    continue
                last_sum, final_cumulative = _emit(
                    result, record, path, offset, bot, ctx, session_id,
                    last_sum, final_cumulative)
            result.watermark[path] = {"offset": fh.tell(), "prefix": prefix}

        if checking and final_cumulative is not None:
            if last_sum != final_cumulative:
                raise CumulativeMismatch(
                    "%s：Σ last_token_usage=%d 不等於最後一筆 "
                    "total_token_usage=%d，codex event 語意可能已改變"
                    % (path, last_sum, final_cumulative))
            result.health["notes"].append(
                "%s 交叉驗證通過（Σ last = final total = %d）"
                % (os.path.basename(path), last_sum))
    return result


def _emit(result, record, path, offset, bot, ctx, session_id,
          last_sum, final_cumulative):
    payload = record.get("payload") or {}

    for json_path, sc in sc_mod.extract(record):
        platform = ctx.platform_for(sc.get("thread_id") or sc.get("channel_id") or "")
        result.tasks.append({
            "schema": TASK_SCHEMA, "bot": bot, "cli": "codex",
            "platform": platform,
            "dedup_key": sc_mod.dedup_key(platform, sc),
            "channel_id": sc.get("channel_id"),
            "thread_id": sc.get("thread_id"),
            "session_id": session_id,
            "sender_id": sc.get("sender_id"),
            "sender_name": sc.get("sender_name"),
            "display_name": sc.get("display_name"),
            "source": sc_mod.classify_source(sc),
            "occurred_at": sc.get("timestamp"),
            "source_file": path, "source_offset": offset,
            "source_ref": json_path,
        })

    if payload.get("type") != "token_count":
        return last_sum, final_cumulative

    info = payload.get("info") or {}
    last = info.get("last_token_usage")
    if isinstance(last, dict):
        parts = tokens_from_last_usage(last)
        result.usages.append({
            "schema": USAGE_SCHEMA, "bot": bot, "cli": "codex",
            "session_id": session_id,
            # model 只信 payload.model；collaboration_mode.settings.model 是設定值。
            "model_id": payload.get("model"), "model_variant": None,
            "occurred_at": record.get("timestamp"),
            "tokens": parts["tokens"], "tokens_info": parts["tokens_info"],
            "cost": None, "cost_source": "subscription",
            "origin": "main",
            # 見 Task 3：aggregator 用 (bot, usage_key) 去重，讓重跑幂等。
            "usage_key": "%s#%d" % (path, offset),
            "source_file": path, "source_offset": offset,
        })
        last_sum += _int(last, "input_tokens") + _int(last, "output_tokens")

    total = info.get("total_token_usage")
    if isinstance(total, dict):
        final_cumulative = _int(total, "input_tokens") + _int(total, "output_tokens")
    return last_sum, final_cumulative
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 52 個測試（`Ran 52 tests`）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/usage-stats/parse_codex.py \
        deployment-guides/k3s/usage-stats/tests/test_parse_codex.py
git commit -m "feat(usage-stats): codex parser —— 用 last_token_usage、對累積值做交叉斷言"
```

---

### Task 5: `parse_opencode.py`

**Files:**
- Create: `deployment-guides/k3s/usage-stats/parse_opencode.py`
- Test: `deployment-guides/k3s/usage-stats/tests/test_parse_opencode.py`

**Interfaces:**
- Consumes: `events.ParseResult`／`ParseContext`、`sender_context` 三個函式
- Produces:
  - `find_db(home: str) -> str | None`
  - `parse_model_field(value) -> tuple` — `(model_id, variant)`，吃字串或 JSON 物件
  - `parse(home: str, bot: str, ctx: ParseContext, watermark: dict) -> ParseResult`

**核心設計決定：成本與 token 放在不同事件上。**

opencode 的成本只存在 session 層（`session.cost`），而 model 在 session 內會變（實測
kimi 一隻用過三個 model）。兩者無法同時在同一個粒度取得。解法是發兩種 usage 事件，
**token 空間完全不重疊**，所以重複計算在結構上不可能發生：

| 事件 | `origin` | `tokens` | `cost` | 用途 |
| --- | --- | --- | --- | --- |
| per-message | `main` | 有（來自 `message.data.tokens`） | `None`，`cost_source="unavailable"` | token 與 model 維度 |
| per-session | `session_cost` | **空 dict** | 有，`cost_source="cli"` | 成本維度 |

**`reasoning` 在 opencode 是加法項，不是子集**（與 codex 相反）。實測 kimi：
`input 1530149 + output 60999 + cache.read 8425568 = 10016716`，而
`tokens.total = 10049081`，差 32365；`reasoning = 32445`。加上 reasoning 後只差 80
（139 筆 message 裡有幾筆欄位不全所致）。所以 `reasoning` 放進互斥的 `tokens`。

- [ ] **Step 1: 寫失敗的測試**

`tests/test_parse_opencode.py`：

```python
"""opencode parser 的測試。

opencode 用 SQLite（不是 JSONL），而且同一筆 token 在 session／message／
part／event 四張表重複出現。這些測試的重點是「只從該取的那一層取」。
"""
import json
import os
import sqlite3
import tempfile
import unittest

from events import ParseContext
from parse_opencode import find_db, parse, parse_model_field

SENDER = {
    "schema": "openab.sender.v1", "sender_id": "824092654060830770",
    "sender_name": "wm4n", "display_name": "william", "channel": "discord",
    "channel_id": "c1", "thread_id": "t1", "is_bot": False,
    "timestamp": "2026-09-10T06:32:10Z", "message_id": "m1",
}
SC = "<sender_context>\n%s\n</sender_context>" % json.dumps(SENDER, ensure_ascii=False)

# 實測 kimi 的 message.data.tokens 形狀
TOKENS = {"input": 1530149, "output": 60999, "reasoning": 32445,
          "total": 10049081, "cache": {"read": 8425568, "write": 0}}
T_CREATED = 1789011069045   # epoch millis ≈ 2026-09-09


def build_db(path, sessions=None, messages=None, parts=None, events=None):
    """照實測 schema 建表（只建統計相關的四張）。"""
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("""CREATE TABLE session (id TEXT, project_id TEXT, parent_id TEXT,
      slug TEXT, directory TEXT, title TEXT, version TEXT, share_url TEXT,
      time_created INTEGER, time_updated INTEGER, workspace_id TEXT, path TEXT,
      agent TEXT, model TEXT, cost REAL, tokens_input INTEGER,
      tokens_output INTEGER, tokens_reasoning INTEGER, tokens_cache_read INTEGER,
      tokens_cache_write INTEGER, metadata TEXT)""")
    cur.execute("""CREATE TABLE message (id TEXT, session_id TEXT,
      time_created INTEGER, time_updated INTEGER, data TEXT)""")
    cur.execute("""CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT,
      time_created INTEGER, time_updated INTEGER, data TEXT)""")
    cur.execute("""CREATE TABLE event (id TEXT, aggregate_id TEXT, seq INTEGER,
      type TEXT, data TEXT)""")
    for row in sessions or []:
        cur.execute("INSERT INTO session (id, parent_id, time_created, time_updated,"
                    " model, cost, tokens_input, tokens_output, tokens_reasoning,"
                    " tokens_cache_read, tokens_cache_write)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
    for row in messages or []:
        cur.execute("INSERT INTO message VALUES (?,?,?,?,?)", row)
    for row in parts or []:
        cur.execute("INSERT INTO part VALUES (?,?,?,?,?,?)", row)
    for row in events or []:
        cur.execute("INSERT INTO event VALUES (?,?,?,?,?)", row)
    con.commit()
    con.close()


def make_home(tmp, **kw):
    d = os.path.join(tmp, ".local", "share", "opencode")
    os.makedirs(d)
    # 真實環境同時存在 .config/opencode（只有設定檔）—— 不可誤判成資料來源
    os.makedirs(os.path.join(tmp, ".config", "opencode"))
    with open(os.path.join(tmp, ".config", "opencode", "opencode.jsonc"), "w") as fh:
        fh.write('{"model":"x"}')
    build_db(os.path.join(d, "opencode.db"), **kw)
    os.makedirs(os.path.join(tmp, ".openab"))
    with open(os.path.join(tmp, ".openab", "thread_map.json"), "w") as fh:
        json.dump({"persisted": {"discord:t1": "ses_1"}}, fh)
    return tmp


class TestFindDb(unittest.TestCase):
    def test_finds_db_under_local_share(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp)
            self.assertTrue(find_db(home).endswith(".local/share/opencode/opencode.db"))

    def test_config_only_home_is_not_mistaken_for_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".config", "opencode"))
            self.assertIsNone(find_db(tmp))


class TestParseModelField(unittest.TestCase):
    def test_plain_string(self):
        self.assertEqual(parse_model_field("moonshotai/kimi-k3"),
                         ("moonshotai/kimi-k3", None))

    def test_json_object_with_variant(self):
        raw = ('{"id":"deepseek/deepseek-v4-pro-0813",'
               '"providerID":"openrouter","variant":"low"}')
        self.assertEqual(parse_model_field(raw),
                         ("deepseek/deepseek-v4-pro-0813", "low"))

    def test_json_object_without_variant(self):
        raw = '{"id":"z-ai/glm-5.2","providerID":"openrouter"}'
        self.assertEqual(parse_model_field(raw), ("z-ai/glm-5.2", None))

    def test_none_and_empty(self):
        self.assertEqual(parse_model_field(None), (None, None))
        self.assertEqual(parse_model_field(""), (None, None))


class TestParse(unittest.TestCase):
    def _ctx(self, home):
        return ParseContext.from_agent_home(home)

    def test_tokens_come_from_message_layer_with_reasoning_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"id": "msg_a", "role": "assistant",
                            "modelID": "moonshotai/kimi-k3", "tokens": TOKENS}))])
            res = parse(home, "kimi", self._ctx(home), {})
            main = [u for u in res.usages if u["origin"] == "main"]
            self.assertEqual(len(main), 1)
            self.assertEqual(main[0]["tokens"], {
                "input": 1530149, "output": 60999, "reasoning": 32445,
                "cache_read": 8425568, "cache_write": 0})

    def test_message_tokens_total_is_excluded_as_aggregate_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"modelID": "m", "tokens": TOKENS}))])
            res = parse(home, "kimi", self._ctx(home), {})
            main = [u for u in res.usages if u["origin"] == "main"][0]
            self.assertNotIn("total", main["tokens"])

    def test_never_sums_tokens_from_part_or_event_tables(self):
        # part 與 event 都帶跟 message 同值的 tokens —— 必須完全不看
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(
                tmp,
                messages=[("msg_a", "ses_1", T_CREATED, T_CREATED,
                           json.dumps({"modelID": "m", "tokens": TOKENS}))],
                parts=[("prt_1", "msg_a", "ses_1", T_CREATED, T_CREATED,
                        json.dumps({"type": "step-finish", "tokens": TOKENS}))],
                events=[("ev_1", "ses_1", 1, "message.part.updated",
                         json.dumps({"info": {"tokens": TOKENS},
                                     "part": {"tokens": TOKENS}}))])
            res = parse(home, "kimi", self._ctx(home), {})
            main = [u for u in res.usages if u["origin"] == "main"]
            self.assertEqual(len(main), 1)
            self.assertEqual(main[0]["tokens"]["input"], 1530149)

    def test_session_cost_event_carries_cost_but_no_tokens(self):
        # token 空間不重疊 —— 這是結構上防止重複計算的機制
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, sessions=[(
                "ses_1", None, T_CREATED, T_CREATED,
                '{"id":"moonshotai/kimi-k3","providerID":"openrouter"}',
                3.1967, 1530149, 60999, 32445, 8425568, 0)])
            res = parse(home, "kimi", self._ctx(home), {})
            cost_events = [u for u in res.usages if u["origin"] == "session_cost"]
            self.assertEqual(len(cost_events), 1)
            self.assertEqual(cost_events[0]["tokens"], {})
            self.assertAlmostEqual(cost_events[0]["cost"], 3.1967)
            self.assertEqual(cost_events[0]["cost_source"], "cli")
            self.assertEqual(cost_events[0]["model_id"], "moonshotai/kimi-k3")

    def test_message_usage_has_no_cost_and_says_so_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"modelID": "m", "tokens": TOKENS}))])
            res = parse(home, "kimi", self._ctx(home), {})
            main = [u for u in res.usages if u["origin"] == "main"][0]
            self.assertIsNone(main["cost"])
            self.assertEqual(main["cost_source"], "unavailable")

    def test_sender_context_read_from_part_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, parts=[(
                "prt_1", "msg_u", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"id": "prt_1", "type": "text", "text": SC}))])
            res = parse(home, "kimi", self._ctx(home), {})
            self.assertEqual(len(res.tasks), 1)
            self.assertEqual(res.tasks[0]["dedup_key"], "discord:m1")
            self.assertEqual(res.tasks[0]["cli"], "opencode")
            self.assertEqual(res.tasks[0]["session_id"], "ses_1")

    def test_same_task_in_part_and_event_shares_one_dedup_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(
                tmp,
                parts=[("prt_1", "msg_u", "ses_1", T_CREATED, T_CREATED,
                        json.dumps({"text": SC}))],
                events=[("ev_1", "ses_1", 1, "x", json.dumps({"part": {"text": SC}}))])
            res = parse(home, "kimi", self._ctx(home), {})
            self.assertEqual(len(res.tasks), 2)
            self.assertEqual({t["dedup_key"] for t in res.tasks}, {"discord:m1"})

    def test_subagent_child_session_is_flagged_in_health_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, sessions=[
                ("ses_1", None, T_CREATED, T_CREATED, "m", 1.0, 1, 1, 0, 0, 0),
                ("ses_2", "ses_1", T_CREATED, T_CREATED, "m", 0.5, 1, 1, 0, 0, 0)])
            res = parse(home, "kimi", self._ctx(home), {})
            self.assertTrue(any("parent_id" in n for n in res.health["notes"]))

    def test_usage_key_is_stable_so_rerun_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"modelID": "m", "tokens": TOKENS}))])
            ctx = self._ctx(home)
            first = parse(home, "kimi", ctx, {})
            second = parse(home, "kimi", ctx, {})
            self.assertEqual([u["usage_key"] for u in first.usages],
                             [u["usage_key"] for u in second.usages])
            self.assertEqual(first.usages[0]["usage_key"], "message:msg_a")

    def test_original_db_file_is_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"modelID": "m", "tokens": TOKENS}))])
            db = find_db(home)
            before = (os.path.getmtime(db), os.path.getsize(db))
            parse(home, "kimi", self._ctx(home), {})
            self.assertEqual((os.path.getmtime(db), os.path.getsize(db)), before)

    def test_occurred_at_converts_epoch_millis_to_iso(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, messages=[(
                "msg_a", "ses_1", T_CREATED, T_CREATED,
                json.dumps({"modelID": "m", "tokens": TOKENS}))])
            res = parse(home, "kimi", self._ctx(home), {})
            main = [u for u in res.usages if u["origin"] == "main"][0]
            self.assertTrue(main["occurred_at"].startswith("2026-09-"))
            self.assertTrue(main["occurred_at"].endswith("+00:00"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_parse_opencode -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'parse_opencode'`

- [ ] **Step 3: 寫最小實作**

`deployment-guides/k3s/usage-stats/parse_opencode.py`：

```python
"""opencode（Kimi／Wall-E／Eve）的 SQLite parser。

資料在 ~/.local/share/opencode/opencode.db（WAL 模式），不是 JSONL。注意
.config/opencode 目錄同時存在但裡面只有幾百 bytes 的設定檔 —— 先比對目錄
會誤判成「沒有資料」。

20 張表裡統計相關的四張，而同一筆 token 在四處重複出現：

  session  權威加總 + cost:REAL（opencode 自己算好實際費用）
  message  per-turn，data:TEXT 的 JSON 有 tokens.* 與 modelID
  part     sender_context 在這裡，但 data 也帶 tokens，與 message 層同值
  event    event sourcing log，data.info.tokens 與 data.part.tokens 又各一份

所以 token 只從 message 取、成本只從 session 取，part／event 只用來抓
sender_context。成本與 token 刻意放在不同事件上（session_cost 事件的
tokens 是空 dict），讓重複計算在結構上不可能發生。
"""
import datetime as dt
import json
import os
import shutil
import sqlite3
import tempfile

import sender_context as sc_mod
from events import TASK_SCHEMA, USAGE_SCHEMA, ParseResult

_DB_CANDIDATES = (
    ".local/share/opencode/opencode.db",
    ".local/state/opencode/opencode.db",
)

# message.data.tokens 的權威欄位 → 正規化名稱。total 是加總欄位，排除。
# reasoning 在 opencode 是加法項（與 codex 相反，見計畫的算術證據），
# 所以進互斥的 tokens。
_FLAT_FIELDS = (("input", "input"), ("output", "output"),
                ("reasoning", "reasoning"))
_CACHE_FIELDS = (("read", "cache_read"), ("write", "cache_write"))


def find_db(home):
    for rel in _DB_CANDIDATES:
        path = os.path.join(home, rel)
        if os.path.isfile(path):
            return path
    return None


def parse_model_field(value):
    """session.model 是 JSON 物件、message.data.modelID 是字串，兩種都要吃。

    回傳 (model_id, variant)。variant（實測 walle 有 low／default）可能影響
    計價，所以 model 維度是 (id, variant) 而不只是 id。
    """
    if not value:
        return (None, None)
    text = value.strip() if isinstance(value, str) else value
    if isinstance(text, str) and text.startswith("{"):
        try:
            obj = json.loads(text)
        except ValueError:
            return (text, None)
        return (obj.get("id"), obj.get("variant"))
    return (text, None)


def _iso_from_millis(millis):
    if not isinstance(millis, int) or millis <= 0:
        return None
    return dt.datetime.fromtimestamp(millis / 1000.0,
                                     tz=dt.timezone.utc).isoformat()


def _tokens_from_message_data(data):
    raw = data.get("tokens")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for src, name in _FLAT_FIELDS:
        value = raw.get(src)
        if isinstance(value, int) and not isinstance(value, bool):
            out[name] = value
    cache = raw.get("cache")
    if isinstance(cache, dict):
        for src, name in _CACHE_FIELDS:
            value = cache.get(src)
            if isinstance(value, int) and not isinstance(value, bool):
                out[name] = value
    return out


def _snapshot(db_path, tmpdir):
    """複製 db/-wal/-shm 到暫存目錄再讀複本。

    DB 正被跑著的 pod 寫入。WAL 模式下連唯讀開啟都可能需要建 -shm 檔，
    所以絕不直接開原檔。複本可能有一點不一致，對統計無妨。
    """
    dst = os.path.join(tmpdir, "snapshot.db")
    shutil.copy2(db_path, dst)
    for ext in ("-wal", "-shm"):
        src = db_path + ext
        if os.path.isfile(src):
            shutil.copy2(src, dst + ext)
    return dst


def _tables(cur):
    return {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def parse(home, bot, ctx, watermark):
    result = ParseResult()
    db_path = find_db(home)
    if not db_path:
        result.health["notes"].append("找不到 opencode.db")
        return result

    since = watermark.get("time_updated", 0)
    high_water = since

    with tempfile.TemporaryDirectory() as tmpdir:
        con = sqlite3.connect(_snapshot(db_path, tmpdir))
        con.text_factory = lambda b: b.decode("utf-8", "replace")
        cur = con.cursor()
        have = _tables(cur)

        if "message" in have:
            high_water = max(high_water,
                             _emit_messages(cur, result, bot, db_path, since))
        if "session" in have:
            high_water = max(high_water,
                             _emit_sessions(cur, result, bot, db_path, since))
        for table in ("part", "event"):
            if table in have:
                high_water = max(high_water,
                                 _emit_tasks(cur, result, table, bot, ctx,
                                             db_path, since))
        con.close()

    result.watermark = {"time_updated": high_water}
    return result


def _emit_messages(cur, result, bot, db_path, since):
    """per-message usage：token 與 model，沒有成本。"""
    high = since
    for msg_id, session_id, created, updated, raw in cur.execute(
            "SELECT id, session_id, time_created, time_updated, data FROM message"
            " WHERE COALESCE(time_updated, 0) > ?", (since,)):
        result.health["records"] += 1
        high = max(high, updated or 0)
        if not isinstance(raw, str):
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            result.health["unparsable"] += 1
            continue
        tokens = _tokens_from_message_data(data)
        if not tokens:
            continue
        model_id, variant = parse_model_field(data.get("modelID"))
        result.usages.append({
            "schema": USAGE_SCHEMA, "bot": bot, "cli": "opencode",
            "session_id": session_id,
            "model_id": model_id, "model_variant": variant,
            "occurred_at": _iso_from_millis(created),
            "tokens": tokens,
            # 成本只在 session 層拿得到，所以這裡明確標成 unavailable，
            # 不可退化成 0（那會被讀成「這些 token 不花錢」）。
            "cost": None, "cost_source": "unavailable",
            "origin": "main",
            "usage_key": "message:%s" % msg_id,
            "source_file": db_path, "source_ref": "message:%s" % msg_id,
        })
    return high


def _emit_sessions(cur, result, bot, db_path, since):
    """per-session 成本事件：tokens 刻意留空，與 message 層不重疊。"""
    high = since
    children = 0
    for (session_id, parent_id, created, updated, model, cost) in cur.execute(
            "SELECT id, parent_id, time_created, time_updated, model, cost"
            " FROM session WHERE COALESCE(time_updated, 0) > ?", (since,)):
        high = max(high, updated or 0)
        if parent_id:
            children += 1
        if not isinstance(cost, (int, float)):
            continue
        model_id, variant = parse_model_field(model)
        result.usages.append({
            "schema": USAGE_SCHEMA, "bot": bot, "cli": "opencode",
            "session_id": session_id,
            "model_id": model_id, "model_variant": variant,
            "occurred_at": _iso_from_millis(created),
            # 空 dict：成本事件不帶 token，這樣不管怎麼加總都不會重複計算。
            "tokens": {},
            "cost": float(cost), "cost_source": "cli",
            "origin": "session_cost",
            "usage_key": "session_cost:%s" % session_id,
            "source_file": db_path, "source_ref": "session:%s" % session_id,
            "parent_session_id": parent_id or None,
        })
    if children:
        result.health["notes"].append(
            "session 表有 %d 列帶 parent_id（subagent 子 session），"
            "聚合時不可與 parent 重複計算" % children)
    return high


def _emit_tasks(cur, result, table, bot, ctx, db_path, since):
    """sender_context 在 part.data（持久）與 event.data（event log）。"""
    high = since
    if table == "part":
        rows = cur.execute(
            "SELECT id, session_id, time_updated, data FROM part"
            " WHERE COALESCE(time_updated, 0) > ? AND CAST(data AS TEXT) LIKE ?",
            (since, "%sender_context%"))
    else:
        # event 表沒有時間欄位，只能靠 dedup_key 去重（全表掃）。
        rows = ((r[0], r[1], 0, r[2]) for r in cur.execute(
            "SELECT id, aggregate_id, data FROM event"
            " WHERE CAST(data AS TEXT) LIKE ?", ("%sender_context%",)))

    for row_id, session_id, updated, raw in rows:
        result.health["records"] += 1
        high = max(high, updated or 0)
        if not isinstance(raw, str):
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            result.health["unparsable"] += 1
            continue
        for json_path, sc in sc_mod.extract(data):
            platform = ctx.platform_for(
                sc.get("thread_id") or sc.get("channel_id") or "")
            result.tasks.append({
                "schema": TASK_SCHEMA, "bot": bot, "cli": "opencode",
                "platform": platform,
                "dedup_key": sc_mod.dedup_key(platform, sc),
                "channel_id": sc.get("channel_id"),
                "thread_id": sc.get("thread_id"),
                "session_id": session_id,
                "sender_id": sc.get("sender_id"),
                "sender_name": sc.get("sender_name"),
                "display_name": sc.get("display_name"),
                "source": sc_mod.classify_source(sc),
                "occurred_at": sc.get("timestamp"),
                "source_file": db_path,
                "source_ref": "%s:%s:%s" % (table, row_id, json_path),
            })
    return high
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 69 個測試（`Ran 69 tests`）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/usage-stats/parse_opencode.py \
        deployment-guides/k3s/usage-stats/tests/test_parse_opencode.py
git commit -m "feat(usage-stats): opencode SQLite parser —— token 與成本分事件、不碰 part/event 的 token"
```

---

### Task 6: `collect.py` —— CronJob 的入口

**Files:**
- Create: `deployment-guides/k3s/usage-stats/collect.py`
- Test: `deployment-guides/k3s/usage-stats/tests/test_collect.py`

**Interfaces:**
- Consumes: `events.day_key`／`write_events`／`ParseContext`、三個 `parse_*.parse`
- Produces:
  - `detect_cli(home: str) -> str | None` — `"opencode"` | `"claude-code"` | `"codex"` | `None`
  - `collect_one(home, bot, out_dir, watermark) -> ParseResult`
  - `main(argv: list) -> int` — CLI 入口，`--root`／`--out`／`--bots`
  - 事件檔命名：`<out_dir>/events/task-YYYY-MM-DD.jsonl`、
    `<out_dir>/events/usage-YYYY-MM-DD.jsonl`
  - 水位檔：`<out_dir>/watermark.json`，形如 `{bot: {...}}`

**關鍵：opencode 必須先判 `opencode.db`。** 真實環境 `.config/opencode` 目錄與
`opencode.db` 同時存在，而前者只有幾百 bytes 的設定檔——**先比對目錄就會把三隻
opencode bot 誤判成「沒有資料」**，實測第一次跑就是這樣錯的。

- [ ] **Step 1: 寫失敗的測試**

`tests/test_collect.py`：

```python
"""collect.py 的測試：CLI 偵測、按日切檔、水位持久化。"""
import json
import os
import sqlite3
import tempfile
import unittest

from collect import collect_one, detect_cli, main


def make_claude_home(root, bot, records):
    home = os.path.join(root, "agent-" + bot)
    d = os.path.join(home, ".claude", "projects", "-home-node")
    os.makedirs(d)
    with open(os.path.join(d, "s1.jsonl"), "w") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.makedirs(os.path.join(home, ".openab"))
    with open(os.path.join(home, ".openab", "thread_map.json"), "w") as fh:
        json.dump({"persisted": {"discord:t1": "s1"}}, fh)
    return home


def sc_text(message_id, ts):
    return ('<sender_context>\n{"schema":"openab.sender.v1","sender_id":"824",'
            '"sender_name":"wm4n","display_name":"william","channel":"discord",'
            '"channel_id":"c1","thread_id":"t1","is_bot":false,'
            '"timestamp":"%s","message_id":"%s"}\n</sender_context>'
            % (ts, message_id))


def user_record(message_id, ts):
    return {"type": "user", "sessionId": "s1", "message": {
        "role": "user", "content": [{"type": "text", "text": sc_text(message_id, ts)}]}}


class TestDetectCli(unittest.TestCase):
    def test_claude_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "h")
            os.makedirs(os.path.join(home, ".claude", "projects"))
            self.assertEqual(detect_cli(home), "claude-code")

    def test_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "h")
            os.makedirs(os.path.join(home, ".codex", "sessions"))
            self.assertEqual(detect_cli(home), "codex")

    def test_opencode_db_wins_over_config_dir(self):
        # 真實環境兩者同時存在；先比對目錄會誤判成「沒有資料」
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "h")
            share = os.path.join(home, ".local", "share", "opencode")
            os.makedirs(share)
            os.makedirs(os.path.join(home, ".config", "opencode"))
            sqlite3.connect(os.path.join(share, "opencode.db")).close()
            self.assertEqual(detect_cli(home), "opencode")

    def test_config_dir_alone_is_not_opencode_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "h")
            os.makedirs(os.path.join(home, ".config", "opencode"))
            self.assertIsNone(detect_cli(home))

    def test_empty_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(detect_cli(tmp))


class TestCollectOne(unittest.TestCase):
    def test_writes_events_split_by_taipei_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            # 06:32Z → 台北 9/10；17:30Z → 台北 9/11
            home = make_claude_home(root, "rick", [
                user_record("m1", "2026-09-10T06:32:10Z"),
                user_record("m2", "2026-09-10T17:30:00Z")])
            out = os.path.join(tmp, "out")
            collect_one(home, "rick", out, {})
            ev = os.path.join(out, "events")
            self.assertTrue(os.path.isfile(os.path.join(ev, "task-2026-09-10.jsonl")))
            self.assertTrue(os.path.isfile(os.path.join(ev, "task-2026-09-11.jsonl")))

    def test_event_without_timestamp_goes_to_unknown_bucket_not_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            bad = {"type": "user", "sessionId": "s1", "message": {
                "role": "user", "content": [{"type": "text", "text":
                    '<sender_context>\n{"schema":"openab.sender.v1",'
                    '"sender_id":"1","is_bot":false,"message_id":"m9"}\n'
                    '</sender_context>'}]}}
            home = make_claude_home(root, "rick", [bad])
            out = os.path.join(tmp, "out")
            collect_one(home, "rick", out, {})
            path = os.path.join(out, "events", "task-unknown.jsonl")
            self.assertTrue(os.path.isfile(path))
            with open(path) as fh:
                self.assertEqual(len(fh.readlines()), 1)

    def test_second_run_writes_nothing_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            home = make_claude_home(root, "rick",
                                    [user_record("m1", "2026-09-10T06:32:10Z")])
            out = os.path.join(tmp, "out")
            first = collect_one(home, "rick", out, {})
            second = collect_one(home, "rick", out, first.watermark)
            self.assertEqual(len(first.tasks), 1)
            self.assertEqual(len(second.tasks), 0)


class TestMain(unittest.TestCase):
    def test_processes_all_agent_dirs_and_persists_watermark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            make_claude_home(root, "rick", [user_record("m1", "2026-09-10T06:32:10Z")])
            make_claude_home(root, "morty", [user_record("m2", "2026-09-10T07:00:00Z")])
            out = os.path.join(tmp, "out")
            rc = main(["--root", root, "--out", out])
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "watermark.json")) as fh:
                marks = json.load(fh)
            self.assertEqual(sorted(marks), ["morty", "rick"])

    def test_bots_filter_limits_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            make_claude_home(root, "rick", [user_record("m1", "2026-09-10T06:32:10Z")])
            make_claude_home(root, "morty", [user_record("m2", "2026-09-10T07:00:00Z")])
            out = os.path.join(tmp, "out")
            main(["--root", root, "--out", out, "--bots", "rick"])
            with open(os.path.join(out, "watermark.json")) as fh:
                self.assertEqual(sorted(json.load(fh)), ["rick"])

    def test_missing_root_returns_nonzero(self):
        self.assertNotEqual(main(["--root", "/nonexistent", "--out", "/tmp/x"]), 0)

    def test_unrecognised_agent_is_reported_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(os.path.join(root, "agent-ghost"))
            out = os.path.join(tmp, "out")
            rc = main(["--root", root, "--out", out])
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "collect-health.json")) as fh:
                health = json.load(fh)
            self.assertIn("ghost", health["unrecognised"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_collect -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'collect'`

- [ ] **Step 3: 寫最小實作**

`deployment-guides/k3s/usage-stats/collect.py`：

```python
#!/usr/bin/env python3
"""收集器：把各 agent CLI 的原始儲存轉成正規化事件。CronJob 跑的就是這支。

**只收集，不產報表。** 報表由 report.py 手動產生。分開的理由是原始資料會被
CLI 清掉（claude-code 有 cleanupPeriodDays，預設 30 天），錯過即永久遺失，
所以收集必須定期跑；而報表隨時可以重跑。

唯讀：絕不寫入 agent 的 HOME。
"""
import argparse
import json
import os
import sys

import parse_claude_code
import parse_codex
import parse_opencode
from events import ParseContext, day_key, write_events

_PARSERS = {
    "claude-code": parse_claude_code.parse,
    "codex": parse_codex.parse,
    "opencode": parse_opencode.parse,
}


def detect_cli(home):
    """判斷這個 agent home 用哪個 CLI。

    opencode 必須先判 —— 它的資料在 SQLite，而 .config/opencode 目錄同時
    存在（裡面只有幾百 bytes 的設定檔）。先比對目錄會把三隻 opencode bot
    誤判成「沒有資料」。
    """
    if parse_opencode.find_db(home):
        return "opencode"
    if os.path.isdir(os.path.join(home, ".claude", "projects")):
        return "claude-code"
    if os.path.isdir(os.path.join(home, ".codex")):
        return "codex"
    return None


def _bucket(event):
    """事件按台北日界線分桶。沒有時間戳的進 unknown —— 不可丟掉。"""
    ts = event.get("occurred_at")
    if not ts:
        return "unknown"
    try:
        return day_key(ts)
    except (ValueError, TypeError):
        return "unknown"


def _write_by_day(out_dir, prefix, items):
    buckets = {}
    for item in items:
        buckets.setdefault(_bucket(item), []).append(item)
    events_dir = os.path.join(out_dir, "events")
    for day, rows in sorted(buckets.items()):
        write_events(os.path.join(events_dir, "%s-%s.jsonl" % (prefix, day)), rows)


def collect_one(home, bot, out_dir, watermark):
    """跑一隻 bot，寫出事件，回傳 ParseResult（含新水位）。"""
    cli = detect_cli(home)
    if not cli:
        raise ValueError("認不出 %s 的 CLI" % bot)
    result = _PARSERS[cli](home, bot, ParseContext.from_agent_home(home),
                           watermark or {})
    _write_by_day(out_dir, "task", result.tasks)
    _write_by_day(out_dir, "usage", result.usages)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="openab 使用統計收集器")
    parser.add_argument("--root", default="/data/william/openab",
                        help="agent-* 目錄的父路徑")
    parser.add_argument("--out", required=True, help="事件與水位的輸出目錄")
    parser.add_argument("--bots", default="",
                        help="只處理這些 bot（逗號分隔），預設全部")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.root):
        print("錯誤：%s 不存在" % args.root, file=sys.stderr)
        return 1

    wanted = [b.strip() for b in args.bots.split(",") if b.strip()]
    marks_path = os.path.join(args.out, "watermark.json")
    try:
        with open(marks_path, encoding="utf-8") as fh:
            marks = json.load(fh)
    except (OSError, ValueError):
        marks = {}

    health = {"bots": {}, "unrecognised": [], "errors": {}}
    for entry in sorted(os.listdir(args.root)):
        if not entry.startswith("agent-"):
            continue
        bot = entry[len("agent-"):]
        if wanted and bot not in wanted:
            continue
        home = os.path.join(args.root, entry)
        if not detect_cli(home):
            # 不可靜默跳過：認不出的 bot 要出現在健康度報告裡。
            health["unrecognised"].append(bot)
            print("警告：認不出 %s 的 CLI，略過" % bot, file=sys.stderr)
            continue
        try:
            result = collect_one(home, bot, args.out, marks.get(bot, {}))
        except Exception as exc:  # noqa: BLE001 —— 一隻壞掉不該讓其他隻收不到
            health["errors"][bot] = "%s: %s" % (type(exc).__name__, exc)
            print("錯誤：%s 收集失敗 —— %s" % (bot, exc), file=sys.stderr)
            continue
        marks[bot] = result.watermark
        health["bots"][bot] = {
            "tasks": len(result.tasks), "usages": len(result.usages),
            "records": result.health["records"],
            "unparsable": result.health["unparsable"],
            "notes": result.health["notes"],
        }
        print("%-8s 任務 %4d  用量 %4d  紀錄 %6d  不可解析 %d"
              % (bot, len(result.tasks), len(result.usages),
                 result.health["records"], result.health["unparsable"]))

    os.makedirs(args.out, exist_ok=True)
    with open(marks_path, "w", encoding="utf-8") as fh:
        json.dump(marks, fh, ensure_ascii=False, indent=2, sort_keys=True)
    with open(os.path.join(args.out, "collect-health.json"), "w",
              encoding="utf-8") as fh:
        json.dump(health, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 81 個測試（`Ran 81 tests`）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/usage-stats/collect.py \
        deployment-guides/k3s/usage-stats/tests/test_collect.py
git commit -m "feat(usage-stats): collect.py —— CronJob 入口，按台北日界線切檔、水位持久化"
```

---
