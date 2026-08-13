# waltcg

A private research tool for trading card game collecting and investing, covering
One Piece TCG (English and Japanese), Pokémon TCG (English and Japanese) and
Riftbound (English). Single user. Not a product, not a service, not published
anywhere.

## Status

Early. Currently building the data layer and evaluating source coverage.

The Reddit ingestion module described below **is not running** — it is pending
approval of a Data API access request under Reddit's Responsible Builder Policy,
and will not make authenticated calls until that approval is granted.

Chinese-language printings (Pokémon Simplified and Traditional, One Piece
Simplified) are under evaluation as a manual-entry tier: no Western data source
carries them, so raw prices are entered by hand and the models consume them
unchanged. See `probe/COVERAGE.md`.

## What it does

Joins card market data with discussion activity to help me make better buying and
grading decisions on individual cards. Three things it computes:

1. **Grading expected value** — given a raw card's price, current grading fees,
   turnaround time, marketplace fees, shipping, FX and the population-report
   grade distribution, what probability of a gem-mint grade is required for a
   submission to break even. The output is a break-even probability rather than a
   point estimate, because the probability is the uncertain input.
2. **Grade-spread screening** — where the price gap between adjacent grades looks
   out of line with the population gap, relative to comparable cards in the same
   game and era.
3. **Interest trend** — whether discussion of a specific card is rising
   abnormally, measured against both that card's own recent baseline and the
   baseline for its game overall.

Every output carries its source, its as-of timestamp and its sample size. Every
alert it produces is written to an immutable ledger and scored forward at 7, 30
and 90 days, so the tool keeps a public-to-me record of whether its own
suggestions worked.

## Reddit Data API usage

This section describes exactly what the Reddit component does, for anyone
reviewing the access request.

**Read-only.** The application requests read scopes only. It makes no posts,
comments, votes, edits, reports or private messages. It has no write path — there
is no code in this repository that calls a write endpoint.

**What it reads.** On a schedule of once every few hours (not continuous
polling), it fetches recent posts and comments from a fixed list of subreddits
(see `config/sentiment.yaml`), matches the text against a list of card names, and
records a daily count per card.

**What it stores.** A daily aggregate count per card per subreddit, and
permalinks to matching threads. It does **not** store post or comment bodies in
bulk. Where a thread is surfaced in my dashboard, it appears as a link that opens
on reddit.com — the tool sends me to Reddit to read, it does not substitute for
reading there.

**What it does not do.** No redistribution of Reddit content. No republishing or
mirroring. No use of Reddit data as training input for any model. No public
interface of any kind — the dashboard is local and single-user.

**Volume.** Roughly 200–500 requests per day, well below the free tier's 100
queries-per-minute ceiling. Rate limiting and backoff are implemented in the
client.

**User-Agent.** Follows the required
`<platform>:<appid>:<version> (by /u/<username>)` format.

**Subreddits.** Listed in `config/sentiment.yaml`. The list is fixed and small;
expanding it would require a change to that file and a corresponding update to
the access request.

## Why this can't be a Devvit app

Devvit apps run inside Reddit and are installed by a moderator into a specific
subreddit. This is not a community tool and I am not a moderator — there is no
subreddit for it to live in.

More fundamentally, its whole function is a join: aggregate discussion counts
across roughly a dozen subreddits, then combine that with external market data —
card marketplace prices, grading population reports, FX rates — held in a
database outside Reddit. That cross-subreddit, off-platform join has no
equivalent inside Devvit, and the output is a private application on my own
infrastructure rather than a Reddit-surface experience.

## Architecture

```
contracts/   response schemas, assumption registry, source map
ingest/      one adapter per data source, uniform interface
  reddit/    the Reddit client described above
store/       point-in-time database, append-only
resolve/     card identity resolution across sources
engine/      expected-value models, screens, index construction
alerts/      rule evaluation and the immutable outcome ledger
api/         local API serving the dashboard
web/         the dashboard
audit/       data integrity and correctness checks
config/      dated configuration — fees, grading tiers, subreddit list
probe/       source coverage probe (see probe/COVERAGE.md)
docs/        goal, audit protocol, source map, open issues, decisions
```

**Point-in-time by construction.** Every row carries both `as_of` (the date a
value refers to) and `observed_at` (when this system saw it). History is
append-only; corrections are new rows, never edits. A test suite asserts that no
calculation can read a value observed after the timestamp it is being evaluated
at.

**Money is never a bare number.** Every monetary value is stored as amount,
currency, the FX rate used and that rate's as-of date.

## Data handling

**No data of any kind is committed to this repository. Only code.**

- API responses are cached to a local directory that is gitignored
- The database is local and gitignored
- Credentials live in `.env`, gitignored, and are never referenced in committed
  code
- The coverage probe writes raw provider responses to `probe/out/`, which is
  gitignored. Its committed report carries coverage status and sample counts
  only — never price values

Several upstream data providers restrict redistribution of their price data. This
tool is for personal use, its output is not published, and no provider's data is
republished, resold, or exposed through any public interface.

## Deliberately out of scope

- Any automated buying, bidding or listing
- Any multi-user, sharing or social feature
- Any public API or hosted service
- Image-based grade prediction
- Deck building, meta analysis or competitive tier lists

## Setup

```sh
cp .env.example .env      # add your own API keys
pip install -r requirements.txt
python -m probe.coverage  # source coverage check
```

Runs on Python 3.11+. Scheduled ingestion runs as a GitHub Action; everything
else runs locally.

The coverage probe is stdlib-only and needs no dependencies — run
`python -m probe.coverage --offline` to regenerate its report without making any
network calls.
