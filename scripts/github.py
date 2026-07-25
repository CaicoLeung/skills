#!/usr/bin/env python3
"""GitHub read gateway — one interface over the ``gh`` CLI.

A transport adapter that owns every ``gh`` *read* the loop driver
(:mod:`loop`) and the review-verdict CI check (:mod:`review_verdict`) perform.
Two adapters justify the seam (the codebase-design "two adapters = real seam"
test):

* :class:`GhCliReader` — the live adapter (subprocess + json). The production
  default.
* any duck-typed fake — the test adapter. Injected via the ``gh`` parameter on
  the driver entry points (twin to ``runner``), so the wiring layer becomes
  testable through its own interface.

Scope (deliberate): **reads only.** Writes (``gh pr merge``, ``gh issue
comment``, ``gh issue close``) stay as pure command-list builders emitted by
:mod:`closeout` / :mod:`loop` and executed by the driver's ``runner`` — they
are already a clean, tested seam (command-as-data + ``--dry-run``). Folding
writes in here would collapse two good patterns into one and lose that property.

Runtime-neutral (ADR-0004): no ``paseo``, no agent, no GitHub-App identity.
Failures surface as ``RuntimeError`` carrying context (the driver's CLI
boundary catches it); a missing resource raises (``gh`` exits non-zero) and an
empty one returns ``[]`` / ``""`` — the contract the callers already assume.

Zero sibling imports: this module depends on nothing else in ``scripts/``, so
it can be placed and imported without cycle risk.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class GitHubReader(Protocol):
    """Read-only GitHub surface — the six ops the loop + CI check need.

    Repo-first param order throughout. Returns raw primitives (``list[str]``,
    ``str``, ``list[dict]``); the typed parsing (``Finding``,
    ``SelectedFindings``) stays where it earns its keep, in :mod:`verdict` /
    :mod:`review_verdict`. The gateway is transport, not a data model.

    ``issue_comments`` serves both PR and issue comments — they share the REST
    endpoint (``/repos/{repo}/issues/{n}/comments``), so one method covers
    both. Pagination is hidden inside it (``--paginate``): callers never want a
    partial comment thread.
    """

    def issue_labels(self, repo: str, issue: int) -> list[str]: ...
    def issue_body(self, repo: str, issue: int) -> str: ...
    def issue_comments(self, repo: str, number: int) -> list[dict[str, Any]]: ...
    def pr_head_sha(self, repo: str, pr: int) -> str: ...
    def pr_diff(self, repo: str, pr: int) -> str: ...
    def pr_changed_files(self, repo: str, pr: int) -> list[str]: ...


def _run_gh(argv: Sequence[str]) -> str:
    """Run a ``gh`` command and return stdout; wrap failures as ``RuntimeError``.

    Single point of error normalization: ``gh`` missing (``FileNotFoundError``)
    and ``gh`` failing (``CalledProcessError``) both become a ``RuntimeError``
    carrying the failing command and stderr, so callers and the CLI boundary
    see one error shape (the fail-loud stance the drivers already take).
    """
    rendered = " ".join(str(a) for a in argv)
    try:
        result = subprocess.run(
            list(argv), check=True, capture_output=True, text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"`gh` CLI not found on PATH ({rendered})") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"{rendered} failed: {(exc.stderr or '').strip()}"
        ) from exc
    return result.stdout


class GhCliReader:
    """Live :class:`GitHubReader` over the ``gh`` CLI (the production default).

    Each method is a thin ``gh`` invocation + json parse; the bodies are
    intentionally the single source of truth for the command shape so the
    driver and the CI check never re-derive it. Verbatim behaviour carried over
    from the per-driver ``_gh_*`` helpers this replaces.
    """

    def issue_labels(self, repo: str, issue: int) -> list[str]:
        out = _run_gh([
            "gh", "issue", "view", str(issue),
            "--repo", repo, "--json", "number,title,labels",
        ])
        data = json.loads(out) if out.strip() else {}
        return [label["name"] for label in data.get("labels", [])]

    def issue_body(self, repo: str, issue: int) -> str:
        out = _run_gh([
            "gh", "issue", "view", str(issue),
            "--repo", repo, "--json", "body",
        ])
        data = json.loads(out) if out.strip() else {}
        return data.get("body", "") or ""

    def issue_comments(self, repo: str, number: int) -> list[dict[str, Any]]:
        # The issues endpoint covers PR comments too (see GitHubReader docs);
        # ``--paginate`` hides paging — callers never want a partial thread.
        out = _run_gh([
            "gh", "api", f"repos/{repo}/issues/{number}/comments", "--paginate",
        ])
        stripped = out.strip()
        comments = json.loads(stripped) if stripped else []
        return comments if isinstance(comments, list) else []

    def pr_head_sha(self, repo: str, pr: int) -> str:
        out = _run_gh([
            "gh", "pr", "view", str(pr),
            "--repo", repo, "--json", "headRefOid",
        ])
        data = json.loads(out) if out.strip() else {}
        return data.get("headRefOid", "") or ""

    def pr_diff(self, repo: str, pr: int) -> str:
        return _run_gh(["gh", "pr", "diff", str(pr), "--repo", repo])

    def pr_changed_files(self, repo: str, pr: int) -> list[str]:
        out = _run_gh([
            "gh", "pr", "view", str(pr),
            "--repo", repo, "--json", "files",
        ])
        data = json.loads(out) if out.strip() else {}
        files = data.get("files") or []
        return [f.get("path") for f in files if f.get("path")]
