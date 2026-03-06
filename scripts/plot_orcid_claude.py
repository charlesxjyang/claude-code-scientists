#!/usr/bin/env python3
"""Plot ORCID scientist Claude Code adoption over time.

Figure 1: % of active ORCID scientists using Claude Code (cumulative, weekly)
Figure 2: Claude commits by scientists vs all users, with % scientist share
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

SCRIPT_DIR = "/Users/charl/Programming/github_claude"
ORCID_FILE = os.path.join(SCRIPT_DIR, "orcid_github_users.json")
COMMITS_FILE = os.path.join(SCRIPT_DIR, "claude_commits_all.json")

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


def load_orcid_users():
    """Load ORCID data and return set of scientist GitHub usernames (lowercase)."""
    with open(ORCID_FILE) as f:
        data = json.load(f)

    users = data.get("users", {})
    total_active = data.get("total_active", 0)

    # Build set of scientist usernames and their Claude dates
    scientist_set = set()
    scientist_claude_dates = {}  # username -> [dates]

    for username, info in users.items():
        scientist_set.add(username.lower())
        claude_dates = info.get("claude_dates", [])
        if claude_dates:
            scientist_claude_dates[username.lower()] = claude_dates

    print(f"Loaded {len(scientist_set):,} ORCID scientists, "
          f"{len(scientist_claude_dates):,} with Claude dates")
    print(f"Total active: {total_active:,}")
    return scientist_set, scientist_claude_dates, total_active


def scan_all_commits(scientist_set):
    """Stream all Claude commits and tally weekly counts: scientist vs non-scientist."""
    print("Scanning all Claude commits...")

    weekly_scientist = defaultdict(int)
    weekly_all = defaultdict(int)
    weekly_scientist_users = defaultdict(set)

    date = None
    count = 0

    with open(COMMITS_FILE) as f:
        for line in f:
            stripped = line.strip()
            if '"date":' in stripped and '"author_date"' not in stripped:
                date = stripped.split(":", 1)[1].strip().strip('",')[:10]
            elif '"github_username":' in stripped:
                username = stripped.split(":", 1)[1].strip().strip('",').lower()
                if date:
                    try:
                        dt = datetime.strptime(date, "%Y-%m-%d")
                        week_start = dt - timedelta(days=dt.weekday())
                        wk = week_start.strftime("%Y-%m-%d")
                        weekly_all[wk] += 1
                        if username in scientist_set:
                            weekly_scientist[wk] += 1
                            weekly_scientist_users[wk].add(username)
                    except ValueError:
                        pass
                count += 1
                if count % 2_000_000 == 0:
                    print(f"  {count/1e6:.0f}M commits...", flush=True)
                date = None

    print(f"  {count:,} total commits scanned")
    return weekly_all, weekly_scientist, weekly_scientist_users


def plot_adoption_rate(scientist_claude_dates, total_active):
    """Fig 1: % of active ORCID scientists using Claude Code over time."""
    # Build weekly cumulative users
    first_use = {}  # username -> first date
    for username, dates in scientist_claude_dates.items():
        if dates:
            first_use[username] = min(dates)

    # Group by week of first use
    weekly_new = defaultdict(set)
    for username, first_date in first_use.items():
        try:
            dt = datetime.strptime(first_date, "%Y-%m-%d")
            week_start = dt - timedelta(days=dt.weekday())
            wk = week_start.strftime("%Y-%m-%d")
            weekly_new[wk].add(username)
        except ValueError:
            pass

    weeks = sorted(weekly_new.keys())
    if not weeks:
        print("No weekly data for adoption plot")
        return

    # Filter to reasonable range
    weeks = [w for w in weeks if "2025-10" <= w <= "2026-02-10"]

    cumulative = set()
    cum_counts = []
    pcts = []
    week_dates = []

    for wk in weeks:
        cumulative |= weekly_new.get(wk, set())
        cum_counts.append(len(cumulative))
        pcts.append(len(cumulative) / total_active * 100)
        week_dates.append(datetime.strptime(wk, "%Y-%m-%d"))

    fig, ax1 = plt.subplots(figsize=(12, 6))

    color1 = "#58a6ff"
    color2 = "#f0883e"

    ax1.fill_between(week_dates, pcts, alpha=0.15, color=color1)
    ax1.plot(week_dates, pcts, color=color1, linewidth=2.5, marker='o', markersize=4,
             label="% of active scientists")
    ax1.set_ylabel("% of active ORCID scientists using Claude Code", color=color1)
    ax1.set_ylim(0, max(pcts) * 1.2)
    ax1.tick_params(axis='y', labelcolor=color1)

    ax2 = ax1.twinx()
    ax2.plot(week_dates, cum_counts, color=color2, linewidth=2, linestyle='--',
             marker='s', markersize=3, label="Cumulative scientists")
    ax2.set_ylabel("Cumulative scientist users", color=color2)
    ax2.tick_params(axis='y', labelcolor=color2)

    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')

    ax1.set_title("Claude Code Adoption Among Active ORCID Scientists",
                   fontsize=14, fontweight='bold', pad=15)
    ax1.grid(True, alpha=0.3)

    # Annotate final value
    ax1.annotate(f'{pcts[-1]:.1f}%\n({cum_counts[-1]:,} scientists)',
                 xy=(week_dates[-1], pcts[-1]),
                 xytext=(20, 15), textcoords='offset points',
                 color=color1, fontsize=10, fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=color1, lw=1.5))

    # Legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left',
               facecolor='#161b22', edgecolor='#30363d', labelcolor='#e6edf3')

    # Subtitle
    fig.text(0.5, 0.01,
             f"Base: {total_active:,} active ORCID-linked GitHub users (≥1 event in past year)",
             ha='center', fontsize=9, color='#8b949e')

    plt.tight_layout()
    plt.subplots_adjust(bottom=0.12)
    fig.savefig(os.path.join(SCRIPT_DIR, "figures", "orcid_adoption_rate.png"), dpi=150,
                bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close()
    print("Saved figures/orcid_adoption_rate.png")


def plot_commits_share(weekly_all, weekly_scientist, weekly_scientist_users):
    """Fig 2: Claude commits — scientists vs all, with % scientist share."""
    weeks = sorted(set(weekly_all.keys()) & set(weekly_scientist.keys()))
    weeks = [w for w in weeks if "2025-10" <= w <= "2026-02-10"]

    if not weeks:
        print("No weekly data for commits plot")
        return

    week_dates = [datetime.strptime(w, "%Y-%m-%d") for w in weeks]
    all_counts = [weekly_all[w] for w in weeks]
    sci_counts = [weekly_scientist[w] for w in weeks]
    non_sci = [a - s for a, s in zip(all_counts, sci_counts)]
    pct_sci = [s / a * 100 if a > 0 else 0 for s, a in zip(sci_counts, all_counts)]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), height_ratios=[2, 1],
                                     sharex=True)

    # Top: stacked bar chart
    bar_width = 5
    ax1.bar(week_dates, sci_counts, width=bar_width, color="#58a6ff", alpha=0.9,
            label="ORCID scientists")
    ax1.bar(week_dates, non_sci, width=bar_width, bottom=sci_counts, color="#30363d",
            alpha=0.7, label="Other users")

    ax1.set_ylabel("Claude Code commits per week")
    ax1.set_title("Claude Code Commits: Scientists vs All Users",
                   fontsize=14, fontweight='bold', pad=15)
    ax1.legend(loc='upper left', facecolor='#161b22', edgecolor='#30363d',
               labelcolor='#e6edf3')
    ax1.grid(True, alpha=0.3, axis='y')

    # Format y-axis with K
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x/1000:.0f}K' if x >= 1000 else f'{x:.0f}'))

    # Bottom: % scientist share
    ax2.fill_between(week_dates, pct_sci, alpha=0.2, color="#f0883e")
    ax2.plot(week_dates, pct_sci, color="#f0883e", linewidth=2.5, marker='o', markersize=4)
    ax2.set_ylabel("% of commits by scientists")
    ax2.set_ylim(0, max(pct_sci) * 1.4)
    ax2.grid(True, alpha=0.3)

    # Annotate trend
    for i, (wd, p) in enumerate(zip(week_dates, pct_sci)):
        if i == len(week_dates) - 2:  # annotate second-to-last (last full week)
            ax2.annotate(f'{p:.1f}%', xy=(wd, p),
                         xytext=(10, 10), textcoords='offset points',
                         color='#f0883e', fontsize=10, fontweight='bold')

    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax2.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')

    # Also add weekly unique scientists on secondary axis of bottom plot
    sci_user_counts = [len(weekly_scientist_users.get(w, set())) for w in weeks]
    ax3 = ax2.twinx()
    ax3.plot(week_dates, sci_user_counts, color='#8b949e', linewidth=1.5,
             linestyle='--', alpha=0.7)
    ax3.set_ylabel("Active scientist users/week", color='#8b949e')
    ax3.tick_params(axis='y', labelcolor='#8b949e')

    plt.tight_layout()
    fig.savefig(os.path.join(SCRIPT_DIR, "figures", "orcid_commits_share.png"), dpi=150,
                bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close()
    print("Saved figures/orcid_commits_share.png")


def main():
    scientist_set, scientist_claude_dates, total_active = load_orcid_users()

    # Scan all commits for weekly breakdown
    weekly_all, weekly_scientist, weekly_scientist_users = scan_all_commits(scientist_set)

    # Plot 1: Adoption rate
    plot_adoption_rate(scientist_claude_dates, total_active)

    # Plot 2: Commits share
    plot_commits_share(weekly_all, weekly_scientist, weekly_scientist_users)

    # Quick stats
    total_sci_commits = sum(weekly_scientist.values())
    total_all_commits = sum(weekly_all.values())
    print(f"\nQuick stats:")
    print(f"  Total Claude commits: {total_all_commits:,}")
    print(f"  By ORCID scientists: {total_sci_commits:,} ({total_sci_commits/total_all_commits*100:.1f}%)")
    print(f"  Scientists using Claude: {len(scientist_claude_dates):,} / {total_active:,} active "
          f"({len(scientist_claude_dates)/total_active*100:.2f}%)")


if __name__ == "__main__":
    main()
