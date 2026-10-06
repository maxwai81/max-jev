# price.com.hk product price (Jev only)

Flexible price lookup: user supplies a **product name/specs** → host searches price.com.hk → **Jev picks the product hit** → host opens quotes → **Jev picks the lowest yesterday-dated merchant price** (HKT).

No chat-LLM comparison path. Uses the existing Jev skill CLI.

## Decision contract

| Part | Choice |
|---|---|
| Decision | Which search hit matches the user intent, and which yesterday-dated quote is the lowest HKD list price? |
| Unit / evidence | Live HTML from `search.php` + `product.php` (merchant, `update_date`, `price_hkd`, channel) |
| Questions | Navigate: 1× `choice`. Price: 2× `noul` + 1× `choice` |
| Consumer | Host opens the selected product URL; reports selected quote HKD / merchant |
| Unknown path | `none` if no hit matches intent, or no quote dated yesterday |
| Success check | `run.py` dry-run validates; live Jev selects product + yesterday quote |

## User inputs

| Flag | Meaning |
|---|---|
| `query` (positional) | Search text, e.g. `iPhone 18 Pro 256GB` |
| `--must-include` | Comma-separated name tokens that should match |
| `--must-exclude` | Comma-separated distractors to reject (e.g. `Max`) |
| `--target-name` | Optional preferred exact title hint for Jev |
| `--as-of-yesterday` | Pin the HKT “yesterday” date (`YYYY-MM-DD`) |

## As-of-yesterday rule

- Timezone: `Asia/Hong_Kong`
- Eligible quotes: `update_date == yesterday`
- Selected price: lowest `price_hkd` among eligible (行貨 preferred on ties)

## Run (Jev end-to-end)

Cloudflare always blocks direct HTTP. Save the search page and the Jev-selected product page from a browser, then:

```bash
python3 examples/price-com-hk-product-price/run.py 'iPhone 18 Pro 256GB' \
  --must-include '18 Pro,256' --must-exclude 'Max' \
  --search-html /tmp/pricehk_search.html \
  --product-html /tmp/pricehk_product.html \
  --as-of-yesterday 2026-10-01
```

`run.py` without `--search-html` exits immediately. With search HTML only, Jev picks a product and exits `3` with `need_product_html` plus `product_url` so the product page can be saved before the price call.

Validate only:

```bash
python3 examples/price-com-hk-product-price/run.py 'iPhone 18 Pro 256GB' --dry-run \
  --search-html /tmp/pricehk_search.html
```

Evidence builders only (no Jev; prefer `run.py` so Jev chooses the product):

```bash
python3 examples/price-com-hk-product-price/fetch_evidence.py 'iPhone 18 Pro 256GB' \
  --must-include '18 Pro,256' --must-exclude 'Max' \
  --search-html /tmp/pricehk_search.html --product-html /tmp/pricehk_product.html
```

## Files

- `run.py` — fetch → Jev navigate → fetch quotes → Jev price → `report.json`
- `fetch_evidence.py` — HTTP parse + request builders (shared)
- `navigate_request.json` / `request.json` — last Jev inputs
- `result-navigate.json` / `result.json` — last Jev outputs
- `evidence.json` / `report.json` — parsed evidence + summary
