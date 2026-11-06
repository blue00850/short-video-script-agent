"""Regenerate every example with the deterministic Mock provider.

This is the reviewer-facing reproduction script. It calls the real CLI entry
point, so the stored output files are produced by the same code path a user
would run. It is NOT evidence of real-model decision quality; see
examples/real/ for that.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]

CASES: List[Dict[str, Any]] = [
    {
        "name": "normal",
        "scenario": "normal",
        "expected": "completed",
        "extra": [],
    },
    {
        "name": "p01_30s",
        "scenario": "p01_30s",
        "expected": "completed",
        "extra": [],
    },
    {
        "name": "no_material",
        "scenario": "no_material",
        "expected": "insufficient_evidence",
        "extra": [],
    },
    {
        "name": "tool_failure",
        "scenario": "tool_failure",
        "expected": "completed",
        "extra": ["--fault", "search_materials=timeout"],
    },
    {
        "name": "impossible",
        "scenario": "impossible",
        "expected": "cannot_satisfy",
        "extra": [],
    },
    {
        "name": "rule_violation",
        "scenario": "rule_violation",
        "expected": "completed",
        "extra": [],
    },
    {
        "name": "semantic_catch",
        "scenario": "semantic_catch",
        "expected": "completed",
        "extra": [],
    },
    {
        "name": "step_limit",
        "scenario": "step_limit",
        "expected": "step_limit_reached",
        "extra": ["--max-steps", "2"],
    },
    {
        "name": "missing",
        "scenario": "normal",
        "expected": "invalid_input",
        "extra": [],
    },
]


def run_case(case: Dict[str, Any]) -> Dict[str, Any]:
    name = case["name"]
    case_dir = ROOT / "examples" / name
    out = case_dir / "output.json"
    trace = case_dir / "trace.jsonl"
    command = [
        sys.executable,
        "-m",
        "src.cli",
        "--provider",
        "mock",
        "--mock-scenario",
        case["scenario"],
        "--input",
        str(case_dir / "input.json"),
        "--out",
        str(out),
        "--trace",
        str(trace),
    ] + case["extra"]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if not out.exists():
        raise RuntimeError("%s: CLI 未生成 output.json\n%s\n%s" % (name, proc.stdout, proc.stderr))
    result = json.loads(out.read_text(encoding="utf-8"))
    actual = result.get("status")
    if actual != case["expected"]:
        raise AssertionError(
            "%s: 期望 %s，实际 %s\nstdout=%s\nstderr=%s"
            % (name, case["expected"], actual, proc.stdout, proc.stderr)
        )
    return {
        "case": name,
        "status": actual,
        "exit_code": proc.returncode,
        "seconds": (result.get("output") or {}).get("estimated_total_seconds"),
        "trace": str(trace.relative_to(ROOT)),
    }


def main() -> int:
    rows = []
    for case in CASES:
        rows.append(run_case(case))
    print("%-16s %-22s %-6s %-8s %s" % ("case", "status", "exit", "seconds", "trace"))
    for row in rows:
        print(
            "%-16s %-22s %-6s %-8s %s"
            % (
                row["case"],
                row["status"],
                row["exit_code"],
                row["seconds"] if row["seconds"] is not None else "-",
                row["trace"],
            )
        )
    print("\n%d/%d examples regenerated." % (len(rows), len(CASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
