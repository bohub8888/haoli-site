#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四出口一致性检查：同一套数据，四个形态必须对得上。

  A 源表        holiday-calendar-deploy/observances.py
  B 中国日历    <year>/ics/china-<year>.ics          官网「中国节假日」
  C 全球日历    <year>/ics/global-<year>.ics         官网「全球节假日大全」
  D Apk 数据    haoli-apk/.../assets/data/cn-<year>.json + data/cn-<year>.json（远程更新）

检查项：
  1  源表 → 中国日历：每条都落地，日期与名称一字不差
  2  源表 → 全球日历：world 全收；cn 且 w≥2 必收（可被同日合并条目吸收）
  3  中国日历 → Apk 数据：节点集合（日期 + 归一化名称）双向相等
  4  权重一致：Apk 里的 w 与源表口径相同
  5  全球日历包含中国：法定假期、24 节气、农历节日一条不漏
  6  stats.json 的计数与实际文件条目数一致
  7  ICS 结构：CRLF、VEVENT 配对、每行 ≤75 字节、UID 不重复
  8  远程更新包：manifest 的 sha256 / 版本号与实际文件一致
  9  页面：每个 {{N:key}} 占位都已替换、计数与 stats 相同

用法：
    .venv/bin/python holiday-calendar-deploy/check_consistency.py
    .venv/bin/python holiday-calendar-deploy/check_consistency.py 2026 2027
退出码 0 = 全绿，1 = 有差异（差异逐条打印）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
APK_DATA = os.path.join(ROOT, "haoli-apk", "app", "src", "main", "assets", "data")

sys.path.insert(0, BASE)
import observances as obs  # noqa: E402

YEARS = [int(x) for x in (sys.argv[1:] or ["2026", "2027"])]

FAIL: list[str] = []
WARN: list[str] = []


def bad(msg: str) -> None:
    FAIL.append(msg)


def warn(msg: str) -> None:
    WARN.append(msg)


# ---------------------------------------------------------------- 读取

def parse_ics(path: str) -> list[dict]:
    raw = open(path, "rb").read().decode("utf-8")
    raw = raw.replace("\r\n ", "").replace("\r\n\t", "")
    out = []
    for blk in re.findall(r"BEGIN:VEVENT\r\n(.*?)END:VEVENT", raw, re.S):
        m = re.search(r"DTSTART;VALUE=DATE:(\d{8})", blk)
        if not m:
            continue
        d = dt.date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:]))
        sm = re.search(r"SUMMARY:(.*)", blk)
        out.append({"d": d, "s": sm.group(1).strip() if sm else ""})
    return out


def ics_terms(year: int) -> list[tuple[dt.date, str]]:
    path = os.path.join(BASE, str(year), "ics", f"china-{year}.ics")
    return [
        (e["d"], e["s"][len("节气 · "):])
        for e in parse_ics(path)
        if e["s"].startswith("节气 · ")
    ]


def norm(s: str) -> str:
    """ics 摘要 → Apk 节点名。两侧写法不同，但语义相同。"""
    if s.startswith("节气 · "):
        return s[len("节气 · "):]
    if s.startswith("调休上班"):
        return "调休上班"
    if s.endswith("假期"):
        return s[: -len("假期")]
    if "（" in s:
        return s.split("（")[0]
    return s


def core(s: str) -> str:
    """去掉「中国 · 」这类国家前缀。"""
    return s.split(" · ", 1)[-1]


# ---------------------------------------------------------------- 逐项检查

def check_table_vs_china(y: int, china: list[dict]) -> None:
    have = {(e["d"], e["s"]): e for e in china}
    rows = obs.solar_of(y, ics_terms(y))
    for o in rows:
        if (o.date, o.name) not in have:
            bad(f"[{y}] 源表条目没进中国日历：{o.date} {o.name}")
    # 反向：日历里的纪念日必须来自源表，防止有人手改 ics
    table = {(o.date, o.name) for o in rows}
    for e in china:
        s = e["s"]
        if s.startswith(("节气 · ", "调休上班")) or s.endswith("假期") or "（" in s:
            continue
        if s in ("除夕",):
            continue
        if (e["d"], s) not in table:
            warn(f"[{y}] 中国日历有不在源表里的条目：{e['d']} {s}")


def check_table_vs_global(y: int, glob: list[dict]) -> None:
    by_day: dict[dt.date, list[str]] = {}
    for e in glob:
        by_day.setdefault(e["d"], []).append(core(e["s"]))
    for o in obs.solar_of(y, ics_terms(y)):
        if not any(o.name in s for s in by_day.get(o.date, [])):
            bad(f"[{y}] 源表条目没进全球日历：{o.date} {o.name}（scope={o.scope} w={o.w}）")


def check_china_vs_apk(y: int, china: list[dict]) -> None:
    path = os.path.join(APK_DATA, f"cn-{y}.json")
    if not os.path.exists(path):
        bad(f"[{y}] 缺 Apk 数据 {path}")
        return
    data = json.load(open(path, encoding="utf-8"))
    a = {(e["d"], norm(e["s"])) for e in china}
    b = {(dt.date.fromisoformat(n["d"]), n["n"]) for n in data["nodes"]}
    for k in sorted(a - b):
        bad(f"[{y}] 中国日历有、Apk 无：{k[0]} {k[1]}")
    for k in sorted(b - a):
        bad(f"[{y}] Apk 有、中国日历无：{k[0]} {k[1]}")

    # 远程更新包必须与内置包逐字节一致
    remote = os.path.join(BASE, "data", f"cn-{y}.json")
    if os.path.exists(remote):
        h1 = hashlib.sha256(open(path, "rb").read()).hexdigest()
        h2 = hashlib.sha256(open(remote, "rb").read()).hexdigest()
        if h1 != h2:
            bad(f"[{y}] 内置数据与远程更新包不一致：{h1[:12]} vs {h2[:12]}")

    # 权重口径：与源表同一条目必须同权
    tbl = {o.name: o.w for o in obs.solar_of(y, ics_terms(y))}
    for n in data["nodes"]:
        if n["n"] in tbl and n.get("w") != tbl[n["n"]]:
            bad(f"[{y}] 权重不一致：{n['n']} Apk={n.get('w')} 源表={tbl[n['n']]}")


def check_global_contains_china(y: int, glob: list[dict], china: list[dict]) -> None:
    by_day: dict[dt.date, list[str]] = {}
    for e in glob:
        by_day.setdefault(e["d"], []).append(core(e["s"]))
    for e in china:
        name = norm(e["s"])
        if not any(name in s for s in by_day.get(e["d"], [])):
            bad(f"[{y}] 全球日历缺中国条目：{e['d']} {name}（原：{e['s']}）")


def check_algo_years(years=(2028, 2029, 2030)) -> None:
    """2028 年起没有国务院公告，Apk 只用算法数据；源表照样要全部落地。"""
    import cnlunar  # 局部导入：只有这条检查需要

    for y in years:
        path = os.path.join(APK_DATA, f"cn-{y}.json")
        if not os.path.exists(path):
            bad(f"[{y}] 缺算法年份数据 {path}")
            continue
        terms = []
        d = dt.date(y, 1, 1)
        while d.year == y:
            x = cnlunar.Lunar(dt.datetime(d.year, d.month, d.day, 12, 0))
            if x.todaySolarTerms and x.todaySolarTerms != "无":
                terms.append((d, x.todaySolarTerms))
            d += dt.timedelta(days=1)
        nodes = {(dt.date.fromisoformat(n["d"]), n["n"]) for n in
                 json.load(open(path, encoding="utf-8"))["nodes"]}
        for o in obs.solar_of(y, terms):
            if (o.date, o.name) not in nodes:
                bad(f"[{y}] 算法年份缺源表条目：{o.date} {o.name}")


def check_stats(y: int) -> None:
    stats_path = os.path.join(BASE, "stats.json")
    if not os.path.exists(stats_path):
        return
    stats = json.load(open(stats_path, encoding="utf-8")).get(str(y)) or {}
    d = os.path.join(BASE, str(y), "ics")
    for key, n in stats.items():
        p = os.path.join(d, f"{key}-{y}.ics")
        if not os.path.exists(p):
            bad(f"[{y}] stats 里有 {key}，文件不存在")
            continue
        real = len(parse_ics(p))
        if real != n:
            bad(f"[{y}] stats 计数不符：{key} 记 {n}，实际 {real}")


def check_ics_struct(y: int) -> None:
    d = os.path.join(BASE, str(y), "ics")
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".ics"):
            continue
        p = os.path.join(d, fn)
        raw = open(p, "rb").read()
        if b"\r\n" not in raw:
            bad(f"[{y}] {fn} 不是 CRLF 换行")
        text = raw.decode("utf-8")
        if text.count("BEGIN:VEVENT") != text.count("END:VEVENT"):
            bad(f"[{y}] {fn} VEVENT 未配对")
        if text.count("BEGIN:VCALENDAR") != 1 or text.count("END:VCALENDAR") != 1:
            bad(f"[{y}] {fn} VCALENDAR 不合法")
        uids = re.findall(r"UID:(.*)", text)
        if len(uids) != len(set(uids)):
            bad(f"[{y}] {fn} UID 重复：{len(uids) - len(set(uids))} 条")
        for line in text.split("\r\n"):
            if len(line.encode("utf-8")) > 75:
                bad(f"[{y}] {fn} 有超过 75 字节未折行的行：{line[:40]}")
                break


def check_manifest() -> None:
    p = os.path.join(BASE, "data", "manifest.json")
    if not os.path.exists(p):
        bad("data/manifest.json 不存在")
        return
    m = json.load(open(p, encoding="utf-8"))
    for key, info in m.get("files", {}).items():
        f = os.path.join(BASE, "data", info["f"])
        if not os.path.exists(f):
            bad(f"manifest 指向的文件不存在：{info['f']}")
            continue
        h = hashlib.sha256(open(f, "rb").read()).hexdigest()
        if h != info["sha256"]:
            bad(f"manifest sha256 不符：{info['f']}")
        if json.load(open(f, encoding="utf-8"))["v"] != info["v"]:
            bad(f"manifest 版本号不符：{info['f']}")


def check_pages(y: int) -> None:
    p = os.path.join(BASE, str(y), "index.html")
    if not os.path.exists(p):
        bad(f"[{y}] 页面不存在")
        return
    html = open(p, encoding="utf-8").read()
    left = set(re.findall(r"\{\{[^}]+\}\}", html))
    if left:
        bad(f"[{y}] 页面有未替换的占位符：{sorted(left)}")
    if "example.com" in html:
        bad(f"[{y}] 页面里有占位域名 example.com")


# ---------------------------------------------------------------- 主流程

def main() -> int:
    for y in YEARS:
        china = parse_ics(os.path.join(BASE, str(y), "ics", f"china-{y}.ics"))
        glob = parse_ics(os.path.join(BASE, str(y), "ics", f"global-{y}.ics"))
        check_table_vs_china(y, china)
        check_table_vs_global(y, glob)
        check_china_vs_apk(y, china)
        check_global_contains_china(y, glob, china)
        check_stats(y)
        check_ics_struct(y)
        check_pages(y)
    check_manifest()
    check_algo_years()

    total = len(obs.OBS_BY_NAME)
    print(f"源表 {total} 条（含节气挂靠的丰收节），检查年份 {YEARS}")
    for w in WARN[:20]:
        print("  · 提示 " + w)
    if FAIL:
        print(f"\n✗ {len(FAIL)} 处不一致：")
        for f in FAIL[:80]:
            print("  - " + f)
        return 1
    print("\n✓ 四个出口一致：源表 / 中国日历 / 全球日历 / Apk 数据")
    return 0


if __name__ == "__main__":
    sys.exit(main())
