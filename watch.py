#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""观察名单核对清单 —— 会议 / 展会日期落地的「最后一公里」。

用法
----
    ../.venv/bin/python watch.py            # 全量清单，按预计日期排序
    ../.venv/bin/python watch.py --due      # 只看本月该核的（自动化任务用这个）
    ../.venv/bin/python watch.py --month 3  # 只看 3 月要核的

为什么不能用一个频率扫全部
--------------------------
不同会议的主办方公布节奏差 3 倍以上，统一每周扫是浪费、统一每年扫会漏：

    两会          次年 3 月开会，前一年 12 月下旬人大常委会才定日期   → 12 月底必核
    广交会        每届开展前 3–4 个月公布                           → 1 月、6 月各核
    国家级展会    进博会 7–8 月 / 服贸会 6–7 月 / 消博会 2–3 月      → 按各自窗口核
    国际组织会议  达沃斯、IMF/世行、CERAWeek、ADIPEC、HIMSS、JPM
                  提前 9–12 个月定档，IMF 甚至提前 2 年              → Q4 核一次即可
    APEC / G20    东道主提前 1 年定城市与月份，提前 6–9 个月定日期    → 每季度核
    COP           东道主提前约 12 个月确认，日期提前 6–9 个月         → 每季度核
    体育赛事      提前 1–3 年定档                                   → Q4 核一次

所以这里的规则是：每条给一个「建议核对月」= 预计日期往前推 5 个月，并在到达
该月之后**每月都复核一次**（主办方常临时改期，越近越要盯）。--due 就是把这个
规则算成本月待办。
"""

from __future__ import annotations

import datetime as dt
import sys

sys.path.insert(0, ".")
import conferences as c  # noqa: E402

LEAD_MONTHS = 5  # 提前 5 个月开始进入核对窗口


def _shift_month(d: dt.date, months: int) -> dt.date:
    m = d.month - months
    y = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return dt.date(y, m, day)


def rows(today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    out = []
    for w in c.WATCHLIST:
        d = dt.date.fromisoformat(w["date_hint"])
        start = _shift_month(d, LEAD_MONTHS)
        out.append(dict(
            w,
            expect=d,
            start=start,
            days_left=(d - today).days,
            due_today=(today.year, today.month) >= (start.year, start.month),
        ))
    return sorted(out, key=lambda x: x["expect"])


def main(argv: list[str]) -> int:
    today = dt.date.today()
    data = rows(today)
    only_due = "--due" in argv
    month = None
    if "--month" in argv:
        month = int(argv[argv.index("--month") + 1])

    sel = [r for r in data if not only_due or r["due_today"]]
    if month:
        sel = [r for r in sel if r["expect"].month == month]

    print(f"观察名单 {len(c.WATCHLIST)} 条｜今天 {today}｜"
          f"{'本月该核' if only_due else '全量'} {len(sel)} 条\n")
    for r in sel:
        flag = "待核" if r["due_today"] else "未到窗口"
        print(f"[{flag}] {r['date_hint']} {r['name']}（还有 {r['days_left']} 天）")
        print(f"        公布节奏：{r['window']}")
        print(f"        官方页：{r['url']}")
    if only_due and not sel:
        print("本月没有到期条目；隔月再看。")

    print("\n核对后处理：")
    print("  1) 官方已定档 → 在 conferences.py 的 ENTRIES 追加一条（cert=\"official\"），")
    print("     并从 WATCHLIST 删除；来源写主办方页面标题 + 链接，等级按来源权威度给 A/B。")
    print("  2) 只公布开幕日 → cert=\"open\"，note 里写清会期补齐依据。")
    print("  3) 仍未定档 → 保留在 WATCHLIST，不动数据。")
    print("  4) 改完跑 ../.venv/bin/python build.py（VER 递增）→ 热更新，不重发 APK。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
