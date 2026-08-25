"""Request and response models.

These double as the published contract: FastAPI turns them into the OpenAPI
document that gets uploaded to the RapidAPI listing, and subscribers depend on
the shape. Adding a field is safe; renaming or removing one is a breaking
change for everyone already subscribed.

Internal values the Flask endpoint happens to return -- the rewrite model name,
Stripe identifiers, the intermediate pre-clean text -- are deliberately absent.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CleanMode = Literal["careful", "thorough"]


class CleanRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"text": "A tidy draft\u200b can still carry invisible edits.",
                 "mode": "careful"}
            ]
        }
    )

    text: str = Field(
        ...,
        description="The text to clean. Send it as plain text, exactly as copied.",
    )
    mode: CleanMode = Field(
        default="careful",
        description=(
            "careful removes hidden Unicode and leaves wording untouched. "
            "thorough also rewrites the wording to remove the Claude wording "
            "pattern, and is restricted to paid plans."
        ),
    )


class Finding(BaseModel):
    codepoint: str = Field(..., description="Unicode code point, for example U+200B.")
    tag: str = Field(..., description="Short label, for example ZWSP.")
    label: str = Field(..., description="Human-readable character name.")
    note: str = Field(..., description="What the character normally does.")
    count: int = Field(..., description="Occurrences with this outcome.")
    positions: list[int] = Field(
        ...,
        description="One-based positions, listing at most the first eight.",
    )
    action: Literal["removed", "preserved"] = Field(
        ...,
        description="preserved means the mark belongs to an emoji sequence.",
    )
    sensitive: bool = Field(
        ...,
        description="True for joiners and variation selectors, which can carry meaning.",
    )


class RewriteInfo(BaseModel):
    applied: bool = Field(..., description="Whether the wording rewrite ran.")
    reason: str | None = Field(
        default=None,
        description="Why the rewrite was skipped, when applied is false.",
    )


class CleanResponse(BaseModel):
    text: str = Field(..., description="The cleaned text.")
    mode: CleanMode = Field(..., description="The mode that ran.")
    input_characters: int = Field(..., description="Length of the scanned text.")
    output_characters: int = Field(..., description="Length of the cleaned text.")
    removed_characters: int = Field(
        ..., description="Hidden characters removed. Preserved marks are not counted."
    )
    normalized: bool = Field(
        ...,
        description="True when NFC normalization also changed the text.",
    )
    findings: list[Finding] = Field(
        default_factory=list, description="One entry per code point and outcome."
    )
    rewrite: RewriteInfo | None = Field(
        default=None, description="Present only for thorough mode."
    )


class ErrorResponse(BaseModel):
    code: str = Field(..., description="Stable machine-readable error code.")
    error: str = Field(..., description="Human-readable explanation.")
