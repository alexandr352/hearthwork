#!/usr/bin/env python3
"""A stand-in for `npx playwright test <file> ...`: writes a JSON report and one trace per test."""
import io, json, os, sys, zipfile
from pathlib import Path

args = sys.argv[1:]
spec = next(a for a in args if not a.startswith("--"))
out = Path(next(a.split("=", 1)[1] for a in args if a.startswith("--output=")))
out.mkdir(parents=True, exist_ok=True)
png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
Path(os.environ["FAKE_PW_LOG"]).write_text(json.dumps({"args": args, "cwd": os.getcwd(),
                                                      "port": os.environ.get("APP_PORT")}))


def trace(path, t0):
    steps = [{"type": "before", "callId": "c1", "startTime": t0, "title": "Press Tab", "category": "pw:api"},
             {"type": "after", "callId": "c1", "endTime": t0 + 20},
             {"type": "before", "callId": "c2", "startTime": t0 + 400, "title": "Expect toBeFocused", "category": "expect"},
             {"type": "after", "callId": "c2", "endTime": t0 + 420}]
    ctx = [{"type": "screencast-frame", "timestamp": t0 + 10, "sha1": "a"},
           {"type": "screencast-frame", "timestamp": t0 + 300, "sha1": "b"}]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("test.trace", "\n".join(json.dumps(e) for e in steps))
        z.writestr("0-trace.trace", "\n".join(json.dumps(e) for e in ctx))
        z.writestr("resources/a", b"\xff\xd8jpegA")
        z.writestr("resources/b", b"\xff\xd8jpegB")


tests = []
for i, title in enumerate(["the pay button shows focus", "the menu opens"]):
    tr, shot = out / f"t{i}" / "trace.zip", out / f"t{i}" / "end.png"
    tr.parent.mkdir(parents=True, exist_ok=True)
    trace(tr, 1000.0 * (i + 1))
    shot.write_bytes(png)
    tests.append({"projectName": "chromium", "results": [{"status": "passed", "attachments": [
        {"name": "trace", "path": str(tr)}, {"name": "screenshot", "path": str(shot)}]}]})
rep = {"suites": [{"title": os.path.basename(spec), "specs": [
    {"title": "the pay button shows focus", "tests": [tests[0]]}, {"title": "the menu opens", "tests": [tests[1]]}]}]}
Path(os.environ["PLAYWRIGHT_JSON_OUTPUT_NAME"]).write_text(json.dumps(rep))
