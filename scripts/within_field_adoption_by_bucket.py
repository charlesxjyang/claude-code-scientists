#!/usr/bin/env python3
"""
Within-field adoption rate by GitHub-tenure bucket
(coder-first / concurrent / scientist-first).

For each scientist:
  github_year = year of GitHub account creation
  pub_year   = earliest ORCID-listed publication year
  lag        = pub_year - github_year
    lag >=  3  ⇒ coder-first    (GitHub at least 3 years before first pub)
    -2..2      ⇒ concurrent
    lag <= -3  ⇒ scientist-first (GitHub at least 3 years after first pub)

Per field with adequate sample size, report adoption rate within each bucket.
"""
import json
from collections import defaultdict, Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def main():
    active = json.load(open(DATA / "active_scientists.json"))["scientists"]
    gh = json.load(open(DATA / "scientist_github_accounts.json"))

    rows = []
    for u, info in active.items():
        rec = gh.get(u) or gh.get(u.lower())
        if not rec or not rec.get("account_created"):
            continue
        try:
            github_year = int(rec["account_created"][:4])
        except (TypeError, ValueError):
            continue
        pub_year = info.get("earliest_pub_year")
        if pub_year is None:
            continue
        lag = pub_year - github_year
        if lag >= 3:
            bucket = "coder-first"
        elif lag <= -3:
            bucket = "scientist-first"
        elif -2 <= lag <= 2:
            bucket = "concurrent"
        else:
            continue
        rows.append({
            "field": info.get("field") or "Unknown",
            "bucket": bucket,
            "claude_user": bool(info.get("claude_user")),
        })

    # Pooled totals
    pooled_total = Counter(r["bucket"] for r in rows)
    pooled_adopt = Counter(r["bucket"] for r in rows if r["claude_user"])

    print(f"n with both GitHub and pub years: {len(rows):,}")
    print()
    print("=== POOLED ADOPTION BY BUCKET ===")
    print(f"{'bucket':<18}{'n':>8}{'adopt':>8}{'rate':>9}")
    for b in ("coder-first", "concurrent", "scientist-first"):
        n = pooled_total[b]
        a = pooled_adopt[b]
        rate = (a / n * 100) if n else 0.0
        print(f"  {b:<18}{n:>6,}{a:>8,}{rate:>8.2f}%")
    print()

    # By-field breakdown
    by_fb_total = defaultdict(int)
    by_fb_adopt = defaultdict(int)
    field_counts = Counter()
    for r in rows:
        key = (r["field"], r["bucket"])
        by_fb_total[key] += 1
        if r["claude_user"]:
            by_fb_adopt[key] += 1
        field_counts[r["field"]] += 1

    print("=== ADOPTION RATE BY FIELD × BUCKET ===")
    print(f"  {'field':<26}{'coder-first':>20}{'concurrent':>20}{'scientist-first':>22}")
    print(f"  {'':<26}{'rate (n / adopters)':>20}{'rate (n / adopters)':>20}{'rate (n / adopters)':>22}")

    fields = [f for f, c in field_counts.most_common() if c >= 100]
    for f in fields:
        cells = []
        for b in ("coder-first", "concurrent", "scientist-first"):
            n = by_fb_total.get((f, b), 0)
            a = by_fb_adopt.get((f, b), 0)
            if n == 0:
                cells.append("--")
            else:
                rate = a / n * 100
                cells.append(f"{rate:5.2f}% ({a}/{n})")
        print(f"  {f:<26}{cells[0]:>20}{cells[1]:>20}{cells[2]:>22}")

    print()
    # Compact two-column view for the appendix table
    print("=== COMPACT TABLE (for appendix) ===")
    print(f"  {'field':<26}{'cf':>10}{'conc':>10}{'sf':>10}")
    for f in fields:
        cells = []
        for b in ("coder-first", "concurrent", "scientist-first"):
            n = by_fb_total.get((f, b), 0)
            a = by_fb_adopt.get((f, b), 0)
            cells.append(f"{(a/n*100):4.1f}%" if n else "--")
        print(f"  {f:<26}{cells[0]:>10}{cells[1]:>10}{cells[2]:>10}")


if __name__ == "__main__":
    main()
