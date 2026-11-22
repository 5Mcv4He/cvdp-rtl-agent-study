"""Select a locked task and independently replay a submitted RTL candidate."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
ACE = LOCAL / "upstream/ace"
SCORE = LOCAL / "score/bin"
SIM = LOCAL / "tools/icarus-verilog/13.0/bin"
LOCK = json.loads((ROOT / "experiments/P0/lock.json").read_text())
DATASET = LOCAL / "data" / LOCK["dataset"]["file"]
PILOT_ID = LOCK["first_task"]["id"]
SEED = "20261122"

FEEDBACK = {
    "pass": "The CVDP test passed.",
    "functional": "The CVDP test compiled and ran, then failed a functional check. Review your RTL and the public task specification.",
    "compile": "The CVDP test could not compile or elaborate the candidate. Review syntax, declarations, and module interfaces.",
    "timeout": "The CVDP test timed out. Check the candidate for nonterminating simulation behavior.",
}


def task_row(task_id):
    raw = DATASET.read_bytes()
    if hashlib.sha256(raw).hexdigest() != LOCK["dataset"]["sha256"]:
        raise ValueError("dataset differs from the lock")
    rows = [row for row in map(json.loads, raw.splitlines()) if row["id"] == task_id]
    row, = rows
    if "cid016" not in row["categories"] or len(row["output"]["context"]) != 1:
        raise ValueError("runner requires a single-target cid016 task")
    return row


def score(row, src, work):
    work.mkdir(mode=0o700)
    completion = work / "completion.jsonl"
    code = src.read_bytes()
    for prohibited in (b"```", b"$system", b"$fopen", b"$readmem", b"$writemem"):
        if prohibited in code:
            raise ValueError(f"unsupported candidate content: {prohibited!r}")
    completion.write_text(json.dumps({
        "id": row["id"],
        "completion": "```systemverilog\n" + code.decode() + "```",
    }) + "\n")
    env = {
        "PATH": os.pathsep.join(map(str, (SCORE, SIM, "/usr/bin", "/bin"))),
        "HOME": str(work), "LANG": "en_US.UTF-8",
        "CVDP_NATIVE_TIMEOUT": "45", "COCOTB_RANDOM_SEED": SEED,
    }
    prefix = work / "cvdp"
    with (work / "console.log").open("w") as log:
        subprocess.run([
            str(SCORE / "python"), str(ROOT / "scripts/score_native.py"),
            "-f", str(DATASET), "-i", row["id"], "-l", "-m", "local_import",
            "--prompts-responses-file", str(completion), "-t", "1", "-p", str(prefix),
        ], env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=75)
    target, = row["output"]["context"]
    tested, = prefix.glob("*/harness/*/" + target)
    if tested.read_bytes() != code:
        raise ValueError("CVDP changed the submitted bytes")
    official = json.loads((prefix / "raw_result.json").read_text())[row["id"]]
    service, = official["tests"]
    report = Path(service["log"])
    diagnostics = report.read_text()
    counts = re.search(r"TESTS=(\d+) PASS=(\d+) FAIL=(\d+) SKIP=(\d+)", diagnostics)
    if counts and int(counts[1]) > 0:
        verdict = "pass" if official["errors"] == 0 and counts[1] == counts[2] and counts[3] == counts[4] == "0" else "functional"
    elif "native harness timeout" in diagnostics:
        verdict = "timeout"
    elif "returned non-zero exit status" in diagnostics and ("iverilog" in diagnostics or "elaborat" in diagnostics):
        verdict = "compile"
    else:
        verdict = "infra"
    result = {
        "task_id": row["id"], "verdict": verdict, "candidate_sha256": hashlib.sha256(code).hexdigest(),
        "cocotb_tests": int(counts[1]) if counts else None,
        "assertion": next((line.strip() for line in diagnostics.splitlines() if "AssertionError:" in line), None),
    }
    (work / "verdict.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result
