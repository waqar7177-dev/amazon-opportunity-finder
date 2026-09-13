# Amazon UK Opportunity Finder

A local web app that helps you decide whether an Amazon UK product is worth buying for **wholesale,
online arbitrage or FBA**. Paste the Amazon page (or type or import the details), add your sourcing cost,
and it estimates Amazon fees, profit, ROI and monthly profit, applies your qualification rules, scores the
risk, ranks the good opportunities, plans which products could reach your monthly profit target, and exports
everything to a formatted Excel workbook.

It runs entirely on your own computer at **http://127.0.0.1:8877**. No login, no cloud, no paid API.

---

## Contents

- [What it does — and what it does not do](#what-it-does--and-what-it-does-not-do)
- [Quick start](#quick-start)
- [Adding products](#adding-products)
- [How Smart Paste works](#how-smart-paste-works)
- [Qualification rules and statuses](#qualification-rules-and-statuses)
- [How profit is calculated](#how-profit-is-calculated)
- [Amazon UK fees](#amazon-uk-fees)
- [What "estimated" means](#what-estimated-means)
- [Risk scoring](#risk-scoring)
- [Opportunity Score and ranking](#opportunity-score-and-ranking)
- [Target profit plan](#target-profit-plan)
- [Excel and CSV export](#excel-and-csv-export)
- [Settings](#settings)
- [Your data: database, history and backups](#your-data-database-history-and-backups)
- [Privacy and security](#privacy-and-security)
- [Project structure](#project-structure)
- [Running the tests](#running-the-tests)
- [Future Keepa integration](#future-keepa-integration)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

---

## What it does — and what it does not do

**It does**

- Extract likely product facts from Amazon UK page text you paste, and let you verify each one before saving.
- Accept manual entry and bulk import from CSV, Excel (.xlsx) or rows pasted from a spreadsheet.
- Estimate the referral fee, FBA fulfilment fee, surcharges and (optionally) VAT from a UK fee table.
- Calculate net profit, ROI, margin, theoretical and conservative monthly profit.
- Apply your qualification rules and explain exactly why each product passed or failed.
- Score risk with transparent, point-based rules and show every reason.
- Rank qualified products with a published 0–100 Opportunity Score and build a target profit plan.
- Detect duplicates, keep value history, and export a professional Excel workbook.

**It does not**

- **Scrape Amazon.** It never loads Amazon pages, never works around CAPTCHAs or bot protection. It only reads text *you* paste.
- **Guess missing data.** A missing price, BSR, sales estimate or seller count is reported as missing. The product is marked *Incomplete Data*, never silently filled in.
- **Tell you an ASIN is ungated.** Restriction status is whatever you record after checking Seller Central. *Unknown* is always treated as a risk.
- **Guarantee fees or income.** Fees, sales, capture rates and monthly profits are estimates. Confirm exact fees in the Seller Central Revenue Calculator before buying stock.
- **Need Keepa or any paid service.** Keepa support is prepared as an optional, disabled plug-in.

---

## Quick start

You need **Python 3.11 or newer** ([python.org/downloads](https://www.python.org/downloads/)). On Windows, tick
**“Add python.exe to PATH”** during setup.

### Windows

Double-click **`run.bat`**. It will:

1. find Python 3.11+ and create a virtual environment in `.venv` (first run only),
2. install the requirements,
3. create the `data` folder and database,
4. start the app and open **http://127.0.0.1:8877** in your browser.

Keep the black window open while you use the app; press **Ctrl+C** in it to stop.

### macOS / Linux

```bash
chmod +x run.sh    # first time only
./run.sh
```

It does the same four steps. On Ubuntu/Debian you may first need `sudo apt install python3 python3-venv`.

### Manual start (any system)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py              # add --no-browser to skip opening a tab, --port 8878 for another port
```

Optional configuration lives in `.env` — copy `.env.example` to `.env` and edit it. Every value is optional.

---

## Adding products

Open **Add Product**. There are three ways in:

| Method | Best for |
|---|---|
| **Smart paste** | One product you are looking at on Amazon right now. |
| **Manual entry** | Products from a supplier list, Keepa or your own notes. |
| **Bulk import** | Many products at once from CSV, Excel or copied spreadsheet rows. |

The form is grouped into *Identity*, *Amazon market data*, *Sourcing and costs*, *Fulfilment, size and fees*,
*Restrictions and risk* and *Notes*. A **Live estimate** panel beside the form recalculates fees, profit, ROI
and the likely status as you type — nothing is saved until you press **Save product**.

To identify a product you need at least an **ASIN, title or Amazon URL**. To fully evaluate it you also need the
selling price, sourcing price, BSR, estimated monthly sales, total sellers, FBA sellers, and — for FBA — the
packaged weight (or the exact FBA fee from Seller Central). Anything you leave out is listed as missing.

### Duplicates

Before saving, the app looks for an existing product with the **same ASIN**; if there is no ASIN, the **same
Amazon URL**; if there is neither, the **same title and brand**. If it finds one you choose:

- **Update existing product** — copies the new values onto it (blank fields keep their current values),
- **Create duplicate anyway** — for example the same ASIN from a different supplier,
- **Cancel** — nothing is saved.

Bulk import offers the same choice for all matching rows (skip, update or create).

### Bulk import

1. **Add Product → Bulk import**, choose a `.csv` / `.xlsx` file or paste rows including the heading row.
2. The preview matches your column headings automatically (e.g. “Cost”, “Sales Rank”, “Buy Box” are recognised).
   Fix any column in the *Import as* dropdowns.
3. Every row is validated like the form. Rows with problems are listed with the reason and are **not imported**.
4. Press **Import**. Everything is saved in one transaction — if anything fails, nothing is saved.

Download the **Excel or CSV template** from the import page; its *Instructions* and *Fee categories* sheets
explain every column. Up to 5,000 rows and 10 MB per import.

### Editing, duplicating, archiving, deleting

Every product page has **Edit**, **Re-evaluate**, **Duplicate** (e.g. to compare suppliers), **Archive** (hide
without deleting) and **Delete** (asks for confirmation; cannot be undone). The products table supports the
same actions for several selected rows at once.

---

## How Smart Paste works

1. On the Amazon UK product page press **Ctrl+A**, then **Ctrl+C**.
2. Paste into the Smart Paste box and press **Extract details**. For seller counts, also copy the
   **“Other sellers on Amazon”** offers list and paste it too.
3. The form fills in and shows the banner **“Auto extracted — please verify.”** Each filled field has a badge
   with its confidence and the text it came from.
4. Check everything, add your costs, and save.

What it looks for (the parser is `opportunity_finder/parsers/amazon_text.py`):

| Field | Recognised from |
|---|---|
| ASIN | `ASIN: B0…`, `/dp/B0…` links, stand-alone `B0XXXXXXXX` codes (warns if several differ) |
| Price | Every `£` amount. Each is scored from its context: “Price”, “Buy new” and discount lines score up; RRP / “Was”, unit prices (`£2.67 / count`), delivery charges, vouchers and “from £” offers score down. **All prices are shown**; the most likely is pre-filled and you are asked to verify it. |
| Best Sellers Rank and category | `Best Sellers Rank: 3,456 in Home & Kitchen`, `#1,234 in …`; sub-category ranks are listed |
| Brand | `Brand: …`, the product-information table, `Visit the … Store`; `Manufacturer` as a low-confidence fallback |
| Title | The page title, or the line just above the brand / rating line |
| Sellers | Only from offers text: `Sold by` / `Dispatches from` pairs (counts distinct sellers; FBA = dispatched by Amazon; Amazon itself counts as a seller but not as an FBA seller), or Amazon's `New (6) from £…` count at low confidence. **FBA sellers are never inferred from the product page alone.** |
| Amazon sells the listing | `Sold by Amazon` |
| Monthly sales | `1K+ bought in past month` — labelled as a rounded lower bound |
| Weight and size | `Package Dimensions: 24.5 x 17 x 13.5 cm; 1.02 kg`, `Item Weight` (converted to g/cm) |

If the text is malformed, non-UK (`$` / `€` only, amazon.com links) or empty, you get a clear warning and an
empty or partial form — never a crash and never invented values.

---

## Qualification rules and statuses

Default rules (all editable in **Settings**):

| Rule | Default |
|---|---|
| Total sellers | ≥ 3 |
| FBA sellers | ≥ 1 |
| Best Sellers Rank | < 25,000 |
| Estimated monthly sales | ≥ 50 |
| Net profit per unit | > £0.00 |
| ROI | ≥ 0% |

Every product gets exactly one status, decided in this order:

| Status | Meaning |
|---|---|
| **✕ Rejected** | At least one rule fails with the data entered. The page lists each failure, e.g. *“BSR 42,831 exceeds maximum 25,000”*. |
| **? Incomplete Data** | No rule fails, but a value needed by a rule is missing. Nothing is guessed. |
| **▲ High Risk** | Every rule passes, but the risk engine scored it HIGH. |
| **! Needs Verification** | Every rule passes and risk is not high, but something must be checked: a £0 sourcing price, Amazon data older than 30 days (setting), or — if you switch it on — an unverified restriction status. |
| **✓ Qualified** | Passes every rule, risk is LOW or MEDIUM, nothing to verify. |

Statuses always use a symbol and a word as well as a colour.

---

## How profit is calculated

Per unit:

```
Net profit = Amazon selling price
           − Sourcing price
           − Referral fee
           − FBA fee
           − Shipping / prep
           − Other costs
           (− fuel surcharge, dangerous-goods fee, digital services fee and VAT, when they apply)

ROI %        = Net profit ÷ Sourcing price × 100
Net margin % = Net profit ÷ Selling price × 100
```

Per month (all **estimated**):

```
Theoretical monthly revenue = Estimated monthly sales × Selling price
Theoretical monthly profit  = Estimated monthly sales × Net profit
Conservative units          = floor(Estimated monthly sales × Capture rate)
Conservative monthly profit = Conservative units × Net profit
Monthly stock investment    = Conservative units × (Sourcing + Shipping/prep + Other costs)
```

Blank shipping/prep or other costs count as £0 and are noted on the product page. With a £0 sourcing price ROI
cannot be calculated, so the product needs verification. The product page also shows the **highest sourcing
price that still meets your minimum profit and ROI** — useful when negotiating with a supplier.

### The conservative sales model

You will not win every sale on a listing, so the app uses an editable **capture rate**:

| FBA sellers | Default capture rate |
|---|---|
| fewer than 5 | 20% |
| 5 – 9 | 10% |
| 10 or more | 5% |

When **Amazon sells the listing**, the capture rate is multiplied by 50% by default (Amazon usually wins most of
the Buy Box). All thresholds and rates are in Settings.

**Worked example** (default settings, 13 Sep 2026): price £24.99, sourcing £8.00, shipping £0.50, 20×15×8 cm,
400 g, 300 sales a month, 3 FBA sellers → referral £3.75 + FBA £3.04 + fuel £0.05 + digital services fee £0.14 =
fees £6.98 → **net profit £9.51**, **ROI 118.9%** → 20% capture = **60 units** → **£570.60 conservative monthly
profit** (£2,853.00 theoretical). This exact case is a unit test.

---

## Amazon UK fees

All fees are **estimates**. *Confirm exact fees in Amazon Seller Central Revenue Calculator before purchasing stock.*

The fee table is data, not code: `opportunity_finder/fees/uk_fee_table.json` (version `uk-2026-07`). It holds:

- **Referral fees** for 52 UK categories — flat rates, whole-price bands (e.g. Beauty 8% up to £10, 15% above)
  and portion bands (e.g. Furniture 15% of the first £175, 10% of the rest), with the £0.25 minimum where it applies.
  Pick the category in the product form; it defaults to *Everything else (15%)*.
- **FBA fulfilment fees** from Amazon's rate card effective **1 July 2026** (UK column): envelope, parcel and
  oversize tiers by size and weight, using dimensional weight (L×W×H ÷ 5,000) where Amazon does.
- **Low-Price FBA** rates for items priced £20 or less (£10 in some categories), when they fit the size limits.
- The **selected-category parcel table** (clothing, footwear, grocery and others) with its per-100 g steps.
- **Festive peak** parcel fees (15 October – 14 January).
- **Surcharges:** 1.5% fuel and logistics surcharge on FBA fees (from 17 April 2026), £0.10 dangerous-goods /
  lithium-battery fee, and Amazon's **2% digital services fee** on selling and FBA fees for UK-established sellers.

If only the weight is known, the size tier is estimated from weight alone (the largest parcel tier for that
weight — deliberately conservative) and the product page says so. If you have the exact numbers from Seller
Central, enter them under **“I have the exact fees from Seller Central”**; they replace the estimates.

**VAT** (Settings → Fees and VAT): *Ignore VAT* (the plain formula, default), *Not VAT registered* (adds 20% VAT
on Amazon's fees, which you can't reclaim) or *VAT registered* (deducts output VAT — price ÷ 6 — from each sale;
enter sourcing costs excluding VAT).

**Not included:** storage, inbound placement, returns processing, low-inventory fees, advertising, and media closing fees.

**Updating fees:** edit the JSON file (rates, bands, dates, surcharges), bump `version`, restart the app. Every
product is re-evaluated automatically because the table version is part of each evaluation's fingerprint.

---

## What "estimated" means

The app separates **RAW** data (what you entered or pasted from Amazon: price, BSR, sellers) from **ESTIMATED**
values (fees, monthly sales, capture rate, conservative units, conservative and theoretical profit, score).
Estimated values carry an **EST** tag everywhere — on screen, in the Excel column headings and in the Summary
sheet. They are assumptions for comparing opportunities, not forecasts or promises of income.

---

## Risk scoring

A transparent points system (`opportunity_finder/services/risk_engine.py`). Every factor that fires is shown
with its points on the product page.

| Factor | Points |
|---|---|
| Product restricted / gated | +45 — **forces HIGH** |
| Possible IP / trademark concern | +45 — **forces HIGH** |
| Hazmat / dangerous goods | +25 |
| Amazon sells this listing | +25 |
| Too many FBA sellers (≥ high-competition threshold) | +20 |
| Contains a battery | +15 |
| Low ROI (below 15%, setting) | +15 |
| Missing critical data | +15 |
| Moderate FBA competition | +10 |
| Thin net margin (below 10%, setting) | +10 |
| Restriction status not verified | +10 |
| Liquid · Fragile · Seasonal | +10 each |

**HIGH** at 40+ points (or any forcing factor), **MEDIUM** at 20+, otherwise **LOW**.
Example: a possible IP concern, Amazon on the listing and ROI of 9.4% → *HIGH RISK — Possible IP concern;
Amazon sells this listing; ROI only 9.4%*.

---

## Opportunity Score and ranking

Qualified products are ranked by a 0–100 score built from six published components
(`opportunity_finder/services/ranking.py`):

| Component | Max | Full points at |
|---|---|---|
| ROI | 25 | 50% ROI or more |
| Net profit per unit | 20 | £10 or more |
| Conservative monthly profit | 20 | a quarter of your monthly target |
| Estimated monthly sales | 15 | 500 a month or more |
| Competition | 10 | 1–2 FBA sellers (8 below medium, 5 medium, 2 high, 0 well above high; −5 if Amazon sells) |
| Risk | 10 | LOW 10, MEDIUM 5, HIGH 0 |

Each product page shows its own points per component. Ties are broken by ROI, then profit per unit, then
conservative monthly profit, then sales.

---

## Target profit plan

Default target: **£1,000 conservative monthly profit** (Settings). On **Opportunities** the app walks down the
ranking and adds each qualified product's conservative monthly profit until the running total reaches the target:

```
Target: £1,000/month
1. Product A   £320   running £320
2. Product B   £280   running £600
3. Product C   £240   running £840
4. Product D   £210   running £1,050
Projected conservative total: £1,050      Target achieved: YES
```

It also shows the shortfall when the target isn't reachable and the monthly stock investment the plan needs.
High Risk products are never included; Needs Verification products only if you switch that on. **Estimated —
not guaranteed income.**

---

## Excel and CSV export

**Export Excel** (dashboard, products table, opportunities, or selected rows) creates a workbook with:

| Sheet | Contents |
|---|---|
| **Qualified** | Rank, score, ASIN, product, brand, category, price, BSR, sellers, FBA sellers, estimated sales, sourcing price, supplier, referral fee, FBA fee, surcharges, total fees, shipping/prep, other costs, net profit, ROI, capture rate, conservative units and profit, theoretical profit, restriction status, risk and reasons, *included in target plan*, source URL, checked date |
| **Rejected** | The same core columns plus *Rejected because* |
| **Incomplete** | Identity and known data plus *Missing data* |
| **Summary** | Counts by status, conservative and theoretical profit, target, target achieved, plan total, stock investment, date generated, fee table version |
| **Needs Review** | High Risk and Needs Verification products with reasons |
| **Target Plan** | The selected products with running totals |
| **Assumptions** | Every setting and the fee table sources used for the export |

Formatting: bold dark header row, frozen panes, filters, sensible widths, £ and % number formats, dates, and
coloured risk / status / plan cells (with the text as well). Estimated columns end in “(EST)”. Text that starts
with `=`, `+`, `-` or `@` is escaped so a pasted title can't run as a spreadsheet formula.

The products table also exports the current filtered view — or selected rows — to **CSV**.

---

## Settings

Everything that affects a result is editable, validated on the server and stored in the database:

- **Qualification rules** — minimum sellers, FBA sellers, maximum BSR, minimum monthly sales, profit and ROI.
- **Monthly profit target** — and whether Needs Verification products may join the plan.
- **Conservative sales model** — capture rates, competition thresholds, the Amazon-on-listing adjustment.
- **Risk and verification** — low-ROI and thin-margin thresholds, stale-data days, require a restriction check.
- **Fees and VAT** — VAT treatment, digital services fee, fuel surcharge, Low-Price FBA, peak fees.

Saving re-evaluates every product immediately. **Reset to defaults** restores the values above.

---

## Your data: database, history and backups

- **Database:** `data/opportunity_finder.db` (SQLite) next to `app.py`. Change the folder with `AOF_DATA_DIR`.
  Tables: `products`, `settings`, `product_snapshots`, `evaluations`, `meta` (schema version / migrations).
- **Logs:** `data/logs/app.log`. If something goes wrong the page shows a short reference code that appears in the log.
- **History:** each product records created, last edited, last evaluated and *Amazon data last checked* dates; a
  snapshot of price, BSR, sellers, FBA sellers, sales and sourcing price whenever they change; and each change in
  status, risk, score or profit. Changing a market value updates “Amazon data last checked” automatically — or
  tick *“I re-checked the Amazon data just now”* when editing.
- **Backups:** Settings → *Download a backup* saves a copy of the database. *Restore backup* checks the file is a
  real backup, keeps a safety copy of your current data in `data/backups`, then restores.

---

## Privacy and security

- Listens on **127.0.0.1** only, so other devices can't reach it. (Changing `AOF_HOST` prints a warning.)
- **No login** is needed; instead every form is protected by a CSRF token and requests with a foreign `Host`
  header are refused, so other web pages open in your browser can't operate the app.
- A strict Content-Security-Policy: no external scripts, fonts or trackers. No data is sent to any external service.
- `SECRET_KEY` comes from the environment, or is generated once and stored in `data/secret_key`. No secrets are in the code.
- Backend validation on every input — the browser checks are only a convenience.

---

## Project structure

```
amazon-opportunity-finder/
├── app.py                     start the server (python app.py [--port N] [--no-browser] [--init-only])
├── config.py                  settings from environment / .env
├── run.bat, run.sh            one-click start
├── requirements.txt           Flask, openpyxl, waitress, python-dotenv (all pure Python)
├── .env.example
├── docs/FAILURES.md           every bug found, its measurement, and the checklist it became
├── opportunity_finder/
│   ├── app_factory.py         Flask app, logging, template helpers, error pages
│   ├── security.py            CSRF, Host check, security headers
│   ├── constants.py           statuses, labels, risk flags — one vocabulary for UI, export and tests
│   ├── domain/                Product and Settings models (+ settings validation)
│   ├── fees/                  engine.py + uk_fee_table.json
│   ├── parsers/amazon_text.py Smart Paste parser
│   ├── providers/             base.py interface, manual.py, keepa.py (disabled stub)
│   ├── services/              calculator, qualification, risk_engine, ranking, target_plan, evaluator,
│   │                          validation, duplicates, product_service, product_query,
│   │                          import_service, excel_export, backup
│   ├── database/              db.py (schema + migrations), repositories.py (all SQL)
│   ├── routes/                dashboard, products, opportunities, imports, settings, exports, api
│   ├── templates/             Jinja pages
│   └── static/                css/app.css, js/app.js (progressive enhancement only)
└── tests/                     pytest suites, fixtures, e2e/smoke.mjs browser test
```

Data providers are separate from calculations: routes turn provider output into a `Product`, and the evaluator
only ever sees a `Product` — it doesn't know whether the data came from you, a paste, a spreadsheet or Keepa.

---

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

198 tests cover fee estimation, profit and ROI, capture rates, qualification, missing-data handling, risk, score,
ranking, the target plan, the Smart Paste parser, validation, duplicates, settings persistence, history, bulk
import, Excel/CSV export, backups and every page and workflow through the Flask test client (including CSRF,
friendly error pages and restart persistence).

**Browser smoke test** (optional, uses your installed Microsoft Edge — no browser download):

```bash
AOF_DATA_DIR=./e2e-data python app.py --port 8878 --no-browser     # a scratch copy, in another terminal
cd tests/e2e && npm install && node smoke.mjs                      # E2E_CHANNEL=chrome to use Chrome
```

It adds products via Smart Paste and the form, checks duplicate handling, validation, bulk import, search,
sorting, bulk actions and the confirm dialog, deletion, settings persistence and Excel download, checks that
no page scrolls sideways at phone width, and saves screenshots to `tests/e2e/screenshots`.

---

## Future Keepa integration

Version 1 needs no Keepa account. The integration point is ready:

1. `opportunity_finder/providers/base.py` defines `DataProvider.fetch(asin) -> ProviderResult` (field values,
   raw/estimated provenance, optional history).
2. `opportunity_finder/providers/keepa.py` is a **disabled stub**. Its `FIELD_MAP` documents how Keepa's product
   response maps to our fields (Buy Box price, sales rank, new-offer count, FBA offers, `monthlySold`, package
   size and weight, and the price/rank/offer-count history arrays).
3. To implement it: set `KEEPA_API_KEY` and `AOF_ENABLE_KEEPA=1` in `.env`, implement `KeepaProvider.fetch` with
   Keepa's product endpoint for the UK domain (`domain=2`), and add a route that calls it and saves the result
   through `ProductService.merge(...)` exactly as a bulk-import row is saved. Evaluation, history snapshots,
   duplicates and exports then work unchanged. The `product_snapshots` table is ready to store imported history.

Until then the Settings page shows Keepa as *Off*, and nothing is sent anywhere.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| **“Python 3.11 or newer was not found”** | Install Python from python.org and tick *Add python.exe to PATH*, then run `run.bat` again. |
| **“Port 8877 is already in use”** | The app is probably already running — open http://127.0.0.1:8877. Or start on another port: `python app.py --port 8878`, or set `AOF_PORT` in `.env`. |
| **Installing requirements fails** | Check your internet connection; behind a proxy set `HTTPS_PROXY`. Delete `.venv` and run the script again. |
| **The browser didn't open** | Open http://127.0.0.1:8877 yourself. `AOF_OPEN_BROWSER=0` in `.env` turns auto-open off. |
| **“Your page was open too long…”** | The form's security token expired (e.g. after restoring a backup or restarting with a new key). Reload the page and try again. |
| **Smart Paste found nothing** | Copy the whole Amazon UK page (Ctrl+A, Ctrl+C), not just the title. Seller counts need the “Other sellers on Amazon” list. You can always type values yourself. |
| **A product is “Incomplete Data”** | Open it — the page lists exactly which values are missing. *Rejected → Incomplete data* shows all of them. |
| **Fees look different from Seller Central** | Pick the right referral fee category, add packaged dimensions, or enter the exact fees under “I have the exact fees from Seller Central”. Check `uk_fee_table.json` is current. |
| **Something went wrong (with a reference code)** | Your data is safe. Search `data/logs/app.log` for the code. |
| **Start fresh** | Stop the app, move or delete the `data` folder, start again. (Download a backup first.) |

---

## Known limitations

- **Fees are estimates** from the July 2026 UK rate card and referral table. Amazon changes fees; storage,
  inbound placement, returns, low-inventory and advertising costs are not included. Some referral bands
  (e.g. Automotive) are simplified — always confirm in the Revenue Calculator.
- **Smart Paste depends on Amazon's page wording.** If Amazon changes its layout, some fields may stop being
  extracted; nothing is ever invented, you just type those values in.
- **Monthly sales are your estimate.** The app has no sales-rank-to-sales model; “bought in past month” is a lower bound.
- **UK marketplace only**, in GBP.
- **Single user, local.** There is no multi-user access or login by design.
- `run.sh` was syntax-checked but not executed on macOS/Linux during development (the build machine is Windows).
