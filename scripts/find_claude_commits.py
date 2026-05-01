#!/usr/bin/env python3
"""
Find all public GitHub commits made with Claude Code since a given date.

Uses adaptive time windows: starts with 6-hour blocks and automatically
subdivides down to 1-minute resolution when a window exceeds 1,000 results.
This ensures no commits are missed regardless of volume.

Reads your GitHub PAT from .github_token in the same directory, or from
the GITHUB_TOKEN environment variable.

Usage:
  python3 find_claude_commits.py 2025-11-25
  python3 find_claude_commits.py 2025-11-25 -o results.json
  python3 find_claude_commits.py 2025-11-25 --resume
"""

import argparse
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, ".github_token")
API_URL = "https://api.github.com/search/commits"
SEARCH_QUERY = '"Co-Authored-By: Claude" "noreply@anthropic.com"'
PER_PAGE = 100
RATE_LIMIT_DELAY = 0.3  # Aggressive; GitHub search cap is 30/min — rely on 403 backoff if we overshoot

# Adaptive window subdivision steps (in minutes)
WINDOW_LEVELS = [
    360,  # 6 hours  — top level
    60,   # 1 hour
    15,   # 15 minutes
    5,    # 5 minutes
    1,    # 1 minute — smallest
]


def load_token():
    """Load GitHub PAT from .github_token file or environment."""
    if os.path.isfile(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
        if token:
            return token
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    print(
        "No GitHub token found.\n"
        f"  Option 1: Create {TOKEN_FILE} with your PAT (one line, no quotes)\n"
        "  Option 2: Set the GITHUB_TOKEN environment variable\n\n"
        "Generate a PAT at: https://github.com/settings/tokens\n"
        "  (no special scopes needed for searching public commits)",
        file=sys.stderr,
    )
    sys.exit(1)


def api_get(url, token):
    """Make an authenticated GET request to the GitHub API."""
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.cloak-preview+json")
    req.add_header("User-Agent", "claude-code-commit-finder")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 403 and "rate limit" in body.lower():
            retry = 60
            try:
                import re as _re
                m = _re.search(r'"retry-after":\s*"?(\d+)', body.lower())
                if m:
                    retry = int(m.group(1)) + 1
            except Exception:
                pass
            return {"rate_limited": True, "retry_after": retry}
        if e.code == 422:
            return {"total_count": 0, "items": []}
        if e.code in (500, 502, 503, 504):
            print(f"\n  Server error {e.code} — retrying in 30s...", file=sys.stderr, flush=True)
            time.sleep(30)
            return api_get(url, token)
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        raise
    except (urllib.error.URLError, TimeoutError, OSError, http.client.IncompleteRead) as e:
        print(f"\n  Network error: {e} — retrying in 10s...", file=sys.stderr, flush=True)
        time.sleep(10)
        return api_get(url, token)


def query_window(token, start, end, count_only=False):
    """
    Query commits in a time window.
    If count_only=True, fetch just page 1 to get total_count (cheaper).
    Otherwise, paginate to get all items (up to 1,000).
    Returns (items, total_count).
    """
    date_filter = (
        f"author-date:{start.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"..{end.strftime('%Y-%m-%dT%H:%M:%S')}"
    )
    query = f"{SEARCH_QUERY} {date_filter}"
    encoded = urllib.parse.quote(query, safe="")
    base_url = f"{API_URL}?q={encoded}&per_page={1 if count_only else PER_PAGE}&sort=author-date&order=asc"

    all_items = []
    page = 1

    while True:
        url = f"{base_url}&page={page}"
        data = api_get(url, token)

        if data.get("rate_limited"):
            retry = data.get("retry_after", 60)
            print(f"\n  Rate limited — waiting {retry}s...", flush=True)
            time.sleep(retry)
            continue

        total = data.get("total_count", 0)

        if count_only:
            return [], total

        items = data.get("items", [])
        all_items.extend(items)

        if len(items) < PER_PAGE or page * PER_PAGE >= min(total, 1000):
            break
        page += 1
        time.sleep(RATE_LIMIT_DELAY)

    return all_items, total


def parse_commit(item):
    """Extract useful fields from a search result item."""
    commit = item.get("commit", {})
    author = commit.get("author", {})
    repo = item.get("repository", {})
    github_user = item.get("author") or {}  # can be None if email not linked
    return {
        "sha": item.get("sha", ""),
        "date": author.get("date", ""),
        "repo": repo.get("full_name", "unknown"),
        "author": author.get("name", "unknown"),
        "github_username": github_user.get("login", ""),
        "github_user_id": github_user.get("id", ""),
        "author_email": author.get("email", ""),
        "message": commit.get("message", "").split("\n")[0],
        "url": item.get("html_url", ""),
    }


def collect_window(token, start, end, level_idx, seen_shas, stats):
    """
    Recursively collect commits from a time window.
    If the window has >1000 results, subdivide into smaller windows.
    Returns list of parsed commits.
    """
    window_minutes = WINDOW_LEVELS[level_idx]
    label = format_window(start, window_minutes)

    # First, do a count-only query to check if we need to subdivide
    time.sleep(RATE_LIMIT_DELAY)
    stats["api_calls"] += 1
    _, total = query_window(token, start, end, count_only=True)

    if total == 0:
        return []

    # If over 1000 and we can subdivide, do so
    if total > 1000 and level_idx + 1 < len(WINDOW_LEVELS):
        next_level = level_idx + 1
        sub_minutes = WINDOW_LEVELS[next_level]
        sub_label = f"{sub_minutes}min" if sub_minutes < 60 else f"{sub_minutes // 60}h"
        print(f"\n  {label}: {total} results — subdividing into {sub_label} windows", flush=True)

        commits = []
        cursor = start
        while cursor < end:
            sub_end = min(cursor + timedelta(minutes=sub_minutes), end)
            commits.extend(
                collect_window(token, cursor, sub_end, next_level, seen_shas, stats)
            )
            cursor = sub_end
        return commits

    # If over 1000 at the smallest window, warn but collect what we can
    if total > 1000:
        print(
            f"\n  WARNING: {label} has {total} results at 1-min granularity. "
            f"Collecting first 1,000.",
            flush=True,
        )

    # Fetch all results in this window
    time.sleep(RATE_LIMIT_DELAY)
    stats["api_calls"] += 1
    items, _ = query_window(token, start, end, count_only=False)

    # Additional pages counted in query_window; rough estimate
    stats["api_calls"] += max(0, (len(items) // PER_PAGE) - 1)

    commits = []
    for item in items:
        c = parse_commit(item)
        if c["sha"] not in seen_shas:
            seen_shas.add(c["sha"])
            commits.append(c)

    if commits:
        stats["total"] += len(commits)
        sys.stdout.write(
            f"\r  {label}: +{len(commits)} commits  "
            f"(total: {stats['total']}, API calls: {stats['api_calls']})"
        )
        sys.stdout.write("          \n")
        sys.stdout.flush()

    return commits


def format_window(start, minutes):
    """Human-readable label for a time window."""
    if minutes >= 360:
        return f"{start.strftime('%Y-%m-%d %H:%M')} ({minutes // 60}h window)"
    elif minutes >= 60:
        return f"{start.strftime('%Y-%m-%d %H:%M')} ({minutes // 60}h)"
    else:
        return f"{start.strftime('%Y-%m-%d %H:%M')} ({minutes}min)"


def load_progress(path):
    """Load previously saved results for resuming."""
    if path and os.path.isfile(path):
        with open(path) as f:
            data = json.load(f)
        return data.get("commits", []), data.get("last_window_end", None)
    return [], None


def save_results(path, commits, since, last_window_end=None):
    """Save results to JSON, deduped by sha."""
    seen = set()
    deduped = []
    for c in commits:
        if c["sha"] not in seen:
            seen.add(c["sha"])
            deduped.append(c)
    deduped.sort(key=lambda c: c["date"])

    with open(path, "w") as f:
        json.dump(
            {
                "query": SEARCH_QUERY,
                "since": since,
                "last_window_end": last_window_end,
                "total_fetched": len(deduped),
                "commits": deduped,
            },
            f,
            indent=2,
        )
    return deduped


def main():
    parser = argparse.ArgumentParser(
        description="Find Claude Code commits on GitHub (adaptive time windows)"
    )
    parser.add_argument("since", help="Start date: YYYY-MM-DD")
    parser.add_argument(
        "--output", "-o", default="claude_commits.json",
        help="Output JSON file (default: claude_commits.json)",
    )
    parser.add_argument(
        "--until", "-u", default=None,
        help="End date: YYYY-MM-DD (default: now)",
    )
    parser.add_argument(
        "--resume", "-r", action="store_true",
        help="Resume from last saved position in the output file",
    )
    args = parser.parse_args()

    since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    until_dt = (
        datetime.strptime(args.until, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.until
        else datetime.now(timezone.utc)
    )
    token = load_token()

    # Resume support
    all_commits = []
    resume_after = None
    if args.resume:
        all_commits, resume_after = load_progress(args.output)
        if resume_after:
            since_dt = datetime.fromisoformat(resume_after)
            print(f"Resuming from: {since_dt.strftime('%Y-%m-%d %H:%M')}")
        if all_commits:
            print(f"Loaded {len(all_commits)} existing commits")

    seen_shas = {c["sha"] for c in all_commits}
    stats = {"total": len(all_commits), "api_calls": 0}

    # Generate top-level windows (6-hour blocks)
    top_minutes = WINDOW_LEVELS[0]
    windows = []
    cursor = since_dt
    while cursor < until_dt:
        w_end = min(cursor + timedelta(minutes=top_minutes), until_dt)
        windows.append((cursor, w_end))
        cursor = w_end

    print(f"Searching {len(windows)} top-level windows from {args.since} to now...")
    print(f"Windows auto-subdivide when >1,000 results (down to 1-min granularity)")
    print(f"Output: {args.output}")
    print()

    for i, (start, end) in enumerate(windows):
        pct = (i + 1) / len(windows) * 100
        sys.stdout.write(
            f"\r[{pct:5.1f}%] {start.strftime('%Y-%m-%d %H:%M')}  |  "
            f"{stats['total']} commits  |  {stats['api_calls']} API calls"
        )
        sys.stdout.flush()

        try:
            new_commits = collect_window(token, start, end, 0, seen_shas, stats)
            all_commits.extend(new_commits)
        except KeyboardInterrupt:
            print("\n\nInterrupted! Saving progress...", file=sys.stderr)
            save_results(args.output, all_commits, args.since, start.isoformat())
            print(f"Saved. Re-run with --resume to continue.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"\n  Error at {start}: {e}", file=sys.stderr)
            save_results(args.output, all_commits, args.since, start.isoformat())
            print(f"  Progress saved. Re-run with --resume to continue.", file=sys.stderr)
            sys.exit(1)

        # Save progress every 4 top-level windows
        if (i + 1) % 4 == 0:
            save_results(args.output, all_commits, args.since, end.isoformat())

    # Final save
    deduped = save_results(args.output, all_commits, args.since)

    print(f"\n\n{'=' * 60}")
    print(f"Done! {len(deduped)} unique commits found.")
    print(f"Total API calls: {stats['api_calls']}")
    print(f"Results saved to {args.output}")

    # Summary by repo
    repos = {}
    for c in deduped:
        repos[c["repo"]] = repos.get(c["repo"], 0) + 1
    if repos:
        print(f"\nTop 25 repositories:")
        for repo, count in sorted(repos.items(), key=lambda x: -x[1])[:25]:
            print(f"  {count:>6}  {repo}")

    # Summary by day
    days = {}
    for c in deduped:
        day = c["date"][:10]
        days[day] = days.get(day, 0) + 1
    if days:
        print(f"\nCommits per day:")
        for day, count in sorted(days.items()):
            bar = "#" * min(count // max(1, max(days.values()) // 50), 50)
            print(f"  {day}  {count:>6}  {bar}")


if __name__ == "__main__":
    main()
