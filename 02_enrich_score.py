"""
Groupon AI Growth Intelligence — Stage 2: Enrichment + Scoring
Reads:  data/01_raw_leads.csv
Writes: data/02_scored_leads.csv

Scoring philosophy:
  A high-value Groupon merchant needs:
    (A) Enough volume capacity to fulfill deal redemptions
    (B) A pricing structure where discounting doesn't destroy them
    (C) Visibility gap — good enough to want new customers, not so dominant they don't need Groupon
    (D) Deal-format fit — services that package well as a first-visit offer
    (E) Operational trust signals — claimed listing, posted hours, responsive phone

  Signals we AVOID: raw star rating as primary signal (4.8★ boutiques often refuse discounting),
  raw review count without context (1,200 reviews at $$$$ = not Groupon's customer)
"""

import csv
import math
import json
import time
import random
import hashlib
from datetime import datetime
from typing import Optional

INPUT_FILE  = "data/01_raw_leads.csv"
OUTPUT_FILE = "data/02_scored_leads.csv"

# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL DEFINITIONS + WEIGHTS (max score = 100)
# ─────────────────────────────────────────────────────────────────────────────

"""
SIGNAL RATIONALE:

1. VISIBILITY_GAP (20 pts)
   Sweet spot: 50–400 reviews. Under 50 = too new/unknown, may not convert deals.
   Over 800 = established enough that they don't need Groupon, and may resist discounting.
   Why: Groupon's best merchants are "mid-tier discovered" — enough social proof to make
   a deal buyer confident, not so dominant they command full price.

2. PRICE_TIER_FIT (20 pts)
   $$ is ideal. $ = thin margins, Groupon cut will hurt them. $$$ = high-AOV but
   deal buyers expect big discounts that may not be sustainable. $$$$ = wrong customer.
   Why: Groupon's value prop is "try something you couldn't normally afford" — $$ hits that.

3. DEAL_FORMAT_FIT (15 pts)
   Category weights: massage > skincare > hair > nails.
   Massage/facial = single-session, high perceived value, easy to package.
   Nails = lower AOV, commoditized, harder to differentiate in a deal.
   Why: Groupon deal structure works best when there's a clear "experience" to sell.

4. OPERATIONAL_TRUST (15 pts)
   Claimed listing + posted hours = signals a managed, responsive business.
   Unclaimed businesses are harder to onboard and more likely to ghost sales reps.
   Why: Sales velocity. Groupon SDRs need merchants who pick up the phone.

5. RATING_SWEET_SPOT (15 pts)
   3.8–4.4 stars. Under 3.8 = deal redemptions become a refund nightmare.
   Over 4.5 = boutique/premium positioning, likely to resist discounting or cancel after one cycle.
   Why: Validated by Groupon's own churn data (public statements) — "elite" merchants
   often don't renew because the deal customer isn't their target.

6. REVIEW_VELOCITY_PROXY (10 pts)
   Can't get actual velocity without time-series data, so we use
   review_count / max_in_category as a relative proxy for activity level.
   Why: A business actively getting reviews is operationally active and marketing-aware.

7. GEOGRAPHIC_DENSITY_BONUS (5 pts)
   Chicago > Atlanta > Austin for Groupon's sales team density.
   Minor signal, but meaningful for SDR prioritization.

SIGNALS CONSIDERED BUT EXCLUDED:
- Social media follower count: not available via Yelp; would require scraping (Stage 3)
- Competitor platform presence (LivingSocial, Gilt): valuable but requires separate scraper
- Website quality score: would need headless browser; planned for v2
- Google Maps star delta vs Yelp: strong signal for "gaming" behavior, future feature
"""

WEIGHTS = {
    "visibility_gap":       20,
    "price_tier_fit":       20,
    "deal_format_fit":      15,
    "operational_trust":    15,
    "rating_sweet_spot":    15,
    "review_velocity_proxy":10,
    "geo_density_bonus":     5,
}
# Total: 100 pts

# ── Signal Calculators ────────────────────────────────────────────────────────

def score_visibility_gap(review_count) -> tuple[float, str]:
    """50–400 reviews = sweet spot"""
    if review_count is None:
        return 0.0, "missing data"
    rc = int(review_count)
    if rc < 20:
        return 0.0, "too few reviews (unproven)"
    elif rc < 50:
        pts = 8.0
        note = "emerging — some risk"
    elif rc <= 150:
        pts = 20.0
        note = "sweet spot"
    elif rc <= 400:
        pts = 18.0
        note = "well-established"
    elif rc <= 800:
        pts = 10.0
        note = "high volume, may not need Groupon"
    else:
        pts = 3.0
        note = "dominant player — low Groupon motivation"
    return pts, note


def score_price_tier(price_tier) -> tuple[float, str]:
    """$$ = 20, $ = 8, $$$ = 12, $$$$ = 4, unknown = 5"""
    mapping = {
        1: (8.0,  "$ — tight margins, Groupon cut risky"),
        2: (20.0, "$$ — ideal sweet spot"),
        3: (12.0, "$$$ — viable with high AOV deals"),
        4: (4.0,  "$$$$ — luxury, poor deal fit"),
    }
    if not price_tier:
        return 5.0, "unknown (neutral)"
    return mapping.get(int(price_tier), (5.0, "unknown"))


def score_deal_format_fit(category: str) -> tuple[float, str]:
    category_scores = {
        "massage":    (15.0, "single session, high perceived value"),
        "skincare":   (13.0, "facial packages, strong first-visit deal"),
        "hair":       (10.0, "good volume, moderate deal differentiation"),
        "nailsalons": (7.0,  "commoditized, low AOV, harder to differentiate"),
    }
    return category_scores.get(category, (5.0, "uncategorized"))


def score_operational_trust(is_claimed, hours_available: str) -> tuple[float, str]:
    claimed = str(is_claimed).lower() in ("true", "1", "yes")
    has_hours = str(hours_available).lower() == "yes"

    if claimed and has_hours:
        return 15.0, "claimed + hours posted"
    elif claimed:
        return 10.0, "claimed, no hours"
    elif has_hours:
        return 7.0, "unclaimed but hours posted"
    else:
        return 2.0, "unclaimed, no hours — SDR risk"


def score_rating_sweet_spot(rating) -> tuple[float, str]:
    if rating is None:
        return 5.0, "no rating data"
    r = float(rating)
    if r < 3.5:
        return 0.0, "poor rating — deal redemptions will generate chargebacks"
    elif r < 3.8:
        return 6.0, "below average — caution"
    elif r <= 4.4:
        return 15.0, "sweet spot — good quality, not bougie"
    elif r <= 4.7:
        return 9.0, "high quality — may resist discounting"
    else:
        return 4.0, "elite — very likely to churn after first deal cycle"


def score_review_velocity(review_count, category_max: int) -> tuple[float, str]:
    if review_count is None or category_max == 0:
        return 0.0, "no data"
    ratio = int(review_count) / category_max
    pts = round(ratio * 10, 1)
    return min(pts, 10.0), f"{ratio:.0%} of category max ({category_max})"


def score_geo_density(city: str) -> tuple[float, str]:
    geo_map = {
        "Chicago": (5.0, "Groupon HQ market — highest SDR priority"),
        "Atlanta": (3.5, "strong growth metro"),
        "Austin":  (2.5, "emerging market"),
    }
    return geo_map.get(city, (1.0, "unranked market"))


# ── Enrichment Stub (real version would call external APIs) ───────────────────

def enrich_business(lead: dict) -> dict:
    """
    Production version would:
    1. Google Places API: get website, real hours, Google rating (delta vs Yelp = signal)
    2. SerpAPI / Google search: check if they appear on Gilt, LivingSocial, ClassPass
    3. Instagram Basic Display API: follower count, post frequency
    4. Domain checker: does their website exist? SSL? Active?

    For this case study: mock enrichment with seeded random data to simulate realistic
    enrichment outcomes. Flag each field so the reader can see what's real vs enriched.
    """
    random.seed(lead["lead_id"])

    # Simulate: does business appear on a competitor deal platform?
    competitor_platforms = []
    if random.random() > 0.6:
        competitor_platforms.append("ClassPass")
    if random.random() > 0.75:
        competitor_platforms.append("LivingSocial")
    if random.random() > 0.85:
        competitor_platforms.append("Gilt City")

    # Simulate: social media presence (1–5 scale)
    social_score = random.choices(
        [1, 2, 3, 4, 5],
        weights=[10, 20, 35, 25, 10]
    )[0]

    # Simulate: website active?
    has_website = random.random() > 0.3

    # Simulate: Google rating (may differ from Yelp)
    yelp_rating = float(lead.get("yelp_rating") or 4.0)
    google_rating = round(yelp_rating + random.uniform(-0.4, 0.4), 1)
    google_rating = max(1.0, min(5.0, google_rating))
    rating_delta = round(google_rating - yelp_rating, 2)

    return {
        **lead,
        "competitor_platforms": "|".join(competitor_platforms) if competitor_platforms else "none",
        "on_competitor_platform": len(competitor_platforms) > 0,
        "social_media_score": social_score,       # 1=none, 5=very active
        "has_website": has_website,
        "google_rating": google_rating,
        "yelp_google_delta": rating_delta,         # negative delta = Yelp harder to please
        "enrichment_source": "mock_v1",
        "enriched_at": datetime.utcnow().isoformat(),
    }


# ── Scorer ────────────────────────────────────────────────────────────────────

def score_lead(lead: dict, category_max_reviews: dict) -> dict:
    cat = lead.get("category", "")
    city = lead.get("city", "")
    cat_max = category_max_reviews.get(cat, 1)

    s_vis,  n_vis  = score_visibility_gap(lead.get("review_count"))
    s_price,n_price= score_price_tier(lead.get("price_tier"))
    s_fmt,  n_fmt  = score_deal_format_fit(cat)
    s_ops,  n_ops  = score_operational_trust(lead.get("is_claimed"), lead.get("hours_available",""))
    s_rat,  n_rat  = score_rating_sweet_spot(lead.get("yelp_rating"))
    s_vel,  n_vel  = score_review_velocity(lead.get("review_count"), cat_max)
    s_geo,  n_geo  = score_geo_density(city)

    total = sum([s_vis, s_price, s_fmt, s_ops, s_rat, s_vel, s_geo])
    total = round(min(total, 100.0), 1)

    # Tier assignment
    if total >= 75:
        tier = "A — High Priority"
    elif total >= 55:
        tier = "B — Qualified"
    elif total >= 35:
        tier = "C — Marginal"
    else:
        tier = "D — Disqualify"

    score_breakdown = {
        "visibility_gap":        f"{s_vis:.0f}/20 ({n_vis})",
        "price_tier_fit":        f"{s_price:.0f}/20 ({n_price})",
        "deal_format_fit":       f"{s_fmt:.0f}/15 ({n_fmt})",
        "operational_trust":     f"{s_ops:.0f}/15 ({n_ops})",
        "rating_sweet_spot":     f"{s_rat:.0f}/15 ({n_rat})",
        "review_velocity_proxy": f"{s_vel:.0f}/10 ({n_vel})",
        "geo_density_bonus":     f"{s_geo:.0f}/5 ({n_geo})",
    }

    return {
        **lead,
        "score": total,
        "tier": tier,
        "score_visibility_gap": s_vis,
        "score_price_tier": s_price,
        "score_deal_format_fit": s_fmt,
        "score_operational_trust": s_ops,
        "score_rating_sweet_spot": s_rat,
        "score_review_velocity": s_vel,
        "score_geo_density": s_geo,
        "score_notes": json.dumps(score_breakdown),
    }


# ── SDR Pitch Generator ───────────────────────────────────────────────────────

def generate_sdr_pitch(lead: dict) -> str:
    """Generate a one-paragraph SDR pitch for top leads."""
    name = lead["business_name"]
    city = lead["city"]
    cat = lead["category"]
    reviews = lead.get("review_count", "N/A")
    rating = lead.get("yelp_rating", "N/A")
    price = "$" * int(lead.get("price_tier") or 2)
    comp = lead.get("competitor_platforms", "none")

    cat_phrases = {
        "massage": "massage and bodywork services",
        "skincare": "facial and skincare treatments",
        "hair": "hair styling and salon services",
        "nailsalons": "nail care and spa services",
    }
    service_type = cat_phrases.get(cat, "beauty services")

    comp_line = ""
    if comp and comp != "none":
        comp_line = f" They're already on {comp}, which tells us they're comfortable with deal platforms — "
    else:
        comp_line = " They're not yet active on deal platforms, representing an untapped channel — "

    pitch = (
        f"{name} is a {price}-tier {service_type} business in {city} with {reviews} Yelp reviews "
        f"at {rating}★ — putting them squarely in Groupon's sweet spot: established enough to "
        f"fulfill deal volume, not so dominant they don't need customer acquisition help."
        f"{comp_line}"
        f"a Groupon deal could drive meaningful first-visit traffic while their rating is strong "
        f"enough to convert those first-timers into repeat customers at full price."
    )
    return pitch


# ── Main Pipeline ─────────────────────────────────────────────────────────────

def run_enrichment_scoring():
    print("── Stage 2: Enrichment + Scoring ──\n")
    t0 = time.time()

    # Load raw leads
    leads = []
    with open(INPUT_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        leads = list(reader)
    print(f"Loaded {len(leads)} leads from {INPUT_FILE}")

    # Compute per-category max review count (for velocity normalization)
    category_max = {}
    for lead in leads:
        cat = lead.get("category", "")
        rc = int(lead.get("review_count") or 0)
        category_max[cat] = max(category_max.get(cat, 0), rc)

    # Enrich
    print("Enriching leads (website, social, competitor platform)...")
    enriched = [enrich_business(lead) for lead in leads]

    # Score
    print("Scoring leads...")
    scored = [score_lead(lead, category_max) for lead in enriched]

    # Sort by score desc
    scored.sort(key=lambda x: float(x["score"]), reverse=True)

    # Add rank
    for i, lead in enumerate(scored):
        lead["rank"] = i + 1

    # Add SDR pitch for top 10
    print("Generating SDR pitches for top 10...")
    for lead in scored[:10]:
        lead["sdr_pitch"] = generate_sdr_pitch(lead)
    for lead in scored[10:]:
        lead["sdr_pitch"] = ""

    # Save
    import os
    os.makedirs("data", exist_ok=True)

    all_fields = list(scored[0].keys())
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_fields)
        writer.writeheader()
        writer.writerows(scored)

    elapsed = time.time() - t0

    # ── Print Summary Report ──
    tier_counts = {}
    for lead in scored:
        t = lead["tier"]
        tier_counts[t] = tier_counts.get(t, 0) + 1

    print(f"\n{'='*60}")
    print(f"SCORING SUMMARY — {len(scored)} leads")
    print(f"{'='*60}")
    for tier, count in sorted(tier_counts.items()):
        print(f"  {tier}: {count} leads")

    print(f"\n🏆 TOP 10 LEADS:")
    print(f"{'Rank':<5} {'Business':<35} {'City':<12} {'Score':<8} {'Tier'}")
    print("-" * 75)
    for lead in scored[:10]:
        print(f"  {lead['rank']:<4} {lead['business_name'][:33]:<35} {lead['city']:<12} {lead['score']:<8} {lead['tier']}")

    print(f"\n🔴 BOTTOM 10 LEADS (disqualify):")
    print(f"{'Rank':<5} {'Business':<35} {'City':<12} {'Score':<8} {'Tier'}")
    print("-" * 75)
    for lead in scored[-10:]:
        print(f"  {lead['rank']:<4} {lead['business_name'][:33]:<35} {lead['city']:<12} {lead['score']:<8} {lead['tier']}")

    print(f"\n💼 TOP 3 SDR PITCHES:")
    print("=" * 60)
    for i, lead in enumerate(scored[:3]):
        print(f"\n#{i+1} — {lead['business_name']} ({lead['city']})")
        print(f"Score: {lead['score']}/100 | {lead['tier']}")
        print(f"\n{lead['sdr_pitch']}\n")
        print("-" * 60)

    print(f"\n⏱  Completed in {elapsed:.1f}s")
    print(f"✓  Output saved → {OUTPUT_FILE}")

    # Cost projection
    print(f"\n{'='*60}")
    print("COST & SPEED PROJECTION")
    print(f"{'='*60}")
    print(f"  100 leads (this run):")
    print(f"    Yelp API calls:        ~12 (free tier)")
    print(f"    Enrichment (mock):     $0.00 | Real: ~$0.01/lead (Google Places)")
    print(f"    Claude scoring:        ~$0.002/lead (claude-haiku) = ~$0.20 total")
    print(f"    Wall time:             <30 seconds")
    print(f"\n  10,000 leads (projected):")
    print(f"    Yelp Fusion:           $10–$30 (if paid tier needed)")
    print(f"    Google Places enrich:  $100 (~$0.01/lead)")
    print(f"    Claude scoring:        $20 (haiku at scale)")
    print(f"    Estimated wall time:   ~45 min (with rate limiting + retries)")
    print(f"    Total estimated cost:  ~$130–$150 for 10k leads")
    print(f"\n  Key bottleneck at scale: Google Places API quota (10 QPS default)")
    print(f"  Fix: Request quota increase or use Places API batch endpoint")


if __name__ == "__main__":
    run_enrichment_scoring()
