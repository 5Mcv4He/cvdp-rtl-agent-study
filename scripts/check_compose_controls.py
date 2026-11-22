"""Report only verified control outcomes from the official CVDP CLI."""
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1]).resolve()
for variant, expected_pass, minimum_tests in (
    ("golden", True, 3), ("original", False, 1), ("behavior", True, 1),
):
    work = root / variant
    records = json.loads((work / "raw_result.json").read_text())
    task, = records.values()
    service, = task["tests"]
    service_report = Path(service["log"]).read_text()
    match = re.search(r"TESTS=(\d+) PASS=(\d+) FAIL=(\d+) SKIP=(\d+)", service_report)
    if match is None:
        raise ValueError(f"{variant}: the simulator did not execute cocotb tests")
    tests, passed, failed, skipped = map(int, match.groups())
    if tests < minimum_tests or skipped or (task["errors"] == 0) != expected_pass:
        raise ValueError(f"{variant}: unexpected outcome ({tests=}, {passed=}, {failed=}, {skipped=})")
    if expected_pass and passed != tests:
        raise ValueError(f"{variant}: expected all checks to pass")
    if variant != "golden":
        scored, = work.glob("*/harness/1/rtl/brent_kung_adder.sv")
        if scored.read_bytes() != (root / f"{variant}.sv").read_bytes():
            raise ValueError(f"{variant}: scored bytes differ from input")
    if variant == "original" and "Carry Out Mismatch: Expected 0, Got 1" not in service_report:
        raise ValueError("expected the original RTL to fail the known carry assertion")
    print(json.dumps({
        "case": variant, "verdict": "pass" if expected_pass else "functional",
        "tests": tests, "failed": failed,
    }), flush=True)
