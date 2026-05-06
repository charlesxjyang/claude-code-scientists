#!/usr/bin/env python3
"""
Two additional controls beyond §3.5:

  Control A — Citation distributions by adopter status, conditioning on
  field AND career-stage bin (rather than just field). Tests whether the
  null citation result in Fig S1 holds within tighter cells.

  Control B — Lag between GitHub account creation and first publication.
  Identifies "coder-first", "concurrent", and "scientist-first" types and
  compares Claude Code adoption rates across the three.
"""
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy import stats

DATA = Path(__file__).parent.parent / "data"
ACTIVE = json.load(open(DATA / "active_scientists.json"))
ACCOUNTS = json.load(open(DATA / "scientist_github_accounts.json"))
CITATIONS = json.load(open(DATA / "scientist_citations.json"))

CURRENT_YEAR = 2026
SENIORITY_BINS = [
    ("Early (0-2y)",   0, 3),
    ("Postdoc (3-6y)", 3, 7),
    ("Mid (7-12y)",    7, 13),
    ("Senior (13-19y)", 13, 20),
    ("Veteran (20+y)", 20, 200),
]


def career_bin(years):
    for label, lo, hi in SENIORITY_BINS:
        if lo <= years < hi:
            return label
    return None


# ----- Control A: citations within (field × career-stage) cells ------------
print("=" * 70)
print("CONTROL A — Citations conditional on field × career stage")
print("=" * 70)

cells = defaultdict(lambda: {"adopt": [], "non": []})
for u, info in ACTIVE["scientists"].items():
    ey = info.get("earliest_pub_year")
    if not ey:
        continue
    cb = career_bin(CURRENT_YEAR - int(ey))
    if cb is None:
        continue
    rec = CITATIONS.get(u)
    if not rec or not rec.get("found"):
        continue
    field = info.get("field") or "Unknown"
    bucket = "adopt" if info.get("claude_user") else "non"
    cells[(field, cb)][bucket].append(rec.get("cited_by_count", 0))

# Top fields × career bins with sufficient adopter sample
print(f"{'Field':22s} {'Stage':18s} {'n_non':>6}{'n_adopt':>8} {'med_non':>9} {'med_adopt':>10} {'ratio':>6} {'KS p':>8}")
results = []
for (field, cb), b in cells.items():
    if len(b["adopt"]) < 4 or len(b["non"]) < 30:
        continue
    med_n = np.median(b["non"])
    med_a = np.median(b["adopt"])
    ratio = med_a / max(1, med_n)
    try:
        ks = stats.ks_2samp(b["non"], b["adopt"])
        p = ks.pvalue
    except Exception:
        p = float("nan")
    results.append((field, cb, len(b["non"]), len(b["adopt"]), med_n, med_a, ratio, p))
results.sort(key=lambda r: -r[3])
for r in results:
    field, cb, n_n, n_a, med_n, med_a, ratio, p = r
    print(f"{field[:22]:22s} {cb:18s} {n_n:>6} {n_a:>8} {med_n:>9.0f} {med_a:>10.0f} {ratio:>5.1f}× {p:>8.3f}")

n_cells = len(results)
n_sig = sum(1 for r in results if r[7] < 0.05)
print(f"\n{n_cells} cells with sufficient sample. {n_sig} cells with KS p<0.05.")

# Pooled within-cell test: stratified Mann-Whitney via aggregated rank-sums
# (Cochran-Mantel-Haenszel-style robustness check)
all_adopt = []
all_non = []
for (field, cb), b in cells.items():
    if len(b["adopt"]) >= 4 and len(b["non"]) >= 30:
        all_adopt.extend(b["adopt"])
        all_non.extend(b["non"])
mw = stats.mannwhitneyu(all_adopt, all_non, alternative="two-sided")
print(f"Pooled within-cell sample: med_adopt={np.median(all_adopt):.0f}, "
      f"med_non={np.median(all_non):.0f}, ratio={np.median(all_adopt)/max(1, np.median(all_non)):.2f}×, "
      f"Mann-Whitney 2-sided p = {mw.pvalue:.3f}")


# ----- Control B: account_created vs earliest_pub_year lag -----------------
print("\n" + "=" * 70)
print("CONTROL B — GitHub-account-vs-first-pub lag and adoption")
print("=" * 70)

# Lag = earliest_pub_year - github_account_year
# Negative lag = GitHub account predates first pub (coder-first)
# Positive lag = first pub predates GitHub account (scientist-first)
LAG_BINS = [
    ("Coder-first (≥3y before first pub)", -200, -3),
    ("Concurrent (within ±2y)",             -3,    3),
    ("Scientist-first (≥3y after first pub)", 3,  200),
]

def lag_bin(lag):
    for label, lo, hi in LAG_BINS:
        if lo <= lag < hi:
            return label
    return None


bucket_total = Counter()
bucket_adopt = Counter()
n_dropped = 0
for u, info in ACTIVE["scientists"].items():
    ey = info.get("earliest_pub_year")
    if not ey:
        n_dropped += 1
        continue
    acc = ACCOUNTS.get(u)
    if not acc or not acc.get("found"):
        n_dropped += 1
        continue
    ts = acc.get("account_created", "")
    try:
        gh_year = datetime.fromisoformat(ts.replace("Z", "+00:00")).year
    except Exception:
        n_dropped += 1
        continue
    lag = int(ey) - gh_year
    b = lag_bin(lag)
    if b is None:
        continue
    bucket_total[b] += 1
    if info.get("claude_user"):
        bucket_adopt[b] += 1

print(f"Sample: {sum(bucket_total.values()):,} scientists with both years; "
      f"{n_dropped:,} dropped (no year or no GH account match)\n")
print(f"{'Bucket':45s}{'n_total':>10}{'n_adopt':>10}{'rate':>8}{'95% CI':>16}")
for label, _, _ in LAG_BINS:
    n = bucket_total[label]
    a = bucket_adopt[label]
    rate = a / n if n else 0
    se = (rate * (1 - rate) / max(1, n)) ** 0.5
    lo = max(0, rate - 1.96 * se)
    hi = rate + 1.96 * se
    print(f"  {label:43s}{n:>10}{a:>10}{rate*100:>7.2f}%  [{lo*100:.2f}, {hi*100:.2f}]%")

# Pairwise tests vs the largest bucket
print()
counts = {label: (bucket_adopt[label], bucket_total[label]) for label, _, _ in LAG_BINS}
labels = [l for l, _, _ in LAG_BINS]
ref = max(labels, key=lambda l: counts[l][1])
print(f"Reference bucket: '{ref}'")
for label in labels:
    if label == ref:
        continue
    a1, n1 = counts[ref]
    a2, n2 = counts[label]
    if n1 == 0 or n2 == 0:
        continue
    # 2-sample proportion test
    p1, p2 = a1 / n1, a2 / n2
    pooled = (a1 + a2) / (n1 + n2)
    se = (pooled * (1 - pooled) * (1 / n1 + 1 / n2)) ** 0.5
    z = (p1 - p2) / se if se else float("nan")
    pval = 2 * (1 - stats.norm.cdf(abs(z)))
    print(f"  vs '{label}': diff = {(p1-p2)*100:+.2f}pp  z = {z:+.2f}  p = {pval:.3g}")
