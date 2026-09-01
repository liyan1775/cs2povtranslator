from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _IssueView:
    code: str
    severity: str
    message_zh: str
    suggestion_zh: str
    logical_path: str | None


class JobRepositoryError(RuntimeError):
    """Stable boundary error for current-version Job persistence."""

    def __init__(
        self,
        code: str,
        message_zh: str,
        suggestion_zh: str,
        logical_path: str | None = None,
        *,
        severity: str = "error",
    ) -> None:
        super().__init__(message_zh)
        self.code = code
        self.message_zh = message_zh
        self.suggestion_zh = suggestion_zh
        self.logical_path = logical_path
        self.severity = severity

    def to_issue(self):
        # Import lazily to keep the error boundary independent of domain code.
        from cs2pov.domain.job import JobIssue

        return JobIssue(
            self.code,
            self.severity,
            self.message_zh,
            self.suggestion_zh,
            self.logical_path,
        )
