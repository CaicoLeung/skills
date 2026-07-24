"""Unit tests for verdict.py (ADR-0007 derived verdict)."""

import pytest

from scripts.verdict import Finding, Severity, VerdictResult, derive_verdict


@pytest.mark.unit
def test_clean_pass_all_files_covered_with_ok():
    """Clean pass: every changed file has explicit OK, no blocking issues."""
    findings_text = """
    src/main.py: OK
    src/utils.py: OK
    tests/test_main.py: OK
    """
    changed_files = ["src/main.py", "src/utils.py", "tests/test_main.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is True
    assert len(result.blocking_issues) == 0
    assert len(result.coverage_gaps) == 0
    assert result.to_dict()["verdict"] == "pass"


@pytest.mark.unit
def test_clean_pass_all_files_covered_with_findings():
    """Clean pass: every changed file has LOW/MEDIUM findings, no blocking."""
    findings_text = """
    src/main.py:42: LOW: Rename variable for clarity.
    src/utils.py:15: MEDIUM: Consider adding type hint.
    tests/test_main.py:8: LOW: Test name could be more descriptive.
    """
    changed_files = ["src/main.py", "src/utils.py", "tests/test_main.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is True
    assert len(result.blocking_issues) == 0
    assert len(result.coverage_gaps) == 0


@pytest.mark.unit
def test_clean_pass_mixed_ok_and_findings():
    """Clean pass: mix of explicit OK and LOW/MEDIUM findings."""
    findings_text = """
    src/main.py: OK
    src/utils.py:15: MEDIUM: Add docstring.
    tests/test_main.py: OK
    """
    changed_files = ["src/main.py", "src/utils.py", "tests/test_main.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is True
    assert len(result.blocking_issues) == 0
    assert len(result.coverage_gaps) == 0


@pytest.mark.unit
def test_fail_on_critical_finding():
    """FAIL on CRITICAL severity finding."""
    findings_text = """
    src/main.py:42: CRITICAL: SQL injection vulnerability.
    src/utils.py:15: LOW: Minor style issue.
    """
    changed_files = ["src/main.py", "src/utils.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is False
    assert len(result.blocking_issues) == 1
    assert result.blocking_issues[0].severity == Severity.CRITICAL
    assert "SQL injection" in result.blocking_issues[0].summary


@pytest.mark.unit
def test_fail_on_high_finding():
    """FAIL on HIGH severity finding."""
    findings_text = """
    src/auth.py:88: HIGH: Missing authentication check.
    src/main.py:10: LOW: Variable name unclear.
    """
    changed_files = ["src/auth.py", "src/main.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is False
    assert len(result.blocking_issues) == 1
    assert result.blocking_issues[0].severity == Severity.HIGH


@pytest.mark.unit
def test_fail_on_multiple_blocking_issues():
    """FAIL on multiple CRITICAL/HIGH findings."""
    findings_text = """
    src/auth.py:88: CRITICAL: Hardcoded secret.
    src/main.py:42: HIGH: Unvalidated user input.
    src/utils.py:15: CRITICAL: Buffer overflow risk.
    """
    changed_files = ["src/auth.py", "src/main.py", "src/utils.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is False
    assert len(result.blocking_issues) == 3
    severity_summaries = {f.severity for f in result.blocking_issues}
    assert Severity.CRITICAL in severity_summaries
    assert Severity.HIGH in severity_summaries


@pytest.mark.unit
def test_medium_and_low_are_non_blocking():
    """MEDIUM and LOW findings do NOT block verdict."""
    findings_text = """
    src/main.py:42: MEDIUM: Missing error handling.
    src/utils.py:15: MEDIUM: Inefficient algorithm.
    src/auth.py:88: LOW: Consider caching.
    """
    changed_files = ["src/main.py", "src/utils.py", "src/auth.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is True
    assert len(result.blocking_issues) == 0
    assert len(result.findings) == 3  # All findings recorded


@pytest.mark.unit
def test_fail_on_coverage_gap_no_finding_or_ok():
    """FAIL when changed file has neither finding nor explicit OK."""
    findings_text = """
    src/main.py:42: LOW: Minor style issue.
    """
    changed_files = ["src/main.py", "src/utils.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is False
    assert len(result.coverage_gaps) == 1
    assert "src/utils.py" in result.coverage_gaps


@pytest.mark.unit
def test_fail_on_multiple_coverage_gaps():
    """FAIL when multiple changed files lack coverage."""
    findings_text = """
    src/main.py: OK
    """
    changed_files = ["src/main.py", "src/utils.py", "src/auth.py", "tests/test.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is False
    assert len(result.coverage_gaps) == 3
    assert "src/utils.py" in result.coverage_gaps
    assert "src/auth.py" in result.coverage_gaps
    assert "tests/test.py" in result.coverage_gaps


@pytest.mark.unit
def test_fail_on_blocking_and_coverage_gap():
    """FAIL when both blocking issues AND coverage gaps exist."""
    findings_text = """
    src/main.py:42: CRITICAL: Security vulnerability.
    src/utils.py: OK
    """
    changed_files = ["src/main.py", "src/utils.py", "src/auth.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is False
    assert len(result.blocking_issues) == 1
    assert len(result.coverage_gaps) == 1


@pytest.mark.unit
def test_empty_findings_all_files_uncovered():
    """Empty findings with changed files = FAIL (coverage gap)."""
    findings_text = ""
    changed_files = ["src/main.py", "src/utils.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is False
    assert len(result.coverage_gaps) == 2


@pytest.mark.unit
def test_empty_findings_no_changed_files():
    """Empty findings, no changed files = PASS (trivial case)."""
    findings_text = ""
    changed_files = []

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is True
    assert len(result.coverage_gaps) == 0


@pytest.mark.unit
def test_aggregate_both_review_axes():
    """Aggregate findings across Standards and Spec axes (ADR-0007)."""
    findings_text = """
    # Standards axis findings
    src/main.py:42: MEDIUM: Missing type hint.
    src/utils.py:15: LOW: Comment unclear.

    # Spec axis findings
    src/auth.py:88: HIGH: Does not implement required auth flow.
    tests/test.py:10: CRITICAL: Missing test coverage for edge case.
    """
    changed_files = ["src/main.py", "src/utils.py", "src/auth.py", "tests/test.py"]

    result = derive_verdict(findings_text, changed_files)

    # CRITICAL + HIGH across both axes should FAIL
    assert result.pass_verdict is False
    assert len(result.blocking_issues) == 2
    assert len(result.findings) == 4


@pytest.mark.unit
def test_finding_parsing_with_line_numbers():
    """Parse findings with line numbers correctly."""
    findings_text = """
    src/main.py:42: CRITICAL: Null pointer dereference.
    src/utils.py:15: HIGH: Missing validation.
    """
    changed_files = ["src/main.py", "src/utils.py"]

    result = derive_verdict(findings_text, changed_files)

    assert len(result.findings) == 2
    main_finding = next(f for f in result.findings if f.file == "src/main.py")
    assert main_finding.line == 42


@pytest.mark.unit
def test_finding_parsing_without_line_numbers():
    """Parse findings without line numbers (file-level findings)."""
    findings_text = """
    src/main.py: MEDIUM: Consider refactoring.
    src/utils.py: LOW: Add docstring.
    """
    changed_files = ["src/main.py", "src/utils.py"]

    result = derive_verdict(findings_text, changed_files)

    assert len(result.findings) == 2
    main_finding = next(f for f in result.findings if f.file == "src/main.py")
    assert main_finding.line is None


@pytest.mark.unit
def test_ignore_malformed_lines():
    """Ignore malformed lines that don't match expected format."""
    findings_text = """
    src/main.py:42: CRITICAL: Valid finding.
    This is not a valid finding line.
    Another invalid line
    src/utils.py:15: LOW: Another valid finding.
    """
    changed_files = ["src/main.py", "src/utils.py"]

    result = derive_verdict(findings_text, changed_files)

    # Should parse only valid findings
    assert len(result.findings) == 2


@pytest.mark.unit
def test_explicit_ok_with_path_separator():
    """Parse explicit OK with various path formats."""
    findings_text = """
    src/main.py: OK
    src/utils/helpers.py: OK
    tests/test_main.py: OK
    """
    changed_files = ["src/main.py", "src/utils/helpers.py", "tests/test_main.py"]

    result = derive_verdict(findings_text, changed_files)

    assert result.pass_verdict is True
    assert len(result.coverage_gaps) == 0


@pytest.mark.unit
def test_whitespace_handling_in_findings():
    """Handle extra whitespace in findings text."""
    findings_text = """
    src/main.py:42:  LOW:  Finding with extra spacing.
    src/utils.py:15:MEDIUM:Finding with no spacing.
    """
    changed_files = ["src/main.py", "src/utils.py"]

    result = derive_verdict(findings_text, changed_files)

    assert len(result.findings) == 2
    assert result.pass_verdict is True
