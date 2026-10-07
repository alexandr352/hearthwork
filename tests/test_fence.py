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
        self.check("Bash", {"command": "git checkout -b T-1-fix main"}, "allow")
        self.check("Bash", {"command": "git switch -c T-1-fix master"}, "allow")
        self.check("Bash", {"command": "git checkout -b main"}, "deny")
        self.check("Bash", {"command": "git switch main"}, "deny")
        self.check("Bash", {"command": "git branch -D main"}, "deny")
        self.check("Bash", {"command": "git branch -f main HEAD"}, "deny")
        self.check("Bash", {"command": "git branch --show-current"}, "allow")
        self.check("Bash", {"command": "git checkout -- cart.py"}, "allow")
        self.check("Bash", {"command": "git -C . reset --hard"}, "deny")
        self.check("Bash", {"command": "git commit -m 'Totals include tax'"}, "allow")
        self.check("Bash", {"command": "git commit -m 'Totals include tax\n\nCo-Authored-By: Claude <noreply@anthropic.com>'"}, "deny")
        self.check("Bash", {"command": "git commit -F - <<'EOF'\nTotals\n\nco-authored-by: Claude\nEOF"}, "deny")

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

    def test_co_author_allowed_when_the_project_wants_it(self):
        policy = dict(self.policy, co_author=True)
        self.assertEqual(ask(policy, "Bash", {"command": "git commit -m 'x\n\nCo-Authored-By: Claude'"}, self.repo), "allow")

    def test_network_allowance(self):
        policy = dict(self.policy, network_commands=["npm ci"])
        self.assertEqual(ask(policy, "Bash", {"command": "npm ci"}, self.repo), "allow")
        self.assertEqual(ask(policy, "Bash", {"command": "curl x"}, self.repo), "deny")


class ReadOnlyFence(unittest.TestCase):
    def test_reader_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.realpath(d)
            pol = {"mode": "executor", "repo": repo, "protected": ["main"], "read_only": True}
            for tool, ti, want in [
                ("Read", {"file_path": f"{repo}/README.md"}, "allow"),
                ("Bash", {"command": "git log --oneline -5"}, "allow"),
                ("Bash", {"command": "ls src && cat package.json"}, "allow"),
                ("Bash", {"command": "npm --version"}, "allow"),
                ("Bash", {"command": f"cd {repo}; ls -a"}, "allow"),
                ("Write", {"file_path": f"{repo}/a.txt", "content": "x"}, "deny"),
                ("Edit", {"file_path": f"{repo}/a.txt"}, "deny"),
                ("Bash", {"command": "echo x > a.txt"}, "deny"),
                ("Bash", {"command": "git add -A"}, "deny"),
                ("Bash", {"command": "git checkout -b x"}, "deny"),
                ("Bash", {"command": "sed -i s/a/b/ a.txt"}, "deny"),
                ("Bash", {"command": "rm a.txt"}, "deny"),
                ("Bash", {"command": "npm run build"}, "deny"),
                ("Bash", {"command": "make"}, "deny"),
            ]:
                self.assertEqual(ask(pol, tool, ti, repo), want, f"{tool} {ti}")


class LinkedTmp(unittest.TestCase):
    """macOS: /tmp is a link to /private/tmp and $TMPDIR points under /var/folders. Scratch
    space is recognised by its real path, and nothing else is let through by it."""

    def test_scratch_by_real_path(self):
        base = tempfile.mkdtemp(prefix=".hw-fence-", dir=str(Path.home()))
        try:
            real = os.path.join(base, "private-tmp")
            os.mkdir(real)
            link = os.path.join(base, "tmp")
            os.symlink(real, link)
            repo = os.path.join(base, "repo")
            os.mkdir(repo)
            pol = {"mode": "executor", "repo": repo, "protected": ["main"]}
            env = dict(os.environ, TMPDIR=link, HEARTHWORK_FENCE_POLICY=json.dumps(pol))

            def ask_env(tool, ti):
                out = subprocess.run([sys.executable, str(FENCE)], input=json.dumps(
                    {"tool_name": tool, "tool_input": ti, "cwd": repo}), capture_output=True, text=True, env=env).stdout
                return json.loads(out)["hookSpecificOutput"]["permissionDecision"]

            self.assertEqual(ask_env("Write", {"file_path": link + "/x.txt", "content": "x"}), "allow")
            self.assertEqual(ask_env("Bash", {"command": f"echo hi > {link}/y.txt"}), "allow")
            self.assertEqual(ask_env("Write", {"file_path": base + "/elsewhere.txt", "content": "x"}), "deny")
            self.assertEqual(ask_env("Bash", {"command": f"echo hi > {base}/elsewhere.txt"}), "deny")
        finally:
            import shutil
            shutil.rmtree(base)


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
            self.assertEqual(ask(pol, "Bash", {"command": 'operator atlas answer 1 "unittest; one file: a ; all: b | c"'}, cwd), "allow",
                             "operators inside quotes are the person's words")
            self.assertEqual(ask(pol, "Bash", {"command": "operator atlas answer 1 'x && y'"}, cwd), "allow")
            self.assertEqual(ask(pol, "Bash", {"command": 'operator atlas answer 1 "$(rm -rf ~)"'}, cwd), "deny")
            self.assertEqual(ask(pol, "Bash", {"command": "operator atlas answer 1 `id`"}, cwd), "deny")
            self.assertEqual(ask(pol, "Bash", {"command": 'operator status && operator ticket list'}, cwd), "deny")
            self.assertEqual(ask(pol, "Bash", {"command": 'operator status 2>&1'}, cwd), "deny")
            self.assertEqual(ask(pol, "Bash", {"command": 'operator status | head'}, cwd), "deny")
            self.assertEqual(ask(pol, "Bash", {"command": 'operator atlas answer 2 "line one\nline two"'}, cwd), "allow",
                             "a newline inside quotes is text")
            self.assertEqual(ask(pol, "Bash", {"command": "operator status\nrm -rf ~"}, cwd), "deny",
                             "a newline outside quotes is a second command")
            self.assertEqual(ask(pol, "Bash", {"command": "operator run --detach"}, cwd), "allow")
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
