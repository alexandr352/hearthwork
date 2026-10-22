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


SITES = ("PATTERN: abc1234 | returns focus to the opener | none\nSITES:\n"
         "[1] a.vue | 10 | focus lost | no return | Dialog\n[2] b.vue | 4 | focus lost | no return | Dialog\n"
         "[3] c.vue | 7 | focus lost | no return | Drawer\nBLOCKED: none\n")


def census(**kw):
    p = inv(mode="FAMILY", role="census", chain="focus", chain_phase=1, chain_total=3,
            chain_steps=["census", "site-fix", "guard"], pattern_commit="abc1234",
            prompt=SCOPE + "\nRETURN: PATTERN: and SITES: blocks\n" + GRAMMAR)
    p.update(kw)
    return p


def site_fix(**kw):
    p = exe(unit=2, mode="FAMILY", role="site-fix", chain="focus", chain_phase=2, chain_total=4,
            commit_expected=False, site_group="1,2",
            prompt="Focus returns.\n" + SITES + "THIS GROUP: SITES[1,2]\nTARGET FILES: a.vue b.vue\n"
                   "INVARIANTS: none other\nDOES NOT FIT: every site left untouched")
    p.update(kw)
    return p


OPEN = {"chain": "focus", "mode": "FAMILY", "phase": 1, "total": 3, "sites": 3, "groups": 2}


class Family(unittest.TestCase):
    def test_sites_and_groups(self):
        self.assertEqual(contract.family_sites(SITES), (3, 2))
        self.assertEqual(contract.family_sites("[1] a | b | c\n"), (0, 0), "no SITES block, nothing counted")
        self.assertEqual(contract.family_sites("SITES:\n[1] a | 1 | x | y\n[2] b | 2 | x | y\n"), (2, 2),
                         "a row without a group is a group of its own")

    def test_opens_with_a_census_on_a_shipped_commit(self):
        self.assertEqual(contract.check_plan(census(), 1, sha_known=lambda s: True), [])
        self.assertTrue(contract.check_plan(census(pattern_commit=None), 1), "no shipped pattern: this is T1")
        self.assertTrue(contract.check_plan(census(), 1, sha_known=lambda s: False), "the sha must be in the repo")
        self.assertTrue(contract.check_plan(census(role="reproduce"), 1))
        self.assertTrue(contract.check_plan(census(chain_total=4, chain_steps=["census", "site-fix", "site-fix", "guard"]), 1))
        self.assertTrue(contract.check_plan(census(prompt=SCOPE + "\nfind them\n" + GRAMMAR), 1), "asks for the blocks")

    def test_site_fix_redeclares_once_to_groups_plus_two(self):
        self.assertEqual(contract.check_plan(site_fix(), 2, "focus", chain_state=OPEN), [])
        self.assertTrue(contract.check_plan(site_fix(chain_total=5), 2, "focus", chain_state=OPEN))
        self.assertTrue(contract.check_plan(site_fix(chain_phase=3, chain_total=5), 2, "focus",
                                            chain_state=dict(OPEN, phase=2, total=4, grown=True)), "only once")
        self.assertEqual(contract.check_plan(site_fix(chain_phase=3, site_group="3"), 2, "focus",
                                             chain_state=dict(OPEN, phase=2, total=4, grown=True)), [])

    def test_site_fix_names_its_group_and_carries_the_blocks(self):
        self.assertTrue(contract.check_plan(site_fix(site_group=None), 2, "focus", chain_state=OPEN))
        self.assertTrue(contract.check_plan(site_fix(site_group="1,9"), 2, "focus", chain_state=OPEN), "no row 9")
        self.assertTrue(contract.check_plan(site_fix(commit_expected=True), 2, "focus", chain_state=OPEN))
        bare = site_fix(prompt="Focus returns.\nTARGET FILES: a.vue\nINVARIANTS: none other, nothing at all")
        self.assertGreaterEqual(len(contract.check_plan(bare, 2, "focus", chain_state=OPEN)), 3)
        self.assertTrue(contract.check_plan(site_fix(), 2, "focus", chain_state=dict(OPEN, sites=0, groups=0)),
                        "a census with no rows refuses every site-fix")

    def test_the_guard_covers_every_site_through_the_lab(self):
        state = dict(OPEN, phase=3, total=4, grown=True)
        guard = exe(unit=4, mode="FAMILY", role="guard", chain="focus", chain_phase=4, chain_total=4,
                    prompt="Focus returns on three dialogs.\n" + SITES + "TARGET FILES: t.spec.js\nINVARIANTS: none\n"
                           "PROVE: operator lab ab t.spec.js\nCOMMIT: yes")
        self.assertEqual(contract.check_plan(guard, 4, "focus", lab_ready=True, chain_state=state), [])
        self.assertTrue(contract.check_plan(dict(guard, prompt=guard["prompt"].replace(SITES, "")), 4, "focus",
                                            chain_state=state))
        no_ab = dict(guard, prompt=guard["prompt"].replace("operator lab ab", "run"))
        self.assertTrue(contract.check_plan(no_ab, 4, "focus", lab_ready=True, chain_state=state))
        self.assertTrue(contract.check_plan(dict(guard, role="fix"), 4, "focus", chain_state=state))

    def test_other_chains_keep_their_freedom(self):
        stab = {"chain": "c", "mode": "STABILIZATION", "phase": 1, "total": 2}
        self.assertEqual(contract.check_plan(exe(chain="c", chain_phase=3, chain_total=3), 2, "c", chain_state=stab), [])

    def test_chain_void(self):
        good = {"action": "continue", "unit_done": True, "units_done": 1, "units_planned": 1,
                "next": "re-plan", "reason": "no further site"}
        self.assertEqual(contract.check_verdict(dict(good, chain_void=True)), [])
        self.assertTrue(contract.check_verdict(dict(good, chain_void="yes")))


REL = ["e2e/pay.spec.js"]


def look(**kw):
    p = inv(mode="VISUAL", role="look", chain="pay-ring", chain_phase=1, chain_total=3,
            chain_steps=["look", "fix", "guard"], released_file="e2e/pay.spec.js",
            prompt=SCOPE + "\nRUN: operator lab frames e2e/pay.spec.js\nRETURN: SIGHTING: and CANDIDATES: blocks; "
                   "SIGHTING names the defect: still drawn = the user still meets it\n" + GRAMMAR)
    p.update(kw)
    return p


VOPEN = {"chain": "pay-ring", "mode": "VISUAL", "phase": 1, "total": 3, "sighting": "still drawn",
         "sighting_confidence": "high"}
SEEN = "SIGHTING: still drawn — t01-end.png | no ring on Pay | confidence high\n"


def vfix(**kw):
    p = exe(unit=2, mode="VISUAL", role="fix", chain="pay-ring", chain_phase=2, chain_total=3, commit_expected=False,
            prompt="Pay shows focus.\n" + SEEN + "TARGET FILES: app.css\nINVARIANTS: other buttons keep their ring")
    p.update(kw)
    return p


class Visual(unittest.TestCase):
    def test_sighting(self):
        self.assertEqual(contract.sighting(SEEN), ("still drawn", "high"))
        self.assertEqual(contract.sighting("x\nSIGHTING: gone — frames t01 | ring shows | confidence: medium"), ("gone", "medium"))
        self.assertEqual(contract.sighting("no line"), (None, None))
        two = SEEN + "SIGHTING: cannot show — t01-end.png | placeholder not measured | confidence medium\n"
        self.assertEqual(contract.sighting(two), ("still drawn", "high"), "one finding still drawn is enough for a fix")
        self.assertEqual(len(contract.sightings(two)), 2)
        self.assertEqual(contract.sighting("SIGHTING: gone | a | confidence high\nSIGHTING: gone | b | confidence low"),
                         ("gone", "low"))
        self.assertEqual(contract.sighting("SIGHTING: gone | a | confidence high\nSIGHTING: cannot show | b | confidence low"),
                         ("cannot show", "low"))

    def test_opens_only_on_a_release_with_a_look(self):
        self.assertEqual(contract.check_plan(look(), 1, released=REL), [])
        self.assertTrue(contract.check_plan(look(), 1), "no release, no VISUAL")
        self.assertTrue(contract.check_plan(look(released_file="e2e/other.spec.js"), 1, released=REL))
        self.assertTrue(contract.check_plan(look(role="reproduce"), 1, released=REL))
        self.assertTrue(contract.check_plan(look(prompt=SCOPE + "\nlook at it\n" + GRAMMAR), 1, released=REL))
        undefined = look(prompt=SCOPE + "\nRUN: operator lab frames e2e/pay.spec.js\nRETURN: SIGHTING: and CANDIDATES:\n" + GRAMMAR)
        self.assertTrue(any("state of the DEFECT" in d for d in contract.check_plan(undefined, 1, released=REL)))

    def test_a_fix_needs_it_still_drawn_at_high_confidence(self):
        self.assertEqual(contract.check_plan(vfix(), 2, "pay-ring", chain_state=VOPEN, released=REL), [])
        for state, why in ((dict(VOPEN, sighting_confidence="medium"), "medium"), (dict(VOPEN, sighting="gone"), "void"),
                           ({k: v for k, v in VOPEN.items() if not k.startswith("sighting")}, "no SIGHTING")):
            devs = contract.check_plan(vfix(), 2, "pay-ring", chain_state=state, released=REL)
            self.assertTrue(any(why in d for d in devs), devs)
        self.assertTrue(contract.check_plan(vfix(prompt="Pay.\nTARGET FILES: a\nINVARIANTS: none other at all here"), 2,
                                            "pay-ring", chain_state=VOPEN, released=REL))
        self.assertTrue(contract.check_plan(vfix(chain_total=4), 2, "pay-ring", chain_state=VOPEN, released=REL))

    def test_the_guard_pictures_and_proves(self):
        g = exe(unit=3, mode="VISUAL", role="guard", chain="pay-ring", chain_phase=3, chain_total=3,
                prompt="Pay shows focus.\n" + SEEN + "TARGET FILES: e2e/pay.spec.js\nINVARIANTS: none\n"
                       "SEE: operator lab frames e2e/pay.spec.js\nPROVE: operator lab ab e2e/pay.spec.js\nCOMMIT: yes")
        st = dict(VOPEN, phase=2)
        self.assertEqual(contract.check_plan(g, 3, "pay-ring", lab_ready=True, chain_state=st, released=REL), [])
        self.assertTrue(contract.check_plan(dict(g, prompt=g["prompt"].replace("operator lab frames", "look")), 3,
                                            "pay-ring", chain_state=st, released=REL))
        self.assertTrue(contract.check_plan(dict(g, prompt=g["prompt"].replace("operator lab ab", "run")), 3,
                                            "pay-ring", lab_ready=True, chain_state=st, released=REL))

    def test_a_probe_insert_may_join(self):
        self.assertEqual(contract.check_plan(inv(unit=2), 2, "pay-ring", chain_state=VOPEN, released=REL), [])
