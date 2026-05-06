#!/usr/bin/env python3
"""
EXPLORATORY — not used by the current paper.

Fetches each active scientist's earliest public GitHub commit via the
Search API as an alternative "started coding" timestamp. The published
paper uses GitHub account-creation date (from
fetch_scientist_github_accounts.py) as the coding-tenure signal, since
the Search API is rate-limited and produces partial coverage. This
script is kept for future analyses that may benefit from the cleaner
first-commit signal.

Output: data/scientist_first_commit.json
"""
import json, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
ACTIVE = DATA / "active_scientists.json"
OUT = DATA / "scientist_first_commit.json"
TOKEN = open("/Users/charl/Programming/github_claude/.github_token").read().strip()
DELAY = 2.1  # GitHub Search API: 30/min cap → 2s/call

API = "https://api.github.com/search/commits"

def fetch(username):
    q = f"author:{username}"
    url = f"{API}?q={urllib.parse.quote(q, safe='')}&per_page=1&sort=author-date&order=asc"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {TOKEN}")
    req.add_header("Accept", "application/vnd.github.cloak-preview+json")
    req.add_header("User-Agent", "claude-code-scientists/1.0")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
            items = d.get("items") or []
            if not items:
                return {"first_commit": None, "found": False}
            return {"first_commit": items[0].get("commit", {}).get("author", {}).get("date"), "found": True}
        except urllib.error.HTTPError as e:
            if e.code == 403 and "rate limit" in (e.read().decode() or "").lower():
                time.sleep(60)
                continue
            if e.code == 422:
                return {"first_commit": None, "found": False, "error": "422"}
            time.sleep(5 * (attempt + 1))
        except Exception:
            time.sleep(5 * (attempt + 1))
    return {"first_commit": None, "found": False, "error": "retries"}

def main():
    with open(ACTIVE) as f:
        active = json.load(f)
    targets = list(active["scientists"].keys())
    print(f"Targets: {len(targets):,}")
    if OUT.exists():
        with open(OUT) as f:
            done = json.load(f)
    else:
        done = {}
    todo = [u for u in targets if u not in done]
    print(f"To fetch: {len(todo):,}; ETA: {len(todo)*DELAY/3600:.1f}h\n")
    started = time.time()
    for i, u in enumerate(todo, 1):
        time.sleep(DELAY)
        done[u] = fetch(u)
        if i % 50 == 0:
            rate = i / max(1, time.time() - started)
            eta = (len(todo) - i) / max(0.01, rate) / 60
            found = sum(1 for v in done.values() if v.get("found"))
            sys.stdout.write(f"\r[{i:>5}/{len(todo)}] rate={rate:.2f}/s found={found} ETA={eta:.0f}m  ")
            sys.stdout.flush()
        if i % 100 == 0:
            tmp = OUT.with_suffix(".json.tmp")
            with open(tmp, "w") as f:
                json.dump(done, f, indent=2)
            tmp.replace(OUT)
    with open(OUT, "w") as f:
        json.dump(done, f, indent=2)
    found = sum(1 for v in done.values() if v.get("found"))
    print(f"\nDone. Found {found:,}/{len(done):,}")

if __name__ == "__main__":
    main()
