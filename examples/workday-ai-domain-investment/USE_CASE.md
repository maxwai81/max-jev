# Workday AI domain investment scoring (Jev)

Quick competitive-intel use case: score **marketing emphasis** of Workday AI on HR vs Finance vs IT from one public page — not dollar R&D spend.

## Decision contract

| Part | Choice |
|---|---|
| Decision | How heavy is each domain’s AI positioning on the page, and which is heaviest? |
| Unit / evidence | Structured excerpts from `https://www.workday.com/en-us/artificial-intelligence.html`, scoped per domain + shared platform claims |
| Questions | 3× `score` (HR / Finance / IT), 1× `noul` (enough evidence?), 1× `choice` (heaviest domain) |
| Consumer | Rank domains by score; flag `needs_review` on the choice when HR/Finance are close |
| Unknown path | Thin IT outcomes → lower score; Legal metrics excluded; choice may `needs_review` |
| Success check | Request dry-runs; live OpenRouter Jev returns typed scores grounded only in supplied evidence |

## Rubric (0–3)

0. Absent / incidental  
1. Named but thin (no domain-linked metric/proof)  
2. Substantive (dedicated narrative + capability **or** outcome/proof)  
3. Heavy (multiple capabilities **and** outcome/proof)

## Run

```bash
python3.12 .cursor/skills/jev/scripts/jev.py decide \
  examples/workday-ai-domain-investment/request.json \
  --provider openrouter --dry-run

python3.12 .cursor/skills/jev/scripts/jev.py decide \
  examples/workday-ai-domain-investment/request.json \
  --provider openrouter > examples/workday-ai-domain-investment/result.json
```

## Pure LLM (same request, no Jev)

`run_llm.py` sends the same `state` and questions to OpenRouter chat completions. It does not call the Jev decisions API. Default model: `x-ai/grok-4.7` (`LLM_COMPARE_MODEL` or `--model` overrides it). Scores are integer rubric indexes. Jev scores are probability-weighted expected values.

```bash
python3 examples/workday-ai-domain-investment/run_llm.py
```

## One-page comparison (2026-10-01)

| | Jev `typesafe/jev-1.13` | LLM `x-ai/grok-4.7` |
|---|---|---|
| HR | 2.86 (mode 3, p=0.87) | 3 Heavy |
| Finance | 2.99 (mode 3, p=0.99) | 3 Heavy |
| IT | 1.06 (mode 1, p=0.94) | 1 Named but thin |
| Evidence enough | true (p=0.89) | true |
| Heaviest | needs_review (HR 0.58, tie 0.32) | hr |
| Latency | 0.63s | 28.71s |
| Tokens | 2199 in / 146 out | 3351 in / 2327 out |
| Cost | $0.000092 | $0.0189 |

Domain levels match. The LLM commits to HR as heaviest because it counts two HR metrics against one Finance metric. Jev’s expected scores put Finance slightly above HR and leave the winner in review.

## Files

- `request.json` — shared evidence + questions
- `result.json` — last live Jev response
- `run_llm.py` — pure LLM runner
- `result-llm.json` — last live LLM response  
