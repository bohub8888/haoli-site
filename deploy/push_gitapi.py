#!/usr/bin/env python3
"""git push 的 API 兜底：把本地 HEAD 的整棵 tree 通过 Git Data API 推到远端。

用法：python3 deploy/push_gitapi.py <本地仓库根> <远端 owner/repo> <提交说明>
对比远端 main 的 tree 与本地 HEAD tree（按 git blob sha1），只上传有差异的 blob，
然后一次 create tree + create commit + update ref，远端历史干净（一个提交）。
git push 被本地代理 502 卡死时用这个。
"""
import base64
import json
import subprocess
import sys
import urllib.request

REPO = sys.argv[2] if len(sys.argv) > 2 else "bohub8888/haoli-calendar"
MESSAGE = sys.argv[3] if len(sys.argv) > 3 else "sync via API"
TOKEN = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
API = f"https://api.github.com/repos/{REPO}"


def call(method: str, path: str, body=None, timeout=60):
    url = f"{API}/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def local_tree():
    """本地 HEAD 的全部文件：path -> (mode, git_blob_sha1)。"""
    out = subprocess.check_output(
        ["git", "ls-tree", "-r", "HEAD"], text=True)
    files = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        mode, typ, sha = meta.split()
        if typ == "blob":
            files[path] = (mode, sha)
    return files


def remote_tree():
    try:
        t = call("GET", "git/trees/main?recursive=1")
    except Exception:
        return {}, None
    files = {
        item["path"]: item["sha"]
        for item in t.get("tree", [])
        if item["type"] == "blob"
    }
    return files, t.get("sha")


def blob_content(sha: str) -> bytes:
    return subprocess.check_output(["git", "cat-file", "blob", sha])


def main():
    local = local_tree()
    remote, remote_tree_sha = remote_tree()
    try:
        ref = call("GET", "git/ref/heads/main")
        base_commit = ref["object"]["sha"]
        ref_exists = True
    except Exception:
        # 空仓首推：远端还没有 main 引用，base_commit 留空由 create commit 决定
        base_commit = None
        ref_exists = False
        remote_tree_sha = None
        print("远端 main 不存在，按空仓首推处理")

    # 远端有、本地没有的 → 删除
    deletions = [{"path": p, "sha": None, "mode": "100644"}
                 for p in remote if p not in local]
    # 本地有、远端缺失或 sha 不同 → 上传
    to_upload = {p: local[p] for p in local
                 if p not in remote or remote[p] != local[p][1]}
    print(f"本地 {len(local)} 文件；远端 {len(remote)}；需上传 {len(to_upload)}，删除 {len(deletions)}")

    tree_entries = list(deletions)
    for i, (path, (mode, sha)) in enumerate(sorted(to_upload.items()), 1):
        data = blob_content(sha)
        r = call("POST", "git/blobs", {
            "content": base64.b64encode(data).decode(),
            "encoding": "base64",
        })
        tree_entries.append({"path": path, "mode": mode, "sha": r["sha"]})
        if i % 50 == 0:
            print(f"  已上传 {i}/{len(to_upload)}")

    new_tree = call("POST", "git/trees", {
        "base_tree": remote_tree_sha, "tree": tree_entries})
    commit_body = {"message": MESSAGE, "tree": new_tree["sha"]}
    if base_commit:
        commit_body["parents"] = [base_commit]
    commit = call("POST", "git/commits", commit_body)
    if ref_exists:
        call("PATCH", "git/refs/heads/main", {"sha": commit["sha"], "force": False})
    else:
        call("POST", "git/refs", {"ref": "refs/heads/main", "sha": commit["sha"]})
    print(f"完成：远端 main → {commit['sha'][:10]}（{len(tree_entries)} 项变动）")


if __name__ == "__main__":
    main()
