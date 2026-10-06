#!/usr/bin/env python3
"""End-to-end price.com.hk lookup: fetch → Jev navigate → fetch quotes → Jev price.

Jev-only. No chat-LLM comparison path.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from fetch_evidence import (
    ROOT,
    collect_product_quotes,
    collect_search,
    split_tokens,
    yesterday_hkt,
)

REPO = ROOT.parents[1]
JEV_PY = REPO / ".cursor" / "skills" / "jev" / "scripts" / "jev.py"
DEFAULT_PYTHON = Path(sys.executable)


def run_jev(request: dict, *, out_path: Path, provider: str, python: Path, dry_run: bool = False) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(request, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    cmd = [str(python), str(JEV_PY), "decide", str(tmp_path), "--provider", provider]
    if dry_run:
        cmd.append("--dry-run")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    finally:
        tmp_path.unlink(missing_ok=True)
    if dry_run:
        if proc.returncode != 0:
            raise SystemExit(f"jev dry-run failed ({proc.returncode}): {proc.stderr or proc.stdout}")
        return {"dry_run": True, "stdout": proc.stdout}
    if proc.returncode not in (0, 2):
        raise SystemExit(f"jev decide failed ({proc.returncode}): {proc.stderr or proc.stdout}")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"jev output was not JSON: {error}\n{proc.stdout[:500]}") from error
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def decision_value(result: dict, qid: str):
    dec = (result.get("decisions") or {}).get(qid) or {}
    return dec.get("value"), dec


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search price.com.hk for a user product and use Jev for navigate + yesterday price."
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Product search text, e.g. 'iPhone 18 Pro 256GB'",
    )
    parser.add_argument("--query", dest="query_flag", default=None)
    parser.add_argument("--must-include", default="", help="Comma-separated required name tokens.")
    parser.add_argument("--must-exclude", default="", help="Comma-separated rejected name tokens.")
    parser.add_argument("--target-name", default=None, help="Optional preferred exact product title.")
    parser.add_argument("--as-of-yesterday", default=None, help="YYYY-MM-DD (HKT yesterday override).")
    parser.add_argument("--provider", default="openrouter", choices=("openrouter", "typesafe"))
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--out-dir", type=Path, default=ROOT)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--dry-run", action="store_true", help="Validate Jev requests only.")
    parser.add_argument("--search-html", type=Path, default=None, help="Saved search.php HTML if HTTP is blocked.")
    parser.add_argument(
        "--product-html",
        type=Path,
        default=None,
        help="Saved product.php HTML used after Jev selects that product id.",
    )
    args = parser.parse_args()

    query = args.query_flag or args.query
    if not query:
        raise SystemExit("Usage: run.py 'PRODUCT NAME / SPECS' [--must-include ...] [--must-exclude ...]")

    if args.search_html is None:
        raise SystemExit(
            "Cloudflare always blocks direct HTTP to price.com.hk. "
            "Open the search page in a browser, save document.documentElement.outerHTML, "
            "and pass --search-html."
        )

    as_of_yesterday = args.as_of_yesterday or yesterday_hkt().isoformat()
    must_include = split_tokens(args.must_include)
    must_exclude = split_tokens(args.must_exclude)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    search = collect_search(
        query,
        must_include=must_include,
        must_exclude=must_exclude,
        target_hint=args.target_name,
        as_of_yesterday=as_of_yesterday,
        timeout=args.timeout,
        search_html_path=args.search_html,
    )
    nav_req = search["navigate_request"]
    (args.out_dir / "navigate_request.json").write_text(
        json.dumps(nav_req, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if not search["search_hits"]:
        raise SystemExit(f"No search hits for {query!r} at {search['search_url']}")

    nav_result = run_jev(
        nav_req,
        out_path=args.out_dir / "result-navigate.json",
        provider=args.provider,
        python=args.python,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        if args.product_html is None:
            print(json.dumps({"dry_run": True, "query": query, "hits": len(search["search_hits"]), "navigate_only": True}, indent=2))
            return 0
        preview = search["search_hits"][0]
        packed = collect_product_quotes(
            preview,
            query=query,
            as_of_yesterday=as_of_yesterday,
            retrieved=search["retrieved"],
            timeout=args.timeout,
            product_html_path=args.product_html,
        )
        (args.out_dir / "request.json").write_text(
            json.dumps(packed["price_request"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        run_jev(
            packed["price_request"],
            out_path=args.out_dir / "result.json",
            provider=args.provider,
            python=args.python,
            dry_run=True,
        )
        print(json.dumps({"dry_run": True, "query": query, "hits": len(search["search_hits"])}, indent=2))
        return 0

    chosen_id, nav_dec = decision_value(nav_result, "open_product")
    if chosen_id in (None, "none") or nav_dec.get("status") == "needs_review":
        raise SystemExit(f"Jev did not select a product to open: {nav_dec}")

    product = nav_req["state"]["search_hits"].get(chosen_id)
    if not product or not product.get("product_id"):
        raise SystemExit(f"Selected {chosen_id} missing from search_hits")

    if args.product_html is None:
        print(json.dumps({
            "status": "need_product_html",
            "open_product": chosen_id,
            "product_id": product["product_id"],
            "product_name": product.get("name"),
            "product_url": f"https://www.price.com.hk/product.php?p={product['product_id']}",
            "message": "Cloudflare blocks HTTP. Save this product page from the browser and re-run with --search-html and --product-html.",
        }, ensure_ascii=False, indent=2))
        return 3

    product_html_path = args.product_html
    if product_html_path is not None:
        # Only reuse a saved product page when it is for the Jev-selected id.
        html_probe = product_html_path.read_text(encoding="utf-8", errors="replace")[:4000]
        if f"p={product['product_id']}" not in html_probe and f"product.php?p={product['product_id']}" not in html_probe:
            # Still allow if canonical product id appears later; keep path and let parser run.
            pass
    packed = collect_product_quotes(
        product,
        query=query,
        as_of_yesterday=as_of_yesterday,
        retrieved=search["retrieved"],
        timeout=args.timeout,
        product_html_path=product_html_path,
    )
    price_req = packed["price_request"]
    (args.out_dir / "request.json").write_text(
        json.dumps(price_req, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    evidence = {
        "retrieved": search["retrieved"],
        "as_of_yesterday": as_of_yesterday,
        "search_url": search["search_url"],
        "query": query,
        "must_include": must_include,
        "must_exclude": must_exclude,
        "target_hint": args.target_name,
        "search_hits": search["search_hits"],
        "jev_selected_product_id": chosen_id,
        "product": product,
        "quotes": packed["quotes"],
        "eligible_yesterday_quotes": packed["eligible_yesterday_quotes"],
        "deterministic_lowest_yesterday": packed["deterministic_lowest_yesterday"],
        "price_history_chart_tail": packed["price_history_chart_tail"],
    }
    (args.out_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    price_result = run_jev(
        price_req,
        out_path=args.out_dir / "result.json",
        provider=args.provider,
        python=args.python,
        dry_run=False,
    )
    quote_id, quote_dec = decision_value(price_result, "lowest_price_quote_as_of_yesterday")
    eligible_noul, eligible_dec = decision_value(price_result, "quote_is_as_of_yesterday_eligible")
    enough, enough_dec = decision_value(price_result, "evidence_enough_to_report_price")
    quote = price_req["state"]["quotes"].get(quote_id) if quote_id and quote_id != "none" else None

    report = {
        "query": query,
        "must_include": must_include,
        "must_exclude": must_exclude,
        "target_hint": args.target_name,
        "as_of_yesterday": as_of_yesterday,
        "search_url": search["search_url"],
        "jev_settings": {
            "model": "typesafe/jev-1.13",
            "provider": args.provider,
            "policy": (nav_result.get("policy") or price_result.get("policy")),
            "navigate": {
                "question": "open_product",
                "type": "choice",
                "user_intent": nav_req["state"].get("user_intent"),
            },
            "price": {
                "as_of_yesterday": as_of_yesterday,
                "eligible_quote_rule": "quote.update_date == yesterday",
                "selection_rule": "lowest price_hkd among eligible quotes; 行貨 on ties",
                "questions": {
                    "quote_is_as_of_yesterday_eligible": "noul",
                    "lowest_price_quote_as_of_yesterday": "choice",
                    "evidence_enough_to_report_price": "noul",
                },
            },
        },
        "jev_navigate": {
            "question": "open_product",
            "selected": chosen_id,
            "decision": nav_dec,
            "product": product,
            "elapsed_seconds": nav_result.get("elapsed_seconds"),
            "model": (nav_result.get("response") or {}).get("model"),
            "usage": (nav_result.get("response") or {}).get("usage"),
        },
        "jev_price": {
            "questions": {
                "quote_is_as_of_yesterday_eligible": eligible_dec,
                "lowest_price_quote_as_of_yesterday": quote_dec,
                "evidence_enough_to_report_price": enough_dec,
            },
            "selected_quote_id": quote_id,
            "selected_quote": quote,
            "elapsed_seconds": price_result.get("elapsed_seconds"),
            "model": (price_result.get("response") or {}).get("model"),
            "usage": (price_result.get("response") or {}).get("usage"),
        },
        "final_price_hkd": quote.get("price_hkd") if quote else None,
        "final_merchant": quote.get("merchant") if quote else None,
        "final_channel": quote.get("channel") if quote else None,
        "eligible_noul": eligible_noul,
        "evidence_enough": enough,
    }
    (args.out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
