---
name: openab-schedule
description: Use whenever a human asks the bot to notify them or do something later — a one-time future reminder, a recurring report (daily PR summary, weekly report), a periodic alert scan, or any other cyclical/scheduled action — or asks to create, modify, view, or disable such a schedule. This is the only scheduling mechanism the bot may use, one-time requests included (see Iron Rules — never CronCreate/CronList/CronDelete/ScheduleWakeup, and never defer to /remind, which is human-only and never runs agent logic). Not for plain questions/code reading.
---

# openab-schedule

## Overview

Uses openab's built-in **usercron** to create schedules — recurring or one-time alike: write a job into `~/.openab/cronjob.toml`. The scheduler polls the file's mtime every minute and hot-reloads it. When a job fires, openab injects its `message` as a **new prompt** — you act on it and post the result to the job's `channel`.

> ⚠️ **Never use `CronCreate`/`CronList`/`CronDelete`/`ScheduleWakeup`, or any other Claude-Code-native scheduling tool.** These belong to the harness's own session-scoped scheduler (dies when the session ends, unrelated to openab's usercron, and does not actually deliver messages to Discord) — a request that sounds like "schedule/remind/notify me" is never their job in this deployment, no matter how directly they seem to fit. Everything here means reading and writing the `~/.openab/cronjob.toml` file directly — never calling a scheduling tool.
>
> `/remind` is a **separate, human-only** slash command — bots are rejected if they try to invoke it, and even when a human uses it themselves it only tags someone at a fixed time, it never runs agent logic. Any request that needs the agent to actually do something later, one-time or recurring, belongs here via a usercron job — never `/remind`.

## Division of Responsibility

- **You CAN** (no restart needed): create/modify/view/disable jobs in `~/.openab/cronjob.toml`. Editing this file hot-reloads within a minute.
- **You CANNOT**: enable the usercron feature itself. That requires adding `[cron]` to `config.toml` and **restarting the container** — you can't read the live runtime config or restart yourself, so that's the human's job outside the container.

> The only proof a schedule really fires is the ping test in step 3 — not this document, not any config you happen to read. Declaring "it's set up" right after writing the file is wrong.

## Hard Gate — Resolve Every Field, Then Confirm With One Summary Card

Before writing to `cronjob.toml`, resolve **all** of the fields below — parse whatever the human specified, fill the rest with defaults — then post them **together as a single summary card** and wait for the human to confirm. Never write the file first and explain after; never confirm one field at a time as separate messages; never omit a field from the card because it "obviously" has a default.

```
📋 排程確認
- 執行內容：<self-contained instruction — the full deferred action, not just a ping>
- 通知時間：<computed absolute next fire — date, weekday, time>
- 時區：<IANA timezone>
- 通知頻道：<channel name>（<channel ID>）<"（預設）" if you picked it, not the human>
- 重複：<"不重複（一次性）" or the recurring pattern in plain language + raw cron>
- 顯示名稱：<sender_name>
- 討論串：<"開新討論串" or "沿用目前討論串">

以上正確嗎？
```

Resolve each field like this:

1. **執行內容 (`message`)** — the entire self-contained instruction for whatever should happen at fire time, including any lookup/research the human asked for. ⚠️ If the request bundles a delayed notification with work to do (e.g. "remind me in 5 min, then list my Jira tickets"), that work belongs entirely in this field — don't do it now and leave this as a bare "time's up" ping.
2. **通知時間 / 重複 (`schedule`)** — compute the real next fire time yourself, never eyeball it; state one-time vs. recurring, and for recurring, the plain-language pattern plus the raw cron expression.
3. **時區 (`timezone`)** — never leave unstated; default `Asia/Taipei` for this deployment. Unset defaults to UTC — 8 hours off.
4. **通知頻道 (`channel`)** — must be a real **channel ID**, not a thread ID (Discord rejects opening a thread under another thread: `failed to create thread: Cannot execute action on this channel type`). Never silently default to "wherever this conversation is happening", and never leave it off the card.
   - If the bot is allowed in more than one channel and one is clearly purpose-matched to the request (e.g. a notification/reminder ask and a channel named `*-notify` exists), you may default to it — but the card must still show it marked `（預設）` so the human can veto.
   - If it isn't obvious which channel fits, don't guess at all — ask directly before building the card.
   - If reusing an existing job's channel because the human said "this channel", confirm once before reusing it.
5. **顯示名稱 (`sender_name`)** — a short label shown in the fire context (`🕐 [sender_name]: message`); auto-generate one from the instruction if not given, but still show it in the card.
6. **討論串 (`thread_id`)** — default is a **new thread** under `channel` (openab's normal behavior); only reuse the current/an existing thread if the human asked for that. State which one explicitly — never decide this silently. To target an existing thread, set both `channel` (real channel ID) and `thread_id` together.

Post the card, wait for confirmation, and only then proceed to step 2. If the human corrects anything, update and re-show the whole card — don't silently patch one field and proceed.

## Steps

### 1. Is usercron even enabled? Don't stall on this — the ping test is the only judge

Go straight to step 2 (write the file). Use the step-3 ping as the sole signal: ping appears = enabled and the whole chain works; no ping = probably disabled, go ask a human to enable it. You usually can't read the live runtime config from inside the container, so don't burn time guessing paths.

Only if you *happen* to be able to read the config (try `~/.openab/config.toml`, `/home/node/config.toml`, `/etc/openab/config.toml`) and it clearly shows `usercron_enabled = false` or no `[cron]` section at all, stop early and ask the human to add this to `config.toml` and redeploy (you can't edit the live config or restart yourself):

```toml
[cron]
usercron_enabled = true
usercron_path = "cronjob.toml"
```

### 2. Write the job — only after the summary card is confirmed; read the existing file first, never clobber someone else's schedule

```bash
mkdir -p ~/.openab
cat ~/.openab/cronjob.toml 2>/dev/null   # check for existing [[jobs]] and keep them
```

Multiple schedules = multiple `[[jobs]]` blocks in the same file. Write the **entire file** (existing jobs untouched + your new one); use `id` to add or replace your own entry — never overwrite the whole file with just your new block.

```toml
[[jobs]]
id = "daily-merged-pr-summary"     # an id is required for reliable scheduler writeback
enabled = true
schedule = "0 9 * * 1-5"
channel = "1490282656913559673"    # quote the snowflake to avoid float precision loss
message = "Summarize yesterday's merged PRs: use gh to find PRs merged in the previous calendar day, list number, title, author, and a one-line highlight; say so plainly if there were none. Report in the requested language."
sender_name = "DailyPR"
timezone = "Asia/Taipei"
```

- `message` must be a **self-contained natural-language instruction** — when it fires, it's a brand-new turn's prompt; it must be able to work out "yesterday", what to say if there's no data, and what language to reply in, entirely on its own.
- ⚠️ Don't bake shell, `date -d`, or crontab-style `%` escaping into `message`: `cronjob.toml` is plain TOML, not crontab, and the container's `date` (BSD vs GNU) isn't guaranteed. Leave date math to the agent that runs at fire time.
- ⚠️ **One-off / "just run it once" requests (including "remind me in N minutes" style asks)**: cron has **no year field**. Even if you compute an exact minute/hour/day/month with `date` and put it in `schedule`, the job fires again next year on the same date and time — it is not truly one-time. Do **not** try to solve this with `disable_on_success = true` (invalid usage — see Common Mistakes). Correct approach: same as the `verify-ping` pattern in step 3 — create it, let it fire once, confirm the result, then **manually delete the job**. Don't expect it to stop itself.

### 3. End-to-end test (the only trustworthy verification)

You can't read `docker logs`, so verify by **observed behavior**: temporarily add a once-a-minute ping job and watch the channel for 1–2 minutes.

```toml
[[jobs]]
id = "verify-ping"
enabled = true
schedule = "* * * * *"
channel = "1490282656913559673"
message = "usercron self-test ping, please ignore"
sender_name = "verify"
timezone = "Asia/Taipei"
```

- **It shows up** → the whole chain works (usercron on, path correct, channel correct, bot present in that channel). **Check it's a real signal first**: a genuine fire is always the fixed format `🕐 [sender_name]: message` — a fresh standalone message, never a reply to anyone. If what you see is text you generated yourself (e.g. you ran `date` and replied with something that *sounds* like a ping, or it's glued onto a reply) that is not a real signal — it means usercron never actually fired. Once you've confirmed it's real, delete the `verify-ping` entry, keep only the real job(s), and save again.
  - Afterwards, repeated fires of the *same* job land in the **same thread that the first fire created** — the scheduler writes `thread_id` back into `cronjob.toml` automatically. Seeing every fire land in one thread is expected, not a bug.
- **Nothing shows up** → usercron is probably disabled (back to step 1 — ask a human to enable it + redeploy), or the channel ID is wrong / the bot isn't in that channel.

### 4. Report back to the human

Once step 3's ping test passes, report back clearly — never just "it's set up":

- **Exact fire date/time**, spelled out in the job's confirmed timezone — not the bare cron expression (e.g. "fires 2026-07-25 23:58 Asia/Taipei", not just "`*/5 * * * *`").
- **Next fire date/time** — for a one-time job this is the same moment as above; for a recurring job, see the next bullet.
- **For recurring jobs, the next 3 fire times** (see "Computing fire times" below) — lets the human sanity-check the schedule without doing cron math themselves.
- **A one-line instruction summary** — paraphrase `message`, don't paste the whole string.
- That you verified it with a real ping (step 3), and that future changes (time, disable, delete) go straight through you — no restart needed.

#### Computing fire times

Never eyeball a cron schedule against a clock in your head — that's the same class of mistake behind this skill's `ScheduleWakeup` incident (wrong tool, then a time reported without real computation). Actually compute each fire time in the job's confirmed timezone:

- Prefer a scripting tool with real timezone/cron support if the container has one (e.g. `python3` with `zoneinfo` for timezone conversion) — check it's actually available before trusting its output.
- If nothing reliable is available, reason through the cron fields by hand (minute → hour → day-of-month → month → day-of-week) against the current date in the confirmed timezone, and show your work rather than asserting a number.
- This is your own reasoning for the human-facing report — don't bake it into `cronjob.toml` itself (see step 2's warning about shell/`date -d` in `message`).

### 5. Disabling or deleting a job — report what stops

When a human asks you to cancel, stop, disable, or remove a schedule:

1. Read the file first; identify the exact job by `id`. If there's any ambiguity about which job they mean, ask — never guess.
2. Apply what they asked: `enabled = false` to disable (keeps the block for later re-enabling), or remove the block entirely if they asked for a real delete.
3. **Report back explicitly**: which job was disabled/deleted (its `id` and a one-line instruction summary) and what this cancels — e.g. "disabled `daily-merged-pr-summary`: this would otherwise have next fired 2026-07-28 09:00 Asia/Taipei (and every weekday after) — that won't happen now."

Never silently disable or delete without telling the human what stopped.

### 6. Listing all schedules — use a consistent table

When asked to list current jobs, don't dump the raw TOML. Read `~/.openab/cronjob.toml` and present a table:

| id | schedule | next run | channel | instruction |
|---|---|---|---|---|
| daily-merged-pr-summary | weekdays 9am (`0 9 * * 1-5`) | 2026-07-27 09:00 Asia/Taipei | 1490282656913559673 | Summarize yesterday's merged PRs... |

- **schedule** — plain language first, raw cron expression in parens.
- **next run** — computed per "Computing fire times" above, never guessed.
- **instruction** — first line / first ~10 words of `message`, not the full text; mark truncation with `…`.
- Include disabled jobs too, marked (e.g. prefix the `id` with `(disabled)`), so the human sees the full picture, not just active ones.

## Quick Reference

| Need | Value |
|---|---|
| Weekdays 9am | `0 9 * * 1-5` |
| Every day 6pm | `0 18 * * *` |
| Sunday midnight | `0 0 * * 0` |
| Every 30 min | `*/30 * * * *` |
| 1st of month, 9am | `0 9 1 * *` |
| View current jobs | `cat ~/.openab/cronjob.toml` |
| Disable a job | set that block's `enabled = false` (or delete the block) |
| Post into an existing thread | set `channel` (real channel) **and** `thread_id` together |
| Only Discord in use | omit `platform` (defaults to `"discord"`; only set `"slack"` if targeting Slack) |

**`disable_on_success`** (goal-driven auto-disable, needs `id`): the value **must be a shell command string** (e.g. `"npm test && echo DONE"`), paired with `disable_on_success_match` — the command must exit 0 **and** its output must contain that string before openab writes `enabled = false` back. It is **not a boolean**, cannot be set to bare `true`, and does not apply to a simple "run once and see" test job (use manual delete instead, per step 2). Full field list / limits: repo's `docs/cronjob.md` or `deployment-guides/CRONJOB.md`.

⚠️ Don't mix numeric and name-based weekdays (`1,Mon` ❌); no wrap-around ranges (`5-2` ❌); don't schedule long-running tasks (>5 min) too tightly (overlap protection skips the next tick).

## Common Mistakes

| Mistake | What happens | Fix |
|---|---|---|
| Using `CronCreate`/`CronList`/`CronDelete`/`ScheduleWakeup` (or any other Claude-Code-native scheduler) | Wrong system entirely — session-scoped, dies with the session, never reaches Discord | Only ever read/write `~/.openab/cronjob.toml` |
| Treating a one-time "remind me in N minutes" request as out of scope, or as `/remind`'s job | `/remind` is human-only (bots rejected) and never runs agent logic — the promised follow-up action never happens, and the human gets no notification at all | Any request needing the agent to notify or act later — one-time or recurring — belongs here, via a one-off usercron job (see step 2's one-off guidance), then manual delete once confirmed |
| `channel` set to a thread ID | Every fire fails: `failed to create thread: Cannot execute action on this channel type` | `channel` = real channel ID; use `thread_id` alongside it to target a specific thread |
| Claiming "it's set up" right after writing the file | No proof it actually fires — silent, invisible failure the human won't notice for days | Always run the step-3 ping test first |
| Fabricating a ping reply (e.g. running `date` and typing a message that looks like a fire) | Looks like success, proves nothing — the real mechanism was never exercised | Only trust the exact `🕐 [sender_name]: message` format arriving as a standalone new message |
| `disable_on_success = true` for a "run once" job | Not valid syntax; does not auto-disable anything; the job still fires again next year (no year field in cron) | Manually delete the job after confirming it fired once |
| Guessing `channel`/`timezone`/`message` instead of asking | Job silently posts to the wrong place, wrong time, or can't act on vague instructions | Confirm all three (or an explicit safe default) before writing |
| Overwriting the whole file with just the new job | Destroys everyone else's existing schedules | Read the file first, keep existing `[[jobs]]`, add/replace by `id` |
| Disabling or deleting a job without telling the human what stopped | Human doesn't know if the automation they expected is gone, still running, or partially changed — may miss an expected notification or get a surprise one later | State which job (`id` + one-line summary) was disabled/deleted and its next-would-have-been fire time |
| Dumping raw `cronjob.toml` content when asked to list jobs | Hard to scan, buries next-run timing in cron syntax, drowns the human in the full `message` text | Present a table: id / schedule (plain language + cron) / next run / channel / instruction summary (see step 6) |
| Silently defaulting `channel` to "wherever this conversation is happening" when more than one channel is available (e.g. a dedicated `*-notify` channel exists) | Schedule fires into the wrong channel with no new thread there; the human has to notice and correct it after the fact | Ask which channel to use whenever more than one is plausible — never assume "this channel" is right just because it's convenient |
| Performing the requested action immediately, then writing a generic "time's up" ping as `message` | The action lands at the wrong time (now, instead of when the human asked for it) and the actual fire event carries no real content | Put the full self-contained instruction for the deferred action into `message` — your immediate reply only confirms the schedule, it doesn't do the work early |
| Confirming fields one at a time in separate messages, or skipping straight to writing without a summary card | Slower back-and-forth, and a wrong field is easy to miss when it isn't shown alongside everything else | Resolve every field first, post ONE structured summary card (see Hard Gate), wait for confirmation |
| Omitting `sender_name` or `thread_id` from the confirmation card because they "obviously" have defaults | Human never sees (and can't veto) that a new thread will be created, or what label the schedule shows under | Always show every field in the card, including ones you defaulted yourself |

## Iron Rules

- Manage schedules only by reading/writing `~/.openab/cronjob.toml` — never `CronCreate`/`CronList`/`CronDelete`/`ScheduleWakeup`/any other Claude-Code-native scheduler, and never by pointing the human at `/remind` when the request needs the agent to act.
- Enabling usercron itself (config + restart) is not yours to do — say so plainly, never fake it.
- Never tell the human "it's live" before the step-3 ping test passes with a real signal.
- Read the existing file before writing; add/replace by `id`; never clobber someone else's job.
- `channel` must be a human-confirmed real channel ID; `timezone` must always be explicit.
- `message` must be a self-contained natural-language instruction — no baked-in shell or date logic.
- Delete one-off test/one-time jobs by hand once confirmed — don't rely on `disable_on_success = true` to stop them.
- When creating a job, report the exact confirmed fire time(s) — computed, never eyeballed — including the next 3 fire times for a recurring job.
- When disabling or deleting a job, state which job it was and what future execution it cancels.
- When listing jobs, present a table (id / schedule / next run / channel / instruction summary) — never dump raw TOML.
- Never default `channel` to "wherever this conversation is happening" — ask when more than one channel is plausible, especially if one is purpose-named for notifications.
- If the human's request bundles a delayed notification with work to do, put that work into `message` to run at fire time — never do it immediately and leave `message` as a bare ping.
- Resolve every field and present them as a single confirmation card before writing — never write first, never confirm field-by-field, never omit a field because it has an obvious default.
