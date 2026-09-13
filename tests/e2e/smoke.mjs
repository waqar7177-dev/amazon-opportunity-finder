// Browser smoke test for Amazon UK Opportunity Finder.
//
//   cd tests/e2e && npm install && node smoke.mjs
//
// Uses playwright-core with the installed Microsoft Edge (or Chrome: E2E_CHANNEL=chrome), so no
// browser download is needed. Run it against a SCRATCH copy of the app, e.g.
//   AOF_DATA_DIR=./e2e-data python app.py --port 8878 --no-browser
// because it creates, edits and deletes products.
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.AOF_URL || "http://127.0.0.1:8878";
const SHOTS = process.env.E2E_SHOTS || path.join(here, "screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const consoleErrors = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok: Boolean(ok), detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
};

const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || "msedge", headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
const page = await context.newPage();
// The app answers a form with problems using HTTP 422 (validation) or 409 (possible duplicate) and
// re-renders it; browsers log those statuses as console "errors". They are intended, so skip them.
const INTENDED_STATUS = /Failed to load resource: the server responded with a status of (409|422)/;
page.on("console", (msg) => {
  if (msg.type() === "error" && !INTENDED_STATUS.test(msg.text())) consoleErrors.push(`${page.url()} :: ${msg.text()}`);
});
page.on("pageerror", (err) => consoleErrors.push(`${page.url()} :: ${err.message}`));
page.on("dialog", (dialog) => dialog.accept());

const shot = (name, target = page) => target.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
const toastText = async () => (await page.locator(".toast").allInnerTexts()).join(" | ");

try {
  // ------------------------------------------------------------ dashboard
  await page.goto(`${BASE}/`);
  check("dashboard loads", await page.locator("h1", { hasText: "Find Winning Products" }).isVisible());
  check("dashboard has the brand input", await page.locator("#brand").isVisible() && await page.locator("button:has-text('Analyze Brand')").first().isVisible());
  check("brand box has the cursor on load", await page.evaluate(() => document.activeElement && document.activeElement.id === "brand"));
  await shot("01-dashboard-empty");
  await page.goto(`${BASE}/products`);
  await page.keyboard.press("Tab");
  check("first Tab reaches the skip link", await page.evaluate(() => document.activeElement.classList.contains("skip")));

  // ------------------------------------------------------------ smart paste
  const fixture = fs.readFileSync(path.join(here, "..", "fixtures", "amazon_product_page.txt"), "utf8");
  await page.goto(`${BASE}/products/new`);
  await page.fill("#pasted_text", fixture);
  await page.click("button:has-text('Extract details')");
  await page.waitForSelector("text=Auto extracted — please verify.");
  check("smart paste extracts ASIN", (await page.inputValue("#f-asin")) === "B0TESTAB12");
  check("smart paste suggests price", (await page.inputValue("#f-selling_price")) === "23.99");
  check("several price candidates offered", (await page.locator(".cand").count()) >= 3);
  await page.locator(".cand").nth(1).click();
  const clickedPrice = await page.inputValue("#f-selling_price");
  await page.locator(".cand").first().click();
  check("price candidate buttons fill the field", clickedPrice !== "23.99" && (await page.inputValue("#f-selling_price")) === "23.99");
  await page.fill("#f-sourcing_price", "7.20");
  await page.fill("#f-fba_sellers", "3");
  await page.fill("#f-total_sellers", "6");
  await page.check("input[name=restriction_status][value=ungated]");
  // Wait for the estimate to catch up with the fields just typed (it is debounced).
  await page.waitForFunction(() => {
    const badge = document.querySelector("[data-live-body] .badge");
    return badge && !badge.textContent.includes("Incomplete");
  }, null, { timeout: 8000 });
  const liveStatus = (await page.locator("[data-live-body] .badge").first().innerText()).replace(/\s+/g, " ");
  check("live estimate updates to a full evaluation", /Qualified|Needs Verification|High Risk|Rejected/.test(liveStatus), liveStatus);
  await shot("02-add-smart-paste");
  await page.click("button:has-text('Save product')");
  await page.waitForURL(/\/products\/\d+$/);
  check("saved product opens its detail page", await page.locator("h2", { hasText: "Profit breakdown" }).isVisible());
  check("detail shows why it passed or failed", await page.locator("#why-h").isVisible(), await page.locator("#why-h").innerText());
  check("fee disclaimer shown", (await page.content()).includes("Confirm exact fees in Amazon Seller Central Revenue Calculator before purchasing stock."));
  await shot("03-product-detail");

  // --------------------------------------------------- manual + duplicates
  await page.goto(`${BASE}/products/new?method=manual`);
  const manual = { asin: "B0MANUAL01", title: "Stainless kettle 1.7L", brand: "Boilwell", selling_price: "34.99", bsr: "42831",
    monthly_sales: "34", total_sellers: "5", fba_sellers: "2", sourcing_price: "14.00", weight_g: "1500", length_cm: "25", width_cm: "20", height_cm: "22" };
  for (const [k, v] of Object.entries(manual)) await page.fill(`#f-${k}`, v);
  await page.click("button:has-text('Save product')");
  await page.waitForURL(/\/products\/\d+$/);
  const whyText = await page.locator(".why").innerText();
  check("manual product rejected with reasons", whyText.includes("BSR 42,831 exceeds maximum 25,000") && whyText.includes("Monthly sales 34 below minimum 50"), whyText.replace(/\n/g, " / "));

  await page.goto(`${BASE}/products/new?method=manual`);
  for (const [k, v] of Object.entries({ ...manual, selling_price: "36.50" })) await page.fill(`#f-${k}`, v);
  await page.click("button:has-text('Save product')");
  await page.waitForSelector("text=This looks like a product you already have");
  check("duplicate ASIN detected before saving", true);
  await shot("04-duplicate-panel");
  await page.click("button:has-text('Update existing product')");
  await page.waitForURL(/\/products\/\d+$/);
  check("update existing keeps one product", (await page.content()).includes("£36.50"));

  // ------------------------------------------------------------ validation
  await page.goto(`${BASE}/products/new?method=manual`);
  await page.fill("#f-title", "Bad data");
  await page.fill("#f-selling_price", "-4");
  await page.fill("#f-total_sellers", "2.5");
  await page.click("button:has-text('Save product')");
  await page.waitForSelector("[data-error-summary]");
  check("backend validation errors shown", (await page.content()).includes("cannot be negative") && (await page.content()).includes("whole number"));
  await shot("05-validation-errors");

  // ------------------------------------------------------------ bulk import
  const csvPath = path.join(os.tmpdir(), "aof-e2e-import.csv");
  fs.writeFileSync(csvPath, [
    "ASIN,Title,Brand,Amazon Price,Sales Rank,Monthly Sales,Sellers,FBA Sellers,Cost,Shipping,Weight (g),Length (cm),Width (cm),Height (cm),Restriction",
    "B0IMPORTE1,Bamboo cutting board set,Woodly,21.99,3200,420,7,4,6.10,0.40,900,38,28,4,ungated",
    "B0IMPORTE2,LED desk lamp,Brightly,29.99,11800,160,4,2,11.50,0.60,1100,40,20,12,ungated",
    "B0IMPORTE3,Silicone baking mats,Bakewise,12.99,7600,380,9,6,3.20,0.30,300,30,22,3,unknown",
    "B0IMPORTE4,Broken row,Nope,-1,abc,,,,,,,,,,",
    "B0IMPORTE5,Travel mug,Sippy,15.99,,,,,4.10,,350,20,10,10,",
  ].join("\n"));
  await page.goto(`${BASE}/import`);
  await page.setInputFiles("input[name=file]", csvPath);
  await page.click("button:has-text('Preview import')");
  await page.waitForSelector("text=Check your import");
  check("import preview lists problems", (await page.content()).includes("cannot be negative"));
  await page.locator("[data-row-filter] button[data-filter=invalid]").click();
  check("row filter hides valid rows", (await page.locator("tr[data-action-row=import]:visible").count()) === 0);
  await shot("06-import-preview");
  await page.click("button:has-text('Import')");
  await page.waitForSelector("text=Import finished");
  check("import finished with a report", (await page.locator(".kpi .value").first().innerText()) === "4");
  await shot("07-import-result");

  // ------------------------------------------------------------ products list
  await page.goto(`${BASE}/products`);
  const rows = await page.locator("table.products-table tbody tr").count();
  check("products table lists products", rows >= 6, `${rows} rows`);
  await page.fill("#q", "lamp");
  await page.click("button:has-text('Apply')");
  check("search filters the table", (await page.locator("table.products-table tbody tr").count()) === 1);
  await page.goto(`${BASE}/products?sort=roi&dir=desc`);
  check("sort by ROI works", (await page.locator("th[aria-sort=descending]").innerText()).includes("ROI"));
  await page.check("[data-select-all]");
  check("bulk bar activates on selection", await page.locator(".bulkbar.active").isVisible());
  await page.click(".bulkbar button:has-text('Delete')");
  await page.waitForSelector("#confirm-modal[open]");
  check("delete asks for confirmation", await page.locator("#confirm-text").isVisible());
  await shot("08-confirm-modal");
  await page.click("#confirm-modal button:has-text('Cancel')");
  check("cancel keeps products", (await page.locator("table.products-table tbody tr").count()) === rows);
  await shot("09-products-list");

  // ------------------------------------------------------------ delete one
  await page.goto(`${BASE}/products?q=Travel`);
  await page.locator("a.product-link").first().click();
  await page.waitForURL(/\/products\/\d+$/);
  check("incomplete import shows missing data", (await page.locator("#why-h").innerText()).includes("Incomplete"));
  await page.click(".actions button:has-text('Delete')");
  await page.waitForSelector("#confirm-modal[open]");
  await page.click("#confirm-ok");
  await page.waitForURL(/\/products$/);
  check("delete via modal works", (await toastText()).includes("Deleted"));

  // ------------------------------------------------------------ settings
  await page.goto(`${BASE}/settings`);
  await page.fill("#f-max_bsr", "50000");
  await page.click("button:has-text('Save settings')");
  await page.waitForSelector(".toast.ok");
  await page.reload();
  check("settings persist", (await page.inputValue("#f-max_bsr")) === "50000");
  await shot("10-settings");
  await page.goto(`${BASE}/rejected`);
  check("rule change re-evaluates products", !(await page.content()).includes("BSR 42,831 exceeds maximum"));
  await page.goto(`${BASE}/settings`);
  await page.click("button:has-text('Reset to defaults')");
  await page.click("#confirm-ok");
  await page.waitForSelector(".toast.ok");
  check("reset restores defaults", (await page.inputValue("#f-max_bsr")) === "25000");

  // ------------------------------------------------------------ pages + export
  await page.goto(`${BASE}/`);
  await shot("11-dashboard");
  await page.goto(`${BASE}/opportunities`);
  check("opportunities page shows the plan", await page.locator("#plan-h").isVisible());
  await shot("12-opportunities");
  await page.goto(`${BASE}/rejected`);
  await shot("13-rejected");
  await page.goto(`${BASE}/products`);
  const [download] = await Promise.all([page.waitForEvent("download"), page.click(".page-head a:has-text('Excel')")]);
  const xlsx = path.join(os.tmpdir(), download.suggestedFilename());
  await download.saveAs(xlsx);
  const head = fs.readFileSync(xlsx).subarray(0, 2).toString();
  check("Excel export downloads a workbook", head === "PK" && download.suggestedFilename().endsWith(".xlsx"), download.suggestedFilename());

  // ------------------------------------------------------------ mobile layout
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const m = await mobile.newPage();
  m.on("pageerror", (err) => consoleErrors.push(`mobile ${m.url()} :: ${err.message}`));
  const firstProduct = await page.locator("a.product-link").first().getAttribute("href");
  for (const [name, url] of [["dashboard", "/"], ["products", "/products"], ["add", "/products/new?method=manual"],
    ["detail", firstProduct], ["opportunities", "/opportunities"], ["rejected", "/rejected"], ["import", "/import"], ["settings", "/settings"],
    ["brands", "/brands"], ["supplier prices", "/supplier-prices"], ["skip list", "/rejected?tab=history"]]) {
    await m.goto(`${BASE}${url}`);
    const overflow = await m.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check(`mobile ${name}: no sideways page scroll`, overflow <= 1, `${overflow}px`);
    if (["dashboard", "products", "detail", "add"].includes(name)) await shot(`m-${name}`, m);
  }
  await mobile.close();
} catch (err) {
  check("smoke run completed without an exception", false, err.message.split("\n")[0]);
  await shot("zz-failure").catch(() => {});
} finally {
  await browser.close();
}

check("no JavaScript console errors", consoleErrors.length === 0, consoleErrors.slice(0, 5).join(" || "));
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed. Screenshots: ${SHOTS}`);
process.exit(failed.length ? 1 : 0);
