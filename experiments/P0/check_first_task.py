"""Read-only audit of the locked P1 example. No dataset code is executed."""
import ast
import hashlib
import json
from pathlib import Path


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def audit():
    here = Path(__file__).resolve().parent
    lock = json.loads((here / "lock.json").read_text())
    dataset = lock["dataset"]
    task = lock["first_task"]
    raw = (here.parents[1] / ".local/data" / dataset["file"]).read_bytes()
    if sha256(raw) != dataset["sha256"]:
        raise ValueError("Dataset SHA-256 differs from lock")
    lines = raw.splitlines()
    line = lines[task["line_1based"] - 1]
    row = json.loads(line)
    if sha256(line) != task["row_sha256_without_newline"] or row["id"] != task["id"]:
        raise ValueError("Task differs from lock")

    public_vectors = []
    for line in row["input"]["prompt"].splitlines():
        cells = [item.strip() for item in line.strip().strip("|").split("|")]
        if len(cells) == 8 and cells[0].isdigit():
            public_vectors.append(tuple(int(cells[i], 16) for i in (1, 2, 3, 4, 6)))

    test_path = "src/test_brent_kung_adder.py"
    tree = ast.parse(row["harness"]["files"][test_path])
    assignments = {
        target.id: node.value
        for node in ast.walk(tree) if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
    }
    fixed = [v[:5] for v in ast.literal_eval(assignments["test_vectors"])]
    random_loop = next(
        n for n in ast.walk(tree) if isinstance(n, ast.For)
        and ast.unparse(n.iter) == "range(num_random_tests)"
    )
    debug = [r for r in map(json.loads, lines) if "cid016" in r["categories"]]
    return {
        "evidence": "static dataset inspection",
        "task_id": row["id"],
        "dataset_sha256": sha256(raw),
        "dataset_rows": len(lines),
        "cid016_rows": len(debug),
        "cid016_rows_with_reference_content": sum(
            bool(r["output"]["response"] or any(r["output"]["context"].values())) for r in debug
        ),
        "public_fixed_vectors": len(public_vectors),
        "checker_fixed_vectors": len(fixed),
        "identical_vectors_in_identical_order": public_vectors == fixed,
        "arithmetically_correct_fixed_expectations": sum(
            a + b + cin == (cout << 32) + result for a, b, cin, result, cout in fixed
        ),
        "random_vectors_in_source": ast.literal_eval(assignments["num_random_tests"]),
        "assert_statements_in_random_loop": sum(isinstance(n, ast.Assert) for n in ast.walk(random_loop)),
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
