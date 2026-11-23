# jsonl-eval

A small, dependency-free Python CLI for comparing two evaluation runs by case ID.
It shows score changes, pass-to-fail regressions, and differences in case coverage.
It does not run a model or decide whether a score should count as passing.

## Quick start

Use Python 3.10 or newer from the repository root. No installation is required.

```sh
python jsonl_eval.py examples/baseline.jsonl examples/candidate.jsonl
python jsonl_eval.py examples/baseline.jsonl examples/candidate.jsonl --format json
python -m unittest discover -s tests -v
```

The example deliberately exits with status `1`: `citations` goes from `0.95`
to `0.75` (`-0.2`) and changes from pass to fail. `formatting` recovers.
`long-context` exists only in the baseline and `new-language` only in the
candidate; neither is treated as a matched case.

## Input and output

Each nonblank line of a UTF-8 file must be a JSON object:

```json
{"case_id":"example-001","score":0.82,"passed":true}
```

- `case_id` must be a nonblank string and unique within its file. IDs are
  case-sensitive and matched literally.
- `score` must be a finite JSON number, not a string or a boolean. The tool
  does not impose a score range. To bound fixed-point expansion, scores may have
  at most 1,000 coefficient digits and a decimal exponent from −1,000 to 1,000.
- `passed` must be the JSON boolean `true` or `false`. Extra fields are
  ignored; duplicate JSON keys are rejected.
- The order of input lines is immaterial. Both output formats show sorted IDs.
  JSON output has a `schema_version`, summary counts, unmatched IDs,
  regression and recovery IDs, and per-case scores and deltas. Score fields
  are decimal strings to preserve exact values, including differences such as
  `0.3 - 0.2 = 0.1`, in consumers that otherwise parse numbers as floats.
- Both complete runs are held in memory. An empty file is a valid empty run.
  Compare only runs that use the same scoring definition and comparable inputs.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | No pass-to-fail regressions and no strict coverage failure. |
| `1` | At least one pass-to-fail regression, or the case sets differ and `--require-same-cases` was set. The report is still written to stdout. |
| `2` | Invalid CLI arguments, unreadable input, or malformed run data. No report is written; the error is sent to stderr. |

A score decrease without a pass-to-fail transition is reported as a decrease,
but is not a regression for exit-code purposes. Use `--require-same-cases`
in CI if omitted cases should not silently pass the gate.

## Provenance

This is an original, AI-assisted portfolio example. The runs in `examples/`
are synthetic and contain no employer, customer, or production data.
