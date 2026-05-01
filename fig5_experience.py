#!/usr/bin/env python3
"""
Figure 5 — Selection on GitHub experience: do Claude Code adopters have
systematically longer GitHub histories than non-adopters, by field?

Violin plot:
  x-axis = field (faceted)
  y-axis = years between GitHub account creation and 2026-03-01
  groups = Claude Code adopter vs non-adopter
  KS / Mann-Whitney U test reported per facet.
"""
import json
import os
from collections import defaultdict
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from scipy import stats

from figure_template import (
    DATA_DIR, OUT_DIR, DPI, PALETTE,
    C_SCIENTIST, C_HIGHLIGHT, C_ALL_USERS,
    save, add_source, add_subtitle,
)

ACTIVE_FILE = os.path.join(DATA_DIR, "active_scientists.json")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "scientist_github_accounts.json")
REFERENCE_DATE = datetime(2026, 3, 1)


def main():
    with open(ACTIVE_FILE) as f:
        active = json.load(f)
    with open(ACCOUNTS_FILE) as f:
        accounts = json.load(f)

    # Build (field, claude_user, years_on_github) records
    rows = []
    for u, info in active["scientists"].items():
        a = accounts.get(u)
        if not a or not a.get("found"):
            continue
        ts = a.get("account_created")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            years = (REFERENCE_DATE - dt.replace(tzinfo=None)).days / 365.25
        except Exception:
            continue
        if years < 0:
            continue
        rows.append({
            "field": info.get("field") or "Unknown",
            "years": years,
            "claude_user": bool(info.get("claude_user")),
        })
    print(f"Scientists with valid GitHub age: {len(rows):,}")

    # Determine fields with enough adopters to plot
    field_n_adopt = defaultdict(int)
    field_n_total = defaultdict(int)
    for r in rows:
        field_n_total[r["field"]] += 1
        if r["claude_user"]:
            field_n_adopt[r["field"]] += 1

    # Take top 8 fields with ≥7 adopters each
    fields = [f for f, n in sorted(field_n_adopt.items(), key=lambda x: -x[1])
              if n >= 7][:8]
    print(f"Fields plotted: {fields}")

    # Order by total scientists for visual consistency (most populous left)
    fields = sorted(fields, key=lambda f: -field_n_total[f])

    # Bucket the data
    by_field_a = {f: [] for f in fields}
    by_field_n = {f: [] for f in fields}
    for r in rows:
        if r["field"] not in fields:
            continue
        if r["claude_user"]:
            by_field_a[r["field"]].append(r["years"])
        else:
            by_field_n[r["field"]].append(r["years"])

    # Stats per field
    print(f"\n{'Field':30s}  {'n_non':>6}  {'n_adopt':>7}  {'med_non':>7}  "
          f"{'med_adopt':>9}  {'diff':>6}  {'p_MW':>7}")
    stats_table = {}
    for f in fields:
        nons = by_field_n[f]
        adopt = by_field_a[f]
        med_n = np.median(nons) if nons else 0
        med_a = np.median(adopt) if adopt else 0
        diff = med_a - med_n
        try:
            mw = stats.mannwhitneyu(adopt, nons, alternative="greater")
            p = mw.pvalue
        except Exception:
            p = float("nan")
        stats_table[f] = (len(nons), len(adopt), med_n, med_a, diff, p)
        print(f"{f:30s}  {len(nons):>6d}  {len(adopt):>7d}  {med_n:>6.1f}y  "
              f"{med_a:>8.1f}y  {diff:>+5.1f}y  {p:>7.2g}")

    # Overall pooled
    all_a = [v for f in fields for v in by_field_a[f]]
    all_n = [v for f in fields for v in by_field_n[f]]
    mw_all = stats.mannwhitneyu(all_a, all_n, alternative="greater")
    print(f"\nPooled across plotted fields: med_adopt={np.median(all_a):.1f}y, "
          f"med_non={np.median(all_n):.1f}y, p={mw_all.pvalue:.3e}")

    # ----- Plot --------------------------------------------------------
    fig, ax = plt.subplots(figsize=(13, 6.5))

    pos_centers = np.arange(len(fields)) * 1.0
    offset = 0.20

    pretty = [f.replace("Biology & Life Sciences", "Bio & Life Sci")
               .replace("Earth & Environmental", "Earth & Env.")
               .replace("Economics & Business", "Econ & Business")
               .replace("Medicine & Health", "Medicine")
               .replace("Physics & Astronomy", "Physics")
               .replace("Materials Science", "Materials Sci")
               .replace("Computer Science", "Comp Sci")
               for f in fields]

    # Non-adopters (left half, gray)
    parts_n = ax.violinplot([by_field_n[f] for f in fields],
                             positions=pos_centers - offset,
                             widths=0.32, showextrema=False, showmedians=False)
    for pc in parts_n["bodies"]:
        pc.set_facecolor(C_ALL_USERS)
        pc.set_alpha(0.45)
        pc.set_edgecolor("none")

    # Adopters (right half, orange)
    parts_a = ax.violinplot([by_field_a[f] for f in fields],
                             positions=pos_centers + offset,
                             widths=0.32, showextrema=False, showmedians=False)
    for pc in parts_a["bodies"]:
        pc.set_facecolor(C_HIGHLIGHT)
        pc.set_alpha=0.55
        pc.set_edgecolor("none")

    # Box overlays + median markers
    bp_n = ax.boxplot([by_field_n[f] for f in fields],
                      positions=pos_centers - offset, widths=0.10,
                      showfliers=False, patch_artist=True,
                      boxprops=dict(facecolor="white", edgecolor="#666666",
                                    linewidth=1.0),
                      medianprops=dict(color="#333333", linewidth=1.6),
                      whiskerprops=dict(color="#666666", linewidth=0.8),
                      capprops=dict(color="#666666", linewidth=0.8))
    bp_a = ax.boxplot([by_field_a[f] for f in fields],
                      positions=pos_centers + offset, widths=0.10,
                      showfliers=False, patch_artist=True,
                      boxprops=dict(facecolor="white", edgecolor=C_HIGHLIGHT,
                                    linewidth=1.0),
                      medianprops=dict(color=PALETTE["red"], linewidth=1.6),
                      whiskerprops=dict(color=C_HIGHLIGHT, linewidth=0.8),
                      capprops=dict(color=C_HIGHLIGHT, linewidth=0.8))

    # significance asterisks
    for i, f in enumerate(fields):
        n_non, n_a, m_n, m_a, diff, p = stats_table[f]
        if p < 0.001:
            sig = "***"
        elif p < 0.01:
            sig = "**"
        elif p < 0.05:
            sig = "*"
        else:
            sig = "ns"
        # place above max y
        y_top = max(np.percentile(by_field_n[f], 95) if by_field_n[f] else 1,
                    np.percentile(by_field_a[f], 95) if by_field_a[f] else 1)
        ax.text(i, y_top + 1.2, sig, ha="center", va="bottom",
                fontsize=11, fontweight="bold",
                color=PALETTE["red"] if p < 0.05 else "#888888")
        # n labels
        ax.text(i, -1.2, f"n={n_non:,} / {n_a}",
                ha="center", va="top", fontsize=8, color="#888888")

    ax.set_xticks(pos_centers)
    ax.set_xticklabels(pretty, fontsize=9, rotation=20, ha="right")
    ax.set_ylabel("Years on GitHub (account creation → March 2026)")
    ax.set_ylim(-0.5, max(np.percentile(all_n + all_a, 99) * 1.18, 16))
    ax.grid(True, axis="y", alpha=0.5)

    # legend
    legend_handles = [
        mpatches.Patch(color=C_ALL_USERS, alpha=0.45, label="Non-adopter"),
        mpatches.Patch(color=C_HIGHLIGHT, alpha=0.55, label="Claude Code adopter"),
    ]
    ax.legend(handles=legend_handles, loc="upper right", frameon=False,
              fontsize=10)

    ax.set_title(
        "Selection on GitHub experience: adopters have longer GitHub histories "
        "than non-adopters",
        loc="left", fontsize=13, fontweight="bold",
    )
    add_subtitle(ax,
                 f"Pooled p (Mann-Whitney U, one-sided) = {mw_all.pvalue:.0e}; "
                 f"adopter median {np.median(all_a):.1f}y vs. {np.median(all_n):.1f}y non-adopter; "
                 f"asterisks: per-field one-sided p (* < 0.05, ** < 0.01, *** < 0.001)")
    add_source(
        fig,
        f"Source: GitHub Core API (account_created) + ORCID public data. "
        f"n={len(rows):,} active scientists across {len(fields)} fields.",
    )

    out_base = os.path.join(OUT_DIR, "fig5_experience")
    fig.savefig(out_base + ".svg", format="svg", bbox_inches="tight")
    fig.savefig(out_base + ".png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved: {out_base}.svg + .png")


if __name__ == "__main__":
    main()
