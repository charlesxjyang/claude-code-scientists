#!/usr/bin/env python3
"""
Figure 5 — Selection on impact: do Claude Code adopters have systematically
different citation counts than non-adopters, controlling for career stage?

Scatter plot:
  x-axis = career years (2026 - earliest_pub_year)
  y-axis = total cited_by_count from OpenAlex (log scale because of skew)
  color  = Claude Code user (yes/no)
  facet  = scientific field (top 6 by adopter count)

Lowess curves for each group within each facet show the conditional mean
shape of impact vs. seniority among adopters and non-adopters.
"""
import json
import os
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

from figure_template import (
    DATA_DIR, OUT_DIR, DPI, PALETTE,
    C_SCIENTIST, C_HIGHLIGHT, C_ALL_USERS,
    save, add_source, add_subtitle,
)

ACTIVE_FILE = os.path.join(DATA_DIR, "active_scientists.json")
CITATIONS_FILE = os.path.join(DATA_DIR, "scientist_citations.json")
ORCID_FILE = os.path.join(DATA_DIR, "orcid_github_users.json")

CURRENT_YEAR = 2026


def lowess(x, y, frac=0.4, n_out=80):
    """Tiny lowess implementation for smoothed conditional mean.
    x and y must be numpy arrays of equal length, ≥4 points."""
    if len(x) < 4:
        return None, None
    order = np.argsort(x)
    xs, ys = np.asarray(x)[order], np.asarray(y)[order]
    xg = np.linspace(xs.min(), xs.max(), n_out)
    yg = np.empty_like(xg)
    n = len(xs)
    bw = max(3, int(frac * n))
    for i, xi in enumerate(xg):
        # Weights: tricube within nearest-bw window
        d = np.abs(xs - xi)
        idx = np.argsort(d)[:bw]
        d_local = d[idx] / max(d[idx].max(), 1e-9)
        w = (1 - d_local ** 3) ** 3
        # Weighted linear regression at xi
        X = np.column_stack([np.ones_like(xs[idx]), xs[idx]])
        W = np.diag(w)
        try:
            beta = np.linalg.solve(X.T @ W @ X, X.T @ W @ ys[idx])
            yg[i] = beta[0] + beta[1] * xi
        except np.linalg.LinAlgError:
            yg[i] = np.average(ys[idx], weights=w)
    return xg, yg


def main():
    with open(ACTIVE_FILE) as f:
        active = json.load(f)
    with open(CITATIONS_FILE) as f:
        cits = json.load(f)

    # Build per-scientist record:  field, career_years, cited_by, claude_user
    rows = []
    n_no_year = 0
    n_no_cite = 0
    for u, info in active["scientists"].items():
        ey = info.get("earliest_pub_year")
        if not ey:
            n_no_year += 1
            continue
        years = CURRENT_YEAR - int(ey)
        c_rec = cits.get(u)
        if not c_rec or not c_rec.get("found"):
            n_no_cite += 1
            continue
        rows.append({
            "field": info.get("field") or "Unknown",
            "career_years": years,
            "cited_by": c_rec.get("cited_by_count", 0),
            "h_index": c_rec.get("h_index", 0),
            "claude_user": bool(info.get("claude_user")),
        })
    print(f"Total scientists with both seniority and OpenAlex citations: {len(rows):,}")
    print(f"  dropped (no first-pub year): {n_no_year:,}")
    print(f"  dropped (no OpenAlex match): {n_no_cite:,}")

    # ----- determine top facets ------------------------------------------
    field_counts = Counter()
    field_adopters = Counter()
    for r in rows:
        field_counts[r["field"]] += 1
        if r["claude_user"]:
            field_adopters[r["field"]] += 1
    # top 6 fields by total adopter count, but require ≥5 adopters
    top_fields = [f for f, n in field_adopters.most_common(8) if n >= 5][:6]
    print(f"Top fields by adopter count: {top_fields}")

    # ----- plot ---------------------------------------------------------
    fig, axes = plt.subplots(2, 3, figsize=(15, 9),
                              sharex=True, sharey=True,
                              gridspec_kw={"hspace": 0.42, "wspace": 0.18})
    axes = axes.flatten()

    # Filter to plotted fields for global y-limit
    plot_rows = [r for r in rows if r["field"] in top_fields]
    cb_pos = [max(1, r["cited_by"]) for r in plot_rows]
    y_max = np.percentile(cb_pos, 99) * 1.5
    x_max = max(1, max(r["career_years"] for r in plot_rows))

    for idx, field in enumerate(top_fields):
        ax = axes[idx]
        adopters = [r for r in rows if r["field"] == field and r["claude_user"]]
        non = [r for r in rows if r["field"] == field and not r["claude_user"]]

        ax.scatter([r["career_years"] for r in non],
                   [max(1, r["cited_by"]) for r in non],
                   s=8, color=C_ALL_USERS, alpha=0.18, edgecolors="none",
                   label=f"non-adopter (n={len(non):,})")
        ax.scatter([r["career_years"] for r in adopters],
                   [max(1, r["cited_by"]) for r in adopters],
                   s=22, color=C_HIGHLIGHT, alpha=0.85, edgecolors="white",
                   linewidths=0.5,
                   label=f"adopter (n={len(adopters):,})")

        # Lowess smoothers
        if len(non) > 8:
            xnon, ynon = np.array([r["career_years"] for r in non]), \
                          np.log10(np.array([max(1, r["cited_by"]) for r in non]))
            xs, ys = lowess(xnon, ynon, frac=0.3)
            if xs is not None:
                ax.plot(xs, 10 ** ys, color=C_SCIENTIST, linewidth=2.0)
        if len(adopters) > 4:
            xa, ya = np.array([r["career_years"] for r in adopters]), \
                      np.log10(np.array([max(1, r["cited_by"]) for r in adopters]))
            xs, ys = lowess(xa, ya, frac=0.5)
            if xs is not None:
                ax.plot(xs, 10 ** ys, color=PALETTE["red"], linewidth=2.2)

        # Median marker per group
        if non:
            med_non = np.median([r["cited_by"] for r in non])
            ax.axhline(med_non, color=C_SCIENTIST, linestyle=":",
                       linewidth=1, alpha=0.6)
        if adopters:
            med_a = np.median([r["cited_by"] for r in adopters])
            ax.axhline(med_a, color=PALETTE["red"], linestyle=":",
                       linewidth=1, alpha=0.6)
            # ratio
            ratio = med_a / max(1, med_non) if non else 1
            ax.text(0.96, 0.05,
                    f"adopter / non med ratio = {ratio:.1f}×",
                    transform=ax.transAxes, ha="right", va="bottom",
                    fontsize=8.5, color="#555555",
                    bbox=dict(boxstyle="round,pad=0.3",
                              facecolor="white", edgecolor="#DDDDDD",
                              linewidth=0.5))

        ax.set_yscale("log")
        ax.set_xlim(-0.5, x_max + 0.5)
        ax.set_ylim(1, y_max)
        ax.set_title(field, loc="left", fontsize=11, fontweight="bold")
        if idx % 3 == 0:
            ax.set_ylabel("Total citations (log)")
        if idx >= 3:
            ax.set_xlabel("Years since first publication")

    # Hide any unused panels
    for j in range(len(top_fields), len(axes)):
        axes[j].axis("off")

    # Legend
    legend_handles = [
        mpatches.Patch(color=C_HIGHLIGHT, label="Claude Code adopter"),
        mpatches.Patch(color=C_ALL_USERS, label="Non-adopter"),
        plt.Line2D([0], [0], color=PALETTE["red"], lw=2, label="adopter trend (lowess)"),
        plt.Line2D([0], [0], color=C_SCIENTIST, lw=2, label="non-adopter trend (lowess)"),
    ]
    fig.legend(handles=legend_handles, loc="upper center", ncol=4,
               bbox_to_anchor=(0.5, 1.01), frameon=False, fontsize=10)

    fig.suptitle(
        "Selection on research impact: are Claude Code adopters more cited?",
        fontsize=14, fontweight="bold", y=1.05, x=0.06, ha="left",
    )
    add_source(
        fig,
        "Source: GitHub Search API + ORCID public data + OpenAlex 2026 author records. "
        f"n = {len(plot_rows):,} active scientists across 6 fields with OpenAlex match.",
    )

    out_base = os.path.join(OUT_DIR, "figS1_impact")
    fig.savefig(out_base + ".svg", format="svg", bbox_inches="tight")
    fig.savefig(out_base + ".png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_base}.svg + .png")

    # Print numerical summary for the table / paper text
    print("\n===== Numerical summary =====")
    print(f"{'Field':30s}  {'n_total':>8}  {'n_adopt':>8}  "
          f"{'med_non':>8}  {'med_adopt':>10}  {'ratio':>6}  {'p_KS':>6}")
    from scipy import stats
    for field in top_fields:
        nons = [r["cited_by"] for r in rows
                if r["field"] == field and not r["claude_user"]]
        adopt = [r["cited_by"] for r in rows
                 if r["field"] == field and r["claude_user"]]
        med_n = np.median(nons) if nons else 0
        med_a = np.median(adopt) if adopt else 0
        ratio = med_a / max(1, med_n)
        try:
            ks = stats.ks_2samp(nons, adopt)
            p = ks.pvalue
        except Exception:
            p = float("nan")
        print(f"{field:30s}  {len(nons)+len(adopt):>8d}  {len(adopt):>8d}  "
              f"{med_n:>8.0f}  {med_a:>10.0f}  {ratio:>5.1f}×  {p:>6.2g}")


if __name__ == "__main__":
    main()
