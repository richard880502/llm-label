"""Durable, resumable execution for API labeling tasks.

The HTTP request that creates a task may disappear, and the web process may be
restarted. Progress therefore lives in PostgreSQL ``task_items`` instead of only
in Python memory. On restart, active API tasks can be submitted again safely:
completed items are skipped and only pending/expired items are processed.
"""

import asyncio
import json
import os
import threading

from ..annotation.models import AnnotationResult
from ..annotation.project_service import get_project_schema
from ..database import DatabaseRow, get_db
from .client import call_llm
from .classifier_runtime import (
    _cancelled_tasks,
    _empty_text_result,
    _load_slot_config,
    compatibility_projection,
    parse_response,
)
from .example_selector import select_examples
from .generic_prompt_builder import build_generic_prompt
from .prompt_policy import get_shared_prompt_template, prompt_fingerprint


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


# This is deliberately independent from per-LLM ``concurrency``. It limits how
# many complete labeling tasks may consume HTTP/DB resources at the same time.
API_TASK_WORKERS = _positive_int_env("API_TASK_WORKERS", 2)
_task_slots = threading.BoundedSemaphore(API_TASK_WORKERS)
_recovery_lock = threading.Lock()
_recovery_threads: set[int] = set()


def _status_filter(target: str) -> str:
    return "r.status = 'pending'" if target == "pending" else "r.status IN ('pending', 'corrected')"


def _task_is_active(task_id: int) -> bool:
    if task_id in _cancelled_tasks:
        return False
    with get_db() as conn:
        row = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    return bool(row and row["status"] in ("pending", "running"))


def _ensure_task_items(conn, task_id: int, project_id: int, target: str) -> tuple[int, int]:
    """Create the task snapshot once and return ``(total, completed)``.

    Legacy API tasks created before this feature have no task_items. For those
    tasks only, results written after the task creation timestamp are treated as
    completed checkpoints so a stuck production task does not restart at row 1.
    """
    existing = conn.execute(
        "SELECT COUNT(*) AS count FROM task_items WHERE task_id=?", (task_id,)
    ).fetchone()["count"]

    if not existing:
        eligible = conn.execute(
            f"SELECT r.id FROM rows r WHERE r.project_id=? AND {_status_filter(target)} ORDER BY r.source_row_number, r.id",
            (project_id,),
        ).fetchall()
        if eligible:
            conn.executemany(
                "INSERT INTO task_items (task_id, row_id, status) VALUES (?, ?, 'pending') ON CONFLICT (task_id, row_id) DO NOTHING",
                [(task_id, row["id"]) for row in eligible],
            )

            # Backfill checkpoints for API tasks that were already running before
            # this migration. Timestamps use the same sortable local-time format.
            conn.execute(
                """UPDATE task_items ti
                   SET status='done', completed_at=COALESCE(ti.completed_at, datetime('now', 'localtime'))
                   WHERE ti.task_id=? AND EXISTS (
                       SELECT 1
                       FROM row_llm_results lr
                       JOIN tasks t ON t.id=ti.task_id
                       WHERE lr.row_id=ti.row_id
                         AND lr.slot=t.slot
                         AND lr.updated_at >= t.created_at
                   )""",
                (task_id,),
            )

    # Anything leased by a process that died is retryable after the lease expires.
    conn.execute(
        """UPDATE task_items
           SET status='pending', lease_token=NULL, lease_expires_at=NULL
           WHERE task_id=? AND status='leased'
             AND lease_expires_at <= datetime('now', 'localtime')""",
        (task_id,),
    )

    total = conn.execute(
        "SELECT COUNT(*) AS count FROM task_items WHERE task_id=?", (task_id,)
    ).fetchone()["count"]
    completed = conn.execute(
        "SELECT COUNT(*) AS count FROM task_items WHERE task_id=? AND status='done'", (task_id,)
    ).fetchone()["count"]
    return total, completed


def _claim_item(task_id: int, row_id: int) -> bool:
    """Lease one row before the external LLM request to prevent duplicate work."""
    with get_db() as conn:
        result = conn.execute(
            """UPDATE task_items
               SET status='leased', lease_token='api-worker',
                   lease_expires_at=datetime('now', 'localtime', '+5 minutes')
               WHERE task_id=? AND row_id=? AND status='pending'""",
            (task_id, row_id),
        )
        claimed = result.rowcount == 1
        if claimed:
            conn.execute(
                "UPDATE tasks SET last_activity_at=datetime('now', 'localtime') WHERE id=?",
                (task_id,),
            )
        conn.commit()
    return claimed


def _release_item(task_id: int, row_id: int, error: str) -> None:
    with get_db() as conn:
        conn.execute(
            """UPDATE task_items
               SET status='pending', lease_token=NULL, lease_expires_at=NULL, error=?
               WHERE task_id=? AND row_id=? AND status='leased'""",
            (error[:1000], task_id, row_id),
        )
        conn.commit()


async def _run_task(task_id: int, project_id: int, target: str, slot: int) -> None:
    with get_db() as conn:
        task = conn.execute(
            "SELECT * FROM tasks WHERE id=? AND project_id=?", (task_id, project_id)
        ).fetchone()
        if not task or task["execution_mode"] != "api" or task["status"] not in ("pending", "running"):
            return

        cfg = _load_slot_config(conn, project_id, slot)
        if not cfg:
            conn.execute(
                "UPDATE tasks SET status='failed', error='找不到 LLM 設定', finished_at=datetime('now', 'localtime') WHERE id=?",
                (task_id,),
            )
            conn.commit()
            return

        schema = get_project_schema(conn, project_id)
        examples = select_examples(conn, project_id, cfg)
        project = conn.execute(
            "SELECT annotation_instructions FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        project_instructions = project["annotation_instructions"] if project else ""
        prompt_template = get_shared_prompt_template(conn, project_id)
        current_fingerprint = prompt_fingerprint(
            prompt_template, examples, project_instructions, schema
        )
        expected_fingerprint = (task["prompt_fingerprint"] or "").strip()
        if expected_fingerprint and expected_fingerprint != current_fingerprint:
            conn.execute(
                """UPDATE tasks SET status='failed',
                   error='Prompt / Codebook 規則已在任務建立後變更，請建立新任務',
                   finished_at=datetime('now', 'localtime') WHERE id=?""",
                (task_id,),
            )
            conn.commit()
            return
        if not expected_fingerprint:
            conn.execute(
                "UPDATE tasks SET prompt_fingerprint=? WHERE id=?",
                (current_fingerprint, task_id),
            )

        total, completed = _ensure_task_items(conn, task_id, project_id, target)
        conn.execute(
            """UPDATE tasks SET total=?, processed=?, status='running', error=NULL,
               last_activity_at=datetime('now', 'localtime') WHERE id=?""",
            (total, completed, task_id),
        )
        conn.commit()

    if total == 0 or completed >= total:
        with get_db() as conn:
            conn.execute(
                "UPDATE tasks SET status='done', processed=?, finished_at=datetime('now', 'localtime') WHERE id=?",
                (completed, task_id),
            )
            conn.commit()
        return

    concurrency = max(1, int(cfg.get("concurrency") or 1))
    api_url = cfg.get("api_url", "")
    model = cfg.get("model", "")
    configured_name = (cfg.get("name") or "").strip()
    source_name = (
        configured_name
        if configured_name and configured_name != f"LLM {slot}"
        else model or configured_name or f"LLM {slot}"
    )
    api_key = cfg.get("api_key", "")
    try:
        extra_body = json.loads(cfg.get("extra_body") or "{}")
        if not isinstance(extra_body, dict):
            extra_body = {}
    except Exception:
        extra_body = {}

    with get_db() as conn:
        rows_to_process = conn.execute(
            """SELECT r.* FROM task_items ti
               JOIN rows r ON r.id=ti.row_id
               WHERE ti.task_id=? AND ti.status='pending'
               ORDER BY r.source_row_number, r.id""",
            (task_id,),
        ).fetchall()

    db_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(concurrency)
    loop = asyncio.get_running_loop()

    async def process_row(row: DatabaseRow) -> None:
        if not _task_is_active(task_id) or not _claim_item(task_id, row["id"]):
            return

        try:
            primary_text = (row.get("text") or row.get("comment_content") or "").strip()
            if not primary_text:
                parsed = _empty_text_result(schema)
            else:
                prompt = build_generic_prompt(
                    prompt_template,
                    examples,
                    primary_text,
                    project_instructions,
                    schema,
                )
                try:
                    raw = await loop.run_in_executor(
                        None,
                        lambda u=api_url, m=model, p=prompt, k=api_key, eb=extra_body: call_llm(
                            u, m, p, api_key=k, extra_body=eb
                        ),
                    )
                    parsed = parse_response(raw, schema)
                except Exception as error:
                    parsed = {
                        "annotation_result": AnnotationResult(
                            relevance=None,
                            labels=[],
                            reason=f"⚠️ LLM 呼叫失敗：{error}",
                        ),
                        "fallback": True,
                        "raw": "",
                    }

            if not _task_is_active(task_id):
                _release_item(task_id, row["id"], "task stopped before result commit")
                return

            annotation_result = parsed["annotation_result"]
            projection = compatibility_projection(schema, annotation_result)
            canonical_json = json.dumps(
                annotation_result.model_dump(mode="json"), ensure_ascii=False
            )
            labels_json = json.dumps(projection["labels"], ensure_ascii=False)
            subtypes_json = json.dumps(projection["emotional_subtypes"], ensure_ascii=False)

            async with db_lock:
                with get_db() as conn:
                    current = conn.execute(
                        "SELECT status FROM tasks WHERE id=?", (task_id,)
                    ).fetchone()
                    if not current or current["status"] not in ("pending", "running"):
                        conn.rollback()
                        return

                    conn.execute(
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
                        (
                            row["id"], slot, source_name, projection["relevance"],
                            labels_json, subtypes_json, projection["reason"], canonical_json,
                        ),
                    )
                    if slot == 1:
                        conn.execute(
                            """UPDATE rows SET prediction=?::jsonb,
                               ai_relevance=?, ai_labels=?, ai_emotional_subtypes=?, ai_reason=?,
                               llm_updated_at=datetime('now', 'localtime') WHERE id=?""",
                            (
                                canonical_json, projection["relevance"], labels_json,
                                subtypes_json, projection["reason"], row["id"],
                            ),
                        )
                    else:
                        conn.execute(
                            "UPDATE rows SET llm_updated_at=datetime('now', 'localtime') WHERE id=?",
                            (row["id"],),
                        )

                    conn.execute(
                        """UPDATE task_items SET status='done', completed_at=datetime('now', 'localtime'),
                           lease_token=NULL, lease_expires_at=NULL, error=NULL
                           WHERE task_id=? AND row_id=?""",
                        (task_id, row["id"]),
                    )
                    processed = conn.execute(
                        "SELECT COUNT(*) AS count FROM task_items WHERE task_id=? AND status='done'",
                        (task_id,),
                    ).fetchone()["count"]
                    conn.execute(
                        """UPDATE tasks SET processed=?, last_activity_at=datetime('now', 'localtime')
                           WHERE id=?""",
                        (processed, task_id),
                    )
                    conn.commit()
        except Exception as error:
            _release_item(task_id, row["id"], str(error))
            raise

    async def process_with_semaphore(row: DatabaseRow) -> None:
        async with semaphore:
            await process_row(row)

    results = await asyncio.gather(
        *[process_with_semaphore(row) for row in rows_to_process],
        return_exceptions=True,
    )

    if not _task_is_active(task_id):
        return

    errors = [result for result in results if isinstance(result, Exception)]
    with get_db() as conn:
        processed = conn.execute(
            "SELECT COUNT(*) AS count FROM task_items WHERE task_id=? AND status='done'",
            (task_id,),
        ).fetchone()["count"]
        remaining = conn.execute(
            "SELECT COUNT(*) AS count FROM task_items WHERE task_id=? AND status!='done'",
            (task_id,),
        ).fetchone()["count"]
        if remaining == 0:
            conn.execute(
                """UPDATE tasks SET status='done', processed=?, error=NULL,
                   finished_at=datetime('now', 'localtime'), last_activity_at=datetime('now', 'localtime')
                   WHERE id=?""",
                (processed, task_id),
            )
        else:
            # Keep it resumable instead of permanently failing the whole job.
            detail = f"{len(errors)} item(s) deferred for retry" if errors else "task interrupted; pending items remain"
            conn.execute(
                """UPDATE tasks SET status='pending', processed=?, error=?,
                   last_activity_at=datetime('now', 'localtime') WHERE id=?""",
                (processed, detail, task_id),
            )
        conn.commit()


async def run_classification_task(
    task_id: int,
    project_id: int,
    target: str,
    slot: int,
) -> None:
    """Run one task with a process-wide cap on concurrently active API jobs."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _task_slots.acquire)
    try:
        await _run_task(task_id, project_id, target, slot)
    except Exception as error:
        if task_id not in _cancelled_tasks:
            with get_db() as conn:
                conn.execute(
                    """UPDATE tasks SET status='pending', error=?,
                       last_activity_at=datetime('now', 'localtime') WHERE id=?
                       AND status IN ('pending', 'running')""",
                    (str(error)[:1000], task_id),
                )
                conn.commit()
    finally:
        _task_slots.release()
        _cancelled_tasks.discard(task_id)


def _resume_one(task: dict) -> None:
    try:
        asyncio.run(
            run_classification_task(
                task_id=task["id"],
                project_id=task["project_id"],
                target=task.get("target") or "pending",
                slot=task.get("slot") or 1,
            )
        )
    finally:
        with _recovery_lock:
            _recovery_threads.discard(task["id"])


def resume_stale_api_tasks() -> int:
    """Resume API tasks left active by a previous process/container.

    Safe to call on every application startup. ``task_items`` checkpoints make
    re-submission idempotent; the task semaphore prevents a restart storm from
    exhausting DB or upstream HTTP capacity.
    """
    with get_db() as conn:
        tasks = conn.execute(
            """SELECT * FROM tasks
               WHERE execution_mode='api' AND status IN ('pending', 'running')
               ORDER BY created_at, id"""
        ).fetchall()

    started = 0
    for row in tasks:
        task = dict(row)
        with _recovery_lock:
            if task["id"] in _recovery_threads:
                continue
            _recovery_threads.add(task["id"])
        thread = threading.Thread(
            target=_resume_one,
            args=(task,),
            name=f"api-task-recovery-{task['id']}",
            daemon=True,
        )
        thread.start()
        started += 1
    return started
