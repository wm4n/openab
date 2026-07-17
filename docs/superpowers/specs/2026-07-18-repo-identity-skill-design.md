# Repo Identity Skill Design

## Goal

Centralize GitHub account selection and repository-local Git identity for Rick, Morty, and Summer. Persona documents must not duplicate owner mappings, account names, or email addresses.

## Structure

```text
deployment-guides/bot-skills/repo-identity/
├── SKILL.md
└── config.toml
```

- `SKILL.md` defines the mandatory preflight workflow: determine `owner/repo`, read configuration, choose the account, run `gh auth switch`, and set local Git identity after cloning.
- `config.toml` is the sole source for owner mapping and account/persona identity values. It contains no tokens or other secrets.
- The skill is installed under the deployment-facing name `wm4n.repo-identity` for Claude and Codex agents.

## Configuration Model

The configuration declares:

- an explicit `cac-william` owner allowlist: `104corp` and `cac-william`;
- `wm4n` as the fallback account for every other resolved owner;
- the shared `wm4n` Git name and email;
- the `cac-william` Git name and email for each persona: Rick, Morty, and Summer.

An unresolved owner remains a hard stop: the agent asks a human rather than selecting a default.

## Invocation and Flow

1. Before any `git` or `gh` command for a software-development task, the bot invokes `wm4n.repo-identity`.
2. The skill determines the target owner from the task; if unavailable, it stops and asks for it.
3. The skill reads `config.toml`, selects the GitHub account, and switches it with `gh auth switch`.
4. After cloning, the skill writes `user.name` and `user.email` with repo-local Git config only.
5. The agent continues its regular or pipeline workflow.

## Document Migration

- Replace the owner/account/email tables in all v2 persona documents with the mandatory skill invocation.
- Replace the duplicate identity section in `_shared/engineer-baseline.md` with the same invocation, so deployment concatenation cannot restore outdated mappings.
- Update the deployment runbook to install the new skill for each relevant bot runtime.

## Validation

- Validate the skill directory with the skill-creator validator.
- Check the configuration has mappings for both allowlisted owners and the fallback account.
- Verify the persona documents and shared baseline contain no account/email mapping and reference `wm4n.repo-identity`.
- Run `git diff --check`.
