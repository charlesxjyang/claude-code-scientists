#!/usr/bin/env python3
"""
Post-process the per-record ORCID dump output (`orcid_full_baseline.jsonl`) to
produce the aggregated baselines used by the paper.

Two outputs:
  - `data/orcid_full_baseline_active.json`: aggregates restricted to records
    with at least one publication in 2024-2026 ("active scientists" in the
    paper's sense).
  - per-field tabulation if the Scopus crosswalk file exists; otherwise we
    fall back to country breakdown only.

Usage:
  python3 scripts/aggregate_orcid_dump.py
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
JSONL = DATA / "orcid_full_baseline.jsonl"
OUT_ACTIVE = DATA / "orcid_full_baseline_active.json"

# Try to import the Scopus journal-to-field lookup so we can bucket by field.
SCOPUS_LOOKUP = None
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from classify_orcid_scopus import build_scopus_lookup
    SCOPUS_LOOKUP, _ = build_scopus_lookup()
    print(f"Loaded Scopus crosswalk: {len(SCOPUS_LOOKUP):,} journal entries")
except Exception as e:
    print(f"Skipping field bucketing — Scopus crosswalk unavailable ({e})")


def field_for(journals):
    """Map a list of journal titles to a single 'middle'-level Scopus field
    (27 subfield buckets, matching OpenAlex's 26-field granularity)."""
    if not SCOPUS_LOOKUP:
        return None
    field_votes = Counter()
    for j in journals or []:
        norm = (j or "").lower().strip()
        info = SCOPUS_LOOKUP.get(norm)
        if info:
            for code in info:  # info is list of (middle, top) tuples
                middle = code[0] if isinstance(code, tuple) else code
                field_votes[middle] += 1
    if not field_votes:
        return None
    return field_votes.most_common(1)[0][0]


def main():
    if not JSONL.exists():
        sys.stderr.write(f"ERROR: {JSONL} not found. Run parse_orcid_dump.py first.\n")
        sys.exit(1)

    n_total = 0
    n_active = 0
    n_active_github = 0
    by_country_active_orcid = Counter()
    by_country_active_github = Counter()
    by_field_active_orcid = Counter()
    by_field_active_github = Counter()

    with open(JSONL) as f:
        for line in f:
            n_total += 1
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not rec.get("has_recent_pub"):
                continue
            n_active += 1
            has_gh = rec.get("has_github", False)
            if has_gh:
                n_active_github += 1
            country = rec.get("country")
            if country:
                by_country_active_orcid[country] += 1
                if has_gh:
                    by_country_active_github[country] += 1
            if SCOPUS_LOOKUP:
                field = field_for(rec.get("journals", []))
                if field:
                    by_field_active_orcid[field] += 1
                    if has_gh:
                        by_field_active_github[field] += 1
            if n_total % 500000 == 0:
                sys.stdout.write(
                    f"\r[{n_total:>9,}] active={n_active:,} active+github={n_active_github:,}"
                )
                sys.stdout.flush()

    print()
    print(f"\nTotal records:              {n_total:,}")
    print(f"Active (>=1 pub 2024-26):   {n_active:,} ({n_active/n_total*100:.1f}%)")
    print(f"Active with GitHub:         {n_active_github:,} ({n_active_github/n_active*100:.3f}%)")

    summary = {
        "n_total_records": n_total,
        "n_active": n_active,
        "n_active_with_github": n_active_github,
        "global_github_rate_active": n_active_github / n_active if n_active else 0,
        "by_country_active_orcid": dict(by_country_active_orcid),
        "by_country_active_github": dict(by_country_active_github),
        "by_field_active_orcid": dict(by_field_active_orcid),
        "by_field_active_github": dict(by_field_active_github),
    }
    with open(OUT_ACTIVE, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved: {OUT_ACTIVE}")

    print(f"\nGlobal P(GitHub | active ORCID) = {summary['global_github_rate_active']*100:.3f}%")
    print(f"  vs. 200k API sample:                    0.188%")

    if by_field_active_orcid:
        print("\nBy field (from dump):")
        for f, n in sorted(by_field_active_orcid.items(), key=lambda x: -x[1])[:15]:
            gh = by_field_active_github.get(f, 0)
            print(f"  {f:30s}  orcid={n:>8,}  github={gh:>5,}  ({gh/n*100:.3f}%)")

    print("\nBy country (top 15 by active ORCID count):")
    for c, n in sorted(by_country_active_orcid.items(), key=lambda x: -x[1])[:15]:
        gh = by_country_active_github.get(c, 0)
        print(f"  {c:6s}  orcid={n:>8,}  github={gh:>5,}  ({gh/n*100:.3f}%)")


if __name__ == "__main__":
    main()
