#!/usr/bin/env python3
"""
Per-author baseline: of scientists active in 2024-2026, how many have ORCID?
By country and by field.

Method: sample random 2024-2026 works via OpenAlex's sample= parameter, extract
unique authors from authorships, tally each unique author once. Avoids the
work-weighted bias where a 5-pub/yr author counts 5x.

Caveats:
  - Authors with more recent-works are more likely to appear in the sample,
    but each unique author is counted exactly once in our tally. So the
    sample preferentially covers productive authors (which is actually fine
    for the "practicing scientists" definition you care about).
  - OpenAlex sample= max is 10,000 works per call; we do multiple independent
    samples with different seeds to expand coverage.
  - Country attribution uses institutions.country_codes from the authorship
    entry in the work (authors can have multiple countries across career).

Output: data/openalex_author_baseline.json
Also writes: data/openalex_sampled_orcids.txt (1 ORCID per line) for downstream
ORCID-profile sampling.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.openalex.org"
EMAIL = "charlesxjyang@gmail.com"
OUT_JSON = Path(__file__).parent.parent / "data" / "openalex_author_baseline.json"
OUT_ORCIDS = Path(__file__).parent.parent / "data" / "openalex_sampled_orcids.txt"
YEARS = "2024-2026"

# OpenAlex sample= does NOT paginate via cursor — each call returns ≤200
# regardless. So we do many independent sample calls with different seeds.
N_SAMPLES = 500  # 500 × 200 = 100,000 works, → ~200k unique authors
PER_PAGE = 200
BASE_SEED = 42

SELECT_FIELDS = "id,authorships,primary_topic"


def fetch(path, params):
    params = dict(params, mailto=EMAIL)
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            print(f"  HTTP {e.code}: {body}", flush=True)
            if e.code == 429 or e.code >= 500:
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except Exception as e:
            print(f"  retry {attempt}: {e}", flush=True)
            time.sleep(3)
    raise RuntimeError(f"Failed after retries: {url}")


def sample_one_batch(seed):
    """One sample call returns ≤200 random works for this seed."""
    data = fetch("works", {
        "filter": f"publication_year:{YEARS},type:article",
        "sample": PER_PAGE,
        "seed": seed,
        "per-page": PER_PAGE,
        "select": SELECT_FIELDS,
    })
    return data.get("results", [])


def extract_authors(works):
    """From works, build a dict of unique authors.
    Returns: {author_id: {orcid, countries, field}}"""
    authors = {}
    for w in works:
        # Field comes from the work's primary_topic; we'll use the majority
        # field per author at the end.
        pt = w.get("primary_topic") or {}
        field_name = (pt.get("field") or {}).get("display_name") or "Unknown"

        for auth in w.get("authorships", []) or []:
            author = auth.get("author") or {}
            aid = author.get("id")
            if not aid:
                continue

            orcid = author.get("orcid")  # full URL or None
            countries = auth.get("countries") or []
            # fall back to institutions.country_code if countries[] missing
            if not countries:
                for inst in auth.get("institutions") or []:
                    cc = inst.get("country_code")
                    if cc:
                        countries.append(cc)

            rec = authors.setdefault(aid, {
                "orcid": orcid,
                "countries": Counter(),
                "fields": Counter(),
                "appearances": 0,
            })
            # If we've seen this author but orcid was None, upgrade to orcid
            if rec["orcid"] is None and orcid:
                rec["orcid"] = orcid
            for cc in countries:
                rec["countries"][cc] += 1
            rec["fields"][field_name] += 1
            rec["appearances"] += 1
    return authors


def tally(authors):
    """Collapse per-author records into summary counts."""
    total = len(authors)
    with_orcid = sum(1 for r in authors.values() if r["orcid"])

    # Primary country = modal country in authorships
    # Primary field = modal field across the author's sampled works
    by_country_total = Counter()
    by_country_orcid = Counter()
    by_field_total = Counter()
    by_field_orcid = Counter()
    no_country = 0

    for r in authors.values():
        country = r["countries"].most_common(1)[0][0] if r["countries"] else None
        field = r["fields"].most_common(1)[0][0] if r["fields"] else "Unknown"
        has_orcid = bool(r["orcid"])

        if country:
            by_country_total[country] += 1
            if has_orcid:
                by_country_orcid[country] += 1
        else:
            no_country += 1
        by_field_total[field] += 1
        if has_orcid:
            by_field_orcid[field] += 1

    return {
        "total_authors": total,
        "with_orcid": with_orcid,
        "no_country": no_country,
        "by_country_total": dict(by_country_total),
        "by_country_orcid": dict(by_country_orcid),
        "by_field_total": dict(by_field_total),
        "by_field_orcid": dict(by_field_orcid),
    }


print(f"Sampling {N_SAMPLES} independent batches × {PER_PAGE} works = up to {N_SAMPLES*PER_PAGE:,} works")
print(f"Filter: publication_year:{YEARS}, type:article")
print()

all_works = []
seen_ids = set()
for i in range(N_SAMPLES):
    seed = BASE_SEED + i
    batch = sample_one_batch(seed)
    before = len(seen_ids)
    for w in batch:
        if w.get("id") and w["id"] not in seen_ids:
            seen_ids.add(w["id"])
            all_works.append(w)
    if (i + 1) % 10 == 0 or i == N_SAMPLES - 1:
        print(f"  batch {i+1}/{N_SAMPLES}: +{len(seen_ids)-before} new ({len(all_works):,} unique total)", flush=True)
    time.sleep(0.1)  # polite pool 10 req/sec

print(f"\nTotal unique works: {len(all_works)}")

print("\nExtracting unique authors from authorships...")
authors = extract_authors(all_works)
print(f"Unique authors: {len(authors):,}")

summary = tally(authors)
print(f"  with ORCID: {summary['with_orcid']:,} ({summary['with_orcid']/summary['total_authors']*100:.1f}%)")
print(f"  no country info: {summary['no_country']:,}")

# Output
OUT_JSON.parent.mkdir(exist_ok=True, parents=True)
out = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "method": "random sample of 2024-2026 articles, unique authors from authorships",
    "works_sampled": len(all_works),
    "unique_authors": summary["total_authors"],
    "summary": summary,
    # Include per-author records for audit (can be large; optional)
    # We omit the per-author dump for file size; keep aggregate only.
}
with open(OUT_JSON, "w") as f:
    json.dump(out, f, indent=2)
print(f"\nSaved: {OUT_JSON}")

# Also write sampled ORCIDs for downstream use
orcid_list = [r["orcid"].replace("https://orcid.org/", "") for r in authors.values() if r["orcid"]]
with open(OUT_ORCIDS, "w") as f:
    for o in orcid_list:
        f.write(o + "\n")
print(f"Saved: {OUT_ORCIDS} ({len(orcid_list):,} ORCIDs)")

# Per-author records with country + field, for the GitHub-baseline step
OUT_AUTHORS = OUT_JSON.parent / "openalex_sampled_authors.json"
per_author = {}
for aid, r in authors.items():
    orcid_id = r["orcid"].replace("https://orcid.org/", "") if r["orcid"] else None
    per_author[aid] = {
        "orcid": orcid_id,
        "country": r["countries"].most_common(1)[0][0] if r["countries"] else None,
        "field": r["fields"].most_common(1)[0][0] if r["fields"] else None,
        "appearances": r["appearances"],
    }
with open(OUT_AUTHORS, "w") as f:
    json.dump(per_author, f, indent=2)
print(f"Saved: {OUT_AUTHORS} ({len(per_author):,} records)")

# Print highlights
def rate(label, pairs_total, pairs_orcid, n=15):
    print(f"\n{label} (top {n} by total active authors in sample):")
    ordered = sorted(pairs_total.items(), key=lambda x: -x[1])
    for key, total in ordered[:n]:
        orcid = pairs_orcid.get(key, 0)
        pct = orcid / total * 100 if total else 0
        print(f"  {key:45s}  total={total:>7,}  orcid={orcid:>7,}  ({pct:5.1f}%)")


rate("ORCID penetration by country", summary["by_country_total"], summary["by_country_orcid"], n=25)
rate("ORCID penetration by field", summary["by_field_total"], summary["by_field_orcid"], n=26)
