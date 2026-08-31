import asyncio
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..annotation.project_service import get_project_schema
from ..auth import CurrentUser, get_current_user
from ..database import get_db
from ..llm.classifier import (
    compatibility_projection,
    mark_task_cancelled,
    parse_response,
)
from ..llm.example_selector import select_examples
from ..llm.generic_prompt_builder import build_generic_prompt
from ..llm.prompt_policy import get_shared_prompt_template, prompt_fingerprint

router = APIRouter()

ACTIVE_STATUSES = ("pending", "waiting_for_agent", "running")


class CreateTaskRequest(BaseModel):
    target: Literal["pending", "all", "parse_failed"] = "pending"
    slot: int = Field(default=1, ge=1, le=3)
    execution_mode: Literal["api", "mcp"] = "api"
    executor_name: str = ""


class LabelingResult(BaseModel):
    """Canonical MCP result with a temporary legacy compatibility field."""

    row_id: int
    relevance: str | None = None
    labels: list[str] = Field(default_factory=list)
    # Deprecated compatibility input. Generic projects should put every selected
    # taxonomy node in labels; legacy agents may keep sending subtype names here.
    emotional_subtypes: list[str] = Field(default_factory=list)
    reason: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubmitBatchRequest(BaseModel):
    lease_token: str
    results: list[LabelingResult]


def _eligible_rows(conn, project_id: int, target: str, slot: int):
    """Return the frozen row scope for a newly created labeling task."""
    if target == "parse_failed":
        return conn.execute(
            """SELECT r.id
               FROM rows r
               JOIN row_llm_results rlr ON rlr.row_id=r.id AND rlr.slot=?
               WHERE r.project_id=? AND rlr.reason LIKE '⚠️%'
               ORDER BY r.source_row_number, r.id""",
            (slot, project_id),
        ).fetchall()

    status_filter = (
        "r.status = 'pending'"
        if target == "pending"
        else "r.status IN ('pending', 'corrected')"
    )
    return conn.execute(
        f"SELECT r.id FROM rows r WHERE r.project_id=? AND {status_filter} ORDER BY r.source_row_number, r.id",
        (project_id,),
    ).fetchall()


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
        "examples_mode": "corrected_only",
        "examples_per_label": 3,
    }


def _prompt_state(conn, project_id: int, slot: int, schema=None) -> dict:
    """Resolve the exact rule-bearing prompt state shared by API and MCP."""
    schema = schema or get_project_schema(conn, project_id)
    cfg = _mcp_config(conn, project_id, slot)
    examples = select_examples(conn, project_id, cfg)
    project = conn.execute(
        "SELECT annotation_instructions FROM projects WHERE id=?", (project_id,)
    ).fetchone()
    project_instructions = project["annotation_instructions"] if project else ""
    prompt_template = get_shared_prompt_template(conn, project_id)
    fingerprint = prompt_fingerprint(
        prompt_template,
        examples,
        project_instructions,
        schema,
    )
    return {
        "cfg": cfg,
        "examples": examples,
        "project_instructions": project_instructions,
        "prompt_template": prompt_template,
        "fingerprint": fingerprint,
        "schema": schema,
    }


def _assert_task_prompt_stable(conn, task, current_fingerprint: str) -> None:
    expected = (task["prompt_fingerprint"] or "").strip()
    if not expected:
        # Compatibility for a task created before this migration was deployed.
        conn.execute(
            "UPDATE tasks SET prompt_fingerprint=? WHERE id=?",
            (current_fingerprint, task["id"]),
        )
        return
    if expected != current_fingerprint:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROMPT_RULES_CHANGED",
                "message": "此任務建立後 Prompt、Codebook、Schema 或 few-shot 已變更；請建立新任務以避免同一任務前後規則不一致。",
                "expected_fingerprint": expected,
                "current_fingerprint": current_fingerprint,
            },
        )


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


def _mcp_result_contract(schema) -> dict:
    relevance = None
    if schema.relevance and schema.relevance.enabled:
        relevance = {
            "required": True,
            "allowed_ids": [item.id for item in schema.relevance.values],
        }
    return {
        "relevance": relevance,
        "labels": {
            "type": "array",
            "allowed_ids": [label.id for label in schema.labels if label.enabled],
        },
        "reason": {"type": "string"},
        "metadata": {"type": "object", "optional": True},
        "legacy_compatibility": {
            "emotional_subtypes": "accepted on submit but deprecated; use labels instead"
        },
    }


@router.get("/{project_id}/tasks")
def list_tasks(project_id: int, _: CurrentUser = Depends(get_current_user)):
    with get_db() as conn:
        tasks = conn.execute(
            "SELECT * FROM tasks WHERE project_id=? ORDER BY created_at DESC, id DESC LIMIT 50",
            (project_id,),
        ).fetchall()
    return [dict(t) for t in tasks]


@router.post("/{project_id}/tasks")
def create_task(
    project_id: int,
    body: CreateTaskRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
):
    with get_db() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not proj:
            raise HTTPException(404, "Project not found")

        if body.execution_mode == "api":
            cfg_row = conn.execute(
                "SELECT * FROM llm_configs WHERE project_id=? AND slot=? AND api_url != '' AND model != ''",
                (project_id, body.slot),
            ).fetchone()
            if not cfg_row:
                raise HTTPException(400, f"LLM {body.slot} 尚未設定或缺少 URL/模型")

        running = conn.execute(
            """SELECT id FROM tasks WHERE project_id=? AND slot=?
               AND status IN ('pending', 'waiting_for_agent', 'running')""",
            (project_id, body.slot),
        ).fetchone()
        if running:
            raise HTTPException(400, f"結果槽 {body.slot} 已有任務執行中")

        prompt_state = _prompt_state(conn, project_id, body.slot)
        initial_status = "pending" if body.execution_mode == "api" else "waiting_for_agent"
        executor_name = body.executor_name.strip() or (
            "platform-api" if body.execution_mode == "api" else "codex"
        )
        cur = conn.execute(
            """INSERT INTO tasks
               (project_id, slot, status, total, processed, failed, created_at,
                execution_mode, executor_name, target, created_by, last_activity_at,
                prompt_fingerprint)
               VALUES (?, ?, ?, 0, 0, 0, datetime('now', 'localtime'), ?, ?, ?, ?,
                       datetime('now', 'localtime'), ?)""",
            (
                project_id,
                body.slot,
                initial_status,
                body.execution_mode,
                executor_name,
                body.target,
                user.username,
                prompt_state["fingerprint"],
            ),
        )
        task_id = cur.lastrowid

        # MCP tasks always freeze their row scope at creation. Failure-retry API
        # tasks do the same so the durable runner resumes the exact error set.
        if body.execution_mode == "mcp" or body.target == "parse_failed":
            eligible = _eligible_rows(conn, project_id, body.target, body.slot)
            if eligible:
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
    with get_db() as conn:
        task = _get_task(conn, project_id, task_id)
        if task["execution_mode"] != "mcp":
            raise HTTPException(400, "只有 MCP 任務可以由外部 Agent 領取")
        if task["status"] not in ("waiting_for_agent", "running"):
            raise HTTPException(400, f"任務目前狀態為 {task['status']}，無法領取")
        claimed_by = task["claimed_by"] or user.username
        if task["claimed_by"] and task["claimed_by"] != user.username:
            raise HTTPException(409, f"任務已由 {task['claimed_by']} 領取")
        conn.execute(
            """UPDATE tasks SET status='running', claimed_by=?,
               last_activity_at=datetime('now', 'localtime') WHERE id=?""",
            (claimed_by, task_id),
        )
        conn.commit()
        result = _task_payload(conn, task_id)
    return result


@router.get("/{project_id}/tasks/{task_id}/batch")
def get_labeling_batch(
    project_id: int,
    task_id: int,
    batch_size: int = Query(default=10, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
):
    with get_db() as conn:
        task = _get_task(conn, project_id, task_id)
        if task["execution_mode"] != "mcp":
            raise HTTPException(400, "這不是 MCP 任務")
        if task["status"] == "waiting_for_agent":
            conn.execute(
                """UPDATE tasks SET status='running', claimed_by=?,
                   last_activity_at=datetime('now', 'localtime') WHERE id=?""",
                (user.username, task_id),
            )
        elif task["status"] != "running":
            raise HTTPException(400, f"任務目前狀態為 {task['status']}")
        elif task["claimed_by"] and task["claimed_by"] != user.username:
            raise HTTPException(409, f"任務已由 {task['claimed_by']} 領取")

        schema = get_project_schema(conn, project_id)
        schema_payload = schema.model_dump(mode="json")
        result_contract = _mcp_result_contract(schema)
        prompt_state = _prompt_state(conn, project_id, task["slot"] or 1, schema=schema)
        _assert_task_prompt_stable(conn, task, prompt_state["fingerprint"])

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
            return {
                "task": updated,
                "lease_token": None,
                "rows": [],
                "schema": schema_payload,
                "result_contract": result_contract,
                "prompt_fingerprint": prompt_state["fingerprint"],
                "message": "目前沒有可領取的資料",
            }

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

        rows = []
        for row in items:
            primary_text = row["text"] or row["comment_content"] or ""
            rows.append(
                {
                    "row_id": row["id"],
                    "source_row_number": row["source_row_number"],
                    "text": primary_text,
                    # Keep old fields while external MCP clients migrate.
                    "content": row["content"] or "",
                    "comment": row["comment_content"] or "",
                    "version": row["version"] or 0,
                    "prompt": build_generic_prompt(
                        prompt_state["prompt_template"],
                        prompt_state["examples"],
                        primary_text,
                        prompt_state["project_instructions"],
                        schema,
                    ),
                }
            )

        conn.commit()
        updated = _task_payload(conn, task_id)
    return {
        "task": updated,
        "lease_token": lease_token,
        "lease_minutes": 5,
        "schema": schema_payload,
        "result_contract": result_contract,
        "prompt_fingerprint": prompt_state["fingerprint"],
        "rows": rows,
    }


@router.post("/{project_id}/tasks/{task_id}/batch")
def submit_labeling_batch(
    project_id: int,
    task_id: int,
    body: SubmitBatchRequest,
    user: CurrentUser = Depends(get_current_user),
):
    with get_db() as conn:
        task = _get_task(conn, project_id, task_id)
        if task["execution_mode"] != "mcp" or task["status"] != "running":
            raise HTTPException(400, "任務目前不接受 MCP 結果")
        if task["claimed_by"] and task["claimed_by"] != user.username:
            raise HTTPException(409, f"任務已由 {task['claimed_by']} 領取")

        schema = get_project_schema(conn, project_id)

        leased = conn.execute(
            """SELECT row_id FROM task_items WHERE task_id=? AND status='leased'
               AND lease_token=? AND lease_expires_at > datetime('now', 'localtime')""",
            (task_id, body.lease_token),
        ).fetchall()
        leased_ids = {row["row_id"] for row in leased}
        result_ids = [result.row_id for result in body.results]
        if not result_ids or len(result_ids) != len(set(result_ids)):
            raise HTTPException(400, "結果不可為空或包含重複 row_id")
        if not set(result_ids).issubset(leased_ids):
            raise HTTPException(409, "部分資料不屬於此批次，或租約已過期")

        slot = task["slot"] or 1
        source_name = _result_source_name(task)
        llm_result_params = []
        rows_update_params = []
        task_item_params = []

        for result in body.results:
            payload = {
                "relevance": result.relevance,
                "labels": result.labels,
                "emotional_subtypes": result.emotional_subtypes,
                "reason": result.reason,
            }
            parsed = parse_response(json.dumps(payload, ensure_ascii=False), schema)
            annotation_result = parsed["annotation_result"]
            if parsed["fallback"]:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "INVALID_ANNOTATION_RESULT",
                        "row_id": result.row_id,
                        "message": annotation_result.reason,
                    },
                )

            metadata = dict(result.metadata)
            if result.confidence is not None:
                metadata.setdefault("confidence", result.confidence)
            if metadata:
                annotation_result = annotation_result.model_copy(
                    update={"metadata": metadata}
                )

            projection = compatibility_projection(schema, annotation_result)
            canonical_json = json.dumps(
                annotation_result.model_dump(mode="json"), ensure_ascii=False
            )
            labels_json = json.dumps(projection["labels"], ensure_ascii=False)
            subtypes_json = json.dumps(
                projection["emotional_subtypes"], ensure_ascii=False
            )

            llm_result_params.append(
                (
                    result.row_id,
                    slot,
                    source_name,
                    projection["relevance"],
                    labels_json,
                    subtypes_json,
                    projection["reason"],
                    canonical_json,
                )
            )
            if slot == 1:
                rows_update_params.append(
                    (
                        canonical_json,
                        projection["relevance"],
                        labels_json,
                        subtypes_json,
                        projection["reason"],
                        result.row_id,
                    )
                )
            else:
                rows_update_params.append((result.row_id,))
            task_item_params.append((task_id, result.row_id))

        conn.executemany(
            """INSERT INTO row_llm_results
               (row_id, slot, source_name, relevance, labels, subtypes, reason, result, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, datetime('now', 'localtime'))
               ON CONFLICT (row_id, slot) DO UPDATE SET
                   source_name=EXCLUDED.source_name,
                   relevance=EXCLUDED.relevance,
                   labels=EXCLUDED.labels,
                   subtypes=EXCLUDED.subtypes,
                   reason=EXCLUDED.reason,
                   result=EXCLUDED.result,
                   updated_at=EXCLUDED.updated_at""",
            llm_result_params,
        )
        if slot == 1:
            conn.executemany(
                """UPDATE rows SET prediction=?::jsonb,
                   ai_relevance=?, ai_labels=?, ai_emotional_subtypes=?, ai_reason=?,
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
        finished_sql = (
            ", finished_at=datetime('now', 'localtime')" if status == "done" else ""
        )
        conn.execute(
            f"""UPDATE tasks SET processed=?, status=?, claimed_by=?,
                last_activity_at=datetime('now', 'localtime'){finished_sql} WHERE id=?""",
            (processed, status, user.username, task_id),
        )
        conn.commit()
        updated = _task_payload(conn, task_id)
    return {"accepted": len(body.results), "task": updated}


@router.post("/{project_id}/tasks/{task_id}/heartbeat")
def heartbeat_task(
    project_id: int,
    task_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    with get_db() as conn:
        task = _get_task(conn, project_id, task_id)
        if task["status"] not in ("waiting_for_agent", "running"):
            raise HTTPException(400, "任務已不在執行中")
        conn.execute(
            "UPDATE tasks SET last_activity_at=datetime('now', 'localtime'), claimed_by=? WHERE id=?",
            (user.username, task_id),
        )
        conn.commit()
        updated = _task_payload(conn, task_id)
    return updated


@router.post("/{project_id}/tasks/{task_id}/cancel")
def cancel_task(project_id: int, task_id: int, _: CurrentUser = Depends(get_current_user)):
    with get_db() as conn:
        task = _get_task(conn, project_id, task_id)
        if task["status"] not in ACTIVE_STATUSES:
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
    return result


@router.delete("/{project_id}/tasks/{task_id}")
def delete_task(project_id: int, task_id: int, _: CurrentUser = Depends(get_current_user)):
    with get_db() as conn:
        task = _get_task(conn, project_id, task_id)
        if task["status"] in ACTIVE_STATUSES:
            raise HTTPException(400, "請先停止任務再刪除")
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
    return {"ok": True}


@router.get("/{project_id}/tasks/{task_id}")
def get_task(project_id: int, task_id: int, _: CurrentUser = Depends(get_current_user)):
    with get_db() as conn:
        task = _get_task(conn, project_id, task_id)
        result = dict(task)
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
