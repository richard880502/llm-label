import json
import sqlite3


def select_examples(conn: sqlite3.Connection, project_id: int, llm_config: dict) -> list[dict]:
    mode = llm_config.get("examples_mode", "corrected_only")
    per_label = int(llm_config.get("examples_per_label", 3))

    if mode == "corrected_only":
        candidates = conn.execute("""
            SELECT * FROM rows
            WHERE project_id=? AND corrected_relevance IS NOT NULL
            ORDER BY reviewed_at DESC
        """, (project_id,)).fetchall()
    else:
        candidates = conn.execute("""
            SELECT * FROM rows
            WHERE project_id=? AND status IN ('approved', 'corrected')
            ORDER BY reviewed_at DESC
        """, (project_id,)).fetchall()

    if not candidates:
        return []

    by_key: dict[str, list] = {}
    for row in candidates:
        row = dict(row)
        relevance = row.get("corrected_relevance") or row.get("ai_relevance") or "無關"
        if relevance == "無關":
            key = "無關"
        else:
            labels = _parse_list(row.get("corrected_labels") or row.get("ai_labels"))
            key = labels[0] if labels else "其他"
        by_key.setdefault(key, [])
        if len(by_key[key]) < per_label:
            by_key[key].append(row)

    result = []
    for items in by_key.values():
        result.extend(items)
    return result


def _parse_list(val: str | None) -> list:
    if not val:
        return []
    try:
        r = json.loads(val)
        return r if isinstance(r, list) else []
    except Exception:
        return [x.strip() for x in val.split(",") if x.strip()]
