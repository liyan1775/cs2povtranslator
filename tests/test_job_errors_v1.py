import pytest

from cs2pov.storage.job_errors import JobRepositoryError


def test_repository_error_exposes_stable_diagnostic_and_issue():
    error = JobRepositoryError("job_manifest_invalid", "清单无效。", "请修复后重试。", "job.json")
    assert error.code == "job_manifest_invalid"
    assert error.message_zh == "清单无效。"
    assert error.suggestion_zh == "请修复后重试。"
    assert error.logical_path == "job.json"
    issue = error.to_issue()
    assert issue.code == error.code
    assert issue.logical_path == "job.json"


@pytest.mark.parametrize("logical_path", ["C:/secret", "/etc/passwd", "\\\\server\\share", "https://example.test/a", "../job.json", "job//x", "job/./x", ""])
def test_repository_diagnostics_reject_absolute_or_non_posix_paths(logical_path):
    with pytest.raises(ValueError):
        JobRepositoryError("job_manifest_invalid", "无效。", "修复。", logical_path)
