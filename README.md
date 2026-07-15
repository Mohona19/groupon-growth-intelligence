# Groupon AI Growth Intelligence Pipeline
### Case Study — Lead Sourcing, Enrichment & Scoring
**Vertical:** Health & Beauty (Spas, Salons, Massage, Med Spas)
**Cities:** Chicago IL | Atlanta GA | Austin TX

---

## Vertical & City Selection — Defense

**Why Health & Beauty?**
Groupon's highest deal redemption rates historically come from service businesses where:
- The "first visit" is a natural purchase trigger (trying a new salon, spa, or massage therapist)
- Services are experiential, easy to package as a single-session deal
- Margins allow 30–50% discounting without destroying the business (unlike restaurants)
- Geographic proximity matters, making city-targeted deals high-conversion

Within H&B, I chose **massage > skincare > hair > nails** (reflected in `deal_format_fit` weights):
- Massage/facials: highest AOV, single-session, high perceived value, strong first-time deal fit
- Nails: commoditized, low AOV, harder for a deal to differentiate

**Why these 3 cities?**
- **Chicago:** Groupon's HQ market — sales team density is highest, fastest to test model predictions, anchor for validation
- **Atlanta:** Strong H&B market, high disposable income suburbs, underserved by national deal platforms
- **Austin:** Fast-growing, high density of new businesses (= businesses that *need* customer acquisition), tech-adjacent professional demographics who buy experiences

---

## Pipeline Architecture

```
01_source_leads.py      →  data/01_raw_leads.csv     (~120 raw → ~100 after dedup)
02_enrich_score.py      →  data/02_scored_leads.csv  (scored, ranked, pitches)
03_validate.py          →  data/03_validation_report.txt
                           data/03_validation_flagged.csv
```

---

## How to Run

**Mock mode (no API key needed — realistic synthetic data):**
```bash
pip install requests
mkdir -p data
python 01_source_leads.py --mock
python 02_enrich_score.py
python 03_validate.py
```

**Live mode (Yelp Fusion API):**
```bash
# Get free key at: https://www.yelp.com/developers/v3/manage_app
export YELP_API_KEY=your_key_here
python 01_source_leads.py
python 02_enrich_score.py
python 03_validate.py
```

---

## Scoring Model

| Signal | Max Pts | Rationale |
|---|---|---|
| Visibility Gap | 20 | Sweet spot: 50–400 reviews. Under-discovered enough to want Groupon, established enough to fulfill volume |
| Price Tier Fit | 20 | `$$` ideal. `$` = thin margins, `$$$$` = wrong customer. Groupon's value prop = "try something you couldn't normally afford" |
| Deal Format Fit | 15 | Massage/skincare > hair > nails. Reward categories with natural first-visit packaging |
| Operational Trust | 15 | Claimed listing + posted hours = manageable, responsive business. Unclaimed = SDR will ghost |
| Rating Sweet Spot | 15 | 3.8–4.4★. Under 3.8 = chargeback risk. Over 4.5 = boutique positioning, likely to churn after one deal cycle |
| Review Velocity Proxy | 10 | Relative review count vs. category max — proxy for operational activity level |
| Geo Density Bonus | 5 | Chicago > Atlanta > Austin for SDR prioritization |
| **Total** | **100** | |

**Signals excluded and why:**
- Raw star rating as primary signal: 4.9★ boutiques often actively resist discounting
- Social follower count: not available via Yelp; planned for enrichment v2
- Competitor platform exclusivity: relevant but requires deeper data (see validation failure modes)

---

## Tier Definitions

| Tier | Score | Meaning |
|---|---|---|
| A — High Priority | 75–100 | Route to SDR immediately |
| B — Qualified | 55–74 | Qualified, normal queue |
| C — Marginal | 35–54 | Nurture or skip |
| D — Disqualify | 0–34 | Do not contact |

---

## Cost & Speed

### 100 Leads (this run)
| Step | Cost | Time |
|---|---|---|
| Yelp sourcing | $0 (free tier) | ~5s |
| Enrichment (mock) | $0 | ~1s |
| Scoring | $0 (Python) | <1s |
| **Total** | **$0** | **<30s** |

### 10,000 Leads (honest projection)
| Step | Cost | Notes |
|---|---|---|
| Yelp Fusion | $10–30 | Paid tier if >500 calls/day; can spread over days free |
| Google Places enrichment | ~$100 | $0.01/lookup for status, hours, website |
| Claude Haiku scoring | ~$20 | If using LLM scoring instead of rules |
| Twilio phone validation | ~$40 | $0.004/call × 10k |
| **Total** | **~$150–200** | |
| Wall time | ~45 min | With rate limiting, retries, parallel workers |

**Key bottleneck:** Google Places API default quota is 10 QPS.
**Fix:** Request quota increase or use the Places API (New) batch endpoint.

---

## Known Failure Modes (from validation)

1. **Franchise false positives** — Chain locations score well on unit signals but can't independently onboard. Fix: franchise name-match database.
2. **Rating inflation** — 5.0★ at <40 reviews is often inauthentic. Fix: minimum review count gate or Wilson confidence interval.
3. **ClassPass/Gilt exclusivity** — Competitor platform presence is treated neutrally but some contracts prohibit concurrent Groupon deals. Fix: check for active deals, not just presence.
4. **Social/brand conflict** — High Instagram presence + premium pricing = brand-protection mindset, likely to refuse discounting. Fix: composite signal flag.
5. **Stale/closed data** — ~3–5% of Yelp businesses are permanently closed. Fix: Google Places `business_status` field or last-review-date recency check.

**Estimated data quality at 10k leads without cleaning:** 15–25% unusable.
**After proposed cleaning pipeline:** ~5% residual bad data (acceptable for outbound).

---

## Files
```
01_source_leads.py          Source ~100 leads from Yelp (or mock)
02_enrich_score.py          Enrich with competitor/social signals, score 0–100
03_validate.py              Validate top/bottom 10, generate failure mode report
data/01_raw_leads.csv       Raw sourced leads
data/02_scored_leads.csv    Enriched + scored + ranked + SDR pitches
data/03_validation_report.txt  Full validation findings
data/03_validation_flagged.csv Leads where model and human reviewer disagreed
```
