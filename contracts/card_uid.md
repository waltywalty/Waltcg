# Card identity

```
card_uid = {game}:{set_code}:{number}:{variant}:{language}

game     ∈ {optcg, pkmn, riftbound}
language ∈ {EN, JP, CN-S, CN-T}
```

Built only by `resolve.identity.card_uid()`. That function is the single sanctioned
constructor and it refuses anything that is not an internal code.

| Part | Meaning | Example |
|---|---|---|
| `game` | Our internal game code. Never a provider slug. | `pkmn` |
| `set_code` | Publisher's set code as printed | `sv3`, `OP05`, `OGN` |
| `number` | Collector number as printed, including denominator | `223/197`, `OP05-119` |
| `variant` | Which physical printing of that number | `base`, `sir`, `sar`, `manga_rare`, `parallel`, `promo`, `overnumbered`, `signature` |
| `language` | Printing language | `EN`, `JP`, `CN-S`, `CN-T` |

Examples:

```
pkmn:sv3:223/197:sir:EN            Charizard ex, Obsidian Flames, Special Illustration Rare
pkmn:sv3:108/108:sar:JP            Lizardon ex, Ruler of the Black Flame, SAR
optcg:OP05:OP05-119:manga_rare:EN  Monkey.D.Luffy manga rare
optcg:OP01:OP01-078:parallel:JP    Boa Hancock, JP parallel
riftbound:OGN:OGN-301:overnumbered:EN
```

---

## The invariant

> **EN and JP printings NEVER share a `card_uid`.** Neither do CN-S and CN-T. Every
> language printing is a different card with its own price series, its own population,
> and its own row in every aggregation.

This is not a preference. Bandai reuses the *same collector code* across languages —
`OP01-121` exists in English, Japanese and Simplified Chinese — so any scheme keyed on
the printed number alone silently merges three different assets with three different
markets into one. A merged series produces a price history that is a blend of markets
that never traded with each other, and a population count that is the sum of pools
graded under different submission behaviour. Every downstream number inherits the error
and none of them look wrong.

Enforced in three places:

1. `resolve.identity.card_uid()` requires `language` and rejects a printing the game
   does not have (there is no Riftbound JP release; asking for one raises).
2. `tests/test_resolver.py::test_every_language_printing_is_a_distinct_card` asserts all
   four printings of one card produce four distinct uids.
3. `screens.schema.json` pins the shape with a regex ending in the language enum, so a
   uid without a language cannot validate.

AUDIT_PROTOCOL Layer 3 adds a fourth: for every card in the labelled set that exists in
two languages, assert distinct uids **and** assert their price series are not correlated
above 0.99 — a correlation that high means they were accidentally merged upstream even
if the uids differ.

---

## Provider identifiers are a separate vocabulary

Providers name games their own way and change those names without telling anyone.

| Vocabulary | Form | Example |
|---|---|---|
| **Internal** (ours) | short stable code | `optcg`, `pkmn`, `riftbound` |
| apitcg.com | hyphenated slug, no language dimension | `one-piece`, `pokemon` |
| tcgapi.dev | opaque numeric id; **language is a separate game entry** | `11` One Piece, `55` Pokémon, `19` Pokémon Japan |

A provider identifier inside a `card_uid` makes the identifier unstable the moment a
provider renames a game, and silently repartitions history. So translation happens once,
at the ingest boundary, and only inbound:

```python
from resolve.identity import from_provider_slug, to_apitcg_slug, to_tcgapi_game_id
from_provider_slug("one-piece")        # -> "optcg"
to_tcgapi_game_id("pkmn", "JP")        # -> "19"
to_tcgapi_game_id("optcg", "JP")       # -> None: no such entry in the catalog
```

`to_tcgapi_game_id` returning `None` is a finding, not an error: it means that source
cannot express that printing at all. One Piece Japan is exactly that case.

**One wrinkle worth knowing.** A provider slug can coincide with an internal code —
apitcg calls Riftbound `riftbound` and so do we. Such a value is valid in both
vocabularies and is accepted; only unambiguously-external tokens are rejected. Treating
the coincident ones as leaks would reject a legitimate internal code, which is what the
first run of the boundary tests actually did.

---

## `card_xref`

External ids live beside the card, never inside its uid.

| Column | Type | Notes |
|---|---|---|
| `card_uid` | text | FK to the card |
| `source` | text | `tcgapi.dev`, `apitcg.com`, `pokemonpricetracker`, `pricecharting` |
| `external_id` | text | The provider's own id, verbatim |
| `secondary_id` | text, nullable | e.g. tcgapi stores the original `tcgplayer_id` separately — map both |
| `confidence` | real, 0–1 | Match confidence |
| `resolved_by` | text | `exact` \| `fuzzy` \| `manual` |
| `observed_at` | timestamp | When we saw this mapping |
| `supersedes` | text, nullable | Previous row this corrects. Append-only; nothing is UPDATEd |

Rules:

- **Anything `fuzzy` below 0.9 confidence is excluded from every signal.** Asserted, not
  assumed — a fuzzy match at 0.85 that reaches a screen is a wrong card with a
  confident price on it.
- A card may have several rows per source over time. The current mapping is the latest
  `observed_at` with no successor.
- `resolved_by = manual` outranks any automatic match at the same confidence.
- One `card_uid` never maps to two live `external_id`s from the same source. Two would
  mean the resolver merged two real cards, which Layer 3's collision test catches.

---

## Why not use a provider id as the primary key

Tempting, and wrong for four reasons:

1. **It encodes the wrong partition.** tcgapi's id for Pokémon Japan is a different
   *game*, not a language attribute, so an id-keyed store cannot express "same art,
   different printing" at all.
2. **It dies with the provider.** TCGplayer's API closed to new applicants; anything
   keyed on their ids would have needed a full re-key.
3. **It cannot represent a card no source carries.** Chinese printings exist and are
   real official releases, and no Western source lists them. They still need identity,
   history and manual prices.
4. **It is not stable.** Providers renumber. Our uid is derived from what is physically
   printed on the card, which does not change.
