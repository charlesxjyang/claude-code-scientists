#!/usr/bin/env python3
"""
Smarter current-employer picker. Uses the ORCID dump's structured
employment-summary blocks rather than the position-zero shortcut, which
our crosswalk audit showed was sometimes the scientist's PhD institution
or a non-employment entry.

Priority order, per scientist:
  1. ORCID employment-summary entry with end_year is None
     (still-active employment). If multiple, pick the one with the
     latest start_year.
  2. ORCID employment-summary entry with the latest start_year
     (most recent employment, even if marked closed).
  3. OpenAlex last_known_institutions (paper-byline derived).
  4. orcid_institutions[0] (legacy ORCID-API scrape; the noisy default).
  5. No data.

Writes refined fields back into data/active_scientists.json:
  institutions = [chosen_name]
  country      = chosen_country
  institution_source = "orcid_emp_active" | "orcid_emp_recent" |
                       "openalex" | "orcid_listed" | "none"

Idempotent. Preserves orcid_institutions / orcid_country audit fields.
"""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
ACTIVE = DATA / "active_scientists.json"
PEDIGREE = DATA / "scientist_pedigree.json"
OA_INST = DATA / "scientist_institutions.json"


def pick_employment(employments):
    """Return (name, country, source_label) for the best 'current'
    employment, or (None, None, None)."""
    if not employments:
        return None, None, None
    open_ended = [e for e in employments if e.get("end_year") in (None, "")]
    if open_ended:
        best = sorted(open_ended, key=lambda e: e.get("start_year") or -1, reverse=True)[0]
        return best.get("org_name"), best.get("org_country"), "orcid_emp_active"
    best = sorted(employments, key=lambda e: e.get("start_year") or -1, reverse=True)[0]
    return best.get("org_name"), best.get("org_country"), "orcid_emp_recent"


def main():
    active = json.load(open(ACTIVE))
    pedigree = json.load(open(PEDIGREE))
    oa = json.load(open(OA_INST))

    counts = {"orcid_emp_active": 0, "orcid_emp_recent": 0,
              "openalex": 0, "orcid_listed": 0, "none": 0}

    for u, info in active["scientists"].items():
        ped = pedigree.get(u) or pedigree.get(u.lower())
        emp_name = emp_country = src = None
        if ped:
            emp_name, emp_country, src = pick_employment(ped.get("employments") or [])

        oa_rec = oa.get(u) or oa.get(u.lower()) or {}
        oa_name = oa_rec.get("institution_name")
        oa_country = oa_rec.get("country_code")

        orcid_first = (info.get("orcid_institutions") or [None])[0]
        orcid_listed_country = info.get("orcid_country")

        if emp_name:
            chosen_name, chosen_country, source = emp_name, emp_country, src
        elif oa_name:
            chosen_name, chosen_country, source = oa_name, oa_country, "openalex"
        elif orcid_first:
            chosen_name, chosen_country, source = orcid_first, orcid_listed_country, "orcid_listed"
        else:
            chosen_name, chosen_country, source = None, None, "none"

        info["institutions"] = [chosen_name] if chosen_name else []
        info["country"] = chosen_country
        info["institution_source"] = source
        counts[source] += 1

    with open(ACTIVE, "w") as f:
        json.dump(active, f, indent=2)

    n = sum(counts.values())
    print(f"Total scientists: {n:,}")
    for k, v in counts.items():
        print(f"  {k:<22} {v:>5,}  ({v/n*100:.1f}%)")


if __name__ == "__main__":
    main()
