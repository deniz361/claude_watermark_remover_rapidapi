"""Error type that renders the same JSON shape as the existing Flask API."""

from __future__ import annotations

from fastapi import HTTPException


class ApiError(HTTPException):
    """An error carrying a stable machine-readable ``code``.

    Consumers on a marketplace cannot be asked to parse prose, and the codes
    here match the ones the Flask endpoint already returns so a caller can
    switch between the two without rewriting their error handling.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code

    @property
    def payload(self) -> dict[str, str]:
        return {"code": self.code, "error": str(self.detail)}
