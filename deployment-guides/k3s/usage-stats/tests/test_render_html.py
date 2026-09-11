"""render_html.py 的測試。

幾何用純函數算，所以可以斷言座標 —— 這是選「程式產生 SVG」而非 JS 圖表庫的
主要理由（JS 庫渲染的結果測不到）。另外鎖住「零外部請求」與「每張圖都有表格」。
"""
import re
import unittest

from render_html import (
    SERIES_DARK, SERIES_LIGHT, hbar_geometry, render, rounded_top_path,
    stack_geometry, svg_hbars, svg_stacked,
)


def report_fixture():
    return {
        "since": "2026-09-09", "until": "2026-09-10", "timezone": "Asia/Taipei",
        "coverage": {"days_expected": 2, "days_present": 2, "missing_days": [],
                     "unparsable": 0, "unrecognised": []},
        "daily_tasks": {
            "2026-09-09": {"rick": {"human": 2, "bot_relay": 1, "cron": 5}},
            "2026-09-10": {"rick": {"human": 3, "bot_relay": 0, "cron": 4}}},
        "daily_conversations": {
            "2026-09-09": {"rick": {"new": 1, "continued": 0}},
            "2026-09-10": {"rick": {"new": 2, "continued": 1}}},
        "token_rows": [
            {"day": "2026-09-10", "bot": "rick", "model_id": "claude-opus-5",
             "model_variant": None,
             "tokens": {"input": 100, "output": 200, "cache_read": 900}}],
        "daily_cost": {"2026-09-10": {"rick": {"cli": 1.5, "pricebook": 0.0,
                                               "subscription": 0.0,
                                               "unavailable": 0.0}}},
        "active_users": {"rick": {"824": {"display_name": "william", "tasks": 5}}},
        "attribution": {"rick": {"attributed": {"824": {"input": 100}},
                                 "shared": {}, "unattributed": {},
                                 "coverage": 1.0}},
        "friction": {"rick": {"followup_median_seconds": 120.0,
                              "tasks_per_session": 1.5,
                              "abandoned_sessions": 1}},
        "failure_proxy": {"rick": {"sessions_created": 18,
                                   "sessions_with_output": 2, "gap": 16}},
        "by_channel": {"1528965074562191420": {"human": 5, "bot_relay": 1,
                                               "cron": 9}},
        "allowlist_bounds": {"rick": 1},
        "channel_names": {"1528965074562191420": "cac-dev-team"},
    }


class TestRoundedTopPath(unittest.TestCase):
    def test_produces_rounded_top_and_square_bottom(self):
        d = rounded_top_path(10, 20, 30, 40, 4)
        self.assertTrue(d.startswith("M 10,60"))   # 左下角 = y + h
        self.assertIn("Q", d)                       # 頂端兩個圓角
        self.assertTrue(d.endswith("Z"))

    def test_radius_clamped_when_bar_is_shorter_than_radius(self):
        d = rounded_top_path(0, 0, 10, 2, 4)
        # 半徑不可大於高度的一半，否則路徑會自交
        self.assertNotIn("Q 0,-", d)


class TestStackGeometry(unittest.TestCase):
    def test_segments_stack_upward_from_baseline(self):
        days = ["2026-09-09"]
        series = {"human": {"2026-09-09": 1}, "cron": {"2026-09-09": 1}}
        geo = stack_geometry(days, series, 200, 100)
        self.assertEqual(len(geo), 2)
        lower = [g for g in geo if g["key"] == "human"][0]
        upper = [g for g in geo if g["key"] == "cron"][0]
        self.assertGreater(lower["y"], upper["y"])   # y 越小越上面

    def test_two_pixel_gap_between_stacked_segments(self):
        days = ["d1"]
        series = {"a": {"d1": 10}, "b": {"d1": 10}}
        geo = sorted(stack_geometry(days, series, 200, 100), key=lambda g: g["y"])
        upper, lower = geo[0], geo[1]
        self.assertEqual(lower["y"] - (upper["y"] + upper["h"]), 2)

    def test_only_topmost_segment_is_flagged_top(self):
        days = ["d1"]
        series = {"a": {"d1": 1}, "b": {"d1": 1}}
        geo = stack_geometry(days, series, 200, 100)
        self.assertEqual(sum(1 for g in geo if g["top"]), 1)

    def test_zero_value_segments_are_omitted_entirely(self):
        days = ["d1"]
        series = {"a": {"d1": 5}, "b": {"d1": 0}}
        geo = stack_geometry(days, series, 200, 100)
        self.assertEqual([g["key"] for g in geo], ["a"])

    def test_all_zero_day_produces_no_geometry_without_dividing_by_zero(self):
        geo = stack_geometry(["d1"], {"a": {"d1": 0}}, 200, 100)
        self.assertEqual(geo, [])

    def test_bar_width_is_capped_so_few_days_do_not_look_absurd(self):
        # 只有兩天時按比例會算出接近 200px 的柱子
        geo = stack_geometry(["d1", "d2"], {"a": {"d1": 1, "d2": 1}}, 640, 180)
        for g in geo:
            self.assertLessEqual(g["w"], 48)

    def test_bars_stay_centred_in_their_slot_after_capping(self):
        geo = stack_geometry(["d1", "d2"], {"a": {"d1": 1, "d2": 1}}, 640, 180)
        first, second = sorted(geo, key=lambda g: g["x"])
        slot = (640 - 8) / 2.0
        self.assertAlmostEqual(second["x"] - first["x"], slot, places=6)

    def test_bars_do_not_overflow_the_plot_width(self):
        days = ["d%d" % i for i in range(7)]
        series = {"a": {d: 1 for d in days}}
        geo = stack_geometry(days, series, 400, 100)
        for g in geo:
            self.assertLessEqual(g["x"] + g["w"], 400)


class TestHbarGeometry(unittest.TestCase):
    def test_widths_are_proportional_to_value(self):
        rows = [("a", 100), ("b", 50)]
        geo = hbar_geometry(rows, 400, 100)
        self.assertAlmostEqual(geo[1]["w"], geo[0]["w"] / 2.0, places=6)

    def test_zero_max_does_not_divide_by_zero(self):
        self.assertEqual(hbar_geometry([("a", 0)], 400, 100)[0]["w"], 0)


class TestSvgOutput(unittest.TestCase):
    def test_stacked_svg_has_a_title_per_mark_for_native_tooltips(self):
        svg = svg_stacked(["d1"], {"human": {"d1": 3}}, {"human": "真人"}, "測試")
        self.assertEqual(svg.count("<title>"), 1)
        self.assertIn("真人", svg)

    def test_stacked_svg_includes_a_legend_when_two_or_more_series(self):
        svg = svg_stacked(["d1"], {"a": {"d1": 1}, "b": {"d1": 1}},
                          {"a": "甲", "b": "乙"}, "測試")
        self.assertIn('class="legend"', svg)

    def test_single_series_hbars_have_no_legend_box(self):
        svg = svg_hbars([("claude-opus-5", 100)], "測試")
        self.assertNotIn('class="legend"', svg)

    def test_values_are_escaped_so_model_names_cannot_inject_markup(self):
        svg = svg_hbars([("<script>x</script>", 5)], "測試")
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)


class TestRender(unittest.TestCase):
    def setUp(self):
        self.html = render(report_fixture())

    def test_makes_no_external_requests_at_all(self):
        for bad in ("<script src", "https://", "http://", "fetch(",
                    "@import", "cdn."):
            self.assertNotIn(bad, self.html, "發現外部請求: %s" % bad)

    def test_has_no_javascript_at_all(self):
        self.assertNotIn("<script", self.html)

    def test_defines_light_palette_on_bare_root_and_dark_in_media_query(self):
        self.assertIn(":root", self.html)
        self.assertIn("prefers-color-scheme: dark", self.html)
        for hex_value in SERIES_LIGHT:
            self.assertIn(hex_value, self.html)
        for hex_value in SERIES_DARK:
            self.assertIn(hex_value, self.html)

    def test_every_chart_is_accompanied_by_a_table(self):
        # 調色盤驗證器對 light mode 的 aqua 給了對比 WARN，規則要求
        # 「可見標籤或表格檢視」補償，所以表格是硬需求不是裝飾
        self.assertEqual(self.html.count("<svg"), self.html.count("</svg>"))
        self.assertGreaterEqual(self.html.count("<table"), self.html.count("<svg"))

    def test_states_timezone_and_range(self):
        self.assertIn("Asia/Taipei", self.html)
        self.assertIn("2026-09-09", self.html)

    def test_carries_the_same_caveats_as_the_text_report(self):
        self.assertIn("僅含成功", self.html)
        self.assertIn("摩擦", self.html)
        self.assertIn("allowlist", self.html)

    def test_never_labels_a_metric_as_satisfaction(self):
        for match in re.finditer("滿意", self.html):
            self.assertEqual(self.html[max(0, match.start() - 2):match.start()],
                             "不是")

    def test_body_paints_its_own_background(self):
        self.assertIn("body", self.html)
        self.assertIn("--surface", self.html)

    def test_wide_tables_scroll_inside_their_own_container(self):
        self.assertIn("overflow-x", self.html)


if __name__ == "__main__":
    unittest.main()
