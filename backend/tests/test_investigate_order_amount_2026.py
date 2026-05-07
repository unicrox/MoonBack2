from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api import investigate
from tools.jinxi_order_api.provider import JinxiOrderGetRequest


class FakeRepository:
    investigations: dict[int, dict] = {}
    points: dict[int, dict] = {}
    next_investigation_id = 1
    next_point_id = 1

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return None

    @classmethod
    def reset(cls):
        cls.investigations = {
            1: {
                "investigation_id": 1,
                "investigation_name": "2026 order amount test",
            }
        }
        cls.points = {
            1: {
                "point_id": 1,
                "investigation_id": 1,
                "parent_point_id": None,
                "point_type": investigate.PointType.ROOT,
                "question": "I want to know the order amount of 2026",
                "raw_data": {},
                "conclusion": "",
                "reason": "",
                "status": investigate.PointStatus.PROCESSING,
                "error": "",
            }
        }
        cls.next_investigation_id = 2
        cls.next_point_id = 2

    def create(self, table: str, data=None, *, returning=None):
        data = dict(data or {})
        if table == investigate._INVESTIGATIONS_TABLE:
            row = {
                "investigation_id": self.__class__.next_investigation_id,
                "investigation_name": data.get("investigation_name", ""),
            }
            self.__class__.next_investigation_id += 1
            self.__class__.investigations[row["investigation_id"]] = row
            return [row] if returning else 1

        if table == investigate._POINTS_TABLE:
            row = {
                "point_id": self.__class__.next_point_id,
                "point_type": "root",
                "question": "",
                "raw_data": {},
                "conclusion": "",
                "parent_point_id": None,
                "investigation_id": None,
                "reason": "",
                "status": "idle",
                "error": "",
                **data,
            }
            self.__class__.next_point_id += 1
            self.__class__.points[row["point_id"]] = row
            return [row] if returning else 1

        raise AssertionError(f"Unexpected create table: {table}")

    def read(self, table: str, *, where=None, params=None, order_by=None, limit=100, columns="*"):
        params = tuple(params or ())
        if table == investigate._INVESTIGATIONS_TABLE:
            if where == "investigation_id = %s":
                row = self.__class__.investigations.get(params[0])
                return [row] if row else []
            return list(self.__class__.investigations.values())

        if table == investigate._POINTS_TABLE:
            rows = list(self.__class__.points.values())
            if where == "point_id = %s":
                rows = [row for row in rows if row["point_id"] == params[0]]
            elif where == "parent_point_id = %s":
                rows = [row for row in rows if row["parent_point_id"] == params[0]]
            elif where == "investigation_id = %s":
                rows = [row for row in rows if row["investigation_id"] == params[0]]
            elif where is not None:
                raise AssertionError(f"Unexpected points where clause: {where}")

            if order_by:
                rows = sorted(rows, key=lambda row: row[order_by])
            if limit is not None:
                rows = rows[:limit]
            return rows

        raise AssertionError(f"Unexpected read table: {table}")

    def update(self, table: str, data, where: str, params=None, *, returning=None):
        params = tuple(params or ())
        if table != investigate._POINTS_TABLE or where != "point_id = %s":
            raise AssertionError(f"Unexpected update: {table} {where}")

        point_id = params[0]
        self.__class__.points[point_id].update(dict(data))
        return [self.__class__.points[point_id]] if returning else 1

    def fetch_one(self, query: str, params=None):
        params = tuple(params or ())
        if f'FROM "{investigate._POINTS_TABLE}"' in query:
            return self.__class__.points.get(params[0])
        raise AssertionError(f"Unexpected fetch_one query: {query}")


class FakeLLM:
    def parse(self, messages, response_format):
        prompt_text = "\n".join(message["content"] for message in messages)
        assert "2026" in prompt_text
        return JinxiOrderGetRequest(
            current=1,
            page_size=20,
            field_filters={
                "order_time": {
                    "gte": "2026-01-01",
                    "lte": "2026-12-31",
                }
            },
            aggregate_sum_field_code="order_amount",
            shown_field_codes=["order_amount", "order_time"],
        )

    def invoke(self, messages):
        prompt_text = "\n".join(message["content"] for message in messages)
        assert "2026" in prompt_text
        return SimpleNamespace(content="2026 年订单金额合计为 12345。")


async def fake_call_jinxi_order_get_api(request):
    payload = request.to_payload()
    result = {
        "total": 1,
        "statistics": {
            "order_amount": 12345,
        },
        "rows": [
            {
                "order_time": "2026-03-01",
                "order_amount": 12345,
            }
        ],
    }
    return payload, json.dumps(result, ensure_ascii=False), None


class InvestigateOrderAmount2026Test(IsolatedAsyncioTestCase):
    async def test_order_search_point_stores_only_api_returned_data(self):
        FakeRepository.reset()
        root_point = FakeRepository.points[1]
        investigation = FakeRepository.investigations[1]
        decision = investigate.InvestigateRouteDecision(
            action=investigate.InvestigateRouteAction.ORDER_SEARCH_NODE,
            instruction="查询 2026 年订单金额总额。",
            reason="用户想知道 2026 年订单金额，需要查询订单数据。",
        )
        state = investigate.AgentState(
            question=root_point["question"],
            route_decision=decision,
            current_investigation=investigation,
            current_point=root_point,
        ).model_dump()

        with (
            patch.object(investigate, "PostgreSQLRepository", FakeRepository),
            patch.object(investigate, "call_jinxi_order_get_api", fake_call_jinxi_order_get_api),
        ):
            result = await investigate.order_search_node(state, FakeLLM())

        assert result["error"] == ""
        created_points = [point for point in FakeRepository.points.values() if point["point_id"] != 1]
        assert len(created_points) == 1

        search_point = created_points[0]
        assert search_point["point_type"] == investigate.PointType.ORDER_SEARCH
        assert search_point["question"] == "查询 2026 年订单金额总额。"
        assert search_point["status"] == investigate.PointStatus.COMPLETED
        assert search_point["error"] == ""
        assert search_point["conclusion"] == "2026 年订单金额合计为 12345。"
        assert search_point["raw_data"] == {
            "total": 1,
            "statistics": {
                "order_amount": 12345,
            },
            "rows": [
                {
                    "order_time": "2026-03-01",
                    "order_amount": 12345,
                }
            ],
        }
        assert "request" not in search_point["raw_data"]
        assert "route_reason" not in search_point["raw_data"]

