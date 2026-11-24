"""数据层短名（v1.55 小组件「双栏流水」卡用）。

口径（用户定档）：
  · 卡片一行只放得下约 12 个汉字宽；名字超过这个宽度**不折行**——折行会吃掉
    一整条的位置、还会把稿纸线搅乱（设计稿 v23/v24）。
  · 解决办法在数据层：给超宽条目一个 12 字以内的**展示短名**。同一条数据在
    App / 网页里仍显示全称，只在卡片上显示短名，不是「从几条里挑一条短的」。
  · 两条规则自动处理大部分：①去掉「（10 个国家/地区）」这类国家数尾巴；
    ②手工表兜底那些真正长、且短不掉的（机构名、外文名、含「暨」的复合名）。
  · 渲染层拿不到短名时退回单行省略号，永不折行。
"""

import json
import os
import re
import unicodedata

# 国家数尾巴：「（10 个国家/地区）」「（2 国）」
_COUNT_TAIL = re.compile(r"（[^（）]*?(?:个国家/地区|国)[^（）]*?）\s*$")

# 手工短名：键 = 去掉「地区 · 」前缀后的显示名（与 App 里看到的一致）
MANUAL = {
    # —— v1.70：主库显示名统一为全称后，卡片仍沿用原短名（详见 observances.py 命名纪律）——
    "全民国家安全教育日": "国家安全日",
    "全国防灾减灾日": "防灾减灾日",
    "五卅运动纪念日": "五卅运动",
    "辛亥革命纪念日": "辛亥革命",
    "澳门回归祖国纪念日": "澳门回归",
    # 台湾光复纪念日 7 字，流水卡沿用短名保护排版（日历/详情仍为官方全名）
    "台湾光复纪念日": "台湾光复日",
    # —— 机构 / 会议：用通用缩写 ——
    "国际货币基金组织与世界银行年会": "IMF 与世界银行年会",
    "联合国教科文组织数字学习周": "教科文组织数字学习周",
    "IEEE 国际机器人与自动化会议": "IEEE 机器人自动化会议",
    "联合国亚太经社会第83届年会": "亚太经社会第83届年会",
    "阿布扎比国际石油展览暨会议": "阿布扎比石油展",
    "贝尔格莱德专业类世界博览会": "贝尔格莱德世博会",
    # —— 中国会议：去掉届次 ——
    "十四届全国人大四次会议开幕": "全国人大会议开幕",
    "全国政协十四届四次会议开幕": "全国政协会议开幕",
    # —— 含「暨」的复合名：取前半 ——
    "阿塔图尔克纪念日暨青年体育节": "阿塔图尔克纪念日",
    "普密蓬国王诞辰暨国庆、父亲节": "普密蓬国王诞辰",
    "自由民主斗争日暨国际学生日": "自由民主斗争日",
    "主显节（三王节暨东正教圣诞）": "主显节",
    # —— 外文名：卡片不出现整句英文 ——
    "Visit of His Holiness Pope Leo XIV": "教皇利奥十四世到访",
    "Eid al-Fitr (additional holiday)": "开斋节（补假）",
    "Local Government Elections": "地方政府选举",
    "Local Election Day": "地方选举日",
    # —— 长专名 ——
    "哈桑纳尔·博尔基亚苏丹诞辰": "文莱苏丹诞辰",
    "第33届世界大学生冬季运动会": "世界大学生冬季运动会",
    "佛诞（卫塞节）（3 个国家/地区）": "佛诞（卫塞节）",
    # —— 「（补假）」条目：留补假标记，砍前面的长定语 ——
    "1·25 革命暨警察日（补假）": "革命暨警察日（补假）",
    "哈萨克斯坦民族团结日（补假）": "民族团结日（补假）",
    "国庆日（普密蓬诞辰）（补假）": "普密蓬诞辰（补假）",
    "奇金基拉圣母念珠日（补假）": "圣母念珠日（补假）",
    "朱拉隆功国王纪念日（补假）": "朱拉隆功纪念日（补假）",
    "澳门特别行政区成立纪念日（补假）": "澳门回归纪念日（补假）",
}


def width(text: str) -> float:
    """显示宽度：汉字 1，拉丁约 0.55。"""
    return round(sum(1 if unicodedata.east_asian_width(c) in "WF" else 0.55 for c in text), 1)


def short_of(name: str) -> str | None:
    """给一个显示名，返回短名；不需要短名时返回 None。"""
    if name in MANUAL:
        return MANUAL[name]
    stripped = _COUNT_TAIL.sub("", name).strip()
    if stripped and stripped != name:
        return stripped
    return None


def display_name(raw: str) -> str:
    """数据池条目「巴西 · 共和国日」→ 显示名「共和国日」。"""
    idx = raw.find("·")
    return raw[idx + 1:].strip() if 0 <= idx < len(raw) - 1 else raw.strip()


def build_map(years) -> dict[str, str]:
    """扫一遍产出池，返回 {显示名: 短名}。"""
    out: dict[str, str] = {}
    for y in years:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", f"all-{y}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            days = json.load(f)["days"]
        for names in days.values():
            for raw in names:
                d = display_name(raw)
                s = short_of(d)
                if s and s != d:
                    out[d] = s
    return dict(sorted(out.items()))


def report(years) -> dict:
    """构建期闸门：还有多少显示名超宽又没短名。"""
    over = []
    for y in years:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", f"all-{y}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            days = json.load(f)["days"]
        for names in days.values():
            for raw in names:
                d = display_name(raw)
                if width(d) > 12.4 and short_of(d) is None:
                    over.append(d)
    return {"over_width_no_short": sorted(set(over)), "manual": len(MANUAL)}


def write(years) -> dict:
    """写 data/short.json 与 APK assets（同一份）。"""
    base = os.path.dirname(os.path.abspath(__file__))
    mapping = build_map(years)
    text = json.dumps(mapping, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    with open(os.path.join(base, "data", "short.json"), "w", encoding="utf-8") as f:
        f.write(text)
    assets = os.path.join(os.path.dirname(base), "haoli-apk", "app", "src", "main", "assets", "data")
    if os.path.isdir(assets):
        with open(os.path.join(assets, "short.json"), "w", encoding="utf-8") as f:
            f.write(text)
    return {"count": len(mapping), "over": report(years)["over_width_no_short"]}
