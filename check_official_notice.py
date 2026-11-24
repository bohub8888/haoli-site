#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""国务院办公厅节假日通知 · 官方公告 diff 校验器（v1.67 自动化流水线第一环）。

学的是 holiday-cn / chinese-days 的那套机制，但按蚝历的红线做了收敛：

    holiday-cn      每天定时抓 gov.cn → 解析 → 数据变了就 CI 自动 commit + tag + release
    chinese-days    AI 读公告 → 自动生成 PR → 自动校验 → 人工合并 → 自动发 npm → 单独 purge CDN
    蚝历            每天定时抓 gov.cn → 解析 → **只报差异 / 生成待审提案** → 人工核源改
                    cn_official.py → pipeline.py 自动构建 + 推数据（热更新，不发 APK）

为什么不让机器自动改写数据：taxonomy.py C1 是 A 级渠道，内容红线要求每条都能追到
官方原文；公告文本解析存在歧义（跨年、临时调整、特殊纪念日追加），机器写错了会
安静地污染 234 份 ICS。所以本脚本**只读不写源表**，把「发现变化」和「采纳变化」分开。

用法
----
    ../.venv/bin/python check_official_notice.py               # 校验所有已覆盖年份 + 次年预警
    ../.venv/bin/python check_official_notice.py --offline     # 只用本地缓存，断网也能跑
    ../.venv/bin/python check_official_notice.py --year 2027   # 只查某年
    ../.venv/bin/python check_official_notice.py --refresh     # 强制重抓官方原文并更新缓存
    ../.venv/bin/python -m unittest test_official_notice -v   # 解析单测

退出码：0 = 一致（或次年公告尚未发布）；1 = 有差异 / 缺数据 / 解析失败（CI 据此红灯）。
产物：data/official-notice-report.json（可公开，无敏感信息）
缓存：data/official-notices/{year}.json（公告原文快照，可公开，保证离线可复现）
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cn_official as cn  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE, "data", "official-notices")
REPORT = os.path.join(BASE, "data", "official-notice-report.json")

UA = "Mozilla/5.0 (compatible; HaoliCalendar/1.0; +official-notice-audit)"

# 国务院办公厅历年通知通常在 11 月上旬发布。11 月起若次年公告已出而本地没数据，
# 就是「产品会在年底过期」的信号，必须红灯提醒。
NOTICE_MONTH = 11
SEARCH_API = "https://sousuo.www.gov.cn/search-gov/data"


# ---------------------------------------------------------------- 网页抓取

class _Text(HTMLParser):
    """只取可见文字，跳过 script / style / 注释。"""

    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def html_text(raw: str) -> str:
    p = _Text()
    p.feed(raw)
    return html.unescape(" ".join(p.parts))


def fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def find_notice_url(year: int) -> str | None:
    """先查已知官方地址，再走 gov.cn 搜索接口（与 holiday-cn 同一接口）。"""
    known = cn.NOTICE_URLS.get(year)
    if known:
        return known
    q = urllib.parse.urlencode({
        "t": "zhengcelibrary_gw", "p": 0, "n": 5,
        "q": "假期 %d" % year,
        "pcodeJiguan": "国办发明电", "puborg": "国务院办公厅",
        "filetype": "通知", "sort": "pubtime",
    })
    try:
        data = json.loads(fetch(SEARCH_API + "?" + q))
        for item in (data.get("searchVO") or {}).get("listVO") or []:
            if str(year) in (item.get("title") or ""):
                u = item.get("url")
                if u:
                    return u
    except Exception:
        pass
    return None


def notice_cache(year: int) -> dict | None:
    p = os.path.join(CACHE_DIR, f"{year}.json")
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def get_notice(year: int, offline: bool = False, refresh: bool = False) -> tuple[dict | None, str]:
    """返回 (公告快照, 说明)。网络失败时回落到本地缓存，绝不因断网误判为「数据错了」。"""
    cached = notice_cache(year)
    if offline:
        return cached, "离线缓存" if cached else "无本地缓存"
    if cached and not refresh and cached.get("text"):
        return cached, "本地缓存（用 --refresh 强制重抓）"

    url = find_notice_url(year)
    if not url:
        return cached, "未找到该年度官方通知（可能尚未发布）"
    try:
        text = html_text(fetch(url))
        body = extract_body(text, year)
        if not body:
            return cached, "抓到页面但没解析出通知正文"
        snap = {
            "year": year, "url": url, "text": body,
            "fetched_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(os.path.join(CACHE_DIR, f"{year}.json"), "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        return snap, "官方原文（已抓）"
    except Exception as e:
        return cached, f"抓取失败（{type(e).__name__}），回落到缓存"


def extract_body(text: str, year: int) -> str:
    """截出「通知如下。」到「鼓励…」之间的正文，排除标题、落款与网页导航。"""
    s = text.find("通知如下")
    if s < 0:
        s = text.find("具体安排通知如下")
    if s < 0:
        return ""
    body = text[s:]
    for marker in ("鼓励单位和个人", "国务院办公厅", "各省、自治区"):
        i = body.find(marker, 10)
        if i > 0:
            body = body[:i]
    return body.strip()


# ---------------------------------------------------------------- 公告解析（纯函数，可单测）

# 节标题必须出现在空白之后、后面紧跟「节日名：」。不能只写「([一二三四五六七八九十]+)、」：
# 公告里「农历正月初八、周六」的「八、」会被误判成新的一节，把春节整段切碎（真实踩过）。
SECTION_HEAD = re.compile(r"(?:^|\s)([一二三四五六七八九十]+)、\s*([^：:，。]{1,10})[：:]")
DATE_TOKEN = re.compile(r"(?:(?P<m>\d{1,2})月)?(?P<d>\d{1,2})日")
DAYS_TOTAL = re.compile(r"共\s*(\d+)\s*天")


def _tokens(text: str) -> list[tuple[int, int]]:
    """把「1月1日…至3日」「1月31日、2月14日」解析成 (月, 日)。省略月的继承前一 token。"""
    out: list[tuple[int, int]] = []
    last_m = 0
    for m in DATE_TOKEN.finditer(text):
        month = int(m.group("m")) if m.group("m") else last_m
        day = int(m.group("d"))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        if m.group("m"):
            last_m = month
        out.append((month, day))
    return out


def parse_notice(body: str, year: int) -> dict:
    """解析通知正文 → 放假日期集合 / 补班日期集合 / 分节明细 / 自检结果。"""
    heads = list(SECTION_HEAD.finditer(body))
    sections: list[dict] = []
    off: set[dt.date] = set()
    work: set[dt.date] = set()
    checks: list[str] = []

    for i, h in enumerate(heads):
        seg = body[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(body)]
        name = h.group(2).strip()
        fi = seg.find("放假")
        if fi < 0:
            continue
        off_text, after = seg[:fi], seg[fi:]
        wi = after.find("上班")
        work_text = after[:wi] if wi >= 0 else ""

        od = _tokens(off_text)
        wd = _tokens(work_text)
        if not od:
            continue

        def to_date(md: tuple[int, int]) -> dt.date:
            return dt.date(year, md[0], md[1])

        if len(od) == 1:
            span = [to_date(od[0])]
        else:
            a, b = to_date(od[0]), to_date(od[-1])
            if b < a:  # 跨年区间（元旦通知里罕见），保守标记为异常
                checks.append(f"{name}: 区间结束早于开始，需人工确认")
                continue
            span = [a + dt.timedelta(days=k) for k in range((b - a).days + 1)]

        declared = DAYS_TOTAL.search(after)
        if declared and int(declared.group(1)) != len(span):
            checks.append(
                f"{name}: 公告写共 {declared.group(1)} 天，解析出 {len(span)} 天，需人工确认"
            )

        wdates = [to_date(x) for x in wd]
        off.update(span)
        work.update(wdates)
        sections.append({
            "name": name,
            "off": [d.isoformat() for d in span],
            "work": [d.isoformat() for d in wdates],
            "declared_days": int(declared.group(1)) if declared else None,
        })

    return {
        "year": year,
        "off": off,
        "work": work,
        "sections": sections,
        "checks": checks,
        "parsed": bool(sections),
    }


# ---------------------------------------------------------------- 比对与预警

def compare(year: int, parsed: dict) -> dict:
    local_off = cn.off_dates(year)
    local_work = cn.workday_dates(year)
    return {
        "year": year,
        "off_days_official": len(parsed["off"]),
        "off_days_local": len(local_off),
        "work_days_official": len(parsed["work"]),
        "work_days_local": len(local_work),
        "missing_off": sorted(d.isoformat() for d in parsed["off"] - local_off),
        "extra_off": sorted(d.isoformat() for d in local_off - parsed["off"]),
        "missing_work": sorted(d.isoformat() for d in parsed["work"] - local_work),
        "extra_work": sorted(d.isoformat() for d in local_work - parsed["work"]),
        "parse_warnings": parsed["checks"],
    }


def is_match(c: dict) -> bool:
    return not any(c[k] for k in ("missing_off", "extra_off", "missing_work", "extra_work",
                                  "parse_warnings"))


def next_year_warning(today: dt.date, notice: dict | None) -> dict:
    """11 月起盯次年：公告发布了但 cn_official 没数据 → 必须红灯。"""
    y = today.year + 1
    has_data = y in cn.CN_OFFICIAL
    has_notice = bool(notice and notice.get("text"))
    if today.month < NOTICE_MONTH and not has_notice:
        action = "未到公告窗口（通常 11 月上旬发布），无需动作"
        urgent = False
    elif has_notice and not has_data:
        action = "次年公告已发布但 cn_official.py 无该年数据：人工核源后补表 → 跑 pipeline.py"
        urgent = True
    elif has_data:
        action = "次年数据已在库，无需动作"
        urgent = False
    else:
        action = "次年数据未入库，公告也尚未抓到；11 月中旬后需人工确认"
        urgent = today.month >= NOTICE_MONTH and today.day >= 15
    return {"year": y, "data_present": has_data, "notice_found": has_notice,
            "action": action, "urgent": urgent}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="国务院放假通知与本地调休表的 diff 校验")
    ap.add_argument("--offline", action="store_true", help="只用本地缓存，不联网")
    ap.add_argument("--refresh", action="store_true", help="强制重抓官方原文")
    ap.add_argument("--year", type=int, help="只校验指定年份")
    ap.add_argument("--today", help="模拟今天（YYYY-MM-DD），用于测试预警窗口")
    a = ap.parse_args(argv)

    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    years = [a.year] if a.year else cn.covered_years()
    results: list[dict] = []
    failures: list[str] = []

    for y in years:
        snap, how = get_notice(y, offline=a.offline, refresh=a.refresh)
        row = {"year": y, "source": how,
               "notice_url": (snap or {}).get("url") or cn.NOTICE_URLS.get(y),
               "fetched_at": (snap or {}).get("fetched_at")}
        if not snap or not snap.get("text"):
            row["status"] = "no_notice"
            row["note"] = "没有官方原文快照；该年按人工核源结果保留，不算失败"
            results.append(row)
            continue
        parsed = parse_notice(snap["text"], y)
        if not parsed["parsed"]:
            row["status"] = "parse_failed"
            row["note"] = "通知正文解析不出分节，需检查页面结构"
            results.append(row)
            failures.append(f"{y}: 公告解析失败")
            continue
        c = compare(y, parsed)
        row.update(c)
        row["sections"] = parsed["sections"]
        row["status"] = "match" if is_match(c) else "mismatch"
        results.append(row)
        if row["status"] == "mismatch":
            failures.append(
                f"{y}: 与官方公告不一致 缺放假 {len(c['missing_off'])} / 多放假 {len(c['extra_off'])}"
                f" / 缺补班 {len(c['missing_work'])} / 多补班 {len(c['extra_work'])}"
                + (f" / 解析警告 {len(c['parse_warnings'])}" if c["parse_warnings"] else "")
            )

    ny_notice, _ = get_notice(today.year + 1, offline=a.offline, refresh=a.refresh)
    nxt = next_year_warning(today, ny_notice)
    if nxt["urgent"]:
        failures.append(f"{nxt['year']}: {nxt['action']}")

    report = {
        "checked_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "offline": a.offline,
        "years": results,
        "next_year": nxt,
        "ok": not failures,
        "failures": failures,
        "policy": "只读校验：脚本不改源表；差异由人工核源后编辑 cn_official.py",
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"官方公告校验 · {today} · {'离线' if a.offline else '在线'}")
    for r in results:
        if r["status"] == "match":
            print(f"  ✓ {r['year']} 一致：放假 {r['off_days_official']} 天 / 补班 "
                  f"{r['work_days_official']} 天（{r['source']}）")
        else:
            print(f"  ! {r['year']} {r['status']}：{r.get('note','见报告')}")
    print(f"  → 次年 {nxt['year']}：{'数据已在库' if nxt['data_present'] else '数据未入库'}，"
          f"{nxt['action']}")
    if failures:
        print("\n✗ 需要处理：")
        for f_ in failures:
            print("   - " + f_)
    else:
        print("\n✓ 与官方公告一致，无需改数据（这不代表要发版）")
    print(f"报告：data/official-notice-report.json")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
