# Repo Identity Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize GitHub account selection and repository-local Git identity in a reusable deployment skill.

**Architecture:** `deployment-guides/bot-skills/repo-identity/` owns the declarative owner-to-account TOML mapping and the workflow that reads it. The v2 persona documents own each bot's repo-local Git name/email, while the shared baseline invokes the installed `wm4n.repo-identity` skill. The deployment runbook installs the skill beside the existing pipeline skills.

**Tech Stack:** Markdown skills, TOML configuration, GitHub CLI, Git local configuration.

## Global Constraints

- Store only owner-to-account routing in the TOML file; never store GitHub tokens or Git identity values.
- Map `104corp` and `cac-william` to `cac-william`; use `wm4n` for every other resolved owner.
- Stop and ask a human when the target owner cannot be determined.
- Set `user.name` and `user.email` only with `git -C <repo> config`; never use global Git configuration.
- Keep persona documents focused on persona and invocation rules, not duplicated identity configuration.

---

### Task 1: Create the declarative repo-identity skill

**Files:**
- Create: `deployment-guides/bot-skills/repo-identity/SKILL.md`
- Create: `deployment-guides/bot-skills/repo-identity/config.toml`
- Create: `deployment-guides/bot-skills/repo-identity/agents/openai.yaml`

**Interfaces:**
- Consumes: a target `owner/repo` and bot persona (`rick`, `morty`, or `summer`).
- Produces: the selected GitHub account.

- [ ] **Step 1: Initialize the skill skeleton in the repository-owned bot skill directory.**

Run:

```bash
python3 /Users/william.chao/.codex/skills/.system/skill-creator/scripts/init_skill.py repo-identity --path deployment-guides/bot-skills --interface display_name="Repo Identity" --interface short_description="Select the GitHub account and local Git identity for a target repository." --interface default_prompt="Use this skill to select the GitHub account and repo-local Git identity for owner/repo."
```

Expected: `deployment-guides/bot-skills/repo-identity/` contains `SKILL.md` and `agents/openai.yaml`.

- [ ] **Step 2: Define the single configuration source.**

Write `config.toml` with this exact model:

```toml
[routing]
cac_owners = ["104corp", "cac-william"]
cac_account = "cac-william"
default_account = "wm4n"
```

- [ ] **Step 3: Write the skill workflow.**

In `SKILL.md`, require the agent to:

1. determine `owner/repo` and stop for a human if owner is unknown;
2. read `config.toml` before selecting credentials;
3. choose `routing.cac_account` only for `routing.cac_owners`, otherwise `routing.default_account`;
5. run `gh auth switch --hostname github.com --user <account>` before clone, fetch, push, or other GitHub CLI work;
6. leave repo-local Git identity to the calling bot's CLAUDE.md or AGENTS.md.

- [ ] **Step 4: Validate the skill metadata.**

Run:

```bash
python3 /Users/william.chao/.codex/skills/.system/skill-creator/scripts/quick_validate.py deployment-guides/bot-skills/repo-identity
```

Expected: validation exits with status 0.

- [ ] **Step 5: Commit the self-contained skill.**

```bash
git add deployment-guides/bot-skills/repo-identity
git commit -m "feat(bots): add repo identity skill"
```

### Task 2: Replace duplicated identity rules with the skill invocation

**Files:**
- Modify: `deployment-guides/Rick-CLAUDE_v2.md:31-45`
- Modify: `deployment-guides/Morty-CLAUDE_v2.md:31-45`
- Modify: `deployment-guides/Summer-AGENTS_v2.md:31-45`
- Modify: `deployment-guides/bot-skills/_shared/engineer-baseline.md:21-41`

**Interfaces:**
- Consumes: installed skill name `wm4n.repo-identity` and its `config.toml`.
- Produces: a mandatory preflight instruction that applies in both regular and pipeline modes.

- [ ] **Step 1: Replace each v2 SOP identity table with one shared instruction.**

Replace the per-file account-selection steps with the skill invocation, then keep each bot's local Git name/email in that bot's own document.

```markdown
在任何遠端 Git 或 GitHub CLI 操作前，必須先以目標 `owner/repo` 使用 `wm4n.repo-identity` skill 選擇並切換 GitHub account。clone 完後，依本 bot 文件設定 repo-local Git 署名。
```

Retain the Jira/GitHub comment signature rule after this instruction.

- [ ] **Step 2: Replace the baseline identity table with the same invocation.**

Replace the entire `## 開工前：依 repo owner 選 GitHub 身份` section with:

```markdown
## 開工前：設定 repo GitHub 身份（每個任務必做，先於任何 `git`／`gh` 操作）

使用 `wm4n.repo-identity` skill，傳入目標 `owner/repo`。帳號分流與 GitHub 切換由 skill 的 `config.toml` 統一管理；repo-local Git 署名由各 bot 文件設定；無法判斷 owner 時停止並詢問人類。
```

Keep the security rule about not posting credential-bearing GitHub information in Discord.

- [ ] **Step 3: Verify the canonical documents no longer contain duplicated mappings.**

Run:

```bash
rg -n 'openabdev|當 owner 為|其餘 owner|Git Email：|Git Name：' deployment-guides/Rick-CLAUDE_v2.md deployment-guides/Morty-CLAUDE_v2.md deployment-guides/Summer-AGENTS_v2.md deployment-guides/bot-skills/_shared/engineer-baseline.md
```

Expected: no matches.

- [ ] **Step 4: Commit the document migration.**

```bash
git add deployment-guides/Rick-CLAUDE_v2.md deployment-guides/Morty-CLAUDE_v2.md deployment-guides/Summer-AGENTS_v2.md deployment-guides/bot-skills/_shared/engineer-baseline.md
git commit -m "refactor(bots): centralize repo identity rules"
```

### Task 3: Install the skill through the three-bot deployment runbook

**Files:**
- Modify: `deployment-guides/BOT_SETUP.md:536-556`
- Modify: `deployment-guides/BOT_SETUP.md:632-639`
- Modify: `deployment-guides/BOT_SETUP.md:726-733`
- Modify: `deployment-guides/BOT_SETUP.md:292-304`

**Interfaces:**
- Consumes: source directory `deployment-guides/bot-skills/repo-identity`.
- Produces: `wm4n.repo-identity` symlinks in the Claude and Codex skill discovery folders.

- [ ] **Step 1: Add the Claude skill symlink for Morty and Rick.**

Add this command to both `~/.claude/skills/` installation blocks:

```bash
ln -sfn /home/node/github-repo/openab/deployment-guides/bot-skills/repo-identity /home/node/.claude/skills/wm4n.repo-identity
```

Update the adjacent `ls` comments to list `wm4n.repo-identity`.

- [ ] **Step 2: Add the Codex skill symlink for Summer.**

Add this command to the `~/.codex/skills/` installation block:

```bash
ln -sfn /home/node/github-repo/openab/deployment-guides/bot-skills/repo-identity /home/node/.codex/skills/wm4n.repo-identity
```

Update the adjacent `ls` comment to list both deployed skills.

- [ ] **Step 3: Remove the duplicated mapping table from Part F2.**

Replace the table and inline account-selection procedure with a short statement that the installed `wm4n.repo-identity` skill reads its versioned `config.toml` to select the account. Keep the existing warning that `gh auth switch` is container-global, and state that bot documents own repo-local identity.

- [ ] **Step 4: Update the skill-name convention note.**

Add `wm4n.repo-identity` to the list of repository-owned skills whose deployment symlink name uses the `wm4n.` prefix.

- [ ] **Step 5: Verify install paths and documentation references.**

Run:

```bash
rg -n 'wm4n\.repo-identity|repo-identity/config\.toml' deployment-guides/BOT_SETUP.md deployment-guides/Rick-CLAUDE_v2.md deployment-guides/Morty-CLAUDE_v2.md deployment-guides/Summer-AGENTS_v2.md deployment-guides/bot-skills/_shared/engineer-baseline.md
git diff --check
```

Expected: all three deployment targets install the skill; all canonical instructions cite it; no whitespace errors.

- [ ] **Step 6: Commit the deployment documentation.**

```bash
git add deployment-guides/BOT_SETUP.md
git commit -m "docs(bots): install repo identity skill"
```
