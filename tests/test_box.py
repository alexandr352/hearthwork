import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hearthwork import box  # noqa: E402


def f(element="Checkout page · Pay button", judgement="fails", criterion="2.4.7", test="t", **kw):
    return dict(test=test, frame="/x/frames/t01-001.jpeg", finding="no ring", element=element,
                judgement=judgement, criterion=criterion, severity="high", confidence="high", **kw)


class Box(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = SimpleNamespace(dir=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_look_replaces_the_report(self):
        self.assertEqual(box.replace_report(self.p, "e2e/pay.spec.ts", "c1", [f(), f(element="Menu")]), (None, "open", 2))
        self.assertEqual(box.replace_report(self.p, "e2e/pay.spec.ts", "c2", [f()]), ("open", "open", 1))
        self.assertEqual(box.replace_report(self.p, "e2e/pay.spec.ts", "c3", []), ("open", "clean", 0))
        self.assertEqual(box.load(self.p)["reports"]["e2e/pay.spec.ts"]["name"], "pay")

    def test_one_control_seen_in_two_files_counts_once(self):
        box.replace_report(self.p, "e2e/pay.spec.ts", "c1", [f()])
        box.replace_report(self.p, "e2e/cart.spec.ts", "c1", [f(element="checkout page · the Pay button"), f(element="Cart · Total")])
        b = box.load(self.p)
        cart, pay = b["reports"]["e2e/cart.spec.ts"], b["reports"]["e2e/pay.spec.ts"]
        self.assertEqual(len(box.own(cart)), 1)
        self.assertEqual(pay["findings"][0]["also_in"][0]["file"], "e2e/cart.spec.ts")
        self.assertIn("1 also seen elsewhere", box.judgement_line(cart))
        box.replace_report(self.p, "e2e/pay.spec.ts", "c2", [])
        self.assertEqual(len(box.own(box.load(self.p)["reports"]["e2e/cart.spec.ts"])), 2, "the first is gone: its copy is its own")
        self.assertEqual(box.shared_moved(self.p, "c2"), {"e2e/cart.spec.ts"}, "and its file is due a look")
        box.replace_report(self.p, "e2e/cart.spec.ts", "c2", [])
        self.assertEqual(box.shared_moved(self.p, "c2"), set())

    def test_release_then_fixed_or_still_seen(self):
        box.replace_report(self.p, "e2e/pay.spec.ts", "c1", [f()])
        box.replace_report(self.p, "e2e/menu.spec.ts", "c1", [f(element="Menu", judgement="other", criterion="none")])
        with self.assertRaises(box.BoxError):
            box.release(self.p, ["menu"], "c1", "UI-1")
        text, files = box.release(self.p, ["1"], "c1", "UI-1")
        self.assertEqual(files, ["e2e/pay.spec.ts"])
        self.assertIn("FAILS · 2.4.7", text)
        self.assertEqual(box.replace_report(self.p, "e2e/pay.spec.ts", "c1", [f()])[1], "released", "same commit: undecided")
        self.assertEqual(box.released_files(self.p, "c2"), {"e2e/pay.spec.ts"})
        self.assertEqual(box.replace_report(self.p, "e2e/pay.spec.ts", "c2", [f()])[1], "still-seen")
        self.assertEqual(box.replace_report(self.p, "e2e/pay.spec.ts", "c3", [f(judgement="other", criterion="none")])[1], "fixed",
                         "only what a release asks to fix keeps it open")

    def test_carried_findings_stay_marked(self):
        box.replace_report(self.p, "e2e/pay.spec.ts", "c1", [], carried=[f()])
        self.assertTrue(box.load(self.p)["reports"]["e2e/pay.spec.ts"]["findings"][0]["carried"])

    def test_render(self):
        box.replace_report(self.p, "e2e/pay.spec.ts", "c1", [f()])
        text = box.render(self.p, {"e2e/pay.spec.ts": {"audited_commit": "c1", "verdict": "findings"}}, 3)
        self.assertIn("Files looked at: 1 of 3", text)
        self.assertIn("pay", text)


if __name__ == "__main__":
    unittest.main()
