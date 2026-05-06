#!/usr/bin/env bash
# End-to-end reproduction pipeline for "Claude Code Scientists".
#
# Required environment variables:
#   GITHUB_TOKEN          GitHub personal access token (no special scopes;
#                         used only against public-data search endpoints)
#   ORCID_CLIENT_ID       ORCID public-API client id (https://orcid.org/developer-tools)
#   ORCID_CLIENT_SECRET   ORCID public-API client secret
#
# Optional:
#   CLAUDE_COMMITS_PATH   Override path to data/claude_commits_all.json
#                         (the ~5 GB raw commit corpus, not LFS-tracked).
#   ORCID_DUMP_TARBALL    Path to ORCID_2024_10_summaries.tar.gz (~37 GB).
#                         Required to (re)run Stages 3b and 4b. Download
#                         from figshare DOI 10.23640/07243.27151305.
#
# Each stage is independently re-runnable; the pipeline checkpoints to JSON
# files in data/ as it goes. Pass --skip-fetch to use the data files already
# in data/ and only regenerate figures.
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p data figures

ORCID_DUMP_TARBALL="${ORCID_DUMP_TARBALL:-data/orcid_dump/ORCID_2024_10_summaries.tar.gz}"

if [[ "${1:-}" != "--skip-fetch" ]]; then

  echo "===== Stage 1: Scrape Claude Code commits from GitHub Search API ====="
  python3 scripts/find_claude_commits.py 2025-10-01 \
      --until 2026-03-01 \
      -o data/claude_commits_all.json

  echo "===== Stage 1b: Per-author commit aggregation ====="
  python3 scripts/analyze_users.py data/claude_commits_all.json \
      -o data/user_analysis.json --resume

  echo "===== Stage 2: Match committers to ORCID profiles ====="
  python3 scripts/find_orcid_users_api.py
  python3 scripts/fetch_orcid_profiles.py
  python3 scripts/fetch_orcid_locations.py

  echo "===== Stage 2b: Field classification + active-scientist filter ====="
  python3 scripts/classify_orcid_scopus.py
  python3 scripts/classify_active_scientists.py

  echo "===== Stage 3: Selection-correction baselines ====="
  echo "  Stage 1 baseline (P(ORCID|active)): OpenAlex author sample"
  python3 scripts/fetch_openalex_author_baseline.py
  echo "  Stage 2 baseline (P(GitHub|ORCID,active)): full ORCID dump"
  if [[ -f "$ORCID_DUMP_TARBALL" ]]; then
    python3 scripts/parse_orcid_dump.py "$ORCID_DUMP_TARBALL"
    python3 scripts/aggregate_orcid_dump.py
  else
    echo "  SKIP: $ORCID_DUMP_TARBALL not found; using existing data/orcid_full_baseline_active.json"
  fi
  # API-sample alternative (deprecated; full-dump baseline is primary):
  # python3 scripts/fetch_orcid_github_baseline.py

  echo "===== Stage 4: Per-scientist enrichments ====="
  python3 scripts/fetch_scientist_citations.py            # OpenAlex citation totals
  python3 scripts/fetch_scientist_github_accounts.py      # GitHub account creation date
  python3 scripts/backfill_latest_pub.py                  # patch missing latest_pub_year
  python3 scripts/fetch_scientist_institutions.py         # OpenAlex last_known_institutions
  if [[ -f "$ORCID_DUMP_TARBALL" ]]; then
    python3 scripts/parse_orcid_pedigree.py "$ORCID_DUMP_TARBALL"   # ORCID employment + education
  else
    echo "  SKIP parse_orcid_pedigree: $ORCID_DUMP_TARBALL not found"
  fi
  python3 scripts/refine_institutions.py                  # ORCID-employment primary picker
  # python3 scripts/merge_institutions.py                 # earlier merge logic; deprecated
                                                           #   (refine_institutions supersedes)

  echo "===== Stage 5: Robustness and auxiliary analyses ====="
  python3 scripts/extra_controls.py                       # citation null x career stage (A.10-A.11)
  python3 scripts/robustness_checks.py                    # cohort/window/top-decile (A.13)
  python3 scripts/within_field_adoption_by_bucket.py      # within-field x lag-bucket (A.12)
  # python3 scripts/fetch_first_commit.py                 # exploratory; not load-bearing
fi

echo "===== Stage 6: Render figures ====="
python3 make_figures/fig1_diffusion.py
python3 make_figures/fig2_career.py
python3 make_figures/fig3_field.py
python3 make_figures/fig4_geography.py
python3 make_figures/fig5_experience.py
python3 make_figures/figS2_seniority_tenure.py
# python3 make_figures/figS1_pub_vs_github.py             # deprecated; figure no longer cited

echo "Done. Figures in figures/. Manuscript in submissions/economics_letters/."
