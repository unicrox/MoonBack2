from enum import IntEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field


class ResponseCode(IntEnum):
    OK = 0
    ERROR = 1


DataT = TypeVar("DataT")


class ResponseMeta(BaseModel):
    const_hash: str | None = Field(
        default=None,
        description="Current backend public constants hash.",
    )
    consts: dict[str, Any] | None = Field(
        default=None,
        description="Public constants returned when the frontend cache is stale.",
    )


class SuccessResponse(BaseModel, Generic[DataT]):
    code: ResponseCode = Field(
        default=ResponseCode.OK,
        description="Application-level response code. See /meta/response-statuses for definitions.",
        examples=[ResponseCode.OK],
    )
    message: str | None = Field(
        default=None,
        description="Optional human-readable message for the response.",
        examples=["Operation completed successfully."],
    )
    data: DataT | None = Field(
        default=None,
        description="Optional payload containing response data.",
        examples=[{"id": 1, "name": "Alice"}],
    )
    meta: ResponseMeta | None = Field(
        default=None,
        description="Response-level metadata.",
    )


class ErrorResponse(BaseModel):
    code: ResponseCode = Field(
        description="Application-level error response code. See /meta/response-statuses for definitions.",
        examples=[ResponseCode.ERROR],
    )
    message: str = Field(
        description="Human-readable error message.",
        examples=["Only .txt files are allowed."],
    )
    data: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured details for debugging or UI display.",
        examples=[{"detail": "Invalid request payload."}],
    )
