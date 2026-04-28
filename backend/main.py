from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
import uvicorn


from helpers.const_helper import (
    get_frontend_consts,
    get_frontend_consts_hash,
)
from helpers.response_helper import (
    CustomException,
    SERVER_ERROR_RESPONSE,
)
from api.meta import router as meta_router
from schemas.response_schemas import ErrorResponse, ResponseCode, SuccessResponse


DEV_CORS_ORIGINS = [
    # Frontend dev server port
    "http://localhost:8210",
    "http://127.0.0.1:8210",
    "https://localhost:8210",
    "https://127.0.0.1:8210",

    # remote
]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Show the local API docs URL when the backend starts.
    print("Swagger docs: http://127.0.0.1:8200/docs")
    yield


app = FastAPI(lifespan=lifespan)

# Allow the hosted frontend and local frontend dev server to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://web.amos-tech.cn",
        *DEV_CORS_ORIGINS,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(meta_router)


@app.middleware("http")
async def inject_frontend_consts_meta(request: Request, call_next):
    # Add frontend constants metadata to successful JSON responses.
    response = await call_next(request)

    content_type = response.headers.get("content-type", "")
    if request.url.path == "/ping" or "application/json" not in content_type:
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    # If the response is not valid JSON, return it unchanged.
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            background=response.background,
        )

    # Only enrich standard success responses.
    if not isinstance(payload, dict) or payload.get("code") != int(ResponseCode.OK):
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return JSONResponse(
            content=payload,
            status_code=response.status_code,
            headers=headers,
            background=response.background,
        )

    frontend_consts = get_frontend_consts()
    const_hash = get_frontend_consts_hash(frontend_consts)
    request_const_hash = request.headers.get("X-Frontend-Consts-Hash")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    # Send full constants only when the frontend has an outdated hash.
    meta["const_hash"] = const_hash
    if request_const_hash != const_hash:
        meta["consts"] = frontend_consts

    payload["meta"] = meta

    headers = dict(response.headers)
    headers.pop("content-length", None)
    return JSONResponse(
        content=payload,
        status_code=response.status_code,
        headers=headers,
        background=response.background,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(
    _request: Request, exc: HTTPException
) -> JSONResponse:
    # Normalize FastAPI and custom HTTP errors into the API response schema.
    detail = exc.detail
    if isinstance(exc, CustomException):
        code = detail.get("code", ResponseCode.ERROR)
        message = str(detail.get("message", "Request failed."))
        data_value = detail.get("data")
        data = data_value if isinstance(data_value, dict) else None
    elif isinstance(detail, str):
        code = ResponseCode.ERROR
        message = detail
        data = None
    elif isinstance(detail, dict):
        code = ResponseCode.ERROR
        message = str(detail.get("message", "Request failed."))
        data_value = detail.get("data")
        if isinstance(data_value, dict):
            data = data_value
        else:
            extra = {k: v for k, v in detail.items() if k != "message"}
            data = extra or None
    else:
        code = ResponseCode.ERROR
        message = "Request failed."
        data = {"detail": detail}

    body = ErrorResponse(
        code=code,
        message=message,
        data=data,
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump())


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Return validation errors in the same envelope as other API errors.
    body = ErrorResponse(
        code=ResponseCode.ERROR,
        message="Request validation failed.",
        data={"errors": exc.errors()},
    )
    return JSONResponse(status_code=422, content=body.model_dump())


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    # Avoid leaking internal exception details to clients.
    body = ErrorResponse(
        code=ResponseCode.ERROR,
        message="Unexpected server error.",
    )
    return JSONResponse(status_code=500, content=body.model_dump())


@app.get(
    "/",
    response_model=SuccessResponse,
    responses=SERVER_ERROR_RESPONSE,
)
def hello() -> SuccessResponse:
    return SuccessResponse(message="Welcome!")


@app.api_route(
    "/ping",
    methods=["GET"],
    response_model=SuccessResponse,
    responses=SERVER_ERROR_RESPONSE,
)
async def ping() -> SuccessResponse:
    return SuccessResponse(message="pong")


def _runtime_base_dir() -> Path:
    # PyInstaller stores bundled files in _MEIPASS when running frozen.
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


if __name__ == "__main__":
    # Keep certificate lookup compatible with both source and packaged runtime.
    cert_dir = _runtime_base_dir() / "cert"
    uvicorn_kwargs = {
        "host": "0.0.0.0",
        "port": 8200,
        # "ssl_certfile": str(cert_dir / "cert.pem"),
        # "ssl_keyfile": str(cert_dir / "key.pem"),
    }

    # Reload only works when uvicorn imports the app from source.
    if getattr(sys, "frozen", False):
        uvicorn.run(app, **uvicorn_kwargs)
    else:
        uvicorn.run("main:app", reload=True, **uvicorn_kwargs)
