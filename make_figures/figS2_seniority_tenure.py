#!/usr/bin/env python3
"""
Figure S2 — Within-seniority GitHub-tenure gap, ex-CS and CS-only.

Demonstrates that the §3.5 tenure-gap finding (adopters have longer
GitHub histories than non-adopters) is robust to conditioning on career
stage: in every seniority bucket, ex-CS and CS-only, adopters have
materially longer tenure.

Two panels:
  (a) Ex-CS: GitHub tenure distribution by seniority × adoption.
  (b) CS-only.

Within each seniority bucket, plot two adjacent violin/box pairs
(adopter, non-adopter), with median markers and a one-sided
Mann-Whitney significance asterisk.
"""
import json
import math
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from figure_template import (
    DATA_DIR, OUT_DIR, DPI,
    C_SCIENTIST, C_HIGHLIGHT, C_SECONDARY,
    add_subtitle, add_source,
)

ACTIVE_FILE = os.path.join(DATA_DIR, "active_scientists.json")
GH_FILE = os.path.join(DATA_DIR, "scientist_github_accounts.json")
REF_YEAR = 2026

BINS = [
    ("0-2",   0, 3),
    ("3-6",   3, 7),
    ("7-12",  7, 13),
    ("13-19", 13, 20),
    ("20+",  20, 200),
]


def bin_for(years):
    for label, lo, hi in BINS:
        if lo <= years < hi:
            return label
    return None


def mwu_one_sided_p(a, b):
    """One-sided MWU H1: a > b. Returns p."""
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return 1.0
    combined = [(v, 0) for v in a] + [(v, 1) for v in b]
    combined.sort(key=lambda x: x[0])
    ranks = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    R1 = sum(ranks[i] for i, (_, g) in enumerate(combined) if g == 0)
    U1 = R1 - n1 * (n1 + 1) / 2
    mean = n1 * n2 / 2
    sd = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    z = (U1 - mean) / sd if sd else 0
    from math import erf, sqrt
    return 1 - 0.5 * (1 + erf(z / sqrt(2)))


def stars(p):
    if p < 0.001: return "***"
    if p < 0.01:  return "**"
    if p < 0.05:  return "*"
    return "n.s."


def collect_data():
    active = json.load(open(ACTIVE_FILE))["scientists"]
    gh = json.load(open(GH_FILE))

    out = {"ex-CS": defaultdict(lambda: {"adopt": [], "non": []}),
           "CS":    defaultdict(lambda: {"adopt": [], "non": []})}

    for u, info in active.items():
        rec = gh.get(u) or gh.get(u.lower())
        if not rec or not rec.get("account_created"):
            continue
        try:
            gy = int(rec["account_created"][:4])
        except (TypeError, ValueError):
            continue
        py = info.get("earliest_pub_year")
        if py is None:
            continue
        sen = REF_YEAR - py
        if sen < 0:
            continue
        b = bin_for(sen)
        if b is None:
            continue
        tenure = REF_YEAR - gy
        if tenure < 0:
            continue
        cohort = "CS" if info.get("field") == "Computer Science" else "ex-CS"
        key = "adopt" if info.get("claude_user") else "non"
        out[cohort][b][key].append(tenure)
    return out


def draw_panel(ax, data, title):
    bin_labels = [b[0] for b in BINS]
    n_bins = len(bin_labels)
    x = np.arange(n_bins)
    offset = 0.20
    width = 0.34

    for i, b in enumerate(bin_labels):
        a = data[b]["adopt"]
        n = data[b]["non"]
        if not a and not n:
            continue
        for tenure_list, side, color in [
            (n, x[i] - offset, C_SECONDARY),
            (a, x[i] + offset, C_HIGHLIGHT),
        ]:
            if not tenure_list:
                continue
            parts = ax.violinplot([tenure_list], positions=[side],
                                   widths=width, showmeans=False,
                                   showmedians=False, showextrema=False)
            for pc in parts["bodies"]:
                pc.set_facecolor(color)
                pc.set_alpha(0.30)
                pc.set_edgecolor("none")
            ax.boxplot([tenure_list], positions=[side],
                       widths=width * 0.45, showfliers=False,
                       patch_artist=True,
                       medianprops=dict(color=color, linewidth=2),
                       boxprops=dict(facecolor="white", edgecolor=color, linewidth=1.1),
                       whiskerprops=dict(color=color, linewidth=1),
                       capprops=dict(color=color, linewidth=1))
            ax.text(side, np.median(tenure_list) + 0.4, f"{np.median(tenure_list):.0f}",
                    ha="center", fontsize=8, fontweight="bold", color=color)

        # significance asterisk above the pair
        if a and n:
            p = mwu_one_sided_p(a, n)
            ax.text(x[i], max(max(a), max(n)) * 1.02, stars(p),
                    ha="center", va="bottom", fontsize=10,
                    fontweight="bold", color="#444444")
        # n labels under the bin
        ax.text(x[i] - offset, -1.2, f"n={len(n):,}",
                ha="center", fontsize=7, color="#888888")
        ax.text(x[i] + offset, -1.2, f"n={len(a):,}",
                ha="center", fontsize=7, color="#888888")

    ax.set_xticks(x)
    ax.set_xticklabels(bin_labels)
    ax.set_xlabel("Years since first publication")
    ax.set_ylabel("GitHub tenure (years)")
    ax.set_ylim(bottom=-2.5)
    ax.set_title(title, loc="left")


def main():
    data = collect_data()

    fig, (axA, axB) = plt.subplots(1, 2, figsize=(13, 5.5),
                                    gridspec_kw={"wspace": 0.30})

    draw_panel(axA, data["ex-CS"], "(a) Ex-Computer Science")
    draw_panel(axB, data["CS"],    "(b) Computer Science only")

    # legend in panel A
    import matplotlib.patches as mpatches
    handles = [
        mpatches.Patch(color=C_HIGHLIGHT, alpha=0.5, label="Adopter"),
        mpatches.Patch(color=C_SECONDARY, alpha=0.5, label="Non-adopter"),
    ]
    axA.legend(handles=handles, loc="upper left", frameon=False, fontsize=9)

    add_source(
        fig,
        "Source: GitHub User API + ORCID public data. "
        "Median tenure shown above each box; "
        "* p < 0.05, ** p < 0.01, *** p < 0.001 (one-sided Mann–Whitney U).",
    )
    plt.tight_layout()

    out_base = os.path.join(OUT_DIR, "figS2_seniority_tenure")
    fig.savefig(out_base + ".svg", format="svg", bbox_inches="tight")
    fig.savefig(out_base + ".png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_base}.svg + .png")


if __name__ == "__main__":
    main()
