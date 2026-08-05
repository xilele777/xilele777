#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「GitHub 统计」SVG 卡片（深色 / 浅色两版）。

展示 7 项个人数据（图标为 GitHub 官方 octicons，与 metrics 卡片一致）：
  提交数 / Pull Requests / Issues / Star 的仓库 / 贡献仓库 / 仓库数 / 存储占用

数据源：
- Search Commits `author:<user>`                  → 提交数
- Search Issues  `author:<user> type:pr`          → PR 数
- Search Issues  `author:<user> type:issue`       → Issue 数
- REST `GET /users/{user}/starred`（分页）          → Star 仓库数
- Search PR 结果聚合（含本人仓库）                   → 贡献仓库数
- REST `GET /users/{user}` 的 public_repos        → 仓库数
- REST `GET /users/{user}/repos` 的 size 求和      → 存储占用（KB→MB）

依赖：仅 Python 标准库。

环境变量（均可选，有默认值）：
  GH_TOKEN     GitHub token（GITHUB_TOKEN 即可，不传则匿名限速）
  INPUT_USER   GitHub 用户名（默认 xilele777）
  OUTPUT_DIR   输出目录（默认 profile）
"""

import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER = os.environ.get("INPUT_USER", "xilele777")
TOKEN = os.environ.get("GH_TOKEN", "")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "profile")

DARK_FILE = "github-stats-dark.svg"
LIGHT_FILE = "github-stats-light.svg"

# 明暗主题与贡献卡片保持一致
THEMES = {
    "dark": {
        "bg": "#0d1117", "panel": "#12171e", "border": "#484f58",
        "accent": "#58a6ff", "text": "#e6edf3", "muted": "#8b949e",
    },
    "light": {
        "bg": "#ffffff", "panel": "#fafbfc", "border": "#e4e9ef",
        "accent": "#0969da", "text": "#1f2328", "muted": "#59636e",
    },
}

# GitHub 官方 octicons（24×24 viewBox 的 path 数据，源自 primer/octicons v19）
OCTICONS = {
    "git-commit": [
        "M16.944 11h4.306a.75.75 0 0 1 0 1.5h-4.306a5.001 5.001 0 0 1-9.888 0H2.75a.75.75 0 0 1 0-1.5h4.306a5.001 5.001 0 0 1 9.888 0Zm-1.444.75a3.5 3.5 0 1 0-7 0 3.5 3.5 0 0 0 7 0Z",
    ],
    "git-pull-request": [
        "M16 19.25a3.25 3.25 0 1 1 6.5 0 3.25 3.25 0 0 1-6.5 0Zm-14.5 0a3.25 3.25 0 1 1 6.5 0 3.25 3.25 0 0 1-6.5 0Zm0-14.5a3.25 3.25 0 1 1 6.5 0 3.25 3.25 0 0 1-6.5 0ZM4.75 3a1.75 1.75 0 1 0 .001 3.501A1.75 1.75 0 0 0 4.75 3Zm0 14.5a1.75 1.75 0 1 0 .001 3.501A1.75 1.75 0 0 0 4.75 17.5Zm14.5 0a1.75 1.75 0 1 0 .001 3.501 1.75 1.75 0 0 0-.001-3.501Z",
        "M13.405 1.72a.75.75 0 0 1 0 1.06L12.185 4h4.065A3.75 3.75 0 0 1 20 7.75v8.75a.75.75 0 0 1-1.5 0V7.75a2.25 2.25 0 0 0-2.25-2.25h-4.064l1.22 1.22a.75.75 0 0 1-1.061 1.06l-2.5-2.5a.75.75 0 0 1 0-1.06l2.5-2.5a.75.75 0 0 1 1.06 0ZM4.75 7.25A.75.75 0 0 1 5.5 8v8A.75.75 0 0 1 4 16V8a.75.75 0 0 1 .75-.75Z",
    ],
    "issue-opened": [
        "M12 1c6.075 0 11 4.925 11 11s-4.925 11-11 11S1 18.075 1 12 5.925 1 12 1ZM2.5 12a9.5 9.5 0 0 0 9.5 9.5 9.5 9.5 0 0 0 9.5-9.5A9.5 9.5 0 0 0 12 2.5 9.5 9.5 0 0 0 2.5 12Zm9.5 2a2 2 0 1 1-.001-3.999A2 2 0 0 1 12 14Z",
    ],
    "star": [
        "M12 .25a.75.75 0 0 1 .673.418l3.058 6.197 6.839.994a.75.75 0 0 1 .415 1.279l-4.948 4.823 1.168 6.811a.751.751 0 0 1-1.088.791L12 18.347l-6.117 3.216a.75.75 0 0 1-1.088-.79l1.168-6.812-4.948-4.823a.75.75 0 0 1 .416-1.28l6.838-.993L11.328.668A.75.75 0 0 1 12 .25Zm0 2.445L9.44 7.882a.75.75 0 0 1-.565.41l-5.725.832 4.143 4.038a.748.748 0 0 1 .215.664l-.978 5.702 5.121-2.692a.75.75 0 0 1 .698 0l5.12 2.692-.977-5.702a.748.748 0 0 1 .215-.664l4.143-4.038-5.725-.831a.75.75 0 0 1-.565-.41L12 2.694Z",
    ],
    "repo-forked": [
        "M8.75 19.25a3.25 3.25 0 1 1 6.5 0 3.25 3.25 0 0 1-6.5 0ZM15 4.75a3.25 3.25 0 1 1 6.5 0 3.25 3.25 0 0 1-6.5 0Zm-12.5 0a3.25 3.25 0 1 1 6.5 0 3.25 3.25 0 0 1-6.5 0ZM5.75 6.5a1.75 1.75 0 1 0-.001-3.501A1.75 1.75 0 0 0 5.75 6.5ZM12 21a1.75 1.75 0 1 0-.001-3.501A1.75 1.75 0 0 0 12 21Zm6.25-14.5a1.75 1.75 0 1 0-.001-3.501A1.75 1.75 0 0 0 18.25 6.5Z",
        "M6.5 7.75v1A2.25 2.25 0 0 0 8.75 11h6.5a2.25 2.25 0 0 0 2.25-2.25v-1H19v1a3.75 3.75 0 0 1-3.75 3.75h-6.5A3.75 3.75 0 0 1 5 8.75v-1Z",
        "M11.25 16.25v-5h1.5v5h-1.5Z",
    ],
    "repo": [
        "M3 2.75A2.75 2.75 0 0 1 5.75 0h14.5a.75.75 0 0 1 .75.75v20.5a.75.75 0 0 1-.75.75h-6a.75.75 0 0 1 0-1.5h5.25v-4H6A1.5 1.5 0 0 0 4.5 18v.75c0 .716.43 1.334 1.05 1.605a.75.75 0 0 1-.6 1.374A3.251 3.251 0 0 1 3 18.75ZM19.5 1.5H5.75c-.69 0-1.25.56-1.25 1.25v12.651A2.989 2.989 0 0 1 6 15h13.5Z",
        "M7 18.25a.25.25 0 0 1 .25-.25h5a.25.25 0 0 1 .25.25v5.01a.25.25 0 0 1-.397.201l-2.206-1.604a.25.25 0 0 0-.294 0L7.397 23.46a.25.25 0 0 1-.397-.2v-5.01Z",
    ],
    "database": [
        "M12 1.25c2.487 0 4.773.402 6.466 1.079.844.337 1.577.758 2.112 1.264.536.507.922 1.151.922 1.907v12.987l-.026.013h.026c0 .756-.386 1.4-.922 1.907-.535.506-1.268.927-2.112 1.264-1.693.677-3.979 1.079-6.466 1.079s-4.774-.402-6.466-1.079c-.844-.337-1.577-.758-2.112-1.264C2.886 19.9 2.5 19.256 2.5 18.5h.026l-.026-.013V5.5c0-.756.386-1.4.922-1.907.535-.506 1.268-.927 2.112-1.264C7.226 1.652 9.513 1.25 12 1.25ZM4 14.371v4.116l-.013.013H4c0 .211.103.487.453.817.351.332.898.666 1.638.962 1.475.589 3.564.971 5.909.971 2.345 0 4.434-.381 5.909-.971.739-.296 1.288-.63 1.638-.962.349-.33.453-.607.453-.817h.013L20 18.487v-4.116a7.85 7.85 0 0 1-1.534.8c-1.693.677-3.979 1.079-6.466 1.079s-4.774-.402-6.466-1.079a7.843 7.843 0 0 1-1.534-.8ZM20 12V7.871a7.85 7.85 0 0 1-1.534.8C16.773 9.348 14.487 9.75 12 9.75s-4.774-.402-6.466-1.079A7.85 7.85 0 0 1 4 7.871V12c0 .21.104.487.453.817.35.332.899.666 1.638.961 1.475.59 3.564.972 5.909.972 2.345 0 4.434-.382 5.909-.972.74-.295 1.287-.629 1.638-.96.35-.33.453-.607.453-.818ZM4 5.5c0 .211.103.487.453.817.351.332.898.666 1.638.962 1.475.589 3.564.971 5.909.971 2.345 0 4.434-.381 5.909-.971.739-.296 1.288-.63 1.638-.962.349-.33.453-.607.453-.817 0-.211-.103-.487-.453-.817-.351-.332-.898-.666-1.638-.962-1.475-.589-3.564-.971-5.909-.971-2.345 0-4.434.381-5.909.971-.739.296-1.288.63-1.638.962C4.104 5.013 4 5.29 4 5.5Z",
    ],
}

API = "https://api.github.com"
SEARCH_ISSUES = API + "/search/issues"
SEARCH_COMMITS = API + "/search/commits"
MAX_ATTEMPTS = 4
PER_PAGE = 100


def _request(url):
    """发起 API 请求，429/403 时退避重试，返回解析后的 JSON。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "stats-card-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < MAX_ATTEMPTS - 1:
                wait = 60 * (attempt + 1)
                print(f"[warn] HTTP {e.code}，{wait}s 后重试", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("API 请求多次重试仍失败")


def _paginate(url):
    """按 per_page=100 分页拉完，返回全部 items。"""
    items, page = [], 1
    while True:
        data = _request(f"{url}&per_page={PER_PAGE}&page={page}")
        batch = data.get("items") if isinstance(data, dict) else data
        items.extend(batch or [])
        print(f"  第 {page} 页：{len(batch or [])} 条（累计 {len(items)}）")
        if not batch or len(batch) < PER_PAGE:
            break
        page += 1
    return items


def collect():
    """拉取全部 7 项数据。"""
    print(f"获取用户 {USER} 的统计…")

    q = urllib.parse.urlencode({"q": f"author:{USER}", "per_page": 1})
    commits = int(_request(SEARCH_COMMITS + "?" + q)["total_count"])
    print(f"  提交数：{commits}")

    q = urllib.parse.urlencode({"q": f"author:{USER} type:pr", "per_page": 1})
    pr_total = int(_request(SEARCH_ISSUES + "?" + q)["total_count"])
    print(f"  PR 数：{pr_total}")

    q = urllib.parse.urlencode({"q": f"author:{USER} type:issue", "per_page": 1})
    issue_total = int(_request(SEARCH_ISSUES + "?" + q)["total_count"])
    print(f"  Issue 数：{issue_total}")

    starred = len(_paginate(f"{API}/users/{USER}/starred?"))
    print(f"  Star 仓库数：{starred}")

    # 贡献仓库：去重本人 PR 所在仓库（含自己的仓库）
    q = urllib.parse.urlencode({"q": f"author:{USER} type:pr"})
    pr_items = _paginate(SEARCH_ISSUES + "?" + q)
    repos = set()
    for item in pr_items:
        parts = (item.get("repository_url") or "").rstrip("/").split("/")
        repos.add("/".join(parts[-2:]))
    contributed = len(repos)
    print(f"  贡献仓库数：{contributed}（去重后的全部仓库）")

    user_data = _request(f"{API}/users/{USER}")
    repo_count = int(user_data.get("public_repos", 0))
    print(f"  仓库数：{repo_count}")

    repo_items = _paginate(f"{API}/users/{USER}/repos?sort=updated")
    size_kb = sum((r.get("size") or 0) for r in repo_items)
    size_mb = size_kb / 1024.0
    print(f"  存储占用：{size_mb:.1f} MB（{size_kb} KB）")

    return commits, pr_total, issue_total, starred, contributed, repo_count, size_mb


def format_size(mb):
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"


# ===== SVG 生成 =====

WIDTH = 720
PAD = 24
FONT = "'Segoe UI', -apple-system, 'Helvetica Neue', Arial, sans-serif"
ICON_SIZE = 16
GRID_COLS = 7      # 一行排下全部 7 项
GRID_GAP = 8
VALUE_FS = 17      # 数值字号
LABEL_FS = 12      # 说明字号


def esc(s):
    return html.escape(str(s), quote=True)


def est_width(s, font_size):
    """文本宽度估算：全角≈1em，半角≈0.62em。"""
    return sum(1.0 if ord(ch) > 0x2E80 else 0.62 for ch in s) * font_size


def build_svg(theme, stats):
    title_y = 34
    divider_y = 44
    top = 56
    value_y = top + 18   # 图标 + 数值 所在行基线
    label_y = top + 40   # 说明文字基线
    footer_y = label_y + 22
    height = footer_y + 24

    cell_w = (WIDTH - 2 * PAD - (GRID_COLS - 1) * GRID_GAP) / GRID_COLS

    L = []
    a = L.append

    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
      f'viewBox="0 0 {WIDTH} {height}" role="img" aria-label="GitHub 统计">')
    a(f'<rect width="{WIDTH}" height="{height}" rx="16" fill="{theme["bg"]}" '
      f'stroke="{theme["border"]}" stroke-width="1.5"/>')

    a(f'<text x="{PAD}" y="{title_y}" font-family="{FONT}" font-size="14" '
      f'fill="{theme["muted"]}">GitHub 统计</text>')
    a(f'<line x1="{PAD}" y1="{divider_y}" x2="{WIDTH - PAD}" y2="{divider_y}" '
      f'stroke="{theme["border"]}" stroke-width="1"/>')

    scale = ICON_SIZE / 24.0
    for idx, (icon, value, label) in enumerate(stats):
        cx = PAD + idx * (cell_w + GRID_GAP) + cell_w / 2

        # 行 1：图标 + 数值 成组水平居中，互不重叠
        group_w = ICON_SIZE + 4 + est_width(value, VALUE_FS)
        gx = cx - group_w / 2
        a(f'<g transform="translate({gx:.1f} {top + 4:.1f}) scale({scale:.4f})">')
        for d in OCTICONS[icon]:
            a(f'<path d="{d}" fill="{theme["muted"]}"/>')
        a("</g>")
        a(f'<text x="{gx + ICON_SIZE + 4:.1f}" y="{value_y}" font-family="{FONT}" '
          f'font-size="{VALUE_FS}" font-weight="700" fill="{theme["text"]}">{esc(value)}</text>')

        # 行 2：说明文字，格内居中
        a(f'<text x="{cx:.1f}" y="{label_y}" text-anchor="middle" font-family="{FONT}" '
          f'font-size="{LABEL_FS}" fill="{theme["muted"]}">{esc(label)}</text>')

    a(f'<text x="{WIDTH / 2}" y="{footer_y}" text-anchor="middle" font-family="{FONT}" '
      f'font-size="12" fill="{theme["muted"]}">Auto-updated by GitHub Actions · {esc(USER)}</text>')

    a("</svg>")
    return "\n".join(L)


def main():
    commits, pr_total, issue_total, starred, contributed, repo_count, size_mb = collect()
    stats = [
        ("git-commit", str(commits), "提交数"),
        ("git-pull-request", str(pr_total), "Pull Requests"),
        ("issue-opened", str(issue_total), "Issues"),
        ("star", str(starred), "Star 的仓库"),
        ("repo-forked", str(contributed), "贡献仓库"),
        ("repo", str(repo_count), "仓库数"),
        ("database", format_size(size_mb), "存储占用"),
    ]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for filename, theme in ((DARK_FILE, THEMES["dark"]), (LIGHT_FILE, THEMES["light"])):
        path = os.path.join(OUTPUT_DIR, filename)
        svg = build_svg(theme, stats)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"已写入 {path}")


if __name__ == "__main__":
    main()
