#!/usr/bin/env python3
"""
Compute the three robustness checks reported in Online Appendix A.9.

  R1 — Alternative active-scientist definition: relax "≥1 pub since 2024"
       to "≥1 pub since 2023".
  R2 — Alternative data window: restrict commits to Oct 2025 – Jan 2026
       (three months) and recompute cohort adoption rate.
  R3 — Drop top decile of CC committer volume; recompute headline.
"""
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
ACTIVE = json.load(open(DATA / "active_scientists.json"))
ORCID_GH = json.load(open(DATA / "orcid_github_users.json"))

CC_PATH = "/Users/charl/Programming/github_claude/claude_commits_all.json"
print("Loading commits...")
with open(CC_PATH) as f:
    CC = json.load(f)
COMMITS = CC["commits"]
print(f"  {len(COMMITS):,} commits\n")

# Build username → first commit + commit count
user_commits = Counter()
user_first = {}
for c in COMMITS:
    u = (c.get("github_username") or "").lower()
    d = c.get("date", "")[:10]
    if not u or not d:
        continue
    user_commits[u] += 1
    if u not in user_first or d < user_first[u]:
        user_first[u] = d

cc_users = set(user_commits.keys())

# Headline numbers ----------------------------------------------------------
sci_set = {u.lower() for u in ACTIVE["scientists"]}
n_sci = len(sci_set)
n_adopt = len(sci_set & cc_users)
print("=" * 70)
print(f"HEADLINE  (replicated): {n_adopt:,} / {n_sci:,} = {n_adopt/n_sci*100:.2f}%")
print("=" * 70)


# ---------------------------------------------------------------------------
# R1 — relax pub-year filter from 2024 to 2023
# ---------------------------------------------------------------------------
print("\nR1 — relax active definition to 'pub since 2023'")
# We rebuild the active set from orcid_github_users.json since the saved
# active_scientists.json is already filtered.
# Each entry has 'recently_active', 'orcid', etc; we need profile data with
# latest_pub_year. That lives in orcid_profiles.json.
PROFILES_PATH = "/Users/charl/Programming/github_claude/orcid_profiles.json"
with open(PROFILES_PATH) as f:
    profiles = json.load(f)

# Cross-reference: github_username → orcid → profile.latest_pub_year
gh_to_orcid = {u: info["orcid"] for u, info in ORCID_GH["users"].items()
               if info.get("orcid")}
gh_to_latest = {}
for gh, orcid in gh_to_orcid.items():
    p = profiles.get(orcid) or profiles.get(gh)
    if p and p.get("latest_pub_year"):
        gh_to_latest[gh] = int(p["latest_pub_year"])

def cohort_pubs_since(year):
    """Active set with '≥1 pub since `year`' as the third filter.
    Approximates classify_active_scientists.py without re-fetching ORCID."""
    sci = set()
    for gh, info in ORCID_GH["users"].items():
        if not info.get("recently_active"):
            continue
        latest = gh_to_latest.get(gh)
        if latest and latest >= year:
            sci.add(gh.lower())
    return sci

r1_sci = cohort_pubs_since(2023)
r1_adopt = len(r1_sci & cc_users)
print(f"  Active: {len(r1_sci):,}  Adopters: {r1_adopt:,}  Rate: "
      f"{r1_adopt/max(1,len(r1_sci))*100:.2f}%")


# ---------------------------------------------------------------------------
# R2 — restrict commit window to Oct 2025 – Jan 2026 (three months)
# ---------------------------------------------------------------------------
print("\nR2 — three-month window (Oct 2025 – Jan 2026)")
restricted_users = set()
for c in COMMITS:
    d = c.get("date", "")[:10]
    if not d:
        continue
    if "2025-10-01" <= d < "2026-02-01":
        u = (c.get("github_username") or "").lower()
        if u:
            restricted_users.add(u)
r2_adopt = len(sci_set & restricted_users)
print(f"  Active: {n_sci:,}  Adopters: {r2_adopt:,}  Rate: "
      f"{r2_adopt/n_sci*100:.2f}%")


# ---------------------------------------------------------------------------
# R3 — drop the top decile of users by Claude-Code commit volume
# ---------------------------------------------------------------------------
print("\nR3 — drop top decile of CC commit volume per user")
# Decile cutoff among all CC users
counts_sorted = sorted(user_commits.values(), reverse=True)
n_top = max(1, len(counts_sorted) // 10)
top_threshold = counts_sorted[n_top - 1]  # 10th-percentile-from-top count
heavy_users = {u for u, n in user_commits.items() if n >= top_threshold}
non_heavy_cc_users = cc_users - heavy_users
r3_adopt = len(sci_set & non_heavy_cc_users)
print(f"  Heavy threshold: ≥{top_threshold} commits ({len(heavy_users):,} users dropped)")
print(f"  Active: {n_sci:,}  Adopters (non-heavy): {r3_adopt:,}  "
      f"Rate: {r3_adopt/n_sci*100:.2f}%")
print(f"  Difference from headline: {r3_adopt/n_sci*100 - n_adopt/n_sci*100:+.2f} percentage points")


# ---------------------------------------------------------------------------
# Print summary in appendix-ready format
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("APPENDIX-READY SUMMARY")
print("=" * 70)
print(f"Headline (active = pub since 2024, full window):  "
      f"{n_adopt:,}/{n_sci:,} = {n_adopt/n_sci*100:.2f}%")
print(f"R1 (active = pub since 2023):                      "
      f"{r1_adopt:,}/{len(r1_sci):,} = {r1_adopt/max(1,len(r1_sci))*100:.2f}%")
print(f"R2 (three-month window Oct 2025 – Jan 2026):       "
      f"{r2_adopt:,}/{n_sci:,} = {r2_adopt/n_sci*100:.2f}%")
print(f"R3 (drop top-decile heavy committers):             "
      f"{r3_adopt:,}/{n_sci:,} = {r3_adopt/n_sci*100:.2f}%")
