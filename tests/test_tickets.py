import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from test_loop import Fixture  # noqa: E402
from hearthwork import cli, tickets  # noqa: E402
from hearthwork.records import Lock, Ticket, read_meter  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


class Rename(Fixture):
    def test_everything_follows_the_new_id(self):
        self.run_units(2)  # unit 2 commits on branch T-1-total
        t = Ticket(self.p, "T-1")
        (t.path("plan.md")).write_text("# T-1 — x\nWork on T-1-total; not T-10, not XT-1.\n")
        (self.p.dir / "knowledge.md").write_text("- totals include tax [T-1]\n- [on T-1-total] total.txt has tax\n")
        self.assertEqual(cli.main(["ticket", "rename", "-p", "demo", "T-1", "PROJ-77"]), 0)
        new = Ticket(self.p, "PROJ-77")
        self.assertTrue(new.exists())
        self.assertFalse(t.dir.exists())
        self.assertEqual(new.read("meta.json")["id"], "PROJ-77")
        self.assertEqual(new.read("meta.json")["renamed_from"], ["T-1"])
        self.assertEqual(new.path("plan.md").read_text(),
                         "# PROJ-77 — x\nWork on PROJ-77-total; not T-10, not XT-1.\n", "only the exact id changes")
        self.assertTrue(all(r["ticket"] == "PROJ-77" for r in read_meter(self.p)))
        st = self.p.read_state()
        self.assertIn("PROJ-77", st["ready"])
        branches = git(self.repo, "branch", "--format=%(refname:short)").split()
        self.assertIn("PROJ-77-total", branches)
        self.assertNotIn("T-1-total", branches)
        k = (self.p.dir / "knowledge.md").read_text()
        self.assertIn("[PROJ-77]", k)
        self.assertIn("[on PROJ-77-total]", k)

    def test_a_pushed_branch_is_left_alone(self):
        self.run_units(2)
        bare = Path(self.tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        git(self.repo, "remote", "add", "origin", str(bare))
        git(self.repo, "push", "-q", "-u", "origin", "T-1-total")
        done = tickets.rename(self.p, "T-1", "T-2x")
        self.assertTrue(any("was pushed" in d for d in done))
        self.assertIn("T-1-total", git(self.repo, "branch", "--format=%(refname:short)").split())

    def test_refusals(self):
        with self.assertRaises(tickets.TicketError):
            tickets.rename(self.p, "T-9", "T-10")
        cli.main(["ticket", "new", "T-2", "-p", "demo", "--text", "x"])
        with self.assertRaises(tickets.TicketError):
            tickets.rename(self.p, "T-1", "T-2")
        with self.assertRaises(tickets.TicketError):
            tickets.rename(self.p, "T-1", "bad id!")
        lock = Lock(self.p)
        lock.acquire()
        try:
            with self.assertRaises(tickets.TicketError):
                tickets.rename(self.p, "T-1", "T-3")
        finally:
            lock.release()
        self.assertTrue(Ticket(self.p, "T-1").exists(), "nothing moved on a refusal")

    def test_title(self):
        self.assertEqual(cli.main(["ticket", "title", "-p", "demo", "T-1", "Totals", "include", "VAT"]), 0)
        t = Ticket(self.p, "T-1")
        self.assertEqual(t.read("meta.json")["title"], "Totals include VAT")
        self.assertTrue(t.path("ticket.md").read_text().startswith("# T-1 — Totals include VAT\n"))


del Fixture

if __name__ == "__main__":
    unittest.main()
