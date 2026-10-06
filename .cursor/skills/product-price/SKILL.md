---
name: product-price
description: >-
  Look up the latest Hong Kong merchant price on price.com.hk for a product
  the user names. Use when the user says product-price, asks for a Price.com.hk
  price, or wants yesterday's lowest quote for a product name or specs.
---

# product-price

The user supplies a **product name** (and optional specs in the same phrase). Do not ask for CLI flags. Run the existing Jev use case and report the price.

Repo root is the directory that contains `examples/price-com-hk-product-price/run.py`.

## Inputs you derive

From the product phrase only:

- **query**: the phrase as given (this is the price.com.hk search).
- **`--must-include`**: distinctive tokens that must appear in the listing title (capacity such as `256GB`, model codes). Skip generic words like brand-only if they match everything.
- **`--must-exclude`**: only an obvious sibling the user did not ask for. Example: `Pro` without `Max` → exclude `Max`. Otherwise omit the flag and let Jev reject distractors.
- **`--as-of-yesterday`**: omit unless the user names a date. The script uses the prior calendar day in Asia/Hong_Kong.
- **`--target-name`**: omit unless the user gives an exact listing title.

## Run

Cloudflare always blocks direct HTTP to price.com.hk. Never call `run.py` or `fetch_evidence.py` without saved page HTML. Do not ask the user to save it.

Need `OPENROUTER_API_KEY` in the environment. Never print it. This task already uses real Jev on OpenRouter (`--provider openrouter`). Do not ask again to choose a provider. Pass system `python3` for the script and `--python "$HOME/.local/bin/python3.12"` for the Jev CLI.

## Browser steps

Use `jev-ui` for any browser step whose next control is not already a known URL. That replaces a long host-model planning turn with one typed decision over the fresh snapshot.

Open these URLs directly. Do not ask Jev which address to load:

- Search: `https://www.price.com.hk/search.php?g=A&q=URL_ENCODED_QUERY`
- Product: the `product_url` from `need_product_html`

For everything else on the page (cookie or login wall, wrong results tab, language, pagination, or a product link when the id is not yet known), follow `jev-ui`:

1. Snapshot the page. Candidates are only controls you just observed.
2. One `choice` request, `--provider openrouter`, with goal, snapshot id, element ids, and a `blocked` or `wait` fallback.
3. Execute only that step, then read the new page. Do not plan the click after that from the old snapshot.

Include any `jev-ui` call’s latency and cost in the reply, next to the navigate and price calls.

1. Open the search URL in the browser.
2. Save `document.documentElement.outerHTML` to `/tmp/pricehk_search.html`.
3. Run with `--search-html` only. Exit code 3 and `status: need_product_html` means Jev picked a product. Open `product_url`, save HTML to `/tmp/pricehk_product.html`.
4. Re-run with both `--search-html` and `--product-html`.

```bash
python3 examples/price-com-hk-product-price/run.py 'PRODUCT NAME' \
  --must-include 'token1,token2' \
  --must-exclude 'sibling' \
  --search-html /tmp/pricehk_search.html \
  --product-html /tmp/pricehk_product.html \
  --python "$HOME/.local/bin/python3.12"
```

Drop `--must-include` or `--must-exclude` when you have nothing to put there. Omit `--product-html` on the first call.

Read `report.json` plus `result-navigate.json` and `result.json` for `response.usage` and `elapsed_seconds`.

## Reply

Always use this order. The price comes last.

### Jev settings

- Model (`typesafe/jev-1.13`), provider, and policy (`min_probability`, `min_margin`).
- Navigate: question id, type, and the intent used (query, must-include, must-exclude, as-of date).
- Price: the three question ids and types, plus the yesterday rule (eligible date, lowest HKD, 行貨 on ties).

### Jev decisions

For each question: status, value, probability, and margin when present. Say what the chosen id is (product name / merchant and price).

Then latency and cost for each Jev call that ran (`jev-ui` steps, navigate, price) and the total (`elapsed_seconds`, `response.usage.cost`, input/output tokens).

### Price

Matched product, as-of date, merchant, channel, and HKD amount.
