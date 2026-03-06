#!/usr/bin/env python3
"""Find GitHub users with ORCID identifiers via the ORCID public API.

Searches the ORCID registry for all records that mention github.com,
then fetches each record to extract GitHub usernames from:
  - researcher-urls (website links)
  - external-identifiers (person-level IDs)
  - biography text

Supports delta mode: loads existing results and only fetches new/failed records.

Cross-references with Claude Code commits, filters by recent GitHub activity,
and produces a timeline of Claude adoption among ORCID researchers.

Outputs:
  - orcid_github_users.json: all ORCID->GitHub mappings + Claude usage + activity
"""

import json
import os
import re
import sys
import time
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import numpy as np

SCRIPT_DIR = "/Users/charl/Programming/github_claude"
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "orcid_github_users.json")
COMMITS_FILE = os.path.join(SCRIPT_DIR, "claude_commits_all.json")
PREV_FILE = os.path.join(SCRIPT_DIR, "orcid_users.json")

GITHUB_TOKEN = open(os.path.join(SCRIPT_DIR, ".github_token")).read().strip()
GITHUB_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

ORCID_API = "https://pub.orcid.org/v3.0"
HEADERS_ORCID = {"Accept": "application/json"}

ORCID_CLIENT_ID = "APP-LY6BGRCJCDBGO0YL"
ORCID_CLIENT_SECRET = "***REVOKED-SECRET***"

SESSION_ORCID = requests.Session()
SESSION_ORCID.headers.update(HEADERS_ORCID)


def get_orcid_token():
    """Get a read-public access token using client credentials."""
    print("  Authenticating with ORCID API...", flush=True)
    r = requests.post(
        "https://orcid.org/oauth/token",
        data={
            "client_id": ORCID_CLIENT_ID,
            "client_secret": ORCID_CLIENT_SECRET,
            "scope": "/read-public",
            "grant_type": "client_credentials",
        },
        headers={"Accept": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    SESSION_ORCID.headers["Authorization"] = f"Bearer {token}"
    print("  Authenticated successfully", flush=True)
    return token


def orcid_get(url, params=None, retries=5):
    """ORCID API request with retry on 429/503."""
    for attempt in range(retries):
        try:
            r = SESSION_ORCID.get(url, params=params, timeout=30)
            if r.status_code in (429, 503):
                wait = min(2 ** attempt * 5, 120)
                print(f"    [ORCID rate limit, waiting {wait}s]", end="", flush=True)
                time.sleep(wait)
                continue
            return r
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            time.sleep(2 ** attempt)
            continue
    return None

ACTIVE_SINCE = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

# GitHub username from URL: github.com/username or github.com/username/
GH_USER_RE = re.compile(
    r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)(?:/|$|\?)",
    re.IGNORECASE,
)

# Exclude org pages and common non-user paths
GH_EXCLUDE = {
    "orgs", "topics", "explore", "trending", "settings", "notifications",
    "marketplace", "features", "security", "pricing", "about", "sponsors",
    "collections", "events", "issues", "pulls", "discussions", "codespaces",
    "search", "stars", "watching", "apps", "new", "login", "signup", "join",
}

# Track GitHub API rate limits
gh_core_remaining = 5000


# ── Step 1: Search ORCID registry ──────────────────────────────────

def _paginate_query(query, label=""):
    """Paginate an ORCID search query, respecting 10K Solr deep-paging limit."""
    orcid_ids = []
    start = 0
    batch_size = 200

    r = orcid_get(f"{ORCID_API}/search/", params={"q": query, "rows": 0})
    if not r:
        if label:
            print(f"    {label}: failed to fetch count", flush=True)
        return orcid_ids
    r.raise_for_status()
    total = r.json()["num-found"]

    if total == 0:
        if label:
            print(f"    {label}: 0 total", flush=True)
        return orcid_ids

    while start < min(total, 9999):
        r = orcid_get(f"{ORCID_API}/search/", params={"q": query, "rows": batch_size, "start": start})
        if not r or r.status_code == 400:
            break
        r.raise_for_status()
        data = r.json()
        results = data.get("result") or []
        if not results:
            break
        for item in results:
            orcid_ids.append(item["orcid-identifier"]["path"])
        start += batch_size

    if label:
        capped = " [CAPPED]" if total > 9999 else ""
        print(f"    {label}: {total:,} total, collected {len(orcid_ids):,}{capped}", flush=True)
    return orcid_ids


def search_orcid_records():
    """Search ORCID for all records mentioning github.com."""
    print("Step 1: Searching ORCID registry for github.com mentions...", flush=True)

    r = orcid_get(f"{ORCID_API}/search/", params={"q": "text:github.com", "rows": 0})
    r.raise_for_status()
    total = r.json()["num-found"]
    print(f"  Total ORCID records: {total:,}", flush=True)

    # Date ranges — split any bucket that could exceed 10K
    date_ranges = [
        ("* TO 2022-12-31T23:59:59Z", "<=2022"),
        ("2023-01-01T00:00:00Z TO 2023-12-31T23:59:59Z", "2023"),
        ("2024-01-01T00:00:00Z TO 2024-06-30T23:59:59Z", "2024-H1"),
        ("2024-07-01T00:00:00Z TO 2024-12-31T23:59:59Z", "2024-H2"),
        ("2025-01-01T00:00:00Z TO 2025-03-31T23:59:59Z", "2025-Q1"),
        ("2025-04-01T00:00:00Z TO 2025-06-30T23:59:59Z", "2025-Q2"),
        ("2025-07-01T00:00:00Z TO 2025-09-30T23:59:59Z", "2025-Q3"),
        ("2025-10-01T00:00:00Z TO 2025-12-31T23:59:59Z", "2025-Q4"),
        ("2026-01-01T00:00:00Z TO 2026-01-31T23:59:59Z", "2026-Jan"),
        ("2026-02-01T00:00:00Z TO 2026-02-28T23:59:59Z", "2026-Feb"),
        ("2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z", "2026-Mar"),
        ("2026-04-01T00:00:00Z TO 2026-12-31T23:59:59Z", "2026-Apr+"),
    ]

    all_ids = set()
    for date_range, label in date_ranges:
        query = f"text:github.com AND profile-last-modified-date:[{date_range}]"
        ids = _paginate_query(query, label)
        all_ids.update(ids)

    print(f"  Found {len(all_ids):,} unique ORCID records mentioning GitHub", flush=True)
    return list(all_ids)


# ── Step 2: Fetch records and extract GitHub usernames ──────────────

def extract_github_from_record(orcid_id):
    """Fetch an ORCID person record and extract GitHub username(s). With retries."""
    for attempt in range(3):
        try:
            r = SESSION_ORCID.get(
                f"{ORCID_API}/{orcid_id}/person",
                timeout=15,
            )
            if r.status_code == 429 or r.status_code == 503:
                time.sleep(2 ** attempt + 1)
                continue
            if r.status_code != 200:
                return orcid_id, None, False  # not retryable

            data = r.json()
            github_users = set()
            sources = []

            # 1. researcher-urls
            researcher_urls = data.get("researcher-urls", {}).get("researcher-url", [])
            for url_entry in researcher_urls:
                url = (url_entry.get("url") or {}).get("value", "")
                match = GH_USER_RE.search(url)
                if match:
                    username = match.group(1)
                    if username.lower() not in GH_EXCLUDE:
                        github_users.add(username)
                        sources.append("researcher-url")

            # 2. external-identifiers
            ext_ids = data.get("external-identifiers", {}).get("external-identifier", [])
            for eid in ext_ids:
                url = (eid.get("external-id-url") or {}).get("value", "")
                match = GH_USER_RE.search(url)
                if match:
                    username = match.group(1)
                    if username.lower() not in GH_EXCLUDE:
                        github_users.add(username)
                        sources.append("external-id")
                eid_type = (eid.get("external-id-type") or "").lower()
                if "github" in eid_type:
                    val = eid.get("external-id-value", "")
                    if val and "/" not in val and val.lower() not in GH_EXCLUDE:
                        github_users.add(val)
                        sources.append("external-id")

            # 3. biography
            bio = (data.get("biography") or {}).get("content", "") or ""
            if "github.com/" in bio.lower():
                for match in GH_USER_RE.finditer(bio):
                    username = match.group(1)
                    if username.lower() not in GH_EXCLUDE:
                        github_users.add(username)
                        sources.append("biography")

            if not github_users:
                return orcid_id, None, False

            name_data = data.get("name") or {}
            given = (name_data.get("given-names") or {}).get("value", "")
            family = (name_data.get("family-name") or {}).get("value", "")
            name = f"{given} {family}".strip()

            return orcid_id, {
                "orcid": orcid_id,
                "name": name,
                "github_usernames": sorted(github_users),
                "source_fields": list(set(sources)),
            }, False

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            time.sleep(2 ** attempt)
            continue
        except Exception:
            return orcid_id, None, False

    return orcid_id, None, True  # exhausted retries


def fetch_all_records(orcid_ids, existing_records=None):
    """Fetch ORCID records in parallel. Skips already-fetched IDs."""
    if existing_records is None:
        existing_records = {}

    # Filter to only IDs we haven't fetched yet
    to_fetch = [oid for oid in orcid_ids if oid not in existing_records]
    print(f"\nStep 2: Fetching ORCID records to extract GitHub usernames...", flush=True)
    print(f"  Total: {len(orcid_ids):,}, already have: {len(existing_records):,}, "
          f"to fetch: {len(to_fetch):,}", flush=True)

    if not to_fetch:
        print(f"  Nothing new to fetch!", flush=True)
        return existing_records

    results = dict(existing_records)
    no_github = 0
    retried_out = 0

    # Lower concurrency to avoid rate limits
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(extract_github_from_record, oid): oid
            for oid in to_fetch
        }

        done = 0
        for future in as_completed(futures):
            done += 1
            orcid_id, result, exhausted = future.result()

            if result is None:
                if exhausted:
                    retried_out += 1
                else:
                    no_github += 1
            else:
                results[orcid_id] = result

            if done % 1000 == 0:
                new_count = len(results) - len(existing_records)
                print(
                    f"  Fetched {done:,}/{len(to_fetch):,} — "
                    f"{new_count:,} new with GitHub, {no_github:,} without, "
                    f"{retried_out:,} failed",
                    flush=True,
                )

    new_count = len(results) - len(existing_records)
    print(f"  Done: {new_count:,} new records with GitHub, "
          f"{no_github:,} without, {retried_out:,} failed after retries", flush=True)
    print(f"  Total records with GitHub: {len(results):,}", flush=True)
    return results


# ── Step 3: Build mapping ──────────────────────────────────────────

def build_github_mapping(orcid_records):
    """Build GitHub username -> ORCID mapping."""
    print(f"\nStep 3: Building GitHub username mapping...", flush=True)

    gh_to_orcid = {}
    multi_orcid = 0

    for orcid_id, record in orcid_records.items():
        for gh_user in record["github_usernames"]:
            gh_lower = gh_user.lower()
            if gh_lower in gh_to_orcid:
                multi_orcid += 1
                continue
            gh_to_orcid[gh_lower] = {
                "github_username": gh_user,
                "orcid": orcid_id,
                "name": record["name"],
                "source_fields": record["source_fields"],
            }

    print(f"  {len(gh_to_orcid):,} unique GitHub usernames", flush=True)
    if multi_orcid:
        print(f"  {multi_orcid} cases of multiple ORCIDs -> same GitHub user (kept first)", flush=True)

    src_counts = Counter()
    for u in gh_to_orcid.values():
        for s in u["source_fields"]:
            src_counts[s] += 1
    for s, n in src_counts.most_common():
        print(f"    {s}: {n:,}", flush=True)

    return gh_to_orcid


def merge_with_previous(gh_to_orcid):
    """Merge with previous GitHub-search-based results for additional coverage."""
    if not os.path.exists(PREV_FILE):
        return gh_to_orcid

    print(f"\nStep 3b: Merging with previous GitHub-API-based results...", flush=True)

    with open(PREV_FILE) as f:
        prev = json.load(f)

    prev_users = prev.get("users", {})
    added = 0
    for username, info in prev_users.items():
        if username.lower() not in gh_to_orcid:
            gh_to_orcid[username.lower()] = {
                "github_username": username,
                "orcid": info.get("orcid", ""),
                "name": info.get("name", ""),
                "source_fields": ["github_search"],
            }
            added += 1

    print(f"  Added {added} users from previous GitHub-API scrape", flush=True)
    print(f"  Total unique GitHub users: {len(gh_to_orcid):,}", flush=True)
    return gh_to_orcid


# ── Step 4: Filter by recent GitHub activity ────────────────────────

def check_activity_batch(usernames):
    """Check a batch of users for recent activity. Returns set of active usernames."""
    global gh_core_remaining
    active = set()

    for username in usernames:
        try:
            r = requests.get(
                f"https://api.github.com/users/{username}/events/public",
                params={"per_page": 5},
                headers=GITHUB_HEADERS,
                timeout=15,
            )
            if "X-RateLimit-Remaining" in r.headers:
                gh_core_remaining = int(r.headers["X-RateLimit-Remaining"])

            if r.status_code == 404:
                continue
            if r.status_code == 403:
                reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(0, reset - time.time()) + 2
                if wait > 0 and wait < 3700:
                    print(f"    [rate limit: {wait:.0f}s]", end="", flush=True)
                    time.sleep(wait)
                    r = requests.get(
                        f"https://api.github.com/users/{username}/events/public",
                        params={"per_page": 5},
                        headers=GITHUB_HEADERS,
                        timeout=15,
                    )
                    if "X-RateLimit-Remaining" in r.headers:
                        gh_core_remaining = int(r.headers["X-RateLimit-Remaining"])
                else:
                    continue

            if r.status_code != 200:
                continue

            events = r.json()
            for event in events:
                created = event.get("created_at", "")[:10]
                if created >= ACTIVE_SINCE:
                    active.add(username)
                    break
        except Exception:
            pass

    return active


def filter_recently_active(gh_to_orcid):
    """Filter to users with at least 1 GitHub event in the past year."""
    print(f"\nStep 4: Filtering to users active since {ACTIVE_SINCE}...", flush=True)

    usernames = list(gh_to_orcid.keys())
    total = len(usernames)
    active_set = set()
    checked = 0

    for username in usernames:
        checked += 1
        result = check_activity_batch([username])
        active_set.update(result)

        if checked % 500 == 0:
            print(f"  Checked {checked:,}/{total:,}, {len(active_set):,} active, "
                  f"API remaining: {gh_core_remaining:,}", flush=True)

        if gh_core_remaining < 50:
            print(f"  Core API very low ({gh_core_remaining}), stopping activity check", flush=True)
            # Include remaining unchecked as "unknown"
            for u in usernames[checked:]:
                active_set.add(u)
            break

    active_users = {k: v for k, v in gh_to_orcid.items() if k in active_set}
    print(f"  {len(active_users):,} of {total:,} users are recently active "
          f"({len(active_users)/total*100:.1f}%)", flush=True)
    return active_users


# ── Step 5: Cross-reference with Claude commits ────────────────────

def cross_reference_claude(gh_to_orcid):
    """Stream Claude commits and find ORCID users."""
    print(f"\nStep 5: Cross-referencing with Claude Code commits...", flush=True)

    if not os.path.exists(COMMITS_FILE):
        print(f"  WARNING: {COMMITS_FILE} not found")
        return {}

    claude_orcid = {}
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
                key = username.lower()
                if key in gh_to_orcid:
                    canonical = gh_to_orcid[key]["github_username"]
                    if canonical not in claude_orcid:
                        claude_orcid[canonical] = {"dates": [], "repos": set(), "total": 0}
                    if date:
                        claude_orcid[canonical]["dates"].append(date)
                    if repo:
                        claude_orcid[canonical]["repos"].add(repo)
                    claude_orcid[canonical]["total"] += 1
                count += 1
                if count % 2_000_000 == 0:
                    print(f"  {count / 1e6:.0f}M commits, {len(claude_orcid)} ORCID matches...", flush=True)
                date = repo = None

    for u in claude_orcid.values():
        u["repos"] = sorted(u["repos"])
        u["dates"] = sorted(u["dates"])
        u["first_date"] = u["dates"][0] if u["dates"] else None
        u["last_date"] = u["dates"][-1] if u["dates"] else None

    print(f"  {count:,} commits scanned")
    print(f"  {len(claude_orcid)} ORCID users with Claude commits "
          f"({sum(u['total'] for u in claude_orcid.values()):,} commits)")
    return claude_orcid


# ── Summary and output ──────────────────────────────────────────────

def print_summary(gh_to_orcid, active_users, claude_overlap):
    """Print final summary with timeline analysis."""
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Total ORCID-linked GitHub users: {len(gh_to_orcid):,}")
    print(f"  Active in past year (>=1 GitHub event): {len(active_users):,}")
    print(f"  Active ORCID users with Claude Code: {len(claude_overlap):,} "
          f"({len(claude_overlap) / max(len(active_users), 1) * 100:.2f}%)")
    print(f"  Total Claude commits by ORCID users: "
          f"{sum(u['total'] for u in claude_overlap.values()):,}")

    if not claude_overlap:
        return

    # Weekly timeline
    weekly = defaultdict(set)
    weekly_commits = defaultdict(int)
    for username, data in claude_overlap.items():
        for d in data["dates"]:
            try:
                dt = datetime.strptime(d, "%Y-%m-%d")
                # ISO week start (Monday)
                week_start = dt - timedelta(days=dt.weekday())
                wk = week_start.strftime("%Y-%m-%d")
                weekly[wk].add(username)
                weekly_commits[wk] += 1
            except ValueError:
                pass

    print(f"\n  Weekly Claude activity by ORCID users:")
    print(f"  {'Week':>12s}  {'Users':>6s}  {'Commits':>8s}  {'Cumul Users':>12s}")
    cumulative = set()
    for week in sorted(weekly.keys()):
        cumulative |= weekly[week]
        print(f"    {week}  {len(weekly[week]):6d}  {weekly_commits[week]:8d}  {len(cumulative):12d}")

    # Monthly summary
    monthly = defaultdict(set)
    monthly_commits = defaultdict(int)
    for username, data in claude_overlap.items():
        for d in data["dates"]:
            m = d[:7]
            monthly[m].add(username)
            monthly_commits[m] += 1

    print(f"\n  Monthly Claude adoption by active ORCID users:")
    cumulative = set()
    for month in sorted(monthly.keys()):
        cumulative |= monthly[month]
        print(f"    {month}: {len(monthly[month]):4d} active, "
              f"{monthly_commits[month]:6d} commits, "
              f"{len(cumulative):4d} cumulative users")

    # Top users
    top = sorted(claude_overlap.items(), key=lambda x: -x[1]["total"])[:20]
    print(f"\n  Top ORCID users by Claude commits:")
    for username, data in top:
        info = active_users.get(username.lower(), gh_to_orcid.get(username.lower(), {}))
        orcid = info.get("orcid", "?")
        name = info.get("name", "")
        print(f"    {username:25s} {data['total']:5d} commits  "
              f"ORCID:{orcid}  {name}")

    # Commit distribution
    commit_counts = [d["total"] for d in claude_overlap.values()]
    print(f"\n  Commit distribution (n={len(commit_counts)}):")
    print(f"    median: {int(np.median(commit_counts))}")
    print(f"    mean:   {np.mean(commit_counts):.0f}")
    print(f"    p90:    {int(np.percentile(commit_counts, 90))}")
    print(f"    max:    {max(commit_counts)}")

    # Adoption rate over time (cumulative users / total active ORCID users)
    total_active = len(active_users)
    print(f"\n  Adoption rate over time (base: {total_active:,} active ORCID users):")
    cumulative = set()
    for month in sorted(monthly.keys()):
        cumulative |= monthly[month]
        rate = len(cumulative) / total_active * 100
        print(f"    {month}: {rate:.2f}%")


def load_existing():
    """Load existing results for delta mode."""
    if not os.path.exists(OUTPUT_FILE):
        return {}

    print(f"Loading existing results from {OUTPUT_FILE}...", flush=True)
    with open(OUTPUT_FILE) as f:
        data = json.load(f)

    # Reconstruct orcid_records dict from saved users
    existing = {}
    users = data.get("users", {})
    for username, info in users.items():
        orcid = info.get("orcid", "")
        if orcid and orcid not in existing:
            existing[orcid] = {
                "orcid": orcid,
                "name": info.get("name", ""),
                "github_usernames": [info.get("github_username", username)],
                "source_fields": info.get("source_fields", []),
            }

    print(f"  Loaded {len(existing):,} existing ORCID records", flush=True)
    return existing


def load_existing_mapping():
    """Load existing results directly as a GitHub mapping (skip ORCID fetch)."""
    if not os.path.exists(OUTPUT_FILE):
        return {}

    print(f"Loading existing GitHub mapping from {OUTPUT_FILE}...", flush=True)
    with open(OUTPUT_FILE) as f:
        data = json.load(f)

    gh_to_orcid = {}
    users = data.get("users", {})
    for username, info in users.items():
        gh_to_orcid[username.lower()] = {
            "github_username": info.get("github_username", username),
            "orcid": info.get("orcid", ""),
            "name": info.get("name", ""),
            "source_fields": info.get("source_fields", []),
        }

    print(f"  Loaded {len(gh_to_orcid):,} GitHub users", flush=True)
    return gh_to_orcid


def main():
    # Authenticate with ORCID API
    get_orcid_token()

    skip_orcid = "--skip-orcid" in sys.argv

    if skip_orcid:
        print("Skipping ORCID search/fetch (using existing data)...", flush=True)
        gh_to_orcid = load_existing_mapping()
        if not gh_to_orcid:
            print("ERROR: No existing data found. Run without --skip-orcid first.")
            sys.exit(1)
        # Also merge with previous GitHub-search results
        gh_to_orcid = merge_with_previous(gh_to_orcid)
    else:
        # Load existing for delta mode
        existing_records = load_existing()

        # Step 1: Search ORCID registry
        orcid_ids = search_orcid_records()

        # Step 2: Fetch records (delta)
        orcid_records = fetch_all_records(orcid_ids, existing_records)

        # Step 3: Build mapping
        gh_to_orcid = build_github_mapping(orcid_records)

        # Step 3b: Merge with previous GitHub-search results
        gh_to_orcid = merge_with_previous(gh_to_orcid)

    print(f"\n  Total ORCID-linked GitHub users: {len(gh_to_orcid):,}", flush=True)

    # Step 4: Filter by recent GitHub activity
    active_users = filter_recently_active(gh_to_orcid)

    # Step 5: Cross-reference with Claude commits (on active users only)
    claude_overlap = cross_reference_claude(active_users)

    # Annotate active users with Claude data
    for username, cdata in claude_overlap.items():
        key = username.lower()
        if key in active_users:
            active_users[key]["claude_commits"] = cdata["total"]
            active_users[key]["claude_repos"] = cdata["repos"]
            active_users[key]["first_claude_date"] = cdata["first_date"]
            active_users[key]["last_claude_date"] = cdata["last_date"]
            active_users[key]["claude_dates"] = cdata["dates"]

    # Save (include all users for future delta, but mark active)
    for k, v in gh_to_orcid.items():
        v["recently_active"] = k in active_users

    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "total_orcid_github_users": len(gh_to_orcid),
            "total_active": len(active_users),
            "total_with_claude": len(claude_overlap),
            "active_since": ACTIVE_SINCE,
            "scraped_at": datetime.now().isoformat(),
            "source": "ORCID public API (text:github.com) + previous GitHub search",
            "users": {v["github_username"]: v for v in gh_to_orcid.values()},
        }, f, indent=2, default=str)
    print(f"\nSaved {OUTPUT_FILE}")

    # Summary
    print_summary(gh_to_orcid, active_users, claude_overlap)


if __name__ == "__main__":
    main()
