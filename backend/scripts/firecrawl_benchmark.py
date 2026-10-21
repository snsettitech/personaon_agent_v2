"""30-person Firecrawl extraction benchmark.

Tests extraction quality across 3 buckets:
- Well-known (10): Public figures with extensive web presence
- Mid-tier (10): Industry professionals, startup founders, speakers
- Low-footprint (10): Less well-known professionals

Scores each on:
1. Completeness: how many key fields are populated (0-100%)
2. Name accuracy: does the extracted name match the input?
3. Quality threshold: passes is_profile_rich() check?

Usage:
    cd backend
    python scripts/firecrawl_benchmark.py
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from adk_core.services.firecrawl_service import extract_profile, is_profile_rich


# ── Test subjects ────────────────────────────────────────────────────

WELL_KNOWN = [
    ("Elon Musk", "CEO of Tesla and SpaceX"),
    ("Oprah Winfrey", "Media executive and TV host"),
    ("Bill Gates", "Co-founder of Microsoft"),
    ("Taylor Swift", "Singer-songwriter"),
    ("Barack Obama", "44th President of the United States"),
    ("Jeff Bezos", "Founder of Amazon"),
    ("Serena Williams", "Tennis champion"),
    ("Mark Zuckerberg", "CEO of Meta"),
    ("Malala Yousafzai", "Nobel Peace Prize laureate"),
    ("Tim Cook", "CEO of Apple"),
]

MID_TIER = [
    ("Garry Tan", "CEO of Y Combinator"),
    ("Hasan Minhaj", "Comedian and former Daily Show correspondent"),
    ("Lex Fridman", "AI researcher and podcast host"),
    ("Sahil Lavingia", "Founder of Gumroad"),
    ("Kara Swisher", "Tech journalist"),
    ("Patrick Collison", "CEO of Stripe"),
    ("Reshma Saujani", "Founder of Girls Who Code"),
    ("Balaji Srinivasan", "Angel investor and author of The Network State"),
    ("Julia Hartz", "CEO of Eventbrite"),
    ("David Heinemeier Hansson", "Creator of Ruby on Rails"),
]

LOW_FOOTPRINT = [
    ("Sainath Setti", "Tech entrepreneur"),
    ("Priya Sharma", "Software engineer in Bangalore"),
    ("James Wilson", "Local restaurant owner in Portland"),
    ("Maria Chen", "Data analyst at a mid-size company"),
    ("Ahmed Hassan", "University lecturer in Cairo"),
    ("Sofia Rodriguez", "Freelance graphic designer"),
    ("Tom Baker", "Real estate agent in Austin"),
    ("Yuki Tanaka", "Product manager at a Japanese startup"),
    ("Elena Petrova", "Yoga instructor and wellness coach"),
    ("Michael O'Brien", "High school math teacher"),
]

# ── Scoring ──────────────────────────────────────────────────────────

SCORED_FIELDS = [
    "name", "occupation", "short_description", "personality_traits",
    "speaking_style", "education", "work_experience", "key_achievements",
    "areas_of_expertise", "contributions",
]


def score_completeness(profile: dict) -> float:
    """Score 0-100 based on how many key fields are populated."""
    populated = 0
    for field in SCORED_FIELDS:
        value = profile.get(field)
        if value:
            if isinstance(value, list) and len(value) > 0 or isinstance(value, str) and value.strip():
                populated += 1
    return round(populated / len(SCORED_FIELDS) * 100, 1)


def check_name_accuracy(profile: dict, expected_name: str) -> bool:
    """Check if extracted name matches (fuzzy — last name must appear)."""
    extracted = (profile.get("name") or "").lower()
    expected_parts = expected_name.lower().split()
    # At least the last name should match
    return any(part in extracted for part in expected_parts if len(part) > 2)


# ── Runner ───────────────────────────────────────────────────────────


def run_bucket(bucket_name: str, subjects: list[tuple[str, str]]) -> list[dict]:
    results = []
    print(f"\n{'='*60}")
    print(f"  BUCKET: {bucket_name} ({len(subjects)} subjects)")
    print(f"{'='*60}")

    for i, (name, context) in enumerate(subjects):
        print(f"\n  [{i+1}/{len(subjects)}] {name} ({context})...")
        start = time.time()

        try:
            profile = extract_profile(name, context)
            elapsed = round(time.time() - start, 1)

            completeness = score_completeness(profile)
            name_match = check_name_accuracy(profile, name)
            rich = is_profile_rich(profile)

            result = {
                "name": name,
                "context": context,
                "bucket": bucket_name,
                "extracted_name": profile.get("name", ""),
                "completeness": completeness,
                "name_match": name_match,
                "is_rich": rich,
                "elapsed_s": elapsed,
                "fields": {f: bool(profile.get(f)) for f in SCORED_FIELDS},
            }

            status = "PASS" if rich and name_match else "WARN" if rich or name_match else "FAIL"
            print(f"    {status} | completeness={completeness}% | name_match={name_match} | rich={rich} | {elapsed}s")
            if not name_match:
                print(f"    !! Extracted: '{profile.get('name', '')}' (expected: '{name}')")

        except Exception as exc:
            elapsed = round(time.time() - start, 1)
            result = {
                "name": name,
                "context": context,
                "bucket": bucket_name,
                "extracted_name": "",
                "completeness": 0,
                "name_match": False,
                "is_rich": False,
                "elapsed_s": elapsed,
                "error": str(exc)[:200],
            }
            print(f"    ERROR | {exc!s:.100} | {elapsed}s")

        results.append(result)

    return results


def print_summary(all_results: list[dict]) -> None:
    print(f"\n{'='*60}")
    print("  BENCHMARK SUMMARY")
    print(f"{'='*60}")

    for bucket in ["well-known", "mid-tier", "low-footprint"]:
        bucket_results = [r for r in all_results if r["bucket"] == bucket]
        if not bucket_results:
            continue

        avg_completeness = sum(r["completeness"] for r in bucket_results) / len(bucket_results)
        name_accuracy = sum(1 for r in bucket_results if r["name_match"]) / len(bucket_results) * 100
        rich_rate = sum(1 for r in bucket_results if r["is_rich"]) / len(bucket_results) * 100
        error_count = sum(1 for r in bucket_results if "error" in r)
        avg_time = sum(r["elapsed_s"] for r in bucket_results) / len(bucket_results)

        print(f"\n  {bucket.upper()} ({len(bucket_results)} subjects):")
        print(f"    Avg completeness: {avg_completeness:.1f}%")
        print(f"    Name accuracy:    {name_accuracy:.0f}%")
        print(f"    Rich profile:     {rich_rate:.0f}%")
        print(f"    Errors:           {error_count}")
        print(f"    Avg time:         {avg_time:.1f}s")

    # Overall
    total = len(all_results)
    overall_rich = sum(1 for r in all_results if r["is_rich"]) / total * 100
    overall_name = sum(1 for r in all_results if r["name_match"]) / total * 100
    overall_errors = sum(1 for r in all_results if "error" in r)

    print(f"\n  OVERALL ({total} subjects):")
    print(f"    Rich profiles: {overall_rich:.0f}%")
    print(f"    Name accuracy: {overall_name:.0f}%")
    print(f"    Errors:        {overall_errors}")

    # Verdict
    print("\n  VERDICT: ", end="")
    if overall_rich >= 70 and overall_name >= 80:
        print("PASS — Firecrawl extraction is production-ready")
    elif overall_rich >= 50:
        print("PARTIAL — Works for well-known, needs manual fallback for others")
    else:
        print("FAIL — Manual input path is critical for launch")


if __name__ == "__main__":
    all_results = []

    all_results.extend(run_bucket("well-known", WELL_KNOWN))
    all_results.extend(run_bucket("mid-tier", MID_TIER))
    all_results.extend(run_bucket("low-footprint", LOW_FOOTPRINT))

    print_summary(all_results)

    # Save raw results
    out_path = os.path.join(os.path.dirname(__file__), "..", "benchmark_results.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Raw results saved to: {out_path}")
