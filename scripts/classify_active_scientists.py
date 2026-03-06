#!/usr/bin/env python3
"""Build filtered dataset of active scientists (published 2024+).

1. Filter orcid_profiles.json to latest_pub_year >= 2024
2. Fetch journal names from ORCID API for those missing them
3. Classify field via Scopus journal matching (keyword fallback)
4. Cross-reference with Claude commit data
5. Save active_scientists.json + figures
"""

import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests

SCRIPT_DIR = "/Users/charl/Programming/github_claude"
PROFILES_FILE = os.path.join(SCRIPT_DIR, "orcid_profiles.json")
ORCID_USERS_FILE = os.path.join(SCRIPT_DIR, "orcid_github_users.json")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "active_scientists.json")

# Scopus data
TITLES_FILE = os.path.join(SCRIPT_DIR, "scopus_titles.tsv")
SUBJECT_AREAS_FILE = os.path.join(SCRIPT_DIR, "scopus_subject_areas.tsv")
ASJC_CODES_FILE = os.path.join(SCRIPT_DIR, "asjc_codes.csv")

# ORCID Auth
token_r = requests.post("https://orcid.org/oauth/token", data={
    "client_id": "APP-LY6BGRCJCDBGO0YL",
    "client_secret": "***REVOKED-SECRET***",
    "scope": "/read-public", "grant_type": "client_credentials",
}, headers={"Accept": "application/json"})
TOKEN = token_r.json()["access_token"]
SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"})


# ── Scopus lookup ─────────────────────────────────────────────────────

def build_scopus_lookup():
    print("Building Scopus journal lookup...", flush=True)
    asjc_to_field = {}
    with open(ASJC_CODES_FILE) as f:
        for row in csv.DictReader(f, delimiter=";"):
            asjc_to_field[int(row["Code"])] = {"top": row["Top"], "middle": row["Middle"]}

    title_to_ids = defaultdict(list)
    with open(TITLES_FILE) as f:
        for row in csv.DictReader(f, delimiter="\t"):
            title_to_ids[row["title_name"].lower().strip()].append(int(row["scopus_id"]))

    id_to_asjc = defaultdict(list)
    with open(SUBJECT_AREAS_FILE) as f:
        for row in csv.DictReader(f, delimiter="\t"):
            id_to_asjc[int(row["scopus_id"])].append(int(row["asjc_code"]))

    journal_to_fields = {}
    for norm_title, sids in title_to_ids.items():
        fields = set()
        for sid in sids:
            for code in id_to_asjc.get(sid, []):
                info = asjc_to_field.get(code) or asjc_to_field.get((code // 100) * 100)
                if info:
                    fields.add((info["middle"], info["top"]))
        if fields:
            journal_to_fields[norm_title] = list(fields)

    print(f"  {len(journal_to_fields):,} journals mapped", flush=True)
    return journal_to_fields


MIDDLE_TO_DISPLAY = {
    "Computer Science": "Computer Science", "Mathematics": "Mathematics",
    "Physics and Astronomy": "Physics & Astronomy", "Chemistry": "Chemistry",
    "Engineering": "Engineering", "Chemical Engineering": "Engineering",
    "Materials Science": "Materials Science",
    "Earth and Planetary Sciences": "Earth & Environmental",
    "Environmental Science": "Earth & Environmental", "Energy": "Engineering",
    "Agricultural and Biological Sciences": "Biology & Life Sciences",
    "Biochemistry, Genetics and Molecular Biology": "Biology & Life Sciences",
    "Immunology and Microbiology": "Biology & Life Sciences",
    "Neuroscience": "Neuroscience",
    "Pharmacology, Toxicology and Pharmaceutics": "Health Sciences",
    "Medicine": "Medicine & Health", "Nursing": "Medicine & Health",
    "Health Professions": "Medicine & Health", "Dentistry": "Medicine & Health",
    "Veterinary": "Biology & Life Sciences",
    "Social Sciences": "Social Sciences", "Arts and Humanities": "Arts & Humanities",
    "Psychology": "Social Sciences",
    "Economics, Econometrics and Finance": "Economics & Business",
    "Business, Management and Accounting": "Economics & Business",
    "Decision Sciences": "Computer Science", "General": "Multidisciplinary",
}

KEYWORD_RULES = {
    "Computer Science": [r"\bcomputer\b", r"\bmachine learning\b", r"\bAI\b", r"\bdata science\b",
                         r"\bsoftware\b", r"\bNLP\b", r"\bdeep learning\b", r"\binformatics\b"],
    "Physics & Astronomy": [r"\bphysics\b", r"\bastronom\b", r"\bastrophys\b", r"\bquantum\b",
                            r"\bcosmolog\b", r"\bparticle\b"],
    "Biology & Life Sciences": [r"\bbiolog\b", r"\bgenomic\b", r"\becolog\b", r"\bevolution\b",
                                r"\bbioinformat\b", r"\bmolecular\b", r"\bbiochem\b"],
    "Medicine & Health": [r"\bmedic\b", r"\bclinical\b", r"\bhealth\b", r"\bepidemiolog\b",
                          r"\bpharmac\b", r"\boncolog\b"],
    "Engineering": [r"\bengineering\b", r"\belectrical\b", r"\bmechanical\b", r"\brobotics\b"],
    "Earth & Environmental": [r"\bearth\b", r"\bgeolog\b", r"\bclimate\b", r"\benvironmental\b",
                              r"\bocean\b", r"\batmospher\b"],
    "Mathematics": [r"\bmathematic\b", r"\bstatistic\b", r"\boptimiz\b", r"\bbayesian\b"],
    "Social Sciences": [r"\bsocial\b", r"\bsociolog\b", r"\bpsycholog\b", r"\beducation\b",
                        r"\blinguistic\b", r"\bpolitical\b"],
    "Chemistry": [r"\bchemist\b", r"\bcatalys\b", r"\bpolymer\b", r"\bnanotech\b"],
    "Materials Science": [r"\bmaterials?\sscien\b", r"\bmetallurg\b", r"\bceramics?\b",
                          r"\bcomposites?\b", r"\bthin\sfilm\b", r"\bsemiconductor\b"],
    "Neuroscience": [r"\bneuroscien\b", r"\bneuroimag\b", r"\bneurolog\b", r"\bbrain\b",
                     r"\bcognitive\sscien\b", r"\bsynaptic\b"],
    "Economics & Business": [r"\beconom\b", r"\bfinance\b", r"\baccounting\b", r"\bmanagement\b",
                             r"\bmarket\b", r"\bbusiness\b", r"\bentrepreneur\b"],
    "Arts & Humanities": [r"\bhumanities\b", r"\bhistory\b", r"\bphilosoph\b", r"\bliterat\b",
                          r"\barchaeolog\b", r"\bmusic\b", r"\bdigital\shumanities\b"],
    "Health Sciences": [r"\bpublic\shealth\b", r"\bnursing\b", r"\brehabilitat\b",
                        r"\bphysiotherap\b", r"\bdentist\b", r"\boccupational\stherap\b"],
    "Multidisciplinary": [r"\bmultidisciplin\b", r"\binterdisciplin\b", r"\btransdisciplin\b"],
}
KEYWORD_COMPILED = {f: [re.compile(p, re.I) for p in ps] for f, ps in KEYWORD_RULES.items()}


def match_journal(journal_name, journal_to_fields):
    norm = journal_name.lower().strip()
    if norm in journal_to_fields:
        return journal_to_fields[norm]
    for strip in [" (online)", " (print)", " (electronic)", "the "]:
        cleaned = norm.replace(strip, "").strip()
        if cleaned in journal_to_fields:
            return journal_to_fields[cleaned]
    # Skip expensive prefix scan — exact match + cleanup is enough for 17K users
    return None


def classify_from_journals(journals, journal_to_fields):
    field_votes = Counter()
    for j in journals:
        fields = match_journal(j, journal_to_fields)
        if fields:
            for middle, top in fields:
                field_votes[MIDDLE_TO_DISPLAY.get(middle, middle)] += 1
    if not field_votes:
        return None
    return field_votes.most_common(1)[0][0]


def classify_from_keywords(keywords, current_role):
    text = " ".join(keywords) + " " + (current_role or "")
    scores = Counter()
    for field, patterns in KEYWORD_COMPILED.items():
        for p in patterns:
            scores[field] += len(p.findall(text))
    if scores:
        return scores.most_common(1)[0][0]
    return "Unknown"


# ── Fetch journals ────────────────────────────────────────────────────

def fetch_journals(orcid_id):
    """Fetch just journal names from /works."""
    journals = []
    for attempt in range(3):
        try:
            r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/works", timeout=20)
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt + 1)
                continue
            if r.status_code == 200:
                for group in r.json().get("group", []):
                    ws = group.get("work-summary", [{}])[0]
                    journal = ws.get("journal-title")
                    if journal and journal.get("value"):
                        journals.append(journal["value"])
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            time.sleep(2 ** attempt)
    return orcid_id, list(dict.fromkeys(journals))[:50]


# ── Main ──────────────────────────────────────────────────────────────

def main():
    # Load data
    profiles = json.load(open(PROFILES_FILE))
    orcid_users = json.load(open(ORCID_USERS_FILE))
    users_info = orcid_users.get("users", {})

    # Filter to active scientists: published 2024+ AND recently active on GitHub
    recently_active = {u for u, info in users_info.items() if info.get("recently_active")}
    active_pub = {u: p for u, p in profiles.items() if (p.get("latest_pub_year") or 0) >= 2024}
    active = {u: p for u, p in active_pub.items() if u in recently_active}
    print(f"Published 2024+: {len(active_pub):,}", flush=True)
    print(f"Also active on GitHub (past year): {len(active):,}", flush=True)
    print(f"  Filtered out {len(active_pub) - len(active):,} inactive GitHub accounts", flush=True)

    # Check which need journal fetch
    need_journals = {}
    have_journals = {}
    for username, profile in active.items():
        if profile.get("journals"):
            have_journals[username] = profile
        else:
            orcid = users_info.get(username, {}).get("orcid")
            if orcid:
                need_journals[orcid] = username
            else:
                have_journals[username] = profile  # No ORCID, skip

    print(f"  Already have journals: {len(have_journals):,}", flush=True)
    print(f"  Need journal fetch: {len(need_journals):,}", flush=True)

    # Fetch journals in batches
    if need_journals:
        # Load checkpoint
        journal_cache_file = os.path.join(SCRIPT_DIR, "journal_cache.json")
        journal_cache = {}
        if os.path.exists(journal_cache_file):
            journal_cache = json.load(open(journal_cache_file))
            print(f"  Loaded {len(journal_cache):,} cached journals", flush=True)

        to_fetch = {oid: u for oid, u in need_journals.items() if u not in journal_cache}
        print(f"  Fetching journals for {len(to_fetch):,} scientists...", flush=True)

        done = 0
        fetch_list = list(to_fetch.items())
        for batch_start in range(0, len(fetch_list), 100):
            batch = fetch_list[batch_start:batch_start + 100]
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(fetch_journals, oid): (oid, u) for oid, u in batch}
                for future in as_completed(futures):
                    oid, username = futures[future]
                    done += 1
                    try:
                        _, journals = future.result()
                        journal_cache[username] = journals
                    except Exception as e:
                        print(f"  Error {username}: {e}", file=sys.stderr, flush=True)

            if done % 1000 < 100:
                with open(journal_cache_file, "w") as f:
                    json.dump(journal_cache, f)
                print(f"  {done:,}/{len(to_fetch):,} fetched", flush=True)

        # Final save
        with open(journal_cache_file, "w") as f:
            json.dump(journal_cache, f)
        print(f"  Done fetching journals ({len(journal_cache):,} cached)", flush=True)

        # Merge journals into active profiles
        for username in need_journals.values():
            if username in journal_cache:
                active[username]["journals"] = journal_cache[username]

    # Build Scopus lookup and classify
    journal_to_fields = build_scopus_lookup()

    print(f"\nClassifying {len(active):,} scientists...", flush=True)
    results = {}
    for username, profile in active.items():
        journals = profile.get("journals", [])
        keywords = profile.get("keywords", [])
        current_role = profile.get("current_role", "")

        field = classify_from_journals(journals, journal_to_fields)
        method = "scopus"
        if field is None:
            field = classify_from_keywords(keywords, current_role)
            method = "keyword" if field != "Unknown" else "none"

        is_claude = users_info.get(username, {}).get("claude_commits", 0) > 0
        claude_commits = users_info.get(username, {}).get("claude_commits", 0)

        results[username] = {
            "field": field,
            "method": method,
            "n_publications": profile.get("n_publications", 0),
            "earliest_pub_year": profile.get("earliest_pub_year"),
            "latest_pub_year": profile.get("latest_pub_year"),
            "institutions": profile.get("institutions", []),
            "current_role": profile.get("current_role"),
            "claude_user": is_claude,
            "claude_commits": claude_commits,
        }

    # Stats
    claude = {u: r for u, r in results.items() if r["claude_user"]}
    baseline = {u: r for u, r in results.items() if not r["claude_user"]}
    print(f"\n{'='*70}", flush=True)
    print(f"ACTIVE SCIENTISTS DATASET", flush=True)
    print(f"{'='*70}", flush=True)
    print(f"  Total: {len(results):,}", flush=True)
    print(f"  Claude users: {len(claude):,} ({len(claude)/len(results)*100:.1f}%)", flush=True)
    print(f"  Baseline: {len(baseline):,}", flush=True)

    # Classification methods
    methods = Counter(r["method"] for r in results.values())
    print(f"\n  Classification methods:", flush=True)
    for m, n in methods.most_common():
        print(f"    {m}: {n:,} ({n/len(results)*100:.1f}%)", flush=True)

    # Field distribution
    claude_fields = Counter(r["field"] for r in claude.values())
    baseline_fields = Counter(r["field"] for r in baseline.values())
    all_fields = sorted(set(claude_fields) | set(baseline_fields),
                        key=lambda f: claude_fields.get(f, 0) + baseline_fields.get(f, 0), reverse=True)

    print(f"\n  {'Field':<30s} {'Claude':>8s} {'%':>6s} {'Baseline':>8s} {'%':>6s} {'Enrich':>7s}", flush=True)
    print(f"  {'-'*67}", flush=True)
    enrichments = {}
    for field in all_fields:
        c = claude_fields.get(field, 0)
        b = baseline_fields.get(field, 0)
        c_pct = c / len(claude) * 100 if claude else 0
        b_pct = b / len(baseline) * 100 if baseline else 0
        ratio = (c_pct / b_pct) if b_pct > 0 else (float('inf') if c_pct > 0 else 1.0)
        enrichments[field] = ratio
        marker = " >>>" if ratio > 1.3 else (" <<<" if ratio < 0.7 else "")
        print(f"  {field:<30s} {c:>8,} {c_pct:>5.1f}% {b:>8,} {b_pct:>5.1f}% {ratio:>6.2f}x{marker}", flush=True)

    # Seniority
    print(f"\n  Seniority (career years = 2026 - earliest_pub_year):", flush=True)
    for label, subset in [("Claude", claude), ("Baseline", baseline)]:
        years = [2026 - r["earliest_pub_year"] for r in subset.values() if r["earliest_pub_year"]]
        pubs = [r["n_publications"] for r in subset.values()]
        if years:
            print(f"    {label} (n={len(subset):,}): career median={int(np.median(years))}yr, "
                  f"mean={np.mean(years):.1f}yr, pubs median={int(np.median(pubs))}, "
                  f"mean={np.mean(pubs):.1f}", flush=True)

    # Top institutions
    print(f"\n  Top institutions (Claude users):", flush=True)
    inst_counter = Counter()
    for r in claude.values():
        for inst in r["institutions"][:1]:  # Primary institution only
            inst_counter[inst] += 1
    for inst, n in inst_counter.most_common(20):
        print(f"    {inst:<55s} {n}", flush=True)

    # Save
    output = {
        "filter": "latest_pub_year >= 2024",
        "total": len(results),
        "claude_users": len(claude),
        "baseline": len(baseline),
        "enrichments": enrichments,
        "scientists": results,
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {OUTPUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
