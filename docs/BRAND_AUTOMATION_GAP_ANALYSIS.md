# Brand automation — gap analysis and data availability report

Written 2026-09-13 before the brand-research upgrade, after inspecting the existing code and probing
amazon.co.uk from this machine (about a dozen page loads in total).

## 1. Existing vs required

| Area | Existing (v1.0) | Required for Brand → Winning Products | Plan |
|---|---|---|---|
| Input | One product at a time: form, Smart Paste, CSV/XLSX import | Brand name only | New "Analyze Brand" workflow on a simplified dashboard |
| Amazon data | Only text the user pastes; never contacts Amazon | Automatic search + product + offers collection | New `providers/amazon` layer (browser-based, throttled) |
| Evaluation | Fees, profit, ROI, capture model, rules, risk, score, target plan — pure functions on a `Product` | Same | **Reused unchanged**; automation produces normal `Product` objects |
| Storage | SQLite: products, snapshots, evaluations, settings | + brands, brand searches, per-search items, rejected history, supplier prices, field provenance | Schema v2 migration (additive; no data loss) |
| Duplicates | ASIN → URL → title+brand check, user chooses | Silent ASIN upsert during automation | Automation updates the existing ASIN record |
| Rejected products | Status only | Persistent rejection history; skip on later searches; explicit re-evaluation | `rejected_products` table + skip logic + "Re-evaluate previously rejected" option (off) |
| Progress | Synchronous requests | Long-running job with visible progress, resumable | Background worker thread, state in SQLite, polling UI |
| Export | Qualified / Rejected / Incomplete / Summary (+3) | + per-brand Summary, Winning, Rejected, Incomplete, Skipped, Collection errors | New brand workbook reusing the existing sheet writer |
| Sourcing cost | Typed per product | Cannot come from Amazon | Supplier price list provider (ASIN/EAN → cost), reused across searches |
| Settings | Rules, capture model, risk, fees | + collection pace, pages, refresh window, delivery postcode | New "Brand research" settings group |

## 2. What the probes showed

1. **Plain HTTP does not work.** A normal Python request for `/s?k=Aero` returned HTTP 202 with a 2 KB
   AWS WAF JavaScript challenge page (no products). Solving that challenge programmatically would be
   circumventing a protection, so it is not done.
2. **A real browser works.** The user's installed Microsoft Edge, driven by Playwright, loaded the same
   search with 48 results and a "Next" page, and product pages with title, brand, Best Sellers Rank,
   dimensions, weight, availability and price.
3. **Location matters.** From this connection Amazon showed prices in PKR, "No featured offers available"
   and no delivery. After setting the site's own preferences — currency **GBP** and delivery postcode
   **SW1A 1AA** (available to every visitor via "Deliver to") — search showed £ prices on 44 of 48 results,
   product pages showed the Buy Box price and stock, and the All Offers Display listed each offer's
   "Dispatches from" and "Sold by".
4. **robots.txt** (`User-agent: *`) does not disallow `/s?` search or `/dp/` product pages. It does disallow
   `/gp/offer-listing`, which is not used; the All Offers Display ajax endpoint is not listed.
5. **Amazon's Conditions of Use** restrict automated data collection. The tool therefore runs only when the
   user starts it, fetches slowly (one page every few seconds, one job at a time), caches pages, stops on any
   CAPTCHA, and never bypasses a block. Using it is the user's decision and responsibility.

## 3. Field-by-field classification

A = collected automatically for free · B = sometimes available automatically · C = needs another source/API ·
D = user-specific information · E = transparently estimated

| Field used by the evaluation | Class | Automatic source | Why it can be missing |
|---|---|---|---|
| ASIN | A | Search result `data-asin`, product page | — |
| Product title | A | Product page title | — |
| Amazon URL | A | Built as `https://www.amazon.co.uk/dp/{ASIN}` | — |
| Brand | A/B | "Brand: …" byline, "Visit the … Store", product details "Brand Name" | Some listings only show a manufacturer |
| Amazon selling price (Buy Box) | B | Product page "price to pay" | No Buy Box / unavailable listing / out of stock |
| Category, BSR category | B | Breadcrumb, Best Sellers Rank line | New or unranked listings |
| Best Sellers Rank | B | Product details | New or unranked listings |
| Total sellers | B | All Offers Display: featured offer + "N other options" (new, for a UK delivery address) | Offers change constantly; hidden when no offers ship to the UK address |
| FBA sellers | B | All Offers Display: offers "Dispatches from Amazon", excluding Amazon's own offer | As above |
| Amazon sells the listing | B | "Sold by Amazon" in the featured offer or offer list | As above |
| Weight and dimensions | B | "Package Dimensions" / "Product Dimensions" / "Item weight" | Some listings omit them; product size can differ from packed size (flagged) |
| Availability | B | Stock message | — |
| Referral fee category | E | Mapped from Amazon's top-level category | Mapping is approximate — flagged ESTIMATED |
| Amazon fees | E | Existing UK fee table (unchanged) | Always an estimate; exact fees are account-specific |
| **Estimated monthly sales** | **B (lower bound) / C** | Amazon's "50+ / 100+ / 1K+ bought in past month" badge, recorded as an ESTIMATED lower bound | Amazon shows it on only some listings. There is **no free, defensible sales model**; without the badge the value stays **Unavailable** and the product is Incomplete |
| **Sourcing cost** | **D** | The user's supplier price list (ASIN or EAN → cost), imported once and reused | A brand name never reveals a trade price |
| Supplier | D | Supplier price list | As above |
| Shipping/prep, other costs | D | Supplier price list or product edit | Business-specific |
| **Restriction / gating status** | **D (C: official API)** | Not collected — stays Unknown | Account-specific; only visible in the seller's own Seller Central |
| Hazmat, battery, liquid, fragile, seasonal, IP concern | D | Not collected automatically | Listing text is not a reliable signal; wrong flags would change risk silently |
| Price / BSR / seller history | C | Local history builds up each time a brand is re-analyzed | Historical data needs Keepa-style tracking |

## 4. Data that cannot be obtained reliably for free

| Data | Why not | Free methods tried / available | What remains | Official or free alternative | Optional paid solution | Can the tool continue without it? |
|---|---|---|---|---|---|---|
| Monthly sales | Amazon does not publish sales figures | "bought in past month" badge (used, lower bound only) | Listings without the badge → Unavailable → Incomplete | None that gives real sales | Keepa (`monthlySold`, rank history), Jungle Scout / Helium 10 sales estimates | Yes — products without a figure are marked Incomplete, never guessed |
| Sourcing cost | Private trade price | Supplier price list import (implemented) | Products not in a price list → "Sourcing cost required" | Your supplier's price list | — | Yes — every other check still runs; the report shows the highest cost that would still qualify |
| Restriction / gating | Tied to the seller account | None without the seller's credentials | Always "Unknown" (counts as a risk point) | **Amazon Selling Partner API — Listings Restrictions** (free for registered sellers; needs developer registration and LWA credentials) | — | Yes |
| Exact Amazon fees | Account- and category-specific | Existing fee table (estimate) | Estimates only | **SP-API Product Fees** (free with credentials) | — | Yes |
| Reliable offer counts | Offers shown depend on location and change hourly | All Offers Display with a UK postcode (implemented) | Snapshot at collection time | **SP-API Product Pricing `getItemOffers`** (free with credentials) | Keepa offer history | Yes |
| History (price, BSR, sellers) | Needs continuous tracking | Local snapshots on every re-analysis (implemented) | Only from the first analysis onward | — | Keepa | Yes |

**Recommendation:** the most valuable free upgrade is the official Amazon SP-API (restrictions, exact fees,
offers, catalog), which needs the user's Seller Central developer credentials. Keepa is the paid option for
sales estimates and history. Neither is required for version 2.
