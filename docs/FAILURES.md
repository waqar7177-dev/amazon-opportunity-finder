# Failures log

**Hard rule:** every fault goes in this file *as part of fixing it*, in the same commit as the fix —
not later, not when asked. Each entry has four parts: what broke, the measurement, why nothing
caught it, and the checklist line it becomes.

## Pre-commit checklist

Ask these before committing. Each line came from a real fault below.

1. Can every input that may legitimately be missing actually be *omitted* when the object is built — not just set to `None` by callers who happen to know? *(F1)*
2. Does any new template filter, global or helper name collide with a built-in of the library it is registered into (Jinja: `int`, `round`, `list`, `default`, `format`…)? *(F2)*
3. Is every name a template macro uses a Jinja *global* or a macro argument — not a context-processor variable? And is each page tested with real data, not only empty? *(F3)*
4. When a test helper forwards `**overrides`, can an override collide with a keyword the helper already passes? *(F4)*
5. Does a template read a dict key that is also a dict method name (`update`, `items`, `keys`, `values`, `get`, `pop`, `copy`)? Use `d['key']`. *(F5)*
6. When a test asserts that text is *absent* from a page, could a flash message or other carried-over UI contain that text? *(F6)*
7. Does test data for a search or filter test contain the search term in *any* searchable field (brand, supplier, notes), not just the one you meant? *(F7)*
8. Have you looked at a screenshot of every changed page, at desktop and phone width — not only asserted that its text is present? *(F8)*
9. Before a test flags browser console output as an error, is that output a consequence of behaviour the app does on purpose? *(F9)*
10. Is every address or port shown to the user read from the same configuration the server uses — not typed a second time into a script or message? *(F10)*
11. Does a brand-new database run every migration, or only an existing one? Test both paths. *(F11)*
12. When a scripted find-and-replace edits a template, does the pattern occur exactly once? *(F12)*
13. Can two workers (a thread and a direct call, or two threads) pick up the same job? Claim jobs atomically. *(F13)*
14. When a user-typed name maps to a stored record, does every later use read the stored value, not the typed one? *(F14)*
15. In a template, does a filter written after `a or b` apply to the whole expression? Parenthesise: `(a or b)|filter`. *(F15)*
16. Is a relevance or matching rule checked against real data, including look-alikes (another brand's product line with the same word)? *(F16)*
17. When a fix tightens a rule, have you re-run it on the real cases the old rule got *right*? *(F17)*

---

## F1 — Fee engine could not represent "no selling price"

- **What broke:** `FeeInputs` declared `selling_price` without a default, so building fee inputs for
  a product whose Amazon price is unknown raised a `TypeError` instead of producing a
  "selling price missing" result. The app's core promise — missing values are reported, never
  guessed — had no way to express the most important missing value at the fee layer.
- **Measurement:** 2026-09-13, first run of the test suite: 99 of 100 tests passed;
  `test_missing_price_means_no_referral_fee` failed with
  `TypeError: FeeInputs.__init__() missing 1 required positional argument: 'selling_price'`.
  The evaluator path hid it because `fee_inputs_for()` always passes the attribute (as `None`).
- **Why nothing caught it:** the only earlier check was a smoke run with a complete product, and
  every internal caller passes all fields by keyword. The gap only shows when the dataclass is
  used the way a future provider (e.g. Keepa) would use it — with just the fields it knows.
- **Fix:** `selling_price: float | None = None`.
- **Checklist line:** 1.

## F2 — App filter `int` silently replaced Jinja's built-in `int`

- **What broke:** the Settings page returned a 500 error. The app registered its number formatter as
  the Jinja filter `int` (so `{{ n|int }}` printed "1,234"). Jinja accepted it without warning and
  replaced the built-in `int` filter for every template, so the Settings example text
  `values.competition_medium_from|int - 1` evaluated `"5" - 1`.
- **Measurement:** 2026-09-13, first run of `tests/test_routes.py`: 131 tests passed, then
  `test_every_page_renders_when_empty[/settings]` got HTTP 500 instead of 200 with
  `TypeError: unsupported operand type(s) for -: 'str' and 'int'` at `settings.html` line 49.
- **Why nothing caught it:** every other `|int` use was display-only, where a formatted string looks
  exactly right, and `jinja_env.filters.update()` gives no signal that a name already existed. It only
  failed where a template did arithmetic on the result.
- **Fix:** the formatter is now `|whole`; the app factory raises at start-up if any custom filter name
  already exists in `jinja_env.filters`, so a future clash fails on the first request of any test.
- **Checklist line:** 2.

## F3 — Status and risk badges crashed every page that showed a product

- **What broke:** the product list, detail, dashboard, opportunities, rejected and import pages all
  returned HTTP 500 as soon as one product existed. The badge macros in `_macros.html` read `C`
  (statuses, labels, tones), which was supplied by a Flask context processor — and macros imported
  with `{% from "_macros.html" import … %}` do not receive the template context.
- **Measurement:** 2026-09-13, second test run: 187 passed, 10 route tests failed with
  `jinja2.exceptions.UndefinedError: 'C' is undefined` at `_macros.html` line 12 (`risk_badge`), while
  all ten empty-page render tests passed.
- **Why nothing caught it:** the empty-state pages never call a badge macro, so "every page renders"
  was only true with zero products. The unit tests never render templates.
- **Fix:** `C`, `APP_NAME` and `APP_VERSION` are registered in `jinja_env.globals`; only the per-request
  `active` nav key stays in the context processor (used by `base.html`, never by a macro).
- **Checklist line:** 3.

## F4 — Route test helper passed `CSRF_ENABLED` twice

- **What broke:** `test_csrf_and_host_checks` could not build its app:
  `TypeError: config.Config() got multiple values for keyword argument 'CSRF_ENABLED'`.
- **Measurement:** same run as F3 — the 11th failure; the CSRF and Host protections were therefore
  untested at that point.
- **Why nothing caught it:** it was the only caller that overrode a key the helper already hard-codes.
- **Fix:** the helper merges its defaults with `**overrides` into one dict before calling `Config`.
- **Checklist line:** 4.

## F5 — Import preview crashed: `counts.update` is a method, not the count

- **What broke:** the bulk-import preview page returned HTTP 500 for every upload. `Preview.counts` is a
  dict with keys `import`, `update`, `skip`, `invalid`; in Jinja `counts.update` resolves to the dict's
  built-in `update` method before the key, so `counts.import + counts.update` added an int to a method.
- **Measurement:** 2026-09-13, third test run: 195 passed, `test_import_preview_and_confirm` failed with
  `TypeError: unsupported operand type(s) for +: 'int' and 'builtin_function_or_method'` at
  `imports/preview.html` line 116.
- **Why nothing caught it:** `counts.import`, `counts.skip` and `counts.invalid` all worked, so the
  pattern looked proven; only the one key that shares a name with a dict method failed, and only on
  the arithmetic line (printing it would have shown `<built-in method update…>` rather than crashing).
- **Fix:** the template uses `counts['update']` / `counts['import']`; grep of all templates found no other
  dict-method-named key lookups.
- **Checklist line:** 5.

## F6 — Two route tests read leftover "Saved …" toasts as page content

- **What broke:** `test_search_filter_sort_paginate` and `test_bulk_archive_and_delete` failed because the
  filtered page still contained a product name that the filter had correctly removed.
- **Measurement:** same run as F5. The names came from flash toasts ("Saved “Route test kettle” —
  Qualified.") queued by the earlier POSTs; the test client doesn't follow redirects, so every queued
  toast rendered on the first GET — the filtered list.
- **Why nothing caught it:** tests that assert *presence* pass with extra text on the page; only
  *absence* assertions are sensitive to carried-over UI.
- **Fix:** a `settle(client)` helper renders one page to drain pending toasts before absence checks. The
  app behaviour (toasts after redirect) is correct and unchanged.
- **Checklist line:** 6.

## F7 — Search test used a term that every test product's brand contains

- **What broke:** `test_search_filter_sort_paginate` expected a search for "kettle" to exclude "Risky mug".
  The app was right to include it: search covers ASIN, title, brand, supplier, category and notes, and
  the shared test fixture gives every product the brand "Kettleco".
- **Measurement:** 2026-09-13, fourth test run: 197 passed, 1 failed — the failure output showed
  `<a class="product-link" href="/products/3">Risky mug</a>` in the results for `?q=kettle`.
- **Why nothing caught it:** the term was chosen by looking at titles only; the brand came from a shared
  default dict defined far from the test.
- **Fix:** the test searches "route test", which appears only in the intended title.
- **Checklist line:** 7.

## F8 — Key figures on the product page ran into their notes

- **What broke:** in the detail page's metric strip each value and its note were inline spans, so they
  printed as one run-on string.
- **Measurement:** 2026-09-13 15:52 desktop screenshot `03-product-detail.png` showed "£974.00100 units",
  "135.3%margin 40.6%" and "88/100#1 of 1 qualified"; the 390 px screenshot `m-detail.png` showed
  "£751.8084 units". The route test for that page passed — it only checks that "£9.51" is present.
- **Why nothing caught it:** text-presence assertions cannot see layout; the first visual review was the
  first time anyone looked at the page.
- **Fix:** `.metric .value` and `.metric .note` are `display:block`.
- **Checklist line:** 8.

## F9 — Smoke test counted the app's intended 409/422 responses as console errors

- **What broke:** the browser smoke test's "no JavaScript console errors" check failed (38/39).
- **Measurement:** 2026-09-13 15:52 run: two console entries, both "Failed to load resource: the server
  responded with a status of 409 (CONFLICT)" and "…422 (UNPROCESSABLE ENTITY)" on `/products/new` — the
  duplicate panel and the validation re-render, which answer with those statuses by design.
- **Why nothing caught it:** Edge logs any 4xx document response as a console error, even for a normal
  form re-render; the check treated every console error as a JavaScript fault.
- **Fix:** the smoke test ignores exactly those two resource-status messages; real JavaScript errors
  (`pageerror` and other console errors) still fail it.
- **Checklist line:** 9.

## F10 — `run.bat` announced port 8877 while the app was on another port

- **What broke:** step 4 of `run.bat` printed a hard-coded "Starting the app at http://127.0.0.1:8877", and
  `run.sh` printed `${AOF_PORT:-8877}`. Neither reads `.env`, so anyone who changed the port was told the wrong
  address (`run.sh` was right only when the port came from the shell environment).
- **Measurement:** 2026-09-13, fresh-install test from a clean `git clone` with `AOF_PORT=8879`: the run log
  said "[4/4] Starting the app at http://127.0.0.1:8877" while `/health` answered 200 on 8879 and nothing
  listened for it on 8877. The Python banner with the real address did not appear in the redirected log
  because stdout was block-buffered.
- **Why nothing caught it:** every earlier run used the default port, where the duplicated number happens to match.
- **Fix:** both scripts say "open the address shown below"; `app.py` prints its banner (built from `Config`)
  with `flush=True` so it appears immediately even when output is redirected.
- **Checklist line:** 10.

## F11 — New databases skipped the version 2 migration

- **What broke:** after adding schema v2 (brand research), every new database crashed on the first product
  insert. `init_db` stamped a brand-new database with `SCHEMA_VERSION` — now 2 — right after creating the v1
  tables, so migration 2 (the new columns and tables) never ran. Existing v1 databases migrated correctly.
- **Measurement:** 2026-09-13, first test run after the change: 31 failed, 169 passed; e.g.
  `test_update_notes_only_keeps_checked_date_and_snapshot` → `sqlite3.OperationalError: table products has no
  column named availability`. The user's real database (v1, 0 products) would have been fine; every fresh
  install would not.
- **Why nothing caught it:** with only one schema version the shortcut was harmless; the bug appeared the
  moment a second version existed, and only for the fresh-install path.
- **Fix:** a new database is stamped version 1 (what `SCHEMA_V1` creates) and then receives every migration.
- **Checklist line:** 11.

## F12 — Template edit broke the Rejected page title

- **What broke:** adding the "Skip list" tab wrapped the page in `{% if %}…{% endif %}` by replacing
  `{% endblock %}` with `{% endif %}{% endblock %}` — but the title block also ends with `{% endblock %}`, so the
  title became `Rejected &amp; incomplete{% endif %}`, a template syntax error.
- **Measurement:** 2026-09-13, seen in the saved diff of `rejected.html` line 3 immediately after the edit,
  before any test run.
- **Why nothing caught it:** the scripted edit asserted the *tab* marker occurred once but not the second pattern.
- **Fix:** restored the title block; only the final `{% endblock %}` carries the new `{% endif %}`.
- **Checklist line:** 12.

## F13 — Research tests ran every search twice at the same time

- **What broke:** `ResearchRunner.start()` wakes a background worker thread; the tests then also called
  `run_pending()` directly, so each search ran in two threads at once. Nothing stopped a second worker from
  taking a search that was already running.
- **Measurement:** 2026-09-13, same run as F11 after the fix: 5 failed, 187 passed. `B0BRIGHT02` was reported
  `skipped_rejected` in its *first* search (the other worker had just rejected it);
  `sqlite3.IntegrityError: UNIQUE constraint failed: brand_search_items.search_id, brand_search_items.asin`;
  a cancelled search finished as `completed`.
- **Why nothing caught it:** in the app only one worker thread exists, so the race never showed there; the
  tests were the first code with two workers.
- **Fix:** tests build the runner with `background=False`; `run_pending` now claims a search with
  `UPDATE … SET status='running' WHERE id=? AND status='queued'` and skips it if another worker got there first.
- **Checklist line:** 13.

## F14 — "Analyze again" searched with whatever capitalisation was typed

- **What broke:** brands are matched case-insensitively ("brightnest" finds the stored brand "Brightnest"), but the
  new search stored the text exactly as typed as its query. The same brand could be searched and reported under
  several spellings, and a report headline showed the lowercase text.
- **Measurement:** 2026-09-13 test run: 227 passed, 3 failed; `test_analyze_brand_end_to_end` — the second search,
  started as "brightnest", requested `https://www.amazon.co.uk/s?k=brightnest` while the brand record was "Brightnest".
- **Why nothing caught it:** every earlier test typed the brand with identical capitalisation.
- **Fix:** `ResearchRunner.start` uses the stored brand name as the search query.
- **Checklist line:** 14.

## F15 — Brand report showed the start time as a raw timestamp

- **What broke:** the report header printed "Started 2026-09-13T19:08:48". In `{{ search.started_at or search.created_at|datetime }}`
  the filter binds to `search.created_at` only, so whenever `started_at` was set the raw ISO string was shown.
- **Measurement:** 2026-09-13 19:14, screenshot `live-progress.png` of the real Aero search on the test server.
- **Why nothing caught it:** route tests check report content, not date formatting; the first real screenshot showed it.
- **Fix:** `(search.started_at or search.created_at)|datetime`; a grep of all templates found no other `or …|filter` expression.
- **Checklist line:** 15.

## F16 — Another brand's product line was analyzed as the searched brand

- **What broke:** the real Aero search (1 page, 47 title matches) listed "UniBond AERO 360° Moisture Absorber Neutral
  Refill" under *Sourcing cost required* as an Aero product. Its listing brand is UniBond; "AERO 360" is its product line.
  The relevance rule accepted a different listed brand whenever the search word was among the title's first three words —
  meant for sub-brands such as "Nestlé Aero", but it cannot tell those from look-alikes.
- **Measurement:** 2026-09-13 19:14, search 1 on the test server at 27/47 products: the report showed the UniBond listing
  with price and BSR in the Aero results; the same run correctly set aside "Nestlé Big Chocolate Box 30 Bars" (brand Nestlé)
  because "Aero" was not in its first three words.
- **Why nothing caught it:** the fixture's look-alike ("Replacement Lids compatible with Brightnest") had the brand word late in
  the title, so the first-three-words exception was never exercised by a false positive.
- **Fix:** a listing whose own brand field names a different brand is *Not this brand*, unless the brand field itself contains the
  searched brand as a whole word ("Nestlé Aero"). The same check now runs when a stored product is reused on a later search.
  New test: `test_product_line_of_another_brand_is_not_the_brand`.
- **Checklist line:** 16.

## F17 — The F16 fix would have excluded a genuine Aero product

- **What broke:** F16's rule ("a different brand field means not this brand") was checked against the look-alike that
  prompted it, but not against the real rows the old rule handled correctly. "Aero Peppermint Milk Chocolate Giant
  Gifting Bar, 295g" is listed under the manufacturer's company name "Nestlé Česko s.r.o." — genuine Aero, which the
  F16 rule would have dropped as *Not this brand*.
- **Measurement:** 2026-09-13 19:22, the F16 rule applied to the stored rows of real search 1: `B0FH56Z5XC` (brand
  "Nestlé Česko s.r.o.", title "Aero Peppermint …") → `brand_mismatch`; `B01LCHCRQO` UniBond AERO 360 → `brand_mismatch`
  (correct); `B0G4XCBQKX` "Manhattan Aero 4K TV Streamer" (brand Manhattan) → `brand_mismatch` (correct).
- **Why nothing caught it:** the F16 test only covered look-alikes, not a real brand product listed under its maker.
- **Fix:** Amazon titles lead with the brand. If the title starts with the listed brand ("UniBond AERO…", "Manhattan Aero…")
  it is not the brand; if it starts with the searched brand while the listing names another company, it is accepted as
  *brand uncertain* (flagged on the product's brand field); anything else is not the brand. New tests cover all six real patterns.
- **Checklist line:** 17.
