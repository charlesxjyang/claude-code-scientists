#!/usr/bin/env python3
"""Fetch seniority and institution data for ALL ~33K ORCID-linked GitHub users.

Pulls from ORCID API:
  - Works: publication count, earliest pub year, journal names
  - Employments: institutions, current role
  - Educations: earliest education year, departments

Saves incrementally to orcid_profiles.json with checkpoint every 500 users.
Supports resume: skips already-fetched users.
"""

import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SCRIPT_DIR = "/Users/charl/Programming/github_claude"
ORCID_FILE = os.path.join(SCRIPT_DIR, "orcid_github_users.json")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "orcid_profiles.json")

# ── ORCID Auth ────────────────────────────────────────────────────────

ORCID_CLIENT_ID = os.environ.get("ORCID_CLIENT_ID")
ORCID_CLIENT_SECRET = os.environ.get("ORCID_CLIENT_SECRET")
if not (ORCID_CLIENT_ID and ORCID_CLIENT_SECRET):
    sys.stderr.write("ERROR: set ORCID_CLIENT_ID + ORCID_CLIENT_SECRET (https://orcid.org/developer-tools)
")
    sys.exit(1)

token_r = requests.post("https://orcid.org/oauth/token", data={
    "client_id": ORCID_CLIENT_ID,
    "client_secret": ORCID_CLIENT_SECRET,
    "scope": "/read-public", "grant_type": "client_credentials",
}, headers={"Accept": "application/json"})
TOKEN = token_r.json()["access_token"]

SESSION = requests.Session()
SESSION.headers.update({
    "Accept": "application/json",
    "Authorization": f"Bearer {TOKEN}",
})


def fetch_profile(orcid_id):
    """Fetch seniority + institution data for one ORCID. Only /works + /employments."""
    profile = {
        "n_publications": 0,
        "earliest_pub_year": None,
        "latest_pub_year": None,
        "institutions": [],
        "current_role": None,
    }

    for attempt in range(3):
        try:
            # Works (pub count, earliest/latest year)
            r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/works", timeout=20)
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt + 1)
                continue
            if r.status_code == 200:
                groups = r.json().get("group", [])
                profile["n_publications"] = len(groups)
                for group in groups:
                    ws = group.get("work-summary", [{}])[0]
                    pub_date = ws.get("publication-date") or {}
                    year_obj = pub_date.get("year")
                    if year_obj and year_obj.get("value"):
                        try:
                            yr = int(year_obj["value"])
                            if yr > 1900:
                                if profile["earliest_pub_year"] is None or yr < profile["earliest_pub_year"]:
                                    profile["earliest_pub_year"] = yr
                                if profile["latest_pub_year"] is None or yr > profile["latest_pub_year"]:
                                    profile["latest_pub_year"] = yr
                        except (ValueError, TypeError):
                            pass

            # Employments (institutions, current role)
            r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/employments", timeout=15)
            if r.status_code == 200:
                for group in r.json().get("affiliation-group", []):
                    for s in group.get("summaries", []):
                        emp = s.get("employment-summary", {})
                        org = (emp.get("organization") or {}).get("name", "")
                        role = emp.get("role-title", "") or ""
                        if org and org not in profile["institutions"]:
                            profile["institutions"].append(org)
                        if not profile["current_role"] and org:
                            end = emp.get("end-date")
                            if end is None:  # Current position
                                profile["current_role"] = f"{role}, {org}" if role else org

            break  # Success
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"  Error fetching {orcid_id}: {e}", file=sys.stderr, flush=True)
            break

    profile["institutions"] = profile["institutions"][:10]

    return orcid_id, profile


def save_checkpoint(profiles, done_count, total):
    """Save current state to disk."""
    with open(OUTPUT_FILE, "w") as f:
        json.dump(profiles, f)
    print(f"  Checkpoint: {done_count:,}/{total:,} saved ({len(profiles):,} profiles)", flush=True)


def main():
    # Load all ORCID users
    with open(ORCID_FILE) as f:
        orcid_data = json.load(f)

    users = orcid_data.get("users", {})
    with_orcid = {u: info for u, info in users.items() if info.get("orcid")}
    print(f"Total ORCID users: {len(with_orcid):,}", flush=True)

    # Load existing profiles (resume support)
    existing = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        print(f"Loaded {len(existing):,} existing profiles", flush=True)

    # Build fetch queue (skip already-fetched)
    to_fetch = {}
    for username, info in with_orcid.items():
        if username not in existing:
            to_fetch[info["orcid"]] = username

    print(f"Need to fetch: {len(to_fetch):,} (skipping {len(existing):,} already done)", flush=True)

    if not to_fetch:
        print("All profiles already fetched!", flush=True)
        return

    # Copy existing into working dict
    profiles = dict(existing)

    # Batched parallel fetch — submit in chunks of 100 to avoid memory bloat
    done = 0
    errors = 0
    BATCH_SIZE = 100
    WORKERS = 10

    fetch_list = list(to_fetch.items())  # [(orcid_id, username), ...]
    total = len(fetch_list)

    for batch_start in range(0, total, BATCH_SIZE):
        batch = fetch_list[batch_start:batch_start + BATCH_SIZE]

        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {
                executor.submit(fetch_profile, orcid_id): (orcid_id, username)
                for orcid_id, username in batch
            }

            for future in as_completed(futures):
                orcid_id, username = futures[future]
                done += 1

                try:
                    _, profile = future.result()
                    profiles[username] = profile
                except Exception as e:
                    errors += 1
                    print(f"  Failed {username} ({orcid_id}): {e}", file=sys.stderr, flush=True)

        if done % 500 < BATCH_SIZE:
            save_checkpoint(profiles, done, total)

    # Final save
    save_checkpoint(profiles, done, total)
    print(f"\nDone! {len(profiles):,} total profiles saved to {OUTPUT_FILE}", flush=True)
    print(f"  Errors: {errors}", flush=True)

    # Quick stats
    has_pubs = sum(1 for p in profiles.values() if p["n_publications"] > 0)
    has_inst = sum(1 for p in profiles.values() if p["institutions"])
    has_role = sum(1 for p in profiles.values() if p["current_role"])
    print(f"\n  With publications: {has_pubs:,} ({has_pubs/len(profiles)*100:.1f}%)")
    print(f"  With institution:  {has_inst:,} ({has_inst/len(profiles)*100:.1f}%)")
    print(f"  With current role: {has_role:,} ({has_role/len(profiles)*100:.1f}%)")


if __name__ == "__main__":
    main()
