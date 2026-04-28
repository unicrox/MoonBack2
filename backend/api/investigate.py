
from enum import StrEnum
from functools import lru_cache, partial
from typing import Any
import json
from fastapi import APIRouter, HTTPException
from helpers.response_helper import COMMON_ERROR_RESPONSES
from fastapi.responses import StreamingResponse
from schemas.response_schemas import ResponseCode
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage
from repositories.postgresql_repository import PostgreSQLRepository
from ai.ark_model import ArkChatModel
from langgraph.graph import StateGraph, START, END



router = APIRouter(prefix="/agent/v2", tags=["agent_v2"])
_INVESTIGATIONS_TABLE = "investigations"
_POINTS_TABLE = "points"


## Schemas --------------------------------

class PointRequestCtx(BaseModel):
    investigation_id: int | None = Field(default=None, description="The ID of the investigation to which this message belongs. If not provided, a new investigation will be created.", examples=["investigation-uuid-xxx"])
    point_id: int | None = Field(default=None, description="The ID of the point to change. If not provided, the message will be treated as a new point.", examples=["point-uuid-xxx"])
    assumption: str = Field(description="The new assumption content to update the point with.", examples=["What is the weather like today?"])
    token: str = Field(description="Auth token forwarded to the business server API.", examples=["lighting-designer-token-xxx"])


class InvestigateAgentState(BaseModel):
    messages: list[HumanMessage] = Field(default_factory=list, description="The current list of messages in the conversation.")
    is_thinking: bool = Field(default=True, description="Whether the agent is currently processing/thinking.")
    error: str = Field(default="", description="Any error message if an error occurred during processing.")


class DeltaPointAction(StrEnum):
    ERROR = "error"
    NEW = "new"
    UPDATE = "update"
    DELETE = "delete"


class DeltaPoint(BaseModel):
    action: DeltaPointAction = Field(description="The type of change to apply to the point.")
    question: str | None = Field(default=None, description="The updated question content for this point.")
    reply: str | None = Field(default=None, description="The updated reply content for this point.")


class AgentV2RouteAction(StrEnum):
    SEARCH_ORDERS = "search_orders"
    CONCLUSION = "conclusion"


## Endpoints --------------------------------

@router.post(
    "/change_point",
    responses=COMMON_ERROR_RESPONSES,
)
async def change_point(ctx: PointRequestCtx) -> StreamingResponse:
    # - process input -
    def _auto_complete_investigation_id(
        repository: PostgreSQLRepository,
        investigation_id: int | None,
    ) -> int:
        if investigation_id is not None:
            return investigation_id

        rows = repository.create(_INVESTIGATIONS_TABLE, returning="id")
        if not rows or not isinstance(rows, list) or rows[0].get("id") is None:
            raise HTTPException(status_code=500, detail="Failed to create investigation.")
        return int(rows[0]["id"])

    def _auto_complete_point_id(
        repository: PostgreSQLRepository,
        point_id: int | None,
        investigation_id: int,
    ) -> int:
        if point_id is not None:
            return point_id

        rows = repository.create(
            _POINTS_TABLE,
            {"investigation_id": investigation_id},
            returning="id",
        )
        if not rows or not isinstance(rows, list) or rows[0].get("id") is None:
            raise HTTPException(status_code=500, detail="Failed to create point.")
        return int(rows[0]["id"])

    with PostgreSQLRepository() as repository:
        investigation_id = _auto_complete_investigation_id(
            repository,
            ctx.investigation_id,
        )
        if investigation_id is None: point_id = None
        point_id = _auto_complete_point_id(
            repository,
            ctx.point_id,
            investigation_id,
        )

    assumption = ctx.assumption.strip() if ctx.assumption else ""
    if not assumption:
        raise HTTPException(status_code=400, detail="assumption must not be empty.")

    token = ctx.token.strip() if ctx.token else ""
    if not token:        
        raise HTTPException(status_code=400, detail="token must not be empty.")

    # - business logic -
    async def event_stream():

        initial_state: InvestigateAgentState = {
            "messages": [HumanMessage(content=assumption)],
            "is_thinking": True,
            "error": "",
        }

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


@router.get(
    "/investigation/{investigation_id}", 
    responses=COMMON_ERROR_RESPONSES,
)
async def get_investigation(investigation_id: int) -> dict[str, Any]:
    pass


## LLM Graph --------------------------------

@lru_cache(maxsize=1)
def build_investigation_graph():
    llm = ArkChatModel()

    graph = StateGraph(InvestigateAgentState)
    graph.add_node("route_node", partial(route_node, llm=llm))
    graph.add_node("order_search_node", partial(order_search_node, llm=llm))
    graph.add_node("reply_node", partial(reply_node, llm=llm))

    graph.add_edge(START, "route_node")
    graph.add_conditional_edges(
        "route_node",
        _route_after_route,
        {"order_search_node": "order_search_node", "reply_node": "reply_node"},
    )
    graph.add_edge("order_search_node", "route_node")
    graph.add_edge("reply_node", END)

    return graph.compile()

def _route_after_route(state: AgentV2State) -> str:
    decision = state.get("route_decision")
    if (
        decision
        and decision.action == AgentV2RouteAction.SEARCH_ORDERS
        and state.get("order_search_count", 0) < _MAX_ORDER_SEARCHES
    ):
        return "order_search_node"
    return "reply_node"


#### Nodes --------------------------------


async def route_node(state: InvestigateAgentState, llm: ArkChatModel) -> dict:
    user_message = _get_latest_user_message(state)
    route_context = 

    try:
        decision = llm.parse(
            messages=[
                {"role": "system", "content": _ROUTE_PROMPT},
                {"role": "user", "content": route_context},
            ],
            response_format=AgentV2RouteDecision,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to route agent v2: {exc}") from exc

    if decision is None or not decision.reason.strip():
        raise HTTPException(status_code=500, detail="Agent v2 route decision is empty.")

    return {"route_decision": decision, "is_thinking": True}


## Helper functions --------------------------------

def state_to_response(state: AgentV2State | None) -> AgentV2MessageResponse:
    reply = None
    for state_message in reversed((state or {}).get("messages") or []):
        if isinstance(state_message, AIMessage):
            reply = str(state_message.content).strip() or None
            break

    return AgentV2MessageResponse(
        code=ResponseCode.OK,
        error=(state or {}).get("error") or None,
        is_thinking=bool((state or {}).get("is_thinking")),
        reply=reply,
    )

def _get_latest_user_message(state: InvestigateAgentState) -> str:
    messages = state.get("messages") or []
    if not messages:
        raise HTTPException(status_code=400, detail="agent state must include at least one message.")

    for state_message in reversed(messages):
        if isinstance(state_message, HumanMessage):
            content = str(state_message.content).strip()
            if content:
                return content

    raise HTTPException(status_code=400, detail="agent state must include a non-empty user message.")
