import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from test_loop import Fixture  # noqa: E402
from hearthwork import cli, mcp  # noqa: E402
from hearthwork.records import read_meter  # noqa: E402


class McpTest(Fixture):
    def setUp(self):
        super().setUp()
        self.server = mcp.Server("demo")

    def call(self, name, **args):
        r = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": name, "arguments": args}})
        res = r["result"]
        return res["content"][0]["text"], res["isError"]

    def lease_of(self, text):
        return text.split("lease: ")[1].split()[0]

    def test_protocol(self):
        r = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(r["result"]["serverInfo"]["name"], "hearthwork")
        names = [t["name"] for t in self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
        self.assertEqual(names, ["next", "submit", "status", "rule"])
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_next_do_submit(self):
        text, err = self.call("next")
        self.assertFalse(err)
        self.assertIn("SCOPE CONSTRAINT", text)
        self.assertIn("EXECUTOR", text, "the executor's rules travel with the unit")
        lease = self.lease_of(text)
        again, _ = self.call("next")
        self.assertEqual(self.lease_of(again), lease, "an open unit is handed out again, not re-planned")
        self.assertNotEqual(cli.main(["run", "-p", "demo"]), 1)
        self.assertTrue(self.t.path("lease.json").exists(), "a headless run does not touch an open unit")
        text, err = self.call("submit", lease=lease, report="[1] File: total.txt | Line: 1 | Finding: total = price | Confidence: high")
        self.assertFalse(err)
        self.assertIn("judged", text)
        rows = read_meter(self.p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["executor"], "mcp")
        self.assertIn("plan", rows[0]["phases"])
        self.assertIn("judge", rows[0]["phases"])
        # unit 2: the session commits, and git — not the report — tells the judge so
        text, _ = self.call("next")
        lease = self.lease_of(text)
        for args in (["checkout", "-q", "-b", "T-1-total"], ["commit", "-q", "--allow-empty", "-m", "Totals include tax"]):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True)
        text, _ = self.call("submit", lease=lease, report="STATUS: success")
        self.assertIn("ready", text)
        self.assertIn("Totals include tax", (self.t.unit_dir(2) / "facts.md").read_text())

    def test_wrong_lease_and_empty_report(self):
        text, _ = self.call("next")
        _, err = self.call("submit", lease="nope", report="x")
        self.assertTrue(err)
        _, err = self.call("submit", lease=self.lease_of(text), report="  ")
        self.assertTrue(err)

    def test_still_planning_then_picked_up(self):
        mcp.WAIT = 0.3
        try:
            self.flag("slow-plan")
            text, err = self.call("next")
            self.assertIn("STILL PLANNING", text)
            for _ in range(20):
                text, err = self.call("next")
                if "lease:" in text:
                    break
            self.assertIn("lease:", text)
        finally:
            mcp.WAIT = 50

    def test_abandon(self):
        self.call("next")
        self.assertEqual(cli.main(["abandon", "-p", "demo"]), 0)
        self.assertFalse(self.t.path("lease.json").exists())
        self.assertIn("abandoned", self.t.path("rulings.md").read_text())

    def test_stdio(self):
        p = subprocess.run([sys.executable, "-m", "hearthwork", "mcp", "-p", "demo"], input="\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "status", "arguments": {}}}),
        ]) + "\n", capture_output=True, text=True, cwd=str(self.repo),
            env={**__import__("os").environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src")})
        lines = [json.loads(l) for l in p.stdout.splitlines()]
        self.assertEqual({l["id"] for l in lines}, {1, 2}, p.stderr)
        status = next(l for l in lines if l["id"] == 2)["result"]["content"][0]["text"]
        self.assertIn("active ticket: T-1", status)


del Fixture

if __name__ == "__main__":
    unittest.main()
