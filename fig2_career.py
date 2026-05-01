#!/usr/bin/env python3
"""
Figure 2 — Adoption by career stage (3 panels)
  (a) Adoption rate by years-since-first-publication
  (b) Distribution of commit intensity (commits/week, log) by seniority
  (c) Distribution of repo breadth (unique repos touched) by seniority
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

from figure_template import (
    DATA_DIR, OUT_DIR, DPI, PALETTE,
    C_SCIENTIST, C_ALL_USERS, C_HIGHLIGHT, C_SECONDARY,
    pct_formatter, save, add_source, add_subtitle,
)

CC_FILE = "/Users/charl/Programming/github_claude/claude_commits_all.json"
ACTIVE_FILE = os.path.join(DATA_DIR, "active_scientists.json")

CURRENT_YEAR = 2026

# Seniority bins (years since first publication)
BINS = [
    ("Early career\n(0-2 yrs)",   0, 3),
    ("Postdoc\n(3-6 yrs)",        3, 7),
    ("Mid-career\n(7-12 yrs)",    7, 13),
    ("Senior\n(13-19 yrs)",      13, 20),
    ("Veteran\n(20+ yrs)",       20, 200),
]


def bin_for(years):
    for label, lo, hi in BINS:
        if lo <= years < hi:
            return label
    return None


def load_data():
    with open(ACTIVE_FILE) as f:
        active = json.load(f)
    scientists = active["scientists"]

    print(f"Loading commits ...")
    with open(CC_FILE) as f:
        cc = json.load(f)
    commits = cc["commits"]
    print(f"  {len(commits):,} commits")

    # Build per-user commit list (scientists only)
    sci_set = {u.lower() for u in scientists}
    user_commit_dates = defaultdict(list)
    user_repos = defaultdict(set)
    for c in commits:
        u = (c.get("github_username") or "").lower()
        if u in sci_set:
            d = c.get("date", "")[:10]
            r = c.get("repo", "")
            if d:
                user_commit_dates[u].append(d)
            if r:
                user_repos[u].add(r)
    return scientists, user_commit_dates, user_repos


def commits_per_week(dates):
    if not dates:
        return 0
    dt = sorted(datetime.strptime(d, "%Y-%m-%d") for d in dates)
    span_days = max(1, (dt[-1] - dt[0]).days + 7)
    return len(dt) / (span_days / 7.0)


def main():
    scientists, user_dates, user_repos = load_data()

    # ----- bucket scientists by seniority --------------------------------
    by_bin_total = Counter()
    by_bin_claude = Counter()
    intensity_by_bin = defaultdict(list)
    breadth_by_bin = defaultdict(list)

    for u, info in scientists.items():
        ey = info.get("earliest_pub_year")
        if not ey:
            continue
        years = CURRENT_YEAR - int(ey)
        b = bin_for(years)
        if b is None:
            continue
        by_bin_total[b] += 1
        if info.get("claude_user"):
            by_bin_claude[b] += 1
            ul = u.lower()
            cw = commits_per_week(user_dates.get(ul, []))
            if cw > 0:
                intensity_by_bin[b].append(cw)
            r = len(user_repos.get(ul, set()))
            if r > 0:
                breadth_by_bin[b].append(r)

    bin_labels = [b[0] for b in BINS]
    rates = []
    for b in bin_labels:
        t = by_bin_total[b]
        c = by_bin_claude[b]
        rates.append(100 * c / t if t else 0)

    # ----- plot ----------------------------------------------------------
    fig, axes = plt.subplots(
        1, 3, figsize=(15, 5.5),
        gridspec_kw={"width_ratios": [1, 1, 1], "wspace": 0.4},
    )
    axA, axB, axC = axes

    # --- Panel A: adoption rate by seniority -----------------------------
    bars = axA.bar(range(len(bin_labels)), rates,
                   color=C_SCIENTIST, edgecolor="white", linewidth=1.4,
                   width=0.7)
    overall = sum(by_bin_claude.values()) / max(1, sum(by_bin_total.values())) * 100
    axA.axhline(overall, color=C_HIGHLIGHT, linestyle="--", linewidth=1.2,
                alpha=0.85)
    axA.text(len(bin_labels) - 0.5, overall + 0.07,
             f"overall {overall:.1f}%",
             color=C_HIGHLIGHT, ha="right", va="bottom",
             fontsize=9, fontweight="bold")

    for i, (b, r) in enumerate(zip(bin_labels, rates)):
        n = by_bin_claude[b]
        axA.text(i, r + 0.07, f"{r:.1f}%", ha="center", va="bottom",
                 fontsize=10, fontweight="bold", color="#333333")
        axA.text(i, -0.35, f"n={by_bin_total[b]:,}",
                 ha="center", va="top", fontsize=8, color="#888888")

    axA.set_xticks(range(len(bin_labels)))
    axA.set_xticklabels(bin_labels, fontsize=9)
    axA.yaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    axA.set_ylim(0, max(rates) * 1.32)
    axA.set_ylabel("Adoption rate")
    axA.set_title("(a) Adoption by seniority", loc="left")
    add_subtitle(axA, "U-shaped: highest among early career and veteran scientists")

    # --- Panel B: intensity distribution by seniority --------------------
    intensity_data = [intensity_by_bin[b] for b in bin_labels]

    parts = axB.violinplot(intensity_data, showmeans=False, showmedians=False,
                           showextrema=False, widths=0.7)
    for pc in parts["bodies"]:
        pc.set_facecolor(C_SCIENTIST)
        pc.set_alpha(0.35)
        pc.set_edgecolor("none")

    # boxplot overlay
    bp = axB.boxplot(intensity_data, positions=range(1, len(bin_labels) + 1),
                     widths=0.18, showfliers=False, patch_artist=True,
                     medianprops=dict(color=PALETTE["red"], linewidth=2),
                     boxprops=dict(facecolor="white", edgecolor=C_SCIENTIST,
                                   linewidth=1.2),
                     whiskerprops=dict(color=C_SCIENTIST, linewidth=1),
                     capprops=dict(color=C_SCIENTIST, linewidth=1))

    axB.set_xticks(range(1, len(bin_labels) + 1))
    axB.set_xticklabels(bin_labels, fontsize=9)
    axB.set_ylabel("Commits per week")
    # Cap visible y-axis at the 95th percentile of the pooled data so outliers
    # don't compress the medians. Box+violin still show the full distribution.
    pooled = [v for vs in intensity_data for v in vs]
    if pooled:
        import numpy as _np
        axB.set_ylim(0, max(1, _np.percentile(pooled, 95)) * 1.1)
    axB.set_title("(b) Commit intensity among adopters", loc="left")
    add_subtitle(axB, "Roughly flat across seniority — adoption ≠ usage gap")
    for i, vals in enumerate(intensity_data, 1):
        if vals:
            med = np.median(vals)
            axB.text(i, med * 1.4, f"{med:.1f}",
                     ha="center", va="bottom", fontsize=9,
                     fontweight="bold", color=PALETTE["red"])

    # --- Panel C: repo breadth by seniority ------------------------------
    breadth_data = [breadth_by_bin[b] for b in bin_labels]

    parts = axC.violinplot(breadth_data, showmeans=False, showmedians=False,
                           showextrema=False, widths=0.7)
    for pc in parts["bodies"]:
        pc.set_facecolor(C_SECONDARY)
        pc.set_alpha(0.35)
        pc.set_edgecolor("none")

    bp = axC.boxplot(breadth_data, positions=range(1, len(bin_labels) + 1),
                     widths=0.18, showfliers=False, patch_artist=True,
                     medianprops=dict(color=PALETTE["red"], linewidth=2),
                     boxprops=dict(facecolor="white", edgecolor=C_SECONDARY,
                                   linewidth=1.2),
                     whiskerprops=dict(color=C_SECONDARY, linewidth=1),
                     capprops=dict(color=C_SECONDARY, linewidth=1))

    axC.set_xticks(range(1, len(bin_labels) + 1))
    axC.set_xticklabels(bin_labels, fontsize=9)
    axC.set_ylabel("Unique repositories touched")
    pooled_b = [v for vs in breadth_data for v in vs]
    if pooled_b:
        import numpy as _np
        axC.set_ylim(0, max(1, _np.percentile(pooled_b, 95)) * 1.15)
    axC.set_title("(c) Repository breadth among adopters", loc="left")
    add_subtitle(axC, "Veterans contribute across more repos than juniors")
    for i, vals in enumerate(breadth_data, 1):
        if vals:
            med = np.median(vals)
            axC.text(i, med * 1.4, f"{med:.0f}",
                     ha="center", va="bottom", fontsize=9,
                     fontweight="bold", color=PALETTE["red"])

    add_source(
        fig,
        "Source: GitHub Search API + ORCID public data. "
        f"Adopters: n = {sum(by_bin_claude.values()):,} active scientists with ≥1 Claude Code commit.",
    )
    plt.tight_layout()

    out_base = os.path.join(OUT_DIR, "fig2_career")
    fig.savefig(out_base + ".svg", format="svg", bbox_inches="tight")
    fig.savefig(out_base + ".png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_base}.svg + .png")


if __name__ == "__main__":
    main()
