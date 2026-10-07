import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from test_loop import Fixture  # noqa: E402
from hearthwork import cli, guide, server, worklog  # noqa: E402
from hearthwork.records import read_meter, running  # noqa: E402


class WhileAUnitRuns(Fixture):
    def test_the_running_unit_is_seen_everywhere(self):
        (self.state).mkdir(parents=True, exist_ok=True)
        (self.state / "slow-exec").write_text("1")
        self.assertEqual(cli.main(["run", "-p", "demo", "--detach"]), 0)
        seen = None
        for _ in range(150):
            r = running(self.p)
            if r and r.get("phase") == "executing":
                seen = r
                break
            time.sleep(0.05)
        self.assertIsNotNone(seen, "the running record names the phase")
        self.assertEqual((seen["ticket"], seen["unit"]), ("T-1", 1))
        self.assertEqual(guide.next_step()["key"], "running")
        page = worklog.render(ui=True)
        self.assertIn('id="t-demo-T-1"', page, "the ticket shows before its first unit is judged")
        self.assertIn("class=runcard", page)
        self.assertIn("the executor is working", page)
        for _ in range(200):
            if read_meter(self.p):
                break
            time.sleep(0.05)
        for _ in range(100):
            if not (self.p.dir / "running.json").exists():
                break
            time.sleep(0.05)
        self.assertIsNone(running(self.p), "the record goes when the unit ends")
        self.assertNotEqual(guide.next_step()["key"], "running")

    def test_a_stale_record_is_ignored(self):
        (self.p.dir / "running.json").write_text(json.dumps({"ticket": "T-1", "unit": 1, "phase": "planning", "pid": 999999}))
        self.assertIsNone(running(self.p))

    def test_a_held_lock_counts_without_a_record(self):
        from hearthwork.records import Lock
        lock = Lock(self.p)
        self.assertTrue(lock.acquire())
        try:
            r = running(self.p)
            self.assertIsNotNone(r, "a run started by an older version still shows")
            self.assertEqual((r["ticket"], r["phase"]), ("T-1", "working"))
            self.assertEqual(guide.next_step()["key"], "running")
        finally:
            lock.release()
        self.assertIsNone(running(self.p))

    def test_new_active_ticket_has_a_section(self):
        self.assertIn('id="t-demo-T-1"', worklog.render(ui=True))
        self.assertIn("no units yet", worklog.render(ui=True))


class ChatHistory(unittest.TestCase):
    def test_kept_and_cleared(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            h = Path(d)
            (h / "spirit").mkdir()
            server.history_add(h, "me", "hello")
            server.history_add(h, "tool", "$ operator next")
            server.history_add(h, "spirit", "**Hi.** No project yet.")
            self.assertEqual([m["kind"] for m in server.history_read(h)], ["me", "tool", "spirit"])
            for i in range(server.HISTORY_KEEP + 20):
                server.history_add(h, "meta", str(i))
            self.assertEqual(len(server.history_read(h)), server.HISTORY_KEEP, "bounded")


del Fixture

if __name__ == "__main__":
    unittest.main()
