import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FENCE = Path(__file__).resolve().parent.parent / "src" / "hearthwork" / "fence.py"
HOME = str(Path.home())


def ask(policy, tool, tool_input, cwd):
    env = dict(os.environ, HEARTHWORK_FENCE_POLICY=json.dumps(policy))
    out = subprocess.run([sys.executable, str(FENCE)], input=json.dumps(
        {"tool_name": tool, "tool_input": tool_input, "cwd": cwd}), capture_output=True, text=True, env=env).stdout
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


class ExecutorFence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = os.path.realpath(cls.tmp.name)
        subprocess.run(["git", "-C", cls.repo, "init", "-q", "-b", "T-1-work"], check=True)
        cls.policy = {"mode": "executor", "repo": cls.repo, "protected": ["main", "master"], "network_commands": []}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self, tool, ti, want):
        self.assertEqual(ask(self.policy, tool, ti, self.repo), want, f"{tool} {ti}")

    def test_quoted_paths_do_not_hide(self):
        self.check("Bash", {"command": 'cat "$HOME/.ssh/id_ed25519"'}, "deny")
        self.check("Bash", {"command": "cat '~/.ssh/id_ed25519'"}, "deny")
        self.check("Bash", {"command": f"python3 -c \"open('{HOME}/.aws/credentials').read()\""}, "deny")
        self.check("Bash", {"command": f'cat "{HOME}/notes.txt"'}, "deny")

    def test_system_reads_are_fine(self):
        self.check("Bash", {"command": 'cat "/etc/hosts"'}, "allow")
        self.check("Bash", {"command": "ls ~/.npm"}, "allow")

    def test_git_rules(self):
        self.check("Bash", {"command": "git status && git diff"}, "allow")
        self.check("Bash", {"command": "timeout 60 git push origin T-1-work"}, "deny")
        self.check("Bash", {"command": "git commit --no-verify -m x"}, "deny")
        self.check("Bash", {"command": "git commit --amend"}, "deny")
        self.check("Bash", {"command": "git checkout main"}, "deny")
        self.check("Bash", {"command": "git checkout -b T-1-fix"}, "allow")
        self.check("Bash", {"command": "git -C . reset --hard"}, "deny")
        self.check("Bash", {"command": "git commit -m 'Totals include tax'"}, "allow")

    def test_shell_rules(self):
        self.check("Bash", {"command": "curl https://example.com"}, "deny")
        self.check("Bash", {"command": 'grep -rn "ssh" src'}, "allow")
        self.check("Bash", {"command": "echo look at this"}, "allow")
        self.check("Bash", {"command": "npm test -- foo &"}, "deny")
        self.check("Bash", {"command": "sudo ls"}, "deny")
        self.check("Bash", {"command": "bash -c 'ls'"}, "deny")
        self.check("Bash", {"command": "nohup make &"}, "deny")
        self.check("Bash", {"command": "npm install left-pad"}, "deny")
        self.check("Bash", {"command": "echo hi > /tmp/x.txt"}, "allow")
        self.check("Bash", {"command": f"echo hi > {HOME}/x.txt"}, "deny")

    def test_file_tools(self):
        self.check("Read", {"file_path": f"{HOME}/.ssh/config"}, "deny")
        self.check("Read", {"file_path": f"{self.repo}/a.txt"}, "allow")
        self.check("Write", {"file_path": f"{self.repo}/a.txt", "content": "x"}, "allow")
        self.check("Write", {"file_path": f"{HOME}/a.txt", "content": "x"}, "deny")
        self.check("Write", {"file_path": f"{self.repo}/.git/config", "content": "x"}, "deny")
        self.check("Edit", {"file_path": f"{self.repo}/../../etc/escape.txt"}, "deny")

    def test_other_tools(self):
        self.check("WebFetch", {"url": "https://example.com"}, "deny")
        self.check("Agent", {"prompt": "x", "run_in_background": True}, "deny")
        self.check("Agent", {"prompt": "x"}, "allow")
        self.check("mcp__anything__tool", {}, "deny")

    def test_network_allowance(self):
        policy = dict(self.policy, network_commands=["npm ci"])
        self.assertEqual(ask(policy, "Bash", {"command": "npm ci"}, self.repo), "allow")
        self.assertEqual(ask(policy, "Bash", {"command": "curl x"}, self.repo), "deny")


class OperatorAndSpiritFence(unittest.TestCase):
    def test_operator_stays_home(self):
        with tempfile.TemporaryDirectory() as d:
            d = os.path.realpath(d)
            pol = {"mode": "operator", "own_dir": d}
            self.assertEqual(ask(pol, "Read", {"file_path": f"{d}/plan.md"}, d), "allow")
            self.assertEqual(ask(pol, "Write", {"file_path": f"{d}/tickets/T/plan.md", "content": "x"}, d), "allow")
            self.assertEqual(ask(pol, "Read", {"file_path": "/etc/hosts"}, d), "deny")
            self.assertEqual(ask(pol, "Bash", {"command": "ls"}, d), "deny")

    def test_spirit(self):
        with tempfile.TemporaryDirectory() as h, tempfile.TemporaryDirectory() as r:
            h, r = os.path.realpath(h), os.path.realpath(r)
            pol = {"mode": "spirit", "home": h, "repos": [r]}
            cwd = f"{h}/spirit"
            self.assertEqual(ask(pol, "Read", {"file_path": f"{r}/src/a.py"}, cwd), "allow")
            self.assertEqual(ask(pol, "Write", {"file_path": f"{h}/spirit/memory/x.md", "content": "x"}, cwd), "allow")
            self.assertEqual(ask(pol, "Write", {"file_path": f"{h}/projects/p/state.json", "content": "x"}, cwd), "deny")
            self.assertEqual(ask(pol, "Bash", {"command": "operator status"}, cwd), "allow")
            self.assertEqual(ask(pol, "Bash", {"command": "operator status; rm -rf /"}, cwd), "deny")
            self.assertEqual(ask(pol, "Bash", {"command": f"git -C {r} log --oneline -5"}, cwd), "allow")
            self.assertEqual(ask(pol, "Bash", {"command": f"git -C {r} push"}, cwd), "deny")
            self.assertEqual(ask(pol, "Bash", {"command": "cat /etc/passwd"}, cwd), "deny")


class NoPolicyDenies(unittest.TestCase):
    def test_missing_policy(self):
        env = {k: v for k, v in os.environ.items() if k != "HEARTHWORK_FENCE_POLICY"}
        out = subprocess.run([sys.executable, str(FENCE)], input='{"tool_name":"Read","tool_input":{}}',
                             capture_output=True, text=True, env=env).stdout
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
