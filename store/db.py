"""The only sanctioned writer.

There is no `update()` and no `delete()` on this class, and that is the point:
append-only cannot be enforced by DuckDB itself (no triggers, no rules), so the
first line of defence is an API that has no path to a mutation. The second is
`seal()`, a hash chain that makes a mutation made behind this class's back
visible after the fact. The third is Postgres, where the same invariant becomes
a real BEFORE UPDATE OR DELETE trigger -- see store/schema_postgres.sql.

Corrections are `supersede()`: a new row, a later observed_at, and a pointer at
the row it replaces. Nothing is ever overwritten, so every number the app ever
showed can still be reconstructed as of the moment it showed it.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import uuid
from decimal import Decimal
from typing import Any, Iterable, Optional

import duckdb

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(REPO, "store", "schema.sql")
DEFAULT_DB = os.path.join(REPO, "store", "waltcg.duckdb")

# Tables whose rows are facts and therefore sealed. `cards` is keyed by
# card_uid rather than row_id and is sealed on its key instead.
FACT_TABLES = ("card_xref", "price_snapshot", "pop_snapshot", "sentiment",
               "fx_rate", "ingest_gap")


class StoreError(RuntimeError):
    pass


class LookAheadError(StoreError):
    """observed_at earlier than as_of, or later than now. Never recoverable by
    retrying: the row is describing a time it could not have seen."""


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _as_ts(value) -> _dt.datetime:
    """Accept a date, a datetime or an ISO string; store a naive UTC datetime.

    A date-only `as_of` becomes midnight, which is what makes
    `observed_at >= as_of` well-typed for a value that refers to a whole day.
    """
    if isinstance(value, _dt.datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        parsed = _dt.datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    raise StoreError(f"cannot read {value!r} as a timestamp")


def _money(value) -> Decimal:
    if isinstance(value, float):
        raise StoreError(
            f"amount {value!r} is a float. Money is Decimal here for the same "
            "reason it is a string in the contract: cents do not survive a "
            "binary float and a fee stack is a chain of additions.")
    return Decimal(str(value))


class Store:
    """Point-in-time store. Opens, migrates, appends, seals, reads."""

    def __init__(self, path: str = DEFAULT_DB, read_only: bool = False):
        self.path = path
        fresh = path == ":memory:" or not os.path.exists(path)
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.con = duckdb.connect(path, read_only=read_only)
        if fresh and not read_only:
            self.migrate()

    # -- schema ----------------------------------------------------------

    def migrate(self):
        with open(SCHEMA, encoding="utf-8") as f:
            self.con.execute(f.read())

    def close(self):
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- the invariant, checked before the database sees the row ---------

    def _check_times(self, as_of, observed_at):
        """The CHECK constraints catch this too. Checking here as well buys a
        message that names the row rather than the constraint."""
        if observed_at < as_of:
            raise LookAheadError(
                f"observed_at {observed_at.isoformat()} is earlier than as_of "
                f"{as_of.isoformat()}: the value would have been seen before "
                "the date it refers to")
        if observed_at > _utc_now():
            raise LookAheadError(
                f"observed_at {observed_at.isoformat()} is in the future")

    def _next_row_id(self) -> int:
        return int(self.con.execute("SELECT nextval('row_id_seq')").fetchone()[0])

    # -- writes (there is no update and no delete) -----------------------

    def upsert_card(self, *, card_uid, game, set_code, number, variant,
                    language, source, observed_at=None, **optional):
        """Catalog rows are keyed by card_uid and are not a time series.

        Named `upsert` and implemented as insert-or-ignore: a second sighting
        of the same printing is not new information, and overwriting the first
        would lose the observed_at that says when we first saw it.
        """
        observed_at = _as_ts(observed_at or _utc_now())
        columns = dict(
            card_uid=card_uid, game=game, set_code=set_code, number=number,
            variant=variant, language=language,
            name_en=optional.get("name_en"), name_jp=optional.get("name_jp"),
            rarity=optional.get("rarity"), artist=optional.get("artist"),
            release_date=optional.get("release_date"),
            obtainment_class=optional.get("obtainment_class", "unknown"),
            image_url=optional.get("image_url"),
            observed_at=observed_at, source=source)
        existing = self.con.execute(
            "SELECT 1 FROM cards WHERE card_uid = ?", [card_uid]).fetchone()
        if existing:
            return card_uid
        keys = ", ".join(columns)
        marks = ", ".join("?" for _ in columns)
        self.con.execute(f"INSERT INTO cards ({keys}) VALUES ({marks})",
                         list(columns.values()))
        self._seal("cards", card_uid, columns)
        return card_uid

    def _insert(self, table: str, columns: dict) -> int:
        as_of = columns.get("as_of")
        observed_at = columns.get("observed_at")
        if as_of is not None and observed_at is not None:
            self._check_times(as_of, observed_at)
        row_id = self._next_row_id()
        columns = {"row_id": row_id, **columns}
        keys = ", ".join(columns)
        marks = ", ".join("?" for _ in columns)
        self.con.execute(f"INSERT INTO {table} ({keys}) VALUES ({marks})",
                         list(columns.values()))
        self._seal(table, row_id, columns)
        return row_id

    def add_xref(self, *, card_uid, source, external_id, confidence,
                 resolved_by, as_of, observed_at, secondary_id=None,
                 supersedes=None) -> int:
        return self._insert("card_xref", dict(
            card_uid=card_uid, source=source, external_id=external_id,
            secondary_id=secondary_id, confidence=Decimal(str(confidence)),
            resolved_by=resolved_by, as_of=_as_ts(as_of),
            observed_at=_as_ts(observed_at), supersedes=supersedes))

    def add_price(self, *, card_uid, grade, condition, marketplace, amount,
                  currency, as_of, observed_at, source, grader=None,
                  fx_rate_used=None, fx_as_of=None, sample_size=None,
                  supersedes=None) -> int:
        if (fx_rate_used is None) != (fx_as_of is None):
            raise StoreError(
                "fx_rate_used and fx_as_of are null together or set together; "
                "null means no conversion happened, never 'unknown'")
        return self._insert("price_snapshot", dict(
            card_uid=card_uid, grade=str(grade), condition=condition,
            grader=grader, marketplace=marketplace, amount=_money(amount),
            currency=currency,
            fx_rate_used=None if fx_rate_used is None else Decimal(str(fx_rate_used)),
            fx_as_of=None if fx_as_of is None else _as_ts(fx_as_of),
            sample_size=sample_size, as_of=_as_ts(as_of),
            observed_at=_as_ts(observed_at), source=source,
            supersedes=supersedes))

    def add_pop(self, *, card_uid, grader, grade, count, as_of, observed_at,
                source, supersedes=None) -> int:
        return self._insert("pop_snapshot", dict(
            card_uid=card_uid, grader=grader, grade=str(grade),
            count=int(count), as_of=_as_ts(as_of),
            observed_at=_as_ts(observed_at), source=source,
            supersedes=supersedes))

    def add_sentiment(self, *, card_uid, platform, mentions, as_of,
                      observed_at, backfilled, source, engagement=None,
                      supersedes=None) -> int:
        if backfilled is None:
            raise StoreError(
                "backfilled must be stated. GOAL D4 excludes backfilled rows "
                "from every backtest, and a null cannot be excluded.")
        return self._insert("sentiment", dict(
            card_uid=card_uid, platform=platform, mentions=int(mentions),
            engagement=engagement, as_of=_as_ts(as_of),
            observed_at=_as_ts(observed_at), backfilled=bool(backfilled),
            source=source, supersedes=supersedes))

    def add_fx(self, *, pair, rate, as_of, observed_at, source,
               supersedes=None) -> int:
        return self._insert("fx_rate", dict(
            pair=pair, rate=Decimal(str(rate)), as_of=_as_ts(as_of),
            observed_at=_as_ts(observed_at), source=source,
            supersedes=supersedes))

    def add_gap(self, *, source, kind, reason, as_of, observed_at,
                card_uid=None, detail=None) -> int:
        """A gap is a row. GOAL D1: never interpolated away, never silent."""
        return self._insert("ingest_gap", dict(
            source=source, card_uid=card_uid, kind=kind, reason=reason,
            detail=detail, as_of=_as_ts(as_of),
            observed_at=_as_ts(observed_at)))

    def supersede(self, table: str, row_id: int, **columns) -> int:
        """Correct a row by writing a new one that points at it.

        The replacement must be observed LATER than the row it replaces. A
        correction observed at or before the original is not a correction; it
        is a second opinion, and the store would have no way to order them.
        """
        if table not in FACT_TABLES:
            raise StoreError(f"{table} is not a fact table")
        original = self.con.execute(
            f"SELECT observed_at FROM {table} WHERE row_id = ?",
            [row_id]).fetchone()
        if original is None:
            raise StoreError(f"{table} has no row_id {row_id} to supersede")
        replacement_observed = _as_ts(columns.get("observed_at") or _utc_now())
        if replacement_observed <= original[0]:
            raise StoreError(
                f"correction observed at {replacement_observed.isoformat()} is "
                f"not later than the row it corrects ({original[0].isoformat()})")
        writer = {
            "card_xref": self.add_xref, "price_snapshot": self.add_price,
            "pop_snapshot": self.add_pop, "sentiment": self.add_sentiment,
            "fx_rate": self.add_fx,
        }[table]
        columns["observed_at"] = replacement_observed
        return writer(supersedes=row_id, **columns)

    # -- tamper seal ------------------------------------------------------

    def _seal(self, table: str, row_id, columns: dict):
        payload = json.dumps(
            {k: (str(v) if isinstance(v, (Decimal, _dt.datetime, _dt.date)) else v)
             for k, v in sorted(columns.items())},
            sort_keys=True, default=str)
        row_hash = hashlib.sha256(payload.encode()).hexdigest()
        previous = self.con.execute(
            "SELECT chain_hash FROM ledger_seal ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        chain = hashlib.sha256(
            ((previous[0] if previous else "") + row_hash).encode()).hexdigest()
        seq = int(self.con.execute("SELECT nextval('seal_seq')").fetchone()[0])
        self.con.execute(
            "INSERT INTO ledger_seal (seq, table_name, row_key, row_hash, "
            "chain_hash, sealed_at) VALUES (?, ?, ?, ?, ?, ?)",
            [seq, table, str(row_id), row_hash, chain, _utc_now()])

    def verify_seal(self) -> dict:
        """Recompute the chain. A broken link means a row was changed after it
        was written -- by a direct connection, since this class cannot do it."""
        rows = self.con.execute(
            "SELECT seq, row_hash, chain_hash FROM ledger_seal ORDER BY seq"
        ).fetchall()
        previous = ""
        for seq, row_hash, chain_hash in rows:
            expected = hashlib.sha256((previous + row_hash).encode()).hexdigest()
            if expected != chain_hash:
                return {"intact": False, "broken_at": seq, "sealed_rows": len(rows)}
            previous = chain_hash
        return {"intact": True, "broken_at": None, "sealed_rows": len(rows)}

    # -- reads ------------------------------------------------------------

    def as_of_view(self, table: str, evaluation_timestamp) -> "duckdb.DuckDBPyRelation":
        """Every row observable AT a moment, superseded rows removed.

        THE shared query wrapper. CLAUDE.md non-negotiable 1: any value used at
        an evaluation timestamp must have observed_at <= that timestamp, and
        nothing may bypass this. Filtering on as_of instead would admit a row
        whose value refers to last Tuesday but which we only saw today -- which
        is exactly the look-ahead the rule exists to stop.
        """
        if table not in FACT_TABLES:
            raise StoreError(f"{table} is not a fact table")
        cutoff = _as_ts(evaluation_timestamp)
        return self.con.sql(f"""
            SELECT * FROM {table} t
            WHERE t.observed_at <= '{cutoff.isoformat()}'
              AND NOT EXISTS (
                  SELECT 1 FROM {table} s
                  WHERE s.supersedes = t.row_id
                    AND s.observed_at <= '{cutoff.isoformat()}')
        """)

    def signal_ready_xrefs(self, evaluation_timestamp):
        """Mappings a signal may use. card_uid.md: anything fuzzy below 0.9 is
        excluded from every signal. Excluded here, in the shared wrapper, so a
        caller cannot forget."""
        cutoff = _as_ts(evaluation_timestamp)
        return self.con.sql(f"""
            SELECT * FROM ({self.as_of_view('card_xref', cutoff).sql_query()})
            WHERE resolved_by = 'manual'
               OR resolved_by = 'exact'
               OR (resolved_by = 'fuzzy' AND confidence >= 0.9)
        """)

    def coverage(self, table: str, card_uid: str, start, end) -> dict:
        """Which days between start and end have a row, and which do not.

        GOAL D1 wants zero SILENT gaps, which is not the same as zero gaps. A
        missing day is reportable; a missing day nobody counted is not.
        """
        start_d, end_d = _as_ts(start).date(), _as_ts(end).date()
        have = {r[0] for r in self.con.execute(
            f"SELECT DISTINCT CAST(as_of AS DATE) FROM {table} "
            "WHERE card_uid = ? AND as_of BETWEEN ? AND ?",
            [card_uid, _as_ts(start), _as_ts(end)]).fetchall()}
        span = (end_d - start_d).days + 1
        days = [start_d + _dt.timedelta(days=i) for i in range(span)]
        missing = [d for d in days if d not in have]
        return {"card_uid": card_uid, "days": span, "present": span - len(missing),
                "missing": missing,
                "consecutive": _longest_run([d in have for d in days])}


def _longest_run(flags: Iterable[bool]) -> int:
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def new_run_id() -> str:
    return uuid.uuid4().hex
