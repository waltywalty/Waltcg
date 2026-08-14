# CRT ARCADE — Design System

A vintage-arcade design language for **trading-card tools**: chunky pixels, CRT glow, neon
phosphor on a purple void. Built for card databases, collection trackers, deck builders and
price/EV tooling — surfaces where dense numeric data has to stay legible while the frame
feels like a cabinet in a dark room.

**This is an original system.** It deliberately contains no reproduction of any real
trading-card game's frames, rarity symbols, type icons, logos or trade dress.

## Sources
| Source | Status |
|---|---|
| Written brand brief ("CRT ARCADE", supplied in chat by *Waltcg*) | The only source. Colors, type scale, spacing, form rules, rarity ladder and card anatomy are transcribed from it verbatim. |
| Codebase / repository | None supplied. |
| Figma file | None supplied. |
| Slide deck / templates | None supplied — no slide kit was authored. |
| Logo / brand assets | **None supplied.** No mark was drawn; the brand name is set in the display face wherever a logo would go (see `assets/README.md`). |

Everything not fixed by the brief (product surfaces, component inventory, copy voice) was
authored here from the brief's logic and should be reviewed.

---

## Index

| Path | What |
|---|---|
| `styles.css` | Single entry point consumers link. `@import` list only. |
| `tokens/fonts.css` | Google Fonts import + family tokens |
| `tokens/colors.css` | Cabinet surfaces, phosphor inks, text inks, semantic aliases |
| `tokens/typography.css` | Type scale, tracking, utility classes (`.crt-label`, `.crt-num`, `.crt-title`) |
| `tokens/spacing.css` | 4px scale, border widths, radius 0 |
| `tokens/effects.css` | Hard offset shadows, focus ring, quantized motion, scanline + foil recipes |
| `tokens/rarity.css` | Rarity inks, bloom radii, `[data-rarity]` scopes |
| `tokens/base.css` | Element resets, link + focus + selection defaults |
| `guidelines/*.card.html` | 17 foundation specimen cards (Colors, Type, Spacing, Brand) |
| `components/` | React primitives — see below |
| `ui_kits/cabinet/` | Cabinet UI kit: browse, card detail, deck builder, price feed |
| `assets/README.md` | Asset inventory + the missing-logo note |
| `SKILL.md` | Agent Skills entry point |

### Components
Grouped by concern; each directory has `<Name>.jsx`, `<Name>.d.ts`, `<Name>.prompt.md` and one card HTML.

- **core/** — `Button`, `IconButton`, `Panel`, `Badge`, `Tag`
- **forms/** — `Field`, `Input`, `Select`, `Checkbox`, `Radio`, `Switch`
- **feedback/** — `Dialog`, `Toast`, `Tooltip`
- **navigation/** — `Tabs`
- **cards/** — `TradingCard`, `RarityBadge`, `Scanlines`, `StatFigure`

No source defined a component inventory, so this is the standard primitive set sized to the
brief. **Intentional additions** (domain components the brief's card anatomy and rarity
ladder require):

- `TradingCard` — the brief's five-zone card anatomy; the system's signature artifact.
- `RarityBadge` — states rarity outside the frame; owns the ink/bloom ladder (exports `RARITY`).
- `Scanlines` — the mandated screen-wide overlay as a wrapper.
- `StatFigure` — every figure must be tabular mono with an uppercase mono label; this enforces it.
- `Field` — carries the label/hint/error typography rules so each control doesn't restate them.
- `Panel` replaces the conventional `Card` (the word "card" means a trading card here).

---

## CONTENT FUNDAMENTALS

**Voice: an arcade cabinet that respects the player.** Terse, confident, mechanical — the
tone of a machine reporting state, never a brand being friendly. Short declaratives. No
exclamation marks, no jokes, no hedging.

- **Person.** Second person for the user's things ("your cabinet", "your packs"), imperative
  for actions ("Add to deck", "Scrap copy"). Never first-person plural — the system is not
  a "we".
- **Casing.** Three registers, used strictly:
  - *Labels, badges, buttons, table headers, footers* → UPPERCASE mono, tracked 0.14em: `COLLECTOR NUMBER`, `ADD TO DECK`, `24H`.
  - *Headlines and card names* → UPPERCASE pixel face: `CARD INDEX`, `VOLT WYRM`.
  - *Prose and rules text* → sentence case in the UI face: "On play: deal 2 damage to a tapped unit."
- **Length.** Buttons 1–3 words. Labels ≤ 3 words. Toast bodies one sentence. Rules text
  two sentences max.
- **Numbers.** Always written as figures, never spelled out, always mono/tabular.
  Sign is explicit for deltas: `+2.15`, `−0.80`, `+4.2%`. Currency leads with `$`,
  two decimals, amber.
- **Errors state the fix, not the failure mood.** "Deck illegal — 4 over limit", not
  "Oops, something went wrong". Destructive confirms name the consequence: "Voltage Rush
  and its 60 cards will be removed from your cabinet."
- **Arcade vocabulary is used only where it's accurate**: *cabinet* (the user's
  collection), *credits* (account balance), *insert coin* (the sign-in / start CTA),
  *scrap* (delete), *feed* (live prices). Don't stack more than one per screen.
- **Emoji: never.** Not in UI, not in copy. Unicode is allowed only as pixel-shaped glyphs
  where an icon would be wrong: `▼` (select caret), `×` (dismiss), `✕` (checkbox mark),
  `←` (back), `+ −` (steppers).
- **Empty states are one uppercase mono line**: "NO CARDS MATCH THESE FILTERS".

Examples, good vs bad:

| Good | Bad |
|---|---|
| `SAVED — Voltage Rush synced to your collection.` | `Nice! We saved your deck 🎉` |
| `Deck illegal — 4 over limit` | `Uh oh, your deck isn't quite right` |
| `EV / PACK  +2.15` | `Expected value is about two dollars` |
| `Scrap copy` | `Remove this card from my collection` |

---

## VISUAL FOUNDATIONS

**The metaphor is a cabinet in a dark room.** Depth comes from stacked opaque surfaces and
hard offset shadows — never blur, never elevation gradients.

### Color
- **Surfaces, deepest to raised:** void `#11071F` (page, shadows) → screen `#1B0F33`
  (panels) → screen-lift `#271650` (headers, active rows, toasts) → bezel `#3A2470`
  (borders, chart bars). **Never pure black — the void is purple.**
- **Phosphor inks, one job each, never decorative:** cyan `#4DE8F0` (primary, links,
  focus-adjacent), magenta `#FF3DA5` (secondary, holo, chart accents), amber `#FFB627`
  (warning, secret rarity, currency, focus ring), lime `#7CFF4D` (success, positive EV),
  red `#FF4D5E` (destructive, negative EV).
- **Max two inks per component.** A cyan button with an amber badge inside is out of spec.
- **Colour is never the only carrier of meaning** — every ink is paired with a word
  (`Legal`, `Banned`, `+`, `−`).
- Text: primary `#EDE6FF`, dim `#A794D4` (prose, rules), muted `#6B5A9E` (labels,
  footers), on-fill `#11071F`.

### Typography
- **Press Start 2P** — display only. Marquee 24px, title 13px, card nameplate 10px.
  **Never body copy, never below 10px, and no glow under 13px.**
- **Chakra Petch** — all prose and rules text. 16px / 1.55. Weights 400 and 600.
- **IBM Plex Mono** — every figure and every label. Data 14px with tabular numerals on;
  labels 11px uppercase, letter-spacing 0.14em.
- Line lengths stay short — the pixel face is wide; headlines are 1–3 words.

### Spacing & layout
- 4px scale only: 4, 8, 12, 16, 24, 32, 48, 64. Nothing between, no percentages for gaps.
- Panels: 16px body padding, 12px/16px header padding. Screen gutters 24px. Sibling groups
  are always flex/grid with `gap` — never margin chains.
- Layout is fixed-chrome: a persistent top bar (screen-lift, 4px bottom border), an
  optional 240px filter rail left, a 280px stats rail right. Content grids are
  `auto-fill minmax(220px, 1fr)`.

### Form
- **Border radius 0 everywhere.** No exceptions — not on inputs, avatars, chips or images.
- Borders 2px default; 4px for emphasis (modals, invalid panels, top-bar rule).
- **Depth = hard offset shadow `4px 4px 0 var(--void)`**; modals use `8px 8px 0`.
  Never a blurred or spread shadow, never an inner shadow except the inset 3px tab underline.
- Buttons **travel into their shadow** on press: `translate(4px,4px)` + shadow removed.
- Inputs are sunken wells: void background inside a bezel border.

### States
- **Hover:** border and text step up one ink level (muted → dim, bezel → cyan); fills do
  not lighten and opacity is never used to fade.
- **Press:** the 4px travel described above. Tabs/toggles hold the sunken look while active.
- **Focus:** `3px solid var(--amber)` with 2px offset, on everything interactive, always.
- **Disabled:** `opacity: .4` + `grayscale(.5)`, cursor not-allowed.
- **Selected:** cyan border + screen-lift background + cyan text.

### Motion
- Quantized only: `steps(4, end)`, 90ms (`--dur-fast`) to 180ms (`--dur-slow`).
  Motion snaps in visible increments; nothing eases, nothing bounces, nothing springs.
- Animate transform, border-color, background — never blur or box-shadow spread.
- No page transitions, no parallax, no entrance animations on load.

### Texture, transparency & imagery
- **Scanline overlay** on every full view: 1px `rgba(17,7,31,.42)` line every 3px, plus a
  radial vignette to the void. One instance per view, at the root, `pointer-events: none`.
- **Dither, never gradient.** Where a gradient would be used, use a checkerboard: the foil
  is a 6px magenta/cyan `repeating-conic-gradient` at `mix-blend-mode: screen`, 0.35
  opacity, **confined to the art window**.
- Transparency is used in exactly three places: the scanline lines, the modal scrim
  (`rgba(17,7,31,.82)`), and alternating table rows (`rgba(39,22,80,.4)`).
  **No backdrop blur anywhere.**
- Art windows are fixed 4:3 with a visible 8px pixel grid over them; `image-rendering:
  pixelated` globally. Imagery should read cool and dark — purple/cyan biased, high
  contrast, low detail, no warm photographic skin tones and no film grain (the scanlines
  are the grain).
- No protection gradients over images; use a solid screen-lift bar instead.

### Rarity — the signature
Rarity is **phosphor burn**, not a corner symbol: each tier raises ink heat and bloom
radius so it reads at thumbnail size.

| Tier | Ink | Bloom |
|---|---|---|
| Common | `#A794D4` | none |
| Uncommon | `#7CFF4D` | 6px |
| Rare | `#4DE8F0` | 14px |
| Holo | `#FF3DA5` | 22px + dithered foil |
| Secret | `#FFB627` | 34px + amber card name |

### Card anatomy (top to bottom)
1. **Nameplate** — name left (pixel face 10px), resource cost right (amber, tabular).
2. **Art window** — fixed 4:3, pixel grid visible through it.
3. **Type bar** — creature type first, then rarity; **max three badges**.
4. **Rules box** — UI face, min 64px tall.
5. **Footer** — set code, collector number, illustrator; uppercase mono, muted.
6. **Foil** — 6px dithered magenta/cyan checkerboard, screen-blended, art window only.

### ALWAYS / NEVER
**Always:** radius 0 · hard offset shadows · tabular numerals · uppercase mono labels tracked
0.14em · spacing from the 4px scale · a word beside every ink.
**Never:** body copy in the pixel face · smooth gradients (dither instead) · more than two
inks in one component · glow on text under 13px · colour as the only carrier of meaning ·
pure black.

---

## ICONOGRAPHY

No icon set, icon font, SVG sprite or PNG glyph was supplied with the brief, and none was
drawn here (hand-rolled SVG is out of scope for a design system).

- **Substitution (flagged):** UI icons come from **Lucide** via CDN
  (`https://unpkg.com/lucide@0.474.0/dist/umd/lucide.js`), rendered as
  `<i data-lucide="search"></i>` + `lucide.createIcons()`. Lucide's 2px stroke and square
  line caps match the system's 2px borders; sizes are 16px in `IconButton`, 20px maximum.
  Icons inherit `currentColor`, so they take their tone's ink and never introduce a
  second colour. **If you have a real (ideally pixel/bitmap) icon set, send it — Lucide's
  smooth curves are the one part of this system that isn't chunky.**
- **Unicode pixel glyphs** are used where an icon would be wrong: `▼` select caret,
  `×` dismiss, `✕` checkbox mark, `←` back, `+ −` quantity steppers.
- **Emoji: never**, in any surface.
- **Logo: none exists.** `assets/` contains no mark; the wordmark specimen sets "CRT ARCADE"
  in Press Start 2P with a cyan glow. Drop a real `assets/logo.svg` in and the thumbnail
  and top bar should switch to it.
- Rarity, legality and EV are never expressed as icons — they are ink + word (see
  `RarityBadge`, `Badge`).

---

## Fonts — substitution note
All three families are Google-hosted originals, loaded via one `@import` in
`tokens/fonts.css`: Press Start 2P, Chakra Petch, IBM Plex Mono. **No lookalike
substitution was needed.** No binaries are vendored into the project — if you need offline
or self-hosted webfonts, send the `.woff2` files and they'll be added with local
`@font-face` rules.
