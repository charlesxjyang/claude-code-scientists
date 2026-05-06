# Claude Code Scientists: Measuring AI Adoption among Scientists

Replication code and data for the working paper documenting Claude Code
adoption among ORCID-linked active scientists, October 2025 – February 2026.

By exploiting Claude Code's default `Co-Authored-By: Claude` commit trailer,
we measure individual-level LLM coding-tool adoption directly from public
GitHub commit metadata, without relying on stylometric inference or
self-report.

## Headline numbers (Oct 1 2025 – Feb 28 2026)

| Quantity                                          | Value             |
| ------------------------------------------------- | ----------------- |
| Claude Code commits on public GitHub              | 9,998,527         |
| Active ORCID-linked scientists in cohort          | 16,010            |
| Cohort adoption rate                              | 2.51%             |
| Monthly cohort growth rate                        | 0.5 pp / month    |
| ORCID adoption among active researchers (Stage 1) | 50.7%             |
| GitHub-link rate among ORCID'd researchers (Stage 2) | 0.367%         |
| Implied population-corrected adoption rate        | ~47 / Mn          |
| Adopter–non-adopter median GitHub-tenure gap      | 2.6 years (within field) |
| Mann-Whitney one-sided *p*                         | 4 × 10⁻²⁶         |

Adopters do not differ from non-adopters on citation impact within field
(Kolmogorov–Smirnov *p* > 0.05 in all six fields tested), so selection
operates on coding experience rather than research productivity. The
ex-Computer Science adoption rate rises monotonically with seniority
(1.9% in 0–2 yrs since first publication → 4.0% in 13–19 yrs); CS shows
a mild U-shape.

## Directory layout

```
.
├── make_figures/                 Figure-generation scripts (Python)
│   ├── figure_template.py        Shared style helpers (palette, fonts, save())
│   ├── fig1_diffusion.py         Figure 1: cumulative adoption + weekly all-vs-sci
│   ├── fig2_career.py            Figure 2: adoption + commits + repos by career stage
│   ├── fig3_field.py             Appendix A.6: field rate, ORCID baseline, corrected rate
│   ├── fig4_geography.py         Appendix A.7: country and institution heterogeneity
│   ├── fig5_experience.py        Figure 5: time-on-GitHub by adopter status
│   ├── figS2_seniority_tenure.py Appendix A.9: within-seniority tenure gap robustness
│   └── figS1_pub_vs_github.py    Deprecated; kept for archival reference
├── figures/                      Generated SVG + PNG outputs (LFS-tracked)
├── scripts/                      Data-collection + analysis pipeline
│   │
│   │ — Stage 1: GitHub commit corpus —
│   ├── find_claude_commits.py    Scrape Co-Authored-By trailers from GitHub Search API
│   ├── analyze_users.py          Per-author commit-list aggregation
│   │
│   │ — Stage 2: ORCID-linked scientist cohort —
│   ├── find_orcid_users_api.py   Match committers → ORCID via API
│   ├── fetch_orcid_profiles.py   Pull ORCID metadata
│   ├── fetch_orcid_locations.py  Pull country / institution self-report
│   ├── classify_orcid_scopus.py  Map publication journals → Scopus ASJC fields
│   ├── classify_active_scientists.py  Apply active-scientist filters → active_scientists.json
│   │
│   │ — Stage 3: Selection-correction baselines —
│   ├── fetch_openalex_author_baseline.py  OpenAlex active-author sample (Stage 1 baseline)
│   ├── fetch_orcid_github_baseline.py     ORCID API GitHub-link sample (deprecated)
│   ├── parse_orcid_dump.py                Stream full ORCID 2024 dump (Stage 2 primary)
│   ├── aggregate_orcid_dump.py            Aggregate dump → by-field / by-country baselines
│   │
│   │ — Stage 4: Per-scientist enrichments —
│   ├── fetch_scientist_citations.py       OpenAlex citation counts per ORCID
│   ├── fetch_scientist_github_accounts.py GitHub account creation date
│   ├── fetch_scientist_institutions.py    OpenAlex last_known_institution per ORCID
│   ├── parse_orcid_pedigree.py            ORCID employment + education from full dump
│   ├── refine_institutions.py             Smart current-employer picker (ORCID emp-block primary)
│   ├── merge_institutions.py              Earlier institution-merge approach (deprecated)
│   ├── backfill_latest_pub.py             Patch missing latest_pub_year fields
│   │
│   │ — Stage 5: Robustness + auxiliary analyses —
│   ├── extra_controls.py                  A.10–A.11 citation null × career stage
│   ├── robustness_checks.py               A.13 cohort-window / decile robustness
│   ├── within_field_adoption_by_bucket.py A.12 within-field × lag-bucket adoption rates
│   ├── fetch_first_commit.py              Per-author first-commit date (exploratory)
│   │
│   ├── asjc_codes.csv                     Scopus ASJC code definitions
│   ├── scopus_titles.tsv                  Scopus journal title → ID
│   └── scopus_subject_areas.tsv           Scopus journal ID → subject area
│
├── data/                       Checkpointed JSON outputs (LFS-tracked)
├── submissions/economics_letters/   Manuscript LaTeX + bib + build script
│   ├── combined_manuscript.tex      Single-doc paper with appendix toggle (\renderappendix)
│   ├── refs.bib                     BibTeX references
│   └── build.sh                     pdflatex + bibtex compile recipe
├── run_pipeline.sh             End-to-end pipeline runner
├── requirements.txt
├── LICENSE                     MIT (code), CC-BY-4.0 (data + figures)
└── CITATION.cff
```

## Setup

```bash
# 1. Clone with LFS (required — most data files are stored via Git LFS)
git lfs install
git clone https://github.com/charlesxjyang/claude-code-scientists.git
cd claude-code-scientists

# 2. Python deps
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Reproducing the figures only

If you trust the checkpointed data in `data/` (this is the version used in
the paper), just render the figures:

```bash
./run_pipeline.sh --skip-fetch
```

Note: `data/claude_commits_all.json` (the raw commit corpus, ~4.6 GB) is
**not** included in the LFS-tracked data because it exceeds GitHub's free LFS
quota. Two ways to obtain it:

1. Run the full pipeline (Stage 1 only, see below) to regenerate it.
2. Set `CLAUDE_COMMITS_PATH` to point to a copy you already have:
   ```bash
   export CLAUDE_COMMITS_PATH=/path/to/claude_commits_all.json
   ./run_pipeline.sh --skip-fetch
   ```

Figures 3, 4, 5, S1 do not depend on this file and can be regenerated from
the LFS-tracked data files alone.

### Reproducing the entire pipeline from scratch

You'll need three credentials, all free:

| Variable               | Source                                         |
| ---------------------- | ---------------------------------------------- |
| `GITHUB_TOKEN`         | https://github.com/settings/tokens (no scopes) |
| `ORCID_CLIENT_ID`      | https://orcid.org/developer-tools              |
| `ORCID_CLIENT_SECRET`  | (same)                                         |

```bash
export GITHUB_TOKEN=ghp_...
export ORCID_CLIENT_ID=APP-...
export ORCID_CLIENT_SECRET=...
./run_pipeline.sh
```

Total wall-clock for full re-run: ~1 day, dominated by the GitHub Search API
rate limits during commit collection.

## Data sources

| Source                                                        | License        | Used for                                  |
| ------------------------------------------------------------- | -------------- | ----------------------------------------- |
| GitHub Search Commits API                                     | TOS            | Claude Code commit detection              |
| GitHub Users / Repos API                                      | TOS            | account creation, profile data            |
| ORCID public registry + API                                   | CC0            | researcher → GitHub link                  |
| OpenAlex                                                      | CC0            | active-author + ORCID-rate baselines      |
| Scopus journal-to-ASJC mapping (via Elsevier journal lookup)  | Elsevier terms | field classification                      |

## Citation

If you use this code or data, please cite:

> Yang, C. (2026). *Claude Code Scientists: Measuring AI Adoption among
> Scientists.* Economics Letters (under review).

A machine-readable citation entry is available in `CITATION.cff`.

## Disclosure

The author declares no competing interests. Replication materials in this
repository were authored with substantial assistance from Claude Code.
