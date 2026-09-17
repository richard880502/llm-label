from __future__ import annotations

import os
from typing import Any

import httpx


OPENCLAW_BASE_URL = os.getenv(
    "OPENCLAW_BASE_URL",
    "http://service-6a9acbdc73ef6eb935f33fce",
).rstrip("/")
OPENCLAW_API_TOKEN = os.getenv("OPENCLAW_API_TOKEN", "")
OPENCLAW_AGENT_ID = os.getenv("OPENCLAW_AGENT_ID", "main")
OPENCLAW_TIMEOUT_SECONDS = float(os.getenv("OPENCLAW_TIMEOUT_SECONDS", "120"))


class OpenClawError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "x-openclaw-agent-id": OPENCLAW_AGENT_ID,
    }
    if OPENCLAW_API_TOKEN:
        headers["Authorization"] = f"Bearer {OPENCLAW_API_TOKEN}"
    return headers


def _output_text(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                texts.append(content["text"])
    return "\n".join(texts).strip()


def send_to_openclaw(
    *,
    conversation_key: str,
    message: str,
    instructions: str,
    previous_response_id: str | None,
) -> tuple[str, str | None]:
    body: dict[str, Any] = {
        "model": f"openclaw/{OPENCLAW_AGENT_ID}",
        "user": conversation_key,
        "input": message,
        "instructions": instructions,
        "max_output_tokens": 1600,
    }
    if previous_response_id:
        body["previous_response_id"] = previous_response_id

    try:
        response = httpx.post(
            f"{OPENCLAW_BASE_URL}/v1/responses",
            headers=_headers(),
            json=body,
            timeout=httpx.Timeout(OPENCLAW_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        detail = error.response.text[:500]
        raise OpenClawError(f"OpenClaw 回傳 {error.response.status_code}: {detail}") from error
    except httpx.HTTPError as error:
        raise OpenClawError(f"無法連線 OpenClaw: {error}") from error

    payload = response.json()
    text = _output_text(payload)
    if not text:
        raise OpenClawError("OpenClaw 沒有回傳可顯示的訊息")
    return text, payload.get("id")


def openclaw_status() -> dict[str, Any]:
    try:
        response = httpx.get(
            f"{OPENCLAW_BASE_URL}/v1/models",
            headers=_headers(),
            timeout=10,
        )
        response.raise_for_status()
        return {"configured": True, "reachable": True, "agent_id": OPENCLAW_AGENT_ID}
    except httpx.HTTPError:
        return {"configured": True, "reachable": False, "agent_id": OPENCLAW_AGENT_ID}
