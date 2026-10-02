import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..annotation.models import AnnotationResult
from ..annotation.project_service import get_project_schema
from ..annotation.review_service import build_corrected_result
from ..annotation.schema_service import SchemaValidationError
from ..auth import CurrentUser, get_current_user, require_scope
from ..database import get_db
from ..llm.classifier import compatibility_projection
from ..pagination import (
    PAGE_ANCHOR_INTERVAL,
    bump_pagination_generation,
    find_page_anchor,
    get_pagination_generation,
    pagination_filter_hash,
    save_page_anchor,
    supports_page_anchors,
)

router = APIRouter()

VALID_ROW_STATUSES = ("pending", "approved", "corrected", "uncertain")


class RowUpdate(BaseModel):
    # Preferred issue #6 contract. Legacy fields below remain accepted until the
    # current ReviewPage migrates to the dynamic schema editor.
    corrected_result: AnnotationResult | None = None
    corrected_relevance: Optional[str] = None
    corrected_labels: Optional[list[str]] = None
    corrected_emotional_subtypes: Optional[list[str]] = None
    reviewer_note: Optional[str] = None
    status: Optional[str] = None  # pending | approved | corrected | uncertain
    version: Optional[int] = None  # optimistic locking


class BatchUpdate(BaseModel):
    ids: Optional[list[int]] = None
    select_all: bool = False
    status_filter: Optional[str] = None
    relevance_filter: Optional[str] = None
    q_filter: Optional[str] = None
    disagreement_filter: Optional[str] = None
    status: str  # pending | approved | corrected | uncertain


@router.get("/{project_id}/rows")
def list_rows(
    project_id: int,
    page: int = 1,
    page_size: int = 50,
    status: Optional[str] = None,
    relevance: Optional[str] = None,
    q: Optional[str] = None,
    disagreement: Optional[str] = None,
    include_total: bool = True,
    after_source_row_number: Optional[int] = None,
    after_id: Optional[int] = None,
):
    conditions = ["r.project_id = ?"]
    params: list = [project_id]

    cursor_requested = after_source_row_number is not None or after_id is not None
    if cursor_requested and (after_source_row_number is None or after_id is None):
        raise HTTPException(400, "Both after_source_row_number and after_id are required")

    if status and status != "all":
        conditions.append("r.status = ?")
        params.append(status)
    if relevance and relevance != "all":
        conditions.append(
            "(r.corrected_relevance = ? OR "
            "(r.corrected_relevance IS NULL AND r.ai_relevance = ?))"
        )
        params += [relevance, relevance]
    if q:
        conditions.append("(r.comment_content LIKE ? OR r.content LIKE ? OR r.text LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    if disagreement == "only":
        conditions.append("""(
            SELECT COUNT(DISTINCT rlr.relevance) FROM row_llm_results rlr
            WHERE rlr.row_id = r.id AND rlr.relevance IS NOT NULL
        ) > 1""")

    where = " AND ".join(conditions)
    disagreement_expr = """CASE WHEN (
                       SELECT COUNT(DISTINCT rlr.relevance)
                       FROM row_llm_results rlr
                       WHERE rlr.row_id = r.id AND rlr.relevance IS NOT NULL
                   ) > 1 THEN 1 ELSE 0 END"""
    parse_failed_expr = """CASE WHEN EXISTS (
                       SELECT 1 FROM row_llm_results rlr
                       WHERE rlr.row_id = r.id AND rlr.reason LIKE '⚠️%'
                   ) THEN 1 ELSE 0 END"""
    order = (
        f"{disagreement_expr} DESC, r.source_row_number ASC, r.id ASC"
        if disagreement == "first"
        else "r.source_row_number ASC, r.id ASC"
    )

    # Cursor pagination is used for sequential navigation. Sparse page anchors are
    # only enabled for filter modes whose membership/order cannot change from
    # background LLM writes in the initial rollout.
    use_cursor = (
        cursor_requested
        and disagreement != "first"
        and after_source_row_number is not None
        and after_id is not None
    )
    anchor_supported = supports_page_anchors(relevance, disagreement)
    filter_hash = (
        pagination_filter_hash(
            status=status,
            relevance=relevance,
            q=q,
            disagreement=disagreement,
        )
        if anchor_supported
        else None
    )

    query_where = where
    query_params = list(params)
    pagination_mode = "cursor" if use_cursor else "offset"
    anchor_page = None
    offset = 0

    with get_db() as conn:
        total = (
            conn.execute(f"SELECT COUNT(*) FROM rows r WHERE {where}", params).fetchone()[0]
            if include_total
            else None
        )
        generation = get_pagination_generation(conn, project_id) if anchor_supported else 0

        if use_cursor:
            query_where = f"{query_where} AND (r.source_row_number, r.id) > (?, ?)"
            query_params += [after_source_row_number, after_id]
        else:
            if page > 1 and anchor_supported and filter_hash is not None:
                anchor = find_page_anchor(
                    conn,
                    project_id=project_id,
                    generation=generation,
                    filter_hash=filter_hash,
                    page_size=page_size,
                    target_page=page,
                )
                if anchor:
                    query_where = (
                        f"{query_where} AND (r.source_row_number, r.id) >= (?, ?)"
                    )
                    query_params += [
                        anchor["cursor_source_row_number"],
                        anchor["cursor_id"],
                    ]
                    anchor_page = anchor["page"]
                    offset = max(0, (page - anchor_page) * page_size)
                    pagination_mode = "anchor"
                else:
                    offset = (page - 1) * page_size
            else:
                offset = (page - 1) * page_size

        if use_cursor:
            rows_db = conn.execute(
                f"""SELECT r.id, r.source_row_number, r.text, r.comment_content, r.content,
                           r.prediction, r.corrected_result,
                           r.ai_relevance, r.ai_labels, r.ai_emotional_subtypes,
                           r.corrected_relevance, r.corrected_labels, r.corrected_emotional_subtypes,
                           r.status, r.reviewed_at, r.llm_updated_at, u.username AS reviewer_username,
                           {disagreement_expr} AS llm_disagreement,
                           {parse_failed_expr} AS llm_parse_failed
                    FROM rows r
                    LEFT JOIN users u ON u.id = r.reviewer_id
                    WHERE {query_where}
                    ORDER BY {order}
                    LIMIT ?""",
                query_params + [page_size],
            ).fetchall()
        else:
            rows_db = conn.execute(
                f"""SELECT r.id, r.source_row_number, r.text, r.comment_content, r.content,
                           r.prediction, r.corrected_result,
                           r.ai_relevance, r.ai_labels, r.ai_emotional_subtypes,
                           r.corrected_relevance, r.corrected_labels, r.corrected_emotional_subtypes,
                           r.status, r.reviewed_at, r.llm_updated_at, u.username AS reviewer_username,
                           {disagreement_expr} AS llm_disagreement,
                           {parse_failed_expr} AS llm_parse_failed
                    FROM rows r
                    LEFT JOIN users u ON u.id = r.reviewer_id
                    WHERE {query_where}
                    ORDER BY {order}
                    LIMIT ? OFFSET ?""",
                query_params + [page_size, offset],
            ).fetchall()

        items = [dict(r) for r in rows_db]
        next_cursor = None
        if items and disagreement != "first":
            last = items[-1]
            if last["source_row_number"] is not None:
                next_cursor = {
                    "source_row_number": last["source_row_number"],
                    "id": last["id"],
                }

        # Persist only sparse checkpoints to avoid turning every list read into a
        # PostgreSQL write. A checkpoint stores the first row of the page so the
        # same deep page can be revisited directly.
        first_item = items[0] if items else None
        if (
            anchor_supported
            and filter_hash is not None
            and first_item is not None
            and first_item["source_row_number"] is not None
            and page % PAGE_ANCHOR_INTERVAL == 0
        ):
            save_page_anchor(
                conn,
                project_id=project_id,
                generation=generation,
                filter_hash=filter_hash,
                page_size=page_size,
                page=page,
                cursor_source_row_number=first_item["source_row_number"],
                cursor_id=first_item["id"],
            )
            conn.commit()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pagination_mode": pagination_mode,
        "anchor_page": anchor_page,
        "next_cursor": next_cursor,
        "items": items,
    }


@router.get("/{project_id}/rows/{row_id}")
def get_row(project_id: int, row_id: int):
    with get_db() as conn:
        row = conn.execute(
            """SELECT r.*, u.username AS reviewer_username
               FROM rows r
               LEFT JOIN users u ON u.id = r.reviewer_id
               WHERE r.id=? AND r.project_id=?""",
            (row_id, project_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Row not found")
        result = dict(row)
        llm_results = conn.execute(
            """SELECT rlr.slot,
                      COALESCE(
                          NULLIF(rlr.source_name, ''),
                          (SELECT CASE
                                      WHEN t.execution_mode = 'mcp' AND t.executor_name = 'claude' THEN 'Claude Code MCP'
                                      WHEN t.execution_mode = 'mcp' AND t.executor_name = 'codex' THEN 'Codex MCP'
                                      WHEN t.execution_mode = 'mcp' AND t.executor_name != '' THEN t.executor_name || ' MCP'
                                      ELSE NULLIF(t.executor_name, '')
                                  END
                             FROM task_items ti
                             JOIN tasks t ON t.id = ti.task_id
                            WHERE ti.row_id = rlr.row_id
                              AND COALESCE(t.slot, 1) = rlr.slot
                              AND ti.status = 'done'
                            ORDER BY ti.completed_at DESC, t.id DESC
                            LIMIT 1),
                          CASE
                              WHEN NULLIF(cfg.name, '') IS NOT NULL AND cfg.name != 'LLM ' || rlr.slot
                                  THEN cfg.name
                              ELSE COALESCE(NULLIF(cfg.model, ''), NULLIF(cfg.name, ''))
                          END,
                          'LLM ' || rlr.slot
                      ) AS name,
                      rlr.relevance, rlr.labels, rlr.subtypes, rlr.reason,
                      rlr.result, rlr.updated_at
                 FROM row_llm_results rlr
                 JOIN rows result_row ON result_row.id = rlr.row_id
                 LEFT JOIN llm_configs cfg
                        ON cfg.project_id = result_row.project_id AND cfg.slot = rlr.slot
                WHERE rlr.row_id=?
                ORDER BY rlr.slot""",
            (row_id,),
        ).fetchall()
        result["llm_results"] = [dict(r) for r in llm_results]
    return result


@router.get("/{project_id}/rows/{row_id}/adjacent")
def adjacent_rows(
    project_id: int,
    row_id: int,
    status: Optional[str] = None,
    relevance: Optional[str] = None,
    q: Optional[str] = None,
    include_total: bool = True,
):
    """Return prev_id and next_id relative to row_id, respecting current filters."""
    conditions = ["project_id = ?"]
    params: list = [project_id]
    if status and status != "all":
        conditions.append("status = ?")
        params.append(status)
    if relevance and relevance != "all":
        conditions.append("(corrected_relevance = ? OR (corrected_relevance IS NULL AND ai_relevance = ?))")
        params += [relevance, relevance]
    if q:
        conditions.append("(comment_content LIKE ? OR content LIKE ? OR text LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    where = " AND ".join(conditions)

    with get_db() as conn:
        current = conn.execute(
            f"SELECT id, source_row_number FROM rows WHERE id = ? AND {where}",
            [row_id] + params,
        ).fetchone()
        if not current:
            total = (
                conn.execute(f"SELECT COUNT(*) FROM rows WHERE {where}", params).fetchone()[0]
                if include_total
                else None
            )
            return {"prev_id": None, "next_id": None, "position": None, "total": total}

        cursor = [current["source_row_number"], current["id"]]
        total = (
            conn.execute(f"SELECT COUNT(*) FROM rows WHERE {where}", params).fetchone()[0]
            if include_total
            else None
        )
        position = conn.execute(
            f"SELECT COUNT(*) FROM rows WHERE {where} AND (source_row_number, id) <= (?, ?)",
            params + cursor,
        ).fetchone()[0]
        prev_row = conn.execute(
            f"""SELECT id FROM rows WHERE {where} AND (source_row_number, id) < (?, ?)
                ORDER BY source_row_number DESC, id DESC LIMIT 1""",
            params + cursor,
        ).fetchone()
        next_row = conn.execute(
            f"""SELECT id FROM rows WHERE {where} AND (source_row_number, id) > (?, ?)
                ORDER BY source_row_number ASC, id ASC LIMIT 1""",
            params + cursor,
        ).fetchone()
    return {
        "prev_id": prev_row["id"] if prev_row else None,
        "next_id": next_row["id"] if next_row else None,
        "position": position,
        "total": total,
    }


@router.patch("/{project_id}/rows/batch")
def batch_update_rows(
    project_id: int,
    body: BatchUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    require_scope(current_user, "reviews:batch_approve")
    if body.status not in VALID_ROW_STATUSES:
        raise HTTPException(400, "Invalid request")
    with get_db() as conn:
        user_row = conn.execute(
            "SELECT id FROM users WHERE username=?", (current_user.username,)
        ).fetchone()
        reviewer_id = user_row["id"] if user_row else None

        if body.select_all:
            conditions = ["project_id = ?"]
            params: list = [project_id]
            if body.status_filter and body.status_filter != "all":
                conditions.append("status = ?")
                params.append(body.status_filter)
            if body.relevance_filter and body.relevance_filter != "all":
                conditions.append("(corrected_relevance = ? OR (corrected_relevance IS NULL AND ai_relevance = ?))")
                params += [body.relevance_filter, body.relevance_filter]
            if body.q_filter:
                conditions.append("(comment_content LIKE ? OR content LIKE ? OR text LIKE ?)")
                like = f"%{body.q_filter}%"
                params += [like, like, like]
            if body.disagreement_filter == "only":
                conditions.append(
                    "(SELECT COUNT(DISTINCT rlr.relevance) FROM row_llm_results rlr"
                    " WHERE rlr.row_id = rows.id AND rlr.relevance IS NOT NULL) > 1"
                )
            where = " AND ".join(conditions)
            row_ids = [r[0] for r in conn.execute(f"SELECT id FROM rows WHERE {where}", params).fetchall()]
        else:
            row_ids = body.ids or []

        if not row_ids:
            return {"updated": 0}

        placeholders = ",".join("?" * len(row_ids))
        cursor = conn.execute(
            f"UPDATE rows SET status=?, reviewer_id=?, reviewed_at=datetime('now','localtime'), version=COALESCE(version,0)+1 "
            f"WHERE id IN ({placeholders}) AND project_id=?",
            [body.status, reviewer_id] + row_ids + [project_id],
        )
        conn.executemany(
            "INSERT INTO audit_log (project_id, row_id, username, status) VALUES (?, ?, ?, ?)",
            [(project_id, rid, current_user.username, body.status) for rid in row_ids],
        )
        updated = cursor.rowcount
        if updated:
            bump_pagination_generation(conn, project_id)
        conn.commit()
    return {"updated": updated}


def _schema_error(row_id: int, error: SchemaValidationError) -> HTTPException:
    return HTTPException(
        400,
        detail={
            "code": "INVALID_ANNOTATION_RESULT",
            "row_id": row_id,
            "issues": error.issues,
        },
    )


@router.patch("/{project_id}/rows/{row_id}")
def update_row(
    project_id: int,
    row_id: int,
    body: RowUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    if body.status == "approved":
        require_scope(current_user, "reviews:approve")
    else:
        require_scope(current_user, "rows:write")
    if body.status is not None and body.status not in VALID_ROW_STATUSES:
        raise HTTPException(400, "Invalid request")

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM rows WHERE id=? AND project_id=?", (row_id, project_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Row not found")

        if body.version is not None and (row["version"] or 0) != body.version:
            raise HTTPException(409, detail="CONFLICT")

        schema = get_project_schema(conn, project_id)
        try:
            canonical = build_corrected_result(
                schema,
                row,
                corrected_result=body.corrected_result,
                corrected_relevance=body.corrected_relevance,
                corrected_labels=body.corrected_labels,
                corrected_emotional_subtypes=body.corrected_emotional_subtypes,
            )
        except SchemaValidationError as error:
            raise _schema_error(row_id, error)

        projection = compatibility_projection(schema, canonical) if canonical is not None else None
        canonical_json = (
            json.dumps(canonical.model_dump(mode="json"), ensure_ascii=False)
            if canonical is not None
            else None
        )

        user_row = conn.execute(
            "SELECT id FROM users WHERE username=?", (current_user.username,)
        ).fetchone()

        updates: dict = {}
        if canonical is not None:
            updates["corrected_result"] = canonical_json
            updates["corrected_relevance"] = projection["relevance"]
            updates["corrected_labels"] = json.dumps(projection["labels"], ensure_ascii=False)
            updates["corrected_emotional_subtypes"] = json.dumps(
                projection["emotional_subtypes"], ensure_ascii=False
            )
        if body.reviewer_note is not None:
            updates["reviewer_note"] = body.reviewer_note
        if body.status is not None:
            updates["status"] = body.status
            updates["reviewed_at"] = "datetime('now', 'localtime')"
        updates["version"] = (row["version"] or 0) + 1
        if user_row:
            updates["reviewer_id"] = user_row["id"]

        if updates:
            reviewed_at_expr = updates.pop("reviewed_at", None)
            set_parts = []
            vals = []
            for key, value in updates.items():
                if key == "corrected_result":
                    set_parts.append("corrected_result = ?::jsonb")
                else:
                    set_parts.append(f"{key} = ?")
                vals.append(value)
            if reviewed_at_expr:
                set_parts.append("reviewed_at = datetime('now', 'localtime')")
            conn.execute(
                f"UPDATE rows SET {', '.join(set_parts)} WHERE id=?",
                vals + [row_id],
            )

            audit_relevance = projection["relevance"] if projection is not None else body.corrected_relevance
            audit_labels = (
                json.dumps(projection["labels"], ensure_ascii=False)
                if projection is not None
                else (
                    json.dumps(body.corrected_labels, ensure_ascii=False)
                    if body.corrected_labels is not None
                    else None
                )
            )
            conn.execute(
                """INSERT INTO audit_log (project_id, row_id, username, status, relevance, labels)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    row_id,
                    current_user.username,
                    body.status,
                    audit_relevance,
                    audit_labels,
                ),
            )
            bump_pagination_generation(conn, project_id)
            conn.commit()

        updated = conn.execute("SELECT * FROM rows WHERE id=?", (row_id,)).fetchone()
    return dict(updated)


@router.get("/{project_id}/rows/{row_id}/audit")
def get_row_audit(project_id: int, row_id: int):
    with get_db() as conn:
        logs = conn.execute(
            "SELECT * FROM audit_log WHERE row_id=? ORDER BY changed_at DESC LIMIT 30",
            (row_id,),
        ).fetchall()
    return [dict(l) for l in logs]
