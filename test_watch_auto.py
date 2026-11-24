#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch_auto 解析器单测：JSON-LD + 新闻通稿双通道 + 强闸门。"""
import datetime as dt
import unittest

import watch_auto as w


class TestExtractJSONLD(unittest.TestCase):
    def test_single_event(self):
        html = '''<script type="application/ld+json">{"@type":"Event",
            "startDate":"2027-11-09","endDate":"2027-11-12"}</script>'''
        self.assertEqual(w.extract_event_dates(html),
                         (dt.date(2027, 11, 9), dt.date(2027, 11, 12)))

    def test_iso_datetime(self):
        html = '''<script type="application/ld+json">{"@type":"Event",
            "startDate":"2026-11-16T09:00:00+02:00",
            "endDate":"2026-11-19T18:00:00+02:00"}</script>'''
        self.assertEqual(w.extract_event_dates(html),
                         (dt.date(2026, 11, 16), dt.date(2026, 11, 19)))

    def test_multi_year_takes_latest(self):
        html = '''<script type="application/ld+json">{"@type":"Event",
            "startDate":"2026-05-07","endDate":"2026-05-13"}</script>
            <script type="application/ld+json">{"@type":"Event",
            "startDate":"2021-02-25","endDate":"2021-03-03"}</script>'''
        self.assertEqual(w.extract_event_dates(html),
                         (dt.date(2026, 5, 7), dt.date(2026, 5, 13)))

    def test_ambiguous_same_year_abandon(self):
        html = '''<script type="application/ld+json">{"@type":"Event",
            "startDate":"2027-11-09","endDate":"2027-11-12"}</script>
            <script type="application/ld+json">{"@type":"Event",
            "startDate":"2027-12-01","endDate":"2027-12-05"}</script>'''
        self.assertEqual(w.extract_event_dates(html), (None, None))

    def test_no_event(self):
        self.assertEqual(w.extract_event_dates('<script type="application/ld+json">{"@type":"WebSite"}</script>'),
                         (None, None))
        self.assertEqual(w.extract_event_dates('<html>nothing</html>'), (None, None))


class TestNewsParse(unittest.TestCase):
    """新闻通稿解析：命中/旧闻放弃/歧义/跨月/地点/关键词。"""
    hint = "2027-11-05"

    def test_hit_with_year(self):
        raw = '<div>第十届进博会将于2027年11月5日至10日在上海举办。</div>'
        r = w.parse_news_dates(raw, ["进博会", "进口博览会"], 2027, self.hint)
        self.assertEqual(r[0], dt.date(2027, 11, 5))
        self.assertEqual(r[1], dt.date(2027, 11, 10))
        self.assertEqual(r[2], "上海")

    def test_old_news_no_year_abandon(self):
        # 往届旧闻：无年份 → 必须放弃（否则拿旧日期冒充新定档）
        raw = '<div>第九届中国国际进口博览会将于11月5日至10日在上海举行。</div>'
        self.assertIsNone(w.parse_news_dates(raw, ["进口博览会"], 2027, self.hint))

    def test_wrong_year_abandon(self):
        raw = '<div>第八届进博会将于2024年11月5日至10日在上海举办。</div>'
        self.assertIsNone(w.parse_news_dates(raw, ["进博会"], 2027, self.hint))

    def test_keyword_mismatch_abandon(self):
        raw = '<div>某其他会议将于2027年11月5日在北京召开。</div>'
        self.assertIsNone(w.parse_news_dates(raw, ["进博会"], 2027, self.hint))

    def test_cross_month(self):
        # 广交会：4月15日至5月5日
        r = w.parse_news_dates('<div>第141届广交会将于2027年4月15日至5月5日在广州举办。</div>',
                               ["广交会"], 2027, "2027-04-15")
        self.assertEqual(r[0], dt.date(2027, 4, 15))
        self.assertEqual(r[1], dt.date(2027, 5, 5))
        self.assertEqual(r[2], "广州")

    def test_ambiguous_abandon(self):
        raw = ('<div>进博会将于2027年11月5日在上海举办。</div>'
               '<div>进博会将于2027年11月20日在上海举办。</div>')
        r = w.parse_news_dates(raw, ["进博会"], 2027, self.hint)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "AMBIG")

    def test_single_day(self):
        r = w.parse_news_dates('<div>全国人大五次会议将于2027年3月5日在北京开幕。</div>',
                               ["人大"], 2027, "2027-03-05")
        self.assertEqual(r[0], dt.date(2027, 3, 5))
        self.assertEqual(r[1], dt.date(2027, 3, 5))

    def test_html_noise_cleaned(self):
        raw = '<div class="x">第十届进博会将于<span>2027年</span>11月5日至10日在上海举办。</div>'
        r = w.parse_news_dates(raw, ["进博会"], 2027, self.hint)
        self.assertEqual(r[0], dt.date(2027, 11, 5))

    def test_out_of_window_abandon(self):
        # 年份对但离预期太远（1月距11月超300天）
        raw = '<div>进博会将于2027年1月1日在上海举办。</div>'
        self.assertIsNone(w.parse_news_dates(raw, ["进博会"], 2027, self.hint))


class TestGate(unittest.TestCase):
    def test_pass(self):
        self.assertTrue(w.gate(dt.date(2027, 11, 9), dt.date(2027, 11, 12), "2027-11-09")[0])

    def test_out_of_window(self):
        ok, why = w.gate(dt.date(2026, 11, 9), dt.date(2026, 11, 12), "2027-11-09")
        self.assertFalse(ok)
        self.assertIn("超过", why)

    def test_end_before_start(self):
        ok, why = w.gate(dt.date(2026, 3, 19), dt.date(2026, 3, 15), "2026-03-15")
        self.assertFalse(ok)

    def test_too_long(self):
        ok, _ = w.gate(dt.date(2027, 1, 1), dt.date(2027, 3, 1), "2027-01-15")
        self.assertFalse(ok)

    def test_no_start(self):
        self.assertFalse(w.gate(None, dt.date(2027, 11, 12), "2027-11-09")[0])


class TestEntryGen(unittest.TestCase):
    def test_entry_passes_validate_shape(self):
        cfg = {"url": "https://websummit.com/", "tag": "会议",
               "scope": "world", "place": "葡萄牙里斯本"}
        line = w.make_entry_line("Web Summit", dt.date(2027, 11, 9), dt.date(2027, 11, 12), cfg)
        self.assertIn('C("2027-11-09", "2027-11-12", "Web Summit"', line)
        self.assertIn('"https://websummit.com/"', line)
        self.assertIn('"A"', line)
        self.assertIn(w.AUTO_MARK, line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
