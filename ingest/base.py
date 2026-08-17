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
    pass


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
    base_delay = 1.0

    def __init__(self, *, raw_root: str = RAW_ROOT, sleep=time.sleep,
                 now=None, transport=None):
        self.raw_root = raw_root
        self._sleep = sleep
        self._now = now or (lambda: _dt.datetime.now(_dt.timezone.utc)
                            .replace(tzinfo=None))
        # Injected in tests and in replay so no code path can reach the network
        # by accident. Production leaves it None and uses http.client.
        self._transport = transport
        self.quota = Quota(limit=self.daily_free_calls)
        self.log: list[str] = []

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
            if self.exhausted():
                raise RateLimited(
                    f"{self.name}: {self.quota.note()}; stopping before the "
                    "call rather than spending the last of the day's quota on "
                    "a request whose result we would not trust")
            try:
                status, body = self._send(url, headers)
            except OSError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._backoff(attempt, last_error, budget)
                continue

            self.quota.consumed_this_run += 1
            path = self.cache_raw(label or url, body)   # BEFORE parsing
            self.log.append(f"{self.name} {status} {url} -> {path}")

            if status == 429:
                last_error = "429 rate limited"
                self._backoff(attempt, last_error, budget)
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
        if self._transport is not None:
            return self._transport(url, headers)
        parts = urllib.parse.urlsplit(url)
        conn = http.client.HTTPSConnection(parts.netloc, timeout=30)
        try:
            target = parts.path + ("?" + parts.query if parts.query else "")
            # http.client, not urllib: urllib title-cases header names and some
            # of these providers are case-sensitive about their key header.
            conn.request("GET", target, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def _backoff(self, attempt: int, why: str, budget: Optional[int] = None):
        # Nothing follows the last attempt, so sleeping after it only delays
        # the error. Discovery calls with attempts=1 would otherwise pay a
        # full backoff for every candidate URL it rules out.
        if budget is not None and attempt >= budget - 1:
            self.log.append(f"{self.name} giving up after {why}")
            return
        delay = self.base_delay * (2 ** attempt)
        self.log.append(f"{self.name} backoff {delay:.0f}s after {why}")
        self._sleep(delay)

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

    ERROR_KEYS = ("error", "errors", "message", "detail", "fault")

    def is_error_body(self, payload) -> bool:
        if not isinstance(payload, dict):
            return False
        for key in self.ERROR_KEYS:
            value = payload.get(key)
            if value not in (None, "", [], {}, False):
                return True
        return False

    def error_text(self, payload) -> str:
        for key in self.ERROR_KEYS:
            if payload.get(key):
                return str(payload[key])[:200]
        return ""


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
