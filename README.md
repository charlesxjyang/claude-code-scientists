# How Many Scientists Use Claude Code?

Analysis of Claude Code adoption among ORCID-linked scientists on GitHub.

## Method

1. Scraped all public GitHub commits with `Co-Authored-By: Claude` signatures (~8M+ commits)
2. Cross-referenced commit authors against ORCID profiles linked to GitHub accounts
3. Filtered to active scientists: recently active on GitHub, ORCID profile linked, published since 2024
4. Classified scientists by field (Scopus journal lookup + keyword fallback), seniority (years since first publication), country, and institution

## Dataset

- **15,934** active ORCID-linked scientists on GitHub
- **331** (2.1%) have made at least one Claude Code commit
- Data period: October 2025 - February 2026

## Figures

| Figure | Description |
|--------|-------------|
| `fig_adoption_rate` | Cumulative % of scientists adopting Claude Code over time |
| `fig_seniority` | Adoption rate by career stage (early career to veteran) |
| `fig_seniority_violin` | Commit intensity and repo breadth by seniority (violin + box) |
| `fig_scientist_profile` | 3-panel: commits/week, languages, repo breadth (scientists vs all) |
| `fig_timeline` | Weekly commits: all users vs scientists (log scale) |
| `fig_field_adoption` | Adoption rate by scientific field |
| `fig_institution` | Adoption rate by institution (histogram + top/bottom lists) |
| `fig_country` | Adoption rate by country (histogram + top/bottom lists) |

## Regenerating figures

```bash
pip install matplotlib numpy scipy
python figure_template.py
```

## Key findings

- ~2.1% of active ORCID scientists on GitHub have used Claude Code (as of Feb 2026)
- Adoption is remarkably uniform across scientific fields (1.4-3.4%)
- Veterans (20+ years since first publication) adopt at higher rates (3.2%) than postdocs (1.3%)
- Once adopted, commit intensity is similar across seniority levels (~7-12 commits/week median)
- Geographic variation: Sweden (4.4%), US (4.0%), Finland (4.0%) lead; India (0.3%), Bangladesh (0.0%) trail
- Scientists use more Python (~40%) and R (~6%) vs non-scientists; less TypeScript

## Data sources

- [GitHub Search API](https://docs.github.com/en/rest/search) — Claude Code commits
- [ORCID Public API](https://info.orcid.org/documentation/api-tutorials/) — scientist profiles, publications, affiliations
- [Scopus](https://www.scopus.com/) — journal-to-field classification
