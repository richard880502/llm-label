import hashlib
import json

from .database import DatabaseConnection


ANCHOR_SORT_VERSION = 1


def supports_page_anchors(
    relevance: str | None,
    disagreement: str | None,
) -> bool:
    """Return whether current ordering/filter semantics are safe for sparse anchors.

    Initial rollout intentionally excludes relevance/disagreement modes because LLM
    results may change those result sets in the background. Status/q filters are safe
    because review mutations bump the project pagination generation in the same DB
    transaction.
    """

    relevance_value = (relevance or "all").strip()
    disagreement_value = (disagreement or "all").strip()
    return relevance_value == "all" and disagreement_value == "all"


def pagination_filter_hash(
    *,
    status: str | None,
    relevance: str | None,
    q: str | None,
    disagreement: str | None,
) -> str:
    payload = {
        "v": ANCHOR_SORT_VERSION,
        "status": status or "all",
        "relevance": relevance or "all",
        "q": q or "",
        "disagreement": disagreement or "all",
        "order": "source_row_number,id",
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def get_pagination_generation(conn: DatabaseConnection, project_id: int) -> int:
    row = conn.execute(
        "SELECT pagination_generation FROM projects WHERE id=?",
        (project_id,),
    ).fetchone()
    return int(row["pagination_generation"] or 0) if row else 0


def bump_pagination_generation(conn: DatabaseConnection, project_id: int) -> None:
    """Invalidate all existing anchors for a project without deleting them eagerly."""

    conn.execute(
        """UPDATE projects
           SET pagination_generation=COALESCE(pagination_generation, 0) + 1
           WHERE id=?""",
        (project_id,),
    )


def find_page_anchor(
    conn: DatabaseConnection,
    *,
    project_id: int,
    generation: int,
    filter_hash: str,
    page_size: int,
    target_page: int,
) -> dict | None:
    row = conn.execute(
        """SELECT page, cursor_source_row_number, cursor_id
           FROM row_page_anchors
           WHERE project_id=?
             AND generation=?
             AND filter_hash=?
             AND page_size=?
             AND page < ?
           ORDER BY page DESC
           LIMIT 1""",
        (project_id, generation, filter_hash, page_size, target_page),
    ).fetchone()
    return dict(row) if row else None


def save_page_anchor(
    conn: DatabaseConnection,
    *,
    project_id: int,
    generation: int,
    filter_hash: str,
    page_size: int,
    page: int,
    cursor_source_row_number: int,
    cursor_id: int,
) -> None:
    """Persist an end-of-page cursor and opportunistically prune stale generations."""

    conn.execute(
        """INSERT INTO row_page_anchors
               (project_id, generation, filter_hash, page_size, page,
                cursor_source_row_number, cursor_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
           ON CONFLICT (project_id, generation, filter_hash, page_size, page)
           DO UPDATE SET
               cursor_source_row_number=EXCLUDED.cursor_source_row_number,
               cursor_id=EXCLUDED.cursor_id,
               created_at=EXCLUDED.created_at""",
        (
            project_id,
            generation,
            filter_hash,
            page_size,
            page,
            cursor_source_row_number,
            cursor_id,
        ),
    )
    conn.execute(
        "DELETE FROM row_page_anchors WHERE project_id=? AND generation<>?",
        (project_id, generation),
    )
