#!/usr/bin/env python3
"""
Analyze GitHub users found in Claude Code commits.

For each unique user from Stage 1, queries their commit history before
2026-01-01 to understand prior AI-assisted coding behavior and repo
creation patterns. Uses the Search API for counting (much more efficient
than enumerating repos+commits).

Reads GitHub PAT from .github_token or GITHUB_TOKEN env var.

Usage:
  python3 analyze_users.py claude_commits.json
  python3 analyze_users.py claude_commits.json --limit 10
  python3 analyze_users.py claude_commits.json --resume
  python3 analyze_users.py claude_commits.json -o results.json
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
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, ".github_token")
CUTOFF_DATE = "2026-01-01"
BASELINE_START = "2025-07-01"  # 6-month baseline window
SEARCH_API = "https://api.github.com/search/commits"
USERS_API = "https://api.github.com/users"

# Rate limit management
SEARCH_DELAY = 2.1  # ~28 req/min, under 30/min cap for search
CORE_DELAY = 0.1    # Core API is 5000/hr, very generous
CHECKPOINT_EVERY = 10


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
        f"  Option 1: Create {TOKEN_FILE} with your PAT\n"
        "  Option 2: Set the GITHUB_TOKEN environment variable",
        file=sys.stderr,
    )
    sys.exit(1)


def api_get(url, token, accept=None):
    """Make an authenticated GET request to the GitHub API."""
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", accept or "application/vnd.github.v3+json")
    req.add_header("User-Agent", "claude-code-user-analyzer")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 403 and "rate limit" in body.lower():
            reset = e.headers.get("X-RateLimit-Reset")
            wait = 60
            if reset:
                wait = max(int(reset) - int(time.time()), 0) + 2
            return {"rate_limited": True, "retry_after": wait}, 403
        if e.code == 422:
            return {"total_count": 0, "items": []}, 422
        if e.code == 404:
            return None, 404
        if e.code in (500, 502, 503, 504):
            print(f"\n  Server error {e.code} — retrying in 30s...", file=sys.stderr, flush=True)
            time.sleep(30)
            return api_get(url, token, accept)
        print(f"  HTTP {e.code}: {body[:200]}", file=sys.stderr)
        return None, e.code
    except (urllib.error.URLError, TimeoutError, OSError, http.client.IncompleteRead) as e:
        print(f"\n  Network error: {e} — retrying in 10s...", file=sys.stderr, flush=True)
        time.sleep(10)
        return api_get(url, token, accept)


def search_commit_count(token, query):
    """Get total_count from a commit search query. Returns (count, capped)."""
    encoded = urllib.parse.quote(query, safe="")
    url = f"{SEARCH_API}?q={encoded}&per_page=1"

    time.sleep(SEARCH_DELAY)
    data, status = api_get(url, token, accept="application/vnd.github.cloak-preview+json")

    if data and data.get("rate_limited"):
        wait = data.get("retry_after", 60)
        print(f"\n  Search rate limited — waiting {wait}s...", flush=True)
        time.sleep(wait)
        return search_commit_count(token, query)

    if data is None:
        return 0, False

    total = data.get("total_count", 0)
    capped = total >= 1000
    return total, capped


def get_user_profile(token, username):
    """Fetch user profile from /users/{username}. Returns dict or None."""
    url = f"{USERS_API}/{urllib.parse.quote(username)}"
    time.sleep(CORE_DELAY)
    data, status = api_get(url, token)

    if data and data.get("rate_limited"):
        wait = data.get("retry_after", 60)
        print(f"\n  Core rate limited — waiting {wait}s...", flush=True)
        time.sleep(wait)
        return get_user_profile(token, username)

    if status == 404 or data is None:
        return None
    return data


def get_user_repos(token, username):
    """Fetch user's owned repos (paginated). Returns list of repo dicts."""
    repos = []
    page = 1
    while True:
        url = (
            f"{USERS_API}/{urllib.parse.quote(username)}/repos"
            f"?sort=created&direction=desc&per_page=100&page={page}&type=owner"
        )
        time.sleep(CORE_DELAY)
        data, status = api_get(url, token)

        if data and isinstance(data, dict) and data.get("rate_limited"):
            wait = data.get("retry_after", 60)
            print(f"\n  Core rate limited — waiting {wait}s...", flush=True)
            time.sleep(wait)
            continue

        if not isinstance(data, list) or not data:
            break

        repos.extend(data)
        if len(data) < 100:
            break
        page += 1

    return repos


def categorize_repos(repos):
    """Split repos into 2025 and 2026 buckets based on created_at."""
    repos_2025 = []
    repos_2026 = []
    for r in repos:
        created = r.get("created_at", "")
        if not created:
            continue
        year = created[:4]
        entry = {
            "name": r.get("full_name", r.get("name", "")),
            "language": r.get("language"),
            "created_at": created,
            "stars": r.get("stargazers_count", 0),
            "fork": r.get("fork", False),
        }
        if year == "2025":
            repos_2025.append(entry)
        elif year == "2026":
            repos_2026.append(entry)
    return repos_2025, repos_2026


def analyze_single_user(token, username, claude_commit_count_since, core_only=False, search_only=False):
    """Run all queries for a single user. Returns result dict or None on error.
    If core_only=True, skip Search API queries (commit counts) and only fetch
    profile + repos using Core API budget.
    If search_only=True, skip Core API queries and only fetch commit counts."""
    result = {
        "github_username": username,
        "claude_commits_since_cutoff": claude_commit_count_since,
    }

    if not core_only:
        # 1. Total commits in 6-month baseline window (Jul-Dec 2025)
        query_total = f"author:{username} author-date:{BASELINE_START}..{CUTOFF_DATE}"
        total_baseline, total_capped = search_commit_count(token, query_total)
        result["total_commits_baseline"] = total_baseline
        result["total_commits_capped"] = total_capped
        result["baseline_window"] = f"{BASELINE_START}..{CUTOFF_DATE}"

        # 2. Claude commits in 6-month baseline window
        query_claude = (
            f'author:{username} "Co-Authored-By: Claude" '
            f'"noreply@anthropic.com" author-date:{BASELINE_START}..{CUTOFF_DATE}'
        )
        claude_baseline, claude_capped = search_commit_count(token, query_claude)
        result["claude_commits_baseline"] = claude_baseline
        result["claude_commits_capped"] = claude_capped

        # Derived
        if total_baseline > 0:
            result["claude_pct_baseline"] = round(claude_baseline / total_baseline * 100, 2)
        else:
            result["claude_pct_baseline"] = 0.0

        # 3. Total commits since cutoff (so we can calculate Claude % post-cutoff)
        query_since = f"author:{username} author-date:>{CUTOFF_DATE}"
        total_since, since_capped = search_commit_count(token, query_since)
        result["total_commits_since_cutoff"] = total_since
        result["total_commits_since_capped"] = since_capped
        if total_since > 0:
            result["claude_pct_since_cutoff"] = round(
                claude_commit_count_since / total_since * 100, 2
            )
        else:
            result["claude_pct_since_cutoff"] = 0.0

    if search_only:
        return result

    # 3. User profile
    profile = get_user_profile(token, username)
    if profile:
        result["account_created"] = profile.get("created_at", "")
        result["public_repos"] = profile.get("public_repos", 0)
        result["followers"] = profile.get("followers", 0)
        result["name"] = profile.get("name", "")
        result["bio"] = profile.get("bio", "")
        result["company"] = profile.get("company", "")
        result["location"] = profile.get("location", "")
    else:
        result["account_created"] = ""
        result["public_repos"] = 0
        result["profile_error"] = True

    # 4. Repos by creation year
    repos = get_user_repos(token, username)
    repos_2025, repos_2026 = categorize_repos(repos)
    result["repos_created_2025"] = repos_2025
    result["repos_created_2025_count"] = len(repos_2025)
    result["repos_created_2026"] = repos_2026
    result["repos_created_2026_count"] = len(repos_2026)

    return result


def extract_users(commits_data):
    """Extract unique GitHub usernames and their commit counts from Stage 1 data."""
    user_counts = {}
    for c in commits_data.get("commits", []):
        username = c.get("github_username", "")
        if username:
            user_counts[username] = user_counts.get(username, 0) + 1
    return user_counts


def load_checkpoint(path):
    """Load previously saved analysis results for resuming."""
    if path and os.path.isfile(path):
        with open(path) as f:
            data = json.load(f)
        return data.get("users", {}), data.get("metadata", {})
    return {}, {}


def save_results(path, users_dict, metadata):
    """Save analysis results to JSON."""
    with open(path, "w") as f:
        json.dump(
            {
                "metadata": metadata,
                "total_users_analyzed": len(users_dict),
                "users": users_dict,
            },
            f,
            indent=2,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Analyze GitHub users from Claude Code commits"
    )
    parser.add_argument("input", help="Path to claude_commits.json from Stage 1")
    parser.add_argument(
        "--output", "-o", default="user_analysis.json",
        help="Output JSON file (default: user_analysis.json)",
    )
    parser.add_argument(
        "--limit", "-l", type=int, default=0,
        help="Limit analysis to N users (for testing)",
    )
    parser.add_argument(
        "--resume", "-r", action="store_true",
        help="Resume from last checkpoint in the output file",
    )
    parser.add_argument(
        "--core-only", action="store_true",
        help="Only fetch profile + repos (Core API). Skip Search API commit counts. "
             "Useful to run in parallel with Stage 1.",
    )
    parser.add_argument(
        "--search-only", action="store_true",
        help="Only fetch commit counts (Search API) for users already in the output. "
             "Use after a --core-only pass to fill in baseline stats.",
    )
    args = parser.parse_args()

    # Load input
    with open(args.input) as f:
        commits_data = json.load(f)

    user_counts = extract_users(commits_data)
    total_users = len(user_counts)
    print(f"Found {total_users} unique GitHub users in {args.input}")

    if args.limit > 0:
        # Take the top N by commit count for testing
        sorted_users = sorted(user_counts.items(), key=lambda x: -x[1])
        user_counts = dict(sorted_users[: args.limit])
        print(f"Limiting to {len(user_counts)} users (--limit {args.limit})")

    token = load_token()

    # Resume support
    results = {}
    metadata = {}
    if args.resume:
        results, metadata = load_checkpoint(args.output)
        if results:
            print(f"Resumed: {len(results)} users already analyzed")

    if args.search_only:
        # Search-only mode: fill in search fields for existing users
        if not results:
            results, metadata = load_checkpoint(args.output)
        if not results:
            print("No existing users found. Run --core-only first.", file=sys.stderr)
            sys.exit(1)

        # Find users missing search data
        to_analyze = [
            u for u in results
            if "total_commits_baseline" not in results[u]
            and u in user_counts
        ]
        print(f"Users needing search data: {len(to_analyze)}")
    else:
        already_done = set(results.keys())
        to_analyze = [u for u in user_counts if u not in already_done]

    print(f"Users to analyze: {len(to_analyze)}")
    print(f"Output: {args.output}")
    print()

    metadata.update({
        "input_file": args.input,
        "cutoff_date": CUTOFF_DATE,
        "total_unique_users": total_users,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    errors = 0
    for i, username in enumerate(to_analyze):
        total_target = len(to_analyze)
        pct = (i + 1) / total_target * 100
        sys.stdout.write(
            f"\r[{pct:5.1f}%] Analyzing {username:<30s} "
            f"({i+1}/{total_target})  errors: {errors}"
        )
        sys.stdout.flush()

        try:
            if args.search_only:
                # Only run search queries, merge into existing result
                search_result = analyze_single_user(
                    token, username, user_counts.get(username, 0), search_only=True
                )
                if search_result:
                    results[username].update(search_result)
            else:
                result = analyze_single_user(token, username, user_counts[username], core_only=args.core_only)
                if result:
                    results[username] = result
        except KeyboardInterrupt:
            print("\n\nInterrupted! Saving checkpoint...", file=sys.stderr)
            metadata["interrupted_at"] = datetime.now(timezone.utc).isoformat()
            save_results(args.output, results, metadata)
            print(f"Saved. Re-run with same flags + --resume to continue.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"\n  Error analyzing {username}: {e}", file=sys.stderr)
            errors += 1

        # Checkpoint
        if (i + 1) % CHECKPOINT_EVERY == 0:
            save_results(args.output, results, metadata)

    # Final save
    metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
    metadata["errors"] = errors
    save_results(args.output, results, metadata)

    print(f"\n\n{'=' * 60}")
    print(f"Done! Analyzed {len(results)} users ({errors} errors).")
    print(f"Results saved to {args.output}")

    # Quick summary
    if results:
        claude_baseline = [
            r["claude_commits_baseline"]
            for r in results.values()
            if "claude_commits_baseline" in r
        ]
        new_users = sum(1 for c in claude_baseline if c == 0)
        existing = sum(1 for c in claude_baseline if c > 0)
        print(f"\nBaseline window: {BASELINE_START} to {CUTOFF_DATE}")
        print(f"New to Claude Code (0 commits in baseline): {new_users}")
        print(f"Existing Claude Code users: {existing}")


if __name__ == "__main__":
    main()
