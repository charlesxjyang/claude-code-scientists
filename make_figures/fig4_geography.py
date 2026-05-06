#!/usr/bin/env python3
"""
Figure 4 — Geography of Claude Code adoption (2 panels)
  (a) Country-level adoption rate within ORCID+GitHub cohort, top/bottom 10
  (b) Institution-level adoption distribution + top 15
"""
import json
import os
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

from figure_template import (
    DATA_DIR, OUT_DIR, DPI, PALETTE,
    C_SCIENTIST, C_HIGHLIGHT, C_SECONDARY,
    pct_formatter, save, add_source, add_subtitle,
)

ACTIVE_FILE = os.path.join(DATA_DIR, "active_scientists.json")

# ISO 3166 alpha-2 → display name
COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "DE": "Germany",
    "FR": "France", "JP": "Japan", "CN": "China", "IN": "India",
    "CA": "Canada", "AU": "Australia", "BR": "Brazil", "IT": "Italy",
    "ES": "Spain", "NL": "Netherlands", "SE": "Sweden", "FI": "Finland",
    "CH": "Switzerland", "BE": "Belgium", "AT": "Austria", "DK": "Denmark",
    "NO": "Norway", "IE": "Ireland", "PL": "Poland", "PT": "Portugal",
    "RU": "Russia", "KR": "South Korea", "TW": "Taiwan", "MX": "Mexico",
    "TR": "Turkey", "IL": "Israel", "SG": "Singapore", "ID": "Indonesia",
    "ZA": "South Africa", "AR": "Argentina", "CL": "Chile", "PK": "Pakistan",
    "EG": "Egypt", "GR": "Greece", "CZ": "Czech Republic", "NG": "Nigeria",
    "MY": "Malaysia", "RO": "Romania", "HU": "Hungary", "NZ": "New Zealand",
    "VN": "Vietnam", "TH": "Thailand", "BD": "Bangladesh", "SA": "Saudi Arabia",
    "IR": "Iran", "UA": "Ukraine", "PH": "Philippines",
}


def main():
    with open(ACTIVE_FILE) as f:
        data = json.load(f)
    sci = data["scientists"]

    # ─── Panel A: country breakdown ──────────────────────────────────
    country_total = Counter()
    country_claude = Counter()
    for u, info in sci.items():
        c = info.get("country")
        if not c:
            continue
        country_total[c] += 1
        if info.get("claude_user"):
            country_claude[c] += 1

    MIN_SCI = 100
    countries = []
    for code, total in country_total.items():
        if total >= MIN_SCI:
            rate = country_claude[code] / total * 100
            countries.append((code, total, country_claude[code], rate))

    overall_rate = sum(country_claude.values()) / max(1, sum(country_total.values())) * 100

    # ranking
    countries.sort(key=lambda x: -x[3])
    top10 = countries[:10]
    bot10 = countries[-10:]  # already descending from the sort above
    show = top10 + [None] + bot10  # spacer

    # ─── Panel B: institution breakdown ─────────────────────────────
    inst_total = Counter()
    inst_claude = Counter()
    for u, info in sci.items():
        insts = info.get("institutions") or []
        if not insts:
            continue
        inst = insts[0]  # primary affiliation
        inst_total[inst] += 1
        if info.get("claude_user"):
            inst_claude[inst] += 1

    MIN_INST = 20
    institutions = []
    for inst, total in inst_total.items():
        if total >= MIN_INST:
            rate = inst_claude[inst] / total * 100
            institutions.append((inst, total, inst_claude[inst], rate))

    institutions.sort(key=lambda x: -x[3])
    inst_top10 = institutions[:10]

    inst_rates = [r[3] for r in institutions]

    # ─── Plot ────────────────────────────────────────────────────────
    fig, (axA, axB) = plt.subplots(
        1, 2, figsize=(14, 7),
        gridspec_kw={"width_ratios": [1, 1.3], "wspace": 0.85},
    )

    # ===== Panel A: country bar chart (top + bottom) ===========
    ys = []
    labels = []
    rates = []
    counts = []
    totals = []
    for i, item in enumerate(show):
        if item is None:
            ys.append(None)
            continue
        code, total, claude, rate = item
        labels.append(COUNTRY_NAMES.get(code, code))
        rates.append(rate)
        counts.append(claude)
        totals.append(total)

    n_top, n_bot = len(top10), len(bot10)
    y = np.arange(n_top + n_bot + 1)
    valid_idx = [i for i in range(len(y)) if i != n_top]  # skip the spacer position

    bars_top = axA.barh([y[i] for i in valid_idx[:n_top]], rates[:n_top],
                        color=C_SCIENTIST, edgecolor="white", linewidth=1.2,
                        height=0.72)
    bars_bot = axA.barh([y[i] for i in valid_idx[n_top:]], rates[n_top:],
                        color="#B0B0B0", edgecolor="white",
                        linewidth=1.2, height=0.72)

    for i_v, idx in enumerate(valid_idx):
        axA.text(rates[i_v] + 0.04, y[idx],
                 f" {rates[i_v]:.1f}%  (n={totals[i_v]:,})",
                 va="center", fontsize=8.5, color="#444444")
    axA.axvline(overall_rate, color=C_HIGHLIGHT, linestyle="--", linewidth=1.2)
    axA.text(overall_rate + 0.05, -0.7, f"  overall {overall_rate:.1f}%",
             color=C_HIGHLIGHT, fontsize=9, fontweight="bold", va="top")

    # spacer label
    axA.text(0, y[n_top], "···  middle countries omitted  ···", va="center",
             color="#999999", fontsize=8.5, fontstyle="italic")

    axA.set_yticks([y[i] for i in valid_idx])
    axA.set_yticklabels(labels, fontsize=9)
    axA.invert_yaxis()
    axA.xaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    axA.set_xlim(0, max(rates) * 1.35)
    axA.set_title("(a) Adoption by country (top 10 vs bottom 10)", loc="left")

    # ===== Panel B: top 10 institutions (horizontal bar) ==========
    inst_y = np.arange(len(inst_top10))
    inst_names = []
    inst_rates_top = []
    inst_totals_top = []
    inst_claude_top = []
    for name, total, claude, rate in inst_top10:
        # Truncate long institution names
        short = name if len(name) <= 38 else name[:36] + "…"
        inst_names.append(short)
        inst_rates_top.append(rate)
        inst_totals_top.append(total)
        inst_claude_top.append(claude)

    axB.barh(inst_y, inst_rates_top,
             color=C_SCIENTIST, edgecolor="white", linewidth=1.2,
             height=0.72)
    for i, (rate, total, claude) in enumerate(zip(inst_rates_top, inst_totals_top, inst_claude_top)):
        axB.text(rate + 0.15, i, f" {rate:.1f}%  ({claude}/{total})",
                 va="center", fontsize=8.5, color="#444444")
    axB.axvline(overall_rate, color=C_HIGHLIGHT, linestyle="--", linewidth=1.2)
    axB.text(overall_rate + 0.1, -0.7, f"  overall {overall_rate:.1f}%",
             color=C_HIGHLIGHT, fontsize=9, fontweight="bold", va="top")

    axB.set_yticks(inst_y)
    axB.set_yticklabels(inst_names, fontsize=9)
    axB.invert_yaxis()
    axB.xaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    axB.set_xlim(0, max(inst_rates_top) * 1.35)
    axB.set_title("(b) Adoption by institution (top 10)", loc="left")

    add_source(
        fig,
        f"Source: GitHub Search API + ORCID public data. "
        f"n={data['total']:,} active scientists, {data['claude_users']} Claude Code adopters.",
    )

    plt.tight_layout()
    out_base = os.path.join(OUT_DIR, "fig4_geography")
    fig.savefig(out_base + ".svg", format="svg", bbox_inches="tight")
    fig.savefig(out_base + ".png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_base}.svg + .png")


if __name__ == "__main__":
    main()
