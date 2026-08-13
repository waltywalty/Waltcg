# Source map

> Every field in `contracts/screens.schema.json` → which upstream source supplies it →
> endpoint → refresh cadence → what happens when it is unavailable.
>
> **The rule that shaped this document:** a field with no reachable source is deleted
> from the schema, not stubbed and not marked TODO. An unsourceable field in the
> contract becomes a beautiful empty box in the UI three weeks later. The deletions are
> listed in section 6 and are the most useful output of the session that produced this.

Current as of 2026-08-13. Source detail in `docs/DATA_SOURCES.md`. Live coverage
findings in `probe/COVERAGE.md`.

---

## 1. Sources in play

| Key | What it gives | Access | Cost |
|---|---|---|---|
| `tcgapi.dev` | catalog, market/low/foil, per-condition, 24h/7d/30d change, history (Pro) | `X-API-Key`, instant | $49.99/mo Pro (provisional) |
| `pokemonpricetracker` | eBay sold **by grade**, population by grader, gem rate, per-grade history | Bearer, instant | $99/mo Business (provisional) |
| `apitcg.com` | catalog, **artist**, JP One Piece card data | `x-api-key`, instant | free |
| `pricecharting` | graded comps across six graders, history, JP cards (export-market price) | token as `t` param | paid |
| `youtube` | video count and view velocity | API key, instant | free quota |
| `pytrends` | search interest, **set / character level only** | none | free |
| `alpha_vantage` | FX only | connected | connected |
| `manual` | anything a human types in | — | — |
| `engine:<model>` | computed here from the above | — | — |

**Not sources, and why** — TCGplayer API (closed to new applicants since the eBay
acquisition), eBay Marketplace Insights (Limited Release, denied to new users), PSA
population (never on an API; PSA's public API is cert-verification only at roughly one
call/day free), Reddit Data API (self-service OAuth registration closed; approval
pending, 2–4 weeks; unauthenticated `.json` endpoints return 403 since May 2026).

---

## 2. Shared types

| Field | Source | Endpoint | Cadence | If unavailable |
|---|---|---|---|---|
| `money.amount`, `.currency` | whichever feed produced the price | — | with the price | Field is null with `unavailable_reason`; never zero |
| `money.fx_rate_used`, `.fx_as_of` | `alpha_vantage` | FX_DAILY | daily | Conversion refused; the amount stays in its native currency |
| `derived_value.source` | — | — | — | Must name a row in this table or `engine:<model>` |
| `derived_value.confidence` | `engine` | — | per call | Never omitted; `unvalidated` is a real value |
| `derived_value.sample_size` | source that supplied the comps | — | per call | Null means not applicable, never unknown |
| `staleness.*` | `engine` | — | per response | Computed by the API, never by the UI |
| `card_ref.card_uid` … `.number` | `resolve/identity.py` | — | on resolve | Card is excluded from output entirely |
| `card_ref.rarity` | `tcgapi.dev`, `apitcg.com` | `/v1/search`, `/api/{game}/cards` | weekly | Null |
| `card_ref.artist` | **`apitcg.com`** | `/api/{game}/cards` | weekly | Null. The price feeds do not carry artist reliably |
| `card_ref.image_url` | `tcgapi.dev`, `apitcg.com` | catalog | weekly | Null; UI shows the ladder without art |

## 3. Prices and population

| Field | Source | Endpoint | Cadence | If unavailable |
|---|---|---|---|---|
| `grade_rung.price` (raw) | `tcgapi.dev` | `/v1/search`, `/v1/prices` | daily | Null + `source_unreachable` |
| `grade_rung.price` (8/9/10) | `pokemonpricetracker` (Pokémon), `pricecharting` (others) | `ebay.salesByGrade`, PC price | daily | Null + `no_source_for_this_game` |
| `grade_rung.population` | **`pokemonpricetracker` — Pokémon only** | `populationByGrader` | weekly | Null + `no_source_for_this_game` for One Piece and Riftbound |
| `population_total`, `population_by_grade` | `pokemonpricetracker` | `totalPopulation` | weekly | As above |
| `price_point.*` (history) | `tcgapi.dev` Pro; `pokemonpricetracker` per-grade | history endpoints | daily | Series truncated to what exists; never interpolated |
| `mover_row.change_pct_24h` | `tcgapi.dev` | built-in 24h change | daily | Null |

**Language coverage is not uniform, and the schema does not pretend it is:**

| Combo | Raw price | Graded comps | Population |
|---|---|---|---|
| Pokémon EN | tcgapi.dev (game 55) | pokemonpricetracker | pokemonpricetracker |
| Pokémon JP | tcgapi.dev (game 19, separate entry) | pokemonpricetracker | pokemonpricetracker |
| One Piece EN | tcgapi.dev (game 11) | pricecharting | **none** |
| One Piece JP | **none** — no One Piece Japan entry in the tcgapi catalog | pricecharting (export price) | **none** |
| Riftbound EN | tcgapi.dev (game 5) | pricecharting (unconfirmed) | **none** |
| Pokémon CN-S / CN-T, One Piece CN-S | **none** — confirmed absent from every Western source | none | none |

Everything in the **none** cells routes to `manual` entry with
`unavailable_reason: awaiting_manual_entry`, or the row is suppressed. No field promises
a value it cannot get.

## 4. Screens

| Field | Source | Endpoint | Cadence | If unavailable |
|---|---|---|---|---|
| `home.portfolio_value`, `.day_change`, `.day_change_pct` | `manual` holdings × `tcgapi.dev` prices | — | daily | Refuse; the number is meaningless partial |
| `home.open_alert_count`, `top_movers` | `engine:alerts`, `engine:portfolio` | — | daily | Empty array, designed empty state |
| `signals.rows[].headline` | `engine:model_a` / `model_c` / `model_d` / `trend` | — | daily | Row omitted; counted in `suppressed_count` |
| `signals.suppressed_count` | `engine` | — | daily | Always present so suppression is visible |
| `card_detail.obtainment.*` | **`manual` classification** | — | on add | `unknown`; no upstream publishes this taxonomy |
| `card_detail.buy_routes[].url` | `tcgapi.dev`, venue URL templates | — | daily | Null |
| `card_detail.buy_routes[].landed_cost` | `tcgapi.dev` (TCGplayer-derived); `manual` for JP/CN venues | — | daily | Null + `awaiting_manual_entry`; the link still works |
| `card_detail.language_variants` | `resolve/identity.py` | — | on resolve | Empty array |
| `grading_lab.break_even_p_target` and siblings | `engine:model_a` | — | on request | `refusal` object, never a number |
| `grading_lab.pop_implied_p_target` | `pokemonpricetracker` | `combinedGemRate` | weekly | Null + `no_source_for_this_game` |
| `grading_lab.cost_breakdown.*` | `config/grading.yaml`, `config/fees.yaml` | — | quarterly | `ConfigIncomplete`; engine refuses |
| `arbitrage_board.rows[].friction.*` | `config/fees.yaml`, `config/grading.yaml` | — | quarterly | Row omitted; a spread without its frictions is not a spread |
| `arbitrage_board.rows[].path` | `engine:model_c` | — | on request | — |
| `trend_radar.*_z` | `youtube`, `pytrends` | Search:list / Videos:list; pytrends | 6-hourly | Null; row omitted |
| `trend_radar.rows[].sources` | — | — | — | Array, so adding a platform later is data, not a schema change |
| `trend_radar.excerpts[]` | `youtube`, `pytrends` | — | 6-hourly | Empty array. Links plus paraphrase only, never bulk text |
| `track_record.*` | `engine:alert_ledger` (our own, append-only) | — | daily forward-scoring | Zero-state with `scored_alert_count: 0` |
| `settings.assumptions[]` | `contracts/assumptions.json` | — | on edit | — |
| `settings.fee_schedules[]`, `.grading_tiers[]` | `config/fees.yaml`, `config/grading.yaml` | — | quarterly | `usable: false`; engine refuses that venue or tier |
| `settings.fx_rates[]` | `alpha_vantage` | FX_DAILY | daily | Last known rate with its true `as_of`; never silently refreshed |
| `settings.score_enabled` | `engine:score` | — | — | Always false until D6 passes |

## 5. Cadence summary

| Cadence | What | Why |
|---|---|---|
| daily | raw and graded prices, FX, portfolio, forward scoring | 90-day trades do not need minute freshness |
| 6-hourly | sentiment | Matches the ingestion schedule; not continuous polling |
| weekly | population, catalog, artist | Pop reports move slowly |
| quarterly | fee and grading config | Plus on any announced change |
| on request | grading lab, arbitrage rows | User-initiated |

---

## 6. DELETED FOR LACK OF A SOURCE

These were designed, found unsourceable, and removed. Each would have become an empty
box.

| Deleted field | Why | What replaced it |
|---|---|---|
| `reddit_mentions`, `reddit_velocity`, `subreddit_breakdown` | Reddit Data API self-service registration is closed; approval pending 2–4 weeks; unauthenticated `.json` returns 403 since May 2026. No reachable source **today**. | `trend_row.sources[]` is an array. When approval lands, Reddit is appended as data — no schema change. |
| `sold_listings[]` (generic recent-sales feed) | eBay Marketplace Insights is Limited Release and denied to new users; the only by-grade sold data is pokemonpricetracker, Pokémon-only. | `grade_rung.price` with `sample_size` on its `derived_value`. |
| `psa_population` sourced from PSA | PSA has never had a population API. Its public API is cert-verification only, throttled to roughly one call/day free. | `population` sourced from pokemonpricetracker, Pokémon-only, null elsewhere. |
| `cert_lookup`, `cert_verified` | PSA public API is cert-only at ~1 call/day. Unusable per-card at any scale. | Nothing. Removed entirely. |
| `predicted_grade_from_photo`, `photo_condition_score` | No source. GOAL lists image-based grade prediction as explicitly out of scope and DATA_SOURCES says buy it, do not build it. | `condition_read` — the user's own read, typed in. |
| `tcgplayer_seller_count`, `direct_low`, `listing_depth` | TCGplayer API closed to new applicants. tcgapi.dev resells market/low/foil but not seller-level depth. | `grade_rung.price` raw only. |
| `search_interest_card_level` | pytrends is useless at individual-card level — DATA_SOURCES is explicit. | `trend_row.game_baseline_z` at set/character level. |
| `bid_ask_spread`, `last_sale_snkrdunk` | SNKRDUNK has no public API. | `buy_route` with `entry_method: manual` and null `landed_cost`. |
| `mercari_jp_sold_price` (automated) | No public API; Apify actors only. A fragile scraper that breaks silently is worse than an honest empty state. | Same manual `buy_route`. |
| `one_piece_jp_market_price` (automated) | The tcgapi catalog has **no One Piece Japan game entry** — confirmed by reading `/v1/games` to the last page. apitcg carries JP One Piece catalog data but no prices. | Manual entry, or pricecharting's export-market price clearly labelled as such. |
| `gem_rate` for One Piece and Riftbound | pokemonpricetracker is Pokémon-only; no other source publishes population. | Null with `no_source_for_this_game`. The field survives because Pokémon can fill it. |
| `chinese_market_price` (automated) | Probe confirmed no Western source carries Simplified or Traditional Chinese printings. | Manual-entry tier, `awaiting_manual_entry`. |

**The shape of the loss.** Two-thirds of these are the same story: the primary sources
closed and a paid intermediary layer grew in their place, so anything the intermediaries
do not resell is simply gone. The rest is Japanese and Chinese market data, which has no
clean API at any price. Population outside Pokémon is the single most damaging gap — it
is an input to Model A's prior and to Model D's whole regression, so One Piece and
Riftbound get a raw-price screener and no grading models until that is solved.

---

## 7. Unverified at time of writing

- Riftbound set codes in the fixtures (`OGN-301`, `OGN-042`, `VDT-017`) are **not
  confirmed against the catalog**. Riftbound is in tcgapi as game id `5`; the individual
  collector numbers and the Vendetta set code have not been read from it.
- Riftbound graded coverage on pricecharting is assumed, not confirmed.
- Every fee and grading value is `secondary, unverified` — see `config/*.yaml`.

## 8. Per-field index

Completeness check for `tests/test_contract.py::test_every_schema_field_is_mapped_to_a_source`.
Fields already covered by the tables above are not repeated. Cadence and
unavailable-behaviour follow the group each field belongs to in sections 2-4.

| Field | Source |
|---|---|
| `acquisition_cost` | `manual` (what I paid) |
| `acting_threshold_met` | `engine:alert_ledger` |
| `age_seconds` | `engine` (computed from as_of) |
| `alert_id` | `engine:alert_ledger` |
| `anchor` | `engine` (refusal detail) -- section within the target screen |
| `annualised_roi` | `engine:model_a` |
| `assumption_ids` | `contracts/assumptions.json` |
| `availability` | `config/grading.yaml` |
| `availability_note` | `config/grading.yaml` |
| `backfilled_excluded` | `engine:trend` |
| `break_even_attainable` | `engine:model_a` |
| `break_even_note` | `engine:model_a` |
| `buy_venue` | `engine:model_c` |
| `calibration_plan` | `contracts/assumptions.json` |
| `category` | `manual` classification |
| `centering_pct` | `manual` (my condition read) |
| `checked_on` | `config/*.yaml` |
| `corner_flag` | `manual` |
| `current_value` | `contracts/assumptions.json` |
| `deep_link` | `engine` (refusal detail) -- where the gap is fixed; null when structural |
| `description` | `contracts/assumptions.json` |
| `double_demeaned_z` | `engine:trend` |
| `downside_case` | `engine:model_a` |
| `edge_flag` | `manual` |
| `editable` | `contracts/assumptions.json` |
| `excess_return_30d` | `engine:alert_ledger` |
| `excess_return_7d` | `engine:alert_ledger` |
| `excess_return_90d` | `engine:alert_ledger` |
| `filtered_by` | UI request echo |
| `fired_at` | `engine:alert_ledger` |
| `fixable` | `engine` (refusal detail) -- false for an absence no input can clear |
| `fx_spread` | `alpha_vantage` + `assumptions.fx_conversion_spread` |
| `grading_fee` | `config/grading.yaml` |
| `gross_spread` | `engine:model_c` |
| `headline_label` | `engine` |
| `hit_rate_30d` | `engine:alert_ledger` |
| `hit_rate_7d` | `engine:alert_ledger` |
| `hit_rate_90d` | `engine:alert_ledger` |
| `horizon_days` | `engine` (turnaround + days_to_sell) |
| `is_stale` | `engine` |
| `kind` | `engine` |
| `landed_cost_meta` | `tcgapi.dev` or `manual` |
| `last_reviewed` | `contracts/assumptions.json` |
| `marketplace_fee` | `config/fees.yaml` |
| `median_excess_return` | `engine:alert_ledger` |
| `meta` | `manual` |
| `missing` | `engine` (refusal detail) |
| `modelled_p_target` | `engine:model_a` |
| `needs_primary_verification` | `config/grading.yaml` |
| `net_margin_pct` | `engine:model_c` |
| `net_spread` | `engine:model_c` |
| `organiser_url` | `manual` |
| `own_baseline_z` | `engine:trend` over `youtube` |
| `pair` | `alpha_vantage` |
| `payment_fee` | `config/fees.yaml` |
| `play_type` | `engine` |
| `portfolio_value_meta` | `engine:portfolio` |
| `price_at_alert` | `tcgapi.dev` snapshot at fire time |
| `price_history` | `tcgapi.dev` Pro / `pokemonpricetracker` |
| `price_history_meta` | `tcgapi.dev` -- freshness and point count of the series |
| `price_meta` | `tcgapi.dev` |
| `reason_code` | `engine` (refusal detail) -- closed enum, one per Refusal the models raise |
| `roi` | `engine:model_a` |
| `sell_venue` | `engine:model_c` |
| `set_code` | `tcgapi.dev`, `apitcg.com` catalog |
| `shipping` | `config/fees.yaml` |
| `sorted_by` | `engine` |
| `surface_flag` | `manual` |
| `thesis` | `engine:alert_ledger` (rule text at fire time) |
| `threshold_seconds` | `engine` (config) |
| `title` | `engine` (refusal detail) -- human-readable, imperative where fixable |
| `turnaround_business_days` | `config/grading.yaml` |
| `ui_chip_required` | `contracts/assumptions.json` |
| `unit` | `contracts/assumptions.json` |
| `window_days` | `engine:trend` (config) |
| `worst_five` | `engine:alert_ledger` |
