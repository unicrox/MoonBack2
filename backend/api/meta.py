from fastapi import APIRouter

from schemas.response_schemas import SuccessResponse
from core.response_helper import RESPONSE_CODE_MEANINGS, SERVER_ERROR_RESPONSE

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get(
    "/response-statuses",
    response_model=SuccessResponse,
    responses=SERVER_ERROR_RESPONSE,
)
def get_response_statuses() -> SuccessResponse:
    return SuccessResponse(
        message="Response status definitions.",
        data={
            "statuses": [
                {"code": int(status), "name": status.name, "meaning": meaning}
                for status, meaning in RESPONSE_CODE_MEANINGS.items()
            ]
        },
    )
