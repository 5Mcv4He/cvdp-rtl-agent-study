"""Replay unsent second-generation requests at a larger fixed input limit."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from model_budget import record, request
from run_dsh_study import rtl_from_response
from study_common import LOCAL, score, task_row

SELECTED = {"cvdp_copilot_coffee_machine_0001", "cvdp_copilot_line_buffer_0003"}


def run_probes(rows):
    output = Path(tempfile.mkdtemp(prefix="context-limit-", dir=LOCAL))
    print(output, flush=True)
    records = []
    for row in rows:
        if row["task"] not in SELECTED or not row["condition"].startswith("ace-") or row["submissions"] != 1:
            continue
        base = LOCAL / row["run"]
        calls = sorted((base / "api").glob("*/request.json"))
        if len(calls) != 3:
            raise ValueError("expected first generator and two reflector calls")
        prompt, = base.glob("*/datapoints/*/attempt_1/iter_02/generator.response.prompt.txt")
        initial = json.loads(calls[0].read_text())["body"]
        model = initial["model"]
        messages = [initial["messages"][0], {"role": "user", "content": prompt.read_text()}]
        payload = {**initial, "messages": messages}
        size = len(json.dumps(payload, ensure_ascii=False).encode())
        if not 48000 < size <= 64000:
            raise ValueError("unexpected replay size")
        case_dir = output / f"{len(records) + 1:02d}"
        case_dir.mkdir()
        raw = request(case_dir / "api", os.environ["DEEPSEEK_API_KEY"], model, 1, payload,
                      "generator", max_request_bytes=64000)
        response = json.loads(raw)
        candidate = rtl_from_response(response["choices"][0]["message"]["content"])
        verdict = None
        if candidate:
            file = case_dir / "candidate.sv"
            file.write_text(candidate)
            verdict = score(task_row(row["task"]), file, case_dir / "replay")["verdict"]
        item = {"task": row["task"], "condition": row["condition"], "repetition": row["repetition"],
                "request_bytes": size, "independent_replay": verdict or "no_candidate",
                "usage": response.get("usage")}
        records.append(item)
        record(case_dir / "result.json", item)
        print(item, flush=True)
    record(output / "results.json", records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("private_suite_results", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    run_probes(json.loads(args.private_suite_results.read_text()))
