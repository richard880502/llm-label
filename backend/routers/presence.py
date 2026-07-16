from fastapi import APIRouter, Depends

from ..auth import CurrentUser, get_current_user
from ..database import get_db

router = APIRouter()


@router.post("/{project_id}/rows/{row_id}/presence")
def update_presence(
    project_id: int,
    row_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    conn = get_db()
    conn.execute(
        """INSERT INTO presence (username, row_id, project_id, last_seen)
           VALUES (?, ?, ?, datetime('now', 'localtime'))
           ON CONFLICT(username, row_id) DO UPDATE SET last_seen = datetime('now', 'localtime')""",
        (current_user.username, row_id, project_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.delete("/{project_id}/rows/{row_id}/presence")
def remove_presence(
    project_id: int,
    row_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    conn = get_db()
    conn.execute(
        "DELETE FROM presence WHERE username=? AND row_id=?",
        (current_user.username, row_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/{project_id}/presence")
def get_presence(project_id: int):
    conn = get_db()
    rows = conn.execute(
        """SELECT username, row_id FROM presence
           WHERE project_id = ?
           AND last_seen > datetime('now', 'localtime', '-30 seconds')""",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
