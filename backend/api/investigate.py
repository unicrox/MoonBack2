
from enum import StrEnum
import uuid
import json
from fastapi import APIRouter, HTTPException
from matplotlib.pylab import Any
from core.response_helper import COMMON_ERROR_RESPONSES
from fastapi.responses import StreamingResponse
from schemas.response_schemas import ResponseCode
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage


router = APIRouter(prefix="/agent/v2", tags=["agent_v2"])


## Schemas --------------------------------

class ChangePointRequest(BaseModel):
    investigation_id: int | None = Field(default=None, description="The ID of the investigation to which this message belongs. If not provided, a new investigation will be created.", examples=["investigation-uuid-xxx"])
    point_id: int | None = Field(default=None, description="The ID of the point to change. If not provided, the message will be treated as a new point.", examples=["point-uuid-xxx"])
    new_question: str | None = Field(default=None, description="The new question content to update the point with. If not provided, the point's question will remain unchanged.", examples=["What is the weather like today?"])
    token: str | None = Field(default=None, description="Auth token forwarded to the business server API.", examples=["lighting-designer-token-xxx"])


class InvestigateAgentState(BaseModel):
    messages: list[HumanMessage] = Field(default_factory=list, description="The current list of messages in the conversation.")
    is_thinking: bool = Field(default=True, description="Whether the agent is currently processing/thinking.")
    error: str = Field(default="", description="Any error message if an error occurred during processing.")
    chat_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique identifier for the chat session.")
    token: str = Field(default="", description="Auth token forwarded to the business server API.")
    order_search_count: int = Field(default=0, description="Number of times order search has been performed in this conversation.")
    order_search_history: list[dict[str, Any]] = Field(default_factory=list, description="History of order search queries and results.")


class DeltaPoint(BaseModel):
    action: DeltaPointAction = Field(description="The type of change to apply to the point.")
    question: str | None = Field(default=None, description="The updated question content for this point.")
    reply: str | None = Field(default=None, description="The updated reply content for this point.")


class DeltaPointAction(StrEnum):
    ERROR = "error"
    NEW = "new"
    UPDATE = "update"
    DELETE = "delete"

## Endpoints --------------------------------

@router.post(
    "/change_point",
    responses=COMMON_ERROR_RESPONSES,
)
async def change_point(message: ChangePointRequest) -> StreamingResponse:
    async def event_stream():
        normalized_message = message.new_question.strip() if message.new_question else ""
        if not normalized_message:
            raise HTTPException(status_code=400, detail="new_question must not be empty.")
        
        def _get_or_create_chat_id(chat_id: str | None) -> str:
            """Get chat_id from request or generate a new UUID if not provided."""
            if not chat_id or not str(chat_id).strip():
                return str(uuid.uuid4())
            return str(chat_id).strip()

        initial_state: InvestigateAgentState = {
            "messages": [HumanMessage(content=normalized_message)],
            "is_thinking": True,
            "error": "",
            "chat_id": _get_or_create_chat_id(message.chat_id),
            "token": str(message.token or "").strip(),
            "order_search_count": 0,
            "order_search_history": [],
        }

        graph = build_agent_v2_graph()
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
def build_agent_v2_graph():
    llm = ArkChatModel()

    graph = StateGraph(AgentV2State)
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