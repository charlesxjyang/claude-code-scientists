#!/usr/bin/env python3
"""Backfill latest_pub_year for profiles already fetched without it.

Only fetches /works endpoint — much faster than full profile fetch.
Updates orcid_profiles.json in place.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SCRIPT_DIR = "/Users/charl/Programming/github_claude"
ORCID_FILE = os.path.join(SCRIPT_DIR, "orcid_github_users.json")
PROFILES_FILE = os.path.join(SCRIPT_DIR, "orcid_profiles.json")
BACKFILL_FILE = os.path.join(SCRIPT_DIR, "orcid_backfill_latest.json")

# ORCID Auth
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


def fetch_latest_pub(orcid_id):
    """Fetch only latest_pub_year for one ORCID."""
    latest = None
    for attempt in range(3):
        try:
            r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/works", timeout=20)
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt + 1)
                continue
            if r.status_code == 200:
                for group in r.json().get("group", []):
                    ws = group.get("work-summary", [{}])[0]
                    pub_date = ws.get("publication-date") or {}
                    year_obj = pub_date.get("year")
                    if year_obj and year_obj.get("value"):
                        try:
                            yr = int(year_obj["value"])
                            if yr > 1900 and (latest is None or yr > latest):
                                latest = yr
                        except (ValueError, TypeError):
                            pass
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            time.sleep(2 ** attempt)
    return orcid_id, latest


def main():
    # Load ORCID user mapping (username -> orcid)
    with open(ORCID_FILE) as f:
        orcid_data = json.load(f)
    users = orcid_data.get("users", {})
    username_to_orcid = {u: info["orcid"] for u, info in users.items() if info.get("orcid")}

    # Load existing profiles
    with open(PROFILES_FILE) as f:
        profiles = json.load(f)

    # Load already-backfilled (resume support)
    backfilled = {}
    if os.path.exists(BACKFILL_FILE):
        with open(BACKFILL_FILE) as f:
            backfilled = json.load(f)

    # Find profiles missing latest_pub_year
    to_fix = {}
    for username, profile in profiles.items():
        if "latest_pub_year" not in profile and username not in backfilled:
            orcid = username_to_orcid.get(username)
            if orcid:
                to_fix[orcid] = username

    print(f"Profiles missing latest_pub_year: {len(to_fix):,} (already backfilled: {len(backfilled):,})", flush=True)

    if not to_fix:
        print("Nothing to backfill!", flush=True)
        # Merge any pending backfills
        if backfilled:
            for username, latest in backfilled.items():
                if username in profiles:
                    profiles[username]["latest_pub_year"] = latest
            with open(PROFILES_FILE, "w") as f:
                json.dump(profiles, f)
            print(f"Merged {len(backfilled):,} backfills into profiles", flush=True)
        return

    done = 0
    BATCH_SIZE = 100

    fetch_list = list(to_fix.items())
    for batch_start in range(0, len(fetch_list), BATCH_SIZE):
        batch = fetch_list[batch_start:batch_start + BATCH_SIZE]

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(fetch_latest_pub, orcid_id): (orcid_id, username)
                for orcid_id, username in batch
            }
            for future in as_completed(futures):
                orcid_id, username = futures[future]
                done += 1
                try:
                    _, latest = future.result()
                    backfilled[username] = latest
                except Exception as e:
                    print(f"  Error {username}: {e}", file=sys.stderr, flush=True)

        if done % 500 < BATCH_SIZE:
            with open(BACKFILL_FILE, "w") as f:
                json.dump(backfilled, f)
            print(f"  {done:,}/{len(to_fix):,} backfilled", flush=True)

    # Final save of backfill
    with open(BACKFILL_FILE, "w") as f:
        json.dump(backfilled, f)

    # Merge into profiles
    print(f"\nMerging {len(backfilled):,} latest_pub_year values into profiles...", flush=True)
    # Reload profiles (main fetcher may have updated it)
    with open(PROFILES_FILE) as f:
        profiles = json.load(f)

    for username, latest in backfilled.items():
        if username in profiles:
            profiles[username]["latest_pub_year"] = latest

    with open(PROFILES_FILE, "w") as f:
        json.dump(profiles, f)

    print(f"Done! Merged into {PROFILES_FILE}", flush=True)

    # Quick stats
    with_latest = sum(1 for p in profiles.values() if p.get("latest_pub_year"))
    recent = sum(1 for p in profiles.values() if (p.get("latest_pub_year") or 0) >= 2023)
    print(f"  With latest_pub_year: {with_latest:,}/{len(profiles):,}")
    print(f"  Published 2023+: {recent:,} (likely still active)")


if __name__ == "__main__":
    main()
