#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""蚝历流水线 v1.67 —— 把「数据热更新」和「App 发版」彻底拆开。

背景（用户 2026-11-16 定档）
---------------------------
过去每次数据变更都顺手打一个新 APK、走完整六步发版。但 App 的 UpdateManager
本来就支持远程热更新：每 24h 拉 data/manifest.json，比较 all-* / widget-* /
cn-* 的版本号，sha256 + schema 校验通过后原子写入 filesDir，内置 assets 只是兜底。
`watch.py` 里其实早就写着「VER 递增 → 热更新，不重发 APK」。

所以正确的两条路是：

    数据变更（加节日、补调休、改译文、会议定档）
        → pipeline.py build → pipeline.py publish-data --yes
        → 只推 JSON / ICS / 首页统计，**不动 apk.json、不动 download/、
          不升 versionCode、不传蒲公英、不装真机**
        → 老用户 24h 内自动收到新数据（或点「检查更新」立即生效）

    代码变更（UI、排序、解析逻辑、内置地址）
        → 升 versionCode → 编译 → 完整六步发版（pipeline.py release-app 只给清单）

「只在数据变化时发布」的实现：build 前后对所有发布产物取 sha256 快照，
差集就是本次需要同步 / purge 的路径。配合 build_state 的幂等写入，源表没变时
差集为空，脚本直接打印「无数据变化，无需发布」并退出——这正是 holiday-cn
「CI 每天跑但只有数据变了才发 release」的等价机制。

用法
----
    ../.venv/bin/python pipeline.py check                    # 只读体检
    ../.venv/bin/python pipeline.py build                   # 构建 + 校验 + 生成更新清单
    ../.venv/bin/python pipeline.py publish-data            # 预演（不碰线上）
    ../.venv/bin/python pipeline.py publish-data --yes      # 真正推数据热更新
    ../.venv/bin/python pipeline.py release-app             # 打印 App 发版清单
    ../.venv/bin/python pipeline.py status                  # 当前版本 / 清单 / 待办

本脚本**不会**自动改 cn_official.py：官方公告差异由 check_official_notice.py
报出来，仍需人工核源后编辑，这是 taxonomy.py C1 / A 级渠道的红线。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MIRROR = os.path.join(ROOT, "haoli-site")
APK_ROOT = os.path.join(ROOT, "haoli-apk")
VENV_PY = os.path.join(ROOT, ".venv", "bin", "python")
PLAN = os.path.join(HERE, "data", "update-plan.json")

MIRROR_REPO = "bohub8888/haoli-site"
CDN_BASE = f"https://cdn.jsdelivr.net/gh/{MIRROR_REPO}@main"
SITE_BASE = "https://49.233.147.15"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519_haoli")
SSH_TARGET = "root@49.233.147.15"
REMOTE_DIR = "/var/www/haoli"

# 参与「发布快照」的路径（相对站点根）。构建期本地状态与调研报告刻意排除。
SNAPSHOT_GLOBS = (
    "data/*.json", "2026/*.json", "2027/*.json", "stats.json",
    "index.html", "robots.txt", "sitemap.xml",
    "ics/*.ics", "2026/ics/*.ics", "2027/ics/*.ics",
)
LOCAL_ONLY = {
    "data/build-state.json", "data/official-notice-report.json",
    "data/official-notices/2027.json",
}


# ---------------------------------------------------------------- 工具

def run(cmd, cwd=HERE, check=True, capture=False):
    print("  $ " + cmd if not capture else "  $ (silent) " + cmd[:90])
    r = subprocess.run(cmd, shell=True, cwd=cwd, text=True,
                       capture_output=capture, timeout=900)
    if check and r.returncode != 0:
        print((r.stdout or "")[-2000:] if capture else "")
        print((r.stderr or "")[-2000:] if capture else "")
        raise SystemExit(f"命令失败（{r.returncode}）：{cmd[:120]}")
    return r


def sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def snapshot() -> dict[str, str]:
    import glob
    out = {}
    for pat in SNAPSHOT_GLOBS:
        for p in glob.glob(os.path.join(HERE, pat)):
            rel = os.path.relpath(p, HERE).replace(os.sep, "/")
            if rel in LOCAL_ONLY or not os.path.isfile(p):
                continue
            out[rel] = sha(p)
    return out


def load_plan() -> dict:
    if not os.path.exists(PLAN):
        return {}
    with open(PLAN, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 命令：check

def cmd_check(offline=False) -> int:
    print("=== 1/3 官方公告 diff 校验 ===")
    r = run(f'"{VENV_PY}" check_official_notice.py' + (" --offline" if offline else ""),
            check=False)
    notice_ok = r.returncode == 0

    print("\n=== 2/3 观察名单到期项（会议 / 展会） ===")
    run(f'"{VENV_PY}" watch.py --due', check=False)

    print("\n=== 3/3 四出口一致性 ===")
    r2 = run(f'"{VENV_PY}" check_consistency.py', check=False, capture=True)
    print((r2.stdout or "").strip().splitlines()[-1] if r2.stdout else "")
    ok = notice_ok and r2.returncode == 0
    print("\n" + ("✓ 体检通过" if ok else "✗ 体检有问题，见上方输出"))
    return 0 if ok else 1


# ---------------------------------------------------------------- 命令：build

def cmd_build() -> int:
    print("=== 构建前快照 ===")
    before = snapshot()
    print(f"  {len(before)} 个发布文件")

    print("\n=== 1/4 重跑数据构建（版本自动推导 + 幂等写入） ===")
    run(f'"{VENV_PY}" build.py', capture=True)

    print("\n=== 2/4 同步 APK 内置兜底数据 + manifest ===")
    # gen_apk_data.py 以项目根为基准读写，必须在 ROOT 下执行。
    run(f'"{VENV_PY}" haoli-apk/tools/gen_apk_data.py', cwd=ROOT, capture=True)

    print("\n=== 3/4 数据校验 ===")
    for script in ("check_consistency.py", "check_key_dates.py", "check_translations.py",
                   "test_official_notice.py", "test_build_state.py"):
        if script.startswith("test_"):
            r = run(f'"{VENV_PY}" -m unittest {script[:-3]}', check=False, capture=True)
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-2:]
            print("   ", " / ".join(tail))
            if r.returncode != 0:
                raise SystemExit(f"单测失败：{script}")
        else:
            r = run(f'"{VENV_PY}" {script}', check=False, capture=True)
            print("   ", (r.stdout or "").strip().splitlines()[-1] if r.stdout else "无输出")
            if r.returncode != 0:
                raise SystemExit(f"校验失败：{script}")

    print("\n=== 4/4 生成更新清单 ===")
    after = snapshot()
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    # index.html 两仓基线注释不同，不能整份覆盖；单独标为人工处理
    auto = [p for p in changed if p != "index.html"]
    manual = ["index.html"] if "index.html" in changed else []
    plan = {
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "kind": "data-hot-update",
        "app_version_changed": False,
        "changed": changed,
        "auto_sync": auto,
        "manual": manual,
        "purge": [p for p in changed if p != "index.html"] + (["index.html"] if manual else []),
        "server": auto,
        "versions": json.load(open(os.path.join(HERE, "data", "build-state.json"),
                                   encoding="utf-8")).get("versions", {}),
        "note": ("本次不动 apk.json / download/ / versionCode / 蒲公英；"
                 "老用户由 App UpdateManager 热更新获取新数据。"),
    }
    with open(PLAN, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"  变化 {len(changed)} 个文件（自动 {len(auto)} / 人工 {len(manual)}）")
    for p in changed[:25]:
        print("   · " + p)
    if len(changed) > 25:
        print(f"   … 另 {len(changed) - 25} 个")
    if not changed:
        print("\n✓ 无数据变化：不需要发布，也不需要发版（这正是幂等的意义）")
    else:
        print("\n→ 预演：pipeline.py publish-data")
        print("→ 执行：pipeline.py publish-data --yes")
        print("→ 注意：这是数据热更新，**不需要打新 APK**")
    return 0


# ---------------------------------------------------------------- 命令：publish-data

def _cdn_fetch(path: str) -> bytes | None:
    url = f"{CDN_BASE}/{path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HaoliPipeline/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except Exception:
        return None


def _purge_with_verify(path: str, expect: bytes, tries: int = 4) -> bool:
    """purge 后直拉比对 sha，解决 CDN 边缘节点回吐旧缓存（1.66 发版踩过）。"""
    for i in range(tries):
        run(f'curl -s --max-time 30 "https://purge.jsdelivr.net/gh/{MIRROR_REPO}@main/{path}"',
            check=False, capture=True)
        time.sleep(1.0)
        got = _cdn_fetch(path)
        if got == expect:
            print(f"    ✓ {path}" + (f"（第 {i + 1} 次）" if i else ""))
            return True
        print(f"    ↻ {path} 第 {i + 1} 次仍是旧内容，重刷")
    print(f"    ✗ {path} {tries} 次后仍不一致")
    return False


def cmd_publish_data(yes=False) -> int:
    plan = load_plan()
    if not plan:
        raise SystemExit("没有 data/update-plan.json，请先跑 pipeline.py build")
    auto, manual = plan.get("auto_sync", []), plan.get("manual", [])
    if not plan.get("changed"):
        print("✓ 清单为空：无数据变化，无需发布（也不发版）")
        return 0

    if manual:
        print("⚠ 需要人工处理（两仓首页注释基线不同，禁止整份覆盖）：")
        for p in manual:
            print(f"   · {p}：把统计数字等变化精准替换到 haoli-site/{p}")
        print("   处理完再跑 publish-data；未处理前不会自动同步首页。\n")

    steps = [
        f"复制 {len(auto)} 个文件到镜像仓 haoli-site",
        "镜像仓 git commit + push_gitapi.py 推送 GitHub",
        f"purge + 校验 {len(plan.get('purge', []))} 条 CDN 路径",
        f"单连接 tar 同步 {len(auto)} 个文件到 {SSH_TARGET}:{REMOTE_DIR}",
        "五方校验：本地 / 官网 / CDN 数据一致，且 apk.json 与 download/ 未变",
    ]
    print("=== 数据热更新（不发 APK）将执行 ===")
    for i, s in enumerate(steps, 1):
        print(f"  {i}. {s}")
    if not yes:
        print("\n[预演] 未加 --yes，什么都没做。加 --yes 才会真正推线上。")
        return 0

    # 1) 同步到镜像仓
    print("\n=== 1/5 同步镜像仓 ===")
    for rel in auto:
        src, dst = os.path.join(HERE, rel), os.path.join(MIRROR, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    print(f"  复制 {len(auto)} 个文件")

    # 2) 提交推送
    print("\n=== 2/5 提交并推送 GitHub 镜像仓 ===")
    ver = ", ".join(f"{k}={v}" for k, v in sorted(plan.get("versions", {}).items()))
    run('git add -A && git -c user.name="bradpitt" '
        '-c user.email="bradpitt@users.noreply.github.com" '
        f'commit -q -m "data hot update: {ver}（不发 APK）"', cwd=MIRROR, check=False)
    run(f'"{VENV_PY}" ../holiday-calendar-deploy/deploy/push_gitapi.py '
        f'"{MIRROR}" {MIRROR_REPO} "data hot update {ver}"', cwd=MIRROR, check=False)

    # 3) purge + 逐条校验
    print("\n=== 3/5 刷新 CDN（带内容校验重试） ===")
    bad = []
    for rel in plan.get("purge", []):
        p = os.path.join(MIRROR, rel)
        if not os.path.exists(p):
            continue
        if not _purge_with_verify(rel, open(p, "rb").read()):
            bad.append(rel)
    if bad:
        print("⚠ 以下路径 CDN 仍不一致，需人工重刷：" + ", ".join(bad))

    # 4) 服务器单连接 tar
    print("\n=== 4/5 服务器同步 ===")
    if auto:
        quoted = " ".join(rel for rel in auto)
        run(f'tar cf - {quoted} | ssh -i {SSH_KEY} -o BatchMode=yes {SSH_TARGET} '
            f'"cd {REMOTE_DIR} && tar xf - && chown -R root:root data ics 2026 2027 '
            'index.html stats.json 2>/dev/null; echo SERVER_OK"', cwd=MIRROR, check=False)

    # 5) 校验（数据侧，且断言 APK 没被动过）
    print("\n=== 5/5 校验 ===")
    ok = True
    for rel in auto[:12]:
        p = os.path.join(HERE, rel)
        if not os.path.exists(p):
            continue
        want = sha(p)
        official = subprocess.run(
            ["curl", "-skL", "--max-time", "30", f"{SITE_BASE}/{rel}"],
            capture_output=True).stdout
        hit = hashlib.sha256(official).hexdigest() == want
        print(f"  {'✓' if hit else '✗'} 官网 {rel}")
        ok &= bool(hit)
    # apk.json 必须原样：证明这次真的没发版
    for base in (SITE_BASE, CDN_BASE):
        try:
            req = urllib.request.Request(f"{base}/data/apk.json",
                                         headers={"User-Agent": "HaoliPipeline/1.0"})
            d = json.load(urllib.request.urlopen(req, timeout=30))
            print(f"  ℹ {base[:28]}… apk.json 仍为 {d.get('version')} / {d.get('versionCode')}"
                  "（未改动，符合数据热更新）")
        except Exception as e:
            print(f"  ! apk.json 读取失败：{e}")
    print("\n" + ("✓ 数据热更新完成，App 用户将在 24h 内自动收到" if ok else "✗ 有校验未通过"))
    return 0 if ok else 1


# ---------------------------------------------------------------- 命令：release-app / status

def cmd_release_app() -> int:
    print("=== App 发版（仅当代码变更时）· 固定六步 ===")
    print("  0. 确认本次确实改了 Kotlin / 布局 / 内置地址 —— 只改数据不要走这里")
    print("  1. build.gradle.kts 升 versionCode / versionName，testDebugUnitTest + assembleRelease")
    print("  2. 两处 data/apk.json + 两仓 index.html 兜底 + download/ 换包、删旧包")
    print("  3. 蒲公英上传（记 build 号）→ 镜像仓 commit + push_gitapi.py")
    print("  4. jsDelivr purge 全部变更路径（逐条拉回校验，边缘节点会回吐旧缓存）")
    print("  5. 服务器单连接 tar 流同步 + 删旧 APK + chown root:root")
    print("  6. 五方 sha256 校验 + 旧包双端 404 + 主仓提交")
    print("\n  数据产物同步范围见 data/update-plan.json；本命令不替你执行，避免误发。")
    return 0


def cmd_status() -> int:
    state_p = os.path.join(HERE, "data", "build-state.json")
    if os.path.exists(state_p):
        with open(state_p, encoding="utf-8") as f:
            st = json.load(f)
        print("数据版本：" + ", ".join(f"{k}={v}" for k, v in sorted(st["versions"].items())))
        print("源表指纹：" + st["source_hash"][:16])
    plan = load_plan()
    if plan:
        print(f"最近清单：{plan['generated'][:19]} · 变化 {len(plan.get('changed', []))} 个文件"
              f" · 类型 {plan.get('kind')}")
    apk = os.path.join(MIRROR, "data", "apk.json")
    if os.path.exists(apk):
        with open(apk, encoding="utf-8") as f:
            d = json.load(f)
        print(f"App 版本：{d.get('version')} / {d.get('versionCode')}（数据更新不应改变它）")
    print("\n体检：pipeline.py check ｜ 构建：pipeline.py build ｜ 发布：publish-data --yes")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="蚝历数据 / 发版流水线")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("check"); p.add_argument("--offline", action="store_true")
    sub.add_parser("build")
    p = sub.add_parser("publish-data"); p.add_argument("--yes", action="store_true")
    sub.add_parser("release-app")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    handlers = {
        "check": lambda: cmd_check(a.offline),
        "build": cmd_build,
        "publish-data": lambda: cmd_publish_data(a.yes),
        "release-app": cmd_release_app,
        "status": cmd_status,
    }
    fn = handlers.get(a.cmd)
    if fn is None:
        ap.print_help()
        return 1
    return fn()


if __name__ == "__main__":
    raise SystemExit(main())
