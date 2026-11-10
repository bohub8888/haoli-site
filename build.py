#!/usr/bin/env python3
"""蚝历 · 节假日日历构建脚本（多年度）。

设计目标：
  - 数据按年构建（一年一个数据目录），但**页面只有一页**：根 index.html 展示
    「常青窗口」（今年 + 明年若可用），/{year}/ 老链接一律跳回首页；
  - 中国内地：法定假日按国务院通知，农历节日与 24 节气由 cnlunar 计算，不手写；
  - 中国港澳台：整理自当地公布的公众假期，统一写作「中国香港 / 中国澳门 / 中国台湾」；
  - 海外 60+ 国家：由 holidays（vacanza/holidays）库按年计算，名称经 holiday_i18n 译为中文；
  - 全球大全：同一天、同一节日（按语义判定，见 holiday_canon）合并成一条，描述里列国家；
    连续多日的连休再压成区间，避免逐日刷屏；
  - 所有 ics 统一 CRLF、统一 UID 命名空间（跨文件、跨年份都不重复）、统一 DTSTAMP；
  - 页面上的年份、说明、FAQ 全部由数据生成，不再手写，避免换年时漏改。

用法：
    SITE=https://你的域名 .venv/bin/python holiday-calendar-deploy/build.py
    YEARS=2026,2027 SITE=... .venv/bin/python ...     # 指定年份（默认 2026,2027）
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from collections import Counter
import hashlib

import cnlunar
import holidays as hlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import holiday_canon as canon  # noqa: E402
import holiday_i18n as i18n  # noqa: E402
import observances as obs  # noqa: E402  中国纪念日/宣传日/国际日总表（与 APK 共用）

BASE = os.path.dirname(os.path.abspath(__file__))
UID_DOMAIN = "haoli"
# 生成时刻（UTC）。订阅端靠 DTSTAMP 判断「这份日历里的这条变过没有」，
# 写死成常量就等于永远告诉对方「没变」——11-07 的常量一直被用到 11-09 的重建，
# 期间改过的条目在部分客户端上不会刷新。每次构建取当前时刻。
DTSTAMP = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
PRODID = "-//Haoli//Holiday Calendar//CN"

D = dt.date

YEARS = [int(x) for x in os.environ.get("YEARS", "2026,2027").split(",") if x.strip()]


def year_dir(y: int) -> str:
    return os.path.join(BASE, str(y))


def ics_dir(y: int) -> str:
    return os.path.join(year_dir(y), "ics")


# ---------------------------------------------------------------- 事件模型

class Ev:
    """一条日历事件。全天事件用 start/end（end 不含）。"""

    def __init__(self, start, end, summary, desc="", alarm=False):
        self.start = start
        self.end = end
        self.summary = summary
        self.desc = desc
        self.alarm = alarm


def one(day: D, summary: str, desc: str = "", alarm: bool = False) -> Ev:
    return Ev(day, day + dt.timedelta(days=1), summary, desc, alarm=alarm)


def span(a: D, b: D, summary: str, desc: str = "", alarm: bool = False) -> Ev:
    """含首含尾的区间。"""
    return Ev(a, b + dt.timedelta(days=1), summary, desc, alarm=alarm)


# ---------------------------------------------------------------- ICS 输出

def esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """RFC 5545：每行不超过 75 字节，超长折行。按 UTF-8 字节切，避免切坏汉字。"""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, chunk, size = [], [], 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        if size + b > (75 if not out else 74):
            out.append("".join(chunk))
            chunk, size = [], 0
        chunk.append(ch)
        size += b
    out.append("".join(chunk))
    return "\r\n ".join(out)


def write_ics(path: str, cal_name: str, events: list[Ev], prefix: str, year: int, cal_desc: str = "") -> int:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(cal_name)}",
        "X-WR-TIMEZONE:Asia/Shanghai",
        "X-WR-CALDESC:" + esc(cal_desc or f"蚝历 · 节假日日历（{year}）"),
    ]
    used: set[str] = set()
    for e in sorted(events, key=lambda x: (x.start, x.summary)):
        # UID 由「日期 + 标题」决定，不用序号：订阅是用 UID 认事件的，
        # 序号会因前面增删一条而整体位移，订阅者那边表现为事件重复或凭空消失。
        h = hashlib.sha1(e.summary.encode("utf-8")).hexdigest()[:8]
        uid = f"{prefix}-{year}{e.start:%m%d}-{h}@{UID_DOMAIN}"
        n = 1
        while uid in used:  # 同一天同名的极少（如某地重复条目），加后缀保证唯一
            n += 1
            uid = f"{prefix}-{year}{e.start:%m%d}-{h}-{n}@{UID_DOMAIN}"
        used.add(uid)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{DTSTAMP}",
            f"DTSTART;VALUE=DATE:{e.start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{e.end:%Y%m%d}",
            f"SUMMARY:{esc(e.summary)}",
        ]
        if e.desc:
            lines.append(f"DESCRIPTION:{esc(e.desc)}")
        lines += ["TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    body = "\r\n".join(fold(x) for x in lines) + "\r\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(body)
    return len(events)


# ---------------------------------------------------------------- 农历工具

def lunar(d: D):
    return cnlunar.Lunar(dt.datetime(d.year, d.month, d.day), godType="8char")


_cache: dict[int, tuple] = {}


def year_lunar(year: int):
    """一次遍历同时取节气表与农历索引，避免重复计算。"""
    if year in _cache:
        return _cache[year]
    terms: list[tuple[D, str]] = []
    index: dict[str, list[D]] = {}
    d = D(year, 1, 1)
    while d.year == year:
        x = lunar(d)
        t = x.todaySolarTerms
        if t and t != "无":
            terms.append((d, t))
        index.setdefault(f"{x.lunarMonth}-{x.lunarDay}", []).append(d)
        d += dt.timedelta(days=1)
    _cache[year] = (terms, index)
    return terms, index


def solar_terms(year: int) -> list[tuple[D, str]]:
    return year_lunar(year)[0]


def lunar_days(year: int) -> dict[str, list[D]]:
    """农历「月-日」→ 公历日期列表，用来定位除夕、元宵、中秋等。"""
    return year_lunar(year)[1]


# ---------------------------------------------------------------- 中国内地

# 国务院办公厅通知。文号未查到的不猜，只写发布机关与日期。
CN_SOURCE = {
    2026: "数据来源：国务院办公厅《关于 2026 年部分节假日安排的通知》，2025 年 11 月 4 日发布。",
    2027: "数据来源：国务院办公厅《关于 2027 年部分节假日安排的通知》（国办发明电〔2026〕10 号）。",
}

CN_OFFICIAL = {
    2026: [
        (D(2026, 1, 1), D(2026, 1, 3), "元旦假期", "1 月 1 日至 3 日放假，共 3 天。1 月 4 日（周日）上班。"),
        (D(2026, 2, 15), D(2026, 2, 23), "春节假期", "2 月 15 日（腊月廿八）至 23 日（正月初七）放假调休，共 9 天。2 月 14 日、2 月 28 日两个周六上班。"),
        (D(2026, 4, 4), D(2026, 4, 6), "清明节假期", "4 月 4 日至 6 日放假，共 3 天。"),
        (D(2026, 5, 1), D(2026, 5, 5), "劳动节假期", "5 月 1 日至 5 日放假调休，共 5 天。5 月 9 日（周六）上班。"),
        (D(2026, 6, 19), D(2026, 6, 21), "端午节假期", "6 月 19 日至 21 日放假，共 3 天。"),
        (D(2026, 9, 25), D(2026, 9, 27), "中秋节假期", "9 月 25 日至 27 日放假，共 3 天。"),
        (D(2026, 10, 1), D(2026, 10, 7), "国庆节假期", "10 月 1 日至 7 日放假调休，共 7 天。9 月 20 日、10 月 10 日两个周六上班。"),
    ],
    2027: [
        (D(2027, 1, 1), D(2027, 1, 3), "元旦假期", "1 月 1 日至 3 日放假，共 3 天。"),
        (D(2027, 2, 5), D(2027, 2, 13), "春节假期", "2 月 5 日（除夕）至 13 日（正月初八）放假调休，共 9 天。1 月 31 日、2 月 14 日上班。"),
        (D(2027, 4, 3), D(2027, 4, 5), "清明节假期", "4 月 3 日至 5 日放假，共 3 天。"),
        (D(2027, 5, 1), D(2027, 5, 5), "劳动节假期", "5 月 1 日至 5 日放假调休，共 5 天。5 月 8 日上班。"),
        (D(2027, 6, 9), D(2027, 6, 9), "端午节假期", "6 月 9 日放假，共 1 天。"),
        (D(2027, 9, 15), D(2027, 9, 15), "中秋节假期", "9 月 15 日放假，共 1 天。"),
        (D(2027, 10, 1), D(2027, 10, 7), "国庆节假期", "10 月 1 日至 7 日放假调休，共 7 天。9 月 26 日、10 月 9 日上班。"),
    ],
}

CN_WORKDAYS = {
    2026: [
        (D(2026, 1, 4), "调休上班（元旦）"),
        (D(2026, 2, 14), "调休上班（春节）"),
        (D(2026, 2, 28), "调休上班（春节）"),
        (D(2026, 5, 9), "调休上班（劳动节）"),
        (D(2026, 9, 20), "调休上班（国庆节）"),
        (D(2026, 10, 10), "调休上班（国庆节）"),
    ],
    2027: [
        (D(2027, 1, 31), "调休上班（春节）"),
        (D(2027, 2, 14), "调休上班（春节）"),
        (D(2027, 5, 8), "调休上班（劳动节）"),
        (D(2027, 9, 26), "调休上班（国庆节）"),
        (D(2027, 10, 9), "调休上班（国庆节）"),
    ],
}

# 农历节日：键是「农历月-日」，值是名称。除夕单独处理（正月初一前一天）。
CN_LUNAR_FEST = {
    "1-1": "春节（正月初一）",
    "1-15": "元宵节（正月十五）",
    "2-2": "龙抬头（二月初二）",
    "3-3": "上巳节（三月三）",
    "5-5": "端午节（五月初五）",
    "7-7": "七夕节（七月初七）",
    "7-15": "中元节（七月十五）",
    "8-15": "中秋节（八月十五）",
    "9-9": "重阳节（九月初九）",
    "10-1": "寒衣节（十月初一）",
    "10-15": "下元节（十月十五）",
    "12-8": "腊八节（腊月初八）",
    "12-23": "小年（腊月廿三）",
}

# 中国固定/浮动节日表已移到 observances.py —— 与 haoli-apk 的 gen_apk_data.py 共用，
# 避免两边各抄一份后漂移（「官网有、App 没有」就是这么来的）。


def build_china(y: int) -> list[Ev]:
    evs: list[Ev] = []
    src = CN_SOURCE[y]

    for a, b, name, desc in CN_OFFICIAL[y]:
        evs.append(span(a, b, name, desc + "\n" + src, alarm=True))
    for d, name in CN_WORKDAYS[y]:
        evs.append(one(d, name, "周末调休上班。"))

    for d, term in solar_terms(y):
        evs.append(one(d, f"节气 · {term}"))

    idx = lunar_days(y)
    for key, name in CN_LUNAR_FEST.items():
        for d in idx.get(key, []):
            evs.append(one(d, name, alarm=name.startswith(("春节", "端午", "中秋"))))

    # 除夕 = 正月初一前一天，直接由春节推，不猜腊月大小
    evs.append(one(idx["1-1"][0] - dt.timedelta(days=1), "除夕", alarm=True))

    # 中国纪念日 / 宣传日 / 国际日 / 洋节 / 电商节：固定日期 + 浮动日期 + 节气挂靠
    # （母亲节、感恩节、丰收节……）统一来自 observances，全量收录，不看权重。
    for o in obs.solar_of(y, solar_terms(y)):
        evs.append(one(o.date, o.name, o.note))

    return evs


# ---------------------------------------------------------------- 中国港澳台
# 香港：政府宪报公布的公众假期。撞周日者官方直接写成「翌日」，照原文。
# 澳门：第 60/2000 号行政命令公众假期 + 公职人员的补假日。
# 台湾：行政院人事行政总处办公日历表，官方以「连假」呈现，故用区间表达。

HK = {
    2026: [
        (D(2026, 1, 1), "元旦"),
        (D(2026, 2, 17), "农历年初一"),
        (D(2026, 2, 18), "农历年初二"),
        (D(2026, 2, 19), "农历年初三"),
        (D(2026, 4, 3), "耶稣受难节"),
        (D(2026, 4, 4), "耶稣受难节翌日"),
        (D(2026, 4, 6), "清明节翌日"),
        (D(2026, 4, 7), "复活节星期一翌日"),
        (D(2026, 5, 1), "劳动节"),
        (D(2026, 5, 25), "佛诞翌日"),
        (D(2026, 6, 19), "端午节"),
        (D(2026, 7, 1), "香港特别行政区成立纪念日"),
        (D(2026, 9, 26), "中秋节翌日"),
        (D(2026, 10, 1), "国庆日"),
        (D(2026, 10, 19), "重阳节翌日"),
        (D(2026, 12, 25), "圣诞节"),
        (D(2026, 12, 26), "圣诞节后第一个周日"),
    ],
    2027: [
        (D(2027, 1, 1), "元旦"),
        (D(2027, 2, 6), "农历年初一"),
        (D(2027, 2, 8), "农历年初三"),
        (D(2027, 2, 9), "农历年初四"),
        (D(2027, 3, 26), "耶稣受难节"),
        (D(2027, 3, 27), "耶稣受难节翌日"),
        (D(2027, 3, 29), "复活节星期一"),
        (D(2027, 4, 5), "清明节"),
        (D(2027, 5, 1), "劳动节"),
        (D(2027, 5, 13), "佛诞"),
        (D(2027, 6, 9), "端午节"),
        (D(2027, 7, 1), "香港特别行政区成立纪念日"),
        (D(2027, 9, 16), "中秋节翌日"),
        (D(2027, 10, 1), "国庆日"),
        (D(2027, 10, 8), "重阳节"),
        (D(2027, 12, 25), "圣诞节"),
        (D(2027, 12, 27), "圣诞节后第一个周日"),
    ],
}

MO = {
    2026: [
        (D(2026, 1, 1), "元旦"),
        (D(2026, 2, 17), "农历正月初一"),
        (D(2026, 2, 18), "农历正月初二"),
        (D(2026, 2, 19), "农历正月初三"),
        (D(2026, 4, 3), "耶稣受难日"),
        (D(2026, 4, 4), "复活节前日"),
        (D(2026, 4, 5), "清明节"),
        (D(2026, 4, 6), "复活节前日补假"),
        (D(2026, 4, 7), "清明节补假"),
        (D(2026, 5, 1), "劳动节"),
        (D(2026, 5, 24), "佛诞节"),
        (D(2026, 5, 25), "佛诞节补假"),
        (D(2026, 6, 19), "端午节"),
        (D(2026, 9, 26), "中秋节翌日"),
        (D(2026, 9, 28), "中秋节翌日补假"),
        (D(2026, 10, 1), "国庆日"),
        (D(2026, 10, 2), "国庆日翌日"),
        (D(2026, 10, 18), "重阳节"),
        (D(2026, 10, 19), "重阳节补假"),
        (D(2026, 11, 2), "追思节"),
        (D(2026, 12, 8), "圣母无原罪瞻礼"),
        (D(2026, 12, 20), "澳门特别行政区成立纪念日"),
        (D(2026, 12, 21), "澳门特别行政区成立纪念日补假"),
        (D(2026, 12, 22), "冬至"),
        (D(2026, 12, 24), "圣诞节前日"),
        (D(2026, 12, 25), "圣诞节"),
    ],
    2027: [
        (D(2027, 1, 1), "元旦"),
        (D(2027, 2, 6), "农历正月初一"),
        (D(2027, 2, 7), "农历正月初二"),
        (D(2027, 2, 8), "农历正月初三"),
        (D(2027, 2, 9), "农历正月初一补假"),
        (D(2027, 2, 10), "农历正月初二补假"),
        (D(2027, 3, 26), "耶稣受难日"),
        (D(2027, 3, 27), "复活节前日"),
        (D(2027, 3, 29), "复活节前日补假"),
        (D(2027, 4, 5), "清明节"),
        (D(2027, 5, 1), "劳动节"),
        (D(2027, 5, 3), "劳动节补假"),
        (D(2027, 5, 13), "佛诞节"),
        (D(2027, 6, 9), "端午节"),
        (D(2027, 9, 16), "中秋节翌日"),
        (D(2027, 10, 1), "国庆日"),
        (D(2027, 10, 2), "国庆日翌日"),
        (D(2027, 10, 4), "国庆日翌日补假"),
        (D(2027, 10, 8), "重阳节"),
        (D(2027, 11, 2), "追思节"),
        (D(2027, 12, 8), "圣母无原罪瞻礼"),
        (D(2027, 12, 20), "澳门特别行政区成立纪念日"),
        (D(2027, 12, 22), "冬至"),
        (D(2027, 12, 24), "圣诞节前日"),
        (D(2027, 12, 25), "圣诞节"),
        (D(2027, 12, 27), "圣诞节补假"),
    ],
}

# 台湾：三元组 (起, 止, 名称)，止为 None 表示单日。官方以连假公布，含周末。
TW = {
    2026: [
        (D(2026, 1, 1), None, "开国纪念日"),
        (D(2026, 2, 14), D(2026, 2, 22), "春节连假"),
        (D(2026, 2, 27), D(2026, 3, 1), "和平纪念日连假"),
        (D(2026, 4, 3), D(2026, 4, 6), "儿童节及清明节连假"),
        (D(2026, 5, 1), D(2026, 5, 3), "劳动节连假"),
        (D(2026, 6, 19), D(2026, 6, 21), "端午节连假"),
        (D(2026, 9, 25), D(2026, 9, 28), "中秋节及教师节连假"),
        (D(2026, 10, 9), D(2026, 10, 11), "国庆日连假"),
        (D(2026, 10, 24), D(2026, 10, 26), "光复节连假"),
        (D(2026, 12, 25), D(2026, 12, 27), "行宪纪念日连假"),
    ],
    2027: [
        (D(2027, 1, 1), D(2027, 1, 3), "开国纪念日连假"),
        (D(2027, 2, 4), D(2027, 2, 10), "春节连假"),
        (D(2027, 2, 27), D(2027, 3, 1), "和平纪念日连假"),
        (D(2027, 4, 3), D(2027, 4, 6), "儿童节及清明节连假"),
        (D(2027, 4, 30), D(2027, 5, 2), "劳动节连假"),
        (D(2027, 6, 9), None, "端午节"),
        (D(2027, 9, 15), None, "中秋节"),
        (D(2027, 9, 28), None, "教师节"),
        (D(2027, 10, 9), D(2027, 10, 11), "国庆日连假"),
        (D(2027, 10, 24), D(2027, 10, 26), "光复节连假"),
        (D(2027, 12, 24), D(2027, 12, 27), "行宪纪念日连假"),
        (D(2027, 12, 31), None, "2028 年元旦补假"),
    ],
}


def prefixed(prefix: str, rows) -> list[Ev]:
    return [one(d, f"{prefix} · {n}") for d, n in rows]


def tw_events(y: int) -> list[Ev]:
    out = []
    for a, b, name in TW[y]:
        if b is None:
            out.append(one(a, f"中国台湾 · {name}"))
        else:
            out.append(span(a, b, f"中国台湾 · {name}"))
    return out


# ---------------------------------------------------------------- 海外

class Country:
    """一个国家的产出：事件列表 + 用于合并的带标注条目。"""

    __slots__ = ("key", "zh", "region", "note", "evs", "tagged")

    def __init__(self, key, zh, region, note, evs, tagged):
        self.key, self.zh, self.region, self.note = key, zh, region, note
        self.evs, self.tagged = evs, tagged


def tag_rows(area: str, rows) -> list[tuple]:
    """(日期, 名称) → (日期, 地区, 规范键, 显示名, 是否推算, 是否补假)。"""
    out = []
    for d, n in rows:
        key, label, est, sub = canon.canonical(n, d, area)
        out.append((d, area, key, label, est, sub))
    return out


def evs_of(tagged) -> list[Ev]:
    return [one(d, f"{area} · {label}" + ("（补假）" if sub else "")) for d, area, _k, label, _e, sub in tagged]


def build_overseas(y: int) -> list[Country]:
    """返回各国数据。名称经 holiday_i18n 译中，再由 holiday_canon 归到规范键。"""
    out = []
    spring = lunar_days(y)["1-1"][0]  # 正月初一

    for code, key, zh, region, note in i18n.COUNTRIES:
        h = hlib.country_holidays(code, years=y, language="en_US")
        pairs: list[tuple[D, str]] = []
        for d, en in sorted(h.items()):
            # holidays 库把韩国 설날 算晚一天，改由 cnlunar 生成
            if code == "KR" and "Korean New Year" in en:
                continue
            for part in (x.strip() for x in i18n.zh_name(en, code).split(" / ")):
                if part:
                    pairs.append((d, part))
        if code == "KR":
            for i, label in enumerate(("春节", "春节初二", "春节初三")):
                pairs.append((spring + dt.timedelta(days=i), label))

        tagged, seen = [], set()
        for d, name in sorted(pairs):
            k, label, est, sub = canon.canonical(name, d, code)
            if (d, label, sub) in seen:
                continue
            seen.add((d, label, sub))
            tagged.append((d, zh, k, label, est, sub))
        out.append(Country(key, zh, region, note, evs_of(tagged), tagged))
    return out


def merge_semantic(tagged, threshold: int = 2) -> list[Ev]:
    """按「日期 + 规范键」合并：同一天、同一个节日的多国条目并成一条。

    只合并同义异名（元旦/元旦假期、劳动节/五一节/劳动者节……），
    不同节日即使撞在同一天也各自保留 —— 见 holiday_canon 的规则说明。
    """
    groups: dict[tuple[D, str], list[tuple[str, str, bool, bool]]] = {}
    for d, area, key, label, est, sub in tagged:
        groups.setdefault((d, key), []).append((area, label, est, sub))

    out: list[Ev] = []
    for (start, _key), items in groups.items():
        areas = sorted({a for a, _l, _e, _s in items})
        label = Counter(l for _a, l, _e, _s in items).most_common(1)[0][0]
        est = any(e for _a, _l, e, _s in items)
        sub = all(s for _a, _l, _e, s in items)
        if sub:
            label += "（补假）"
        if len(areas) < threshold:
            out.append(one(start, f"{areas[0]} · {label}"))
            continue
        unit = "个国家/地区" if any(a.endswith(("香港", "澳门", "台湾")) for a in areas) else "国"
        desc = f"包含 {len(areas)} {unit}：{'、'.join(areas)}。"
        if est:
            desc += "日期按天文推算，可能与当地最终公布相差一天。"
        out.append(Ev(start, start + dt.timedelta(days=1), f"{label}（{len(areas)} {unit}）", desc))
    return out


def collapse_runs(evs: list[Ev]) -> list[Ev]:
    """同一国家、同一节日的连续单日条目并成一条区间。

    缅甸新年、俄罗斯元旦假期这类是 5–9 天连休，逐日列出会刷屏，
    合并成「缅甸 · 缅甸新年」4/13–4/21 一条，日历上是一根连着的横条。
    """
    runs: dict[str, list[Ev]] = {}
    out: list[Ev] = []
    for e in evs:
        if (e.end - e.start).days == 1 and not e.desc.startswith("包含 "):
            runs.setdefault(e.summary, []).append(e)
        else:
            out.append(e)
    for summary, items in runs.items():
        items.sort(key=lambda x: x.start)
        cur = items[0]
        for e in items[1:]:
            if e.start == cur.end:
                cur = Ev(cur.start, e.end, summary)
            else:
                out.append(cur)
                cur = e
        out.append(cur)
    return out


# ---------------------------------------------------------------- 页面分组

DISPLAY_GROUPS: list[tuple[str, str, list[str]]] = [
    ("东亚", "east-asia", ["东亚"]),
    ("东南亚", "southeast", ["东南亚"]),
    ("南亚 · 中亚", "south-asia", ["南亚", "中亚"]),
    ("中东", "middle-east", ["中东"]),
    ("欧洲", "europe", ["欧洲"]),
    ("北美", "north-america", ["北美"]),
    ("南美", "south-america", ["南美"]),
    ("大洋洲", "oceania", ["大洋洲"]),
    ("非洲", "africa", ["非洲"]),
]


def china_nodes(y: int) -> list[tuple]:
    """大全里的中国节点：24 节气 + 农历传统节日。

    这两类在其他国家的数据里根本不存在（节气是中国独有，农历节日只有东亚几国），
    却是中文用户最在意的东西。之前只把法定假期放进大全，导致导入「全球」的人
    看不到立冬、重阳、腊八 —— 2026-11-07 用户实测发现，故补入。

    农历节日走 canon 规范键，与韩国/越南/新加坡的同一节日合并成一条（春节 → spring），
    不会出现同一天两条「春节」。
    """
    out: list[tuple] = []
    for d, term in solar_terms(y):
        out.append((d, "中国", f"节气:{term}", f"节气 · {term}", False, False))
    idx = lunar_days(y)
    for key, name in CN_LUNAR_FEST.items():
        base = name.split("（")[0]
        for d in idx.get(key, []):
            k, label, est, sub = canon.canonical(base, d, "中国")
            out.append((d, "中国", k, label, est, sub))
    # 除夕 = 正月初一前一天
    d0 = idx["1-1"][0] - dt.timedelta(days=1)
    k, label, est, sub = canon.canonical("除夕", d0, "中国")
    out.append((d0, "中国", k, label, est, sub))
    return out


def global_obs(y: int) -> list[Ev]:
    """全球日历里的「日子」：中国的全收，国际日原样收。

    老逻辑用「名字是否以世界/国际开头」判断，那是命名巧合不是分类：全国消防日、
    记者节、双十一全被漏掉，于是导入「全球大全」的人看不到中国的纪念日——同一张表、
    两个入口，一个有、一个没有。现在范围写在数据里（scope 字段），代码不再猜。

    不变量：中国日历里有的每一条，全球日历里都能找到对应条目。中国条目加「中国 · 」
    前缀，与「中国 · 春节假期」保持同一写法；国际日本身就是全球通称，不加前缀。
    """
    out: list[Ev] = []
    for o in obs.solar_of(y, solar_terms(y)):
        if o.scope == "world":
            out.append(one(o.date, o.name, o.note or "国际日 / 世界日，全球共同纪念。"))
        else:
            out.append(one(o.date, f"中国 · {o.name}", o.note or "中国法定假日、纪念日或传统节日。"))
    return out


def merge_days(glob: list[Ev], cand: list[Ev]) -> list[Ev]:
    """把候选「日子」并进全球日历，判断「这一天是不是已经说过了」。

    国际日看名字就够：当天标题里有「世界水日」，再单列一条就是重复。
    中国条目不能只看名字——「圣诞节（47 个国家/地区）」名字里虽然有圣诞节，
    但那 47 国里没有中国（中国不在 holidays 库里），直接跳过就等于把中国的圣诞节
    弄丢了。所以中国条目要求「已有条目的标题是中国的」或者「条目的国家名单里有中国」。
    """
    by_day: dict[D, list[Ev]] = {}
    for e in glob:
        by_day.setdefault(e.start, []).append(e)

    def lists_cn(desc: str) -> bool:
        """合并条目的国家名单里是否有「中国」内地。

        不能用「'中国' in desc」判断——名单里「中国香港」「中国澳门」也含「中国」，
        会把「圣诞节（47 个国家/地区）」误判成已经包含内地。
        """
        if "：" not in desc:
            return False
        items = desc.split("：", 1)[1].rstrip("。").split("、")
        return "中国" in items

    out = list(glob)
    for e in cand:
        bare = e.summary.split(" · ", 1)[-1]
        is_cn = e.summary.startswith("中国 · ")
        covered = False
        for x in by_day.get(e.start, []):
            xs = x.summary
            if bare not in xs:
                continue
            if not is_cn:                      # 国际日：同名即算覆盖
                covered = True
                break
            if xs.startswith("中国"):          # 已有中国条目（含「中国 · 春节假期」）
                covered = True
                break
            if lists_cn(x.desc or ""):         # 合并条目的国家名单里有中国内地
                covered = True
                break
        if covered:
            continue
        by_day.setdefault(e.start, []).append(e)
        out.append(e)
    return out


def china_in_global(y: int) -> list[Ev]:
    """大全里的中国内地：法定假期区间与调休上班。

    节气与农历节日由 china_nodes() 并入，纪念日/国际日由 global_obs() 并入，
    这里只负责「放几天、哪天补班」这类官方安排。
    """
    src = CN_SOURCE[y] + "\n"
    out = [span(a, b, f"中国 · {n}", d + "\n" + src, alarm=True) for a, b, n, d in CN_OFFICIAL[y]]
    out += [one(d, f"中国 · {n}", "周末调休上班。") for d, n in CN_WORKDAYS[y]]
    return out


def build_year(y: int) -> tuple[dict, dict]:
    out_ics = ics_dir(y)
    os.makedirs(out_ics, exist_ok=True)
    stats: dict[str, int] = {}
    meta: dict[str, dict] = {}

    stats["china"] = write_ics(
        os.path.join(out_ics, f"china-{y}.ics"),
        f"蚝历 · 中国节假日（{y}）",
        build_china(y),
        "cn",
        y,
        f"中国法定假日、调休上班、24 节气、农历传统节日与纪念日（{y}）",
    )

    hk_t = tag_rows("中国香港", HK[y])
    stats["hk"] = write_ics(os.path.join(out_ics, f"hk-{y}.ics"),
                            f"蚝历 · 中国香港公众假期（{y}）", evs_of(hk_t), "hk", y)
    mo_t = tag_rows("中国澳门", MO[y])
    stats["mo"] = write_ics(os.path.join(out_ics, f"mo-{y}.ics"),
                            f"蚝历 · 中国澳门公众假期（{y}）", evs_of(mo_t), "mo", y)
    stats["tw"] = write_ics(os.path.join(out_ics, f"tw-{y}.ics"),
                            f"蚝历 · 中国台湾节日（{y}）", tw_events(y), "tw", y)
    # 港澳台的名字/说明落进 meta：网站卡片和 App 的「国家目录」都从这里取，避免两处各写一份
    meta["hk"] = {"zh": "中国香港", "note": "公众假期", "region": "港澳台"}
    meta["mo"] = {"zh": "中国澳门", "note": "公众假期与补假", "region": "港澳台"}
    meta["tw"] = {"zh": "中国台湾", "note": "办公日历表连假", "region": "港澳台"}

    overseas = build_overseas(y)
    by_region: dict[str, list[tuple]] = {}
    for c in overseas:
        stats[c.key] = write_ics(
            os.path.join(out_ics, f"{c.key}-{y}.ics"),
            f"蚝历 · {c.zh}（{y}）",
            c.evs,
            c.key,
            y,
            f"{c.zh} {y} 年公众假期，数据来源 holidays 开源假日库，名称已译为中文",
        )
        meta[c.key] = {"zh": c.zh, "note": c.note, "region": c.region}
        by_region.setdefault(c.region, []).extend(c.tagged)

    for title, slug, regions in DISPLAY_GROUPS:
        tagged: list[tuple] = []
        for r in regions:
            tagged += by_region.get(r, [])
        stats[slug] = write_ics(
            os.path.join(out_ics, f"{slug}-{y}.ics"),
            f"蚝历 · {title}合集（{y}）",
            collapse_runs(merge_semantic(tagged)),
            slug,
            y,
            f"{title}各国公众假期合集，同一天同一节日按国家合并标注",
        )
        meta[slug] = {"zh": f"{title}合集", "note": i18n.REGION_NOTE.get(regions[0], ""), "region": title}

    pool: list[tuple] = []
    for c in overseas:
        pool += c.tagged
    pool += hk_t + mo_t
    glob = collapse_runs(merge_semantic(pool + china_nodes(y))) + china_in_global(y)
    glob = merge_days(glob, global_obs(y))

    stats["global"] = write_ics(
        os.path.join(out_ics, f"global-{y}.ics"),
        f"蚝历 · 全球节假日（{y}）",
        glob,
        "gl",
        y,
        f"中国（含 24 节气、农历节日、纪念日与节日）+ {len(overseas)} 国 {y} 年节假日 + 世界性国际日；"
        f"同一天同一节日合并为一条，描述内列出国家和地区",
    )

    # 月视图数据源：把全球大全（含中国，同日同名已合并）展开成逐日 JSON，
    # 供网页月历（仿三星日历月视图）加载。跨天假期按天展开，每天都能看到。
    day_rows: list[dict] = []
    for e in glob:
        d = e.start
        while d < e.end:
            row = {"d": d.isoformat(), "t": e.summary}
            if e.desc:
                row["x"] = e.desc
            day_rows.append(row)
            d += dt.timedelta(days=1)
    day_rows.sort(key=lambda r: (r["d"], r["t"]))
    with open(os.path.join(year_dir(y), "events.json"), "w", encoding="utf-8") as f:
        json.dump(day_rows, f, ensure_ascii=False, separators=(",", ":"))

    # 宗教 / 天象：每年的源文件放在 _source/ 下，逐年维护。
    # 没有源文件的年份不产出、页面也不显示该卡片 —— 宁可少一张，不猜日期。
    for key, cal, note in (
        ("religion", "全球宗教节日", "开斋节、宰牲节、复活节、佛诞等跨宗教节日"),
        ("world-events", "天象与赛事", "日食、月食、流星雨与大型赛事"),
    ):
        src_path = os.path.join(BASE, "_source", f"{key}-{y}.ics")
        if os.path.exists(src_path):
            evs = parse_ics(src_path)
            stats[key] = write_ics(os.path.join(out_ics, f"{key}-{y}.ics"),
                                   f"蚝历 · {cal}（{y}）", evs, key[:3], y, f"{cal}（{y}）：{note}")
            meta[key] = {"zh": cal, "note": note, "region": "专题"}

    # 页面渲染收口到 build()：单页常青版式只需渲染一次（旧版在这里逐页渲染）
    return stats, meta


def parse_ics(path: str) -> list[Ev]:
    """读回已有的专题 ics（宗教 / 天象），只做重排与 UID 重编号。"""
    raw = open(path, encoding="utf-8", errors="replace").read().replace("\r\n", "\n")
    out = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", raw, re.S):
        unfolded = block.replace("\n ", "")
        d = re.search(r"DTSTART[^:]*:(\d{8})", unfolded)
        e = re.search(r"DTEND[^:]*:(\d{8})", unfolded)
        s = re.search(r"SUMMARY:(.*)", unfolded)
        sc = re.search(r"DESCRIPTION:(.*)", unfolded)
        if not (d and s):
            continue
        start = dt.datetime.strptime(d.group(1), "%Y%m%d").date()
        end = dt.datetime.strptime(e.group(1), "%Y%m%d").date() if e else start + dt.timedelta(days=1)
        desc = sc.group(1).replace("\\n", "\n").replace("\\,", ",") if sc else ""
        out.append(Ev(start, end, s.group(1).strip(), desc))
    return out


# ---------------------------------------------------------------- 页面渲染

def card_html(title: str, note: str, count: int, path: str, badge: str = "", full: bool = False,
              webcal: str = "", sub_name: str = "") -> str:
    """单张日历卡片：主按钮一次性导入，下面一行订阅（自动更新）+ 复制地址（安卓用）。

    主按钮下载的是**当年快照**（path 带年份，相对当年页面）；订阅走的是**常青地址**
    （sub_name 不带年份，指向 /ics/{sub_name}.ics，内容滚动包含最近两个年度）——
    订阅一次，明年自动延续，用户永远不用回来重新订阅。
    sub_name 为空则退回按年的老地址（兼容）。安卓不认 webcal:// 协议，
    所以额外给一个 https 地址让用户复制。
    """
    cls = ' style="grid-column:1/-1"' if full else ""
    badge_html = f' <span class="badge">{badge}</span>' if badge else ""
    btn_cls = "primary" if full else "secondary"
    label = "点击导入手机日历" if full else "导入手机日历"
    sub = ""
    if webcal:
        url = f"{webcal}ics/{sub_name}.ics" if sub_name else f"{webcal}ics/{path}"
        https = url.replace("webcal://", "https://", 1)
        sub = (
            '<div class="subrow">'
            f'<a class="sub" href="{url}">订阅 · 自动更新</a>'
            f'<button type="button" class="cpy" data-copy="{https}">复制地址</button>'
            "</div>"
        )
    return "\n".join(
        x for x in [
            f'      <div class="card"{cls}>',
            f'        <div class="card-head"><h3>{title}{badge_html}</h3><span class="count">{count} 条</span></div>',
            f"        <p>{note}</p>",
            f'        <a class="btn {btn_cls}" href="ics/{path}" download>{label}</a>',
            f"        {sub}" if sub else "",
            "      </div>",
        ] if x
    )


def md(d: D) -> str:
    return f"{d.month} 月 {d.day} 日"


def describe_year(y: int) -> str:
    """meta description：把当年的放假安排压成一句话，供搜索结果显示。"""
    parts = []
    for a, b, name, _d in CN_OFFICIAL[y]:
        days = (b - a).days + 1
        if days >= 3:
            parts.append(f"{name.replace('假期', '')} {md(a)}至{b.day} 日共 {days} 天")
    return f"{y} 年放假安排：" + "，".join(parts) + f"。提供中国及全球 {len(i18n.COUNTRIES)} 国节假日 .ics 日历，点一下就能导入 iPhone、安卓、Outlook 的日历。"


def faq_html(y: int) -> str:
    """FAQ 全部由数据生成，换年不用改模板。"""
    off = {n: (a, b, d) for a, b, n, d in CN_OFFICIAL[y]}
    items: list[tuple[str, str, bool]] = []

    for key, label in (("春节假期", "春节"), ("国庆节假期", "国庆")):
        if key in off:
            _a, _b, desc = off[key]
            items.append((f"{y} 年{label}放几天？", desc, key == "春节假期"))

    rest = []
    for a, b, name, _d in CN_OFFICIAL[y]:
        if name in ("春节假期", "国庆节假期"):
            continue
        days = (b - a).days + 1
        rest.append(f"{name.replace('假期', '')} {md(a)}" + (f"至{b.day} 日共 {days} 天" if days > 1 else "共 1 天"))
    items.append((f"{y} 年其他假期怎么放？", "；".join(rest) + "。", False))

    items += [
        ("「元旦（55 个国家/地区）」这种合并条目，点开还能看到具体国家吗？",
         "能。合并只在标题上做：同一天、同一个节日的条目并成一条，点开描述就是完整名单（如「包含 55 个国家/地区：中国香港、中国澳门、中国台湾、日本、美国……」）。这样月视图不会在 1 月 1 日堆出五十多条，信息一条没少。只合并同义异名（元旦/元旦假期、劳动节/五一节/劳动者节），不同节日即使撞在同一天也各自保留。", False),
        ("「导入」和「订阅」有什么区别？选哪个？",
         "导入＝往你日历里塞一份一次性快照，覆盖当前窗口的全部年度（如 2026–2027）；数据更新后回来再点一次导入，就是刷新，不会重复堆积。订阅＝把日历挂在我这边的一个固定地址上，地址永远不变，内容自动滚动（今年＋明年，过期年份自动退场），我更新你手机上自动跟着变，订阅一次管到永远。想装了蚝历 App 一键导入、还自动分组的就选导入；想一直保持最新就选订阅。两者别同时用，否则同一天会出现两条。", False),
        ("安卓能像 iPhone 那样一键订阅吗？",
         "不能。webcal:// 是苹果和 Outlook 认的协议，安卓系统日历和 Google 日历都不接管它。安卓的做法是：点卡片下方的「复制地址」，再进系统日历「添加日历 → 通过网址添加」粘贴；更省事的办法是直接装「蚝历 App」，App 里的「导入」会在你手机日历里自动创建独立的「蚝历」分组，效果和订阅的独立分组一样。", False),
        ("导入后跟我自己的日程混在「我的日历」里，能单独分一组吗？",
         "装「蚝历 App」（安卓，v1.34 起）再点导入：App 会向你要日历权限，然后在手机日历里自动创建独立的「蚝历 · 中国节假日」「蚝历 · 全球节假日」分组，所有节日只写进这个分组，可单独改颜色、单独隐藏、整组删除，再次导入就是刷新。不想装 App 就用订阅：走 Google 日历或系统日历的「通过网址添加」，也会单独成组。", False),
        ("以前导入的那一批怎么清掉？",
         "用「蚝历 App」（v1.34 起）导入的不用清：再点一次导入就是刷新，旧数据自动替换。老版 App 或网页下载导入的（落进「我的日历」的那批）要手动删：三星日历：设置 → 日历 → 长按「我的日历」→ 删除日历，它下面的所有日程一起消失（如果你的个人日程也在这一组，先别删，见下条）。Google 日历：网页版设置 → 选该日历 → 删除。想只删节假日、保留自己的日程：在日历里搜索「春节」「立冬」等节日名，长按进入多选后批量删除，或改用 App 导入 / 订阅，再把旧的那组整组删掉。", False),
        ("导入后会把原来的日程覆盖掉吗？",
         "不会。导入只是往你现有日历里「加一份」，已有日程不受影响。反过来，如果你想撤掉，删掉这个日历分组就行。", False),
        ("日历会提醒我吗？",
         "法定假日和春节、端午、中秋会带一条当天上午的提醒。其他纪念日、节气不提醒，避免打扰。", False),
        ("安卓 App 怎么装？桌面小组件怎么加？",
         f"点页面右上角的「蚝历 App」下载 APK（{y} 版约 700 KB，不需要 Google Play）。装好后长按桌面空白处 →「小组件」→ 找到「蚝历」→ 选 4×2 / 2×2 / 2×1 拖到桌面即可。App 里内置 2026–2030 五年数据，跨年不用管；国务院公布次年放假安排后，App 会自动下载新数据，不用重新装。小组件每天零点自己翻到今天，「下一个节点」按最近的一条算——假期、节气、传统节日、纪念日一视同仁，谁最近显示谁。", False),
        ("数据准确吗？来源是什么？",
         f"中国内地依据{CN_SOURCE[y].replace('数据来源：', '').rstrip('。')}；农历节日与 24 节气按天文历法计算。中国香港、中国澳门按当地政府公布的公众假期，中国台湾按行政院人事行政总处办公日历表。海外 {len(i18n.COUNTRIES)} 国由开源假日库 holidays 按 {y} 年当地规则计算，名称已译为中文；个别伊斯兰节日按天文推算，可能与当地最终公布相差一天，出行前请以当地官方为准。", False),
    ]

    out = []
    for i, (q, a, open_) in enumerate(items):
        o = " open" if open_ else ""
        out.append(f"      <details{o}><summary>{q}</summary><p>{a}</p></details>")
    return "\n".join(out)


def nav_html(y: int) -> str:
    """年份切换：上一年在左，下一年在右；不存在的一侧留空。"""
    prev_y, next_y = y - 1, y + 1
    left = f'<a class="yn yn-left" href="../{prev_y}/">‹ {prev_y}</a>' if prev_y in YEARS else "<span></span>"
    right = f'<a class="yn yn-right" href="../{next_y}/">{next_y} ›</a>' if next_y in YEARS else "<span></span>"
    return f'  <div class="yearnav">{left}{right}</div>'


def _apk_release() -> dict:
    """发布元数据只认 data/apk.json 这一个来源。

    页面上的版本号曾经写死在环境变量默认值里（1.15），发版时忘了传就渲染成旧版本，
    1.16 已经因为同类问题把下载链接甩到占位域名上。这里改成默认读文件，少一个记性负担。
    """
    try:
        with open(os.path.join(BASE, "data", "apk.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _apk_size_text() -> str:
    kb = int(_apk_release().get("size") or 0) // 1024
    return f"{kb} KB" if kb else "770 KB"


def write_countries_json(stats: dict, meta: dict, window: list[int]) -> None:
    """给 App 用的「国家/地区目录」：/data/countries.json。

    App 里要和网站一样按分区列出所有国家（含合集），但国家名、说明、条数
    这些都不该硬编码进 APK——数据一变就得改代码重新发版。这里按网站的
    DISPLAY_GROUPS 原样导出一次，App 联网读它、本地缓存，网站加国家 App 自动有。
    """
    label = f"{window[0]}–{window[-1]}" if len(window) > 1 else str(window[0])
    groups: list[dict] = []

    def item(slug: str, zh: str, note: str) -> dict:
        return {"slug": slug, "zh": zh, "note": note, "count": int(stats.get(slug, 0))}

    # 中国港澳台：放最前，和网站「中国」分区相邻
    hmt = [item(k, meta[k]["zh"], meta[k]["note"]) for k in ("hk", "mo", "tw") if k in stats]
    if hmt:
        groups.append({"title": "中国港澳台", "items": hmt})

    for title, slug, regions in DISPLAY_GROUPS:
        keys = [k for k, m in meta.items() if m["region"] in regions and k not in (slug,)]
        if not keys:
            continue
        items = [item(slug, f"{title}合集", i18n.REGION_NOTE.get(regions[0], ""))]
        items += [item(k, meta[k]["zh"], meta[k]["note"]) for k in keys]
        groups.append({"title": title, "items": items})

    topics = [item(k, meta[k]["zh"], tip) for k, tip in
              (("religion", "开斋节 · 宰牲节 · 复活节 · 佛诞"),
               ("world-events", "日食 · 月食 · 流星雨 · 大赛")) if k in stats]
    if topics:
        groups.append({"title": "专题", "items": topics})

    payload = {"window": label, "groups": groups}
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    with open(os.path.join(BASE, "data", "countries.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    n = sum(len(g["items"]) for g in groups)
    print(f"  data/countries.json：{len(groups)} 个分区 / {n} 个国家地区")


def render_site(all_stats: dict[int, dict], metas: dict) -> None:
    """单页常青版式：只渲染「当前窗口」（今年 + 明年若可用）这一页，落在根 index.html。

    老设计是首页跳转器 + /2026/、/2027/ 两个年度页；v1.34 起数据本身是滚动窗口
    （下载、订阅、App 导入拿到的都是同一份 /ics/{name}.ics），页面再分年份只会让
    用户困惑「我该去哪年」。所以只留一页：标题显示窗口（2026–2027），跨年重建后
    自动变 2027–2028。/{year}/ 老链接由 write_year_redirects 跳回首页。
    """
    window = evergreen_window(sorted(all_stats))
    y = window[0]
    # 卡片条数 = 窗口内各年合计：用户下载/订阅到的就是窗口数据
    stats: dict[str, int] = {}
    for w in window:
        for k, n in all_stats[w].items():
            stats[k] = stats.get(k, 0) + int(n)
    meta: dict = {}
    for w in window:
        meta.update(metas[w])  # 窗口内各年 meta 合并：某年缺的卡（如专题）由另一年补上
    site = os.environ.get("SITE", "https://49.233.147.15").rstrip("/")
    if "example.com" in site:
        raise SystemExit("SITE 指向占位域名，会让全站下载/订阅链接失效，请设置 SITE=https://真实域名")
    # 订阅与下载都走**常青地址**（/ics/{name}.ics，内容=滚动窗口，地址永不变化）
    webcal = "webcal://" + site.split("://", 1)[-1] + "/" if not site.startswith("file:") else ""

    sections: list[str] = []
    topic_cards = []
    for key, tip in (("religion", "开斋节 · 宰牲节 · 复活节 · 佛诞"),
                     ("world-events", "日食 · 月食 · 流星雨 · 大赛")):
        if key in stats:
            topic_cards.append(card_html(meta[key]["zh"], tip, stats[key], f"{key}.ics",
                                         webcal=webcal, sub_name=key))
    sections.append(
        "  <div class=\"section\">\n"
        '    <div class="section-title">全球 · 一键全导入</div>\n'
        '    <div class="cards">\n'
        + card_html("全球节假日大全",
                    f"中国（含 24 节气 · 农历节日 · 纪念日）+ {len(i18n.COUNTRIES)} 国 + 世界性国际日，同日同节日合并为一条",
                    stats["global"], "global.ics", badge="推荐", full=True, webcal=webcal,
                    sub_name="global")
        + ("\n" + "\n".join(topic_cards) if topic_cards else "")
        + "\n    </div>\n  </div>"
    )

    for title, slug, regions in DISPLAY_GROUPS:
        keys = [k for k, m in meta.items() if m["region"] in regions and k not in (slug,)]
        if not keys:
            continue
        cards = [card_html(f"{title}合集", i18n.REGION_NOTE.get(regions[0], ""), stats[slug],
                           f"{slug}.ics", badge="合集", full=True, webcal=webcal, sub_name=slug)]
        for k in keys:
            m = meta[k]
            cards.append(card_html(m["zh"], m["note"], stats[k], f"{k}.ics",
                                   webcal=webcal, sub_name=k))
        sections.append(
            f'  <div class="section">\n    <div class="section-title">{title}</div>\n'
            '    <div class="cards">\n' + "\n".join(cards) + "\n    </div>\n  </div>"
        )

    tpl = open(os.path.join(BASE, "template.html"), encoding="utf-8").read()
    window_label = f"{window[0]}–{window[-1]}" if len(window) > 1 else str(window[0])
    repl = {
        "{{SITE}}": site,
        "{{YEAR}}": str(y),
        "{{WINDOW}}": window_label,
        "{{EVENT_YEARS}}": json.dumps(window),
        "{{NAV}}": "",
        "{{SECTIONS}}": "\n\n".join(sections),
        "{{COUNTRIES}}": str(len(i18n.COUNTRIES)),
        "{{TOTAL}}": f"{sum(stats.values()):,}",
        "{{DESC}}": describe_year(y),
        "{{FAQ}}": faq_html(y),
        "{{WEBCAL}}": webcal,
        "{{HOST}}": site.split("://", 1)[-1],
        "{{APP_VER}}": os.environ.get("APP_VER") or _apk_release().get("version", "1.16"),
        "{{BJ_VER}}": os.environ.get("BJ_VER", "3.6"),
        "{{APP_SIZE}}": os.environ.get("APP_SIZE") or _apk_size_text(),
        "{{APP_YEARS}}": os.environ.get("APP_YEARS", "2026–2030 五"),
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    for key, n in stats.items():
        tpl = tpl.replace("{{N:%s}}" % key, str(n))

    icp = os.environ.get("ICP", "").strip()
    tpl = tpl.replace("{{ICP}}", f' · <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener nofollow">{icp}</a>' if icp else "")

    left = set(re.findall(r"\{\{[^}]+\}\}", tpl))
    if left:
        raise SystemExit(f"[!] 模板有未替换的占位符：{sorted(left)}")

    # 唯一的正式页面落在根路径；logo/二维码在根目录下同级，../ 前缀要修正
    tpl = tpl.replace('src="../oyster-logo.png"', 'src="oyster-logo.png"')
    tpl = tpl.replace('href="../oyster-logo.png"', 'href="oyster-logo.png"')
    tpl = tpl.replace('src="../wx-qr.jpg"', 'src="wx-qr.jpg"')
    open(os.path.join(BASE, "index.html"), "w", encoding="utf-8").write(tpl)
    print(f"  site: 根 index.html（窗口 {window_label}，{len(sections)} 个分区）")
    write_countries_json(stats, meta, window)


def write_year_redirects() -> None:
    """/{year}/ 老链接不再承载独立页面：一律跳回根首页（单页常青）。

    meta refresh + JS + 文本链接三保险；旧年度页的 sitemap 一并撤掉，
    避免搜索引擎继续收录按年分页的地址。
    """
    for y in sorted(YEARS):
        os.makedirs(year_dir(y), exist_ok=True)
        with open(os.path.join(year_dir(y), "index.html"), "w", encoding="utf-8") as f:
            f.write(
                "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
                f"<meta http-equiv=\"refresh\" content=\"0; url=/\">\n"
                "<link rel=\"canonical\" href=\"/\">\n"
                "<title>蚝历 · 节假日日历</title>\n"
                "</head>\n<body>\n"
                f"<p>页面已合并到首页，<a href=\"/\">点这里打开 {dt.date.today().year} 年节假日日历</a>…</p>\n"
                "<script>location.replace('/');</script>\n"
                "</body>\n</html>\n"
            )
        old_sitemap = os.path.join(year_dir(y), "sitemap.xml")
        if os.path.exists(old_sitemap):
            os.remove(old_sitemap)
        old_ics = os.path.join(year_dir(y), "robots.txt")
        if os.path.exists(old_ics):
            os.remove(old_ics)
    print(f"  redirects: {', '.join('/%d/' % y for y in sorted(YEARS))} → /")


def evergreen_window(years: list[int]) -> list[int]:
    """常青滚动窗口：今年 + 明年（若明年数据已构建），过期年份自动出局。

    - 2026-11 构建、YEARS=2026,2027 → 窗口 2026+2027；
    - 2027-03 构建 → 窗口只剩 2027（2026 已过期，对用户没用）；
    - 2027-12 加入 2028 数据重建 → 窗口 2027+2028。
    跨年那一刻需要重建一次才能剔除旧年（由每年 1 月 1 日的自动任务兜底）。
    """
    today_year = dt.date.today().year
    return sorted(y for y in years if y >= today_year) or [max(years)]


def build_evergreen(years: list[int]) -> int:
    """生成**常青订阅文件**：/ics/{name}.ics，不带年份、地址永不变化。

    为什么需要它：日历 App 的「订阅」只会刷新同一个 URL 的内容，不会自己延长年份。
    老方案里订阅地址带年份（/2026/ics/china-2026.ics），2026 年底内容就走完了，
    用户得回来重新订阅一次——这违背了订阅的初衷。常青文件把一个**滚动窗口**
    （见 evergreen_window：今年 + 明年若可用）的年度事件合并进同一个固定地址，
    订阅一次管到永远。

    实现上不做任何重算：直接汇总窗口内各年已生成的 ics 里的 VEVENT 块（UID 含
    年份，跨文件唯一，原样搬运即可），按日期排序重写 DTSTAMP。名字从各年文件名
    里收，某年缺的（如宗教节日只有一年）就只含现有年份。
    """
    years = evergreen_window(years)
    ever_dir = os.path.join(BASE, "ics")
    os.makedirs(ever_dir, exist_ok=True)
    names: dict[str, list[int]] = {}
    for y in years:
        for f in os.listdir(ics_dir(y)):
            m = re.fullmatch(r"(.+)-(\d{4})\.ics", f)
            if m:
                names.setdefault(m.group(1), []).append(y)

    total = 0
    for name, ys in sorted(names.items()):
        blocks: list[str] = []
        newest_raw = ""
        for y in sorted(ys):
            raw = open(os.path.join(ics_dir(y), f"{name}-{y}.ics"),
                       encoding="utf-8").read().replace("\r\n", "\n")
            newest_raw = raw
            blocks += re.findall(r"BEGIN:VEVENT.*?END:VEVENT", raw, re.S)
        blocks = [b.replace("\n", "\r\n").strip() for b in blocks]

        def sort_key(b: str) -> str:
            d = re.search(r"DTSTART[^:]*:(\d{8})", b)
            s = re.search(r"SUMMARY:(.*)", b)
            return (d.group(1) if d else "99999999") + (s.group(1) if s else "")

        blocks.sort(key=sort_key)

        # 日历名去掉年份尾巴；描述说明这是滚动两年窗的常青订阅
        m = re.search(r"X-WR-CALNAME:(.+)", newest_raw)
        cal_name = re.sub(r"（\d{4}）$", "", (m.group(1) if m else f"蚝历 · {name}"))
        lo, hi = min(ys), max(ys)
        desc = (f"常青订阅：包含 {lo}" + (f" 与 {hi} 两个年度" if hi != lo else " 年度")
                + "，逐年滚动更新，订阅一次即可，无需每年重新订阅")

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            f"PRODID:{PRODID}",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{esc(cal_name)}",
            "X-WR-TIMEZONE:Asia/Shanghai",
            f"X-WR-CALDESC:{esc(desc)}",
        ]
        # 头部行按 ics 规范折行；VEVENT 块**原样搬运**——它们在年度文件里已经折好了，
        # 再过一遍 fold 会把整块当成一行重新断行，把 DTSTART 从中间切断（踩过一次）。
        header = "\r\n".join(fold(x) for x in lines)
        body = header + "\r\n" + "\r\n".join(blocks) + "\r\nEND:VCALENDAR\r\n"
        with open(os.path.join(ever_dir, f"{name}.ics"), "w", encoding="utf-8", newline="") as f:
            f.write(body)
        total += len(blocks)
    return total


def write_root_files() -> None:
    site = os.environ.get("SITE", "https://49.233.147.15").rstrip("/")
    with open(os.path.join(BASE, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % site)
    # 单页常青：只收录首页；/{year}/ 是跳转页，不再进 sitemap
    with open(os.path.join(BASE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url><loc>{site}/</loc><changefreq>monthly</changefreq><priority>1.0</priority></url>\n"
            "</urlset>\n"
        )


def build() -> None:
    all_stats = {}
    metas = {}
    for y in YEARS:
        print(f"[{y}] 构建中…")
        stats, meta = build_year(y)
        all_stats[y] = stats
        metas[y] = meta
        print(f"  {y}: {len(stats)} 个文件 / {sum(stats.values())} 条")
    n_ever = build_evergreen(sorted(YEARS))
    print(f"  evergreen: /ics/ 下 {len(os.listdir(os.path.join(BASE, 'ics')))} 份常青订阅文件，共 {n_ever} 条")
    render_site(all_stats, metas)
    write_year_redirects()
    write_root_files()

    with open(os.path.join(BASE, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(all_stats, f, ensure_ascii=False, indent=2)

    print(json.dumps(all_stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
