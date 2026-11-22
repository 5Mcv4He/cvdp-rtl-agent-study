"""Check a Brent–Kung candidate against independent 33-bit addition."""
import argparse
import json
from pathlib import Path
import random
import re
import subprocess
import tempfile

from study_common import LOCAL, SIM


def arithmetic_check(source):
    rng = random.Random(20261122)
    mask = (1 << 32) - 1
    # Explicit carry chains and a seeded sample model different input distributions.
    edge = [(mask >> i, 1, 0) for i in range(32)]
    random_sample = [(rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(1))
                     for _ in range(4096)]
    vectors = edge + random_sample
    calls = "\n".join(f"check(32'h{a:08x},32'h{b:08x},1'b{cin});" for a, b, cin in vectors)
    with tempfile.TemporaryDirectory(prefix="adder-check-", dir=LOCAL) as directory:
        work = Path(directory)
        tb = work / "tb.sv"
        tb.write_text("""module tb;
  logic [31:0] a,b;
  logic carry_in;
  wire [31:0] sum;
  wire carry_out;
  integer errors = 0;
  brent_kung_adder dut (a,b,carry_in,sum,carry_out);
  task check(input logic [31:0] x,y,input logic cin);
    logic [32:0] wanted;
    begin
      a=x; b=y; carry_in=cin;
      wanted={1'b0,x}+{1'b0,y}+{32'b0,cin};
      #1;
      if ({carry_out,sum} !== wanted) errors=errors+1;
    end
  endtask
  initial begin
""" + calls + """
    $display("MISMATCHES=%0d",errors);
    $finish;
  end
endmodule
""")
        env = {"PATH": f"{SIM}:/usr/bin:/bin"}
        subprocess.run([str(SIM / "iverilog"), "-g2012", "-s", "tb", "-o", "sim", str(source.resolve()), "tb.sv"],
                       cwd=work, env=env, timeout=30, check=True)
        run = subprocess.run([str(SIM / "vvp"), "sim"], cwd=work, env=env, timeout=30, check=True,
                             text=True, capture_output=True)
        matched = re.search(r"^MISMATCHES=(\d+)$", run.stdout, re.MULTILINE)
        if matched is None:
            raise ValueError("simulation did not finish the arithmetic checker")
        return {"vectors": len(vectors), "mismatches": int(matched[1])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    print(json.dumps(arithmetic_check(parser.parse_args().candidate)))
