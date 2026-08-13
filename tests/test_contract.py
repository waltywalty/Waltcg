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
        self.assertEqual(set(dv["required"]),
                         {"value", "source", "as_of", "confidence", "sample_size"})
        self.assertEqual(set(load(SCHEMA_PATH)["$defs"]["confidence"]["enum"]),
                         {"high", "medium", "low", "unvalidated"})

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

    def test_one_fixture_per_screen(self):
        self.assertEqual(sorted(self.fixtures), sorted(SCREENS))

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
            self.assertEqual(payload["screen"], name)


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
