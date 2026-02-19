#!/usr/bin/env python3
"""
Apollo Decision-Makers Search & Enrichment Script (Two-Phase)

Phase 1: People Search (FREE) — searches all companies, saves search_results.csv
Phase 2: People Enrichment (COSTS credits) — enriches filtered contacts, saves enriched_contacts.csv
"""

import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

import requests

# ─── Configuration ────────────────────────────────────────────────────────────

API_KEY = "Emchb6ssXHRMl7Xiu-X6VA"
HEADERS = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
}

SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
ENRICH_URL = "https://api.apollo.io/api/v1/people/match"
BULK_ENRICH_URL = "https://api.apollo.io/api/v1/people/bulk_match"

INPUT_CSV = "companies.csv"
SEARCH_RESULTS_CSV = "search_results.csv"
ENRICHED_CSV = "enriched_contacts.csv"
CHECKPOINT_CSV = "enriched_contacts_checkpoint.csv"

CATEGORY_TITLES = {
    "SEO / SERP Data": [
        "SEO Manager", "Head of SEO", "SEO Director", "SEO Lead",
        "Digital Marketing Director", "Digital Marketing Manager",
        "Growth Lead", "Head of Growth", "VP Marketing",
        "Product Manager", "Head of Product", "CTO", "VP Engineering",
        "Founder", "CEO", "COO",
    ],
    "E-commerce / Price Intelligence": [
        "Head of Competitive Intelligence", "Competitive Intelligence",
        "Pricing Manager", "Pricing Director", "Head of Pricing",
        "E-commerce Director", "E-commerce Manager", "Head of E-commerce",
        "Data Ops Lead", "Data Operations Manager",
        "Product Manager", "Head of Product",
        "CTO", "VP Engineering", "VP Technology",
        "Founder", "CEO", "COO",
    ],
    "Ad Verification / Brand Safety": [
        "Head of Ad Ops", "Ad Operations Manager", "Ad Ops Director",
        "Ad Verification Lead", "Ad Verification Manager",
        "Brand Safety Manager", "Brand Safety Director",
        "Programmatic Director", "Programmatic Manager",
        "Media Director", "VP Media",
        "CTO", "VP Engineering",
        "Founder", "CEO", "COO",
    ],
    "Web Scraping / Data Extraction": [
        "CTO", "VP Engineering", "VP Technology",
        "Lead Data Engineer", "Head of Data", "Data Engineering Manager",
        "Head of Data Engineering", "Principal Engineer",
        "Product Manager", "Head of Product",
        "Founder", "CEO", "COO",
    ],
    "Social Data / Monitoring": [
        "Social Media Manager", "Head of Social",
        "Brand Manager", "Brand Director",
        "Growth Lead", "Head of Growth",
        "CTO", "VP Engineering",
        "Founder", "CEO", "COO",
    ],
    "Other / Unknown": [
        "CTO", "VP Engineering", "VP Technology",
        "Head of Data", "Data Engineering Manager",
        "Product Manager", "Head of Product",
        "Founder", "CEO", "COO",
    ],
}

SENIORITIES = ["c_suite", "vp", "director", "head", "manager", "founder"]

# Titles to exclude (case-insensitive substring match)
EXCLUDE_TITLE_WORDS = [
    "intern", "junior", "associate", "coordinator", "assistant",
    "trainee", "freelance", "contractor", "student",
]

# Titles that are only valid if accompanied by a senior qualifier
SOLO_TITLES = ["developer", "engineer", "designer", "analyst"]
SENIOR_QUALIFIERS = [
    "lead", "head", "senior", "principal", "manager", "director",
    "vp", "chief", "staff", "vice president",
]

# Seniority priority for ranking (lower = higher priority)
SENIORITY_RANK = {
    "c_suite": 0,
    "founder": 1,
    "vp": 2,
    "director": 3,
    "head": 4,
    "manager": 5,
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_max_contacts(company_size: str) -> int:
    """Determine max contacts based on company_size string."""
    sz = (company_size or "").lower()
    if any(kw in sz for kw in ["enterprise", "5000+", "10000+", "1001-5000", "large"]):
        return 7
    if any(kw in sz for kw in ["mid-market", "201-", "501-1000"]):
        return 5
    return 3


def infer_seniority_from_title(title: str) -> str:
    """Infer seniority level from job title when API doesn't provide it."""
    if not title:
        return ""
    t = title.lower()

    # C-suite
    if any(kw in t for kw in [
        "chief", "ceo", "cto", "cfo", "coo", "cmo", "cio", "cpo", "cro",
        "c.e.o", "c.t.o",
    ]):
        return "c_suite"

    # Founder
    if "founder" in t or "co-founder" in t:
        return "founder"

    # VP
    if "vice president" in t or t.startswith("vp ") or " vp " in t or t == "vp":
        return "vp"

    # Director
    if "director" in t:
        return "director"

    # Head
    if "head of" in t or "head," in t or t.startswith("head "):
        return "head"

    # Manager
    if "manager" in t:
        return "manager"

    # Lead
    if "lead" in t or "principal" in t or "senior" in t:
        return "manager"  # treat as manager-level for ranking

    return ""


def is_title_excluded(title: str) -> bool:
    """Check if a person's title should be excluded."""
    if not title:
        return True
    t = title.lower()

    # Check for "specialist" without "senior"
    if "specialist" in t and "senior" not in t:
        return True

    # Check explicit exclusion words
    for word in EXCLUDE_TITLE_WORDS:
        if word in t:
            return True

    # Check solo titles without senior qualifiers
    has_solo = any(s in t for s in SOLO_TITLES)
    has_qualifier = any(q in t for q in SENIOR_QUALIFIERS)
    if has_solo and not has_qualifier:
        return True

    return False


def rank_person(person: dict) -> int:
    """Return a ranking value for sorting (lower = better)."""
    seniority = (person.get("_inferred_seniority") or "").lower()
    return SENIORITY_RANK.get(seniority, 99)


def api_request(url: str, payload: dict, max_retries: int = 3) -> dict | None:
    """Make API request with rate-limit handling."""
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = 60
                print(f"\n    Rate limited (429). Waiting {wait}s...", end="")
                sys.stdout.flush()
                time.sleep(wait)
                continue
            if resp.status_code == 422:
                return None
            print(f"\n    HTTP {resp.status_code}: {resp.text[:150]}", end="")
            if attempt < max_retries:
                time.sleep(2 ** (attempt + 1))
        except requests.exceptions.RequestException as e:
            print(f"\n    Request error: {e}", end="")
            if attempt < max_retries:
                time.sleep(2 ** (attempt + 1))
    return None


# ─── Phase 1: People Search ──────────────────────────────────────────────────

def load_companies(path: str) -> list[dict]:
    """Load companies from CSV."""
    companies = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            domain = (row.get("domain") or "").strip()
            if domain and "." in domain:
                companies.append(row)
    return companies


def search_people_for_company(
    domain: str, titles: list[str], seniorities: list[str], per_page: int
) -> list[dict]:
    """Call Apollo People Search API for a single domain."""
    payload = {
        "person_titles": titles,
        "person_seniorities": seniorities,
        "q_organization_domains_list": [domain],
        "per_page": per_page,
    }
    data = api_request(SEARCH_URL, payload)
    if not data:
        return []
    return data.get("people", []) or []


def filter_and_rank(people: list[dict], max_contacts: int) -> list[dict]:
    """Filter out irrelevant titles and rank by seniority."""
    filtered = []
    for p in people:
        title = p.get("title") or ""
        if is_title_excluded(title):
            continue
        p["_inferred_seniority"] = infer_seniority_from_title(title)
        filtered.append(p)

    # Sort by seniority rank (best first)
    filtered.sort(key=rank_person)
    return filtered[:max_contacts]


def run_phase1():
    """Phase 1: People Search for all companies (FREE)."""
    companies = load_companies(INPUT_CSV)
    total = len(companies)
    print(f"\n{'='*60}")
    print(f"PHASE 1: People Search (FREE — no credits used)")
    print(f"Companies to process: {total}")
    print(f"{'='*60}\n")

    all_results = []
    seen_person_ids = set()
    companies_with_contacts = 0
    companies_no_contacts = 0

    for i, company in enumerate(companies, 1):
        name = company.get("company_name", "")
        domain = company.get("domain", "").strip()
        category = company.get("category_norm", "Other / Unknown")
        use_case = company.get("proxy_use_case_norm", "")
        size = company.get("company_size", "")

        titles = CATEGORY_TITLES.get(category, CATEGORY_TITLES["Other / Unknown"])
        max_contacts = get_max_contacts(size)

        print(
            f"Processing {i}/{total}: {domain} "
            f"(cat={category[:25]}, max={max_contacts})",
            end="",
        )
        sys.stdout.flush()

        # Request more than max_contacts to have room for filtering
        raw_people = search_people_for_company(
            domain, titles, SENIORITIES, per_page=25
        )
        filtered = filter_and_rank(raw_people, max_contacts)

        # Deduplicate across companies
        unique = []
        for p in filtered:
            pid = p.get("id")
            if pid and pid not in seen_person_ids:
                seen_person_ids.add(pid)
                unique.append(p)

        if unique:
            companies_with_contacts += 1
        else:
            companies_no_contacts += 1

        print(
            f" -- found {len(raw_people)} raw, "
            f"{len(filtered)} filtered, {len(unique)} unique"
        )

        for p in unique:
            first = p.get("first_name", "") or ""
            last_obf = p.get("last_name_obfuscated", "") or ""
            inferred_sen = p.get("_inferred_seniority", "")
            all_results.append({
                "company_name": name,
                "company_domain": domain,
                "category_norm": category,
                "proxy_use_case": use_case,
                "company_size": size,
                "contact_name": f"{first} {last_obf}".strip(),
                "contact_title": p.get("title", ""),
                "contact_linkedin_url": "",  # Not in free search
                "contact_email": "",  # Not in free search
                "email_status": "",
                "contact_seniority": inferred_sen,
                "apollo_person_id": p.get("id", ""),
                "has_email": str(p.get("has_email", False)),
            })

        # Checkpoint every 50 companies
        if i % 50 == 0:
            save_search_results(
                all_results,
                SEARCH_RESULTS_CSV.replace(".csv", "_checkpoint.csv"),
            )
            print(f"  [Checkpoint saved at {i}/{total}]")

        # Rate limit pause
        time.sleep(1)

    # Save final results
    save_search_results(all_results, SEARCH_RESULTS_CSV)

    # Print statistics
    print(f"\n{'='*60}")
    print(f"PHASE 1 COMPLETE")
    print(f"{'='*60}")
    print(f"Companies processed:      {total}")
    print(f"Companies with contacts:  {companies_with_contacts}")
    print(f"Companies without:        {companies_no_contacts}")
    print(f"Total contacts found:     {len(all_results)}")

    has_email_count = sum(
        1 for r in all_results if r.get("has_email") == "True"
    )
    print(f"Contacts with has_email:  {has_email_count}")

    # Seniority breakdown
    seniority_counts = Counter(r["contact_seniority"] for r in all_results)
    print(f"\nSeniority breakdown:")
    for sen, cnt in seniority_counts.most_common():
        print(f"  {sen or 'unknown':20s}  {cnt}")

    # Top 10 titles
    title_counts = Counter(r["contact_title"] for r in all_results)
    print(f"\nTop 10 titles:")
    for title, cnt in title_counts.most_common(10):
        print(f"  {cnt:4d}  {title}")

    # Category breakdown
    cat_counts = Counter(r["category_norm"] for r in all_results)
    print(f"\nContacts by category:")
    for cat, cnt in cat_counts.most_common():
        print(f"  {cnt:4d}  {cat}")

    print(f"\nResults saved to: {SEARCH_RESULTS_CSV}")
    print(f"\nTo run Phase 2 (Enrichment with emails — COSTS credits):")
    print(f"  python3 apollo_enrichment.py --phase2")

    return all_results


def save_search_results(results: list[dict], path: str):
    """Save search results to CSV."""
    if not results:
        return
    fieldnames = [
        "company_name", "company_domain", "category_norm", "proxy_use_case",
        "company_size", "contact_name", "contact_title", "contact_linkedin_url",
        "contact_email", "email_status", "contact_seniority", "apollo_person_id",
        "has_email",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


# ─── Phase 2: People Enrichment ──────────────────────────────────────────────

def load_search_results(path: str) -> list[dict]:
    """Load Phase 1 search results."""
    results = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            results.append(row)
    return results


def bulk_enrich(person_ids: list[str]) -> dict:
    """Call Bulk People Enrichment API. Returns {person_id: person_data}."""
    if not person_ids:
        return {}

    payload = {
        "reveal_personal_emails": False,
        "reveal_phone_number": False,
        "details": [{"id": pid} for pid in person_ids],
    }
    data = api_request(BULK_ENRICH_URL, payload)
    if not data:
        return {}

    result = {}
    matches = data.get("matches", []) or []
    for person in matches:
        if person and person.get("id"):
            result[person["id"]] = person
    return result


def run_phase2():
    """Phase 2: Enrich contacts with emails (COSTS credits)."""
    if not os.path.exists(SEARCH_RESULTS_CSV):
        print(f"ERROR: {SEARCH_RESULTS_CSV} not found. Run Phase 1 first.")
        sys.exit(1)

    results = load_search_results(SEARCH_RESULTS_CSV)
    total = len(results)
    print(f"\n{'='*60}")
    print(f"PHASE 2: People Enrichment (USES credits)")
    print(f"Contacts to enrich: {total}")
    print(f"{'='*60}\n")

    # Collect all person IDs
    person_ids = [
        r["apollo_person_id"]
        for r in results
        if r.get("apollo_person_id")
    ]
    print(f"Person IDs to enrich: {len(person_ids)}")

    # Process in batches of 10
    enriched_map = {}
    batch_size = 10
    batches = [
        person_ids[j : j + batch_size]
        for j in range(0, len(person_ids), batch_size)
    ]

    for bi, batch in enumerate(batches, 1):
        print(
            f"  Enriching batch {bi}/{len(batches)} "
            f"({len(batch)} people)...",
            end="",
        )
        sys.stdout.flush()
        batch_result = bulk_enrich(batch)
        enriched_map.update(batch_result)
        found = len(batch_result)
        emails = sum(1 for p in batch_result.values() if p.get("email"))
        print(f" got {found} matches, {emails} with email")

        # Checkpoint every 50 batches
        if bi % 50 == 0:
            _save_enriched(results, enriched_map, CHECKPOINT_CSV)
            print(f"  [Checkpoint saved at batch {bi}]")

        time.sleep(1)

    # Merge enrichment data into results
    _save_enriched(results, enriched_map, ENRICHED_CSV)

    # Final statistics
    final = load_search_results(ENRICHED_CSV)
    email_count = sum(1 for r in final if r.get("contact_email"))
    linkedin_count = sum(1 for r in final if r.get("contact_linkedin_url"))

    seniority_counts = Counter(
        r.get("contact_seniority", "") for r in final
    )
    title_counts = Counter(r.get("contact_title", "") for r in final)

    print(f"\n{'='*60}")
    print(f"PHASE 2 COMPLETE")
    print(f"{'='*60}")
    print(f"Total contacts enriched:  {len(final)}")
    print(f"With email:               {email_count}")
    print(f"With LinkedIn URL:        {linkedin_count}")

    print(f"\nSeniority breakdown:")
    for sen, cnt in seniority_counts.most_common():
        print(f"  {sen or 'unknown':20s}  {cnt}")

    print(f"\nTop 10 titles:")
    for title, cnt in title_counts.most_common(10):
        print(f"  {cnt:4d}  {title}")

    print(f"\nFinal results saved to: {ENRICHED_CSV}")


def _save_enriched(results: list[dict], enriched_map: dict, path: str):
    """Merge enrichment data and save."""
    output = []
    for r in results:
        row = dict(r)
        pid = r.get("apollo_person_id", "")
        if pid in enriched_map:
            person = enriched_map[pid]
            row["contact_email"] = person.get("email", "") or ""
            row["email_status"] = person.get("email_status", "") or ""
            row["contact_linkedin_url"] = (
                person.get("linkedin_url", "")
                or row.get("contact_linkedin_url", "")
            )
            row["contact_seniority"] = (
                person.get("seniority", "")
                or row.get("contact_seniority", "")
            )
            # Update name with full last name if available
            first = person.get("first_name", "") or ""
            last = person.get("last_name", "") or ""
            if last:
                row["contact_name"] = f"{first} {last}".strip()
        output.append(row)
    save_search_results(output, path)


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--phase2" in sys.argv:
        run_phase2()
    else:
        run_phase1()
