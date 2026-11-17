#!/usr/bin/env python3
"""Generate the terminal-styled METRICS.LOG cards for the profile README.

Both cards are plain SVG, drawn in the same amber-on-charcoal palette as the
rest of the README, so they stop looking like embeds from another site.

Usage:  GITHUB_TOKEN=... python3 scripts/metrics.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

USER = os.environ.get("GH_USER", "SchlangeGoto")
TOKEN = os.environ.get("STATS_TOKEN") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
OUT_DIR = Path(__file__).resolve().parent.parent / "profile"

BG = "#1c1917"
BORDER = "#3a2f24"
AMBER = "#f59e0b"
AMBER_SOFT = "#fbbf24"
AMBER_DEEP = "#92400e"
CREAM = "#ebdbb2"
MUTED = "#a89984"
DIM = "#6f635b"
TRACK = "#2a2420"
GRID = "#302821"

FONT = (
    "ui-monospace, 'SFMono-Regular', 'SF Mono', Menlo, Consolas, "
    "'Liberation Mono', 'DejaVu Sans Mono', monospace"
)

GRAPHQL = """
query($login: String!, $from: DateTime!) {
  user(login: $login) {
    followers { totalCount }
    following { totalCount }
    createdAt
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection(from: $from) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      restrictedContributionsCount
      contributionCalendar {
        weeks {
          contributionDays { date contributionCount }
        }
      }
    }
  }
}
"""


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
def fetch() -> dict:
    if not TOKEN:
        sys.exit("missing GITHUB_TOKEN")

    one_year_ago = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    payload = json.dumps({"query": GRAPHQL, "variables": {"login": USER, "from": one_year_ago}})

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload.encode(),
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": f"{USER}-profile-metrics",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as exc:
        sys.exit(f"graphql failed: {exc.code} {exc.read()[:300]!r}")

    if "errors" in body:
        sys.exit(f"graphql errors: {body['errors']}")

    return body["data"]["user"]


def collect(user: dict) -> dict:
    contrib = user["contributionsCollection"]
    repos = user["repositories"]

    weeks = [
        [(day["date"], day["contributionCount"]) for day in week["contributionDays"]]
        for week in contrib["contributionCalendar"]["weeks"]
    ]
    daily = [count for week in weeks for _, count in week]

    current, longest, run = 0, 0, 0
    for count in daily:
        if count:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    for count in reversed(daily):
        if not count:
            break
        current += 1

    languages: dict[str, int] = {}
    stars = 0
    for repo in repos["nodes"]:
        stars += repo["stargazerCount"]
        for edge in repo["languages"]["edges"]:
            languages[edge["node"]["name"]] = languages.get(edge["node"]["name"], 0) + edge["size"]

    return {
        "commits": contrib["totalCommitContributions"],
        "prs": contrib["totalPullRequestContributions"],
        "issues": contrib["totalIssueContributions"],
        "private": contrib["restrictedContributionsCount"],
        "followers": user["followers"]["totalCount"],
        "repos": repos["totalCount"],
        "stars": stars,
        "weeks": weeks,
        "current_streak": current,
        "longest_streak": longest,
        "languages": sorted(languages.items(), key=lambda kv: kv[1], reverse=True),
    }


# --------------------------------------------------------------------------- #
# svg helpers
# --------------------------------------------------------------------------- #
def esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def text(x, y, value, size=12, fill=CREAM, weight=400, spacing=0, anchor="start", opacity=1.0):
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-weight="{weight}" '
        f'font-family="{FONT}" letter-spacing="{spacing}" text-anchor="{anchor}" '
        f'opacity="{opacity}">{esc(value)}</text>'
    )


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def mix(a: str, b: str, t: float) -> str:
    ra, ga, ba = hex_to_rgb(a)
    rb, gb, bb = hex_to_rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in ((ra, rb), (ga, gb), (ba, bb)))


def header(width: int, index: str, title: str, aside: str) -> str:
    pad = 32
    parts = [
        text(pad, 40, index, 12, AMBER, 700, 1.5),
        text(pad + 26, 40, f"// {title}", 12, CREAM, 600, 2.2),
        text(width - pad, 40, aside, 10.5, DIM, 400, 1.2, "end"),
        f'<line x1="{pad}" y1="58" x2="{width - pad}" y2="58" stroke="{BORDER}"/>',
        f'<rect x="{pad}" y="57" width="34" height="2" fill="{AMBER}"/>',
    ]
    return "\n".join(parts)


def stat_block(x, y, value, label, unit=""):
    parts = [
        text(x, y, value, 32, CREAM, 700),
        text(x + (len(str(value)) * 19.4) + 8, y, unit, 11, AMBER, 600, 1.2),
        text(x, y + 20, label, 9.5, DIM, 500, 1.8),
    ]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# card 1: activity
# --------------------------------------------------------------------------- #
def activity_svg(d: dict) -> str:
    width, height = 860, 280
    pad = 32

    rows = [
        (d["commits"], "COMMITS"),
        (d["prs"], "PULL REQUESTS"),
        (d["repos"], "PUBLIC REPOS"),
        (d["followers"], "FOLLOWERS"),
    ]
    stats = "\n".join(
        stat_block(pad + (i % 2) * 168, 138 + (i // 2) * 86, value, label)
        for i, (value, label) in enumerate(rows)
    )

    # contribution map: 53 columns x 7 rows, fitted to the right column
    weeks = d["weeks"]
    x0, x1 = 356, width - pad
    top = 112
    step = (x1 - x0) / len(weeks)
    cell = step - 2.3
    max_day = max((c for week in weeks for _, c in week), default=1) or 1

    levels = ["#2a2420", "#4a3413", "#93610c", "#d97706", "#fbbf24"]
    squares = []
    for wi, week in enumerate(weeks):
        for di, (_, count) in enumerate(week):
            if count <= 0:
                level = 0
            else:
                ratio = (count / max_day) ** 0.5
                level = 1 + min(3, int(ratio * 3.0))
            x = round(x0 + wi * step, 2)
            y = round(top + di * step, 2)
            squares.append(
                f'<rect x="{x}" y="{y}" width="{round(cell, 2)}" height="{round(cell, 2)}" '
                f'rx="1.5" fill="{levels[level]}"/>'
            )

    months = []
    seen = set()
    for wi, week in enumerate(weeks):
        first = next((day for day, _ in week if day), None)
        if not first:
            continue
        day = date.fromisoformat(first)
        key = (day.year, day.month)
        if key in seen or day.day > 7:
            continue
        seen.add(key)
        months.append(text(round(x0 + wi * step) + 1, top + 7 * step + 16, day.strftime("%b").upper(), 9, DIM, 500, 0.8))

    total = sum(count for week in weeks for _, count in week)
    streak_y = top + 7 * step + 52

    right = [
        text(x0, 92, "CONTRIBUTION MAP", 9.5, DIM, 500, 1.8),
        text(x1, 92, "53 WEEKS", 9.5, DIM, 500, 1.2, "end"),
        *squares,
        *months,
        text(x0, streak_y, "STREAK", 9.5, DIM, 500, 1.8),
        text(x0, streak_y + 24, f"{d['current_streak']}d", 18, AMBER, 700),
        text(x0 + 74, streak_y, "BEST", 9.5, DIM, 500, 1.8),
        text(x0 + 74, streak_y + 24, f"{d['longest_streak']}d", 18, CREAM, 700),
        text(x0 + 148, streak_y, "CONTRIBUTIONS", 9.5, DIM, 500, 1.8),
        text(x0 + 148, streak_y + 24, str(total), 18, CREAM, 700),
    ]

    body = "\n".join(
        [
            header(width, "01", "ACTIVITY", f"{USER} · LAST 12 MONTHS"),
            stats,
            *right,
        ]
    )
    desc = (
        f"{d['commits']} commits, {d['prs']} pull requests, {d['followers']} followers and "
        f"{d['repos']} public repositories. {total} contributions over the last 12 months, "
        f"current streak {d['current_streak']} days."
    )
    return render(width, height, f"{USER} · activity", desc, body, "")


# --------------------------------------------------------------------------- #
# card 2: languages
# --------------------------------------------------------------------------- #
def languages_svg(d: dict) -> str:
    width = 860
    languages = d["languages"][:6]
    total = sum(size for _, size in languages) or 1
    total_all = sum(size for _, size in d["languages"]) or 1

    row_count = (len(languages) + 1) // 2
    height = 148 + row_count * 34 + 34
    pad = 32

    bar_x, bar_w, bar_y, bar_h = pad, width - pad * 2, 96, 14
    ramp = [AMBER_SOFT, AMBER, "#d97706", "#b45309", "#92400e", "#7c4a1e"]

    segments = []
    cursor = bar_x
    for i, (name, size) in enumerate(languages):
        seg_w = bar_w * size / total
        segments.append(
            f'<rect x="{round(cursor, 2)}" y="{bar_y}" width="{round(seg_w + 0.6, 2)}" '
            f'height="{bar_h}" fill="{ramp[i % len(ramp)]}"/>'
        )
        cursor += seg_w
    if cursor < bar_x + bar_w:
        segments.append(
            f'<rect x="{round(cursor, 2)}" y="{bar_y}" width="{round(bar_x + bar_w - cursor, 2)}" '
            f'height="{bar_h}" fill="{TRACK}"/>'
        )

    legend = []
    for i, (name, size) in enumerate(languages):
        rows_total = (len(languages) + 1) // 2
        col, row = i // rows_total, i % rows_total
        x = pad + col * ((width - pad * 2) / 2 + 4)
        y = 150 + row * 34
        pct = size / total_all * 100
        legend += [
            f'<rect x="{x}" y="{y - 9}" width="8" height="8" rx="2" fill="{ramp[i % len(ramp)]}"/>',
            text(x + 20, y, name, 12.5, CREAM, 500),
            text(x + (width - pad * 2) / 2 - 28, y, f"{pct:4.1f}%", 11.5, MUTED, 500, 1.0, "end"),
        ]

    repo_label = f"{d['repos']} PUBLIC REPOS"
    body = "\n".join(
        [
            header(width, "02", "LANGUAGES", f"{fmt_bytes(total_all)} · {repo_label}"),
            f'<g clip-path="url(#barclip)">',
            *segments,
            "</g>",
            *legend,
            text(pad, height - 22, "BYTES OF CODE · TOP 6 LANGUAGES", 9, DIM, 500, 1.4),
        ]
    )
    defs = '<clipPath id="barclip"><rect x="32" y="96" width="796" height="14" rx="7"/></clipPath>'
    desc = "Language distribution: " + ", ".join(
        f"{name} {size / total_all * 100:.0f}%" for name, size in languages
    )
    return render(width, height, f"{USER} · languages", desc, body, defs)


def fmt_bytes(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return ""


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #
def render(width, height, title, desc, body, defs) -> str:
    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none"
     xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">{esc(title)}</title>
  <desc id="desc">{esc(desc)}</desc>
  <defs>
{defs}
  </defs>
  <g>
    <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" fill="{BG}" stroke="{BORDER}"/>
  </g>
{body}
</svg>
"""


def main() -> None:
    data = collect(fetch())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "metrics-activity.svg").write_text(activity_svg(data), encoding="utf-8")
    (OUT_DIR / "metrics-languages.svg").write_text(languages_svg(data), encoding="utf-8")

    snapshot = {k: v for k, v in data.items() if k not in {"weeks", "languages"}}
    snapshot["languages"] = [[name, size] for name, size in data["languages"]]
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
