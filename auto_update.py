#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全自动数据更新大脑（可在本地或 GitHub Actions 运行）。

职责：核对官方公告 → 严格核源 → 自动生成源表 → 调 pipeline 构建校验。
分发（推两个仓 + 服务器 + CDN）由调用方（CI 或 pipeline.publish-data）完成。

设计红线（用户 2026-11-19 定档）：
  · 全程零人工参与：拿不准就静默放弃，绝不猜、绝不编造、绝不打扰用户。
  · 唯一数据源是官方原文（中国政府网）；解析有歧义（checks 非空）即放弃。
  · 生成后必须让 check_official_notice 重跑回到 match，否则回滚放弃。
  · 全端一致：改的是唯一源表，后续 build 自然同步到所有端。

退出码：
  0  无变化 / 或更新成功（两种情况 CI 都不需要报错）
  2  发现差异但核源不过，已静默放弃（CI 记日志但不报警打扰用户）
  1  真正的系统错误（构建失败、校验不过）——需修，非用户决策

用法：
  .venv/bin/python auto_update.py            # 在线核对 + 自动更新
  .venv/bin/python auto_update.py --dry-run  # 只核对，不改任何文件
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VENV_PY = os.path.join(ROOT, ".venv", "bin", "python")
if not os.path.exists(VENV_PY):
    VENV_PY = sys.executable  # CI 里直接用当前 python

REPORT = os.path.join(HERE, "data", "official-notice-report.json")
CN_OFFICIAL = os.path.join(HERE, "cn_official.py")


def log(msg: str) -> None:
    print(f"[auto_update] {msg}", flush=True)


def run(cmd: str, cwd: str = HERE, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, shell=True, cwd=cwd, text=True,
                       capture_output=True, timeout=900)
    if check and r.returncode != 0:
        raise RuntimeError(f"命令失败: {cmd}\n{r.stdout}\n{r.stderr}")
    return r


# ---------------------------------------------------------------- 核对

def audit() -> dict:
    """在线核对官方公告，返回报告 dict。"""
    r = run(f'"{VENV_PY}" check_official_notice.py --refresh')
    log("核对输出：")
    for line in (r.stdout or "").splitlines():
        log("  " + line)
    with open(REPORT, encoding="utf-8") as f:
        return json.load(f)


def has_real_change(report: dict) -> tuple[bool, list[dict]]:
    """判断是否有需要处理的真实变化。返回 (是否有, 有问题的年份明细)。"""
    problems = []
    for row in report.get("years", []):
        if row.get("status") == "mismatch":
            problems.append(row)
        elif row.get("status") in ("parse_failed",):
            problems.append(row)  # 解析失败按需要核源处理（多半会放弃）
    nxt = report.get("next_year", {})
    if nxt.get("urgent"):
        problems.append({"year": nxt["year"], "kind": "next_year_new",
                         "action": nxt.get("action")})
    return bool(problems), problems


# ---------------------------------------------------------------- 核源闸门

def source_ok(row: dict) -> bool:
    """严格闸门：只有官方原文明确、解析无歧义、差异模式合理才放行。"""
    # 解析警告非空 → 放弃（这是 parse_notice 自己的保守检查）
    if row.get("parse_warnings"):
        log(f"  ✗ {row.get('year')} 解析有警告：{row['parse_warnings']} → 放弃")
        return False
    # parse_failed → 放弃
    if row.get("status") == "parse_failed":
        log(f"  ✗ {row.get('year')} 公告解析失败 → 放弃")
        return False
    # 新增次年：必须 sections 完整（7 个法定节日）
    if row.get("kind") == "next_year_new":
        log(f"  · 次年 {row['year']} 公告已发布，走 sections 校验")
        return True
    # mismatch：必须有官方 URL，且差异项目集中在放假/补班（不是解析垃圾）
    if not row.get("notice_url"):
        log(f"  ✗ {row.get('year')} 无官方 URL → 放弃")
        return False
    allowed = {"missing_off", "extra_off", "missing_work", "extra_work"}
    diff_keys = {k for k in allowed if row.get(k)}
    if not diff_keys:
        log(f"  ✗ {row.get('year')} status=mismatch 但无具体差异项 → 放弃")
        return False
    return True


def plausible(sections: list[dict], year: int) -> bool:
    """差异模式合理性：节名认识、天数在常规范围、无跨月异常。"""
    known = {"元旦", "春节", "清明节", "劳动节", "端午节", "中秋节", "国庆节"}
    if not sections:
        log("  ✗ 解析无 sections → 放弃")
        return False
    for s in sections:
        name = s.get("name", "")
        days = len(s.get("off", []))
        if name not in known:
            log(f"  ✗ 未知节名 {name!r} → 放弃")
            return False
        if not (1 <= days <= 10):
            log(f"  ✗ {name} 放假 {days} 天超出常规范围 → 放弃")
            return False
        declared = s.get("declared_days")
        if declared and declared != days:
            log(f"  ✗ {name} 公告写 {declared} 天、解析 {days} 天 → 放弃")
            return False
    return True


# ---------------------------------------------------------------- 改表

def get_sections(report: dict, year: int) -> list[dict] | None:
    for row in report.get("years", []):
        if row.get("year") == year and row.get("sections"):
            return row["sections"]
    return None


def generate_blocks(year: int, sections: list[dict]) -> tuple[str, str] | None:
    """由 sections 生成 (CN_OFFICIAL 年份块, CN_WORKDAYS 年份块) 源码文本。

    放假段：每节首日到末日（sections.off 已排序）。
    说明里的「放假 / 放假调休」按该节有无补班日自动区分，不一律写调休。
    补班日：各节 work 汇总进 CN_WORKDAYS，名称「调休上班（{节名}）」。
    """
    off_lines = [f"    {year}: ["]
    work_rows: list[tuple[dt.date, str]] = []
    for s in sections:
        off = sorted(dt.date.fromisoformat(x) for x in s["off"])
        a, b = off[0], off[-1]
        name = s["name"] + "假期"
        has_work = bool(s.get("work"))
        if a == b:
            span = f"{a.month} 月 {a.day} 日"
        else:
            span = f"{a.month} 月 {a.day} 日至 {b.month} 月 {b.day} 日"
        tail = "放假调休" if has_work else "放假"
        desc = f"{span}{tail}，共 {len(off)} 天。"
        off_lines.append(f"        (D({year}, {a.month}, {a.day}), D({year}, {b.month}, {b.day}), "
                         f'"{name}", "{desc}"),')
        for w in s.get("work", []):
            d = dt.date.fromisoformat(w)
            work_rows.append((d, f"调休上班（{s['name']}）"))
    off_lines.append("    ],")

    work_lines = [f"    {year}: ["]
    for d, label in sorted(work_rows):
        work_lines.append(f'        (D({year}, {d.month}, {d.day}), "{label}"),')
    work_lines.append("    ],")
    return "\n".join(off_lines), "\n".join(work_lines)


def apply_year_blocks(year: int, off_block: str, work_block: str) -> bool:
    """把生成的年份块写入 cn_official.py 的 CN_OFFICIAL 与 CN_WORKDAYS。返回是否改动。"""
    src = open(CN_OFFICIAL, encoding="utf-8").read()
    new = _replace_year_block(src, year, off_block, "CN_OFFICIAL")
    if new is None:
        return False
    new2 = _replace_year_block(new, year, work_block, "CN_WORKDAYS")
    if new2 is None:
        return False
    if new2 == src:
        return False
    shutil.copy2(CN_OFFICIAL, CN_OFFICIAL + ".autobak")
    open(CN_OFFICIAL, "w", encoding="utf-8").write(new2)
    return True


def _replace_year_block(src: str, year: int, block: str, table: str) -> str | None:
    """在指定字典（CN_OFFICIAL / CN_WORKDAYS）中替换或追加年份块。"""
    tpos = src.find(f"{table}:")
    if tpos < 0:
        log(f"  ✗ 找不到 {table} 字典 → 放弃")
        return None
    marker = f"    {year}: ["
    start = src.find(marker, tpos)
    if start >= 0:
        end = src.find("    ],", start)
        if end < 0:
            log(f"  ✗ {table} {year} 块无结束 → 放弃")
            return None
        end += len("    ],")
        return src[:start] + block + src[end:]
    # 新增：插到该字典闭合的 "}" 前
    close = src.find("\n}", tpos)
    if close < 0:
        log(f"  ✗ 找不到 {table} 字典末尾 → 放弃")
        return None
    return src[:close] + "\n" + block + src[close:]


def verify_back_to_match(year: int) -> bool:
    """改表后重跑核对，确认该年回到 match。"""
    r = run(f'"{VENV_PY}" check_official_notice.py --refresh --year {year}', check=False)
    log("  复核输出：" + " | ".join((r.stdout or "").splitlines()[:4]))
    return r.returncode == 0


def rollback() -> None:
    bak = CN_OFFICIAL + ".autobak"
    if os.path.exists(bak):
        shutil.move(bak, CN_OFFICIAL)
        log("  已回滚 cn_official.py")


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只核对，不改动")
    args = ap.parse_args()

    report = audit()
    changed, problems = has_real_change(report)
    if not changed:
        log("✓ 与官方公告一致 / 无新增次年数据，无需更新（静默结束）")
        return 0

    log(f"发现 {len(problems)} 处待处理差异，开始逐条核源：")
    for p in problems:
        log(f"  · 年份 {p.get('year')} 状态 {p.get('status', p.get('kind'))}")

    if args.dry_run:
        log("[dry-run] 只核对，不改动，退出")
        return 0

    # 严格闸门：任一条不过就整批放弃（宁可不上，不可上错）
    for p in problems:
        if not source_ok(p):
            log("✗ 核源闸门未通过，静默放弃本次更新（不打扰用户）")
            return 2

    # 逐年生成并应用。次年新增用刚抓的 sections；mismatch 用报告里的 sections。
    touched = False
    for p in problems:
        year = p["year"]
        sections = get_sections(report, year)
        if not sections or not plausible(sections, year):
            log(f"✗ {year} sections 不合理，静默放弃本次更新")
            rollback()
            return 2
        blocks = generate_blocks(year, sections)
        if not blocks:
            log(f"✗ {year} 生成源表失败，静默放弃")
            rollback()
            return 2
        off_block, work_block = blocks
        log(f"  生成 {year} 源表块：\n{off_block}\n{work_block}")
        if apply_year_blocks(year, off_block, work_block):
            touched = True
            log(f"  ✓ 已写入 {year} 源表（含调休上班日）")
            if not verify_back_to_match(year):
                log(f"✗ {year} 改后核对未回到 match，回滚放弃")
                rollback()
                return 2
        else:
            log(f"  · {year} 源表无实质变化")
    if not touched:
        log("✓ 源表已是最新，无需构建")
        return 0

    # 清理备份（确认成功后）
    bak = CN_OFFICIAL + ".autobak"
    if os.path.exists(bak):
        os.remove(bak)

    # 重建 + 全量校验（复用 pipeline，经过验证的构建链）
    log("开始重建 + 校验（pipeline.py build）...")
    r = run(f'"{VENV_PY}" pipeline.py build', check=False)
    log((r.stdout or "").splitlines()[-1] if r.stdout else "build 无输出")
    if r.returncode != 0:
        log("✗ 构建/校验失败，回滚源表")
        rollback()
        return 1

    log("✓ 自动更新完成：源表已改、数据已重建、全量校验通过")
    log("→ 分发交给调用方：pipeline.py publish-data --yes（或 CI workflow）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
