"""The point-in-time store's invariants, tested by trying to break them.

CLAUDE.md non-negotiable 1 is enforced here or nowhere: any value used at an
evaluation timestamp must have observed_at <= that timestamp, and nothing may
bypass the shared query wrapper. The rest of the app trusts this file.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb  # noqa: E402

from store.db import LookAheadError, Store, StoreError  # noqa: E402

CARD = "pkmn:sv3:223/197:sir:EN"


def seeded():
    store = Store(":memory:")
    store.upsert_card(card_uid=CARD, game="pkmn", set_code="sv3",
                      number="223/197", variant="sir", language="EN",
                      name_en="Charizard ex", rarity="Special Illustration Rare",
                      release_date=_dt.date(2023, 8, 11), source="test")
    return store


def now():
    return _dt.datetime.utcnow()


class YouCannotObserveTheFuture(unittest.TestCase):

    def test_observed_before_as_of_is_refused(self):
        store = seeded()
        with self.assertRaises(LookAheadError):
            store.add_price(card_uid=CARD, grade="10", condition="graded",
                            grader="PSA", marketplace="ebay", amount="540",
                            currency="USD", as_of=now(),
                            observed_at=now() - _dt.timedelta(days=1),
                            source="t")

    def test_observed_in_the_future_is_refused(self):
        store = seeded()
        with self.assertRaises(LookAheadError):
            store.add_price(card_uid=CARD, grade="10", condition="graded",
                            grader="PSA", marketplace="ebay", amount="540",
                            currency="USD", as_of=now(),
                            observed_at=now() + _dt.timedelta(hours=1),
                            source="t")

    def test_the_database_refuses_it_too_not_just_the_writer(self):
        """The Python guard buys a better message. The CHECK is what actually
        holds when someone writes SQL directly."""
        store = seeded()
        with self.assertRaises(duckdb.ConstraintException):
            store.con.execute(
                "INSERT INTO pop_snapshot (row_id, card_uid, grader, grade, "
                "count, as_of, observed_at, source) VALUES "
                "(9001, ?, 'PSA', '10', 5, ?, ?, 'direct')",
                [CARD, now(), now() - _dt.timedelta(days=2)])

    def test_now_is_enforced_by_the_database(self):
        store = seeded()
        with self.assertRaises(duckdb.ConstraintException):
            store.con.execute(
                "INSERT INTO fx_rate (row_id, pair, rate, as_of, observed_at, "
                "source) VALUES (9002, 'GBP/USD', 1.27, ?, ?, 'direct')",
                [now(), now() + _dt.timedelta(days=365)])


class MoneyIsNeverNaked(unittest.TestCase):

    def test_a_float_amount_is_refused(self):
        store = seeded()
        with self.assertRaises(StoreError) as ctx:
            store.add_price(card_uid=CARD, grade="10", condition="graded",
                            grader="PSA", marketplace="ebay", amount=540.0,
                            currency="USD", as_of=now(), observed_at=now(),
                            source="t")
        self.assertIn("float", str(ctx.exception))

    def test_currency_is_not_nullable(self):
        store = seeded()
        with self.assertRaises(duckdb.ConstraintException):
            store.con.execute(
                "INSERT INTO price_snapshot (row_id, card_uid, grade, "
                "condition, grader, marketplace, amount, currency, as_of, "
                "observed_at, source) VALUES "
                "(9003, ?, '10', 'graded', 'PSA', 'ebay', 540, NULL, ?, ?, 'x')",
                [CARD, now(), now()])

    def test_fx_rate_and_fx_as_of_are_null_together_or_set_together(self):
        store = seeded()
        with self.assertRaises(StoreError):
            store.add_price(card_uid=CARD, grade="10", condition="graded",
                            grader="PSA", marketplace="ebay", amount="540",
                            currency="USD", fx_rate_used="1.27",
                            as_of=now(), observed_at=now(), source="t")

    def test_amounts_round_trip_as_decimal(self):
        store = seeded()
        store.add_price(card_uid=CARD, grade="10", condition="graded",
                        grader="PSA", marketplace="ebay", amount="540.55",
                        currency="USD", as_of=now(), observed_at=now(),
                        source="t")
        amount = store.con.execute(
            "SELECT amount FROM price_snapshot").fetchone()[0]
        self.assertEqual(amount, Decimal("540.5500"))
        self.assertNotIsInstance(amount, float)


class GradeAndGraderAgree(unittest.TestCase):

    def test_a_raw_price_may_not_name_a_grader(self):
        store = seeded()
        with self.assertRaises(duckdb.ConstraintException):
            store.add_price(card_uid=CARD, grade="raw", condition="nm",
                            grader="PSA", marketplace="ebay", amount="140",
                            currency="USD", as_of=now(), observed_at=now(),
                            source="t")

    def test_a_graded_price_must_name_a_grader(self):
        store = seeded()
        with self.assertRaises(duckdb.ConstraintException):
            store.add_price(card_uid=CARD, grade="10", condition="graded",
                            marketplace="ebay", amount="540", currency="USD",
                            as_of=now(), observed_at=now(), source="t")

    def test_there_is_no_population_of_raw(self):
        store = seeded()
        with self.assertRaises(duckdb.ConstraintException):
            store.add_pop(card_uid=CARD, grader="PSA", grade="raw", count=10,
                          as_of=now(), observed_at=now(), source="t")

    def test_raw_is_a_grade(self):
        store = seeded()
        store.add_price(card_uid=CARD, grade="raw", condition="nm",
                        marketplace="ebay", amount="140", currency="USD",
                        as_of=now(), observed_at=now(), source="t")
        self.assertEqual(store.con.execute(
            "SELECT count(*) FROM price_snapshot WHERE grade = 'raw'"
        ).fetchone()[0], 1)

    def test_half_grades_are_storable(self):
        """CGC and BGS award them and PSA does not. One enum, both realities."""
        store = seeded()
        store.add_price(card_uid=CARD, grade="9.5", condition="graded",
                        grader="CGC", marketplace="ebay", amount="300",
                        currency="USD", as_of=now(), observed_at=now(),
                        source="t")
        self.assertEqual(store.con.execute(
            "SELECT grade FROM price_snapshot").fetchone()[0], "9.5")


class TheUidMustMatchItsParts(unittest.TestCase):
    """A card whose uid disagrees with its columns is two cards wearing one
    key, and every language-merge bug starts there."""

    def test_a_mismatched_uid_is_refused(self):
        store = Store(":memory:")
        with self.assertRaises(duckdb.ConstraintException):
            store.con.execute(
                "INSERT INTO cards (card_uid, game, set_code, number, variant, "
                "language, observed_at, source) VALUES "
                "('pkmn:sv3:223/197:sir:EN', 'pkmn', 'sv3', '223/197', 'sir', "
                "'JP', ?, 'x')", [now()])

    def test_two_languages_of_one_number_are_two_rows(self):
        store = Store(":memory:")
        for language in ("EN", "JP", "CN-S"):
            store.upsert_card(card_uid=f"optcg:OP01:OP01-121:base:{language}",
                              game="optcg", set_code="OP01", number="OP01-121",
                              variant="base", language=language, source="t")
        self.assertEqual(store.con.execute(
            "SELECT count(*) FROM cards WHERE number = 'OP01-121'"
        ).fetchone()[0], 3)


class HistoryIsAppendOnly(unittest.TestCase):

    def test_the_writer_has_no_update_or_delete(self):
        """First line of defence: an API with no path to a mutation."""
        for forbidden in ("update", "delete", "remove", "overwrite"):
            self.assertFalse(
                any(name.startswith(forbidden) for name in dir(Store)),
                f"Store exposes a {forbidden}* method")

    def test_a_correction_is_a_new_row_pointing_at_the_old_one(self):
        store = seeded()
        original = store.add_price(
            card_uid=CARD, grade="10", condition="graded", grader="PSA",
            marketplace="ebay", amount="540", currency="USD",
            as_of=now() - _dt.timedelta(days=1),
            observed_at=now() - _dt.timedelta(hours=2), source="t")
        replacement = store.supersede(
            "price_snapshot", original, card_uid=CARD, grade="10",
            condition="graded", grader="PSA", marketplace="ebay",
            amount="545", currency="USD", as_of=now() - _dt.timedelta(days=1),
            observed_at=now(), source="t")
        rows = store.con.execute(
            "SELECT count(*) FROM price_snapshot").fetchone()[0]
        self.assertEqual(rows, 2, "the original must still be there")
        self.assertEqual(store.con.execute(
            "SELECT supersedes FROM price_snapshot WHERE row_id = ?",
            [replacement]).fetchone()[0], original)

    def test_a_correction_observed_no_later_is_refused(self):
        """Two rows with the same observed_at cannot be ordered, so one cannot
        be said to correct the other."""
        store = seeded()
        stamp = now() - _dt.timedelta(hours=1)
        original = store.add_price(
            card_uid=CARD, grade="10", condition="graded", grader="PSA",
            marketplace="ebay", amount="540", currency="USD",
            as_of=stamp, observed_at=stamp, source="t")
        with self.assertRaises(StoreError):
            store.supersede("price_snapshot", original, card_uid=CARD,
                            grade="10", condition="graded", grader="PSA",
                            marketplace="ebay", amount="545", currency="USD",
                            as_of=stamp, observed_at=stamp, source="t")

    def test_the_seal_detects_a_mutation_the_database_cannot_prevent(self):
        """DuckDB has no triggers, so this is the guarantee that actually
        exists here. Postgres turns it into prevention."""
        store = seeded()
        store.add_price(card_uid=CARD, grade="10", condition="graded",
                        grader="PSA", marketplace="ebay", amount="540",
                        currency="USD", as_of=now(), observed_at=now(),
                        source="t")
        self.assertTrue(store.verify_seal()["intact"])
        # Tamper the way only a direct connection can.
        store.con.execute("UPDATE ledger_seal SET row_hash = 'forged' "
                          "WHERE seq = (SELECT max(seq) FROM ledger_seal)")
        broken = store.verify_seal()
        self.assertFalse(broken["intact"])
        self.assertIsNotNone(broken["broken_at"])


class TheSharedQueryWrapper(unittest.TestCase):
    """CLAUDE.md non-negotiable 1: never bypass it."""

    def setUp(self):
        self.store = seeded()
        self.yesterday = now() - _dt.timedelta(days=1)
        self.old = self.store.add_price(
            card_uid=CARD, grade="10", condition="graded", grader="PSA",
            marketplace="ebay", amount="540", currency="USD",
            as_of=self.yesterday, observed_at=self.yesterday, source="t")
        self.new = self.store.add_price(
            card_uid=CARD, grade="10", condition="graded", grader="PSA",
            marketplace="ebay", amount="560", currency="USD",
            as_of=now(), observed_at=now(), source="t")

    def test_a_row_observed_later_is_invisible_at_an_earlier_timestamp(self):
        rows = self.store.as_of_view(
            "price_snapshot", self.yesterday).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], self.old)

    def test_both_rows_are_visible_now(self):
        rows = self.store.as_of_view("price_snapshot", now()).fetchall()
        self.assertEqual(len(rows), 2)

    def test_a_superseded_row_drops_out_once_its_replacement_is_visible(self):
        replacement = self.store.supersede(
            "price_snapshot", self.old, card_uid=CARD, grade="10",
            condition="graded", grader="PSA", marketplace="ebay",
            amount="541", currency="USD", as_of=self.yesterday,
            observed_at=now(), source="t")
        ids = {r[0] for r in self.store.as_of_view(
            "price_snapshot", now()).fetchall()}
        self.assertNotIn(self.old, ids)
        self.assertIn(replacement, ids)

    def test_the_superseded_row_is_still_visible_before_the_correction(self):
        """Point-in-time means the app can show what it showed. A correction
        made today does not retroactively change yesterday's answer."""
        self.store.supersede(
            "price_snapshot", self.old, card_uid=CARD, grade="10",
            condition="graded", grader="PSA", marketplace="ebay",
            amount="541", currency="USD", as_of=self.yesterday,
            observed_at=now(), source="t")
        ids = {r[0] for r in self.store.as_of_view(
            "price_snapshot", self.yesterday).fetchall()}
        self.assertIn(self.old, ids)

    def test_a_thin_fuzzy_xref_never_reaches_a_signal(self):
        self.store.add_xref(card_uid=CARD, source="tcgapi", external_id="a",
                            confidence=0.85, resolved_by="fuzzy",
                            as_of=self.yesterday, observed_at=self.yesterday)
        self.store.add_xref(card_uid=CARD, source="tcgapi", external_id="b",
                            confidence=0.95, resolved_by="fuzzy",
                            as_of=self.yesterday, observed_at=self.yesterday)
        # By NAME, not by position: card_xref has an optional secondary_id
        # between external_id and confidence, and an index here silently read
        # the wrong column.
        relation = self.store.signal_ready_xrefs(now())
        confidence_at = relation.columns.index("confidence")
        usable = {r[confidence_at] for r in relation.fetchall()}
        self.assertEqual(usable, {Decimal("0.950")})

    def test_an_exact_match_below_full_confidence_is_a_contradiction(self):
        with self.assertRaises(duckdb.ConstraintException):
            self.store.add_xref(card_uid=CARD, source="tcgapi",
                                external_id="c", confidence=0.8,
                                resolved_by="exact", as_of=self.yesterday,
                                observed_at=self.yesterday)


class GapsAreRowsNotSilence(unittest.TestCase):

    def test_coverage_names_the_missing_days(self):
        store = seeded()
        start = now() - _dt.timedelta(days=4)
        for offset in (0, 1, 3, 4):
            day = start + _dt.timedelta(days=offset)
            store.add_price(card_uid=CARD, grade="raw", condition="nm",
                            marketplace="ebay", amount="140", currency="USD",
                            as_of=day, observed_at=now(), source="t")
        coverage = store.coverage("price_snapshot", CARD, start, now())
        self.assertEqual(coverage["present"], 4)
        self.assertEqual(len(coverage["missing"]), 1)
        self.assertEqual(coverage["consecutive"], 2)

    def test_a_gap_row_says_which_source_and_why(self):
        store = seeded()
        store.add_gap(source="tcgapi", kind="unreachable",
                      reason="adapter gave up", as_of=now(), observed_at=now())
        row = store.con.execute(
            "SELECT source, kind, reason FROM ingest_gap").fetchone()
        self.assertEqual(row, ("tcgapi", "unreachable", "adapter gave up"))


class SentimentSaysWhetherItWasBackfilled(unittest.TestCase):
    """GOAL D4: backfilled rows are excluded from every backtest, and a null
    cannot be excluded."""

    def test_backfilled_is_not_nullable(self):
        store = seeded()
        with self.assertRaises(duckdb.ConstraintException):
            store.con.execute(
                "INSERT INTO sentiment (row_id, card_uid, platform, mentions, "
                "as_of, observed_at, backfilled, source) VALUES "
                "(9100, ?, 'youtube', 5, ?, ?, NULL, 'x')",
                [CARD, now(), now()])

    def test_the_writer_will_not_default_it(self):
        store = seeded()
        with self.assertRaises(StoreError):
            store.add_sentiment(card_uid=CARD, platform="youtube", mentions=5,
                                as_of=now(), observed_at=now(),
                                backfilled=None, source="t")


if __name__ == "__main__":
    unittest.main(verbosity=2)
