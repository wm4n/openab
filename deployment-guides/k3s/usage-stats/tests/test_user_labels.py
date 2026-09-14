"""使用者顯示名稱：設定檔對照優先於 sender_context 帶的 display_name。

跟 channel_label 同一套邏輯 —— 查得到用查到的，查不到就退回既有值，
絕不留空白。額外鎖住：每位使用者的任務數明細要出現在全部三種輸出格式。
"""
import unittest

from report import build_report, load_config, render_md, render_text, user_label


def task(dedup_key, sender_id="824", display_name="william", bot="rick",
         source="human", ts="2026-09-10T06:00:00Z", session_id="s1"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "sender_id": sender_id, "display_name": display_name,
            "session_id": session_id, "occurred_at": ts}


class TestUserLabel(unittest.TestCase):
    def test_configured_override_wins_over_display_name(self):
        self.assertEqual(
            user_label("824", "wm4n", {"824": "William Chao"}), "William Chao")

    def test_falls_back_to_display_name_when_not_configured(self):
        self.assertEqual(user_label("824", "wm4n", {}), "wm4n")

    def test_falls_back_to_raw_sender_id_when_nothing_else_available(self):
        self.assertEqual(user_label("824", None, {}), "824")

    def test_none_user_names_is_treated_as_empty(self):
        self.assertEqual(user_label("824", "wm4n", None), "wm4n")


class TestBuildReportCarriesUserNames(unittest.TestCase):
    def test_user_names_from_config_appear_in_report(self):
        cfg = load_config(None)
        cfg["user_names"] = {"824": "William Chao"}
        rep = build_report([task("d:1")], [], cfg, "2026-09-09", "2026-09-10", {})
        self.assertEqual(rep["user_names"]["824"], "William Chao")

    def test_defaults_to_empty_dict_when_not_configured(self):
        rep = build_report([task("d:1")], [], load_config(None),
                           "2026-09-09", "2026-09-10", {})
        self.assertEqual(rep["user_names"], {})


class TestRenderersShowPerUserTaskCounts(unittest.TestCase):
    def _report(self, user_names=None):
        cfg = load_config(None)
        cfg["user_names"] = user_names or {}
        return build_report([task("d:1", sender_id="824", display_name="wm4n"),
                             task("d:2", sender_id="824", display_name="wm4n"),
                             task("d:3", sender_id="999", display_name="Alice")],
                            [], cfg, "2026-09-09", "2026-09-10", {})

    def test_text_report_shows_configured_name_and_task_count(self):
        out = render_text(self._report({"824": "William Chao"}))
        self.assertIn("William Chao", out)
        self.assertIn("2 個任務", out)

    def test_markdown_report_has_a_per_user_table(self):
        out = render_md(self._report({"824": "William Chao"}))
        self.assertIn("William Chao", out)
        # 兩位使用者都要各自成一列，不能只顯示人數彙總
        self.assertIn("Alice", out)

    def test_html_report_has_a_per_user_table(self):
        import render_html
        html = render_html.render(self._report({"824": "William Chao"}))
        self.assertIn("William Chao", html)
        self.assertIn("Alice", html)


if __name__ == "__main__":
    unittest.main()
