from __future__ import annotations

import os
from typing import Any

import httpx


OPENCLAW_BASE_URL = os.getenv(
    "OPENCLAW_BASE_URL",
    "https://duduclaw-6a98317e.zeabur.app",
).rstrip("/")
OPENCLAW_API_TOKEN = os.getenv("OPENCLAW_API_TOKEN", "")
DEDICATED_AGENT_ID = "llm-label-assistant"
OPENCLAW_AGENT_ID = os.getenv("OPENCLAW_AGENT_ID", DEDICATED_AGENT_ID).strip() or DEDICATED_AGENT_ID
OPENCLAW_TIMEOUT_SECONDS = float(os.getenv("OPENCLAW_TIMEOUT_SECONDS", "120"))

PLATFORM_CONTROL_GUARDRAIL = """
你目前是嵌入 llm-label 資料標注平台內的「專案控制助手」，不是一般用途的 OpenClaw 主代理。

工具與資料邊界：
- 所有專案、資料列、分類任務、LLM 槽位與任務狀態，都只能以 llm-label 傳入的可信專案內容為準。
- 不得使用 OpenClaw 自身的檔案系統、Shell/Exec、Browser、Web、Memory、Session、Subagent、Cron、Gateway 或其他宿主工具來完成 llm-label 平台操作。
- 不得搜尋 OpenClaw 自己的 workspace、記憶、設定檔或本機檔案來回答 llm-label 專案問題。
- 不得自行模擬 API 呼叫、捏造執行結果，或聲稱已經修改平台。
- 平台變更只能透過本次 instructions 明確列出的 <assistant_action> 格式提出；真正執行、驗證與權限檢查由 llm-label 後端負責。
- 若使用者要求的能力不在 llm-label 提供的 action 範圍內，直接說目前平台助手尚未提供該操作，不要改用 OpenClaw 自身工具繞過限制。

你可以做的是：理解使用者意圖、閱讀 llm-label 提供的專案上下文、回答狀態問題、規劃下一步，以及在允許時提出一個結構化平台 action。
""".strip()


class OpenClawError(RuntimeError):
    pass


def _ensure_dedicated_agent() -> None:
    """Fail closed instead of silently sending platform requests to OpenClaw's main agent."""

    if OPENCLAW_AGENT_ID.lower() == "main":
        raise OpenClawError(
            "OPENCLAW_AGENT_ID 不可使用 main；請在 OpenClaw 建立專用的 "
            "llm-label-assistant，限制其工具權限後再設定 OPENCLAW_AGENT_ID。"
        )


def _effective_instructions(instructions: str) -> str:
    return f"{PLATFORM_CONTROL_GUARDRAIL}\n\n--- llm-label 專案指令 ---\n{instructions.strip()}"


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
    _ensure_dedicated_agent()
    body: dict[str, Any] = {
        "model": f"openclaw/{OPENCLAW_AGENT_ID}",
        "user": conversation_key,
        "input": message,
        "instructions": _effective_instructions(instructions),
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
    if OPENCLAW_AGENT_ID.lower() == "main":
        return {
            "configured": False,
            "reachable": False,
            "agent_id": OPENCLAW_AGENT_ID,
            "error": "請改用受限的 llm-label-assistant；main agent 不允許作為平台助手。",
        }
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
