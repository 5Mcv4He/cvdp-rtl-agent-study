"""Prepare the locked task and two local-import candidates for Compose calibration."""
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "experiments/P0/lock.json").read_text())


def prepare(work):
    d = LOCK["dataset"]
    t = LOCK["first_task"]
    url = f"https://huggingface.co/datasets/{d['repo']}/resolve/{d['revision']}/{d['file']}"
    with urlopen(url, timeout=50) as response:
        raw = response.read()
    if hashlib.sha256(raw).hexdigest() != d["sha256"]:
        raise ValueError("dataset differs from the lock")
    line = raw.splitlines()[t["line_1based"] - 1]
    if hashlib.sha256(line).hexdigest() != t["row_sha256_without_newline"]:
        raise ValueError("task differs from the lock")
    row = json.loads(line)
    target, = t["target_paths"]
    control = """module brent_kung_adder(
    input logic [31:0] a, b,
    input logic carry_in,
    output logic [31:0] sum,
    output logic carry_out
);
    assign {carry_out, sum} = {1'b0, a} + {1'b0, b} + {32'b0, carry_in};
endmodule
"""
    (work / "task.jsonl").write_bytes(line + b"\n")
    for name, source in {"original": row["input"]["context"][target], "behavior": control}.items():
        (work / f"{name}.sv").write_text(source)
        record = {"id": row["id"], "completion": "```systemverilog\n" + source + "```"}
        (work / f"{name}.jsonl").write_text(json.dumps(record) + "\n")


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
