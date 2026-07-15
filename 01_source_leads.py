"""
Groupon AI Growth Intelligence — Stage 1: Lead Sourcing
Vertical: Health & Beauty (Spas, Salons, Med Spas)
Cities: Chicago IL | Atlanta GA | Austin TX

Usage:
  MOCK mode (no API key):  python 01_source_leads.py --mock
  Live mode:               YELP_API_KEY=xxx python 01_source_leads.py

Output: data/01_raw_leads.csv (~100 records)
"""

import os
import csv
import time
import random
import argparse
import requests
import hashlib
from datetime import datetime
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────

TARGETS = [
    {"city": "Chicago",  "state": "IL", "lat": 41.8781, "lon": -87.6298},
    {"city": "Atlanta",  "state": "GA", "lat": 33.7490, "lon": -84.3880},
    {"city": "Austin",   "state": "TX", "lat": 30.2672, "lon": -97.7431},
]

CATEGORIES = [
    "hair",            # salons — high Groupon deal volume
    "skincare",        # facials, med spas — high AOV
    "massage",         # massage parlors — strong repeat/deal redemption
    "nailsalons",      # nail salons — price-sensitive, deal-hungry
]

YELP_SEARCH_URL = "https://api.yelp.com/v3/businesses/search"
RESULTS_PER_CITY_CAT = 10   # 3 cities × 4 categories × 10 = 120 raw → ~100 after dedup
OUTPUT_DIR = "data"
OUTPUT_FILE = f"{OUTPUT_DIR}/01_raw_leads.csv"

FIELDNAMES = [
    "lead_id", "business_name", "yelp_id", "city", "state",
    "category", "address", "phone", "website",
    "yelp_rating", "review_count", "price_tier",
    "is_claimed", "hours_available",
    "latitude", "longitude",
    "source", "sourced_at",
]

# ── Yelp Live Fetcher ─────────────────────────────────────────────────────────

def fetch_yelp(api_key: str, city: str, state: str, category: str, offset: int = 0) -> list[dict]:
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "term": category,
        "location": f"{city}, {state}",
        "categories": category,
        "limit": RESULTS_PER_CITY_CAT,
        "offset": offset,
        "sort_by": "review_count",   # bias toward established businesses
    }
    try:
        r = requests.get(YELP_SEARCH_URL, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("businesses", [])
    except requests.exceptions.RequestException as e:
        print(f"  [WARN] Yelp API error for {city}/{category}: {e}")
        return []


def parse_yelp_business(biz: dict, city: str, state: str, category: str) -> dict:
    address_parts = biz.get("location", {})
    address = ", ".join(filter(None, [
        address_parts.get("address1"),
        address_parts.get("city"),
        address_parts.get("state"),
        address_parts.get("zip_code"),
    ]))
    price = biz.get("price", "")
    price_tier = len(price) if price else None   # $ = 1, $$ = 2, etc.

    yelp_id = biz.get("id", "")
    lead_id = hashlib.md5(yelp_id.encode()).hexdigest()[:10]

    return {
        "lead_id": lead_id,
        "business_name": biz.get("name", ""),
        "yelp_id": yelp_id,
        "city": city,
        "state": state,
        "category": category,
        "address": address,
        "phone": biz.get("phone", ""),
        "website": biz.get("url", ""),           # Yelp profile URL; enrichment adds real website
        "yelp_rating": biz.get("rating"),
        "review_count": biz.get("review_count"),
        "price_tier": price_tier,
        "is_claimed": biz.get("is_claimed", False),
        "hours_available": "yes" if biz.get("hours") else "no",
        "latitude": biz.get("coordinates", {}).get("latitude"),
        "longitude": biz.get("coordinates", {}).get("longitude"),
        "source": "yelp_fusion",
        "sourced_at": datetime.utcnow().isoformat(),
    }


# ── Mock Data Generator ───────────────────────────────────────────────────────

MOCK_NAMES = {
    "hair": [
        "Luxe Locks Studio", "The Blowout Bar", "Silk & Shear Salon",
        "Crown & Glory Hair", "The Mane Event", "Allure Hair Lounge",
        "Studio 22 Hair Co.", "Velvet Scissors", "Nova Hair Studio", "Gloss & Go",
    ],
    "skincare": [
        "Glow Lab MedSpa", "Pure Radiance Studio", "The Skin Clinic",
        "Dermify MedSpa", "Luminary Aesthetics", "Revive Skin Studio",
        "Flawless Face Lounge", "AuraSkin Bar", "The Facial Room", "Clarity Spa",
    ],
    "massage": [
        "Zen Body Works", "Restore Massage Studio", "Deep Roots Bodywork",
        "The Massage Room", "Align Bodywork", "Serenity Massage Lounge",
        "Knot Your Average Spa", "Cloud Nine Massage", "Balance Bodyworks", "RefreshSpa",
    ],
    "nailsalons": [
        "Polish & Pout", "The Nail Bar", "Lacquer Lounge",
        "Tip & Toe Studio", "Gleam Nail Spa", "Pink Coat Nails",
        "The Mani Cave", "Gel & Go Nails", "Polished Social Club", "Nailed It Spa",
    ],
}

MOCK_STREETS = [
    "Michigan Ave", "Peachtree St", "Congress Ave", "Wacker Dr",
    "Buckhead Loop", "South Congress", "Navy Pier Blvd", "Midtown Ave", "6th St",
]

def mock_business(city: str, state: str, category: str, idx: int) -> dict:
    random.seed(f"{city}{category}{idx}")
    names = MOCK_NAMES[category]
    name = names[idx % len(names)]
    # Add city suffix to differentiate duplicates
    if idx >= len(names):
        name = f"{name} ({city[:3].upper()})"

    yelp_id = f"mock-{city[:3].lower()}-{category[:3]}-{idx:03d}"
    lead_id = hashlib.md5(yelp_id.encode()).hexdigest()[:10]

    rating = round(random.choice([3.0, 3.5, 3.5, 4.0, 4.0, 4.0, 4.5, 4.5, 5.0]), 1)
    review_count = random.choice([
        12, 28, 45, 67, 102, 150, 204, 311, 478, 620, 850, 1100, 1450,
    ])
    price_tier = random.choice([1, 1, 2, 2, 2, 3, 3, 4])
    street_num = random.randint(100, 9999)
    street = random.choice(MOCK_STREETS)
    phone = f"+1{random.randint(2000000000,9999999999)}"
    is_claimed = random.random() > 0.25   # 75% claimed on Yelp
    has_hours = random.random() > 0.15

    return {
        "lead_id": lead_id,
        "business_name": name,
        "yelp_id": yelp_id,
        "city": city,
        "state": state,
        "category": category,
        "address": f"{street_num} {street}, {city}, {state}",
        "phone": phone,
        "website": f"https://www.{name.lower().replace(' ','').replace('&','and')[:20]}.com",
        "yelp_rating": rating,
        "review_count": review_count,
        "price_tier": price_tier,
        "is_claimed": is_claimed,
        "hours_available": "yes" if has_hours else "no",
        "latitude": TARGETS[[t["city"] for t in TARGETS].index(city)]["lat"] + random.uniform(-0.08, 0.08),
        "longitude": TARGETS[[t["city"] for t in TARGETS].index(city)]["lon"] + random.uniform(-0.08, 0.08),
        "source": "mock",
        "sourced_at": datetime.utcnow().isoformat(),
    }


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(leads: list[dict]) -> list[dict]:
    """
    Dedup strategy:
    1. Exact yelp_id match
    2. Fuzzy: same city + normalized name (handles 'The Nail Bar' vs 'Nail Bar, The')
    """
    seen_ids = set()
    seen_names = set()
    unique = []
    dupes = 0

    for lead in leads:
        # Primary key: yelp_id
        if lead["yelp_id"] in seen_ids:
            dupes += 1
            continue

        # Secondary: normalized name+city fingerprint
        normalized = (
            lead["city"].lower(),
            lead["business_name"].lower()
                .replace("the ", "")
                .replace(",", "")
                .strip()
        )
        if normalized in seen_names:
            dupes += 1
            continue

        seen_ids.add(lead["yelp_id"])
        seen_names.add(normalized)
        unique.append(lead)

    print(f"  [DEDUP] Removed {dupes} duplicates → {len(unique)} unique leads")
    return unique


# ── Main Pipeline ─────────────────────────────────────────────────────────────

def source_leads(mock: bool = False, api_key: Optional[str] = None) -> list[dict]:
    all_leads = []
    total_calls = 0

    for target in TARGETS:
        city, state = target["city"], target["state"]
        print(f"\n── {city}, {state} ──")

        for cat in CATEGORIES:
            print(f"  Fetching [{cat}]...", end=" ")

            if mock:
                businesses = [
                    mock_business(city, state, cat, i)
                    for i in range(RESULTS_PER_CITY_CAT)
                ]
                all_leads.extend(businesses)
                print(f"{len(businesses)} records (mock)")
            else:
                raw = fetch_yelp(api_key, city, state, cat)
                parsed = [parse_yelp_business(b, city, state, cat) for b in raw]
                all_leads.extend(parsed)
                print(f"{len(parsed)} records")
                total_calls += 1
                time.sleep(0.25)   # Yelp rate limit: 5000 req/day, polite pacing

    print(f"\nTotal raw records: {len(all_leads)}")
    return all_leads


def save_leads(leads: list[dict], filepath: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(leads)
    print(f"\n✓ Saved {len(leads)} leads → {filepath}")


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Groupon Lead Sourcing — Stage 1")
    parser.add_argument("--mock", action="store_true", help="Use mock data (no API key needed)")
    args = parser.parse_args()

    api_key = os.environ.get("YELP_API_KEY")
    use_mock = args.mock or not api_key

    if use_mock:
        print("⚙  Running in MOCK mode (realistic synthetic data)")
        print("   To use live Yelp data: YELP_API_KEY=your_key python 01_source_leads.py")
    else:
        print(f"⚙  Running in LIVE mode (Yelp Fusion API)")

    t0 = time.time()
    raw_leads = source_leads(mock=use_mock, api_key=api_key)
    unique_leads = deduplicate(raw_leads)
    save_leads(unique_leads, OUTPUT_FILE)

    elapsed = time.time() - t0
    print(f"⏱  Sourcing completed in {elapsed:.1f}s")
    print(f"📊 Coverage: {len(TARGETS)} cities × {len(CATEGORIES)} categories")
    print(f"🔢 Final lead count: {len(unique_leads)}")

    # Cost estimate
    if not use_mock:
        api_calls = len(TARGETS) * len(CATEGORIES)
        print(f"\n💰 Cost estimate:")
        print(f"   Yelp Fusion: {api_calls} API calls (free tier: 500 calls/day)")
        print(f"   At 10,000 leads: ~{10000 // RESULTS_PER_CITY_CAT} calls → still within free tier if batched over days")
        print(f"   Paid Yelp plan: ~$0.001/call → $10 for 10,000 leads at this density")
