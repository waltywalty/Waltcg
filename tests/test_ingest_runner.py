"""When the daily run should go red, and when it must not.

Run #3 failed entirely because one deliberately-deferred paid provider had no
key. Four working providers ingested nothing, no store was written, no artifact
was uploaded, and the job summary -- the one artefact whose job is explaining a
failure -- came back empty because it read a database the failure had prevented
from existing.

Three outcomes, three meanings, and the whole point is that they are different:

  * absent BY CHOICE      -> gap row, run continues, exit 0
  * configured but failed -> failure, exit 1
  * zero rows ingested    -> failure, exit 1
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest.base import Adapter, AdapterGaveUp, Record  # noqa: E402
from ingest.runner import (STATUS, decide_exit, load_expectations,  # noqa: E402
                           render_summary, run_source)
from store.db import Store  # noqa: E402

CARD = "pkmn:sv3:223/197:sir:EN"


def seeded_store():
    store = Store(":memory:")
    store.upsert_card(card_uid=CARD, game="pkmn", set_code="sv3",
                      number="223/197", variant="sir", language="EN",
                      source="test")
    return store


class Working(Adapter):
    name = "working"
    key_env = None

    def fetch(self, since=None, **kw):
        now = self._now()
        return [Record(kind="price", source=self.name, as_of=now,
                       observed_at=now,
                       payload={"card_uid": CARD, "grade": "raw",
                                "condition": "nm", "marketplace": "ebay",
                                "amount": "140.00", "currency": "USD"})]


class Silent(Adapter):
    """Reached, returned nothing. Not the same as unreachable."""
    name = "silent"
    key_env = None

    def fetch(self, since=None, **kw):
        return []


class Broken(Adapter):
    name = "broken"
    key_env = None

    def fetch(self, since=None, **kw):
        raise AdapterGaveUp("broken: gave up after 4 attempts")


class Keyless(Adapter):
    name = "keyless"
    key_env = "DEFINITELY_NOT_SET_KEY"


class ADeferredSourceDoesNotFailTheRun(unittest.TestCase):
    """The bug. One deferred paid provider took down four working ones."""

    def test_a_deferred_source_is_a_gap_not_a_failure(self):
        store = seeded_store()
        result = run_source(store, "keyless", Keyless(), {},
                            {"expected": False,
                             "deferred_note": "paid; deferred by choice"})
        self.assertEqual(result["status"], "deferred")
        self.assertFalse(STATUS["deferred"]["failure"])
        self.assertIn("deferred by choice", result["detail"])

    def test_it_still_writes_a_gap_row(self):
        """Skipped is not the same as absent from history. The store must never
        imply the source was consulted."""
        store = seeded_store()
        run_source(store, "keyless", Keyless(), {}, {"expected": False})
        row = store.con.execute(
            "SELECT source, kind, reason FROM ingest_gap").fetchone()
        self.assertEqual(row[0], "keyless")
        self.assertEqual(row[1], "auth")
        self.assertIn("deferred", row[2])

    def test_the_real_configuration_exits_zero(self):
        """Four expected sources working, PriceCharting deferred."""
        results = [
            {"source": "tcgapi", "status": "ok", "rows": 12, "gaps": 0},
            {"source": "pokemonpricetracker", "status": "ok", "rows": 40, "gaps": 0},
            {"source": "apitcg", "status": "ok", "rows": 8, "gaps": 0},
            {"source": "fx_alphavantage", "status": "ok", "rows": 5, "gaps": 0},
            {"source": "pricecharting", "status": "deferred", "rows": 0, "gaps": 1},
        ]
        code, reason = decide_exit(results)
        self.assertEqual(code, 0, reason)


class AConfiguredSourceThatFailsIsAFailure(unittest.TestCase):

    def test_a_missing_key_on_an_EXPECTED_source_fails(self):
        """The safety net. Deferred-by-choice must not become a hiding place
        for a key that was deleted by accident."""
        store = seeded_store()
        result = run_source(store, "keyless", Keyless(), {},
                            {"expected": True})
        self.assertEqual(result["status"], "not_configured")
        self.assertTrue(STATUS["not_configured"]["failure"])

    def test_an_adapter_that_gave_up_fails(self):
        store = seeded_store()
        result = run_source(store, "broken", Broken(), {}, {"expected": True})
        self.assertEqual(result["status"], "failed")
        code, _ = decide_exit([{"source": "a", "status": "ok", "rows": 5, "gaps": 0},
                               result])
        self.assertEqual(code, 1, "one failure must fail the run even when "
                                  "another source succeeded")

    def test_the_failure_names_the_source_and_the_status(self):
        code, reason = decide_exit([
            {"source": "tcgapi", "status": "failed", "rows": 0, "gaps": 1},
            {"source": "apitcg", "status": "ok", "rows": 3, "gaps": 0}])
        self.assertEqual(code, 1)
        self.assertIn("tcgapi", reason)
        self.assertIn("failed", reason)


class ZeroIngestedIsAFailure(unittest.TestCase):
    """A day with no data is a failure even when nothing errored."""

    def test_everything_deferred_still_fails(self):
        code, reason = decide_exit([
            {"source": "a", "status": "deferred", "rows": 0, "gaps": 1},
            {"source": "b", "status": "deferred", "rows": 0, "gaps": 1}])
        self.assertEqual(code, 1)
        self.assertIn("zero sources ingested", reason)

    def test_reached_but_empty_is_not_ingested(self):
        store = seeded_store()
        result = run_source(store, "silent", Silent(), {}, {"expected": True})
        self.assertEqual(result["status"], "empty")
        self.assertFalse(STATUS["empty"]["ingested"])
        self.assertFalse(STATUS["empty"]["failure"],
                         "reaching a source and getting nothing is not the "
                         "source's failure; it fails the run only by leaving "
                         "the day empty")
        code, _ = decide_exit([result])
        self.assertEqual(code, 1)

    def test_one_row_is_enough_to_pass(self):
        store = seeded_store()
        result = run_source(store, "working", Working(), {}, {"expected": True})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["rows"], 1)
        code, _ = decide_exit([result,
                               {"source": "x", "status": "deferred",
                                "rows": 0, "gaps": 1}])
        self.assertEqual(code, 0)


class TheSummaryAlwaysRenders(unittest.TestCase):
    """It came back empty once, which is the one thing that must not happen:
    the artefact that explains a failure cannot depend on the thing that
    failed."""

    RESULTS = [
        {"source": "tcgapi", "status": "ok", "rows": 12, "gaps": 0,
         "quota": "provider reports 88/100 remaining"},
        {"source": "pricecharting", "status": "deferred", "rows": 0, "gaps": 1,
         "detail": "PRICECHARTING_TOKEN is not set -- paid, deferred"},
        {"source": "apitcg", "status": "failed", "rows": 0, "gaps": 1,
         "detail": "gave up after 4 attempts"},
    ]

    def test_it_names_who_ran_who_was_skipped_and_why(self):
        text = render_summary(self.RESULTS)
        self.assertIn("tcgapi", text)
        self.assertIn("pricecharting", text)
        self.assertIn("skipped by choice", text)
        self.assertIn("deferred", text)
        self.assertIn("FAILED", text)
        self.assertIn("gave up after 4 attempts", text)

    def test_it_renders_with_no_database_at_all(self):
        """Built only from the results list. Nothing in it can fail."""
        text = render_summary(self.RESULTS, seal=None, db_path=None)
        self.assertGreater(len(text), 200)
        self.assertIn("| Source | Status | Rows | Gaps | Detail |", text)

    def test_it_renders_when_every_source_failed(self):
        text = render_summary([
            {"source": "a", "status": "not_configured", "rows": 0, "gaps": 1,
             "detail": "A_KEY is not set"}])
        self.assertIn("FAILED", text)
        self.assertIn("KEY MISSING", text)

    def test_failures_sort_to_the_top(self):
        lines = render_summary(self.RESULTS).splitlines()
        rows = [l for l in lines if l.startswith("| `")]
        self.assertTrue(rows[0].startswith("| `apitcg`"),
                        f"failures must lead the table, got {rows[0]}")

    def test_a_pipe_in_a_detail_cannot_break_the_table(self):
        text = render_summary([{"source": "a", "status": "failed", "rows": 0,
                                "gaps": 1, "detail": "a|b|c"}])
        self.assertIn(r"a\|b\|c", text)

    def test_the_verdict_line_states_the_outcome(self):
        ok = render_summary([{"source": "a", "status": "ok", "rows": 3, "gaps": 0}])
        self.assertIn("OK -- 1 source(s) ingested 3 row(s)", ok)
        none = render_summary([{"source": "a", "status": "deferred",
                                "rows": 0, "gaps": 1}])
        self.assertIn("zero sources ingested", none)


class TheExpectationsFileIsReadable(unittest.TestCase):

    def test_pricecharting_is_declared_deferred(self):
        sources = load_expectations()
        self.assertIn("pricecharting", sources)
        self.assertFalse(sources["pricecharting"]["expected"])
        self.assertIn("deferred_note", sources["pricecharting"])

    def test_the_other_four_are_expected(self):
        sources = load_expectations()
        for name in ("tcgapi", "pokemonpricetracker", "apitcg",
                     "fx_alphavantage"):
            self.assertTrue(sources[name]["expected"], name)

    def test_a_deferred_source_records_why(self):
        """So a future reader knows it was a decision, not an oversight."""
        note = load_expectations()["pricecharting"]["deferred_note"]
        self.assertGreater(len(note), 40)


class TheStoreExistsEvenWhenNothingIngests(unittest.TestCase):
    """No store meant no artifact, which meant no evidence about the run."""

    def test_a_run_where_everything_is_deferred_still_has_a_database(self):
        store = seeded_store()
        run_source(store, "keyless", Keyless(), {}, {"expected": False})
        tables = {r[0] for r in store.con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}
        self.assertIn("ingest_gap", tables)
        self.assertEqual(store.con.execute(
            "SELECT count(*) FROM ingest_gap").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
