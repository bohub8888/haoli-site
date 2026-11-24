#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据治理总表：固定来源渠道 + 正交分类 + 安全红线 + 生成期校验。

三件以前靠「中文名反推」或「散落在代码各处的 if」做的事，全部收口到这里：
  1. 来源渠道 CHANNELS —— 只有 4 类，新增条目必须挂到某一类，不许「东一个西一个」；
  2. 正交分类 KINDS / SCOPES —— kind / scope / source / level / verified 写进数据；
  3. 安全红线 REDLINES —— 按 scope 隔离，中国池整层豁免，绝不再用宽泛关键词误伤。

分层（v18：用户确认「方案一 = 小组件放全球」，撤销 v1.45 的「以中国为主」分层）：
  all-YYYY.json     网站月视图 / 全球合集订阅 = 全球池。
  widget-YYYY.json 小组件 + App 首页 = 同一个全球池，只是不收 adjustment
                    （调休补假属于日历、不属于节日，不进「今天有 N 个」）。
  两者条目名称都用原始「地区 · 名称」形式，App 按「·」拆成「名称 | 国家/地区」两列。
  *-YYYY.ics         分国家订阅 = 各国原始条目（含调休补假）。

安全红线（v18 修订）：从「按国别 / 按类别整组排除」改成「按内容点名」。
  只剔战犯与侵略战争、主权表述错误、以及 3 条战前体制关联日；
  中性民俗、节气、外国正面人物、别国内政纪念日一律保留，不再连坐。
  规则对所有端统一生效，不再有 STRICT / HARD 两套口径打架。
"""

from __future__ import annotations

import datetime as dt
import re

VERIFIED = "2026-11-12"

# ---------------------------------------------------------------- 1. 固定渠道

CHANNELS: list[dict] = [
    {
        "id": "C1",
        "name": "程序化基础库",
        "level": "B",
        "entries": ["holidays==0.108（60+ 国法定假日，版本锁在 requirements.txt）",
                    "cnlunar==0.2.5（农历、24 节气算法）"],
        "rhythm": "年度评估升级；升级前跑 check_key_dates.py 关键日期断言",
        "rule": "只取结构化字段，不人工改名；库升级即全量重算",
    },
    {
        "id": "C2",
        "name": "中国官方发文",
        "level": "A",
        "entries": ["国务院办公厅节假日安排通知（CN_SOURCE / CN_OFFICIAL / CN_WORKDAYS）",
                    "全国人大常委会决定、国务院批复",
                    "港澳台政府公众假期公告"],
        "rhythm": "每年 Q4 录入次年；突发调整随发随录",
        "rule": "照录官方名称与文号，不改写、不合并、不自造简称",
    },
    {
        "id": "C3",
        "name": "中国权威叙事",
        "level": "A",
        "entries": ["人民网·中国共产党新闻网 党史频道（党史上的今天 / 党史大事记 / 重要会议 / 英雄烈士谱）",
                    "中国政府网、中央党史和文献研究院、新华社",
                    "人民日报 / 光明日报 / 中青在线固定纪念栏目"],
        "rhythm": "季度扫描候选 → 逐条核源 → 过 curated.validate() 闸门才入库",
        "rule": "只收日期固定、可年度复现、且有 A 级依据的日子："
                "① 官方曾以「纪念 / 周年」形式发布；"
                "② A 级央媒按日固定栏目 / 逢十周年报道逐年回顾的史实时刻（v1.65）。"
                "普通史实记录不等于纪念日；名称一律照录官方史实表述，不自造「XX 纪念日」。"
                "v1.65 口径（用户定档）：中国体育夺冠 / 党史胜利时刻按「节日」计数与措辞，"
                "分类前缀统一「中国 · 」，不单设纪念文案——沿用 1.62 的 nounOf 逻辑："
                "单独存在是节日，节日加会议仍是节日，只有纯会议才叫活动",
    },
    {
        "id": "C4",
        "name": "国际与权威百科",
        "level": "B",
        "entries": ["维基百科条目及其引用、大英百科",
                    "UN / UNESCO 国际日清单、国际组织官方页",
                    "Google Doodle 官方归档（仅作选题线索，不作事实依据）"],
        "rhythm": "季度扫描；Doodle 归档只用来发现选题，事实必须回 A/B 复核",
        "rule": "C 级（行业民间 / Doodle）只作佐证；D 级（二手媒体、聚合站、自媒体）永不作依据",
    },
    {
        "id": "C5",
        "name": "官方会议与活动日历（含旗舰行业展）",
        "level": "A",
        "entries": ["APEC 官网 Events Calendar（apec.org/engage-with-us/events-calendar）",
                    "G20 官网 Events（g20.org/events/）",
                    "UNFCCC 官方通知、联合国全球会议日历",
                    "中国政府网 / 外交部 / 商务部重点展会目录 / 各展会官网 / 中国政协网",
                    "轮值主席国官网、新华社、人民日报赛历",
                    "国际单项体育联合会官网（FIFA / World Athletics / FISU / ITTF / UCI）",
                    "ITU / BIE / UN ESCAP 官方通知，CES / GSMA / IFA / Web Summit 等主办方官网"],
        "rhythm": "每年 Q4 逐源头扫下一年官方定档（含体育联合会 / 国际组织 / 展会官网）→ 逐条核源 → conferences.py 追加；改期随发随改",
        "rule": "只收国家 / 政府间组织 / 国际单项体育联合会主办，或主办方官网定档的旗舰行业展；"
                "必须已公布确切日期，只落开幕日；"
                "只收名称 + 日期 + 地点，不收议题 / 宣言 / 参会方表述；港澳台按一个中国原则写",
    },
]

SOURCE_LEVEL = {c["id"]: c["level"] for c in CHANNELS}

# ---------------------------------------------------------------- 2. 正交分类

# kind → 小组件第二列的 2 字标签。原来这一列是「国家」，只显示中国后全是
# 「中国」没有信息量，改显示类型。版式与 XML 一律不动，只换取值。
KINDS: dict[str, str] = {
    "official": "法定",
    "traditional": "传统",
    "solar_term": "节气",
    "memorial": "纪念",
    "person": "人物",
    "milestone": "大事",
    "theme": "主题",
    "religious": "宗教",
    "folk": "民俗",
    "adjustment": "调休",
    # v1.49：世界级 / 国家级会议与活动。名称写成「会议 · X」，App 按「·」拆两列后
    # 右列自然显示「会议」，与「摩洛哥 · 独立日」同构，无需改一行 App 代码。
    "conference": "会议",
}

SCOPES = {"cn": "中国内地", "cn-region": "中国港澳台", "world": "国际/无国别", "foreign": "外国国别"}

# observances.py 的 cat → v12 kind。cat 是源头字段，不是从名字猜的。
CAT_TO_KIND = {
    "法定": "official", "传统": "traditional", "纪念": "memorial",
    "民俗": "folk", "国际": "theme",
    "职业": "theme", "健康": "theme", "环境": "theme", "文化": "theme",
    "社会": "theme", "消费": "theme", "体育": "theme",
}

# 排序权重（大者靠前）。小组件 4 行按此排，不是按名称顺序。
# v1.49：会议排在法定节日之后、传统节气之前——国家级 / 世界级会议比主题日更靠前，
# 但不会挤掉法定节假日。conference 必须在此表内，否则小组件排序会退化成 99。
KIND_ORDER = ["official", "conference", "traditional", "solar_term", "memorial",
              "person", "milestone", "theme", "religious", "folk"]


def meta(kind: str, scope: str, channel: str, detail: str = "",
         url: str = "", level: str | None = None, verified: str = VERIFIED) -> dict:
    """构造一条元数据。level 缺省按渠道级别，渠道不认得就报错。"""
    if kind not in KINDS:
        raise ValueError(f"未知 kind: {kind}")
    if scope not in SCOPES:
        raise ValueError(f"未知 scope: {scope}")
    if channel not in SOURCE_LEVEL:
        raise ValueError(f"未登记渠道: {channel}")
    return {
        "kind": kind,
        "scope": scope,
        "channel": channel,
        "source": detail or CHANNELS[[c["id"] for c in CHANNELS].index(channel)]["name"],
        "level": level or SOURCE_LEVEL[channel],
        "url": url,
        "verified": verified,
    }


def label(m: dict) -> str:
    return KINDS[m["kind"]]


def widget_visible(m: dict, name: str = "") -> bool:
    """v18：小组件恢复「方案一 = 全球」，所有条目都可见。

    v1.45 曾按 v16 路线 2 把外国国别条目整层挡在小组件外（用户当时是在讨论
    「方案二：只放中国」，并非要求改动线上方案一）。这里撤销那道按国别的过滤，
    改为只由「内容红线」决定去留：有问题的剔掉，没问题的都出现。

    调休补假（adjustment）不在这里过滤，由 build.py 生成 widget 文件时排除，
    保证「今天有 N 个」与空态判定都按 v12 口径一致。
    """
    return True


# ---------------------------------------------------------------- 3. 安全红线（v18：按内容点名）

REDLINES = [
    ("R1", "ALL", "战犯与侵略战争",
     "战犯、靖国神社、纳粹、侵略/殖民战争胜利纪念，任何一端零容忍（点名关键词）"),
    ("R2", "ALL", "国家主权表述",
     "港澳台只能作地区，固定写「中国香港 / 中国澳门 / 中国台湾」，绝不作为国家"),
    ("R3", "ALL", "战前体制关联日（点名 3 条）",
     "日本 · 昭和日 / 建国日 / 文化日；其余日本中性民俗、节气、天皇诞辰照常保留"),
    ("R4", "ALL", "中国池整层豁免",
     "中国官方人物/纪念日名称同样含「诞辰」，不能被任何人物类黑名单误删"),
    ("R5", "会议层", "会议层议题性表述（v1.49）",
     "「会议 · X」/「展会 · X」只收名称 + 日期 + 地点：战犯侵略 / 主权 / 制裁 / 军演 / 台独疆独藏独 / "
     "宣言声明公报决议 / 人权领土等议题词一律拦；港澳台必须写「中国香港 / 中国澳门 / 中国台湾」"),
    ("已撤销", "—", "按国别/按类别整组排除",
     "v1.45 的 R1 敏感国别整组、R2 外国人物一律不收、R3 战争政权评价性一律不收，"
     "共连坐 70 条/年（13 条中性日本民俗、25 条外国正面人物、32 条别国内政纪念日）。"
     "v18 起改为只按「内容是否有问题」逐条判定，没问题的可以出现在小组件里。"),
]

# 只保留「内容确实有问题」的点名清单；不再有「诞辰」「胜利日」这类宽泛关键词。
_HARD_BAN = ("靖国", "希特勒", "纳粹", "战犯", "大东亚", "皇军", "神风")
_JP_PREFIX = "日本 · "
# 修 v1.45 缺陷：数据里实际叫「日本 · 建国日」，旧规则写「建国纪念日」导致漏网。
_JP_SENSITIVE = ("昭和日", "建国日", "文化日")
_BAD_SOVEREIGN = ("台湾 · ", "香港 · ", "澳门 · ", "中华民国 · ", "Taiwan · ", "Hong Kong · ")
_CN_PREFIX = ("中国 · ", "中国香港 · ", "中国澳门 · ", "中国台湾 · ")
# v1.49 会议层 / v1.50 展会层：名称本身中性，议题才可能踩线。这里对两类前缀再上一道统一红线，
# 与 conferences.validate() 双保险——生成期任何一端写入会议名都会过这一关。
_CONF_PREFIX = ("会议 · ", "展会 · ")
_CONF_BAN = ("战犯", "侵略", "靖国", "纳粹", "天皇", "军国", "慰安",
             "主权", "制裁", "军演", "台独", "疆独", "藏独", "独立公投",
             "宣言", "声明", "公报", "决议", "人权", "领土")
_CONF_SOVEREIGN = re.compile(r"(?<!中国)(香港|澳门|台湾)")


def is_cn(t: str) -> bool:
    return t.startswith(_CN_PREFIX)


def content_reason(name: str) -> str | None:
    """v18 唯一红线：只按内容点名，返回命中原因，None = 放行。

    所有端（网站 / 全球总表 / 分国家订阅 / 小组件）统一用这一套，
    不再有 STRICT / HARD 两套口径互相打架。
    R4 中国池豁免必须早于 R3，避免官方条目被卷入。
    """
    t = name.strip()
    if any(k in t for k in _HARD_BAN):
        return "R1 战犯与侵略战争"
    if t.startswith(_BAD_SOVEREIGN):
        return "R2 国家主权表述"
    if t.startswith(_CONF_PREFIX):
        if any(k in t for k in _CONF_BAN):
            return "R5 会议层议题性表述"
        if _CONF_SOVEREIGN.search(t):
            return "R2 国家主权表述"
    if is_cn(t):
        return None
    if t.startswith(_JP_PREFIX) and any(k in t for k in _JP_SENSITIVE):
        return "R3 战前体制关联日"
    return None


# 兼容旧调用点：build.py 里 STRICT 链路与 HARD 链路现在指向同一套规则。
def strict_reason(name: str) -> str | None:
    return content_reason(name)


def hard_reason(name: str) -> str | None:
    return content_reason(name)


def banned(name: str, strict: bool = True) -> str | None:
    return content_reason(name)


# ---------------------------------------------------------------- 4. 名称 → 元数据

_AREA_PREFIX = re.compile(r"^([^\s·（(]+?)\s*·\s*(.+)$")

# ---------------------------------------------------------------- v1.71 显示名剥前缀
# 用户定稿 2026-11-20：显示名一律裸名，不带「地区 · 」「N 国 · 」等前缀
# （前缀 + 间隔号占了小组件 / 网站一大块宽度，核心节日名反而显示不全）。
AREA_HEADS = {"中国", "中国香港", "中国澳门", "中国台湾", "国际",
              "会议", "展会", "天象", "宗教", "全球宗教"}
_NATION_HEAD = re.compile(r"^(\d+\s*国(?:家/地区)?)\s*·\s*(.+)$")
# 名字本身的间隔号（马丁·路德·金）转全角「・」：App splitEntries 按 U+00B7
# 拆两列，裸名里再出现半角间隔号会被误拆成「分类=马丁」。
_INNER_DOT = str.maketrans({"·": "・"})


def register_areas(names) -> None:
    """build.py 把 i18n 国别中文名注册进来，剥前缀只认这份名单，防误伤。"""
    AREA_HEADS.update(names)


def display_name(t: str) -> str:
    """对外显示名：剥「地区 · 」前缀与「（N 国）」合并尾巴，返回裸名。"""
    t = t.strip()
    head, rest = "", t
    pm = _AREA_PREFIX.match(t)
    if pm and pm.group(1) in AREA_HEADS:
        head, rest = pm.group(1), pm.group(2).strip()
    else:
        nm = _NATION_HEAD.match(t)
        if nm:
            rest = nm.group(2).strip()
    # v1.72 用户定稿：会议/展会的「会议 · 」「展会 · 」也是类别头，单列展示端
    # 一律剥掉——名称就是名称（广交会就显示「广交会」）。类别信息在小组件
    # 两列格式（widget_name）与 meta 的 kind 字段里。
    return _merge_tail_strip(rest.translate(_INNER_DOT))


def classify(name: str, *, obs_index: dict, country_names: set[str],
             lunar_names: set[str], term_names: set[str],
             curated_names: set[str], desc: str = "", year: int = 0,
             topic: bool = False) -> dict:
    """把一条全量池条目挂上元数据。

    判定依据是「生成来源」，不是中文名里的词：
      - 中国 / 港澳台 / 外国国别前缀是 build.py 结构化写入的地区标识；
      - 节气温 observances.py 的 scope / cat 字段与 24 节气集合；
      - 策展条目按名单精确匹配；
      - 合并条目的 desc 里带「包含 N 国」名单，据此判外国聚合。
    无法可靠归类的兜底为 (theme, world) 并标 inferred，生成期会统计上报。
    """
    t = name.strip()
    pm = _AREA_PREFIX.match(t)
    area = pm.group(1).strip() if pm else ""
    rest = pm.group(2).strip() if pm else t
    # 「中国 · 节气 · 立春」里还嵌一层「节气 · 」
    core = rest.split(" · ", 1)[1].strip() if rest.startswith("节气 · ") else rest

    def m(kind, scope, channel, detail, url="", level=None):
        return meta(kind, scope, channel, detail, url, level)

    # 1) 人工策展（A 级，来源逐条带 URL）
    if t in curated_names or core in curated_names:
        for c in __import__("curated").ENTRIES:
            if c["name"] in (t, core, rest):
                return m(c["kind"], "cn", "C3", c["sources"][0][0], c["sources"][0][1], "A")

    # 2) 官方放假安排 / 调休（desc 是 build.py 写入的结构化标记）
    if desc.startswith("周末调休上班"):
        return m("adjustment", "cn", "C2", "国务院办公厅节假日安排通知 · 周末调休上班")
    if "国务院办公厅" in desc or "节假日安排" in desc:
        return m("official", "cn", "C2", "国务院办公厅节假日安排通知")

    # 3) 24 节气 / 农历传统节日（只对内地条目生效）。
    #    「中国澳门 · 冬至」是澳门公众假期，不能因为名字撞上节气就标成节气，
    #    否则会和同日「中国 · 节气 · 冬至」在小组件里去重成一条。
    if area in ("", "中国", "节气") and (
            core in term_names
            or t.startswith("节气 · ")  # 旧写法兼容
            or (core.endswith("节气") and core[:-2] in term_names)):  # v1.70「小雪节气」
        return m("solar_term", "cn", "C1", "cnlunar 二十四节气算法")
    if area in ("", "中国") and core in lunar_names:
        return m("traditional", "cn", "C1", "cnlunar 农历 + 中国传统节日表")

    # 4) 结构化地区前缀 —— 必须早于 observances 查询。
    #    外国节日与中国节日重名极多（元旦、儿童节、劳动节、建军节、中秋节…），
    #    先剥前缀再查表会把「俄罗斯 · 元旦」误判成中国元旦，进而混进小组件。
    if area and area != "节气":
        if area.startswith("中国") and area != "中国":
            return m("official", "cn-region", "C2", f"{area} 政府公众假期公告")
        if area == "中国":
            o = obs_index.get(core) or obs_index.get(rest)
            if o is not None:
                return m(CAT_TO_KIND.get(o.cat, "theme"), "cn", "C3",
                         f"observances.py cat={o.cat} scope={o.scope}")
            return m("memorial", "cn", "C3", "中国官方纪念日（observances.py）")
        # 未知前缀也保守当外国，绝不误收进小组件
        return m("official", "foreign", "C1", "holidays 开源假日库 · " + area)

    # 5) 多国合并条目：desc 带「包含 N 国」名单
    if desc.startswith("包含 "):
        if "世界" in t or "国际" in t:
            return m("theme", "world", "C1", "多国同日同节合并 · 国际主题日")
        return m("official", "foreign", "C1", "holidays 开源假日库 · 多国同日同节合并")

    # 6) 无前缀：observances 精确匹配（不剥前缀）
    o = obs_index.get(t)
    if o is not None:
        scope = "world" if o.scope == "world" else "cn"
        return m(CAT_TO_KIND.get(o.cat, "theme"), scope,
                 "C4" if scope == "world" else "C3",
                 f"observances.py cat={o.cat} scope={o.scope}")

    # 7) 专题（宗教 / 天象赛事）
    if topic or t.startswith(("全球宗教", "天象")):
        return m("religious" if "宗教" in t or "节" in t else "theme",
                 "world", "C4", "专题订阅源文件 _source/*.ics")

    # 8) 无国别前缀的国际日 / 主题日兜底
    inferred = m("theme", "world", "C4", "国际日 / 世界日（UN / UNESCO 清单）")
    inferred["inferred"] = True
    return inferred


def bare_name(name: str) -> str:
    """去掉结构化地区前缀，给小组件用。"""
    t = name.strip()
    if " · " in t:
        t = t.split(" · ", 1)[1].strip()
    if t.startswith("节气 · "):
        t = t.split(" · ", 1)[1].strip()
    # 合并条目的「（N 个国家/地区）」保留，是有效信息
    return t


def widget_name(name: str, m: dict) -> str:
    """小组件 / App 数据的两列传输格式「类别 · 名称」（v1.72 用户定稿 2026-11-20）。

    用户模型：数据里名称与类别是两列，就像姓与名——展示时名称列只显示
    名称、类别列只显示类别，名称永远不带类别。App 的 splitEntries 按第一
    个「·」拆开：左列小字=类别（中国/国际/N 国/民俗/宗教/天象/会议/展会/
    国名），右列=纯名称；FlowCard 查 short.json 用的就是右列裸名键。
    「会议 · 」「展会 · 」在数据里也回归类别列语义，展示端名称列同样干净，
    App 的 isActivityName / nounOf 逻辑不受影响（无需发 APK）。

    单列展示端（网站 events.json / ICS SUMMARY / meta 依据页）不用本函数，
    用 display_name()（裸名）。
    """
    t = name.strip()
    if t.startswith("节气 · "):
        # 旧写法「节气 · 小雪」→ 两列「中国 · 小雪节气」（节气是中国独有）
        return "中国 · " + t[len("节气 · "):].strip() + "节气"
    bare = display_name(t)
    if bare.endswith("节气") and len(bare) == 4:
        # 名称仍是「小雪节气」四字（用户 v1.70 定稿），但必须补回类别列「中国」：
        # 两列模型要求每条都有分类，节气是二十四节气、中国独有，分类就是中国。
        return "中国 · " + bare
    if " · " in t:
        return t          # 原名自带类别头（中国/国际/会议/国名…），原样即两列
    split = widget_cat(t)
    return f"{split[0]} · {split[1]}" if split else t


# 名字自带国名、却没写成前缀的两条，直接还原成标准两列
_OWN_COUNTRY = {"法国国庆": ("法国", "国庆"), "墨西哥亡灵节": ("墨西哥", "亡灵节")}
# 多国合并尾巴：「（47 个国家/地区）」「（2 国）」
_MERGE_TAIL = re.compile(r"（(\d+)\s*(?:个国家/地区|国)）$")
# 天象：不是节日，但确实在日历里
_ASTRO_KEYS = ("流星雨", "日全食", "日环食", "日偏食", "月全食", "月食", "极光", "超级月亮")
# 宗教节日（无国别前缀的那些）
_RELIGIOUS_KEYS = (
    "光明节", "逾越节", "犹太新年", "赎罪日", "卫塞节", "排灯节", "洒红节",
    "斋月", "复活节", "主显节", "开斋", "宰牲", "先知", "阿舒拉", "阿拉法特",
    "圣灵", "圣母", "诸圣", "万灵", "圣周六", "耶稣", "佛诞", "仲夏",
    "圣彼得", "黑天", "罗摩", "湿婆", "十胜", "登霄",
)
# 民俗节日（无国别前缀的那些）
_FOLK_NAMES = {"万圣节", "情人节", "白色情人节", "愚人节", "母亲节", "父亲节"}


def _merge_tail_strip(t: str) -> str:
    """v1.60 用户：「名字按 6 字容量、『圣诞节（47…』很难看」——
    带国数的合并条目**名字**只留节日名（与 build.py 合并展示口径一致）。"""
    mm = _MERGE_TAIL.search(t)
    return t[: mm.start()].strip() if mm else t


def widget_cat(t: str) -> tuple[str, str] | None:
    """把一条无前缀名称拆成 (分类, 名称)；无法判定时返回 None（保持原样）。"""
    t = t.strip()
    if not t:
        return None
    if t in _OWN_COUNTRY:
        return _OWN_COUNTRY[t]
    mm = _MERGE_TAIL.search(t)
    if mm:
        return (f"{mm.group(1)} 国", _merge_tail_strip(t))
    if any(k in t for k in _ASTRO_KEYS):
        return ("天象", t)
    if any(k in t for k in _RELIGIOUS_KEYS):
        return ("宗教", t)
    if t in _FOLK_NAMES:
        return ("民俗", t)
    # 节气（「小雪节气」式）是中国独有，分类必须是「中国」，不能落国际兜底。
    # 名称仍为「小雪节气」四字，类别列单独填「中国」。
    if t.endswith("节气") and len(t) == 4:
        return ("中国", t)
    # 其余无国别条目 = 世界 / 国际 / UN 主题日
    return ("国际", t)


# ---------------------------------------------------------------- 5. 生成期校验

def validate(records: list[dict], *, strict: bool = True) -> list[str]:
    """全量扫描：任何一条不合格即返回错误，由 build.py 让构建失败。"""
    errs: list[str] = []
    for r in records:
        m = r.get("meta") or {}
        for k in ("kind", "scope", "channel", "source", "level", "verified"):
            if not m.get(k):
                errs.append(f"元数据缺 {k}: {r.get('name', '')}")
        if m.get("kind") not in KINDS:
            errs.append(f"未知 kind: {r.get('name', '')} -> {m.get('kind')}")
        if m.get("channel") not in SOURCE_LEVEL:
            errs.append(f"未登记渠道: {r.get('name', '')} -> {m.get('channel')}")
        if m.get("level") not in ("A", "B"):
            errs.append(f"来源等级不合规: {r.get('name', '')}")
        # R4 中国池必须整层豁免红线
        if m.get("scope") in ("cn", "cn-region"):
            reason = content_reason(r.get("name", ""))
            if reason:
                errs.append(f"R4 中国池被红线误伤: {r.get('name', '')} -> {reason}")
    return errs


if __name__ == "__main__":
    import json
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import curated
    print("渠道:", ", ".join(f"{c['id']} {c['name']}({c['level']})" for c in CHANNELS))
    print("分类:", ", ".join(f"{k}={v}" for k, v in KINDS.items()))
    errs = curated.validate()
    print(f"策展库 {len(curated.ENTRIES)} 条，闸门：{'通过' if not errs else errs}")
    for y in (2026, 2027):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", f"all-{y}.json")
        if not os.path.exists(p):
            continue
        days = json.load(open(p, encoding="utf-8"))["days"]
        rows = [t for v in days.values() for t in v]
        hits = [(t, content_reason(t)) for t in rows if content_reason(t)]
        print(f"{y}: 全量 {len(rows)} 条 | 内容红线命中 {len(hits)} 条 -> {set(r for _, r in hits)}")
