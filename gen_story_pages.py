#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「蚝历故事」高质量文章页（真实策展数据 + 官方来源驱动）。

这是 SEO 内容的第二层：guide/ 页是「数据表格」，story/ 页是有叙述、有观点的文章，
承载蚝历的核心特色——党史/革命/体育提气时刻与传统文化这些有权威出处的内容，
以及法定假日、节气等日历该有的基础内容。

内容红线（务必遵守）：
  · 所有史实陈述只取自 curated.py 的 public 字段（已过 A 级来源闸门）与
    sources 标题本身承载的信息，绝不自行添加未经核实的细节。
  · 每条都列出真实官方来源链接，可点开核对。
  · 周年由 anchor 与当前年份计算，不写死。
  · 「为什么值得记住」写价值观层面的意义，不编造史实。

产出三类到 ../story-pages/：提气时刻（策展库全部）+ 传统节日 + 专题聚合。
每页自包含（内联 CSS）、独立 Article JSON-LD、canonical、内链。
"""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
SITE = "https://oyster111.top"
THIS_YEAR = 2027
OUT = BASE.parent / "story-pages"


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif;background:#fafafa;color:#1d1d1f;line-height:1.9;-webkit-font-smoothing:antialiased}
.wrap{max-width:680px;margin:0 auto;padding:0 20px 56px;background:#fff;box-shadow:0 0 40px rgba(0,0,0,.04);min-height:100vh}
a{color:#ff6b35;text-decoration:none}
.brand{display:flex;align-items:center;gap:9px;padding:20px 0 4px}
.brand img{width:34px;height:34px;border-radius:8px}
.brand .name{font-size:18px;font-weight:800}
.crumb{font-size:12px;color:#8e8e93;margin:12px 0 22px}
.crumb a{color:#8e8e93}
.kicker{display:inline-block;font-size:11px;font-weight:700;color:#ff6b35;background:#fff1eb;border-radius:6px;padding:3px 9px;margin-bottom:12px;letter-spacing:.04em}
h1{font-size:27px;font-weight:800;line-height:1.4;letter-spacing:-0.02em;margin-bottom:12px}
.meta{font-size:12px;color:#a0a0a8;margin-bottom:24px;padding-bottom:18px;border-bottom:1px solid #f0f0f5}
.lead{font-size:16px;color:#3a3a3c;line-height:1.85;margin-bottom:22px;font-weight:500}
h2{font-size:19px;font-weight:800;margin:30px 0 12px;line-height:1.5;display:flex;align-items:center;gap:8px}
h2::before{content:"";width:4px;height:17px;background:#ff6b35;border-radius:2px;flex:0 0 auto}
p{font-size:15px;color:#3a3a3c;margin-bottom:15px;line-height:1.95}
.voice{border-left:3px solid #ff6b35;padding-left:16px;color:#1d1d1f;font-size:15.5px;line-height:2}
.prod .voice{padding-left:0;border-left:0;color:#3a3a3c;font-size:14px}
.factbox{background:#fff8f4;border:1px solid #ffe3d5;border-radius:12px;padding:16px 18px;margin:18px 0}
.factbox .lab{font-size:11px;font-weight:700;color:#ff6b35;letter-spacing:.05em;margin-bottom:6px}
.factbox p{font-size:14.5px;color:#1d1d1f;margin:0;line-height:1.85}
.datecard{background:#f7f7f9;border-radius:12px;padding:14px 18px;margin:18px 0}
.datecard .lab{font-size:11px;font-weight:700;color:#ff6b35;letter-spacing:.05em;margin-bottom:8px}
.datecard table{border-collapse:collapse;width:100%}
.datecard th,.datecard td{font-size:13.5px;text-align:left;padding:5px 0;color:#3a3a3c;line-height:1.6}
.datecard th{width:118px;color:#8e8e93;font-weight:500}
.src{background:#f7f7f9;border-radius:12px;padding:14px 18px;margin:18px 0}
.src .lab{font-size:11px;font-weight:700;color:#8e8e93;letter-spacing:.05em;margin-bottom:8px}
.src ol{margin:0;padding-left:18px}
.src li{font-size:12.5px;color:#6e6e73;line-height:1.9;word-break:break-all}
.src a{color:#ff6b35}
.prod{background:linear-gradient(135deg,#fff6f1,#fff);border:1px solid #ffe3d5;border-radius:14px;padding:18px 20px;margin:24px 0}
.prod h3{font-size:14px;font-weight:800;color:#ff6b35;margin-bottom:10px}
.prod p{font-size:13.5px;margin-bottom:8px;line-height:1.85}
.prod .btn{display:inline-block;background:#ff6b35;color:#fff;font-size:13px;font-weight:700;padding:9px 18px;border-radius:9px;margin-top:8px}
.cta{display:flex;flex-direction:column;gap:10px;margin:26px 0}
.btn2{display:block;text-align:center;padding:13px;border-radius:11px;text-decoration:none;font-size:15px;font-weight:700}
.btn2.primary{background:#ff6b35;color:#fff}
.btn2.ghost{background:#fff;color:#1d1d1f;border:1px solid #eaeaef}
.related{border-top:1px solid #f0f0f5;margin-top:28px;padding-top:18px}
.related .lab{font-size:12px;font-weight:700;color:#8e8e93;margin-bottom:10px}
.related a{display:inline-block;font-size:13px;margin:0 10px 8px 0;color:#6e6e73}
.foot{border-top:1px solid #eaeaef;margin-top:30px;padding-top:16px;font-size:11px;color:#a0a0a8;line-height:1.8}
"""


def article_page(kicker, title, lead, sections_html, sources, jsonld_extra, canonical, related_html):
    src_html = ""
    if sources:
        lis = "".join(
            f'<li>{esc(t)} — <a href="{esc(u)}" target="_blank" rel="noopener noreferrer">原文</a></li>'
            for t, u, _ in sources)
        src_html = f'<div class="src"><div class="lab">资料来源（可点开核对）</div><ol>{lis}</ol></div>'
    j = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": title, "description": lead,
        "datePublished": "2026-11-18", "dateModified": "2026-11-18",
        "author": {"@type": "Organization", "name": "蚝历"},
        "publisher": {"@type": "Organization", "name": "蚝历",
                      "logo": {"@type": "ImageObject", "url": f"{SITE}/oyster-logo.png"}},
        "mainEntityOfPage": canonical,
    }
    j.update(jsonld_extra or {})
    jd = json.dumps(j, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}｜蚝历</title>
<meta name="description" content="{esc(lead)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(lead)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{SITE}/oyster-logo.png">
<link rel="icon" href="../oyster-logo.png">
<style>{CSS}</style>
<script type="application/ld+json">{jd}</script>
</head>
<body>
<div class="wrap">
<a class="brand" href="../"><img src="../oyster-logo.png" alt="蚝历"><span class="name">蚝历</span></a>
<div class="crumb"><a href="../">蚝历首页</a> › <a href="index.html">蚝历故事</a> › 正文</div>
<span class="kicker">{esc(kicker)}</span>
<h1>{esc(title)}</h1>
<div class="meta">蚝历编辑部 · 2026-11-18 · 数据以官方公告为准</div>
<p class="lead">{esc(lead)}</p>
{sections_html}
{src_html}
<div class="cta">
<a class="btn2 primary" href="../ics/china.ics" download>📅 把这些日子装进手机日历</a>
</div>
<div class="related">
<div class="lab">继续读</div>
{related_html}
<a href="index.html">← 返回蚝历故事目录</a>
</div>
<div class="foot">
本文史实依据上方所列权威来源整理，仅供个人了解与纪念参考；蚝历将该日子收录为日历条目，具体安排以官方发布为准。<br>
蚝历 · 每一天的好日子 · 京ICP备2026079812号 · <a href="../privacy.html">隐私政策</a>
</div>
</div>
</body>
</html>
"""


# ---------- 一、提气时刻（策展库） ----------
KIND_KICKER = {"milestone": "提气时刻", "person": "值得记住的人", "memorial": "铭记"}


def why_box(name, kind, anchor):
    """价值观层面的意义，不编造史实。全部用中文引号。"""
    if kind == "person":
        return (f"在蚝历看来，一个人的诞辰之所以值得写进日历，不是因为它是节气或调休日，"
                f"而是因为从 {anchor} 年往后的每一个年头，总有一些人愿意在这一天停下来想一想。"
                f"这些由党和国家以正式纪念活动固定下来的日子，本身就是一种态度："
                f"有些名字，值得被一代代人记得。日历的意义，从来不只是「哪天放假」。")
    if kind == "memorial":
        return (f"这一类日子，蚝历坚持把它放进日历，是为了让「铭记」有一个具体的落点——"
                f"不是停在抽象的口号里，而是出现在你某一天抬眼看日历的那一刻。"
                f"记住英烈，是每一个普通人都能做到的、最朴素也最有力量的事。")
    if any(k in name for k in ["奥运", "女排", "冠军", "夺冠", "首金"]):
        return (f"体育的高光之所以值得写进日历，是因为它记录的不只是一场比赛、一枚奖牌，"
                f"而是一个时代里「中国人也能做到」的集体记忆，是一代人共同的情绪坐标。"
                f"{name}就是这样一天——它提醒我们，有些胜利，值得被反复记起。")
    return (f"{name}出现在蚝历里，是因为它是那段历史里绕不开的坐标。"
            f"把这样的日子放回日历，让「铭记」不只在课本和纪念活动里，"
            f"也在日常的抬头之间。记住来路，才好理解今天从哪里来。")


def curated_pages():
    import curated
    import story_angles
    pages = []
    for e in curated.ENTRIES:
        name, kind, mmdd = e["name"], e["kind"], e["mmdd"]
        # 领导人物诞辰类不进故事页（敏感）：只保留史实里程碑与英烈纪念
        if kind == "person":
            continue
        anchor = e.get("anchor")
        fact = e["public"]
        sources = [(t, u, lv) for t, u, lv in e.get("sources", [])]
        kicker = KIND_KICKER.get(kind, "提气时刻")
        m, d = mmdd.split("-")
        title = f"{int(m)} 月 {int(d)} 日 · {name}：这一天为什么值得记住"
        lead = (f"{int(m)} 月 {int(d)} 日是{name}。蚝历把它与法定假日、传统节日并列收录，"
                f"写清出处与 {THIS_YEAR} 年的具体日期。")
        src_titles = "；".join(t for t, _, _ in sources[:2])
        voice = story_angles.CURATED.get(name)
        if not voice:
            continue  # 没有独写角度的条目不发，宁缺毋滥
        sec = [
            '<h2>这一天，发生了什么</h2>'
            f'<div class="factbox"><div class="lab">官方史实</div><p>{esc(fact)}</p></div>'
            + date_card_html(mmdd, anchor)
            + (f'<p>这一天的记载，可以在下列权威来源中核对：{esc(src_titles)}。</p>' if sources else ''),
            '<h2>这一天为什么在蚝历里</h2>'
            f'<p class="voice">{esc(voice)}</p>',
            neighbor_html(mmdd),
        ]
        pages.append((f"{mmdd}-{slug_of(name)}", kicker, title, lead, "\n".join(sec), sources, {"about": fact}))
    return pages


def slug_of(name):
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", name)
    return s[:12] or "story"


def dated_index():
    """全部固定公历日期的条目：(日期, 名称, 文章文件名前缀)。"""
    import curated
    import discovered_days
    rows = [(e["mmdd"], e["name"], "") for e in curated.ENTRIES if e["kind"] != "person"]
    rows += [(e["mmdd"], e["name"], "") for e in NATIONAL_DAYS]
    rows += [(e["mmdd"], e["name"], "disc-") for e in discovered_days.DISCOVERED]
    return sorted(set(rows))


def date_card_html(mmdd, anchor):
    """每篇独有的年份信息：星期与年内序位是搜索引擎答不了的长尾信息。"""
    m, d = (int(x) for x in mmdd.split("-"))
    dt = date(THIS_YEAR, m, d)
    rows = [
        ("公历日期", f"{THIS_YEAR} 年 {m} 月 {d} 日"),
        ("这一天是", "星期" + "一二三四五六日"[dt.weekday()]),
        ("一年中的第几天", f"第 {dt.timetuple().tm_yday} 天"),
    ]
    if anchor:
        rows.append(("起点年份", f"{anchor} 年 · 至 {THIS_YEAR} 年 {THIS_YEAR - anchor} 周年"))
    trs = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows)
    return (f'<div class="datecard"><div class="lab">{THIS_YEAR} 年这一天</div>'
            f"<table>{trs}</table></div>")


def neighbor_html(mmdd):
    """前后日期的真实内链，每篇都不同，让爬虫在文章间自然流转。"""
    rows = dated_index()
    keys = [r[0] for r in rows]
    if mmdd not in keys or len(rows) < 3:
        return ""
    i = keys.index(mmdd)
    prev_row = rows[i - 1] if i > 0 else rows[-1]
    next_row = rows[i + 1] if i < len(rows) - 1 else rows[0]

    def link(row):
        day, name, prefix = row
        mm, dd = (int(x) for x in day.split("-"))
        return f'<a href="{prefix}{day}-{slug_of(name)}.html">{esc(name)}（{mm} 月 {dd} 日）</a>'

    return ("<h2>日历上的前后日子</h2>"
            "<p>在蚝历的中国日历里，这一天前后还写着这些日子——每一条都有出处，点开就能看。</p>"
            f"<p>前一条：{link(prev_row)}<br>后一条：{link(next_row)}</p>")


# ---------- 一·补 国家级法定纪念日（有 A 级来源，事实取自决定/新华社原文） ----------
# 内容红线：fact 只写官方来源明确表述；sources 为真实可点开的权威链接；anchor 为决定/事件年份。
NATIONAL_DAYS = [
    {
        "name": "中国人民抗日战争胜利纪念日", "mmdd": "09-03", "anchor": 2014, "kicker": "铭记",
        "fact": "2014 年 2 月 27 日，十二届全国人大常委会第七次会议以立法形式决定将 9 月 3 日确定为中国"
                "人民抗日战争胜利纪念日，每年 9 月 3 日国家举行纪念活动。决定指出，中国人民抗日战争是近代以来"
                "中国反抗外敌入侵第一次取得完全胜利的民族解放战争。",
        "why": "以国家立法形式固定下来的纪念日，分量不同于一般的民间纪念。它提醒我们：胜利不是理所当然的，"
               "是从苦难与抗争里一步步走出来的。把这一天放进日历，是让「铭记」有一个具体的落点——"
               "不是抽象的口号，而是每年这一天，你都能在日历上看见它。",
        "sources": [
            ("中国人大网·关于确定中国人民抗日战争胜利纪念日的决定（2014）",
             "http://www.npc.gov.cn/zgrdw/npc/xinwen/lfgz/lfdt/2014-02/28/content_1832448.htm", "A"),
            ("人民网·史料图说：抗战胜利纪念日为什么选择 9 月 3 日",
             "https://politics.people.com.cn/n/2015/0902/c1001-27541970.html", "A"),
        ],
    },
    {
        "name": "南京大屠杀死难者国家公祭日", "mmdd": "12-13", "anchor": 2014, "kicker": "铭记",
        "fact": "2014 年 2 月 27 日，十二届全国人大常委会第七次会议决定将 12 月 13 日设立为南京大屠杀死难者"
                "国家公祭日，每年 12 月 13 日国家举行公祭活动。决定指出，1937 年 12 月 13 日侵华日军在南京"
                "开始长达四十多天的大屠杀，三十多万同胞惨遭杀戮。",
        "why": "国家公祭日以最庄重的方式告诉后人：苦难不能被遗忘，同胞不能被轻忽。日历上的这一格，"
               "不是为了让日子变得沉重，而是为了在下一次抬头时，仍能记起和平有多珍贵。"
               "铭记不是为了延续仇恨，而是为了让历史不再重演。",
        "sources": [
            ("中国人大网·关于设立南京大屠杀死难者国家公祭日的决定（2014）",
             "http://www.npc.gov.cn/zgrdw/npc/xinwen/lfgz/lfdt/2014-02/28/content_1832448.htm", "A"),
            ("中国共产党新闻网·9 月 3 日为抗战胜利纪念日、12 月 13 日为国家公祭日",
             "https://cpc.people.com.cn/BIG5/n/2014/0228/c87228-24487471.html", "A"),
        ],
    },
    {
        "name": "烈士纪念日", "mmdd": "09-30", "anchor": 2014, "kicker": "铭记",
        "fact": "2014 年 8 月 31 日，十二届全国人大常委会第十次会议通过决定，将 9 月 30 日设立为烈士纪念日，"
                "每年 9 月 30 日国家举行纪念烈士活动。决定指出，近代以来无数英雄为争取民族独立和人民自由幸福"
                "献出了生命，烈士的功勋彪炳史册，烈士的精神永垂不朽。",
        "why": "把 9 月 30 日——国庆前一天——设为烈士纪念日，寓意很郑重：国庆勿忘祭先烈。"
               "在举国同庆的前一天，先停下来纪念那些没能看到今天的人。这是一种朴素而有力的提醒："
               "眼前的安稳，是有人用生命换来的。",
        "sources": [
            ("中国人大网·关于设立烈士纪念日的决定（2014）",
             "http://www.npc.gov.cn/c2/c12435/c12489/201905/t20190521_219266.html", "A"),
            ("人民网·全国人大常委会关于设立烈士纪念日的决定",
             "https://politics.people.com.cn/BIG5/n/2014/0831/c70731-25574249.html", "A"),
        ],
    },
    {
        "name": "七七事变纪念日", "mmdd": "07-07", "anchor": 1937, "kicker": "铭记",
        "fact": "1937 年 7 月 7 日，日军诡称一名士兵失踪，悍然向卢沟桥和宛平城发起进攻，制造了震惊中外的"
                "卢沟桥事变（七七事变），日本全面侵华战争爆发。中国共产党当天发出通电："
                "「全中国的同胞们！平津危急！华北危急！中华民族危急！只有全民族实行抗战，才是我们的出路！」",
        "why": "这一天打响了全民族抗战的第一枪。纪念七七，是纪念一个民族在危亡时刻的觉醒与团结——"
               "从那一刻起，大江南北、长城内外，中华儿女共赴国难。把这一天放进日历，"
               "是让那份「亡国灭种之际挺身而出」的勇气，始终有迹可循。",
        "sources": [
            ("新华网·87 年前的今天，我们永不忘记！",
             "https://www.xinhuanet.com/politics/20240707/5d6d72364b674159be8252dde573f16d/c.html", "A"),
            ("中国共产党新闻网·铭记历史缅怀先烈珍视和平警示未来",
             "https://cpc.people.com.cn/n/2014/0708/c87228-25250342.html", "A"),
        ],
    },
    {
        "name": "九一八事变纪念日", "mmdd": "09-18", "anchor": 1931, "kicker": "铭记",
        "fact": "1931 年 9 月 18 日夜，日军自爆南满铁路柳条湖段，反诬中国军队所为，随即炮轰沈阳北大营、"
                "攻占沈阳城，九一八事变爆发，中华民族艰苦卓绝的 14 年抗日战争从此开始。事变第二天，"
                "《中共满洲省委为日本帝国主义武装占领满洲宣言》贴在沈阳大街小巷，号召人民奋起抗战。",
        "why": "每年 9 月 18 日，沈阳全城都会响起防空警报——这是历史的回声，是一个民族对苦难的正视。"
               "所谓「警钟长鸣」，不是停留在那一天，而是把「落后就要挨打、自强才能自立」的道理，"
               "一年一次地提醒到自己。日历上的这个日子，就是那声每年都会响起的警钟。",
        "sources": [
            ("新华网·勿忘九一八！",
             "https://xinhuanet.com/politics/20260918/b8feefb4f2f04ebea3d8ed8177ff5320/c.html", "A"),
            ("新华网·新华时评：历史的回声 永远的铭记",
             "https://www.news.cn/2023-09/18/c_1129868568.htm", "A"),
        ],
    },
    {
        "name": "一二·九运动纪念日", "mmdd": "12-09", "anchor": 1935, "kicker": "铭记",
        "fact": "1935 年 12 月 9 日，北平学生举行声势浩大的抗日游行，高喊「停止内战，一致抗日」"
                "「武装保卫华北」，由此开始的一二·九运动迅速波及全国。据新华社记载，这标志着中国人民"
                "抗日救亡运动新高潮的到来，推动了全民抗战的发动。",
        "why": "一二·九是青年学生用脚步和呐喊推动历史的一天。在国家危亡面前，最先站出来的往往是最年轻的人。"
               "把这一天写进日历，是记住：一股年轻的力量，可以成为时代转向的先声。"
               "这份「天下兴亡、匹夫有责」的担当，值得每一代人重新认识。",
        "sources": [
            ("新华网·百个瞬间说百年：1936「停止内战，一致抗日」",
             "https://www.xinhuanet.com/politics/2021-04/13/c_1211107824.htm", "A"),
            ("新华网·1931—1937 年局部抗战启示录",
             "http://news.xinhuanet.com/politics/2015-08/10/c_1116197323_3.htm", "A"),
        ],
    },
    {
        "name": "西安事变纪念日", "mmdd": "12-12", "anchor": 1936, "kicker": "铭记",
        "fact": "1936 年 12 月 12 日，张学良、杨虎城在西安发动兵谏，扣留蒋介石，通电全国提出停止内战、"
                "一致抗日等主张，这就是震惊中外的西安事变。事变发生后，中共中央以中华民族团结抗日的大局为重，"
                "确定了和平解决的方针；西安事变的和平解决成为时局转换的枢纽，对促成抗日民族统一战线的建立"
                "起到重要作用。",
        "why": "这一天之所以值得记住，是因为在民族危亡的关口，大局被放在了恩怨之上。"
               "西安事变的和平解决，让十年内战局面基本结束、国内和平初步实现，为全民族抗战创造了前提。"
               "它提醒我们：在更大的共同目标面前，团结与担当，往往比对抗更需要勇气。",
        "sources": [
            ("新华网·百个瞬间说百年：1936「停止内战，一致抗日」",
             "https://www.xinhuanet.com/politics/2021-04/13/c_1211107824.htm", "A"),
            ("中国共产党新闻网·西安事变，时局转换的枢纽（人民日报）",
             "https://cpc.people.com.cn/n1/2021/0202/c435238-32019585.html", "A"),
        ],
    },
    {
        "name": "抗美援朝纪念日", "mmdd": "10-25", "anchor": 1950, "kicker": "提气时刻",
        "fact": "1950 年 10 月 25 日，中国人民志愿军在朝鲜温井西北两水洞地区首战告捷，"
                "揭开了抗美援朝战争的序幕，这一天后来被确定为中国人民志愿军抗美援朝出国作战纪念日。"
                "据新华社记载，在两年零九个月的战斗中，志愿军将士被誉为「最可爱的人」，"
                "1953 年 7 月 27 日《朝鲜停战协定》在板门店签订。",
        "why": "这是一个让中国人挺直腰杆的日子。在新中国成立不久、百废待兴的时候，"
               "志愿军将士跨过鸭绿江，用一场艰苦卓绝的胜利向世界表明：保卫和平、捍卫家园的决心，"
               "从来不取决于装备的优劣。把这一天写进日历，是记住那句掷地有声的话——"
               "「最可爱的人」，值得被一代代记起。",
        "sources": [
            ("新华网·75 年了，我们永远不会忘记！",
             "https://www.xinhuanet.com/20251025/babe02c33a5b44978a363ce7194ecc06/c.html", "A"),
            ("中国政府网·中朝双方共同纪念抗美援朝出国作战 72 周年",
             "https://www.gov.cn/xinwen/2022-10/27/content_5721835.htm", "A"),
        ],
    },
]


def national_pages():
    """国家级法定/历史纪念日文章，史实只取自 A 级来源原文。"""
    import story_angles
    pages = []
    for e in NATIONAL_DAYS:
        name, mmdd, anchor = e["name"], e["mmdd"], e["anchor"]
        fact = e["fact"]
        sources = [(t, u, lv) for t, u, lv in e["sources"]]
        m, d = mmdd.split("-")
        title = f"{int(m)} 月 {int(d)} 日 · {name}：这一天为什么值得记住"
        lead = (f"{int(m)} 月 {int(d)} 日是{name}。蚝历把它与法定假日、传统节日并列收录，"
                f"写清出处与 {THIS_YEAR} 年的具体日期。")
        src_titles = "；".join(t for t, _, _ in sources[:2])
        voice = story_angles.NATIONAL.get(name)
        if not voice:
            continue
        sec = [
            '<h2>这一天，发生了什么</h2>'
            f'<div class="factbox"><div class="lab">官方史实</div><p>{esc(fact)}</p></div>'
            + date_card_html(mmdd, anchor)
            + f'<p>这一天的记载，可以在下列权威来源中核对：{esc(src_titles)}。</p>',
            '<h2>这一天为什么在蚝历里</h2>'
            f'<p class="voice">{esc(voice)}</p>',
            neighbor_html(mmdd),
        ]
        pages.append((f"{mmdd}-{slug_of(name)}", e["kicker"], title, lead, "\n".join(sec),
                      sources, {"about": fact}))
    return pages


# ---------- 二、传统节日（农历文化） ----------
TRADITION = [
    ("春节", "农历正月初一", "岁首，中国人最重要的传统节日。辞旧迎新、阖家团圆，是一年里最有仪式感的一天。"),
    ("除夕", "农历腊月最后一天", "岁末之夜。守岁、年夜饭、辞旧迎新，是中国人情感浓度最高的一夜。"),
    ("元宵节", "农历正月十五", "上元佳节。赏灯、猜灯谜、吃元宵，是春节年俗的压轴。"),
    ("清明节", "公历 4 月 5 日前后", "既是节气也是节日。扫墓祭祖、踏青郊游，慎终追远与迎接春天并行。"),
    ("端午节", "农历五月初五", "纪念屈原、赛龙舟、吃粽子。2009 年入选联合国教科文组织人类非物质文化遗产名录。"),
    ("中秋节", "农历八月十五", "团圆节。赏月、吃月饼，寄托着中国人对团圆的重视。"),
    ("重阳节", "农历九月初九", "敬老登高、赏菊思亲，也是今天的老年节。"),
    ("七夕节", "农历七月初七", "乞巧节，牛郎织女的传说让它成为中国的情人节。"),
    ("腊八节", "农历腊月初八", "腊八粥的节日，过了腊八就是年。"),
    ("小年", "农历腊月廿三或廿四", "祭灶、扫尘，正式拉开春节的序幕。"),
    ("龙抬头", "农历二月初二", "春回大地、万物复苏，民间有理发祈福的习俗。"),
    ("中元节", "农历七月十五", "追思先人的日子，民间有放河灯等习俗。"),
    ("上巳节", "农历三月初三", "古老的春游节日，曲水流觞、踏青祓禊。"),
    ("寒衣节", "农历十月初一", "为先人送去寒衣、慎终追远的日子，民间有焚送寒衣的习俗。"),
    ("下元节", "农历十月十五", "水官解厄之日，民间有祈福消灾、祭祀祖先的传统。"),
]


def discovered_pages():
    """从数据源主动挖掘的纪念日（非用户点名），与国家级同规格渲染。"""
    import discovered_days
    pages = []
    for e in discovered_days.DISCOVERED:
        name, mmdd, anchor = e["name"], e["mmdd"], e["anchor"]
        fact = e["fact"]
        sources = [(t, u, lv) for t, u, lv in e["sources"]]
        voice = discovered_days.VOICES.get(name)
        if not voice:
            continue
        m, d = mmdd.split("-")
        title = f"{int(m)} 月 {int(d)} 日 · {name}：这一天为什么值得记住"
        lead = (f"{int(m)} 月 {int(d)} 日是{name}。蚝历把它与法定假日、传统节日并列收录，"
                f"写清出处与 {THIS_YEAR} 年的具体日期。")
        src_titles = "；".join(t for t, _, _ in sources[:2])
        sec = [
            '<h2>这一天，发生了什么</h2>'
            f'<div class="factbox"><div class="lab">官方史实</div><p>{esc(fact)}</p></div>'
            + date_card_html(mmdd, anchor)
            + f'<p>这一天的记载，可以在下列权威来源中核对：{esc(src_titles)}。</p>',
            '<h2>这一天为什么在蚝历里</h2>'
            f'<p class="voice">{esc(voice)}</p>',
            neighbor_html(mmdd),
        ]
        pages.append((f"disc-{mmdd}-{slug_of(name)}", e["kicker"], title, lead, "\n".join(sec),
                      sources, {"about": fact}))
    return pages


def tradition_pages():
    import story_angles
    result = []
    for name, lunar, desc in TRADITION:
        voice = story_angles.TRADITION.get(name)
        if not voice:
            continue
        title = f"{name}：{lunar}背后的中国传统，蚝历帮你记在日历里"
        lead = f"{name}在{lunar}。蚝历按农历规则逐年换算，把 {len(TRADITION)} 个传统节日直接放进你的日历。"
        sec = [
            '<h2>这是一个什么样的日子</h2>'
            f'<p class="voice">{esc(voice)}</p>'
            f'<p>{esc(name)}按<strong>{esc(lunar)}</strong>确定日期，跟着农历走，'
            '每年的公历日期都不一样。蚝历按农历规则逐年换算，订阅地址不带年份，'
            '跨年自动滚动，不用每年自己重新查。</p>',
        ]
        result.append((f"trad-{slug_of(name)}", "传统节日", title, lead, "\n".join(sec), [], {"about": desc}))
    return result


# ---------- 三、专题聚合 ----------
FEATURES = [
    ("why-haoli", "产品视角", "一本有来处的日历：蚝历为什么要记录这些值得记住的日子",
     "一本日历可以只告诉你今天周几、放不放假。蚝历想多做一点：把那些有权威出处、值得被记住的日子，也放进你的日历，让每一天都有来处。",
     [
         ("<h2>大多数日历，只有三种日子</h2><p>打开任意一款日历 App，你能看到的通常是三类：法定放假与调休、农历和节气，以及部分国际日。它们当然有用，但中国人对日历的期待，其实不止于此。翻开日历，很多人希望看到的不仅是今天周几，还有今天是个什么日子。</p>",),
         ("<h2>蚝历多出来的那一层</h2><p>在这一层之上，蚝历有自己的侧重：额外收录了三类内容——党史与革命历程中具有明确史实出处的重大时刻；中国体育走向世界的高光节点；中华民族代代相传的传统文化节日。每一条都经过权威来源核对，写得清出处、日期与意义，点开当天就能读到。</p>",),
         ("<h2>基础内容也没落下</h2><p>特色之外，基础功能一点没少：中国法定假日与调休按国务院公告逐年更新，24 节气用天文算法计算，农历传统节日按历法换算，全球 62 个国家和地区的节假日一并覆盖。你不用为了看传统节日再装一个 App，也不用为了查外国假期再翻一个网站。</p>",),
         ("<h2>这些日子怎么进日历的</h2><p>它们不是随手加的。蚝历为每一条建立了准入标准：要有 A 级来源、要能年度复现、名称照录官方表述不自造。查不到出处的，宁可不收。这样你看到的每一个特别的日子，都点得开来源、经得起核对。</p>",),
         ("<h2>技术上也没妥协</h2><p>1.3 MB 的安装包，无广告、无账号、无统计，权限只有网络和日历。导入后生成独立日历节点，可单独配色、隐藏、删除——v1.69 还加了一键清除，避免导入容易删不掉。它想做的，是一本干净、有内容、又不会给你添麻烦的日历。</p>",),
     ]),
    ("sports-glory", "体育精神", "从女排首冠到奥运首金：蚝历里的中国体育高光时刻",
     "1981 年女排首冠、1984 年奥运首金、2008 年北京奥运……这些让中国人提气的日子，蚝历把它们一条条收进了日历。",
     [
         ("<h2>为什么把体育时刻写进日历</h2><p>体育的高光，记录的往往不只是一场比赛。它是一个时代里我们能做到的集体记忆，也是一代人共同的情绪坐标。把这些日子放进日历，是让这种记忆有了一个具体的落点——不是尘封在新闻里，而是每年都在你眼前出现一次。</p>",),
         ("<h2>蚝历收录了哪些</h2><p>从新中国第一个世界冠军容国团，到中国女排首次夺冠、五连冠，再到许海峰实现奥运金牌零的突破、北京申奥成功与奥运开幕——每一条都有明确的日期和权威来源，点开当天就能看到。它们串起来，是一部浓缩的中国体育走向世界的简史。</p>",),
         ("<h2>女排精神，值得每年记一次</h2><p>1981 年 11 月 16 日，中国女排首次夺得世界冠军，次日《人民日报》头版刊发《学习女排，振兴中华》。这个日子在蚝历里被完整保留，连同它的来历一起。四十多年过去，这种精神仍值得被记起。</p>",),
         ("<h2>怎么把这些日子装进手机</h2><p>在蚝历里，这些体育高光和中国法定假日、传统节日并排列出。打开 App 或官网点开对应日期就能看到详情，也可以一键把整个中国日历导入手机系统日历，独立节点、不与私人日程混排，跨年自动更新。</p>",),
     ]),
    ("party-history", "历史脉络", "从遵义会议到长征胜利：蚝历里的一条党史时间线",
     "遵义会议、中共一大、秋收起义、平型关大捷、长征胜利、十一届三中全会……蚝历把这些重大节点按日期串成了一条可以翻看的时间线。",
     [
         ("<h2>把历史放回日历里</h2><p>历史课本上的日期是抽象的，但当它出现在你某一天抬眼看的日历上，感觉会不一样。蚝历把这些重大历史节点按各自的公历日期收录，让铭记有一个日常的落点。你不必特意去查，它们自己会走到你眼前。</p>",),
         ("<h2>时间线上的关键节点</h2><p>从 1921 年中共一大开幕、1935 年遵义会议、1937 年平型关大捷，到 1936 年长征胜利、1978 年十一届三中全会——这些日子在蚝历里按日期排列，点开就能看到官方史实与出处。它们串成了一条清晰的时间线。</p>",),
         ("<h2>每一条都有出处</h2><p>蚝历对这类内容的态度很克制：只收有权威来源、能年度复现、名称照录官方表述的日子。来源来自人民日报、新华社、中国共产党新闻网等，文章里都列出可点开的原文。没有出处的，一条都不收。</p>",),
         ("<h2>纪念，是为了理解今天</h2><p>记住来路，才好理解今天从哪里来。这不是口号，而是把这些日子放进日历的意义——在忙碌的日常里，和历史打一个不经意的照面。蚝历做的，就是把这种照面变得自然、安静、不打扰。</p>",),
     ]),
    ("solar-terms", "传统文化", "24 节气放进日历：蚝历如何让古老的时间智慧重新可见",
     "立春、惊蛰、清明、谷雨……24 节气是中国人观察自然、安排农事的古老智慧。蚝历用天文算法逐年计算，让它们准确出现在你的日历里。",
     [
         ("<h2>节气是中国人的时间观</h2><p>24 节气把一年切成 24 段，每一段对应着气候、物候和农事的变化。它是古人仰望天空、俯察大地总结出的时间智慧，2016 年被列入联合国教科文组织人类非物质文化遗产名录。直到今天，很多人仍按节气安排吃穿与养生。</p>",),
         ("<h2>为什么需要精确计算</h2><p>节气是按太阳黄经位置确定的，每一年的公历日期并不固定，前后会有一天左右浮动。蚝历用天文算法逐年计算，订阅后跨年自动更新，不用自己查表，也不会出现去年记的日期今年错了的尴尬。</p>",),
         ("<h2>节气与节日，一起看</h2><p>在蚝历里，节气和农历节日、法定假日放在同一张日历上。比如清明既是节气也是节日，你能在同一天看到它的双重身份——这正是中国传统时间观的体现：自然节律与人文情感，本来就是一件事。</p>",),
         ("<h2>订阅一次，年年都在</h2><p>蚝历的节气订阅地址不带年份，跨年自动滚动。你不需要每年重新导入，也不用到处找今年的节气表。把日历打开，24 节气就安安静静地待在它该在的那一天。</p>",),
     ]),
    ("clear-imported", "使用指南", "导入日历删不掉？蚝历 1.69 的一键清除怎么解决这个痛点",
     "很多日历 App 导进去容易、删起来难。蚝历 1.69 新增「一键清除已导入的日历」，带确认弹窗，只删自己的节点，绝不碰私人日程。",
     [
         ("<h2>这是一个真实的高频痛点</h2><p>把节假日导进系统日历后，很多人发现：想删的时候删不干净，或者一删就把自己的日程也弄乱了。根源在于日历节点的归属没有分开——别人的日程和导入的节日混在一起，自然无从下手。</p>",),
         ("<h2>蚝历的做法：独立节点</h2><p>蚝历导入时在日历里生成独立的节点，和你的私人日程完全分开。你可以单独配色、单独隐藏，不想要了整节点删除，自己的安排一点不受影响。这也是它从一开始就坚持的设计。</p>",),
         ("<h2>1.69 新增加一键清除</h2><p>新增的一键清除会精确匹配蚝历导入的本地节点，带确认弹窗，一次性删干净，绝不误删私人日历或订阅。这是对用户真实反馈的直接回应——导入要简单，删除更要干净。</p>",),
         ("<h2>还有这些细节</h2><p>订阅地址是常青的，跨年自动更新；App 只有 1.3 MB，无广告、无账号；除了中国节假日，还能导入全球 62 国的假期。一本好日历，应该让你用得省心，也走得干净。</p>",),
     ]),
    ("global-holidays", "全球视野", "做外贸、常出差的人，怎么把 62 国节假日装进手机日历",
     "德国圣诞、日本黄金周、中东斋月、印度排灯节……客户说放假不用再翻网页。蚝历把 62 个国家和地区的节假日做成可订阅的日历。",
     [
         ("<h2>跨时区打交道的痛点</h2><p>做外贸或经常出差，最尴尬的不是谈不拢价格，而是对方突然说下周我们放假。每个市场的放假逻辑都不同，逐个搜索、维护一张 Excel，年年都要重来。更麻烦的是一些宗教节日每年日期都在变，静态表一到次年就作废。</p>",),
         ("<h2>把查变成看得见</h2><p>蚝历把 62 个国家和地区的节假日按分区整理，支持一键导入或订阅到系统日历。客户说放假，下拉日历就能看到放到哪天，明年自动更新，不用每年重新弄。从查表变成看见，这是效率上的本质变化。</p>",),
         ("<h2>订阅地址是常青的</h2><p>蚝历的 ICS 订阅地址不带年份，跨年自动滚动更新，订阅一次即可。这也是它和普通下载一份 ICS 文件最大的区别——后者到年底就断了，前者会一直跟着你走。</p>",),
         ("<h2>中国部分也没落下</h2><p>除了全球假期，蚝历的中国部分按国务院公告写明放假与调休，哪天补班都标清楚；传统文化节日、24 节气和历史高光时刻也一应俱全。一个 App，把国内国外的时间都装进去。</p>",),
     ]),
]


def feature_pages():
    import story_angles
    result = []
    for slug, kicker, title, lead, blocks in FEATURES:
        body = "\n".join(b[0] for b in blocks)
        closing = story_angles.FEATURE_CLOSINGS.get(slug)
        if closing:
            body += f'<div class="prod"><p class="voice">{esc(closing)}</p></div>'
        result.append((slug, kicker, title, lead, body, [], {"about": lead}))
    return result


def index_page(all_pages):
    from collections import defaultdict
    groups = defaultdict(list)
    for key, kicker, title, *_ in all_pages:
        groups[kicker].append((key, title))
    blocks = []
    for kicker, items in groups.items():
        links = "".join(f'<li><a href="{k}.html">{esc(t)}</a></li>' for k, t in items)
        blocks.append(f'<h2>{esc(kicker)}</h2><ul>{links}</ul>')
    body = ("<h1>蚝历故事</h1>"
            '<p class="lead">这里收录的文章，讲的都是蚝历为什么要把某些日子放进日历——'
            '有党史与革命的重大时刻、中国体育的高光、民族的传统文化，也有把 62 国节假日装进手机的方法。</p>'
            + "\n".join(blocks))
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>蚝历故事 · 有来处的日历</title>
<meta name="description" content="蚝历故事：党史、体育、传统文化与全球节假日的日历文章。">
<link rel="canonical" href="{SITE}/story/"><link rel="icon" href="../oyster-logo.png"><style>{CSS}
ul{{list-style:none;padding:0}}li{{font-size:14.5px;padding:9px 0;border-bottom:1px solid #f5f5f7}}
</style></head><body><div class="wrap">
<a class="brand" href="../"><img src="../oyster-logo.png" alt="蚝历"><span class="name">蚝历</span></a>
{body}
<div class="foot">蚝历 · 每一天的好日子 · 京ICP备2026079812号</div>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sitemap", action="store_true")
    args = ap.parse_args()

    if not OUT.exists():
        OUT.mkdir()
    all_pages = (curated_pages() + national_pages() + discovered_pages()
                 + tradition_pages() + feature_pages())

    from collections import defaultdict
    by_kicker = defaultdict(list)
    for key, kicker, title, *_ in all_pages:
        by_kicker[kicker].append((key, title))

    for key, kicker, title, lead, body, sources, jx in all_pages:
        peers = [p for p in by_kicker[kicker] if p[0] != key][:8]
        if len(peers) < 4:  # 专题类每类仅 1 篇，跨类补齐内链，避免「继续读」空白
            extras = [(p[0], p[2]) for p in all_pages
                      if p[0] != key and p[0] not in {x[0] for x in peers}
                      and p[1] in ("产品视角", "体育精神", "历史脉络", "传统文化", "使用指南", "全球视野")]
            peers += extras[:6]
        rel = "".join(f'<a href="{pk}.html">{esc(pt.split("：")[0])}</a>' for pk, pt in peers)
        (OUT / f"{key}.html").write_text(
            article_page(kicker, title, lead, body, sources, jx,
                         f"{SITE}/story/{key}.html", rel), encoding="utf-8")
    (OUT / "index.html").write_text(index_page(all_pages), encoding="utf-8")

    if args.sitemap:
        keys = [p[0] for p in all_pages] + ["index"]
        locs = "\n".join(
            f"  <url><loc>{SITE}/story/{k}.html</loc>"
            f"<changefreq>monthly</changefreq><priority>0.6</priority></url>" for k in keys)
        (OUT / "sitemap-story.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f'{locs}\n</urlset>\n', encoding="utf-8")

    print(f"生成 {len(all_pages)} 篇文章 + 1 目录页 → {OUT}")
    from collections import Counter
    print("分类:", dict(Counter(p[1] for p in all_pages)))


if __name__ == "__main__":
    main()
