#!/usr/bin/env python3
"""waltcg source-coverage probe.

Answers one question: for each game/language combo we care about, can the
three candidate sources actually deliver the fields the grading-EV and
grade-spread models need?

  tcgapi.dev              catalog resolution + raw/per-condition market price
  apitcg.com              second catalog opinion (agreement check)
  pokemonpricetracker.com graded comps (ebay.salesByGrade) + population

Design notes
------------
* Stdlib only. No pip install on the runner.
* Free tiers are 100 req/day per provider. Every call is budgeted, and a 429
  parks the provider (records PARTIAL) instead of raising.
* Endpoint shapes are *discovered*: each operation has an ordered list of
  candidate URL templates. The first that answers 2xx is pinned for the rest
  of the run, so discovery costs at most len(candidates) requests once.
  Every template can be overridden by env var without editing this file.
* Field extraction is tolerant: we search the response tree by key name
  rather than hardcoding one path, because the exact schemas could not be
  verified from the dev sandbox (the proxy blocks both hosts).
* Every raw response is written to probe/out/ (gitignored) so a run can be
  re-read without spending budget again.

Output policy
-------------
COVERAGE.md is committed to a PUBLIC repo. It carries coverage STATUS and
sample COUNTS only. No price values, ever. Prices live in probe/out/, which
is gitignored. `scrub_report()` is a backstop assertion on that rule, not the
primary mechanism -- the report builder only ever reads status/count fields.

Usage
-----
  python probe/coverage.py                # live run, needs TCGAPI_KEY / PPT_KEY
  python probe/coverage.py --offline      # no network; emits UNTESTED scaffold
  python probe/coverage.py --use-cache    # replay probe/out/ without spending budget
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
RAW_DIR = os.path.join(OUT_DIR, "raw")
REPORT_PATH = os.path.join(HERE, "COVERAGE.md")

# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------

FULL, PARTIAL, NONE, UNTESTED = "FULL", "PARTIAL", "NONE", "UNTESTED"
_RANK = {FULL: 3, PARTIAL: 2, NONE: 1, UNTESTED: 0}


def roll_up(statuses):
    """Combine per-card statuses into one combo-level status.

    A mix of tested and untested cards is PARTIAL, never FULL: if a 429 or a
    budget stop meant we never reached card 3, the combo has not earned a
    clean bill of health.
    """
    seen = [s for s in statuses if s]
    if not seen or all(s == UNTESTED for s in seen):
        return UNTESTED
    real = [s for s in seen if s != UNTESTED]
    if len(real) != len(seen):
        return PARTIAL
    if all(s == FULL for s in real):
        return FULL
    if all(s == NONE for s in real):
        return NONE
    return PARTIAL


# ---------------------------------------------------------------------------
# Cards under test -- 3 per Western combo, 2 per Chinese combo, 21 total
# ---------------------------------------------------------------------------
#
# Selection rule: recognisable chase cards with real secondary-market depth,
# and -- deliberately -- the SAME card across every language in which the
# printing exists. That makes the separation test sharp: if a source
# hands back one id (or one price) for both printings, it has collapsed them.
# `pair` links the two printings of one card.
#
# Riftbound is English-only -- there is no Japanese release -- so it has one
# combo and no separation test to run.
#
# `number` is an expected value used as a cross-check on whatever the API
# resolves, not as the lookup key. Where numbering is marked unverified the
# probe resolves by name + set only.

COMBOS = [
    ("one-piece", "EN", "One Piece EN"),
    ("one-piece", "JP", "One Piece JP"),
    ("pokemon", "EN", "Pokemon EN"),
    ("pokemon", "JP", "Pokemon JP"),
    ("riftbound", "EN", "Riftbound EN"),
    # Chinese-language editions. All three are confirmed official releases;
    # see CHINESE_TIER_NOTE for what was checked and what does not exist.
    ("pokemon", "CN-S", "Pokemon CN-Simplified"),
    ("pokemon", "CN-T", "Pokemon CN-Traditional"),
    ("one-piece", "CN-S", "One Piece CN-Simplified"),
]

# Combos we predict the Western sources cannot serve at all. Stated up front so
# a NONE row reads as a confirmed result rather than an unexplained hole.
EXPECTED_NONE = {"pokemon:CN-S", "pokemon:CN-T", "one-piece:CN-S"}

CARDS = [
    # -- One Piece EN ------------------------------------------------------
    dict(game="one-piece", lang="EN", pair="op-luffy-sec",
         name="Monkey.D.Luffy", set="Romance Dawn", set_code="OP01",
         number="OP01-121", rarity_hint="SEC"),
    dict(game="one-piece", lang="EN", pair="op-nami-sr",
         name="Nami", set="Romance Dawn", set_code="OP01",
         number="OP01-024", rarity_hint="SR"),
    dict(game="one-piece", lang="EN", pair="op-ace-sr",
         name="Portgas.D.Ace", set="Paramount War", set_code="OP02",
         number="OP02-013", rarity_hint="SR"),

    # -- One Piece JP (same codes; Bandai reuses numbering across languages)
    dict(game="one-piece", lang="JP", pair="op-luffy-sec",
         name="Monkey.D.Luffy", set="ROMANCE DAWN", set_code="OP01",
         number="OP01-121", rarity_hint="SEC"),
    dict(game="one-piece", lang="JP", pair="op-nami-sr",
         name="Nami", set="ROMANCE DAWN", set_code="OP01",
         number="OP01-024", rarity_hint="SR"),
    dict(game="one-piece", lang="JP", pair="op-ace-sr",
         name="Portgas.D.Ace", set="PARAMOUNT WAR", set_code="OP02",
         number="OP02-013", rarity_hint="SR"),

    # -- Pokemon EN --------------------------------------------------------
    dict(game="pokemon", lang="EN", pair="pkm-charizard-base",
         name="Charizard", set="Base Set", set_code="base1",
         number="4/102", rarity_hint="Holo Rare"),
    dict(game="pokemon", lang="EN", pair="pkm-umbreon-vmax",
         name="Umbreon VMAX", set="Evolving Skies", set_code="swsh7",
         number="215/203", rarity_hint="Alternate Art Secret Rare"),
    dict(game="pokemon", lang="EN", pair="pkm-charizard-ex-sir",
         name="Charizard ex", set="Obsidian Flames", set_code="sv3",
         number="223/197", rarity_hint="Special Illustration Rare"),

    # -- Pokemon JP (counterparts of the three above) ----------------------
    dict(game="pokemon", lang="JP", pair="pkm-charizard-base",
         name="Lizardon", set="Base (1996)", set_code="base-jp",
         number="006", rarity_hint="Holo"),
    dict(game="pokemon", lang="JP", pair="pkm-umbreon-vmax",
         name="Blacky VMAX", set="Eevee Heroes", set_code="s6a",
         number="189/069", rarity_hint="SA"),
    dict(game="pokemon", lang="JP", pair="pkm-charizard-ex-sir",
         name="Lizardon ex", set="Ruler of the Black Flame", set_code="sv3",
         number="108/108", rarity_hint="SAR"),

    # -- Riftbound EN (Origins, Oct 2025) ----------------------------------
    # Collector numbering not verified from the sandbox; resolve by name+set.
    dict(game="riftbound", lang="EN", pair="rift-jinx",
         name="Jinx", set="Origins", set_code="OGN",
         number=None, rarity_hint="Legend", number_unverified=True),
    dict(game="riftbound", lang="EN", pair="rift-viktor",
         name="Viktor", set="Origins", set_code="OGN",
         number=None, rarity_hint="Legend", number_unverified=True),
    dict(game="riftbound", lang="EN", pair="rift-leesin",
         name="Lee Sin", set="Origins", set_code="OGN",
         number=None, rarity_hint="Legend", number_unverified=True),

    # -- Pokemon Simplified Chinese (launched 28 Oct 2022, Pokemon Shanghai) --
    # Simplified sets track the SV-era Japanese releases with a C suffix.
    # Collector numbers unverified, so these resolve by name + set.
    dict(game="pokemon", lang="CN-S", api_lang="zh-Hans", pair="pkm-charizard-ex-sir",
         name="Charizard ex", set="Ruler of the Black Flame (Simplified)", set_code="csv3C",
         number=None, rarity_hint="SAR", number_unverified=True),
    dict(game="pokemon", lang="CN-S", api_lang="zh-Hans", pair="pkm-umbreon-ex-terastal",
         name="Umbreon ex", set="Terastal Gathering", set_code="csv9.5C",
         number=None, rarity_hint="SAR", number_unverified=True),

    # -- Pokemon Traditional Chinese (launched 9 Oct 2019, Taiwan / Hong Kong)
    # Caught up to Japan set-for-set after the initial compilations, so the
    # JP chase cards have direct Traditional counterparts.
    dict(game="pokemon", lang="CN-T", api_lang="zh-Hant", pair="pkm-umbreon-vmax",
         name="Umbreon VMAX", set="Eevee Heroes (Traditional)", set_code="CS-s6a",
         number=None, rarity_hint="SA", number_unverified=True),
    dict(game="pokemon", lang="CN-T", api_lang="zh-Hant", pair="pkm-charizard-ex-sir",
         name="Charizard ex", set="Ruler of the Black Flame (Traditional)", set_code="CS-sv3",
         number=None, rarity_hint="SAR", number_unverified=True),

    # -- One Piece Simplified Chinese (released Nov 2022) -------------------
    # Bandai numbers the Simplified printings with the same OP codes, so these
    # are the same collapse test as the EN/JP pair, one language further out.
    dict(game="one-piece", lang="CN-S", api_lang="zh-Hans", pair="op-luffy-sec",
         name="Monkey.D.Luffy", set="ROMANCE DAWN (Simplified)", set_code="OP01",
         number="OP01-121", rarity_hint="SEC"),
    dict(game="one-piece", lang="CN-S", api_lang="zh-Hans", pair="op-ace-sr",
         name="Portgas.D.Ace", set="PARAMOUNT WAR (Simplified)", set_code="OP02",
         number="OP02-013", rarity_hint="SR"),
]

# ---------------------------------------------------------------------------
# Endpoint candidates
# ---------------------------------------------------------------------------
#
# These could not be verified against live hosts (the dev sandbox proxy
# returns 403 CONNECT for tcgapi.dev and pokemonpricetracker.com), so each
# operation carries several plausible shapes and the probe pins whichever
# answers first. Override any list with a comma-separated env var to skip
# discovery entirely once the real shape is known:
#
#   TCGAPI_CATALOG_URLS, TCGAPI_PRICE_URLS, APITCG_CATALOG_URLS,
#   PPT_CARD_URLS, PPT_POP_URLS
#
# Placeholders: {game} {lang} {name} {number} {set} {set_code} {id}

ENDPOINTS = {
    "tcgapi.catalog": [
        "https://api.tcgapi.dev/v1/{game}/cards?search={name}&language={lang}",
        "https://api.tcgapi.dev/v1/cards?game={game}&search={name}&language={lang}",
        "https://tcgapi.dev/api/v1/{game}/cards?search={name}&language={lang}",
        "https://api.tcgapi.dev/v1/{game}/cards?name={name}&lang={lang}",
    ],
    "tcgapi.price": [
        "https://api.tcgapi.dev/v1/{game}/cards/{id}/prices",
        "https://api.tcgapi.dev/v1/prices?game={game}&cardId={id}",
        "https://api.tcgapi.dev/v1/{game}/prices/{id}",
        "https://tcgapi.dev/api/v1/{game}/cards/{id}/prices",
    ],
    "apitcg.catalog": [
        "https://apitcg.com/api/{game}/cards?name={name}",
        "https://apitcg.com/api/{game}/cards?property=code&value={number}",
        "https://www.apitcg.com/api/{game}/cards?name={name}",
    ],
    "ppt.card": [
        "https://www.pokemonpricetracker.com/api/v2/cards?search={name}&setId={set_code}",
        "https://www.pokemonpricetracker.com/api/v2/prices?search={name}",
        "https://www.pokemonpricetracker.com/api/v1/prices?name={name}&setId={set_code}",
        "https://www.pokemonpricetracker.com/api/v1/cards?search={name}",
    ],
    "ppt.pop": [
        "https://www.pokemonpricetracker.com/api/v2/population?cardId={id}",
        "https://www.pokemonpricetracker.com/api/v2/cards/{id}/population",
        "https://www.pokemonpricetracker.com/api/v1/population?name={name}",
    ],
}

# apitcg.com uses its own game slugs.
APITCG_GAME = {"one-piece": "one-piece", "pokemon": "pokemon", "riftbound": "riftbound"}

FREE_TIER_PER_DAY = 100

# Fill these from each provider's pricing page to get a monthly total in the
# report. Left None deliberately: the probe cannot read a pricing page, and
# inventing subscription costs would make the recommendation worthless.
PAID_TIERS = {
    "tcgapi.dev": {"monthly_usd": None, "req_per_day": None,
                   "pricing_url": "https://tcgapi.dev/pricing"},
    "apitcg.com": {"monthly_usd": None, "req_per_day": None,
                   "pricing_url": "https://apitcg.com/pricing"},
    "pokemonpricetracker.com": {"monthly_usd": None, "req_per_day": None,
                                "pricing_url": "https://www.pokemonpricetracker.com/pricing"},
}

# Production load assumptions used for the paid-tier sizing math.
WATCHLIST_CARDS = int(os.environ.get("PROBE_WATCHLIST_CARDS", "250"))
REFRESHES_PER_DAY = int(os.environ.get("PROBE_REFRESHES_PER_DAY", "1"))
CALLS_PER_CARD = {"tcgapi.dev": 2, "apitcg.com": 1, "pokemonpricetracker.com": 2}

MIN_SAMPLE = 5          # median 90d graded sales below this is inadequate
SAMPLE_WINDOW_DAYS = 90

# Which Chinese-language editions actually exist, checked before adding combos
# rather than assumed. Verified August 2026.
CHINESE_TIER_NOTE = """\
### Which Chinese editions exist

Checked before adding these combos, not assumed:

- **Pokemon Simplified Chinese -- exists.** Announced September 2022 by Pokemon
  Shanghai Toy Ltd and launched 28 October 2022, the first Simplified Chinese
  printing of the TCG. Opened with three *Sun & Moon: Crossing the Sky* sets;
  SV-era sets now track the Japanese releases with a `C` suffix (e.g. `csv9.5C`,
  Terastal Gathering).
- **Pokemon Traditional Chinese -- exists.** Launched 9 October 2019 for Taiwan
  and Hong Kong, opening with *All Stars Collection* (`AC1a`). Early sets were
  compilations to catch up with Japan; since then it tracks Japanese sets
  one-for-one, so the JP chase cards have direct counterparts.
- **One Piece Simplified Chinese -- exists.** Released November 2022, with its
  own anniversary sets and Simplified-exclusive promos. Bandai reuses the `OP`
  collector codes, so a Simplified printing is the same id-collision test as
  the EN/JP pair, one language further out.
- **One Piece Traditional Chinese -- does not exist.** Bandai's own Asian
  regional rules list the Japanese and Simplified Chinese versions as the
  editions sold across Japan, Hong Kong, Taiwan, Singapore, Malaysia,
  Indonesia, the Philippines, Thailand and China. Hong Kong and Taiwan are
  served by those two, not by a Traditional Chinese localisation. No combo
  added.

### Hypothesis

All three Chinese combos are expected to return `NONE` from every Western
source. tcgapi.dev and apitcg.com are built around the EN and JP printings, and
pokemonpricetracker tracks Western graded comps. A `NONE` here is a **result**
that routes the combo, not a coverage gap to be chased.

### Manual-entry tier

Chinese cards are expected to become a manual-entry tier: raw prices are
supplied by hand from Xianyu and Taobao, and the EV models run on them
unchanged. Nothing downstream needs to know where the raw price came from --
grading EV, grade-spread screening and interest trend all take a raw price and
a population distribution as inputs, and none of them care whether that price
arrived over HTTP or by hand. What is lost is refresh rate and an as-of
timestamp that updates itself, so manual rows should carry their own entry date
and be treated as staler than API-sourced rows.
"""

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:80]


def card_slug(card):
    return slugify(f"{card['game']}-{card['lang']}-{card['name']}-{card.get('number') or card['set_code']}")


def walk_dicts(obj):
    """Yield every dict in a JSON tree, outermost first."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def _norm_key(k):
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def find_key(obj, *names, want=None):
    """First value in the tree whose key matches any of `names` (loosely)."""
    targets = {_norm_key(n) for n in names}
    for d in walk_dicts(obj):
        for k, v in d.items():
            if _norm_key(k) in targets and v not in (None, "", [], {}):
                if want is None or isinstance(v, want):
                    return v
    return None


def to_number(v):
    """Coerce a price-ish or count-ish value to float. None if not numeric."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        for k in ("value", "amount", "price", "median", "average", "avg", "mean"):
            if k in v:
                n = to_number(v[k])
                if n is not None:
                    return n
        return None
    if isinstance(v, str):
        m = re.search(r"-?\d[\d,]*\.?\d*", v.replace(" ", ""))
        if m:
            try:
                return float(m.group().replace(",", ""))
            except ValueError:
                return None
    return None


def first_record(payload):
    """Pull the most likely single card record out of a search response."""
    if payload is None:
        return None
    if isinstance(payload, dict):
        for k in ("data", "results", "cards", "items", "records", "response"):
            if k in payload:
                inner = payload[k]
                if isinstance(inner, list):
                    return inner[0] if inner else None
                if isinstance(inner, dict):
                    return inner
        # a bare card object
        if any(_norm_key(k) in {"id", "cardid", "name"} for k in payload):
            return payload
    if isinstance(payload, list):
        return payload[0] if payload else None
    return None


def key_paths(obj, prefix="", out=None, depth=0):
    """Structural digest: key paths only, never values."""
    if out is None:
        out = set()
    if depth > 6:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.add(p)
            key_paths(v, p, out, depth + 1)
    elif isinstance(obj, list) and obj:
        key_paths(obj[0], f"{prefix}[]", out, depth + 1)
    return out


# ---------------------------------------------------------------------------
# HTTP layer: budgeted, cached, 429-tolerant
# ---------------------------------------------------------------------------


class Provider:
    def __init__(self, name, key, auth_styles):
        self.name = name
        self.key = key
        self.auth_styles = list(auth_styles)
        self.auth_style = self.auth_styles[0] if self.auth_styles else None
        self.requests = 0
        self.rate_limited = False
        self.exhausted = False
        self.errors = []
        self.quota_headers = {}

    def headers(self, style=None):
        h = {"Accept": "application/json", "User-Agent": "waltcg-coverage-probe/1.0"}
        style = style or self.auth_style
        if self.key and style == "x-api-key":
            h["x-api-key"] = self.key
        elif self.key and style == "bearer":
            h["Authorization"] = f"Bearer {self.key}"
        elif self.key and style == "query":
            pass
        return h

    def status_note(self):
        if not self.key:
            return "no API key in env"
        if self.rate_limited:
            return "rate limited (429)"
        if self.exhausted:
            return "local request budget exhausted"
        return "ok"


class Prober:
    def __init__(self, args):
        self.args = args
        self.offline = args.offline
        self.use_cache = args.use_cache
        self.budget = args.budget
        self.timeout = args.timeout
        self.pinned = {}          # op -> url template that answered
        self.attempts = []        # (op, template, status) discovery log
        self.shapes = {}          # op -> sorted key paths
        self.safe_tokens = set()  # subscription costs, allowlisted for scrub_report
        self.providers = {
            "tcgapi.dev": Provider("tcgapi.dev", os.environ.get("TCGAPI_KEY", "").strip(),
                                   ["x-api-key", "bearer"]),
            # apitcg.com issues its own key; fall back to TCGAPI_KEY so a
            # single-key setup still gets tried rather than silently skipped.
            "apitcg.com": Provider("apitcg.com",
                                   (os.environ.get("APITCG_KEY")
                                    or os.environ.get("TCGAPI_KEY", "")).strip(),
                                   ["x-api-key", "bearer"]),
            "pokemonpricetracker.com": Provider("pokemonpricetracker.com",
                                                os.environ.get("PPT_KEY", "").strip(),
                                                ["bearer", "x-api-key"]),
        }
        os.makedirs(RAW_DIR, exist_ok=True)

    # -- raw request ------------------------------------------------------

    def _cache_path(self, provider, url):
        h = hashlib.sha1(url.encode()).hexdigest()[:16]
        d = os.path.join(RAW_DIR, slugify(provider))
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{h}.json")

    def _record(self, path, rec):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rec, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"  ! could not cache {path}: {e}", file=sys.stderr)

    def fetch(self, provider_name, url):
        """Return (payload, status, note). Never raises on network problems."""
        p = self.providers[provider_name]
        cache = self._cache_path(provider_name, url)

        if self.use_cache and os.path.exists(cache):
            try:
                with open(cache, encoding="utf-8") as f:
                    rec = json.load(f)
                return rec.get("json"), rec.get("status", 0), "cache"
            except (OSError, ValueError):
                pass

        if self.offline:
            return None, 0, "offline"
        if not p.key:
            return None, 0, "no-key"
        if p.rate_limited:
            return None, 429, "provider parked after 429"
        if p.requests >= self.budget:
            p.exhausted = True
            return None, 0, "budget exhausted"

        payload = status = None
        note = ""
        for attempt, style in enumerate(p.auth_styles if p.auth_style is None
                                        else [p.auth_style] + [s for s in p.auth_styles
                                                               if s != p.auth_style]):
            if p.requests >= self.budget:
                p.exhausted = True
                return None, 0, "budget exhausted"
            p.requests += 1
            req = urllib.request.Request(url, headers=p.headers(style))
            body = ""
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    status = r.status
                    body = r.read().decode("utf-8", "replace")
                    for hk in ("x-ratelimit-limit", "x-ratelimit-remaining",
                               "ratelimit-limit", "retry-after"):
                        if r.headers.get(hk):
                            p.quota_headers[hk] = r.headers.get(hk)
            except urllib.error.HTTPError as e:
                status = e.code
                try:
                    body = e.read().decode("utf-8", "replace")
                except Exception:
                    body = ""
                if e.code == 429:
                    p.rate_limited = True
                    note = "429 rate limited"
                    if e.headers.get("retry-after"):
                        p.quota_headers["retry-after"] = e.headers.get("retry-after")
            except urllib.error.URLError as e:
                status = 0
                note = f"network error: {e.reason}"
            except Exception as e:                     # noqa: BLE001 - never crash a run
                status = 0
                note = f"error: {e.__class__.__name__}: {e}"

            try:
                payload = json.loads(body) if body else None
            except ValueError:
                payload = None
                if status and 200 <= status < 300:
                    note = "200 but body was not JSON"

            self._record(cache, {
                "url": url, "provider": provider_name, "auth_style": style,
                "status": status, "fetched_at": now_iso(),
                "note": note, "json": payload,
                "body_head": body[:2000] if payload is None else None,
            })

            if status in (401, 403) and attempt == 0 and len(p.auth_styles) > 1:
                note = f"{status} with {style}, retrying alternate auth"
                continue
            if status and 200 <= status < 300:
                p.auth_style = style
            break

        if status == 429:
            p.rate_limited = True
        if status and not (200 <= status < 300) and note == "":
            note = f"HTTP {status}"
        if note and note not in p.errors:
            p.errors.append(note)
        return payload, status or 0, note

    # -- operation with endpoint discovery --------------------------------

    def call(self, op, provider_name, card, extra=None):
        ctx = {
            "game": card["game"],
            # api_lang carries the code a provider is likely to accept
            # (zh-Hans / zh-Hant); lang is our own display label.
            "lang": card.get("api_lang") or card["lang"],
            "name": urllib.parse.quote(card["name"]),
            "number": urllib.parse.quote(card.get("number") or ""),
            "set": urllib.parse.quote(card.get("set") or ""),
            "set_code": urllib.parse.quote(card.get("set_code") or ""),
            "id": urllib.parse.quote(str((extra or {}).get("id") or "")),
        }
        if provider_name == "apitcg.com":
            ctx["game"] = APITCG_GAME.get(card["game"], card["game"])

        env_override = os.environ.get(op.replace(".", "_").upper() + "_URLS")
        templates = ([t.strip() for t in env_override.split(",") if t.strip()]
                     if env_override else list(ENDPOINTS[op]))
        if op in self.pinned:
            templates = [self.pinned[op]]

        for tmpl in templates:
            if "{id}" in tmpl and not ctx["id"]:
                continue
            if "{number}" in tmpl and not ctx["number"]:
                continue
            try:
                url = tmpl.format(**ctx)
            except KeyError:
                continue
            payload, status, note = self.fetch(provider_name, url)
            self.attempts.append({"op": op, "template": tmpl, "status": status,
                                  "note": note, "card": card_slug(card)})
            if status and 200 <= status < 300:
                self.pinned.setdefault(op, tmpl)
                if payload is not None:
                    self.shapes.setdefault(op, set()).update(key_paths(payload))
                return payload, status, note
            if note in ("offline", "no-key", "budget exhausted") or self.providers[provider_name].rate_limited:
                return None, status, note
        return None, 0, "no candidate endpoint answered"


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

CONDITION_KEYS = ["nearmint", "nm", "lightlyplayed", "lp", "moderatelyplayed", "mp",
                  "heavilyplayed", "hp", "damaged", "dmg", "excellent", "good", "played"]

GRADE_TARGETS = {"psa10": ["psa10", "10", "psa 10", "gem mint 10"],
                 "psa9": ["psa9", "9", "psa 9", "mint 9"],
                 "psa8": ["psa8", "8", "psa 8", "nm-mt 8"]}


def extract_catalog(payload):
    rec = first_record(payload)
    if rec is None:
        return {"found": False}
    cid = find_key(rec, "id", "cardId", "card_id", "uuid", "slug")
    if isinstance(cid, (dict, list)):
        cid = None
    return {
        "found": True,
        "id": str(cid) if cid is not None else None,
        "artist": find_key(rec, "artist", "illustrator", "artistName", want=str),
        "rarity": find_key(rec, "rarity", "rarityName", "rarityCode", want=str),
        "release_date": find_key(rec, "releaseDate", "released_at", "release",
                                 "setReleaseDate", "releasedOn", want=str),
        "name": find_key(rec, "name", "cardName", want=str),
        "number": find_key(rec, "number", "code", "cardNumber", "collectorNumber"),
        "set": find_key(rec, "setName", "set", "expansion", want=str),
        "language": find_key(rec, "language", "lang", "locale", want=str),
    }


def extract_raw_price(payload):
    """Raw (ungraded) market price + per-condition breakdown. Values stay local."""
    if payload is None:
        return {"raw_price": None, "conditions": {}, "currency": None}
    raw = None
    for k in ("marketPrice", "market_price", "market", "raw", "rawPrice",
              "ungraded", "price", "midPrice", "median"):
        v = find_key(payload, k)
        n = to_number(v)
        if n is not None:
            raw = n
            break
    conditions = {}
    for d in walk_dicts(payload):
        for k, v in d.items():
            nk = _norm_key(k)
            if nk in CONDITION_KEYS:
                n = to_number(v)
                if n is not None:
                    conditions[nk] = n
    return {
        "raw_price": raw,
        "conditions": conditions,
        "currency": find_key(payload, "currency", "currencyCode", want=str),
    }


def _grade_bucket(container, aliases):
    """Find one grade's entry inside a salesByGrade container (dict or list)."""
    if isinstance(container, dict):
        for k, v in container.items():
            if _norm_key(k) in {_norm_key(a) for a in aliases}:
                return v
    if isinstance(container, list):
        for item in container:
            if isinstance(item, dict):
                g = item.get("grade", item.get("gradeLabel", item.get("label")))
                if g is not None and _norm_key(g) in {_norm_key(a) for a in aliases}:
                    return item
    return None


def extract_graded(payload):
    """ebay.salesByGrade -> per-grade price + sample size."""
    out = {"source_path": None, "grades": {}, "window_days": None}
    if payload is None:
        return out

    container = None
    ebay = find_key(payload, "ebay")
    if isinstance(ebay, dict):
        sbg = find_key(ebay, "salesByGrade")
        if sbg:
            container, out["source_path"] = sbg, "ebay.salesByGrade"
    if container is None:
        sbg = find_key(payload, "salesByGrade", "sales_by_grade", "gradedSales")
        if sbg:
            container, out["source_path"] = sbg, "salesByGrade"
    if container is None:
        return out

    win = find_key(payload, "windowDays", "periodDays", "days", "period")
    n = to_number(win)
    out["window_days"] = int(n) if n else None

    for grade, aliases in GRADE_TARGETS.items():
        bucket = _grade_bucket(container, aliases)
        if bucket is None:
            out["grades"][grade] = {"price": None, "count": None}
            continue
        price = None
        for k in ("averagePrice", "avgPrice", "average", "median", "medianPrice",
                  "price", "value", "mean"):
            price = to_number(find_key(bucket, k) if isinstance(bucket, dict) else None)
            if price is not None:
                break
        if price is None:
            price = to_number(bucket)
        count = None
        for k in ("count", "sales", "numSales", "sampleSize", "n", "salesCount",
                  "quantity", "volume"):
            c = to_number(find_key(bucket, k) if isinstance(bucket, dict) else None)
            if c is not None:
                count = int(c)
                break
        out["grades"][grade] = {"price": price, "count": count}
    return out


def extract_population(payload):
    if payload is None:
        return {"populationByGrader": None, "totalPopulation": None, "combinedGemRate": None}
    pbg = find_key(payload, "populationByGrader", "population_by_grader", "populations")
    total = to_number(find_key(payload, "totalPopulation", "total_population", "totalPop"))
    gem = to_number(find_key(payload, "combinedGemRate", "combined_gem_rate", "gemRate"))
    return {
        "populationByGrader": pbg if isinstance(pbg, (dict, list)) else None,
        "graders": sorted(pbg.keys()) if isinstance(pbg, dict) else None,
        "totalPopulation": int(total) if total is not None else None,
        "combinedGemRate": gem,
    }


# ---------------------------------------------------------------------------
# Per-card probe
# ---------------------------------------------------------------------------


def norm_cmp(a, b):
    if a is None or b is None:
        return "UNKNOWN"
    sa, sb = re.sub(r"\W", "", str(a).lower()), re.sub(r"\W", "", str(b).lower())
    if not sa or not sb:
        return "UNKNOWN"
    return "AGREE" if (sa == sb or sa in sb or sb in sa) else "DISAGREE"


def probe_card(prober, card):
    res = {"card": card, "slug": card_slug(card)}

    # 1. catalog: tcgapi.dev
    payload, status, note = prober.call("tcgapi.catalog", "tcgapi.dev", card)
    res["tcgapi_catalog"] = extract_catalog(payload)
    res["tcgapi_catalog"]["http"] = {"status": status, "note": note}

    # 2. catalog: apitcg.com
    payload, status, note = prober.call("apitcg.catalog", "apitcg.com", card)
    res["apitcg_catalog"] = extract_catalog(payload)
    res["apitcg_catalog"]["http"] = {"status": status, "note": note}

    # agreement between the two catalogs
    a, b = res["tcgapi_catalog"], res["apitcg_catalog"]
    res["agreement"] = {f: norm_cmp(a.get(f), b.get(f))
                        for f in ("artist", "rarity", "release_date", "number")}

    # 3. pricing from tcgapi.dev (needs the id we just resolved)
    cid = a.get("id")
    if cid:
        payload, status, note = prober.call("tcgapi.price", "tcgapi.dev", card, {"id": cid})
    else:
        payload, status, note = None, 0, "no card id resolved"
    res["price"] = extract_raw_price(payload)
    res["price"]["http"] = {"status": status, "note": note}

    # 4. graded comps + population from pokemonpricetracker
    payload, status, note = prober.call("ppt.card", "pokemonpricetracker.com", card)
    res["graded"] = extract_graded(payload)
    res["graded"]["http"] = {"status": status, "note": note}
    res["pop"] = extract_population(payload)
    res["pop"]["http"] = {"status": status, "note": note}

    # only spend a second PPT call if population was missing from the card doc
    if res["pop"]["totalPopulation"] is None and status and 200 <= status < 300:
        ppt_id = find_key(payload, "id", "cardId") if payload else None
        p2, s2, n2 = prober.call("ppt.pop", "pokemonpricetracker.com", card,
                                 {"id": ppt_id if isinstance(ppt_id, str) else ""})
        if p2 is not None:
            res["pop"] = extract_population(p2)
            res["pop"]["http"] = {"status": s2, "note": n2}

    res["status"] = score_card(res)
    return res


NOT_REACHED = ("offline", "no-key", "budget exhausted", "provider parked after 429",
               "429 rate limited")


def not_reached(note):
    """True when we never got an answer, as opposed to getting an empty one."""
    return any(note == n or note.startswith(n) for n in NOT_REACHED)


def score_card(res):
    a, b = res["tcgapi_catalog"], res["apitcg_catalog"]
    untested_catalog = (not_reached(a["http"]["note"]) and not_reached(b["http"]["note"]))

    # catalog
    if untested_catalog:
        catalog = UNTESTED
    elif not a.get("found") and not b.get("found"):
        catalog = NONE
    else:
        best = a if a.get("found") else b
        fields = [best.get("id"), best.get("artist"), best.get("rarity"), best.get("release_date")]
        if a.get("found") and b.get("found"):
            for f in ("artist", "rarity", "release_date"):
                fields.append(a.get(f) or b.get(f))
        catalog = FULL if all(fields[:4]) else PARTIAL

    # raw price. A missing card id is only a real NONE if the catalog lookup
    # actually happened -- otherwise the price endpoint was never reached.
    pr = res["price"]
    if not_reached(pr["http"]["note"]):
        price = UNTESTED
    elif pr["http"]["note"] == "no card id resolved" and catalog == UNTESTED:
        price = UNTESTED
    elif pr["raw_price"] is None and not pr["conditions"]:
        price = NONE
    elif pr["raw_price"] is not None and len(pr["conditions"]) >= 2:
        price = FULL
    else:
        price = PARTIAL

    # graded comps
    g = res["graded"]
    gstat = {}
    for grade in ("psa10", "psa9", "psa8"):
        e = g["grades"].get(grade) or {}
        if not_reached(g["http"]["note"]):
            gstat[grade] = UNTESTED
        elif e.get("count") == 0:
            # The field exists but nothing sold. That is a schema hit, not a
            # comp -- never let it read as FULL.
            gstat[grade] = PARTIAL
        elif e.get("price") is not None and e.get("count") is not None:
            gstat[grade] = FULL
        elif e.get("price") is not None or e.get("count") is not None:
            gstat[grade] = PARTIAL
        else:
            gstat[grade] = NONE

    # population
    p = res["pop"]
    if not_reached(p["http"]["note"]):
        pop = UNTESTED
    else:
        have = [p["populationByGrader"] is not None,
                p["totalPopulation"] is not None,
                p["combinedGemRate"] is not None]
        pop = FULL if all(have) else (PARTIAL if any(have) else NONE)

    counts = [e.get("count") for e in g["grades"].values() if e.get("count") is not None]

    # "The source answered and has no such card" is a finding. "We never got an
    # answer" is not. Only the first justifies reporting an absence.
    def answered(rec):
        s = (rec.get("http") or {}).get("status") or 0
        return 200 <= s < 300

    return {"catalog": catalog, "price": price, "pop": pop,
            "psa10": gstat["psa10"], "psa9": gstat["psa9"], "psa8": gstat["psa8"],
            "graded_sales_total": sum(counts) if counts else None,
            "catalog_absent_confirmed": (catalog == NONE
                                         and (answered(a) or answered(b))),
            "graded_absent_confirmed": (gstat["psa10"] == NONE and answered(g))}


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def source_label(cards_res, kind):
    srcs = set()
    for r in cards_res:
        if kind == "catalog":
            if r["tcgapi_catalog"].get("found"):
                srcs.add("tcgapi.dev")
            if r["apitcg_catalog"].get("found"):
                srcs.add("apitcg.com")
        elif kind == "price":
            if r["price"]["raw_price"] is not None or r["price"]["conditions"]:
                srcs.add("tcgapi.dev")
        else:
            g, p = r["graded"], r["pop"]
            if g["grades"] or p["totalPopulation"] is not None:
                if any(e.get("price") or e.get("count") for e in g["grades"].values()) \
                        or p["totalPopulation"] is not None:
                    srcs.add("pokemonpricetracker")
    return "+".join(sorted(srcs)) if srcs else "--"


def _resolved_id(entry):
    return entry["tcgapi_catalog"].get("id") or entry["apitcg_catalog"].get("id")


def language_separation(by_pair, game, lang):
    """Does this language's printing stay distinct from every other language's?

    Generalised beyond EN/JP: with Chinese printings in the set, a card can
    collide with any other language, so each counterpart is checked in turn.
    """
    verdicts, detail = [], []
    for pair, entries in by_pair.items():
        same_game = [e for e in entries if e["card"]["game"] == game]
        mine = [e for e in same_game if e["card"]["lang"] == lang]
        others = [e for e in same_game if e["card"]["lang"] != lang]
        if not mine or not others:
            continue
        me = mine[0]
        my_id, my_price = _resolved_id(me), me["price"].get("raw_price")
        for other in others:
            ol = other["card"]["lang"]
            o_id, o_price = _resolved_id(other), other["price"].get("raw_price")
            if my_id is None and o_id is None:
                verdicts.append(UNTESTED)
                detail.append(f"{pair} vs {ol}: neither printing resolved")
            elif my_id is None or o_id is None:
                verdicts.append(PARTIAL)
                detail.append(f"{pair} vs {ol}: only one printing resolved")
            elif my_id == o_id:
                verdicts.append(NONE)
                detail.append(f"{pair} vs {ol}: SAME id -- printings collapsed")
            elif my_price is not None and o_price is not None:
                if my_price != o_price:
                    verdicts.append(FULL)
                    detail.append(f"{pair} vs {ol}: distinct ids, distinct prices")
                else:
                    verdicts.append(PARTIAL)
                    detail.append(f"{pair} vs {ol}: distinct ids but identical price")
            else:
                verdicts.append(PARTIAL)
                detail.append(f"{pair} vs {ol}: distinct ids, price missing one side")
    if not verdicts:
        return UNTESTED, "no cross-language pair resolved"
    # One confirmed collision is disqualifying. Do not let it average away
    # against a counterpart that simply failed to resolve.
    if NONE in verdicts:
        return NONE, "; ".join(detail)
    return roll_up(verdicts), "; ".join(detail)


def aggregate(results):
    by_pair = {}
    for r in results:
        by_pair.setdefault(r["card"]["pair"], []).append(r)

    rows = []
    for game, lang, label in COMBOS:
        cards_res = [r for r in results if r["card"]["game"] == game and r["card"]["lang"] == lang]
        if not cards_res:
            continue
        st = [r["status"] for r in cards_res]
        counts = [s["graded_sales_total"] for s in st if s["graded_sales_total"] is not None]
        median_sales = statistics.median(counts) if counts else None

        if median_sales is None:
            sample = UNTESTED if all(s["psa10"] == UNTESTED for s in st) else NONE
        elif median_sales >= MIN_SAMPLE:
            sample = FULL
        elif median_sales > 0:
            sample = PARTIAL
        else:
            sample = NONE

        # A game published in one language only has nothing to separate.
        # Saying UNTESTED there would imply a test worth running.
        if len({l for g, l, _ in COMBOS if g == game}) < 2:
            sep, sep_detail = "N/A", "single-language game -- no counterpart printing exists"
        else:
            sep, sep_detail = language_separation(by_pair, game, lang)

        rows.append({
            "combo": label, "game": game, "lang": lang,
            "catalog": roll_up([s["catalog"] for s in st]),
            "catalog_src": source_label(cards_res, "catalog"),
            "agreement": summarize_agreement(cards_res),
            "price": roll_up([s["price"] for s in st]),
            "price_src": source_label(cards_res, "price"),
            "psa10": roll_up([s["psa10"] for s in st]),
            "psa9": roll_up([s["psa9"] for s in st]),
            "psa8": roll_up([s["psa8"] for s in st]),
            "graded_src": source_label(cards_res, "graded"),
            "sample": sample,
            "median_sales": median_sales,
            "per_card_sales": [s["graded_sales_total"] for s in st],
            "pop": roll_up([s["pop"] for s in st]),
            "separation": sep,
            "separation_detail": sep_detail,
            "expected_none": f"{game}:{lang}" in EXPECTED_NONE,
            "catalog_absent_confirmed": sum(1 for s in st if s["catalog_absent_confirmed"]),
            "graded_absent_confirmed": sum(1 for s in st if s["graded_absent_confirmed"]),
            "n_cards": len(st),
            "cards": cards_res,
        })
    for row in rows:
        row["verdict"], row["why"] = verdict_for(row)
    return rows


def summarize_agreement(cards_res):
    vals = []
    for r in cards_res:
        vals.extend(r["agreement"].values())
    if not vals or all(v == "UNKNOWN" for v in vals):
        return "not comparable"
    if any(v == "DISAGREE" for v in vals):
        n = sum(1 for v in vals if v == "DISAGREE")
        return f"{n} field disagreement(s)"
    return "agree"


def verdict_for(row):
    if row["catalog"] == UNTESTED:
        return "UNTESTED", "probe has not run against live endpoints yet"
    # A predicted absence that the sources confirm is a routing decision, not
    # a failure: these cards move to the manual-entry tier.
    if row["expected_none"] and row["catalog"] == NONE:
        confirmed = ("confirmed by %d/%d empty 2xx responses"
                     % (row["catalog_absent_confirmed"], row["n_cards"])
                     if row["catalog_absent_confirmed"] else
                     "sources did not answer; absence assumed, not confirmed")
        return "MANUAL TIER", ("no Western source carries this printing -- hypothesis held (%s); "
                               "raw prices entered by hand from Xianyu/Taobao" % confirmed)
    if row["catalog"] == NONE:
        return "NO GO", "catalog resolution fails -- cards cannot be identified"
    if row["separation"] == NONE:
        return "NO GO", "printings of different languages collapse to one id/price"
    graded_ok = row["psa10"] in (FULL, PARTIAL) and row["psa9"] in (FULL, PARTIAL)
    sample_ok = row["median_sales"] is not None and row["median_sales"] >= MIN_SAMPLE
    if row["price"] in (FULL, PARTIAL) and graded_ok and sample_ok:
        return "GO", "catalog + raw price + PSA 9/10 comps, median sample >= %d" % MIN_SAMPLE

    # "never reached" is not the same finding as "reached and empty". A 429 or
    # a spent budget must not be reported as an absence of graded data.
    graded_untested = row["psa10"] == UNTESTED and row["psa9"] == UNTESTED
    if graded_untested:
        return "INCONCLUSIVE", ("catalog and raw price resolve, but the graded source was never "
                                "reached (rate limit or budget) -- re-run before classifying")
    if row["price"] in (FULL, PARTIAL):
        missing = []
        if not graded_ok:
            missing.append("no PSA 9/10 comps")
        if not sample_ok:
            m = row["median_sales"]
            missing.append("no graded sales returned" if m is None
                           else "median graded sample %s < %d" % (fmt_median(m), MIN_SAMPLE))
        return "RAW ONLY", "screener works; grading models blocked (%s)" % ", ".join(missing)
    return "NO GO", "no usable raw price feed"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

PRICE_LEAK = re.compile(
    r"[$£¥€]\s?\d"          # currency symbol followed by a digit
    r"|\b\d+\.\d{2}\b"                      # 2-dp decimal, i.e. a money amount
    r"|\b(?:USD|JPY|EUR|GBP)\s?\d",
    re.IGNORECASE,
)


def scrub_report(text, safe_tokens=()):
    """Backstop: refuse to write a report containing provider price data.

    `safe_tokens` are subscription costs rendered from the local PAID_TIERS
    constant. Those are our own notes on what an API plan costs, never a card
    price pulled from a response, so they are masked before scanning. Anything
    else that looks like money is a bug and stops the write.
    """
    probe = text
    for tok in sorted(set(safe_tokens), key=len, reverse=True):
        if tok:
            probe = probe.replace(tok, "<tier-cost>")
    bad = PRICE_LEAK.findall(probe)
    if bad:
        raise SystemExit(
            "REFUSING TO WRITE COVERAGE.md: price-shaped values detected "
            f"({bad[:5]}). Prices must stay in probe/out/ (gitignored)."
        )
    return text


def fmt_cell(status, src=None):
    return f"{status}" + (f" ({src})" if src and src != "--" and status != UNTESTED else "")


def fmt_median(v):
    if v is None:
        return "--"
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"


def paid_tier_section(rows, prober):
    lines = []
    verdicts = {r["combo"]: r["verdict"] for r in rows}
    all_untested = all(v == "UNTESTED" for v in verdicts.values())
    inconclusive = any(v == "INCONCLUSIVE" for v in verdicts.values())
    any_go = any(v == "GO" for v in verdicts.values())
    pokemon_go = any(v == "GO" for c, v in verdicts.items() if c.startswith("Pokemon"))
    raw_needed = any(v in ("GO", "RAW ONLY") for v in verdicts.values())

    if all_untested:
        lines.append("_No combo has been probed yet, so nothing below is a recommendation._ "
                     "The request math is real (it depends only on watchlist size); the buy/skip "
                     "column stays `PENDING` until a live run fills in the matrix.\n")

    lines.append(f"Sizing assumption: **{WATCHLIST_CARDS} cards** on the watchlist, "
                 f"refreshed **{REFRESHES_PER_DAY}x/day**. Free tiers are "
                 f"{FREE_TIER_PER_DAY} req/day each.\n")
    if any(r["verdict"] == "MANUAL TIER" for r in rows):
        lines.append("Manual-tier cards are excluded from this math -- they consume no API "
                     "budget, which is the one upside of hand-entry.\n")
    lines.append("| Provider | Needed for | Projected req/day | Free tier enough? | Buy? | Monthly |")
    lines.append("|---|---|---|---|---|---|")

    decisions = []
    for prov, per_card in CALLS_PER_CARD.items():
        need = WATCHLIST_CARDS * per_card * REFRESHES_PER_DAY
        enough = "yes" if need <= FREE_TIER_PER_DAY else "no"
        if prov == "tcgapi.dev":
            used_for = "catalog + raw/per-condition price (every combo)"
            buy = "BUY" if raw_needed else "SKIP"
            why = "the only raw-price feed in the stack" if raw_needed else "nothing downstream uses it"
        elif prov == "apitcg.com":
            used_for = "second catalog opinion only"
            disagreements = any("disagreement" in r["agreement"] for r in rows)
            buy = "BUY" if disagreements else "SKIP"
            why = ("catalogs disagree, so the cross-check is load-bearing"
                   if disagreements else
                   "catalogs agree where both resolve; a paid second catalog buys nothing. "
                   "Keep the free tier as a spot-check")
        else:
            used_for = "graded comps + population (Pokemon only)"
            if pokemon_go:
                buy, why = "BUY", "grading-EV model depends on it and Pokemon combos are GO"
            elif inconclusive:
                buy, why = "PENDING", ("the graded source was rate-limited this run, so its "
                                       "coverage is unknown -- re-run before deciding")
            else:
                buy, why = "SKIP", ("no combo reaches GO on graded comps, so there is nothing "
                                    "to pay for yet")
        if all_untested:
            buy = "PENDING"
            why = "no live run yet -- cannot judge"
        tier = PAID_TIERS.get(prov, {})
        cost = tier.get("monthly_usd")
        cost_s = "not recorded" if cost is None else f"${cost:.0f}"
        if cost is not None:
            prober.safe_tokens.add(cost_s)
        lines.append(f"| {prov} | {used_for} | {need} | {enough} | **{buy}** | {cost_s} |")
        decisions.append((prov, buy, why, cost))

    known = [c for _, b, _, c in decisions if b == "BUY" and c is not None]
    unknown_buys = [p for p, b, _, c in decisions if b == "BUY" and c is None]
    lines.append("")
    if all_untested:
        lines.append("**Monthly total: pending the first live run.**")
    elif not any(b == "BUY" for _, b, _, _ in decisions):
        lines.append("**Monthly total: nothing to buy.** No provider clears the bar for a paid "
                     "plan on this run -- see the per-provider calls below.")
    elif unknown_buys:
        lines.append(
            f"**Monthly total: cannot be computed.** {', '.join(unknown_buys)} are marked BUY but "
            "their subscription prices are not recorded. Fill `PAID_TIERS` in `probe/coverage.py` "
            "from each provider's pricing page and re-run; the total is then computed here. "
            "(The probe reads card data, not pricing pages, and guessed subscription costs would "
            "make this recommendation worthless.)")
    else:
        total_s = f"${sum(known):.0f}"
        prober.safe_tokens.add(total_s)
        lines.append(f"**Monthly total: {total_s}.**")
    lines.append("")
    for prov, buy, why, _ in decisions:
        lines.append(f"- **{prov} -- {buy}.** {why}.")
    if not any_go and not all_untested and not inconclusive:
        lines.append("")
        lines.append("- Overall: nothing here justifies a graded-data subscription yet. Buy the raw "
                     "price feed, keep the graded provider on free tier, and re-probe once the "
                     "blocked combos have population depth.")
    obs = {p.name: p.quota_headers for p in prober.providers.values() if p.quota_headers}
    if obs:
        lines.append("")
        lines.append("Observed rate-limit headers during the run: `%s`" % json.dumps(obs))
    return "\n".join(lines)


def build_report(rows, prober, ran_live):
    ts = now_iso()
    L = []
    A = L.append

    A("# Source coverage probe")
    A("")
    if ran_live:
        A(f"Generated by `probe/coverage.py` at **{ts}**.")
    else:
        A(f"Scaffold generated by `probe/coverage.py --offline` at **{ts}**. "
          "**No live calls have been made.** Every cell is `UNTESTED` until the "
          "`probe` workflow runs with real API keys.")
    A("")
    A("> **Public repo policy.** This file carries coverage status and sample *counts* only. "
      "No price values appear here, by design -- that would be redistributing provider price "
      "data. Raw payloads and all prices stay in `probe/out/`, which is gitignored.")
    A("")

    # provider health
    A("## Provider status")
    A("")
    A("| Provider | Requests spent | State |")
    A("|---|---|---|")
    for p in prober.providers.values():
        A(f"| {p.name} | {p.requests} | {p.status_note()} |")
    A("")

    # 1 matrix
    A("## 1. Coverage matrix")
    A("")
    A("`FULL` = every probed card in the combo returned the field. `PARTIAL` = some did, "
      "or the field came back incomplete. `NONE` = no card returned it. `UNTESTED` = not "
      "reached (no key, budget, or 429). `N/A` = the test does not apply to this combo.")
    A("")
    A("| Combo | Catalog | Raw price | PSA 10 comp | PSA 9 comp | Sample adequacy | Pop data | Language separation |")
    A("|---|---|---|---|---|---|---|---|")
    for r in rows:
        A("| **{combo}** | {cat} | {price} | {p10} | {p9} | {samp} | {pop} | {sep} |".format(
            combo=r["combo"],
            cat=fmt_cell(r["catalog"], r["catalog_src"]),
            price=fmt_cell(r["price"], r["price_src"]),
            p10=fmt_cell(r["psa10"], r["graded_src"]),
            p9=fmt_cell(r["psa9"], r["graded_src"]),
            samp=r["sample"],
            pop=fmt_cell(r["pop"], r["graded_src"]),
            sep=r["separation"]))
    A("")
    A("Catalog cross-check (tcgapi.dev vs apitcg.com):")
    A("")
    for r in rows:
        A(f"- {r['combo']}: {r['agreement']}")
    A("")
    A("Language separation detail (each language vs every counterpart printing):")
    A("")
    for r in rows:
        A(f"- {r['combo']}: {r['separation_detail']}")
    A("")

    # 2 sample depth
    A(f"## 2. Graded sample depth ({SAMPLE_WINDOW_DAYS}-day window)")
    A("")
    A(f"Median graded sale count across the 3 probed cards. Flagged when below **{MIN_SAMPLE}** -- "
      "under that, a PSA comp is a coincidence, not a price.")
    A("")
    A("| Combo | Per-card graded sales | Median | Adequate? |")
    A("|---|---|---|---|")
    for r in rows:
        per = ", ".join("--" if c is None else str(c) for c in r["per_card_sales"])
        med = fmt_median(r["median_sales"])
        if r["sample"] == UNTESTED:
            flag = "UNTESTED"
        elif r["median_sales"] is None:
            flag = "**NO -- source returned no graded sales**"
        elif r["median_sales"] >= MIN_SAMPLE:
            flag = "yes"
        else:
            flag = f"**NO -- below {MIN_SAMPLE}**"
        A(f"| {r['combo']} | {per} | {med} | {flag} |")
    A("")

    # 3 go / no-go
    A("## 3. Go / no-go")
    A("")
    A("- **GO** -- catalog resolves, raw price present, PSA 9 and 10 comps present, "
      f"median graded sample >= {MIN_SAMPLE}.")
    A("- **RAW ONLY** -- the screener works, the grading models do not.")
    A("- **NO GO** -- resolution fails, or two language printings merge into one record.")
    A("- **INCONCLUSIVE** -- the graded source was never reached (429 or budget). Not a finding; "
      "re-run.")
    A("- **MANUAL TIER** -- no Western source carries the printing, as predicted. Raw prices come "
      "in by hand; see section 4.")
    A("")
    A("| Combo | Verdict | Reason |")
    A("|---|---|---|")
    for r in rows:
        A(f"| **{r['combo']}** | **{r['verdict']}** | {r['why']} |")
    A("")
    if not ran_live:
        A("**Prior expectation, to be confirmed or refuted by the first live run (not a finding):** "
          "Riftbound EN is expected to land on `RAW ONLY` -- the game launched late 2025, so there "
          "should be little or no graded population yet, which starves the PSA comps while leaving "
          "the raw screener usable. If the run disagrees, the run wins.")
        A("")

    # 4 chinese tier
    A("## 4. Chinese-language tier")
    A("")
    A(CHINESE_TIER_NOTE)
    A("")
    A("### Hypothesis vs result")
    A("")
    A("| Combo | Predicted | Catalog | Graded | Confirmed absent | Outcome |")
    A("|---|---|---|---|---|---|")
    for r in rows:
        if not r["expected_none"]:
            continue
        if r["catalog"] == UNTESTED:
            outcome = "not yet run"
        elif r["catalog"] == NONE:
            outcome = ("**held** -- absence confirmed by empty 2xx responses"
                       if r["catalog_absent_confirmed"] else
                       "**held, weakly** -- sources never answered, so absence is assumed")
        else:
            outcome = "**refuted** -- a Western source does carry this printing"
        A("| {c} | NONE | {cat} | {g} | {n}/{t} cards | {o} |".format(
            c=r["combo"], cat=r["catalog"], g=r["psa10"],
            n=r["catalog_absent_confirmed"], t=r["n_cards"], o=outcome))
    A("")

    # 5 paid tiers
    A("## 5. Paid tiers")
    A("")
    A(paid_tier_section(rows, prober))
    A("")

    # appendices
    A("## Appendix A -- cards probed")
    A("")
    A("Chase cards with real secondary-market depth. Where a printing exists in both "
      "languages the *same* card is probed in each, so the separation test is "
      "sharp: one shared id means the source has collapsed the printings.")
    A("")
    A("| Combo | Card | Set | Expected no. | Resolved id (tcgapi.dev) | Pair |")
    A("|---|---|---|---|---|---|")
    for r in rows:
        for c in r["cards"]:
            card = c["card"]
            num = card.get("number") or "_unverified_"
            if card.get("number_unverified"):
                num = f"{num} (numbering unverified)"
            rid = c["tcgapi_catalog"].get("id") or "--"
            A(f"| {r['combo']} | {card['name']} | {card['set']} | {num} | {rid} | `{card['pair']}` |")
    A("")

    A("## Appendix B -- endpoint discovery")
    A("")
    A("Endpoint shapes were not verifiable from the dev sandbox (its proxy returns "
      "`403 CONNECT` for both hosts), so each operation tries candidate URL templates and "
      "pins the first that answers. If a row below is all failures, correct the template via "
      "the matching `*_URLS` env var -- no code change needed.")
    A("")
    if prober.attempts:
        A("| Operation | Template | HTTP | Note |")
        A("|---|---|---|---|")
        seen = set()
        for at in prober.attempts:
            k = (at["op"], at["template"])
            if k in seen:
                continue
            seen.add(k)
            A(f"| `{at['op']}` | `{at['template']}` | {at['status'] or '--'} | {at['note'] or ''} |")
    else:
        A("_No requests attempted (offline scaffold)._")
    A("")
    A("Pinned templates: " + (", ".join(f"`{k}` -> `{v}`" for k, v in prober.pinned.items())
                              if prober.pinned else "_none_"))
    A("")

    A("## Appendix C -- response shape digest")
    A("")
    A("Key paths only, no values -- enough to fix field extraction without shipping "
      "provider data into a public repo.")
    A("")
    if prober.shapes:
        for op, paths in sorted(prober.shapes.items()):
            A(f"**`{op}`**")
            A("")
            A("```")
            for p in sorted(paths)[:60]:
                A(p)
            A("```")
            A("")
    else:
        A("_No responses captured._")
        A("")

    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description="waltcg source-coverage probe")
    ap.add_argument("--offline", action="store_true",
                    help="make no network calls; emit the UNTESTED scaffold")
    ap.add_argument("--use-cache", action="store_true",
                    help="replay cached responses in probe/out/ before spending budget")
    ap.add_argument("--budget", type=int, default=int(os.environ.get("PROBE_BUDGET", "90")),
                    help="max requests per provider (free tiers are 100/day)")
    ap.add_argument("--timeout", type=int, default=20)
    args = ap.parse_args()

    prober = Prober(args)

    if not args.offline:
        missing = [n for n, p in prober.providers.items() if not p.key]
        if missing:
            print(f"warning: no API key for {', '.join(missing)} -- "
                  "those columns will report UNTESTED", file=sys.stderr)

    results = []
    for card in CARDS:
        print(f"probing {card['game']}/{card['lang']}: {card['name']}", file=sys.stderr)
        results.append(probe_card(prober, card))

    os.makedirs(OUT_DIR, exist_ok=True)
    # Full results, prices included, stay here. probe/out/ is gitignored.
    with open(os.path.join(OUT_DIR, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": now_iso(), "results": results,
                   "attempts": prober.attempts,
                   "pinned": prober.pinned}, f, indent=2, ensure_ascii=False, default=str)

    rows = aggregate(results)
    ran_live = any(p.requests for p in prober.providers.values())
    report = build_report(rows, prober, ran_live)
    report = scrub_report(report, prober.safe_tokens)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nwrote {REPORT_PATH}", file=sys.stderr)
    for r in rows:
        print(f"  {r['combo']:<16} {r['verdict']}", file=sys.stderr)
    for p in prober.providers.values():
        print(f"  [{p.name}] {p.requests} requests, {p.status_note()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
