from __future__ import annotations

MAX_STUDENT_TURNS_PER_SESSION = 40
MAX_HINT_REQUESTS_PER_SESSION = 20
MAX_HYPOTHESIS_RECORDS_PER_SESSION = 20


class SessionResourceLimitError(RuntimeError):
    def __init__(self, resource_kind: str) -> None:
        super().__init__("session resource limit reached")
        self.resource_kind = resource_kind
