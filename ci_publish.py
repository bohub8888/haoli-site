#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 专用分发器：把 haoli-data 的发布产物推到 haoli-site 仓 + 服务器 + CDN。

只在 GitHub Actions 里跑，依赖环境变量：
  GITHUB_TOKEN       CI 自动提供，用于写 haoli-site 仓
  HAOLI_DEPLOY_KEY   受限 SSH 私钥（只能写 /var/www/haoli 数据目录）

输入：data/build-state.json 经 pipeline build 后的更新清单，或显式 --files。
设计红线：
  · 不碰 apk.json / download/ / versionCode —— 数据热更新不发版。
  · index.html 两仓基线不同，不整份覆盖。
  · 任一步失败即非零退出，CI 会留痕但不打扰用户（用户零参与）。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_REPO = "bohub8888/haoli-site"
API = f"https://api.github.com/repos/{SITE_REPO}"
CDN = f"https://cdn.jsdelivr.net/gh/{SITE_REPO}@main"
SSH_TARGET = "root@49.233.147.15"

# 禁止分发的文件（发版相关 / 本地状态）
DENY_PREFIX = ("download/", ".secrets/")
DENY_EXACT = {"apk.json", "index.html"}


def token() -> str:
    # GITHUB_TOKEN 作用域仅限当前仓（haoli-data），无权写 haoli-site（跨仓 → 403）。
    # 跨仓写用 PAT：HAOLI_SITE_TOKEN（对 haoli-site 有 push 权限）。
    t = (os.environ.get("HAOLI_SITE_TOKEN")
         or os.environ.get("GITHUB_TOKEN")
         or os.environ.get("GH_TOKEN"))
    if not t:
        raise SystemExit("缺 HAOLI_SITE_TOKEN / GITHUB_TOKEN")
    return t


def call(method: str, path: str, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}/{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token()}")
    req.add_header("Accept", "application/vnd.github+json")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def safe_files(files: list[str]) -> list[str]:
    out = []
    for f in files:
        f = f.lstrip("./")
        base = os.path.basename(f)
        if f.startswith(DENY_PREFIX) or base in DENY_EXACT:
            continue
        if not os.path.exists(os.path.join(HERE, f)):
            continue
        out.append(f)
    return out


def push_to_site_repo(files: list[str]) -> bool:
    """用 Git Data API 把文件推到 haoli-site 的 main。"""
    # 远端当前 tree
    ref = call("GET", "git/ref/heads/main")
    commit_sha = ref["object"]["sha"]
    commit = call("GET", f"git/commits/{commit_sha}")
    base_tree = commit["tree"]["sha"]
    remote = {}
    for item in call("GET", f"git/trees/{base_tree}?recursive=1")["tree"]:
        if item["type"] == "blob":
            remote[item["path"]] = item["sha"]

    entries = []
    for f in files:
        content = open(os.path.join(HERE, f), "rb").read()
        blob = call("POST", "git/blobs", {
            "content": base64.b64encode(content).decode(), "encoding": "base64"})
        entries.append({"path": f, "mode": "100644", "sha": blob["sha"]})

    if not entries:
        print("  无文件需推 haoli-site")
        return True
    tree = call("POST", "git/trees", {"base_tree": base_tree, "tree": entries})
    msg = f"data auto-update（不发 APK）· {time.strftime('%Y-%m-%d %H:%M')}"
    new_commit = call("POST", "git/commits", {
        "message": msg, "tree": tree["sha"], "parents": [commit_sha]})
    call("PATCH", "git/refs/heads/main", {"sha": new_commit["sha"], "force": False})
    print(f"  ✓ haoli-site 已更新 {len(entries)} 文件 → {new_commit['sha'][:10]}")
    return True


def push_to_server(files: list[str]) -> bool:
    """单连接 tar 流，用受限密钥推服务器同步脚本。"""
    key = os.environ.get("HAOLI_DEPLOY_KEY_FILE")
    if not key:
        print("  ! 无 HAOLI_DEPLOY_KEY_FILE，跳过服务器同步")
        return False
    quoted = " ".join(f for f in files if f)
    # 用 python 组装 tar 子进程，避免 shell 引号问题
    tar = subprocess.Popen(["tar", "cf", "-", "-C", HERE] + files, stdout=subprocess.PIPE)
    ssh = subprocess.run(
        ["ssh", "-i", key, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
         "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15",
         SSH_TARGET],
        stdin=tar.stdout, capture_output=True, text=True, timeout=180)
    tar.stdout.close()
    tar.wait()
    out = (ssh.stdout or "").strip()
    print(f"  服务器返回：{out[-200:]}")
    return ssh.returncode == 0 and "SYNC_OK" in out


def purge_cdn(files: list[str]) -> None:
    """purge jsDelivr 并直拉校验 sha（CDN 边缘可能回吐旧内容）。"""
    bad = []
    for f in files:
        want = open(os.path.join(HERE, f), "rb").read()
        for i in range(4):
            try:
                urllib.request.urlopen(
                    f"https://purge.jsdelivr.net/gh/{SITE_REPO}@main/{f}", timeout=30).read()
            except Exception:
                pass
            time.sleep(1)
            try:
                got = urllib.request.urlopen(f"{CDN}/{f}", timeout=30).read()
                if got == want:
                    break
            except Exception:
                pass
        else:
            bad.append(f)
    if bad:
        print("  ! CDN 未刷新：" + ", ".join(bad[:10]))
    else:
        print(f"  ✓ CDN 已刷新 {len(files)} 路径")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", help="逗号分隔的相对路径；不填则读 data/update-plan.json")
    args = ap.parse_args()

    if args.files:
        files = [x.strip() for x in args.files.split(",") if x.strip()]
    else:
        plan_path = os.path.join(HERE, "data", "update-plan.json")
        if not os.path.exists(plan_path):
            print("无更新清单，无需分发")
            return 0
        plan = json.load(open(plan_path, encoding="utf-8"))
        if not plan.get("changed"):
            print("更新清单为空，无需分发")
            return 0
        files = plan.get("auto_sync", [])

    files = safe_files(files)
    if not files:
        print("无可分发文件")
        return 0
    print(f"待分发 {len(files)} 文件：" + ", ".join(files[:12]))

    ok = True
    print("=== 1/3 推 haoli-site 仓 ===")
    ok &= push_to_site_repo(files)
    print("=== 2/3 推服务器（受限密钥）===")
    ok &= push_to_server(files)
    print("=== 3/3 刷新 CDN ===")
    purge_cdn(files)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
