"""Independent public development checks for the two trusted D2 RTL fixtures."""

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import tempfile

from study_common import SIM

DEFAULT_SEED = 20261122
MASK32 = (1 << 32) - 1
MASK64 = (1 << 64) - 1
SAMPLES = 4096


def adder_vectors(seed):
    rng = random.Random(seed)
    edge = (0, 1, 0x7fffffff, 0x80000000, MASK32, 0x55555555, 0xaaaaaaaa)
    for a in edge:
        for b in edge:
            for cin in (0, 1):
                yield "boundary", a, b, cin
    for width in range(1, 33):
        low = (1 << width) - 1
        yield "carry_chain", low, 0, 1
        yield "carry_chain", 0, low, 1
        yield "carry_chain", low, 1, 0
        yield "carry_chain", 1, low, 0
    for _ in range(SAMPLES):
        a, b = rng.getrandbits(32), rng.getrandbits(32)
        for cin in (0, 1):
            yield "seeded", a, b, cin


def adder_bench(seed):
    pairs = list(adder_vectors(seed))
    labels = [group for group, *_ in pairs]
    vectors = "\n".join(
        f"  check({index}, 32'h{a:08x}, 32'h{b:08x}, 1'b{cin}, 33'h{a + b + cin:09x});"
        for index, (_, a, b, cin) in enumerate(pairs)
    )
    return labels, f"""\
`timescale 1ns/1ps
module d2_tb;
  logic [31:0] a, b;
  logic cin;
  wire [31:0] sum;
  wire cout;
  brent_kung_adder dut (.a(a), .b(b), .carry_in(cin), .sum(sum), .carry_out(cout));
  task check(input integer n, input logic [31:0] x, y,
             input logic c, input logic [32:0] expected);
    a = x; b = y; cin = c;
    #2;
    $display("D2 %0d %0d %0d", n, sum !== expected[31:0], cout !== expected[32]);
  endtask
  initial begin
    if ($bits(dut.a) != 32 || $bits(dut.b) != 32 || $bits(dut.carry_in) != 1 ||
        $bits(dut.sum) != 32 || $bits(dut.carry_out) != 1) begin
      $display("D2_INTERFACE");
      $finish;
    end
{vectors}
    $display("D2_DONE");
    $finish;
  end
endmodule
"""


def encoder_vectors(seed):
    # Expected output follows state across drives, including times without edges.
    rng = random.Random(seed)
    clock = reset = 0
    data, control = 0, 0
    output = None

    def step(group, *, clk=None, rst=None, word=None, mask=None):
        nonlocal clock, reset, data, control, output
        new_clock = clock if clk is None else clk
        new_reset = reset if rst is None else rst
        data = data if word is None else word
        control = control if mask is None else mask
        if (clock == 0 and new_clock == 1) or (reset == 0 and new_reset == 1):
            if new_reset:
                output = 0
            elif control:
                output = 2 << 64
            else:
                output = (1 << 64) | data
        clock, reset = new_clock, new_reset
        if output is None:
            raise ValueError("encoder stimulus used before initial reset")
        return group, clock, reset, data, control, output

    yield step("async_assert_low", rst=1)
    yield step("reset_priority", clk=1, word=MASK64, mask=0x81)
    yield step("reset_release_hold", rst=0)
    yield step("between_edges_hold", clk=0, word=0x123456789abcdef0, mask=0)
    yield step("data_capture", clk=1)
    yield step("between_edges_hold", word=0, mask=0xff)
    yield step("async_assert_high", rst=1)
    yield step("reset_release_hold", rst=0)
    yield step("between_edges_hold", clk=0, word=MASK64, mask=0)
    yield step("data_capture", clk=1)
    yield step("between_edges_hold", clk=0)
    yield step("async_assert_low", rst=1)
    yield step("reset_release_hold", rst=0)
    for mask in range(256):
        word = (0x0123456789abcdef ^ (mask << 48)) & MASK64
        # Prime with nonzero data to distinguish clearing from retained payload.
        yield step("between_edges_hold", clk=0, mask=0, word=word)
        yield step("data_capture", clk=1)
        yield step("between_edges_hold", clk=0, mask=mask, word=word ^ MASK64)
        yield step("control_masks" if mask else "data_capture", clk=1)
    for _ in range(128):
        mask = rng.choice((0, rng.randrange(1, 256)))
        yield step("between_edges_hold", clk=0, mask=mask, word=rng.getrandbits(64))
        yield step("seeded_transitions", clk=1)


def encoder_bench(seed):
    events = list(encoder_vectors(seed))
    labels = [group for group, *_ in events]
    vectors = "\n".join(
        f"  check({i}, 1'b{clk}, 1'b{rst}, 64'h{data:016x}, 8'h{mask:02x}, 66'h{out:017x});"
        for i, (_, clk, rst, data, mask, out) in enumerate(events)
    )
    return labels, f"""\
`timescale 1ns/1ps
module d2_tb;
  logic clock = 0, reset = 0;
  logic [63:0] data = 0;
  logic [7:0] mask = 0;
  wire [65:0] encoded;
  encoder_64b66b dut (.clk_in(clock), .rst_in(reset), .encoder_data_in(data),
                     .encoder_control_in(mask), .encoder_data_out(encoded));
  task check(input integer n, input logic c, r, input logic [63:0] d,
             input logic [7:0] m, input logic [65:0] expected);
    #2;
    data = d; mask = m; reset = r; clock = c;
    #2;
    $display("D2 %0d %0d %0d", n,
             encoded[63:0] !== expected[63:0], encoded[65:64] !== expected[65:64]);
  endtask
  initial begin
    if ($bits(dut.clk_in) != 1 || $bits(dut.rst_in) != 1 ||
        $bits(dut.encoder_data_in) != 64 || $bits(dut.encoder_control_in) != 8 ||
        $bits(dut.encoder_data_out) != 66) begin
      $display("D2_INTERFACE");
      $finish;
    end
{vectors}
    $display("D2_DONE");
    $finish;
  end
endmodule
"""


TASKS = {"adder": (adder_bench, "sum", "carry"),
         "encoder": (encoder_bench, "payload", "header")}


def executable(name):
    path = SIM / name
    if path.is_file():
        return path
    found = shutil.which(name)
    if not found:
        raise FileNotFoundError(f"{name} is required")
    return Path(found).resolve()


def score_candidate(task, source, seed, work):
    generate, low, high = TASKS[task]
    work.mkdir(mode=0o700)
    # Both verifiers work from frozen candidate bytes; reject unsupported
    # host I/O consistently with the CVDP native replay used in this study.
    candidate = source.read_bytes()
    unsupported = (b"```", b"$system", b"$fopen", b"$readmem", b"$writemem", b"`include")
    if any(token in candidate for token in unsupported):
        return {"verdict": "unsupported_candidate", "groups": None}
    (work / "candidate.sv").write_bytes(candidate)
    labels, bench = generate(seed)
    bench_bytes = bench.encode()
    (work / "bench.sv").write_bytes(bench_bytes)
    result = {"verdict": None, "groups": None,
              "stimulus_sha256": hashlib.sha256(bench_bytes).hexdigest()}
    env = {"PATH": "/usr/bin:/bin", "HOME": str(work.resolve()), "LANG": "C"}
    stages = {"compile": [str(executable("iverilog")), "-g2012", "-s", "d2_tb",
                          "-o", "sim", "candidate.sv", "bench.sv"],
              "simulate": [str(executable("vvp")), "sim"]}
    for stage, command in stages.items():
        try:
            with (work / f"{stage}.log").open("wb") as log:
                output = subprocess.run(command, cwd=work, env=env, stdout=log,
                                        stderr=subprocess.STDOUT, timeout=30)
        except subprocess.TimeoutExpired:
            return {**result, "verdict": f"{stage}_timeout"}
        if output.returncode:
            return {**result, "verdict": f"{stage}_error"}

    lines = (work / "simulate.log").read_text().splitlines()
    if "D2_INTERFACE" in lines:
        return {**result, "verdict": "interface_mismatch"}
    rows = [re.fullmatch(r"D2 (\d+) ([01]) ([01])", line)
            for line in lines if line.startswith("D2 ")]
    if (lines.count("D2_DONE") != 1 or len(rows) != len(labels)
            or any(row is None or int(row[1]) != i for i, row in enumerate(rows))):
        return {**result, "verdict": "incomplete"}
    groups = defaultdict(lambda: {"checks": 0, f"{low}_errors": 0, f"{high}_errors": 0})
    first_failure = None
    for i, (label, row) in enumerate(zip(labels, rows)):
        groups[label]["checks"] += 1
        groups[label][f"{low}_errors"] += int(row[2])
        groups[label][f"{high}_errors"] += int(row[3])
        if first_failure is None and (row[2] == "1" or row[3] == "1"):
            first_failure = {"index": i, "check": label, low: bool(int(row[2])), high: bool(int(row[3]))}
    return {**result, "verdict": "functional" if first_failure else "pass",
            "groups": dict(groups), "first_failure": first_failure}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=TASKS)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="rtl-d2-") as tmp:
        result = score_candidate(args.task, args.candidate, args.seed, Path(tmp) / "run")
    print(json.dumps(result, indent=2))
    return {"pass": 0, "functional": 1}.get(result["verdict"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
