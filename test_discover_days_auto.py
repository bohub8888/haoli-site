#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""discover_days_auto.py 单元测试。"""
import unittest

import discover_days_auto as d


SAMPLE_UN = """
<div class="view-content">
<h3>January</h3>
<div class="views-row">
<span class="field-content"><a href="https://www.un.org/en/observances/braille-day">World Braille Day</a></span>
<span>(<a href="http://undocs.org/en/A/RES/73/161">A/RES/73/161</a>)</span>
<div class="views-field views-field-field-event-date-1"><div class="field-content">04 Jan</div></div>
</div>
<div class="views-row">
<span class="field-content"><a href="https://www.un.org/en/observances/wetlands-day">World Wetlands Day</a></span>
<span>(<a href="http://undocs.org/en/A/RES/75/317">A/RES/75/317</a>)</span>
<div class="views-field views-field-field-event-date-1"><div class="field-content">02 Feb</div></div>
</div>
<div class="views-row">
<span class="field-content"><a href="https://www.un.org/en/observances/fake-day">Impossible Day</a></span>
<div class="views-field views-field-field-event-date-1"><div class="field-content">30 Feb</div></div>
</div>
<a href="https://www.un.org/en/observances/list">International Days and Weeks</a>
"""


class ParseUNTest(unittest.TestCase):
    def test_parses_name_date_resolution(self):
        items = d.parse_un(SAMPLE_UN)
        self.assertEqual(len(items), 2)  # 30 Feb 非法被丢弃
        braille = next(x for x in items if x["name_en"] == "World Braille Day")
        self.assertEqual(braille["mmdd"], "01-04")
        self.assertEqual(braille["resolution"], "A/RES/73/161")

    def test_invalid_date_dropped(self):
        items = d.parse_un(SAMPLE_UN)
        self.assertFalse(any(x["name_en"] == "Impossible Day" for x in items))

    def test_category_link_not_treated_as_holiday(self):
        items = d.parse_un(SAMPLE_UN)
        self.assertFalse(any("Days and Weeks" in x["name_en"] for x in items))

    def test_empty_input(self):
        self.assertEqual(d.parse_un(""), [])

    def test_new_un_entry_yields_candidate(self):
        """UN 新增节日（英文名不在已见基线）应产出候选。"""
        seen = {"World Braille Day"}
        first_run = False
        items = d.parse_un(SAMPLE_UN)
        candidates = []
        for it in items:
            en = it["name_en"]
            zh = d._UN_ZH.get(en)
            newly = en not in seen
            if zh:
                candidates.append(en)
            elif newly and not first_run:
                candidates.append(en)
        self.assertIn("World Wetlands Day", candidates)  # 新英文名被报出
        self.assertNotIn("World Braille Day", [c for c in candidates if c not in d._UN_ZH])


class DiffTest(unittest.TestCase):
    def test_known_name_not_reported(self):
        # 世界盲文日已在库 → 映射后不进候选
        known = {"世界盲文日"}
        zh = d._UN_ZH.get("World Braille Day")
        self.assertIn(zh, known)  # 证明映射已校准到库内真实名

    def test_all_mapped_names_point_to_real_library_names(self):
        # 每个映射的中文名都应是库里真实存在的（防止误报）
        known = d._known_names()
        missed = [zh for zh in d._UN_ZH.values() if zh not in known]
        self.assertEqual(missed, [], f"映射表有库里不存在的名字: {missed}")


class CCTVTest(unittest.TestCase):
    def test_authority_required(self):
        raw = '<p>某公司在2024年5月10日决定将每年6月1日设立为欢乐节</p>'
        self.assertEqual(d.parse_cctv(raw, set()), [])  # 非权威机构 → 放弃

    def test_redline_dropped(self):
        raw = ('<p>2024年全国人大常委会决定将每年6月1日设立为'
             '台湾光复纪念日</p>')
        self.assertEqual(d.parse_cctv(raw, set()), [])  # 红线 → 放弃

    def test_known_name_not_reported(self):
        raw = ('<p>2014年全国人大常委会决定将每年12月4日设立为'
             '国家宪法日</p>')
        self.assertEqual(d.parse_cctv(raw, {"国家宪法日"}), [])  # 已在库

    def test_valid_new_holiday_captured(self):
        raw = ('<p>2026年全国人大常委会决定将每年9月3日设立为'
             '抗战胜利纪念日</p>')
        out = d.parse_cctv(raw, set())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name_zh"], "抗战胜利纪念日")
        self.assertEqual(out[0]["mmdd"], "09-03")

    def test_no_year_dropped(self):
        raw = '<p>全国人大常委会决定将每年9月3日设立为抗战胜利纪念日</p>'
        self.assertEqual(d.parse_cctv(raw, set()), [])  # 无年份 → 旧闻放弃


if __name__ == "__main__":
    unittest.main(verbosity=2)
