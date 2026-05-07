from __future__ import annotations

import json
import asyncio
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

import app_secrets


_TOOL_DIR = Path(__file__).resolve().parent
_SUPER_FUNCTION_SCHEMA_PATH = _TOOL_DIR / "super_function_schema.md"
_ENDPOINT_GET_PATH = _TOOL_DIR / "endpoint_get.md"
JINXI_ORDER_GET_URL = "https://run.amos-tech.cn/get"


def get_order_api_context_prompt() -> str:
    super_function_schema = _SUPER_FUNCTION_SCHEMA_PATH.read_text(encoding="utf-8")
    endpoint_get = _ENDPOINT_GET_PATH.read_text(encoding="utf-8")

    return (
        "你需要根据用户的调查目标，生成一个用于查询线上订单接口的结构化请求。\n"
        "只能使用下面资料中存在的字段、查询方式和接口约定，不要编造字段。\n\n"
        "# 订单表字段结构\n"
        f"{super_function_schema}\n\n"
        "# 线上查询接口说明\n"
        f"{endpoint_get}\n\n"
        "生成请求时请遵守：\n"
        "- 固定使用 model_code=\"super_function\"。\n"
        "- 默认使用 without_meta=true，除非确实需要元信息。\n"
        "- 优先填写 shown_field_codes，减少返回数据量。\n"
        "- 如果要统计数量或分组，使用 with_total_count、aggregate_id_field_code 等统计参数。\n"
        "- 如果查询时间范围，优先使用订单字段中的日期字段，例如 event_date、order_time、created_at。\n"
        "- 输出必须是可直接用于 /get 接口 JSON body 的结构化结果。"
    )


class JinxiOrderGetRequest(BaseModel):
    record_id: str | None = Field(default=None, description="Order record id for detail query. Do not use pagination with this.")
    current: int = Field(default=1, description="Page number for list query.")
    page_size: int = Field(default=20, description="Page size for list query.")
    field_filters: dict[str, Any] | None = Field(default=None, description="Field filters for the /get query.")
    field_sorts: dict[str, str] | None = Field(default=None, description="Field sort directions, such as {'event_date': 'desc'}.")
    shown_field_codes: list[str] = Field(default_factory=list, description="Fields to return in the response.")
    aggregate_id_field_code: str | None = Field(default=None, description="Field code used for grouped statistics.")
    aggregate_sum_field_code: str | None = Field(default=None, description="Single field code used for sum statistics.")
    aggregate_sum_field_codes: list[str] = Field(default_factory=list, description="Multiple field codes used for sum statistics.")
    aggregate_where: dict[str, Any] | None = Field(default=None, description="Statistics-specific override filters.")
    is_force_statistics: bool | None = Field(default=None, description="Force statistics after pagination.")
    with_node_cnts: bool | None = Field(default=None, description="Whether to return node counts.")
    is_self_node_statistic: bool | None = Field(default=None, description="Whether to use self node statistics.")
    only_node_in_validity: bool | None = Field(default=None, description="Whether to count only valid nodes.")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model_code": "super_function",
            "without_meta": True,
        }

        if self.record_id:
            payload["_id"] = self.record_id
        else:
            payload["current"] = self.current
            payload["pageSize"] = self.page_size
            payload["with_total_count"] = True
            if self.field_filters:
                payload["field_filters"] = self.field_filters
            if self.field_sorts:
                payload["field_sorts"] = self.field_sorts
            if self.aggregate_id_field_code:
                payload["aggregate_id_field_code"] = self.aggregate_id_field_code
            if self.aggregate_sum_field_code:
                payload["aggregate_sum_field_code"] = self.aggregate_sum_field_code
            if self.aggregate_sum_field_codes:
                payload["aggregate_sum_field_codes"] = self.aggregate_sum_field_codes
            if self.aggregate_where:
                payload["aggregate_where"] = self.aggregate_where
            if self.is_force_statistics is not None:
                payload["is_force_statistics"] = self.is_force_statistics
            if self.with_node_cnts is not None:
                payload["with_node_cnts"] = self.with_node_cnts
            if self.is_self_node_statistic is not None:
                payload["is_self_node_statistic"] = self.is_self_node_statistic
            if self.only_node_in_validity is not None:
                payload["only_node_in_validity"] = self.only_node_in_validity

        if self.shown_field_codes:
            payload["shown_field_codes"] = self.shown_field_codes

        return payload


async def call_jinxi_order_get_api(
    request: JinxiOrderGetRequest,
    *,
    url: str = JINXI_ORDER_GET_URL,
    timeout: float = 30.0,
) -> tuple[dict[str, Any], str, str | None]:
    return await asyncio.to_thread(
        _call_jinxi_order_get_api_sync,
        request,
        url=url,
        timeout=timeout,
    )


def _call_jinxi_order_get_api_sync(
    request: JinxiOrderGetRequest,
    *,
    url: str,
    timeout: float,
) -> tuple[dict[str, Any], str, str | None]:
    payload = request.to_payload()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "token": app_secrets.JINXI_SERVER_TMP_TOKEN,
    }
    http_request = Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(http_request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        error = f"Business API request failed ({exc.code}): {error_body}"
        return payload, error, error
    except URLError as exc:
        error = f"Business API request failed: {exc.reason}"
        return payload, error, error

    print(f"Received response from Jinxi order API: {response_body}")
    return payload, response_body, None


__all__ = [
    "JinxiOrderGetRequest",
    "call_jinxi_order_get_api",
    "get_order_api_context_prompt",
]
