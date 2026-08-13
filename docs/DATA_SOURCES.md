# Data Sources — WaFT Cards

> Place at `docs/DATA_SOURCES.md`. Current as of 12 Aug 2026. Re-verify pricing and access terms before you subscribe — this space moves fast and several of these changed in the last six months.

---

## 1. What's closed, and why it matters

Three doors you might assume are open are not. Knowing this saves you two weeks.

**TCGplayer API** — public developer applications have been closed for years. eBay acquired TCGplayer in 2022 and access is now restricted to established sellers and approved partners. TCGplayer's own getting-started page states plainly that new API access is not being granted. If you apply today, expect silence. Everything downstream of TCGplayer pricing therefore comes from third parties who already have a pipeline.

**eBay Marketplace Insights API** — the only official source of eBay sold data, covering roughly the last 90 days. It is a Limited Release API requiring business-level approval, and eBay's docs describe it as restricted and not open to new users. Developers on eBay's own forums report being explicitly denied and told access is for major partners only. Don't apply; route around it.

**PSA population reports** — never on the API, and mid-2026 PSA cut both anonymous and free registered tokens to roughly one call per day, pushing cert lookups onto a paid plan. The population report exists only on the website. Third parties who scrape it are your realistic route.

The shape of the market: the primary sources have all closed, and a layer of paid intermediaries has grown up in their place. Budget for that layer rather than fighting it.

---

## 2. Recommended stack

### Tier 1 — get these first

**TCG API** · `tcgapi.dev`
- Catalog and pricing for every game on TCGplayer — 89+, including all four of yours. Riftbound is in the top-7 daily-refresh group alongside Pokémon and One Piece.
- Market / low / foil prices, per-condition NM→Damaged, built-in 24h/7d/30d change tracking (so you don't have to store history yourself for short-horizon screens).
- Auth: static `X-API-Key` header. No OAuth dance.
- Free 100 req/day → Hobby $9.99 → Starter $19.99 → **Pro $49.99** (full history, bulk endpoints, commercial licence) → Business $99.99.
- **Get Pro.** Price history and bulk endpoints are what make the backtest possible, and bulk is what keeps you inside quota when you're refreshing a few thousand cards daily.
- Gotcha: it has its own internal `id` and stores the original TCGplayer product ID separately as `tcgplayer_id`. Map both into `card_xref`.

**PokemonPriceTracker** · `pokemonpricetracker.com`
- The most important source in the stack, because it's the only self-serve one that gives you all three of: **eBay sold prices by grade** (`ebay.salesByGrade.psa10 / .psa9 / .psa8`), **population by grader** with `combinedGemRate`, and **per-grade price history**. CGC, BGS and SGC included alongside PSA.
- Also covers Japanese cards and sealed product, and has a Parse Title endpoint for matching messy eBay listing titles to cards — which will save you real time on the resolver.
- Free 100 credits/day → API $9.99 → **Business $99** (population data, 12+ months history, daily CSV dump).
- **The daily CSV dump on Business is the single best value in this list.** Load it locally once a day and query it for free instead of burning credits per card.
- Pokémon only. One Piece and Riftbound grade-level data has to come from PriceCharting or scraping.

### Tier 2 — add when you need breadth

**apitcg.com** — free, open-source card catalog covering One Piece, Pokémon, Digimon, Gundam, Union Arena and **Riftbound**. Your cross-check for card metadata and, importantly, **artist attribution**, which you need for the artist-premium feature and which the price APIs don't reliably carry. Also useful for JP One Piece card data.

**PriceCharting** — the broadest grade coverage anywhere: PSA, BGS, CGC, SGC, TAG and ACE, with full price history and recent sold listings. Paid subscription; token from Subscription ▸ API/Download, passed as a `t` query parameter. **Read the ToS carefully** — PriceCharting claims ownership of its price data and restricts redistribution. Personal research and internal use are fine. Exposing that data publicly requires either their top-tier plan or written permission. Your app is private and single-user, which keeps you inside the line — but it's a reason never to commit their price data or put a public API in front of it. The code may be public; their data may not be.

**Cardmarket-derived APIs** — several third parties now resell Cardmarket (EU) pricing with Riftbound and One Piece coverage, some bundling eBay graded-slab sold medians with sample sizes. Useful as a **third opinion** for the cross-source divergence check in Layer 2 of the audit. EUR-denominated, so exercise your FX layer.

**JustTCG** — TCG-only pricing blended from online listings and real in-store sales, roughly 20 games with condition-level pricing, 90d/180d history. Ships an **MCP endpoint**, so it can be added directly as a custom MCP server in Claude and queried conversationally as well as programmatically. Narrower coverage than TCG API; better provenance on the ones it covers.

### Tier 3 — sentiment

**Reddit Data API** — free tier is 100 QPM per OAuth client for non-commercial use, which is plenty for your volume. Two problems: **self-service OAuth registration closed** under Reddit's Responsible Builder Policy, so a new token needs manual approval on a roughly two-to-four week timeline; and unauthenticated `.json` endpoints started returning 403 in May 2026, so there's no unauthenticated fallback. **Apply today.** Set a correct `User-Agent` in the `platform:appid:version (by /u/username)` format or you'll get throttled regardless.

**YouTube Data API** — free quota, instant access, and honestly a better early-trend signal than Reddit for TCG: opening video count and view velocity for a set or card name moves before Reddit discussion does. Start here while the Reddit approval is pending.

**pytrends (Google Trends)** — free, no key, no approval. Good at character and set level, useless at individual card level. Use it for the character-popularity feature, not the trend module.

**Bright Data** — if you need Reddit at scale, or SNKRDUNK, or Mercari JP, this is the industrial answer and you already have the plugin skills available (`scraper-builder`, `scrape`, `search`, `brand-listening`). Costs real money. Only worth it once the ledger shows the trend module is finding something.

### Tier 4 — Japanese market (the genuine gap)

There is no clean API for JP card pricing. This is the weakest part of the stack and you should size your expectations accordingly.

- **SNKRDUNK** — functions like StockX for Japanese cards: verified authentication, real transaction data, transparent bid/ask. The best single source for JP sealed and singles pricing. No public API.
- **Mercari JP** — shows completed sale prices, which is what you actually want. Filter to sold items. No public API; Apify actors exist.
- **Yahoo Auctions JP** — deepest for vintage and JP-exclusive promos. No public API.
- **PriceCharting** — does cover Japanese cards in PSA 10 / PSA 9 / ungraded, sourced from eBay completed sales. That's an *export-market* price, systematically different from the domestic JP price. Both are useful; don't confuse them.

**Practical approach for v1:** use PriceCharting for JP graded comps (it's an API and it works), treat SNKRDUNK/Mercari as a manual-entry field you fill in yourself for cards you're actually considering, and defer automated JP scraping to v2. A fragile scraper that breaks silently is worse than an honest empty state.

**FX:** every JP price needs `USDJPY` at the observation date, from Alpha Vantage (already connected). Store the rate used, never just the converted number.

---

## 3. Grading economics — the config that must not be hardcoded

Everything here changed in 2026. Verify current values at build time and re-verify quarterly.

**PSA**
- Tier pricing updated 10 Feb 2026.
- **In June 2026 PSA paused its four lowest-cost Value tiers** against a backlog reported at roughly 10 million cards. Regular turnaround extended to around 50–60 business days.
- Value Bulk, when available, requires Collectors Club membership (~$149/yr) and a 20-card minimum. Real all-in cost per card runs meaningfully above the headline fee once you add Card Savers, shipping both ways, insurance and supplies — plan on roughly $10–12 per card of overhead on top of the tier fee for a ten-card submission.
- **Crossover service:** you specify a minimum grade; if PSA won't hit it the card comes back in its original slab. This is the mechanic that makes Model C's `psa_crossover` path low-risk relative to crack-and-resubmit.

**CGC** — materially cheaper on modern (roughly $17–20/card, no membership), turnaround around 65 days Economy. Pristine 10 sits above Gem Mint 10. Strong traction in Pokémon and TCG specifically.

**BGS** — half-point scale with four subgrades; Black Label requires 9.5 across all four. Stricter than PSA on centering. Charges a handling fee on crossover and reholder services. **The subgrades are the signal** for crossover decisions: balanced 9.5s cross well, a lone 9.0 on corners or surface is where crossovers die.

**Market reality to encode:** PSA 10 carries a liquidity and price premium over equivalent grades from other companies — commonly cited around 15–25% on vintage, narrower on modern where CGC's fee saving often erases the gap entirely. Your Model C should compute this per-card from actual comps, not apply a blanket multiplier.

**Capital lockup is a real cost.** At 50–60 business days plus intake plus listing time, a grading play ties up capital for a quarter or more. Annualise the ROI or you will systematically overrate slow, thin trades.

---

## 4. Licensing and conduct

- **No provider data is ever committed. Code may be public; data never is.** Do not publish a public API, do not resell, do not redistribute price data. Enforced by CI on every push — repository visibility is not a control.
- PriceCharting's terms restrict downstream exposure of their price data specifically.
- Reddit's free tier is non-commercial only; commercial use requires approval and a negotiated agreement with a large minimum.
- Respect `robots.txt` and rate limits on anything scraped. Cache aggressively — you are not doing anything that needs minute-level freshness on a 90-day trade.
- Cache raw responses before parsing. When a parser breaks you want the day's data preserved, not lost.

---

## 5. Things you should buy rather than build

**AI grade prediction from photos.** Several apps do camera-based pre-grading now. Independent testing of one of the popular ones found it never inflated grades relative to PSA — every miss was conservative, typically returning 9.3–9.5 on cards that came back PSA 10. That's the right failure mode for your use case (it talks you out of marginal submissions rather than into them), and it maps more naturally onto TAG's half-grade scale than onto PSA's whole-grade rounding. Building this yourself is a computer-vision project, not a weekend. Use one as an input to Model A's condition read and move on.

**Population report scraping.** Third-party services already maintain PSA and CGC pop scrapers. Paying for a maintained one is cheaper than owning a scraper that breaks whenever PSA touches their markup.

---

## 6. Quick reference

| Source | Games | Gives you | Cost | Access |
|---|---|---|---|---|
| TCG API | all 4 | catalog, market/low/foil, conditions, 24h/7d/30d change, history (Pro) | $50/mo Pro | instant |
| PokemonPriceTracker | Pokémon (EN+JP) | eBay sold by grade, pop by grader, gem rate, per-grade history, CSV dump | $99/mo Business | instant |
| apitcg.com | OP, Pkmn, Riftbound | catalog, artist, JP data | free | instant |
| PriceCharting | all | graded comps across 6 graders, full history | paid | instant |
| PSA public API | all | cert verification only | ~1 call/day free, else paid | instant |
| Reddit Data API | — | sentiment | free (non-comm) | **2–4 wks** |
| YouTube Data API | — | video velocity | free quota | instant |
| pytrends | — | search interest | free | instant |
| Alpha Vantage | — | FX (USDJPY, GBPUSD, HKDUSD) | already connected | instant |
| SNKRDUNK / Mercari JP | JP | true JP domestic prices | scraping only | manual for v1 |
