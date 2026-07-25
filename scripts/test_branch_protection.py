#!/usr/bin/env python3
"""Unit tests for the branch-protection drift guard (ADR-0003, issue #53).

Zero-dependency: runnable directly as ``python3 scripts/test_branch_protection.py``.
Exits non-zero on any failure. Covers the guard **through its own interface**
(``scripts/branch_protection.py``) — the pure drift logic (job-name parsing +
the contexts↔jobs matching) needs no network and no ``GITHUB_TOKEN``; the
GitHub REST fetch is exercised only via the ``contexts`` injection seam, so
the composition is testable without leaving the machine.

Scope: the 1:1 mapping between required status-check contexts and workflow job
names — the invariant the guard exists to assert. Network/token behavior
(graceful skip on 404/403/401) is a transport concern, not asserted here.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import branch_protection as bp  # noqa: E402


def _check(condition: bool, label: str, failed: list[str]) -> None:
    if not condition:
        print(f"  FAIL {label}")
        failed.append(label)


def _write_workflow(dir_: Path, name: str, body: str) -> None:
    (dir_ / name).write_text(body, encoding="utf-8")


def main() -> int:
    failed: list[str] = []

    # =========================================================================
    # workflow_job_names: parse top-level job names from a jobs: block
    # =========================================================================
    print("workflow_job_names (parse job names from *.yml):")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        _write_workflow(wf, "validate-skills.yml", """\
name: validate-skills
on: [pull_request]
jobs:
  validate-skills:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
  lint-extra:
    runs-on: ubuntu-latest
    steps:
      - run: echo bye
""")
        _write_workflow(wf, "review-verdict.yml", """\
name: review-verdict
on: [pull_request]
jobs:
  review-verdict:
    runs-on: ubuntu-latest
""")
        names = bp.workflow_job_names(wf)
        _check(names == {"validate-skills", "lint-extra", "review-verdict"},
               f"parses job names across files (got {sorted(names)})", failed)
        # A step line (``- run``) is one level deeper than the job name; it must
        # NOT be collected as a job.
        _check("run" not in names and "steps" not in names,
               "step keys are not collected as jobs", failed)

    # An absent workflows dir yields an empty set (not an error).
    _check(bp.workflow_job_names(Path("/nonexistent/path")) == set(),
           "absent workflows dir -> empty set", failed)

    # A workflow with NO jobs: block yields nothing for that file.
    with tempfile.TemporaryDirectory() as tmp:
        wf = Path(tmp) / ".github" / "workflows"
        wf.mkdir(parents=True)
        _write_workflow(wf, "none.yml", "name: none\non: [push]\n")
        _check(bp.workflow_job_names(wf) == set(),
               "workflow without jobs: -> empty", failed)

    # =========================================================================
    # missing_job_errors: each unmatched context -> one stable error
    # =========================================================================
    print("missing_job_errors (contexts <-> jobs matching):")
    _check(bp.missing_job_errors([], {"a"}) == [],
           "no contexts -> no errors", failed)
    _check(
        bp.missing_job_errors(["validate-skills", "review-verdict"],
                              {"validate-skills", "review-verdict"}) == [],
        "all contexts present -> no errors",
        failed,
    )
    errs = bp.missing_job_errors(["validate-skills", "bogus"],
                                 {"validate-skills"})
    _check(len(errs) == 1, "one missing context -> one error", failed)
    # The error NAMES the missing context ('bogus'); the present job surfaces
    # only inside the (found: [...]) list — both are legitimate.
    _check(
        errs and "requires context 'bogus'" in errs[0],
        "the error names the missing context ('bogus')",
        failed,
    )
    # The found list is sorted + stable (ADR-0003 contexts<->jobs mapping).
    _check(
        errs and "found: ['validate-skills']" in errs[0],
        "the error reports the sorted discovered jobs",
        failed,
    )
    errs2 = bp.missing_job_errors(["a", "b", "c"], set())
    _check(len(errs2) == 3, "all contexts missing -> one error each", failed)

    # =========================================================================
    # drift_errors: composition, tested via the contexts injection seam
    # =========================================================================
    print("drift_errors (composition via injected contexts, no network):")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        _write_workflow(wf, "validate-skills.yml", "jobs:\n  validate-skills:\n")

        # Clean: every injected context has a matching job.
        _check(
            bp.drift_errors(root, contexts=["validate-skills"]) == [],
            "all contexts matched -> no drift errors",
            failed,
        )
        # Drift: an injected context with no job.
        drift = bp.drift_errors(root, contexts=["validate-skills", "review-verdict"])
        _check(len(drift) == 1 and "review-verdict" in drift[0],
               "missing context surfaces as a drift error", failed)
        # Empty contexts (the unauthenticated/no-protection path) -> skip the
        # per-context check gracefully (jobs exist, so no structural error).
        _check(
            bp.drift_errors(root, contexts=[]) == [],
            "empty contexts -> graceful skip (no structural error when jobs exist)",
            failed,
        )

    # Structural error: workflows dir has no jobs at all.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)  # no .github/workflows
        structural = bp.drift_errors(root, contexts=["validate-skills"])
        _check(
            any("no workflow job names found" in e for e in structural),
            "no jobs discoverable -> structural error regardless of contexts",
            failed,
        )

    # =========================================================================
    # drift_info: orphan jobs (not required) -> a non-failing note
    # =========================================================================
    print("drift_info (orphan jobs -> non-failing note):")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        _write_workflow(wf, "x.yml", "jobs:\n  validate-skills:\n  extra-job:\n")
        info = bp.drift_info(root, contexts=["validate-skills"])
        _check(len(info) == 1 and "extra-job" in info[0],
               "an orphan job (not required) is flagged as a note", failed)
        _check(
            "not required by branch protection" in (info[0] if info else ""),
            "the note explains it is not required",
            failed,
        )
        _check(
            bp.drift_info(root, contexts=["validate-skills", "extra-job"]) == [],
            "all jobs required -> no orphan note",
            failed,
        )

    # =========================================================================
    # check: exit code 0 clean / 1 on drift (via the injection seam)
    # =========================================================================
    print("check (exit code 0 clean / 1 drift):")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        _write_workflow(wf, "validate-skills.yml", "jobs:\n  validate-skills:\n")
        _write_workflow(wf, "review-verdict.yml", "jobs:\n  review-verdict:\n")
        _check(
            bp.check(root, contexts=["validate-skills", "review-verdict"]) == 0,
            "check returns 0 when every context has a matching job",
            failed,
        )
        _check(
            bp.check(root, contexts=["validate-skills", "bogus"]) == 1,
            "check returns 1 on drift (a context with no job)",
            failed,
        )
        # No token / no injected contexts in production: graceful skip -> 0 when
        # jobs exist (the unauthenticated local path).
        _check(
            bp.check(root, contexts=[]) == 0,
            "check returns 0 on the graceful-skip path (no contexts, jobs exist)",
            failed,
        )

    if failed:
        print(f"\n{len(failed)} branch-protection test(s) failed.", file=sys.stderr)
        return 1
    print("\nAll branch-protection drift-guard tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
