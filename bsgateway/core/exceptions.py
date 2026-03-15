from __future__ import annotations


class DuplicateError(Exception):
    """Raised when a unique constraint violation occurs."""

    def __init__(self, message: str = "Duplicate resource") -> None:
        self.message = message
        super().__init__(self.message)
