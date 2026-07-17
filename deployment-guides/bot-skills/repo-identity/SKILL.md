---
name: repo-identity
description: Use when a software-development task needs to select the GitHub account for a known repository owner before running `gh` or remote Git operations.
---

# Repo Identity

Select the GitHub account and its repo-local Git identity for the target repository.

## Rule

1. Determine the target repository owner. If it cannot be determined, stop and ask a human.
2. Read `config.toml`.
3. Select the account:

   ```text
   if owner is in routing.cac_owners:
       account = routing.cac_account
   else:
       account = routing.default_account
   ```

4. Switch to that account before running remote Git or GitHub CLI operations:

   ```bash
   gh auth switch --hostname github.com --user <account>
   ```

5. After cloning, use the matching `[accounts.<account>]` values to set local Git identity:

   ```bash
   git -C <repo> config user.name "<git_name>"
   git -C <repo> config user.email "<git_email>"
   ```

   Never use `git config --global`.

6. Continue the task.
