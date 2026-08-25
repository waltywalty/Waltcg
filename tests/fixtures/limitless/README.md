# Hand-written Limitless page fixtures

**Synthetic. Not captured responses.** Every file here was typed by hand to
reproduce a page's STRUCTURE — the product link, the print table, the image
filename, the card-level reprint line. The same rule `probe/fixtures/` lives
under.

**The price table is omitted deliberately.** Real Limitless card pages carry
USD and EUR columns, TCGplayer and Cardmarket links, and a price history
block. That is provider price data, and it is not committed, not cached and
not persisted: `LimitlessAdapter._get_text` parses in memory and never calls
`cache_raw`. A fixture with a price table in it would put on disk exactly what
the adapter is written to avoid putting on disk.

The shapes here are taken from the observations in ADR-0042 — the real title
form, the body link form, the slug forms and the image filename — not from a
saved page.
