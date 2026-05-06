#!/usr/bin/env python3
"""
Pedigree extractor (pedigree-experiment branch).

Streams the ORCID 2024 summaries tarball and extracts education-summary and
employment-summary blocks for active scientists only (the ~16k whose GitHub
profile is in our cohort). Outputs data/scientist_pedigree.json.

Filtering by tar member name (which encodes the ORCID id) lets us skip
~99.9% of records cheaply, so a full pass takes a few minutes rather than
the 30+ minutes of the full parser.

Usage:
  python3 scripts/parse_orcid_pedigree.py \\
      data/orcid_dump/ORCID_2024_10_summaries.tar.gz
"""
import argparse
import json
import sys
import tarfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
ACTIVE_FILE = DATA / "active_scientists.json"
MAPPING_FILE = DATA / "orcid_github_users.json"
OUT_FILE = DATA / "scientist_pedigree.json"


def load_target_orcids():
    with open(ACTIVE_FILE) as f:
        active = json.load(f)["scientists"]
    with open(MAPPING_FILE) as f:
        mapping = json.load(f)["users"]
    orcid_to_user = {}
    for u in active:
        rec = mapping.get(u) or mapping.get(u.lower())
        if rec and rec.get("orcid"):
            orcid_to_user[rec["orcid"]] = u
    return orcid_to_user


def localtag(elem):
    return elem.tag.split("}", 1)[-1]


def get_year(elem):
    """Find the first <year> child anywhere under elem."""
    if elem is None:
        return None
    for sub in elem.iter():
        if localtag(sub) == "year" and sub.text:
            try:
                return int(sub.text.strip())
            except ValueError:
                return None
    return None


def parse_affiliation_block(elem):
    """Parse one education-summary or employment-summary element."""
    org_name = None
    org_country = None
    org_city = None
    disamb_id = None
    disamb_source = None
    role_title = None
    department = None
    start_year = None
    end_year = None

    for sub in elem.iter():
        tag = localtag(sub)
        if tag == "name" and org_name is None:
            # the <organization>/<name> is what we want; skip later <name> tags
            # by checking the parent path. We rely on document order: the
            # organization block usually comes before any nested <name>.
            org_name = (sub.text or "").strip() or None
        elif tag == "country" and org_country is None:
            org_country = (sub.text or "").strip() or None
        elif tag == "city" and org_city is None:
            org_city = (sub.text or "").strip() or None
        elif tag == "disambiguated-organization-identifier" and disamb_id is None:
            disamb_id = (sub.text or "").strip() or None
        elif tag == "disambiguation-source" and disamb_source is None:
            disamb_source = (sub.text or "").strip() or None
        elif tag == "role-title" and role_title is None:
            role_title = (sub.text or "").strip() or None
        elif tag == "department-name" and department is None:
            department = (sub.text or "").strip() or None
        elif tag == "start-date" and start_year is None:
            start_year = get_year(sub)
        elif tag == "end-date" and end_year is None:
            end_year = get_year(sub)

    return {
        "org_name": org_name,
        "org_country": org_country,
        "org_city": org_city,
        "disamb_id": disamb_id,
        "disamb_source": disamb_source,
        "role_title": role_title,
        "department": department,
        "start_year": start_year,
        "end_year": end_year,
    }


def parse_record(xml_bytes):
    """Return {'educations': [...], 'employments': [...]}."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    educations = []
    employments = []
    for elem in root.iter():
        tag = localtag(elem)
        if tag == "education-summary":
            educations.append(parse_affiliation_block(elem))
        elif tag == "employment-summary":
            employments.append(parse_affiliation_block(elem))
    return {"educations": educations, "employments": employments}


def orcid_from_name(name):
    """ORCID_2024_10_summaries/XXX/0000-0001-5067-0000.xml → '0000-0001-5067-0000'."""
    base = name.rsplit("/", 1)[-1]
    if base.endswith(".xml"):
        base = base[:-4]
    if len(base) == 19 and base.count("-") == 3:
        return base
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tarball", help="Path to ORCID_2024_10_summaries.tar.gz")
    ap.add_argument("--out", default=str(OUT_FILE))
    ap.add_argument("--print-every", type=int, default=200_000)
    args = ap.parse_args()

    orcid_to_user = load_target_orcids()
    targets = set(orcid_to_user.keys())
    print(f"Targeting {len(targets):,} ORCIDs of active scientists.", flush=True)

    out = {}
    started = time.time()
    n_seen = 0
    n_matched = 0

    with tarfile.open(args.tarball, "r:gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(".xml"):
                continue
            n_seen += 1
            orcid = orcid_from_name(member.name)
            if orcid is None or orcid not in targets:
                if n_seen % args.print_every == 0:
                    elapsed = time.time() - started
                    rate = n_seen / elapsed if elapsed else 0
                    sys.stdout.write(
                        f"\r[seen {n_seen:>10,}] rate={rate:>5.0f}/s  matched={n_matched:>5,}/{len(targets):,}  elapsed={elapsed/60:>4.1f}m  "
                    )
                    sys.stdout.flush()
                continue

            f = tar.extractfile(member)
            if f is None:
                continue
            rec = parse_record(f.read())
            if rec is None:
                continue
            rec["orcid"] = orcid
            rec["github_username"] = orcid_to_user[orcid]
            out[orcid_to_user[orcid]] = rec
            n_matched += 1

            if n_matched % 1000 == 0:
                elapsed = time.time() - started
                rate = n_seen / elapsed if elapsed else 0
                sys.stdout.write(
                    f"\r[seen {n_seen:>10,}] rate={rate:>5.0f}/s  matched={n_matched:>5,}/{len(targets):,}  elapsed={elapsed/60:>4.1f}m  "
                )
                sys.stdout.flush()

            if n_matched >= len(targets):
                break

    elapsed = time.time() - started
    print(f"\n\nDone in {elapsed/60:.1f} min. Matched {n_matched:,} / {len(targets):,} active scientists.")

    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
