"""Compare two evaluation runs without floating-point rounding."""

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path


# Bounding input scale and precision keeps fixed-point rendering predictable.
SCORE_LIMIT = 1000


class RunError(ValueError):
    """The run cannot be read or contains invalid input."""


@dataclass(frozen=True)
class Case:
    score: Decimal
    passed: bool


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {json.dumps(key)}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"{value} is not a JSON number")


def load_run(path: Path) -> dict[str, Case]:
    """Read one JSON object per nonblank UTF-8 line, with line diagnostics."""
    run: dict[str, Case] = {}
    try:
        with path.open("rb") as stream:
            for number, raw in enumerate(stream, 1):
                try:
                    line = raw.decode("utf-8")
                    if not line.strip():
                        continue
                    value = json.loads(
                        line,
                        parse_float=Decimal,
                        parse_int=Decimal,
                        parse_constant=reject_constant,
                        object_pairs_hook=unique_object,
                    )
                    if not isinstance(value, dict):
                        raise ValueError("expected a JSON object")
                    case_id = value.get("case_id")
                    score = value.get("score")
                    passed = value.get("passed")
                    if not isinstance(case_id, str) or not case_id.strip():
                        raise ValueError("case_id must be a nonblank string")
                    if not isinstance(score, Decimal):
                        raise ValueError("score must be a finite JSON number")
                    digits = score.as_tuple()
                    if len(digits.digits) > SCORE_LIMIT or abs(digits.exponent) > SCORE_LIMIT:
                        raise ValueError(
                            f"score must have at most {SCORE_LIMIT} coefficient digits "
                            f"and an exponent between -{SCORE_LIMIT} and {SCORE_LIMIT}"
                        )
                    if not isinstance(passed, bool):
                        raise ValueError("passed must be a JSON boolean")
                    if case_id in run:
                        raise ValueError(f"duplicate case_id {json.dumps(case_id)}")
                    run[case_id] = Case(score, passed)
                except (ValueError, ArithmeticError, RecursionError) as error:
                    raise RunError(f"{path}:{number}: {error}") from error
    except OSError as error:
        raise RunError(f"{path}: {error.strerror or error}") from error
    return run


def decimal_text(value: Decimal) -> str:
    """Canonical, exact decimal string; unify signed zero and trailing zeros."""
    if not value:
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def compare(baseline: dict[str, Case], candidate: dict[str, Case]) -> dict:
    rows, regressions, recoveries = [], [], []
    rises, drops = 0, 0
    # In the worst case, align scores at exponents +1000 and -1000,
    # retain all 1000 coefficient digits, and allow another digit for carry.
    with localcontext() as context:
        context.prec = 3 * SCORE_LIMIT + 2
        for case_id in sorted(baseline.keys() & candidate.keys()):
            before, after = baseline[case_id], candidate[case_id]
            delta = after.score - before.score
            rises += delta > 0
            drops += delta < 0
            if before.passed and not after.passed:
                regressions.append(case_id)
            elif not before.passed and after.passed:
                recoveries.append(case_id)
            rows.append({
                "case_id": case_id,
                "baseline_score": decimal_text(before.score),
                "candidate_score": decimal_text(after.score),
                "delta": decimal_text(delta),
                "baseline_passed": before.passed,
                "candidate_passed": after.passed,
            })
    baseline_only = sorted(baseline.keys() - candidate.keys())
    candidate_only = sorted(candidate.keys() - baseline.keys())
    return {
        "schema_version": 1,
        "summary": {
            "baseline_cases": len(baseline),
            "candidate_cases": len(candidate),
            "matched_cases": len(rows),
            "baseline_only_cases": len(baseline_only),
            "candidate_only_cases": len(candidate_only),
            "score_increased": rises,
            "score_decreased": drops,
            "score_unchanged": len(rows) - rises - drops,
            "pass_to_fail": len(regressions),
            "fail_to_pass": len(recoveries),
        },
        "baseline_only": baseline_only,
        "candidate_only": candidate_only,
        "regressions": regressions,
        "recoveries": recoveries,
        "cases": rows,
    }


def human_report(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"Matched: {s['matched_cases']} | Baseline: {s['baseline_cases']} | Candidate: {s['candidate_cases']}",
        f"Scores: {s['score_increased']} up, {s['score_decreased']} down, {s['score_unchanged']} unchanged",
        f"Outcomes: {s['pass_to_fail']} pass -> fail, {s['fail_to_pass']} fail -> pass",
    ]
    for key, label in (
        ("regressions", "Regressions"), ("recoveries", "Recoveries"),
        ("baseline_only", "Baseline only"), ("candidate_only", "Candidate only"),
    ):
        lines.append(f"{label}: {json.dumps(report[key])}")
    if report["cases"]:
        lines.extend(("", "Case  |  Baseline score -> Candidate score  |  Delta  |  Outcome"))
        for case in report["cases"]:
            before = "PASS" if case["baseline_passed"] else "FAIL"
            after = "PASS" if case["candidate_passed"] else "FAIL"
            delta = case["delta"]
            if delta != "0" and not delta.startswith("-"):
                delta = "+" + delta
            lines.append(
                f"{json.dumps(case['case_id'])}  |  {case['baseline_score']} -> "
                f"{case['candidate_score']}  |  {delta}  |  {before} -> {after}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="baseline JSONL run")
    parser.add_argument("candidate", type=Path, help="candidate JSONL run")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--require-same-cases", action="store_true",
        help="also fail if IDs are missing or added",
    )
    args = parser.parse_args(argv)
    try:
        report = compare(load_run(args.baseline), load_run(args.candidate))
    except RunError as error:
        print(f"jsonl-eval: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(report, sort_keys=True, indent=2)
        if args.format == "json"
        else human_report(report)
    )
    coverage_changed = bool(report["baseline_only"] or report["candidate_only"])
    return int(bool(report["regressions"]) or (args.require_same_cases and coverage_changed))


if __name__ == "__main__":
    raise SystemExit(main())
