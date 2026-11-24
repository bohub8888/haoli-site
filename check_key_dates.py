#!/usr/bin/env python3
"""关键日期断言：人工核实过的「铁的事实」，防依赖库升级后日期漂移。

背景：数据来自 vacanza/holidays 等外部库，库升级可能悄悄改变行为。
这个脚本断言一组**人工核实过**的日期事实（不是和库自洽，是和现实自洽），
任何一次构建后跑一遍，日期错了立刻报错，而不是等用户发现。

用法：python3 check_key_dates.py   （默认检查 2026/2027 两年）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

# (文件, 日期 YYYYMMDD, SUMMARY 必须包含的关键词)
# 每一条都是人工对照官方来源核实过的；新增年份时在这里补断言。
FACTS: list[tuple[str, str, str]] = [
    # ---- 中国（法定 + 农历）----
    ("2026/ics/china-2026.ics", "20260101", "元旦"),
    ("2026/ics/china-2026.ics", "20260217", "春节"),
    ("2026/ics/china-2026.ics", "20261001", "国庆节"),
    ("2027/ics/china-2027.ics", "20270101", "元旦"),
    ("2027/ics/china-2027.ics", "20270206", "春节"),
    # ---- 中国香港 ----
    ("2026/ics/hk-2026.ics", "20260101", "元旦"),
    # ---- 日本（祝日）----
    ("2026/ics/jp-2026.ics", "20260101", "元旦"),
    ("2026/ics/jp-2026.ics", "20260112", "成人"),
    # ---- 美国（固定规则）----
    ("2026/ics/us-2026.ics", "20260704", "独立日"),
    ("2026/ics/us-2026.ics", "20261225", "圣诞节"),
    # ---- 韩国 ----
    ("2026/ics/korea-2026.ics", "20260101", "元旦"),
]


def events(path: Path) -> dict[str, str]:
    """解析一个 ics：date(YYYYMMDD) -> 该日全部 SUMMARY 拼接。"""
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}，先跑 build.py")
    text = path.read_text(encoding="utf-8")
    out: dict[str, list[str]] = {}
    date = ""
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"DTSTART(?:;[^:]*)?:(\d{8})", line)
        if m:
            date = m.group(1)
            continue
        m = re.match(r"SUMMARY:(.+)", line)
        if m and date:
            out.setdefault(date, []).append(m.group(1))
            date = ""
    return {d: " | ".join(v) for d, v in out.items()}


def main() -> int:
    cache: dict[str, dict[str, str]] = {}
    failures = 0
    for file, date, keyword in FACTS:
        if file not in cache:
            cache[file] = events(BASE / file)
        summary = cache[file].get(date, "")
        if keyword in summary:
            print(f"  ✓ {file} {date} {keyword}")
        else:
            failures += 1
            print(f"  ✗ {file} {date} 应有「{keyword}」，实际：{summary or '（该日无事件）'}")
    print(f"\n{'全部通过' if failures == 0 else f'{failures} 条断言失败！'}（{len(FACTS)} 条）")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
