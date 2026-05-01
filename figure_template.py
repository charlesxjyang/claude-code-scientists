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


