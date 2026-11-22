"""Replay a single local RTL file with CVDP local_import and check the scored bytes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
candidate = Path(sys.argv[1]).resolve()
content = candidate.read_bytes()
if b"```" in content:
    raise SystemExit("candidate contains a Markdown fence delimiter")
plan = json.loads((root / "experiments/P0/lock.json").read_text())
task = plan["first_task"]
dataset = root / ".local/data" / plan["dataset"]["file"]

if hashlib.sha256(dataset.read_bytes()).hexdigest() != plan["dataset"]["sha256"]:
    raise SystemExit("dataset does not match the P0 lock")
score = root / ".local/score/bin"
sim = root / ".local/tools/icarus-verilog/13.0/bin"
os.umask(0o077)
run = Path(tempfile.mkdtemp(prefix="replay-", dir=root / ".local"))
print(run, flush=True)
completion = run / "completion.jsonl"
completion.write_text(json.dumps({
    "id": task["id"], "completion": "```systemverilog\n" + content.decode() + "```",
}) + "\n")
env = {
    "PATH": os.pathsep.join(map(str, (score, sim, "/usr/bin", "/bin"))),
    "HOME": str(run), "LANG": "en_US.UTF-8",
}
with (run / "console.log").open("w") as log:
    subprocess.run([
        str(score / "python"), str(root / "scripts/score_native.py"),
        "-f", str(dataset), "-i", task["id"],
        "-l", "-m", "local_import", "--prompts-responses-file", str(completion),
        "-t", "1", "-p", str(run / "work"),
    ], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
tested, = (run / "work").glob("*/harness/1/" + task["target_paths"][0])
if tested.read_bytes() != content:
    raise SystemExit(f"the scorer changed the submitted bytes: {tested}")
print(f"Candidate SHA-256: {hashlib.sha256(content).hexdigest()}")
report, = (run / "work").glob("*/reports/1.txt")
print("\n".join(line.strip() for line in report.read_text().splitlines()
                if "TESTS=" in line or "AssertionError:" in line))
