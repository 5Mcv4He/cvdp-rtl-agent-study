"""Run a tool-free DSH session with CVDP feedback between submissions."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import tempfile
import time
from unittest.mock import patch

from model_budget import record
from study_common import FEEDBACK, LOCAL, PILOT_ID, score, task_row

MODEL = "deepseek-flash"


def rtl_from_response(response):
    text = response.strip()
    if "```" in text:
        blocks = re.findall(r"```(?:systemverilog|verilog|sv)?[ \t]*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if len(blocks) != 1:
            return None
        text = blocks[0].strip()
    if not text or not re.search(r"\bmodule\s+\w+", text):
        return None
    return text + "\n"


def run_dsh(task, rounds):
    from deepseek_harness import DeepSeekHarness

    row = task_row(task)
    out = LOCAL / "dsh-runs"
    out.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="study-", dir=out))
    print(run, flush=True)
    work = run / "solve"
    work.mkdir()
    target, = row["output"]["context"]
    context = "\n".join(f"File: {name}\n```systemverilog\n{source}\n```"
                        for name, source in row["input"]["context"].items())
    output_contract = f"Return the complete corrected contents of {target}. Preserve the module interface. Return only SystemVerilog."
    prompt = "\n\n".join((row["input"]["prompt"], context, output_contract))
    if len(prompt.encode()) > 24000:
        raise ValueError("public task exceeds the DSH study input limit")
    settings = run / "tool-free.yml"
    settings.write_text(
        "- id: persistent-bash\n  disabled: true\n"
        "- id: persistent-pwsh\n  disabled: true\n"
        "- id: tool-fs\n  disabled: true\n"
        "- id: tool-working-directory\n  disabled: true\n"
        "- id: llm-retry\n  disabled: true\n"
        "- id: session-log-deepseek\n  config:\n    enabled: false\n"
    )
    (run / "input.txt").write_text(prompt)
    scores = []
    usage = []
    start = time.monotonic()
    env = {
        "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8",
        "DEEPSEEK_API_KEY": os.environ["DEEPSEEK_API_KEY"],
    }
    with patch.dict(os.environ, env, clear=True):
        with DeepSeekHarness(
            cwd=str(work), dsh_home=str(work / ".dsh"), profile="sdk-minimal",
            model=MODEL, reasoning_effort="off", max_tokens=4096, patches=(str(settings),),
            request_timeout_seconds=95,
        ) as harness:
            session = harness.start_session()
            for i in range(1, rounds + 1):
                response = session.run(prompt)
                record(run / f"turn-{i}.json", asdict(response))
                for event in response.events:
                    if event["type"] == "assistant/message":
                        usage.append(event["data"].get("usage"))
                candidate = rtl_from_response(response.final_response)
                if candidate is None:
                    break
                snapshot = run / f"candidate-{i}.sv"
                snapshot.write_text(candidate)
                verdict = score(row, snapshot, run / f"replay-{i}")
                scores.append(verdict)
                if verdict["verdict"] not in ("functional", "compile", "timeout"):
                    break
                if len(response.final_response.encode()) > 16000:
                    break
                prompt = FEEDBACK[verdict["verdict"]] + " " + output_contract
    result = {
        "task_id": task, "agent": "dsh", "model": MODEL, "compact_feedback": True,
        "seconds": round(time.monotonic() - start, 3), "scores": scores, "usage": usage,
    }
    record(run / "result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default=PILOT_ID)
    parser.add_argument("--rounds", choices=(1, 2), type=int, default=2)
    args = parser.parse_args()
    os.umask(0o077)
    run_dsh(args.task, args.rounds)
