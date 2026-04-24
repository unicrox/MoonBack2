import hashlib
import json
from typing import Any

import constants


def get_frontend_consts() -> dict[str, Any]:
    frontend_consts: dict[str, Any] = {}

    for name in dir(constants):
        if not name.isupper():
            continue

        value = getattr(constants, name)
        try:
            json.dumps(value)
        except TypeError:
            continue

        frontend_consts[name] = value

    return frontend_consts


def get_frontend_consts_hash(frontend_consts: dict[str, Any] | None = None) -> str:
    payload = json.dumps(
        frontend_consts if frontend_consts is not None else get_frontend_consts(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()