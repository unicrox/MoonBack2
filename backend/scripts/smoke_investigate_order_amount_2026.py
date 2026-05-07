from __future__ import annotations

import argparse
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8200"
DEFAULT_QUESTION = "I want to know the order amount of 2026"


def post_json(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    return _read_json(request)


def get_json(base_url: str, path: str) -> dict[str, Any]:
    request = Request(
        f"{base_url}{path}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    return _read_json(request)


def _read_json(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed: {exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Response is not JSON: {body}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Response JSON is not an object: {data}")
    return data


def response_data(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"Response missing data object: {response}")
    return data


def print_points(points: list[dict[str, Any]]) -> None:
    for point in points:
        print(
            "  "
            f"#{point.get('point_id')} "
            f"type={point.get('point_type')} "
            f"status={point.get('status')} "
            f"question={point.get('question')!r} "
            f"conclusion={point.get('conclusion')!r} "
            f"error={point.get('error')!r}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke test the investigation API with a 2026 order amount question.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--token", default="test-token")
    parser.add_argument("--polls", type=int, default=12)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"Creating point at {base_url} ...")
    set_response = post_json(
        base_url,
        "/set_point",
        {
            "question": args.question,
            "conclusion": "",
        },
    )
    point = response_data(set_response).get("point")
    if not isinstance(point, dict):
        raise RuntimeError(f"/set_point response missing point: {set_response}")
    point_id = point["point_id"]
    investigation_id = point["investigation_id"]
    print(f"Created investigation_id={investigation_id}, point_id={point_id}")

    print("Scheduling investigation ...")
    process_response = post_json(
        base_url,
        "/process_point_endpoint",
        {
            "point_id": point_id,
            "token": args.token,
        },
    )
    print(json.dumps(process_response, ensure_ascii=False, indent=2))

    for index in range(args.polls):
        print(f"\nPoll {index + 1}/{args.polls}")
        investigation = get_json(base_url, f"/investigation_and_its_points/{investigation_id}")
        points = investigation.get("points", [])
        if not isinstance(points, list):
            raise RuntimeError(f"Polling response missing points list: {investigation}")
        print_points(points)

        statuses = {point.get("status") for point in points}
        if points and "processing" not in statuses:
            print("\nInvestigation is no longer processing.")
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
