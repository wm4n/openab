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
