#!/usr/bin/env python3
"""
Figure 1 — Diffusion of Claude Code among scientists (2 panels)
  (a) Cumulative adoption rate over time among active ORCID+GitHub scientists
  (b) Weekly Claude Code commits: all GitHub users vs scientists (log scale)
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

from figure_template import (
    DATA_DIR, OUT_DIR, DPI, PALETTE,
    C_SCIENTIST, C_ALL_USERS, C_HIGHLIGHT,
    pct_formatter, k_formatter, save, add_source, add_subtitle, direct_label,
)

CC_FILE = "/Users/charl/Programming/github_claude/claude_commits_all.json"
ACTIVE_FILE = os.path.join(DATA_DIR, "active_scientists.json")

DATA_LABEL = "Oct 2025 – Mar 2026"


def load_data():
    with open(ACTIVE_FILE) as f:
        active = json.load(f)
    scientist_set = {u.lower() for u in active["scientists"]}
    total_active = active["total"]

    print(f"Loading {CC_FILE}...")
    with open(CC_FILE) as f:
        cc = json.load(f)
    commits = cc["commits"]
    print(f"  {len(commits):,} commits")
    return scientist_set, total_active, commits


def main():
    scientist_set, total_active, commits = load_data()

    # ------------------------------------------------------------------
    # Aggregate by week
    # ------------------------------------------------------------------
    def week_start(ds):  # ds is YYYY-MM-DD
        dt = datetime.strptime(ds[:10], "%Y-%m-%d")
        return (dt - timedelta(days=dt.weekday())).date()

    weekly_all = Counter()
    weekly_sci = Counter()
    first_use = {}  # scientist username -> earliest commit date
    for c in commits:
        ds = c.get("date", "")
        u = (c.get("github_username") or "").lower()
        if not ds or not u:
            continue
        wk = week_start(ds)
        weekly_all[wk] += 1
        if u in scientist_set:
            weekly_sci[wk] += 1
            cur = first_use.get(u)
            day = ds[:10]
            if cur is None or day < cur:
                first_use[u] = day

    weeks = sorted(weekly_all.keys())
    # Trim partial weeks from BOTH ends so weekly counts compare like-for-like.
    # We keep weeks that lie entirely within the data window.
    all_dates = [c.get("date", "")[:10] for c in commits if c.get("date")]
    data_min = min(all_dates)
    data_max = max(all_dates)
    from datetime import date as _date
    dmin = _date.fromisoformat(data_min)
    dmax = _date.fromisoformat(data_max)
    weeks = [w for w in weeks
             if w >= dmin and w + timedelta(days=6) <= dmax]

    # Cumulative adopters by week
    weekly_new_adopters = defaultdict(int)
    for u, ds in first_use.items():
        weekly_new_adopters[week_start(ds)] += 1

    cum = 0
    cum_pct = []
    for wk in weeks:
        cum += weekly_new_adopters.get(wk, 0)
        cum_pct.append(100 * cum / total_active)

    # ------------------------------------------------------------------
    # Plot — 2 panels stacked vertically
    # ------------------------------------------------------------------
    fig, (axA, axB) = plt.subplots(
        2, 1, figsize=(10, 9),
        gridspec_kw={"height_ratios": [1, 1.1], "hspace": 0.45},
    )

    # ─── Panel A: cumulative adoption ────────────────────────────────
    week_dt = [datetime.combine(w, datetime.min.time()) for w in weeks]
    axA.fill_between(week_dt, cum_pct, alpha=0.12, color=C_SCIENTIST)
    axA.plot(week_dt, cum_pct, color=C_SCIENTIST, linewidth=2.5,
             marker="o", markersize=4)

    axA.set_ylim(0, max(3, max(cum_pct) * 1.18))
    axA.yaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    axA.yaxis.set_major_locator(ticker.MultipleLocator(0.5))
    axA.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    axA.xaxis.set_major_locator(mdates.MonthLocator())
    axA.set_ylabel("% of active ORCID+GitHub scientists")
    axA.set_title("(a) Cumulative Claude Code adoption", loc="left")
    add_subtitle(axA, f"Among {total_active:,} active ORCID-linked scientists with GitHub profile and a 2024+ publication")
    direct_label(axA, week_dt[-1], cum_pct[-1],
                 f"  {cum_pct[-1]:.2f}%\n  ({cum:,} scientists)",
                 color=C_SCIENTIST, fontsize=11, fontweight="bold")

    # ─── Panel B: weekly commits, log scale ──────────────────────────
    sci_y = [weekly_sci.get(wk, 0) for wk in weeks]
    all_y = [weekly_all.get(wk, 0) for wk in weeks]

    axB.plot(week_dt, all_y, color=C_ALL_USERS, linewidth=2.2,
             marker="o", markersize=4, label="All Claude Code commits")
    axB.plot(week_dt, sci_y, color=C_SCIENTIST, linewidth=2.5,
             marker="o", markersize=4, label="Scientists")
    axB.set_yscale("log")
    axB.yaxis.set_major_formatter(ticker.FuncFormatter(k_formatter))
    axB.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    axB.xaxis.set_major_locator(mdates.MonthLocator())
    axB.set_ylabel("Weekly Claude Code commits (log scale)")
    axB.set_title("(b) Scientist share of all Claude Code commits", loc="left")
    add_subtitle(axB, f"Weekly counts; scientists are a stable ~{sci_y[-1] / all_y[-1] * 100:.2f}% of total")

    direct_label(axB, week_dt[-1], all_y[-1], "  all users",
                 color="#777777", fontsize=10, fontweight="bold")
    direct_label(axB, week_dt[-1], sci_y[-1], "  scientists",
                 color=C_SCIENTIST, fontsize=10, fontweight="bold")

    # ------------------------------------------------------------------
    add_source(
        fig,
        f"Source: GitHub Search API (claude-coauthored commits, {DATA_LABEL}) + ORCID public data + OpenAlex.",
    )
    plt.tight_layout()

    out_base = os.path.join(OUT_DIR, "fig1_diffusion")
    fig.savefig(out_base + ".svg", format="svg", bbox_inches="tight")
    fig.savefig(out_base + ".png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_base}.svg + .png")


if __name__ == "__main__":
    main()
