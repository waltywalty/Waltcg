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

## S3 — the labelled set is 21 of 250

`tests/test_resolver_gate.py` is deliberately red. Six failures in every run,
and they are the only six. Candidates must be adjudicated by hand
(`python -m resolve.label_cli propose`); generating them from the catalogs the
resolver reads would make the precision score a measurement of the catalog.

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
