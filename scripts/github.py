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
    """Read-only GitHub surface — the ops the loop, the CI check, and the
    supervisor need.

    Repo-first param order throughout. Returns raw primitives (``list[str]``,
    ``str``, ``list[dict]``); the typed parsing (``Finding``,
    ``SelectedFindings``, :class:`supervise.GateState`) stays where it earns
    its keep, in :mod:`verdict` / :mod:`review_verdict` / :mod:`loop`. The
    gateway is transport, not a data model.

    ``issue_comments`` serves both PR and issue comments — they share the REST
    endpoint (``/repos/{repo}/issues/{n}/comments``), so one method covers
    both. Pagination is hidden inside it (``--paginate``): callers never want a
    partial comment thread.

    Supervisor reads (ADR-0006): ``pr_merge_state`` and
    ``commit_status_contexts`` are the gate-state surface the supervisor
    observes. They are **platform state**, not agent internals — the
    "don't poll agents" guidance never applied to them (ADR-0006 §4).
    """

    def issue_labels(self, repo: str, issue: int) -> list[str]: ...
    def issue_body(self, repo: str, issue: int) -> str: ...
    def issue_comments(self, repo: str, number: int) -> list[dict[str, Any]]: ...
    def pr_head_sha(self, repo: str, pr: int) -> str: ...
    def pr_diff(self, repo: str, pr: int) -> str: ...
    def pr_changed_files(self, repo: str, pr: int) -> list[str]: ...
    def pr_merge_state(self, repo: str, pr: int) -> dict[str, Any]: ...
    def commit_status_contexts(self, repo: str, sha: str) -> list[dict[str, Any]]: ...


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
def _normalize_check_run(run: dict[str, Any]) -> dict[str, str]:
    """Normalize a GitHub **check-run** into the supervisor's status shape.

    GitHub reports Actions results as *check-runs*
    (``/commits/{sha}/check-runs``), which the legacy
    ``/commits/{sha}/status`` endpoint does NOT list. Branch protection's
    ``required_status_checks.contexts`` rule unifies the two surfaces by name,
    so the supervisor must too — otherwise an Actions-only repo (this one)
    reads every required check as absent and falsely escalates after the
    absence-of-signal deadline.

    Maps a check-run's ``(status, conclusion)`` to the single ``state`` value
    the supervisor already speaks (and that ``loop``'s gate-build reads off a
    status-context entry)::

        status      = queued | in_progress              -> "pending"
        conclusion  = success                           -> "success"
        conclusion  = failure | timed_out | cancelled
                     | action_required                  -> "failure"
        conclusion  = stale                             -> "error"
        conclusion  = neutral | skipped | "" | unknown  -> ""   (ran, no pass/fail)

    ``neutral`` / ``skipped`` map to ``""`` (not success, not failure): a
    seen-but-neutral check is WAIT, never a pass. Pure function — no network,
    unit-tested directly so the Actions/legacy unification is provable without
    a live ``gh`` call.
    """
    name = run.get("name") or ""
    status = (run.get("status") or "").lower()
    conclusion = (run.get("conclusion") or "").lower()

    if status in ("queued", "in_progress"):
        state = "pending"
    elif status == "completed":
        if conclusion == "success":
            state = "success"
        elif conclusion in ("failure", "timed_out", "cancelled", "action_required"):
            state = "failure"
        elif conclusion == "stale":
            state = "error"
        else:  # neutral, skipped, "", or anything unrecognized
            state = ""
    else:
        state = ""
    return {"context": name, "state": state}


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

    def pr_merge_state(self, repo: str, pr: int) -> dict[str, Any]:
        """Fetch the PR's merge-state fields the supervisor watches (ADR-0006).

        Returns the four fields the supervisor's gate observation needs:
        ``state`` (``OPEN`` | ``MERGED`` | ``CLOSED``), ``mergeStateStatus``
        (``UNKNOWN`` | ``BEHIND`` | ``BLOCKED`` | ``CLEAN`` | ``DIRTY`` |
        ``HAS_HOOKS``), ``mergedAt`` (ISO timestamp or ``""``), and
        ``headRefOid`` (the head SHA — the supervisor needs it to fetch the
        commit's status contexts in a follow-up call).

        ``gh pr view --json`` is the GitHub CLI's stable projection; it hides
        the GraphQL/REST split. Failure modes match the rest of the gateway:
        ``gh`` missing or non-zero raises ``RuntimeError``.
        """
        out = _run_gh([
            "gh", "pr", "view", str(pr),
            "--repo", repo,
            "--json", "state,mergeStateStatus,mergedAt,headRefOid",
        ])
        data = json.loads(out) if out.strip() else {}
        return {
            "state": data.get("state", "") or "",
            "mergeStateStatus": data.get("mergeStateStatus", "") or "",
            "mergedAt": data.get("mergedAt", "") or "",
            "headRefOid": data.get("headRefOid", "") or "",
        }

    def commit_status_contexts(self, repo: str, sha: str) -> list[dict[str, Any]]:
        """Fetch the unified per-context status list for a commit (ADR-0006).

        Backs the supervisor's absence-of-signal detector: the required check
        is "seen" iff a context with that name appears in this list. GitHub
        has TWO status surfaces — legacy **status contexts**
        (``/commits/{sha}/status``; external CI / status posts) and
        **check-runs** (``/commits/{sha}/check-runs``; GitHub Actions).
        Branch protection's ``required_status_checks.contexts`` rule unifies
        them by name; this method does too, so an Actions-only repo (this one)
        reads its required checks as *seen* rather than as *absent*.

        Both surfaces are normalized to ``{"context": <name>, "state": <s>}``
        where ``state`` is ``success`` | ``failure`` | ``error`` | ``pending``
        | ``""``. Check-runs override legacy statuses of the same context name
        (Actions is the modern default and the surface branch protection
        honors for required checks). Returns ``[]`` when neither surface has
        reported yet — the absence case the detector fires on.
        """
        # Legacy status contexts — already {context, state, ...}. Keyed by
        # context name so the check-run pass below can override on collision.
        merged: dict[str, dict[str, Any]] = {}
        out_status = _run_gh([
            "gh", "api", f"repos/{repo}/commits/{sha}/status", "--paginate",
        ])
        stripped = out_status.strip()
        if stripped:
            data = json.loads(stripped)
            statuses = data.get("statuses") if isinstance(data, dict) else None
            if isinstance(statuses, list):
                for st in statuses:
                    ctx = st.get("context") or ""
                    if ctx:
                        merged[ctx] = {"context": ctx, "state": (st.get("state") or "")}

        # Check-runs (GitHub Actions) — normalized, override on name collision.
        out_runs = _run_gh([
            "gh", "api", f"repos/{repo}/commits/{sha}/check-runs", "--paginate",
        ])
        stripped = out_runs.strip()
        if stripped:
            data = json.loads(stripped)
            runs = data.get("check_runs") if isinstance(data, dict) else None
            if isinstance(runs, list):
                for run in runs:
                    norm = _normalize_check_run(run)
                    if norm.get("context"):
                        merged[norm["context"]] = norm

        return list(merged.values())
