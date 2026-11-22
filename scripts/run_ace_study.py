"""Run one bounded multi-round ACE-RTL evaluation on a locked CVDP task."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from model_budget import MODELS
from study_common import ACE, LOCK, ROOT, SIM, PILOT_ID, SEED, score, task_row


def run_ace(task, model, rounds, calls, compact):
    row = task_row(task)
    key = os.environ["DEEPSEEK_API_KEY"]
    bin_dir = ACE / ".cvdp-native/bin"
    dataset = ACE / "datasets" / LOCK["dataset"]["file"]
    if hashlib.sha256(dataset.read_bytes()).hexdigest() != LOCK["dataset"]["sha256"]:
        raise ValueError("ACE dataset differs from the lock")
    output = ACE / "outputs"
    output.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="study-", dir=output))
    print(run, flush=True)
    env = {
        "PATH": os.pathsep.join(map(str, (bin_dir, SIM, "/usr/bin", "/bin"))),
        "HOME": str(run), "LANG": "en_US.UTF-8",
        "DEEPSEEK_API_KEY": key,
        "ACE_RTL_LLM_SCRIPT": str(ROOT / "scripts/ace_adapter.py"),
        "STUDY_TRACE": str(run / "api"), "STUDY_MODEL": model, "STUDY_MAX_CALLS": str(calls),
        "ACE_RTL_DISABLE_EDA_SETUP": "1", "CVDP_NATIVE_HARNESS": "1",
        "ACE_RTL_STREAM": "0", "ACE_RTL_ENABLE_REASONING": "0",
        "ACE_RTL_MAX_TOKENS": "4096", "ACE_RTL_LLM_TIMEOUT": "60",
        "COCOTB_RANDOM_SEED": SEED,
        "CVDP_COMPACT_FEEDBACK": "1" if compact else "",
    }
    cmd = [
        str(bin_dir / "python"), "skills/ace-rtl/scripts/ace_cvdp_native_runner.py",
        "--workspace", str(ACE), "--cvdp-repo", str(ACE / "external/cvdp_benchmark"),
        "--dataset", str(dataset), "--cid", "cid016", "--id", task, "--outputs-root", str(run),
        "--generator-model", model, "--reflector-model", model, "--coordinator-model", model,
        "--attempts", "1", "--datapoint-workers", "1", "--max-iterations", str(rounds),
        "--llm-timeout", "65", "--evaluator-timeout", "45",
    ]
    (run / "command.json").write_text(json.dumps(cmd, indent=2))
    start = time.monotonic()
    with (run / "console.log").open("w") as log:
        subprocess.run(cmd, cwd=ACE, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=360, check=True)
    candidates = sorted(run.glob("*/datapoints/*/attempt_1/iter_*/candidate/" + next(iter(row["output"]["context"]))))
    result = {
        "task_id": task, "agent": "ace", "model": model, "compact_feedback": compact,
        "seconds": round(time.monotonic() - start, 3),
        "scores": [score(row, src, run / f"replay-{i}") for i, src in enumerate(candidates, 1)],
    }
    (run / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
    return run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=PILOT_ID)
    parser.add_argument("--model", choices=sorted(MODELS), default="deepseek-flash")
    parser.add_argument("--rounds", choices=(1, 2), type=int, default=2)
    parser.add_argument("--calls", choices=(1, 2, 3, 4, 5), type=int, default=3)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    run_ace(args.task, args.model, args.rounds, args.calls, args.compact)
