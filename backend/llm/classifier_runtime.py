import asyncio
import json
import re

from ..annotation.legacy import LEGACY_LABEL_SCHEMA, generic_to_legacy_result
from ..annotation.models import AnnotationResult, AnnotationSchema
from ..annotation.project_service import get_project_schema
from ..annotation.result_service import normalize_result
from ..annotation.schema_service import SchemaValidationError, validate_result
from ..database import DatabaseConnection, DatabaseRow, get_db
from .client import call_llm
from .example_selector import select_examples
from .generic_prompt_builder import build_generic_prompt


PARSE_FAIL_MARKER = "⚠️ 解析失敗"

# 記錄使用者按下「停止」的任務 ID。同一個 process 內跨執行緒共用。
_cancelled_tasks: set[int] = set()


def mark_task_cancelled(task_id: int) -> None:
    _cancelled_tasks.add(task_id)


def _is_legacy_schema(schema: AnnotationSchema) -> bool:
    return schema.model_dump(mode="json") == LEGACY_LABEL_SCHEMA.model_dump(mode="json")


def _token(value) -> str | None:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        candidate = value.get("id") or value.get("name")
        return candidate.strip() if isinstance(candidate, str) else None
    return None


def _resolve_label(schema: AnnotationSchema, value) -> str | None:
    token = _token(value)
    if not token:
        return None
    by_id = {label.id: label.id for label in schema.labels}
    by_name = {label.name: label.id for label in schema.labels}
    # Preserve unknown tokens so schema validation can report model mistakes.
    return by_id.get(token) or by_name.get(token) or token


def _resolve_relevance(schema: AnnotationSchema, value) -> str | None:
    if not schema.relevance or not schema.relevance.enabled:
        return None
    token = _token(value)
    if not token:
        return None
    by_id = {item.id: item.id for item in schema.relevance.values}
    by_name = {item.name: item.id for item in schema.relevance.values}
    return by_id.get(token) or by_name.get(token) or token


def _parse_failure(message: str, raw: str = "") -> dict:
    snippet = raw.strip()[:300]
    if raw.strip() and len(raw.strip()) > 300:
        snippet += "…"
    reason = f"{PARSE_FAIL_MARKER}：{message}"
    if snippet:
        reason += f"，原始回傳：{snippet}"
    return {
        "annotation_result": AnnotationResult(relevance=None, labels=[], reason=reason),
        "fallback": True,
        "raw": raw,
    }


def parse_response(text: str, schema: AnnotationSchema) -> dict:
    """Parse an LLM response into the canonical project-scoped result contract."""
    original = text.strip()
    payload_text = original
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", payload_text)
    if fenced:
        payload_text = fenced.group(1).strip()

    try:
        data = json.loads(payload_text)
        if not isinstance(data, dict):
            return _parse_failure("LLM 回傳必須是 JSON object", original)

        raw_labels = data.get("labels") or []
        if not isinstance(raw_labels, list):
            return _parse_failure("labels 必須是陣列", original)

        # Backward-compatible input tolerance: old prompts may still emit
        # emotional_subtypes. Treat them as ordinary label references and let the
        # active project schema decide whether they are valid children.
        raw_subtypes = data.get("emotional_subtypes") or []
        if not isinstance(raw_subtypes, list):
            return _parse_failure("emotional_subtypes 必須是陣列", original)

        labels: list[str] = []
        for item in [*raw_labels, *raw_subtypes]:
            label_id = _resolve_label(schema, item)
            if label_id is not None:
                labels.append(label_id)

        reason = data.get("reason", "")
        if not isinstance(reason, str):
            reason = str(reason)

        result = AnnotationResult(
            relevance=_resolve_relevance(schema, data.get("relevance")),
            labels=labels,
            reason=reason,
        )
        result = normalize_result(schema, result)
        validate_result(schema, result)
        return {"annotation_result": result, "fallback": False, "raw": original}
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        return _parse_failure(str(error), original)
    except SchemaValidationError as error:
        return _parse_failure("；".join(error.issues), original)
    except Exception as error:
        return _parse_failure(str(error), original)


def _negative_relevance(schema: AnnotationSchema) -> str | None:
    if not schema.relevance or not schema.relevance.enabled:
        return None
    negative_tokens = {
        "unrelated",
        "irrelevant",
        "not_relevant",
        "not relevant",
        "無關",
        "不相關",
    }
    for item in schema.relevance.values:
        if item.id.strip().lower() in negative_tokens or item.name.strip().lower() in negative_tokens:
            return item.id
    return None


def _empty_text_result(schema: AnnotationSchema) -> dict:
    result = AnnotationResult(
        relevance=_negative_relevance(schema),
        labels=[],
        reason="無可分類的主要文字",
    )
    try:
        result = normalize_result(schema, result)
        validate_result(schema, result)
        return {"annotation_result": result, "fallback": False, "raw": ""}
    except SchemaValidationError:
        return _parse_failure("主要文字為空，且 schema 沒有可安全推定的 relevance")


def compatibility_projection(schema: AnnotationSchema, result: AnnotationResult) -> dict:
    """Project canonical results onto fields still consumed by the legacy UI/API."""
    if _is_legacy_schema(schema):
        return generic_to_legacy_result(result)

    label_names = {label.id: label.name for label in schema.labels}
    relevance_names = (
        {item.id: item.name for item in schema.relevance.values}
        if schema.relevance and schema.relevance.enabled
        else {}
    )
    return {
        "relevance": relevance_names.get(result.relevance, result.relevance),
        "labels": [label_names.get(label_id, label_id) for label_id in result.labels],
        "emotional_subtypes": [],
        "reason": result.reason,
    }


def _load_slot_config(conn: DatabaseConnection, project_id: int, slot: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM llm_configs WHERE project_id=? AND slot=?", (project_id, slot)
    ).fetchone()
    if row:
        return dict(row)
    if slot == 1:
        proj = conn.execute("SELECT llm_config FROM projects WHERE id=?", (project_id,)).fetchone()
        if proj and proj["llm_config"]:
            try:
                old = json.loads(proj["llm_config"])
                if old.get("api_url") and old.get("model"):
                    return {"slot": 1, "name": "LLM 1", "concurrency": 1, **old}
            except Exception:
                pass
    return None


async def run_classification_task(
    task_id: int,
    project_id: int,
    target: str,
    slot: int,
) -> None:
    try:
        if task_id in _cancelled_tasks:
            return

        # Read all local configuration before waiting on external LLM calls. Do not
        # retain a pooled DB connection while network requests are in flight.
        with get_db() as conn:
            cfg = _load_slot_config(conn, project_id, slot)
            if not cfg:
                conn.execute(
                    "UPDATE tasks SET status='failed', error='找不到 LLM 設定', finished_at=datetime('now', 'localtime') WHERE id=?",
                    (task_id,),
                )
                conn.commit()
                return

            schema = get_project_schema(conn, project_id)

            if target == "pending":
                status_filter = "status = 'pending'"
            else:
                status_filter = "status IN ('pending', 'corrected')"

            rows_to_process = conn.execute(
                f"SELECT * FROM rows WHERE project_id=? AND {status_filter} ORDER BY source_row_number ASC",
                (project_id,),
            ).fetchall()
            total = len(rows_to_process)
            conn.execute("UPDATE tasks SET total=?, status='running' WHERE id=?", (total, task_id))
            examples = select_examples(conn, project_id, cfg)
            project = conn.execute(
                "SELECT annotation_instructions FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            project_instructions = project["annotation_instructions"] if project else ""
            conn.commit()

        if total == 0:
            with get_db() as conn:
                conn.execute(
                    "UPDATE tasks SET status='done', finished_at=datetime('now', 'localtime') WHERE id=?",
                    (task_id,),
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
        prompt_template = cfg.get("prompt_template", "")
        try:
            extra_body = json.loads(cfg.get("extra_body") or "{}")
            if not isinstance(extra_body, dict):
                extra_body = {}
        except Exception:
            extra_body = {}

        processed_count = 0
        db_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(concurrency)
        loop = asyncio.get_event_loop()

        async def process_row(row: DatabaseRow) -> None:
            nonlocal processed_count
            if task_id in _cancelled_tasks:
                return

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

            annotation_result: AnnotationResult = parsed["annotation_result"]
            projection = compatibility_projection(schema, annotation_result)
            canonical_json = json.dumps(
                annotation_result.model_dump(mode="json"), ensure_ascii=False
            )
            labels_json = json.dumps(projection["labels"], ensure_ascii=False)
            subtypes_json = json.dumps(projection["emotional_subtypes"], ensure_ascii=False)

            async with db_lock:
                with get_db() as conn:
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
                            row["id"],
                            slot,
                            source_name,
                            projection["relevance"],
                            labels_json,
                            subtypes_json,
                            projection["reason"],
                            canonical_json,
                        ),
                    )
                    # Slot 1 remains the primary prediction and mirrors into legacy
                    # columns until the review/list APIs switch to corrected_result.
                    if slot == 1:
                        conn.execute(
                            """UPDATE rows SET prediction=?::jsonb,
                                      ai_relevance=?, ai_labels=?, ai_emotional_subtypes=?, ai_reason=?,
                                      llm_updated_at=datetime('now', 'localtime')
                               WHERE id=?""",
                            (
                                canonical_json,
                                projection["relevance"],
                                labels_json,
                                subtypes_json,
                                projection["reason"],
                                row["id"],
                            ),
                        )
                    else:
                        conn.execute(
                            "UPDATE rows SET llm_updated_at=datetime('now', 'localtime') WHERE id=?",
                            (row["id"],),
                        )
                    processed_count += 1
                    conn.execute(
                        "UPDATE tasks SET processed=? WHERE id=?", (processed_count, task_id)
                    )
                    conn.commit()

        async def process_with_semaphore(row: DatabaseRow) -> None:
            async with semaphore:
                await process_row(row)

        await asyncio.gather(*[process_with_semaphore(row) for row in rows_to_process])

        if task_id in _cancelled_tasks:
            return

        with get_db() as conn:
            conn.execute(
                "UPDATE tasks SET status='done', finished_at=datetime('now', 'localtime') WHERE id=?",
                (task_id,),
            )
            conn.commit()

    except Exception as error:
        if task_id in _cancelled_tasks:
            return
        with get_db() as conn:
            conn.execute(
                "UPDATE tasks SET status='failed', error=?, finished_at=datetime('now', 'localtime') WHERE id=?",
                (str(error), task_id),
            )
            conn.commit()
    finally:
        _cancelled_tasks.discard(task_id)
