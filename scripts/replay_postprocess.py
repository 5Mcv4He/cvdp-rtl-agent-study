"""D1: compare processing paths for frozen responses using the V1 native scorer."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from micu_api import KEY_VARIABLES, normalize
from run_dsh_study import rtl_from_response
from study_common import ACE, LOCAL, SEED, SIM, score, task_row

ACE_SCRIPTS = ACE / "skills/ace-rtl/scripts"
AUDIT = LOCAL / "methodology-v2-audit"


def read_json(path):
    return json.loads(path.read_text())


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def matrix_run(task, condition, repetition=1):
    rows = read_json(AUDIT / "index.json")
    row, = (r for r in rows if (r["task"], r["condition"], r["repetition"]) ==
            (task, condition, repetition))
    return LOCAL.parent / row["run"], row


def ace_iteration(run, iteration):
    directory, = run.glob(f"*/datapoints/*/attempt_1/iter_{iteration:02d}")
    return directory


def ace_visible_choice(request, response):
    payload = read_json(response)
    model = read_json(request)["body"]["model"]
    if model in KEY_VARIABLES:
        payload = normalize(model, payload)
    return payload["choices"][0]


def sdk_visible_text(turn):
    event, = (e for e in turn["events"] if e["type"] == "assistant/message")
    content = event["data"]["message"]["content"]
    text = "".join(block["text"] for block in content if block["type"] == "text")
    if text != turn["final_response"]:
        raise ValueError("DSH final response does not match visible SDK message")
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New private experiment directory under .local")
    args = parser.parse_args()
    os.umask(0o077)
    sys.path.insert(0, str(ACE_SCRIPTS))
    from ace_cvdp_native.sv import lower_always_comb_for_native_icarus
    from extract_solution import extract_code

    if args.output:
        work = args.output.resolve()
        if not work.is_relative_to(LOCAL.resolve()):
            parser.error("--output must be under .local")
        work.mkdir(mode=0o700)
    else:
        work = Path(tempfile.mkdtemp(prefix="v2-d1-", dir=LOCAL))
    print(work, flush=True)

    fsm = "cvdp_copilot_fsm_seq_detector_0023"
    swizzler = "cvdp_copilot_swizzler_0014"
    cases = [
        ("fsm-always-comb", fsm, "ace-gpt", "always_comb"),
        ("fsm-cast-control", fsm, "dsh-gpt", "always_comb"),
        ("swizzler-extraction", swizzler, "ace-gpt", "extraction"),
        ("counter-extraction", "cvdp_copilot_generic_nbit_counter_0036",
         "dsh-flash", "extraction"),
    ]
    results = []
    for case, task, condition, factor in cases:
        directory = work / case
        directory.mkdir()
        run, index = matrix_run(task, condition)
        row = task_row(task)
        target, = row["output"]["context"]
        if condition.startswith("ace"):
            iteration = ace_iteration(run, 1)
            response = iteration / "generator.response.json"
            accepted = read_json(response)
            text = accepted["content"]
            matched = []
            for request in sorted(run.glob("api/*/request.json")):
                provider = request.with_name("provider-response")
                if read_json(request)["role"] != "generator" or not provider.exists():
                    continue
                choice = ace_visible_choice(request, provider)
                if (choice["message"]["content"].strip() == text.strip() and
                        choice["finish_reason"] == accepted["finish_reason"]):
                    matched.append(provider)
            if len(matched) != 1:
                raise ValueError(f"{case}: accepted Generator response is not uniquely traceable")
            ace_code = extract_code(text).rstrip() + "\n"
            saved = iteration / "candidate" / target
            saved_extraction = saved.with_suffix(saved.suffix + ".raw")
            if not saved_extraction.exists():
                saved_extraction = saved
            if ace_code.encode() != saved_extraction.read_bytes():
                raise ValueError(f"{case}: ACE extraction does not reproduce archived bytes")
            baseline, mutations = (ace_code, 0) if factor == "extraction" else (
                lower_always_comb_for_native_icarus(ace_code))
            baseline_name = "ace_extract" if factor == "extraction" else "ace_extract_then_lower"
            if baseline.encode() != saved.read_bytes():
                raise ValueError(f"{case}: historical path does not reproduce the saved RTL")
            if factor == "extraction":
                variants = [(baseline_name, baseline), ("dsh_extract", rtl_from_response(text))]
            else:
                variants = [("ace_extract", ace_code), (baseline_name, baseline)]
        elif factor == "extraction":
            response = run / "turn-2.json"
            turn = read_json(response)
            text = sdk_visible_text(turn)
            baseline = rtl_from_response(text)
            if (turn["finish_reason"] != "completed" or baseline is not None or
                    len(index["candidate_sha256"]) != 1 or (run / "candidate-2.sv").exists()):
                raise ValueError(f"{case}: archived extraction stop did not reproduce")
            baseline_name = "dsh_extract"
            variants = [(baseline_name, None), ("ace_extract", extract_code(text).rstrip() + "\n")]
        else:
            response = run / "turn-1.json"
            text = sdk_visible_text(read_json(response))
            baseline = rtl_from_response(text)
            if baseline is None or baseline.encode() != (run / "candidate-1.sv").read_bytes():
                raise ValueError(f"{case}: DSH extraction does not reproduce archived bytes")
            lowered, mutations = lower_always_comb_for_native_icarus(baseline)
            baseline_name = "dsh_extract"
            variants = [(baseline_name, baseline), ("dsh_extract_then_lower", lowered)]
        historic_hash = index["candidate_sha256"][0] if baseline is not None else None
        if baseline is not None and sha256(baseline.encode()) != historic_hash:
            raise ValueError(f"{case}: archived hash mismatch")
        historic_verdict = (read_json(run / "replay-1/verdict.json")["verdict"]
                            if baseline is not None else "no_candidate")
        measurements = []
        for name, content in variants:
            if content is None:
                measurements.append({"path": name, "verdict": "no_candidate",
                                     "candidate_sha256": None, "cocotb_tests": None})
                print(case, name, "no_candidate", flush=True)
                continue
            candidate = directory / f"{name}.sv"
            candidate.write_bytes(content.encode())
            verdict = score(row, candidate, directory / name)
            if verdict["verdict"] == "infra":
                raise ValueError(f"{case}: native scorer encountered an infrastructure error")
            measurements.append({"path": name, **verdict})
            if name == baseline_name and verdict["verdict"] != historic_verdict:
                raise ValueError(f"{case}: historical verdict did not reproduce")
            print(case, name, verdict["verdict"], flush=True)
        both_scored = all(code is not None for _, code in variants)
        results.append({
            "case": case, "task": task, "condition": condition, "repetition": 1,
            "round": 2 if baseline is None else 1,
            "factor": factor, "source": str(response.relative_to(LOCAL.parent)),
            "response_text_sha256": sha256(text.encode()), "historic_path": baseline_name,
            "historic_candidate_sha256": historic_hash, "historic_verdict": historic_verdict,
            "always_comb_replacements": mutations if factor == "always_comb" else None,
            "candidate_bytes_changed": (variants[0][1] != variants[1][1]) if both_scored else None,
            "scoring_admission_changed": not both_scored,
            "scored_verdict_changed": (measurements[0]["verdict"] != measurements[1]["verdict"])
            if both_scored else None,
            "measurements": measurements,
        })
    result = {"dataset": "CVDP v1.1.0", "scorer": "native local_import",
              "seed": SEED, "iverilog_sha256": sha256((SIM / "iverilog").read_bytes()),
              "model_requests": 0, "cases": results}
    (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    public = {**result, "cases": [
        {**{k: v for k, v in case.items() if k not in ("source", "measurements")},
         "measurements": [{k: v for k, v in measurement.items() if k != "assertion"}
                          for measurement in case["measurements"]]}
        for case in results
    ]}
    (work / "public-summary.json").write_text(json.dumps(public, indent=2) + "\n")


if __name__ == "__main__":
    main()
