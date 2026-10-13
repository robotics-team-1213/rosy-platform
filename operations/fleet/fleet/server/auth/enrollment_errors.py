"""Classified enrollment refusal, shared by the enrollment service and its hub-link mixin."""

from __future__ import annotations


class EnrollmentError(Exception):
    """A classified refusal; never carries a code or token."""

    def __init__(self, code: str, status: int, message: str, *, reason: str | None = None,
                 retry_after: int | None = None, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.reason = reason
        self.retry_after = retry_after
        self.detail = detail or {}

    def body(self) -> dict:
        out = {"code": self.code, "message": str(self)}
        if self.reason is not None:
            out["reason"] = self.reason
        if self.retry_after is not None:
            out["retry_after"] = self.retry_after
        out.update(self.detail)
        return out
