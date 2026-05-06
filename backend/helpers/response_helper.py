from typing import Any

from fastapi import HTTPException
from schemas.response_schemas import ErrorResponse, ResponseCode


RESPONSE_CODE_MEANINGS: dict[ResponseCode, str] = {
    ResponseCode.OK: "Success",
    ResponseCode.ERROR: "Request failed.",
}


def response_code_from_http(http_status: int) -> ResponseCode:
    if http_status >= 400:
        return ResponseCode.ERROR
    return ResponseCode.OK

class CustomException(HTTPException):
    def __init__(
        self,
        http_status: int = 400,
        code: ResponseCode = ResponseCode.ERROR,
        message: str = "Request failed.",
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=http_status,
            detail={
                "code": code,
                "message": message,
                "data": data,
            },
        )


COMMON_ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Bad request"},
    422: {"model": ErrorResponse, "description": "Validation error"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
}

SERVER_ERROR_RESPONSE = {
    500: {"model": ErrorResponse, "description": "Internal server error"},
}
