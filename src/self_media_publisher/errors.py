from __future__ import annotations


class PublisherError(RuntimeError):
    def __init__(self, message: str, status: str = "error", **details):
        super().__init__(message)
        self.status = status
        self.details = details
