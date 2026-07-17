"""
標注審查平台 — MCP Server

透過 HTTP 呼叫平台的 REST API，讓 Claude Code / Codex 等 agent 工具
能夠瀏覽專案、查看審查資料、比對 LLM 歧異、修正與批次核准。

認證：使用環境變數中的帳密自動登入取得 JWT，快取於記憶體，
      過期或失效（401）時自動重新登入。後端無需任何改動。

環境變數：
    ANNOTATION_API_URL     平台網址，預設 http://localhost:8080
    ANNOTATION_USERNAME    登入帳號（必填）
    ANNOTATION_PASSWORD    登入密碼（必填）
    ANNOTATION_CA_CERT     自簽憑證的根 CA 檔路徑（用 Caddy tls internal 時建議設定）
    ANNOTATION_INSECURE    設為 1/true 則跳過 TLS 憑證驗證（自簽且未提供 CA 時使用，較不安全）
"""

import json
import os
from typing import Any, Optional, Union

import httpx
from mcp.server.fastmcp import Context, FastMCP

API_URL = os.getenv("ANNOTATION_API_URL", "http://localhost:8080").rstrip("/")
USERNAME = os.getenv("ANNOTATION_USERNAME", "")
PASSWORD = os.getenv("ANNOTATION_PASSWORD", "")
CA_CERT = os.getenv("ANNOTATION_CA_CERT", "")
INSECURE = os.getenv("ANNOTATION_INSECURE", "").lower() in ("1", "true", "yes")
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

# httpx 的 verify 參數：
#   - 有指定 CA 檔 → 用該 CA 驗證（自簽但可信任，推薦）
#   - 設了 INSECURE → 完全不驗證（自簽的最省事做法，但不防中間人）
#   - 都沒有 → 預設驗證公開 CA（適用 Let's Encrypt / 一般 HTTPS）
_verify: Union[str, bool] = CA_CERT if CA_CERT else (False if INSECURE else True)

mcp = FastMCP(
    "annotation-platform",
    instructions=(
        "Use labeling tasks for batch classification: claim the task, repeatedly get a batch, "
        "classify every row strictly according to its prompt, submit the complete batch, and continue "
        "until the task reports done. Never invent labels outside the supplied schema."
    ),
    host=MCP_HOST,
    port=MCP_PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)

# 記憶體中的 JWT 快取
_token: Optional[str] = None


def _login() -> str:
    """用帳密登入取得 JWT。"""
    if not USERNAME or not PASSWORD:
        raise RuntimeError(
            "缺少認證資訊：請設定 ANNOTATION_USERNAME 與 ANNOTATION_PASSWORD 環境變數"
        )
    resp = httpx.post(
        f"{API_URL}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=30,
        verify=_verify,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"登入失敗（{resp.status_code}）：{resp.text}")
    data = resp.json()
    if data.get("requires_totp"):
        raise RuntimeError(
            "此帳號啟用了兩步驟驗證（TOTP），無法用於自動化。"
            "請改用未啟用 TOTP 的專用帳號。"
        )
    token = data.get("token")
    if not token:
        raise RuntimeError(f"登入回應缺少 token：{data}")
    return token


def _context_token(ctx: Optional[Context]) -> str:
    """Remote HTTP MCP 時沿用 Codex/Claude 傳來的 Bearer token。"""
    if ctx is None:
        return ""
    try:
        request = ctx.request_context.request
        auth = request.headers.get("authorization", "") if request is not None else ""
        return auth[7:] if auth.lower().startswith("bearer ") else ""
    except Exception:
        return ""


def _request(method: str, path: str, *, ctx: Optional[Context] = None, **kwargs) -> Any:
    """發送已認證的 API 請求，401 時自動重新登入一次。"""
    global _token
    forwarded_token = _context_token(ctx)
    if not forwarded_token and _token is None:
        _token = _login()

    def _do() -> httpx.Response:
        headers = {"Authorization": f"Bearer {forwarded_token or _token}"}
        return httpx.request(
            method, f"{API_URL}/api{path}", headers=headers, timeout=60, verify=_verify, **kwargs
        )

    resp = _do()
    if resp.status_code == 401 and not forwarded_token:
        # token 過期，重登一次再試
        _token = _login()
        resp = _do()

    if resp.status_code == 409:
        raise RuntimeError(
            "衝突（409）：這筆資料已被其他人修改，請先重新讀取最新版本再更新。"
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"API 錯誤（{resp.status_code}）：{resp.text}")
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


# ────────────────────────────────────────────────────────────
# Tools
# ────────────────────────────────────────────────────────────


@mcp.tool()
def list_projects(ctx: Context) -> str:
    """列出所有標注專案，包含每個專案的審查進度（總筆數 / 已核准 / 已修正 / 待審）。

    回傳 JSON 字串，每個專案包含 id、name、total、approved、corrected、pending。
    通常是操作任何專案前的第一步，用來取得 project id。
    """
    projects = _request("GET", "/projects", ctx=ctx)
    summary = [
        {
            "id": p["id"],
            "name": p["name"],
            "total": p.get("total", 0),
            "approved": p.get("approved") or 0,
            "corrected": p.get("corrected") or 0,
            "pending": p.get("pending") or 0,
        }
        for p in projects
    ]
    return json.dumps(summary, ensure_ascii=False, indent=2)


@mcp.tool()
def get_project(project_id: int, ctx: Context) -> str:
    """取得單一專案的詳細資訊與審查進度統計。

    參數：
        project_id  專案 ID

    回傳 JSON，含 name、total_rows、approved、corrected、pending。
    """
    project = _request("GET", f"/projects/{project_id}", ctx=ctx)
    return json.dumps(project, ensure_ascii=False, indent=2)


@mcp.tool()
def list_rows(
    project_id: int,
    status: str = "all",
    relevance: str = "all",
    q: str = "",
    disagreement: str = "all",
    page: int = 1,
    page_size: int = 50,
    ctx: Context = None,
) -> str:
    """列出某專案的審查資料，支援篩選與分頁。

    參數：
        project_id    專案 ID
        status        狀態篩選：all | pending（待審）| approved（已核准）| corrected（已修正）
        relevance     相關性篩選：all | 相關 | 無關
        q             關鍵字，搜尋留言與內文
        disagreement  歧異篩選：all | first（歧異優先排序）| only（只看有 LLM 歧異的）
        page          頁碼，從 1 開始
        page_size     每頁筆數，預設 50

    回傳 JSON，含 total（符合條件總筆數）與 items（本頁資料）。
    每筆 item 含 id、source_row_number、comment_content、相關性、標籤、status、
    llm_disagreement（1 表示多個 LLM 判斷不一致）。

    典型用法：先用 status=pending、disagreement=first 找出待審且無歧異的資料，
    再用 batch_approve 批次核准。
    """
    params = {
        "status": status,
        "relevance": relevance,
        "q": q,
        "disagreement": disagreement,
        "page": page,
        "page_size": page_size,
    }
    result = _request("GET", f"/projects/{project_id}/rows", params=params, ctx=ctx)
    items = [
        {
            "id": r["id"],
            "row_number": r["source_row_number"],
            "comment": r.get("comment_content", ""),
            "relevance": r.get("corrected_relevance") or r.get("ai_relevance"),
            "labels": _parse(r.get("corrected_labels") or r.get("ai_labels")),
            "status": r["status"],
            "llm_disagreement": bool(r.get("llm_disagreement")),
            "reviewer": r.get("reviewer_username"),
        }
        for r in result["items"]
    ]
    return json.dumps(
        {"total": result["total"], "page": result["page"], "items": items},
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def get_row(project_id: int, row_id: int, ctx: Context) -> str:
    """取得單筆資料的完整內容，包含原始留言、AI 初判、人工修正結果，
    以及各個 LLM 槽位的分析比對（用於判斷歧異）。

    參數：
        project_id  專案 ID
        row_id      資料列 ID（來自 list_rows 的 id）

    回傳 JSON，含 comment_content、content、ai_relevance、ai_labels、ai_reason、
    corrected_*（人工修正）、status、version（樂觀鎖版本號，更新時需帶回）、
    llm_results（各 LLM 槽的 relevance/labels/subtypes/reason）。
    """
    row = _request("GET", f"/projects/{project_id}/rows/{row_id}", ctx=ctx)
    detail = {
        "id": row["id"],
        "row_number": row["source_row_number"],
        "content": row.get("content", ""),
        "comment": row.get("comment_content", ""),
        "ai_relevance": row.get("ai_relevance"),
        "ai_labels": _parse(row.get("ai_labels")),
        "ai_emotional_subtypes": _parse(row.get("ai_emotional_subtypes")),
        "ai_reason": row.get("ai_reason"),
        "corrected_relevance": row.get("corrected_relevance"),
        "corrected_labels": _parse(row.get("corrected_labels")),
        "corrected_emotional_subtypes": _parse(row.get("corrected_emotional_subtypes")),
        "reviewer_note": row.get("reviewer_note"),
        "status": row["status"],
        "version": row.get("version", 0),
        "llm_results": [
            {
                "slot": lr["slot"],
                "name": lr.get("name", f"LLM {lr['slot']}"),
                "relevance": lr.get("relevance"),
                "labels": _parse(lr.get("labels")),
                "subtypes": _parse(lr.get("subtypes")),
                "reason": lr.get("reason"),
            }
            for lr in row.get("llm_results", [])
        ],
    }
    return json.dumps(detail, ensure_ascii=False, indent=2)


@mcp.tool()
def update_row(
    project_id: int,
    row_id: int,
    version: int,
    status: Optional[str] = None,
    corrected_relevance: Optional[str] = None,
    corrected_labels: Optional[list[str]] = None,
    corrected_emotional_subtypes: Optional[list[str]] = None,
    reviewer_note: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """更新單筆資料的審查結果（人工修正或核准）。

    參數：
        project_id                    專案 ID
        row_id                        資料列 ID
        version                       目前版本號（務必先用 get_row 取得，用於樂觀鎖防止覆蓋他人修改）
        status                        新狀態：approved（核准 AI 判斷）| corrected（採用人工修正）| pending
        corrected_relevance           人工修正的相關性：相關 | 無關
        corrected_labels              人工修正的標籤清單
        corrected_emotional_subtypes  人工修正的情緒子類清單
        reviewer_note                 審查備註

    只需傳入要修改的欄位。若 version 與伺服器不符會回傳衝突錯誤，
    此時請重新 get_row 取得最新版本再試。

    回傳更新後的資料 JSON。
    """
    body: dict[str, Any] = {"version": version}
    if status is not None:
        body["status"] = status
    if corrected_relevance is not None:
        body["corrected_relevance"] = corrected_relevance
    if corrected_labels is not None:
        body["corrected_labels"] = corrected_labels
    if corrected_emotional_subtypes is not None:
        body["corrected_emotional_subtypes"] = corrected_emotional_subtypes
    if reviewer_note is not None:
        body["reviewer_note"] = reviewer_note

    updated = _request(
        "PATCH", f"/projects/{project_id}/rows/{row_id}", json=body, ctx=ctx
    )
    return json.dumps(
        {"id": updated["id"], "status": updated["status"], "version": updated.get("version")},
        ensure_ascii=False,
    )


@mcp.tool()
def batch_approve(
    project_id: int,
    row_ids: Optional[list[int]] = None,
    select_all: bool = False,
    status_filter: str = "pending",
    relevance_filter: str = "all",
    q_filter: str = "",
    disagreement_filter: str = "all",
    ctx: Context = None,
) -> str:
    """批次核准多筆資料（將 status 設為 approved）。

    兩種模式擇一：
      1. 指定 ID：傳入 row_ids=[...]，只核准這些筆。
      2. 全選符合條件：設 select_all=True，並用 *_filter 指定範圍
         （與 list_rows 的篩選參數相同），核准所有符合條件的資料。

    參數：
        project_id           專案 ID
        row_ids              要核准的資料列 ID 清單（模式 1）
        select_all           是否核准所有符合篩選條件的資料（模式 2）
        status_filter        select_all 時的狀態篩選，預設 pending
        relevance_filter     select_all 時的相關性篩選
        q_filter             select_all 時的關鍵字篩選
        disagreement_filter  select_all 時的歧異篩選：all（全部）| only（僅有歧異者）
                             注意：沒有「排除歧異」選項，only 會篩出「有」歧異的資料。

    安全建議：不要自動核准有 LLM 歧異的資料。由於 select_all 無法直接「排除」
    歧異資料，要安全地只核准無歧異者，請用以下模式（模式 1，指定 ID）：
        1. 用 list_rows 逐頁取得資料，挑出 llm_disagreement=False 的 id。
        2. 把這些 id 傳入 row_ids 批次核准。
    有歧異的資料（llm_disagreement=True）應交由人工判斷，勿自動核准。

    回傳 JSON，含 updated（實際更新的筆數）。
    """
    body: dict[str, Any] = {"status": "approved"}
    if select_all:
        body.update(
            {
                "select_all": True,
                "status_filter": status_filter,
                "relevance_filter": relevance_filter,
                "q_filter": q_filter,
                "disagreement_filter": disagreement_filter,
            }
        )
    else:
        if not row_ids:
            raise RuntimeError("非全選模式必須提供 row_ids，或設 select_all=True")
        body["ids"] = row_ids

    result = _request("PATCH", f"/projects/{project_id}/rows/batch", json=body, ctx=ctx)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def list_labeling_tasks(project_id: int, ctx: Context) -> str:
    """列出專案的分類任務。優先選 execution_mode=mcp 且狀態為等待或執行中的任務。"""
    tasks = _request("GET", f"/projects/{project_id}/tasks", ctx=ctx)
    return json.dumps(tasks, ensure_ascii=False, indent=2)


@mcp.tool()
def claim_labeling_task(project_id: int, task_id: int, ctx: Context) -> str:
    """領取一個由網頁建立的 MCP 分類任務。領取後持續取得並提交批次直到完成。"""
    task = _request("POST", f"/projects/{project_id}/tasks/{task_id}/claim", ctx=ctx)
    return json.dumps(task, ensure_ascii=False, indent=2)


@mcp.tool()
def get_labeling_batch(
    project_id: int,
    task_id: int,
    batch_size: int = 10,
    ctx: Context = None,
) -> str:
    """領取下一批待分類資料。每筆都有完整 prompt；務必保留 lease_token 供提交使用。"""
    result = _request(
        "GET",
        f"/projects/{project_id}/tasks/{task_id}/batch",
        params={"batch_size": max(1, min(50, batch_size))},
        ctx=ctx,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def submit_labeling_batch(
    project_id: int,
    task_id: int,
    lease_token: str,
    results: list[dict[str, Any]],
    ctx: Context = None,
) -> str:
    """提交一整批結構化分類結果，再繼續呼叫 get_labeling_batch，直到 task.status=done。"""
    result = _request(
        "POST",
        f"/projects/{project_id}/tasks/{task_id}/batch",
        json={"lease_token": lease_token, "results": results},
        ctx=ctx,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


def _parse(val: Optional[str]) -> list[str]:
    """把資料庫中的 JSON 字串陣列解析為 list，容錯處理。"""
    if not val:
        return []
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else [str(parsed)]
    except (json.JSONDecodeError, TypeError):
        return [x.strip() for x in val.split(",") if x.strip()]


if __name__ == "__main__":
    mcp.run(transport=MCP_TRANSPORT)
