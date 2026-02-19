#!/usr/bin/env python3
"""
Phase 2: Apollo Bulk People Enrichment

Reads contacts_for_enrichment.csv (filtered from search_results.csv),
enriches each contact via Apollo Bulk People Enrichment API,
and outputs enriched_contacts.csv.
"""

import csv
import json
import os
import sys
import time
from collections import Counter

import requests

# ── Config ──────────────────────────────────────────────────────────────
API_KEY = "Emchb6ssXHRMl7Xiu-X6VA"
API_URL = "https://api.apollo.io/api/v1/people/bulk_match"
BATCH_SIZE = 10
PAUSE_BETWEEN_BATCHES = 1.5  # seconds
RATE_LIMIT_WAIT = 60  # seconds
MAX_RETRIES = 3
CHECKPOINT_EVERY = 20  # batches (= 200 contacts)

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
SEARCH_RESULTS = os.path.join(WORK_DIR, "search_results.csv")
CONTACTS_FOR_ENRICHMENT = os.path.join(WORK_DIR, "contacts_for_enrichment.csv")
ENRICHED_OUTPUT = os.path.join(WORK_DIR, "enriched_contacts.csv")
CHECKPOINT_FILE = os.path.join(WORK_DIR, "enriched_contacts_checkpoint.csv")
PROGRESS_FILE = os.path.join(WORK_DIR, "enrichment_progress.json")

OUTPUT_COLUMNS = [
    "company_name", "company_domain", "category_norm", "proxy_use_case",
    "proxy_relevance", "company_size", "contact_name", "contact_title",
    "contact_linkedin_url", "contact_email", "email_status",
    "contact_seniority", "title_tier", "apollo_person_id",
]


# ── Tier assignment ─────────────────────────────────────────────────────
def assign_tier(row):
    """Assign title tier A-D based on seniority and title keywords."""
    s = row.get("contact_seniority", "").strip().lower()
    t = row.get("contact_title", "").strip().lower()

    if s in ("c_suite", "founder"):
        return "A"
    if s == "vp":
        return "B"
    if s in ("head", "director"):
        return "C"
    if s == "manager":
        return "D"

    # Empty seniority — infer from title
    if not s:
        if any(k in t for k in ["ceo", "cto", "coo", "cfo", "cmo", "cpo", "cro",
                                  "chief", "co-founder", "cofounder", "founder"]):
            return "A"
        if any(k in t for k in ["vp,", "vp ", "vice president", "evp", "svp"]):
            return "B"
        if any(k in t for k in ["head of", "head,", "director"]):
            return "C"
        if any(k in t for k in ["manager", "lead"]):
            return "D"
    return None


# ── Step 1: Generate contacts_for_enrichment.csv ────────────────────────
def generate_contacts_for_enrichment():
    """Filter search_results.csv → contacts_for_enrichment.csv"""
    if os.path.exists(CONTACTS_FOR_ENRICHMENT):
        with open(CONTACTS_FOR_ENRICHMENT, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if rows:
            print(f"[INFO] contacts_for_enrichment.csv already exists with {len(rows)} contacts")
            return rows

    print("[INFO] Generating contacts_for_enrichment.csv from search_results.csv ...")
    with open(SEARCH_RESULTS, newline="", encoding="utf-8") as f:
        all_contacts = list(csv.DictReader(f))

    print(f"  Total contacts in search_results.csv: {len(all_contacts)}")

    filtered = []
    seen_ids = set()
    for row in all_contacts:
        pid = row.get("apollo_person_id", "").strip()
        if not pid or pid in seen_ids:
            continue

        # Must have email
        if row.get("has_email", "").strip() != "True":
            continue

        tier = assign_tier(row)
        if tier is None:
            continue

        # Exclude plain "Product Manager" with no further qualifier
        title = row.get("contact_title", "").strip()
        if title == "Product Manager":
            continue

        seen_ids.add(pid)
        row["title_tier"] = tier
        # Ensure proxy_relevance column exists (may not be in source)
        if "proxy_relevance" not in row:
            row["proxy_relevance"] = ""
        filtered.append(row)

    # Write CSV
    with open(CONTACTS_FOR_ENRICHMENT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(filtered)

    print(f"  Filtered contacts for enrichment: {len(filtered)}")
    tier_counts = Counter(r["title_tier"] for r in filtered)
    for t in sorted(tier_counts):
        print(f"    Tier {t}: {tier_counts[t]}")
    return filtered


# ── API call ────────────────────────────────────────────────────────────
HEADERS = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
}

def call_bulk_match(person_ids):
    """Call Apollo Bulk People Enrichment for a batch of person IDs."""
    payload = {
        "reveal_personal_emails": False,
        "reveal_phone_number": False,
        "details": [{"id": pid} for pid in person_ids],
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = RATE_LIMIT_WAIT * attempt
                print(f"    [RATE LIMIT] 429 — waiting {wait}s (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
            elif resp.status_code == 422:
                print(f"    [ERROR] 422 Unprocessable Entity — skipping batch")
                return None
            else:
                print(f"    [ERROR] HTTP {resp.status_code} (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(5 * attempt)
        except requests.exceptions.RequestException as e:
            print(f"    [ERROR] Network: {e} (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(5 * attempt)

    print("    [FAILED] Max retries exceeded — skipping batch")
    return None


# ── Extract enrichment data from API response ──────────────────────────
def extract_enrichment(match):
    """Extract relevant fields from a single match result."""
    if not match:
        return {}
    return {
        "contact_email": match.get("email") or "",
        "email_status": match.get("email_status") or "",
        "contact_linkedin_url": match.get("linkedin_url") or "",
        "contact_title": match.get("title") or "",
        "contact_name": match.get("name") or "",
    }


# ── Checkpoint / Resume ────────────────────────────────────────────────
def load_progress():
    """Load enrichment progress (which batches have been processed)."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {"completed_batches": 0, "enriched": {}}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


def save_checkpoint(contacts, enriched_map):
    """Save intermediate enriched results."""
    rows = build_output_rows(contacts, enriched_map)
    write_csv(CHECKPOINT_FILE, rows)
    print(f"  [CHECKPOINT] Saved {len(rows)} contacts to checkpoint")


def build_output_rows(contacts, enriched_map):
    """Merge original contact data with enrichment results."""
    rows = []
    seen = set()
    for c in contacts:
        pid = c.get("apollo_person_id", "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)

        row = {col: c.get(col, "") for col in OUTPUT_COLUMNS}
        row["title_tier"] = c.get("title_tier", assign_tier(c) or "")

        enrich = enriched_map.get(pid, {})
        if enrich:
            # Update with enriched data, but keep original if enriched is empty
            if enrich.get("contact_email"):
                row["contact_email"] = enrich["contact_email"]
            if enrich.get("email_status"):
                row["email_status"] = enrich["email_status"]
            if enrich.get("contact_linkedin_url"):
                row["contact_linkedin_url"] = enrich["contact_linkedin_url"]
            if enrich.get("contact_title"):
                row["contact_title"] = enrich["contact_title"]
            if enrich.get("contact_name"):
                row["contact_name"] = enrich["contact_name"]

        rows.append(row)
    return rows


def write_csv(filepath, rows):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ── Main enrichment loop ───────────────────────────────────────────────
def run_enrichment():
    # Step 1: Get filtered contacts
    contacts = generate_contacts_for_enrichment()
    if not contacts:
        print("[ERROR] No contacts to enrich!")
        sys.exit(1)

    # Collect person IDs
    person_ids = []
    id_set = set()
    for c in contacts:
        pid = c.get("apollo_person_id", "").strip()
        if pid and pid not in id_set:
            person_ids.append(pid)
            id_set.add(pid)

    total_contacts = len(person_ids)
    total_batches = (total_contacts + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"\n{'='*60}")
    print(f"Phase 2: Bulk People Enrichment")
    print(f"  Contacts to enrich: {total_contacts}")
    print(f"  Batches of {BATCH_SIZE}: {total_batches}")
    print(f"  Estimated credits: ~{total_contacts}")
    print(f"{'='*60}\n")

    # Load progress for resume
    progress = load_progress()
    enriched_map = progress.get("enriched", {})
    start_batch = progress.get("completed_batches", 0)

    if start_batch > 0:
        print(f"[RESUME] Resuming from batch {start_batch + 1}/{total_batches} "
              f"({len(enriched_map)} already enriched)\n")

    stats = {
        "total": 0, "enriched": 0, "with_email": 0,
        "verified_email": 0, "with_linkedin": 0, "failed": 0,
    }

    # Count already-enriched stats
    for pid, data in enriched_map.items():
        stats["total"] += 1
        if data:
            stats["enriched"] += 1
            if data.get("contact_email"):
                stats["with_email"] += 1
                if data.get("email_status") == "verified":
                    stats["verified_email"] += 1
            if data.get("contact_linkedin_url"):
                stats["with_linkedin"] += 1
        else:
            stats["failed"] += 1

    for batch_idx in range(start_batch, total_batches):
        batch_start = batch_idx * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, total_contacts)
        batch_ids = person_ids[batch_start:batch_end]

        # Skip already-enriched IDs in this batch
        ids_to_fetch = [pid for pid in batch_ids if pid not in enriched_map]
        if not ids_to_fetch:
            print(f"  Batch {batch_idx + 1}/{total_batches}: already enriched, skipping")
            continue

        result = call_bulk_match(ids_to_fetch)

        batch_enriched = 0
        batch_with_email = 0

        if result and "matches" in result:
            matches = result["matches"]
            for match in matches:
                if not match:
                    continue
                pid = match.get("id", "")
                if not pid:
                    continue
                enrich = extract_enrichment(match)
                enriched_map[pid] = enrich
                stats["total"] += 1
                stats["enriched"] += 1
                batch_enriched += 1
                if enrich.get("contact_email"):
                    stats["with_email"] += 1
                    batch_with_email += 1
                    if enrich.get("email_status") == "verified":
                        stats["verified_email"] += 1
                if enrich.get("contact_linkedin_url"):
                    stats["with_linkedin"] += 1

            # Mark IDs without matches as failed
            matched_ids = {m.get("id") for m in matches if m}
            for pid in ids_to_fetch:
                if pid not in matched_ids and pid not in enriched_map:
                    enriched_map[pid] = {}
                    stats["total"] += 1
                    stats["failed"] += 1
        else:
            # Whole batch failed
            for pid in ids_to_fetch:
                if pid not in enriched_map:
                    enriched_map[pid] = {}
                    stats["total"] += 1
                    stats["failed"] += 1

        print(f"  Batch {batch_idx + 1}/{total_batches}: "
              f"enriched {batch_enriched} contacts, {batch_with_email} with email  "
              f"[total: {stats['with_email']}/{stats['total']}]")

        # Save progress
        progress["completed_batches"] = batch_idx + 1
        progress["enriched"] = enriched_map
        save_progress(progress)

        # Checkpoint every N batches
        if (batch_idx + 1) % CHECKPOINT_EVERY == 0:
            save_checkpoint(contacts, enriched_map)

        # Pause between batches
        if batch_idx < total_batches - 1:
            time.sleep(PAUSE_BETWEEN_BATCHES)

    # ── Final output ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Writing final enriched_contacts.csv ...")
    rows = build_output_rows(contacts, enriched_map)
    write_csv(ENRICHED_OUTPUT, rows)
    print(f"Saved {len(rows)} contacts to enriched_contacts.csv")

    # Also save final checkpoint
    write_csv(CHECKPOINT_FILE, rows)

    # ── Statistics ──────────────────────────────────────────────────────
    # Recompute stats from final data for accuracy
    final_stats = recompute_stats(rows)
    print_stats(final_stats, contacts)

    # Cleanup progress file
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

    print(f"\n{'='*60}")
    print("Phase 2 complete!")
    print(f"{'='*60}")


def recompute_stats(rows):
    """Recompute stats from final output rows."""
    s = {
        "total": len(rows),
        "with_email": 0,
        "verified_email": 0,
        "guessed_email": 0,
        "with_linkedin": 0,
        "no_email": 0,
    }
    for r in rows:
        email = r.get("contact_email", "").strip()
        status = r.get("email_status", "").strip()
        linkedin = r.get("contact_linkedin_url", "").strip()

        if email:
            s["with_email"] += 1
            if status == "verified":
                s["verified_email"] += 1
            elif status == "guessed":
                s["guessed_email"] += 1
        else:
            s["no_email"] += 1

        if linkedin:
            s["with_linkedin"] += 1
    return s


def print_stats(stats, contacts):
    print(f"\n{'='*60}")
    print("ENRICHMENT STATISTICS")
    print(f"{'='*60}")
    print(f"  Total contacts processed:   {stats['total']}")
    print(f"  With email:                 {stats['with_email']} ({pct(stats['with_email'], stats['total'])})")
    print(f"    Verified email:           {stats['verified_email']} ({pct(stats['verified_email'], stats['total'])})")
    print(f"    Guessed email:            {stats['guessed_email']} ({pct(stats['guessed_email'], stats['total'])})")
    print(f"  With LinkedIn URL:          {stats['with_linkedin']} ({pct(stats['with_linkedin'], stats['total'])})")
    print(f"  No email (failed):          {stats['no_email']} ({pct(stats['no_email'], stats['total'])})")

    # Breakdown by category_norm
    cat_counter = Counter()
    tier_counter = Counter()
    for c in contacts:
        cat_counter[c.get("category_norm", "Unknown")] += 1
        tier_counter[c.get("title_tier", assign_tier(c) or "?")] += 1

    print(f"\n  By category_norm:")
    for cat, count in cat_counter.most_common():
        print(f"    {cat}: {count}")

    print(f"\n  By title_tier:")
    for tier, count in sorted(tier_counter.items()):
        print(f"    Tier {tier}: {count}")


def pct(n, total):
    if total == 0:
        return "0%"
    return f"{n/total*100:.1f}%"


if __name__ == "__main__":
    run_enrichment()
