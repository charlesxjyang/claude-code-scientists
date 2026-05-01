#!/usr/bin/env bash
# End-to-end reproduction pipeline.
#
# Required environment variables:
#   GITHUB_TOKEN          GitHub personal access token (no special scopes;
#                         used only against public-data search endpoints)
#   ORCID_CLIENT_ID       ORCID public-API client id (https://orcid.org/developer-tools)
#   ORCID_CLIENT_SECRET   ORCID public-API client secret
#
# Each stage is independently re-runnable; the pipeline checkpoints to JSON
# files in data/ as it goes. Pass --skip-fetch to use the data files already
# in data/ and only regenerate figures.
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p data figures

if [[ "${1:-}" != "--skip-fetch" ]]; then
  echo "===== 1. Scrape Claude Code commits from GitHub Search API ====="
  python3 scripts/find_claude_commits.py 2025-10-01 \
      --until 2026-03-01 \
      -o data/claude_commits_all.json

  echo "===== 2. Analyze GitHub users that authored Claude Code commits ====="
  python3 scripts/analyze_users.py data/claude_commits_all.json \
      -o data/user_analysis.json --resume

  echo "===== 3. Find ORCID profiles linked to GitHub ====="
  python3 scripts/find_orcid_users_api.py
  python3 scripts/fetch_orcid_profiles.py
  python3 scripts/fetch_orcid_locations.py

  echo "===== 4. Classify scientists by field (Scopus ASJC) and filter active ====="
  python3 scripts/classify_orcid_scopus.py
  python3 scripts/classify_active_scientists.py

  echo "===== 5. Selection-correction baselines ====="
  python3 scripts/fetch_openalex_author_baseline.py
  python3 scripts/fetch_orcid_github_baseline.py

  echo "===== 6. Citation impact + GitHub experience for active scientists ====="
  python3 scripts/fetch_scientist_citations.py
  python3 scripts/fetch_scientist_github_accounts.py
fi

echo "===== 7. Render figures ====="
python3 fig1_diffusion.py
python3 fig2_career.py
python3 fig3_field.py
python3 fig4_geography.py
python3 fig5_experience.py
python3 figS1_impact.py

echo "Done. Figures in figures/."
