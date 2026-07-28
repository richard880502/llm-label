import asyncio
import json
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import CurrentUser, get_current_user
from ..database import get_db
from ..llm.classifier import ALLOWED_LABELS, ALLOWED_SUBTYPES, mark_task_cancelled
from ..llm.example_selector import select_examples
from ..llm.prompt_builder import DEFAULT_TEMPLATE, build_prompt

router = APIRouter()

ACTIVE_STATUSES = ("pending", "waiting_for_agent", "running")


class CreateTaskRequest(BaseModel):
    target: Literal["pending", "all"] = "pending"
    slot: int = Field(default=1, ge=1, le=3)
    execution_mode: Literal["api", "mcp"] = "api"
    executor_name: str = ""


class LabelingResult(BaseModel):
    row_id: int
    relevance: Literal["相關", "無關"]
    labels: list[str] = []
    emotional_subtypes: list[str] = []
    reason: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)


class SubmitBatchRequest(BaseModel):
    lease_token: str
    results: list[LabelingResult]


def _status_filter(target: str) -> str:
    return "status = 'pending'" if target == "pending" else "status IN ('pending', 'corrected')"


def _get_task(conn, project_id: int, task_id: int):
    task = conn.execute(
        "SELECT * FROM tasks WHERE id=? AND project_id=?", (task_id, project_id)
    ).fetchone()
    if not task:
        raise HTTPException(404, "Task not found")
    return task


def _mcp_config(conn, project_id: int, slot: int) -> dict:
    row = conn.execute(
        "SELECT * FROM llm_configs WHERE project_id=? AND slot=?", (project_id, slot)
    ).fetchone()
    if row:
        return dict(row)
    return {
        "prompt_template": DEFAULT_TEMPLATE,
        "examples_mode": "corrected_only",
        "examples_per_label": 3,
    }


def _task_payload(conn, task_id: int) -> dict:
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else {}


def _result_source_name(task) -> str:
    """Return the human-facing executor name stored with each result snapshot."""
    executor_name = (task["executor_name"] or "").strip()
    if task["execution_mode"] == "mcp":
        if executor_name == "claude":
            return "Claude Code MCP"
        if executor_name == "codex":
            return "Codex MCP"
        return f"{executor_name} MCP" if executor_name else "MCP"
    return executor_name or f"LLM {task['slot'] or 1}"


@router.get("/{project_id}/tasks")
def list_tasks(project_id: int, _: CurrentUser = Depends(get_current_user)):
    conn = get_db()
    tasks = conn.execute(
        "SELECT * FROM tasks WHERE project_id=? ORDER BY created_at DESC, id DESC LIMIT 50",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(t) for t in tasks]


@router.post("/{project_id}/tasks")
def create_task(
    project_id: int,
    body: CreateTaskRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
):
    conn = get_db()
    proj = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not proj:
        conn.close()
        raise HTTPException(404, "Project not found")

    if body.execution_mode == "api":
        cfg_row = conn.execute(
            "SELECT * FROM llm_configs WHERE project_id=? AND slot=? AND api_url != '' AND model != ''",
            (project_id, body.slot),
        ).fetchone()
        if not cfg_row:
            conn.close()
            raise HTTPException(400, f"LLM {body.slot} 尚未設定或缺少 URL/模型")

    running = conn.execute(
        """SELECT id FROM tasks WHERE project_id=? AND slot=?
           AND status IN ('pending', 'waiting_for_agent', 'running')""",
        (project_id, body.slot),
    ).fetchone()
    if running:
        conn.close()
        raise HTTPException(400, f"結果槽 {body.slot} 已有任務執行中")

    initial_status = "pending" if body.execution_mode == "api" else "waiting_for_agent"
    executor_name = body.executor_name.strip() or ("platform-api" if body.execution_mode == "api" else "codex")
    cur = conn.execute(
        """INSERT INTO tasks
           (project_id, slot, status, total, processed, failed, created_at,
            execution_mode, executor_name, target, created_by, last_activity_at)
           VALUES (?, ?, ?, 0, 0, 0, datetime('now', 'localtime'), ?, ?, ?, ?, datetime('now', 'localtime'))""",
        (project_id, body.slot, initial_status, body.execution_mode, executor_name, body.target, user.username),
    )
    task_id = cur.lastrowid

    if body.execution_mode == "mcp":
        eligible = conn.execute(
            f"SELECT id FROM rows WHERE project_id=? AND {_status_filter(body.target)} ORDER BY source_row_number",
            (project_id,),
        ).fetchall()
        conn.executemany(
            "INSERT INTO task_items (task_id, row_id) VALUES (?, ?)",
            [(task_id, row["id"]) for row in eligible],
        )
        conn.execute("UPDATE tasks SET total=? WHERE id=?", (len(eligible), task_id))
        if not eligible:
            conn.execute(
                "UPDATE tasks SET status='done', finished_at=datetime('now', 'localtime') WHERE id=?",
                (task_id,),
            )

    conn.commit()
    task = _task_payload(conn, task_id)
    conn.close()

    if body.execution_mode == "api":
        background_tasks.add_task(
            _run_sync,
            task_id=task_id,
            project_id=project_id,
            target=body.target,
            slot=body.slot,
        )
    return task


@router.post("/{project_id}/tasks/{task_id}/claim")
def claim_task(
    project_id: int,
    task_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    conn = get_db()
    task = _get_task(conn, project_id, task_id)
    if task["execution_mode"] != "mcp":
        conn.close()
        raise HTTPException(400, "只有 MCP 任務可以由外部 Agent 領取")
    if task["status"] not in ("waiting_for_agent", "running"):
        conn.close()
        raise HTTPException(400, f"任務目前狀態為 {task['status']}，無法領取")
    claimed_by = task["claimed_by"] or user.username
    if task["claimed_by"] and task["claimed_by"] != user.username:
        conn.close()
        raise HTTPException(409, f"任務已由 {task['claimed_by']} 領取")
    conn.execute(
        """UPDATE tasks SET status='running', claimed_by=?,
           last_activity_at=datetime('now', 'localtime') WHERE id=?""",
        (claimed_by, task_id),
    )
    conn.commit()
    result = _task_payload(conn, task_id)
    conn.close()
    return result


@router.get("/{project_id}/tasks/{task_id}/batch")
def get_labeling_batch(
    project_id: int,
    task_id: int,
    batch_size: int = Query(default=10, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
):
    conn = get_db()
    task = _get_task(conn, project_id, task_id)
    if task["execution_mode"] != "mcp":
        conn.close()
        raise HTTPException(400, "這不是 MCP 任務")
    if task["status"] == "waiting_for_agent":
        conn.execute(
            """UPDATE tasks SET status='running', claimed_by=?,
               last_activity_at=datetime('now', 'localtime') WHERE id=?""",
            (user.username, task_id),
        )
    elif task["status"] != "running":
        conn.close()
        raise HTTPException(400, f"任務目前狀態為 {task['status']}")
    elif task["claimed_by"] and task["claimed_by"] != user.username:
        conn.close()
        raise HTTPException(409, f"任務已由 {task['claimed_by']} 領取")

    conn.execute(
        """UPDATE task_items SET status='pending', lease_token=NULL, lease_expires_at=NULL
           WHERE task_id=? AND status='leased'
           AND lease_expires_at <= datetime('now', 'localtime')""",
        (task_id,),
    )
    items = conn.execute(
        """SELECT ti.id AS item_id, r.* FROM task_items ti
           JOIN rows r ON r.id=ti.row_id
           WHERE ti.task_id=? AND ti.status='pending'
           ORDER BY r.source_row_number LIMIT ?""",
        (task_id, batch_size),
    ).fetchall()

    if not items:
        counts = conn.execute(
            "SELECT status, COUNT(*) AS count FROM task_items WHERE task_id=? GROUP BY status",
            (task_id,),
        ).fetchall()
        by_status = {row["status"]: row["count"] for row in counts}
        if by_status.get("done", 0) >= task["total"]:
            conn.execute(
                "UPDATE tasks SET status='done', finished_at=datetime('now', 'localtime') WHERE id=?",
                (task_id,),
            )
        conn.commit()
        updated = _task_payload(conn, task_id)
        conn.close()
        return {"task": updated, "lease_token": None, "rows": [], "message": "目前沒有可領取的資料"}

    lease_token = uuid.uuid4().hex
    conn.executemany(
        """UPDATE task_items SET status='leased', lease_token=?,
           lease_expires_at=datetime('now', 'localtime', '+5 minutes') WHERE id=?""",
        [(lease_token, row["item_id"]) for row in items],
    )
    conn.execute(
        "UPDATE tasks SET claimed_by=?, last_activity_at=datetime('now', 'localtime') WHERE id=?",
        (user.username, task_id),
    )

    cfg = _mcp_config(conn, project_id, task["slot"] or 1)
    examples = select_examples(conn, project_id, cfg)
    prompt_template = cfg.get("prompt_template") or DEFAULT_TEMPLATE
    rows = [
        {
            "row_id": row["id"],
            "source_row_number": row["source_row_number"],
            "content": row["content"] or "",
            "comment": row["comment_content"] or "",
            "version": row["version"] or 0,
            "prompt": build_prompt(prompt_template, examples, row["comment_content"] or ""),
        }
        for row in items
    ]
    conn.commit()
    updated = _task_payload(conn, task_id)
    conn.close()
    return {"task": updated, "lease_token": lease_token, "lease_minutes": 5, "rows": rows}


@router.post("/{project_id}/tasks/{task_id}/batch")
def submit_labeling_batch(
    project_id: int,
    task_id: int,
    body: SubmitBatchRequest,
    user: CurrentUser = Depends(get_current_user),
):
    conn = get_db()
    task = _get_task(conn, project_id, task_id)
    if task["execution_mode"] != "mcp" or task["status"] != "running":
        conn.close()
        raise HTTPException(400, "任務目前不接受 MCP 結果")
    if task["claimed_by"] and task["claimed_by"] != user.username:
        conn.close()
        raise HTTPException(409, f"任務已由 {task['claimed_by']} 領取")

    leased = conn.execute(
        """SELECT row_id FROM task_items WHERE task_id=? AND status='leased'
           AND lease_token=? AND lease_expires_at > datetime('now', 'localtime')""",
        (task_id, body.lease_token),
    ).fetchall()
    leased_ids = {row["row_id"] for row in leased}
    result_ids = [result.row_id for result in body.results]
    if not result_ids or len(result_ids) != len(set(result_ids)):
        conn.close()
        raise HTTPException(400, "結果不可為空或包含重複 row_id")
    if not set(result_ids).issubset(leased_ids):
        conn.close()
        raise HTTPException(409, "部分資料不屬於此批次，或租約已過期")

    slot = task["slot"] or 1
    source_name = _result_source_name(task)
    llm_result_params = []
    rows_update_params = []
    task_item_params = []
    for result in body.results:
        unknown_labels = set(result.labels) - ALLOWED_LABELS
        unknown_subtypes = set(result.emotional_subtypes) - ALLOWED_SUBTYPES
        if unknown_labels or unknown_subtypes:
            conn.close()
            raise HTTPException(
                400,
                f"row {result.row_id} 含不允許的標籤：{sorted(unknown_labels | unknown_subtypes)}",
            )
        labels = json.dumps(result.labels, ensure_ascii=False)
        subtypes = json.dumps(result.emotional_subtypes, ensure_ascii=False)
        llm_result_params.append(
            (result.row_id, slot, source_name, result.relevance, labels, subtypes, result.reason)
        )
        if slot == 1:
            rows_update_params.append((result.relevance, labels, subtypes, result.reason, result.row_id))
        else:
            rows_update_params.append((result.row_id,))
        task_item_params.append((task_id, result.row_id))

    conn.executemany(
        """INSERT INTO row_llm_results
           (row_id, slot, source_name, relevance, labels, subtypes, reason, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
           ON CONFLICT (row_id, slot) DO UPDATE SET
               source_name=EXCLUDED.source_name,
               relevance=EXCLUDED.relevance,
               labels=EXCLUDED.labels,
               subtypes=EXCLUDED.subtypes,
               reason=EXCLUDED.reason,
               updated_at=EXCLUDED.updated_at""",
        llm_result_params,
    )
    if slot == 1:
        conn.executemany(
            """UPDATE rows SET ai_relevance=?, ai_labels=?, ai_emotional_subtypes=?, ai_reason=?,
               llm_updated_at=datetime('now', 'localtime') WHERE id=?""",
            rows_update_params,
        )
    else:
        conn.executemany(
            "UPDATE rows SET llm_updated_at=datetime('now', 'localtime') WHERE id=?",
            rows_update_params,
        )
    conn.executemany(
        """UPDATE task_items SET status='done', completed_at=datetime('now', 'localtime'),
           lease_token=NULL, lease_expires_at=NULL WHERE task_id=? AND row_id=?""",
        task_item_params,
    )

    processed = conn.execute(
        "SELECT COUNT(*) AS count FROM task_items WHERE task_id=? AND status='done'",
        (task_id,),
    ).fetchone()["count"]
    status = "done" if processed >= task["total"] else "running"
    finished_sql = ", finished_at=datetime('now', 'localtime')" if status == "done" else ""
    conn.execute(
        f"""UPDATE tasks SET processed=?, status=?, claimed_by=?,
            last_activity_at=datetime('now', 'localtime'){finished_sql} WHERE id=?""",
        (processed, status, user.username, task_id),
    )
    conn.commit()
    updated = _task_payload(conn, task_id)
    conn.close()
    return {"accepted": len(body.results), "task": updated}


@router.post("/{project_id}/tasks/{task_id}/heartbeat")
def heartbeat_task(
    project_id: int,
    task_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    conn = get_db()
    task = _get_task(conn, project_id, task_id)
    if task["status"] not in ("waiting_for_agent", "running"):
        conn.close()
        raise HTTPException(400, "任務已不在執行中")
    conn.execute(
        "UPDATE tasks SET last_activity_at=datetime('now', 'localtime'), claimed_by=? WHERE id=?",
        (user.username, task_id),
    )
    conn.commit()
    updated = _task_payload(conn, task_id)
    conn.close()
    return updated


@router.post("/{project_id}/tasks/{task_id}/cancel")
def cancel_task(project_id: int, task_id: int, _: CurrentUser = Depends(get_current_user)):
    conn = get_db()
    task = _get_task(conn, project_id, task_id)
    if task["status"] not in ACTIVE_STATUSES:
        conn.close()
        raise HTTPException(400, "只能停止等待中或執行中的任務")
    if task["execution_mode"] == "api":
        mark_task_cancelled(task_id)
    conn.execute(
        """UPDATE tasks SET status='cancelled', error='使用者手動停止',
           finished_at=datetime('now', 'localtime'), last_activity_at=datetime('now', 'localtime')
           WHERE id=?""",
        (task_id,),
    )
    conn.commit()
    result = _task_payload(conn, task_id)
    conn.close()
    return result


@router.delete("/{project_id}/tasks/{task_id}")
def delete_task(project_id: int, task_id: int, _: CurrentUser = Depends(get_current_user)):
    conn = get_db()
    task = _get_task(conn, project_id, task_id)
    if task["status"] in ACTIVE_STATUSES:
        conn.close()
        raise HTTPException(400, "請先停止任務再刪除")
    conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/{project_id}/tasks/{task_id}")
def get_task(project_id: int, task_id: int, _: CurrentUser = Depends(get_current_user)):
    conn = get_db()
    task = _get_task(conn, project_id, task_id)
    result = dict(task)
    conn.close()
    return result


def _run_sync(task_id: int, project_id: int, target: str, slot: int) -> None:
    from ..llm.classifier import run_classification_task

    asyncio.run(
        run_classification_task(
            task_id=task_id,
            project_id=project_id,
            target=target,
            slot=slot,
        )
    )
