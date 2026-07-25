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
    """In-memory :class:`github.GitHubReader` for driver tests."""

    def __init__(self) -> None:
        self.labels: dict[int, list[str]] = {}
        self.bodies: dict[int, str] = {}
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.head_shas: dict[int, str] = {}
        self.diffs: dict[int, str] = {}
        self.changed_files: dict[int, list[str]] = {}

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
