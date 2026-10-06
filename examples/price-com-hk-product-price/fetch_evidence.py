#!/usr/bin/env python3
"""Fetch price.com.hk search + product quotes and write Jev request JSON files.

Does not call Jev. Product query/specs come from CLI (no hardcoded model).
Stdlib only.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
HK = ZoneInfo("Asia/Hong_Kong")
SEARCH_URL = "https://www.price.com.hk/search.php"
PRODUCT_URL = "https://www.price.com.hk/product.php"


def fetch(url: str, timeout: float = 25.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as error:
        raise RuntimeError(
            f"HTTP fetch failed for {url}: {error}. "
            "price.com.hk may present a Cloudflare challenge; pass --search-html / --product-html "
            "from a browser session, or use run.py after saving page HTML."
        ) from error


def read_html(path: Path | None, url: str | None, timeout: float) -> str:
    if path is not None:
        return path.read_text(encoding="utf-8", errors="replace")
    if not url:
        raise ValueError("url or html path required")
    return fetch(url, timeout=timeout)


def yesterday_hkt(as_of: date | None = None) -> date:
    today = as_of or datetime.now(HK).date()
    return today - timedelta(days=1)


def split_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in re.split(r"[,|]+", raw) if t.strip()]


def parse_search_products(html: str) -> list[dict]:
    products: list[dict] = []
    seen: set[str] = set()
    for match in re.finditer(r'data-add-compare-name="([^"]+)"', html):
        name = html_lib.unescape(match.group(1)).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        window = html[max(0, match.start() - 1200) : match.start() + 1600]
        pid_match = re.search(r"product\.php\?p=(\d+)", window)
        prices = [float(p) for p in re.findall(r'data-price="([\d.]+)"', window)[:4]]
        products.append(
            {
                "name": name,
                "product_id": pid_match.group(1) if pid_match else None,
                "listed_prices_hkd": prices,
            }
        )
    return products


def parse_product_quotes(html: str) -> list[dict]:
    quotes: list[dict] = []
    for item in re.split(r'<div class="item clearfix">', html)[1:]:
        name_match = re.search(
            r'class="quotation-merchant-name"[\s\S]*?<a[^>]*>(.*?)</a>',
            item,
        )
        if not name_match:
            continue
        merchant = html_lib.unescape(re.sub(r"<[^>]+>", "", name_match.group(1))).strip()
        date_match = re.search(r"<div>(20\d{2}-\d{2}-\d{2})</div>", item)
        price_match = re.search(
            r'class="product-price[^"]*"[\s\S]*?data-price="([\d.]+)"',
            item,
        ) or re.search(r'data-price="([\d.]+)"', item)
        if "hong_20.png" in item:
            channel = "行貨"
        elif "water_20.png" in item:
            channel = "水貨"
        else:
            channel = "unknown"
        qd_match = re.search(r"tr_qd=(\d{8})", item)
        quotes.append(
            {
                "merchant": merchant,
                "update_date": date_match.group(1) if date_match else None,
                "price_hkd": float(price_match.group(1)) if price_match else None,
                "channel": channel,
                "tr_qd": qd_match.group(1) if qd_match else None,
            }
        )
    return quotes


def parse_price_trend(html: str) -> dict | None:
    match = re.search(r"priceTrendData = jQuery\.parseJSON\('(\{.*?\})'\)", html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def build_navigate_request(
    products: list[dict],
    *,
    query: str,
    must_include: list[str],
    must_exclude: list[str],
    target_hint: str | None,
    retrieved: str,
) -> dict:
    candidates = {}
    criteria = {}
    for index, product in enumerate(products[:12], start=1):
        cid = f"p{index}"
        candidates[cid] = product
        criteria[cid] = (
            f"Open product_id={product.get('product_id')} named {product['name']} "
            f"(listed {product.get('listed_prices_hkd')})."
        )
    criteria["none"] = "No observed search hit matches the user product intent."

    intent = {
        "search_query": query,
        "must_include_in_name": must_include,
        "must_exclude_from_name": must_exclude,
        "preferred_exact_name": target_hint,
    }
    include_txt = ", ".join(must_include) if must_include else "(none)"
    exclude_txt = ", ".join(must_exclude) if must_exclude else "(none)"
    hint_txt = target_hint or "(none)"

    return {
        "model": "typesafe/jev-1.13",
        "state": {
            "goal": (
                f"From price.com.hk search results for {query!r}, open the single best-matching "
                "product page for the user's intended product/specs. Prefer exact preferred name when "
                "supplied; otherwise match must_include tokens and reject must_exclude distractors "
                "(e.g. wrong capacity, Pro Max vs Pro, wrong generation)."
            ),
            "source": {
                "site": "https://www.price.com.hk/",
                "search_url": f"{SEARCH_URL}?g=A&q={urllib.parse.quote(query)}",
                "retrieved": retrieved,
                "timezone": "Asia/Hong_Kong",
            },
            "user_intent": intent,
            "permissions": "Read-only navigation and price reading; no purchase, login, or messaging merchants.",
            "search_hits": candidates,
        },
        "questions": {
            "open_product": {
                "type": "choice",
                "instructions": (
                    "Choose the search hit in state.search_hits that best matches state.user_intent. "
                    f"Preferred exact name: {hint_txt}. "
                    f"Name should include all of: {include_txt}. "
                    f"Reject hits whose name contains any of: {exclude_txt}. "
                    "If several remain, pick the closest retail product match to the search query. "
                    "Choose none if nothing fits."
                ),
                "criteria": criteria,
            }
        },
    }


def build_price_request(
    quotes: list[dict],
    *,
    product: dict,
    query: str,
    as_of_yesterday: str,
    retrieved: str,
    trend: dict | None,
) -> dict:
    candidates = {}
    criteria = {}
    for index, quote in enumerate(quotes, start=1):
        cid = f"q{index}"
        candidates[cid] = quote
        criteria[cid] = (
            f"{quote.get('merchant')}: HK${quote.get('price_hkd')} "
            f"{quote.get('channel')} updated {quote.get('update_date')}"
        )
    criteria["none"] = "No quote is eligible for the as-of-yesterday rule."

    product_name = product.get("name") or query
    trend_tail = None
    if trend:
        trend_tail = {
            "hong_last": (trend.get("H") or [])[-5:],
            "water_last": [row for row in (trend.get("W") or []) if row.get("y")][-5:],
        }

    return {
        "model": "typesafe/jev-1.13",
        "state": {
            "goal": (
                f"Report the latest merchant list price on price.com.hk for {product_name} "
                f"as of yesterday ({as_of_yesterday} Asia/Hong_Kong): among quotes whose update_date "
                "equals yesterday, select the lowest listed HKD price (最平報價 for that day)."
            ),
            "source": {
                "site": "https://www.price.com.hk/",
                "search_query": query,
                "product_url": f"{PRODUCT_URL}?p={product.get('product_id')}",
                "product_id": product.get("product_id"),
                "product_name": product_name,
                "retrieved": retrieved,
                "timezone": "Asia/Hong_Kong",
            },
            "as_of_policy": {
                "yesterday": as_of_yesterday,
                "eligible_quote_rule": "quote.update_date == yesterday",
                "selection_rule": "lowest price_hkd among eligible quotes",
                "exclude": [
                    "Quotes updated today or earlier than yesterday",
                    "Wrong product variants already rejected at navigation",
                    "Do not invent prices absent from state.quotes",
                ],
            },
            "price_history_chart_tail": trend_tail,
            "quotes": candidates,
            "permissions": "Read-only; no purchase or merchant contact.",
        },
        "questions": {
            "quote_is_as_of_yesterday_eligible": {
                "type": "noul",
                "instructions": (
                    "Is there at least one quote in state.quotes whose update_date equals "
                    "state.as_of_policy.yesterday and that has a numeric price_hkd?"
                ),
                "criteria": {
                    "true": "One or more quotes are dated yesterday with a listed HKD price.",
                    "false": "No yesterday-dated quote with a listed price is present.",
                },
            },
            "lowest_price_quote_as_of_yesterday": {
                "type": "choice",
                "instructions": (
                    "Using only state.quotes and state.as_of_policy, choose the candidate id of the "
                    "eligible yesterday quote with the lowest price_hkd. If several share that price, "
                    "prefer 行貨 over 水貨/unknown, then the earlier candidate id. Choose none if no quote qualifies."
                ),
                "criteria": criteria,
            },
            "evidence_enough_to_report_price": {
                "type": "noul",
                "instructions": (
                    f"Is the supplied product identity plus yesterday-dated quote list sufficient to report "
                    f"a single HKD list price for {product_name} as of yesterday without browsing further?"
                ),
                "criteria": {
                    "true": "Product is identified and at least one eligible yesterday quote exists.",
                    "false": "Product mismatch, missing dates, or no usable yesterday quote.",
                },
            },
        },
    }


def collect_search(
    query: str,
    *,
    must_include: list[str],
    must_exclude: list[str],
    target_hint: str | None,
    as_of_yesterday: str,
    timeout: float = 25.0,
    search_html_path: Path | None = None,
) -> dict:
    retrieved = datetime.now(timezone.utc).astimezone(HK).strftime("%Y-%m-%dT%H:%M%z")
    search_url = f"{SEARCH_URL}?g=A&q={urllib.parse.quote(query)}"
    search_html = read_html(search_html_path, search_url, timeout)
    products = parse_search_products(search_html)
    navigate_request = build_navigate_request(
        products,
        query=query,
        must_include=must_include,
        must_exclude=must_exclude,
        target_hint=target_hint,
        retrieved=retrieved,
    )
    return {
        "retrieved": retrieved,
        "as_of_yesterday": as_of_yesterday,
        "search_url": search_url,
        "query": query,
        "must_include": must_include,
        "must_exclude": must_exclude,
        "target_hint": target_hint,
        "search_hits": products,
        "navigate_request": navigate_request,
    }


def collect_product_quotes(
    product: dict,
    *,
    query: str,
    as_of_yesterday: str,
    retrieved: str,
    timeout: float = 25.0,
    product_html_path: Path | None = None,
) -> dict:
    product_url = f"{PRODUCT_URL}?p={product['product_id']}"
    product_html = read_html(product_html_path, product_url, timeout)
    quotes = parse_product_quotes(product_html)
    trend = parse_price_trend(product_html)
    price_request = build_price_request(
        quotes,
        product=product,
        query=query,
        as_of_yesterday=as_of_yesterday,
        retrieved=retrieved,
        trend=trend,
    )
    eligible = [
        q
        for q in quotes
        if q.get("update_date") == as_of_yesterday and isinstance(q.get("price_hkd"), (int, float))
    ]
    lowest = min(eligible, key=lambda q: q["price_hkd"]) if eligible else None
    return {
        "product": product,
        "quotes": quotes,
        "price_request": price_request,
        "eligible_yesterday_quotes": eligible,
        "deterministic_lowest_yesterday": lowest,
        "price_history_chart_tail": price_request["state"]["price_history_chart_tail"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch price.com.hk evidence for a user-specified product (Jev request JSON only)."
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Search text, e.g. 'iPhone 18 Pro 256GB' or 'Sony WH-1000XM5'",
    )
    parser.add_argument("--query", dest="query_flag", default=None, help="Same as positional query.")
    parser.add_argument(
        "--must-include",
        default="",
        help="Comma-separated name tokens that should match (e.g. '256GB,Pro').",
    )
    parser.add_argument(
        "--must-exclude",
        default="",
        help="Comma-separated name tokens to reject (e.g. 'Max').",
    )
    parser.add_argument(
        "--target-name",
        default=None,
        help="Optional preferred exact product title hint for Jev (not used to hard-pick).",
    )
    parser.add_argument(
        "--product-id",
        default=None,
        help="Optional: skip search and fetch this product.php?p= id directly for quote request only.",
    )
    parser.add_argument(
        "--as-of-yesterday",
        default=None,
        help="YYYY-MM-DD override for yesterday (default: prior calendar day in Asia/Hong_Kong).",
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--search-html", type=Path, default=None, help="Saved search.php HTML (CF bypass).")
    parser.add_argument("--product-html", type=Path, default=None, help="Saved product.php HTML (CF bypass).")
    args = parser.parse_args()

    query = args.query_flag or args.query
    if not query and not args.product_id:
        raise SystemExit("Provide a product search query, e.g. fetch_evidence.py 'iPhone 18 Pro 256GB'")

    as_of_yesterday = args.as_of_yesterday or yesterday_hkt().isoformat()
    must_include = split_tokens(args.must_include)
    must_exclude = split_tokens(args.must_exclude)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.product_id:
        retrieved = datetime.now(timezone.utc).astimezone(HK).strftime("%Y-%m-%dT%H:%M%z")
        product = {"name": args.target_name or query or f"product {args.product_id}", "product_id": args.product_id}
        packed = collect_product_quotes(
            product,
            query=query or product["name"],
            as_of_yesterday=as_of_yesterday,
            retrieved=retrieved,
            timeout=args.timeout,
            product_html_path=args.product_html,
        )
        nav = None
        search_bundle = {
            "retrieved": retrieved,
            "as_of_yesterday": as_of_yesterday,
            "search_url": None,
            "query": query,
            "search_hits": [],
        }
    else:
        search_bundle = collect_search(
            query,
            must_include=must_include,
            must_exclude=must_exclude,
            target_hint=args.target_name,
            as_of_yesterday=as_of_yesterday,
            timeout=args.timeout,
            search_html_path=args.search_html,
        )
        nav = search_bundle["navigate_request"]
        # Write navigate request; product quotes need a Jev (or --product-id) choice.
        # For fetch-only convenience, also materialize quotes for the first hit that
        # satisfies include/exclude filters when possible (host should prefer run.py + Jev).
        products = search_bundle["search_hits"]
        filtered = []
        for p in products:
            name = p.get("name") or ""
            if must_include and not all(tok.lower() in name.lower() for tok in must_include):
                continue
            if must_exclude and any(tok.lower() in name.lower() for tok in must_exclude):
                continue
            filtered.append(p)
        preview = filtered[0] if filtered else (products[0] if products else None)
        if not preview or not preview.get("product_id"):
            raise SystemExit(f"no search hits for {query!r}: {products[:6]}")
        packed = collect_product_quotes(
            preview,
            query=query,
            as_of_yesterday=as_of_yesterday,
            retrieved=search_bundle["retrieved"],
            timeout=args.timeout,
            product_html_path=args.product_html,
        )
        packed["preview_note"] = (
            "Quotes preview uses first include/exclude-filtered hit; "
            "run.py lets Jev choose the product before quoting."
        )

    nav_path = args.out_dir / "navigate_request.json"
    price_path = args.out_dir / "request.json"
    evidence_path = args.out_dir / "evidence.json"
    if nav is not None:
        nav_path.write_text(json.dumps(nav, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    price_path.write_text(json.dumps(packed["price_request"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence = {
        **{k: search_bundle[k] for k in ("retrieved", "as_of_yesterday", "search_url", "query") if k in search_bundle},
        "must_include": must_include,
        "must_exclude": must_exclude,
        "target_hint": args.target_name,
        "search_hits": search_bundle.get("search_hits", []),
        "product": packed["product"],
        "quotes": packed["quotes"],
        "eligible_yesterday_quotes": packed["eligible_yesterday_quotes"],
        "deterministic_lowest_yesterday": packed["deterministic_lowest_yesterday"],
        "price_history_chart_tail": packed["price_history_chart_tail"],
        "preview_note": packed.get("preview_note"),
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "wrote": [str(p) for p in (nav_path if nav else None, price_path, evidence_path) if p],
        "query": query,
        "product_id": packed["product"].get("product_id"),
        "product_name": packed["product"].get("name"),
        "as_of_yesterday": as_of_yesterday,
        "eligible_count": len(packed["eligible_yesterday_quotes"]),
        "deterministic_lowest_yesterday": packed["deterministic_lowest_yesterday"],
        "preview_note": packed.get("preview_note"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
