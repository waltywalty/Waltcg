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

## RESOLVED — C6 has a kind, and the gate requires it

`same_printed_number_different_treatment`. Verbose on purpose: it names the
thing that matters and cannot be mistaken for `alt_art_variant`, which is C3
and requires the numbers to DIFFER. **Added to the gate's required kinds**,
because C6 is one of the three blocking failures and a gate that does not
demand a case for it is missing the class it most needs to measure.

14 rows carry it — 10 One Piece base-vs-parallel pairs plus the 4 re-tagged
Riftbound rows below — and all 14 are `verified`.

## RESOLVED — the four Riftbound rows were re-tagged C5 → C6

`299/298`, `299*/298`, `303/298`, `303*/298`. C5 is cards that share a name and
are genuinely different cards; these are two printings of ONE card, treatment
the only difference. The asterisk being printed INSIDE the number is a notation
detail, not a different class — Riftbound writes the treatment into the number,
One Piece writes it nowhere and leaves it to an image filename. Same
relationship, two conventions.

Each row records `reclassified_from` and a note saying why, because a re-tag
with no trace is indistinguishable from data that was always that way. The
guard test is inverted rather than deleted: it asserted C5 while they were
mis-tagged and asserts C6 now, so the next person to change them hits the same
wall.

`map-classes` recomputes `hard_cases` rather than merging into it, so the
re-tag **dropped** the stale `name_is_not_unique`. Merging would have left the
four claiming a gate requirement they no longer meet.

## RECORDED, NOT RECONCILED — two kinds no C class covers

`hard_case` kinds are the schema. The C classes were an **input** — a research
taxonomy built to decide what to collect — and the kinds were derived from
failure modes this repository has actually hit. Where they disagree, the
disagreement stands:

- **`same_number_different_rarity`** (3 rows). Adjacent to C6 and not the same:
  C6 is distinguished only by treatment, and an OP01-025 base SR and its
  parallel both read `SR`. Here the provider reports two different rarities at
  one number, which asks a different question — whether rarity can be trusted
  as a discriminator at all.
- **`box_code_vs_card_number`** (1 row). Not a printing relationship at all,
  which is why no class covers it: a parsing failure mode, found by ingest
  rather than by research.

Neither is forced into a class, and a test asserts neither ever is.

## S2 — the fourth reprint shape has no rows

`same_number_new_set_new_variant` is declared and REQUIRED by the gate, and
nothing carries it. That is the point: a gate that only demands what it already
has measures nothing, and this is the case a set-only test (Celebrations) and a
variant-only test (OP01-025) both miss — a resolver can pass each and still
mishandle the two together.

C6 was NOT widened to absorb it. A widened C6 reads "variant differs, set may
or may not" — a disjunction, and disjunctive kinds are how C6 itself nearly got
buried inside `alt_art_variant`.

The five PRB pairs are the rows it wants. Their originals carry
`reprinted_in: prb01`/`prb02`; the PRB side is not minted because the variant
is the one field no source here supplies. apitcg would give `_p3`/`_p4`/`_p5`,
which is catalog-derived and excluded by rule.

## S1 — OP01-120 `manga_rare` may be homed to the wrong product

`OP01-120` has **six printings across two products**: `op01` holds `OP01-120`,
`_p1`, `_p2`; `prb01` holds `_p3`, `_p4`, `_p5`. A marketplace listing reading
`OP01-120 Manga` cannot pick between six, and both `manga_rare` rows were
sourced from exactly that kind of listing.

**Not re-homed.** apitcg carries no treatment names — every One Piece rarity
field is null — so nothing available says which of the six is the manga
printing. Re-homing to `prb01` on the strength of "OP-01 predates manga" would
be an inference, and inference is what put the row in `op01` in the first
place.

S1 rather than S2 because these two rows are `verified` and counted: if they
are mis-homed, a wrong identity is in ground truth. Flagged on the rows and
left counted rather than demoted — demoting would move the gate numbers on a
suspicion.

## RESOLVED — OP01-014 / OP01-015, and pass 4 is the one that is wrong

Pass 4 claimed `OP01-014` = Tony Tony.Chopper and `OP01-015` = Jinbe. Bandai's
list has **`OP01-014` = Jinbe and `OP01-015` = Tony Tony.Chopper**. The existing
verified EN row is correct; pass 4 has the pair swapped — the same failure
shape as batch 2's OP01-002/003.

No existing row corrected. The three quarantined rows are not ingested as
claimed, and correct rows for OP01-014 EN/JP and OP01-015 JP still need
sourcing afresh: minting them from apitcg would make them catalog-derived.

## RESOLVED — every required kind now has a verified example

`reprint` 24 verified, `promo_vs_set` 13, `same_number_different_product` 8.
Batch 2 filled both gaps. Verified rows carrying a hard case: **116 of 60** —
the hard-case gate passes.

## S3 — tcgdex renumbers the Celebrations Classic Collection

The printed card says `4/102`. tcgdex calls it `CC002`. Both describe the same
Charizard, and the printed number is the identity, so the labelled row keeps
`4/102` and the catalog keeps `CC002`.

The consequence: `cel` aliases to `cel25cc` correctly and the rows still cannot
match a catalog row, because the numbering schemes have nothing in common. The
bridge refuses rather than guessing, which is right — but it means the
`same_number_new_set` pairs, the hardest of the three reprint shapes, have no
catalog counterpart to be tested against.

## S3 — three set codes could not be verified

`mcd2023`, `s10b`, `s12a`. Recorded in `UNVERIFIED_SET_CODES` with the reason
and passed through untouched. The local apitcg snapshot stops at `mcd22` and
holds English only, and the catalog's Japanese set codes come from a different
scheme entirely (`SM10`, `SM12a`, `SV11B`).

An unaliased code and an unverifiable one behave identically — both pass
through — and only one of them is a decision. This is how you tell later that
somebody looked.

## S3 — 57 rows carry a `difficulty_class` the gate cannot read

The 86 researched rows tag themselves `C1`..`C6` — 28 `C1`, 21 `C5`, 10 `C3`,
10 `C6`, 4 `C4`, 2 `C2`. The gate counts `hard_case`, and requires four named
kinds: `same_art_different_language`, `reprint`, `alt_art_variant`,
`promo_vs_set`.

**RESOLVED** by the definitions above. **51 of 57** verified rows now carry a
hard case, against a target of 60.

`hard_case` had to become plural to do it: 18 of the 57 rows carry two classes
(`C1,C6`, `C3,C5`, `C2,C4`), and a single-valued field has to drop one —
silently deciding which gate requirement goes unmet. `hard_cases_of()` reads
both fields so nothing already recorded is lost.

`reprint` (C2) is the one required kind still absent from verified rows — see
above; that gate failure is deliberate.

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
