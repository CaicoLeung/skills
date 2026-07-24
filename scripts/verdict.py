#!/usr/bin/env python3
"""Derive verdict from code-review findings.

Implements ADR-0007 derived verdict protocol. The verdict is computed from
severity-tagged findings, never self-declared.

Verdict rule:
  pass = (no CRITICAL and no HIGH) AND (every changed file has a finding or explicit OK)
  fail = any CRITICAL or HIGH finding OR any changed file lacks coverage

This is a pure function — no agent, network, or GitHub calls.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from enum import Enum


# Regex for explicit OK lines: 'file: OK' with optional whitespace
OK_RE = re.compile(r"^(.+?)\s*:\s*OK\s*$")


class Severity(Enum):
    """Finding severity levels."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @classmethod
    def from_string(cls, value: str) -> Severity | None:
        """Parse severity from string."""
        try:
            return cls[value.upper()]
        except KeyError:
            return None


def _normalize_path(path: str) -> str:
    """Normalize file path for comparison.

    Strips leading './' and normalizes path separators.
    """
    return os.path.normpath(path).lstrip("./\\")


@dataclass(frozen=True)
class Finding:
    """A code-review finding."""

    file: str
    line: int | None
    severity: Severity
    summary: str

    @classmethod
    def from_string(cls, line: str) -> Finding | None:
        """Parse finding from '[file:line]: SEVERITY: summary' format."""
        pattern = r"^([^:]+):(?:(\d+):)?\s*([A-Z]+):\s*(.+)$"
        match = re.match(pattern, line.strip())
        if not match:
            return None

        file_path, line_str, severity_str, summary = match.groups()
        severity = Severity.from_string(severity_str)
        if not severity:
            return None

        return cls(
            file=_normalize_path(file_path),
            line=int(line_str) if line_str else None,
            severity=severity,
            summary=summary.strip(),
        )


@dataclass(frozen=True)
class VerdictResult:
    """Verdict computation result."""

    pass_verdict: bool
    findings: list[Finding]
    changed_files: set[str]
    coverage_gaps: tuple[str, ...]  # Files with no findings or explicit OK
    blocking_issues: tuple[Finding, ...]  # CRITICAL or HIGH findings

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "verdict": "pass" if self.pass_verdict else "fail",
            "findings_count": len(self.findings),
            "blocking_count": len(self.blocking_issues),
            "coverage_gaps": list(self.coverage_gaps),
            "blocking_files": [f.file for f in self.blocking_issues],
        }


def derive_verdict(
    findings_text: str, changed_files: list[str]
) -> VerdictResult:
    """Derive verdict from code-review findings and changed files.

    Args:
        findings_text: Raw findings output from code-review, one per line.
                       Format: '[file:line]: SEVERITY: summary'
                       Or: 'file: OK' for explicit OK
        changed_files: List of files that were changed in the PR.

    Returns:
        VerdictResult with pass/fail and detailed breakdown.

    Verdict rule:
        pass = (no CRITICAL and no HIGH) AND
               (every changed file has a finding or explicit OK)
        fail = any CRITICAL or HIGH OR coverage gap
    """
    findings: list[Finding] = []
    explicitly_ok_files: set[str] = set()

    # Parse findings
    for line in findings_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # Try to parse as a finding first (more specific pattern)
        finding = Finding.from_string(line)
        if finding:
            findings.append(finding)
            continue

        # Check for explicit OK: 'file: OK' (robust to whitespace)
        # Only treat as OK if finding parsing failed
        ok_match = OK_RE.match(line)
        if ok_match:
            ok_file = _normalize_path(ok_match.group(1))
            explicitly_ok_files.add(ok_file)
            continue

    # Check for blocking issues (CRITICAL or HIGH)
    blocking_issues = tuple(f for f in findings if f.severity in (Severity.CRITICAL, Severity.HIGH))

    # Check for coverage gaps (changed file with no finding or OK)
    changed_file_set = {_normalize_path(f) for f in changed_files}
    files_with_findings = {f.file for f in findings}
    files_with_coverage = files_with_findings | explicitly_ok_files

    coverage_gaps = tuple(sorted(changed_file_set - files_with_coverage))

    # Derive verdict
    pass_verdict = len(blocking_issues) == 0 and len(coverage_gaps) == 0

    return VerdictResult(
        pass_verdict=pass_verdict,
        findings=findings,
        changed_files=changed_file_set,
        coverage_gaps=coverage_gaps,
        blocking_issues=blocking_issues,
    )


def main() -> int:
    """CLI entry point for verdict derivation."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Derive verdict from code-review findings (ADR-0007)"
    )
    parser.add_argument(
        "findings_file",
        type=argparse.FileType("r"),
        help="File containing code-review findings",
    )
    parser.add_argument(
        "changed_files",
        nargs="*",
        help="List of changed files (or use --changed-files-file)",
    )
    parser.add_argument(
        "--changed-files-file",
        type=argparse.FileType("r"),
        help="File containing changed files (one per line)",
    )

    args = parser.parse_args()

    with args.findings_file:
        findings_text = args.findings_file.read()

    if args.changed_files_file:
        with args.changed_files_file:
            changed_files = [f.strip() for f in args.changed_files_file if f.strip()]
    else:
        changed_files = args.changed_files

    result = derive_verdict(findings_text, changed_files)

    print(json.dumps(result.to_dict(), indent=2))

    return 0 if result.pass_verdict else 1


if __name__ == "__main__":
    sys.exit(main())
