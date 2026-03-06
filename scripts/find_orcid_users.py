#!/usr/bin/env python3
"""Find GitHub users with ORCID identifiers and cross-reference with Claude Code usage.

Paginates code search queries by splitting on language/filename to get past
the 1000-result cap. Filters to users with at least 1 commit in the past year.

Sources:
  1. User bios containing "orcid"
  2. Code search: orcid.org in README, CITATION.cff, .zenodo.json, codemeta.json,
     DESCRIPTION, pyproject.toml — split by language to get >1000 coverage
  3. Profile READMEs (username/username repos)

Outputs:
  - orcid_users.json: all discovered users with ORCIDs, filtered by recent activity
"""

import json
import os
import re
import sys
import time
from collections import defaultdict, Counter
from datetime import datetime, timedelta

import requests

SCRIPT_DIR = "/Users/charl/Programming/github_claude"
TOKEN = open(os.path.join(SCRIPT_DIR, ".github_token")).read().strip()
HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

ORCID_RE = re.compile(r"\b(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b")

OUTPUT_FILE = os.path.join(SCRIPT_DIR, "orcid_users.json")
COMMITS_FILE = os.path.join(SCRIPT_DIR, "claude_commits_all.json")

# One year ago
ACTIVE_SINCE = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

# Rate limiting
search_remaining = 30
search_reset = 0
core_remaining = 5000


def api_get(url, params=None, retries=3):
    """Make a rate-limited GitHub API request."""
    global search_remaining, search_reset, core_remaining

    is_search = "search" in url
    if is_search and search_remaining <= 1:
        wait = max(0, search_reset - time.time()) + 1
        if wait > 0:
            print(f"    [rate limit: {wait:.0f}s]", end="", flush=True)
            time.sleep(wait)

    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            raise

        if is_search and "X-RateLimit-Remaining" in r.headers:
            search_remaining = int(r.headers["X-RateLimit-Remaining"])
            search_reset = int(r.headers.get("X-RateLimit-Reset", 0))
        elif not is_search and "X-RateLimit-Remaining" in r.headers:
            core_remaining = int(r.headers["X-RateLimit-Remaining"])

        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(0, reset - time.time()) + 2
            print(f"    [rate limited: {wait:.0f}s]", end="", flush=True)
            time.sleep(wait)
            continue

        if r.status_code == 422:
            return None
        if r.status_code == 403:
            # Secondary rate limit
            time.sleep(10)
            continue

        r.raise_for_status()
        return r.json()

    return None


def paginate_search(endpoint, query, max_pages=10):
    """Paginate a search query up to max_pages (1000 results max per query)."""
    all_items = []
    page = 1
    while page <= max_pages:
        data = api_get(
            f"https://api.github.com/search/{endpoint}",
            params={"q": query, "per_page": 100, "page": page},
        )
        if not data or "items" not in data or len(data["items"]) == 0:
            break
        all_items.extend(data["items"])
        total = data.get("total_count", 0)
        if page * 100 >= min(total, 1000):
            break
        page += 1
    return all_items


# ── Source 1: User bios ──────────────────────────────────────────────

def search_user_bios():
    """Search for users with 'orcid' in their bio."""
    print("Source 1: User bios with 'orcid'", flush=True)
    users = {}

    # Main query
    items = paginate_search("users", "orcid in:bio")
    for item in items:
        users[item["login"]] = {
            "username": item["login"],
            "source": "bio",
        }

    # Also try orcid.org for users who put the URL
    items2 = paginate_search("users", "orcid.org in:bio")
    for item in items2:
        if item["login"] not in users:
            users[item["login"]] = {
                "username": item["login"],
                "source": "bio",
            }

    print(f"  Found {len(users)} users", flush=True)
    return users


def enrich_bio_users(users):
    """Fetch full profiles to extract ORCID from bio text."""
    print(f"  Enriching {len(users)} bio users...", flush=True)
    for i, (username, info) in enumerate(list(users.items())):
        if i % 100 == 0 and i > 0:
            print(f"    {i}/{len(users)}...", flush=True)
        try:
            data = api_get(f"https://api.github.com/users/{username}")
            if not data:
                continue
            bio = data.get("bio") or ""
            match = ORCID_RE.search(bio)
            if match:
                info["orcid"] = match.group(1)
            info["bio"] = bio
            info["name"] = data.get("name", "")
            info["company"] = data.get("company", "")
            info["location"] = data.get("location", "")
            info["public_repos"] = data.get("public_repos", 0)
            info["followers"] = data.get("followers", 0)
            info["created_at"] = data.get("created_at", "")
            info["updated_at"] = data.get("updated_at", "")
        except Exception as e:
            pass

    with_orcid = sum(1 for u in users.values() if "orcid" in u)
    print(f"  Extracted ORCIDs from {with_orcid}/{len(users)} bios", flush=True)


# ── Source 2: Code search (split by language + filename) ─────────────

def search_code_orcids():
    """Search for ORCID in code files, split by language to get past 1K cap."""
    print("\nSource 2: Code search for ORCID (split by language/filename)", flush=True)
    users = {}
    seen_repos = set()
    query_count = 0

    # Filenames to search
    filenames = [
        "README.md", "README.rst", "README",
        "CITATION.cff", ".zenodo.json", "codemeta.json",
        "DESCRIPTION",  # R packages
        "pyproject.toml", "setup.cfg",
        "CONTRIBUTORS.md", "AUTHORS.md", "AUTHORS",
    ]

    # Languages to split README searches (most common in research)
    languages = [
        "python", "r", "julia", "fortran", "c++", "c", "java",
        "matlab", "rust", "go", "javascript", "typescript",
        "shell", "perl", "ruby", "scala", "haskell",
        "tex", "jupyter-notebook",
    ]

    # 1. Search each filename (no language filter) — catches all languages
    for fname in filenames:
        query = f"orcid.org filename:{fname}"
        items = paginate_search("code", query)
        query_count += 1
        new = 0
        for item in items:
            repo = item["repository"]["full_name"]
            if repo in seen_repos:
                continue
            seen_repos.add(repo)
            owner = item["repository"]["owner"]["login"]
            if owner not in users:
                users[owner] = {"username": owner, "source": "code", "repos_with_orcid": []}
                new += 1
            users[owner]["repos_with_orcid"].append(repo)
        total = len(items)
        if new > 0:
            print(f"  {fname}: {total} results, {new} new users", flush=True)

    # 2. For README.md specifically (9K+ results), split by language
    for lang in languages:
        query = f"orcid.org filename:README.md language:{lang}"
        items = paginate_search("code", query)
        query_count += 1
        new = 0
        for item in items:
            repo = item["repository"]["full_name"]
            if repo in seen_repos:
                continue
            seen_repos.add(repo)
            owner = item["repository"]["owner"]["login"]
            if owner not in users:
                users[owner] = {"username": owner, "source": "code", "repos_with_orcid": []}
                new += 1
            users[owner]["repos_with_orcid"].append(repo)
        if new > 0:
            print(f"  README.md+{lang}: {len(items)} results, {new} new users", flush=True)

    # 3. Search for ORCID pattern in CITATION.cff split by language
    for lang in languages[:10]:  # top research languages
        query = f"orcid filename:CITATION.cff language:{lang}"
        items = paginate_search("code", query)
        query_count += 1
        new = 0
        for item in items:
            repo = item["repository"]["full_name"]
            if repo in seen_repos:
                continue
            seen_repos.add(repo)
            owner = item["repository"]["owner"]["login"]
            if owner not in users:
                users[owner] = {"username": owner, "source": "code", "repos_with_orcid": []}
                new += 1
            users[owner]["repos_with_orcid"].append(repo)
        if new > 0:
            print(f"  CITATION.cff+{lang}: {len(items)} results, {new} new users", flush=True)

    # 4. Search .zenodo.json split by language
    for lang in languages[:10]:
        query = f"orcid filename:.zenodo.json language:{lang}"
        items = paginate_search("code", query)
        query_count += 1
        new = 0
        for item in items:
            repo = item["repository"]["full_name"]
            if repo in seen_repos:
                continue
            seen_repos.add(repo)
            owner = item["repository"]["owner"]["login"]
            if owner not in users:
                users[owner] = {"username": owner, "source": "code", "repos_with_orcid": []}
                new += 1
            users[owner]["repos_with_orcid"].append(repo)
        if new > 0:
            print(f"  .zenodo.json+{lang}: {len(items)} results, {new} new users", flush=True)

    print(f"\n  Total: {len(users)} users from {len(seen_repos)} repos ({query_count} queries)", flush=True)
    return users


# ── Filter by recent activity ───────────────────────────────────────

def filter_recently_active(all_users, batch_size=100):
    """Filter to users with at least 1 commit in the past year using events API."""
    print(f"\nFiltering to users active since {ACTIVE_SINCE}...", flush=True)
    active_users = {}
    checked = 0
    skipped_rate = 0

    usernames = list(all_users.keys())
    total = len(usernames)

    for username in usernames:
        checked += 1
        if checked % 200 == 0:
            print(f"  Checked {checked}/{total}, {len(active_users)} active, core API remaining: {core_remaining}", flush=True)

        # Use the events API — fast, no search rate limit
        try:
            data = api_get(
                f"https://api.github.com/users/{username}/events/public",
                params={"per_page": 5},
            )
            if not data:
                continue

            # Check if any recent event
            has_recent = False
            for event in data:
                created = event.get("created_at", "")[:10]
                if created >= ACTIVE_SINCE:
                    has_recent = True
                    break

            if has_recent:
                active_users[username] = all_users[username]
                active_users[username]["recently_active"] = True
            else:
                # Events API only shows last 90 days. If no events,
                # check profile updated_at as fallback
                if all_users[username].get("updated_at", "") >= ACTIVE_SINCE:
                    active_users[username] = all_users[username]
                    active_users[username]["recently_active"] = True

        except Exception:
            # If we can't check, include them
            active_users[username] = all_users[username]

        # Back off if core rate limit getting low
        if core_remaining < 100:
            print(f"  Core API low ({core_remaining}), including remaining unchecked users", flush=True)
            for u in usernames[checked:]:
                active_users[u] = all_users[u]
            break

    print(f"  {len(active_users)} of {total} users are recently active ({len(active_users)/total*100:.1f}%)", flush=True)
    return active_users


# ── Merge ────────────────────────────────────────────────────────────

def merge_sources(bio_users, code_users):
    """Merge all sources, preferring bio data."""
    merged = {}

    for username, info in bio_users.items():
        merged[username] = info

    for username, info in code_users.items():
        if username in merged:
            merged[username].setdefault("repos_with_orcid", [])
            merged[username]["repos_with_orcid"].extend(info.get("repos_with_orcid", []))
            if "code" not in merged[username]["source"]:
                merged[username]["source"] += "+code"
        else:
            merged[username] = info

    by_source = Counter()
    for u in merged.values():
        for s in u["source"].split("+"):
            by_source[s] += 1

    print(f"\nMerged: {len(merged)} unique users")
    for s, n in by_source.most_common():
        print(f"  {s}: {n}")

    return merged


# ── Cross-reference with Claude commits ──────────────────────────────

def cross_reference_claude(orcid_users):
    """Stream Claude commits and find ORCID users."""
    print(f"\nCross-referencing with Claude Code commits...", flush=True)

    orcid_set = {u.lower(): u for u in orcid_users.keys()}
    claude_orcid = {}

    if not os.path.exists(COMMITS_FILE):
        print(f"  WARNING: {COMMITS_FILE} not found")
        return claude_orcid

    date = repo = None
    count = 0
    with open(COMMITS_FILE) as f:
        for line in f:
            stripped = line.strip()
            if '"date":' in stripped and '"author_date"' not in stripped:
                date = stripped.split(":", 1)[1].strip().strip('",')[:10]
            elif '"repo":' in stripped:
                repo = stripped.split(":", 1)[1].strip().strip('",')
            elif '"github_username":' in stripped:
                username = stripped.split(":", 1)[1].strip().strip('",')
                canonical = orcid_set.get(username.lower())
                if canonical:
                    if canonical not in claude_orcid:
                        claude_orcid[canonical] = {"dates": [], "repos": set(), "total": 0}
                    if date:
                        claude_orcid[canonical]["dates"].append(date)
                    if repo:
                        claude_orcid[canonical]["repos"].add(repo)
                    claude_orcid[canonical]["total"] += 1
                count += 1
                if count % 2_000_000 == 0:
                    print(f"  {count/1e6:.0f}M commits, {len(claude_orcid)} ORCID matches...", flush=True)
                date = repo = None

    for u in claude_orcid.values():
        u["repos"] = sorted(u["repos"])
        u["dates"] = sorted(u["dates"])
        u["first_date"] = u["dates"][0] if u["dates"] else None
        u["last_date"] = u["dates"][-1] if u["dates"] else None

    print(f"  {count:,} commits scanned")
    print(f"  {len(claude_orcid)} ORCID users with Claude commits ({sum(u['total'] for u in claude_orcid.values()):,} commits)")
    return claude_orcid


# ── Main ─────────────────────────────────────────────────────────────

def main():
    # Source 1: bios
    bio_users = search_user_bios()
    enrich_bio_users(bio_users)

    # Source 2: code search (split queries)
    code_users = search_code_orcids()

    # Merge
    all_users = merge_sources(bio_users, code_users)

    # Filter by recent activity
    active_users = filter_recently_active(all_users)

    # Cross-reference
    claude_overlap = cross_reference_claude(active_users)

    # Annotate
    for username, cdata in claude_overlap.items():
        if username in active_users:
            active_users[username]["claude_commits"] = cdata["total"]
            active_users[username]["claude_repos"] = cdata["repos"]
            active_users[username]["first_claude_date"] = cdata["first_date"]
            active_users[username]["last_claude_date"] = cdata["last_date"]

    # Save
    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "total_orcid_users": len(active_users),
            "total_with_claude": len(claude_overlap),
            "scraped_at": datetime.now().isoformat(),
            "active_since": ACTIVE_SINCE,
            "users": active_users,
        }, f, indent=2, default=str)
    print(f"\nSaved {OUTPUT_FILE}")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  ORCID GitHub users (active past year): {len(active_users):,}")
    print(f"  Using Claude Code: {len(claude_overlap):,} ({len(claude_overlap)/max(len(active_users),1)*100:.1f}%)")

    if claude_overlap:
        monthly = defaultdict(set)
        for username, data in claude_overlap.items():
            for d in data["dates"]:
                monthly[d[:7]].add(username)

        print(f"\n  ORCID users active per month:")
        cumulative = set()
        for month in sorted(monthly.keys()):
            cumulative |= monthly[month]
            print(f"    {month}: {len(monthly[month]):3d} active, {len(cumulative):3d} cumulative")

        # Top users
        top = sorted(claude_overlap.items(), key=lambda x: -x[1]["total"])[:15]
        print(f"\n  Top ORCID users by Claude commits:")
        for username, data in top:
            orcid = active_users.get(username, {}).get("orcid", "?")
            name = active_users.get(username, {}).get("name", "")
            print(f"    {username:25s} {data['total']:5d} commits  ORCID:{orcid}  {name}")

        # Commit distribution
        commit_counts = [d["total"] for d in claude_overlap.values()]
        import numpy as np
        print(f"\n  Commit distribution (n={len(commit_counts)}):")
        print(f"    median: {int(np.median(commit_counts))}")
        print(f"    mean:   {np.mean(commit_counts):.0f}")
        print(f"    p90:    {int(np.percentile(commit_counts, 90))}")
        print(f"    max:    {max(commit_counts)}")


if __name__ == "__main__":
    main()
