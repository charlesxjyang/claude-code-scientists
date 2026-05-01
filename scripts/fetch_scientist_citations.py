#!/usr/bin/env python3
"""
For each of our 16,010 active ORCID-linked scientists, fetch the matching
OpenAlex author record (by ORCID) and extract citation count + h-index.

Output: data/scientist_citations.json
{
  "github_username": {
    "orcid": "...",
    "openalex_id": "...",
    "cited_by_count": int,
    "works_count": int,
    "h_index": int,
    "i10_index": int,
    "found": True/False,
  },
  ...
}

Resumable: skips usernames already in the output file.
"""
import concurrent.futures
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
ORCID_FILE = DATA / "orcid_github_users.json"
OUT_FILE = DATA / "scientist_citations.json"

EMAIL = "charlesxjyang@gmail.com"
WORKERS = 10
CHECKPOINT_EVERY = 500


def fetch(orcid_id):
    url = f"https://api.openalex.org/authors/orcid:{orcid_id}?mailto={EMAIL}"
    req = urllib.request.Request(url, headers={"User-Agent": "claude-code-scientists/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429 or e.code >= 500:
                time.sleep(1 + attempt * 2)
                continue
            return None
        except Exception:
            time.sleep(1 + attempt * 2)
    return None


def process_one(args):
    username, orcid = args
    a = fetch(orcid)
    if a is None:
        return username, {"orcid": orcid, "found": False}
    summary = a.get("summary_stats", {}) or {}
    return username, {
        "orcid": orcid,
        "openalex_id": (a.get("id") or "").replace("https://openalex.org/", ""),
        "cited_by_count": a.get("cited_by_count", 0),
        "works_count": a.get("works_count", 0),
        "h_index": summary.get("h_index", 0),
        "i10_index": summary.get("i10_index", 0),
        "found": True,
    }


def main():
    with open(ORCID_FILE) as f:
        og = json.load(f)
    scientists = og["users"]
    targets = [(u, info["orcid"])
               for u, info in scientists.items()
               if info.get("orcid")]
    print(f"Total scientists with ORCID: {len(targets):,}")

    # Resume
    if OUT_FILE.exists():
        with open(OUT_FILE) as f:
            done = json.load(f)
    else:
        done = {}
    print(f"Already processed: {len(done):,}")

    todo = [t for t in targets if t[0] not in done]
    print(f"To fetch: {len(todo):,}\n")

    if not todo:
        return

    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(process_one, t): t[0] for t in todo}
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            try:
                u, res = fut.result()
                done[u] = res
            except Exception as e:
                print(f"\n  error on {futures[fut]}: {e}", flush=True)
                continue
            if i % 200 == 0:
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                eta = (len(todo) - i) / rate / 60 if rate else 0
                found = sum(1 for v in done.values() if v.get("found"))
                sys.stdout.write(f"\r[{i:>6}/{len(todo)}] rate={rate:.1f}/s found={found} ETA={eta:.0f}m   ")
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
    print(f"\n\nDone. Found {found:,}/{len(done):,} = {found/len(done)*100:.1f}% on OpenAlex")


if __name__ == "__main__":
    main()
