#!/usr/bin/env python3
"""用 GitHub Contents API 发布站点（git push 被代理 502 时的兜底）。

用法：python3 deploy/gh_push.py <本地站点目录> <提交说明>
会按目录里的文件增量比对远端：新增/修改走 PUT，本地已删的走 DELETE。
"""
import base64
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = "bohub8888/haoli-site"
TOKEN = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
API = f"https://api.github.com/repos/{REPO}"


def call(method: str, path: str, body=None):
    url = f"{API}/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def remote_map():
    """远端全部文件：path -> sha（递归）。空仓库时返回 {}。"""
    try:
        tree = call("GET", "git/trees/main?recursive=1")
    except Exception:
        return {}
    return {
        item["path"]: item["sha"]
        for item in tree.get("tree", [])
        if item["type"] == "blob"
    }


def blob_sha(data: bytes) -> str:
    """git blob 的 sha1，和远端 tree 里的 sha 可直接比对，省掉重复上传。"""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def main():
    root = Path(sys.argv[1]).resolve()
    message = sys.argv[2] if len(sys.argv) > 2 else "deploy"
    remote = remote_map()
    local = {
        str(p.relative_to(root)): p
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }

    changed = 0
    for path, p in sorted(local.items()):
        data = p.read_bytes()
        if remote.get(path) == blob_sha(data):
            continue
        body = {
            "message": f"{message} · {path}",
            "content": base64.b64encode(data).decode(),
            "branch": "main",
        }
        if path in remote:
            body["sha"] = remote[path]
        call("PUT", f"contents/{path}", body)
        print(("改 " if path in remote else "增 ") + path)
        changed += 1

    for path in sorted(set(remote) - set(local)):
        call("DELETE", f"contents/{path}", {
            "message": f"{message} · 删 {path}",
            "sha": remote[path],
            "branch": "main",
        })
        print("删 " + path)
        changed += 1

    print(f"完成，{changed} 个文件有变动")


if __name__ == "__main__":
    main()
