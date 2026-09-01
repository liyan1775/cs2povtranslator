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
