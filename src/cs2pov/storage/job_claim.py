from __future__ import annotations

from typing import TYPE_CHECKING

from cs2pov.domain.job import JobWriteClaim

from .job_errors import JobRepositoryError

if TYPE_CHECKING:
    from .job_repository import FileSystemJobRepository


# An incomplete claim may be a process that crashed between creating its
# directory and publishing claim.json.  A fixed grace period prevents another
# writer from treating that short publication window as an expired lease.
CLAIM_INITIALIZATION_GRACE_US = 30_000_000


class JobWriteSession:
    """An explicit, manually heartbeated lease for one Job writer."""

    def __init__(
        self,
        repository: FileSystemJobRepository,
        job_id: str,
        claim: JobWriteClaim,
    ) -> None:
        if not isinstance(claim, JobWriteClaim):
            raise TypeError("claim must be a JobWriteClaim")
        if claim.job_id != job_id:
            raise ValueError("claim job_id does not match the session")
        self.repository = repository
        self.job_id = job_id
        self.claim = claim
        self._closed = False

    def heartbeat(self) -> JobWriteClaim:
        if self._closed:
            raise JobRepositoryError(
                "job_write_interrupted",
                "写入会话已经结束。",
                "请重新取得写入权后再继续。",
                "events/.writer_claim/claim.json",
            )
        refreshed = self.repository._heartbeat_write(self.job_id, self.claim)
        self.claim = refreshed
        return refreshed

    def release(self) -> None:
        if self._closed:
            return
        self.repository._release_write(self.job_id, self.claim)
        self._closed = True

    def __enter__(self) -> JobWriteSession:
        if self._closed:
            raise JobRepositoryError(
                "job_write_interrupted",
                "写入会话已经结束。",
                "请重新取得写入权后再继续。",
                "events/.writer_claim/claim.json",
            )
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
