#!/usr/bin/env python3
"""Generate the METRICS.LOG block in the profile README.

The README is written like a terminal session, so the stats are too: plain
text inside a fenced code block. GitHub renders that with the viewer's own
theme (light, dark, high contrast), so it always matches the rest of the page
instead of shipping its own colours.

Usage:  GITHUB_TOKEN=... python3 scripts/metrics.py [--stdout]

Writes between <!-- METRICS:START --> and <!-- METRICS:END --> in README.md.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER = os.environ.get("GH_USER", "SchlangeGoto")
TOKEN = os.environ.get("STATS_TOKEN") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

START = "<!-- METRICS:START -->"
END = "<!-- METRICS:END -->"

WIDTH = 72

GRAPHQL = """
query($login: String!, $from: DateTime!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
      nodes {
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
    contributionsCollection(from: $from) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      restrictedContributionsCount
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
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

    one_year_ago = (datetime.now(timezone.utc) - timedelta(days=364)).isoformat()
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
            if current == 0:      # today may still be empty; the streak goes back from yesterday
                continue
            break
        current += 1

    languages: dict[str, int] = {}
    for repo in repos["nodes"]:
        for edge in repo["languages"]["edges"]:
            languages[edge["node"]["name"]] = languages.get(edge["node"]["name"], 0) + edge["size"]

    return {
        "commits": contrib["totalCommitContributions"],
        "prs": contrib["totalPullRequestContributions"],
        "contributions": sum(daily),
        "followers": user["followers"]["totalCount"],
        "repos": repos["totalCount"],
        "since": user["createdAt"][:4],
        "current_streak": current,
        "longest_streak": longest,
        "weeks": weeks,
        "languages": sorted(languages.items(), key=lambda kv: kv[1], reverse=True),
    }


# --------------------------------------------------------------------------- #
# ascii
# --------------------------------------------------------------------------- #
def rule(label: str, aside: str = "") -> str:
    left = f"{label} "
    fill = WIDTH - len(left) - len(aside) - (1 if aside else 0)
    return f"{left}{'─' * max(0, fill)}{' ' + aside if aside else ''}".rstrip()


def human_size(size: int) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"


def metric(label: str, value: object, lw: int, vw: int) -> str:
    return f"{label:<{lw}}{value:>{vw}}"


def render(d: dict) -> str:
    gap = " " * 5

    pairs = [
        ("commits", d["commits"], "followers", d["followers"]),
        ("pull requests", d["prs"], "on github since", d["since"]),
        ("public repos", d["repos"], "current streak", f"{d['current_streak']} days"),
        ("contributions", d["contributions"], "longest streak", f"{d['longest_streak']} days"),
    ]
    activity = "\n".join(
        "  " + metric(left, lv, 15, 5) + gap + metric(right, rv, 17, 10)
        for left, lv, right, rv in pairs
    )

    languages = d["languages"][:6]
    total = sum(size for _, size in d["languages"]) or 1
    peak = languages[0][1] if languages else 1
    bar_width = 48
    lang_lines = "\n".join(
        f"  {name:<12}{'█' * max(1, round(bar_width * size / peak)):<{bar_width}}  {size / total * 100:4.1f}%"
        for name, size in languages
    )

    return "\n".join(
        [
            "```text",
            '$ metrics --since="12 months"',
            "",
            rule("ACTIVITY"),
            activity,
            "",
            rule("LANGUAGES", f"{human_size(total)} of code"),
            lang_lines,
            "```",
        ]
    )


def update_readme(block: str) -> None:
    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        sys.exit(f"README.md is missing {START} / {END}")

    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    README.write_text(f"{head}{START}\n{block}\n{END}{tail}", encoding="utf-8")


def main() -> None:
    block = render(collect(fetch()))
    if "--stdout" in sys.argv:
        print(block)
        return
    update_readme(block)
    print(block)


if __name__ == "__main__":
    main()
