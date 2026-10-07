import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from test_loop import Fixture  # noqa: E402
from test_fence import ask  # noqa: E402
from hearthwork import cli, economy  # noqa: E402
from hearthwork.records import read_meter  # noqa: E402


class EconomyTest(Fixture):
    def by_role(self):
        out = {}
        for c in self.calls():
            role = "operator" if c["cwd"] == str(self.p.dir) else "executor"
            out.setdefault(role, []).append(c)
        return out

    def test_defaults_are_full_economy(self):
        self.assertEqual(economy.load(), economy.DEFAULTS)
        self.run_units(1)
        roles = self.by_role()
        self.assertTrue(all(c["ttl"] == "1h" for c in roles["operator"]))
        self.assertTrue(all(c["ttl"] == "5m" for c in roles["executor"]))
        self.assertTrue(all("--strict-mcp-config" in c["argv"] for c in self.calls()))
        rec = read_meter(self.p)[0]
        self.assertEqual(rec["economy"], economy.DEFAULTS)
        self.assertEqual({c["cache_ttl"] for c in rec["phases"]["plan"]}, {"1h"})

    def test_switches(self):
        self.assertEqual(cli.main(["economy", "--mcp", "on", "--cache", "auto"]), 0)
        self.run_units(1)
        roles = self.by_role()
        self.assertTrue(all(c["ttl"] is None for c in self.calls()), "auto leaves the CLI to decide")
        self.assertTrue(all("--strict-mcp-config" not in c["argv"] for c in roles["executor"]))
        self.assertTrue(all("--strict-mcp-config" in c["argv"] for c in roles["operator"]), "the operator never gets MCP")
        self.assertEqual(economy.label(economy.load()), "custom")
        cli.main(["economy", "--reset"])
        self.assertEqual(economy.load(), economy.DEFAULTS)

    def test_reading_sessions_never_get_mcp(self):
        cli.main(["economy", "--mcp", "on"])
        self.assertEqual(cli.main(["atlas", "-p", "demo"]), 0)
        atlas = [c for c in self.calls() if c["prompt"].startswith("ATLAS BUILD")][0]
        self.assertIn("--strict-mcp-config", atlas["argv"])

    def test_personal_claude_md(self):
        fake_home = Path(self.tmp.name) / "fakehome"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "CLAUDE.md").write_text("Prefer early returns.\n")
        old = os.environ.get("HOME")
        os.environ["HOME"] = str(fake_home)
        try:
            self.run_units(1)
            ex = [c for c in self.calls() if c["cwd"] == str(self.repo)][0]["argv"]
            self.assertNotIn("Prefer early returns.", ex[ex.index("--append-system-prompt") + 1])
            cli.main(["economy", "--claude-md", "on"])
            self.run_units(1)
            ex = [c for c in self.calls() if c["cwd"] == str(self.repo)][-1]["argv"]
            self.assertIn("Prefer early returns.", ex[ex.index("--append-system-prompt") + 1])
        finally:
            os.environ["HOME"] = old

    def test_bad_values_refused(self):
        with self.assertRaises(ValueError):
            economy.save({"cache": "forever"})
        with self.assertRaises(ValueError):
            economy.save({"tools": "all"})


class McpAllowList(unittest.TestCase):
    def test_fence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.realpath(d)
            base = {"mode": "executor", "repo": repo, "protected": ["main"]}
            self.assertEqual(ask(base, "mcp__postgres__query", {}, repo), "deny")
            allow = dict(base, mcp_allow=["postgres__query", "browser__*"])
            self.assertEqual(ask(allow, "mcp__postgres__query", {}, repo), "allow")
            self.assertEqual(ask(allow, "mcp__postgres__execute", {}, repo), "deny")
            self.assertEqual(ask(allow, "mcp__browser__navigate", {}, repo), "allow")


del Fixture

if __name__ == "__main__":
    unittest.main()
