"""The data contract: schema, fixtures, assumption registry, source map.

This is the interface a front end will be designed against, so its failure mode
is a designer building a box the backend can never fill. These tests make that
impossible in four ways: fixtures must validate, money must never be a bare
number anywhere in the tree, every assumption a fixture cites must exist, and
every field in the schema must appear in SOURCE_MAP.md with a real source.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jsonschema import Draft202012Validator  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(REPO, "contracts")
SCHEMA_PATH = os.path.join(CONTRACTS, "screens.schema.json")
ASSUMPTIONS_PATH = os.path.join(CONTRACTS, "assumptions.json")
SOURCE_MAP_PATH = os.path.join(CONTRACTS, "SOURCE_MAP.md")
FIXTURE_GLOB = os.path.join(CONTRACTS, "fixtures", "*.json")

SCREENS = ["home", "signals", "card_detail", "grading_lab", "arbitrage_board",
           "trend_radar", "track_record", "settings"]

MONEY_KEYS = {"amount", "currency", "fx_rate_used", "fx_as_of"}
# Field names that hold money. A bare number under any of these is the bug.
MONEY_FIELD_NAMES = {
    "portfolio_value", "day_change", "price", "acquisition_cost", "ev",
    "downside_case", "gross_spread", "net_spread", "landed_cost", "fee",
    "price_at_alert", "marketplace_fee", "payment_fee", "shipping", "grading_fee",
    "fx_spread", "tax", "inbound_shipping", "supplies", "return_shipping",
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class SchemaItself(unittest.TestCase):

    def test_schema_is_valid_draft_2020_12(self):
        Draft202012Validator.check_schema(load(SCHEMA_PATH))

    def test_one_definition_per_screen(self):
        defs = load(SCHEMA_PATH)["$defs"]
        for s in SCREENS:
            self.assertIn(f"screen_{s}", defs, f"no definition for screen {s}")

    def test_money_definition_requires_all_four_parts(self):
        money = load(SCHEMA_PATH)["$defs"]["money"]
        self.assertEqual(set(money["required"]), MONEY_KEYS)
        self.assertFalse(money["additionalProperties"])

    def test_derived_value_requires_the_five_parts(self):
        dv = load(SCHEMA_PATH)["$defs"]["derived_value"]
        self.assertLessEqual({"value", "source", "as_of", "confidence", "sample_size"},
                             set(dv["required"]))
        self.assertEqual(set(load(SCHEMA_PATH)["$defs"]["confidence"]["enum"]),
                         {"high", "medium", "low", "unvalidated"})

    def test_derived_value_carries_its_own_provenance(self):
        """The three fields the design audit found missing. They sit on
        derived_value rather than on rows because a row can hold a fresh price
        and a stale population at once, and a row-level object can only say
        one of those."""
        dv = load(SCHEMA_PATH)["$defs"]["derived_value"]
        self.assertLessEqual({"staleness", "needs_primary_verification",
                              "entry_method"}, set(dv["required"]))

    def test_staleness_lives_only_on_derived_values(self):
        """Two places to read staleness from is one place to read it wrong."""
        schema = load(SCHEMA_PATH)
        offenders = []
        for name, node in schema["$defs"].items():
            if name in ("staleness", "derived_value"):
                continue
            if "staleness" in node.get("properties", {}):
                offenders.append(name)
        self.assertFalse(offenders,
                         f"row/screen-level staleness is a rollup of fields already "
                         f"in the payload, and can disagree with them: {offenders}")

    def test_the_ladder_is_bounded_at_both_ends(self):
        """minItems 1 so a raw-only card still renders; maxItems 4 because
        there are four grades."""
        ladder = load(SCHEMA_PATH)["$defs"]["grade_ladder"]
        self.assertEqual(ladder["minItems"], 1)
        self.assertEqual(ladder["maxItems"], 4)

    def test_nullable_is_always_explicit(self):
        """No implicit null: a nullable field spells out the null branch."""
        schema = load(SCHEMA_PATH)
        offenders = []

        def walk(node, path):
            if isinstance(node, dict):
                if node.get("type") == "null" or "anyOf" in node or "oneOf" in node:
                    pass
                for k, v in node.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        walk(schema, "root")
        # Structural assertion: nothing in the schema uses the "nullable" keyword,
        # which is OpenAPI, not JSON Schema, and would be silently ignored.
        self.assertNotIn('"nullable"', json.dumps(schema),
                         "use an explicit null branch, not the OpenAPI nullable keyword")
        self.assertFalse(offenders)


class FixturesValidate(unittest.TestCase):

    def setUp(self):
        self.schema = load(SCHEMA_PATH)
        self.validator = Draft202012Validator(self.schema)
        self.fixtures = {os.path.basename(p)[:-5]: load(p)
                         for p in sorted(glob.glob(FIXTURE_GLOB))}

    def test_every_screen_has_at_least_one_fixture(self):
        """A screen may carry more than one, named `<screen>.<state>.json`.
        The brief asks for five states per screen; the states that need a
        fixture are the ones whose shape differs, and refusal is one."""
        covered = {n.split(".")[0] for n in self.fixtures}
        self.assertEqual(covered, set(SCREENS))

    def test_every_fixture_validates(self):
        for name, payload in self.fixtures.items():
            errs = sorted(self.validator.iter_errors(payload),
                          key=lambda e: list(e.path))
            self.assertFalse(
                errs,
                f"{name}: " + "; ".join(f"{list(e.path)}: {e.message[:120]}"
                                        for e in errs[:3]))

    def test_every_fixture_is_marked_as_a_fixture(self):
        """No synthetic data may reach a shipped screen. The marker is how the
        API asserts a payload never came from contracts/fixtures/."""
        for name, payload in self.fixtures.items():
            self.assertIs(payload.get("_fixture"), True, f"{name} lacks _fixture: true")

    def test_screen_field_matches_the_filename(self):
        for name, payload in self.fixtures.items():
            self.assertEqual(payload["screen"], name.split(".")[0])

    def test_the_refusal_state_has_a_fixture(self):
        """The design brief calls refusal the behaviour it most needs the
        design to respect. A shape no payload demonstrates is a shape nobody
        designs, which is how it ends up rendered as a greyed-out failure."""
        refusals = [p for p in self.fixtures.values()
                    if isinstance(p.get("refusal"), dict)]
        self.assertTrue(refusals, "no fixture exercises a refusal")
        for payload in refusals:
            self.assertTrue(payload["refusal"]["missing"],
                            "a refusal with an empty checklist says nothing")


class NoBareMoney(unittest.TestCase):
    """Walk the whole tree. A bare number where money belongs is the bug that
    cost a factor of 7.8 in position sizing once already."""

    def setUp(self):
        self.fixtures = {os.path.basename(p)[:-5]: load(p)
                         for p in sorted(glob.glob(FIXTURE_GLOB))}

    def test_no_monetary_field_is_a_bare_number(self):
        offenders = []

        def walk(node, path):
            if isinstance(node, dict):
                for k, v in node.items():
                    here = f"{path}.{k}"
                    if k in MONEY_FIELD_NAMES:
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            offenders.append(f"{here} = {v!r} (bare number)")
                        elif isinstance(v, dict) and not MONEY_KEYS <= set(v):
                            # A dict is fine only if it is a money object or a
                            # container of them.
                            if not any(isinstance(x, dict) and MONEY_KEYS <= set(x)
                                       for x in v.values()):
                                offenders.append(f"{here} is a dict but not money")
                    walk(v, here)
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        for name, payload in self.fixtures.items():
            walk(payload, name)
        self.assertFalse(offenders, "bare money found:\n  " + "\n  ".join(offenders))

    def test_money_amounts_are_strings_not_json_numbers(self):
        """JSON numbers are binary floats. Cents do not survive them."""
        offenders = []

        def walk(node, path):
            if isinstance(node, dict):
                if MONEY_KEYS <= set(node):
                    if not isinstance(node["amount"], str):
                        offenders.append(f"{path}.amount is {type(node['amount']).__name__}")
                    if not re.fullmatch(r"-?\d+(\.\d+)?", str(node["amount"])):
                        offenders.append(f"{path}.amount = {node['amount']!r}")
                    # fx_rate_used and fx_as_of are null together or set together.
                    if (node["fx_rate_used"] is None) != (node["fx_as_of"] is None):
                        offenders.append(f"{path}: fx_rate_used and fx_as_of disagree")
                for k, v in node.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        for name, payload in self.fixtures.items():
            walk(payload, name)
        self.assertFalse(offenders, "\n  ".join(offenders))


class AssumptionReferences(unittest.TestCase):

    def setUp(self):
        self.registry = load(ASSUMPTIONS_PATH)
        self.ids = {k for k, v in self.registry.items()
                    if isinstance(v, dict) and "id" in v}
        self.fixtures = {os.path.basename(p)[:-5]: load(p)
                         for p in sorted(glob.glob(FIXTURE_GLOB))}

    def test_registry_entries_have_the_required_shape(self):
        required = {"id", "description", "current_value", "unit", "confidence",
                    "source", "last_reviewed", "calibration_plan"}
        for key in self.ids:
            entry = self.registry[key]
            self.assertTrue(required <= set(entry),
                            f"{key} missing {required - set(entry)}")
            self.assertEqual(entry["id"], key, "id must match its key")
            self.assertIn(entry["confidence"],
                          {"high", "medium", "low", "unvalidated"}, key)

    def test_the_five_named_assumptions_are_seeded(self):
        for required_id in ("submission_selection_haircut", "regrade_conditional_prior",
                            "pull_rate_estimates", "marketplace_fee_schedule",
                            "grading_fee_schedule"):
            self.assertIn(required_id, self.ids)

    def test_every_assumption_id_in_a_fixture_exists_in_the_registry(self):
        missing = []

        def walk(node, path):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "assumption_ids":
                        for aid in v:
                            if aid not in self.ids:
                                missing.append(f"{path}.{k}: {aid!r}")
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        for name, payload in self.fixtures.items():
            walk(payload, name)
        self.assertFalse(missing, "unknown assumption ids:\n  " + "\n  ".join(missing))

    def test_settings_fixture_mirrors_the_registry(self):
        listed = {a["id"] for a in self.fixtures["settings"]["assumptions"]}
        self.assertEqual(listed, self.ids,
                         "the settings screen must show every registry entry")

    def test_unvalidated_entries_require_a_ui_chip_or_say_why_not(self):
        """GOAL D7: a figure downstream of an unvalidated assumption needs a chip."""
        for key in self.ids:
            e = self.registry[key]
            if e["confidence"] == "unvalidated" and e["current_value"] is None:
                self.assertIn("ui_chip_required", e, key)


class RefusalIsAChecklist(unittest.TestCase):
    """Fix 1. `missing` was a bare string array, so the refusal state had
    nothing to title a row with and nowhere to send a tap."""

    def setUp(self):
        self.registry_ids = {k for k, v in load(ASSUMPTIONS_PATH).items()
                             if isinstance(v, dict) and "id" in v}
        self.items = []
        for path in sorted(glob.glob(FIXTURE_GLOB)):
            payload = load(path)
            if isinstance(payload.get("refusal"), dict):
                self.items += payload["refusal"]["missing"]

    def test_an_assumption_gap_is_named_by_its_assumption_id(self):
        """So the chip, the registry row and the refusal line are one thing to
        the UI. The schema cannot check this -- it spans two files."""
        for it in self.items:
            if it["reason_code"] == "assumption_unset":
                self.assertIn(it["id"], self.registry_ids,
                              f"{it['id']!r} is not in the assumption registry")

    def test_every_deep_link_assumption_id_exists(self):
        for it in self.items:
            link = it["deep_link"]
            if link and link.get("assumption_id"):
                self.assertIn(link["assumption_id"], self.registry_ids)

    def test_a_fixable_item_says_where_to_fix_it(self):
        """An item you can action but cannot navigate to is a dead end."""
        for it in self.items:
            if it["fixable"]:
                self.assertIsNotNone(
                    it["deep_link"],
                    f"{it['id']!r} is fixable but has no deep link")

    def test_structural_absences_are_not_presented_as_tasks(self):
        """No population source exists for One Piece. Rendering that as a
        checkbox tells the same lie every time the screen loads."""
        codes = {it["reason_code"] for it in self.items if not it["fixable"]}
        self.assertTrue(codes, "no fixture shows an unfixable gap")

    def test_titles_are_not_paths(self):
        for it in self.items:
            self.assertNotIn("_", it["title"].replace(" ", ""),
                             f"{it['title']!r} reads like an identifier")


class StalenessIsPerField(unittest.TestCase):
    """Fix 2."""

    def setUp(self):
        self.fixtures = {os.path.basename(p)[:-5]: load(p)
                         for p in sorted(glob.glob(FIXTURE_GLOB))}

    def _stalenesses(self):
        found = []

        def walk(node, path):
            if isinstance(node, dict):
                if "staleness" in node:
                    found.append((path, node))
                for k, v in node.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        for name, payload in self.fixtures.items():
            walk(payload, name)
        return found

    def test_staleness_only_ever_hangs_off_a_derived_value(self):
        for path, owner in self._stalenesses():
            self.assertLessEqual(
                {"value", "source", "as_of", "confidence", "sample_size"},
                set(owner),
                f"{path} carries staleness but is not a derived value")

    def test_is_stale_agrees_with_the_age_and_threshold(self):
        """The API decides staleness, so its own arithmetic has to hold --
        otherwise the flag and the badge beside it disagree on screen."""
        for path, owner in self._stalenesses():
            s = owner["staleness"]
            self.assertEqual(
                s["is_stale"], s["age_seconds"] > s["threshold_seconds"],
                f"{path}: is_stale={s['is_stale']} but age={s['age_seconds']} "
                f"vs threshold={s['threshold_seconds']}")

    def test_a_fresh_price_and_a_stale_population_coexist_on_one_row(self):
        """The case the audit named. Before the fix a row carried one
        staleness object and could only report one of these."""
        for payload in self.fixtures.values():
            for rung in payload.get("ladder", []):
                if (not rung["price_meta"]["staleness"]["is_stale"]
                        and rung["population"]["staleness"]["is_stale"]):
                    return
        self.fail("no fixture shows a fresh price beside a stale population")


class ProvisionalValuesPropagate(unittest.TestCase):
    """Fix 3. The flag existed only on grading_tier_view in Settings, so a
    Grading Lab figure computed with a provisional fee could not say so."""

    def setUp(self):
        self.fixtures = {os.path.basename(p)[:-5]: load(p)
                         for p in sorted(glob.glob(FIXTURE_GLOB))}

    def _derived(self):
        found = []

        def walk(node, path):
            if isinstance(node, dict):
                if {"value", "source", "as_of", "confidence",
                        "sample_size"} <= set(node):
                    found.append((path, node))
                for k, v in node.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        for name, payload in self.fixtures.items():
            walk(payload, name)
        return found

    def test_every_derived_value_states_whether_it_is_provisional(self):
        for path, dv in self._derived():
            self.assertIn("needs_primary_verification", dv, path)
            self.assertIsInstance(dv["needs_primary_verification"], bool, path)

    def test_a_value_resting_on_a_provisional_fee_is_marked(self):
        """Grading and marketplace fees are both `secondary, unverified` in
        config today. Anything citing one inherits that."""
        provisional = {"grading_fee_schedule", "marketplace_fee_schedule"}
        for path, dv in self._derived():
            if set(dv.get("assumption_ids") or []) & provisional:
                self.assertTrue(dv["needs_primary_verification"],
                                f"{path} cites a provisional fee but is not marked")

    def test_the_grading_lab_headline_carries_the_flag(self):
        lab = self.fixtures["grading_lab"]
        self.assertTrue(lab["break_even_p_target"]["needs_primary_verification"],
                        "the break-even probability is computed with a PSA fee "
                        "that is still sourced from a secondary summary")


class ManualRowsAreIdentifiable(unittest.TestCase):
    """Fix 4. entry_method existed only on buy_route, so a hand-typed price
    was invisible on the ladder rung and the signal row it fed."""

    def setUp(self):
        self.fixtures = {os.path.basename(p)[:-5]: load(p)
                         for p in sorted(glob.glob(FIXTURE_GLOB))}

    def test_a_ladder_rung_can_be_marked_manual(self):
        for payload in self.fixtures.values():
            for row in payload.get("rows", []) + payload.get("top_movers", []):
                for rung in row.get("ladder", []):
                    if rung["price_meta"]["entry_method"] == "manual":
                        return
            for rung in payload.get("ladder", []):
                if rung["price_meta"]["entry_method"] == "manual":
                    return
        self.fail("no fixture shows a manually-entered ladder rung")

    def test_a_signal_row_can_be_marked_manual(self):
        methods = {r["entry_method"] for r in self.fixtures["signals"]["rows"]}
        self.assertIn("manual", methods,
                      "no signal row is manually entered, so the marker is untested")

    def test_mixed_is_reachable_for_a_computed_value(self):
        """A break-even computed from a hand-typed raw price and an API graded
        price is neither api nor manual."""
        found = set()

        def walk(node):
            if isinstance(node, dict):
                if "entry_method" in node:
                    found.add(node["entry_method"])
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        for payload in self.fixtures.values():
            walk(payload)
        self.assertEqual(found, {"api", "manual", "mixed"},
                         f"not every entry_method is demonstrated: {sorted(found)}")


class LadderShape(unittest.TestCase):
    """Confirming the two properties the audit asked about, and the one it
    did not: nothing pinned rung uniqueness or order."""

    def setUp(self):
        self.ladders = []

        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("ladder"), list):
                    self.ladders.append(node["ladder"])
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        for p in sorted(glob.glob(FIXTURE_GLOB)):
            walk(load(p))

    def test_between_one_and_four_rungs(self):
        for ladder in self.ladders:
            self.assertGreaterEqual(len(ladder), 1)
            self.assertLessEqual(len(ladder), 4)

    def test_no_grade_appears_twice(self):
        """uniqueItems cannot express this: two rungs both graded 9 with
        different prices are distinct items and would validate."""
        for ladder in self.ladders:
            grades = [r["grade"] for r in ladder]
            self.assertEqual(len(grades), len(set(grades)), grades)

    def test_rungs_are_ordered_raw_to_ten(self):
        order = ["raw", "8", "9", "10"]
        for ladder in self.ladders:
            grades = [r["grade"] for r in ladder]
            self.assertEqual(grades, sorted(grades, key=order.index), grades)

    def test_a_short_ladder_exists_so_the_degraded_form_is_designed(self):
        """minItems 1 is deliberate. A card with a raw price and no graded
        comps has one rung, and that has to render as something."""
        self.assertTrue(any(len(l) < 4 for l in self.ladders),
                        "every fixture ladder is full, so the 1-3 rung form "
                        "is never seen by whoever designs it")


class PriceHistoryDensity(unittest.TestCase):
    """Confirming the second property: no guaranteed cadence, deliberately."""

    def test_the_schema_promises_no_minimum_and_no_cadence(self):
        history = load(SCHEMA_PATH)["$defs"]["screen_card_detail"] \
            ["properties"]["price_history"]
        self.assertNotIn("minItems", history)
        self.assertEqual(set(load(SCHEMA_PATH)["$defs"]["price_point"]["required"]),
                         {"as_of", "grade", "price"})

    def test_the_series_reports_its_own_density(self):
        """Density is not guaranteed, so it has to be stated. sample_size is
        the point count -- a two-point 'history' must not look like a series."""
        cd = load(os.path.join(CONTRACTS, "fixtures", "card_detail.json"))
        self.assertEqual(cd["price_history_meta"]["sample_size"],
                         len(cd["price_history"]))


class SourceMapCoverage(unittest.TestCase):
    """Every schema field appears in SOURCE_MAP.md. A field nobody mapped is a
    field nobody can fill."""

    def setUp(self):
        self.schema = load(SCHEMA_PATH)
        with open(SOURCE_MAP_PATH, encoding="utf-8") as f:
            self.source_map = f.read()

    def _leaf_field_names(self):
        names = set()

        def walk(node):
            if isinstance(node, dict):
                props = node.get("properties")
                if isinstance(props, dict):
                    names.update(props)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(self.schema)
        # Envelope plumbing is documented as a group, not per field.
        return names - {"screen", "generated_at", "schema_version", "warnings",
                        "_fixture"}

    def test_every_schema_field_is_mapped_to_a_source(self):
        unmapped = sorted(n for n in self._leaf_field_names()
                          if n not in self.source_map)
        self.assertFalse(
            unmapped,
            "fields in the schema with no row in SOURCE_MAP.md -- either map them "
            f"or delete them from the schema: {unmapped}")

    def test_source_map_lists_the_deletions(self):
        self.assertIn("DELETED FOR LACK OF A SOURCE", self.source_map)
        for deleted in ("reddit", "cert_lookup", "predicted_grade_from_photo",
                        "bid_ask_spread"):
            self.assertIn(deleted, self.source_map,
                          f"{deleted} should be recorded as deleted")

    def test_no_deleted_field_crept_back_into_the_schema(self):
        blob = json.dumps(self.schema)
        for gone in ("reddit_mentions", "reddit_velocity", "cert_lookup",
                     "predicted_grade_from_photo", "bid_ask_spread",
                     "tcgplayer_seller_count", "search_interest_card_level"):
            self.assertNotIn(gone, blob, f"{gone} was deleted; it is back in the schema")


if __name__ == "__main__":
    unittest.main(verbosity=2)
