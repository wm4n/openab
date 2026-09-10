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

### Task 7: `aggregate.py` —— 任務數、每人任務數、對話數

**Files:**
- Create: `deployment-guides/k3s/usage-stats/aggregate.py`
- Test: `deployment-guides/k3s/usage-stats/tests/test_aggregate_tasks.py`

**Interfaces:**
- Consumes: `events.day_key`
- Produces（全部是純函數，吃事件 list 吐 dict）：
  - `dedupe_tasks(tasks: list) -> list` — 依 `(bot, dedup_key)` 去重，保留第一筆
  - `daily_task_counts(tasks: list) -> dict` —
    `{day: {bot: {"human": n, "bot_relay": n, "cron": n}}}`
  - `daily_per_user(tasks: list) -> dict` —
    `{day: {bot: {sender_id: n}}}`，只算 `source == "human"`
  - `active_users(tasks: list) -> dict` —
    `{bot: {sender_id: {"display_name": str, "tasks": n}}}`
  - `daily_conversations(tasks: list) -> dict` —
    `{day: {bot: {"new": n, "continued": n}}}`

**去重是必須的，不是優化。** 實測同一筆任務會出現在多個路徑（summer 74 筆
`sender_context` 只有 37 個 distinct `message_id`），不去重會直接把任務數翻倍。

- [ ] **Step 1: 寫失敗的測試**

`tests/test_aggregate_tasks.py`：

```python
"""aggregate.py 任務側指標的測試。

去重、三分類、以及「新開 vs 延續對話」的日界線判斷。
"""
import unittest

from aggregate import (
    active_users, daily_conversations, daily_per_user, daily_task_counts,
    dedupe_tasks,
)


def task(dedup_key, source="human", bot="rick", ts="2026-09-10T06:32:10Z",
         sender_id="824", display_name="william", session_id="s1"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "occurred_at": ts, "sender_id": sender_id,
            "display_name": display_name, "session_id": session_id}


class TestDedupeTasks(unittest.TestCase):
    def test_same_task_from_two_paths_collapses_to_one(self):
        rows = dedupe_tasks([task("discord:m1"), task("discord:m1")])
        self.assertEqual(len(rows), 1)

    def test_different_bots_with_same_message_id_are_kept_separate(self):
        # 同一則 Discord 訊息可能同時 @ 兩隻 bot —— 那是兩個任務
        rows = dedupe_tasks([task("discord:m1", bot="rick"),
                             task("discord:m1", bot="morty")])
        self.assertEqual(len(rows), 2)

    def test_keeps_first_occurrence_order_stable(self):
        rows = dedupe_tasks([task("discord:m1", display_name="first"),
                             task("discord:m1", display_name="second")])
        self.assertEqual(rows[0]["display_name"], "first")

    def test_empty_input(self):
        self.assertEqual(dedupe_tasks([]), [])


class TestDailyTaskCounts(unittest.TestCase):
    def test_splits_three_sources_and_never_merges_them(self):
        rows = [task("d:1", "human"), task("d:2", "human"),
                task("d:3", "bot_relay"), task("d:4", "cron"), task("d:5", "cron")]
        got = daily_task_counts(rows)
        self.assertEqual(got["2026-09-10"]["rick"],
                         {"human": 2, "bot_relay": 1, "cron": 2})

    def test_uses_taipei_day_boundary(self):
        # 17:30Z = 台北隔日 01:30
        rows = [task("d:1", ts="2026-09-10T17:30:00Z")]
        self.assertIn("2026-09-11", daily_task_counts(rows))

    def test_deduplicates_before_counting(self):
        got = daily_task_counts([task("d:1"), task("d:1")])
        self.assertEqual(got["2026-09-10"]["rick"]["human"], 1)

    def test_task_without_timestamp_lands_in_unknown_bucket(self):
        rows = [dict(task("d:1"), occurred_at=None)]
        self.assertEqual(daily_task_counts(rows)["unknown"]["rick"]["human"], 1)

    def test_zero_source_still_present_so_reader_sees_a_real_zero(self):
        got = daily_task_counts([task("d:1", "human")])
        self.assertEqual(got["2026-09-10"]["rick"]["cron"], 0)


class TestDailyPerUser(unittest.TestCase):
    def test_counts_only_human_tasks(self):
        rows = [task("d:1", "human", sender_id="824"),
                task("d:2", "human", sender_id="824"),
                task("d:3", "human", sender_id="999"),
                task("d:4", "cron", sender_id="openab-cron")]
        got = daily_per_user(rows)
        self.assertEqual(got["2026-09-10"]["rick"], {"824": 2, "999": 1})

    def test_cron_sender_never_appears(self):
        got = daily_per_user([task("d:1", "cron", sender_id="openab-cron")])
        self.assertEqual(got, {})


class TestActiveUsers(unittest.TestCase):
    def test_counts_distinct_humans_per_bot(self):
        rows = [task("d:1", sender_id="824", display_name="william"),
                task("d:2", sender_id="999", display_name="Alice")]
        got = active_users(rows)
        self.assertEqual(sorted(got["rick"]), ["824", "999"])
        self.assertEqual(got["rick"]["824"]["tasks"], 1)

    def test_display_name_takes_the_most_recent_occurrence(self):
        # 名稱會隨改名而變；聚合以 sender_id 為準，顯示取最近一次
        rows = [task("d:1", sender_id="824", display_name="old",
                     ts="2026-09-01T00:00:00Z"),
                task("d:2", sender_id="824", display_name="new",
                     ts="2026-09-10T00:00:00Z")]
        self.assertEqual(active_users(rows)["rick"]["824"]["display_name"], "new")


class TestDailyConversations(unittest.TestCase):
    def test_first_day_of_a_session_is_new(self):
        rows = [task("d:1", session_id="sA", ts="2026-09-10T06:00:00Z")]
        self.assertEqual(daily_conversations(rows)["2026-09-10"]["rick"],
                         {"new": 1, "continued": 0})

    def test_later_day_of_same_session_is_continued(self):
        rows = [task("d:1", session_id="sA", ts="2026-09-10T06:00:00Z"),
                task("d:2", session_id="sA", ts="2026-09-11T06:00:00Z")]
        got = daily_conversations(rows)
        self.assertEqual(got["2026-09-10"]["rick"], {"new": 1, "continued": 0})
        self.assertEqual(got["2026-09-11"]["rick"], {"new": 0, "continued": 1})

    def test_multiple_tasks_in_one_session_count_the_session_once(self):
        rows = [task("d:1", session_id="sA"), task("d:2", session_id="sA")]
        self.assertEqual(daily_conversations(rows)["2026-09-10"]["rick"]["new"], 1)

    def test_counts_all_sources_not_just_human(self):
        # 對話數是資源指標，cron 開的 session 也佔資源
        rows = [task("d:1", "cron", session_id="sA")]
        self.assertEqual(daily_conversations(rows)["2026-09-10"]["rick"]["new"], 1)

    def test_task_without_session_id_is_ignored_for_conversations(self):
        rows = [dict(task("d:1"), session_id=None)]
        self.assertEqual(daily_conversations(rows), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_aggregate_tasks -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'aggregate'`

- [ ] **Step 3: 寫最小實作**

`deployment-guides/k3s/usage-stats/aggregate.py`：

```python
"""正規化事件 → 每日指標。全部是純函數，吃 list 吐 dict。

純函數化的用意是「指標定義改了可以重算歷史」—— 不用重新解析原始儲存
（那些資料可能已經被 CLI 清掉了）。
"""
from events import day_key

# 任務來源的三個分類。cron 不能混進 bot_relay：實測 Rick 的負載 84% 來自
# 排程、真正的三 bot 接力只佔 5%，混在一起會讓採用率數字失去意義。
SOURCES = ("human", "bot_relay", "cron")

_UNKNOWN_DAY = "unknown"


def _day_of(event):
    ts = event.get("occurred_at")
    if not ts:
        return _UNKNOWN_DAY
    try:
        return day_key(ts)
    except (ValueError, TypeError):
        return _UNKNOWN_DAY


def dedupe_tasks(tasks):
    """依 (bot, dedup_key) 去重，保留第一筆。

    這是必須的不是優化：同一筆任務會出現在多個路徑（實測 summer 74 筆
    sender_context 只有 37 個 distinct message_id），不去重任務數直接翻倍。
    同一則訊息 @ 兩隻 bot 是兩個任務，所以 key 要帶 bot。
    """
    seen = set()
    out = []
    for task in tasks:
        key = (task.get("bot"), task.get("dedup_key"))
        if key in seen:
            continue
        seen.add(key)
        out.append(task)
    return out


def daily_task_counts(tasks):
    """{day: {bot: {human, bot_relay, cron}}}。三個分類一律都在，缺的是真 0。"""
    out = {}
    for task in dedupe_tasks(tasks):
        day = _day_of(task)
        bot = task.get("bot")
        bucket = out.setdefault(day, {}).setdefault(
            bot, dict.fromkeys(SOURCES, 0))
        source = task.get("source")
        if source in bucket:
            bucket[source] += 1
    return out


def daily_per_user(tasks):
    """{day: {bot: {sender_id: n}}}，只算真人任務。

    這一項是精確值（每筆任務都帶觸發者，無歧義），跟 token 的 session 層
    歸因不同 —— 報表不可讓兩者看起來同等可信。
    """
    out = {}
    for task in dedupe_tasks(tasks):
        if task.get("source") != "human":
            continue
        day = _day_of(task)
        bot = task.get("bot")
        users = out.setdefault(day, {}).setdefault(bot, {})
        sender_id = task.get("sender_id")
        users[sender_id] = users.get(sender_id, 0) + 1
    return out


def active_users(tasks):
    """{bot: {sender_id: {"display_name": str, "tasks": n}}}。

    聚合以 sender_id 為準（穩定鍵），display_name 只用於顯示且取最近一次
    出現的值 —— 使用者改名時舊名稱不該蓋掉新名稱。
    """
    out = {}
    latest = {}
    for task in dedupe_tasks(tasks):
        if task.get("source") != "human":
            continue
        bot = task.get("bot")
        sender_id = task.get("sender_id")
        entry = out.setdefault(bot, {}).setdefault(
            sender_id, {"display_name": None, "tasks": 0})
        entry["tasks"] += 1
        ts = task.get("occurred_at") or ""
        if ts >= latest.get((bot, sender_id), ""):
            latest[(bot, sender_id)] = ts
            entry["display_name"] = task.get("display_name")
    return out


def daily_conversations(tasks):
    """{day: {bot: {"new": n, "continued": n}}}。

    「新開」= 該 session 的第一筆事件落在當日。session TTL 是 24 小時，
    跨日的 session 會在兩天都被算進「有活動」—— 這是對的，但報表必須註明
    「逐日加總會大於實際對話數」。
    """
    deduped = dedupe_tasks(tasks)
    first_day = {}
    for task in deduped:
        session_id = task.get("session_id")
        if not session_id:
            continue
        key = (task.get("bot"), session_id)
        day = _day_of(task)
        if key not in first_day or day < first_day[key]:
            first_day[key] = day

    active = set()
    for task in deduped:
        session_id = task.get("session_id")
        if session_id:
            active.add((task.get("bot"), session_id, _day_of(task)))

    out = {}
    for bot, session_id, day in active:
        bucket = out.setdefault(day, {}).setdefault(
            bot, {"new": 0, "continued": 0})
        if first_day[(bot, session_id)] == day:
            bucket["new"] += 1
        else:
            bucket["continued"] += 1
    return out
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 99 個測試（`Ran 99 tests`）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/usage-stats/aggregate.py \
        deployment-guides/k3s/usage-stats/tests/test_aggregate_tasks.py
git commit -m "feat(usage-stats): aggregate 任務側 —— 去重、三分類、每人任務數、對話數"
```

---

### Task 8: `aggregate.py` —— token、成本、session 層歸因

**Files:**
- Modify: `deployment-guides/k3s/usage-stats/aggregate.py`（附加函式，不改 Task 7 的）
- Test: `deployment-guides/k3s/usage-stats/tests/test_aggregate_usage.py`

**Interfaces:**
- Consumes: Task 7 的 `_day_of`、`dedupe_tasks`
- Produces:
  - `TOKEN_KINDS = ("input", "output", "cache_read", "cache_write", "reasoning")`
  - `dedupe_usages(usages: list) -> list` — 依 `(bot, usage_key)` 去重
  - `daily_tokens(usages: list) -> dict` —
    `{day: {bot: {(model_id, variant): {kind: n}}}}`（key 是 tuple）
  - `daily_cost(usages: list) -> dict` —
    `{day: {bot: {cost_source: float}}}`，`cost_source` ∈ `cli`／`pricebook`／
    `subscription`／`unavailable`
  - `session_attribution(tasks: list, usages: list) -> dict` —
    `{bot: {"attributed": {sender_id: {kind: n}}, "shared": {kind: n},
    "unattributed": {kind: n}, "coverage": float}}`

**成本三段分開，不可混加。** `cost_source` 決定一筆成本能不能信：`cli` 是 opencode
自己算的實際費用、`subscription` 是 Claude 家族（token 數**不等於**帳單金額）、
`unavailable` 是有 token 但拿不到成本。混加會算出假成本，比沒有數字更糟。

**歸因到 session 層而非 task 層。** 一個 session 只有一位真人 sender 時歸因無歧義；
有多位時歸到 `shared` 不強行拆分。`coverage` 是無歧義歸因佔總量的比例——沒有這個
數字，讀者無法判斷「誰在燒量」可信到什麼程度。

- [ ] **Step 1: 寫失敗的測試**

`tests/test_aggregate_usage.py`：

```python
"""aggregate.py 用量側指標的測試。

成本三段不可混加、token 的 model 維度是 (id, variant)、歸因到 session 層。
"""
import unittest

from aggregate import (
    TOKEN_KINDS, daily_cost, daily_tokens, dedupe_usages, session_attribution,
)


def usage(usage_key, tokens=None, bot="rick", model="claude-opus-5",
          variant=None, ts="2026-09-10T06:33:00Z", cost=None,
          cost_source="subscription", session_id="s1", origin="main"):
    return {"bot": bot, "usage_key": usage_key,
            "tokens": {"input": 100, "output": 200} if tokens is None else tokens,
            "model_id": model, "model_variant": variant, "occurred_at": ts,
            "cost": cost, "cost_source": cost_source,
            "session_id": session_id, "origin": origin}


def task(dedup_key, sender_id="824", session_id="s1", bot="rick",
         source="human", ts="2026-09-10T06:32:10Z"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "sender_id": sender_id, "session_id": session_id,
            "occurred_at": ts, "display_name": "william"}


class TestDedupeUsages(unittest.TestCase):
    def test_rerun_of_collector_does_not_double_count(self):
        rows = dedupe_usages([usage("f#1#main"), usage("f#1#main")])
        self.assertEqual(len(rows), 1)

    def test_different_origin_on_same_offset_is_distinct(self):
        # claude-code 一筆紀錄可能同時有 main 與 subagent 用量
        rows = dedupe_usages([usage("f#1#main"), usage("f#1#subagent")])
        self.assertEqual(len(rows), 2)


class TestDailyTokens(unittest.TestCase):
    def test_groups_by_model_and_variant_tuple(self):
        rows = [usage("k1", model="deepseek/x", variant="low"),
                usage("k2", model="deepseek/x", variant="default")]
        got = daily_tokens(rows)["2026-09-10"]["rick"]
        self.assertEqual(sorted(got), [("deepseek/x", "default"),
                                       ("deepseek/x", "low")])

    def test_sums_each_kind_separately_never_totalling(self):
        rows = [usage("k1", {"input": 10, "output": 20, "cache_read": 30}),
                usage("k2", {"input": 1, "output": 2, "cache_read": 3})]
        got = daily_tokens(rows)["2026-09-10"]["rick"][("claude-opus-5", None)]
        self.assertEqual(got["input"], 11)
        self.assertEqual(got["cache_read"], 33)

    def test_absent_kind_is_omitted_not_zeroed(self):
        # 「不支援」與 0 必須可區分
        got = daily_tokens([usage("k1", {"input": 5})])
        bucket = got["2026-09-10"]["rick"][("claude-opus-5", None)]
        self.assertNotIn("cache_write", bucket)

    def test_session_cost_events_contribute_no_tokens(self):
        # opencode 的成本事件 tokens 是空 dict —— 結構上不可能重複計算
        rows = [usage("m1", {"input": 10}),
                usage("sc1", {}, cost=1.5, cost_source="cli",
                      origin="session_cost")]
        got = daily_tokens(rows)["2026-09-10"]["rick"]
        self.assertEqual(sum(v.get("input", 0) for v in got.values()), 10)

    def test_all_five_kinds_are_recognised(self):
        full = dict.fromkeys(TOKEN_KINDS, 7)
        got = daily_tokens([usage("k1", full)])["2026-09-10"]["rick"]
        self.assertEqual(got[("claude-opus-5", None)], full)


class TestDailyCost(unittest.TestCase):
    def test_keeps_cost_sources_separate(self):
        rows = [usage("k1", cost=1.5, cost_source="cli"),
                usage("k2", cost=None, cost_source="subscription")]
        got = daily_cost(rows)["2026-09-10"]["rick"]
        self.assertAlmostEqual(got["cli"], 1.5)
        self.assertEqual(got["subscription"], 0.0)

    def test_subscription_never_accumulates_money(self):
        # Claude 家族走訂閱制，token 數不等於帳單金額
        rows = [usage("k1", cost=99.0, cost_source="subscription")]
        self.assertEqual(daily_cost(rows)["2026-09-10"]["rick"]["subscription"],
                         0.0)

    def test_unavailable_is_reported_as_a_category(self):
        rows = [usage("k1", cost=None, cost_source="unavailable")]
        self.assertIn("unavailable", daily_cost(rows)["2026-09-10"]["rick"])


class TestSessionAttribution(unittest.TestCase):
    def test_single_human_session_is_attributed_unambiguously(self):
        tasks = [task("d:1", sender_id="824", session_id="sA")]
        usages = [usage("k1", {"input": 100}, session_id="sA")]
        got = session_attribution(tasks, usages)["rick"]
        self.assertEqual(got["attributed"]["824"]["input"], 100)
        self.assertEqual(got["coverage"], 1.0)

    def test_multi_human_session_goes_to_shared_not_split(self):
        tasks = [task("d:1", sender_id="824", session_id="sA"),
                 task("d:2", sender_id="999", session_id="sA")]
        usages = [usage("k1", {"input": 100}, session_id="sA")]
        got = session_attribution(tasks, usages)["rick"]
        self.assertEqual(got["shared"]["input"], 100)
        self.assertEqual(got["attributed"], {})
        self.assertEqual(got["coverage"], 0.0)

    def test_session_with_no_human_task_is_unattributed(self):
        # 例如純 cron 開的 session
        tasks = [task("d:1", source="cron", sender_id="openab-cron",
                      session_id="sA")]
        usages = [usage("k1", {"input": 100}, session_id="sA")]
        got = session_attribution(tasks, usages)["rick"]
        self.assertEqual(got["unattributed"]["input"], 100)

    def test_coverage_is_the_unambiguous_share_of_total_tokens(self):
        tasks = [task("d:1", sender_id="824", session_id="sA"),
                 task("d:2", sender_id="824", session_id="sB"),
                 task("d:3", sender_id="999", session_id="sB")]
        usages = [usage("k1", {"input": 300}, session_id="sA"),
                  usage("k2", {"input": 100}, session_id="sB")]
        got = session_attribution(tasks, usages)["rick"]
        self.assertAlmostEqual(got["coverage"], 0.75)

    def test_coverage_is_zero_when_there_is_nothing_to_attribute(self):
        self.assertEqual(session_attribution([], []), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_aggregate_usage -v
```

Expected: FAIL — `ImportError: cannot import name 'daily_tokens' from 'aggregate'`

- [ ] **Step 3: 寫最小實作**

在 `aggregate.py` **檔尾附加**（不動 Task 7 已有的函式）：

```python
# --- 用量側 ---------------------------------------------------------------

# tokens 裡前四項互斥可加；reasoning 只有 opencode 有（該家是加法項）。
# codex 的 reasoning 是 output 的子集，parser 已把它移到 tokens_info，
# 所以這裡看到的 reasoning 一律是加法項。
TOKEN_KINDS = ("input", "output", "cache_read", "cache_write", "reasoning")

# 只有這兩種來源代表真實可加的金額。subscription 是訂閱制（token 數不等於
# 帳單金額）、unavailable 是有 token 但拿不到成本 —— 兩者都不可累加金額，
# 但必須以分類出現在報表上，否則會被讀成「不花錢」。
_MONEY_SOURCES = ("cli", "pricebook")


def dedupe_usages(usages):
    """依 (bot, usage_key) 去重，讓 CronJob 重跑不會重複計算。"""
    seen = set()
    out = []
    for row in usages:
        key = (row.get("bot"), row.get("usage_key"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def daily_tokens(usages):
    """{day: {bot: {(model_id, variant): {kind: n}}}}。

    model 維度是 (id, variant) 而不只是 id —— opencode 的 variant
    （實測 walle 有 low／default）可能影響計價。
    """
    out = {}
    for row in dedupe_usages(usages):
        tokens = row.get("tokens") or {}
        if not tokens:
            continue
        day = _day_of(row)
        model_key = (row.get("model_id"), row.get("model_variant"))
        bucket = out.setdefault(day, {}).setdefault(
            row.get("bot"), {}).setdefault(model_key, {})
        for kind in TOKEN_KINDS:
            value = tokens.get(kind)
            if isinstance(value, int) and not isinstance(value, bool):
                bucket[kind] = bucket.get(kind, 0) + value
    return out


def daily_cost(usages):
    """{day: {bot: {cost_source: float}}}。四種來源都會出現，缺的是真 0。"""
    out = {}
    for row in dedupe_usages(usages):
        day = _day_of(row)
        bucket = out.setdefault(day, {}).setdefault(row.get("bot"), {
            "cli": 0.0, "pricebook": 0.0, "subscription": 0.0,
            "unavailable": 0.0})
        source = row.get("cost_source")
        if source not in bucket:
            continue
        cost = row.get("cost")
        if source in _MONEY_SOURCES and isinstance(cost, (int, float)):
            bucket[source] += float(cost)
    return out


def _add_tokens(target, tokens):
    for kind in TOKEN_KINDS:
        value = tokens.get(kind)
        if isinstance(value, int) and not isinstance(value, bool):
            target[kind] = target.get(kind, 0) + value


def session_attribution(tasks, usages):
    """把用量歸因到 session 的真人 sender。

    歸因層級刻意停在 session：把 token 對應到「某一個具體任務」需要一個
    三種格式都不保證的順序假設。一個 session 只有一位真人時無歧義；有多位
    時歸到 shared 不強行拆分。coverage 是無歧義歸因佔總量的比例，沒有它
    讀者無法判斷這個數字可信到什麼程度。
    """
    senders = {}
    for task in dedupe_tasks(tasks):
        if task.get("source") != "human":
            continue
        session_id = task.get("session_id")
        if session_id:
            senders.setdefault((task.get("bot"), session_id), set()).add(
                task.get("sender_id"))

    out = {}
    for row in dedupe_usages(usages):
        tokens = row.get("tokens") or {}
        if not tokens:
            continue
        bot = row.get("bot")
        entry = out.setdefault(bot, {"attributed": {}, "shared": {},
                                     "unattributed": {}, "coverage": 0.0})
        who = senders.get((bot, row.get("session_id")), set())
        if len(who) == 1:
            sender_id = next(iter(who))
            _add_tokens(entry["attributed"].setdefault(sender_id, {}), tokens)
        elif len(who) > 1:
            _add_tokens(entry["shared"], tokens)
        else:
            _add_tokens(entry["unattributed"], tokens)

    for entry in out.values():
        attributed = sum(sum(v.values()) for v in entry["attributed"].values())
        total = (attributed + sum(entry["shared"].values())
                 + sum(entry["unattributed"].values()))
        entry["coverage"] = (attributed / total) if total else 0.0
    return out
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 114 個測試（`Ran 114 tests`）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/usage-stats/aggregate.py \
        deployment-guides/k3s/usage-stats/tests/test_aggregate_usage.py
git commit -m "feat(usage-stats): aggregate 用量側 —— token 按 (model,variant)、成本三段分離、session 歸因"
```

---

### Task 9: `aggregate.py` —— 摩擦指標、失敗率代理、資料覆蓋率

**Files:**
- Modify: `deployment-guides/k3s/usage-stats/aggregate.py`（再附加，不動前兩批）
- Test: `deployment-guides/k3s/usage-stats/tests/test_aggregate_quality.py`

**Interfaces:**
- Consumes: Task 7 的 `_day_of`／`dedupe_tasks`
- Produces:
  - `friction_signals(tasks: list) -> dict` —
    `{bot: {"followup_median_seconds": float|None, "tasks_per_session": float|None,
    "abandoned_sessions": int}}`
  - `failure_proxy(thread_map_counts: dict, tasks: list) -> dict` —
    `{bot: {"sessions_created": int, "sessions_with_output": int, "gap": int}}`
  - `data_coverage(days: list, collect_health: dict) -> dict` —
    `{"days_expected": int, "days_present": int, "missing_days": list,
    "unparsable": int, "unrecognised": list}`

**摩擦指標**一律用「摩擦」不用「滿意」命名，報表必須明寫這不是滿意度量測。

**第一版只做兩個「結構性」訊號**（追問密度、放棄 session），**不做否定詞偵測**。
spec 原本列了三個訊號，但否定詞需要把使用者的訊息內容擷取進事件檔——那既有隱私
成本，而它又是三個訊號裡最弱的一項（「這段程式碼不對」是在講 code 不是在罵 bot）。
成本效益不對，延後到有明確評分機制可以校準它時再說。留下的兩個訊號只需要時間戳與
session ID，**事件檔完全不含對話內容**。

**失敗率代理**：`thread_map.json` 的 entry 數（`pool.rs:347-357` 在 `session/new`
成功後、送 prompt 之前就寫入）對比實際產出過 task 事件的 session 數。實測落差
morty 18 進 2 出、rick 33 進 26 出。這只有 session 粒度，也無法區分「失敗」與
「使用者只是 @ 了一下」——**定位是揪出可疑 bot 的紅旗，不是失敗率量測**。

- [ ] **Step 1: 寫失敗的測試**

`tests/test_aggregate_quality.py`：

```python
"""摩擦指標、失敗率代理、資料覆蓋率的測試。

這三項都是弱訊號或粗略代理，測試同時鎖住「它們算得對」與「它們不會假裝精確」。
"""
import unittest

from aggregate import data_coverage, failure_proxy, friction_signals


def task(dedup_key, ts, session_id="sA", bot="rick", sender_id="824",
         source="human"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "sender_id": sender_id, "session_id": session_id,
            "occurred_at": ts}


class TestFrictionSignals(unittest.TestCase):
    def test_followup_median_uses_gaps_between_same_sender_tasks(self):
        rows = [task("d:1", "2026-09-10T06:00:00Z"),
                task("d:2", "2026-09-10T06:01:00Z"),   # +60s
                task("d:3", "2026-09-10T06:04:00Z")]   # +180s
        got = friction_signals(rows)["rick"]
        self.assertEqual(got["followup_median_seconds"], 120.0)

    def test_single_task_session_has_no_followup_median(self):
        got = friction_signals([task("d:1", "2026-09-10T06:00:00Z")])["rick"]
        self.assertIsNone(got["followup_median_seconds"])

    def test_tasks_per_session_averages_human_tasks(self):
        rows = [task("d:1", "2026-09-10T06:00:00Z", session_id="sA"),
                task("d:2", "2026-09-10T06:01:00Z", session_id="sA"),
                task("d:3", "2026-09-10T06:02:00Z", session_id="sB")]
        self.assertEqual(friction_signals(rows)["rick"]["tasks_per_session"], 1.5)

    def test_no_message_content_is_needed_or_reported(self):
        # 第一版刻意不擷取對話內容：留下的兩個訊號只需要時間戳與 session ID
        rows = [task("d:1", "2026-09-10T06:00:00Z")]
        self.assertEqual(set(rows[0]) & {"prompt", "prompt_excerpt", "text"},
                         set())
        self.assertNotIn("negative_hits", friction_signals(rows)["rick"])

    def test_abandoned_session_is_one_that_only_ever_had_one_task(self):
        rows = [task("d:1", "2026-09-10T06:00:00Z", session_id="sA"),
                task("d:2", "2026-09-10T06:01:00Z", session_id="sA"),
                task("d:3", "2026-09-10T07:00:00Z", session_id="sB")]
        self.assertEqual(friction_signals(rows)["rick"]["abandoned_sessions"], 1)

    def test_cron_and_bot_tasks_are_excluded_from_friction(self):
        # 摩擦是人的感受，排程與 bot 互呼不算
        rows = [task("d:1", "2026-09-10T06:00:00Z", source="cron"),
                task("d:2", "2026-09-10T06:01:00Z", source="bot_relay")]
        self.assertEqual(friction_signals(rows), {})


class TestFailureProxy(unittest.TestCase):
    def test_gap_is_sessions_created_minus_sessions_with_output(self):
        # 實測 morty：thread_map 18 筆，只有 2 個 session 產出過 task
        counts = {"morty": 18}
        tasks = [task("d:1", "2026-09-10T06:00:00Z", session_id="s1", bot="morty"),
                 task("d:2", "2026-09-10T06:01:00Z", session_id="s2", bot="morty")]
        got = failure_proxy(counts, tasks)["morty"]
        self.assertEqual(got, {"sessions_created": 18,
                               "sessions_with_output": 2, "gap": 16})

    def test_more_output_sessions_than_thread_map_gives_negative_clamped_to_zero(self):
        # genie 實測 160 進 362 出（一 thread 多任務 + entry 會被移除）
        counts = {"genie": 2}
        # dedup_key 必須各不相同 —— 共用同一個會被 dedupe_tasks 收斂成一筆
        tasks = [task("d:%d" % i, "2026-09-10T06:00:00Z",
                      session_id="s%d" % i, bot="genie") for i in range(5)]
        self.assertEqual(failure_proxy(counts, tasks)["genie"]["gap"], 0)

    def test_bot_with_no_thread_map_entry_reports_none_not_zero(self):
        tasks = [task("d:1", "2026-09-10T06:00:00Z", bot="rick")]
        got = failure_proxy({}, tasks)["rick"]
        self.assertIsNone(got["sessions_created"])
        self.assertIsNone(got["gap"])


class TestDataCoverage(unittest.TestCase):
    def test_reports_missing_days_so_gaps_do_not_look_like_no_usage(self):
        got = data_coverage(["2026-09-08", "2026-09-10"], {})
        self.assertEqual(got["missing_days"], ["2026-09-09"])
        self.assertEqual(got["days_expected"], 3)
        self.assertEqual(got["days_present"], 2)

    def test_single_day_has_no_gap(self):
        got = data_coverage(["2026-09-10"], {})
        self.assertEqual(got["missing_days"], [])

    def test_surfaces_unparsable_count_from_collect_health(self):
        health = {"bots": {"rick": {"unparsable": 3}, "morty": {"unparsable": 1}}}
        self.assertEqual(data_coverage(["2026-09-10"], health)["unparsable"], 4)

    def test_surfaces_unrecognised_bots(self):
        health = {"unrecognised": ["ghost"]}
        self.assertEqual(data_coverage(["2026-09-10"], health)["unrecognised"],
                         ["ghost"])

    def test_no_days_at_all_is_reported_not_crashed(self):
        got = data_coverage([], {})
        self.assertEqual((got["days_expected"], got["days_present"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_aggregate_quality -v
```

Expected: FAIL — `ImportError: cannot import name 'friction_signals' from 'aggregate'`

- [ ] **Step 3: 寫最小實作**

在 `aggregate.py` **檔尾再附加**：

```python
# --- 摩擦指標、失敗率代理、覆蓋率 ------------------------------------------

def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def friction_signals(tasks):
    """{bot: {兩個弱訊號}}。**這不是滿意度量測。**

    兩個訊號都弱：追問密度可能只是任務本身複雜、放棄 session 也可能是使用者
    換 thread 繼續。報表必須用「摩擦」而非「滿意」命名，並明寫這一點。真正的
    滿意度要等明確評分機制，屆時才能用它來校準這些弱訊號。

    第一版刻意不做否定詞偵測 —— 那需要把使用者訊息內容擷取進事件檔（隱私
    成本），而它又是最弱的訊號。這裡的兩個訊號只用時間戳與 session ID。
    """
    per_bot = {}
    for task in dedupe_tasks(tasks):
        # 摩擦是人的感受：排程與 bot 互呼不算。
        if task.get("source") != "human":
            continue
        per_bot.setdefault(task.get("bot"), []).append(task)

    out = {}
    for bot, rows in per_bot.items():
        gaps = []
        by_session = {}
        for task in rows:
            by_session.setdefault(
                (task.get("session_id"), task.get("sender_id")), []).append(task)

        for group in by_session.values():
            stamps = sorted(t.get("occurred_at") or "" for t in group)
            for earlier, later in zip(stamps, stamps[1:]):
                delta = _seconds_between(earlier, later)
                if delta is not None:
                    gaps.append(delta)

        sessions = {t.get("session_id") for t in rows if t.get("session_id")}
        counts = {}
        for task in rows:
            session_id = task.get("session_id")
            if session_id:
                counts[session_id] = counts.get(session_id, 0) + 1

        out[bot] = {
            "followup_median_seconds": _median(gaps),
            "tasks_per_session": (len(rows) / float(len(sessions)))
                                 if sessions else None,
            # 只被問過一次就沒下文的 session。可能是任務一次就解決，
            # 也可能是使用者放棄 —— 這正是它可信度低的原因。
            "abandoned_sessions": sum(1 for n in counts.values() if n == 1),
        }
    return out


def _seconds_between(earlier, later):
    from events import _parse_iso
    try:
        return (_parse_iso(later) - _parse_iso(earlier)).total_seconds()
    except (ValueError, TypeError):
        return None


def failure_proxy(thread_map_counts, tasks):
    """開過 session 但沒產出的比例 —— 揪紅旗用，不是失敗率量測。

    thread_map.json 的 entry 在 session/new 成功後、送 prompt 之前就寫入
    （pool.rs:347-357），所以落差代表「開了 session 沒產出」。無法區分
    「失敗」與「使用者只是 @ 了一下沒下任務」，也只有 session 粒度。
    """
    with_output = {}
    for task in dedupe_tasks(tasks):
        session_id = task.get("session_id")
        if session_id:
            with_output.setdefault(task.get("bot"), set()).add(session_id)

    out = {}
    for bot in set(list(thread_map_counts) + list(with_output)):
        created = thread_map_counts.get(bot)
        produced = len(with_output.get(bot, ()))
        if created is None:
            # 沒有 thread_map 就是「不知道」，不可填 0 —— 那會被讀成沒落差。
            out[bot] = {"sessions_created": None,
                        "sessions_with_output": produced, "gap": None}
        else:
            out[bot] = {"sessions_created": created,
                        "sessions_with_output": produced,
                        "gap": max(0, created - produced)}
    return out


def data_coverage(days, collect_health):
    """報表的資料覆蓋率。缺口不可偽裝成「那天沒人用」。"""
    present = sorted(d for d in days if d and d != _UNKNOWN_DAY)
    missing = []
    expected = len(present)
    if len(present) >= 2:
        import datetime as dt
        start = dt.date.fromisoformat(present[0])
        end = dt.date.fromisoformat(present[-1])
        expected = (end - start).days + 1
        have = set(present)
        for offset in range(expected):
            day = (start + dt.timedelta(days=offset)).isoformat()
            if day not in have:
                missing.append(day)

    unparsable = 0
    for stats in (collect_health.get("bots") or {}).values():
        unparsable += stats.get("unparsable", 0)

    return {
        "days_expected": expected,
        "days_present": len(present),
        "missing_days": missing,
        "unparsable": unparsable,
        "unrecognised": list(collect_health.get("unrecognised") or []),
    }
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 128 個測試（`Ran 128 tests`）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/usage-stats/aggregate.py \
        deployment-guides/k3s/usage-stats/tests/test_aggregate_quality.py
git commit -m "feat(usage-stats): 摩擦指標、thread_map 落差代理、資料覆蓋率"
```

---

### Task 10: `report.py` —— 使用者 CLI 與 text／markdown 輸出

**Files:**
- Create: `deployment-guides/k3s/usage-stats/report.py`
- Create: `deployment-guides/k3s/usage-stats/config.example.json`
- Test: `deployment-guides/k3s/usage-stats/tests/test_report.py`

**Interfaces:**
- Consumes: `events.read_events`、`aggregate` 的全部公開函式
- Produces:
  - `DEFAULT_CONFIG = {"channel_names": {}, "allowlist_bounds": {}, "pricebook": {}}`
  - `load_config(path: str | None) -> dict`
  - `load_events(events_dir: str, since: str, until: str) -> tuple` —
    `(tasks, usages)`
  - `build_report(tasks, usages, config, since, until, collect_health) -> dict`
  - `render_text(report: dict) -> str`
  - `render_md(report: dict) -> str`
  - `main(argv: list) -> int`

**`build_report` 回傳的資料模型**（Task 11 的 HTML renderer 也吃這個，所以欄位名
在這裡定案）：

```python
{
  "since": "2026-09-01", "until": "2026-09-10", "timezone": "Asia/Taipei",
  "coverage": {...},              # aggregate.data_coverage
  "daily_tasks": {...},           # aggregate.daily_task_counts
  "daily_conversations": {...},   # aggregate.daily_conversations
  "token_rows": [                 # tuple key 攤平成 list，兩個 renderer 好用
    {"day": str, "bot": str, "model_id": str, "model_variant": str|None,
     "tokens": {kind: int}},
  ],
  "daily_cost": {...},            # aggregate.daily_cost
  "active_users": {...},          # aggregate.active_users
  "attribution": {...},           # aggregate.session_attribution
  "friction": {...},              # aggregate.friction_signals
  "failure_proxy": {...},         # aggregate.failure_proxy
  "allowlist_bounds": {bot: int|None},
}
```

- [ ] **Step 1: 寫失敗的測試**

`tests/test_report.py`：

```python
"""report.py 的測試：日期篩選、報表資料模型、兩種文字輸出。

報表最重要的責任不是好看，而是**不讓讀者誤解數字**：缺口不能偽裝成
「沒人用」、allowlist 上界要標出來、摩擦指標不能寫成滿意度。
"""
import json
import os
import re
import tempfile
import unittest

from report import (
    build_report, load_config, load_events, main, render_md, render_text,
)


def task_event(day, bot="rick", source="human", dedup_key=None,
               sender_id="824", session_id="s1"):
    return {"schema": "openab.stats.task.v1", "bot": bot, "source": source,
            "dedup_key": dedup_key or ("discord:%s-%s" % (bot, day)),
            "sender_id": sender_id, "display_name": "william",
            "session_id": session_id, "occurred_at": day + "T06:00:00Z"}


def usage_event(day, bot="rick", model="claude-opus-5", variant=None,
                tokens=None, cost=None, cost_source="subscription",
                key=None, session_id="s1"):
    return {"schema": "openab.stats.usage.v1", "bot": bot,
            "usage_key": key or ("k-%s-%s" % (bot, day)),
            "model_id": model, "model_variant": variant,
            "tokens": {"input": 10, "output": 20} if tokens is None else tokens,
            "cost": cost, "cost_source": cost_source,
            "session_id": session_id, "occurred_at": day + "T06:05:00Z"}


def write_events_dir(root, tasks_by_day, usages_by_day):
    ev = os.path.join(root, "events")
    os.makedirs(ev)
    for day, rows in tasks_by_day.items():
        with open(os.path.join(ev, "task-%s.jsonl" % day), "w") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for day, rows in usages_by_day.items():
        with open(os.path.join(ev, "usage-%s.jsonl" % day), "w") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return root


class TestLoadConfig(unittest.TestCase):
    def test_missing_path_returns_defaults(self):
        cfg = load_config(None)
        self.assertEqual(cfg["channel_names"], {})
        self.assertEqual(cfg["allowlist_bounds"], {})

    def test_reads_json_and_merges_over_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            with open(p, "w") as fh:
                json.dump({"channel_names": {"c1": "cac-dev-team"}}, fh)
            cfg = load_config(p)
            self.assertEqual(cfg["channel_names"]["c1"], "cac-dev-team")
            self.assertEqual(cfg["pricebook"], {})

    def test_unreadable_config_raises_rather_than_silently_defaulting(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.json")
            with open(p, "w") as fh:
                fh.write("{not json")
            with self.assertRaises(ValueError):
                load_config(p)


class TestLoadEvents(unittest.TestCase):
    def test_only_loads_days_in_range(self):
        with tempfile.TemporaryDirectory() as d:
            root = write_events_dir(
                d,
                {"2026-09-08": [task_event("2026-09-08")],
                 "2026-09-09": [task_event("2026-09-09")],
                 "2026-09-10": [task_event("2026-09-10")]},
                {})
            tasks, _ = load_events(os.path.join(root, "events"),
                                   "2026-09-09", "2026-09-10")
            self.assertEqual(len(tasks), 2)

    def test_includes_unknown_bucket_so_it_is_never_lost(self):
        with tempfile.TemporaryDirectory() as d:
            root = write_events_dir(d, {"unknown": [task_event("2026-09-09")]}, {})
            tasks, _ = load_events(os.path.join(root, "events"),
                                   "2026-09-01", "2026-09-30")
            self.assertEqual(len(tasks), 1)

    def test_empty_dir_returns_two_empty_lists(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_events(d, "2026-09-01", "2026-09-30"), ([], []))


class TestBuildReport(unittest.TestCase):
    def _report(self, tasks=None, usages=None, config=None, health=None):
        return build_report(tasks or [], usages or [], config or load_config(None),
                            "2026-09-09", "2026-09-10", health or {})

    def test_flattens_token_tuple_keys_into_rows(self):
        rep = self._report(usages=[usage_event("2026-09-10", model="x",
                                               variant="low")])
        self.assertEqual(len(rep["token_rows"]), 1)
        row = rep["token_rows"][0]
        self.assertEqual((row["model_id"], row["model_variant"]), ("x", "low"))
        self.assertEqual(row["day"], "2026-09-10")

    def test_states_timezone_explicitly(self):
        self.assertEqual(self._report()["timezone"], "Asia/Taipei")

    def test_carries_allowlist_bounds_from_config(self):
        cfg = load_config(None)
        cfg["allowlist_bounds"] = {"rick": 1}
        rep = self._report(tasks=[task_event("2026-09-10")], config=cfg)
        self.assertEqual(rep["allowlist_bounds"]["rick"], 1)

    def test_reports_missing_days_in_coverage(self):
        rep = self._report(tasks=[task_event("2026-09-08"),
                                  task_event("2026-09-10")])
        self.assertIn("2026-09-09", rep["coverage"]["missing_days"])

    def test_includes_all_six_metric_sections(self):
        rep = self._report()
        for key in ("daily_tasks", "daily_conversations", "token_rows",
                    "daily_cost", "active_users", "attribution", "friction",
                    "failure_proxy"):
            self.assertIn(key, rep)


class TestRenderText(unittest.TestCase):
    def _rendered(self, **kw):
        rep = build_report(kw.get("tasks", []), kw.get("usages", []),
                           kw.get("config", load_config(None)),
                           "2026-09-09", "2026-09-10", kw.get("health", {}))
        return render_text(rep)

    def test_never_labels_a_metric_as_satisfaction(self):
        # 章節標題「[摩擦指標] 不是滿意度」本身含「滿意度」，那是想要的否定
        # 語境。真正的需求是：每一次出現「滿意」都必須緊接在「不是」之後。
        out = self._rendered(tasks=[task_event("2026-09-10")])
        self.assertIn("摩擦指標", out)
        for match in re.finditer("滿意", out):
            self.assertEqual(out[max(0, match.start() - 2):match.start()],
                             "不是", "「滿意」出現在非否定語境")

    def test_states_that_task_counts_exclude_failures(self):
        out = self._rendered(tasks=[task_event("2026-09-10")])
        self.assertIn("僅含成功", out)

    def test_shows_timezone_in_header(self):
        self.assertIn("Asia/Taipei", self._rendered())

    def test_flags_allowlist_bound_so_one_user_is_not_read_as_low_adoption(self):
        cfg = load_config(None)
        cfg["allowlist_bounds"] = {"rick": 1}
        out = self._rendered(tasks=[task_event("2026-09-10")], config=cfg)
        self.assertIn("allowlist", out)

    def test_warns_about_missing_days(self):
        out = self._rendered(tasks=[task_event("2026-09-08"),
                                    task_event("2026-09-10")])
        self.assertIn("2026-09-09", out)

    def test_notes_that_daily_conversation_sums_exceed_reality(self):
        out = self._rendered(tasks=[task_event("2026-09-10")])
        self.assertIn("逐日加總", out)

    def test_resolves_channel_names_when_configured(self):
        cfg = load_config(None)
        cfg["channel_names"] = {"c1": "cac-dev-team"}
        rep = build_report([task_event("2026-09-10")], [], cfg,
                           "2026-09-09", "2026-09-10", {})
        self.assertEqual(rep["channel_names"]["c1"], "cac-dev-team")


class TestRenderMd(unittest.TestCase):
    def test_produces_markdown_tables(self):
        rep = build_report([task_event("2026-09-10")], [], load_config(None),
                           "2026-09-09", "2026-09-10", {})
        out = render_md(rep)
        self.assertIn("| ", out)
        self.assertIn("# ", out)

    def test_separates_cost_sources_and_marks_subscription(self):
        usages = [usage_event("2026-09-10", cost=1.5, cost_source="cli"),
                  usage_event("2026-09-10", cost=None,
                              cost_source="subscription", key="k2")]
        rep = build_report([], usages, load_config(None),
                           "2026-09-09", "2026-09-10", {})
        out = render_md(rep)
        self.assertIn("訂閱制", out)
        self.assertIn("1.5", out)


class TestMain(unittest.TestCase):
    def test_writes_markdown_to_output_path(self):
        with tempfile.TemporaryDirectory() as d:
            write_events_dir(d, {"2026-09-10": [task_event("2026-09-10")]}, {})
            out = os.path.join(d, "r.md")
            rc = main(["--data", d, "--since", "2026-09-10",
                       "--until", "2026-09-10", "--format", "md", "-o", out])
            self.assertEqual(rc, 0)
            with open(out) as fh:
                self.assertIn("# ", fh.read())

    def test_bots_filter_narrows_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            write_events_dir(d, {"2026-09-10": [
                task_event("2026-09-10", bot="rick"),
                task_event("2026-09-10", bot="morty")]}, {})
            out = os.path.join(d, "r.md")
            main(["--data", d, "--since", "2026-09-10", "--until", "2026-09-10",
                  "--bots", "rick", "--format", "md", "-o", out])
            with open(out) as fh:
                body = fh.read()
            self.assertIn("rick", body)
            self.assertNotIn("morty", body)

    def test_missing_data_dir_returns_nonzero(self):
        self.assertNotEqual(
            main(["--data", "/nonexistent", "--since", "2026-09-10",
                  "--until", "2026-09-10"]), 0)

    def test_since_after_until_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            write_events_dir(d, {}, {})
            self.assertNotEqual(
                main(["--data", d, "--since", "2026-09-10",
                      "--until", "2026-09-01"]), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_report -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'report'`

- [ ] **Step 3: 寫實作**

先建 `deployment-guides/k3s/usage-stats/config.example.json`：

```json
{
  "channel_names": {
    "1528965074562191420": "cac-dev-team",
    "1528965173761802420": "cac-notify",
    "1522271475552354394": "dev-bot",
    "1526283579309690990": "bot-notify"
  },
  "allowlist_bounds": {
    "rick": 1,
    "morty": 1
  },
  "pricebook": {}
}
```

`allowlist_bounds` 是「這隻 bot 的 `allowedUsers` 有幾個人」。rick／morty 是 1
（`values-openab-claude.yaml:48`、`:100`），其餘 bot 的 `allowedUsers` 為空所以不列。
`pricebook` 留空：opencode 三隻的成本由 CLI 自算，Claude 家族走訂閱制不換算金額。

再建 `deployment-guides/k3s/usage-stats/report.py`：

```python
#!/usr/bin/env python3
"""報表 CLI —— 使用者手動跑，吃已累積的正規化事件，不碰原始儲存。

    report.py --since 2026-09-01 --until 2026-09-10
    report.py --since 2026-09-01 --bots rick,morty
    report.py --since 2026-09-01 --format md   -o report.md
    report.py --since 2026-09-01 --format html -o report.html

因為不碰原始儲存，所以可以重跑、可以改指標定義後重算歷史 —— 原始資料可能
已經被 CLI 清掉了（claude-code 有 cleanupPeriodDays，預設 30 天）。
"""
import argparse
import datetime as dt
import json
import os
import sys

import aggregate
from events import read_events

DEFAULT_CONFIG = {"channel_names": {}, "allowlist_bounds": {}, "pricebook": {}}

_TZ_NAME = "Asia/Taipei"


def load_config(path):
    """讀 JSON 設定並疊在預設值上。壞掉的設定檔要拋錯不可靜默用預設值。"""
    config = dict(DEFAULT_CONFIG)
    if not path:
        return config
    with open(path, encoding="utf-8") as fh:
        try:
            loaded = json.load(fh)
        except ValueError as exc:
            raise ValueError("設定檔 %s 解析失敗: %s" % (path, exc))
    config.update(loaded)
    return config


def _days_between(since, until):
    start = dt.date.fromisoformat(since)
    end = dt.date.fromisoformat(until)
    out = []
    while start <= end:
        out.append(start.isoformat())
        start += dt.timedelta(days=1)
    return out


def load_events(events_dir, since, until):
    """讀指定日期範圍的事件檔。unknown 桶一律納入 —— 絕不遺失。"""
    days = _days_between(since, until) + ["unknown"]
    task_paths = [os.path.join(events_dir, "task-%s.jsonl" % d) for d in days]
    usage_paths = [os.path.join(events_dir, "usage-%s.jsonl" % d) for d in days]
    return list(read_events(task_paths)), list(read_events(usage_paths))


def _thread_map_counts(data_dir):
    """收集階段留下的 thread_map 計數（失敗率代理用）。缺檔就是不知道。"""
    path = os.path.join(data_dir, "thread-map-counts.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def build_report(tasks, usages, config, since, until, collect_health,
                 thread_map_counts=None):
    token_rows = []
    for day, bots in sorted(aggregate.daily_tokens(usages).items()):
        for bot, models in sorted(bots.items()):
            for (model_id, variant), tokens in sorted(
                    models.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
                token_rows.append({"day": day, "bot": bot, "model_id": model_id,
                                   "model_variant": variant, "tokens": tokens})

    days_seen = sorted({r["day"] for r in token_rows}
                       | set(aggregate.daily_task_counts(tasks)))
    return {
        "since": since, "until": until, "timezone": _TZ_NAME,
        "coverage": aggregate.data_coverage(days_seen, collect_health),
        "daily_tasks": aggregate.daily_task_counts(tasks),
        "daily_conversations": aggregate.daily_conversations(tasks),
        "token_rows": token_rows,
        "daily_cost": aggregate.daily_cost(usages),
        "active_users": aggregate.active_users(tasks),
        "attribution": aggregate.session_attribution(tasks, usages),
        "friction": aggregate.friction_signals(tasks),
        "failure_proxy": aggregate.failure_proxy(thread_map_counts or {}, tasks),
        "allowlist_bounds": dict(config.get("allowlist_bounds") or {}),
        "channel_names": dict(config.get("channel_names") or {}),
    }


# --- 共同的敘述文字：兩個文字 renderer 與 HTML renderer 都用同一套措辭，
#     避免同一個限制在不同輸出裡講得不一樣。
CAVEATS = (
    "任務數**僅含成功的任務** —— 失敗的 turn 不會在 transcript 裡留下痕跡，"
    "錯誤只丟給聊天平台。",
    "對話數的「有活動」跨日會重複計入（session TTL 24 小時），"
    "所以**逐日加總會大於實際對話數**。",
    "摩擦指標**不是滿意度量測**，兩個訊號都弱，只能看趨勢不能當結論。",
    "「誰在燒量」歸因到 session 層；多人共用的 session 記為 shared 不強行拆分，"
    "覆蓋率請看歸因區塊。",
)


def _caveat_lines(report):
    lines = list(CAVEATS)
    bounds = report.get("allowlist_bounds") or {}
    if bounds:
        listed = "、".join("%s 上界 %d 人" % (bot, n)
                          for bot, n in sorted(bounds.items()))
        lines.append(
            "以下 bot 受 allowlist 限制，活躍人數的上界就是設定值（%s）——"
            "看到 1 不代表沒人想用。" % listed)
    missing = (report.get("coverage") or {}).get("missing_days") or []
    if missing:
        lines.append("**資料缺口**：%s 沒有任何事件，缺口不等於「那天沒人用」。"
                     % "、".join(missing))
    unparsable = (report.get("coverage") or {}).get("unparsable") or 0
    if unparsable:
        lines.append("收集時有 %d 筆紀錄無法解析（可能是 CLI 升版改了格式）。"
                     % unparsable)
    return lines


def render_text(report):
    out = []
    out.append("openab bot 使用統計  %s ~ %s  （時區 %s）"
               % (report["since"], report["until"], report["timezone"]))
    out.append("=" * 64)

    out.append("\n[每日任務數]  真人 / bot 互呼 / cron 排程")
    for day, bots in sorted(report["daily_tasks"].items()):
        for bot, counts in sorted(bots.items()):
            out.append("  %s  %-8s  %4d / %4d / %4d"
                       % (day, bot, counts["human"], counts["bot_relay"],
                          counts["cron"]))

    out.append("\n[每日對話數]  新開 / 延續")
    for day, bots in sorted(report["daily_conversations"].items()):
        for bot, counts in sorted(bots.items()):
            out.append("  %s  %-8s  %4d / %4d"
                       % (day, bot, counts["new"], counts["continued"]))

    out.append("\n[Token 用量]  bot / model (variant)")
    for row in report["token_rows"]:
        kinds = ", ".join("%s=%d" % (k, v) for k, v in sorted(row["tokens"].items()))
        model = row["model_id"] or "(未知)"
        if row["model_variant"]:
            model += " (%s)" % row["model_variant"]
        out.append("  %s  %-8s  %-36s %s" % (row["day"], row["bot"], model, kinds))

    out.append("\n[成本]  依來源分開，不可混加")
    for day, bots in sorted(report["daily_cost"].items()):
        for bot, sources in sorted(bots.items()):
            out.append("  %s  %-8s  CLI 自算 %.4f  價目表 %.4f  "
                       "訂閱制（不計金額）  無成本資料"
                       % (day, bot, sources["cli"], sources["pricebook"]))

    out.append("\n[活躍觸發者]  依 sender_id 聚合，名稱取最近一次")
    for bot, users in sorted(report["active_users"].items()):
        bound = report["allowlist_bounds"].get(bot)
        suffix = ("  ※ 受 allowlist 限制，上界 %d 人" % bound) if bound else ""
        out.append("  %-8s  %d 人%s" % (bot, len(users), suffix))
        for sender_id, info in sorted(users.items(),
                                      key=lambda kv: -kv[1]["tasks"]):
            out.append("      %-24s %4d 個任務"
                       % (info["display_name"] or sender_id, info["tasks"]))

    out.append("\n[Token 歸因]  誰在燒量（session 層，估計值）")
    for bot, info in sorted(report["attribution"].items()):
        out.append("  %-8s  無歧義歸因覆蓋率 %.0f%%" % (bot, info["coverage"] * 100))

    out.append("\n[摩擦指標]  不是滿意度")
    for bot, info in sorted(report["friction"].items()):
        median = info["followup_median_seconds"]
        out.append("  %-8s  追問間隔中位數 %s  每 session 任務數 %s  "
                   "只問一次就沒下文 %d"
                   % (bot,
                      ("%.0f 秒" % median) if median is not None else "n/a",
                      ("%.2f" % info["tasks_per_session"])
                      if info["tasks_per_session"] is not None else "n/a",
                      info["abandoned_sessions"]))

    out.append("\n[開了 session 沒產出]  紅旗指標，不是失敗率")
    for bot, info in sorted(report["failure_proxy"].items()):
        created = info["sessions_created"]
        out.append("  %-8s  建立 %s  產出 %d  落差 %s"
                   % (bot, created if created is not None else "未知",
                      info["sessions_with_output"],
                      info["gap"] if info["gap"] is not None else "未知"))

    out.append("\n[讀這份報表前必須知道]")
    for line in _caveat_lines(report):
        out.append("  - " + line.replace("**", ""))
    return "\n".join(out) + "\n"


def render_md(report):
    out = []
    out.append("# openab bot 使用統計")
    out.append("")
    out.append("- 範圍：%s ~ %s" % (report["since"], report["until"]))
    out.append("- 時區：%s" % report["timezone"])
    out.append("")
    out.append("## 讀這份報表前必須知道")
    out.append("")
    for line in _caveat_lines(report):
        out.append("- " + line)

    out.append("")
    out.append("## 每日任務數")
    out.append("")
    out.append("| 日期 | bot | 真人 | bot 互呼 | cron 排程 |")
    out.append("| --- | --- | --- | --- | --- |")
    for day, bots in sorted(report["daily_tasks"].items()):
        for bot, c in sorted(bots.items()):
            out.append("| %s | %s | %d | %d | %d |"
                       % (day, bot, c["human"], c["bot_relay"], c["cron"]))

    out.append("")
    out.append("## 每日對話數")
    out.append("")
    out.append("| 日期 | bot | 新開 | 延續 |")
    out.append("| --- | --- | --- | --- |")
    for day, bots in sorted(report["daily_conversations"].items()):
        for bot, c in sorted(bots.items()):
            out.append("| %s | %s | %d | %d |" % (day, bot, c["new"], c["continued"]))

    out.append("")
    out.append("## Token 用量")
    out.append("")
    out.append("| 日期 | bot | model | variant | 明細 |")
    out.append("| --- | --- | --- | --- | --- |")
    for row in report["token_rows"]:
        kinds = ", ".join("%s=%d" % (k, v) for k, v in sorted(row["tokens"].items()))
        out.append("| %s | %s | %s | %s | %s |"
                   % (row["day"], row["bot"], row["model_id"] or "(未知)",
                      row["model_variant"] or "—", kinds))

    out.append("")
    out.append("## 成本")
    out.append("")
    out.append("依來源分開列示，**不可混加**：`cli` 是 opencode 自算的實際費用、"
               "`pricebook` 是價目表推算、**訂閱制的 token 數不等於帳單金額**、"
               "`unavailable` 是有 token 但拿不到成本。")
    out.append("")
    out.append("| 日期 | bot | CLI 自算 | 價目表 |")
    out.append("| --- | --- | --- | --- |")
    for day, bots in sorted(report["daily_cost"].items()):
        for bot, s in sorted(bots.items()):
            out.append("| %s | %s | %.4f | %.4f |"
                       % (day, bot, s["cli"], s["pricebook"]))

    out.append("")
    out.append("## 活躍觸發者")
    out.append("")
    out.append("| bot | 人數 | 備註 |")
    out.append("| --- | --- | --- |")
    for bot, users in sorted(report["active_users"].items()):
        bound = report["allowlist_bounds"].get(bot)
        note = ("受 allowlist 限制，上界 %d 人" % bound) if bound else "—"
        out.append("| %s | %d | %s |" % (bot, len(users), note))

    out.append("")
    out.append("## 摩擦指標（不是滿意度）")
    out.append("")
    out.append("| bot | 追問間隔中位數（秒） | 每 session 任務數 | 只問一次就沒下文 |")
    out.append("| --- | --- | --- | --- |")
    for bot, info in sorted(report["friction"].items()):
        median = info["followup_median_seconds"]
        per = info["tasks_per_session"]
        out.append("| %s | %s | %s | %d |"
                   % (bot, ("%.0f" % median) if median is not None else "n/a",
                      ("%.2f" % per) if per is not None else "n/a",
                      info["abandoned_sessions"]))
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="openab 使用統計報表")
    parser.add_argument("--data", required=True,
                        help="collect.py 的輸出目錄（內含 events/）")
    parser.add_argument("--since", required=True, help="起日 YYYY-MM-DD")
    parser.add_argument("--until", required=True, help="迄日 YYYY-MM-DD")
    parser.add_argument("--bots", default="", help="只看這些 bot（逗號分隔）")
    parser.add_argument("--format", default="text",
                        choices=("text", "md", "html"))
    parser.add_argument("--config", default=None, help="config.json 路徑")
    parser.add_argument("-o", "--output", default=None, help="輸出檔，預設 stdout")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.data):
        print("錯誤：%s 不存在" % args.data, file=sys.stderr)
        return 1
    try:
        if dt.date.fromisoformat(args.since) > dt.date.fromisoformat(args.until):
            print("錯誤：--since 晚於 --until", file=sys.stderr)
            return 1
    except ValueError as exc:
        print("錯誤：日期格式不對 —— %s" % exc, file=sys.stderr)
        return 1

    config = load_config(args.config)
    tasks, usages = load_events(os.path.join(args.data, "events"),
                                args.since, args.until)
    wanted = [b.strip() for b in args.bots.split(",") if b.strip()]
    if wanted:
        tasks = [t for t in tasks if t.get("bot") in wanted]
        usages = [u for u in usages if u.get("bot") in wanted]

    health = {}
    health_path = os.path.join(args.data, "collect-health.json")
    if os.path.isfile(health_path):
        with open(health_path, encoding="utf-8") as fh:
            try:
                health = json.load(fh)
            except ValueError:
                health = {}

    report = build_report(tasks, usages, config, args.since, args.until,
                          health, _thread_map_counts(args.data))

    if args.format == "html":
        import render_html
        body = render_html.render(report)
    elif args.format == "md":
        body = render_md(report)
    else:
        body = render_text(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(body)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 152 個測試（`Ran 152 tests`）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/usage-stats/report.py \
        deployment-guides/k3s/usage-stats/config.example.json \
        deployment-guides/k3s/usage-stats/tests/test_report.py
git commit -m "feat(usage-stats): report.py —— CLI 與 text/md 輸出，報表自帶限制說明"
```

---

### Task 11: `render_html.py` —— 自帶資源的單一 HTML 與 inline SVG 圖表

**Files:**
- Create: `deployment-guides/k3s/usage-stats/render_html.py`
- Test: `deployment-guides/k3s/usage-stats/tests/test_render_html.py`

**Interfaces:**
- Consumes: Task 10 的 `build_report` 回傳的 report dict
- Produces:
  - `SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a")`
  - `SERIES_DARK = ("#3987e5", "#d95926", "#199e70")`
  - `rounded_top_path(x, y, w, h, r) -> str` — 頂端圓角的 SVG path `d`
  - `stack_geometry(days, series, width, height) -> list` —
    `[{"day", "key", "value", "x", "y", "w", "h", "top"}]`
  - `hbar_geometry(rows, width, height) -> list` —
    `[{"label", "value", "x", "y", "w", "h"}]`
  - `svg_stacked(days, series, labels, title) -> str`
  - `svg_hbars(rows, title) -> str`
  - `render(report: dict) -> str` — 完整 HTML

**圖表設計依據（dataviz skill 的程序，逐條記錄以免日後被「順手改漂亮」破壞）：**

1. **形式**：每日任務數與每日對話數都是「隨時間的組成」→ 堆疊柱狀；model token
   佔比的類別名稱很長（`moonshotai/kimi-k2.7-code`）→ 橫條。
2. **色彩**：三者都是 categorical（identity），用固定順序的前三個 slot，**不循環
   配色**。
3. **調色盤已跑驗證器**（`dataviz` skill 的 `validate_palette.js`），兩個 mode 全部
   PASS：light `#2a78d6,#eb6834,#1baf7a`（worst adjacent CVD ΔE 9.2、normal 27.6）、
   dark `#3987e5,#d95926,#199e70`（CVD ΔE 9.4、normal 26.5）。
   **light mode 有一個不可忽略的 WARN**：aqua `#1baf7a` 對淺底對比 2.74 < 3:1，
   規則要求「可見標籤或表格檢視」補償——所以**每張圖都必須附一份表格**。
4. **標記規格**：堆疊段之間留 2px 底色間隙、最上層段頂端 4px 圓角、格線與軸線
   recessive、數值文字用文字色不用 series 色。
5. **互動層用純 SVG `<title>`**（瀏覽器原生 tooltip），**零 JavaScript**——自帶資源
   的前提下不引入任何腳本，而且 `<title>` 可以用測試斷言。
6. **無障礙**：≥2 series 一定有圖例、每張圖都有表格檢視、深色模式是**各自選過的
   色階**不是自動反轉。

**硬性限制：零外部請求。** 不連 CDN、不載外部字型、沒有 `fetch`／`<script src>`。
`open report.html` 必須完全正常。

- [ ] **Step 1: 寫失敗的測試**

`tests/test_render_html.py`：

```python
"""render_html.py 的測試。

幾何用純函數算，所以可以斷言座標 —— 這是選「程式產生 SVG」而非 JS 圖表庫的
主要理由（JS 庫渲染的結果測不到）。另外鎖住「零外部請求」與「每張圖都有表格」。
"""
import re
import unittest

from render_html import (
    SERIES_DARK, SERIES_LIGHT, hbar_geometry, render, rounded_top_path,
    stack_geometry, svg_hbars, svg_stacked,
)


def report_fixture():
    return {
        "since": "2026-09-09", "until": "2026-09-10", "timezone": "Asia/Taipei",
        "coverage": {"days_expected": 2, "days_present": 2, "missing_days": [],
                     "unparsable": 0, "unrecognised": []},
        "daily_tasks": {
            "2026-09-09": {"rick": {"human": 2, "bot_relay": 1, "cron": 5}},
            "2026-09-10": {"rick": {"human": 3, "bot_relay": 0, "cron": 4}}},
        "daily_conversations": {
            "2026-09-09": {"rick": {"new": 1, "continued": 0}},
            "2026-09-10": {"rick": {"new": 2, "continued": 1}}},
        "token_rows": [
            {"day": "2026-09-10", "bot": "rick", "model_id": "claude-opus-5",
             "model_variant": None,
             "tokens": {"input": 100, "output": 200, "cache_read": 900}}],
        "daily_cost": {"2026-09-10": {"rick": {"cli": 1.5, "pricebook": 0.0,
                                               "subscription": 0.0,
                                               "unavailable": 0.0}}},
        "active_users": {"rick": {"824": {"display_name": "william", "tasks": 5}}},
        "attribution": {"rick": {"attributed": {"824": {"input": 100}},
                                 "shared": {}, "unattributed": {},
                                 "coverage": 1.0}},
        "friction": {"rick": {"followup_median_seconds": 120.0,
                              "tasks_per_session": 1.5,
                              "abandoned_sessions": 1}},
        "failure_proxy": {"rick": {"sessions_created": 18,
                                   "sessions_with_output": 2, "gap": 16}},
        "by_channel": {"1528965074562191420": {"human": 5, "bot_relay": 1,
                                               "cron": 9}},
        "allowlist_bounds": {"rick": 1},
        "channel_names": {"1528965074562191420": "cac-dev-team"},
    }


class TestRoundedTopPath(unittest.TestCase):
    def test_produces_rounded_top_and_square_bottom(self):
        d = rounded_top_path(10, 20, 30, 40, 4)
        self.assertTrue(d.startswith("M 10,60"))   # 左下角 = y + h
        self.assertIn("Q", d)                       # 頂端兩個圓角
        self.assertTrue(d.endswith("Z"))

    def test_radius_clamped_when_bar_is_shorter_than_radius(self):
        d = rounded_top_path(0, 0, 10, 2, 4)
        # 半徑不可大於高度的一半，否則路徑會自交
        self.assertNotIn("Q 0,-", d)


class TestStackGeometry(unittest.TestCase):
    def test_segments_stack_upward_from_baseline(self):
        days = ["2026-09-09"]
        series = {"human": {"2026-09-09": 1}, "cron": {"2026-09-09": 1}}
        geo = stack_geometry(days, series, 200, 100)
        self.assertEqual(len(geo), 2)
        lower = [g for g in geo if g["key"] == "human"][0]
        upper = [g for g in geo if g["key"] == "cron"][0]
        self.assertGreater(lower["y"], upper["y"])   # y 越小越上面

    def test_two_pixel_gap_between_stacked_segments(self):
        days = ["d1"]
        series = {"a": {"d1": 10}, "b": {"d1": 10}}
        geo = sorted(stack_geometry(days, series, 200, 100), key=lambda g: g["y"])
        upper, lower = geo[0], geo[1]
        self.assertEqual(lower["y"] - (upper["y"] + upper["h"]), 2)

    def test_only_topmost_segment_is_flagged_top(self):
        days = ["d1"]
        series = {"a": {"d1": 1}, "b": {"d1": 1}}
        geo = stack_geometry(days, series, 200, 100)
        self.assertEqual(sum(1 for g in geo if g["top"]), 1)

    def test_zero_value_segments_are_omitted_entirely(self):
        days = ["d1"]
        series = {"a": {"d1": 5}, "b": {"d1": 0}}
        geo = stack_geometry(days, series, 200, 100)
        self.assertEqual([g["key"] for g in geo], ["a"])

    def test_all_zero_day_produces_no_geometry_without_dividing_by_zero(self):
        geo = stack_geometry(["d1"], {"a": {"d1": 0}}, 200, 100)
        self.assertEqual(geo, [])

    def test_bar_width_is_capped_so_few_days_do_not_look_absurd(self):
        # 只有兩天時按比例會算出接近 200px 的柱子
        geo = stack_geometry(["d1", "d2"], {"a": {"d1": 1, "d2": 1}}, 640, 180)
        for g in geo:
            self.assertLessEqual(g["w"], 48)

    def test_bars_stay_centred_in_their_slot_after_capping(self):
        geo = stack_geometry(["d1", "d2"], {"a": {"d1": 1, "d2": 1}}, 640, 180)
        first, second = sorted(geo, key=lambda g: g["x"])
        slot = (640 - 8) / 2.0
        self.assertAlmostEqual(second["x"] - first["x"], slot, places=6)

    def test_bars_do_not_overflow_the_plot_width(self):
        days = ["d%d" % i for i in range(7)]
        series = {"a": {d: 1 for d in days}}
        geo = stack_geometry(days, series, 400, 100)
        for g in geo:
            self.assertLessEqual(g["x"] + g["w"], 400)


class TestHbarGeometry(unittest.TestCase):
    def test_widths_are_proportional_to_value(self):
        rows = [("a", 100), ("b", 50)]
        geo = hbar_geometry(rows, 400, 100)
        self.assertAlmostEqual(geo[1]["w"], geo[0]["w"] / 2.0, places=6)

    def test_zero_max_does_not_divide_by_zero(self):
        self.assertEqual(hbar_geometry([("a", 0)], 400, 100)[0]["w"], 0)


class TestSvgOutput(unittest.TestCase):
    def test_stacked_svg_has_a_title_per_mark_for_native_tooltips(self):
        svg = svg_stacked(["d1"], {"human": {"d1": 3}}, {"human": "真人"}, "測試")
        self.assertEqual(svg.count("<title>"), 1)
        self.assertIn("真人", svg)

    def test_stacked_svg_includes_a_legend_when_two_or_more_series(self):
        svg = svg_stacked(["d1"], {"a": {"d1": 1}, "b": {"d1": 1}},
                          {"a": "甲", "b": "乙"}, "測試")
        self.assertIn('class="legend"', svg)

    def test_single_series_hbars_have_no_legend_box(self):
        svg = svg_hbars([("claude-opus-5", 100)], "測試")
        self.assertNotIn('class="legend"', svg)

    def test_values_are_escaped_so_model_names_cannot_inject_markup(self):
        svg = svg_hbars([("<script>x</script>", 5)], "測試")
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)


class TestRender(unittest.TestCase):
    def setUp(self):
        self.html = render(report_fixture())

    def test_makes_no_external_requests_at_all(self):
        for bad in ("<script src", "https://", "http://", "fetch(",
                    "@import", "cdn."):
            self.assertNotIn(bad, self.html, "發現外部請求: %s" % bad)

    def test_has_no_javascript_at_all(self):
        self.assertNotIn("<script", self.html)

    def test_defines_light_palette_on_bare_root_and_dark_in_media_query(self):
        self.assertIn(":root", self.html)
        self.assertIn("prefers-color-scheme: dark", self.html)
        for hex_value in SERIES_LIGHT:
            self.assertIn(hex_value, self.html)
        for hex_value in SERIES_DARK:
            self.assertIn(hex_value, self.html)

    def test_every_chart_is_accompanied_by_a_table(self):
        # 調色盤驗證器對 light mode 的 aqua 給了對比 WARN，規則要求
        # 「可見標籤或表格檢視」補償，所以表格是硬需求不是裝飾
        self.assertEqual(self.html.count("<svg"), self.html.count("</svg>"))
        self.assertGreaterEqual(self.html.count("<table"), self.html.count("<svg"))

    def test_states_timezone_and_range(self):
        self.assertIn("Asia/Taipei", self.html)
        self.assertIn("2026-09-09", self.html)

    def test_carries_the_same_caveats_as_the_text_report(self):
        self.assertIn("僅含成功", self.html)
        self.assertIn("摩擦", self.html)
        self.assertIn("allowlist", self.html)

    def test_never_labels_a_metric_as_satisfaction(self):
        for match in re.finditer("滿意", self.html):
            self.assertEqual(self.html[max(0, match.start() - 2):match.start()],
                             "不是")

    def test_body_paints_its_own_background(self):
        self.assertIn("body", self.html)
        self.assertIn("--surface", self.html)

    def test_wide_tables_scroll_inside_their_own_container(self):
        self.assertIn("overflow-x", self.html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_render_html -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'render_html'`

- [ ] **Step 3: 寫實作**

`deployment-guides/k3s/usage-stats/render_html.py`：

```python
"""把報表資料模型算成自帶資源的單一 HTML。

**硬性限制：零外部請求。** 不連 CDN、不載外部字型、沒有 fetch 或 <script>。
`open report.html` 必須完全正常，也才能直接寄給人或發佈成網頁。

圖表是**程式產生的 inline SVG**，不用 JS 圖表庫：自帶資源的前提下 inline
一個庫動輒數百 KB，而這裡要的三種圖形產生 SVG 的程式碼更短，而且幾何是純
函數、可以斷言座標 —— JS 庫渲染的結果測不到。

互動層用 SVG 原生 <title>（瀏覽器內建 tooltip），所以零 JavaScript。

配色順序固定（categorical，不循環），已用 dataviz 的 validate_palette.js
在兩個 mode 驗過：light 最差相鄰 CVD ΔE 9.2／normal 27.6，dark 9.4／26.5。
light mode 的 aqua 對比 2.74 < 3:1 拿到 WARN，規則要求以「可見標籤或表格
檢視」補償 —— 所以**每張圖都附一份表格**，那是硬需求不是裝飾。
"""
import html as html_mod

# 前三個 categorical slot（blue／orange／aqua）。深色是各自選過的色階，
# 不是自動反轉。
SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a")
SERIES_DARK = ("#3987e5", "#d95926", "#199e70")

_PLOT_W = 640
_PLOT_H = 180
_PAD_L = 8
_PAD_B = 22
_GAP = 2          # 堆疊段之間的底色間隙
_RADIUS = 4       # 最上層段的頂端圓角
# 柱寬上限：日期數很少時（例如只查兩天）按比例算會得到接近 200px 的巨大
# 柱子，視覺上很怪。dataviz 程序第 7 步「render 出來看」抓到的。
_BAR_MAX = 48


def _esc(value):
    return html_mod.escape(str(value), quote=True)


def rounded_top_path(x, y, w, h, r):
    """頂端圓角、底端方角的 path d。用於堆疊的最上層段。"""
    r = max(0, min(r, w / 2.0, h / 2.0))
    return ("M %g,%g L %g,%g Q %g,%g %g,%g L %g,%g Q %g,%g %g,%g L %g,%g Z"
            % (x, y + h,              # 起點：左下角
               x, y + r,              # 左邊往上到圓角起點
               x, y, x + r, y,        # 左上圓角
               x + w - r, y,          # 頂邊
               x + w, y, x + w, y + r,  # 右上圓角
               x + w, y + h))         # 右邊往下回基線


def stack_geometry(days, series, width=_PLOT_W, height=_PLOT_H):
    """堆疊柱狀的幾何。回傳每一段的座標，y 越小越上面。

    值為 0 的段完全不畫（畫一條 0 高的色塊只會製造視覺雜訊），整日為 0
    也不會除以零。
    """
    if not days:
        return []
    totals = {d: sum((series[k].get(d) or 0) for k in series) for d in days}
    peak = max(totals.values()) if totals else 0
    if peak <= 0:
        return []

    plot_h = height - _PAD_B
    slot = (width - _PAD_L) / float(len(days))
    bar_w = min(_BAR_MAX, max(4.0, slot * 0.62))
    keys = list(series)

    out = []
    for index, day in enumerate(days):
        x = _PAD_L + index * slot + (slot - bar_w) / 2.0
        cursor = plot_h
        drawn = []
        for key in keys:
            value = series[key].get(day) or 0
            if value <= 0:
                continue
            h = (value / float(peak)) * (plot_h - _GAP * max(0, len(keys) - 1))
            cursor -= h
            drawn.append({"day": day, "key": key, "value": value,
                          "x": x, "y": cursor, "w": bar_w, "h": h,
                          "top": False})
            cursor -= _GAP
        if drawn:
            drawn[-1]["top"] = True
        out.extend(drawn)
    return out


def hbar_geometry(rows, width=_PLOT_W, height=_PLOT_H):
    """橫條的幾何。rows 是 [(label, value), ...]。類別名稱長時用這個形式。"""
    if not rows:
        return []
    peak = max((v for _l, v in rows), default=0)
    row_h = 22
    out = []
    for index, (label, value) in enumerate(rows):
        w = ((value / float(peak)) * (width - _PAD_L)) if peak > 0 else 0
        out.append({"label": label, "value": value, "x": _PAD_L,
                    "y": index * row_h, "w": w, "h": row_h - 6})
    return out


def _series_var(index):
    return "var(--series-%d)" % (index + 1)


def svg_stacked(days, series, labels, title):
    """堆疊柱狀。≥2 series 一定有圖例（識別絕不只靠顏色）。"""
    geo = stack_geometry(days, series)
    keys = list(series)
    colour_of = {k: _series_var(i) for i, k in enumerate(keys)}

    marks = []
    for seg in geo:
        tip = "%s ／ %s：%s" % (seg["day"], labels.get(seg["key"], seg["key"]),
                                seg["value"])
        shape = ('<path d="%s"' % rounded_top_path(
            seg["x"], seg["y"], seg["w"], seg["h"], _RADIUS)) if seg["top"] else (
            '<rect x="%g" y="%g" width="%g" height="%g"'
            % (seg["x"], seg["y"], seg["w"], seg["h"]))
        marks.append('%s fill="%s"><title>%s</title>%s'
                     % (shape, colour_of[seg["key"]], _esc(tip),
                        "</path>" if seg["top"] else "</rect>"))

    ticks = []
    slot = (_PLOT_W - _PAD_L) / float(len(days)) if days else 0
    for index, day in enumerate(days):
        ticks.append('<text class="tick" x="%g" y="%g" text-anchor="middle">%s</text>'
                     % (_PAD_L + index * slot + slot / 2.0, _PLOT_H - 6,
                        _esc(day[5:])))

    legend = ""
    if len(keys) >= 2:
        items = "".join(
            '<span class="key"><i style="background:%s"></i>%s</span>'
            % (colour_of[k], _esc(labels.get(k, k))) for k in keys)
        legend = '<div class="legend">%s</div>' % items

    return ('<figure><figcaption>%s</figcaption>%s'
            '<svg viewBox="0 0 %d %d" role="img" aria-label="%s">%s%s</svg>'
            '</figure>' % (_esc(title), legend, _PLOT_W, _PLOT_H,
                           _esc(title), "".join(marks), "".join(ticks)))


def svg_hbars(rows, title):
    """橫條。單一 series 不需要圖例 —— 標題已經說明它是什麼。"""
    geo = hbar_geometry(rows)
    height = max(_PLOT_H, len(geo) * 22)
    marks = []
    for bar in geo:
        marks.append(
            '<rect x="%g" y="%g" width="%g" height="%g" rx="%d" fill="%s">'
            '<title>%s：%s</title></rect>'
            % (bar["x"], bar["y"], bar["w"], bar["h"], _RADIUS,
               _series_var(0), _esc(bar["label"]), _esc(bar["value"])))
        marks.append('<text class="tick" x="%g" y="%g">%s</text>'
                     % (bar["x"] + 6, bar["y"] + bar["h"] - 5,
                        _esc(bar["label"])))
    return ('<figure><figcaption>%s</figcaption>'
            '<svg viewBox="0 0 %d %d" role="img" aria-label="%s">%s</svg>'
            '</figure>' % (_esc(title), _PLOT_W, height, _esc(title),
                           "".join(marks)))


def _table(headers, rows):
    head = "".join("<th>%s</th>" % _esc(h) for h in headers)
    body = "".join(
        "<tr>%s</tr>" % "".join("<td>%s</td>" % _esc(c) for c in row)
        for row in rows)
    return ('<div class="scroll"><table><thead><tr>%s</tr></thead>'
            "<tbody>%s</tbody></table></div>" % (head, body))


_CSS = """
:root {
  --surface: #fcfcfb; --panel: #ffffff; --ink: #1a1a19; --ink-2: #55534f;
  --ink-3: #86837d; --rule: #e6e4e0;
  --series-1: %s; --series-2: %s; --series-3: %s;
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface: #1a1a19; --panel: #232320; --ink: #f2f0ec; --ink-2: #b3afa8;
    --ink-3: #86837d; --rule: #33322e;
    --series-1: %s; --series-2: %s; --series-3: %s;
  }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 32px 20px; background: var(--surface);
       color: var(--ink); max-width: 900px; margin-inline: auto;
       font: 15px/1.65 ui-sans-serif, system-ui, "Helvetica Neue", sans-serif; }
h1 { font-size: 1.5rem; margin: 0 0 4px; }
h2 { font-size: 1.05rem; margin: 32px 0 10px; padding-top: 14px;
     border-top: 1px solid var(--rule); }
.meta { color: var(--ink-2); font-size: .9rem; margin: 0 0 20px; }
.caveats { background: var(--panel); border: 1px solid var(--rule);
           border-radius: 10px; padding: 14px 18px; margin: 0 0 8px; }
.caveats li { color: var(--ink-2); margin: 5px 0; }
figure { margin: 0 0 14px; }
figcaption { font-size: .85rem; color: var(--ink-2); margin-bottom: 6px; }
svg { width: 100%%; height: auto; display: block; }
.tick { font-size: 10px; fill: var(--ink-3); }
.legend { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 8px;
          font-size: .82rem; color: var(--ink-2); }
.key { display: inline-flex; align-items: center; gap: 6px; }
.key i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%%; font-size: .86rem; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--rule);
         white-space: nowrap; }
th { color: var(--ink-3); font-weight: 600; }
td { color: var(--ink); }
"""


def render(report):
    """完整 HTML。文字色一律用 ink token，不用 series 色。"""
    import report as report_mod   # 共用同一套限制措辭，避免兩邊講得不一樣

    days = sorted(set(report["daily_tasks"]) | set(report["daily_conversations"]))
    days = [d for d in days if d != "unknown"]

    task_series = {
        "human": {}, "bot_relay": {}, "cron": {},
    }
    for day, bots in report["daily_tasks"].items():
        for counts in bots.values():
            for key in task_series:
                task_series[key][day] = task_series[key].get(day, 0) + counts[key]

    conv_series = {"new": {}, "continued": {}}
    for day, bots in report["daily_conversations"].items():
        for counts in bots.values():
            for key in conv_series:
                conv_series[key][day] = conv_series[key].get(day, 0) + counts[key]

    model_totals = {}
    for row in report["token_rows"]:
        label = row["model_id"] or "(未知)"
        if row["model_variant"]:
            label += " (%s)" % row["model_variant"]
        model_totals[label] = model_totals.get(label, 0) + sum(row["tokens"].values())
    model_rows = sorted(model_totals.items(), key=lambda kv: -kv[1])

    parts = []
    parts.append("<title>openab bot 使用統計</title>")
    parts.append("<style>%s</style>" % (_CSS % (SERIES_LIGHT + SERIES_DARK)))
    parts.append("<h1>openab bot 使用統計</h1>")
    parts.append('<p class="meta">%s ~ %s ・ 時區 %s</p>'
                 % (_esc(report["since"]), _esc(report["until"]),
                    _esc(report["timezone"])))

    parts.append('<div class="caveats"><strong>讀這份報表前必須知道</strong><ul>')
    for line in report_mod._caveat_lines(report):
        parts.append("<li>%s</li>" % _esc(line.replace("**", "")))
    parts.append("</ul></div>")

    parts.append("<h2>每日任務數</h2>")
    parts.append(svg_stacked(days, task_series,
                             {"human": "真人", "bot_relay": "bot 互呼",
                              "cron": "cron 排程"}, "按來源分類的每日任務數"))
    parts.append(_table(
        ["日期", "bot", "真人", "bot 互呼", "cron 排程"],
        [[day, bot, c["human"], c["bot_relay"], c["cron"]]
         for day, bots in sorted(report["daily_tasks"].items())
         for bot, c in sorted(bots.items())]))

    parts.append("<h2>每日對話數</h2>")
    parts.append(svg_stacked(days, conv_series,
                             {"new": "新開", "continued": "延續"},
                             "每日有活動的 session"))
    parts.append(_table(
        ["日期", "bot", "新開", "延續"],
        [[day, bot, c["new"], c["continued"]]
         for day, bots in sorted(report["daily_conversations"].items())
         for bot, c in sorted(bots.items())]))

    parts.append("<h2>Token 用量（依 model）</h2>")
    parts.append(svg_hbars(model_rows, "各 model 的 token 總量"))
    parts.append(_table(
        ["日期", "bot", "model", "variant", "明細"],
        [[row["day"], row["bot"], row["model_id"] or "(未知)",
          row["model_variant"] or "—",
          ", ".join("%s=%d" % (k, v) for k, v in sorted(row["tokens"].items()))]
         for row in report["token_rows"]]))

    parts.append("<h2>活躍觸發者</h2>")
    parts.append(_table(
        ["bot", "人數", "備註"],
        [[bot, len(users),
          ("受 allowlist 限制，上界 %d 人" % report["allowlist_bounds"][bot])
          if report["allowlist_bounds"].get(bot) else "—"]
         for bot, users in sorted(report["active_users"].items())]))

    parts.append("<h2>摩擦指標（不是滿意度）</h2>")
    parts.append(_table(
        ["bot", "追問間隔中位數（秒）", "每 session 任務數", "只問一次就沒下文"],
        [[bot,
          "%.0f" % info["followup_median_seconds"]
          if info["followup_median_seconds"] is not None else "n/a",
          "%.2f" % info["tasks_per_session"]
          if info["tasks_per_session"] is not None else "n/a",
          info["abandoned_sessions"]]
         for bot, info in sorted(report["friction"].items())]))

    parts.append("<h2>開了 session 沒產出（紅旗，不是失敗率）</h2>")
    parts.append(_table(
        ["bot", "建立 session", "有產出", "落差"],
        [[bot,
          info["sessions_created"] if info["sessions_created"] is not None else "未知",
          info["sessions_with_output"],
          info["gap"] if info["gap"] is not None else "未知"]
         for bot, info in sorted(report["failure_proxy"].items())]))

    return "\n".join(parts)
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 177 個測試（`Ran 177 tests`）

- [ ] **Step 5: 產一份真實 HTML 用瀏覽器看過**

dataviz 的程序第 7 步：驗證器只查顏色不查版面，必須實際打開看有沒有標籤重疊、
幾何錯位、溢出。

```bash
cd deployment-guides/k3s/usage-stats
python3 -c "
import json, render_html
from tests.test_render_html import report_fixture
open('/tmp/openab-stats-preview.html','w').write(render_html.render(report_fixture()))
print('已寫出 /tmp/openab-stats-preview.html')
"
open /tmp/openab-stats-preview.html   # Linux 用 xdg-open
```

確認：日期標籤沒重疊、堆疊段之間看得到 2px 間隙、最上層段頂端是圓角、
表格在窄視窗會自己橫向滾動而不是把頁面撐寬、切換系統深淺色兩邊都正常。

- [ ] **Step 6: Commit**

```bash
git add deployment-guides/k3s/usage-stats/render_html.py \
        deployment-guides/k3s/usage-stats/tests/test_render_html.py
git commit -m "feat(usage-stats): render_html.py —— 自帶資源單一 HTML，程式產生 inline SVG"
```

---

### Task 12: 部署 —— CronJob、thread_map 計數、文件

**Files:**
- Create: `deployment-guides/k3s/usage-stats/cronjob.yaml`
- Create: `deployment-guides/k3s/usage-stats/README.md`
- Modify: `deployment-guides/k3s/usage-stats/collect.py`（加 thread_map 計數輸出）
- Modify: `deployment-guides/k3s/README.md`（檔案表加一列 + 指到新 README）
- Modify: `deployment-guides/K3S.md`（靜態 PV 與 CronJob 的部署步驟）
- Test: `deployment-guides/k3s/usage-stats/tests/test_collect_thread_map.py`

**部署決策與理由：**

- **image 用公開的 `python:3.12-slim`**，不用先例 `jira-grill-poller` 的
  `ghcr.io/104corp/openab`。理由：收集器只讀檔，不需要 openab 的任何工具，而那批
  image 有沒有 python3 是未知的（`poller.sh` 刻意用 `node -e` 而不是 `jq`，因為
  「這批 image 沒裝 jq」）。公開 image 也不需要 `imagePullSecrets`。
  **若叢集拉不到公開 image**，退回 openab image 並先在裡面確認
  `python3 --version`；三個腳本只用標準庫，任何 3.8+ 都能跑。
- **腳本走 ConfigMap 掛載**，沿用 `jira-grill-poller` 的形式（`defaultMode: 0755`）。
- **原始資料用 `hostPath` 唯讀掛**。PV 是 `local` 型、`nodeAffinity` 全部釘在節點
  `openab`（`K3S.md` 第 2 步），所以一個 Pod 就看得到全部七隻，不需要去搶
  `ReadWriteOnce` 的 PVC。
- **輸出寫獨立 PVC**（`usage-stats-data`），**不可**寫回 agent 的 PVC——避免污染
  agent 的 HOME，也避免收集器持有 agent 家目錄的寫入權限。
- **每天跑一次就夠**（`schedule: "20 3 * * *"`，台北時間清晨），因為收集是增量的、
  水位持久化。

- [ ] **Step 1: 寫失敗的測試（thread_map 計數）**

失敗率代理需要 `thread_map.json` 的 entry 數，那要在收集階段記下來——報表階段
讀不到 agent 的 HOME。`tests/test_collect_thread_map.py`：

```python
"""collect.py 要把 thread_map 的 entry 數存下來給失敗率代理用。

報表階段只讀事件檔、碰不到 agent 的 HOME，所以這個計數必須在收集時記錄。
"""
import json
import os
import tempfile
import unittest

from collect import count_thread_map, main
from tests.test_collect import make_claude_home, user_record


class TestCountThreadMap(unittest.TestCase):
    def test_counts_persisted_entries(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".openab"))
            with open(os.path.join(d, ".openab", "thread_map.json"), "w") as fh:
                json.dump({"persisted": {"discord:a": "1", "discord:b": "2"}}, fh)
            self.assertEqual(count_thread_map(d), 2)

    def test_missing_file_returns_none_not_zero(self):
        # 「不知道」與「沒有落差」必須可區分
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(count_thread_map(d))

    def test_broken_json_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".openab"))
            with open(os.path.join(d, ".openab", "thread_map.json"), "w") as fh:
                fh.write("{broken")
            self.assertIsNone(count_thread_map(d))

    def test_flat_mapping_without_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".openab"))
            with open(os.path.join(d, ".openab", "thread_map.json"), "w") as fh:
                json.dump({"discord:a": "1"}, fh)
            self.assertEqual(count_thread_map(d), 1)


class TestMainWritesCounts(unittest.TestCase):
    def test_writes_thread_map_counts_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "data")
            os.makedirs(root)
            make_claude_home(root, "rick",
                             [user_record("m1", "2026-09-10T06:32:10Z")])
            out = os.path.join(tmp, "out")
            self.assertEqual(main(["--root", root, "--out", out]), 0)
            with open(os.path.join(out, "thread-map-counts.json")) as fh:
                counts = json.load(fh)
            self.assertEqual(counts["rick"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_collect_thread_map -v
```

Expected: FAIL — `ImportError: cannot import name 'count_thread_map' from 'collect'`

- [ ] **Step 3: 在 `collect.py` 加 `count_thread_map` 並在 `main` 輸出**

在 `collect.py` 的 `detect_cli` 之後加：

```python
def count_thread_map(home):
    """thread_map.json 的 entry 數 —— 失敗率代理的分母。

    這個計數必須在收集階段記下來：報表階段只讀事件檔、碰不到 agent 的
    HOME。讀不到時回 None 而不是 0 —— 「不知道」與「沒有落差」必須可區分。
    """
    path = os.path.join(home, ".openab", "thread_map.json")
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None
    inner = raw if isinstance(raw, dict) else {}
    for wrapper in ("persisted", "threads", "mapping"):
        if isinstance(inner.get(wrapper), dict):
            inner = inner[wrapper]
            break
    return len(inner)
```

然後在 `main` 裡：`health = {...}` 那行下面加 `tm_counts = {}`；在成功處理完一隻
bot 之後（`marks[bot] = result.watermark` 那行下面）加：

```python
        count = count_thread_map(home)
        if count is not None:
            tm_counts[bot] = count
```

並在寫 `collect-health.json` 之後加：

```python
    with open(os.path.join(args.out, "thread-map-counts.json"), "w",
              encoding="utf-8") as fh:
        json.dump(tm_counts, fh, ensure_ascii=False, indent=2, sort_keys=True)
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 182 個測試（`Ran 182 tests`）

- [ ] **Step 5: 寫 `cronjob.yaml`**

`deployment-guides/k3s/usage-stats/cronjob.yaml`：

```yaml
# openab 使用統計收集器。**只收集不產報表** —— 報表由使用者手動跑 report.py。
#
# 分開的理由是原始資料會被 CLI 清掉（claude-code 有 cleanupPeriodDays，預設
# 30 天），錯過即永久遺失，所以收集必須定期跑；報表隨時可以重跑。
#
# 部署前置：
#   1. 建 PVC 用的靜態 PV（見 K3S.md「使用統計 CronJob」一節）
#   2. kubectl create configmap usage-stats-scripts -n cac \
#        --from-file=events.py --from-file=sender_context.py \
#        --from-file=parse_claude_code.py --from-file=parse_codex.py \
#        --from-file=parse_opencode.py --from-file=collect.py
#      （腳本改了要重建 configmap；只用標準庫所以不需要裝任何東西）
#   3. kubectl apply -f cronjob.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: usage-stats-data
  namespace: cac
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: cac-local
  resources:
    requests:
      storage: 5Gi
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: usage-stats-collect
  namespace: cac
spec:
  # 台北清晨跑。收集是增量的（水位持久化），一天一次就夠。
  schedule: "20 3 * * *"
  timeZone: "Asia/Taipei"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 1
      template:
        spec:
          restartPolicy: Never
          # PV 是 local 型、nodeAffinity 全部釘在這個節點，所以收集器也必須
          # 排在同一節點才看得到 /data/william/openab。
          nodeSelector:
            kubernetes.io/hostname: openab
          securityContext:
            runAsUser: 0 # /data/william/... 是 root-only
          containers:
            - name: collect
              # 公開 image：收集器只讀檔，不需要 openab 的任何工具，也不需要
              # imagePullSecrets。三個腳本只用標準庫。若叢集拉不到公開 image，
              # 改用 ghcr.io/104corp/openab 並先確認裡面有 python3。
              image: "python:3.12-slim"
              command:
                - python3
                - /scripts/collect.py
                - --root
                - /agents
                - --out
                - /out
              volumeMounts:
                - name: scripts
                  mountPath: /scripts
                - name: agents
                  mountPath: /agents
                  readOnly: true # 唯讀：絕不寫入 agent 的 HOME
                - name: out
                  mountPath: /out
          volumes:
            - name: scripts
              configMap:
                name: usage-stats-scripts
                defaultMode: 0755
            - name: agents
              hostPath:
                path: /data/william/openab
                type: Directory
            - name: out
              persistentVolumeClaim:
                claimName: usage-stats-data
```

- [ ] **Step 6: 寫 `usage-stats/README.md`**

內容要涵蓋：這是什麼、為什麼收集與報表分開、四個元件各自的職責、怎麼跑測試、
怎麼部署 CronJob、怎麼產報表（三種格式的指令）、以及**指回 spec 的七條資料契約
重點**（不要在這裡重複，只指路）。至少要有這幾段：

```markdown
# openab bot 使用統計

從各 agent CLI 自己的儲存挖出使用統計。**不改 openab 本體**，資料源已在 k3s
節點實機驗證（工具與結果見 `../verify-stats-sources.py` 與 `../README.md`）。

設計依據：`docs/superpowers/specs/2026-09-10-bot-usage-stats-design.md`
實作計畫：`docs/superpowers/plans/2026-09-11-bot-usage-stats.md`

## 收集與報表是兩件事

- **收集**（`collect.py`，CronJob 每天跑）：把原始儲存轉成正規化事件並累積。
  **必須定期跑** —— claude-code 有 transcript 保留期限（`cleanupPeriodDays`，
  預設 30 天），錯過即永久遺失。
- **報表**（`report.py`，你想看就跑）：吃已累積的事件，不碰原始儲存。所以可以
  重跑、可以改指標定義後重算歷史、可以指定任意日期範圍。

## 產報表

    python3 report.py --data <收集輸出目錄> --since 2026-09-01 --until 2026-09-10
    python3 report.py --data … --since … --until … --bots rick,morty
    python3 report.py --data … --since … --until … --format md   -o report.md
    python3 report.py --data … --since … --until … --format html -o report.html

HTML 是自帶所有資源的單一檔案（零外部請求），`open report.html` 就能看，
不需要 nginx 或任何靜態檔服務。

## 跑測試

    python3 -m unittest discover -s tests -t . -v

只用標準庫，沒有 pip 依賴。

## 讀數字前必須知道的限制

報表本身會印出這些，但先讀一次：任務數僅含成功的任務、對話數逐日加總會大於
實際、摩擦指標不是滿意度、token 歸因是 session 層估計值、`allowedUsers` 非空的
bot 活躍人數有上界。細節與資料契約的七條重點見 spec。
```

- [ ] **Step 7: 更新 `deployment-guides/k3s/README.md` 與 `K3S.md`**

`k3s/README.md` 的檔案表加一列：

```markdown
| `usage-stats/` | bot 使用統計：CronJob 收集 + 手動產報表。見 [`usage-stats/README.md`](usage-stats/README.md) |
```

`K3S.md` 加一節「使用統計 CronJob」，內容是靜態 PV（`pv-cac-usage-stats`，
`claimRef` 指 `cac/usage-stats-data`，path `/data/william/openab-usage-stats`）、
建 ConfigMap、apply cronjob，以及手動觸發一次驗證的指令：

```bash
kubectl create job --from=cronjob/usage-stats-collect usage-stats-manual -n cac
kubectl logs -f job/usage-stats-manual -n cac
```

- [ ] **Step 8: 端對端驗收（人工對照，不可省）**

```bash
# 1. 在節點上跑一次收集
kubectl create job --from=cronjob/usage-stats-collect usage-stats-verify -n cac
kubectl logs job/usage-stats-verify -n cac

# 2. 產一天的報表
python3 report.py --data <PVC 掛載點> --since <昨天> --until <昨天>
```

**人工對照 Discord 頻道當天的實際訊息數，確認「真人任務數」對得上。** 這步不能
省——統計系統最常見的失敗模式是「跑得很順、數字全錯」，而且錯了沒人發現。

另外用 `verify-stats-sources.py` 的 token 加總當上界檢查：報表算出的 token 總量
**絕不該超過**探查工具看到的權威路徑總和。

- [ ] **Step 9: Commit**

```bash
git add deployment-guides/k3s/usage-stats/ deployment-guides/k3s/README.md \
        deployment-guides/K3S.md
git commit -m "feat(usage-stats): CronJob、thread_map 計數、部署文件"
```

---

### Task 13: 頻道維度（獨立於 Task 12，先後不拘）

**Files:**
- Modify: `deployment-guides/k3s/usage-stats/aggregate.py`（附加一個函式）
- Modify: `deployment-guides/k3s/usage-stats/report.py`（三處插入）
- Modify: `deployment-guides/k3s/usage-stats/render_html.py`（一處插入）
- Test: `deployment-guides/k3s/usage-stats/tests/test_channels.py`

**為什麼要這個 task：** 自我檢查發現 `channel_names` 被載入設定、放進報表資料
模型、也有測試，但**沒有任何 renderer 用到它**——那是死設定。而 spec 明確要求
頻道名稱查表，「哪個團隊在用」也是採用率用途的一部分。

**注意 `channel_id` 的語意**：在 thread 裡它是**父頻道**、`thread_id` 才是 thread
本身（`discord.rs:2140`）。所以按 `channel_id` 分組得到的是「父頻道層級」的使用
分布，這正是要的——thread 是任務的容器，不是團隊的邊界。

- [ ] **Step 1: 寫失敗的測試**

`tests/test_channels.py`：

```python
"""頻道維度：分組、名稱查表、以及未知頻道的處理。"""
import unittest

from aggregate import tasks_by_channel
from report import build_report, channel_label, load_config, render_md, render_text


def task(dedup_key, channel_id="1528965074562191420", source="human",
         bot="rick", ts="2026-09-10T06:00:00Z"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "channel_id": channel_id, "sender_id": "824",
            "display_name": "william", "session_id": "s1", "occurred_at": ts}


class TestTasksByChannel(unittest.TestCase):
    def test_groups_by_channel_with_three_sources(self):
        rows = [task("d:1", "c1"), task("d:2", "c1", source="cron"),
                task("d:3", "c2")]
        got = tasks_by_channel(rows)
        self.assertEqual(got["c1"], {"human": 1, "bot_relay": 0, "cron": 1})
        self.assertEqual(got["c2"]["human"], 1)

    def test_deduplicates_before_grouping(self):
        got = tasks_by_channel([task("d:1", "c1"), task("d:1", "c1")])
        self.assertEqual(got["c1"]["human"], 1)

    def test_task_without_channel_id_goes_to_unknown_not_dropped(self):
        rows = [dict(task("d:1"), channel_id=None)]
        self.assertEqual(tasks_by_channel(rows)["unknown"]["human"], 1)

    def test_empty_input(self):
        self.assertEqual(tasks_by_channel([]), {})


class TestChannelLabel(unittest.TestCase):
    def test_resolves_configured_name(self):
        self.assertEqual(channel_label("c1", {"c1": "cac-dev-team"}),
                         "cac-dev-team")

    def test_falls_back_to_the_raw_id_so_it_is_never_blank(self):
        self.assertEqual(channel_label("c9", {}), "c9")

    def test_unknown_bucket_gets_a_readable_label(self):
        self.assertEqual(channel_label("unknown", {}), "（無頻道資訊）")


class TestRenderersShowChannels(unittest.TestCase):
    def _report(self, names):
        cfg = load_config(None)
        cfg["channel_names"] = names
        return build_report([task("d:1", "1528965074562191420")], [], cfg,
                            "2026-09-09", "2026-09-10", {})

    def test_report_carries_by_channel(self):
        rep = self._report({})
        self.assertIn("by_channel", rep)
        self.assertIn("1528965074562191420", rep["by_channel"])

    def test_text_report_uses_the_configured_name_not_the_raw_id(self):
        out = render_text(self._report({"1528965074562191420": "cac-dev-team"}))
        self.assertIn("cac-dev-team", out)

    def test_markdown_report_has_a_channel_table(self):
        out = render_md(self._report({"1528965074562191420": "cac-dev-team"}))
        self.assertIn("頻道", out)
        self.assertIn("cac-dev-team", out)

    def test_html_report_has_a_channel_table(self):
        import render_html
        html = render_html.render(
            self._report({"1528965074562191420": "cac-dev-team"}))
        self.assertIn("cac-dev-team", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest tests.test_channels -v
```

Expected: FAIL — `ImportError: cannot import name 'tasks_by_channel' from 'aggregate'`

- [ ] **Step 3a: `aggregate.py` 檔尾附加**

```python
def tasks_by_channel(tasks):
    """{channel_id: {human, bot_relay, cron}}。

    注意 channel_id 在 thread 裡是**父頻道**（discord.rs:2140），所以這是
    父頻道層級的使用分布 —— thread 是任務的容器，不是團隊的邊界，這正是
    「哪個團隊在用」要的粒度。
    """
    out = {}
    for task in dedupe_tasks(tasks):
        channel_id = task.get("channel_id") or "unknown"
        bucket = out.setdefault(channel_id, dict.fromkeys(SOURCES, 0))
        source = task.get("source")
        if source in bucket:
            bucket[source] += 1
    return out
```

- [ ] **Step 3b: `report.py` 三處插入**

在 `_TZ_NAME = "Asia/Taipei"` 那行下面加：

```python
def channel_label(channel_id, channel_names):
    """頻道的顯示名稱。查不到就用原始 ID —— 絕不留空白。"""
    if channel_id == "unknown":
        return "（無頻道資訊）"
    return (channel_names or {}).get(channel_id, channel_id)
```

在 `build_report` 回傳 dict 裡，`"channel_names": ...` 那一行**上面**加：

```python
        "by_channel": aggregate.tasks_by_channel(tasks),
```

在 `render_text` 的 `out.append("\n[讀這份報表前必須知道]")` **上面**加：

```python
    out.append("\n[各頻道使用量]  真人 / bot 互呼 / cron 排程")
    for channel_id, counts in sorted(
            report["by_channel"].items(), key=lambda kv: -sum(kv[1].values())):
        out.append("  %-24s  %4d / %4d / %4d"
                   % (channel_label(channel_id, report["channel_names"]),
                      counts["human"], counts["bot_relay"], counts["cron"]))
```

在 `render_md` 的 `out.append("## 摩擦指標（不是滿意度）")` **上面**加：

```python
    out.append("")
    out.append("## 各頻道使用量")
    out.append("")
    out.append("| 頻道 | 真人 | bot 互呼 | cron 排程 |")
    out.append("| --- | --- | --- | --- |")
    for channel_id, c in sorted(report["by_channel"].items(),
                                key=lambda kv: -sum(kv[1].values())):
        out.append("| %s | %d | %d | %d |"
                   % (channel_label(channel_id, report["channel_names"]),
                      c["human"], c["bot_relay"], c["cron"]))
```

- [ ] **Step 3c: `render_html.py` 一處插入**

在 `parts.append("<h2>摩擦指標（不是滿意度）</h2>")` **上面**加：

```python
    parts.append("<h2>各頻道使用量</h2>")
    parts.append(_table(
        ["頻道", "真人", "bot 互呼", "cron 排程"],
        [[report_mod.channel_label(cid, report["channel_names"]),
          c["human"], c["bot_relay"], c["cron"]]
         for cid, c in sorted((report.get("by_channel") or {}).items(),
                              key=lambda kv: -sum(kv[1].values()))]))
```

- [ ] **Step 3d: 同步 Task 11 的測試 fixture**

`tests/test_render_html.py` 的 `report_fixture()` 是手寫的報表資料模型，Task 13
新增了 `by_channel` 欄位，所以那份 fixture 也要補上，否則它就不再反映
`build_report` 的真實輸出：

```python
        "by_channel": {"1528965074562191420": {"human": 5, "bot_relay": 1,
                                               "cron": 9}},
        "channel_names": {"1528965074562191420": "cac-dev-team"},
```

（`render_html.render` 本身對這個欄位用 `report.get("by_channel") or {}` 防禦性
讀取，所以舊的報表 dict 不會炸掉，但 fixture 仍應與真實輸出一致。）

- [ ] **Step 4: 跑測試確認通過**

```bash
cd deployment-guides/k3s/usage-stats && python3 -m unittest discover -s tests -t . -v
```

Expected: PASS，累計 193 個測試（`Ran 193 tests`）

- [ ] **Step 5: Commit**

```bash
git add deployment-guides/k3s/usage-stats/aggregate.py \
        deployment-guides/k3s/usage-stats/report.py \
        deployment-guides/k3s/usage-stats/render_html.py \
        deployment-guides/k3s/usage-stats/tests/test_channels.py
git commit -m "feat(usage-stats): 頻道維度 —— 讓 channel_names 設定真的被用到"
```

---

## 實作前必做的一次性驗證

**Task 1 之前先跑這個**，它決定收集器要多急著上線（不影響程式碼，只影響時程）：

```bash
sudo grep -o '"cleanupPeriodDays":[0-9]*' /data/william/openab/agent-*/.claude/settings.json
```

有設定值就確認了保留期限；沒有設定則走預設 30 天。實測 genie 的最舊 transcript
剛好卡在 31 天前、而 codex 那隻有 52 天，**符合「claude-code 砍舊 transcript、
codex 不砍」的模式**。若成立，claude-code 三隻的歷史上限就是 30 天且每天少一天
——現在不收，最舊的資料每天在消失。

把結果記進 `deployment-guides/k3s/usage-stats/README.md`。
