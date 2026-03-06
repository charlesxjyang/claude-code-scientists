#!/usr/bin/env python3
"""
Figure template for Substack post: "How Many Scientists Use Claude Code?"

Style guide: Saloni's Guide to Data Visualization
  - Light background, clean layout, colorblind-friendly palette
  - Direct labeling over legends where possible
  - All text horizontal
  - Standalone figures: title, subtitle, source, sample size
  - Export SVG + high-res PNG
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates
import numpy as np
import os
from datetime import datetime

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
OUT_DIR = os.path.join(SCRIPT_DIR, "figures")
os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Colorblind-friendly palette (Wong 2011, Nature Methods)
# ---------------------------------------------------------------------------
PALETTE = {
    'blue':    '#0072B2',
    'orange':  '#E69F00',
    'green':   '#009E73',
    'pink':    '#CC79A7',
    'sky':     '#56B4E9',
    'red':     '#D55E00',
    'yellow':  '#F0E442',
    'black':   '#000000',
}

# Ordered list for cycling through categorical data
COLORS = [
    PALETTE['blue'],
    PALETTE['orange'],
    PALETTE['green'],
    PALETTE['pink'],
    PALETTE['sky'],
    PALETTE['red'],
    PALETTE['yellow'],
]

# Semantic colors for this project
C_SCIENTIST = PALETTE['blue']
C_ALL_USERS = '#B0B0B0'
C_HIGHLIGHT = PALETTE['orange']
C_SECONDARY = PALETTE['green']
C_ANNOTATION = '#555555'

# ---------------------------------------------------------------------------
# Global rcParams — Saloni-style: clean, light, readable
# ---------------------------------------------------------------------------
plt.rcParams.update({
    # Background
    'figure.facecolor':  '#FFFFFF',
    'axes.facecolor':    '#FFFFFF',
    'savefig.facecolor': '#FFFFFF',

    # Font — system sans-serif stack
    'font.family':       'sans-serif',
    'font.sans-serif':   ['Helvetica Neue', 'Helvetica', 'Arial', 'DejaVu Sans'],
    'font.size':         12,

    # Axes
    'axes.edgecolor':    '#CCCCCC',
    'axes.linewidth':    0.8,
    'axes.labelcolor':   '#333333',
    'axes.labelsize':    12,
    'axes.titlesize':    14,
    'axes.titleweight':  'bold',
    'axes.titlepad':     14,
    'axes.spines.top':   False,
    'axes.spines.right': False,

    # Ticks
    'xtick.color':       '#555555',
    'ytick.color':       '#555555',
    'xtick.labelsize':   10,
    'ytick.labelsize':   10,
    'xtick.major.size':  4,
    'ytick.major.size':  4,
    'xtick.major.width': 0.6,
    'ytick.major.width': 0.6,

    # Grid — subtle horizontal only by default
    'axes.grid':         True,
    'axes.grid.axis':    'y',
    'grid.color':        '#E5E5E5',
    'grid.linewidth':    0.6,
    'grid.alpha':        1.0,

    # Lines / bars
    'lines.linewidth':   2.0,
    'lines.markersize':  5,

    # Legend
    'legend.frameon':     False,
    'legend.fontsize':    10,
    'legend.labelcolor':  '#333333',

    # Text
    'text.color':        '#333333',
})

# ---------------------------------------------------------------------------
# Sizing constants (Substack content width ~700px)
# ---------------------------------------------------------------------------
FIG_SINGLE = (8, 5)        # single panel
FIG_WIDE   = (10, 5)       # wide single panel
FIG_DOUBLE = (12, 5)       # side-by-side
FIG_SMALL_MULT = (12, 8)   # 2x2 or 2x3 small multiples
DPI = 200

# ---------------------------------------------------------------------------
# Filtered scientist set (shared across all figures)
# Filters: recently_active + ORCID profile linked + published since 2024
# ---------------------------------------------------------------------------
import json

def load_filtered_scientists():
    """Load the filtered scientist set and ORCID user data."""
    FILTERED_FILE = os.path.join(DATA_DIR, "filtered_scientists.json")
    ORCID_FILE = os.path.join(DATA_DIR, "orcid_github_users.json")

    with open(FILTERED_FILE) as f:
        filt = json.load(f)
    with open(ORCID_FILE) as f:
        orcid = json.load(f)

    filtered_set = set(filt['usernames'])  # already lowercase
    total_filtered = filt['total_filtered']

    # Build scientist-with-claude set from filtered
    sci_claude_set = set()
    sci_claude_info = {}
    for username, info in orcid['users'].items():
        u = username.lower()
        if u in filtered_set and info.get('claude_commits', 0) > 0:
            sci_claude_set.add(u)
            sci_claude_info[u] = info

    return filtered_set, total_filtered, sci_claude_set, sci_claude_info, orcid

_FILTERED_CACHE = None
def get_filtered():
    global _FILTERED_CACHE
    if _FILTERED_CACHE is None:
        _FILTERED_CACHE = load_filtered_scientists()
    return _FILTERED_CACHE

FILTER_LABEL = 'active ORCID-GitHub scientists (published since 2024)'


# ===================================================================
# Helper functions
# ===================================================================

def save(fig, name):
    """Save figure as both SVG (editable) and PNG (Substack upload)."""
    fig.savefig(os.path.join(OUT_DIR, f'{name}.svg'),
                format='svg', bbox_inches='tight')
    fig.savefig(os.path.join(OUT_DIR, f'{name}.png'),
                dpi=DPI, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved {name}.svg + .png")


def add_source(fig, text, x=0.99, y=0.01):
    """Add a small source / sample-size note at the bottom-right."""
    fig.text(x, y, text, ha='right', va='bottom',
             fontsize=8, color='#999999', style='italic')


def add_subtitle(ax, text):
    """Add a lighter subtitle below the main title."""
    ax.set_title(text, fontsize=10, fontweight='normal',
                 color='#777777', pad=4, loc='left')


def direct_label(ax, x, y, text, color='#333333', offset=(5, 0), fontsize=10, **kwargs):
    """Place a label directly next to a data point (no legend needed)."""
    ax.annotate(text, xy=(x, y),
                xytext=offset, textcoords='offset points',
                fontsize=fontsize, color=color, va='center', **kwargs)


def bar_labels(ax, bars, fmt='{:.0f}', above=True, fontsize=9, color='#333333'):
    """Add value labels above (or inside) each bar."""
    for bar in bars:
        val = bar.get_height()
        y = bar.get_height() + (bar.get_height() * 0.02 if above else -bar.get_height() * 0.15)
        va = 'bottom' if above else 'top'
        ax.text(bar.get_x() + bar.get_width() / 2, y,
                fmt.format(val), ha='center', va=va,
                fontsize=fontsize, color=color, fontweight='bold')


def pct_formatter(x, _):
    return f'{x:.0f}%'


def k_formatter(x, _):
    if x >= 1000:
        return f'{x/1000:.0f}K'
    return f'{x:.0f}'


# ===================================================================
# Figure templates — fill in with real data
# ===================================================================

def fig_adoption_rate():
    """
    Figure: % of active ORCID scientists using Claude Code over time.
    0-100% y-axis to show scale. Includes monthly growth rate annotation.
    """
    from collections import defaultdict
    from datetime import timedelta

    filtered_set, total_active, sci_claude_set, sci_claude_info, orcid = get_filtered()

    # First Claude date per filtered scientist
    first_use = {}
    for u, info in sci_claude_info.items():
        dates = info.get('claude_dates', [])
        if dates:
            first_use[u] = min(dates)

    # Weekly cumulative
    weekly_new = defaultdict(set)
    for username, first_date in first_use.items():
        dt = datetime.strptime(first_date, '%Y-%m-%d')
        week_start = dt - timedelta(days=dt.weekday())
        weekly_new[week_start.strftime('%Y-%m-%d')].add(username)

    weeks_str = sorted(weekly_new.keys())
    week_dates = [datetime.strptime(w, '%Y-%m-%d') for w in weeks_str]
    cumulative = set()
    cum_counts = []
    pct = []
    for wk in weeks_str:
        cumulative |= weekly_new.get(wk, set())
        cum_counts.append(len(cumulative))
        pct.append(len(cumulative) / total_active * 100)

    # Monthly growth rates (%/month) — compute for each ~4-week window
    growth_rates = []  # (mid_date, rate_pct_per_month)
    for i in range(4, len(pct)):
        delta_pct = pct[i] - pct[i - 4]  # ~4 weeks = ~1 month
        mid_date = week_dates[i - 2]
        growth_rates.append((mid_date, delta_pct))

    # --- Plot ---
    fig, ax = plt.subplots(figsize=FIG_SINGLE)

    # Main adoption line
    ax.fill_between(week_dates, pct, alpha=0.12, color=C_SCIENTIST)
    ax.plot(week_dates, pct, color=C_SCIENTIST, linewidth=2.5, marker='o', markersize=4)

    ax.set_ylim(0, 10)
    ax.set_ylabel('% of active ORCID-linked GitHub scientists')
    ax.set_xlabel('')
    ax.set_title('Claude Code Adoption Among Scientists', loc='left')
    add_subtitle(ax, f'Cumulative share of {total_active:,} {FILTER_LABEL}')

    ax.yaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    ax.yaxis.set_major_locator(ticker.MultipleLocator(1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b\n%Y'))
    ax.xaxis.set_major_locator(mdates.MonthLocator())

    # Direct label at endpoint
    direct_label(ax, week_dates[-1], pct[-1],
                 f'  {pct[-1]:.1f}%\n  ({cum_counts[-1]:,} scientists)',
                 color=C_SCIENTIST, fontsize=11, fontweight='bold')

    # Growth rate annotations — pick 3 well-spaced points: early, mid, recent
    picks = [
        (growth_rates[0], (-30, 18)),     # early (Nov)
        (growth_rates[len(growth_rates)//2], (15, 16)),  # mid (~Dec/Jan)
        (growth_rates[-1], (-35, 18)),    # recent (Feb)
    ]
    for (gr_date, gr_rate), ofs in picks:
        nearest_idx = min(range(len(week_dates)),
                          key=lambda j: abs((week_dates[j] - gr_date).days))
        y_val = pct[nearest_idx]
        ax.annotate(f'+{gr_rate:.2f}%/mo',
                    xy=(gr_date, y_val),
                    xytext=ofs, textcoords='offset points',
                    fontsize=9, color=C_HIGHLIGHT, fontweight='bold',
                    ha='center',
                    arrowprops=dict(arrowstyle='->', color=C_HIGHLIGHT,
                                    lw=0.8, shrinkA=0, shrinkB=2))

    add_source(fig, f'Source: GitHub Search API + ORCID public data. '
                    f'Base: {total_active:,} {FILTER_LABEL}.')
    plt.tight_layout()
    save(fig, 'fig_adoption_rate')


def fig_commits_share():
    """
    Figure: Weekly Claude commits — scientist share as stacked bar + line.
    Top panel: stacked bars (scientists vs others).
    Bottom panel: % share line.
    """
    # --- PLACEHOLDER DATA ---
    weeks = [datetime(2025, 10, 6) + __import__('datetime').timedelta(weeks=i) for i in range(18)]
    all_commits = [50000 + i * 5000 + np.random.randint(-2000, 2000) for i in range(18)]
    sci_commits = [int(a * (0.01 + i * 0.001)) for i, a in enumerate(all_commits)]
    # --- END PLACEHOLDER ---

    non_sci = [a - s for a, s in zip(all_commits, sci_commits)]
    pct_sci = [s / a * 100 if a > 0 else 0 for s, a in zip(sci_commits, all_commits)]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 8), height_ratios=[2, 1],
                                     sharex=True, gridspec_kw={'hspace': 0.08})

    bar_w = 5
    ax1.bar(weeks, sci_commits, width=bar_w, color=C_SCIENTIST, label='ORCID scientists')
    ax1.bar(weeks, non_sci, width=bar_w, bottom=sci_commits, color=C_ALL_USERS, label='Other users')

    ax1.set_ylabel('Claude Code commits / week')
    ax1.set_title('Scientists as a Share of Claude Code Activity', loc='left')
    add_subtitle(ax1, 'Weekly commits by ORCID-linked scientists vs all GitHub users')
    ax1.yaxis.set_major_formatter(ticker.FuncFormatter(k_formatter))
    ax1.legend(loc='upper left')

    ax2.fill_between(weeks, pct_sci, alpha=0.15, color=C_HIGHLIGHT)
    ax2.plot(weeks, pct_sci, color=C_HIGHLIGHT, linewidth=2.5, marker='o', markersize=4)
    ax2.set_ylabel('Scientist share (%)')
    ax2.yaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator())
    ax2.set_ylim(bottom=0)

    # Direct label at endpoint
    direct_label(ax2, weeks[-1], pct_sci[-1], f'  {pct_sci[-1]:.1f}%',
                 color=C_HIGHLIGHT, fontweight='bold')

    add_source(fig, 'Source: GitHub Search API + ORCID public data.')
    plt.tight_layout()
    save(fig, 'fig_commits_share')


def fig_field_breakdown():
    """
    Figure: Horizontal bar chart — Claude adoption rate by scientific field.
    Saloni principle: horizontal text, direct bar labels, ordered by value.
    """
    # --- PLACEHOLDER DATA ---
    fields = [
        'Computer Science', 'Physics', 'Biology', 'Chemistry',
        'Mathematics', 'Engineering', 'Medicine', 'Earth Sciences',
        'Economics', 'Psychology',
    ]
    rates = [4.2, 2.8, 1.9, 1.7, 1.5, 1.3, 0.9, 0.8, 0.7, 0.5]
    # --- END PLACEHOLDER ---

    # Sort ascending (largest at top — Saloni recommends logical ordering)
    order = np.argsort(rates)
    fields_sorted = [fields[i] for i in order]
    rates_sorted = [rates[i] for i in order]

    fig, ax = plt.subplots(figsize=FIG_SINGLE)

    bars = ax.barh(fields_sorted, rates_sorted, color=C_SCIENTIST, height=0.6, edgecolor='none')

    # Direct labels at end of each bar
    for bar, val in zip(bars, rates_sorted):
        ax.text(val + 0.08, bar.get_y() + bar.get_height() / 2,
                f'{val:.1f}%', va='center', fontsize=10, color='#333333', fontweight='bold')

    ax.set_xlabel('% of active researchers using Claude Code')
    ax.set_title('Claude Code Adoption by Scientific Field', loc='left')
    add_subtitle(ax, 'Share of active ORCID researchers in each discipline with at least one Claude commit')

    ax.set_xlim(0, max(rates_sorted) * 1.25)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))

    add_source(fig, 'Source: ORCID profiles + GitHub Search API. Fields from ORCID keywords.')
    plt.tight_layout()
    save(fig, 'fig_field_breakdown')


def fig_dose_response():
    """
    Figure: Small multiples — how metrics scale with Claude usage intensity.
    2x2 or 2x3 grid. Saloni principle: small multiples over one busy chart.
    """
    # --- PLACEHOLDER DATA ---
    intensity_labels = ['1-5\ncommits', '6-20', '21-100', '100+']
    x = np.arange(len(intensity_labels))

    metrics = [
        ('New language adopted', [31, 34, 37, 40], '%'),
        ('Repos created (2026)', [1.2, 2.1, 3.8, 6.5], ''),
        ('Commits to org repos', [3, 8, 14, 20], '%'),
        ('Contributes to 100+ star repos', [1.2, 2.5, 3.8, 5.1], '%'),
    ]
    # --- END PLACEHOLDER ---

    fig, axes = plt.subplots(2, 2, figsize=FIG_SMALL_MULT)

    for idx, (title, vals, unit) in enumerate(metrics):
        ax = axes[idx // 2][idx % 2]
        gradient_colors = [COLORS[0], COLORS[0], COLORS[0], COLORS[0]]
        alphas = [0.4, 0.6, 0.8, 1.0]

        for i, (v, a) in enumerate(zip(vals, alphas)):
            bar = ax.bar(x[i], v, color=C_SCIENTIST, alpha=a, width=0.55, edgecolor='none')
            fmt = f'{v:.0f}{unit}' if unit else f'{v:.1f}'
            ax.text(x[i], v + max(vals) * 0.03, fmt,
                    ha='center', va='bottom', fontsize=10, fontweight='bold', color='#333333')

        ax.set_xticks(x)
        ax.set_xticklabels(intensity_labels, fontsize=9)
        ax.set_title(title, loc='left', fontsize=12)
        ax.set_ylim(0, max(vals) * 1.25)
        ax.set_xlabel('Claude commits', fontsize=9, color='#999999')

        if unit == '%':
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))

    fig.suptitle('How Metrics Scale with Claude Code Usage',
                 fontsize=15, fontweight='bold', x=0.02, ha='left', y=0.98)

    add_source(fig, 'Source: GitHub Search API. n=95K users.')
    plt.tight_layout(rect=[0, 0.02, 1, 0.95])
    save(fig, 'fig_dose_response')


def _draw_violin(ax, plot_data, stage_labels, ns, color, ylabel):
    """Helper: draw violin + boxplot on an axis."""
    parts = ax.violinplot(plot_data, positions=range(len(plot_data)),
                          showmeans=False, showmedians=False, showextrema=False)
    for pc in parts['bodies']:
        pc.set_facecolor(color)
        pc.set_alpha(0.3)
        pc.set_edgecolor(color)
        pc.set_linewidth(1)

    bp = ax.boxplot(plot_data, positions=range(len(plot_data)),
                    widths=0.15, patch_artist=True,
                    showfliers=False, zorder=3)
    for box in bp['boxes']:
        box.set_facecolor(color)
        box.set_alpha(0.7)
        box.set_edgecolor(color)
    for element in ['whiskers', 'caps']:
        for line in bp[element]:
            line.set_color(color)
            line.set_linewidth(1.5)
    for median in bp['medians']:
        median.set_color('white')
        median.set_linewidth(2)

    ax.set_xticks(range(len(stage_labels)))
    ax.set_xticklabels(stage_labels, fontsize=9)
    ax.set_ylabel(ylabel)


def fig_seniority_violin():
    """
    Figure: 2-panel violin plot by researcher seniority.
    A) Claude Code commits/week  B) # repos contributed to with Claude Code.
    """
    PROFILES_FILE = os.path.join(DATA_DIR, "orcid_profiles.json")
    DATES_FILE = os.path.join(DATA_DIR, "user_commit_dates.json")
    REPO_COUNTS_FILE = os.path.join(DATA_DIR, "user_repo_counts.json")

    with open(PROFILES_FILE) as f:
        profiles = json.load(f)
    with open(DATES_FILE) as f:
        user_dates = json.load(f)
    with open(REPO_COUNTS_FILE) as f:
        user_repo_counts = json.load(f)

    filtered_set, total_filtered, sci_claude_set, sci_claude_info, orcid = get_filtered()
    prof_lower = {k.lower(): v for k, v in profiles.items()}

    current_year = 2026
    stages = [
        ('Early career\n(0-2 yrs)',  0,  2),
        ('Postdoc\n(3-5 yrs)',       3,  5),
        ('Mid-career\n(6-10 yrs)',   6, 10),
        ('Senior\n(11-20 yrs)',     11, 20),
        ('Veteran\n(20+ yrs)',      21, 999),
    ]

    # Build per-seniority data for both metrics
    cpw_data = [[] for _ in stages]
    repo_data = [[] for _ in stages]

    for u in sci_claude_set:
        prof = prof_lower.get(u)
        if not prof:
            continue
        yr = prof.get('earliest_pub_year')
        if not yr:
            continue
        career_len = current_year - yr

        # Commits/week
        dates_info = user_dates.get(u)
        if not dates_info:
            continue
        first = datetime.strptime(dates_info['first'], '%Y-%m-%d')
        last = datetime.strptime(dates_info['last'], '%Y-%m-%d')
        weeks = max((last - first).days / 7, 1 / 7)
        cpw = dates_info['commits'] / weeks

        # Repo count
        n_repos = user_repo_counts.get(u, 1)

        for i, (_, lo, hi) in enumerate(stages):
            if lo <= career_len <= hi:
                cpw_data[i].append(cpw)
                repo_data[i].append(n_repos)
                break

    # Filter buckets with enough data
    stage_labels = []
    cpw_plot = []
    repo_plot = []
    ns = []
    for i, (label, _, _) in enumerate(stages):
        if len(cpw_data[i]) >= 2:
            stage_labels.append(label)
            cpw_plot.append(cpw_data[i])
            repo_plot.append(repo_data[i])
            ns.append(len(cpw_data[i]))

    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(14, 7))

    # Panel A: commits/week
    _draw_violin(ax_a, cpw_plot, stage_labels, ns, C_SCIENTIST, 'Claude Code commits / week')
    ax_a.set_ylim(0, 100)
    ax_a.set_xlabel('Career stage (years since first publication)', fontsize=9)
    ax_a.set_title('A. Commit intensity', loc='left', fontweight='bold')
    # Draw n labels inside the plot area
    for i, n in enumerate(ns):
        ax_a.text(i, 97, f'n={n}', ha='center', va='top', fontsize=8, color='#666666')

    # Panel B: repos
    _draw_violin(ax_b, repo_plot, stage_labels, ns, PALETTE['orange'], 'Repos contributed to with Claude Code')
    ax_b.set_ylim(0, max(q3 for q3 in [np.percentile(d, 95) for d in repo_plot]) * 1.3)
    ax_b.set_xlabel('Career stage (years since first publication)', fontsize=9)
    ax_b.set_title('B. Repo breadth', loc='left', fontweight='bold')
    ylim_b = ax_b.get_ylim()
    for i, n in enumerate(ns):
        ax_b.text(i, ylim_b[1] * 0.96, f'n={n}', ha='center', va='top', fontsize=8, color='#666666')

    fig.suptitle('Claude Code Usage Intensity by Researcher Seniority',
                 fontsize=13, fontweight='bold', x=0.02, ha='left', y=0.98)
    fig.text(0.02, 0.94, 'Scientist Claude Code users only, by career stage',
             fontsize=10, color='#666666', ha='left')

    total_n = sum(ns)
    add_source(fig, f'Source: ORCID profiles + GitHub. n={total_n} scientist Claude Code users.')
    plt.tight_layout(rect=[0, 0.03, 1, 0.92])
    save(fig, 'fig_seniority_violin')


def fig_institution():
    """
    Figure: % of scientists at each institution using Claude Code.
    Bar chart of distribution + inset tables for top 10 and bottom 10.
    """
    from collections import Counter

    PROFILES_FILE = os.path.join(DATA_DIR, "orcid_profiles.json")
    with open(PROFILES_FILE) as f:
        profiles = json.load(f)

    filtered_set, total_filtered, sci_claude_set, sci_claude_info, orcid = get_filtered()
    prof_lower = {k.lower(): v for k, v in profiles.items()}

    MIN_SCIENTISTS = 20  # minimum scientists at institution for inclusion

    # Count scientists and Claude users per institution
    inst_total = Counter()
    inst_claude = Counter()
    for u in filtered_set:
        prof = prof_lower.get(u)
        if not prof:
            continue
        for inst in prof.get('institutions', []):
            inst_total[inst] += 1
            if u in sci_claude_set:
                inst_claude[inst] += 1

    # Filter to institutions with enough scientists
    inst_rates = {}
    for inst, total in inst_total.items():
        if total >= MIN_SCIENTISTS:
            rate = inst_claude.get(inst, 0) / total * 100
            inst_rates[inst] = {
                'rate': rate,
                'claude': inst_claude.get(inst, 0),
                'total': total,
            }

    n_inst = len(inst_rates)
    rates = sorted(inst_rates.values(), key=lambda x: x['rate'])
    all_rates = [r['rate'] for r in rates]

    # Top 10 and bottom 10
    ranked = sorted(inst_rates.items(), key=lambda x: x[1]['rate'], reverse=True)
    top10 = ranked[:10]
    bot10 = ranked[-10:][::-1]  # reverse so lowest is last

    fig = plt.figure(figsize=(13, 8))
    ax = fig.add_axes([0.06, 0.1, 0.42, 0.78])

    # Histogram of rates with KDE overlay
    from scipy.stats import gaussian_kde
    bins = np.arange(0, max(all_rates) + 1, 0.5)
    counts, _, _ = ax.hist(all_rates, bins=bins, color=C_SCIENTIST, alpha=0.5, edgecolor='white', linewidth=0.5)

    # KDE smoothed curve
    kde = gaussian_kde(all_rates, bw_method=0.3)
    x_smooth = np.linspace(0, max(all_rates) + 1, 200)
    kde_vals = kde(x_smooth)
    # Scale KDE to match histogram height
    kde_scaled = kde_vals * len(all_rates) * 0.5  # bin width = 0.5
    ax.plot(x_smooth, kde_scaled, color=C_SCIENTIST, linewidth=2.5)

    ax.set_yscale('log')
    ax.set_xlabel('% of scientists using Claude Code')
    ax.set_ylabel('Number of institutions (log scale)')
    ax.axvline(np.median(all_rates), color=PALETTE['orange'], linewidth=2, linestyle='--', label=f'Median: {np.median(all_rates):.1f}%')
    ax.axvline(np.mean(all_rates), color=PALETTE['red'], linewidth=2, linestyle=':', label=f'Mean: {np.mean(all_rates):.1f}%')
    ax.set_ylim(bottom=0.8)
    ax.legend(fontsize=9)

    ax.set_title('Claude Code Adoption Rate by Institution', loc='left')
    add_subtitle(ax, f'Institutions with {MIN_SCIENTISTS}+ ORCID-linked scientists on GitHub (n={n_inst})')

    # Inset: top 10
    ax_top = fig.add_axes([0.52, 0.52, 0.46, 0.40])
    ax_top.set_xlim(0, 1)
    ax_top.set_ylim(0, 11)
    ax_top.set_title('Top 10 institutions', fontsize=10, fontweight='bold', loc='left')
    ax_top.axis('off')

    for i, (inst, info) in enumerate(top10):
        y = 10.2 - i
        short = inst[:30] + '...' if len(inst) > 30 else inst
        ax_top.text(0.0, y, f'{i+1}.', fontsize=8, va='center', color='#888888')
        ax_top.text(0.04, y, short, fontsize=8.5, va='center', color='#333333')
        ax_top.text(0.72, y, f'{info["rate"]:.1f}%', fontsize=9, va='center',
                    fontweight='bold', color=PALETTE['green'], ha='right')
        ax_top.text(0.74, y, f'({info["claude"]}/{info["total"]})', fontsize=7.5,
                    va='center', color='#888888')

    # Inset: bottom 10
    ax_bot = fig.add_axes([0.52, 0.08, 0.46, 0.40])
    ax_bot.set_xlim(0, 1)
    ax_bot.set_ylim(0, 11)
    ax_bot.set_title('Bottom 10 institutions', fontsize=10, fontweight='bold', loc='left')
    ax_bot.axis('off')

    for i, (inst, info) in enumerate(bot10):
        y = 10.2 - i
        short = inst[:30] + '...' if len(inst) > 30 else inst
        rank = n_inst - len(bot10) + i + 1
        ax_bot.text(0.0, y, f'{rank}.', fontsize=8, va='center', color='#888888')
        ax_bot.text(0.07, y, short, fontsize=8.5, va='center', color='#333333')
        ax_bot.text(0.72, y, f'{info["rate"]:.1f}%', fontsize=9, va='center',
                    fontweight='bold', color=PALETTE['red'], ha='right')
        ax_bot.text(0.74, y, f'(0/{info["total"]})', fontsize=7.5,
                    va='center', color='#888888')

    add_source(fig, f'Source: ORCID profiles + GitHub. {n_inst} institutions with {MIN_SCIENTISTS}+ scientists.')
    save(fig, 'fig_institution')


def fig_country():
    """
    Figure: Claude Code adoption by country.
    Left: histogram of adoption rates. Right: top/bottom country tables.
    """
    from collections import Counter

    # ISO 3166 alpha-2 -> name (common ones)
    _COUNTRY_NAMES = {
        'US': 'United States', 'DE': 'Germany', 'IN': 'India', 'CN': 'China',
        'GB': 'United Kingdom', 'BR': 'Brazil', 'ES': 'Spain', 'FR': 'France',
        'IT': 'Italy', 'CA': 'Canada', 'BD': 'Bangladesh', 'AU': 'Australia',
        'CH': 'Switzerland', 'NL': 'Netherlands', 'JP': 'Japan', 'KR': 'South Korea',
        'ID': 'Indonesia', 'IR': 'Iran', 'PT': 'Portugal', 'TR': 'Turkey', 'MX': 'Mexico',
        'AT': 'Austria', 'SE': 'Sweden', 'PK': 'Pakistan', 'CO': 'Colombia',
        'BE': 'Belgium', 'PL': 'Poland', 'NO': 'Norway', 'DK': 'Denmark',
        'FI': 'Finland', 'CL': 'Chile', 'IE': 'Ireland', 'IL': 'Israel',
        'ZA': 'South Africa', 'NG': 'Nigeria', 'TW': 'Taiwan', 'CZ': 'Czechia',
        'GR': 'Greece', 'RO': 'Romania', 'NZ': 'New Zealand', 'HU': 'Hungary',
        'TH': 'Thailand', 'MY': 'Malaysia', 'SG': 'Singapore', 'AR': 'Argentina',
        'EG': 'Egypt', 'SA': 'Saudi Arabia', 'UA': 'Ukraine', 'RU': 'Russia',
        'PH': 'Philippines', 'VN': 'Vietnam', 'KE': 'Kenya', 'PE': 'Peru',
        'EC': 'Ecuador', 'GH': 'Ghana', 'TN': 'Tunisia', 'MA': 'Morocco',
        'LK': 'Sri Lanka', 'NP': 'Nepal', 'ET': 'Ethiopia', 'HK': 'Hong Kong',
    }

    ACTIVE_FILE = os.path.join(DATA_DIR, "active_scientists.json")
    with open(ACTIVE_FILE) as f:
        data = json.load(f)

    MIN_SCIENTISTS = 100

    country_total = Counter()
    country_claude = Counter()
    for u, info in data['scientists'].items():
        c = info.get('country')
        if not c:
            continue
        country_total[c] += 1
        if info.get('claude_user'):
            country_claude[c] += 1

    # Filter to countries with enough scientists
    country_rates = {}
    for code, total in country_total.items():
        if total >= MIN_SCIENTISTS:
            rate = country_claude.get(code, 0) / total * 100
            country_rates[code] = {
                'rate': rate,
                'claude': country_claude.get(code, 0),
                'total': total,
            }

    def country_name(code):
        return _COUNTRY_NAMES.get(code, code)

    n_countries = len(country_rates)
    all_rates = [r['rate'] for r in country_rates.values()]
    overall = sum(country_claude.values()) / sum(country_total.values()) * 100

    # Top and bottom
    ranked = sorted(country_rates.items(), key=lambda x: x[1]['rate'], reverse=True)
    top15 = ranked[:15]
    bot15 = ranked[-15:][::-1]

    fig = plt.figure(figsize=(13, 8))
    ax = fig.add_axes([0.06, 0.1, 0.42, 0.78])

    # Histogram with KDE
    from scipy.stats import gaussian_kde
    bins = np.arange(0, max(all_rates) + 0.5, 0.5)
    ax.hist(all_rates, bins=bins, color=C_SCIENTIST, alpha=0.5, edgecolor='white', linewidth=0.5)

    kde = gaussian_kde(all_rates, bw_method=0.35)
    x_smooth = np.linspace(0, max(all_rates) + 1, 200)
    kde_scaled = kde(x_smooth) * len(all_rates) * 0.5
    ax.plot(x_smooth, kde_scaled, color=C_SCIENTIST, linewidth=2.5)

    ax.grid(False)
    ax.set_xlabel('% of scientists using Claude Code')
    ax.set_ylabel('Number of countries')
    ax.axvline(np.median(all_rates), color=PALETTE['orange'], linewidth=2, linestyle='--',
               label=f'Median: {np.median(all_rates):.1f}%')
    ax.axvline(overall, color=PALETTE['red'], linewidth=2, linestyle=':',
               label=f'Overall: {overall:.1f}%')
    ax.legend(fontsize=9)

    ax.set_title('Claude Code Adoption Rate by Country', loc='left')
    add_subtitle(ax, f'Countries with {MIN_SCIENTISTS}+ ORCID-linked scientists on GitHub (n={n_countries})')

    # Top 15
    ax_top = fig.add_axes([0.52, 0.50, 0.46, 0.44])
    ax_top.set_xlim(0, 1)
    ax_top.set_ylim(0, 16)
    ax_top.set_title('Top 15 countries', fontsize=10, fontweight='bold', loc='left')
    ax_top.axis('off')

    for i, (code, info) in enumerate(top15):
        y = 15.2 - i
        name = country_name(code)
        short = name[:28] + '...' if len(name) > 28 else name
        ax_top.text(0.0, y, f'{i+1}.', fontsize=8, va='center', color='#888888')
        ax_top.text(0.04, y, short, fontsize=8.5, va='center', color='#333333')
        ax_top.text(0.62, y, f'{info["rate"]:.1f}%', fontsize=9, va='center',
                    fontweight='bold', color=PALETTE['green'], ha='right')
        ax_top.text(0.64, y, f'({info["claude"]}/{info["total"]})', fontsize=7.5,
                    va='center', color='#888888')

    # Bottom 15
    ax_bot = fig.add_axes([0.52, 0.05, 0.46, 0.42])
    ax_bot.set_xlim(0, 1)
    ax_bot.set_ylim(0, 16)
    ax_bot.set_title('Bottom 15 countries', fontsize=10, fontweight='bold', loc='left')
    ax_bot.axis('off')

    for i, (code, info) in enumerate(bot15):
        y = 15.2 - i
        name = country_name(code)
        short = name[:28] + '...' if len(name) > 28 else name
        rank = n_countries - len(bot15) + i + 1
        ax_bot.text(0.0, y, f'{rank}.', fontsize=8, va='center', color='#888888')
        ax_bot.text(0.07, y, short, fontsize=8.5, va='center', color='#333333')
        ax_bot.text(0.62, y, f'{info["rate"]:.1f}%', fontsize=9, va='center',
                    fontweight='bold', color=PALETTE['red'], ha='right')
        ax_bot.text(0.64, y, f'({info["claude"]}/{info["total"]})', fontsize=7.5,
                    va='center', color='#888888')

    add_source(fig, f'Source: ORCID + GitHub. {n_countries} countries with {MIN_SCIENTISTS}+ scientists.')
    save(fig, 'fig_country')


def fig_field_adoption():
    """
    Figure: Claude Code adoption % by scientific field.
    Horizontal bar chart sorted by adoption rate.
    """
    ACTIVE_FILE = os.path.join(DATA_DIR, "active_scientists.json")
    with open(ACTIVE_FILE) as f:
        data = json.load(f)

    from collections import Counter
    field_total = Counter()
    field_claude = Counter()
    for u, info in data['scientists'].items():
        field = info.get('field')
        if not field or field == 'Unknown' or field == 'veterinary':
            continue
        field_total[field] += 1
        if info.get('claude_user'):
            field_claude[field] += 1

    # Sort by adoption rate
    fields = sorted(field_total.keys(),
                    key=lambda f: field_claude.get(f, 0) / field_total[f])
    rates = [field_claude.get(f, 0) / field_total[f] * 100 for f in fields]
    claude_n = [field_claude.get(f, 0) for f in fields]
    totals = [field_total[f] for f in fields]

    fig, ax = plt.subplots(figsize=(10, 7))

    y = np.arange(len(fields))
    bars = ax.barh(y, rates, color=C_SCIENTIST, height=0.6, edgecolor='none')

    # Direct labels
    for i, (bar, rate, cn, tn) in enumerate(zip(bars, rates, claude_n, totals)):
        ax.text(rate + 0.08, i, f'{rate:.1f}%  ({cn}/{tn:,})',
                va='center', fontsize=9, fontweight='bold', color='#333333')

    ax.set_yticks(y)
    ax.set_yticklabels(fields, fontsize=10)
    ax.set_xlabel('% of scientists using Claude Code')
    ax.set_xlim(0, max(rates) * 1.6)

    # Overall average line
    total_claude = sum(field_claude.values())
    total_all = sum(field_total.values())
    avg = total_claude / total_all * 100
    ax.axvline(avg, color=PALETTE['orange'], linewidth=1.5, linestyle='--',
               label=f'Overall average: {avg:.1f}%')
    ax.legend(fontsize=9, loc='lower right')

    ax.set_title('Claude Code Adoption by Scientific Field', loc='left')
    add_subtitle(ax, 'ORCID scientists active on GitHub, published since 2024, classified via Scopus + keywords')

    add_source(fig, f'Source: ORCID + GitHub + Scopus. n={total_all:,} classified scientists, '
                    f'{total_claude} Claude Code users.')
    plt.tight_layout()
    save(fig, 'fig_field_adoption')


def fig_seniority():
    """
    Figure: Claude Code adoption rate by researcher seniority.
    Vertical bar chart, x-axis ordered by career stage, any Claude commits.
    """
    PROFILES_FILE = os.path.join(DATA_DIR, "orcid_profiles.json")
    with open(PROFILES_FILE) as f:
        seniority = json.load(f)

    filtered_set, total_filtered, sci_claude_set, sci_claude_info, orcid = get_filtered()
    prof_lower = {k.lower(): v for k, v in seniority.items()}

    # All Claude users (any commits)
    claude_5plus = set()
    for username, info in orcid['users'].items():
        u = username.lower()
        if u in filtered_set and info.get('claude_commits', 0) > 0:
            claude_5plus.add(u)

    current_year = 2026
    stages = [
        ('Early career\n(0-2 yrs)',  0,  2),
        ('Postdoc\n(3-5 yrs)',       3,  5),
        ('Mid-career\n(6-10 yrs)',   6, 10),
        ('Senior\n(11-20 yrs)',     11, 20),
        ('Veteran\n(20+ yrs)',      21, 999),
    ]

    totals = []
    claude_n = []
    for _, lo, hi in stages:
        bt = bc = 0
        for u in filtered_set:
            prof = prof_lower.get(u)
            if not prof:
                continue
            yr = prof.get('earliest_pub_year')
            if not yr:
                continue
            cl = current_year - yr
            if lo <= cl <= hi:
                bt += 1
                if u in claude_5plus:
                    bc += 1
        totals.append(bt)
        claude_n.append(bc)

    rates = [c / t * 100 if t > 0 else 0 for c, t in zip(claude_n, totals)]
    stage_labels = [s[0] for s in stages]

    fig, ax = plt.subplots(figsize=FIG_SINGLE)

    x = np.arange(len(stage_labels))
    bars = ax.bar(x, rates, color=C_SCIENTIST, width=0.55, edgecolor='none')

    # Direct labels above each bar
    for i, (bar, rate, nc, nt) in enumerate(zip(bars, rates, claude_n, totals)):
        ax.text(bar.get_x() + bar.get_width() / 2, rate + 0.05,
                f'{rate:.1f}%\n({nc}/{nt:,})',
                ha='center', va='bottom', fontsize=10, fontweight='bold', color='#333333')

    ax.set_xticks(x)
    ax.set_xticklabels(stage_labels, fontsize=10)
    ax.set_ylabel('% using Claude Code')
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    ax.set_ylim(0, max(rates) * 1.5)
    ax.set_xlabel('Career stage (years since first publication)', fontsize=10)

    ax.set_title('Claude Code Adoption by Researcher Seniority', loc='left')
    add_subtitle(ax, 'Career length estimated from earliest ORCID publication year')

    n_total = sum(totals)
    n_claude = sum(claude_n)
    add_source(fig, f'Source: ORCID profiles + GitHub. n={n_total:,} filtered scientists, '
                    f'{n_claude:,} Claude Code users.')
    plt.tight_layout()
    save(fig, 'fig_seniority')


def fig_scientist_profile():
    """
    Figure: 3-panel profile of scientist Claude Code users.
    A) Commit distribution (histogram, scientists vs all users)
    B) Language mix (scientists vs all, horizontal grouped bar)
    C) Repo ownership (own vs org, scientists vs all)
    """
    from collections import Counter

    filtered_set, total_filtered, sci_claude_set, sci_claude_info, orcid = get_filtered()

    UA_FILE = os.path.join(DATA_DIR, "user_analysis.json")
    with open(UA_FILE) as f:
        ua_data = json.load(f)
    ua = ua_data['users']
    ua_lower = {k.lower(): v for k, v in ua.items()}

    # Scientist set = filtered scientists with Claude commits
    sci_set = sci_claude_set
    sci_repos_raw = {u: info.get('claude_repos', []) for u, info in sci_claude_info.items()}

    # --- Panel A: Commits per week (since first Claude commit) ---
    DATES_FILE = os.path.join(DATA_DIR, "user_commit_dates.json")
    with open(DATES_FILE) as f:
        user_dates = json.load(f)

    from datetime import timedelta
    sci_cpw = []
    nonsci_cpw = []
    for username_lower, info in user_dates.items():
        first = datetime.strptime(info['first'], '%Y-%m-%d')
        last = datetime.strptime(info['last'], '%Y-%m-%d')
        weeks = max((last - first).days / 7, 1 / 7)  # at least 1 day
        cpw = info['commits'] / weeks
        if username_lower in sci_set:
            sci_cpw.append(cpw)
        else:
            nonsci_cpw.append(cpw)

    # --- Panel B: Languages (2026 repos) ---
    sci_langs = Counter()
    nonsci_langs = Counter()
    for username_lower, entry in ua_lower.items():
        is_sci = username_lower in sci_set
        for repo in entry.get('repos_created_2026', []):
            lang = repo.get('language')
            if lang:
                if is_sci:
                    sci_langs[lang] += 1
                else:
                    nonsci_langs[lang] += 1

    # --- Panel C: Own vs org repos ---
    sci_own = sci_org = 0
    for username, repos in sci_repos_raw.items():
        for repo in repos:
            owner = repo.split('/')[0].lower() if '/' in repo else ''
            if owner == username:
                sci_own += 1
            else:
                sci_org += 1

    # ========== PLOT ==========
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(16, 6.5))

    # --- A: Commits per week distribution ---
    bins = [0, 1, 3, 10, 30, 100000]
    bin_labels = ['<1', '1-3', '3-10', '10-30', '30+']
    sci_hist = [sum(1 for c in sci_cpw if lo <= c < hi) for lo, hi in zip(bins, bins[1:])]
    nonsci_hist = [sum(1 for c in nonsci_cpw if lo <= c < hi) for lo, hi in zip(bins, bins[1:])]
    sci_pct = [x / len(sci_cpw) * 100 for x in sci_hist]
    nonsci_pct = [x / len(nonsci_cpw) * 100 for x in nonsci_hist]

    x = np.arange(len(bin_labels))
    w = 0.35
    b1 = ax1.bar(x - w/2, sci_pct, w, color=C_SCIENTIST, label='Scientists')
    b2 = ax1.bar(x + w/2, nonsci_pct, w, color=C_ALL_USERS, label='All other users')

    for bars in [b1, b2]:
        for bar in bars:
            val = bar.get_height()
            if val > 2:
                ax1.text(bar.get_x() + bar.get_width()/2, val + 0.5,
                         f'{val:.0f}%', ha='center', va='bottom', fontsize=8, fontweight='bold')

    ax1.set_xticks(x)
    ax1.set_xticklabels(bin_labels)
    ax1.set_xlabel('Commits per week\n(since first Claude Code commit)', fontsize=10)
    ax1.set_ylabel('% of users')
    ax1.yaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    ax1.set_title('Commit intensity', loc='left', fontsize=12)
    ax1.legend(fontsize=9)

    # --- B: Language comparison (top 8 for scientists, show relative share) ---
    top_sci_langs = sci_langs.most_common(8)
    lang_names = [l for l, _ in top_sci_langs]

    sci_total = sum(sci_langs.values())
    nonsci_total = sum(nonsci_langs.values())
    sci_shares = [sci_langs[l] / sci_total * 100 for l in lang_names]
    nonsci_shares = [nonsci_langs[l] / nonsci_total * 100 for l in lang_names]

    y = np.arange(len(lang_names))
    h = 0.35
    ax2.barh(y + h/2, sci_shares, h, color=C_SCIENTIST, label='Scientists')
    ax2.barh(y - h/2, nonsci_shares, h, color=C_ALL_USERS, label='All other users')

    ax2.set_yticks(y)
    ax2.set_yticklabels(lang_names)
    ax2.set_xlabel('% of repos created in 2026')
    ax2.xaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    ax2.set_title('Languages used', loc='left', fontsize=12)
    ax2.legend(fontsize=9, loc='lower right')
    ax2.invert_yaxis()

    # --- C: Repo breadth — scientists vs all other users ---
    REPO_COUNTS_FILE = os.path.join(DATA_DIR, "user_repo_counts.json")
    with open(REPO_COUNTS_FILE) as f:
        all_repo_counts = json.load(f)

    sci_repos_per = [all_repo_counts.get(u, len(sci_repos_raw.get(u, [])))
                     for u in sci_set if u in all_repo_counts]
    nonsci_repos_per = [v for u, v in all_repo_counts.items() if u not in sci_set]

    repo_bins = ['1 repo', '2-3', '4-10', '11+']
    def bucket_repos(vals):
        return [
            sum(1 for r in vals if r == 1),
            sum(1 for r in vals if 2 <= r <= 3),
            sum(1 for r in vals if 4 <= r <= 10),
            sum(1 for r in vals if r > 10),
        ]

    sci_hist_r = bucket_repos(sci_repos_per)
    nonsci_hist_r = bucket_repos(nonsci_repos_per)
    sci_pct_r = [x / len(sci_repos_per) * 100 for x in sci_hist_r]
    nonsci_pct_r = [x / len(nonsci_repos_per) * 100 for x in nonsci_hist_r]

    x3 = np.arange(len(repo_bins))
    w3 = 0.35
    b3a = ax3.bar(x3 - w3/2, sci_pct_r, w3, color=C_SCIENTIST, label='Scientists')
    b3b = ax3.bar(x3 + w3/2, nonsci_pct_r, w3, color=C_ALL_USERS, label='All other users')

    for bars in [b3a, b3b]:
        for bar in bars:
            val = bar.get_height()
            if val > 2:
                ax3.text(bar.get_x() + bar.get_width()/2, val + 0.5,
                         f'{val:.0f}%', ha='center', va='bottom',
                         fontsize=8, fontweight='bold', color='#333333')

    ax3.set_xticks(x3)
    ax3.set_xticklabels(repo_bins)
    ax3.set_xlabel('Claude repos per user')
    ax3.set_ylabel('% of users')
    ax3.yaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    ax3.set_title('Repo breadth', loc='left', fontsize=12)
    ax3.set_ylim(0, max(max(sci_pct_r), max(nonsci_pct_r)) * 1.3)
    ax3.legend(fontsize=9)

    fig.suptitle('Profile of Scientist Claude Code Users',
                 fontsize=15, fontweight='bold', x=0.02, ha='left', y=1.02)

    add_source(fig, f'Source: GitHub + ORCID. {len(sci_cpw):,} scientists, '
                    f'{len(nonsci_cpw):,} other users. Commits/week since first Claude commit.')
    plt.tight_layout()
    save(fig, 'fig_scientist_profile')


def fig_comparison_bar():
    """
    Figure: Grouped bar chart — scientists vs non-scientists on key metrics.
    Saloni principle: match colors to concepts, direct labels.
    """
    # --- PLACEHOLDER DATA ---
    metrics = ['Repos with\nClaude', 'Median\ncommits', 'Uses in\norg repos', 'New lang\nadopted']
    scientists = [3.2, 28, 18, 42]
    non_scientists = [2.1, 15, 12, 35]
    # --- END PLACEHOLDER ---

    x = np.arange(len(metrics))
    width = 0.32

    fig, ax = plt.subplots(figsize=FIG_SINGLE)

    b1 = ax.bar(x - width/2, scientists, width, color=C_SCIENTIST, label='Scientists')
    b2 = ax.bar(x + width/2, non_scientists, width, color=C_ALL_USERS, label='Non-scientists')

    ax.set_xticks(x)
    ax.set_xticklabels(metrics, fontsize=10)
    ax.set_title('Scientists vs Non-Scientists', loc='left')
    add_subtitle(ax, 'Key Claude Code usage metrics compared')
    ax.legend(loc='upper right')

    # Direct labels on bars
    for bars in [b1, b2]:
        for bar in bars:
            val = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, val + max(scientists) * 0.02,
                    f'{val:.0f}', ha='center', va='bottom', fontsize=9, fontweight='bold')

    ax.set_ylim(0, max(scientists) * 1.3)
    add_source(fig, 'Source: GitHub + ORCID. Scientists: ORCID-linked accounts.')
    plt.tight_layout()
    save(fig, 'fig_comparison_bar')


def fig_timeline_annotations():
    """
    Figure: Two-line timeline — total Claude commits vs scientist commits per week.
    Annotated with scientist share % at key points.
    """
    WEEKLY_FILE = os.path.join(DATA_DIR, "weekly_sci_commits.json")
    with open(WEEKLY_FILE) as f:
        data = json.load(f)

    weekly_all = data['weekly_all']
    weekly_sci = data['weekly_sci']

    # Sort and drop partial weeks at edges
    weeks = sorted(set(weekly_all.keys()) & set(weekly_sci.keys()))
    weeks = [w for w in weeks if '2025-10-13' <= w <= '2026-02-09']

    week_dates = [datetime.strptime(w, '%Y-%m-%d') for w in weeks]
    all_vals = [weekly_all[w] for w in weeks]
    sci_vals = [weekly_sci[w] for w in weeks]
    pct_vals = [s / a * 100 if a > 0 else 0 for s, a in zip(sci_vals, all_vals)]

    fig, ax = plt.subplots(figsize=FIG_WIDE)

    # Total commits line
    ax.fill_between(week_dates, all_vals, alpha=0.08, color=C_ALL_USERS)
    ax.plot(week_dates, all_vals, color='#888888', linewidth=2, label='All users')

    # Scientist commits on same axis
    ax.fill_between(week_dates, sci_vals, alpha=0.2, color=C_SCIENTIST)
    ax.plot(week_dates, sci_vals, color=C_SCIENTIST, linewidth=2.5, label='Scientists')

    ax.set_yscale('log')
    ax.set_ylabel('Claude Code commits / week (log scale)')
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(
        lambda x, p: f'{x/1000:.0f}K' if x >= 1000 else f'{x:.0f}'))

    ax.set_title('Claude Code Commits: All Users vs Scientists', loc='left')
    add_subtitle(ax, f'Weekly commits on public GitHub with Co-Authored-By: Claude signature')

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d\n%Y'))
    ax.xaxis.set_major_locator(mdates.MonthLocator())

    # Annotate scientist share % at a few points
    annotations = [
        (2, (0, 30)),      # early
        (8, (0, 30)),      # mid
        (-5, (30, 35)),    # jan
        (-2, (-50, -40)),  # recent
    ]
    for idx, ofs in annotations:
        w = week_dates[idx]
        s = sci_vals[idx]
        pct = pct_vals[idx]
        ax.annotate(f'{pct:.2f}%\nof total',
                    xy=(w, s),
                    xytext=ofs, textcoords='offset points',
                    fontsize=8.5, color=C_HIGHLIGHT, fontweight='bold',
                    ha='center',
                    arrowprops=dict(arrowstyle='->', color=C_HIGHLIGHT, lw=1))

    ax.legend(loc='upper left', fontsize=9)

    add_source(fig, f'Source: GitHub Search API + ORCID. Scientists: {FILTER_LABEL}.')
    plt.tight_layout()
    save(fig, 'fig_timeline')


# ===================================================================
# Run all templates to see the style
# ===================================================================
if __name__ == '__main__':
    np.random.seed(42)
    print("Generating template figures (placeholder data)...")
    fig_adoption_rate()
    fig_commits_share()
    fig_field_breakdown()
    fig_dose_response()
    fig_seniority()
    fig_scientist_profile()
    fig_comparison_bar()
    fig_timeline_annotations()
    print(f"\nAll template figures saved to {OUT_DIR}/")
    print("Replace PLACEHOLDER DATA sections with real data from your pipeline.")
