import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from jsonl_eval import Case, RunError, compare, load_run


ROOT = Path(__file__).resolve().parents[1]


class LoadRunTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.jsonl"
            path.write_bytes(data)
            return load_run(path)

    def test_blank_lines_extra_fields_and_decimal(self):
        run = self.load(
            b'\n {"case_id":"a","score":0.1234567890123456789,"passed":false,"annotation":1}\n'
        )
        self.assertEqual(run, {"a": Case(Decimal("0.1234567890123456789"), False)})
        self.assertEqual(self.load(b"\n"), {})

    def test_duplicate_case_reports_actual_line(self):
        line = b'{"case_id":"a","score":1,"passed":true}\n'
        with self.assertRaisesRegex(RunError, r'run\.jsonl:3: duplicate case_id "a"'):
            self.load(line + b"\n" + line)

    def test_invalid_lines(self):
        cases = [
            (b"[1]", "expected a JSON object"),
            (b"{broken}", "Expecting property name"),
            (b'{"case_id":" ", "score":1, "passed":true}', "case_id"),
            (b'{"case_id":"a", "score":true, "passed":true}', "finite JSON number"),
            (b'{"case_id":"a", "score":"1", "passed":true}', "finite JSON number"),
            (b'{"case_id":"a", "score":1, "passed":1}', "JSON boolean"),
            (b'{"case_id":"a", "score":1}', "JSON boolean"),
            (b'{"case_id":"a", "score":NaN, "passed":true}', "not a JSON number"),
            (b'{"case_id":"a", "score":Infinity, "passed":true}', "not a JSON number"),
            (b'{"case_id":"a", "score":1e1001, "passed":true}', "coefficient digits"),
            (b'{"case_id":"a", "score":1, "score":2, "passed":true}', "duplicate JSON key"),
            (bytes([255]), "utf-8"),
        ]
        for data, reason in cases:
            with self.subTest(data=data), self.assertRaisesRegex(RunError, reason):
                self.load(data)


class CompareTests(unittest.TestCase):
    def test_outcomes_are_independent_of_scores(self):
        def c(score, passed):
            return Case(Decimal(score), passed)

        report = compare(
            {"z": c("0.2", True), "a": c("0.3", False), "b": c("0.2", True),
             "n": c("-0", True), "old": c("1", True)},
            {"z": c("0.3", False), "a": c("0.2", True), "b": c("0.1", True),
             "n": c("0.00", True), "new": c("1", True)},
        )
        self.assertEqual([x["case_id"] for x in report["cases"]], ["a", "b", "n", "z"])
        self.assertEqual([x["delta"] for x in report["cases"]], ["-0.1", "-0.1", "0", "0.1"])
        self.assertEqual(report["regressions"], ["z"])
        self.assertEqual(report["recoveries"], ["a"])
        self.assertEqual(report["baseline_only"], ["old"])
        self.assertEqual(report["candidate_only"], ["new"])

    def test_delta_is_exact_beyond_decimal_default_precision(self):
        before = Case(Decimal("1e1000"), True)
        after = Case(Decimal("1e-1000"), True)
        delta = compare({"x": before}, {"x": after})["cases"][0]["delta"]
        self.assertEqual(delta, "-" + "9" * 1000 + "." + "9" * 1000)


class CLITests(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "jsonl_eval.py"), *map(str, args)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def test_exit_one_with_human_and_stable_json_reports(self):
        base = ROOT / "examples/baseline.jsonl"
        candidate = ROOT / "examples/candidate.jsonl"
        human = self.invoke(base, candidate)
        self.assertEqual(human.returncode, 1)
        self.assertIn('"citations"  |  0.95 -> 0.75  |  -0.2  |  PASS -> FAIL', human.stdout)
        report = self.invoke(base, candidate, "--format", "json")
        self.assertEqual(report.returncode, 1)
        self.assertEqual(report.stderr, "")
        self.assertEqual(json.loads(report.stdout)["schema_version"], 1)
        with tempfile.TemporaryDirectory() as directory:
            reordered = Path(directory) / "reordered.jsonl"
            reordered.write_text("\n".join(reversed(candidate.read_text().splitlines())))
            self.assertEqual(self.invoke(base, reordered, "--format", "json").stdout, report.stdout)

    def test_no_regression_exit_zero_and_strict_coverage_exit_one(self):
        base = ROOT / "examples/baseline.jsonl"
        self.assertEqual(self.invoke(base, base, "--require-same-cases").returncode, 0)
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.jsonl"
            empty.write_text("")
            self.assertEqual(self.invoke(base, empty).returncode, 0)
            self.assertEqual(self.invoke(base, empty, "--require-same-cases").returncode, 1)

    def test_missing_file_exits_two_and_writes_only_error(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.jsonl"
            result = self.invoke(missing, missing, "--format", "json")
            self.assertEqual(result.returncode, 2)
            self.assertIn("missing.jsonl", result.stderr)
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
