"""Score the fixed D2 controls and functional mutants with both verifiers."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import tempfile

from study_common import LOCAL, LOCK, PILOT_ID, SEED, score, task_row
from verify_rtl_d2 import DEFAULT_SEED, executable, score_candidate

TASKS = {"adder": PILOT_ID, "encoder": "cvdp_copilot_64b66b_encoder_0005"}
MUTATIONS = {
    "adder": {
        "ignore_carry_in": (
            " + {32'b0, carry_in}", "",
        ),
        "drop_carry_out": (
            "assign {carry_out, sum} =", "assign carry_out = 1'b0;\n    assign sum =",
        ),
        "drop_operand_bit17": (
            "{1'b0, a}", "{1'b0, (a & 32'hfffdffff)}",
        ),
        "lose_full_width_cin_carry": (
            "{32'b0, carry_in}", "{32'b0, (carry_in && ((a ^ b) != 32'hffffffff))}",
        ),
    },
    "encoder": {
        "retain_control_payload": (
            "encoder_data_out <= {2'b10, 64'b0};", "encoder_data_out[65:64] <= 2'b10;",
        ),
        "bad_control_header": (
            "encoder_data_out <= {2'b10, 64'b0};", "encoder_data_out <= {2'b01, 64'b0};",
        ),
        "synchronous_reset_only": (
            "posedge clk_in or posedge rst_in", "posedge clk_in",
        ),
        "ignore_unrecognized_control_masks": (
            "encoder_control_in == 8'h00", "encoder_control_in != 8'hff",
        ),
        "capture_on_falling_edge": (
            "posedge clk_in or posedge rst_in", "negedge clk_in or posedge rst_in",
        ),
    },
}
REPETITIONS = 3
ALTERNATE_SEED = DEFAULT_SEED + 1


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def controls(task, row, directory):
    target, = row["output"]["context"]
    primary = (directory / f"{task}-primary.sv").read_text()
    alternate = (directory / f"{task}-alternate.sv").read_text()
    yield "positive_primary", "positive", primary
    yield "positive_alternate", "positive", alternate
    yield "original", "original_negative", row["input"]["context"][target]

    for name, (before, after) in MUTATIONS[task].items():
        if primary.count(before) != 1 or before == after:
            raise ValueError(f"{task}/{name}: the single-change mutant anchor does not match")
        mutant = primary.replace(before, after, 1)
        if mutant == primary:
            raise ValueError(f"{task}/{name}: mutant did not change the source")
        yield name, "functional_mutant", mutant


def audit_fixture(task, row, fixture, work):
    name, kind, content = fixture
    work.mkdir()
    candidate = work / "fixture.sv"
    blob = content.encode()
    candidate.write_bytes(blob)

    independent = [
        score_candidate(task, candidate, DEFAULT_SEED, work / f"independent-{i}")
        for i in range(1, REPETITIONS + 1)
    ]
    alternate = score_candidate(task, candidate, ALTERNATE_SEED, work / "independent-alternate")
    cvdp = []
    for i in range(1, REPETITIONS + 1):
        verdict = score(row, candidate, work / f"cvdp-{i}")
        if verdict["candidate_sha256"] != digest(blob):
            raise ValueError("CVDP compared different candidate bytes")
        cvdp.append({key: verdict[key] for key in ("verdict", "cocotb_tests")})
    return {
        "fixture": name, "kind": kind, "candidate_sha256": digest(blob),
        "expected": "pass" if kind == "positive" else "functional",
        "independent": independent[0],
        "independent_fixed_seed_replays": [x["verdict"] for x in independent],
        "independent_fixed_seed_identical": all(x == independent[0] for x in independent),
        "independent_alternate_seed": alternate,
        "cvdp": cvdp[0],
        "cvdp_fixed_seed_replays": [x["verdict"] for x in cvdp],
        "cvdp_fixed_seed_identical": all(x == cvdp[0] for x in cvdp),
    }


def summarize(rows, key):
    positives = [r for r in rows if r["kind"] == "positive"]
    mutants = [r for r in rows if r["kind"] == "functional_mutant"]
    original, = (r for r in rows if r["kind"] == "original_negative")
    return {
        "positive_controls_passed": sum(r[key]["verdict"] == "pass" for r in positives),
        "positive_controls": len(positives),
        "false_rejects": [r["fixture"] for r in positives if r[key]["verdict"] != "pass"],
        "functionally_rejected_mutants": sum(r[key]["verdict"] == "functional" for r in mutants),
        "functional_mutants": len(mutants),
        "escaping_mutants": [r["fixture"] for r in mutants if r[key]["verdict"] == "pass"],
        "original_verdict": original[key]["verdict"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controls", type=Path, default=LOCAL / "d2-controls")
    parser.add_argument("--workers", type=int, default=3, choices=range(1, 5))
    args = parser.parse_args()
    os.umask(0o077)
    output = Path(tempfile.mkdtemp(prefix="v2-d2-", dir=LOCAL))
    print(output, flush=True)
    if int(SEED) != DEFAULT_SEED:
        raise ValueError("independent fixed-seed schedule differs from CVDP replay seed")
    result = {
        "dataset_sha256": LOCK["dataset"]["sha256"], "model_requests": 0,
        "fixed_seed": DEFAULT_SEED, "fixed_seed_repetitions": REPETITIONS,
        "alternate_independent_seed": ALTERNATE_SEED,
        "simulator_sha256": {tool: digest(executable(tool).read_bytes())
                             for tool in ("iverilog", "vvp")},
        "tasks": {},
    }
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for task, task_id in TASKS.items():
            row = task_row(task_id)
            directory = output / task
            directory.mkdir()
            fixtures = list(controls(task, row, args.controls))
            jobs = [pool.submit(audit_fixture, task, row, fixture, directory / fixture[0])
                    for fixture in fixtures]
            rows = []
            for job in jobs:
                entry = job.result()
                print(task, entry["fixture"], entry["independent"]["verdict"],
                      entry["cvdp"]["verdict"], flush=True)
                rows.append(entry)
            result["tasks"][task] = {
                "task_id": task_id, "fixtures": rows,
                "independent": summarize(rows, "independent"), "cvdp": summarize(rows, "cvdp"),
            }
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    issues = [(task, r["fixture"]) for task, info in result["tasks"].items() for r in info["fixtures"]
              if (r["independent"]["verdict"] != r["expected"] or
                  r["independent_alternate_seed"]["verdict"] != r["expected"] or
                  not r["independent_fixed_seed_identical"] or
                  not r["cvdp_fixed_seed_identical"] or
                  r["cvdp"]["verdict"] not in ("pass", "functional"))]
    if issues:
        raise SystemExit(f"Verifier quality gate failed on {issues}; measured results retained.")


if __name__ == "__main__":
    main()
