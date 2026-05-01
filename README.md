# Diffusion of AI Coding Assistants Among Active Scientists: Evidence from Claude Code

Replication code and data for the working paper documenting Claude Code
adoption among ORCID-linked active scientists, October 2025 – February 2026.

By exploiting Claude Code's default `Co-Authored-By: Claude` commit trailer,
we measure individual-level LLM coding-tool adoption directly from public
GitHub commit metadata, without relying on stylometric inference or
self-report.

## Headline numbers (Oct 14 2025 – Feb 28 2026)

| Quantity                                    | Value      |
| ------------------------------------------- | ---------- |
| Claude Code commits on public GitHub        | 9,998,527  |
| Active ORCID-linked scientists in cohort    | 16,010     |
| Cohort adoption rate                        | 2.07%      |
| ORCID adoption among active researchers     | 55.6%      |
| GitHub-link rate among ORCID'd researchers  | 0.188%     |
| Implied population-corrected adoption rate  | ~30 / Mn   |

Adopters have a 3.1-year longer median GitHub history than non-adopters
within field (Mann-Whitney p = 2 × 10⁻²⁷); they do not differ on citation
impact.

## Directory layout

```
.
├── fig1_diffusion.py          Figure 1: cumulative adoption + weekly all-vs-sci
├── fig2_career.py             Figure 2: adoption + intensity by career stage
├── fig3_field.py              Figure 3: field rate, ORCID baseline, corrected rate
├── fig4_geography.py          Figure 4: country and institution heterogeneity
├── fig5_experience.py         Figure 5: time-on-GitHub by adopter status
├── figS1_impact.py            Online appendix: citation impact by adoption
├── figure_template.py         Shared style helpers (palette, fonts, save())
├── figures/                   Generated SVG + PNG outputs (LFS-tracked)
├── scripts/                   Data-collection pipeline (see run_pipeline.sh)
│   ├── find_claude_commits.py
│   ├── analyze_users.py
│   ├── find_orcid_users_api.py
│   ├── fetch_orcid_profiles.py
│   ├── fetch_orcid_locations.py
│   ├── classify_orcid_scopus.py
│   ├── classify_active_scientists.py
│   ├── fetch_openalex_author_baseline.py
│   ├── fetch_orcid_github_baseline.py
│   ├── fetch_scientist_citations.py
│   └── fetch_scientist_github_accounts.py
├── data/                      All checkpointed data (LFS-tracked)
├── run_pipeline.sh            End-to-end re-run
├── requirements.txt
├── LICENSE                    MIT (code), CC-BY-4.0 (data + figures)
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

> Yang, C. (2026). *Diffusion of AI Coding Assistants Among Active Scientists:
> Evidence from Claude Code.* Economics Letters (under review).

A machine-readable citation entry is available in `CITATION.cff`.

## Disclosure

Author affiliated with Renaissance Philanthropy. The author has no financial
interest in Anthropic or in any of the AI coding tools discussed. Replication
materials in this repository were authored with substantial assistance from
Claude Code.
