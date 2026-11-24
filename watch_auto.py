#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会议日期全自动核对入库（云端 CI 运行；零用户参与）。

设计红线（用户 2026-11-19 定档）
--------------------------------
  · 用户判断：重要会议日期一旦官方确定即稳定，官方媒体发布即可信 → 自动采纳，不设人工闸门。
  · 命中即自动生成 ENTRY，从 WATCHLIST 移除，重建 → 全量校验 → 写信号 → 交给 CI 分发。
    全端一致，不发 APK。
  · 拿不准就静默放弃：抓取失败 / 日期歧义 / 闸门不过 → 一律不动。

两条核源通道（2026-11-19 升级：用户指出"官方媒体必发通稿"，实测推翻旧结论）
-----------------------------------------------------------------------------
  1) JSON-LD：部分国际展会官网有机器可读 Event.startDate/endDate，直接读。
  2) 新闻通稿：对 WATCHLIST 全部条目，抓央视网搜索结果，识别
     "将于/定于[20XX年]X月X日[至X月X日]在X举行/举办/召开/开幕" 句式。
     —— 只有"自带 4 位年份且年份==预期年份"的通稿句才被采纳：往届旧闻
     （"第九届进博会将于11月5日…"无年份）一律放弃，杜绝拿旧日期冒充新定档。
  实测：进博会→2027-11-5~10、广交会→2027-4-15~5-5，均精准；旧闻被挡。
  之前"不读新闻"的结论是只测了官网首页/通用搜索/政策库、漏测媒体通稿所致，已纠正。

用法
----
    python watch_auto.py               # 在线核对 + 自动更新
    python watch_auto.py --dry-run     # 只核对解析，不改任何文件
    python watch_auto.py --offline     # 用缓存（调试解析器）
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
CONF = os.path.join(HERE, "conferences.py")
CACHE = os.path.join(HERE, "data", "conference-watch-cache")
REPORT = os.path.join(HERE, "data", "conference-watch-report.json")
SIG = os.path.join(HERE, ".auto_update_changed")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"
WINDOW_DAYS = 240          # 解析日期须落在 date_hint 前后这个窗口内
AUTO_MARK = "自动核源"      # 本脚本入库条目的 note 标记，用于改期复检与防重

# ---------------------------------------------------------------- 通道一：官网 JSON-LD
# 只有这些官网确认有稳定的 JSON-LD Event 日期（2026-11-19 实测）。
STRUCTURED_SOURCES: dict[str, dict] = {
    "Web Summit":   {"url": "https://websummit.com/", "tag": "会议", "scope": "world", "place": "葡萄牙里斯本"},
    "GITEX Global": {"url": "https://www.gitex.com/", "tag": "展会", "scope": "world", "place": "阿联酋迪拜"},
    "世界能源大会":   {"url": "https://www.worldenergy.org/", "tag": "会议", "scope": "world", "place": "主办地待官网公布"},
}

# ---------------------------------------------------------------- 通道二：新闻通稿搜索词
# 每条 WATCHLIST：央视网 qtext 搜索词（简称往往比全称命中率高）+ 识别关键词（任一命中即可）。
# 这是"检索配置"，非人工闸门——运行时全自动。
NEWS_SOURCES: dict[str, dict] = {
    "全国政协十四届五次会议":   {"query": "全国政协五次会议", "keys": ["政协", "两会"]},
    "十四届全国人大五次会议":   {"query": "全国人大五次会议", "keys": ["人大", "两会"]},
    "中国国际医疗器械博览会（春季）": {"query": "CMEF 春季 医疗器械博览会", "keys": ["医疗器械博览会", "CMEF"]},
    "中国国际消费品博览会":    {"query": "消博会", "keys": ["消博会", "消费品博览会"]},
    "中国进出口商品交易会（春季）": {"query": "广交会", "keys": ["广交会", "进出口商品交易会"]},
    "世界能源大会":           {"query": "世界能源大会", "keys": ["世界能源大会", "World Energy Congress"]},
    "世界数字教育大会":        {"query": "世界数字教育大会", "keys": ["数字教育大会"]},
    "世界卫生大会":           {"query": "世界卫生大会", "keys": ["世界卫生大会", "世卫大会"]},
    "陆家嘴论坛":             {"query": "陆家嘴论坛", "keys": ["陆家嘴论坛"]},
    "中国国际供应链促进博览会":  {"query": "链博会", "keys": ["链博会", "供应链促进博览会"]},
    "机器人世界杯":           {"query": "机器人世界杯 RoboCup", "keys": ["机器人世界杯", "RoboCup"]},
    "世界人工智能大会":        {"query": "世界人工智能大会", "keys": ["人工智能大会", "WAIC"]},
    "中国国际服务贸易交易会":   {"query": "服贸会", "keys": ["服贸会", "服务贸易交易会"]},
    "中国—东盟博览会":         {"query": "中国东盟博览会", "keys": ["东盟博览会"]},
    "全球数字贸易博览会":      {"query": "全球数字贸易博览会", "keys": ["数字贸易博览会"]},
    "世界粮食论坛":           {"query": "世界粮食论坛", "keys": ["世界粮食论坛"]},
    "GITEX Global":           {"query": "GITEX", "keys": ["GITEX"]},
    "中国国际工业博览会":      {"query": "工博会", "keys": ["工博会", "工业博览会"]},
    "中国进出口商品交易会（秋季）": {"query": "广交会", "keys": ["广交会", "进出口商品交易会"]},
    "金融街论坛年会":          {"query": "金融街论坛", "keys": ["金融街论坛"]},
    "中国国际教育年会":        {"query": "中国国际教育年会", "keys": ["教育年会"]},
    "世界互联网大会乌镇峰会":   {"query": "世界互联网大会 乌镇峰会", "keys": ["乌镇峰会", "世界互联网大会"]},
    "中国香港金融科技周":      {"query": "香港金融科技周", "keys": ["金融科技周", "FinTech Week"]},
    "中国国际进口博览会":      {"query": "进博会", "keys": ["进博会", "进口博览会"]},
    "联合国气候变化大会":      {"query": "联合国气候变化大会 COP", "keys": ["气候变化大会", "COP"]},
    "Web Summit":            {"query": "Web Summit", "keys": ["Web Summit"]},
    "中国国际农产品交易会":    {"query": "中国国际农产品交易会", "keys": ["农产品交易会"]},
    "世界智能制造大会":        {"query": "世界智能制造大会", "keys": ["智能制造大会"]},
}

# 正式池无同名条目时的兜底配置（scope / place / tag）。url 一律取 WATCHLIST 自带。
FALLBACK_CFG: dict[str, dict] = {
    "全国政协十四届五次会议":   {"scope": "cn", "place": "中国北京", "tag": "会议"},
    "十四届全国人大五次会议":   {"scope": "cn", "place": "中国北京", "tag": "会议"},
    "中国国际医疗器械博览会（春季）": {"scope": "cn", "place": "中国上海", "tag": "展会"},
    "中国进出口商品交易会（春季）": {"scope": "cn", "place": "中国广州", "tag": "展会"},
    "中国进出口商品交易会（秋季）": {"scope": "cn", "place": "中国广州", "tag": "展会"},
    "世界能源大会":           {"scope": "world", "place": "主办地待公布", "tag": "会议"},
}

CCTV_SEARCH = "https://search.cctv.com/search.php?qtext={q}&type=web"


def log(msg: str) -> None:
    print(f"[watch_auto] {msg}", flush=True)


# ---------------------------------------------------------------- 抓取

def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def cache_path(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "_", name)
    return os.path.join(CACHE, safe + ".html")


def get_page(name: str, url: str, offline: bool = False) -> tuple[str, str]:
    """返回 (正文, 来源说明)。在线成功则刷新缓存；失败回落缓存；无缓存返回空。"""
    cp = cache_path(name)
    if offline:
        return (open(cp, encoding="utf-8", errors="replace").read(), "缓存（离线）") if os.path.exists(cp) else ("", "无缓存（离线）")
    try:
        raw = fetch(url)
        os.makedirs(CACHE, exist_ok=True)
        with open(cp, "w", encoding="utf-8") as f:
            f.write(raw)
        return raw, "官网在线"
    except Exception as e:
        if os.path.exists(cp):
            log(f"  ! {name} 抓取失败({type(e).__name__})，回落缓存")
            return open(cp, encoding="utf-8", errors="replace").read(), "缓存（抓取失败）"
        return "", f"抓取失败({type(e).__name__})，无缓存"


# ---------------------------------------------------------------- 解析（纯函数，可单测）

LD_BLOCK = re.compile(r'application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
DATE_FIELD = re.compile(r'"(startDate|endDate)"\s*:\s*"([^"]+)"')
TYPE_EVENT = re.compile(r'"@type"\s*:\s*"Event"', re.I)


def _parse_date(value: str) -> dt.date | None:
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", value.strip())
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def extract_event_dates(html_text: str) -> tuple[dt.date | None, dt.date | None]:
    """取出 JSON-LD 里「最新年份」那组 Event 的 (start, end)。"""
    candidates: list[tuple[int, dt.date | None, dt.date | None]] = []
    for block in LD_BLOCK.findall(html_text):
        if not TYPE_EVENT.search(block):
            continue
        fields = DATE_FIELD.findall(block)
        if not fields:
            continue
        d = {k: _parse_date(v) for k, v in fields}
        start, end = d.get("startDate"), d.get("endDate")
        if start or end:
            candidates.append((start.year if start else (end.year if end else 0), start, end))
    if not candidates:
        return None, None
    top_year = max(c[0] for c in candidates)
    same = [c for c in candidates if c[0] == top_year]
    starts = {c[1] for c in same if c[1]}
    if len(starts) > 1:
        log(f"  ! 同一年 {top_year} 出现 {len(starts)} 个不同开幕日 → 歧义放弃")
        return None, None
    start = next(iter(starts)) if starts else None
    ends = {c[2] for c in same if c[2]}
    end = sorted(ends)[-1] if ends else None
    return start, end


# ---- 新闻通稿解析 ----
_TAG = re.compile(r"<[^>]+>")
_SENT = re.compile(
    r"(?P<prefix>[^。；！？\n]{0,50}?)"
    r"(?:将于|定于)\s*"
    r"(?:(?P<y>20\d{2})\s*年\s*)?"
    r"(?P<m1>\d{1,2})\s*月\s*(?P<d1>\d{1,2})\s*日"
    r"(?:\s*[至到—\-~～]\s*(?:(?P<m2>\d{1,2})\s*月\s*)?(?P<d2>\d{1,2})\s*日)?"
    r"[^。；！？\n]{0,45}?"
    r"(?P<verb>举行|举办|召开|开幕|开展)"
    r"(?P<suffix>[^。；！？\n]{0,40})"
)


def clean_html(raw: str) -> str:
    txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S | re.I)
    return html.unescape(_TAG.sub(" ", txt))


NEWS_WINDOW_DAYS = 45     # 新闻通稿：开幕日须距预期 ≤45 天（挡住春/秋同名的撞车）


def parse_news_dates(raw: str, keys: list[str], want_year: int, hint: str) -> tuple | None:
    """从央视网搜索页提取带年份的确切会期。

    返回 (start, end, place, 句) 命中；("AMBIG", [..]) 歧义；None 放弃。
    红线：只认自带 4 位年份且 == want_year 的通稿句（无年份=往年旧闻，一律弃）；
    且开幕日须落在预期 ±45 天内（广交会春/秋同名，用这个窗口挡住串季）。
    """
    h = dt.date.fromisoformat(hint)
    txt = clean_html(raw)
    out: list[tuple] = []
    for m in _SENT.finditer(txt):
        ctx = m.group("prefix") + m.group(0)
        if not any(k in ctx for k in keys):
            continue
        y = int(m.group("y")) if m.group("y") else None
        if y is None or y != want_year:      # 旧闻 / 年份不符 → 弃
            continue
        m1, d1 = int(m.group("m1")), int(m.group("d1"))
        m2 = int(m.group("m2")) if m.group("m2") else m1
        d2 = int(m.group("d2")) if m.group("d2") else d1
        if m2 < m1:                           # 跨年不处理
            continue
        try:
            start, end = dt.date(y, m1, d1), dt.date(y, m2, d2)
        except ValueError:
            continue
        if end < start or (end - start).days > 30:
            continue
        if abs((start - h).days) > NEWS_WINDOW_DAYS:   # 串季/串会防御
            continue
        pm = re.search(r"在([^，,。；\s]{2,15}?)(?:举行|举办|召开|开幕)", m.group(0))
        place = pm.group(1) if pm else ""
        out.append((start, end, place, ctx.strip()[:100]))
    if not out:
        return None
    if len({(o[0], o[1]) for o in out}) > 1:  # 多句日期不一致 → 歧义放弃
        return ("AMBIG", out)
    return out[0]


def gate(start: dt.date | None, end: dt.date | None, hint: str) -> tuple[bool, str]:
    """强闸门：日期合法 / 落在预期窗口 / 跨度合理。"""
    if not start:
        return False, "无确切开幕日"
    h = dt.date.fromisoformat(hint)
    if abs((start - h).days) > WINDOW_DAYS:
        return False, f"开幕日 {start} 距预期 {h} 超过 {WINDOW_DAYS} 天"
    if end:
        if end < start:
            return False, f"结束日 {end} 早于开幕 {start}"
        if (end - start).days > 30:
            return False, f"会期跨度 {(end - start).days} 天异常"
    return True, "通过"


# ---------------------------------------------------------------- 源码改写（精确、幂等）

def watch_hint(src: str, name: str) -> str | None:
    m = re.search(r'W\("(\d{4}-\d{2}-\d{2})",\s*"' + re.escape(name) + r'"', src)
    return m.group(1) if m else None


def watch_url(src: str, name: str) -> str | None:
    m = re.search(r'W\("\d{4}-\d{2}-\d{2}",\s*"' + re.escape(name) + r'".*?"(https?://[^"]+)"', src, re.S)
    return m.group(1) if m else None


def entry_years(src: str, name: str) -> set[int]:
    years = set()
    for m in re.finditer(r'C\("(\d{4})-\d{2}-\d{2}",\s*"\d{4}-\d{2}-\d{2}",\s*"' + re.escape(name) + r'"', src):
        years.add(int(m.group(1)))
    return years


def config_for(name: str, src: str) -> dict | None:
    """生成新条目所需配置：scope/place/tag 优先继承正式池同名，否则兜底；url 取 WATCHLIST。"""
    cfg = dict(FALLBACK_CFG.get(name, {}))
    for m in re.finditer(r'C\("\d{4}-\d{2}-\d{2}",\s*"\d{4}-\d{2}-\d{2}",\s*"' + re.escape(name) + r'",\s*"([^"]*)",\s*"([^"]*)"', src):
        cfg["scope"], cfg["place"] = m.group(1), m.group(2)
        # tag 在该 C(...) 条目内：从匹配点到下一个 C( 或 WATCHLIST 声明
        nxt = re.search(r'\n\s*(?:C\(|WATCHLIST:)', src[m.end():])
        tail_end = m.end() + nxt.start() if nxt else len(src)
        tail = src[m.start():tail_end]
        tm = re.search(r'tag="([^"]+)"', tail)
        cfg["tag"] = tm.group(1) if tm else "会议"   # C() 的 tag 默认就是"会议"
        break
    url = watch_url(src, name)
    if url:
        cfg["url"] = url
    if not all(k in cfg for k in ("scope", "place", "tag", "url")):
        return None
    return cfg


def make_entry_line(name: str, start: dt.date, end: dt.date | None, cfg: dict) -> str:
    place = cfg["place"]
    where = f"在{place}" if place and "待" not in place and "公布" not in place else ""
    if end and end > start:
        pub = f"{name}于 {start.month} 月 {start.day} 日至 {end.day} 日{where}举行。"
    else:
        pub = f"{name}于 {start.month} 月 {start.day} 日{where}举行。"
    src_label = cfg.get("source", f"{name}官网·官方发布")
    note = f"官方发布确切会期；{AUTO_MARK}自动入库。"
    return (
        f'    C("{start.isoformat()}", "{(end or start).isoformat()}", "{name}",\n'
        f'      "{cfg["scope"]}", "{cfg["place"]}",\n'
        f'      "{src_label}",\n'
        f'      "{cfg["url"]}", "A",\n'
        f'      "{pub}",\n'
        f'      "{note}", tag="{cfg["tag"]}"),'
    )


def apply_entry(src: str, name: str, line: str) -> str:
    """追加 ENTRY 到 ENTRIES 末尾，并从 WATCHLIST 删除该条（仅删精确匹配名）。"""
    wl = re.compile(r'\n[ \t]*W\("\d{4}-\d{2}-\d{2}",\s*"' + re.escape(name) + r'".*?\),(?=\n)', re.S)
    src2, n = wl.subn("", src, count=1)
    if n != 1:
        raise RuntimeError(f"WATCHLIST 中未找到唯一条目：{name}")
    wpos = src2.find("WATCHLIST:")
    epos = src2.rfind("\n]", 0, wpos)
    if epos < 0:
        raise RuntimeError("找不到 ENTRIES 结束符")
    return src2[:epos] + "\n" + line + src2[epos:]


def update_existing(src: str, name: str, start: dt.date, end: dt.date | None) -> str:
    """改期复检：只更新带 AUTO_MARK 的自动条目。"""
    d0, d1 = start.isoformat(), (end or start).isoformat()
    pat = re.compile(
        r'C\("(\d{4}-\d{2}-\d{2})",\s*"(\d{4}-\d{2}-\d{2})",\s*"' + re.escape(name) +
        r'".*?' + AUTO_MARK + r'.*?\)', re.S)
    def repl(m):
        return re.sub(r'C\("\d{4}-\d{2}-\d{2}",\s*"\d{4}-\d{2}-\d{2}"',
                      f'C("{d0}", "{d1}"', m.group(0), count=1)
    new, n = pat.subn(repl, src, count=1)
    return new if n else src


# ---------------------------------------------------------------- 构建与校验

def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, shell=True, cwd=HERE, text=True, capture_output=True, timeout=900)
    if check and r.returncode != 0:
        raise RuntimeError(f"命令失败: {cmd}\n{r.stdout}\n{r.stderr}")
    return r


def rebuild_and_verify() -> bool:
    log("重建（build.py）…")
    r = run(f'"{PY}" build.py', check=False)
    if r.returncode != 0:
        log("✗ 构建失败：" + (r.stdout or "")[-500:])
        return False
    log("全量校验…")
    for script in ("check_consistency.py", "check_key_dates.py", "check_translations.py"):
        rr = run(f'"{PY}" {script}', check=False)
        log(f"  {script}: {'OK' if rr.returncode == 0 else 'FAIL'}")
        if rr.returncode != 0:
            log(f"    报错详情: {(rr.stdout or '')[-800:]} {(rr.stderr or '')[-400:]}")
            return False
    return True


# ---------------------------------------------------------------- 主流程

def resolve_dates(name: str, hint: str, offline: bool) -> tuple[dt.date | None, dt.date | None, str, dict]:
    """双通道解析。返回 (start, end, 通道说明, 附加dict{place,src_label})。"""
    meta: dict = {}
    # 通道一：官网 JSON-LD
    if name in STRUCTURED_SOURCES:
        cfg0 = STRUCTURED_SOURCES[name]
        raw, how = get_page(name, cfg0["url"], offline=offline)
        if raw:
            s, e = extract_event_dates(raw)
            if s:
                return s, e, f"JSON-LD（{how}）", {"place": "", "src_label": f"{name}官网·结构化事件数据（JSON-LD）"}
    # 通道二：央视网新闻通稿
    ns = NEWS_SOURCES.get(name)
    if not ns:
        return None, None, "无核源配置", meta
    q = CCTV_SEARCH.format(q=urllib.parse.quote(ns["query"]))
    raw, how = get_page("新闻_" + name, q, offline=offline)
    if not raw:
        return None, None, f"新闻抓取失败（{how}）", meta
    want_year = dt.date.fromisoformat(hint).year
    r = parse_news_dates(raw, ns["keys"], want_year, hint)
    if r is None:
        return None, None, "通稿无带年份的确切会期（放弃）", meta
    if isinstance(r[0], str) and r[0] == "AMBIG":
        log(f"  ! {name} 多篇通稿日期不一致 → 歧义放弃")
        return None, None, "通稿日期歧义（放弃）", meta
    s, e, place, sent = r
    return s, e, f"新闻通稿（{how}）：{sent}", {"place": place, "src_label": f"央视网·{name}官方发布通稿"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    if os.path.exists(SIG):
        os.remove(SIG)

    src = open(CONF, encoding="utf-8").read()
    results: list[dict] = []
    new_src = src
    changed = False

    # 遍历 WATCHLIST 全部条目（不再只遍历 3 条 JSON-LD）
    names = re.findall(r'W\("\d{4}-\d{2}-\d{2}",\s*"([^"]+)"', src)
    for name in names:
        hint = watch_hint(new_src, name)
        row = {"name": name, "watch_hint": hint}
        if not hint:
            row["status"] = "no_hint"; results.append(row); continue

        start, end, how, meta = resolve_dates(name, hint, args.offline)
        row["source"] = how
        row["dates"] = [d.isoformat() for d in (start, end) if d]
        if not start:
            row["status"] = "no_date"; log(f"{name}: {how} → 放弃"); results.append(row); continue

        ok, why = gate(start, end, hint)
        if not ok:
            row["status"] = "gate_reject"; row["why"] = why
            log(f"{name}: 闸门未过（{why}）→ 放弃"); results.append(row); continue

        have = entry_years(new_src, name)
        if start.year in have:
            row["status"] = "already_in_pool"
            if AUTO_MARK in new_src and f'"{name}"' in new_src:
                updated = update_existing(new_src, name, start, end)
                if updated != new_src:
                    new_src = updated; changed = True; row["status"] = "updated"
                    log(f"{name}: 自动条目检测到改期 → {start}~{end}")
            else:
                log(f"{name}: {start.year} 已在库（人工条目，不动）")
            results.append(row); continue

        cfg = config_for(name, new_src)
        if not cfg:
            row["status"] = "no_config"
            log(f"{name}: 无 scope/place/tag/url 配置 → 放弃"); results.append(row); continue
        if meta.get("place") and "待" not in meta["place"]:
            cfg["place"] = meta["place"]        # 通稿里的举办地优先
        if meta.get("src_label"):
            cfg["source"] = meta["src_label"]

        line = make_entry_line(name, start, end, cfg)
        row["status"] = "new_entry"
        log(f"{name}: 命中新档期 {start}~{end}（{how[:40]}）→ 生成 {start.year} 条目")
        if not args.dry_run:
            new_src = apply_entry(new_src, name, line)
            changed = True
        results.append(row)

    report = {
        "checked_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "policy": "官网JSON-LD + 央视网带年份通稿双通道；拿不准静默放弃；零用户参与",
        "results": results,
        "changed": changed,
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    if args.dry_run:
        log("[dry-run] 未改动任何文件"); return 0
    if not changed:
        log("✓ 无新定档 / 无改期，未改动（静默结束）"); return 0

    bak = CONF + ".autobak"
    shutil.copy2(CONF, bak)
    with open(CONF, "w", encoding="utf-8") as f:
        f.write(new_src)
    r = run(f'"{PY}" conferences.py', check=False)
    if r.returncode != 0:
        log("✗ conferences 闸门失败，回滚：" + (r.stdout or "")[-400:])
        shutil.move(bak, CONF); return 2
    if not rebuild_and_verify():
        log("✗ 重建/校验失败，回滚")
        shutil.move(bak, CONF); return 2
    os.remove(bak)
    with open(SIG, "w", encoding="utf-8") as f:
        f.write(dt.datetime.now().astimezone().isoformat(timespec="seconds"))
    log("✓ 会议日期已更新，全端重建完成 → 交给 CI 分发")
    return 0


if __name__ == "__main__":
    sys.exit(main())
