#!/usr/bin/env python3
"""
Figure 3 — Adoption by field, with selection correction (3 panels)
  (a) Raw adoption rate by field (within ORCID+GitHub+active cohort)
  (b) ORCID base rate by field (from OpenAlex 2024-2026 active authors)
  (c) Selection-corrected adoption rate by field:
       P(adopt | scientist) = P(ORCID|sci) × P(GitHub|ORCID) × P(adopt|cohort)
"""
import json
import os
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

from figure_template import (
    DATA_DIR, OUT_DIR, DPI, PALETTE,
    C_SCIENTIST, C_HIGHLIGHT, C_SECONDARY, C_ALL_USERS,
    pct_formatter, save, add_source, add_subtitle,
)

ACTIVE_FILE = os.path.join(DATA_DIR, "active_scientists.json")
OPENALEX_FILE = os.path.join(DATA_DIR, "openalex_author_baseline.json")
ORCID_GH_FILE = os.path.join(DATA_DIR, "orcid_full_baseline_active.json")  # full ORCID dump 2024

# Map our 16 scientist-fields → list of OpenAlex 26 fields whose counts to sum.
# Preserves overall consistency (Scopus ASJC top-level groups).
FIELD_MAP = {
    "Computer Science":          ["Computer Science"],
    "Biology & Life Sciences":   ["Biochemistry, Genetics and Molecular Biology",
                                  "Agricultural and Biological Sciences",
                                  "Immunology and Microbiology"],
    "Engineering":               ["Engineering", "Chemical Engineering"],
    "Earth & Environmental":     ["Earth and Planetary Sciences",
                                  "Environmental Science", "Energy"],
    "Medicine & Health":         ["Medicine", "Health Professions", "Nursing",
                                  "Dentistry",
                                  "Pharmacology, Toxicology and Pharmaceutics"],
    "Physics & Astronomy":       ["Physics and Astronomy"],
    "Social Sciences":           ["Social Sciences"],
    "Mathematics":               ["Mathematics", "Decision Sciences"],
    "Chemistry":                 ["Chemistry"],
    "Neuroscience":              ["Neuroscience", "Psychology"],
    "Economics & Business":      ["Economics, Econometrics and Finance",
                                  "Business, Management and Accounting"],
    "Materials Science":         ["Materials Science"],
    "Arts & Humanities":         ["Arts and Humanities"],
    "veterinary":                ["Veterinary"],
    # Multidisciplinary, Health Sciences: no clean ASJC mapping → omit from baseline
}


def load():
    with open(ACTIVE_FILE) as f:
        active = json.load(f)
    with open(OPENALEX_FILE) as f:
        oa = json.load(f)
    with open(ORCID_GH_FILE) as f:
        og = json.load(f)
    return active, oa, og


def main():
    active, oa, og = load()

    scientists = active["scientists"]

    # ---- Panel A: raw adoption rate per scientist field -----------
    by_field_total = Counter()
    by_field_claude = Counter()
    for u, info in scientists.items():
        f = info.get("field")
        if not f:
            continue
        by_field_total[f] += 1
        if info.get("claude_user"):
            by_field_claude[f] += 1

    # ---- Panel B: ORCID base rate by field (from OpenAlex sample) -
    oa_field_total = oa["summary"]["by_field_total"]      # {field: count}
    oa_field_orcid = oa["summary"]["by_field_orcid"]
    orcid_rate_by_our_field = {}
    for our_field, oa_fields in FIELD_MAP.items():
        tot = sum(oa_field_total.get(f, 0) for f in oa_fields)
        with_o = sum(oa_field_orcid.get(f, 0) for f in oa_fields)
        if tot:
            orcid_rate_by_our_field[our_field] = (with_o / tot, tot, with_o)

    # ---- Panel C: ORCID→GitHub linkage rate by field --------------
    # Source: full ORCID dump 2024, restricted to active (>=1 pub 2024-2026).
    # The dump's "by_field_active_*" maps use the same 27-field Scopus middle
    # level as our OpenAlex 26-field taxonomy, so the FIELD_MAP crosswalk works.
    og_orcid_by_field = og.get("by_field_active_orcid", {})
    og_gh_by_field = og.get("by_field_active_github", {})
    gh_rate_by_our_field = {}
    for our_field, oa_fields in FIELD_MAP.items():
        tot = sum(og_orcid_by_field.get(f, 0) for f in oa_fields)
        with_g = sum(og_gh_by_field.get(f, 0) for f in oa_fields)
        if tot:
            gh_rate_by_our_field[our_field] = (with_g / tot, tot, with_g)

    # ---- Build the corrected estimate -----------------------------
    fields = sorted(
        [f for f in by_field_total if f in FIELD_MAP and by_field_total[f] >= 50],
        key=lambda f: -by_field_total[f],
    )

    raw_rate = []
    base_rate = []
    gh_rate = []
    corr_rate = []  # P(adopt | scientist) ≈ ORCID × GH × cohort_adopt
    for f in fields:
        raw = (by_field_claude[f] / by_field_total[f]) if by_field_total[f] else 0
        raw_rate.append(raw * 100)

        orate = orcid_rate_by_our_field.get(f, (None, 0, 0))[0]
        base_rate.append((orate or 0) * 100)

        ghr = gh_rate_by_our_field.get(f, (None, 0, 0))[0]
        gh_rate.append((ghr or 0) * 100)

        if orate is not None and ghr is not None:
            # Selection-corrected adoption rate among all active scientists
            corr = (orate * ghr * raw) * 100  # in %
        else:
            corr = 0.0
        corr_rate.append(corr)

    # ---- Plot: 3 panels horizontal with shared y-axis (fields) -----
    fig, axes = plt.subplots(
        1, 3, figsize=(15, 7),
        gridspec_kw={"width_ratios": [1, 1, 1.2], "wspace": 0.4},
    )
    axA, axB, axC = axes

    y = np.arange(len(fields))
    pretty_field = [f.replace("Biology & Life Sciences", "Bio & Life Sci")
                     .replace("Earth & Environmental", "Earth & Env.")
                     .replace("Economics & Business", "Econ & Business")
                     .replace("Medicine & Health", "Medicine & Health")
                     .replace("Physics & Astronomy", "Physics & Astro")
                     .replace("Materials Science", "Materials Sci")
                     .replace("Arts & Humanities", "Arts & Humanities")
                     for f in fields]

    # ===================================================================
    # Panel A — Raw adoption rate (within cohort)
    # ===================================================================
    overall_raw = sum(by_field_claude.values()) / max(1, sum(by_field_total.values())) * 100
    barsA = axA.barh(y, raw_rate, color=C_SCIENTIST, edgecolor="white",
                     linewidth=1.2, height=0.72)
    axA.axvline(overall_raw, color=C_HIGHLIGHT, linestyle="--", linewidth=1.2)
    axA.text(overall_raw + 0.03, len(fields) - 0.4, f"  overall {overall_raw:.1f}%",
             color=C_HIGHLIGHT, fontsize=9, fontweight="bold", va="top")
    for i, (val, total) in enumerate(zip(raw_rate, [by_field_total[f] for f in fields])):
        axA.text(val + 0.05, i, f" {val:.1f}%  (n={total:,})",
                 va="center", fontsize=8.5, color="#444444")

    axA.set_yticks(y)
    axA.set_yticklabels(pretty_field, fontsize=9)
    axA.invert_yaxis()
    axA.xaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    axA.set_xlim(0, max(raw_rate) * 1.45)
    axA.set_title("(a) Raw adoption rate within cohort", loc="left")

    # ===================================================================
    # Panel B — ORCID base rate by field (from OpenAlex sample)
    # ===================================================================
    barsB = axB.barh(y, base_rate, color=C_SECONDARY, edgecolor="white",
                     linewidth=1.2, height=0.72)
    overall_base = (oa["summary"]["with_orcid"] /
                    max(1, oa["summary"]["total_authors"])) * 100
    axB.axvline(overall_base, color=C_HIGHLIGHT, linestyle="--", linewidth=1.2)
    axB.text(overall_base + 1, len(fields) - 0.4, f"  global {overall_base:.0f}%",
             color=C_HIGHLIGHT, fontsize=9, fontweight="bold", va="top")
    for i, val in enumerate(base_rate):
        axB.text(val + 0.6, i, f" {val:.0f}%", va="center",
                 fontsize=8.5, color="#444444")

    axB.set_yticks(y)
    axB.set_yticklabels([])
    axB.xaxis.set_major_formatter(ticker.FuncFormatter(pct_formatter))
    axB.set_xlim(0, 100)
    axB.invert_yaxis()
    axB.set_title("(b) ORCID coverage among active authors", loc="left")

    # ===================================================================
    # Panel C — Selection-corrected population-level rate
    # ===================================================================
    # plot bars in basis points (much more readable than tiny %)
    corr_bp = [c * 100 for c in corr_rate]   # convert % -> basis points
    barsC = axC.barh(y, corr_bp, color=C_HIGHLIGHT, edgecolor="white",
                     linewidth=1.2, height=0.72)
    overall_corr_bp = (sum(corr_bp[i] * by_field_total[fields[i]] for i in range(len(fields))) /
                       max(1, sum(by_field_total[f] for f in fields)))
    axC.axvline(overall_corr_bp, color=PALETTE["red"], linestyle="--", linewidth=1.2)
    axC.text(overall_corr_bp + 0.03, len(fields) - 0.4,
             f"  overall {overall_corr_bp:.1f} bp",
             color=PALETTE["red"], fontsize=9, fontweight="bold", va="top")
    for i, val in enumerate(corr_bp):
        axC.text(val + 0.05, i, f" {val:.1f} bp", va="center",
                 fontsize=8.5, color="#444444")

    axC.set_yticks(y)
    axC.set_yticklabels([])
    axC.invert_yaxis()
    axC.set_xlim(0, max(corr_bp) * 1.4)
    axC.set_xlabel("Basis points (1 bp = 0.01%)")
    axC.set_title("(c) Selection-corrected population rate", loc="left")

    add_source(
        fig,
        f"Source: GitHub Search API + ORCID public data + OpenAlex 2024–2026 sample. "
        f"Scientists: n={active['total']:,}; ORCID baseline n={oa['unique_authors']:,}; "
        f"GitHub-linkage baseline n={og.get('n_active', 0):,} (full ORCID 2024 dump, active).",
    )

    plt.tight_layout()
    out_base = os.path.join(OUT_DIR, "fig3_field")
    fig.savefig(out_base + ".svg", format="svg", bbox_inches="tight")
    fig.savefig(out_base + ".png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_base}.svg + .png")

    # Also print the underlying numbers for the table
    print("\nSelection-correction summary (per field):")
    print(f"  {'Field':25s}  {'cohort %':>8}  {'ORCID %':>7}  {'GH/ORCID %':>10}  {'corrected %':>11}")
    for i, f in enumerate(fields):
        print(f"  {f:25s}  {raw_rate[i]:>7.2f}%  {base_rate[i]:>6.1f}%  "
              f"{gh_rate[i]:>9.2f}%  {corr_rate[i]:>10.4f}%")


if __name__ == "__main__":
    main()
