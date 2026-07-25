#!/usr/bin/env python3
"""Shared test doubles for the driver/CI unit suites.

The hand-rolled suites (``test_loop``, ``test_closeout``, ...) run as
standalone scripts with ``scripts/`` on ``sys.path``; this module is their one
shared fake, so the in-memory :class:`FakeGitHubReader` lives in one place.
The leading underscore keeps pytest (which collects ``test_*.py``) from
treating this as a test module.

The fake twins the ``runner`` injection: the driver is exercised through its
own interface with no ``gh`` and no network. It holds dicts keyed by issue/PR
number. Return types match :class:`github.GitHubReader` exactly (notably
``list[dict[str, Any]]``), so it satisfies the Protocol under strict mypy and
the ``runtime_checkable`` ``isinstance`` smoke check alike.
"""

from __future__ import annotations

from typing import Any


class FakeGitHubReader:
    """In-memory :class:`github.GitHubReader` for driver tests.

    Holds dicts keyed by issue/PR number (and by commit SHA for statuses).
    Return types match :class:`github.GitHubReader` exactly (notably
    ``list[dict[str, Any]]``), so it satisfies the Protocol under strict mypy
    and the ``runtime_checkable`` ``isinstance`` smoke check alike.
    """

    def __init__(self) -> None:
        self.labels: dict[int, list[str]] = {}
        self.bodies: dict[int, str] = {}
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.head_shas: dict[int, str] = {}
        self.diffs: dict[int, str] = {}
        self.changed_files: dict[int, list[str]] = {}
        # Supervisor (ADR-0006) — gate-state surface. ``merge_states`` is
        # keyed by PR number (matches the rest); ``statuses`` by commit SHA
        # (one list of per-context dicts per commit, mirroring the REST shape).
        self.merge_states: dict[int, dict[str, Any]] = {}
        self.statuses: dict[str, list[dict[str, Any]]] = {}

    def issue_labels(self, repo: str, issue: int) -> list[str]:
        return self.labels.get(issue, [])

    def issue_body(self, repo: str, issue: int) -> str:
        return self.bodies.get(issue, "")

    def issue_comments(self, repo: str, number: int) -> list[dict[str, Any]]:
        return self.comments.get(number, [])

    def pr_head_sha(self, repo: str, pr: int) -> str:
        return self.head_shas.get(pr, "")

    def pr_diff(self, repo: str, pr: int) -> str:
        return self.diffs.get(pr, "")

    def pr_changed_files(self, repo: str, pr: int) -> list[str]:
        return self.changed_files.get(pr, [])

    def pr_merge_state(self, repo: str, pr: int) -> dict[str, Any]:
        ms = self.merge_states.get(pr)
        if ms is None:
            # Default to an open, untouched PR — the supervisor's WAIT path.
            return {
                "state": "OPEN",
                "mergeStateStatus": "UNKNOWN",
                "mergedAt": "",
                "headRefOid": self.head_shas.get(pr, ""),
            }
        # Let tests override any subset of the four fields; fill the rest.
        base = {
            "state": "OPEN",
            "mergeStateStatus": "UNKNOWN",
            "mergedAt": "",
            "headRefOid": self.head_shas.get(pr, ""),
        }
        base.update(ms)
        return base

    def commit_status_contexts(self, repo: str, sha: str) -> list[dict[str, Any]]:
        return self.statuses.get(sha, [])
