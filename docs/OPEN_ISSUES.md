# Open issues

Severity tags: **S1** wrong numbers reach a decision · **S2** data lost or
merged silently · **S3** reported wrongly but recoverable · **S4** cosmetic.

Session ritual says this file is updated at the end of every session. It did
not exist until run #11; the entries below are the ones live at that point,
not a full history.

---

## S1 — the composite score is still disabled, and correctly so

`SCORE_ENABLED=false`. It has not been benchmarked out-of-sample against a
pre-registration, so nothing here is a signal yet. Unchanged, and not a defect.

## S2 — Celebrations prints four different cards at collector number 15

`cel25c-15_A1` .. `_A4` are Venusaur, *Here Comes Team Rocket!*, Rocket's
Zapdos and Claydol. Four **different cards**, one collector number, and the
provider disambiguates them with a suffix that looks exactly like One Piece's
parallel marker but means something else entirely.

Three card_uids collide as a result (`pkmn:cel25c:15:base:EN`). They are the
only collisions left in the Pokémon catalog after the One Piece fix.

**Not fixed, deliberately.** The One Piece rule is scoped to One Piece
(`ID_SUFFIX_VARIANT_GAMES`) because applying it here would label four distinct
cards as parallels of each other, which is worse than the collision. The right
fix is a set-specific rule for Celebrations, and it needs someone to look at
what the printed numbers actually are.

Cost of leaving it: three Classic Collection cards share a price series.

## S2 — One Piece CN-S has no catalog source

tcgdex is Pokémon-only; apitcg has no Chinese One Piece. Manual entry for v1.
Recorded rather than discovered from an empty screen.

## S3 — apitcg's rate limit is unknown

Not in `openapi.json`, not in a response header, not on the docs site. 250
calls succeeded on 2026-08-17; 16 were refused on 2026-08-18. Two data points,
recorded in `config/rate_limits.yaml`, and not enough for a daily quota — the
shape is more consistent with a per-minute or per-hour window.

Mitigated rather than solved: the catalog cache means a refusal costs nothing,
and the two-strike breaker means we stop asking. Add each run's numbers from
the ingest step's rate-limit table.

## S1 — Model A cannot run at all: three assumptions are null

Every tier on every route refuses with `ConfigIncomplete` on the same three:

```
assumptions.submission_selection_haircut.current_value
assumptions.empirical_bayes_prior_strength.current_value
assumptions.empirical_bayes_min_card_pop.current_value
```

23 tier/route pairs, no exceptions. These are the registered assumptions
CLAUDE.md calls known-fragile — the haircut is "a guess until calibrated
against my own submission results" — and the model refusing rather than
picking a plausible default is the correct behaviour, not a defect. But it
does mean **Model A produces nothing today**, and that is worth stating
plainly rather than leaving to be discovered from an empty screen.

Unblocking it is a decision, not a fix: put a number in with a calibration
plan, or leave it refusing.

## S2 — PSA's four Value tiers are null, and TAG has no route

`PSA.value_bulk`, `value`, `value_plus`, `value_max` each have a null `fee`,
`min_cards` and `turnaround_business_days` — PSA paused those tiers in June
2026, which is exactly why they live in dated config. Two more tiers block on
`turnaround_business_days` alone: `BGS.base`, `BGS.base_subgrades`, and all
four SGC tiers.

Separately, `config/grading.yaml` declares four routes — `cgc_uk`, `psa_us`,
`bgs_us`, `sgc_us` — and none of them is TAG. So TAG's four tiers are
unreachable from Model A regardless of their config: there is no route that
gets a card to them and back.

## S2 — 57 rows carry a `difficulty_class` the gate cannot read

The 86 researched rows tag themselves `C1`..`C6` — 28 `C1`, 21 `C5`, 10 `C3`,
10 `C6`, 4 `C4`, 2 `C2`. The gate counts `hard_case`, and requires four named
kinds: `same_art_different_language`, `reprint`, `alt_art_variant`,
`promo_vs_set`.

So **1 of 57 verified rows counts as a hard case**, against a target of 60, and
`test_every_hard_case_kind_is_covered` fails on three of the four kinds — while
the set almost certainly contains examples of all four.

**Not mapped, deliberately.** The notes suggest `C1` is same-art-across-
languages and `C4` is promo-versus-set, but that is inference from a handful of
annotations and the taxonomy is not documented here. Guessing a mapping is the
same coercion this session refused for variant tokens, and it would put
invented labels into the set that measures labelling.

Needs one of: the C1–C6 definitions, so the mapping is a translation rather
than a guess; or `hard_case` added to the rows at source.

## S2 — nine variant tokens are rejected and 18 rows are waiting on them

The 86-row external research file uses 18 variant tokens. Nine are not in
`resolve.identity.VARIANTS`, so 18 rows are held out of the set:

**RESOLVED.** Eight extended, one renamed, and the vocabulary is now PER GAME
— `SHARED_VARIANTS` plus `GAME_VARIANTS`, exactly like the rarity band tables.
`sr` is valid for `pkmn` and invalid for `optcg`, where those two letters name
a rarity band instead, and the rejection message says so rather than "unknown".
All 86 rows are in.

## S3 — the catalog carries no set totals yet, so the bridge refuses everything

The catalog is tcgdex-derived and stores BARE collector numbers — `199`, `95`,
`173`. The labelled set stores what is printed on the card — `199/165`,
`095/203`, `173/165`. Neither is wrong and neither should change: the printed
number is the identity, and tcgdex's `localId` is what the provider sends.

`printed_from_bare` bridges them, one direction only, using the set's official
card count. **The count is not in `targets.json` yet** — `set_totals()` was
added to the tcgdex adapter this session and populates `_set_totals` on the
next Actions run.

Until then the bridge REFUSES every comparison, which is the designed
behaviour: 10 refusals, 0 matches, 0 merges. With the counts simulated
(`sv03.5` 165, `swsh7` 203) three rows bridge immediately — `199/165`
Charizard ex, `205/165` Mew ex, `095/203` Umbreon VMAX.

Set codes are bridged, for two sets, by `SET_CODE_ALIASES`. Nothing bridges
the rest: `sv2a`, `s6a`, `s7R`, `151C`, `SV2aF`, `op01`, `op08`, `OGN`, `VEN`
all have no counterpart in the current catalog — mostly because apitcg has been
throttled and optcg/riftbound catalogs are empty, so there is nothing to
reconcile against yet. 93 of 103 labelled rows have no candidate at all.

## S3 — the labelled set is 103 rows, 57 of them ground truth

`tests/test_resolver_gate.py` is deliberately red. Six failures in every run,
and they are the only six. Candidates must be adjudicated by hand
(`python -m resolve.label_cli propose`); generating them from the catalogs the
resolver reads would make the precision score a measurement of the catalog.

57 `verified`, 29 `single_source`, 12 `in_repo`, 5 `unstated`. Precision and
recall are 1.0000 over the 57 — and that is a point estimate, not a passing
gate. Zero errors at n=57 gives a 95% lower bound of **0.9488**, against a
0.98 threshold. n=250 gives 0.9881 and survives one mistake, which is what
ADR-0015 sized the set on.

Every combination now has verified rows, and every combination is still below
the 20-row detection floor.

Five `unstated` rows remain, down from nine: four were superseded by sourced
rows. The rest need re-adjudication or discarding.

## S3 — the seven-day catalog threshold is a guess

`DEFAULT_MAX_AGE_DAYS = 7`. Sets release monthly, so a week is comfortably
inside the cadence, but it is a starting point and not a measurement. A set
that drops mid-week is missed until the refresh; `--force` exists for that day.

---

# Known-fragile

Carried from CLAUDE.md, still true. Treat with suspicion, do not "fix":

- Submission selection haircut — a guess until calibrated against my own
  submission results
- Regrade conditional prior — same, smaller sample coming
- Pull rate estimates — community-sourced and often wrong
- Riftbound history — sub-1-year market. Exploratory only, and the UI says so
- JP market coverage — no clean API; manual entry for v1
- Grade-level comp thinness — most of the universe has single-digit graded
  sales per quarter
