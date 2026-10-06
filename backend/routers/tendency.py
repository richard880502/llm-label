import json
from typing import Any

from fastapi import APIRouter

from ..annotation.project_service import get_project_schema
from ..annotation.tendency import tendency_report
from ..database import get_db

router = APIRouter()


def _as_dict(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


@router.get("/{project_id}/tendency")
def annotation_tendency(project_id: int):
    """Reviewer and label tendencies from existing review records (no extra labelling)."""
    with get_db() as conn:
        schema = get_project_schema(conn, project_id)
        rows = conn.execute(
            """SELECT u.username AS reviewer, r.status, r.source_row_number,
                      r.prediction, r.corrected_result
               FROM rows r LEFT JOIN users u ON u.id = r.reviewer_id
               WHERE r.project_id = ?""",
            (project_id,),
        ).fetchall()
    prepared = [
        {
            **dict(row),
            "prediction": _as_dict(row["prediction"]),
            "corrected_result": _as_dict(row["corrected_result"]),
        }
        for row in rows
    ]
    return tendency_report(prepared, [label.id for label in schema.labels])
