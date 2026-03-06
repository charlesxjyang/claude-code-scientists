#!/usr/bin/env python3
"""Classify ORCID scientists by field using Scopus journal-to-subject-area mapping.

For each scientist, matches their ORCID publication journal names to the Scopus
journal database and looks up ASJC subject areas. Falls back to keyword/department
regex for scientists without publications or unmatched journals.

Also extracts seniority metrics (pub count, career years) and institution.
"""

import csv
import json
import os
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

import numpy as np
import requests

SCRIPT_DIR = "/Users/charl/Programming/github_claude"
ORCID_FILE = os.path.join(SCRIPT_DIR, "orcid_github_users.json")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "orcid_fields.json")

# Scopus data files
TITLES_FILE = os.path.join(SCRIPT_DIR, "scopus_titles.tsv")
SUBJECT_AREAS_FILE = os.path.join(SCRIPT_DIR, "scopus_subject_areas.tsv")
ASJC_CODES_FILE = os.path.join(SCRIPT_DIR, "asjc_codes.csv")

# ORCID auth
token_r = requests.post("https://orcid.org/oauth/token", data={
    "client_id": "APP-LY6BGRCJCDBGO0YL",
    "client_secret": "***REVOKED-SECRET***",
    "scope": "/read-public", "grant_type": "client_credentials",
}, headers={"Accept": "application/json"})
TOKEN = token_r.json()["access_token"]
SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"})


# ── Build Scopus lookup tables ──────────────────────────────────────

def build_scopus_lookup():
    """Build journal name -> list of (middle_category, top_category) mapping."""
    print("Building Scopus journal lookup...", flush=True)

    # 1. ASJC code -> (middle, top)
    asjc_to_field = {}
    with open(ASJC_CODES_FILE) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            code = int(row["Code"])
            asjc_to_field[code] = {
                "top": row["Top"],
                "middle": row["Middle"],
                "low": row["Low"],
            }

    # Also build from the dhimmel asjc-codes.tsv (has description -> code mapping)
    asjc_desc_to_code = {}
    with open(os.path.join(SCRIPT_DIR, "scopus_asjc_codes.tsv")) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            code = int(row["asjc_code"])
            asjc_desc_to_code[row["asjc_description"]] = code

    # 2. scopus_id -> title
    id_to_title = {}
    title_to_ids = defaultdict(list)  # normalized title -> [scopus_ids]
    with open(TITLES_FILE) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            sid = int(row["scopus_id"])
            title = row["title_name"]
            id_to_title[sid] = title
            # Normalize for matching
            title_to_ids[title.lower().strip()].append(sid)

    # 3. scopus_id -> [asjc_codes]
    id_to_asjc = defaultdict(list)
    with open(SUBJECT_AREAS_FILE) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            sid = int(row["scopus_id"])
            code = int(row["asjc_code"])
            id_to_asjc[sid].append(code)

    # 4. Build final: normalized_journal_name -> [field categories]
    journal_to_fields = {}
    for norm_title, sids in title_to_ids.items():
        fields = set()
        for sid in sids:
            for code in id_to_asjc.get(sid, []):
                info = asjc_to_field.get(code)
                if not info:
                    # Try the hundreds-level code (e.g., 1700 for 1701)
                    info = asjc_to_field.get((code // 100) * 100)
                if info:
                    fields.add((info["middle"], info["top"]))
        if fields:
            journal_to_fields[norm_title] = list(fields)

    print(f"  {len(journal_to_fields):,} journals mapped to subject areas")
    print(f"  {len(asjc_to_field)} ASJC codes")
    return journal_to_fields, asjc_to_field


def match_journal(journal_name, journal_to_fields):
    """Match a journal name to Scopus. Returns list of (middle, top) tuples or None."""
    norm = journal_name.lower().strip()

    # Exact match
    if norm in journal_to_fields:
        return journal_to_fields[norm]

    # Remove common suffixes/prefixes
    for strip in [" (online)", " (print)", " (electronic)", "the "]:
        cleaned = norm.replace(strip, "").strip()
        if cleaned in journal_to_fields:
            return journal_to_fields[cleaned]

    # Try prefix match (journal names often have subtitles)
    for stored in journal_to_fields:
        if stored.startswith(norm) or norm.startswith(stored):
            if abs(len(stored) - len(norm)) < 20:
                return journal_to_fields[stored]

    return None


# ── Map middle categories to our display labels ─────────────────────

MIDDLE_TO_DISPLAY = {
    # Physical Sciences
    "Computer Science": "Computer Science",
    "Mathematics": "Mathematics",
    "Physics and Astronomy": "Physics & Astronomy",
    "Chemistry": "Chemistry",
    "Engineering": "Engineering",
    "Chemical Engineering": "Engineering",
    "Materials Science": "Materials Science",
    "Earth and Planetary Sciences": "Earth & Environmental",
    "Environmental Science": "Earth & Environmental",
    "Energy": "Engineering",
    # Life Sciences
    "Agricultural and Biological Sciences": "Biology & Life Sciences",
    "Biochemistry, Genetics and Molecular Biology": "Biology & Life Sciences",
    "Immunology and Microbiology": "Biology & Life Sciences",
    "Neuroscience": "Neuroscience",
    "Pharmacology, Toxicology and Pharmaceutics": "Health Sciences",
    # Health Sciences
    "Medicine": "Medicine & Health",
    "Nursing": "Medicine & Health",
    "Health Professions": "Medicine & Health",
    "Dentistry": "Medicine & Health",
    "veterinary": "Biology & Life Sciences",
    # Social Sciences
    "Social Sciences": "Social Sciences",
    "Arts and Humanities": "Arts & Humanities",
    "Psychology": "Social Sciences",
    "Economics, Econometrics and Finance": "Economics & Business",
    "Business, Management and Accounting": "Economics & Business",
    "Decision Sciences": "Computer Science",
    # General
    "General": "Multidisciplinary",
}

# Fallback keyword rules for scientists without journal matches
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


# ── Fetch ORCID signals ─────────────────────────────────────────────

def fetch_orcid_data(orcid_id):
    """Fetch publications, keywords, employments, educations for one ORCID."""
    data = {
        "journals": [], "keywords": [], "departments": [],
        "institutions": [], "current_role": None,
        "n_publications": 0, "earliest_pub_year": None, "earliest_edu_year": None,
        "work_titles": [],
    }

    for attempt in range(3):
        try:
            # Works
            r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/works", timeout=15)
            if r.status_code == 429 or r.status_code == 503:
                time.sleep(2 ** attempt + 1)
                continue
            if r.status_code == 200:
                groups = r.json().get("group", [])
                data["n_publications"] = len(groups)
                for group in groups:
                    ws = group.get("work-summary", [{}])[0]
                    journal = ws.get("journal-title")
                    if journal and journal.get("value"):
                        data["journals"].append(journal["value"])
                    title_obj = ws.get("title") or {}
                    title = (title_obj.get("title") or {}).get("value", "")
                    if title:
                        data["work_titles"].append(title)
                    pub_date = ws.get("publication-date")
                    if pub_date and pub_date.get("year"):
                        try:
                            yr = int(pub_date["year"]["value"])
                            if 1950 < yr <= 2026:
                                if data["earliest_pub_year"] is None or yr < data["earliest_pub_year"]:
                                    data["earliest_pub_year"] = yr
                        except (ValueError, TypeError):
                            pass

            # Keywords
            r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/keywords", timeout=15)
            if r.status_code == 200:
                for kw in r.json().get("keyword", []):
                    data["keywords"].append(kw.get("content", ""))

            # Employments
            r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/employments", timeout=15)
            if r.status_code == 200:
                for i, group in enumerate(r.json().get("affiliation-group", [])):
                    for s in group.get("summaries", []):
                        emp = s.get("employment-summary", {})
                        dept = emp.get("department-name", "") or ""
                        role = emp.get("role-title", "") or ""
                        org = emp.get("organization", {}).get("name", "") or ""
                        if dept:
                            data["departments"].append(dept)
                        if org:
                            data["institutions"].append(org)
                            if i == 0 and not data["current_role"]:
                                data["current_role"] = f"{role}, {org}" if role else org

            # Educations
            r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/educations", timeout=15)
            if r.status_code == 200:
                for group in r.json().get("affiliation-group", []):
                    for s in group.get("summaries", []):
                        edu = s.get("education-summary", {})
                        dept = edu.get("department-name", "") or ""
                        if dept:
                            data["departments"].append(dept)
                        start = edu.get("start-date")
                        if start and start.get("year"):
                            try:
                                yr = int(start["year"]["value"])
                                if data["earliest_edu_year"] is None or yr < data["earliest_edu_year"]:
                                    data["earliest_edu_year"] = yr
                            except (ValueError, TypeError):
                                pass

            break  # Success
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            time.sleep(2 ** attempt)

    return orcid_id, data


def classify_from_journals(journals, journal_to_fields):
    """Classify a scientist using their publication journals via Scopus lookup."""
    field_votes = Counter()

    matched = 0
    for j in journals:
        fields = match_journal(j, journal_to_fields)
        if fields:
            matched += 1
            for middle, top in fields:
                display = MIDDLE_TO_DISPLAY.get(middle, middle)
                field_votes[display] += 1

    if not field_votes:
        return None, 0, matched

    best = field_votes.most_common(1)[0]
    return best[0], best[1], matched


def classify_from_text(keywords, departments, work_titles):
    """Fallback: classify from keywords, departments, and titles via regex."""
    text = " ".join(keywords + departments + work_titles[:10])
    scores = Counter()
    for field, patterns in KEYWORD_COMPILED.items():
        for p in patterns:
            scores[field] += len(p.findall(text))

    if scores:
        best = scores.most_common(1)[0]
        return best[0], best[1]
    return "Unknown", 0


def classify_scientist(data, journal_to_fields):
    """Classify a scientist: try Scopus journal lookup first, then keyword fallback."""
    field, score, n_matched = classify_from_journals(data["journals"], journal_to_fields)
    method = "scopus"

    if field is None or score == 0:
        field, score = classify_from_text(data["keywords"], data["departments"],
                                          data["work_titles"])
        method = "keyword" if field != "Unknown" else "none"

    return field, method


# ── Main ─────────────────────────────────────────────────────────────

def main():
    # Build Scopus lookup
    journal_to_fields, asjc_to_field = build_scopus_lookup()

    # Load ORCID users
    with open(ORCID_FILE) as f:
        orcid_data = json.load(f)

    users = orcid_data.get("users", {})
    claude_scientists = {u: i for u, i in users.items() if i.get("orcid") and i.get("claude_commits", 0) > 0}
    all_with_orcid = {u: i for u, i in users.items() if i.get("orcid")}

    print(f"Claude-using scientists with ORCID: {len(claude_scientists):,}")

    # Sample baseline
    import random
    random.seed(42)
    non_claude = {u: i for u, i in all_with_orcid.items() if i.get("claude_commits", 0) == 0}
    sample_size = min(2000, len(non_claude))
    baseline_keys = random.sample(list(non_claude.keys()), sample_size)

    to_fetch = {}
    for u, i in claude_scientists.items():
        to_fetch[i["orcid"]] = u
    for u in baseline_keys:
        orcid = non_claude[u]["orcid"]
        if orcid not in to_fetch:
            to_fetch[orcid] = u

    print(f"Fetching {len(to_fetch):,} ORCID records ({len(claude_scientists)} Claude + {sample_size} baseline)...",
          flush=True)

    # Parallel fetch
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_orcid_data, oid): (oid, u) for oid, u in to_fetch.items()}
        done = 0
        for future in as_completed(futures):
            done += 1
            orcid_id, data = future.result()
            _, username = futures[future]
            results[username] = data
            if done % 500 == 0:
                print(f"  {done:,}/{len(to_fetch):,}", flush=True)

    print(f"  Done fetching", flush=True)

    # Classify
    classifications = {}
    for username, data in results.items():
        field, method = classify_scientist(data, journal_to_fields)
        classifications[username] = {
            "field": field,
            "method": method,
            "n_publications": data["n_publications"],
            "earliest_pub_year": data["earliest_pub_year"],
            "earliest_edu_year": data["earliest_edu_year"],
            "institutions": data["institutions"][:3],
            "current_role": data["current_role"],
            "n_journals_matched": len([j for j in data["journals"] if match_journal(j, journal_to_fields)]),
            "n_journals_total": len(data["journals"]),
        }

    # Analyze
    claude_fields = Counter()
    baseline_fields = Counter()
    claude_methods = Counter()
    baseline_methods = Counter()

    for username, cls in classifications.items():
        if username in claude_scientists:
            claude_fields[cls["field"]] += 1
            claude_methods[cls["method"]] += 1
        else:
            baseline_fields[cls["field"]] += 1
            baseline_methods[cls["method"]] += 1

    print(f"\n{'='*70}")
    print("FIELD DISTRIBUTION (Scopus-based)")
    print(f"{'='*70}")

    print(f"\n  Classification method (Claude users):")
    for m, n in claude_methods.most_common():
        print(f"    {m}: {n} ({n/sum(claude_methods.values())*100:.1f}%)")

    print(f"\n  Claude-using scientists (n={sum(claude_fields.values())}):")
    for field, count in claude_fields.most_common():
        pct = count / sum(claude_fields.values()) * 100
        print(f"    {field:30s} {count:4d} ({pct:5.1f}%)")

    print(f"\n  Baseline scientists (n={sum(baseline_fields.values())}):")
    for field, count in baseline_fields.most_common():
        pct = count / sum(baseline_fields.values()) * 100
        print(f"    {field:30s} {count:4d} ({pct:5.1f}%)")

    # Enrichment
    print(f"\n  Enrichment (Claude vs baseline):")
    all_fields = sorted(set(claude_fields.keys()) | set(baseline_fields.keys()))
    enrichments = {}
    for field in all_fields:
        c_pct = claude_fields.get(field, 0) / max(sum(claude_fields.values()), 1)
        b_pct = baseline_fields.get(field, 0) / max(sum(baseline_fields.values()), 1)
        ratio = c_pct / b_pct if b_pct > 0 else (float('inf') if c_pct > 0 else 1.0)
        enrichments[field] = ratio
        marker = ">>>" if ratio > 1.3 else ("<<<" if ratio < 0.7 else "   ")
        print(f"    {field:30s} {ratio:5.2f}x  "
              f"(Claude: {c_pct*100:5.1f}%, Base: {b_pct*100:5.1f}%) {marker}")

    # Seniority
    print(f"\n{'='*70}")
    print("SENIORITY")
    print(f"{'='*70}")

    def seniority_report(usernames, label):
        pubs = [classifications[u]["n_publications"] for u in usernames if u in classifications]
        earliest = [classifications[u]["earliest_pub_year"] for u in usernames
                    if u in classifications and classifications[u]["earliest_pub_year"]]
        career_years = [2026 - y for y in earliest]

        print(f"\n  {label} (n={len(usernames)}):")
        if pubs:
            print(f"    Pubs: median={int(np.median(pubs))}, mean={np.mean(pubs):.1f}, "
                  f"p90={int(np.percentile(pubs, 90))}")
        if career_years:
            print(f"    Career yrs: median={int(np.median(career_years))}, "
                  f"mean={np.mean(career_years):.1f}, p90={int(np.percentile(career_years, 90))}")
            bins = {"0-2 (early)": 0, "3-5": 0, "6-10": 0, "11-20": 0, "20+ (senior)": 0}
            for cy in career_years:
                if cy <= 2: bins["0-2 (early)"] += 1
                elif cy <= 5: bins["3-5"] += 1
                elif cy <= 10: bins["6-10"] += 1
                elif cy <= 20: bins["11-20"] += 1
                else: bins["20+ (senior)"] += 1
            for stage, n in bins.items():
                print(f"      {stage:20s} {n:4d} ({n/len(career_years)*100:5.1f}%)")
        return pubs, career_years

    c_pubs, c_careers = seniority_report(list(claude_scientists.keys()), "Claude users")
    b_pubs, b_careers = seniority_report(baseline_keys, "Baseline")

    # Institutions
    print(f"\n{'='*70}")
    print("TOP INSTITUTIONS (Claude users)")
    print(f"{'='*70}")
    inst_counter = Counter()
    for u in claude_scientists:
        if u in classifications:
            insts = classifications[u]["institutions"]
            if insts:
                inst_counter[insts[0]] += 1
    for inst, n in inst_counter.most_common(25):
        print(f"    {inst:55s} {n:3d}")

    # ── Plot ──────────────────────────────────────────────────────────
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.facecolor": "#0d1117", "axes.facecolor": "#161b22",
        "axes.edgecolor": "#30363d", "axes.labelcolor": "#e6edf3",
        "text.color": "#e6edf3", "xtick.color": "#8b949e",
        "ytick.color": "#8b949e", "grid.color": "#21262d", "font.size": 11,
    })

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. Field distribution
    ax = axes[0, 0]
    display_fields = [f for f, _ in claude_fields.most_common() if f != "Unknown"]
    c_pcts = [claude_fields.get(f, 0) / sum(claude_fields.values()) * 100 for f in display_fields]
    b_pcts = [baseline_fields.get(f, 0) / sum(baseline_fields.values()) * 100 for f in display_fields]
    x = np.arange(len(display_fields))
    w = 0.35
    ax.barh(x + w/2, c_pcts, w, color="#58a6ff", alpha=0.9, label="Claude users")
    ax.barh(x - w/2, b_pcts, w, color="#8b949e", alpha=0.7, label="Baseline")
    ax.set_yticks(x)
    ax.set_yticklabels(display_fields, fontsize=9)
    ax.set_xlabel("% of scientists")
    ax.set_title("Field Distribution (Scopus-based)", fontweight='bold')
    ax.legend(loc='lower right', facecolor='#161b22', edgecolor='#30363d', labelcolor='#e6edf3')
    ax.grid(True, alpha=0.3, axis='x')
    ax.invert_yaxis()

    # 2. Enrichment
    ax = axes[0, 1]
    enrich_fields = [f for f in display_fields if f in enrichments]
    ratios = [enrichments[f] for f in enrich_fields]
    colors = ['#58a6ff' if r >= 1 else '#f85149' for r in ratios]
    bars = ax.barh(enrich_fields, ratios, color=colors, alpha=0.8)
    ax.axvline(x=1.0, color='#e6edf3', linewidth=1, linestyle='--', alpha=0.5)
    ax.set_xlabel("Enrichment (Claude / Baseline)")
    ax.set_title("Claude Adoption by Field", fontweight='bold')
    ax.grid(True, alpha=0.3, axis='x')
    ax.invert_yaxis()
    for bar, ratio in zip(bars, ratios):
        ax.text(bar.get_width() + 0.02, bar.get_y() + bar.get_height()/2,
                f'{ratio:.2f}x', va='center', fontsize=9, color='#e6edf3')

    # 3. Career years
    ax = axes[1, 0]
    if c_careers and b_careers:
        bins_r = list(range(0, 42, 2))
        ax.hist(c_careers, bins=bins_r, alpha=0.7, color='#58a6ff', label='Claude', density=True)
        ax.hist(b_careers, bins=bins_r, alpha=0.5, color='#8b949e', label='Baseline', density=True)
        ax.set_xlabel("Career years (2026 - first publication)")
        ax.set_ylabel("Density")
        ax.set_title("Career Seniority", fontweight='bold')
        ax.legend(facecolor='#161b22', edgecolor='#30363d', labelcolor='#e6edf3')
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, 40)

    # 4. Pub count
    ax = axes[1, 1]
    if c_pubs and b_pubs:
        bins_p = [0, 1, 5, 10, 20, 50, 100, 500]
        c_h, _ = np.histogram(c_pubs, bins=bins_p)
        b_h, _ = np.histogram(b_pubs, bins=bins_p)
        c_h_pct = c_h / len(c_pubs) * 100
        b_h_pct = b_h / len(b_pubs) * 100
        labels = ["0", "1-4", "5-9", "10-19", "20-49", "50-99", "100+"]
        x = np.arange(len(labels))
        ax.bar(x - w/2, c_h_pct, w, color='#58a6ff', alpha=0.9, label='Claude')
        ax.bar(x + w/2, b_h_pct, w, color='#8b949e', alpha=0.7, label='Baseline')
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_xlabel("Publications")
        ax.set_ylabel("% of scientists")
        ax.set_title("Publication Count", fontweight='bold')
        ax.legend(facecolor='#161b22', edgecolor='#30363d', labelcolor='#e6edf3')
        ax.grid(True, alpha=0.3, axis='y')

    fig.suptitle("ORCID Scientists: Claude Code Users vs Baseline (Scopus classification)",
                 fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    fig.savefig(os.path.join(SCRIPT_DIR, "figures", "orcid_scopus_profiles.png"),
                dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close()
    print(f"\nSaved figures/orcid_scopus_profiles.png")

    # Save
    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "classifications": classifications,
            "claude_fields": dict(claude_fields),
            "baseline_fields": dict(baseline_fields),
            "enrichments": enrichments,
            "claude_methods": dict(claude_methods),
            "baseline_methods": dict(baseline_methods),
        }, f, indent=2)
    print(f"Saved {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
