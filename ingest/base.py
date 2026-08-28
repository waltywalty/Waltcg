"""One interface, one set of guarantees, five adapters.

Every adapter implements `fetch(since) -> list[Record]`, and every Record
carries `as_of` and `observed_at` explicitly -- never one timestamp used twice.
The base class holds everything that must be true of all of them, because a
guarantee re-implemented per adapter is a guarantee that holds in four of five:

* **Raw responses are cached before anything is parsed.** raw/{source}/{date}/.
  A parser bug then costs an afternoon rather than a day of provider quota, and
  every historical payload can be re-parsed by a fixed parser. This is why the
  cache write happens before the first `json.loads`, not after a successful one.

* **Rate limits are respected from the provider's own counter** where it
  publishes one, not from our count of requests. Counting our own underestimates
  whenever a call costs more than one credit -- PokemonPriceTracker bills by
  `metadata.apiCallsConsumed.costPerCard` -- and the way you find out is a 429
  in the middle of a run.

* **Backoff is bounded and gives up loudly.** An adapter that quietly stops is
  indistinguishable from a source with no data, which is the confusion
  ingest_gap exists to prevent.

* **Nothing is mutated.** Adapters only ever return records. Writing is the
  store's job, and the store has no update path.
"""

from __future__ import annotations

import datetime as _dt
import email.utils
import http.client
import json
import os
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_ROOT = os.path.join(REPO, "raw")

# Every kind a Record can be. Closed, because a typo in a kind string would
# silently route rows to a table that never receives them.
KINDS = ("card", "xref", "price", "pop", "sentiment", "fx")


@dataclass
class Record:
    """One observation, with both timestamps stated.

    `as_of` is the date the value refers to. `observed_at` is when we saw it.
    They are separate arguments with no default relationship, because the one
    bug this whole store is built against is the two collapsing into one.
    """

    kind: str
    payload: dict
    as_of: _dt.datetime
    observed_at: _dt.datetime
    source: str

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown record kind {self.kind!r}; expected one "
                             f"of {', '.join(KINDS)}")
        if self.observed_at < self.as_of:
            raise ValueError(
                f"{self.source}: observed_at {self.observed_at.isoformat()} is "
                f"before as_of {self.as_of.isoformat()}")


@dataclass
class Quota:
    """What the provider says is left, not what we counted."""

    remaining: Optional[int] = None
    limit: Optional[int] = None
    reported_by_provider: bool = False
    consumed_this_run: int = 0

    def note(self) -> str:
        if self.reported_by_provider and self.remaining is not None:
            cap = f"/{self.limit}" if self.limit else ""
            return f"provider reports {self.remaining}{cap} remaining"
        return (f"{self.consumed_this_run} calls made this run; provider "
                "publishes no counter, so remaining is UNKNOWN rather than "
                "assumed")


class RateLimited(RuntimeError):
    """The provider ANSWERED, and the answer was "not now".

    Deliberately not a subclass of AdapterGaveUp. A 429 and a dead endpoint
    are different facts: one is fixable by waiting and the other needs a code
    change, and a run that files them together sends you hunting for a broken
    URL that works fine.
    """


class AdapterGaveUp(RuntimeError):
    """Backoff exhausted. Raised, never swallowed: an adapter that stops
    quietly looks exactly like a source with nothing to say."""


class Adapter:
    """Base for every source adapter."""

    name = "base"
    key_env: Optional[str] = None
    api_key_header = "x-api-key"
    host = ""
    daily_free_calls: Optional[int] = None

    # Backoff: 1s, 2s, 4s, 8s. Four attempts then give up loudly.
    max_attempts = 4

    # HOW MANY 429s BEFORE WE STOP ASKING. Run #11: apitcg refused 16 calls
    # after four attempts each, having served 250 the day before. Four attempts
    # against a 429 is four ways to be refused -- the provider is not failing,
    # it is answering, and the answer is "not now". After the second refusal
    # this adapter is CLOSED for the rest of the run and every later call
    # raises RateLimited without touching the network.
    #
    # `rate_limited` and `unreachable` are different facts and only one of them
    # is fixable by waiting; a run that conflates them tells you to go looking
    # for a broken endpoint that is not broken.
    stop_calling_after_rate_limits = 2

    # Longest `Retry-After` worth honouring inside one run. The job has a
    # 30-minute ceiling; a provider asking for an hour is telling us to come
    # back tomorrow, and sleeping on it would spend the whole run learning
    # nothing. Past this we trip the breaker immediately and say what was
    # asked for.
    max_retry_after_seconds = 120.0
    # Does this adapter need a card list to do anything at all? A source that
    # was handed nothing did not "return no rows" -- it was never asked. Run #5
    # conflated those and reported a snapshot with 8,313 identities and zero
    # prices as a success.
    requires_targets = False
    base_delay = 1.0

    # HOW MANY CARDS ONE REQUEST CAN COVER. 1 means this source is asked per
    # card and there is no batched form; anything higher is a batch or paged
    # endpoint that serves that many at once.
    #
    # WHY THIS IS ON THE ADAPTER AND IN THE RUN REPORT. apitcg's fetch made
    # one request PER CARD -- 3,494 of them -- for a field `/api/products`
    # serves 100 at a time, and the run report had no column that would have
    # shown it. The rate-limit table counted CALLS, which looked like a
    # provider ceiling rather than an amplifier of our own making, and the
    # observation written into the dated rate-limit record was drawn from the
    # catalog step's count alone -- a few hundred out of several thousand
    # requests we sent that day. Both of this session's quota findings were
    # client-side. A request-count column would have shown both.
    cards_per_request = 1

    def __init__(self, *, raw_root: str = RAW_ROOT, sleep=time.sleep,
                 now=None, transport=None, monotonic=None):
        self.raw_root = raw_root
        self._sleep = sleep
        self._monotonic = monotonic or time.monotonic
        self._last_call: Optional[float] = None
        self._now = now or (lambda: _dt.datetime.now(_dt.timezone.utc)
                            .replace(tzinfo=None))
        # Injected in tests and in replay so no code path can reach the network
        # by accident. Production leaves it None and uses http.client.
        self._transport = transport
        self.quota = Quota(limit=self.daily_free_calls)
        self.log: list[str] = []
        # 429 accounting. `rate_limited` is the breaker: once it is set this
        # adapter makes no further calls this run, and every combination it
        # had not reached yet is `rate_limited` rather than `unreachable`.
        self.rate_limit_hits = 0
        self.rate_limited = False
        self.rate_limited_why: Optional[str] = None
        # WHAT THE PROVIDER SAYS ITS LIMIT IS -- verbatim, because we do not
        # know apitcg's quota and it is not in the OpenAPI spec. Every
        # rate-related header off every response, kept as sent. The last one
        # wins for reporting; the count is how many responses carried any.
        self.rate_headers: dict = {}
        self.rate_headers_seen = 0
        self.responses_seen = 0

    # -- the interface ----------------------------------------------------

    def fetch(self, since: Optional[_dt.datetime] = None) -> list[Record]:
        raise NotImplementedError

    # -- key handling -----------------------------------------------------

    @property
    def key(self) -> Optional[str]:
        return os.environ.get(self.key_env) if self.key_env else None

    def preflight(self) -> dict:
        """Say whether the key is present WITHOUT ever logging it.

        A missing key marks the source untested rather than sending an
        unauthenticated request that comes back as a generic failure and gets
        recorded as "the source had nothing".

        Every key in the returned dict is ALWAYS present, including for a
        keyless source. It used to return a short dict in that case, which was
        fine until the first keyless adapter arrived: the reporting step read
        `key_length` on the ready branch and died with a KeyError before any
        provider ran. A contract whose shape depends on a branch is a contract
        that only holds on the branches something has exercised.
        """
        key = self.key if self.key_env else None
        return {
            "source": self.name,
            "key_required": self.key_env is not None,
            "ready": bool(key) if self.key_env else True,
            "env": self.key_env,
            "key_length": len(key) if key else 0,
            "key_prefix": key[:4] if key else None,
            "reason": None if (key or not self.key_env) else "key absent",
        }

    # -- raw cache --------------------------------------------------------

    def cache_raw(self, label: str, body: bytes) -> str:
        """Write the response to raw/{source}/{date}/ BEFORE parsing it."""
        day = self._now().date().isoformat()
        directory = os.path.join(self.raw_root, self.name, day)
        os.makedirs(directory, exist_ok=True)
        safe = urllib.parse.quote(label, safe="")[:120]
        stamp = self._now().strftime("%H%M%S%f")
        path = os.path.join(directory, f"{stamp}-{safe}.json")
        with open(path, "wb") as handle:
            handle.write(body)
        return path

    # -- transport --------------------------------------------------------

    def get(self, url: str, *, headers: Optional[dict] = None,
            label: Optional[str] = None,
            attempts: Optional[int] = None) -> dict:
        """One GET, cached raw, with bounded backoff and quota accounting.

        `attempts` overrides the retry budget for this call. Discovery uses
        `attempts=1`: when several candidate URLs are being tried because the
        endpoint shape is not verified, backing off four times on each wrong
        guess spends a minute proving nothing.
        """
        headers = dict(headers or {})
        if self.key_env and self.key:
            headers[self.api_key_header] = self.key

        budget = self.max_attempts if attempts is None else max(1, int(attempts))
        last_error = None
        for attempt in range(budget):
            # THE BREAKER, checked before anything else. Once this adapter has
            # been refused twice it stops calling for the rest of the run --
            # including on the retries of a call already in flight, which is
            # where "four attempts, four refusals" came from.
            if self.rate_limited:
                raise RateLimited(
                    f"{self.name}: stopped calling after "
                    f"{self.rate_limit_hits} rate-limit refusals "
                    f"({self.rate_limited_why}). Everything it had not reached "
                    "is RATE LIMITED, not unreachable -- the provider answered, "
                    "and the answer was 'not now'.")
            self.throttle()
            if self.exhausted():
                raise RateLimited(
                    f"{self.name}: {self.quota.note()}; stopping before the "
                    "call rather than spending the last of the day's quota on "
                    "a request whose result we would not trust")
            try:
                status, body, response_headers = self._send(url, headers)
            except OSError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._backoff(attempt, last_error, budget)
                continue

            self.quota.consumed_this_run += 1
            self.responses_seen += 1
            self._last_call = self._monotonic()
            self.note_rate_headers(response_headers)
            path = self.cache_raw(label or url, body)   # BEFORE parsing
            self.log.append(f"{self.name} {status} {url} -> {path}")

            if status == 429:
                last_error = self.note_rate_limit(response_headers)
                if self.rate_limited:
                    raise RateLimited(f"{self.name}: {last_error}")
                self._backoff(attempt, last_error, budget,
                              seconds=retry_after_seconds(response_headers))
                continue

            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                # The bytes are already on disk, so this is recoverable later.
                raise AdapterGaveUp(
                    f"{self.name}: response was not JSON ({exc}); the raw body "
                    f"is cached at {path} and can be re-parsed") from exc

            self.note_quota(payload)

            # A 2xx carrying an error object is a FAILURE, not an empty result.
            # apitcg.com answers auth failures with HTTP 200, and reading that
            # as "no cards matched" is how an absence gets confidently reported
            # (ADR-0001).
            if self.is_error_body(payload):
                raise AdapterGaveUp(
                    f"{self.name}: HTTP {status} carrying an error body -- "
                    f"{self.error_text(payload)!r}. This is not an empty result.")
            return payload

        raise AdapterGaveUp(
            f"{self.name}: gave up after {budget} attempts on {url} "
            f"({last_error}). Recorded as a gap, never as 'no data'.")

    def probe(self, candidates, *, label: str):
        """First candidate URL that answers with JSON, and which one it was.

        Returns (url, payload) or (None, [(url, why), ...]). Used where the
        endpoint shape has NOT been verified against the live service: the
        alternative is hardcoding one guess and reporting its failure as
        "the source has no data for this", which is the confusion ingest_gap
        exists to prevent.
        """
        tried = []
        for url in candidates:
            try:
                return url, self.get(url, label=label, attempts=1)
            except (AdapterGaveUp, RateLimited, OSError) as exc:
                tried.append((url, str(exc)[:160]))
        return None, tried

    def _send(self, url: str, headers: dict):
        """(status, body, response_headers).

        RESPONSE HEADERS WERE BEING THROWN AWAY, which is why we still cannot
        say what apitcg's quota is: `Retry-After` and any `X-RateLimit-*` the
        provider sends arrived and were discarded one frame below where they
        were needed.

        A transport that returns the old two-tuple still works -- the test
        fakes predate this -- and is read as "no headers", which is a
        different thing from "no rate headers sent" only in that we never
        claim the second from the first.
        """
        if self._transport is not None:
            answer = self._transport(url, headers)
            if isinstance(answer, tuple) and len(answer) >= 3:
                return answer[0], answer[1], dict(answer[2] or {})
            return answer[0], answer[1], {}
        parts = urllib.parse.urlsplit(url)
        conn = http.client.HTTPSConnection(parts.netloc, timeout=30)
        try:
            target = parts.path + ("?" + parts.query if parts.query else "")
            # http.client, not urllib: urllib title-cases header names and some
            # of these providers are case-sensitive about their key header.
            conn.request("GET", target, headers=headers)
            response = conn.getresponse()
            return (response.status, response.read(),
                    {k: v for k, v in response.getheaders()})
        finally:
            conn.close()

    # -- what the provider says about its own limits ----------------------

    def note_rate_headers(self, response_headers) -> dict:
        """Keep every rate-related header VERBATIM.

        Verbatim because we are trying to discover a limit nobody documents,
        and a normalised or summarised header is a header we have already
        started interpreting. Names are matched loosely (`X-RateLimit-Limit`,
        `x-rate-limit-limit`, `RateLimit-Remaining`) and stored exactly as the
        provider spelled them.
        """
        found = {k: v for k, v in (response_headers or {}).items()
                 if _norm_key(k) in RATE_HEADER_NAMES
                 or _norm_key(k).startswith(("ratelimit", "xratelimit"))}
        if found:
            self.rate_headers_seen += 1
            self.rate_headers.update(found)
        return found

    def note_rate_limit(self, response_headers) -> str:
        """Record a 429 and decide whether this adapter is done for the run."""
        self.rate_limit_hits += 1
        wait = retry_after_seconds(response_headers)
        asked = (f"; provider asked for {wait:.0f}s" if wait is not None
                 else "; no Retry-After sent")
        why = f"429 #{self.rate_limit_hits}{asked}"
        if wait is not None and wait > self.max_retry_after_seconds:
            # Longer than the run has. Waiting it out would spend the whole
            # job on one provider's cooldown.
            self.rate_limited = True
            why += (f" -- longer than the {self.max_retry_after_seconds:.0f}s "
                    "this run can wait")
        elif self.rate_limit_hits >= self.stop_calling_after_rate_limits:
            self.rate_limited = True
        if self.rate_limited:
            self.rate_limited_why = why
            self.log.append(f"{self.name} STOP -- {why}")
        return why

    def _backoff(self, attempt: int, why: str, budget: Optional[int] = None,
                 seconds: Optional[float] = None):
        # Nothing follows the last attempt, so sleeping after it only delays
        # the error. Discovery calls with attempts=1 would otherwise pay a
        # full backoff for every candidate URL it rules out.
        if budget is not None and attempt >= budget - 1:
            self.log.append(f"{self.name} giving up after {why}")
            return
        # The provider's own number beats ours whenever it sends one: an
        # exponential guess that undershoots earns another 429, and one that
        # overshoots wastes the run.
        delay = self.base_delay * (2 ** attempt)
        if seconds is not None:
            delay = min(max(seconds, 0.0), self.max_retry_after_seconds)
            self.log.append(f"{self.name} honouring Retry-After {delay:.0f}s")
        self.log.append(f"{self.name} backoff {delay:.0f}s after {why}")
        self._sleep(delay)

    # -- rate limiting ----------------------------------------------------
    #
    # Separate from quota on purpose. Quota is "how many are left today";
    # this is "how fast may I go right now", and a provider can refuse you on
    # the second while the first still says you have plenty. Alpha Vantage
    # publishes both -- 25 a day and 5 a minute -- and run #5 tripped the
    # per-minute one with five FX pairs and a four-attempt retry budget behind
    # each: up to twenty requests in a couple of seconds against a 5/min cap.
    #
    # `min_interval_seconds` is None for providers that publish no per-minute
    # limit. Inventing one would slow every run down to protect against a rule
    # nobody stated.

    min_interval_seconds: Optional[float] = None

    def throttle(self):
        """Wait, if going now would exceed the provider's stated rate."""
        if not self.min_interval_seconds or self._last_call is None:
            return
        waited = self._monotonic() - self._last_call
        remaining = self.min_interval_seconds - waited
        if remaining > 0:
            self.log.append(f"{self.name} throttling {remaining:.1f}s "
                            f"({self.min_interval_seconds:.0f}s between calls)")
            self._sleep(remaining)

    # -- quota ------------------------------------------------------------

    def note_quota(self, payload: dict):
        """Read the provider's own counter. Overridden where one exists."""

    def exhausted(self, reserve: int = 0) -> bool:
        if self.quota.remaining is not None:
            return self.quota.remaining <= reserve
        if self.quota.limit is not None:
            return self.quota.consumed_this_run >= self.quota.limit - reserve
        return False

    # -- error bodies -----------------------------------------------------

    # HTTP 200 CARRYING AN ERROR BODY. Nine separate times now, across five
    # providers: apitcg answers auth failures with 200, Alpha Vantage answers
    # a throttle with 200 and an "Information" key, and the rest is variations
    # on the theme. It is the single most common failure shape in this project
    # and the most dangerous, because the failure arrives wearing the costume
    # of an empty result.
    #
    # These are SHARED. `EXTRA_ERROR_KEYS` is how a provider adds its own
    # dialect; a subclass that set `ERROR_KEYS` would REPLACE this list, which
    # is what the FX adapter did -- it gained Alpha Vantage's three keys and
    # silently lost all five generic ones, while every other adapter never
    # gained "Note" or "Information" at all.
    ERROR_KEYS = ("error", "errors", "message", "detail", "fault",
                  "error message", "note", "information", "warning",
                  "exception", "status message")
    EXTRA_ERROR_KEYS: tuple = ()

    @classmethod
    def error_keys(cls) -> tuple:
        """Every key this adapter treats as an error marker: the shared set
        plus its own, never one instead of the other."""
        return tuple(dict.fromkeys(
            [_norm_key(k) for k in cls.ERROR_KEYS]
            + [_norm_key(k) for k in cls.EXTRA_ERROR_KEYS]))

    def _error_entry(self, payload):
        """(key, value) of the first error marker present, or None.

        Matches on a NORMALISED key, because the same marker arrives as
        `Error Message`, `error_message` and `errorMessage` from three
        providers and a literal comparison catches one of the three.
        """
        if not isinstance(payload, dict):
            return None
        wanted = set(self.error_keys())
        for key, value in payload.items():
            if _norm_key(key) in wanted and value not in (None, "", [], {},
                                                          False, 0):
                return key, value
        return None

    def is_error_body(self, payload) -> bool:
        return self._error_entry(payload) is not None

    def error_text(self, payload) -> str:
        entry = self._error_entry(payload)
        return f"{entry[0]}: {entry[1]}"[:200] if entry else ""


# Header names that carry a rate limit, normalised. Providers disagree about
# hyphens, case and the `X-` prefix, and there is no standard: `RateLimit-*` is
# a draft, `X-RateLimit-*` is the convention, `Retry-After` is the only one
# actually in an RFC. Matched loosely, stored verbatim.
RATE_HEADER_NAMES = frozenset({
    "retryafter", "ratelimit", "ratelimitlimit", "ratelimitremaining",
    "ratelimitreset", "ratelimitused", "ratelimitpolicy", "ratelimitresource",
    "xratelimitlimit", "xratelimitremaining", "xratelimitreset",
    "xratelimitused", "xratelimitretryafter", "xrateremaining",
    "xquotalimit", "xquotaremaining", "xdailylimit", "xdailyremaining",
})


def retry_after_seconds(response_headers) -> Optional[float]:
    """`Retry-After` in seconds, whichever of its two forms was sent.

    RFC 9110 allows delta-seconds OR an HTTP-date, and a provider is free to
    pick either. Reading only the integer form turns a date into "no
    Retry-After sent", which is the same mistake as reading a 200 with an
    error body as an empty result: an answer misread as silence.
    """
    for key, value in (response_headers or {}).items():
        if _norm_key(key) != "retryafter":
            continue
        text = str(value).strip()
        try:
            return float(text)
        except ValueError:
            pass
        try:
            when = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=_dt.timezone.utc)
        gap = (when - _dt.datetime.now(_dt.timezone.utc)).total_seconds()
        return max(gap, 0.0)
    return None


def _norm_key(key) -> str:
    """`Error Message`, `error_message`, `errorMessage` -> `errormessage`."""
    text = str(key)
    out = []
    for index, char in enumerate(text):
        if char.isupper() and index and not text[index - 1].isupper():
            out.append("")
        out.append(char.lower())
    return "".join(out).replace("_", "").replace("-", "").replace(" ", "")


def find(payload, *names):
    """First value under any of `names`, at any depth. Providers rename keys
    between versions and a fixed path breaks silently when they do."""
    if isinstance(payload, dict):
        for name in names:
            if name in payload:
                return payload[name]
        for value in payload.values():
            found = find(value, *names)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = find(item, *names)
            if found is not None:
                return found
    return None
