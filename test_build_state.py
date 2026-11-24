#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建状态与幂等写入单测（标准库 unittest，全程用临时目录，不碰真实产物）。

    ../.venv/bin/python -m unittest test_build_state -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

import build_state as bs


class TestVersionResolve(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        os.makedirs(os.path.join(self.base, "data"))
        for name in bs.SOURCE_FILES:
            with open(os.path.join(self.base, name), "w", encoding="utf-8") as f:
                f.write("# " + name + "\n")
        self._write_all("2026.12")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_all(self, v: str):
        with open(os.path.join(self.base, "data", "all-2026.json"), "w", encoding="utf-8") as f:
            json.dump({"year": 2026, "v": v, "days": {}}, f)

    def test_first_run_keeps_existing_version(self):
        self.assertEqual({2026: "2026.12"}, bs.resolve_versions(self.base, [2026]))

    def test_no_source_change_no_bump(self):
        v = bs.resolve_versions(self.base, [2026])
        bs.commit(self.base, v)
        self.assertEqual({2026: "2026.12"}, bs.resolve_versions(self.base, [2026]))

    def test_source_change_bumps_once(self):
        v = bs.resolve_versions(self.base, [2026])
        bs.commit(self.base, v)
        with open(os.path.join(self.base, "observances.py"), "a", encoding="utf-8") as f:
            f.write("# 新增一条节日\n")
        self.assertEqual({2026: "2026.13"}, bs.resolve_versions(self.base, [2026]))
        # 连续两次 resolve 不能重复 +1
        self.assertEqual({2026: "2026.13"}, bs.resolve_versions(self.base, [2026]))
        bs.commit(self.base, bs.resolve_versions(self.base, [2026]))
        self.assertEqual({2026: "2026.13"}, bs.resolve_versions(self.base, [2026]))

    def test_never_downgrades_below_online_version(self):
        """1.64 踩过：线上手抬到 .9，硬编码 .8 重跑把版本降回去。"""
        v = bs.resolve_versions(self.base, [2026])
        bs.commit(self.base, v)
        self._write_all("2026.20")           # 模拟线上/产物版本更高
        with open(os.path.join(self.base, "curated.py"), "a", encoding="utf-8") as f:
            f.write("# 变更\n")
        self.assertEqual({2026: "2026.21"}, bs.resolve_versions(self.base, [2026]))

    def test_two_years_independent(self):
        self._write_all("2026.12")
        with open(os.path.join(self.base, "data", "all-2027.json"), "w", encoding="utf-8") as f:
            json.dump({"year": 2027, "v": "2027.7", "days": {}}, f)
        self.assertEqual({2026: "2026.12", 2027: "2027.7"},
                         bs.resolve_versions(self.base, [2026, 2027]))


class TestStableWrites(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = os.path.join(self.tmp.name, "cal.ics")

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_content_not_rewritten(self):
        body = "BEGIN:VCALENDAR\r\nDTSTAMP:20260101T000000Z\r\nEND:VCALENDAR\r\n"
        self.assertTrue(bs.write_ics_stable(self.p, body))
        self.assertFalse(bs.write_ics_stable(self.p, body))

    def test_only_dtstamp_change_is_ignored(self):
        a = "BEGIN:VCALENDAR\r\nDTSTAMP:20260101T000000Z\r\nSUMMARY:元旦\r\nEND:VCALENDAR\r\n"
        b = a.replace("20260101T000000Z", "20261116T120000Z")
        bs.write_ics_stable(self.p, a)
        self.assertFalse(bs.write_ics_stable(self.p, b), "只有 DTSTAMP 变了不该重写")
        with open(self.p, encoding="utf-8", newline="") as f:
            self.assertEqual(a, f.read(), "原文件的旧 DTSTAMP 应原样保留")

    def test_real_content_change_is_written(self):
        a = "BEGIN:VCALENDAR\r\nDTSTAMP:20260101T000000Z\r\nSUMMARY:元旦\r\nEND:VCALENDAR\r\n"
        b = a.replace("元旦", "春节")
        bs.write_ics_stable(self.p, a)
        self.assertTrue(bs.write_ics_stable(self.p, b))
        with open(self.p, encoding="utf-8", newline="") as f:
            self.assertIn("春节", f.read())

    def test_json_ignores_generated_timestamp(self):
        p = os.path.join(self.tmp.name, "report.json")
        obj = {"counts": {"2026": 849}, "generated": "2026-11-16T12:00:00+08:00"}
        self.assertTrue(bs.write_json_stable(p, obj, volatile=("generated",)))
        obj2 = dict(obj, generated="2026-11-17T09:00:00+08:00")
        self.assertFalse(bs.write_json_stable(p, obj2, volatile=("generated",)))
        obj3 = dict(obj2, counts={"2026": 850})
        self.assertTrue(bs.write_json_stable(p, obj3, volatile=("generated",)))


if __name__ == "__main__":
    unittest.main()
