"""頻道維度：分組、名稱查表、以及未知頻道的處理。"""
import unittest

from aggregate import tasks_by_channel
from report import build_report, channel_label, load_config, render_md, render_text


def task(dedup_key, channel_id="1528965074562191420", source="human",
         bot="rick", ts="2026-09-10T06:00:00Z"):
    return {"bot": bot, "dedup_key": dedup_key, "source": source,
            "channel_id": channel_id, "sender_id": "824",
            "display_name": "william", "session_id": "s1", "occurred_at": ts}


class TestTasksByChannel(unittest.TestCase):
    def test_groups_by_channel_with_three_sources(self):
        rows = [task("d:1", "c1"), task("d:2", "c1", source="cron"),
                task("d:3", "c2")]
        got = tasks_by_channel(rows)
        self.assertEqual(got["c1"], {"human": 1, "bot_relay": 0, "cron": 1})
        self.assertEqual(got["c2"]["human"], 1)

    def test_deduplicates_before_grouping(self):
        got = tasks_by_channel([task("d:1", "c1"), task("d:1", "c1")])
        self.assertEqual(got["c1"]["human"], 1)

    def test_task_without_channel_id_goes_to_unknown_not_dropped(self):
        rows = [dict(task("d:1"), channel_id=None)]
        self.assertEqual(tasks_by_channel(rows)["unknown"]["human"], 1)

    def test_empty_input(self):
        self.assertEqual(tasks_by_channel([]), {})


class TestChannelLabel(unittest.TestCase):
    def test_resolves_configured_name(self):
        self.assertEqual(channel_label("c1", {"c1": "cac-dev-team"}),
                         "cac-dev-team")

    def test_falls_back_to_the_raw_id_so_it_is_never_blank(self):
        self.assertEqual(channel_label("c9", {}), "c9")

    def test_unknown_bucket_gets_a_readable_label(self):
        self.assertEqual(channel_label("unknown", {}), "（無頻道資訊）")


class TestRenderersShowChannels(unittest.TestCase):
    def _report(self, names):
        cfg = load_config(None)
        cfg["channel_names"] = names
        return build_report([task("d:1", "1528965074562191420")], [], cfg,
                            "2026-09-09", "2026-09-10", {})

    def test_report_carries_by_channel(self):
        rep = self._report({})
        self.assertIn("by_channel", rep)
        self.assertIn("1528965074562191420", rep["by_channel"])

    def test_text_report_uses_the_configured_name_not_the_raw_id(self):
        out = render_text(self._report({"1528965074562191420": "cac-dev-team"}))
        self.assertIn("cac-dev-team", out)

    def test_markdown_report_has_a_channel_table(self):
        out = render_md(self._report({"1528965074562191420": "cac-dev-team"}))
        self.assertIn("頻道", out)
        self.assertIn("cac-dev-team", out)

    def test_html_report_has_a_channel_table(self):
        import render_html
        html = render_html.render(
            self._report({"1528965074562191420": "cac-dev-team"}))
        self.assertIn("cac-dev-team", html)


if __name__ == "__main__":
    unittest.main()
