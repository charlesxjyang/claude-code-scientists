#!/usr/bin/env python3
"""Fetch location data for active scientists from ORCID.

Pulls:
  - /address: self-reported country
  - /employments: org city + country (current position first)

Merges into active_scientists.json.
"""

import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SCRIPT_DIR = "/Users/charl/Programming/github_claude"
ACTIVE_FILE = os.path.join(SCRIPT_DIR, "active_scientists.json")
ORCID_USERS_FILE = os.path.join(SCRIPT_DIR, "orcid_github_users.json")
LOCATION_CACHE = os.path.join(SCRIPT_DIR, "orcid_locations.json")

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
SESSION.headers.update({"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"})


def fetch_location(orcid_id):
    """Fetch country from /address and org location from /employments."""
    location = {
        "country": None,
        "org_city": None,
        "org_country": None,
        "org_name": None,
    }

    for attempt in range(3):
        try:
            # Self-reported country
            r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/address", timeout=10)
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt + 1)
                continue
            if r.status_code == 200:
                addresses = r.json().get("address", [])
                if addresses:
                    location["country"] = addresses[0].get("country", {}).get("value")

            # Current employment location
            r = SESSION.get(f"https://pub.orcid.org/v3.0/{orcid_id}/employments", timeout=10)
            if r.status_code == 200:
                for group in r.json().get("affiliation-group", []):
                    for s in group.get("summaries", []):
                        emp = s.get("employment-summary", {})
                        end = emp.get("end-date")
                        org = emp.get("organization") or {}
                        addr = org.get("address") or {}
                        org_name = org.get("name", "")
                        city = addr.get("city", "")
                        country = addr.get("country", "")

                        if org_name and (city or country):
                            # Prefer current positions (no end date)
                            if end is None or not location["org_country"]:
                                location["org_name"] = org_name
                                location["org_city"] = city or None
                                location["org_country"] = country or None
                            if end is None:
                                break  # Found current position
                    else:
                        continue
                    break

            # Fall back: use org country as country if self-reported is missing
            if not location["country"] and location["org_country"]:
                location["country"] = location["org_country"]

            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"  Error {orcid_id}: {e}", file=sys.stderr, flush=True)
            break

    return orcid_id, location


def main():
    # Load active scientists
    with open(ACTIVE_FILE) as f:
        active_data = json.load(f)
    scientists = active_data["scientists"]

    # Load ORCID IDs
    with open(ORCID_USERS_FILE) as f:
        users_info = json.load(f).get("users", {})

    # Load cache (resume support)
    cache = {}
    if os.path.exists(LOCATION_CACHE):
        cache = json.load(open(LOCATION_CACHE))
        print(f"Loaded {len(cache):,} cached locations", flush=True)

    # Build fetch queue
    to_fetch = {}
    for username in scientists:
        if username not in cache:
            orcid = users_info.get(username, {}).get("orcid")
            if orcid:
                to_fetch[orcid] = username

    print(f"Active scientists: {len(scientists):,}", flush=True)
    print(f"Need location fetch: {len(to_fetch):,} (cached: {len(cache):,})", flush=True)

    # Fetch in batches
    if to_fetch:
        done = 0
        fetch_list = list(to_fetch.items())
        for batch_start in range(0, len(fetch_list), 100):
            batch = fetch_list[batch_start:batch_start + 100]
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(fetch_location, oid): (oid, u) for oid, u in batch}
                for future in as_completed(futures):
                    oid, username = futures[future]
                    done += 1
                    try:
                        _, loc = future.result()
                        cache[username] = loc
                    except Exception as e:
                        print(f"  Error {username}: {e}", file=sys.stderr, flush=True)

            if done % 1000 < 100:
                with open(LOCATION_CACHE, "w") as f:
                    json.dump(cache, f)
                print(f"  {done:,}/{len(to_fetch):,}", flush=True)

        with open(LOCATION_CACHE, "w") as f:
            json.dump(cache, f)
        print(f"  Done ({len(cache):,} cached)", flush=True)

    # Merge into active scientists
    for username in scientists:
        if username in cache:
            scientists[username]["country"] = cache[username]["country"]
            scientists[username]["org_city"] = cache[username]["org_city"]
            scientists[username]["org_country"] = cache[username]["org_country"]

    # Stats
    has_country = sum(1 for s in scientists.values() if s.get("country"))
    has_org_loc = sum(1 for s in scientists.values() if s.get("org_country"))
    print(f"\nLocation coverage:", flush=True)
    print(f"  With country: {has_country:,}/{len(scientists):,} ({has_country/len(scientists)*100:.1f}%)", flush=True)
    print(f"  With org location: {has_org_loc:,}/{len(scientists):,} ({has_org_loc/len(scientists)*100:.1f}%)", flush=True)

    # Country distribution
    claude = {u: s for u, s in scientists.items() if s.get("claude_user")}
    baseline = {u: s for u, s in scientists.items() if not s.get("claude_user")}

    print(f"\n{'='*70}", flush=True)
    print(f"COUNTRY DISTRIBUTION", flush=True)
    print(f"{'='*70}", flush=True)

    claude_countries = Counter(s["country"] for s in claude.values() if s.get("country"))
    baseline_countries = Counter(s["country"] for s in baseline.values() if s.get("country"))

    all_countries = sorted(set(claude_countries) | set(baseline_countries),
                           key=lambda c: claude_countries.get(c, 0) + baseline_countries.get(c, 0),
                           reverse=True)

    c_total = sum(claude_countries.values())
    b_total = sum(baseline_countries.values())

    print(f"\n  {'Country':<8s} {'Claude':>8s} {'%':>6s} {'Baseline':>8s} {'%':>6s} {'Enrich':>7s}", flush=True)
    print(f"  {'-'*45}", flush=True)
    for country in all_countries[:25]:
        c = claude_countries.get(country, 0)
        b = baseline_countries.get(country, 0)
        c_pct = c / c_total * 100 if c_total else 0
        b_pct = b / b_total * 100 if b_total else 0
        ratio = (c_pct / b_pct) if b_pct > 0 else (float('inf') if c_pct > 0 else 1.0)
        marker = " >>>" if ratio > 1.3 else (" <<<" if ratio < 0.7 else "")
        print(f"  {country:<8s} {c:>8,} {c_pct:>5.1f}% {b:>8,} {b_pct:>5.1f}% {ratio:>6.2f}x{marker}", flush=True)

    # Save updated active_scientists.json
    active_data["scientists"] = scientists
    with open(ACTIVE_FILE, "w") as f:
        json.dump(active_data, f, indent=2)
    print(f"\nUpdated {ACTIVE_FILE}", flush=True)


if __name__ == "__main__":
    main()
