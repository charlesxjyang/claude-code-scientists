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


def title_with_subtitle(ax, label, subtitle):
    """Section label + subtitle below it. Uses set_title for the bold
    label and a text annotation just above the axes for the subtitle so
    they don't clobber each other (the previous `add_subtitle` helper
    did a second `set_title(loc='left')` which silently replaced the
    first title)."""
    ax.set_title(label, loc="left", fontsize=11, fontweight="bold", pad=22)
    ax.text(0, 1.012, subtitle, transform=ax.transAxes,
            fontsize=9, color="#777777", ha="left", va="bottom",
            style="italic")

CC_FILE = os.environ.get("CLAUDE_COMMITS_PATH",
                          os.path.join(DATA_DIR, "claude_commits_all.json"))
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

    user_commit_dates = defaultdict(list)
    user_repos = defaultdict(set)
    if os.path.exists(CC_FILE):
        print(f"Loading commits ...")
        with open(CC_FILE) as f:
            cc = json.load(f)
        commits = cc["commits"]
        print(f"  {len(commits):,} commits")
        sci_set = {u.lower() for u in scientists}
        for c in commits:
            u = (c.get("github_username") or "").lower()
            if u in sci_set:
                d = c.get("date", "")[:10]
                r = c.get("repo", "")
                if d:
                    user_commit_dates[u].append(d)
                if r:
                    user_repos[u].add(r)
    else:
        print(f"NOTE: {CC_FILE} not present; panels B/C will be empty.")
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
    # Per-bin counts split into ex-CS vs CS-only so all three panels compare
    # the two cohorts.
    by_bin_total = {"ex-CS": Counter(), "CS": Counter(), "all": Counter()}
    by_bin_claude = {"ex-CS": Counter(), "CS": Counter(), "all": Counter()}
    intensity_by_bin = {"ex-CS": defaultdict(list), "CS": defaultdict(list)}
    breadth_by_bin = {"ex-CS": defaultdict(list), "CS": defaultdict(list)}

    for u, info in scientists.items():
        ey = info.get("earliest_pub_year")
        if not ey:
            continue
        years = CURRENT_YEAR - int(ey)
        b = bin_for(years)
        if b is None:
            continue
        is_cs = (info.get("field") == "Computer Science")
        cohort = "CS" if is_cs else "ex-CS"
        by_bin_total[cohort][b] += 1
        by_bin_total["all"][b] += 1
        if info.get("claude_user"):
            by_bin_claude[cohort][b] += 1
            by_bin_claude["all"][b] += 1
            ul = u.lower()
            cw = commits_per_week(user_dates.get(ul, []))
            if cw > 0:
                intensity_by_bin[cohort][b].append(cw)
            r = len(user_repos.get(ul, set()))
            if r > 0:
                breadth_by_bin[cohort][b].append(r)

    bin_labels = [b[0] for b in BINS]

    def rates_for(cohort):
        out = []
        for b in bin_labels:
            t = by_bin_total[cohort][b]
            c = by_bin_claude[cohort][b]
            out.append(100 * c / t if t else 0)
        return out

    rates_excs = rates_for("ex-CS")
    rates_cs   = rates_for("CS")

    # ----- plot ----------------------------------------------------------
    # If commit corpus is unavailable (panels B/C have no data), drop to
    # a single-panel figure showing only adoption-by-seniority.
    have_commits = bool(intensity_by_bin) and any(intensity_by_bin.values())
    if have_commits:
        fig, axes = plt.subplots(
            1, 3, figsize=(15, 5.5),
            gridspec_kw={"width_ratios": [1, 1, 1], "wspace": 0.4},
        )
        axA, axB, axC = axes
    else:
        fig, axA = plt.subplots(figsize=(7.5, 5.5))
        axB = axC = None

    # --- Panel A: adoption rate by seniority -----------------------------
    # Split into ex-CS and CS-only to show the U-shape is largely a CS effect.
    x = np.arange(len(bin_labels))
    w = 0.38
    bars_excs = axA.bar(x - w/2, rates_excs, width=w,
                        color=C_SCIENTIST, edgecolor="white", linewidth=1.2,
                        label="ex-CS")
    bars_cs = axA.bar(x + w/2, rates_cs, width=w,
                      color=C_SECONDARY, edgecolor="white", linewidth=1.2,
                      label="CS only")

    for i in range(len(bin_labels)):
        axA.text(x[i] - w/2, rates_excs[i] + 0.07, f"{rates_excs[i]:.1f}%",
                 ha="center", va="bottom", fontsize=9, fontweight="bold",
                 color="#333333")
        axA.text(x[i] + w/2, rates_cs[i] + 0.07, f"{rates_cs[i]:.1f}%",
                 ha="center", va="bottom", fontsize=9, fontweight="bold",
                 color="#333333")

    axA.set_xticks(x)
    axA.set_xticklabels(bin_labels, fontsize=9)
    axA.yaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    axA.set_ylim(0, max(max(rates_excs), max(rates_cs)) * 1.32)
    axA.set_ylabel("Adoption rate")
    axA.set_title("(a) Adoption by seniority", loc="left")
    axA.legend(loc="upper left", frameon=False, fontsize=9)

    if not have_commits:
        # We're done — single-panel figure.
        add_source(
            fig,
            "Source: GitHub Search API + ORCID public data. "
            f"Adopters: n = {sum(by_bin_claude['all'].values()):,} active scientists with ≥1 Claude Code commit.",
        )
        plt.tight_layout()
        out_base = os.path.join(OUT_DIR, "fig2_career")
        fig.savefig(out_base + ".svg", format="svg", bbox_inches="tight")
        fig.savefig(out_base + ".png", dpi=DPI, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved (panel A only): {out_base}.svg + .png")
        return

    # --- Helper: paired CS / ex-CS violin+box at one bin -----------------
    def paired_violin(ax, bin_data, ylabel, title, ylim_pct=95,
                      fmt="{:.1f}"):
        """bin_data is a dict {'ex-CS': {bin: [...]}, 'CS': {bin: [...]}}."""
        n_bins = len(bin_labels)
        x = np.arange(n_bins)
        offset = 0.20
        width = 0.34

        for i, b in enumerate(bin_labels):
            for cohort, side, color in [
                ("ex-CS", x[i] - offset, C_SCIENTIST),
                ("CS",    x[i] + offset, C_SECONDARY),
            ]:
                vals = bin_data[cohort][b]
                if not vals:
                    continue
                parts = ax.violinplot([vals], positions=[side], widths=width,
                                       showmeans=False, showmedians=False,
                                       showextrema=False)
                for pc in parts["bodies"]:
                    pc.set_facecolor(color)
                    pc.set_alpha(0.30)
                    pc.set_edgecolor("none")
                ax.boxplot([vals], positions=[side], widths=width * 0.45,
                           showfliers=False, patch_artist=True,
                           medianprops=dict(color=color, linewidth=2),
                           boxprops=dict(facecolor="white", edgecolor=color,
                                         linewidth=1.1),
                           whiskerprops=dict(color=color, linewidth=1),
                           capprops=dict(color=color, linewidth=1))
                med = np.median(vals)
                ax.text(side, med, "  " + fmt.format(med),
                        ha="left", va="center", fontsize=8,
                        fontweight="bold", color=color)

        ax.set_xticks(x)
        ax.set_xticklabels(bin_labels, fontsize=9)
        ax.set_ylabel(ylabel)
        pooled = [v for c in ("ex-CS", "CS")
                    for b in bin_labels
                    for v in bin_data[c][b]]
        if pooled:
            ax.set_ylim(0, max(1, np.percentile(pooled, ylim_pct)) * 1.12)
        ax.set_title(title, loc="left")

    # --- Panel B: commit intensity ---------------------------------------
    paired_violin(
        axB, intensity_by_bin,
        ylabel="Commits per week",
        title="(b) Commit intensity among adopters",
        fmt="{:.1f}",
    )

    # --- Panel C: repo breadth -------------------------------------------
    paired_violin(
        axC, breadth_by_bin,
        ylabel="Unique repositories touched",
        title="(c) Repository breadth among adopters",
        fmt="{:.0f}",
    )

    add_source(
        fig,
        "Source: GitHub Search API + ORCID public data. "
        f"Adopters: n = {sum(by_bin_claude['all'].values()):,} active scientists with ≥1 Claude Code commit.",
    )
    plt.tight_layout()

    out_base = os.path.join(OUT_DIR, "fig2_career")
    fig.savefig(out_base + ".svg", format="svg", bbox_inches="tight")
    fig.savefig(out_base + ".png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_base}.svg + .png")


if __name__ == "__main__":
    main()
