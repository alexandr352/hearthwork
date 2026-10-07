import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hearthwork import contract  # noqa: E402
from hearthwork.claude import CostLedger, extract_json  # noqa: E402

SCOPE = ("SCOPE CONSTRAINT: Read at most 2 files. Read at most 150 lines per file. Do not exceed these limits "
         "regardless of what you find.")
GRAMMAR = "[N] File: <path> | Line: <line> | Finding: <fact> | Confidence: <level>"


def inv(**kw):
    p = {"action": "execute", "unit": 1, "kind": "investigation", "title": "look", "budget": "LOW",
         "commit_expected": False, "prompt": SCOPE + "\nQUESTIONS: where?\n" + GRAMMAR}
    p.update(kw)
    return p


def exe(**kw):
    p = {"action": "execute", "unit": 2, "kind": "execution", "title": "fix", "budget": "NONE",
         "commit_expected": True, "prompt": "Gives tax.\nTARGET FILES: a.py\nINVARIANTS: none other\nCOMMIT: yes"}
    p.update(kw)
    return p


class Plans(unittest.TestCase):
    def test_good(self):
        self.assertEqual(contract.check_plan(inv(), 1), [])
        self.assertEqual(contract.check_plan(exe(), 2), [])
        self.assertEqual(contract.check_plan({"action": "halt", "reason": "which?"}, 1), [])

    def test_investigation_needs_scope_and_grammar(self):
        self.assertTrue(contract.check_plan(inv(prompt="Look around the code base please, all of it, carefully."), 1))
        self.assertTrue(contract.check_plan(inv(commit_expected=True), 1))

    def test_execution_needs_targets(self):
        self.assertTrue(contract.check_plan(exe(prompt="Fix it somehow, in whatever way looks best to you here."), 2))
        self.assertTrue(contract.check_plan(exe(prompt=SCOPE + "\nTARGET FILES: a\nINVARIANTS: b"), 2))

    def test_unit_number_and_fences(self):
        self.assertTrue(contract.check_plan(inv(unit=3), 1))
        self.assertTrue(contract.check_plan(inv(prompt=SCOPE + "\n```\ncode\n```\n" + GRAMMAR), 1))

    def test_chain_rules(self):
        self.assertEqual(contract.check_plan(exe(chain="c", chain_phase=2, chain_total=2), 2), [])
        self.assertTrue(contract.check_plan(exe(chain="c", chain_phase=1, chain_total=2), 2), "only the last phase commits")
        self.assertTrue(contract.check_plan(exe(chain="d", chain_phase=2, chain_total=2), 2, open_chain="c"))
        self.assertTrue(contract.check_plan(exe(), 2, open_chain="c"))
        self.assertEqual(contract.check_plan(inv(), 1, open_chain="c"), [], "an insert may join an open chain")


    def test_labels_for_the_work_log(self):
        self.assertEqual(contract.check_plan(inv(mode="FEATURE", role="surface"), 1), [])
        self.assertTrue(contract.check_plan(inv(mode="BUGFIX"), 1))
        self.assertTrue(contract.check_plan(inv(role="Reproduce the bug carefully please"), 1))
        ok = exe(chain="c", chain_phase=2, chain_total=2, chain_steps=["reproduce", "fix"])
        self.assertEqual(contract.check_plan(ok, 2), [])
        self.assertTrue(contract.check_plan(dict(ok, chain_steps=["reproduce"]), 2))


class Verdicts(unittest.TestCase):
    def test_verdict(self):
        good = {"action": "continue", "unit_done": True, "units_done": 1, "units_planned": 3,
                "next": "unit 2", "reason": "fine"}
        self.assertEqual(contract.check_verdict(good), [])
        self.assertTrue(contract.check_verdict(dict(good, units_done=4)))
        self.assertTrue(contract.check_verdict(dict(good, action="done")))


class Helpers(unittest.TestCase):
    def test_extract_json(self):
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('Here: {"a": {"b": 2}} done'), {"a": {"b": 2}})
        self.assertIsNone(extract_json("no json"))

    def test_cost_increments(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            c = CostLedger(Path(d) / "c.json")
            self.assertEqual(c.cost("s", 0.5, False), (0.5, "whole"))
            self.assertEqual(c.cost("s", 0.8, True), (0.3, "increment"))
            self.assertEqual(c.cost("t", 0.4, True), (0.4, "unknown"))
            self.assertEqual(c.cost("s", 0.1, True), (0.1, "dropped"))


if __name__ == "__main__":
    unittest.main()
