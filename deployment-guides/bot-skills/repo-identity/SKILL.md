---
name: repo-identity
description: 選擇目標 GitHub repository 的帳號並設定 repo-local Git 署名。處理任何需要 `git` 或 `gh` 操作的軟體開發任務時使用，包含 clone、fetch、push、開 PR、Issue 或 review；在這些操作前必須先完成身份設定。
---

# Repo Identity

根據目標 `owner/repo` 與呼叫 bot 的 persona，從同目錄 `config.toml` 選擇 GitHub 帳號與 repo-local Git 署名。設定檔是 owner 分流與身份資料的唯一來源，不可將值複製到 persona 或 pipeline 文件。

## 必要輸入

- 目標 repository 的 `owner/repo`。
- 呼叫者 persona：`rick`、`morty` 或 `summer`。

若無法從任務、Jira、GitHub URL 或既有 repo 判斷 owner，停止並詢問人類；不得猜測。

## 操作流程

1. 讀取同目錄的 `config.toml`。
2. 若 owner 在 `routing.cac_owners`，選擇 `cac-william`；否則選擇 `routing.default_account`。
3. 在 clone、fetch、push、開 PR、Issue 或 review 前執行：

   ```bash
   gh auth switch --hostname github.com --user <selected-account>
   ```

4. clone 完目標 repository 後，選擇 Git identity：

   - 帳號為 `wm4n`：使用 `[accounts.wm4n]`。
   - 帳號為 `cac-william`：使用 `[personas.<persona>.accounts.cac-william]`。

5. 僅對目標 repository 寫入 local 署名：

   ```bash
   git -C <repo> config user.name "<git_name>"
   git -C <repo> config user.email "<git_email>"
   ```

6. 確認後才繼續任務的 `git` 或 `gh` 操作。

## 安全限制

- 絕不使用 `git config --global` 設定署名。
- 絕不將 token 寫入 `config.toml`、Discord、Jira 或 GitHub。
- 絕不將 `gh auth status`、`~/.config/gh/hosts.yml`、`git remote -v` 的輸出貼到 Discord。
