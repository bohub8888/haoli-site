#!/usr/bin/env python3
"""译名自查：扫所有 ics，找出 SUMMARY 里完全不含中文的条目。

holiday_i18n.zh_name() 有英文兜底（词典没命中就留英文），这是刻意的降级，
但每次构建后应该看一眼还有多少漏网的：全是英文的节日名对用户是半个废条目。
输出按出现次数排序的未翻译英文名 top 列表，供往 holiday_i18n.ZH 补词条。

用法：python3 check_translations.py [目录 ...]   （默认 2026 2027 ics）
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent

# 摘要里至少要有这么多个 CJK 字符才算翻译过
MIN_CJK = 1


def summaries(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return re.findall(r"^SUMMARY:(.+)$", text, re.M)


def main() -> int:
    dirs = sys.argv[1:] or ["2026", "2027", "ics"]
    untagged: Counter[str] = Counter()
    total = 0
    for d in dirs:
        p = BASE / d
        if not p.exists():
            continue
        files = [p] if p.is_file() else sorted(p.glob("*.ics"))
        for f in files:
            for s in summaries(f):
                total += 1
                # 纯数字名（520、618 这类电商/网络节）本来就叫数字，不算漏翻
                if re.fullmatch(r"[\d\s·.]+", s.strip()):
                    continue
                if len(re.findall(r"[\u4e00-\u9fff]", s)) < MIN_CJK:
                    untagged[s.strip()] += 1

    print(f"扫描 {total} 条 SUMMARY，未含中文 {sum(untagged.values())} 条（去重 {len(untagged)} 个）")
    if untagged:
        print("\n未翻译 Top 20（补进 holiday_i18n.ZH 后重跑构建）:")
        for name, n in untagged.most_common(20):
            print(f"  {n:>4}  {name}")
    return 0


if __name__ == "__main__":
    main()
