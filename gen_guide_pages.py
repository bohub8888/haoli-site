#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 SEO 长尾指南页（真实数据驱动，可重复执行）。

产出两类静态页，全部自包含（内联 CSS、无 JS、无外链依赖），放站点 /guide/ 下：
  1. 中国七大节日页：2027春节放假安排、国庆、清明……（日期/调休来自官方公告核对结果）
  2. 国家/地区节假日页：德国2027节假日、日本祝日……（节日本身来自该国 ICS）

每页都有独立 title/description/keywords/H1/真实数据表/JSON-LD/canonical/导入按钮，
避免"桥页"——内容因页面而异、全部取自项目真实数据，不是关键词堆砌空壳。

数据源：
  data/official-notice-report.json → 中国放假/调休（已与 gov.cn 核对）
  ics/{slug}.ics                   → 各国 2027 真实节假日
  data/countries.json              → slug→中文名映射
  site_config.py                   → 站点地址单点配置

用法：
  python3 gen_guide_pages.py            # 生成到 ../guide-pages/
  python3 gen_guide_pages.py --sitemap  # 同时生成 sitemap-guide.xml 片段
"""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
SITE = "https://oyster111.top"
YEAR = 2027
OUT = BASE.parent / "guide-pages"

WEEK = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def weekday(d: str) -> str:
    y, m, dd = (int(x) for x in d.split("-"))
    return WEEK[date(y, m, dd).weekday()]


def md(d: str) -> str:
    y, m, dd = (int(x) for x in d.split("-"))
    return f"{m} 月 {dd} 日"


def esc(s: str) -> str:
    return html.escape(s, quote=True)


# ---------- 公共页面骨架 ----------
CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif;background:#f5f5f7;color:#1d1d1f;line-height:1.7;-webkit-font-smoothing:antialiased}
.wrap{max-width:640px;margin:0 auto;padding:0 18px 48px}
a{color:#ff6b35}
.brand{display:flex;align-items:center;gap:9px;padding:20px 0 4px;text-decoration:none;color:inherit}
.brand img{width:34px;height:34px;border-radius:8px}
.brand .name{font-size:18px;font-weight:800}
.crumb{font-size:12px;color:#8e8e93;margin:10px 0 16px}
.crumb a{color:#8e8e93;text-decoration:none}
h1{font-size:24px;font-weight:800;line-height:1.35;letter-spacing:-0.02em;margin-bottom:8px}
.lead{font-size:14px;color:#6e6e73;margin-bottom:20px}
.panel{background:#fff;border-radius:14px;padding:16px 18px;box-shadow:0 1px 3px rgba(0,0,0,.05);margin-bottom:16px}
.panel h2{font-size:16px;font-weight:700;margin-bottom:12px;display:flex;align-items:center;gap:7px}
.panel h2::before{content:"";width:4px;height:15px;background:#ff6b35;border-radius:2px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:9px 6px;border-bottom:1px solid #f0f0f5;vertical-align:top}
th{color:#8e8e93;font-weight:600;font-size:12px;white-space:nowrap}
tr:last-child td{border-bottom:none}
.dt{font-variant-numeric:tabular-nums;white-space:nowrap;color:#1d1d1f;font-weight:600}
.wd{color:#8e8e93;font-size:12px;font-weight:400}
.tag{display:inline-block;font-size:11px;font-weight:600;color:#ff6b35;background:#fff1eb;border-radius:5px;padding:1px 6px;margin-left:4px}
.tag.off{color:#0a8f4d;background:#eaf8f0}
.cta{display:flex;flex-direction:column;gap:10px;margin:20px 0}
.btn{display:block;text-align:center;padding:13px;border-radius:11px;text-decoration:none;font-size:15px;font-weight:700}
.btn.primary{background:#ff6b35;color:#fff}
.btn.ghost{background:#fff;color:#1d1d1f;border:1px solid #eaeaef}
.note{font-size:12px;color:#8e8e93;line-height:1.7;margin-top:8px}
.related{font-size:13.5px;line-height:2}
.related a{text-decoration:none}
.foot{border-top:1px solid #eaeaef;margin-top:28px;padding-top:16px;font-size:11.5px;color:#a0a0a8;line-height:1.8}
.foot a{color:#a0a0a8}
"""


ROOT = "../../"  # 页面在 /guide/2027/ 下，回两级到站点根


def page(title, desc, keywords, h1, lead, body_html, jsonld, canonical, related_html):
    j = json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="keywords" content="{esc(keywords)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{canonical}">
<link rel="icon" href="{ROOT}oyster-logo.png">
<style>{CSS}</style>
<script type="application/ld+json">{j}</script>
</head>
<body>
<div class="wrap">
<a class="brand" href="{ROOT}"><img src="{ROOT}oyster-logo.png" alt="蚝历"><span class="name">蚝历</span></a>
<div class="crumb"><a href="{ROOT}">蚝历首页</a> › {esc(h1)}</div>
<h1>{esc(h1)}</h1>
<p class="lead">{esc(lead)}</p>
{body_html}
<div class="cta">
<a class="btn primary" href="{ROOT}ics/china.ics" download>📅 一键导入手机日历</a>
<a class="btn ghost" href="{ROOT}#app">下载蚝历 App（桌面小组件 · 全球节假日）</a>
</div>
<div class="panel">
<h2>相关内容</h2>
<div class="related">{related_html}</div>
</div>
<div class="foot">
数据仅供参考，最终以官方公告为准。蚝历整理 · 无广告、无账号、无统计。<br>
<a href="{ROOT}privacy.html">隐私政策</a> · <a href="{ROOT}">返回首页</a> · 京ICP备2026079812号
</div>
</div>
</body>
</html>
"""


def related_links(items):
    out = []
    for s, n in items:
        href = f"{s}.html" if s else ROOT
        out.append(f'<a href="{href}">{esc(n)}</a>')
    return "<br>".join(out)


# ---------- 中国节日页 ----------
CN_SLUG = {
    "元旦": "new-year", "春节": "spring-festival", "清明节": "qingming",
    "劳动节": "labor-day", "端午节": "dragon-boat", "中秋节": "mid-autumn",
    "国庆节": "national-day",
}
CN_NOUN = {
    "元旦": "元旦", "春节": "春节", "清明节": "清明节", "劳动节": "劳动节",
    "端午节": "端午节", "中秋节": "中秋节", "国庆节": "国庆节",
}


def cn_pages():
    r = json.load(open(BASE / "data" / "official-notice-report.json"))
    y = [x for x in r["years"] if x["year"] == YEAR][0]
    pages = []
    for s in y["sections"]:
        name = s["name"]
        slug = CN_SLUG.get(name)
        if not slug:
            continue
        off, work = s["off"], s.get("work", [])
        noun = CN_NOUN[name]
        title = f"{YEAR}年{noun}放假安排：{md(off[0])} 至 {md(off[-1])}，共 {len(off)} 天｜蚝历"
        desc = (f"{YEAR}年{noun}放假 {md(off[0])} 至 {md(off[-1])}，共 {len(off)} 天"
                + (f"；{('、'.join(md(w) for w in work))} 调休上班。" if work else "，无调休。")
                + " oyster111.top 提供放假安排、调休上班日与一键导入手机日历。")
        kws = f"{YEAR}年{noun}放假,{noun}放假安排,{YEAR}{noun},{noun}调休,{noun}放几天,放假安排,节假日日历"
        h1 = f"{YEAR}年{noun}放假安排"
        lead = (f"根据国务院办公厅《关于 {YEAR} 年部分节假日安排的通知》，"
                f"{YEAR} 年{noun}放假 {len(off)} 天。"
                + (f"其中 {('、'.join(md(w) for w in work))} 需调休上班。" if work else "本次假期无需调休。"))

        rows = "".join(
            f"<tr><td class='dt'>{md(d)}<span class='wd'> {weekday(d)}</span></td>"
            f"<td>{noun}假期<span class='tag off'>放假</span></td></tr>" for d in off)
        if work:
            rows += "".join(
                f"<tr><td class='dt'>{md(d)}<span class='wd'> {weekday(d)}</span></td>"
                f"<td>调休上班<span class='tag'>补班</span></td></tr>" for d in work)
        body = f"""<div class="panel">
<h2>{noun}放假与调休一览</h2>
<table><thead><tr><th>日期</th><th>安排</th></tr></thead><tbody>{rows}</tbody></table>
<p class="note">以上日期来自国务院办公厅节假日安排通知，蚝历已与中国政府网公布原文逐日核对。最终请以官方公告为准。</p>
</div>
<div class="panel">
<h2>怎么把 {noun} 放进手机日历</h2>
<p style="font-size:13.5px;color:#6e6e73">点上方「一键导入手机日历」可把 {YEAR} 年全部中国法定节假日（含调休上班日）一次导入系统日历，中国部分会生成独立日历节点，可单独配色、隐藏或删除，不与你自己的日程混排。想让明年自动更新，可在首页复制常青订阅地址。</p>
</div>"""

        jsonld = {
            "@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{
                "@type": "Question",
                "name": f"{YEAR}年{noun}放几天？",
                "acceptedAnswer": {"@type": "Answer", "text":
                    f"{YEAR}年{noun}放假 {len(off)} 天，从 {md(off[0])} 到 {md(off[-1])}。"
                    + (f"{('、'.join(md(w) for w in work))} 调休上班。" if work else "")},
            }],
        }
        rel = related_links([(f"{YEAR}/{k}", CN_NOUN[k2]) for k2, k in CN_SLUG.items() if k2 != name][:6]
                            + [("", "蚝历首页 · 全球节假日")])
        pages.append((f"{YEAR}/{slug}", page(title, desc, kws, h1, lead, body, jsonld,
                                             f"{SITE}/guide/{YEAR}/{slug}.html", rel)))
    return pages


# ---------- 国家页 ----------
# 只给"单一国家/地区"建页，跳过合集（合集内容重复、易被判桥页）
SKIP = {"east-asia", "southeast", "south-asia", "middle-east", "europe",
        "north-america", "south-america", "oceania", "africa", "religion", "world-events"}


def parse_ics(slug):
    p = BASE / "ics" / f"{slug}.ics"
    if not p.exists():
        return []
    raw = p.read_text(encoding="utf-8")
    # ICS 有折叠行（以空格续行），先还原
    raw = re.sub(r"\r?\n[ \t]", "", raw)
    out = []
    for block in raw.split("BEGIN:VEVENT")[1:]:
        m_d = re.search(r"DTSTART(?:;VALUE=DATE)?:(\d{8})", block)
        m_s = re.search(r"SUMMARY:(.+)", block)
        if not (m_d and m_s):
            continue
        ds = m_d.group(1)
        if not ds.startswith(str(YEAR)):
            continue
        d = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
        name = m_s.group(1).strip()
        name = re.sub(r"^[^·]+·\s*", "", name)  # 去掉 "德国 · " 前缀
        out.append((d, name))
    return sorted(set(out))


def country_pages():
    co = json.load(open(BASE / "data" / "countries.json"))
    items = []
    for g in co["groups"]:
        for it in g["items"]:
            if it["slug"] in SKIP:
                continue
            items.append(it)
    pages = []
    for it in items:
        slug, zh, note = it["slug"], it["zh"], it["note"]
        evs = parse_ics(slug)
        if not evs:
            continue
        d0, d1 = evs[0][0], evs[-1][0]
        title = f"{YEAR}年{zh}节假日一览：{len(evs)}个法定节日与纪念日｜蚝历"
        desc = (f"{YEAR} 年{zh}共有 {len(evs)} 个节假日与纪念日，含{note}。"
                f"查看完整日期表并一键导入手机日历， oyster111.top 蚝历整理。")
        kws = f"{YEAR}{zh}节假日,{zh}放假,{zh}公共假日,{zh} holidays {YEAR},{zh}节日,{note},世界节假日日历"
        h1 = f"{YEAR}年{zh}节假日"
        lead = f"蚝历收录 {YEAR} 年{zh}的 {len(evs)} 个节假日与纪念日（{note}），按日期排列如下，可一键导入手机日历。"

        rows = "".join(
            f"<tr><td class='dt'>{md(d)}<span class='wd'> {weekday(d)}</span></td>"
            f"<td>{esc(n)}</td></tr>" for d, n in evs)
        body = f"""<div class="panel">
<h2>{YEAR} 年{zh}节假日完整列表</h2>
<table><thead><tr><th>日期</th><th>节日 / 纪念日</th></tr></thead><tbody>{rows}</tbody></table>
<p class="note">{zh}节假日数据来自公开节假日库，蚝历按 {YEAR} 年整理，最终以当地官方公告为准。日期为当地全天事件。</p>
</div>
<div class="panel">
<h2>怎么把{zh}节假日放进手机日历</h2>
<p style="font-size:13.5px;color:#6e6e73">点上方「一键导入手机日历」可导入中国节假日；完整 60+ 国家与地区的节假日请在蚝历 App 或首页选择对应分区导入 / 订阅。订阅地址为常青地址，跨年自动更新，不用每年重新导入。</p>
</div>"""

        jsonld = {
            "@context": "https://schema.org", "@type": "ItemList",
            "name": h1, "numberOfItems": len(evs),
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": n, "datePublished": d}
                for i, (d, n) in enumerate(evs)
            ],
        }
        rel = related_links([(f"{YEAR}/{k}", CN_NOUN[k2]) for k2, k in CN_SLUG.items()][:4]
                            + [("", "蚝历首页 · 全球节假日")])
        pages.append((f"{YEAR}/{slug}", page(title, desc, kws, h1, lead, body, jsonld,
                                             f"{SITE}/guide/{YEAR}/{slug}.html", rel)))
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sitemap", action="store_true", help="生成 sitemap-guide.xml")
    args = ap.parse_args()

    if not OUT.exists():
        OUT.mkdir(exist_ok=True)
    if not (OUT / str(YEAR)).exists():
        (OUT / str(YEAR)).mkdir(exist_ok=True)
    pages = cn_pages() + country_pages()
    for rel, content in pages:
        (OUT / f"{rel}.html").write_text(content, encoding="utf-8")

    if args.sitemap:
        locs = "\n".join(
            f"  <url><loc>{SITE}/guide/{rel}.html</loc>"
            f"<changefreq>yearly</changefreq><priority>0.7</priority></url>"
            for rel, _ in pages)
        xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               f'{locs}\n</urlset>\n')
        (OUT / "sitemap-guide.xml").write_text(xml, encoding="utf-8")

    print(f"生成 {len(pages)} 个指南页 → {OUT}")
    print(f"  中国节日页: {len(cn_pages())}  国家页: {len(country_pages())}")


if __name__ == "__main__":
    main()
