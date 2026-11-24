#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建状态：数据版本自动推导 + 幂等写入（v1.67 自动化流水线地基）。

两个目的
--------
1. **版本号不再手写**。以前 build.py 里写死 `VER = f"{y}.12"`，1.64 曾因线上手抬到
   `.9` 而代码还是 `.8`，重跑直接把版本降回去，App 缓存挡住新数据。现在版本由
   「数据定义文件的指纹」决定：源表没变就沿用旧版本，源表变了才自动 +1。
   这正是 holiday-cn「只在数据变化时发版」的等价实现。

2. **重跑零差异**。以前每次 build 都把 232 份 ICS 的 DTSTAMP 刷成当前时刻，
   226 份是纯噪声，只能事后逐个 git checkout 回滚。现在写文件前先比「去掉易变字段
   后的内容」：一样就不写，文件字节和 mtime 都不动；只有内容真变了才写新的
   DTSTAMP（订阅端也才需要刷新）。

状态文件 `data/build-state.json` 只记录源表指纹与版本号，是**构建期本地状态，
不发布到线上**，也不进数据更新同步清单。
"""

from __future__ import annotations

import hashlib
import json
import os
import re

# 参与指纹的数据定义文件。刻意不含 build.py：改构建逻辑不该抬数据版本。
SOURCE_FILES = (
    "observances.py", "curated.py", "conferences.py", "taxonomy.py",
    "holiday_i18n.py", "holiday_canon.py", "shortnames.py", "cn_official.py",
)

STATE_FILE = "data/build-state.json"


def source_fingerprint(base: str) -> str:
    h = hashlib.sha256()
    for name in SOURCE_FILES:
        p = os.path.join(base, name)
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        if os.path.exists(p):
            with open(p, "rb") as f:
                h.update(f.read())
        h.update(b"\0")
    return h.hexdigest()


def _ver_tuple(v: str) -> tuple[int, int]:
    parts = (v or "").split(".")
    try:
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return (0, 0)


def _bump(v: str, year: int) -> str:
    major, minor = _ver_tuple(v)
    return f"{year}.{max(minor, 0) + 1}"


def _load_state(base: str) -> dict:
    p = os.path.join(base, STATE_FILE)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _disk_version(base: str, year: int) -> list[str]:
    """从现有产物与清单里收集版本候选，取最大的那个，绝不降版本。"""
    out = []
    p = os.path.join(base, "data", f"all-{year}.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f).get("v", ""))
        except Exception:
            pass
    m = os.path.join(base, "data", "manifest.json")
    if os.path.exists(m):
        try:
            with open(m, encoding="utf-8") as f:
                e = json.load(f).get("files", {}).get(f"all-{year}")
            if e:
                out.append(e.get("v", ""))
        except Exception:
            pass
    return [v for v in out if v]


def resolve_versions(base: str, years: list[int]) -> dict[int, str]:
    """决定本次构建各年份该用的数据版本。"""
    state = _load_state(base)
    fp = source_fingerprint(base)
    known = state.get("versions") or {}
    same_source = bool(state) and state.get("source_hash") == fp

    out: dict[int, str] = {}
    for y in years:
        candidates = _disk_version(base, y)
        k = str(y)
        if known.get(k):
            candidates.append(known[k])
        current = max(candidates, key=_ver_tuple) if candidates else f"{y}.1"

        if not state:
            # 首次引入状态文件：沿用线上既有版本，绝不因为「装了新机制」就抬版本。
            out[y] = current
        elif same_source:
            out[y] = max([current, known.get(k, f"{y}.0")], key=_ver_tuple)
        else:
            # 源表变了：自动 +1。取 max 是为了防止有人手改过线上产物。
            out[y] = _bump(current, y)
    return out


def commit(base: str, versions: dict[int, str]) -> str:
    """构建成功后再落状态。构建失败不会留下「版本已抬」的假象。"""
    data = {
        "source_hash": source_fingerprint(base),
        "versions": {str(y): v for y, v in sorted(versions.items())},
        "policy": "源表指纹变化才自动 +1；改构建逻辑不抬版本；状态文件不发布到线上",
    }
    p = os.path.join(base, STATE_FILE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    _write_stable(p, text, lambda s: s)
    return p


# ---------------------------------------------------------------- 幂等写入

def _write_stable(path: str, text: str, normalize) -> bool:
    """内容（归一化后）没变就不碰文件。返回是否真的写了。"""
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as f:
            old = f.read()
        if normalize(old) == normalize(text):
            return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return True


_ICS_STAMP = re.compile(r"DTSTAMP:[^\r\n]*")


def write_ics_stable(path: str, body: str) -> bool:
    """ICS：DTSTAMP 是易变字段，比较时抹掉；内容没变就整份不写。"""
    return _write_stable(path, body, lambda s: _ICS_STAMP.sub("DTSTAMP:*", s))


def write_json_stable(path: str, obj: dict, volatile: tuple[str, ...] = ()) -> bool:
    """JSON：忽略 generated 之类时间戳字段；其余内容没变就不写。"""
    def norm(s: str) -> str:
        try:
            d = json.loads(s)
            for k in volatile:
                d.pop(k, None)
            return json.dumps(d, ensure_ascii=False, sort_keys=True)
        except Exception:
            return s
    # 与既有 json.dump(..., indent=2) 产物逐字一致，不额外加尾换行，
    # 免得第一次启用幂等机制时把 governance-report.json 刷成「无意义变更」。
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    return _write_stable(path, text, norm)


def write_text_stable(path: str, text: str) -> bool:
    return _write_stable(path, text, lambda s: s)
