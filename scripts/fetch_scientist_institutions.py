#!/usr/bin/env python3
"""
For each ORCID-linked active scientist, fetch the OpenAlex Author record and
extract the most recent institutional affiliation (and its country).

Output: data/scientist_institutions.json
{
  "github_username": {
    "orcid": "...",
    "openalex_id": "...",
    "institution_name": "Lawrence Berkeley National Laboratory",
    "institution_id": "I123456789",
    "country_code": "US",
    "all_affiliations": [...],
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
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
ORCID_FILE = DATA / "orcid_github_users.json"
OUT_FILE = DATA / "scientist_institutions.json"
EMAIL = "contact@charlesyang.io"
WORKERS = 8
CHECKPOINT_EVERY = 500


def fetch_author(orcid_id):
    url = (f"https://api.openalex.org/authors/orcid:{orcid_id}"
           f"?select=id,last_known_institutions,affiliations,works_count,cited_by_count"
           f"&mailto={EMAIL}")
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
    a = fetch_author(orcid)
    if a is None:
        return username, {"orcid": orcid, "found": False}
    last_known = a.get("last_known_institutions") or []
    affiliations = a.get("affiliations") or []
    primary = last_known[0] if last_known else None
    inst_name = (primary or {}).get("display_name") if primary else None
    inst_id = ((primary or {}).get("id") or "").replace("https://openalex.org/", "") if primary else None
    country = (primary or {}).get("country_code") if primary else None
    # Fall back to most-recent affiliation from full list
    if not inst_name and affiliations:
        first = (affiliations[0].get("institution") or {})
        inst_name = first.get("display_name")
        country = first.get("country_code")
        inst_id = (first.get("id") or "").replace("https://openalex.org/", "")
    return username, {
        "orcid": orcid,
        "openalex_id": (a.get("id") or "").replace("https://openalex.org/", ""),
        "institution_name": inst_name,
        "institution_id": inst_id,
        "country_code": country,
        "n_affiliations_listed": len(affiliations),
        "found": True,
    }


def main():
    with open(ORCID_FILE) as f:
        og = json.load(f)
    targets = [(u, info["orcid"]) for u, info in og["users"].items() if info.get("orcid")]
    print(f"Total ORCID-linked users: {len(targets):,}")

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
                print(f"\n  err on {futures[fut]}: {e}", flush=True)
                continue
            if i % 200 == 0:
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                eta = (len(todo) - i) / rate / 60 if rate else 0
                found = sum(1 for v in done.values() if v.get("found"))
                with_inst = sum(1 for v in done.values() if v.get("institution_name"))
                sys.stdout.write(f"\r[{i:>5}/{len(todo)}] rate={rate:.1f}/s found={found} with_inst={with_inst} ETA={eta:.0f}m   ")
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
    with_inst = sum(1 for v in done.values() if v.get("institution_name"))
    print(f"\n\nDone. Found {found:,}/{len(done):,} on OpenAlex; {with_inst:,} with institution data")


if __name__ == "__main__":
    main()
