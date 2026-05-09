
from enum import StrEnum
from functools import lru_cache, partial
from typing import Any
import asyncio
import json
import re
from fastapi import APIRouter, HTTPException
from helpers.response_helper import COMMON_ERROR_RESPONSES
from schemas.response_schemas import SuccessResponse
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


# This module implements a poll-based investigation workflow.
#
# Public API flow:
# 1. The frontend creates/updates a point with /set_point if needed.
# 2. The frontend calls /process_point_endpoint.
# 3. The endpoint returns immediately with investigation_id and point_id.
# 4. The graph continues in the background.
# 5. The frontend polls /investigation_and_its_points/{investigation_id}.
#
# Graph flow:
# - route_node chooses exactly one next action for the current point.
# - sub_question_node is root-only and creates one child question at a time.
# - order_search_node creates one order-search child point and stores API evidence.
# - conclusion_node writes the final conclusion for the current point.
router = APIRouter(tags=["investigation"])
_INVESTIGATIONS_TABLE = "investigations"
_POINTS_TABLE = "points"
_MAX_ORDER_SEARCHES = 3
_MAX_SUB_QUESTIONS = 5


## Schemas --------------------------------

class SetPointRequest(BaseModel):
    investigation_id: int | None = Field(default=None, description="The ID of the investigation to which this message belongs. If not provided, a new investigation will be created.", examples=["investigation-uuid-xxx"])
    point_id: int | None = Field(default=None, description="The ID of the point to change. If not provided, the message will be treated as a new point.", examples=["point-uuid-xxx"])
    question: str = Field(description="The new question content to update the point with.", examples=["What is the weather like today?"])
    conclusion: str = Field(description="The conclusion content to update the point with.", examples=["The question is supported by the available order data."])

class ProcessPointRequest(BaseModel):
    point_id: int | None = Field(default=None, description="The ID of the point to change. If not provided, the message will be treated as a new point.", examples=["point-uuid-xxx"])


class DeltaPointAction(StrEnum):
    ERROR = "error"
    NEW = "new"
    UPDATE = "update"
    DELETE = "delete"


class DeltaPoint(BaseModel):
    action: DeltaPointAction = Field(description="The type of change to apply to the point.")
    question: str | None = Field(default=None, description="The updated question content for this point.")
    reply: str | None = Field(default=None, description="The updated reply content for this point.")


class PointStatus(StrEnum):
    IDLE = "idle"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class PointType(StrEnum):
    ROOT = "root"
    TRUNK = "trunk"
    ORDER_SEARCH = "order_search"


class InvestigateRouteAction(StrEnum):
    SUB_QUESTION_NODE = "sub_question_node"
    ORDER_SEARCH_NODE = "order_search_node"
    CONCLUSION_NODE = "conclusion_node"


class InvestigateRouteDecision(BaseModel):
    action: InvestigateRouteAction = Field(..., description="Whether the agent should search order data again or proceed to final reply.")
    instruction: str = Field(..., description="Concrete next-step instruction for the node selected by action.")
    reason: str = Field(..., description="A brief user-safe rationale for this routing decision. Do not include hidden reasoning.")


class AgentState(BaseModel):
    question: str = Field(description="The question content from the point table.")
    is_thinking: bool = Field(default=True, description="Whether the agent is currently processing/thinking.")
    error: str = Field(default="", description="Any error message if an error occurred during processing.")
    route_decision: InvestigateRouteDecision | None = Field(default=None, description="The latest routing decision.")
    current_investigation: PgInvestigations | None = Field(default=None, description="The latest investigation state from the database.")
    current_point: PgPoints | None = Field(default=None, description="The latest point state from the database.")


## Endpoints --------------------------------

@router.get(
    "/investigations",
    response_model=SuccessResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def get_investigations(limit: int = 50) -> SuccessResponse:
    limit = min(max(limit, 1), 200)
    with PostgreSQLRepository() as repository:
        investigation_rows = repository.read(
            _INVESTIGATIONS_TABLE,
            order_by="investigation_id",
            limit=None,
        )
        investigation_rows = sorted(
            investigation_rows,
            key=lambda row: int(row.get("investigation_id") or 0),
            reverse=True,
        )[:limit]

        summaries: list[dict[str, Any]] = []
        for investigation in investigation_rows:
            investigation_id = investigation["investigation_id"]
            point_rows = repository.read(
                _POINTS_TABLE,
                where="investigation_id = %s",
                params=(investigation_id,),
                order_by="point_id",
                limit=None,
            )
            root_point = next(
                (point for point in point_rows if point.get("point_type") == PointType.ROOT),
                point_rows[0] if point_rows else None,
            )
            summaries.append(
                {
                    **investigation,
                    "root_point_id": root_point.get("point_id") if root_point else None,
                    "root_question": root_point.get("question", "") if root_point else "",
                    "root_status": root_point.get("status", "") if root_point else "",
                    "point_count": len(point_rows),
                }
            )

    return SuccessResponse(data={"investigations": summaries})


@router.get(
    "/investigation_and_its_points/{investigation_id}", 
    response_model=SuccessResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def get_investigation(investigation_id: int) -> SuccessResponse:
    # Polling endpoint: return the current persisted state only.
    # It never starts or resumes graph work.
    with PostgreSQLRepository() as repository:
        investigation_rows = repository.read(
            _INVESTIGATIONS_TABLE,
            where="investigation_id = %s",
            params=(investigation_id,),
            limit=1,
        )
        if not investigation_rows:
            raise HTTPException(status_code=404, detail="Investigation not found.")

        point_rows = repository.read(
            _POINTS_TABLE,
            where="investigation_id = %s",
            params=(investigation_id,),
            order_by="point_id",
            limit=None,
        )

    return SuccessResponse(
        data={
            "investigation": investigation_rows[0],
            "points": point_rows,
        }
    )

@router.post(
    "/set_point",
    responses=COMMON_ERROR_RESPONSES,
)
async def set_point(req: SetPointRequest):
    # Manual point upsert endpoint used by the UI/editor layer.
    # New points created here are root points unless a future endpoint adds
    # explicit child creation semantics.
    with PostgreSQLRepository() as repository:
        if req.point_id is not None:
            rows = repository.update(
                _POINTS_TABLE,
                {
                    "question": req.question,
                    "conclusion": req.conclusion,
                },
                where="point_id = %s",
                params=(req.point_id,),
                returning="*",
            )
            if not rows or not isinstance(rows, list):
                raise HTTPException(status_code=404, detail="Point not found.")
            return SuccessResponse(data={"point": rows[0]})

        investigation_id = req.investigation_id
        if investigation_id is None:
            investigation_rows = repository.create(
                _INVESTIGATIONS_TABLE,
                {"investigation_id": _next_id(repository, _INVESTIGATIONS_TABLE, "investigation_id")},
                returning="*",
            )
            if not investigation_rows or not isinstance(investigation_rows, list):
                raise HTTPException(status_code=500, detail="Failed to create investigation.")
            investigation_id = investigation_rows[0]["investigation_id"]
        else:
            investigation_rows = repository.read(
                _INVESTIGATIONS_TABLE,
                where="investigation_id = %s",
                params=(investigation_id,),
                limit=1,
            )
            if not investigation_rows:
                raise HTTPException(status_code=404, detail="Investigation not found.")

        point_rows = repository.create(
            _POINTS_TABLE,
            {
                "point_id": _next_id(repository, _POINTS_TABLE, "point_id"),
                "investigation_id": investigation_id,
                "point_type": PointType.ROOT,
                "question": req.question,
                "conclusion": req.conclusion,
                "reason": "",
                "status": PointStatus.IDLE,
                "error": "",
                "raw_data": {},
            },
            returning="*",
        )
        if not point_rows or not isinstance(point_rows, list):
            raise HTTPException(status_code=500, detail="Failed to create point.")

    return SuccessResponse(data={"point": point_rows[0]})

@router.delete(
    "/delete_child_points/{point_id}",
    response_model=SuccessResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def delete_child_points(point_id: int) -> SuccessResponse:
    # Delete every descendant of the selected point while keeping the selected
    # point itself. This lets callers clear stale investigation branches before
    # retrying a point.
    with PostgreSQLRepository() as repository:
        parent_rows = repository.read(
            _POINTS_TABLE,
            where="point_id = %s",
            params=(point_id,),
            limit=1,
        )
        if not parent_rows:
            raise HTTPException(status_code=404, detail="Point not found.")

        investigation_id = parent_rows[0].get("investigation_id")
        if investigation_id is None:
            point_rows = repository.read(
                _POINTS_TABLE,
                order_by="point_id",
                limit=None,
            )
        else:
            point_rows = repository.read(
                _POINTS_TABLE,
                where="investigation_id = %s",
                params=(investigation_id,),
                order_by="point_id",
                limit=None,
            )
        descendant_ids = _descendant_point_ids(point_id, point_rows)
        if not descendant_ids:
            return SuccessResponse(
                message="No child points to delete.",
                data={
                    "point_id": point_id,
                    "deleted_count": 0,
                    "deleted_point_ids": [],
                },
            )

        deleted_rows = repository.fetch_all(
            f'DELETE FROM "{_POINTS_TABLE}" WHERE point_id = ANY(%s) RETURNING point_id',
            (descendant_ids,),
        )

    deleted_point_ids = sorted(int(row["point_id"]) for row in deleted_rows)
    return SuccessResponse(
        message="Child points deleted.",
        data={
            "point_id": point_id,
            "deleted_count": len(deleted_point_ids),
            "deleted_point_ids": deleted_point_ids,
        },
    )

@router.delete(
    "/delete_investigation_and_child_points/{investigation_id}",
    response_model=SuccessResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def delete_investigation_and_child_points(investigation_id: int) -> SuccessResponse:
    with PostgreSQLRepository() as repository:
        investigation_rows = repository.read(
            _INVESTIGATIONS_TABLE,
            where="investigation_id = %s",
            params=(investigation_id,),
            limit=1,
        )
        if not investigation_rows:
            raise HTTPException(status_code=404, detail="Investigation not found.")

        deleted_point_rows = repository.fetch_all(
            f'DELETE FROM "{_POINTS_TABLE}" WHERE investigation_id = %s RETURNING point_id',
            (investigation_id,),
        )
        deleted_investigation_rows = repository.delete(
            _INVESTIGATIONS_TABLE,
            where="investigation_id = %s",
            params=(investigation_id,),
            returning="investigation_id",
        )

    if not deleted_investigation_rows or not isinstance(deleted_investigation_rows, list):
        raise HTTPException(status_code=500, detail="Failed to delete investigation.")

    deleted_point_ids = sorted(int(row["point_id"]) for row in deleted_point_rows)
    return SuccessResponse(
        message="Investigation deleted.",
        data={
            "investigation_id": investigation_id,
            "deleted_point_count": len(deleted_point_ids),
            "deleted_point_ids": deleted_point_ids,
        },
    )

@router.post(
    "/process_point_endpoint",
    response_model=SuccessResponse,
    responses=COMMON_ERROR_RESPONSES,
)
async def process_point_endpoint(req: ProcessPointRequest) -> SuccessResponse:
    # Create/validate the processing target synchronously so the frontend has
    # stable ids to poll, then run the graph without blocking this request.
    current_investigation, current_point = _load_or_create_processing_point(req.point_id)
    asyncio.create_task(process_point(current_point.point_id))
    return SuccessResponse(
        message="Point processing scheduled.",
        data={
            "investigation_id": current_investigation.investigation_id,
            "point_id": current_point.point_id,
        },
    )


async def process_point(point_id: int | None):
    # Shared processing entrypoint.
    # HTTP endpoints schedule this with create_task; graph nodes await it when
    # they need a child point to finish before the parent can continue.
    current_point: PgPoints | None = None
    try:
        current_investigation, current_point = _load_or_create_processing_point(point_id)
        _update_point_status(
            current_point.point_id,
            status=PointStatus.PROCESSING,
            error="",
        )

        agent_state = AgentState(
            question=current_point.question,
            is_thinking=True,
            error="",
            current_investigation=current_investigation,
            current_point=current_point,
        )

        await agent_graph().ainvoke(agent_state.model_dump(), config={"recursion_limit": 50})
    except Exception as exc:
        # Background task exceptions are not returned to the original HTTP
        # request, so persist them for the polling endpoint.
        if current_point is not None:
            _update_point_status(
                current_point.point_id,
                status=PointStatus.FAILED,
                error=str(exc),
            )
        else:
            raise


## LLM Graph --------------------------------

@lru_cache(maxsize=1)
def agent_graph():
    # One compiled graph handles both root and child points. Point type and
    # parent_point_id decide which actions are valid at runtime.
    llm = ArkChatModel()

    graph = StateGraph(AgentState)
    graph.add_node("route_node", partial(route_node, llm=llm))
    graph.add_node("sub_question_node", partial(sub_question_node, llm=llm))
    graph.add_node("order_search_node", partial(order_search_node, llm=llm))
    graph.add_node("conclusion_node", partial(conclusion_node, llm=llm))

    graph.add_edge(START, "route_node")
    graph.add_conditional_edges(
        "route_node",
        _trunk_route,
        {
            "sub_question_node": "sub_question_node", 
            "order_search_node": "order_search_node", 
            "conclusion_node": "conclusion_node",
        },
    )
    graph.add_edge("sub_question_node", "route_node")
    graph.add_edge("order_search_node", "route_node")
    graph.add_edge("conclusion_node", END)

    return graph.compile()

def _trunk_route(state: AgentState) -> str:
    # Conditional edge resolver. Route action values must match graph node names.
    decision = _state_decision(state)
    if decision is None:
        raise HTTPException(status_code=500, detail="Agent route decision is missing.")
    return str(decision.action)


def leave_graph():
    pass

#### Nodes --------------------------------


async def route_node(state: AgentState, llm: ArkChatModel) -> dict:
    print(f"-- route_node -- point: {state.current_point.point_id if state.current_point else 'N/A'}, question: {state.question}")
    # Decide the next single step for the current point, using persisted child
    # points as memory from previous loop iterations.
    current_point = _load_point(_state_point(state).point_id)
    current_investigation = _state_investigation(state)
    context = _build_context(current_point, current_investigation)

    if current_point.point_type == PointType.ORDER_SEARCH:
        if current_point.status == PointStatus.PROCESSING:
            return {
                "route_decision": InvestigateRouteDecision(
                    action=InvestigateRouteAction.ORDER_SEARCH_NODE,
                    instruction=current_point.question,
                    reason="重新执行订单查询点。",
                ),
                "current_point": current_point,
                "is_thinking": True,
            }
        if current_point.status == PointStatus.FAILED:
            raise HTTPException(
                status_code=500,
                detail=current_point.error or "Order search point failed.",
            )
        # Search points are evidence leaves. After their search has been stored,
        # they should summarize/conclude instead of spawning more work.
        return {
            "route_decision": _force_conclusion_decision("订单查询点已经完成搜索流程，应该生成查询结论。"),
            "current_point": current_point,
            "is_thinking": True,
        }
    if current_point.point_type == PointType.ROOT and _question_child_count(current_point.point_id) >= _MAX_SUB_QUESTIONS:
        # Hard stop for iterative root breakdown.
        return {
            "route_decision": _force_conclusion_decision("已达到根节点可生成子问题数量上限。"),
            "current_point": current_point,
            "is_thinking": True,
        }
    if _search_child_count(current_point.point_id) >= _MAX_ORDER_SEARCHES:
        # Hard stop for endpoint-search loops under any point.
        return {
            "route_decision": _force_conclusion_decision("已达到当前节点订单查询次数上限。"),
            "current_point": current_point,
            "is_thinking": True,
        }

    if current_point.point_type == PointType.ROOT:
        action_options = (
            "1. sub_question_node：继续拆分一个新的直接子问题。\n"
            "2. order_search_node：通过订单 /get 接口查询业务数据。\n"
            "3. conclusion_node：基于已有上下文生成当前点结论。"
        )
    else:
        action_options = (
            "1. order_search_node：通过订单 /get 接口查询业务数据。\n"
            "2. conclusion_node：基于已有上下文生成当前点结论。"
        )

    _ROUTE_INSTRUCTION = (
        "你是一个调查助手的路由决策器，只负责判断下一步应该执行哪类动作。\n\n"
        f"可选动作：\n{action_options}\n\n"
        "判断规则：\n"
        "- 每次选择 sub_question_node 只代表生成一个新的子问题，不要一次性生成多个。\n"
        "- 根节点如果包含对比、多个年份、多个指标、多个条件或需要先拆分的问题，优先选择 sub_question_node，而不是直接查询订单。\n"
        "- 根节点只有在问题已经是单一、明确、可直接查询的原子问题时，才选择 order_search_node。\n"
        "- 非根节点如果需要订单列表、订单详情、客户购买记录、交付状态、金额、时间、商品、服务记录等业务数据来验证或回答，选择 order_search_node。\n"
        "- 如果已有直接子点结论、订单查询结果或当前问题信息足够，选择 conclusion_node。\n"
        "- 判断是否继续调查时，必须参考已有“直接子点”，避免重复生成已经调查过的子问题或重复查询。\n"
        "- 不要编造订单信息；无法确定但可能依赖订单事实时，优先选择 order_search_node。\n"
        "- 对于类似“比较 2026 和 2025 的订单数量和收入金额”的根节点，应依次拆分出“2026 订单数量”“2025 订单数量”“2026 收入金额”“2025 收入金额”等直接子问题；这些子问题再各自查询订单。\n"
        "- instruction 必须给出下一步代理应该执行的具体任务，且要和 action 匹配。\n"
        "- 当 action 为 sub_question_node 时，instruction 应说明下一个子问题应该补足哪一类调查缺口。\n"
        "- 当 action 为 order_search_node 时，instruction 应说明要查询什么订单数据，例如查询今年订单、统计订单数量、检查客户购买记录等。\n"
        "- 当 action 为 conclusion_node 时，instruction 应说明如何基于现有信息回复或总结。\n"
        "- reason 必须使用简洁中文说明决策原因。"
    )
    user_message = (
        "请判断当前调查点的下一步路由动作。\n\n"
        f"当前调查上下文：\n{context}"
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
        raise HTTPException(status_code=500, detail=f"Failed to route investigation: {exc}") from exc

    if decision is None or not decision.instruction.strip() or not decision.reason.strip():
        raise HTTPException(status_code=500, detail="Investigation route decision is empty.")

    if (
        current_point.point_type == PointType.ROOT
        and decision.action == InvestigateRouteAction.ORDER_SEARCH_NODE
        and _question_child_count(current_point.point_id) == 0
        and _looks_like_compound_root_question(current_point.question)
    ):
        decision = InvestigateRouteDecision(
            action=InvestigateRouteAction.SUB_QUESTION_NODE,
            instruction=(
                "当前根问题包含对比或多个指标，先生成一个直接子问题。"
                "优先补足一个可独立查询的指标，例如某一年订单数量或某一年收入金额。"
            ),
            reason="根问题不是单一原子查询，需要先拆分子问题。",
        )

    if current_point.point_type != PointType.ROOT and decision.action == InvestigateRouteAction.SUB_QUESTION_NODE:
        # Enforce root-only breakdown in code, not only in the prompt.
        decision = InvestigateRouteDecision(
            action=InvestigateRouteAction.ORDER_SEARCH_NODE,
            instruction=(
                "当前点不是根节点，不能继续拆分子问题。"
                "请基于当前问题和已有上下文查询必要的订单数据。"
            ),
            reason="非根节点禁止拆分子问题，改为订单数据调查。",
        )
    if decision.action == InvestigateRouteAction.ORDER_SEARCH_NODE and _search_child_count(current_point.point_id) >= _MAX_ORDER_SEARCHES:
        decision = _force_conclusion_decision("已达到订单查询次数上限。")

    return {"route_decision": decision, "current_point": current_point, "is_thinking": True}


async def sub_question_node(state: AgentState, llm: ArkChatModel) -> dict:
    print(f"-- sub_question_node -- point: {state.current_point.point_id if state.current_point else 'N/A'}, question: {state.question}")
    # Root-only node: generate exactly one new child question, process it to
    # completion, then return control to the root route loop.
    current_point = _load_point(_state_point(state).point_id)
    current_investigation = _state_investigation(state)
    if _question_child_count(current_point.point_id) >= _MAX_SUB_QUESTIONS:
        return {
            "route_decision": _force_conclusion_decision("已达到根节点子问题数量上限。"),
            "current_point": current_point,
            "is_thinking": True,
        }

    decision = _state_decision(state)
    context = _build_context(current_point, current_investigation)
    _SUB_QUESTION_PROMPT = (
        "你是调查助手的子问题生成器。你只能生成一个新的子问题。\n"
        "要求：\n"
        "- 只生成一个子问题，不要生成列表。\n"
        "- 子问题必须服务于回答根节点问题。\n"
        "- 必须参考已有“直接子点”，避免重复已经调查过的方向。\n"
        "- 子问题应该具体、可调查、可通过后续订单数据或已有信息回答。\n"
        "- 子问题应该是单一原子问题，一次只包含一个年份、一个指标或一个条件。\n"
        "- 如果根问题要求比较多个年份和多个指标，应按缺口逐个生成，例如先生成“2026 年订单数量是多少？”，再生成“2025 年订单数量是多少？”，再生成收入金额相关子问题。\n"
        "- 只输出子问题文本本身，不要输出 JSON、标题、编号或解释。"
    )
    user_message = (
        "请根据当前调查上下文生成一个新的直接子问题。\n\n"
        f"路由指令：\n{decision.instruction if decision else ''}\n\n"
        f"调查上下文：\n{context}"
    )

    try:
        next_question = llm.invoke([
            {"role": "system", "content": _SUB_QUESTION_PROMPT},
            {"role": "user", "content": user_message},
        ]).content
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate sub-question: {exc}") from exc

    next_question_text = _clean_text_response(next_question)
    if not next_question_text:
        raise HTTPException(status_code=500, detail="Generated sub-question is empty.")

    with PostgreSQLRepository() as repository:
        child_rows = repository.create(
            _POINTS_TABLE,
            {
                "point_id": _next_id(repository, _POINTS_TABLE, "point_id"),
                "investigation_id": current_point.investigation_id,
                "parent_point_id": current_point.point_id,
                "point_type": PointType.TRUNK,
                "question": next_question_text,
                "reason": decision.reason if decision else "",
                "status": PointStatus.PROCESSING,
                "error": "",
                "raw_data": {},
            },
            returning="*",
        )
    if not child_rows or not isinstance(child_rows, list):
        raise HTTPException(status_code=500, detail="Failed to create sub-question point.")

    await process_point(child_rows[0]["point_id"])
    # Reload the parent so the next route iteration sees any new child result.
    return {"current_point": _load_point(current_point.point_id), "is_thinking": True}


async def conclusion_node(state: AgentState, llm: ArkChatModel) -> dict:
    print(f"-- conclusion_node -- point: {state.current_point.point_id if state.current_point else 'N/A'}, question: {state.question}")
    # Final node for a point. The point remains visible to polling clients as
    # completed after its conclusion is persisted.
    current_point = _load_point(_state_point(state).point_id)
    current_investigation = _state_investigation(state)
    decision = _state_decision(state)
    context = _build_context(current_point, current_investigation)
    _CONCLUSION_PROMPT = (
        "你是调查助手的结论生成器。请根据已有上下文生成当前调查点的结论。\n"
        "要求：\n"
        "- 不要编造订单事实。\n"
        "- 根节点结论应主要基于直接子点结论和根节点自身信息。\n"
        "- 叶子节点结论应基于自身信息、直接订单查询子点结论和 raw_data。\n"
        "- 如果证据不足，请明确说明不确定性和缺口。\n"
        "- 只输出结论文本本身，不要输出 JSON、标题或解释。"
    )
    user_message = (
        "请为当前调查点生成最终结论。\n\n"
        f"结论指令：\n{decision.instruction if decision else ''}\n\n"
        f"调查上下文：\n{context}"
    )
    try:
        generated = llm.invoke([
            {"role": "system", "content": _CONCLUSION_PROMPT},
            {"role": "user", "content": user_message},
        ]).content
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate conclusion: {exc}") from exc

    conclusion = _clean_text_response(generated)
    if not conclusion:
        raise HTTPException(status_code=500, detail="Generated conclusion is empty.")

    with PostgreSQLRepository() as repository:
        repository.update(
            _POINTS_TABLE,
            {
                "conclusion": conclusion,
                "status": PointStatus.COMPLETED,
                "error": "",
            },
            where="point_id = %s",
            params=(current_point.point_id,),
        )
    return {"current_point": _load_point(current_point.point_id), "is_thinking": False}


async def order_search_node(state: AgentState, llm: ArkChatModel) -> dict:
    print(f"-- order_search_node -- point: {state.current_point.point_id if state.current_point else 'N/A'}, question: {state.question}")
    # Create one search/evidence child point for this route decision, call the
    # order API, store the result, then loop back so the parent can decide again.
    current_point = _load_point(_state_point(state).point_id)
    current_investigation = _state_investigation(state)
    decision = _state_decision(state)
    if decision is None:
        raise HTTPException(status_code=500, detail="Investigation route decision is missing.")
    is_direct_order_search_retry = current_point.point_type == PointType.ORDER_SEARCH
    if not is_direct_order_search_retry and _search_child_count(current_point.point_id) >= _MAX_ORDER_SEARCHES:
        return {
            "route_decision": _force_conclusion_decision("已达到订单查询次数上限。"),
            "current_point": current_point,
            "is_thinking": True,
        }

    context = _build_context(current_point, current_investigation)
    search_question = decision.instruction.strip() or current_point.question

    _ORDER_SEARCH_PROMPT = get_order_api_context_prompt()
    user_message = (
        "请根据调查问题和路由指令，生成一个线上订单 /get 接口查询请求。\n\n"
        f"当前调查点问题：\n{current_point.question}\n\n"
        f"路由指令：\n{decision.instruction}\n\n"
        f"路由原因：\n{decision.reason}\n\n"
        f"已有调查上下文：\n{context}"
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
        raise HTTPException(status_code=500, detail="Investigation order search request is empty.")

    if is_direct_order_search_retry:
        search_point = current_point
    else:
        with PostgreSQLRepository() as repository:
            search_point_rows = repository.create(
                _POINTS_TABLE,
                {
                    "point_id": _next_id(repository, _POINTS_TABLE, "point_id"),
                    "investigation_id": current_point.investigation_id,
                    "parent_point_id": current_point.point_id,
                    "point_type": PointType.ORDER_SEARCH,
                    "question": search_question,
                    "reason": decision.reason,
                    "status": PointStatus.PROCESSING,
                    "error": "",
                    "raw_data": {},
                },
                returning="*",
            )
        if not search_point_rows or not isinstance(search_point_rows, list):
            raise HTTPException(status_code=500, detail="Failed to create order search point.")
        search_point = PgPoints.model_validate(search_point_rows[0])

    payload, result_text, error = await call_jinxi_order_get_api(search_request)
    conclusion = _summarize_order_search(
        llm=llm,
        search_point=search_point,
        request_payload=payload,
        result_text=result_text,
        error=error,
    )

    result_json: Any
    try:
        result_json = json.loads(result_text)
    except json.JSONDecodeError:
        result_json = {"text": result_text}

    with PostgreSQLRepository() as repository:
        repository.update(
            _POINTS_TABLE,
            {
                "conclusion": conclusion,
                "status": PointStatus.FAILED if error else PointStatus.COMPLETED,
                "error": error or "",
                "raw_data": result_json,
            },
            where="point_id = %s",
            params=(search_point.point_id,),
        )

    return {
        "error": error or "",
        "current_point": _load_point(search_point.point_id if is_direct_order_search_retry else current_point.point_id),
        "is_thinking": True,
    }


#### Utils --------------------------------

def _load_or_create_processing_point(point_id: int | None) -> tuple[PgInvestigations, PgPoints]:
    # A missing point_id means "start a new investigation with a root point".
    # Existing ids are validated and loaded with their investigation row.
    with PostgreSQLRepository() as repository:
        if point_id is None:
            investigation_rows = repository.create(
                _INVESTIGATIONS_TABLE,
                {"investigation_id": _next_id(repository, _INVESTIGATIONS_TABLE, "investigation_id")},
                returning="*",
            )
            if not investigation_rows or not isinstance(investigation_rows, list):
                raise HTTPException(status_code=500, detail="Failed to create investigation.")

            current_investigation = PgInvestigations.model_validate(investigation_rows[0])
            point_rows = repository.create(
                _POINTS_TABLE,
                {
                    "point_id": _next_id(repository, _POINTS_TABLE, "point_id"),
                    "investigation_id": current_investigation.investigation_id,
                    "point_type": PointType.ROOT,
                    "reason": "",
                    "status": PointStatus.PROCESSING,
                    "error": "",
                    "raw_data": {},
                },
                returning="*",
            )
            if not point_rows or not isinstance(point_rows, list):
                raise HTTPException(status_code=500, detail="Failed to create point.")

            return current_investigation, PgPoints.model_validate(point_rows[0])

        point_rows = repository.read(
            _POINTS_TABLE,
            where="point_id = %s",
            params=(point_id,),
            limit=1,
        )
        if not point_rows:
            raise HTTPException(status_code=404, detail="Point not found.")

        investigation_id = point_rows[0].get("investigation_id")
        if investigation_id is None:
            raise HTTPException(status_code=500, detail="Point is missing investigation_id.")

        investigation_rows = repository.read(
            _INVESTIGATIONS_TABLE,
            where="investigation_id = %s",
            params=(investigation_id,),
            limit=1,
        )
        if not investigation_rows:
            raise HTTPException(status_code=404, detail="Investigation not found.")

        return (
            PgInvestigations.model_validate(investigation_rows[0]),
            PgPoints.model_validate(point_rows[0]),
        )


def _clean_text_response(content: Any) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        content = "".join(parts)
    return str(content or "").strip().strip('"').strip("'").strip()


def _update_point_status(point_id: int, *, status: PointStatus, error: str = "") -> None:
    # Status and error are first-class columns so polling clients do not need to
    # parse raw_data to render progress.
    with PostgreSQLRepository() as repository:
        repository.update(
            _POINTS_TABLE,
            {
                "status": status,
                "error": error,
            },
            where="point_id = %s",
            params=(point_id,),
        )


def _next_id(repository: PostgreSQLRepository, table: str, id_column: str) -> int:
    rows = repository.read(table, columns=id_column, order_by=id_column, limit=None)
    ids = [int(row[id_column]) for row in rows if row.get(id_column) is not None]
    return max(ids, default=0) + 1


def _state_value(state: AgentState | dict[str, Any], key: str) -> Any:
    if isinstance(state, AgentState):
        return getattr(state, key)
    return state.get(key)


def _state_point(state: AgentState | dict[str, Any]) -> PgPoints:
    # LangGraph may hand back dicts after state merging; normalize to PgPoints.
    point = _state_value(state, "current_point")
    if point is None:
        raise HTTPException(status_code=500, detail="Current point is missing.")
    return PgPoints.model_validate(point)


def _state_investigation(state: AgentState | dict[str, Any]) -> PgInvestigations:
    investigation = _state_value(state, "current_investigation")
    if investigation is None:
        raise HTTPException(status_code=500, detail="Current investigation is missing.")
    return PgInvestigations.model_validate(investigation)


def _state_decision(state: AgentState | dict[str, Any]) -> InvestigateRouteDecision | None:
    # Normalize route decisions for the same dict/Pydantic state boundary.
    decision = _state_value(state, "route_decision")
    if decision is None:
        return None
    return InvestigateRouteDecision.model_validate(decision)


def _load_point(point_id: int) -> PgPoints:
    with PostgreSQLRepository() as repository:
        row = repository.fetch_one(
            f'SELECT * FROM "{_POINTS_TABLE}" WHERE point_id = %s',
            (point_id,),
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Point not found.")
    return PgPoints.model_validate(row)


def _load_direct_children(point_id: int) -> list[PgPoints]:
    with PostgreSQLRepository() as repository:
        rows = repository.read(
            _POINTS_TABLE,
            where="parent_point_id = %s",
            params=(point_id,),
            order_by="point_id",
            limit=None,
        )
    return [PgPoints.model_validate(row) for row in rows]


def _descendant_point_ids(point_id: int, point_rows: list[dict[str, Any]]) -> list[int]:
    children_by_parent: dict[int, list[int]] = {}
    for row in point_rows:
        child_id = row.get("point_id")
        parent_id = row.get("parent_point_id")
        if child_id is None or parent_id is None:
            continue
        children_by_parent.setdefault(int(parent_id), []).append(int(child_id))

    descendant_ids: list[int] = []
    pending = list(children_by_parent.get(point_id, []))
    while pending:
        child_id = pending.pop()
        descendant_ids.append(child_id)
        pending.extend(children_by_parent.get(child_id, []))

    return descendant_ids


def _search_child_count(point_id: int) -> int:
    return sum(1 for child in _load_direct_children(point_id) if child.point_type == PointType.ORDER_SEARCH)


def _question_child_count(point_id: int) -> int:
    return sum(1 for child in _load_direct_children(point_id) if child.point_type != PointType.ORDER_SEARCH)


def _looks_like_compound_root_question(question: str) -> bool:
    normalized = question.lower()
    compound_markers = (
        " and ",
        " or ",
        "compare",
        "better than",
        " vs ",
        " versus ",
        "以及",
        "和",
        "与",
        "对比",
        "比较",
        "是否更好",
        "多个",
    )
    metric_markers = (
        "count",
        "amount",
        "income",
        "sales",
        "订单数量",
        "数量",
        "金额",
        "收入",
        "销售",
    )
    year_count = len(set(re.findall(r"\b20\d{2}\b", normalized)))
    return (
        year_count >= 2
        or sum(marker in normalized for marker in compound_markers) >= 1
        and sum(marker in normalized for marker in metric_markers) >= 2
    )


def _point_summary(point: PgPoints) -> dict[str, Any]:
    return {
        "点ID": point.point_id,
        "父点ID": point.parent_point_id,
        "点类型": point.point_type,
        "状态": point.status,
        "问题": point.question,
        "原因": point.reason,
        "结论": point.conclusion,
        "错误": point.error,
    }


def _build_context(point: PgPoints, investigation: PgInvestigations) -> str:
    # Route and generation prompts use direct children as the current point's
    # memory from earlier loop iterations.
    direct_children = _load_direct_children(point.point_id)
    context = {
        "当前点": _point_summary(point),
        "直接子点": [_point_summary(child) for child in direct_children],
        "限制": {
            "最大子问题数量": _MAX_SUB_QUESTIONS,
            "当前子问题数量": _question_child_count(point.point_id),
            "最大订单查询次数": _MAX_ORDER_SEARCHES,
            "当前订单查询次数": _search_child_count(point.point_id),
        },
    }
    return json.dumps(context, ensure_ascii=False, indent=2)


def _force_conclusion_decision(reason: str) -> InvestigateRouteDecision:
    # Guards and invalid routes collapse to conclusion instead of letting the
    # graph loop indefinitely.
    return InvestigateRouteDecision(
        action=InvestigateRouteAction.CONCLUSION_NODE,
        instruction="请基于当前已经完成的调查信息生成结论，并明确说明仍然不确定的部分。",
        reason=reason,
    )


def _summarize_order_search(
    *,
    llm: ArkChatModel,
    search_point: PgPoints,
    request_payload: dict[str, Any],
    result_text: str,
    error: str | None,
) -> str:
    # Convert raw endpoint output into a point-level conclusion that parent
    # points can use as investigation context.
    _CONCLUSION_PROMPT = (
        "你是订单查询结果总结器。请根据接口请求和结果，为这个订单查询点生成简洁结论。\n"
        "要求：\n"
        "- 不要编造接口结果中不存在的事实。\n"
        "- 如果接口失败，请说明失败原因和该查询未能提供证据。\n"
        "- 结论需要说明该查询得到的关键证据。\n"
        "- 只输出结论文本本身，不要输出 JSON、标题或解释。"
    )
    user_message = (
        f"订单查询点问题：\n{search_point.question}\n\n"
        f"接口请求：\n{json.dumps(request_payload, ensure_ascii=False, indent=2)}\n\n"
        f"接口错误：\n{error or ''}\n\n"
        f"接口结果：\n{result_text}"
    )
    generated = llm.invoke([
        {"role": "system", "content": _CONCLUSION_PROMPT},
        {"role": "user", "content": user_message},
    ]).content
    conclusion = _clean_text_response(generated)
    if not conclusion:
        if error:
            return f"订单查询失败，未能获得有效证据：{error}"
        return "订单查询已完成，但模型未能生成有效结论。"
    return conclusion
