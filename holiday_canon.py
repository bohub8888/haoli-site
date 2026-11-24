#!/usr/bin/env python3
"""节假日语义归并：把「同义异名」映射到同一个规范键。

为什么需要这一层：
  同一个节日，各国译名不一样 —— 「元旦 / 元旦假期」、 「劳动节 / 国际劳动节 /
  五一节 / 劳动者节」、 「圣诞节次日 / 节礼日 / 圣斯德望日」。
  若只按名字字符串去重，1 月 1 日仍会出现几十条同义条目。

归并规则：
  1. 规范键相同 **且日期相同** 才算同一个节日 —— 只做同义归并，
     不做「宽泛归类」，不同节日即使撞在同一天也不合并；
  2. 含义确有差别的不合并：除夕≠跨年夜、东正教圣诞(1/7)≠圣诞(12/25)、
     中秋≠中秋翌日、各国「独立日 / 国庆日」按日期自然分开；
  3. 「（补假）」是补休日，与正日不是同一天，加 #sub 后缀，永不与正日合并；
  4. 「（推算）」是伊斯兰/农历节日按天文推算的日期，合并时只在描述里提示，
     因为对用户来说它就是开斋节，只是可能差一天。

新增国家或出现新译名时：未收录的名字会以自身为键（不合并），
用 `python holiday_canon.py` 自查清单里还有哪些同义项漏收。
"""

from __future__ import annotations

# 名称 → (规范键, 显示名)。键相同的条目才会被合并。
CANON: dict[str, tuple[str, str]] = {
    # ---------------- 元旦 / 新年 ----------------
    "元旦": ("new-year", "元旦"),
    "元旦假期": ("new-year", "元旦"),
    "元旦节": ("new-year", "元旦"),
    "新年": ("new-year", "元旦"),
    "元旦次日": ("new-year", "元旦"),
    "跨年夜": ("new-year-eve", "跨年夜"),
    "新年前夜": ("new-year-eve", "跨年夜"),
    "新年前夕": ("new-year-eve", "跨年夜"),
    # ---------------- 春节（农历新年，各国叫法不同） ----------------
    "春节": ("spring", "春节"),
    "农历新年": ("spring", "春节"),
    "农历新年假期": ("spring", "春节"),
    "韩国新年": ("spring", "春节"),
    "越南新年": ("spring", "春节"),
    "农历年初一": ("spring", "春节"),
    "农历正月初一": ("spring", "春节"),
    "春节（农历新年）": ("spring", "春节"),
    "除夕": ("spring-eve", "除夕"),
    "韩国新年前一日": ("spring-eve", "除夕"),
    "农历除夕": ("spring-eve", "除夕"),
    "春节初二": ("spring", "春节"),
    "农历年初二": ("spring", "春节"),
    "农历正月初二": ("spring", "春节"),
    "春节次日": ("spring", "春节"),
    "春节初三": ("spring", "春节"),
    "农历年初三": ("spring", "春节"),
    "农历正月初三": ("spring", "春节"),
    "韩国新年第二天": ("spring", "春节"),
    "春节初四": ("spring", "春节"),
    "农历年初四": ("spring", "春节"),
    "农历正月初四": ("spring", "春节"),
    "春节初五": ("spring", "春节"),
    "农历正月初五": ("spring", "春节"),
    # ---------------- 秋夕 = 中秋 ────────────────
    "秋夕": ("mid-autumn", "中秋节"),
    "秋夕（中秋）": ("mid-autumn", "中秋节"),
    "中秋节": ("mid-autumn", "中秋节"),
    "秋夕前一日": ("mid-autumn", "中秋节"),
    "秋夕第二天": ("mid-autumn", "中秋节"),
    "中秋节翌日": ("mid-autumn", "中秋节"),
    "中秋節翌日": ("mid-autumn", "中秋节"),
    "中秋节次日": ("mid-autumn", "中秋节"),
    # ---------------- 端午 ----------------
    "端午节": ("dragon-boat", "端午节"),
    "端午": ("dragon-boat", "端午节"),
    "端午节翌日": ("dragon-boat", "端午节"),
    # ---------------- 劳动节 ----------------
    "劳动节": ("labour", "劳动节"),
    "国际劳动节": ("labour", "劳动节"),
    "五一节": ("labour", "劳动节"),
    "五一": ("labour", "劳动节"),
    "劳动者节": ("labour", "劳动节"),
    "劳动与团结日": ("labour", "劳动节"),
    "春季劳动节": ("labour", "劳动节"),
    "劳动节暨团结日": ("labour", "劳动节"),
    "五月公假": ("labour", "劳动节"),
    # ---------------- 妇女 / 儿童 ----------------
    "国际妇女节": ("women", "国际妇女节"),
    "妇女节": ("women", "国际妇女节"),
    "国际妇女权利日": ("women", "国际妇女节"),
    "儿童节": ("children", "儿童节"),
    "国际儿童节": ("children", "儿童节"),
    # ---------------- 圣诞系 ----------------
    "圣诞节": ("christmas", "圣诞节"),
    "圣诞节后": ("christmas", "圣诞节次日"),
    "博爱日": ("new-year", "元旦"),
    "圣诞节假期": ("christmas", "圣诞节"),
    "平安夜": ("christmas-eve", "平安夜"),
    "圣诞节前日": ("christmas-eve", "平安夜"),
    "圣诞节次日": ("christmas", "圣诞节次日"),
    "节礼日": ("christmas", "圣诞节次日"),
    "圣斯德望日": ("christmas", "圣诞节次日"),
    "圣诞节后第一个周日": ("christmas", "圣诞节次日"),
    "圣诞节后第一个星期一": ("christmas", "圣诞节次日"),
    "东正教圣诞节": ("orthodox-christmas", "东正教圣诞节"),
    "科普特圣诞节": ("coptic-christmas", "科普特圣诞节"),
    # ---------------- 复活节系（日期各不相同，按日期自然分开） ----------------
    "耶稣受难日": ("good-friday", "耶稣受难日"),
    "耶稣受难节": ("good-friday", "耶稣受难日"),
    "圣周五": ("good-friday", "耶稣受难日"),
    "濯足节": ("maundy", "濯足节"),
    "圣周四": ("maundy", "濯足节"),
    "圣周六": ("holy-saturday", "圣周六"),
    "黑色星期六": ("holy-saturday", "圣周六"),
    "复活节前日": ("holy-saturday", "圣周六"),
    "复活节": ("easter", "复活节"),
    "复活节星期一": ("easter-monday", "复活节翌日"),
    "复活节次日": ("easter-monday", "复活节翌日"),
    "耶稣升天节": ("ascension", "耶稣升天节"),
    "圣灵降临节": ("pentecost", "圣灵降临节"),
    "五旬节": ("pentecost", "圣灵降临节"),
    "圣灵降临节星期一": ("whit-monday", "圣灵降临节翌日"),
    "基督圣体节": ("corpus-christi", "基督圣体节"),
    "耶稣圣心节": ("sacred-heart", "耶稣圣心节"),
    # ---------------- 圣母 / 诸圣 ----------------
    "圣母升天节": ("assumption", "圣母升天节"),
    "圣母安息节": ("assumption", "圣母升天节"),
    "圣母无原罪日": ("immaculate", "圣母无原罪日"),
    "圣母无原罪瞻礼": ("immaculate", "圣母无原罪日"),
    "诸圣节": ("all-saints", "诸圣节"),
    "万圣节": ("halloween", "万圣夜"),
    "万灵节": ("all-souls", "万灵节"),
    "追思节": ("all-souls", "万灵节"),
    "主显节": ("epiphany", "主显节"),
    "圣若瑟日": ("saint-joseph", "圣若瑟日"),
    "圣彼得与圣保罗日": ("saints-peter-paul", "圣彼得与圣保罗日"),
    "施洗约翰节": ("saint-john", "施洗约翰节"),
    "宗教改革日": ("reformation", "宗教改革日"),
    # ---------------- 国庆 / 独立 / 宪法 ----------------
    "国庆节": ("national-day", "国庆日"),
    "国庆日": ("national-day", "国庆日"),
    "国庆假期": ("national-day", "国庆日"),
    "加拿大国庆日": ("national-day", "国庆日"),
    "澳大利亚国庆日": ("national-day", "国庆日"),
    "卡塔尔国庆日": ("national-day", "国庆日"),
    "老挝国庆日": ("national-day", "国庆日"),
    "五月三日国庆日": ("national-day", "国庆日"),
    "独立日": ("independence", "独立日"),
    "国家独立日": ("independence", "独立日"),
    "独立宣言日": ("independence", "独立日"),
    "独立恢复日": ("independence", "独立日"),
    "自由独立日": ("independence", "独立日"),
    "宪法日": ("constitution", "宪法日"),
    "制宪日": ("constitution", "宪法日"),
    "共和国日": ("republic", "共和国日"),
    "共和国宣言日": ("republic", "共和国日"),
    "解放日": ("liberation", "解放日"),
    "胜利日": ("victory", "胜利日"),
    "停战纪念日": ("armistice", "停战纪念日"),
    "阵亡将士纪念日": ("memorial", "阵亡将士纪念日"),
    "烈士日": ("memorial", "阵亡将士纪念日"),
    "光复节": ("liberation-kr", "光复节"),
    # ---------------- 伊斯兰节日 ----------------
    "开斋节": ("eid-fitr", "开斋节"),
    "开斋节假期": ("eid-fitr", "开斋节"),
    "开斋节第二天": ("eid-fitr", "开斋节"),
    "开斋节第三天": ("eid-fitr", "开斋节"),
    "宰牲节": ("eid-adha", "宰牲节"),
    "宰牲节假期": ("eid-adha", "宰牲节"),
    "古尔邦节": ("eid-adha", "宰牲节"),
    "伊斯兰新年": ("islamic-new-year", "伊斯兰新年"),
    "希吉来历新年": ("islamic-new-year", "伊斯兰新年"),
    "先知诞辰": ("mawlid", "先知诞辰"),
    "先知穆罕默德诞辰": ("mawlid", "先知诞辰"),
    "阿舒拉节": ("ashura", "阿舒拉节"),
    "登霄节": ("isra-miraj", "登霄节"),
    "盖德尔夜": ("laylat-qadr", "盖德尔夜"),
    "阿拉法特日": ("arafat", "阿拉法特日"),
    "斋月开始": ("ramadan-start", "斋月开始"),
    # ---------------- 南亚 / 东南亚 ----------------
    "卫塞节": ("vesak", "佛诞（卫塞节）"),
    "佛诞节": ("vesak", "佛诞（卫塞节）"),
    "佛诞": ("vesak", "佛诞（卫塞节）"),
    "万佛节": ("makha-bucha", "万佛节"),
    "排灯节": ("diwali", "排灯节"),
    "灯节": ("diwali", "排灯节"),
    "财神日": ("diwali", "排灯节"),
    "洒红节": ("holi", "洒红节"),
    "洒红节（特莱地区）": ("holi", "洒红节"),
    "十胜节": ("dussehra", "十胜节"),
    "十胜节第八日": ("dussehra", "十胜节"),
    "十胜节第九日": ("dussehra", "十胜节"),
    "十胜节第十日": ("dussehra", "十胜节"),
    "十胜节第十一日": ("dussehra", "十胜节"),
    "十胜节第十二日": ("dussehra", "十胜节"),
    "诺鲁孜节": ("nowruz", "诺鲁孜节"),
    # 春分之日是日本法定假「春分の日」，跟伊朗/中亚的诺鲁孜节是两回事，
    # 各给各的规范键，不许并到一起（2026-11-10 修正：之前日本 3/20 被错标成诺鲁孜节）
    "春分日": ("vernal-equinox", "春分日"),
    "宋干节（泼水节）": ("songkran", "宋干节（泼水节）"),
    "高棉新年": ("khmer-new-year", "高棉新年"),
    "老挝新年": ("lao-new-year", "老挝新年"),
    "缅甸新年": ("myanmar-new-year", "缅甸新年"),
    "孟加拉新年": ("bengali-new-year", "孟加拉新年"),
    "尼泊尔新年": ("nepali-new-year", "尼泊尔新年"),
    "藏历新年": ("tibetan-new-year", "藏历新年"),
    "犹太新年": ("rosh-hashanah", "犹太新年"),
    "赎罪日": ("yom-kippur", "赎罪日"),
    "逾越节": ("passover", "逾越节"),
    "住棚节": ("sukkot", "住棚节"),
    "妥拉节": ("simchat-torah", "妥拉节"),
    # ---------------- 中国港澳台 ----------------
    "清明节": ("qingming", "清明节"),
    "重阳节": ("double-ninth", "重阳节"),
    "冬至": ("winter-solstice", "冬至"),
    "香港特别行政区成立纪念日": ("hk-sar", "香港特别行政区成立纪念日"),
    "澳门特别行政区成立纪念日": ("mo-sar", "澳门特别行政区成立纪念日"),
    "情人节": ("valentine", "情人节"),
    "愚人节": ("april-fool", "愚人节"),
}

# 补假 / 推算 后缀：先剥离再查表，避免「中秋节（补假）」这类变体各自成键。
# 港澳用「圣诞节补假」「劳动节补假」这种不带括号的写法，一并处理。
SUB_SUFFIX = ("（补假·推算）", "（补假）", "(补假)", "补假")
EST_SUFFIX = ("（推算）", "(推算)", "（天文推算）")

# 个别国家把同一天叫成别的节日名（库里的命名差异），按「日期 + 名称」定点纠正。
# 按国家纠库里的命名偏差：(国家代码, 月, 日, 名称) → (键, 显示名)
COUNTRY_BY_DATE: dict[tuple[str, int, int, str], tuple[str, str]] = {
    # 波兰 5/1 是劳动节（Święto Pracy），库写作 National Day
    ("PL", 5, 1, "国庆节"): ("labour", "劳动节"),
    # 俄罗斯 1/7 是东正教圣诞节（儒略历 12/25），库写作 Christmas Day
    ("RU", 1, 7, "圣诞节"): ("orthodox-christmas", "东正教圣诞节"),
}

BY_DATE: dict[tuple[int, int, str], tuple[str, str]] = {
    # 罗马尼亚把 12/26 也写作 Christmas Day，实为圣诞第二天
    (12, 26, "圣诞节"): ("christmas", "圣诞节次日"),
}


def split_flags(name: str) -> tuple[str, bool, bool]:
    """拆出「（补假）」「（推算）」，返回 (基名, 是否补假, 是否推算)。"""
    base, sub, est = name.strip(), False, False
    for suf in SUB_SUFFIX:
        if base.endswith(suf) and len(base) > len(suf):
            base, sub = base[: -len(suf)], True
            if "推算" in suf:
                est = True
            break
    for suf in EST_SUFFIX:
        if base.endswith(suf) and len(base) > len(suf):
            base, est = base[: -len(suf)], True
            break
    return base, sub, est


def canonical(name: str, day=None, code: str = "") -> tuple[str, str, bool, bool]:
    """名称（可带日期）→ (规范键, 显示名, 是否推算, 是否补假)。

    未收录的名字以自身为键 —— 宁可不合并，也不要合并错。
    「补假」不换键：补休日若正好落在别国正日那天，本质是同一个「今天放假」，
    合并后由调用方按「全组都是补假」决定是否在标题里标注。
    """
    base, sub, est = split_flags(name)
    if day is not None and (code, day.month, day.day, base) in COUNTRY_BY_DATE:
        key, label = COUNTRY_BY_DATE[(code, day.month, day.day, base)]
    elif day is not None and (day.month, day.day, base) in BY_DATE:
        key, label = BY_DATE[(day.month, day.day, base)]
    else:
        key, label = CANON.get(base, (base, base))
    return key, label, est, sub


def unknown_names(names) -> list[str]:
    """列出没有收录进 CANON 的名字，用于人工补表。"""
    return sorted({n for n in names if split_flags(n)[0] not in CANON})


if __name__ == "__main__":
    import collections
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import holidays as hlib

    import holiday_i18n as i18n

    names = collections.Counter()
    for code, _key, _zh, _region, _note in i18n.COUNTRIES:
        h = hlib.country_holidays(code, years=2027, language="en_US")
        for _d, n in h.items():
            names[i18n.zh_name(n, code)] += 1
    miss = unknown_names(names)
    print(f"未收录 {len(miss)} 个名字（各自独立成键、不合并）：")
    for n in miss:
        print("  ", n)
