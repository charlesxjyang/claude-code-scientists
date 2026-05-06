#!/usr/bin/env python3
"""
Stream-parse the ORCID 2024 summaries tarball (~37 GB compressed) and extract
the metadata needed for the GitHub-link baseline:

  - ORCID id
  - researcher_urls list
  - biography text
  - external_identifiers (looking for github)
  - country (from primary affiliation)
  - has 2024-2026 publication (from activities-summary)
  - top journal/field signal (from activities-summary; for field bucketing)

Output: data/orcid_full_baseline.json (one line per ORCID, JSONL-style),
plus an aggregate summary at data/orcid_full_baseline_summary.json.

Usage:
  python3 scripts/parse_orcid_dump.py data/orcid_dump/ORCID_2024_10_summaries.tar.gz
"""
import argparse
import gzip
import json
import os
import re
import sys
import tarfile
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

GITHUB_URL_RE = re.compile(
    r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)(?:/|$|\?|\s)",
    re.IGNORECASE,
)

# Common ORCID XML namespaces (varies slightly across schema versions)
NS = {
    "common": "http://www.orcid.org/ns/common",
    "person": "http://www.orcid.org/ns/person",
    "rurl": "http://www.orcid.org/ns/researcher-url",
    "bio": "http://www.orcid.org/ns/personal-details",
    "extid": "http://www.orcid.org/ns/external-identifier",
    "address": "http://www.orcid.org/ns/address",
    "activities": "http://www.orcid.org/ns/activities",
    "work": "http://www.orcid.org/ns/work",
    "record": "http://www.orcid.org/ns/record",
    "employment": "http://www.orcid.org/ns/employment",
}


def extract_github(researcher_urls, biography, external_ids):
    """Find GitHub usernames via the same heuristics as the API-based baseline."""
    users = set()
    for url in researcher_urls:
        m = GITHUB_URL_RE.search(url or "")
        if m:
            users.add(m.group(1).lower())
    if biography:
        for m in GITHUB_URL_RE.finditer(biography):
            users.add(m.group(1).lower())
    for eid_type, eid_val in external_ids:
        if "github" in (eid_type or "").lower() and eid_val:
            if "/" in eid_val:
                m = GITHUB_URL_RE.search(eid_val)
                if m:
                    users.add(m.group(1).lower())
            elif not eid_val.startswith("http"):
                users.add(eid_val.lower())
    NON_USERNAMES = {"orgs", "apps", "about", "pricing", "features", "settings",
                     "marketplace", "topics", "trending"}
    return sorted(u for u in users if u and u not in NON_USERNAMES)


def parse_record(xml_bytes):
    """Parse a single ORCID record XML and return a dict with the fields we need.
    Returns None if the XML is malformed or empty."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    # ORCID id is in common:path or in element common:orcid-identifier > common:path
    orcid_id = None
    for elem in root.iter():
        tag = elem.tag.split("}", 1)[-1]
        if tag == "path" and elem.text and "-" in (elem.text or ""):
            orcid_id = elem.text.strip().lstrip("/")
            break
    if not orcid_id or len(orcid_id) < 19:
        # Fall back: extract from the source-orcid element
        for elem in root.iter():
            tag = elem.tag.split("}", 1)[-1]
            if tag == "uri" and elem.text and "orcid.org/" in elem.text:
                orcid_id = elem.text.split("orcid.org/")[-1].rstrip("/")
                break

    researcher_urls = []
    biography = ""
    external_ids = []
    countries = []
    pub_years = []
    journals = []

    for elem in root.iter():
        tag = elem.tag.split("}", 1)[-1]
        if tag == "url" and elem.text:
            researcher_urls.append(elem.text)
        elif tag == "content" and elem.text:
            # Biography content
            parent_tag = ""
            biography += " " + elem.text
        elif tag == "external-id-type":
            eid_type = (elem.text or "")
            # Find sibling external-id-value
            parent = root  # we'll fish it out below
            external_ids.append((eid_type, None))  # placeholder, fix below
        elif tag == "external-id-value":
            if external_ids and external_ids[-1][1] is None:
                external_ids[-1] = (external_ids[-1][0], elem.text or "")
        elif tag == "country" and elem.text:
            countries.append(elem.text.strip())
        elif tag == "publication-date":
            year_elem = elem.find("{*}year") if hasattr(elem, "find") else None
            for sub in elem.iter():
                stag = sub.tag.split("}", 1)[-1]
                if stag == "year" and sub.text:
                    try:
                        pub_years.append(int(sub.text))
                    except ValueError:
                        pass
                    break
        elif tag == "journal-title" and elem.text:
            journals.append(elem.text)

    has_recent_pub = any(y >= 2024 for y in pub_years)
    primary_country = countries[0] if countries else None
    github_users = extract_github(researcher_urls, biography.strip() or None, external_ids)

    return {
        "orcid": orcid_id,
        "github_usernames": github_users,
        "has_github": len(github_users) > 0,
        "country": primary_country,
        "has_recent_pub": has_recent_pub,
        "n_works": len(pub_years),
        "earliest_pub_year": min(pub_years) if pub_years else None,
        "latest_pub_year": max(pub_years) if pub_years else None,
        "journals": journals[:5],   # keep at most 5 for field signal
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tarball", help="Path to ORCID_2024_10_summaries.tar.gz")
    ap.add_argument("--out-jsonl", default="data/orcid_full_baseline.jsonl")
    ap.add_argument("--out-summary", default="data/orcid_full_baseline_summary.json")
    ap.add_argument("--limit", type=int, default=0,
                    help="Max records to process (0 = all). For testing.")
    ap.add_argument("--print-every", type=int, default=10000)
    args = ap.parse_args()

    out_path = Path(args.out_jsonl)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    n_records = 0
    n_with_orcid = 0
    n_with_github = 0
    n_recent = 0

    by_country_orcid = Counter()
    by_country_github = Counter()
    by_country_active_orcid = Counter()
    by_country_active_github = Counter()

    with open(out_path, "w") as fout, tarfile.open(args.tarball, "r:gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(".xml"):
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            xml_bytes = f.read()
            rec = parse_record(xml_bytes)
            if rec is None:
                continue

            n_records += 1
            if rec["orcid"]:
                n_with_orcid += 1
            if rec["has_github"]:
                n_with_github += 1
            if rec["has_recent_pub"]:
                n_recent += 1
                if rec["country"]:
                    by_country_active_orcid[rec["country"]] += 1
                    if rec["has_github"]:
                        by_country_active_github[rec["country"]] += 1
            if rec["country"]:
                by_country_orcid[rec["country"]] += 1
                if rec["has_github"]:
                    by_country_github[rec["country"]] += 1

            fout.write(json.dumps(rec) + "\n")

            if n_records % args.print_every == 0:
                elapsed = time.time() - started
                rate = n_records / elapsed if elapsed else 0
                sys.stdout.write(
                    f"\r[{n_records:>9,}] rate={rate:.0f}/s  "
                    f"github={n_with_github:>6,}  active(2024+)={n_recent:>9,}"
                )
                sys.stdout.flush()

            if args.limit and n_records >= args.limit:
                break

    elapsed = time.time() - started
    print(f"\n\nProcessed {n_records:,} records in {elapsed/60:.1f} min")
    print(f"  with GitHub link:                {n_with_github:>10,} ({n_with_github/n_records*100:.3f}%)")
    print(f"  with 2024+ publication (active): {n_recent:>10,} ({n_recent/n_records*100:.1f}%)")

    summary = {
        "source_file": os.path.basename(args.tarball),
        "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_records": n_records,
        "with_github_global": n_with_github,
        "active_orcid_global": n_recent,
        "by_country_all_orcid": dict(by_country_orcid),
        "by_country_github_among_all_orcid": dict(by_country_github),
        "by_country_active_orcid": dict(by_country_active_orcid),
        "by_country_github_among_active_orcid": dict(by_country_active_github),
    }
    with open(args.out_summary, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved per-record JSONL: {args.out_jsonl}")
    print(f"Saved summary:          {args.out_summary}")


if __name__ == "__main__":
    main()
