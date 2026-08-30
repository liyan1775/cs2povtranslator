class WorkspaceError(Exception):
    """Base class for workspace path contract errors."""


class WorkspaceRootRequiredError(WorkspaceError):
    """Raised when an explicit absolute workspace root is missing or invalid."""


class WorkspaceResourcePathError(WorkspaceError):
    """Raised when a resource path is malformed."""


class WorkspacePathOutsideRootError(WorkspaceError):
    """Raised when a path would escape the workspace root."""
