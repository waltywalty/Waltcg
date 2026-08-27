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


# ---------------------------------------------------------------------------
# Run #4: a reporting step that could crash, and code that could take the run
# down before anything ran
# ---------------------------------------------------------------------------


class ThePreflightContractHoldsOnEveryBranch(unittest.TestCase):
    """Run #4 died in fifteen seconds with a KeyError on `key_length`.

    `preflight()` returned a SHORT dict for a keyless source and a full one
    otherwise, and the reporting step read `key_length` on the ready branch.
    Five key-bearing adapters had exercised that branch for months; the first
    keyless adapter reached it and the job was over before any provider ran.

    A contract whose shape depends on a branch only holds on the branches
    something has exercised. So the shape is now invariant.
    """

    KEYS = ("source", "key_required", "ready", "env", "key_length",
            "key_prefix", "reason")

    # NB: the module-level `Keyless` means "key absent", not "no key required".
    # This one is genuinely keyless, which is the case run #4 tripped over.
    class NoKeyNeeded(Adapter):
        name = "nokey"
        key_env = None

    def test_a_keyless_source_returns_the_same_keys_as_a_key_bearing_one(self):
        keyless = self.NoKeyNeeded().preflight()
        bearing = Working().preflight()
        self.assertEqual(set(keyless), set(bearing))
        for key in self.KEYS:
            self.assertIn(key, keyless)

    def test_a_keyless_source_is_ready_and_requires_nothing(self):
        info = self.NoKeyNeeded().preflight()
        self.assertTrue(info["ready"])
        self.assertFalse(info["key_required"])
        self.assertIsNone(info["env"])
        self.assertEqual(info["key_length"], 0)

    def test_no_preflight_ever_reveals_a_key(self):
        os.environ["WALTCG_TEST_KEY"] = "supersecretvalue"
        try:
            class Bearing(Adapter):
                name, key_env = "bearing", "WALTCG_TEST_KEY"
            info = Bearing().preflight()
        finally:
            os.environ.pop("WALTCG_TEST_KEY")
        self.assertNotIn("supersecretvalue", repr(info))
        self.assertEqual(info["key_prefix"], "supe")
        self.assertEqual(info["key_length"], 16)


class ThePreflightReportCannotFailTheRun(unittest.TestCase):
    """It is a REPORT. The one thing it must never do is stop the thing it is
    reporting on -- which is exactly what it did on run #4."""

    def test_it_renders_a_keyless_source_without_raising(self):
        from ingest.runner import render_preflight
        class NoKeyNeeded(Adapter):
            name, key_env = "nokey", None

        report = render_preflight(expectations={},
                                  adapters={"nokey": NoKeyNeeded}, broken={})
        self.assertIn("no key required", report)

    def test_it_renders_a_source_whose_code_did_not_import(self):
        from ingest.runner import render_preflight
        report = render_preflight(
            expectations={}, adapters={},
            broken={"tcgdex": {"module": "ingest.catalog_sources",
                               "error": "ImportError: no module named nope",
                               "traceback": "Traceback..."}})
        self.assertIn("CODE DID NOT IMPORT", report)
        self.assertIn("no module named nope", report)

    def test_it_survives_an_adapter_whose_preflight_raises(self):
        """Belt and braces. Anything reachable from a report is a thing that
        can end the run if the report is allowed to die."""
        from ingest.runner import render_preflight

        class Exploding(Adapter):
            name = "exploding"

            def preflight(self):
                raise RuntimeError("boom")

        report = render_preflight(expectations={},
                                  adapters={"exploding": Exploding}, broken={})
        self.assertIn("preflight raised", report)
        self.assertIn("boom", report)

    def test_it_marks_which_sources_are_unverified(self):
        from ingest.runner import render_preflight
        report = render_preflight(
            expectations={"keyless": {"unverified": True}},
            adapters={"keyless": Keyless}, broken={})   # key absent + unverified
        self.assertIn("unverified", report)


class ABrokenImportIsOneBrokenSource(unittest.TestCase):
    """The structural fix. New, speculative code used to execute in the same
    breath as four working providers, so it could stop them before they
    started. Now each module is imported on its own terms."""

    def test_the_registry_returns_the_ones_that_loaded_and_names_the_rest(self):
        from ingest.registry import load
        adapters, broken = load((
            ("tcgapi", "ingest.adapters", "TcgApiAdapter"),
            ("nope", "ingest.this_module_does_not_exist", "Whatever"),
        ))
        self.assertIn("tcgapi", adapters)
        self.assertIn("nope", broken)
        self.assertIn("Traceback", broken["nope"]["traceback"])

    def test_a_missing_class_in_a_real_module_is_also_contained(self):
        from ingest.registry import load
        adapters, broken = load((
            ("tcgapi", "ingest.adapters", "TcgApiAdapter"),
            ("ghost", "ingest.adapters", "NoSuchAdapter"),
        ))
        self.assertEqual(list(adapters), ["tcgapi"])
        self.assertIn("AttributeError", broken["ghost"]["error"])

    def test_the_speculative_adapters_live_in_their_own_module(self):
        """Load-bearing, not cosmetic: the three unverified adapters are the
        code most likely to be wrong, and keeping them out of adapters.py is
        what makes their breakage containable at all."""
        from ingest.registry import SPECS
        modules = {name: module for name, module, _c in SPECS}
        for name in ("tcgdex", "cryst", "wiki52poke"):
            self.assertEqual(modules[name], "ingest.catalog_sources")
        for name in ("tcgapi", "pokemonpricetracker", "apitcg",
                     "pricecharting", "fx_alphavantage"):
            self.assertEqual(modules[name], "ingest.adapters")

    def test_an_unverified_source_that_will_not_import_is_a_gap(self):
        from ingest.runner import broken_source
        store = seeded_store()
        result = broken_source(store, "tcgdex",
                               {"module": "ingest.catalog_sources",
                                "error": "SyntaxError: bad", "traceback": "T"},
                               {"unverified": True})
        self.assertEqual(result["status"], "unverified_failed")
        self.assertFalse(STATUS[result["status"]]["failure"])
        self.assertEqual(decide_exit([
            {"source": "tcgapi", "status": "ok", "rows": 9, "gaps": 0},
            result])[0], 0)

    def test_an_expected_source_that_will_not_import_still_fails_the_run(self):
        """Containment is not forgiveness. A verified provider whose code
        broke is a real regression and the run must go red -- just not before
        the others have run and the summary has rendered."""
        from ingest.runner import broken_source
        store = seeded_store()
        result = broken_source(store, "tcgapi",
                               {"module": "ingest.adapters",
                                "error": "ImportError: x", "traceback": "T"},
                               {"expected": True})
        self.assertEqual(result["status"], "failed")
        self.assertTrue(STATUS[result["status"]]["failure"])
        self.assertEqual(decide_exit([result])[0], 1)

    def test_it_writes_a_gap_row_so_the_store_records_the_day(self):
        from ingest.runner import broken_source
        store = seeded_store()
        broken_source(store, "cryst",
                      {"module": "ingest.catalog_sources",
                       "error": "ImportError: x", "traceback": "T"},
                      {"unverified": True})
        rows = store.con.execute(
            "SELECT kind, reason FROM ingest_gap WHERE source = 'cryst'"
        ).fetchall()
        self.assertEqual(rows[0][0], "broken_import")

    def test_the_summary_carries_the_traceback(self):
        """Run #4's traceback was lost entirely -- the reporting step died
        alongside the code it was reporting on. The traceback is the only
        thing that can fix a broken import, so it has to survive."""
        summary = render_summary([
            {"source": "tcgapi", "status": "ok", "rows": 12, "gaps": 0},
            {"source": "tcgdex", "status": "unverified_failed", "rows": 0,
             "gaps": 1, "detail": "import failed",
             "traceback": "Traceback (most recent call last):\n  KeyError: 'x'"},
        ])
        self.assertIn("did not import", summary)
        self.assertIn("KeyError", summary)
        self.assertIn("OK --", summary,
                      "a broken unverified source took the run down with it")

    def test_a_broken_source_still_appears_in_the_run(self):
        """It is absent from ADAPTERS, so iterating that would make it vanish
        -- no row, no gap, no line in the summary. Disappearing quietly is the
        one outcome this runner exists to prevent."""
        from ingest.registry import ALL_SOURCE_NAMES, SPECS
        self.assertEqual(set(ALL_SOURCE_NAMES),
                         {name for name, _m, _c in SPECS})
        self.assertIn("tcgdex", ALL_SOURCE_NAMES)


class EveryAdapterImportsFromRequirementsAlone(unittest.TestCase):
    """The 60ade11 check, made permanent. That failure passed locally because
    the session environment already had jsonschema and never declared it."""

    def test_nothing_is_broken_right_now(self):
        from ingest.registry import BROKEN_ADAPTERS
        self.assertEqual(
            BROKEN_ADAPTERS, {},
            "an adapter module does not import: "
            + "; ".join(f"{n}: {f['error']}"
                        for n, f in BROKEN_ADAPTERS.items()))

    def test_no_adapter_module_imports_a_third_party_package(self):
        """A declared dependency is one CI installs. An undeclared one is one
        that happens to be in the environment you tested in."""
        import ast
        declared = {"yaml", "duckdb", "jsonschema"}
        for module in ("ingest/adapters.py", "ingest/catalog_sources.py",
                       "ingest/base.py", "ingest/registry.py"):
            with open(module, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [(node.module or "").split(".")[0]]
                for name in names:
                    if name in declared:
                        continue
                    self.assertIn(
                        name, sys.stdlib_module_names | {"ingest", "resolve",
                                                         "store", ""},
                        f"{module} imports {name!r}, which is neither stdlib "
                        "nor declared in requirements.txt")


class TheRunCoversEverySourceEvenTheBrokenOnes(unittest.TestCase):
    """End to end through main(). The unit tests above assert the pieces; this
    asserts the loop actually visits a source that is absent from ADAPTERS.

    Iterating ADAPTERS instead of ALL_SOURCE_NAMES makes a broken source
    vanish -- no row, no gap, no line in the summary -- which is the same
    silent disappearance the gap rows exist to prevent, arriving through a
    different door.
    """

    def test_a_source_missing_from_adapters_still_produces_a_result(self):
        import json as _json
        import tempfile
        from ingest import runner as mod

        saved = mod.ADAPTERS, mod.BROKEN_ADAPTERS
        mod.ADAPTERS = {k: v for k, v in saved[0].items() if k != "tcgdex"}
        mod.BROKEN_ADAPTERS = {"tcgdex": {
            "module": "ingest.catalog_sources",
            "error": "SyntaxError: '(' was never closed",
            "traceback": "Traceback (most recent call last): SyntaxError"}}
        work = tempfile.mkdtemp()
        results_path = os.path.join(work, "r.json")
        try:
            mod.main(["--db", os.path.join(work, "t.duckdb"),
                      "--results", results_path])
            with open(results_path, encoding="utf-8") as handle:
                results = _json.load(handle)["results"]
        finally:
            mod.ADAPTERS, mod.BROKEN_ADAPTERS = saved

        by_source = {r["source"]: r for r in results}
        self.assertEqual(set(by_source), set(mod.ALL_SOURCE_NAMES),
                         "a source dropped out of the run entirely")
        # tcgdex was promoted to a hard dependency once run #5 verified it
        # (877 CN-S, 7,436 CN-T), so its breakage now fails the run -- it is
        # the only catalog source either Chinese Pokemon printing has.
        self.assertEqual(by_source["tcgdex"]["status"], "failed")
        self.assertIn("SyntaxError", by_source["tcgdex"]["traceback"])

    def test_the_database_and_results_survive_a_broken_module(self):
        """Run #4 produced neither. Both are what a post-mortem reads."""
        import tempfile
        from ingest import runner as mod

        saved = mod.ADAPTERS, mod.BROKEN_ADAPTERS
        mod.ADAPTERS = {}
        mod.BROKEN_ADAPTERS = {n: {"module": "m", "error": "ImportError: x",
                                   "traceback": "T"}
                               for n in mod.ALL_SOURCE_NAMES}
        work = tempfile.mkdtemp()
        db_path = os.path.join(work, "t.duckdb")
        summary_path = os.path.join(work, "s.md")
        try:
            code = mod.main(["--db", db_path, "--summary", summary_path])
        finally:
            mod.ADAPTERS, mod.BROKEN_ADAPTERS = saved

        self.assertEqual(code, 1, "every source broken should still exit 1")
        self.assertTrue(os.path.exists(db_path), "no database was written")
        with open(summary_path, encoding="utf-8") as handle:
            summary = handle.read()
        self.assertIn("did not import", summary)
        self.assertTrue(summary.strip(), "the summary came back empty again")


# ---------------------------------------------------------------------------
# Run #5: green with 8,313 identities and zero prices
# ---------------------------------------------------------------------------


class ASourceThatWasNeverAskedIsNotASourceWithNothingToSay(unittest.TestCase):
    """Run #5 ingested 8,313 card identities and no prices, and passed.

    tcgapi, PPT and apitcg each reported "0 calls made this run". targets.json
    was still the hand-authored stub with an empty card list for every price
    source, so each adapter iterated over nothing and returned nothing -- which
    reads as `empty`, and `empty` does not fail a run. Meanwhile tcgdex had
    ingested thousands of rows, so `decide_exit` saw a source that ingested and
    returned 0.

    Identities without prices is not a snapshot. The distinction that was
    missing: asked-and-got-nothing versus never-asked.
    """

    class NeedsCards(Adapter):
        name = "needscards"
        key_env = None
        requires_targets = True

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.calls = 0

        def fetch(self, since=None, cards=()):
            self.calls += 1
            return []

    def test_a_price_source_with_no_targets_fails_the_run(self):
        store = seeded_store()
        adapter = self.NeedsCards()
        result = run_source(store, "needscards", adapter, {}, {})
        self.assertEqual(result["status"], "no_targets")
        self.assertTrue(STATUS["no_targets"]["failure"])
        self.assertEqual(decide_exit([result])[0], 1)

    def test_it_does_not_even_call_the_adapter(self):
        """Nothing to ask about. Calling anyway spends quota to confirm it."""
        store = seeded_store()
        adapter = self.NeedsCards()
        run_source(store, "needscards", adapter, {}, {})
        self.assertEqual(adapter.calls, 0)

    def test_the_run_fails_even_when_another_source_ingested_plenty(self):
        """The exact shape of run #5: a catalog source succeeds loudly and
        carries a run with no prices in it over the line."""
        code, reason = decide_exit([
            {"source": "tcgdex", "status": "ok", "rows": 8313, "gaps": 0},
            {"source": "tcgapi", "status": "no_targets", "rows": 0, "gaps": 1},
        ])
        self.assertEqual(code, 1)
        self.assertIn("tcgapi", reason)

    def test_the_old_behaviour_would_have_passed(self):
        """Pins the bug so the fix cannot be quietly undone: with the same two
        sources but `empty` instead of `no_targets`, the run goes green."""
        code, _reason = decide_exit([
            {"source": "tcgdex", "status": "ok", "rows": 8313, "gaps": 0},
            {"source": "tcgapi", "status": "empty", "rows": 0, "gaps": 1},
        ])
        self.assertEqual(code, 0, "the old shape should still read as green")

    def test_targets_present_for_another_source_do_not_count(self):
        """`targets.get(name, {})` is per-source. A source is asked only if
        ITS list has entries."""
        from ingest.runner import _has_targets
        self.assertFalse(_has_targets({}))
        self.assertFalse(_has_targets({"cards": []}))
        self.assertTrue(_has_targets({"cards": [{"card_uid": "x"}]}))

    def test_a_source_that_needs_nothing_is_unaffected(self):
        """The FX and catalog adapters supply their own work list."""
        from ingest.registry import ADAPTERS
        self.assertFalse(ADAPTERS["fx_alphavantage"].requires_targets)
        self.assertFalse(ADAPTERS["tcgdex"].requires_targets)
        for name in ("tcgapi", "pokemonpricetracker", "apitcg", "pricecharting"):
            self.assertTrue(ADAPTERS[name].requires_targets,
                            f"{name} prices a card list and must say so")


class SupersededAndIdleAreNotGaps(unittest.TestCase):

    def test_a_superseded_source_is_not_called_and_writes_no_gap(self):
        class Loud(Adapter):
            name, key_env = "loud", None

            def fetch(self, since=None, **kw):
                raise AssertionError("a superseded source was called")

        store = seeded_store()
        result = run_source(store, "cryst", Loud(), {},
                            {"superseded_by": "tcgdex",
                             "superseded_note": "tcgdex covers it"})
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(result["gaps"], 0)
        self.assertFalse(STATUS["superseded"]["failure"])
        self.assertIn("tcgdex", result["detail"])
        rows = store.con.execute(
            "SELECT count(*) FROM ingest_gap WHERE source = 'cryst'").fetchone()
        self.assertEqual(rows[0], 0, "a superseded source wrote a gap row")

    def test_an_idle_enrichment_source_writes_no_gap(self):
        """Filing an idle enrichment source as a gap every single day devalues
        the gap rows that mean something."""
        store = seeded_store()
        result = run_source(store, "wiki52poke", Silent(), {"cards": [1]},
                            {"enrichment": True})
        self.assertEqual(result["status"], "enrichment_idle")
        self.assertEqual(result["gaps"], 0)
        self.assertFalse(STATUS["enrichment_idle"]["failure"])
        rows = store.con.execute(
            "SELECT count(*) FROM ingest_gap "
            "WHERE source = 'wiki52poke'").fetchone()
        self.assertEqual(rows[0], 0)

    def test_a_normal_source_returning_nothing_still_writes_a_gap(self):
        """The exemption is narrow. An ordinary source that reached its
        provider and got nothing is still a gap -- that is data we expected
        and did not get."""
        store = seeded_store()
        result = run_source(store, "silent", Silent(), {"cards": [1]}, {})
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["gaps"], 1)


class TheErrorBodyDetectionIsShared(unittest.TestCase):
    """HTTP 200 carrying an error body: nine times now, across five providers.

    The FX adapter had Alpha Vantage's three keys and, by declaring
    `ERROR_KEYS`, REPLACED the five generic ones -- so it gained a dialect and
    lost the shared vocabulary, while every other adapter never learned that
    `Information` means "you are being throttled".
    """

    def test_every_adapter_knows_the_shared_markers(self):
        from ingest.registry import ADAPTERS
        for name, cls in ADAPTERS.items():
            keys = set(cls.error_keys())
            for marker in ("error", "message", "note", "information"):
                self.assertIn(marker, keys,
                              f"{name} does not treat {marker!r} as an error")

    def test_a_provider_dialect_adds_rather_than_replaces(self):
        from ingest.adapters import FxAlphaVantageAdapter
        keys = set(FxAlphaVantageAdapter.error_keys())
        self.assertIn("errormessage", keys)     # Alpha Vantage's own
        self.assertIn("information", keys)      # its throttle marker
        self.assertIn("fault", keys)            # and the shared set, kept

    def test_the_throttle_shape_is_detected(self):
        """The actual run #5 payload shape: 200 OK, and a body that says no."""
        from ingest.adapters import FxAlphaVantageAdapter
        adapter = FxAlphaVantageAdapter()
        self.assertTrue(adapter.is_error_body(
            {"Information": "Thank you for using Alpha Vantage! Our standard "
                            "API rate limit is 25 requests per day."}))
        self.assertIn("Information", adapter.error_text(
            {"Information": "rate limit"}))

    def test_the_same_marker_is_caught_in_any_casing(self):
        """`Error Message`, `error_message` and `errorMessage` are one marker
        arriving from three providers, and a literal comparison catches one."""
        adapter = Working()
        for spelling in ("Error Message", "error_message", "errorMessage",
                         "ERROR-MESSAGE"):
            self.assertTrue(adapter.is_error_body({spelling: "nope"}),
                            f"{spelling!r} was not recognised")

    def test_a_healthy_payload_is_not_an_error(self):
        adapter = Working()
        self.assertFalse(adapter.is_error_body({"data": [1, 2, 3]}))
        self.assertFalse(adapter.is_error_body({"error": None}))
        self.assertFalse(adapter.is_error_body({"errors": []}))
        self.assertFalse(adapter.is_error_body([1, 2, 3]))


class TheFxAdapterRespectsAStatedRateLimit(unittest.TestCase):
    """Run #5 rate-limited Alpha Vantage on five FX pairs against a free tier
    of 25/day and 5/MINUTE. The daily cap was never the problem.

    Three things conspired: five pairs where three are needed, `max_attempts=4`
    behind each so up to twenty requests in a couple of seconds, and a retry on
    a throttle -- the one error where retrying immediately is guaranteed to
    fail and to deepen the hole.
    """

    def _adapter(self, routes, day="2026-08-17"):
        import tempfile
        from ingest.adapters import FxAlphaVantageAdapter

        clock = {"t": 0.0}

        def sleep(seconds):
            clock["t"] += seconds

        def transport(url, headers):
            import json as _json
            for fragment, payload in routes.items():
                if fragment in url:
                    return 200, _json.dumps(payload).encode("utf-8")
            return 200, _json.dumps({"Information": "rate limit"}).encode("utf-8")

        adapter = FxAlphaVantageAdapter(
            raw_root=tempfile.mkdtemp(), sleep=sleep, transport=transport,
            monotonic=lambda: clock["t"],
            now=lambda: _dt.datetime(2026, 8, 17, 6, 15))
        adapter.calls = []
        original = adapter._send

        def counted(url, hdrs):
            adapter.calls.append(url)
            return original(url, hdrs)

        adapter._send = counted
        adapter.clock = clock
        return adapter

    def _series(self, close="1.2700"):
        return {"Time Series FX (Daily)": {"2026-08-17": {"4. close": close}}}

    def test_only_three_pairs_are_requested(self):
        """EUR and HKD were speculative and cost two of the five per-minute
        slots for rates nothing reads."""
        from ingest.adapters import FxAlphaVantageAdapter
        self.assertEqual(len(FxAlphaVantageAdapter.PAIRS), 3)
        self.assertNotIn(("EUR", "USD"), FxAlphaVantageAdapter.PAIRS)

    def test_one_request_per_pair_per_run(self):
        adapter = self._adapter({"from_symbol=GBP": self._series(),
                                 "from_symbol=USD": self._series("150.0")})
        adapter.fetch()
        self.assertEqual(len(adapter.calls), 3,
                         f"expected one call per pair, got {adapter.calls}")

    def test_it_waits_between_calls(self):
        """5/minute is one per 12s. Without a floor, three pairs go out in
        milliseconds and the fourth request of the day is refused."""
        from ingest.adapters import FxAlphaVantageAdapter
        self.assertGreaterEqual(FxAlphaVantageAdapter.min_interval_seconds, 12)
        adapter = self._adapter({"from_symbol=GBP": self._series(),
                                 "from_symbol=USD": self._series("150.0")})
        adapter.fetch()
        # Two gaps between three calls.
        self.assertGreaterEqual(adapter.clock["t"], 24)

    def test_a_throttle_is_not_retried(self):
        """A 200-with-an-error-body saying 'rate limit' is not a transient
        network error. Retrying it is asking harder."""
        from ingest.adapters import FxAlphaVantageAdapter
        self.assertEqual(FxAlphaVantageAdapter.max_attempts, 1)
        adapter = self._adapter({})          # everything throttles
        with self.assertRaises(AdapterGaveUp):
            adapter.fetch()
        self.assertEqual(len(adapter.calls), 3,
                         "a throttled pair was retried")

    def test_one_throttled_pair_does_not_lose_the_others(self):
        adapter = self._adapter({"from_symbol=GBP": self._series()})
        records = adapter.fetch()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].payload["pair"], "GBP/USD")

    def test_todays_rate_is_cached_so_a_later_failure_does_not_lose_it(self):
        """A run that dies on pair three must not also lose pairs one and two.
        Losing the whole day to one throttle puts a gap in every converted
        figure, and the engine refuses to convert without a rate."""
        routes = {"from_symbol=GBP": self._series("1.2700")}
        first = self._adapter(routes)
        first.fetch()

        second = self._adapter({})           # everything throttles now
        second.raw_root = first.raw_root     # same day, same cache
        records = second.fetch()
        self.assertEqual(len(records), 1)
        self.assertEqual(str(records[0].payload["rate"]), "1.2700")
        self.assertEqual(len(second.calls), 2,
                         "a cached pair was requested again")

    def test_the_cached_rate_keeps_its_own_as_of(self):
        """A cached rate is the rate it was, not the rate as of now. Restamping
        it would be a look-ahead violation dressed as a convenience."""
        adapter = self._adapter({"from_symbol=GBP": self._series()})
        adapter.fetch()
        again = self._adapter({})
        again.raw_root = adapter.raw_root
        record = again.fetch()[0]
        self.assertEqual(record.as_of.date().isoformat(), "2026-08-17")
        self.assertGreaterEqual(record.observed_at, record.as_of)


class ACardNameWithASpaceDoesNotKillTheRun(unittest.TestCase):
    """`InvalidURL: URL can't contain control characters` on
    `/v1/search?q=Rare Candy&game=55`. It raised from inside the transport, so
    it was not an adapter failure the runner could record as a gap -- it took
    the whole ingest run down. Five consecutive daily runs died on the first
    card whose name has a space."""

    def test_the_name_is_percent_encoded(self):
        import urllib.parse
        from ingest.adapters import TcgApiAdapter
        url = TcgApiAdapter.SEARCH.format(
            name=urllib.parse.quote("Rare Candy", safe=""), game="55")
        self.assertNotIn(" ", url)
        self.assertIn("Rare%20Candy", url)

    def test_http_client_accepts_the_encoded_path(self):
        """The check that matters: the failure was in http.client's own
        validation, so the assertion has to be that validation."""
        import http.client
        import urllib.parse
        from ingest.adapters import TcgApiAdapter
        url = TcgApiAdapter.SEARCH.format(
            name=urllib.parse.quote("Rare Candy", safe=""), game="55")
        parts = urllib.parse.urlsplit(url)
        target = parts.path + ("?" + parts.query if parts.query else "")
        http.client.HTTPConnection("example.invalid")._validate_path(target)

    def test_the_unencoded_form_is_what_http_client_rejects(self):
        """Pins the diagnosis rather than trusting the fix."""
        import http.client
        with self.assertRaises(http.client.InvalidURL):
            http.client.HTTPConnection(
                "example.invalid")._validate_path("/v1/search?q=Rare Candy")


class ApitcgSweepsInsteadOfAskingPerCard(unittest.TestCase):
    """apitcg publishes no quota and refused after 16 calls on 2026-08-18.
    `fetch` was making ONE request PER CARD -- 3,494 of them on the current
    target list -- for an `artist` field `/api/products` serves 100 at a time.
    That is why `optcg:EN`, `optcg:JP` and `riftbound:EN` have had no catalog
    for several runs, and it is the single constraint on the catalog-in
    measurement's ceiling.
    """

    @staticmethod
    def _adapter(pages, by_code=None):
        from ingest.adapters import ApiTcgAdapter

        class Stub(ApiTcgAdapter):
            def __init__(self):
                super().__init__()
                self.calls = []

            def get(self, url, label=None, attempts=None):
                self.calls.append(url)
                if "code=" in url:
                    return {"data": (by_code or {}).get(
                        url.split("code=")[1], [])}
                page = int(url.split("page=")[1])
                return {"data": pages[page - 1] if page <= len(pages) else [],
                        "total": sum(len(p) for p in pages)}
        return Stub()

    @staticmethod
    def _hit(code, artist):
        return {"code": code, "name": f"card {code}",
                "attributes": {"Artist": artist, "Rarity": "SR"}}

    @staticmethod
    def _card(code):
        return {"card_uid": f"optcg:OP01:{code}:base:EN", "game": "optcg",
                "number": code}

    def test_one_sweep_serves_every_card(self):
        page = [self._hit(f"OP01-{i:03d}", "Someone") for i in range(1, 101)]
        adapter = self._adapter([page])
        cards = [self._card(f"OP01-{i:03d}") for i in range(1, 101)]
        records = adapter.fetch(cards=cards)
        self.assertEqual(len(records), 100)
        self.assertEqual(len(adapter.calls), 1,
                         f"100 cards cost {len(adapter.calls)} requests: "
                         f"{adapter.calls[:3]}")
        self.assertEqual(records[0].payload["artist"], "Someone")

    def test_pages_until_the_total_is_covered(self):
        pages = [[self._hit(f"OP01-{i:03d}", "A") for i in range(1, 101)],
                 [self._hit(f"OP01-{i:03d}", "B") for i in range(101, 121)]]
        adapter = self._adapter(pages)
        records = adapter.fetch(cards=[self._card("OP01-110")])
        self.assertEqual(len(adapter.calls), 2)
        self.assertEqual(records[0].payload["artist"], "B")

    def test_a_code_the_sweep_missed_is_counted_and_capped(self):
        page = [self._hit("OP01-001", "A")]
        adapter = self._adapter([page])
        cards = [self._card(f"OP02-{i:03d}") for i in range(1, 81)]
        adapter.fetch(cards=cards)
        self.assertEqual(adapter.uncovered_by_sweep, 80)
        per_card = [u for u in adapter.calls if "code=" in u]
        self.assertEqual(len(per_card), adapter.MAX_PER_CARD_FALLBACK,
                         "the per-card fallback has no ceiling, which is the "
                         "behaviour this replaced")
        self.assertTrue(any("counted and left" in line
                            for line in adapter.log), adapter.log)

    def test_a_refused_sweep_propagates_and_costs_nothing_more(self):
        """Answering "not now" with thousands of requests is the 8,313-fetch
        mistake in a different file."""
        from ingest.adapters import ApiTcgAdapter
        from ingest.base import RateLimited

        class Refusing(ApiTcgAdapter):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def get(self, url, label=None, attempts=None):
                self.calls += 1
                raise RateLimited("429")

        adapter = Refusing()
        with self.assertRaises(RateLimited):
            adapter.fetch(cards=[self._card(f"OP01-{i:03d}")
                                 for i in range(1, 200)])
        self.assertEqual(adapter.calls, 1)

    def test_the_index_is_built_once_per_game(self):
        page = [self._hit("OP01-001", "A")]
        adapter = self._adapter([page])
        adapter.fetch(cards=[self._card("OP01-001")] * 25)
        self.assertEqual(len(adapter.calls), 1)
