#!/usr/bin/env python3
"""Classify ORCID scientists by research field using keywords, departments, and journals.

Fetches profile data from ORCID API and assigns a broad discipline using keyword matching.
"""

import json
import os
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SCRIPT_DIR = "/Users/charl/Programming/github_claude"
ORCID_FILE = os.path.join(SCRIPT_DIR, "orcid_github_users.json")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "orcid_fields.json")

# Auth
token_r = requests.post("https://orcid.org/oauth/token", data={
    "client_id": "APP-LY6BGRCJCDBGO0YL",
    "client_secret": "***REVOKED-SECRET***",
    "scope": "/read-public", "grant_type": "client_credentials",
}, headers={"Accept": "application/json"})
TOKEN = token_r.json()["access_token"]
HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# Field classification rules — order matters (first match wins for ambiguous terms)
FIELD_RULES = {
    "Computer Science": [
        r"\bcomputer science\b", r"\bcomputer engineering\b", r"\bsoftware\b",
        r"\bmachine learning\b", r"\bartificial intelligence\b", r"\bdeep learning\b",
        r"\bnatural language processing\b", r"\bnlp\b", r"\bdata science\b",
        r"\bcybersecurity\b", r"\bcomputer vision\b", r"\brobotics\b",
        r"\bhuman.computer interaction\b", r"\bhci\b", r"\binformatics\b",
        r"\bcomputing\b", r"\balgorithm\b", r"\bdistributed system\b",
        r"\bprogramming\b", r"\bneural network\b", r"\breinforcement learning\b",
        r"\bIEEE.*comput\b", r"\bACM\b", r"\barXiv.*cs\b",
    ],
    "Physics": [
        r"\bphysics\b", r"\bastrophysics\b", r"\bastronomy\b", r"\bcosmology\b",
        r"\bquantum\b", r"\bparticle physics\b", r"\bcondensed matter\b",
        r"\boptics\b", r"\bphotonics\b", r"\bhigh energy\b",
        r"\bPhys\. Rev\b", r"\bPhysical Review\b", r"\bAstrophys\b",
        r"\bMNRAS\b", r"\barXiv.*astro\b", r"\barXiv.*hep\b", r"\bCERN\b",
    ],
    "Biology / Life Sciences": [
        r"\bbiolog\b", r"\bbioinformatics\b", r"\bgenomics\b", r"\bgenetics\b",
        r"\becolog\b", r"\bevolution\b", r"\bneuroscien\b", r"\bmolecular\b",
        r"\bcell biology\b", r"\bmicrobiology\b", r"\bbiotechnol\b",
        r"\bproteomics\b", r"\btranscriptomics\b", r"\bbiochemist\b",
        r"\bimmunolog\b", r"\bphysiolog\b", r"\bzoolog\b", r"\bbotany\b",
        r"\bPLoS\b", r"\bNature.*Bio\b", r"\bBMC\b", r"\bLife Sci\b",
        r"\bbiodiversity\b", r"\bphylogen\b", r"\bmetagenom\b",
    ],
    "Medicine / Health": [
        r"\bmedicine\b", r"\bmedical\b", r"\bclinical\b", r"\bhealth\b",
        r"\bepidemiolog\b", r"\bpublic health\b", r"\bpharmac\b",
        r"\boncolog\b", r"\bcardio\b", r"\bneurolog\b", r"\bsurger\b",
        r"\bpatholog\b", r"\bradiol\b", r"\bpsychiatr\b",
        r"\bLancet\b", r"\bBMJ\b", r"\bJAMA\b", r"\bN Engl J Med\b",
        r"\bbiomedical\b", r"\bdiagnostic\b", r"\btherapeutic\b",
    ],
    "Chemistry": [
        r"\bchemist\b", r"\bchemical\b", r"\bmaterial science\b",
        r"\bpolymer\b", r"\bcatalys\b", r"\belectrochem\b",
        r"\bJ\. Am\. Chem\b", r"\bAngew\. Chem\b", r"\bChem\. Rev\b",
        r"\bnanotech\b", r"\bnanomaterial\b",
    ],
    "Earth / Environmental Sciences": [
        r"\bearth science\b", r"\bgeolog\b", r"\bgeophys\b", r"\bgeochem\b",
        r"\bclimate\b", r"\batmospher\b", r"\bocean\b", r"\bhydrolog\b",
        r"\benvironmental\b", r"\bseismolog\b", r"\bremote sensing\b",
        r"\bgeospatial\b", r"\bGIS\b", r"\bgeography\b",
        r"\bJ\. Geophys\b", r"\bGeophys\. Res\b", r"\bEarth\b",
    ],
    "Mathematics / Statistics": [
        r"\bmathematic\b", r"\bstatistic\b", r"\bapplied math\b",
        r"\boptimization\b", r"\bnumerical\b", r"\bstochastic\b",
        r"\bbayesian\b", r"\btopolog\b", r"\balgebra\b",
        r"\bJ\. Math\b", r"\bMath\. Program\b", r"\bSIAM\b",
    ],
    "Engineering": [
        r"\bengineering\b", r"\belectrical\b", r"\bmechanical\b",
        r"\bcivil engineer\b", r"\baerospace\b", r"\bsignal processing\b",
        r"\bcontrol system\b", r"\btelecommunic\b", r"\bIoT\b",
        r"\bIEEE\b", r"\bmanufactur\b",
    ],
    "Social Sciences": [
        r"\bsocial science\b", r"\bsociolog\b", r"\bpsycholog\b",
        r"\beconomic\b", r"\bpolitical science\b", r"\blinguistic\b",
        r"\banthropolog\b", r"\beducation\b", r"\bcognitive\b",
        r"\bdigital humanities\b", r"\bcommunication\b",
    ],
}

# Compile patterns
FIELD_PATTERNS = {}
for field, patterns in FIELD_RULES.items():
    FIELD_PATTERNS[field] = [re.compile(p, re.IGNORECASE) for p in patterns]


def classify_text(text):
    """Classify text into a field. Returns (field, score) or (None, 0)."""
    scores = Counter()
    for field, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            matches = pattern.findall(text)
            scores[field] += len(matches)
    if scores:
        best = scores.most_common(1)[0]
        return best[0], best[1]
    return None, 0


def fetch_orcid_signals(orcid_id):
    """Fetch keywords, departments, journal names, and seniority metrics."""
    signals = []
    seniority = {"n_publications": 0, "earliest_pub_year": None, "earliest_edu_year": None,
                  "institutions": [], "current_role": None}

    try:
        # Keywords
        r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/keywords", timeout=15)
        if r.status_code == 200:
            for kw in r.json().get("keyword", []):
                signals.append(("keyword", kw.get("content", "")))

        # Employments (department + role + institution)
        r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/employments", timeout=15)
        if r.status_code == 200:
            for i, group in enumerate(r.json().get("affiliation-group", [])):
                for s in group.get("summaries", []):
                    emp = s.get("employment-summary", {})
                    dept = emp.get("department-name", "") or ""
                    role = emp.get("role-title", "") or ""
                    org = emp.get("organization", {}).get("name", "") or ""
                    if dept:
                        signals.append(("department", dept))
                    if role:
                        signals.append(("role", role))
                    if org:
                        seniority["institutions"].append(org)
                        if i == 0 and not seniority["current_role"]:
                            seniority["current_role"] = f"{role}, {org}" if role else org

        # Educations (department + earliest year)
        r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/educations", timeout=15)
        if r.status_code == 200:
            for group in r.json().get("affiliation-group", []):
                for s in group.get("summaries", []):
                    edu = s.get("education-summary", {})
                    dept = edu.get("department-name", "") or ""
                    role = edu.get("role-title", "") or ""
                    if dept:
                        signals.append(("edu_dept", dept))
                    if role:
                        signals.append(("edu_role", role))
                    # Extract earliest education start year
                    start = edu.get("start-date")
                    if start and start.get("year"):
                        yr = int(start["year"]["value"])
                        if seniority["earliest_edu_year"] is None or yr < seniority["earliest_edu_year"]:
                            seniority["earliest_edu_year"] = yr

        # Works — journal names + count + earliest publication year
        r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/works", timeout=15)
        if r.status_code == 200:
            groups = r.json().get("group", [])
            seniority["n_publications"] = len(groups)
            for group in groups:
                ws = group.get("work-summary", [{}])[0]
                journal = ws.get("journal-title")
                if journal:
                    signals.append(("journal", journal.get("value", "")))
                title = ws.get("title", {}).get("title", {})
                if title:
                    signals.append(("work_title", title.get("value", "")))
                # Publication year
                pub_date = ws.get("publication-date")
                if pub_date and pub_date.get("year"):
                    try:
                        yr = int(pub_date["year"]["value"])
                        if yr > 1950 and yr <= 2026:
                            if seniority["earliest_pub_year"] is None or yr < seniority["earliest_pub_year"]:
                                seniority["earliest_pub_year"] = yr
                    except (ValueError, TypeError):
                        pass

    except Exception:
        pass

    return orcid_id, signals, seniority


def classify_scientist(signals):
    """Classify a scientist from their collected signals."""
    # Weight different signal types
    weights = {
        "keyword": 3,
        "department": 3,
        "edu_dept": 2,
        "role": 1,
        "edu_role": 1,
        "journal": 2,
        "work_title": 1,
    }

    field_scores = Counter()
    for signal_type, text in signals:
        field, score = classify_text(text)
        if field and score > 0:
            field_scores[field] += score * weights.get(signal_type, 1)

    if field_scores:
        best = field_scores.most_common(1)[0]
        # Also get all fields with scores
        return best[0], dict(field_scores)
    return "Unknown", {}


def main():
    # Load ORCID users with Claude commits
    with open(ORCID_FILE) as f:
        data = json.load(f)

    users = data.get("users", {})

    # Get all users who have Claude commits AND an ORCID
    claude_scientists = {}
    all_scientists = {}
    for username, info in users.items():
        orcid = info.get("orcid", "")
        if not orcid:
            continue
        all_scientists[username] = info
        if info.get("claude_commits", 0) > 0:
            claude_scientists[username] = info

    print(f"Total ORCID scientists with ORCID IDs: {len(all_scientists):,}")
    print(f"Claude-using scientists with ORCID IDs: {len(claude_scientists):,}")

    # Fetch signals for Claude users + a sample of non-Claude for comparison
    # First do all Claude users
    to_fetch = {}
    for username, info in claude_scientists.items():
        to_fetch[info["orcid"]] = username

    # Add a random sample of non-Claude scientists for baseline comparison
    import random
    random.seed(42)
    non_claude = {u: i for u, i in all_scientists.items()
                  if i.get("claude_commits", 0) == 0 and i.get("orcid")}
    sample_size = min(2000, len(non_claude))
    sample_keys = random.sample(list(non_claude.keys()), sample_size)
    for username in sample_keys:
        orcid = non_claude[username]["orcid"]
        if orcid not in to_fetch:
            to_fetch[orcid] = username

    print(f"\nFetching ORCID signals for {len(to_fetch):,} scientists "
          f"({len(claude_scientists):,} Claude + {sample_size:,} baseline)...")

    # Parallel fetch
    results = {}
    seniority_data = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_orcid_signals, oid): (oid, uname)
            for oid, uname in to_fetch.items()
        }

        done = 0
        for future in as_completed(futures):
            done += 1
            orcid_id, signals, seniority = future.result()
            _, username = futures[future]
            results[username] = signals
            seniority_data[username] = seniority

            if done % 200 == 0:
                print(f"  Fetched {done:,}/{len(to_fetch):,}", flush=True)

    print(f"  Done fetching signals")

    # Classify everyone
    classifications = {}
    for username, signals in results.items():
        field, scores = classify_scientist(signals)
        classifications[username] = {
            "field": field,
            "scores": scores,
            "n_signals": len(signals),
        }

    # Analyze Claude users vs baseline
    claude_fields = Counter()
    baseline_fields = Counter()
    for username, cls in classifications.items():
        if username in claude_scientists:
            claude_fields[cls["field"]] += 1
        else:
            baseline_fields[cls["field"]] += 1

    print(f"\n{'='*60}")
    print("FIELD DISTRIBUTION")
    print(f"{'='*60}")

    print(f"\n  Claude-using scientists (n={sum(claude_fields.values())}):")
    for field, count in claude_fields.most_common():
        pct = count / sum(claude_fields.values()) * 100
        print(f"    {field:35s} {count:4d} ({pct:5.1f}%)")

    print(f"\n  Baseline scientists (n={sum(baseline_fields.values())}):")
    for field, count in baseline_fields.most_common():
        pct = count / sum(baseline_fields.values()) * 100
        print(f"    {field:35s} {count:4d} ({pct:5.1f}%)")

    # Enrichment: which fields are over/under-represented in Claude users?
    print(f"\n  Enrichment (Claude vs baseline):")
    all_fields = set(claude_fields.keys()) | set(baseline_fields.keys())
    enrichments = {}
    for field in all_fields:
        claude_pct = claude_fields.get(field, 0) / max(sum(claude_fields.values()), 1)
        base_pct = baseline_fields.get(field, 0) / max(sum(baseline_fields.values()), 1)
        if base_pct > 0:
            ratio = claude_pct / base_pct
        else:
            ratio = float('inf') if claude_pct > 0 else 1.0
        enrichments[field] = ratio
        print(f"    {field:35s} {ratio:5.2f}x  "
              f"(Claude: {claude_pct*100:5.1f}%, Base: {base_pct*100:5.1f}%)")

    # ── Seniority analysis ──────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SENIORITY ANALYSIS")
    print(f"{'='*60}")

    import numpy as np

    def seniority_stats(usernames, label):
        pubs = [seniority_data[u]["n_publications"] for u in usernames if u in seniority_data]
        earliest = [seniority_data[u]["earliest_pub_year"] for u in usernames
                    if u in seniority_data and seniority_data[u]["earliest_pub_year"]]
        career_years = [2026 - y for y in earliest] if earliest else []

        print(f"\n  {label} (n={len(usernames)}):")
        if pubs:
            print(f"    Publications: median={int(np.median(pubs))}, "
                  f"mean={np.mean(pubs):.1f}, p90={int(np.percentile(pubs, 90))}")
        if career_years:
            print(f"    Career years (2026 - first pub): median={int(np.median(career_years))}, "
                  f"mean={np.mean(career_years):.1f}, p90={int(np.percentile(career_years, 90))}")

        # Bin by career stage
        if career_years:
            bins = {"0-2 yrs (early)": 0, "3-5 yrs": 0, "6-10 yrs": 0,
                    "11-20 yrs": 0, "20+ yrs (senior)": 0}
            for cy in career_years:
                if cy <= 2: bins["0-2 yrs (early)"] += 1
                elif cy <= 5: bins["3-5 yrs"] += 1
                elif cy <= 10: bins["6-10 yrs"] += 1
                elif cy <= 20: bins["11-20 yrs"] += 1
                else: bins["20+ yrs (senior)"] += 1
            total = sum(bins.values())
            print(f"    Career stage distribution:")
            for stage, n in bins.items():
                print(f"      {stage:25s} {n:4d} ({n/total*100:5.1f}%)")

        # Bin by publication count
        if pubs:
            bins = {"0 pubs": 0, "1-5": 0, "6-20": 0, "21-50": 0, "50+": 0}
            for p in pubs:
                if p == 0: bins["0 pubs"] += 1
                elif p <= 5: bins["1-5"] += 1
                elif p <= 20: bins["6-20"] += 1
                elif p <= 50: bins["21-50"] += 1
                else: bins["50+"] += 1
            total = sum(bins.values())
            print(f"    Publication count distribution:")
            for stage, n in bins.items():
                print(f"      {stage:25s} {n:4d} ({n/total*100:5.1f}%)")

        return pubs, career_years

    claude_users_list = [u for u in claude_scientists.keys() if u in seniority_data]
    baseline_users_list = [u for u in sample_keys if u in seniority_data]

    claude_pubs, claude_careers = seniority_stats(claude_users_list, "Claude-using scientists")
    base_pubs, base_careers = seniority_stats(baseline_users_list, "Baseline scientists")

    # Institution analysis
    print(f"\n{'='*60}")
    print("TOP INSTITUTIONS")
    print(f"{'='*60}")

    claude_insts = Counter()
    baseline_insts = Counter()
    for u in claude_users_list:
        for inst in seniority_data[u].get("institutions", [])[:1]:  # First (current) only
            claude_insts[inst] += 1
    for u in baseline_users_list:
        for inst in seniority_data[u].get("institutions", [])[:1]:
            baseline_insts[inst] += 1

    print(f"\n  Claude-using scientists — top institutions:")
    for inst, n in claude_insts.most_common(20):
        print(f"    {inst:50s} {n:3d}")

    print(f"\n  Baseline — top institutions:")
    for inst, n in baseline_insts.most_common(20):
        print(f"    {inst:50s} {n:3d}")

    # ── Plot ──────────────────────────────────────────────────────────
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.facecolor": "#0d1117",
        "axes.facecolor": "#161b22",
        "axes.edgecolor": "#30363d",
        "axes.labelcolor": "#e6edf3",
        "text.color": "#e6edf3",
        "xtick.color": "#8b949e",
        "ytick.color": "#8b949e",
        "grid.color": "#21262d",
        "font.size": 11,
    })

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. Field distribution — Claude vs baseline
    ax = axes[0, 0]
    fields_order = [f for f, _ in sorted(enrichments.items(), key=lambda x: -x[1]) if f != "Unknown"]
    claude_pcts = [claude_fields.get(f, 0) / sum(claude_fields.values()) * 100 for f in fields_order]
    base_pcts = [baseline_fields.get(f, 0) / sum(baseline_fields.values()) * 100 for f in fields_order]
    x = np.arange(len(fields_order))
    w = 0.35
    ax.barh(x + w/2, claude_pcts, w, color="#58a6ff", alpha=0.9, label="Claude users")
    ax.barh(x - w/2, base_pcts, w, color="#8b949e", alpha=0.7, label="Baseline")
    ax.set_yticks(x)
    ax.set_yticklabels([f.replace(" / ", "/\n") for f in fields_order], fontsize=9)
    ax.set_xlabel("% of scientists")
    ax.set_title("Field Distribution", fontweight='bold')
    ax.legend(loc='lower right', facecolor='#161b22', edgecolor='#30363d', labelcolor='#e6edf3')
    ax.grid(True, alpha=0.3, axis='x')
    ax.invert_yaxis()

    # 2. Enrichment ratios
    ax = axes[0, 1]
    ratios = [enrichments.get(f, 1.0) for f in fields_order]
    colors = ['#58a6ff' if r >= 1 else '#f85149' for r in ratios]
    bars = ax.barh(fields_order, ratios, color=colors, alpha=0.8)
    ax.axvline(x=1.0, color='#e6edf3', linewidth=1, linestyle='--', alpha=0.5)
    ax.set_xlabel("Enrichment ratio (Claude / Baseline)")
    ax.set_title("Claude Adoption Enrichment by Field", fontweight='bold')
    ax.set_yticklabels([f.replace(" / ", "/\n") for f in fields_order], fontsize=9)
    ax.grid(True, alpha=0.3, axis='x')
    ax.invert_yaxis()
    for bar, ratio in zip(bars, ratios):
        ax.text(bar.get_width() + 0.03, bar.get_y() + bar.get_height()/2,
                f'{ratio:.2f}x', va='center', fontsize=9, color='#e6edf3')

    # 3. Career years distribution
    ax = axes[1, 0]
    if claude_careers and base_careers:
        bins_range = range(0, max(max(claude_careers), max(base_careers)) + 2, 2)
        ax.hist(claude_careers, bins=list(bins_range), alpha=0.7, color='#58a6ff',
                label='Claude users', density=True)
        ax.hist(base_careers, bins=list(bins_range), alpha=0.5, color='#8b949e',
                label='Baseline', density=True)
        ax.set_xlabel("Career years (2026 - first publication)")
        ax.set_ylabel("Density")
        ax.set_title("Career Seniority Distribution", fontweight='bold')
        ax.legend(facecolor='#161b22', edgecolor='#30363d', labelcolor='#e6edf3')
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, 40)

    # 4. Publication count distribution
    ax = axes[1, 1]
    if claude_pubs and base_pubs:
        bins_range = [0, 1, 5, 10, 20, 50, 100, 500]
        claude_h, _ = np.histogram(claude_pubs, bins=bins_range)
        base_h, _ = np.histogram(base_pubs, bins=bins_range)
        claude_h_pct = claude_h / len(claude_pubs) * 100
        base_h_pct = base_h / len(base_pubs) * 100
        labels = ["0", "1-4", "5-9", "10-19", "20-49", "50-99", "100+"]
        x = np.arange(len(labels))
        ax.bar(x - w/2, claude_h_pct, w, color='#58a6ff', alpha=0.9, label='Claude users')
        ax.bar(x + w/2, base_h_pct, w, color='#8b949e', alpha=0.7, label='Baseline')
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_xlabel("Number of publications")
        ax.set_ylabel("% of scientists")
        ax.set_title("Publication Count Distribution", fontweight='bold')
        ax.legend(facecolor='#161b22', edgecolor='#30363d', labelcolor='#e6edf3')
        ax.grid(True, alpha=0.3, axis='y')

    fig.suptitle("ORCID Scientist Profiles: Claude Code Users vs Baseline",
                 fontsize=15, fontweight='bold', y=1.02)
    plt.tight_layout()
    fig.savefig(os.path.join(SCRIPT_DIR, "figures", "orcid_scientist_profiles.png"),
                dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close()
    print(f"\nSaved figures/orcid_scientist_profiles.png")

    # Save
    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "classifications": classifications,
            "seniority": {u: s for u, s in seniority_data.items()},
            "claude_fields": dict(claude_fields),
            "baseline_fields": dict(baseline_fields),
            "enrichments": enrichments,
        }, f, indent=2)
    print(f"Saved {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
