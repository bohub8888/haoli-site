#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""节日自动发现器 —— 每天从权威源发现「尚未纳入」的节日候选。

背景（用户 2026-11-19 定档）
----------------------------
此前节日全靠人工策展（curated.py / observances.py / discovered_days.py），
没有「主动扫描发现」能力。用户早上问元宝得到一批同类节日、我却没有主动
发现，因此要求补上这个模块：每天自动通过搜索 / 扫描官媒，发现值得纳入
的节日。

两条发现通道（按可靠性排序）
----------------------------
1. UN 官方国际日列表 https://www.un.org/en/observances/list-days-weeks
   —— 权威、结构化、自带日期 + A/RES 决议号，机器可读。已实测可解析 98 条。
   与 observances.py 现有中文名做差集，差出来的即「官方有、我库里没有」。
2. 央视网新闻通稿搜索 https://search.cctv.com/search.php?qtext=
   —— 「决定 / 设立每年 X 月 X 日为 XX 日」句式。复用会议模块已验证的
   fetch + clean_html。这条通道命中不稳定（查询词回显噪音多），只作候选，
   且必须自带 4 位年份 + 权威机构 + 确切日期才采纳，拿不准一律放弃。

红线（拿不准就放弃，绝不误入库）
--------------------------------
  * 只产出「候选」，不直接改任何源表 —— 节日入库要写 public/note 编者文字
    和 A/B 级来源，机器无法保证质量，这部分维持人工策展；本模块的职责是
    「把候选可靠地找出来并留痕」，让人工核源有明确入口。
  * 已在库里的（名称或同月同日同名）一律不重复报。
  * 抓取失败 / 解析异常 / 无确切日期 / 无来源 → 静默放弃。
  * 候选报告写入 data/discovered-holidays-report.json（含日期、来源、决议号、
    抓取时间、来源 URL），供人工核源；同时打印人类可读摘要。

用法
----
  python discover_days_auto.py              # 在线发现,写候选报告
  python discover_days_auto.py --dry-run    # 只打印不写文件
  python discover_days_auto.py --offline    # 用缓存(调试)

本文件由 haoli-data 仓维护；入库仍走 curated.py / observances.py 的人工闸门。
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "data", "discovered-holidays-report.json")
SEEN = os.path.join(HERE, "data", "discovery-seen.json")
CACHE = os.path.join(HERE, "data", "discovery-cache")
UN_URL = "https://www.un.org/en/observances/list-days-weeks"
CCTV_SEARCH = "https://search.cctv.com/search.php?qtext={q}&type=web"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"

_MONTH = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

# 官媒通稿里「值得纳入」的信号机构：只有这些主体设立/决定的才进候选
_AUTHORITY = ("全国人大常委会", "全国人民代表大会常务委员会", "国务院", "中共中央",
              "中央军委", "国家主席", "联合国大会")

# 明显的政治/领土/战争议题红线（与 taxonomy REDLINES 对齐）：命中直接放弃
_REDLINE = ("台湾", "西藏", "新疆", "香港", "主权", "制裁", "侵略", "战争", "领土")

_TAG = re.compile(r"<[^>]+>")


def log(msg: str) -> None:
    print(f"[discover] {msg}", flush=True)


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def clean_html(raw: str) -> str:
    txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S | re.I)
    return html.unescape(_TAG.sub(" ", txt))


def _cache_path(key: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "_", key)
    return os.path.join(CACHE, safe + ".html")


def get_page(key: str, url: str, offline: bool = False) -> str:
    """在线成功刷新缓存；失败回落缓存；都没有返回空串（上层静默放弃）。"""
    cp = _cache_path(key)
    if offline:
        return open(cp, encoding="utf-8", errors="replace").read() if os.path.exists(cp) else ""
    try:
        raw = fetch(url)
        os.makedirs(CACHE, exist_ok=True)
        with open(cp, "w", encoding="utf-8") as f:
            f.write(raw)
        return raw
    except Exception as e:
        log(f"抓取失败（{type(e).__name__}），回落缓存：{key}")
        return open(cp, encoding="utf-8", errors="replace").read() if os.path.exists(cp) else ""


# ------------------------------------------------------------------ 通道1：UN 列表

# UN 页面每条 = 名称<a> + 决议号 + field-event-date-1 里的 "DD Mon"。
# 不靠「切块到下个链接」（日期字段距名称超过固定长度会漏），改为全文按位置就近配对。
_UN_LINK = re.compile(
    r'<a href="https://www\.un\.org/en/observances/[^"]+">([^<]{3,70})</a>')
_UN_DATE_POS = re.compile(
    r'field-event-date-1[^>]*>\s*(?:<[^>]+>\s*)*(\d{1,2})\s+([A-Za-z]{3})')
_UN_RES = re.compile(r"A/RES/[0-9/]+")


def parse_un(raw: str) -> list[dict]:
    """解析 UN 官方列表，返回 [{name_en, mmdd, resolution, url}]. 拿不准的跳过。"""
    # 名称锚点（只收 Day/Week/Year/Decade 结尾的节日，排除栏目名）
    names = [(m.start(), html.unescape(m.group(1)).strip()) for m in _UN_LINK.finditer(raw)]
    names = [(p, n) for p, n in names if re.search(r"(Day|Week|Year|Decade)$", n)
             and n not in ("International Days and Weeks",)]
    dates = [(m.start(), int(m.group(1)), _MONTH.get(m.group(2)[:3].title()))
             for m in _UN_DATE_POS.finditer(raw)]
    dates = [(p, d, mo) for p, d, mo in dates if mo]

    out: list[dict] = []
    for pos, name in names:
        # 就近取该名称之后、下一个名称之前的第一组日期（含首不含尾）
        nxt = next((p2 for p2, _ in names if p2 > pos), len(raw))
        cand = [(p, d, mo) for p, d, mo in dates if pos < p < nxt]
        if not cand:
            continue
        _p, day, mon = cand[0]
        try:
            dt.date(2000, mon, day)  # 校验日期合法（含 2/29）
        except ValueError:
            continue
        seg = raw[pos:nxt]
        res = _UN_RES.search(seg)
        out.append({
            "name_en": name,
            "mmdd": f"{mon:02d}-{day:02d}",
            "resolution": res.group(0) if res else "",
            "source": "联合国官方国际日/周列表（A/RES 决议）",
            "url": UN_URL,
        })
    return out


# ------------------------------------------------------------------ 通道2：官媒通稿

# 「决定/设立 每年 X 月 X 日为 XX（日/节/周）」——自带年份才采纳
_CCTV_SENT = re.compile(
    r"(?P<prefix>[^。；！？\n]{0,60}?)"
    r"(?P<y>20\d{2})\s*年"
    r"[^。；！？\n]{0,40}?"
    r"(?:决定|设立|批准|同意)"
    r"[^。；！？\n]{0,40}?"
    r"(?:每年)?\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"
    r"[^。；！？\n]{0,30}?"
    r"为(?P<name>[\u4e00-\u9fff]{2,12}?(?:日|节|周|月))"
    r"(?P<suffix>[^。；！？\n]{0,30})"
)

# 已知节日的中文名（用于差集）；从现有库导入，避免重复报
def _known_names() -> set[str]:
    names: set[str] = set()
    try:
        import observances as obs
        names |= {x[2] for x in obs.CN_SOLAR}
    except Exception:
        pass
    try:
        import curated
        names |= {e["name"] for e in curated.ENTRIES}
    except Exception:
        pass
    # 不依赖 deploy 仓的 discovered_days.py：那是故事页选题库（部分条目不在主日历库），
    # 且 CI 的数据仓 checkout 里没有该目录。去重基准只认本仓的观测表 + 策展库，
    # 保证 CI 与本地行为一致；故事页库里的中文名不会与 UN 英文候选相撞。
    return names


# 英文 UN 名 -> 中文通行名的粗略映射（只覆盖已确认译法；无映射的留给人工）
_UN_ZH = {
    "World Braille Day": "世界盲文日", "World Wetlands Day": "世界湿地日",
    "International Mother Language Day": "国际母语日", "World Radio Day": "世界无线电日",
    "International Women's Day": "妇女节", "World Water Day": "世界水日",
    "World Health Day": "世界卫生日", "Earth Day": "世界地球日",
    "International Labour Day": "劳动节", "World Environment Day": "世界环境日",
    "International Children's Day": "儿童节", "World Ocean Day": "世界海洋日",
    "International Literacy Day": "国际扫盲日", "World Teachers' Day": "世界教师日",
    "United Nations Day": "联合国日", "World AIDS Day": "世界艾滋病日",
    "International Human Rights Day": "世界人权日",
}


def parse_cctv(raw: str, known: set[str]) -> list[dict]:
    """解析央视网搜索页，提取「新设纪念日」候选。红线命中/无权威机构/已知的一律放弃。"""
    txt = clean_html(raw)
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for m in _CCTV_SENT.finditer(txt):
        ctx = m.group("prefix") + m.group(0) + m.group("suffix")
        if not any(a in ctx for a in _AUTHORITY):  # 必须权威机构设立
            continue
        if any(r in ctx for r in _REDLINE):        # 政治/领土红线
            continue
        y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
        name = m.group("name").strip()
        try:
            date = dt.date(y, mo, d)
        except ValueError:
            continue
        if name in known:                          # 已在库 → 不报
            continue
        key = (name, f"{mo:02d}-{d:02d}")
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "name_zh": name,
            "mmdd": f"{mo:02d}-{d:02d}",
            "year_established": y,
            "source": "央视网通稿（权威机构设立）",
            "url": "",
            "sentence": ctx.strip()[:120],
        })
    return out


# ------------------------------------------------------------------ 主流程

def main() -> int:
    offline = "--offline" in sys.argv
    dry = "--dry-run" in sys.argv
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    log(f"开始节日发现（{'离线' if offline else '在线'}，{now}）")

    known = _known_names()
    log(f"现有库已知节日名 {len(known)} 个（去重基准）")

    # 已见过的 UN 英文名：首次运行把当前列表记为基线，之后只报「新出现」的，
    # 避免每天把同一批无译名条目反复当候选（噪音）。
    try:
        seen = set(json.load(open(SEEN, encoding="utf-8"))["seen_en"])
    except Exception:
        seen = set()
    first_run = not seen

    candidates: list[dict] = []

    # 通道1：UN 官方列表
    raw = get_page("un_list_days_weeks", UN_URL, offline)
    raw_un_ok = bool(raw)
    if raw:
        un_items = parse_un(raw)
        log(f"UN 列表解析出 {len(un_items)} 条")
        for it in un_items:
            en = it["name_en"]
            zh = _UN_ZH.get(en)
            newly_seen = en not in seen

            # 已入库的中文名永远不报；未译名的只报「首次见到」的新增
            if zh:
                if zh not in known:
                    candidates.append({
                        "name_zh": zh, "name_en": en, "mmdd": it["mmdd"],
                        "source": it["source"], "url": it["url"],
                        "resolution": it["resolution"], "channel": "UN官方列表",
                        "status": "待核源入库",
                    })
            elif newly_seen and not first_run:
                candidates.append({
                    "name_zh": "", "name_en": en, "mmdd": it["mmdd"],
                    "source": it["source"], "url": it["url"],
                    "resolution": it["resolution"], "channel": "UN官方列表",
                    "status": "需人工译名",
                })
            seen.add(en)
        log(f"UN 列表 {len(un_items)} 条（{'首轮建基线' if first_run else '增量比对'}）")
    else:
        log("UN 列表无数据，跳过该通道")

    # 通道2：官媒通稿（只扫几个通用词，避免逐条盲扫）
    for q in ("全国人大常委会 决定 设立 每年 纪念日", "国务院 批准 设立 每年 日"):
        raw = get_page("cctv_" + q, CCTV_SEARCH.format(q=urllib.parse.quote(q)), offline)
        if not raw:
            continue
        for c in parse_cctv(raw, known):
            c["channel"] = "央视网通稿"
            candidates.append(c)

    # 去重（按中文名 + 月日）
    uniq: dict[tuple[str, str], dict] = {}
    for c in candidates:
        uniq.setdefault((c.get("name_zh", ""), c.get("mmdd", "")), c)
    final = sorted(uniq.values(), key=lambda x: x.get("mmdd", ""))

    report = {
        "generated_at": now,
        "known_count": len(known),
        "candidate_count": len(final),
        "candidates": final,
        "note": "候选需人工核源并过 curated/observances 闸门后才入库；本模块不直接改源表。",
    }
    log(f"发现候选 {len(final)} 条")
    for c in final:
        log(f"  · {c['mmdd']} {c.get('name_zh') or c.get('name_en')} "
            f"[{c['channel']}] {c.get('resolution', '')}")

    if not dry:
        os.makedirs(os.path.dirname(REPORT), exist_ok=True)
        with open(REPORT, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        log(f"候选报告已写入 {os.path.relpath(REPORT, HERE)}")
        # 更新已见基线：只有英文名集合真的变化才写，避免每天因时间戳产生无意义 commit。
        # 只在成功抓取 UN 列表后写，防止抓取失败时空列表覆盖基线。
        if raw_un_ok:
            try:
                old_seen = set(json.load(open(SEEN, encoding="utf-8"))["seen_en"])
            except Exception:
                old_seen = set()
            if seen != old_seen:
                with open(SEEN, "w", encoding="utf-8") as f:
                    json.dump({"seen_en": sorted(seen), "updated_at": now}, f, ensure_ascii=False, indent=2)
                log(f"已见基线已更新（{len(old_seen)} → {len(seen)} 条）")
            else:
                log("已见基线无变化，不重写")
    else:
        log("dry-run：未写文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
