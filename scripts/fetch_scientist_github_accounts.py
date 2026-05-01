#!/usr/bin/env python3
"""
For each of the 16,010 active ORCID-linked scientists, fetch their GitHub
profile to get the account_created timestamp (proxy for time-on-GitHub).

Output: data/scientist_github_accounts.json
{
  "github_username": {
    "account_created": "2014-08-12T...",
    "public_repos": int,
    "followers": int,
    "found": True/False,
  },
  ...
}

GitHub Core API rate limit: 5000/hr authenticated.
"""
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
ACTIVE_FILE = DATA / "active_scientists.json"
USER_ANALYSIS_FILE = "/Users/charl/Programming/github_claude/user_analysis.json"
OUT_FILE = DATA / "scientist_github_accounts.json"

TOKEN_FILE = "/Users/charl/Programming/github_claude/.github_token"
WORKERS = 3   # lower to avoid GitHub's secondary "abuse detection" rate limit
PER_CALL_SLEEP = 0.10  # ~30 req/sec across pool; well under 5000/hr cap and below abuse trigger
CHECKPOINT_EVERY = 500

with open(TOKEN_FILE) as f:
    TOKEN = f.read().strip()


def fetch_user(username):
    url = f"https://api.github.com/users/{urllib.parse.quote(username)}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {TOKEN}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "claude-code-scientists/1.0")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 403:
                # rate limit
                reset = e.headers.get("X-RateLimit-Reset")
                wait = 60
                if reset:
                    wait = max(int(reset) - int(time.time()), 0) + 2
                print(f"\n  rate limited, sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            if e.code >= 500:
                time.sleep(1 + attempt * 2)
                continue
            return None
        except Exception:
            time.sleep(1 + attempt * 2)
    return None


def process_one(username):
    time.sleep(PER_CALL_SLEEP)
    p = fetch_user(username)
    if p is None:
        return username, {"found": False}
    return username, {
        "account_created": p.get("created_at", ""),
        "public_repos": p.get("public_repos", 0),
        "followers": p.get("followers", 0),
        "found": True,
    }


def main():
    with open(ACTIVE_FILE) as f:
        active = json.load(f)
    target_users = list(active["scientists"].keys())
    print(f"Active scientists: {len(target_users):,}")

    # Pre-load adopter records from user_analysis.json (already have account_created)
    pre = {}
    if os.path.isfile(USER_ANALYSIS_FILE):
        with open(USER_ANALYSIS_FILE) as f:
            ua = json.load(f)
        for u in target_users:
            r = ua.get("users", {}).get(u)
            if r and r.get("account_created"):
                pre[u] = {
                    "account_created": r["account_created"],
                    "public_repos": r.get("public_repos", 0),
                    "followers": r.get("followers", 0),
                    "found": True,
                }
        print(f"Pre-loaded from user_analysis: {len(pre):,}")

    # Resume
    if OUT_FILE.exists():
        with open(OUT_FILE) as f:
            done = json.load(f)
        for k, v in pre.items():
            if k not in done:
                done[k] = v
    else:
        done = dict(pre)

    todo = [u for u in target_users if u not in done]
    print(f"To fetch: {len(todo):,}\n")

    if not todo:
        return

    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(process_one, u): u for u in todo}
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            try:
                u, res = fut.result()
                done[u] = res
            except Exception as e:
                print(f"\n  err on {futures[fut]}: {e}", flush=True)
                continue
            if i % 100 == 0:
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                eta = (len(todo) - i) / rate / 60 if rate else 0
                found = sum(1 for v in done.values() if v.get("found"))
                sys.stdout.write(f"\r[{i:>5}/{len(todo)}] rate={rate:.1f}/s found={found} ETA={eta:.0f}m   ")
                sys.stdout.flush()
            if i % CHECKPOINT_EVERY == 0:
                tmp = OUT_FILE.with_suffix(".json.tmp")
                with open(tmp, "w") as f:
                    json.dump(done, f, indent=2)
                tmp.replace(OUT_FILE)

    tmp = OUT_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(done, f, indent=2)
    tmp.replace(OUT_FILE)

    found = sum(1 for v in done.values() if v.get("found"))
    print(f"\n\nDone. Found {found:,}/{len(done):,} on GitHub")


if __name__ == "__main__":
    main()
