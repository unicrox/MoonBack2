
from enum import StrEnum
from functools import lru_cache, partial
from typing import Any
import json
from fastapi import APIRouter, HTTPException
from helpers.response_helper import COMMON_ERROR_RESPONSES
from fastapi.responses import StreamingResponse
from schemas.response_schemas import ResponseCode
from pydantic import BaseModel, Field
from repositories.postgresql_repository import PostgreSQLRepository
from ai.ark_model import ArkChatModel
from langgraph.graph import StateGraph, START, END
from tools.jinxi_order_api.provider import (
    JinxiOrderGetRequest,
    call_jinxi_order_get_api,
    get_order_api_context_prompt,
)
from schemas.pg_schemas import PgInvestigations, PgPoints



router = APIRouter(prefix="/agent/v2", tags=["agent_v2"])
_INVESTIGATIONS_TABLE = "investigations"
_POINTS_TABLE = "points"
_MAX_ORDER_SEARCHES = 3


## Schemas --------------------------------

class SetPointRequest(BaseModel):
    investigation_id: int | None = Field(default=None, description="The ID of the investigation to which this message belongs. If not provided, a new investigation will be created.", examples=["investigation-uuid-xxx"])
    point_id: int | None = Field(default=None, description="The ID of the point to change. If not provided, the message will be treated as a new point.", examples=["point-uuid-xxx"])
    assumption: str = Field(description="The new assumption content to update the point with.", examples=["What is the weather like today?"])
    conclusion: str = Field(description="The conclusion content to update the point with.", examples=["The assumption is supported by the available order data."])

class MakeConclusionRequest(BaseModel):
    investigation_id: int | None = Field(default=None, description="The ID of the investigation to which this message belongs. If not provided, a new investigation will be created.", examples=["investigation-uuid-xxx"])
    point_id: int | None = Field(default=None, description="The ID of the point to change. If not provided, the message will be treated as a new point.", examples=["point-uuid-xxx"])
    assumption: str = Field(description="The new assumption content to update the point with.", examples=["What is the weather like today?"])
    token: str = Field(description="Auth token forwarded to the business server API.", examples=["lighting-designer-token-xxx"])


class DeltaPointAction(StrEnum):
    ERROR = "error"
    NEW = "new"
    UPDATE = "update"
    DELETE = "delete"


class DeltaPoint(BaseModel):
    action: DeltaPointAction = Field(description="The type of change to apply to the point.")
    question: str | None = Field(default=None, description="The updated question content for this point.")
    reply: str | None = Field(default=None, description="The updated reply content for this point.")


class InvestigateRouteAction(StrEnum):
    SEARCH_ORDERS = "search_orders"
    CONCLUSION = "conclusion"


class InvestigateRouteDecision(BaseModel):
    action: InvestigateRouteAction = Field(..., description="Whether the agent should search order data again or proceed to final reply.")
    instruction: str = Field(..., description="Concrete next-step instruction for the node selected by action.")
    reason: str = Field(..., description="A brief user-safe rationale for this routing decision. Do not include hidden reasoning.")


class InvestigateAgentState(BaseModel):
    assumption: str = Field(description="The assumption content from the point table.")
    is_thinking: bool = Field(default=True, description="Whether the agent is currently processing/thinking.")
    error: str = Field(default="", description="Any error message if an error occurred during processing.")
    route_decision: InvestigateRouteDecision | None = Field(default=None, description="The latest routing decision.")
    current_investigation: PgInvestigations | None = Field(default=None, description="The latest investigation state from the database.")
    current_point: PgPoints | None = Field(default=None, description="The latest point state from the database.")


## Endpoints --------------------------------

@router.get(
    "/investigation_and_its_points/{investigation_id}", 
    responses=COMMON_ERROR_RESPONSES,
)
async def get_investigation(investigation_id: int) -> dict[str, Any]:
    pass

@router.post(
    "/set_point",
    responses=COMMON_ERROR_RESPONSES,
)
async def set_point(req: SetPointRequest):
    pass

@router.post(
    "/make_conclusion",
    responses=COMMON_ERROR_RESPONSES,
)
async def make_conclusion(req: MakeConclusionRequest) -> StreamingResponse:
    # - process input -
    def _auto_complete_investigation(
        repository: PostgreSQLRepository,
        investigation_id: int | None,
    ) -> PgInvestigations:
        if investigation_id is not None:
            rows = repository.read(
                _INVESTIGATIONS_TABLE,
                where="investigation_id = %s",
                params=(investigation_id,),
                limit=1,
            )
            if rows:
                return PgInvestigations.model_validate(rows[0])

        rows = repository.create(_INVESTIGATIONS_TABLE, returning="*")
        if not rows or not isinstance(rows, list):
            raise HTTPException(status_code=500, detail="Failed to create investigation.")
        return PgInvestigations.model_validate(rows[0])

    def _auto_complete_point(
        repository: PostgreSQLRepository,
        point_id: int | None,
        investigation_id: int,
    ) -> PgPoints:
        if point_id is not None:
            rows = repository.read(
                _POINTS_TABLE,
                where="point_id = %s",
                params=(point_id,),
                limit=1,
            )
            if rows:
                return PgPoints.model_validate(rows[0])

        rows = repository.create(
            _POINTS_TABLE,
            {"investigation_id": investigation_id},
            returning="*",
        )
        if not rows or not isinstance(rows, list):
            raise HTTPException(status_code=500, detail="Failed to create point.")
        return PgPoints.model_validate(rows[0])

    with PostgreSQLRepository() as repository:
        current_investigation = _auto_complete_investigation(
            repository,
            req.investigation_id,
        )
        current_point = _auto_complete_point(
            repository,
            req.point_id,
            current_investigation.investigation_id,
        )

    assumption = req.assumption.strip() if req.assumption else ""
    if not assumption:
        raise HTTPException(status_code=400, detail="assumption must not be empty.")

    token = req.token.strip() if req.token else ""
    if not token:        
        raise HTTPException(status_code=400, detail="token must not be empty.")

    initial_state = InvestigateAgentState(
            assumption=assumption,
            is_thinking=True,
            error="",
            current_investigation=current_investigation,
            current_point=current_point,
    )

    # - business logic -
    async def event_stream():
        graph = build_investigation_graph()
        yield ("agent_state", state_to_response(initial_state))
        try:
            async for chunk in graph.astream(
                initial_state,
                stream_mode="updates",
            ):
                node_name, update = next(iter(chunk.items()))
                yield (node_name, state_to_response(update))
        except Exception as exc:
            yield (
                "error",
                DeltaPoint(
                    code=ResponseCode.ERROR,
                    error=str(exc),
                    is_thinking=False,
                    reply=None,
                ),
            )

        async for event_name, chunk in stream_chat_to_agent_v2(message):
            yield (
                f"event: {event_name}\n"
                f"data: {json.dumps(chunk.model_dump(), ensure_ascii=False)}\n\n"
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


## LLM Graph --------------------------------

@lru_cache(maxsize=1)
def build_investigation_graph():
    llm = ArkChatModel()

    graph = StateGraph(InvestigateAgentState)
    graph.add_node("route_node", partial(route_node, llm=llm))
    graph.add_node("order_search_node", partial(order_search_node, llm=llm))
    graph.add_node("conclusion_node", partial(conclusion_node, llm=llm))

    graph.add_edge(START, "route_node")
    graph.add_conditional_edges(
        "route_node",
        _route_after_route,
        {"order_search_node": "order_search_node", "conclusion_node": "conclusion_node"},
    )
    graph.add_edge("order_search_node", "route_node")
    graph.add_edge("conclusion_node", END)

    return graph.compile()

def _route_after_route(state: InvestigateAgentState) -> str:
    decision = state.get("route_decision")
    if (
        decision
        and decision.action == InvestigateRouteAction.SEARCH_ORDERS
        and state.get("order_search_count", 0) < _MAX_ORDER_SEARCHES
    ):
        return "order_search_node"
    return "conclusion_node"


#### Nodes --------------------------------


async def route_node(state: InvestigateAgentState, llm: ArkChatModel) -> dict:
    assumption = state["assumption"]
    _ROUTE_INSTRUCTION = (
        "你是一个调查助手的路由决策器，只负责判断下一步应该执行哪类动作。\n\n"
        "可选动作：\n"
        "1. search_orders：当用户的假设、问题或待验证内容需要查询订单/业务数据后才能判断时选择。\n"
        "2. conclusion：当用户输入已经足够生成结论、回复或澄清，不需要再查询订单数据时选择。\n\n"
        "判断规则：\n"
        "- 如果需要订单列表、订单详情、客户购买记录、交付状态、金额、时间、商品、服务记录等业务数据来验证或回答，选择 search_orders。\n"
        "- 如果用户只是表达假设、要求总结、要求解释、信息不足且无法通过订单查询直接补全，选择 conclusion。\n"
        "- 不要编造订单信息；无法确定但可能依赖订单事实时，优先选择 search_orders。\n"
        "- instruction 必须给出下一步代理应该执行的具体任务，且要和 action 匹配。\n"
        "- 当 action 为 search_orders 时，instruction 应说明要查什么订单数据，例如查询今年订单、统计订单数量、检查客户购买记录等。\n"
        "- 当 action 为 conclusion 时，instruction 应说明如何基于现有信息回复或总结。\n"
        "- reason 必须使用简洁中文说明决策原因。"
    )
    user_message = (
        "请判断下面用户输入的下一步路由动作。\n\n"
        f"假设：\n{assumption}"
    )

    try:
        decision = llm.parse(
            messages=[
                {"role": "system", "content": _ROUTE_INSTRUCTION},
                {"role": "user", "content": user_message},
            ],
            response_format=InvestigateRouteDecision,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to route agent v2: {exc}") from exc

    if decision is None or not decision.instruction.strip() or not decision.reason.strip():
        raise HTTPException(status_code=500, detail="Agent v2 route decision is empty.")

    return {"route_decision": decision, "is_thinking": True}


async def order_search_node(state: InvestigateAgentState, llm: ArkChatModel) -> dict:
    assumption = state["assumption"]
    decision = state.get("route_decision")
    if decision is None:
        raise HTTPException(status_code=500, detail="Agent v2 route decision is missing.")

    _ORDER_SEARCH_PROMPT = get_order_api_context_prompt()
    user_message = (
        "请根据调查假设和路由指令，生成一个线上订单 /get 接口查询请求。\n\n"
        f"调查假设：\n{assumption}\n\n"
        f"路由指令：\n{decision.instruction}\n\n"
        f"路由原因：\n{decision.reason}"
    )
    try:
        search_request = llm.parse(
            messages=[
                {"role": "system", "content": _ORDER_SEARCH_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format=JinxiOrderGetRequest,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build order search request: {exc}") from exc

    if search_request is None:
        raise HTTPException(status_code=500, detail="Agent v2 order search request is empty.")

    _payload, _result_text, error = call_jinxi_order_get_api(search_request)

    return {
        "order_search_count": state.get("order_search_count", 0) + 1,
        "error": error or "",
        "is_thinking": True,
    }


## Helper functions --------------------------------

def state_to_response(state: AgentV2State | None) -> AgentV2MessageResponse:
    return AgentV2MessageResponse(
        code=ResponseCode.OK,
        error=(state or {}).get("error") or None,
        is_thinking=bool((state or {}).get("is_thinking")),
        reply=None,
    )
