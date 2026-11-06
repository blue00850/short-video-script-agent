"""CLI-level tests: exit codes, files, and invalid input handling."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from src.cli import main


class CliTests(unittest.TestCase):
    def test_normal_run_writes_result_and_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            trace = Path(tmp) / "trace.jsonl"
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = main(
                    [
                        "--provider",
                        "mock",
                        "--mock-scenario",
                        "normal",
                        "--topic",
                        "小影一键成片",
                        "--platform",
                        "抖音",
                        "--target-seconds",
                        "30",
                        "--product-id",
                        "P02",
                        "--out",
                        str(out),
                        "--trace",
                        str(trace),
                    ]
                )
            self.assertEqual(0, code)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("completed", result["status"])
            self.assertTrue(trace.exists())
            self.assertIn("status: completed", stdout.getvalue())

    def test_missing_platform_is_invalid_input_with_exit_5(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            input_path.write_text(
                json.dumps(
                    {"topic": "小影字幕", "audience": "创作者", "target_seconds": 30},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            out = Path(tmp) / "result.json"
            trace = Path(tmp) / "trace.jsonl"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--provider",
                        "mock",
                        "--input",
                        str(input_path),
                        "--out",
                        str(out),
                        "--trace",
                        str(trace),
                    ]
                )
            self.assertEqual(5, code)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("invalid_input", result["status"])
            self.assertEqual("platform", result["output"]["errors"][0]["field"])
            events = [
                json.loads(line)
                for line in trace.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual("validation_error", events[0]["event"])

    def test_step_limit_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            trace = Path(tmp) / "trace.jsonl"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--provider",
                        "mock",
                        "--mock-scenario",
                        "step_limit",
                        "--topic",
                        "小影一键成片",
                        "--platform",
                        "抖音",
                        "--target-seconds",
                        "30",
                        "--product-id",
                        "P02",
                        "--max-steps",
                        "2",
                        "--out",
                        str(out),
                        "--trace",
                        str(trace),
                    ]
                )
            self.assertEqual(4, code)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("step_limit_reached", result["status"])

    def test_unknown_fault_is_rejected_before_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                code = main(
                    [
                        "--provider",
                        "mock",
                        "--topic",
                        "x",
                        "--platform",
                        "抖音",
                        "--target-seconds",
                        "30",
                        "--fault",
                        "nope=timeout",
                        "--out",
                        str(Path(tmp) / "result.json"),
                        "--trace",
                        str(Path(tmp) / "trace.jsonl"),
                    ]
                )
            self.assertEqual(3, code)


if __name__ == "__main__":
    unittest.main()
