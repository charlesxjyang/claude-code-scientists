#!/usr/bin/env python3
"""
ORCID → ORCID-with-GitHub baseline.

Input: data/openalex_sampled_orcids.txt (ORCIDs sampled from OpenAlex 2024-2026
active authors) + data/openalex_sampled_authors.json (country/field per author).

For each ORCID:
  - Fetch the public ORCID /person section (smaller than /record).
  - Check for a GitHub link in researcher-urls, biography, and external IDs.
  - Tally has_github yes/no.

Then aggregate: conditional P(GitHub | ORCID) globally, by country, by field.

Output: data/orcid_github_baseline.json

Uses ThreadPoolExecutor for parallelism (ORCID's polite cap is 24 req/sec).
Checkpoints every ~1000 records so we can resume.
"""

import concurrent.futures
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
ORCIDS_FILE = DATA / "openalex_sampled_orcids.txt"
AUTHORS_FILE = DATA / "openalex_sampled_authors.json"
OUT_FILE = DATA / "orcid_github_baseline.json"

ORCID_API = "https://pub.orcid.org/v3.0"
WORKERS = 12  # parallel HTTP requests
CHECKPOINT_EVERY = 1000

GITHUB_URL_RE = re.compile(
    r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)(?:/|$|\?|\s)",
    re.IGNORECASE,
)

# Common path prefixes that are NOT user names
NON_USERNAMES = {
    "orgs", "apps", "about", "pricing", "features", "settings", "marketplace",
    "topics", "trending", "explore", "search", "issues", "pulls", "notifications",
    "login", "logout", "join", "new", "organizations", "enterprise", "blog",
}


def orcid_person(orcid_id):
    """Fetch a public ORCID /person record as JSON. Returns dict or None."""
    url = f"{ORCID_API}/{orcid_id}/person"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "claude-code-scientists-baseline/1.0")
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


def extract_github(person):
    """Find GitHub usernames in an ORCID /person section."""
    if not person:
        return []
    users = set()

    urls = ((person.get("researcher-urls") or {}).get("researcher-url") or [])
    for u in urls:
        url = (u.get("url") or {}).get("value") or ""
        m = GITHUB_URL_RE.search(url)
        if m:
            users.add(m.group(1).lower())

    bio = ((person.get("biography") or {}).get("content") or "")
    for m in GITHUB_URL_RE.finditer(bio or ""):
        users.add(m.group(1).lower())

    eids = ((person.get("external-identifiers") or {}).get("external-identifier") or [])
    for eid in eids:
        etype = (eid.get("external-id-type") or "").lower()
        if "github" in etype:
            val = eid.get("external-id-value") or ""
            if "/" in val:
                m = GITHUB_URL_RE.search(val)
                if m:
                    users.add(m.group(1).lower())
            elif val and not val.startswith("http"):
                users.add(val.lower())

    users = {u for u in users if u and u not in NON_USERNAMES}
    return sorted(users)


def process_one(orcid):
    """Worker: fetch and parse one ORCID. Returns (orcid, result_dict)."""
    try:
        person = orcid_person(orcid)
        ghs = extract_github(person) if person else []
        return orcid, {
            "has_record": person is not None,
            "github_usernames": ghs,
            "has_github": len(ghs) > 0,
        }
    except Exception as e:
        return orcid, {
            "has_record": False, "github_usernames": [], "has_github": False,
            "error": str(e)[:100],
        }


def load_checkpoint():
    if OUT_FILE.exists():
        with open(OUT_FILE) as f:
            return json.load(f)
    return None


def save(state):
    tmp = OUT_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(OUT_FILE)


def aggregate(results, orcid_to_meta):
    by_country_orcid = Counter()
    by_country_github = Counter()
    by_field_orcid = Counter()
    by_field_github = Counter()
    total_orcid = 0
    total_github = 0
    for orcid, r in results.items():
        country, field = orcid_to_meta.get(orcid, (None, None))
        total_orcid += 1
        if r.get("has_github"):
            total_github += 1
        if country:
            by_country_orcid[country] += 1
            if r.get("has_github"):
                by_country_github[country] += 1
        if field:
            by_field_orcid[field] += 1
            if r.get("has_github"):
                by_field_github[field] += 1
    return {
        "global": {
            "orcid_sampled": total_orcid,
            "with_github": total_github,
            "rate": total_github / total_orcid if total_orcid else 0,
        },
        "by_country": {c: {
            "orcid": by_country_orcid[c],
            "github": by_country_github[c],
            "rate": by_country_github[c] / by_country_orcid[c] if by_country_orcid[c] else 0,
        } for c in by_country_orcid},
        "by_field": {f: {
            "orcid": by_field_orcid[f],
            "github": by_field_github[f],
            "rate": by_field_github[f] / by_field_orcid[f] if by_field_orcid[f] else 0,
        } for f in by_field_orcid},
    }


def main():
    with open(ORCIDS_FILE) as f:
        orcids = [line.strip() for line in f if line.strip()]
    with open(AUTHORS_FILE) as f:
        authors_meta = json.load(f)

    orcid_to_meta = {}
    for aid, m in authors_meta.items():
        if m.get("orcid"):
            orcid_to_meta[m["orcid"]] = (m.get("country"), m.get("field"))

    print(f"Input: {len(orcids):,} ORCIDs, {len(orcid_to_meta):,} with metadata", flush=True)
    print(f"Workers: {WORKERS}", flush=True)

    state = load_checkpoint()
    if state and state.get("records"):
        results = dict(state["records"])
        print(f"Resuming: {len(results):,} already processed", flush=True)
    else:
        results = {}

    to_do = [o for o in orcids if o not in results]
    print(f"Remaining: {len(to_do):,}\n", flush=True)

    started = time.time()
    completed_since_checkpoint = 0
    lock = threading.Lock()

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(process_one, orcid): orcid for orcid in to_do}
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            orcid, res = fut.result()
            with lock:
                results[orcid] = res
                completed_since_checkpoint += 1

            if i % 200 == 0:
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                eta_min = (len(to_do) - i) / rate / 60 if rate else 0
                with_gh = sum(1 for r in results.values() if r.get("has_github"))
                sys.stdout.write(
                    f"\r[{i:>7}/{len(to_do)}] rate={rate:.1f}/s  "
                    f"with_github={with_gh}  ETA={eta_min:.0f}m   "
                )
                sys.stdout.flush()

            if completed_since_checkpoint >= CHECKPOINT_EVERY:
                with lock:
                    save({
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "records": results,
                        "processed": len(results),
                    })
                    completed_since_checkpoint = 0

    # Final save + aggregate
    summary = aggregate(results, orcid_to_meta)
    save({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": results,
        "summary": summary,
        "processed": len(results),
    })

    g = summary["global"]
    print(f"\n\nGlobal: {g['with_github']:,} / {g['orcid_sampled']:,} = {g['rate']*100:.3f}%")
    print(f"\nBy country (top 25):")
    for c, d in sorted(summary["by_country"].items(), key=lambda x: -x[1]["orcid"])[:25]:
        print(f"  {c:6s}  orcid={d['orcid']:>6}  github={d['github']:>5}  ({d['rate']*100:5.2f}%)")
    print(f"\nBy field:")
    for f, d in sorted(summary["by_field"].items(), key=lambda x: -x[1]["orcid"]):
        print(f"  {f:45s}  orcid={d['orcid']:>6}  github={d['github']:>5}  ({d['rate']*100:5.2f}%)")


if __name__ == "__main__":
    main()
