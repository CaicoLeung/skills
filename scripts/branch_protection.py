#!/usr/bin/env python3
"""Branch-protection drift guard (ADR-0003).

Asserts the 1:1 mapping between GitHub branch-protection *required status-check
contexts* and *workflow job names*: every required context must have a matching
job in ``.github/workflows/*.yml``. A required context with no matching job
fails the guard, so renaming a job (or a context) without the other surfaces as
a drift error instead of silently breaking the merge gate.

Extracted from ``scripts/skills.py`` (issue #53) so ``validate`` shrinks to its
real job — frontmatter + schema, with no network side-effect — and the guard
earns its own seam, its own CLI, and its own tests. Consistent with ADR-0003:
the gate is **honored, not weakened**; extraction gives it a dedicated, visible
home. The live ``validate-skills`` CI job runs this as its own step.

The pure drift logic (:func:`workflow_job_names`, :func:`missing_job_errors`)
has no network and is unit-tested directly; the GitHub REST fetch
(:func:`required_status_contexts`) is the I/O boundary, injected into
:func:`drift_errors` via the optional ``contexts`` argument so the composition
is testable without a token or network.

CLI:
    python3 scripts/branch_protection.py [--root ROOT] [--repo OWNER/NAME]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def workflow_job_names(workflows_dir: Path) -> set[str]:
    """Extract top-level job names from all workflow YAML files under ``workflows_dir``.

    Walks each ``*.yml`` file's ``jobs:`` block and collects the keys one
    indentation level deeper than the ``jobs:`` line — the job names GitHub
    Actions surfaces as status-check contexts. Returns ``set()`` when the
    directory is absent. Pure: no network, no token.
    """
    jobs: set[str] = set()
    if not workflows_dir.exists():
        return jobs

    for wf_file in workflows_dir.glob("*.yml"):
        content = wf_file.read_text(encoding="utf-8")
        lines = content.splitlines()

        in_jobs = False
        jobs_indent: int | None = None
        for raw in lines:
            stripped = raw.strip()
            if stripped == "jobs:":
                in_jobs = True
                jobs_indent = len(raw) - len(raw.lstrip())
                continue

            if in_jobs and jobs_indent is not None and raw.strip():
                current_indent = len(raw) - len(raw.lstrip())
                # Exit the jobs section on a same-level or less-indented key.
                if current_indent <= jobs_indent and ":" in raw:
                    in_jobs = False
                    continue

                # Job name: exactly one level deeper than ``jobs:``.
                if ":" in raw:
                    line_indent = len(raw) - len(raw.lstrip())
                    if line_indent == jobs_indent + 2:
                        potential = raw.strip().split(":", 1)[0].strip()
                        if potential and not potential.startswith("#"):
                            jobs.add(potential)

    return jobs


def missing_job_errors(contexts: list[str], job_names: set[str]) -> list[str]:
    """Each required context with no matching workflow job name -> one error.

    Pure: given the branch-protection contexts and the discovered workflow job
    names, return one drift error per context that has no job of the same name.
    The error text is stable (asserted by ADR-0003's contexts↔jobs mapping).
    """
    found = sorted(job_names)
    return [
        f"branch protection requires context '{ctx}' "
        f"but no workflow job has that name (found: {found})"
        for ctx in contexts
        if ctx not in job_names
    ]


def required_status_contexts(repo: str = "CaicoLeung/skills") -> list[str]:
    """Fetch required status-check contexts from branch protection via GitHub REST.

    Uses ``GITHUB_TOKEN`` for auth. Returns ``[]`` when unauthenticated, when no
    protection is configured (404), or when permissions are insufficient
    (403/401). In CI, any *other* transport failure raises loudly; locally it
    skips gracefully — the contract the rest of the guard already assumed.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return []

    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/branches/main/protection",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            contexts = data.get("required_status_checks", {}).get("contexts", [])
            return [str(c) for c in contexts]
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as e:
        # 404 = no protection configured, 403/401 = insufficient permissions.
        if isinstance(e, urllib.error.HTTPError) and e.code in (404, 403, 401):
            return []
        # In CI, fail loudly; locally, skip gracefully.
        if os.environ.get("CI"):
            raise RuntimeError(f"Failed to fetch branch protection: {e}") from e
        return []


def _drift_inputs(
    repo_root: Path,
    contexts: list[str] | None,
    repo: str,
) -> tuple[set[str], list[str]]:
    """Resolve the two inputs the drift comparison shares.

    Returns ``(workflow_job_names, required_contexts)``: job names come from
    :func:`workflow_job_names` (pure), and required contexts are the injected
    ``contexts`` when given, else fetched via :func:`required_status_contexts`
    (the production path). Centralizing this keeps the network fallback in one
    place for both :func:`drift_errors` and :func:`drift_info`.
    """
    workflows_dir = repo_root / ".github" / "workflows"
    job_names = workflow_job_names(workflows_dir)
    required = contexts if contexts is not None else required_status_contexts(repo)
    return job_names, required


def drift_errors(
    repo_root: Path,
    *,
    contexts: list[str] | None = None,
    repo: str = "CaicoLeung/skills",
) -> list[str]:
    """Validate that each branch-protection context has a matching workflow job.

    Args:
        repo_root: The repo root (``.github/workflows`` lives under it).
        contexts: Required contexts. When ``None``, fetched via
            :func:`required_status_contexts` (the production path); pass a list
            to test the drift logic with no token or network.
        repo: ``owner/name`` for the REST fetch (ignored when ``contexts`` is
            given).

    Returns ``["no workflow job names found in .github/workflows/*.yml"]`` when
    no jobs are discoverable (a structural error independent of contexts). When
    contexts resolve empty (unauthenticated / no protection), only that
    structural error survives — the per-context check is skipped gracefully.
    """
    errors: list[str] = []
    job_names, required = _drift_inputs(repo_root, contexts, repo)
    if not job_names:
        errors.append("no workflow job names found in .github/workflows/*.yml")

    if not required:
        # Empty contexts (unauthenticated / no protection / injected-empty in a
        # test) — skip the per-context check gracefully, as before.
        return errors

    errors.extend(missing_job_errors(required, job_names))
    return errors


def drift_info(
    repo_root: Path,
    *,
    contexts: list[str] | None = None,
    repo: str = "CaicoLeung/skills",
) -> list[str]:
    """Return informational (non-failing) notes about branch-protection drift.

    Flags workflow jobs that are not required by branch protection (an orphan
    job is not an error, just a note). Same injection seam as
    :func:`drift_errors`.
    """
    info: list[str] = []
    job_names, required = _drift_inputs(repo_root, contexts, repo)
    if required:
        orphan_jobs = job_names - set(required)
        if orphan_jobs:
            info.append(
                f"note: workflow job(s) {sorted(orphan_jobs)} not required by branch protection"
            )

    return info


def check(
    repo_root: Path,
    repo: str = "CaicoLeung/skills",
    *,
    contexts: list[str] | None = None,
) -> int:
    """Run the drift guard. Returns ``0`` if clean, ``1`` on any drift.

    Drift errors go to stderr and fail the run; informational notes go to
    stdout and never fail. Mirrors the output shape the guard had when it lived
    inside ``cmd_validate``. ``contexts`` is the injection seam for tests (no
    token / no network); when ``None`` it is fetched via
    :func:`required_status_contexts`.
    """
    errors = drift_errors(repo_root, repo=repo, contexts=contexts)
    if errors:
        print("Branch protection guard:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    for msg in drift_info(repo_root, repo=repo, contexts=contexts):
        print(f"  {msg}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Branch-protection drift guard CLI (ADR-0003)."""
    p = argparse.ArgumentParser(
        description="Assert branch-protection contexts map 1:1 to workflow jobs (ADR-0003).",
    )
    p.add_argument("--root", default=".", help="repo root (default: cwd)")
    p.add_argument("--repo", default="CaicoLeung/skills", help="owner/name repo")
    args = p.parse_args(argv)
    return check(Path(args.root).resolve(), args.repo)


if __name__ == "__main__":
    sys.exit(main())
