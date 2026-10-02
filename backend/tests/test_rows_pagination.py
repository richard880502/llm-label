import uuid

import psycopg
import pytest

from backend.auth import CurrentUser
from backend.database import _get_pool, get_db
from backend.routers.rows import (
    BatchUpdate,
    adjacent_rows,
    batch_update_rows,
    list_rows,
)


def _pool_reachable() -> bool:
    try:
        with _get_pool().connection(timeout=3):
            return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _pool_reachable(),
    reason="requires a reachable Postgres (see docker-compose.yml, DATABASE_URL)",
)


@pytest.fixture
def project_factory():
    created_project_ids: list[int] = []

    def create(rows: list[dict]) -> int:
        name = f"pagination-test-{uuid.uuid4().hex}"
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO projects (name, filename, total_rows) VALUES (?, ?, ?)",
                (name, "pagination.csv", len(rows)),
            )
            project_id = cursor.lastrowid
            assert project_id is not None

            conn.executemany(
                """
                INSERT INTO rows
                    (project_id, source_row_number, original_data, content,
                     comment_content, ai_relevance, corrected_relevance, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        project_id,
                        row.get("source_row_number"),
                        row.get("original_data", "{}"),
                        row.get("content", ""),
                        row.get("comment_content", ""),
                        row.get("ai_relevance"),
                        row.get("corrected_relevance"),
                        row.get("status", "pending"),
                    )
                    for row in rows
                ],
            )
            conn.commit()

        created_project_ids.append(project_id)
        return project_id

    yield create

    if created_project_ids:
        with get_db() as conn:
            for project_id in created_project_ids:
                conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            conn.commit()


def _row_ids_by_source(project_id: int) -> dict[int, list[int]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, source_row_number
            FROM rows
            WHERE project_id=?
            ORDER BY source_row_number, id
            """,
            (project_id,),
        ).fetchall()

    result: dict[int, list[int]] = {}
    for row in rows:
        result.setdefault(row["source_row_number"], []).append(row["id"])
    return result


def test_list_rows_paginates_in_source_order_and_preserves_total(project_factory):
    project_id = project_factory(
        [{"source_row_number": i, "comment_content": f"row {i}"} for i in range(1, 124)]
    )

    first = list_rows(project_id, page=1, page_size=50)
    third = list_rows(project_id, page=3, page_size=50)

    assert first["total"] == 123
    assert [item["source_row_number"] for item in first["items"]] == list(range(1, 51))

    assert third["total"] == 123
    assert [item["source_row_number"] for item in third["items"]] == list(range(101, 124))


def test_deep_page_returns_exact_window(project_factory):
    project_id = project_factory(
        [{"source_row_number": i, "comment_content": f"row {i}"} for i in range(1, 1006)]
    )

    result = list_rows(project_id, page=101, page_size=10)

    assert result["total"] == 1005
    assert [item["source_row_number"] for item in result["items"]] == [1001, 1002, 1003, 1004, 1005]


def test_filters_are_applied_before_pagination(project_factory):
    project_id = project_factory(
        [
            {
                "source_row_number": i,
                "status": "pending" if i % 2 == 0 else "approved",
                "corrected_relevance": "相關" if i % 4 == 0 else None,
                "ai_relevance": "相關" if i % 4 == 2 else "無關",
                "comment_content": f"{'needle ' if i % 5 == 0 else ''}row {i}",
            }
            for i in range(1, 81)
        ]
    )

    result = list_rows(
        project_id,
        page=2,
        page_size=3,
        status="pending",
        relevance="相關",
        q="needle",
    )

    # Matching source rows are 10,20,30,40,50,60,70,80.
    assert result["total"] == 8
    assert [item["source_row_number"] for item in result["items"]] == [40, 50, 60]


def test_include_total_false_keeps_page_contents_but_skips_count(project_factory):
    project_id = project_factory(
        [{"source_row_number": i, "comment_content": f"row {i}"} for i in range(1, 76)]
    )

    with_total = list_rows(project_id, page=2, page_size=25, include_total=True)
    without_total = list_rows(project_id, page=2, page_size=25, include_total=False)

    assert with_total["total"] == 75
    assert without_total["total"] is None
    assert [item["id"] for item in without_total["items"]] == [
        item["id"] for item in with_total["items"]
    ]


def test_disagreement_and_parse_failed_flags_survive_pagination_filters(project_factory):
    project_id = project_factory(
        [{"source_row_number": i, "comment_content": f"row {i}"} for i in range(1, 5)]
    )
    ids = {source: values[0] for source, values in _row_ids_by_source(project_id).items()}

    with get_db() as conn:
        conn.executemany(
            """
            INSERT INTO row_llm_results
                (row_id, slot, source_name, relevance, labels, subtypes, reason)
            VALUES (?, ?, ?, ?, '[]', '[]', ?)
            """,
            [
                (ids[1], 1, "model-a", "相關", "ok"),
                (ids[2], 1, "model-a", "相關", "ok"),
                (ids[2], 2, "model-b", "無關", "ok"),
                (ids[3], 1, "model-a", "相關", "⚠️ malformed"),
                (ids[4], 1, "model-a", "相關", "⚠️ malformed"),
                (ids[4], 2, "model-b", "無關", "ok"),
            ],
        )
        conn.commit()

    all_rows = list_rows(project_id, page=1, page_size=10)
    by_source = {item["source_row_number"]: item for item in all_rows["items"]}

    assert by_source[1]["llm_disagreement"] == 0
    assert by_source[1]["llm_parse_failed"] == 0
    assert by_source[2]["llm_disagreement"] == 1
    assert by_source[2]["llm_parse_failed"] == 0
    assert by_source[3]["llm_disagreement"] == 0
    assert by_source[3]["llm_parse_failed"] == 1
    assert by_source[4]["llm_disagreement"] == 1
    assert by_source[4]["llm_parse_failed"] == 1

    disagreement_only = list_rows(
        project_id,
        page=1,
        page_size=10,
        disagreement="only",
    )
    assert disagreement_only["total"] == 2
    assert [item["source_row_number"] for item in disagreement_only["items"]] == [2, 4]

    disagreement_first = list_rows(
        project_id,
        page=1,
        page_size=10,
        disagreement="first",
    )
    assert [item["source_row_number"] for item in disagreement_first["items"]] == [2, 4, 1, 3]


def test_adjacent_rows_uses_id_as_tiebreaker_and_respects_filters(project_factory):
    project_id = project_factory(
        [
            {"source_row_number": 10, "status": "pending"},
            {"source_row_number": 10, "status": "pending"},
            {"source_row_number": 10, "status": "approved"},
            {"source_row_number": 11, "status": "pending"},
        ]
    )
    ids_by_source = _row_ids_by_source(project_id)
    duplicate_ids = ids_by_source[10]

    result = adjacent_rows(
        project_id,
        duplicate_ids[1],
        status="pending",
        include_total=True,
    )

    assert result["prev_id"] == duplicate_ids[0]
    assert result["next_id"] == ids_by_source[11][0]
    assert result["position"] == 2
    assert result["total"] == 3


def test_cursor_page_matches_offset_page_and_uses_stable_tiebreaker(project_factory):
    project_id = project_factory(
        [
            {"source_row_number": 1, "comment_content": "a"},
            {"source_row_number": 2, "comment_content": "b"},
            {"source_row_number": 2, "comment_content": "c"},
            {"source_row_number": 3, "comment_content": "d"},
            {"source_row_number": 4, "comment_content": "e"},
            {"source_row_number": 5, "comment_content": "f"},
        ]
    )

    first = list_rows(project_id, page=1, page_size=3)
    cursor = first["next_cursor"]
    assert cursor is not None

    cursor_page = list_rows(
        project_id,
        page=2,
        page_size=3,
        include_total=False,
        after_source_row_number=cursor["source_row_number"],
        after_id=cursor["id"],
    )
    offset_page = list_rows(project_id, page=2, page_size=3, include_total=False)

    assert cursor_page["pagination_mode"] == "cursor"
    assert [item["id"] for item in cursor_page["items"]] == [
        item["id"] for item in offset_page["items"]
    ]
    assert [item["source_row_number"] for item in cursor_page["items"]] == [3, 4, 5]


def test_cursor_respects_filters(project_factory):
    project_id = project_factory(
        [
            {
                "source_row_number": i,
                "status": "pending" if i % 2 == 0 else "approved",
                "ai_relevance": "相關" if i % 4 in (0, 2) else "無關",
                "comment_content": f"row {i}",
            }
            for i in range(1, 21)
        ]
    )

    first = list_rows(
        project_id,
        page=1,
        page_size=3,
        status="pending",
        relevance="相關",
    )
    cursor = first["next_cursor"]
    assert cursor is not None

    second = list_rows(
        project_id,
        page=2,
        page_size=3,
        status="pending",
        relevance="相關",
        include_total=False,
        after_source_row_number=cursor["source_row_number"],
        after_id=cursor["id"],
    )

    assert second["pagination_mode"] == "cursor"
    assert [item["source_row_number"] for item in second["items"]] == [8, 10, 12]
    assert all(item["status"] == "pending" for item in second["items"])


def test_partial_cursor_is_rejected(project_factory):
    project_id = project_factory(
        [{"source_row_number": i} for i in range(1, 4)]
    )

    with pytest.raises(Exception) as exc_info:
        list_rows(
            project_id,
            page=2,
            page_size=2,
            after_source_row_number=2,
        )

    assert getattr(exc_info.value, "status_code", None) == 400


def test_disagreement_first_keeps_offset_fallback(project_factory):
    project_id = project_factory(
        [{"source_row_number": i} for i in range(1, 5)]
    )

    result = list_rows(
        project_id,
        page=1,
        page_size=2,
        disagreement="first",
        after_source_row_number=2,
        after_id=999999,
    )

    assert result["pagination_mode"] == "offset"
    assert result["next_cursor"] is None



def test_deep_jump_reuses_nearest_page_anchor(project_factory):
    project_id = project_factory(
        [{"source_row_number": i, "comment_content": f"row {i}"} for i in range(1, 401)]
    )

    anchor_source = list_rows(project_id, page=10, page_size=10)
    assert anchor_source["pagination_mode"] == "offset"

    jumped = list_rows(project_id, page=15, page_size=10, include_total=False)

    assert jumped["pagination_mode"] == "anchor"
    assert jumped["anchor_page"] == 10
    assert [item["source_row_number"] for item in jumped["items"]] == list(range(141, 151))


def test_page_anchor_generation_invalidates_after_review_mutation(project_factory):
    project_id = project_factory(
        [{"source_row_number": i, "comment_content": f"row {i}"} for i in range(1, 301)]
    )
    ids = _row_ids_by_source(project_id)

    list_rows(project_id, page=10, page_size=10)

    with get_db() as conn:
        before = conn.execute(
            "SELECT pagination_generation FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()["pagination_generation"]

    batch_update_rows(
        project_id,
        BatchUpdate(ids=[ids[1][0]], status="approved"),
        CurrentUser("pagination-test-user", "admin"),
    )

    with get_db() as conn:
        after = conn.execute(
            "SELECT pagination_generation FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()["pagination_generation"]

    jumped = list_rows(project_id, page=15, page_size=10, include_total=False)

    assert after == before + 1
    assert jumped["pagination_mode"] == "offset"
    assert jumped["anchor_page"] is None
    assert [item["source_row_number"] for item in jumped["items"]] == list(range(141, 151))


def test_page_anchors_are_disabled_for_relevance_filters(project_factory):
    project_id = project_factory(
        [
            {
                "source_row_number": i,
                "ai_relevance": "相關",
                "comment_content": f"row {i}",
            }
            for i in range(1, 301)
        ]
    )

    first_jump = list_rows(
        project_id,
        page=10,
        page_size=10,
        relevance="相關",
    )
    second_jump = list_rows(
        project_id,
        page=15,
        page_size=10,
        relevance="相關",
        include_total=False,
    )

    assert first_jump["pagination_mode"] == "offset"
    assert second_jump["pagination_mode"] == "offset"
    assert second_jump["anchor_page"] is None


def test_anchor_rows_are_namespaced_by_filter_signature(project_factory):
    project_id = project_factory(
        [
            {
                "source_row_number": i,
                "status": "pending" if i <= 200 else "approved",
                "comment_content": f"row {i}",
            }
            for i in range(1, 301)
        ]
    )

    list_rows(project_id, page=10, page_size=10, status="pending")
    approved = list_rows(
        project_id,
        page=5,
        page_size=10,
        status="approved",
        include_total=False,
    )

    assert approved["pagination_mode"] == "offset"
    assert approved["anchor_page"] is None
    assert [item["source_row_number"] for item in approved["items"]] == list(range(241, 251))
