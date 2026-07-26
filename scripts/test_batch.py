#!/usr/bin/env python3
"""Unit tests for the batch queue-drainer (ADR-0012).

Zero-dependency: runnable directly as ``python3 scripts/test_batch.py``.
Exits non-zero on any failure. Covers the load-bearing behavior of
:func:`loop.run_batch` and :func:`loop.list_ready_issues`:

  * the ready queue is queried with the right ``gh`` argv and parsed
    newest-first;
  * a clean queue drains end-to-end with every issue dispatched;
  * the first dispatch error fail-stops the run and records the culprit;
  * ``--limit`` caps the run even if the lister returns more;
  * an empty queue is a no-op, not an error;
  * ``--dry-run`` propagates through the default dispatcher to
    :func:`loop.run_ticket_loop`.

No agents, no ``paseo``, no live ``gh``: both the queue query and the
per-issue dispatch are injected. Behavior, not plumbing.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import loop  # noqa: E402


def _check(condition: bool, label: str, failed: list[str]) -> None:
    if not condition:
        print(f"  FAIL {label}")
        failed.append(label)


def _test_list_ready_issues_builds_gh_argv(failed: list[str]) -> None:
    """The queue query targets open <label> issues via gh, newest-first."""
    captured: dict = {}

    def fake_run_gh(argv):
        captured["argv"] = list(argv)
        return '[{"number": 41}, {"number": 40}]'

    original = loop.github._run_gh
    loop.github._run_gh = fake_run_gh
    try:
        nums = loop.list_ready_issues("acme/widgets", "ready-for-agent", 10)
    finally:
        loop.github._run_gh = original

    argv = captured["argv"]
    _check(argv[:3] == ["gh", "issue", "list"], "list_ready_issues uses gh issue list", failed)
    _check("--repo" in argv and "acme/widgets" in argv, "list_ready_issues targets --repo", failed)
    _check("--state" in argv and "open" in argv, "list_ready_issues filters open state", failed)
    _check("--label" in argv and "ready-for-agent" in argv, "list_ready_issues filters by label", failed)
    _check("--limit" in argv and "10" in argv, "list_ready_issues forwards the cap", failed)
    _check(nums == [41, 40], f"list_ready_issues parses numbers newest-first (got {nums})", failed)


def _cfg() -> "loop.DriverConfig":
    return loop.DriverConfig(
        repo="acme/widgets", base_branch="main",
        provider="anthropic", model="claude-sonnet-4", mode="primary",
    )


def _test_run_batch_drains_clean_queue(failed: list[str]) -> None:
    """A clean queue dispatches every issue, no fail-stop."""
    dispatched: list[int] = []

    def lister(repo, label, limit):
        return [28, 29, 30]

    def dispatcher(issue):
        dispatched.append(issue)
        return {"issue": issue}

    report = loop.run_batch(_cfg(), lister=lister, dispatcher=dispatcher)

    _check(report["queue"] == [28, 29, 30], f"report carries the queue (got {report['queue']})", failed)
    _check(dispatched == [28, 29, 30], f"every issue dispatched in order (got {dispatched})", failed)
    _check(report["dispatched"] == [28, 29, 30], "report lists dispatched issues", failed)
    _check(report["stopped_at"] is None, "no fail-stop on a clean queue", failed)
    _check(report["error"] is None, "no error on a clean queue", failed)


def _test_run_batch_fail_stops_on_first_error(failed: list[str]) -> None:
    """The first dispatch error halts the run and names the culprit issue."""
    dispatched: list[int] = []

    def lister(repo, label, limit):
        return [28, 29, 30]

    def dispatcher(issue):
        if issue == 29:
            raise RuntimeError("boom at 29")
        dispatched.append(issue)
        return {"issue": issue}

    report = loop.run_batch(_cfg(), lister=lister, dispatcher=dispatcher)

    _check(dispatched == [28], f"only pre-failure issues dispatched (got {dispatched})", failed)
    _check(report["dispatched"] == [28], "report lists only pre-failure dispatches", failed)
    _check(report["stopped_at"] == 29, f"stopped_at names the culprit (got {report['stopped_at']})", failed)
    _check(report["error"] == "boom at 29", f"error carries the message (got {report['error']!r})", failed)


def _test_run_batch_limit_caps_dispatch(failed: list[str]) -> None:
    """--limit caps the run even when the lister ignores it."""
    dispatched: list[int] = []

    def lister(repo, label, limit):
        return [1, 2, 3, 4, 5]  # deliberately ignores limit

    def dispatcher(issue):
        dispatched.append(issue)
        return {"issue": issue}

    report = loop.run_batch(_cfg(), limit=2, lister=lister, dispatcher=dispatcher)

    _check(dispatched == [1, 2], f"limit caps dispatches (got {dispatched})", failed)
    _check(report["dispatched"] == [1, 2], "report respects the cap", failed)


def _test_run_batch_empty_queue_is_noop(failed: list[str]) -> None:
    """An empty queue dispatches nothing and is not an error."""

    def lister(repo, label, limit):
        return []

    def dispatcher(issue):
        raise AssertionError("dispatcher must not run on an empty queue")

    report = loop.run_batch(_cfg(), lister=lister, dispatcher=dispatcher)

    _check(report["dispatched"] == [], "empty queue dispatches nothing", failed)
    _check(report["stopped_at"] is None, "empty queue is not a fail-stop", failed)
    _check(report["error"] is None, "empty queue carries no error", failed)


def _test_run_batch_default_dispatcher_propagates_dry_run(failed: list[str]) -> None:
    """The default dispatcher forwards dry_run to run_ticket_loop."""
    seen: dict = {}

    def fake_run_ticket_loop(issue, cfg, dry_run=False):
        seen["issue"] = issue
        seen["dry_run"] = dry_run
        return {"issue": issue}

    def lister(repo, label, limit):
        return [7]

    original = loop.run_ticket_loop
    loop.run_ticket_loop = fake_run_ticket_loop
    try:
        report = loop.run_batch(_cfg(), dry_run=True, lister=lister)
    finally:
        loop.run_ticket_loop = original

    _check(seen.get("dry_run") is True, "default dispatcher forwards dry_run=True", failed)
    _check(seen.get("issue") == 7, "default dispatcher forwards the issue", failed)
    _check(report["dry_run"] is True, "report records dry_run", failed)


def main() -> int:
    failed: list[str] = []
    tests = [
        ("list_ready_issues builds the gh argv", _test_list_ready_issues_builds_gh_argv),
        ("run_batch drains a clean queue", _test_run_batch_drains_clean_queue),
        ("run_batch fail-stops on first error", _test_run_batch_fail_stops_on_first_error),
        ("run_batch limit caps dispatch", _test_run_batch_limit_caps_dispatch),
        ("run_batch empty queue is a no-op", _test_run_batch_empty_queue_is_noop),
        ("run_batch default dispatcher propagates dry_run", _test_run_batch_default_dispatcher_propagates_dry_run),
    ]
    for label, fn in tests:
        print(f"{label}:")
        fn(failed)
    if failed:
        print(f"\n{len(failed)} batch test(s) FAILED:")
        for label in failed:
            print(f"  - {label}")
        return 1
    print("\nAll batch tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
