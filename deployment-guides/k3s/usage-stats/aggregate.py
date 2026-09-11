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
