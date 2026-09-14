"""「誰在燒量」的逐使用者 token + 花費明細，三種輸出格式都要看得到。

之前只有 text 格式印出歸因覆蓋率（一個百分比），三種格式都沒有印出實際
歸因到每個人的 token 與花費明細，html 甚至完全沒有成本區塊——這裡補上，
並確認 shared／unattributed 兩個桶不會被靜默省略。
"""
import unittest

from report import build_report, load_config, render_md, render_text


def task(dedup_key, sender_id="824", session_id="s1", bot="rick",
         source="human", ts="2026-09-10T06:00:00Z"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "sender_id": sender_id, "display_name": "william",
            "session_id": session_id, "occurred_at": ts}


def usage(usage_key, tokens=None, bot="rick", cost=None,
          cost_source="subscription", session_id="s1", origin="main",
          model="claude-opus-5"):
    return {"bot": bot, "usage_key": usage_key,
            "tokens": {} if tokens is None else tokens,
            "model_id": model, "model_variant": None,
            "occurred_at": "2026-09-10T06:05:00Z",
            "cost": cost, "cost_source": cost_source,
            "session_id": session_id, "origin": origin}


class TestBurnRowsAppearInAllFormats(unittest.TestCase):
    def _report(self, user_names=None):
        cfg = load_config(None)
        cfg["user_names"] = user_names or {}
        tasks = [task("d:1", sender_id="824", session_id="sA"),
                 task("d:2", sender_id="999", session_id="sB")]
        usages = [usage("k1", {"input": 100, "output": 50}, session_id="sA",
                        cost=1.5, cost_source="cli", origin="session_cost"),
                  usage("k2", {"input": 20}, session_id="sB")]
        return build_report(tasks, usages, cfg, "2026-09-09", "2026-09-10", {})

    def test_report_carries_cost_attribution(self):
        rep = self._report()
        self.assertIn("cost_attribution", rep)
        self.assertAlmostEqual(
            rep["cost_attribution"]["rick"]["attributed"]["824"], 1.5)

    def test_text_report_shows_per_user_tokens_and_cost(self):
        out = render_text(self._report({"824": "William Chao"}))
        self.assertIn("William Chao", out)
        self.assertIn("input=100", out)
        self.assertIn("1.5000", out)

    def test_markdown_report_has_a_burn_rate_table(self):
        out = render_md(self._report({"824": "William Chao"}))
        self.assertIn("誰在燒量", out)
        self.assertIn("William Chao", out)
        self.assertIn("input=100", out)
        self.assertIn("1.5000", out)

    def test_html_report_has_a_burn_rate_table_and_cost_section(self):
        import render_html
        html = render_html.render(self._report({"824": "William Chao"}))
        self.assertIn("誰在燒量", html)
        self.assertIn("William Chao", html)
        self.assertIn("input=100", html)
        self.assertIn("1.5000", html)
        # 之前 html 完全沒有成本區塊
        self.assertIn("<h2>成本</h2>", html)

    def test_shared_bucket_is_not_silently_dropped(self):
        cfg = load_config(None)
        tasks = [task("d:1", sender_id="824", session_id="sA"),
                 task("d:2", sender_id="999", session_id="sA")]  # 兩人共用
        usages = [usage("k1", {"input": 40}, session_id="sA")]
        rep = build_report(tasks, usages, cfg, "2026-09-09", "2026-09-10", {})
        out = render_md(rep)
        # 這句話跟通用限制說明裡的「共用」不同——要是實際被算進 shared
        # 桶的那一列，不能只靠字面上「共用」兩字（那個字在說明文字裡本來就有）
        self.assertIn("input=40", out)
        self.assertIn("多人共用 session", out)


if __name__ == "__main__":
    unittest.main()
