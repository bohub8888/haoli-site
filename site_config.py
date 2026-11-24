#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""站点地址单一配置点（v1.68，正式域名已生效）。

    HAOLI_SITE_ORIGIN=https://你的域名 ../.venv/bin/python build.py

注意：Android App 内置的数据地址在 haoli-apk 的 SiteConfig.kt，
线上热更新地址的切换需要一次 App 发版（见《数据更新与发版流程》）。
"""

from __future__ import annotations

import os

# 站点根地址（无尾斜杠）。保留旧环境变量 SITE 作为兼容入口。
SITE_ORIGIN = (
    os.environ.get("HAOLI_SITE_ORIGIN")
    or os.environ.get("SITE")
    or "https://oyster111.top"
).rstrip("/")

# GitHub 镜像仓与 jsDelivr CDN：热更新的备用源，与 App 的 BACKUP 对齐。
MIRROR_REPO = os.environ.get("HAOLI_MIRROR_REPO", "bohub8888/haoli-site")
CDN_BASE = f"https://cdn.jsdelivr.net/gh/{MIRROR_REPO}@main"
