#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「开源贡献」SVG 卡片（深色 / 浅色两版）。

卡片内容：
- 顶部统计：总 PR / 已合并 / 合并率 / 进行中（含所有 PR，包括自己仓库的）
- 贡献仓库网格：对他人开源项目的贡献，每格 = 头像 + 仓库名（不含 owner）+ 采纳状态点
  自动排除 owner 为本人自己的仓库

数据源：
- GitHub Search API  `author:<user> type:pr`
- REST `GET /repos/{owner}/{repo}`  拿 owner 头像地址

依赖：仅 Python 标准库。

环境变量（均可选，有默认值）：
  GH_TOKEN     GitHub token（GITHUB_TOKEN 即可，不传则匿名限速）
  INPUT_USER   GitHub 用户名（默认 xilele777）
  OUTPUT_DIR   输出目录（默认 profile）
  MAX_REPOS    贡献仓库展示条数（默认 8）
"""

import base64
import html
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER = os.environ.get("INPUT_USER", "xilele777")
TOKEN = os.environ.get("GH_TOKEN", "")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "profile")
MAX_REPOS = int(os.environ.get("MAX_REPOS", "8"))

DARK_FILE = "pr-contributions-dark.svg"
LIGHT_FILE = "pr-contributions-light.svg"

# 状态语义遵循 GitHub：进行中=绿、已合并=紫、关闭未合并=红
THEMES = {
    "dark": {
        "bg": "#0d1117", "panel": "#12171e", "border": "#30363d",
        "accent": "#58a6ff", "open": "#3fb950",
        "merged": "#a371f7", "closed": "#f85149",
        "text": "#e6edf3", "muted": "#8b949e",
    },
    "light": {
        "bg": "#ffffff", "panel": "#fafbfc", "border": "#d1d9e0",
        "accent": "#0969da", "open": "#1a7f37",
        "merged": "#8250df", "closed": "#cf222e",
        "text": "#1f2328", "muted": "#59636e",
    },
}

# 首字母 fallback 头像色板（GitHub 风格）
AVATAR_COLORS = ["#8250df", "#0969da", "#1a7f37", "#9a6700",
                 "#cf222e", "#bf3989", "#0550ae", "#0a3069"]

STATUS_LABEL = {"merged": "已合并", "open": "进行中", "closed": "未合并"}

SEARCH_URL = "https://api.github.com/search/issues"
PER_PAGE = 100
MAX_TOTAL = 1000  # Search API 对单个查询的硬上限
MAX_ATTEMPTS = 4

_avatar_cache = {}


def _request(url):
    """发起 API 请求，429/403 时退避重试，返回解析后的 JSON。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "pr-card-generator",
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


def collect_prs():
    """分页拉取该用户的所有 PR，返回 (prs, total, incomplete)。"""
    prs, total, incomplete, page = [], None, False, 1
    while True:
        query = urllib.parse.urlencode({
            "q": f"author:{USER} type:pr",
            "per_page": PER_PAGE, "page": page,
            "sort": "created", "order": "desc",
        })
        data = _request(SEARCH_URL + "?" + query)
        total = int(data["total_count"])
        incomplete = incomplete or bool(data.get("incomplete_results"))
        items = data.get("items") or []
        prs.extend(items)
        print(f"  第 {page} 页：{len(items)} 条（累计 {len(prs)}/{total}）")
        if not items or len(prs) >= total or page * PER_PAGE >= MAX_TOTAL:
            break
        page += 1
    return prs, total, incomplete


def classify(pr):
    """三态判定：merged（已合并）/ open（进行中）/ closed（关闭未合并）。"""
    if (pr.get("pull_request") or {}).get("merged_at"):
        return "merged"
    if pr.get("state") == "open":
        return "open"
    return "closed"


def repo_name(pr):
    """从 repository_url 解析 owner/repo。"""
    parts = (pr.get("repository_url") or "").rstrip("/").split("/")
    return "/".join(parts[-2:])


def aggregate_repos(prs):
    """按仓库聚合 PR，并对每个仓库补充采纳状态与 owner 头像地址。"""
    repos = {}
    for pr in prs:
        key = repo_name(pr)
        if key not in repos:
            owner, _, rname = key.partition("/")
            repos[key] = {"owner": owner, "repo": rname, "prs": []}
        repos[key]["prs"].append(pr)

    for key, info in repos.items():
        # 仓库详情：owner 头像地址
        try:
            data = _request(f"https://api.github.com/repos/{key}")
            info["avatar_url"] = (data.get("owner") or {}).get("avatar_url", "")
        except Exception as e:
            print(f"[warn] 获取仓库 {key} 详情失败：{e}", file=sys.stderr)
            info["avatar_url"] = ""
        # 采纳状态聚合：有进行中 → 进行中；全部已合并 → 已合并；否则 → 未合并
        statuses = [classify(p) for p in info["prs"]]
        if "open" in statuses:
            info["status"] = "open"
        elif all(s == "merged" for s in statuses):
            info["status"] = "merged"
        else:
            info["status"] = "closed"
        # 最新贡献时间，用于排序；并取该仓库最新一条 PR 的标题作为注释
        latest_pr = max(info["prs"], key=lambda p: p.get("created_at") or "")
        info["latest"] = latest_pr.get("created_at") or ""
        info["title"] = latest_pr.get("title") or ""
        print(f"  {key}：{len(info['prs'])} PR，{info['status']}")
    return repos


def avatar_data_uri(owner, url):
    """下载 owner 头像并转 base64 data URI（按 owner 缓存）。"""
    if owner in _avatar_cache:
        return _avatar_cache[owner]
    if not url:
        _avatar_cache[owner] = None
        return None
    try:
        fetch_url = url + ("&" if "?" in url else "?") + "size=64"
        req = urllib.request.Request(
            fetch_url, headers={"User-Agent": "pr-card-generator"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            blob = resp.read()
            mime = resp.headers.get("Content-Type", "image/png") or "image/png"
        uri = f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"
        _avatar_cache[owner] = uri
        print(f"  头像 {owner} 已内嵌（{len(blob)} 字节）")
        return uri
    except Exception as e:
        print(f"[warn] 头像 {owner} 下载失败，改用首字母：{e}", file=sys.stderr)
        _avatar_cache[owner] = None
        return None


# ===== SVG 生成 =====

WIDTH = 640
PAD = 24
FONT = "'Segoe UI', -apple-system, 'Helvetica Neue', Arial, sans-serif"

COLS = 3          # 网格列数
GAP = 12          # 方块间水平间距
CELL_H = 48       # 方块高度（两行：仓库名 + 注释）
ROW_PITCH = 56    # 行距（方块高 + 垂直间距）


def esc(s):
    return html.escape(str(s), quote=True)


def est_width(s, font_size):
    """文本宽度估算：全角≈1em，半角≈0.62em（用于截断判断）。"""
    return sum(1.0 if ord(ch) > 0x2E80 else 0.62 for ch in s) * font_size


def truncate(s, max_width, font_size):
    """超宽按宽度截断，尾部补省略号。"""
    if est_width(s, font_size) <= max_width:
        return s
    ellipsis = "…"
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if est_width(s[:mid], font_size) + est_width(ellipsis, font_size) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo] + ellipsis


def build_svg(theme, total, merged, opened, merge_rate, repos, incomplete):
    n = min(MAX_REPOS, len(repos))
    cell_w = (WIDTH - 2 * PAD - (COLS - 1) * GAP) / COLS
    list_top = 122
    rows = max(1, math.ceil(n / COLS)) if n else 1
    footer_y = list_top + rows * ROW_PITCH + 12
    height = footer_y + 22

    rate_text = f"{merge_rate * 100:.1f}%" if total else "0%"
    stats = [
        ("已提交 PR", str(total)),
        ("已合并", str(merged)),
        ("合并率", rate_text),
        ("进行中", str(opened)),
    ]

    L = []
    a = L.append

    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
      f'viewBox="0 0 {WIDTH} {height}" role="img" aria-label="开源贡献统计">')
    a(f'<rect width="{WIDTH}" height="{height}" rx="16" fill="{theme["bg"]}" '
      f'stroke="{theme["border"]}" stroke-width="1.5"/>')
    block_w = (WIDTH - 2 * PAD) / 4.0
    for i, (label, value) in enumerate(stats):
        cx = PAD + block_w * i + block_w / 2
        a(f'<text x="{cx:.1f}" y="44" text-anchor="middle" font-family="{FONT}" '
          f'font-size="24" font-weight="700" fill="{theme["text"]}">{esc(value)}</text>')
        a(f'<text x="{cx:.1f}" y="64" text-anchor="middle" font-family="{FONT}" '
          f'font-size="12" fill="{theme["muted"]}">{esc(label)}</text>')

    a(f'<line x1="{PAD}" y1="78" x2="{WIDTH - PAD}" y2="78" stroke="{theme["border"]}" stroke-width="1"/>')

    # 小节标题 + 状态图例
    a(f'<text x="{PAD}" y="102" font-family="{FONT}" font-size="13" '
      f'fill="{theme["muted"]}">贡献的仓库</text>')
    legend_items = [("merged", "已合并"), ("open", "进行中"), ("closed", "未合并")]
    lx = WIDTH - PAD  # 图例右对齐
    for status, label in reversed(legend_items):
        lw = est_width(label, 11) + 16
        dot_x = lx - lw + 8
        a(f'<text x="{lx}" y="102" text-anchor="end" font-family="{FONT}" font-size="11" '
          f'fill="{theme["muted"]}">{esc(label)}</text>')
        a(f'<circle cx="{dot_x}" cy="96" r="3" fill="{theme[status]}"/>')
        lx -= lw

    # 贡献仓库网格
    if n:
        clips = []
        for i, info in enumerate(repos[:n]):
            col = i % COLS
            row = i // COLS
            cell_x = PAD + col * (cell_w + GAP)
            top = list_top + row * ROW_PITCH
            cy = top + 15          # 第一行（头像/仓库名/状态点）中心
            avatar_cx = cell_x + 16
            repo_x = cell_x + 28
            baseline = top + 19
            title_y = top + 36     # 第二行：注释 baseline

            # 小方块背景
            a(f'<rect x="{cell_x:.1f}" y="{top}" width="{cell_w:.1f}" height="{CELL_H}" '
              f'rx="8" fill="{theme["panel"]}" stroke="{theme["border"]}" stroke-width="1"/>')

            uri = avatar_data_uri(info["owner"], info["avatar_url"])
            if uri:
                clip_id = f"ava{i}"
                clips.append(f'<clipPath id="{clip_id}">'
                             f'<circle cx="{avatar_cx}" cy="{cy}" r="8"/></clipPath>')
                a(f'<image href="{uri}" x="{avatar_cx - 8}" y="{cy - 8}" '
                  f'width="16" height="16" clip-path="url(#{clip_id})"/>')
            else:
                color_hex = AVATAR_COLORS[sum(ord(c) for c in info["owner"]) % len(AVATAR_COLORS)]
                a(f'<circle cx="{avatar_cx}" cy="{cy}" r="8" fill="{color_hex}"/>')
                a(f'<text x="{avatar_cx}" y="{baseline}" text-anchor="middle" '
                  f'font-family="{FONT}" font-size="11" font-weight="700" fill="#ffffff">'
                  f'{esc(info["owner"][0].upper())}</text>')

            # 第一行：仓库名 + 紧跟其后的状态点
            repo_display = truncate(info["repo"], cell_w - 28 - 16, 11)
            dot_x = repo_x + est_width(repo_display, 11) + 5
            a(f'<text x="{repo_x}" y="{baseline}" font-family="{FONT}" font-size="11" '
              f'font-weight="700" fill="{theme["accent"]}">{esc(repo_display)}</text>')
            a(f'<circle cx="{dot_x}" cy="{cy}" r="3" fill="{theme[info["status"]]}"/>')

            # 第二行：最新 PR 标题（注释），字体略浅
            title_display = truncate(info["title"], cell_w - 24, 10)
            a(f'<text x="{cell_x + 12}" y="{title_y}" font-family="{FONT}" font-size="10" '
              f'fill="{theme["muted"]}">{esc(title_display)}</text>')

        if clips:
            a("<defs>" + "".join(clips) + "</defs>")
    else:
        a(f'<text x="{WIDTH / 2}" y="{list_top + 18}" text-anchor="middle" '
          f'font-family="{FONT}" font-size="13" fill="{theme["muted"]}">'
          f'暂无对他人的开源贡献</text>')

    a(f'<text x="{WIDTH / 2}" y="{footer_y}" text-anchor="middle" font-family="{FONT}" '
      f'font-size="11" fill="{theme["muted"]}">Auto-updated by GitHub Actions · {esc(USER)}</text>')
    if incomplete:
        a(f'<text x="{WIDTH / 2}" y="{footer_y - 16}" text-anchor="middle" font-family="{FONT}" '
          f'font-size="11" fill="{theme["open"]}">部分数据未获取（超出搜索上限 1000）</text>')

    a("</svg>")
    return "\n".join(L)


def main():
    print(f"获取用户 {USER} 的 PR 数据…")
    prs, total, incomplete = collect_prs()
    merged = sum(1 for p in prs if classify(p) == "merged")
    opened = sum(1 for p in prs if classify(p) == "open")
    closed = total - merged - opened
    merge_rate = merged / total if total else 0.0
    print(f"总计 {total} 个 PR：已合并 {merged}，进行中 {opened}，关闭未合并 {closed}，"
          f"数据不完整 {incomplete}")

    repos = aggregate_repos(prs)
    # 只保留对他人开源项目的贡献（排除本人自己的仓库）
    ordered = sorted(
        (r for r in repos.values() if r["owner"] != USER),
        key=lambda r: r["latest"], reverse=True)
    print(f"贡献仓库 {len(ordered)} 个（已排除 {len(repos) - len(ordered)} 个本人仓库）")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for filename, theme in ((DARK_FILE, THEMES["dark"]), (LIGHT_FILE, THEMES["light"])):
        path = os.path.join(OUTPUT_DIR, filename)
        svg = build_svg(theme, total, merged, opened, merge_rate, ordered, incomplete)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"已写入 {path}")


if __name__ == "__main__":
    main()
