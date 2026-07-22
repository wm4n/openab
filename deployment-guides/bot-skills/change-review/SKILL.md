---
name: change-review
description: 當收到一個 PR URL 或新 push（SHA）並被要求 review、或人類明確要求正式 code review 時使用。單純問問題、討論做法時不要用。
---

# change-review

## 角色 D：PR 複審

觸發：被 @ 且訊息含 PR 連結（github.com/.../pull/數字）或 PR 編號。

1. 用內建 `/review <PR 網址或編號>` 審這個 PR。
2. 以 COMMENT 形式把發現貼到 PR（不要用 GitHub Approve）。
3. 回報 Builder（環境變數 `$HANDOFF_BUILDER` 的值，原樣貼上）：
   - 有問題：`$HANDOFF_BUILDER changes requested:<重點清單>,PR=<URL>`
   - 沒問題：`$HANDOFF_BUILDER clean，無 blocking 問題，PR=<URL>`
4. 絕不 merge、絕不 approve PR。
