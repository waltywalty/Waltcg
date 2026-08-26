"""The audit's own tests, built from the red team's evasion corpus.

THIS CHECK SHIPPED INERT ON ITS FIRST RUN. It reported clean against a
brand-new module containing an unguarded elevation, because `git ls-files`
returns only TRACKED files and a new module is untracked at the moment it is
written -- the same `by_scope` defect `no_provider_data` has, in the check
built to catch exactly that class of thing.

So the negative cases below are not decoration. Every one of them is an
evasion that got past a draft of this audit, and the test that a check CAN
FAIL is the only test that distinguishes it from one that cannot.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.checks import no_unguarded_elevation as AUDIT  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TheVocabularyIsPinnedToProduction(unittest.TestCase):

    def test_the_confidence_values_match_the_cli(self):
        """The check scopes itself by this vocabulary, so a new rung added in
        `label_cli` without adding it here would silently narrow the audit."""
        from resolve.label_cli import CONFIDENCE
        self.assertEqual(set(AUDIT.CONFIDENCE_VALUES), set(CONFIDENCE))

    def test_the_gate_roots_all_exist(self):
        violations, _info, _ex, problems = AUDIT.check(REPO)
        stale = [p for p in problems if "does not exist" in p[1]]
        self.assertEqual(stale, [], f"pinned gate roots missing: {stale}")

    def test_the_repository_is_clean(self):
        violations, _info, _ex, problems = AUDIT.check(REPO)
        self.assertEqual(problems, [])
        self.assertEqual([v["qualname"] for v in violations], [])

    def test_the_exemption_roster_matches(self):
        _v, _i, exemptions, _p = AUDIT.check(REPO)
        self.assertEqual(len(exemptions), AUDIT.EXPECTED_EXEMPTIONS,
                         "an exemption was added or removed without raising "
                         "EXPECTED_EXEMPTIONS in the same commit")


#: A minimal stand-in for the two modules the audit pins. Probes run against
#: this rather than the real tree: parsing 150 files per probe took 277
#: seconds for fourteen tests, and a suite nobody will wait for is a suite
#: that gets skipped.
_STUB_CORROBORATION = """
def field_is_established(field, sources, checksum_passed=False):
    if not sources:
        return False, "nothing attests it"
    return True, "established"


def row_is_verifiable(sources, checksum_passed=False):
    ok, why = field_is_established("number", sources, checksum_passed)
    if not ok:
        return {"verified": False}
    return {"verified": True}


def may_read(profile, field):
    if profile is None:
        return False, "unknown reader"
    return True, ""


def physical_card_row_is_well_formed(row):
    problems = [] if row.get("read_by") else ["missing read_by"]
    return not problems, problems


def art_call_admits_a_name(call):
    if call.get("outcome") != "agrees":
        return False, "not an agreement"
    return True, ""
"""

_STUB_CLI = """
import json
import os

LABELLED = os.path.join(os.path.dirname(__file__), "labelled_200.json")
CONFIDENCE = ("verified", "single_source", "in_repo", "unstated")
SCORED = ("verified",)


def second_source_is_admissible(second_source, card):
    from resolve.corroboration import row_is_verifiable
    if not second_source:
        return False, "unnamed"
    found = row_is_verifiable((second_source,))
    if not found["verified"]:
        return False, "not established"
    return True, ""
"""


class _Probe(unittest.TestCase):
    """Drop a module into a minimal repo, run the audit, tear it down."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.tmp, "resolve"))
        for name, body in (("corroboration", _STUB_CORROBORATION),
                           ("label_cli", _STUB_CLI)):
            with open(os.path.join(cls.tmp, "resolve", f"{name}.py"),
                      "w", encoding="utf-8") as handle:
                handle.write(body)
        subprocess.run(["git", "init", "-q"], cwd=cls.tmp)
        subprocess.run(["git", "add", "-A"], cwd=cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, source, name="_elevation_probe"):
        path = os.path.join(self.tmp, "resolve", f"{name}.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(source))
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        violations, _info, _ex, problems = AUDIT.check(self.tmp)
        self.assertEqual(problems, [], f"the stub gate is broken: {problems}")
        return [v for v in violations if name in v["file"]]


class EvasionsThatMustBeCaught(_Probe):
    """Each of these got past a draft. They are regressions now."""

    def test_a_brand_new_untracked_module(self):
        """The bug this audit shipped with."""
        found = self._run('''
            import json
            from resolve.label_cli import LABELLED
            def promote(rows, path=LABELLED):
                with open(path) as h:
                    labelled = json.load(h)
                labelled["cards"].extend(rows)
                with open(path, "w") as h:
                    json.dump(labelled, h)
        ''')
        self.assertTrue(found, "a new untracked write path was invisible")

    def test_the_collection_is_aliased_before_mutating(self):
        found = self._run('''
            import json
            from resolve.label_cli import LABELLED
            def promote(rows, path=LABELLED):
                labelled = json.load(open(path))
                cards = labelled["cards"]
                cards.extend(rows)
                with open(path, "w") as h:
                    json.dump(labelled, h)
        ''')
        self.assertTrue(found, "aliasing the collection hid the mutation")

    def test_a_class_splits_mutation_from_persistence(self):
        """`raise_row` mutates, `save` persists, neither calls the other."""
        found = self._run('''
            import json
            from resolve.label_cli import LABELLED
            class Promoter:
                def __init__(self, path=LABELLED):
                    self.path = path
                    self.data = json.load(open(path))
                def raise_row(self, uid, level):
                    for row in self.data["cards"]:
                        if row["card_uid"] == uid:
                            row["confidence"] = level
                def save(self):
                    with open(self.path, "w") as h:
                        json.dump(self.data, h)
        ''')
        self.assertTrue(found, "sibling methods evaded the closure")

    def test_a_data_driven_patch_with_no_literal_anywhere(self):
        """`ingest` produced 238 verified rows and contains no literal."""
        found = self._run('''
            import json
            from resolve.label_cli import LABELLED
            def apply_patches(patches, path=LABELLED):
                labelled = json.load(open(path))
                for row in labelled["cards"]:
                    row.update(patches.get(row["card_uid"], {}))
                with open(path, "w") as h:
                    json.dump(labelled, h)
        ''')
        self.assertTrue(found, "a data-driven patch carried no literal")

    def test_a_false_exemption_claim_is_refused(self):
        """An exemption asserting something false is worse than none: it
        reads as a considered decision."""
        found = self._run('''
            import json
            from resolve.label_cli import LABELLED
            def promote(path=LABELLED):
                labelled = json.load(open(path))
                for row in labelled["cards"]:
                    # ELEVATION-EXEMPT(no-confidence-write): honestly it does not
                    row["confidence"] = "verified"
                with open(path, "w") as h:
                    json.dump(labelled, h)
        ''')
        self.assertTrue(found)
        self.assertTrue(any("which is false" in v["why"] for v in found))

    def test_an_unreadable_destination_keeps_the_obligation(self):
        """Default-deny: not being able to say where a labelled row is going
        is a finding, not a clearance."""
        found = self._run('''
            import json
            def promote(rows, destination):
                payload = {"cards": [dict(r, card_uid=r["card_uid"])
                                     for r in rows]}
                with open(destination, "w") as h:
                    json.dump(payload, h)
        ''')
        self.assertTrue(found)


class PathsThatMustNotBeFlagged(_Probe):
    """A check that flags everything is as useless as one that flags
    nothing, and it gets switched off faster."""

    def test_a_foreign_confidence_field_is_not_a_labelled_row(self):
        """`engine/` writes `"confidence": "low"`; `store/` writes 1.0."""
        found = self._run('''
            import json
            from resolve.label_cli import LABELLED
            def summarise(scores, path=LABELLED):
                report = {"confidence": "low", "n": len(scores)}
                with open("/tmp/report.json", "w") as h:
                    json.dump(report, h)
                return report
        ''')
        self.assertEqual(found, [])

    def test_reading_the_set_and_reporting_on_it_is_not_an_elevation(self):
        found = self._run('''
            import json
            from resolve.label_cli import LABELLED
            def count(path=LABELLED):
                labelled = json.load(open(path))
                cards = labelled.get("cards", [])
                scored = [c for c in cards if c.get("confidence") == "verified"]
                return len(scored)
        ''')
        self.assertEqual(found, [])

    def test_a_projection_out_of_the_set_is_outbound(self):
        """Its confidence values flow OUT. Direction, not location."""
        found = self._run('''
            import json
            from resolve.label_cli import LABELLED
            def export(path=LABELLED):
                labelled = json.load(open(path))
                rows = [{"uid": c["card_uid"], "conf": c.get("confidence")}
                        for c in labelled["cards"]]
                with open("probe/export.json", "w") as h:
                    json.dump(rows, h)
        ''')
        self.assertEqual(found, [])


class TheGateItselfIsChecked(unittest.TestCase):
    """A pinned gate list is only defensible if these hold."""

    def test_a_gate_that_cannot_refuse_is_reported(self):
        source = "def gate(row):\n    return True, ''\n"
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        subprocess.run(["git", "init", "-q"], cwd=tmp)
        os.makedirs(os.path.join(tmp, "resolve"))
        for name in ("corroboration", "label_cli"):
            with open(os.path.join(tmp, "resolve", f"{name}.py"), "w") as h:
                h.write(source)
        subprocess.run(["git", "add", "-A"], cwd=tmp)
        _v, _i, _e, problems = AUDIT.check(tmp)
        self.assertTrue(any("no refusing exit" in why or "does not exist" in why
                            for _root, why in problems))


if __name__ == "__main__":
    unittest.main()
