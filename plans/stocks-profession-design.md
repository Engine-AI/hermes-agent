# Stocks profession design

Goal: make the existing `Stocks` profession operational for common stock-investing conversations by pairing it with focused, composable skills that map cleanly into Hermes profession discovery.

## Profession scope

Profession name: Stocks
Slug: `stocks`

Core user intents:
- look up a quote or recent price snapshot
- understand what a company does and how it is positioned
- review fundamentals and valuation signals
- interpret charts and technical indicators
- summarize earnings results and management guidance
- digest recent market/news catalysts
- manage a lightweight watchlist
- draft a trade plan with entry, exit, and invalidation logic
- perform position/risk checks before acting

Guardrails:
- outputs are informational, not investment advice
- always state market/exchange assumptions
- always separate facts from interpretation
- call out delayed data, stale data, or missing data
- avoid pretending to execute trades or guarantee returns

## Skill map

1. `stock-quote`
   - Fast market snapshot for ticker, exchange, last price, change, volume, and timestamp.
   - Best first skill when the user asks “多少钱”, “today”, “涨跌”, or “现价”.

2. `stock-details`
   - Company overview, business lines, exchange, sector, geography, and notable context.
   - Best for “这家公司是做什么的”.

3. `stock-fundamentals`
   - Revenue, margins, growth, balance sheet, valuation multiples, and red flags.
   - Best for medium/long-term investment analysis.

4. `stock-technicals`
   - Trend, support/resistance, momentum, moving averages, RSI/MACD framing.
   - Best for chart-based questions and timing discussions.

5. `earnings-analysis`
   - Revenue/EPS beat or miss, guidance changes, segment drivers, and market reaction.
   - Best around earnings season and quarterly reports.

6. `stock-news`
   - Recent catalysts, regulatory events, launches, macro pressure, or sector headlines.
   - Best when price moved and the user asks “为什么涨/跌”.

7. `watchlist-manager`
   - Track symbols, reasons to watch, upcoming catalysts, and status updates.
   - Useful for repeated monitoring conversations.

8. `trade-planner`
   - Structured trade thesis: setup, trigger, sizing idea, stop, targets, invalidation.
   - Best when the user asks for a plan rather than a raw opinion.

9. `risk-check`
   - Position concentration, scenario risk, earnings risk, gap risk, liquidity, and downside framing.
   - Best before entry/add/reduce decisions.

## Directory design

Local skills path:
- `~/.hermes/skills/stocks/<skill-name>/SKILL.md`

This keeps the profession self-contained in local skills while allowing Hermes to infer the profession through frontmatter metadata:

```yaml
metadata:
  hermes:
    professions: [Stocks]
    problem_domains:
      - ...
```

## Integration plan

1. Create the 9 local skills under the `stocks` category.
2. Add explicit `metadata.hermes.professions: [Stocks]` to every skill.
3. Bind each created skill into `PROFESSIONS.md` using `bind_skill_to_professions()`.
4. Set the active profession to `stocks` so future stock conversations route toward the new profession.
5. Verify with skill listing + profession inspection.

## Expected result

After integration, Hermes should:
- show `Stocks` in profession listings
- list the new stocks skills under that profession
- keep problem domains synchronized from skill metadata
- be ready to answer stock-analysis requests with a more specialized skill set
