import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import CurrentUser, get_current_user
from ..database import get_db

router = APIRouter()

VALID_ROW_STATUSES = ("pending", "approved", "corrected", "uncertain")


class RowUpdate(BaseModel):
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
):
    conn = get_db()
    conditions = ["r.project_id = ?"]
    params: list = [project_id]

    if status and status != "all":
        conditions.append("r.status = ?")
        params.append(status)
    if relevance and relevance != "all":
        conditions.append("(r.corrected_relevance = ? OR (r.corrected_relevance IS NULL AND r.ai_relevance = ?))")
        params += [relevance, relevance]
    if q:
        conditions.append("(r.comment_content LIKE ? OR r.content LIKE ?)")
        like = f"%{q}%"
        params += [like, like]
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
    order = f"{disagreement_expr} DESC, r.source_row_number ASC" if disagreement == "first" else "r.source_row_number ASC"

    total = conn.execute(f"SELECT COUNT(*) FROM rows r WHERE {where}", params).fetchone()[0]
    offset = (page - 1) * page_size
    rows_db = conn.execute(
        f"""SELECT r.id, r.source_row_number, r.comment_content, r.content,
                   r.ai_relevance, r.ai_labels, r.ai_emotional_subtypes,
                   r.corrected_relevance, r.corrected_labels, r.corrected_emotional_subtypes,
                   r.status, r.reviewed_at, r.llm_updated_at, u.username AS reviewer_username,
                   {disagreement_expr} AS llm_disagreement,
                   {parse_failed_expr} AS llm_parse_failed
            FROM rows r
            LEFT JOIN users u ON u.id = r.reviewer_id
            WHERE {where}
            ORDER BY {order}
            LIMIT ? OFFSET ?""",
        params + [page_size, offset],
    ).fetchall()
    conn.close()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [dict(r) for r in rows_db],
    }


@router.get("/{project_id}/rows/{row_id}")
def get_row(project_id: int, row_id: int):
    conn = get_db()
    row = conn.execute(
        """SELECT r.*, u.username AS reviewer_username
           FROM rows r
           LEFT JOIN users u ON u.id = r.reviewer_id
           WHERE r.id=? AND r.project_id=?""",
        (row_id, project_id),
    ).fetchone()
    if not row:
        conn.close()
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
                  rlr.relevance, rlr.labels, rlr.subtypes, rlr.reason, rlr.updated_at
             FROM row_llm_results rlr
             JOIN rows result_row ON result_row.id = rlr.row_id
             LEFT JOIN llm_configs cfg
                    ON cfg.project_id = result_row.project_id AND cfg.slot = rlr.slot
            WHERE rlr.row_id=?
            ORDER BY rlr.slot""",
        (row_id,),
    ).fetchall()
    result["llm_results"] = [dict(r) for r in llm_results]
    conn.close()
    return result


@router.get("/{project_id}/rows/{row_id}/adjacent")
def adjacent_rows(project_id: int, row_id: int, status: Optional[str] = None, relevance: Optional[str] = None, q: Optional[str] = None):
    """Return prev_id and next_id relative to row_id, respecting current filters."""
    conn = get_db()
    conditions = ["project_id = ?"]
    params: list = [project_id]
    if status and status != "all":
        conditions.append("status = ?")
        params.append(status)
    if relevance and relevance != "all":
        conditions.append("(corrected_relevance = ? OR (corrected_relevance IS NULL AND ai_relevance = ?))")
        params += [relevance, relevance]
    if q:
        conditions.append("(comment_content LIKE ? OR content LIKE ?)")
        like = f"%{q}%"
        params += [like, like]
    where = " AND ".join(conditions)

    current = conn.execute(
        f"SELECT id, source_row_number FROM rows WHERE id = ? AND {where}",
        [row_id] + params,
    ).fetchone()
    if not current:
        total = conn.execute(f"SELECT COUNT(*) FROM rows WHERE {where}", params).fetchone()[0]
        conn.close()
        return {"prev_id": None, "next_id": None, "position": None, "total": total}

    cursor = [current["source_row_number"], current["id"]]
    total = conn.execute(f"SELECT COUNT(*) FROM rows WHERE {where}", params).fetchone()[0]
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
    conn.close()
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
    if body.status not in VALID_ROW_STATUSES:
        raise HTTPException(400, "Invalid request")
    conn = get_db()
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
            conditions.append("(comment_content LIKE ? OR content LIKE ?)")
            like = f"%{body.q_filter}%"
            params += [like, like]
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
        conn.close()
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
    conn.commit()
    updated = cursor.rowcount
    conn.close()
    return {"updated": updated}


@router.patch("/{project_id}/rows/{row_id}")
def update_row(
    project_id: int,
    row_id: int,
    body: RowUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    if body.status is not None and body.status not in VALID_ROW_STATUSES:
        raise HTTPException(400, "Invalid request")

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM rows WHERE id=? AND project_id=?", (row_id, project_id)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Row not found")

    if body.version is not None and (row["version"] or 0) != body.version:
        conn.close()
        raise HTTPException(409, detail="CONFLICT")

    user_row = conn.execute(
        "SELECT id FROM users WHERE username=?", (current_user.username,)
    ).fetchone()

    updates: dict = {}
    if body.corrected_relevance is not None:
        updates["corrected_relevance"] = body.corrected_relevance
    if body.corrected_labels is not None:
        updates["corrected_labels"] = json.dumps(body.corrected_labels, ensure_ascii=False)
    if body.corrected_emotional_subtypes is not None:
        updates["corrected_emotional_subtypes"] = json.dumps(body.corrected_emotional_subtypes, ensure_ascii=False)
    if body.reviewer_note is not None:
        updates["reviewer_note"] = body.reviewer_note
    if body.status is not None:
        updates["status"] = body.status
        updates["reviewed_at"] = "datetime('now', 'localtime')"
    updates["version"] = (row["version"] or 0) + 1
    if user_row:
        updates["reviewer_id"] = user_row["id"]

    if updates:
        # Handle datetime specially
        reviewed_at_expr = updates.pop("reviewed_at", None)
        set_parts = [f"{k} = ?" for k in updates]
        vals = list(updates.values())
        if reviewed_at_expr:
            set_parts.append("reviewed_at = datetime('now', 'localtime')")
        conn.execute(
            f"UPDATE rows SET {', '.join(set_parts)} WHERE id=?",
            vals + [row_id],
        )
        conn.execute(
            """INSERT INTO audit_log (project_id, row_id, username, status, relevance, labels)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project_id, row_id, current_user.username,
             body.status,
             body.corrected_relevance,
             json.dumps(body.corrected_labels, ensure_ascii=False) if body.corrected_labels is not None else None),
        )
        conn.commit()

    updated = conn.execute("SELECT * FROM rows WHERE id=?", (row_id,)).fetchone()
    conn.close()
    return dict(updated)


@router.get("/{project_id}/rows/{row_id}/audit")
def get_row_audit(project_id: int, row_id: int):
    conn = get_db()
    logs = conn.execute(
        "SELECT * FROM audit_log WHERE row_id=? ORDER BY changed_at DESC LIMIT 30",
        (row_id,),
    ).fetchall()
    conn.close()
    return [dict(l) for l in logs]
