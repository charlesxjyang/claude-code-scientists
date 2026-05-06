#!/usr/bin/env python3
"""
DEPRECATED — superseded by scripts/refine_institutions.py.

Earlier merge approach: take ORCID-listed affiliations[0] as primary,
fall back to OpenAlex last_known_institution. The audit in Appendix A.2
showed that ORCID-listed affiliations[0] was unreliable as a current-
employer signal (often pointed to the scientist's PhD institution or a
non-employment block). The newer refine_institutions.py uses the
structured ORCID employment-summary block (with end_year=None preferred)
as primary and is the canonical institution assignment for the paper.
This script is kept for archival reference and reproducibility of the
earlier draft's institution numbers.

Original behavior: prefer ORCID-listed affiliations[0]; fall back to
OpenAlex last_known_institution. Idempotent — recovers the original
ORCID values from audit fields if a prior merge has run.
"""
import json
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
ACTIVE = DATA / "active_scientists.json"
INST = DATA / "scientist_institutions.json"

with open(ACTIVE) as f:
    active = json.load(f)
with open(INST) as f:
    inst = json.load(f)

n_total = 0
n_oa = 0
n_orcid = 0
n_neither = 0

for u, info in active["scientists"].items():
    n_total += 1

    # Recover original ORCID-listed values (audit fields take precedence
    # in case a previous merge already overwrote `institutions`/`country`).
    orcid_insts = info.get("orcid_institutions")
    if orcid_insts is None:
        orcid_insts = info.get("institutions") or []
    orcid_country = info.get("orcid_country")
    if orcid_country is None:
        orcid_country = info.get("country")

    # OpenAlex fallback values
    rec = inst.get(u) or inst.get(u.lower())
    oa_inst = rec.get("institution_name") if rec else None
    oa_country = rec.get("country_code") if rec else None

    # Persist audit copies on every run
    info["orcid_institutions"] = orcid_insts
    info["orcid_country"] = orcid_country

    if orcid_insts:
        info["institutions"] = [orcid_insts[0]]
        info["country"] = orcid_country
        info["institution_source"] = "orcid"
        n_orcid += 1
    elif oa_inst:
        info["institutions"] = [oa_inst]
        info["country"] = oa_country
        info["institution_source"] = "openalex"
        n_oa += 1
    else:
        info["institutions"] = []
        info["country"] = None
        info["institution_source"] = "none"
        n_neither += 1

with open(ACTIVE, "w") as f:
    json.dump(active, f, indent=2)

print(f"Total scientists: {n_total:,}")
print(f"  Institution from ORCID (preferred):     {n_orcid:,} ({n_orcid/n_total*100:.1f}%)")
print(f"  Institution from OpenAlex (fallback):   {n_oa:,} ({n_oa/n_total*100:.1f}%)")
print(f"  No institution data:                    {n_neither:,} ({n_neither/n_total*100:.1f}%)")
