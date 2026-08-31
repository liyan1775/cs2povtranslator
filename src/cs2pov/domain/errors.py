class DomainSchemaError(ValueError):
    def __init__(self, code: str, message: str, action: str, path: str | None = None):
        super().__init__(message); self.code=code; self.message=message; self.action=action; self.path=path
