# Mobile app design brief

_Started 2026-08-13 08:01 UTC_

---

## User

Design a mobile app. Look at the design brief i have pasted here.

## Assistant

_[tool: update_todos]_

_[tool: github_get_tree]_

_[tool: github_read_files]_

_[tool: github_read_files]_

_[tool: github_search_code]_

_[tool: github_read_files]_

_[tool: github_read_files]_

_[tool: list_files]_

_[tool: list_files]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: dc_write]_

_[tool: write_file]_

_[tool: ready_for_verification]_

Two directions, no screens — as asked.

**1a Cabinet Ledger** — ledger spine, population as bar *mass*, magenta spent only on the 9→10 gap. No-pop form: hollow hatched rungs of equal height.
**1b Phosphor Scope** — instrument, population as *bloom heat*, one hero figure per screen in the pixel face. No-pop form: dotted rails that become the P(10) input.

Both sit inside the CRT Arcade system bound to this project, so the three faces (Press Start 2P / Chakra Petch / IBM Plex Mono tabular) and surface tokens are fixed — the directions differ in ink assignment, spine, and ladder encoding.

Two things to note: the repo has no `web/` code committed, so there was no existing UI to match — this is from the contracts only. And the schema's eighth screen is Trend Radar, not Manual Entry; the red panel lists that plus seven other places the design would assume more than the schema guarantees. Pick a direction (or a hybrid) and I'll build the eight screens × five states.

## User

Found issues — fixing…

## Assistant

_[tool: run_script]_

_[tool: ready_for_verification]_

Widened the grade-label gutter to 48px and the money column to 112px, both `nowrap` — labels and prices no longer wrap and the numeral columns align.

## User

Going with 1a as the base — bar height for population reads
instantly, and spending magenta once on the 9->10 gap is the
right discipline. Pull three things from 1b: underline badges
instead of boxes (keeping stale as the solid red slug), one
hero figure per screen, and YOUR P(10) TAP TO SET inline on
the empty rail rather than a separate button.

Before building all eight: show me Grading Lab in three
states side by side — computed, refusal with the nine-item
checklist, and no-population with manual P(10). That screen
carries the most weight and I want to see its worst state
before you commit the pattern across everything.

On Trend Radar: skip it. The trend data source isn't approved
yet and it's the screen most likely to change. Build the
eight from the brief with Manual Entry, not Trend Radar.

I'm sending the schema gaps you flagged back to Claude Code
to fix — assume refusal.missing will become objects with
titles and deep links, and that manual-entry rows will be
markable everywhere.

## Assistant

_[tool: github_read_files]_

_[tool: dc_html_str_replace]_

_[tool: ready_for_verification]_

_[tool: ready_for_verification]_

_[tool: write_file]_

Turn 2 is at the top: Grading Lab in **2a computed**, **2b refusal**, **2c no-population**, all 390-wide, all on 1a's spine with the three pulls from 1b.

Key decisions in the worst state (2b): the screen doesn't empty out — known inputs (cost, centering, pop total) stay visible and only derived figures go to `—`; the nine-item checklist *becomes* the content, numbered, each row 44pt with a deep link, and there's no "accept defaults" affordance because there are no defaults. Hero panel is `9 INPUTS` in amber rather than a fake zero.

Two calls worth overruling, both noted under the screens:
- Hero is EV, not P(10) needed. EV is the decision, but P(10) transfers better across Signals/Comparison — if you want one hero figure that's the same everywhere, it should be P(10).
- 2c spends the magenta gap ink on *positive* headroom. That makes magenta "the gap" rather than "the problem" — fine, but it's a real widening of the rule before it propagates to eight screens.

Say go and I'll build the eight (Manual Entry in, Trend Radar out) on this pattern.

## User

Go — build the eight (Manual Entry in, Trend Radar out) on
this pattern. 2b is exactly right.

Two calls:

Magenta on positive headroom: keep it. The gap is signed, and
you already word it. One gap ink is worth more than switching
on sign.

Hero: EV stays in 2a, but NOT in 2c. A large green +$46.10
above "your number, not a measured one" is a confident figure
resting on a probability I typed. Where P(10) is user-
supplied, the hero is the needed-vs-yours pair — "you need
0.341, you're claiming 0.480" — and EV drops to secondary.
That distinction should hold anywhere a user-supplied input
drives a headline figure.

Note: I'm having the fixture arithmetic checked. Some values
may shift. Design the relationships, don't tune to specific
digits.

## Assistant

_[tool: github_read_files]_

_[tool: dc_write]_

_[tool: write_file]_

_[tool: ready_for_verification]_

_[tool: ready_for_verification]_

## User

Found issues — fixing…

## Assistant

_[tool: dc_html_str_replace]_

_[tool: ready_for_verification]_

Rebuilt the Track Record excess-return chart as two fixed 36px halves around the zero rule — bars sized in px, no percentage margins, so nothing escapes the panel.

## User

Type passes on phone — Press Start 2P stays as assigned.
Hero ruling looks right in 3d2.

One bug: in the P(10) RAILS panel, MODELLED and POP-IMPL
render as hatched bars at ~60% width with a "—" value. A
hatched bar of any length implies a magnitude, and there is
no modelled P(10) for One Piece. Draw unmeasured rails at
full width (the rail exists, unfilled) or at zero — never at
an arbitrary intermediate length. The user's rail is the only
one that should have a length, since it's the only one with
a value.

Otherwise go — finish the eight.

## Assistant

_[tool: dc_html_str_replace]_

_[tool: ready_for_verification]_

_[tool: grep]_

_[tool: ready_for_verification]_

## User

Two things.

1. Track Record hero is wrong. Hit rate is the most
   flattering and least informative number on that screen —
   you can hit 58% and still lose money. The hero must be
   median excess return vs the game index. Hit rate drops to
   the three-window row.

   And the window choice makes it worse: 30D shows 58.4%
   while 90D shows 46.8%, below a coin flip. Never let a
   screen pick its own most flattering window. Either the
   longest available window is hero, or all three carry
   equal weight.

2. The fixtures were corrected — grading_lab's figures were
   invented and every one is now recomputed by the engine.
   Ladder is now raw 140 / 8 88 / 9 142 / 10 540, needed
   P(10) 0.301 against modelled 0.199.

   One relationship to check rather than a digit: modelled
   P(10) can NEVER exceed pop-implied P(10). The selection
   haircut only moves mass down. The old 0.412 / 0.286 pair
   had it inverted. If that ordering is encoded anywhere as
   a visual relationship, it's teaching the opposite of the
   truth.

Otherwise go — the state matrix, then the prototype.

## User

Two things.

1. Track Record hero is wrong. Hit rate is the most
   flattering and least informative number on that screen —
   you can hit 58% and still lose money. The hero must be
   median excess return vs the game index. Hit rate drops to
   the three-window row.

   And the window choice makes it worse: 30D shows 58.4%
   while 90D shows 46.8%, below a coin flip. Never let a
   screen pick its own most flattering window. Either the
   longest available window is hero, or all three carry
   equal weight.

2. The fixtures were corrected — grading_lab's figures were
   invented and every one is now recomputed by the engine.
   Ladder is now raw 140 / 8 88 / 9 142 / 10 540, needed
   P(10) 0.301 against modelled 0.199.

   One relationship to check rather than a digit: modelled
   P(10) can NEVER exceed pop-implied P(10). The selection
   haircut only moves mass down. The old 0.412 / 0.286 pair
   had it inverted. If that ordering is encoded anywhere as
   a visual relationship, it's teaching the opposite of the
   truth.

Otherwise go — the state matrix, then the prototype.

## Assistant

_[tool: run_script]_

_[tool: grep]_

_[tool: run_script]_

_[tool: ready_for_verification]_

_[tool: dc_html_str_replace]_

_[tool: ready_for_verification]_

## User

Found issues — fixing…

## Assistant

_[tool: run_script]_

_[tool: ready_for_verification]_

Added `white-space:nowrap` to the three grade labels in the 4c cached ladder — "PSA 10" no longer wraps and the rows share a baseline again.

Turn 4 (state matrix) is now above turn 3: the 8×5 grid, plus full-size loading, empty, error and stale treatments. Both of your rulings are in — Track Record's hero is median excess return at the longest window with hit rate demoted to an equal-weight three-window row, and pop-implied now sits *above* modelled everywhere with the shorter modelled bar and a stated ceiling, so the haircut only ever reads downward.

Four blockers listed for the prototype — the sharpest is per-figure staleness, which 4d needs and the schema can't express. Say go and I'll build the clickable Home → Signals → Card Detail → Grading Lab path with refusal and stale reachable inside it.

## User

Track Record hero is right, and "either number alone is the
flattering half" is the sentence that screen needed.

Minimum-n floor is my call: show the median at n>=30, and
mark anything below n=50 as not-actionable. Those are
different thresholds on purpose — 30 to display, 50 before I
trade on it.

Two things:

1. The by-play-type bars carry hit rates with no n. Grade gap
   at 38% could be five calls. Every other figure in this app
   shows its sample size; that panel must too.

2. Don't develop the CRACK & RESUBMIT panel further. It's
   currently showing Model A's Charizard figures under a
   regrade label — the regrade model isn't wired, and its
   conditional prior is a different distribution from the base
   rate. I'm having that resolved. Treat 9 -> 10 as unbuilt
   until I confirm.

Otherwise go — build the clickable Home -> Signals -> Card
Detail -> Grading Lab path with refusal and stale reachable
inside it.

## Assistant

_[tool: run_script]_

_[tool: dc_write]_

_[tool: write_file]_

_[tool: ready_for_verification]_

_[tool: ready_for_verification]_

## User

Found issues — fixing…

## Assistant

_[tool: dc_js_str_replace]_

_[tool: ready_for_verification]_

Fixed — a filled row now reads just "Set." The remaining count lives in one place, the header counter, so there's nothing to drift.

The prototype is live: tap alerts on Home into Signals, the Charizard row into Card Detail, then into Grading Lab. The feed-state switch above the frame reaches stale (gap and EV withheld, slug on the driving input) and refusal (the nine-item checklist, tappable, count moves and no row disappears).

