import hashlib
import json

from .database import DatabaseConnection


ANCHOR_SORT_VERSION = 3
PAGE_ANCHOR_INTERVAL = 20


def supports_page_anchors(
    relevance: str | None,
    disagreement: str | None,
) -> bool:
    """Return whether current ordering/filter semantics are safe for sparse anchors.

    Initial rollout intentionally excludes relevance/disagreement modes because LLM
    results may change those result sets in the background. Status/q filters are safe
    because membership changes bump the affected status generations in the same DB
    transaction. Unfiltered anchors survive review-only edits.
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


def get_pagination_generation(conn: DatabaseConnection, project_id: int, status: str | None = None) -> int:
    row = conn.execute(
        "SELECT pagination_generation, pagination_status_generations FROM projects WHERE id=?",
        (project_id,),
    ).fetchone()
    if not row:
        return 0
    versions = row["pagination_status_generations"] or {}
    return int(row["pagination_generation"] or 0) + int(versions.get(status or "all", 0))


def invalidate_status_transitions(conn: DatabaseConnection, project_id: int, old_statuses, new_status: str) -> None:
    """Advance only memberships that changed, in the review transaction."""
    affected = {status for status in old_statuses if status != new_status}
    if not affected:
        return
    affected.add(new_status)
    # Lock the project to serialize concurrent reviewers' counter increments.
    row = conn.execute(
        "SELECT pagination_status_generations FROM projects WHERE id=? FOR UPDATE", (project_id,)
    ).fetchone()
    versions = dict(row["pagination_status_generations"] or {})
    for status in affected:
        versions[status] = int(versions.get(status, 0)) + 1
    conn.execute(
        "UPDATE projects SET pagination_status_generations=?::jsonb WHERE id=?",
        (json.dumps(versions), project_id),
    )


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
             AND page <= ?
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
    """Persist a page-start cursor and opportunistically prune stale generations."""

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
        "DELETE FROM row_page_anchors WHERE project_id=? AND filter_hash=? AND generation<?",
        (project_id, filter_hash, generation),
    )
