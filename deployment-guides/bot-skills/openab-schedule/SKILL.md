---
name: openab-schedule
description: Use when a human asks the bot to run a task on a recurring schedule and report back (daily PR summary, weekly report, periodic alert scan...), or asks to create, modify, view, or disable a schedule. Not for one-time delayed reminders (that's /remind) or plain questions/code reading.
---

# openab-schedule

## Overview

Uses openab's built-in **usercron** to create recurring schedules: write a job into `~/.openab/cronjob.toml`. The scheduler polls the file's mtime every minute and hot-reloads it. When a job fires, openab injects its `message` as a **new prompt** — you act on it and post the result to the job's `channel`.

> ⚠️ **Never use `CronCreate`/`CronList`/`CronDelete`.** Those are Claude Code's own built-in, session-scoped scheduler (dies when the session ends, unrelated to openab's usercron, and does not actually deliver messages to Discord). Everything here means reading and writing the `~/.openab/cronjob.toml` file directly — never calling a scheduling tool.

## Division of Responsibility

- **You CAN** (no restart needed): create/modify/view/disable jobs in `~/.openab/cronjob.toml`. Editing this file hot-reloads within a minute.
- **You CANNOT**: enable the usercron feature itself. That requires adding `[cron]` to `config.toml` and **restarting the container** — you can't read the live runtime config or restart yourself, so that's the human's job outside the container.

> The only proof a schedule really fires is the ping test in step 4 — not this document, not any config you happen to read. Declaring "it's set up" right after writing the file is wrong.

## Hard Gate — Confirm Before Writing Anything

**`channel`, `timezone`, and `message` must be confirmed with the human — or given a safe explicit default — before you write to `cronjob.toml`.** Never guess these. Prefer asking again over inventing a value.

1. **`channel`** — must be a real **channel ID**, not a thread ID. openab always tries to open a **new thread under `channel`** when a job fires; Discord rejects opening a thread under another thread (`failed to create thread: Cannot execute action on this channel type`). You have no reliable way to resolve "the current channel" to an ID from inside the container — ask the human to right-click the channel → Copy Channel ID (needs Developer Mode).
   - If the human just says "this channel" and an existing job already uses some channel ID, you may *assume* it's the same one — but confirm once before reusing it.
   - To post into an **existing thread** instead of a new one, keep `channel` as the real channel ID and additionally set `thread_id` to that thread's ID (both fields together, not either/or).
2. **`timezone`** — unset defaults to **UTC**, off by 8 hours from Taiwan time. Confirm with the human (usually `Asia/Taipei` for this deployment).
3. **Schedule semantics** — spell out your interpretation and confirm it: `*` for day-of-week means "every day"; `1-5` means "weekdays". E.g. "you said daily at 18:00 = `0 18 * * *` (weekends included), correct?"
4. **`message`** — must be self-contained: confirm target repo/data scope and the definition of "success/failure" (e.g. which repo a CI check targets, whether "failing" includes cancelled/timed-out runs).

## Steps

### 1. Is usercron even enabled? Don't stall on this — the ping test is the only judge

Go straight to step 3 (write the file). Use the step-4 ping as the sole signal: ping appears = enabled and the whole chain works; no ping = probably disabled, go ask a human to enable it. You usually can't read the live runtime config from inside the container, so don't burn time guessing paths.

Only if you *happen* to be able to read the config (try `~/.openab/config.toml`, `/home/node/config.toml`, `/etc/openab/config.toml`) and it clearly shows `usercron_enabled = false` or no `[cron]` section at all, stop early and ask the human to add this to `config.toml` and redeploy (you can't edit the live config or restart yourself):

```toml
[cron]
usercron_enabled = true
usercron_path = "cronjob.toml"
```

### 2. Write the job — read the existing file first, never clobber someone else's schedule

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
- ⚠️ **One-off / "just run it once" requests**: cron has **no year field**. Even if you compute an exact minute/hour/day/month with `date` and put it in `schedule`, the job fires again next year on the same date and time — it is not truly one-time. Do **not** try to solve this with `disable_on_success = true` (invalid usage — see Common Mistakes). Correct approach: same as the `verify-ping` pattern in step 4 — create it, let it fire once, confirm the result, then **manually delete the job**. Don't expect it to stop itself.

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

State clearly: the real job's time/channel/content, that you verified it with a real ping, and that future changes (time, disable) go straight through you (you edit `cronjob.toml`, no restart needed).

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
| Using `CronCreate`/`CronList`/`CronDelete` | Wrong system entirely — session-scoped, dies with the session, never reaches Discord | Only ever read/write `~/.openab/cronjob.toml` |
| `channel` set to a thread ID | Every fire fails: `failed to create thread: Cannot execute action on this channel type` | `channel` = real channel ID; use `thread_id` alongside it to target a specific thread |
| Claiming "it's set up" right after writing the file | No proof it actually fires — silent, invisible failure the human won't notice for days | Always run the step-3 ping test first |
| Fabricating a ping reply (e.g. running `date` and typing a message that looks like a fire) | Looks like success, proves nothing — the real mechanism was never exercised | Only trust the exact `🕐 [sender_name]: message` format arriving as a standalone new message |
| `disable_on_success = true` for a "run once" job | Not valid syntax; does not auto-disable anything; the job still fires again next year (no year field in cron) | Manually delete the job after confirming it fired once |
| Guessing `channel`/`timezone`/`message` instead of asking | Job silently posts to the wrong place, wrong time, or can't act on vague instructions | Confirm all three (or an explicit safe default) before writing |
| Overwriting the whole file with just the new job | Destroys everyone else's existing schedules | Read the file first, keep existing `[[jobs]]`, add/replace by `id` |

## Iron Rules

- Manage schedules only by reading/writing `~/.openab/cronjob.toml` — never `CronCreate`/`CronList`/`CronDelete`.
- Enabling usercron itself (config + restart) is not yours to do — say so plainly, never fake it.
- Never tell the human "it's live" before the step-3 ping test passes with a real signal.
- Read the existing file before writing; add/replace by `id`; never clobber someone else's job.
- `channel` must be a human-confirmed real channel ID; `timezone` must always be explicit.
- `message` must be a self-contained natural-language instruction — no baked-in shell or date logic.
- Delete one-off test/one-time jobs by hand once confirmed — don't rely on `disable_on_success = true` to stop them.
