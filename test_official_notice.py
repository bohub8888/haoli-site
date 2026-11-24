#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""官方公告解析与 diff 校验的单测（标准库 unittest，无第三方依赖）。

    ../.venv/bin/python -m unittest test_official_notice -v
"""

from __future__ import annotations

import datetime as dt
import json
import os
import unittest

import check_official_notice as con
import cn_official as cn

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "data", "official-notices", "2027.json")

# 2027 年通知正文的逐字副本（与 gov.cn 缓存同源）。用作解析回归的基准样本。
TEXT_2027 = (
    "一、元旦： 1月1日（周五）至3日（周日）放假，共3天。 "
    "二、春节： 2月5日（农历除夕、周五）至13日（农历正月初八、周六）放假调休，共9天。"
    "1月31日（周日）、2月14日（周日）上班。 "
    "三、清明节： 4月3日（周六）至5日（周一）放假，共3天。 "
    "四、劳动节： 5月1日（周六）至5日（周三）放假调休，共5天。5月8日（周六）上班。 "
    "五、端午节： 6月9日（周三）放假，共1天。 "
    "六、中秋节： 9月15日（周三）放假，共1天。 "
    "七、国庆节： 10月1日（周五）至7日（周四）放假调休，共7天。"
    "9月26日（周日）、10月9日（周六）上班。"
)


class TestParse(unittest.TestCase):

    def test_2027_seven_sections(self):
        r = con.parse_notice(TEXT_2027, 2027)
        self.assertEqual(7, len(r["sections"]))
        self.assertEqual(["元旦", "春节", "清明节", "劳动节", "端午节", "中秋节", "国庆节"],
                         [s["name"] for s in r["sections"]])

    def test_2027_dates_match_local_table(self):
        """解析结果必须与 cn_official.py 逐日一致 —— 这是校验器的最终目的。"""
        r = con.parse_notice(TEXT_2027, 2027)
        self.assertEqual(cn.off_dates(2027), r["off"])
        self.assertEqual(cn.workday_dates(2027), r["work"])
        self.assertEqual(29, len(r["off"]))
        self.assertEqual(5, len(r["work"]))
        self.assertEqual([], r["checks"], "公告写的共 N 天必须与解析区间长度一致")

    def test_regression_lunar_eighth_is_not_a_section(self):
        """「农历正月初八、周六」里的「八、」曾被误判为节标题，把春节整段切碎。"""
        heads = [m.group(2) for m in con.SECTION_HEAD.finditer(TEXT_2027)]
        self.assertEqual(7, len(heads))
        self.assertNotIn("周六", heads)
        self.assertIn("春节", heads)

    def test_month_inheritance(self):
        """「至3日」省略月份，继承前一个 token 的月。"""
        self.assertEqual([(1, 1), (1, 3)], con._tokens("1月1日（周五）至3日（周日）"))
        self.assertEqual([(9, 26), (10, 9)], con._tokens("9月26日（周日）、10月9日（周六）"))

    def test_declared_days_mismatch_is_flagged(self):
        bad = TEXT_2027.replace("共9天", "共8天")
        r = con.parse_notice(bad, 2027)
        self.assertTrue(any("春节" in w for w in r["checks"]))

    def test_extract_body_drops_signature_and_preamble(self):
        full = ("国务院办公厅关于2027年部分节假日安排的通知 国办发明电〔2026〕10号 "
                "各省、自治区、直辖市人民政府：经国务院批准，现将2027年…具体安排通知如下。"
                + TEXT_2027 + " 鼓励单位和个人结合落实带薪年休假等制度。"
                " 国务院办公厅 2026年11月5日")
        body = con.extract_body(full, 2027)
        self.assertIn("国庆节", body)
        self.assertNotIn("2026年11月5日", body, "落款日期会被误解析成节日")
        self.assertNotIn("鼓励", body)


class TestCompare(unittest.TestCase):

    def test_match(self):
        r = con.parse_notice(TEXT_2027, 2027)
        c = con.compare(2027, r)
        self.assertTrue(con.is_match(c))
        for k in ("missing_off", "extra_off", "missing_work", "extra_work", "parse_warnings"):
            self.assertEqual([], c[k], k)

    def test_detect_drift(self):
        """模拟本地表被改错一天，必须报差异。"""
        r = con.parse_notice(TEXT_2027, 2027)
        fake = set(r["off"])
        fake.add(dt.date(2027, 12, 25))
        r2 = dict(r, off=fake)
        c = con.compare(2027, r2)
        self.assertFalse(con.is_match(c))
        self.assertEqual(["2027-12-25"], c["missing_off"])


class TestNextYearWarning(unittest.TestCase):

    def test_before_window_is_quiet(self):
        w = con.next_year_warning(dt.date(2026, 6, 1), None)
        self.assertFalse(w["urgent"])

    def test_notice_published_but_no_data_is_urgent(self):
        w = con.next_year_warning(dt.date(2026, 11, 16), {"year": 2027, "text": TEXT_2027})
        # 2027 已在库，所以不急；换成还没入库的 2028 场景
        self.assertFalse(w["urgent"])
        w2 = con.next_year_warning(dt.date(2027, 11, 16), {"year": 2028, "text": TEXT_2027})
        self.assertTrue(w2["urgent"])
        self.assertFalse(w2["data_present"])

    def test_no_notice_mid_november_is_urgent(self):
        w = con.next_year_warning(dt.date(2027, 11, 20), None)
        self.assertTrue(w["urgent"])


class TestLocalTable(unittest.TestCase):

    def test_spans_and_workdays_sane(self):
        for y in cn.covered_years():
            for a, b, n, d in cn.CN_OFFICIAL[y]:
                self.assertLessEqual(a, b, f"{y} {n} 区间倒挂")
                self.assertEqual(y, a.year)
                self.assertEqual(y, b.year)
            off, work = cn.off_dates(y), cn.workday_dates(y)
            self.assertTrue(off.isdisjoint(work), f"{y} 同一天既放假又补班")

    def test_official_cache_exists_and_is_consistent(self):
        self.assertTrue(os.path.exists(CACHE), "2027 官方原文缓存应随仓库提供，保证离线可校验")
        with open(CACHE, encoding="utf-8") as f:
            snap = json.load(f)
        self.assertIn("www.gov.cn", snap["url"])
        self.assertIn("春节", snap["text"])
        r = con.parse_notice(snap["text"], 2027)
        self.assertEqual(cn.off_dates(2027), r["off"])


if __name__ == "__main__":
    unittest.main()
