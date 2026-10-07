import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hearthwork import home, worklog  # noqa: E402

REPORT = ("[1] File: src/app.py | Line: 10 | Finding: something true about the code | Confidence: high\n" * 60)


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class History(unittest.TestCase):
    """1,000 units over 200 tickets: the page stays small, nothing is lost."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        os.environ["HEARTHWORK_HOME"] = str(root / "home")
        repo = root / "repo"
        (repo / ".git").mkdir(parents=True)
        home.init_home()
        pdir = root / "home" / "projects" / "big"
        (pdir / "tickets").mkdir(parents=True)
        (pdir / "project.toml").write_text(f'repo = "{repo}"\ntrunk = "main"\n')
        rows, t0 = [], time.time() - 200 * 86400
        for k in range(200):
            tid = f"T-{k + 1}"
            tdir = pdir / "tickets" / tid
            tdir.mkdir()
            (tdir / "ticket.md").write_text(f"# {tid}\n")
            (tdir / "meta.json").write_text(json.dumps({"id": tid, "title": f"ticket number {k + 1}"}))
            for n in range(1, 6):
                d = tdir / "units" / f"{n:02d}"
                d.mkdir(parents=True)
                plan = {"action": "execute", "unit": n, "kind": "investigation" if n < 5 else "execution",
                        "title": f"step {n}", "mode": "FEATURE", "role": ["surface", "probe", "build", "build", "spec"][n - 1],
                        "chain": "c", "chain_phase": n, "chain_total": 5, "commit_expected": n == 5,
                        "chain_steps": ["surface", "probe", "build", "build", "spec"]}
                (d / "plan.json").write_text(json.dumps(plan))
                for f in ("prompt.md", "report.md", "facts.md"):
                    (d / f).write_text(REPORT)
                rows.append({"ts": iso(t0 + k * 86400 + n * 600), "project": "big", "ticket": tid, "unit": n,
                             "kind": plan["kind"], "title": plan["title"], "role": plan["role"], "mode": "FEATURE",
                             "phases": {"plan": [{"cost_usd": 0.05, "model": "m", "seconds": 10}]},
                             "cost_usd": 0.05, "seconds": 60, "outcome": "continue",
                             "verdict": {"action": "continue", "unit_done": True, "units_done": n, "units_planned": 5,
                                         "next": "more", "reason": "fine", "summary": f"did step {n}"}})
        (pdir / "units.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        # T-3, long ago, is still the active ticket
        (pdir / "state.json").write_text(json.dumps({"active_ticket": "T-3", "ready": [f"T-{k}" for k in range(4, 201)]}))
        cls.home = root / "home"
        t = time.time()
        cls.path = worklog.build()
        cls.seconds = time.time() - t
        cls.html = cls.path.read_text()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_page_stays_small_and_fast(self):
        self.assertLess(len(self.html), 600_000, f"{len(self.html)} bytes")
        self.assertLess(self.seconds, 20, f"build took {self.seconds:.1f}s")

    def test_totals_count_everything(self):
        self.assertIn("all time · 1000 units", self.html)
        self.assertIn("$50.00", self.html)

    def test_old_active_ticket_is_shown_in_full(self):
        self.assertIn('id="t-big-T-3"', self.html)

    def test_recent_window_and_older_rows(self):
        self.assertIn('id="t-big-T-200"', self.html)
        self.assertNotIn('id="t-big-T-100"', self.html)
        self.assertIn('href="archive/big/T-100.html"', self.html)

    def test_chain_is_never_cut(self):
        # T-1 gets 12 more units in two chains of 6; a window of 10 would start inside the first
        pdir = self.home / "projects" / "big"
        p = home.resolve_project("big")
        rows = []
        for n in range(6, 18):
            d = pdir / "tickets" / "T-1" / "units" / f"{n:02d}"
            d.mkdir(parents=True, exist_ok=True)
            chain, phase = ("x", n - 5) if n < 12 else ("y", n - 11)
            (d / "plan.json").write_text(json.dumps({"chain": chain, "chain_phase": phase, "chain_total": 6}))
            rows.append({"ticket": "T-1", "unit": n, "ts": iso(time.time())})
        shown = worklog.window(p, rows, 10)
        self.assertEqual(shown[0]["unit"], 6, "the window reaches back to the start of chain x")
        shown = worklog.window(p, rows, 6)
        self.assertEqual(shown[0]["unit"], 12, "a window that starts on a chain's first unit stays there")

    def test_every_ticket_has_an_archive_page(self):
        pages = list((self.home / "archive" / "big").glob("*.html"))
        self.assertEqual(len(pages), 200)
        idx = (self.home / "archive" / "index.html").read_text()
        self.assertIn("200 tickets", idx)
        page = (self.home / "archive" / "big" / "T-50.html").read_text()
        self.assertIn("../../projects/big/tickets/T-50/units/03/report.md", page)
        self.assertNotIn("something true about the code", page, "archive pages link, never embed")

    def test_unchanged_tickets_are_not_rewritten(self):
        p = self.home / "archive" / "big" / "T-10.html"
        before = p.stat().st_mtime_ns
        time.sleep(0.01)
        worklog.build()
        self.assertEqual(p.stat().st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
