import json
from typing import Any


def select_examples(conn: Any, project_id: int, llm_config: dict) -> list[dict]:
    mode = llm_config.get("examples_mode", "corrected_only")
    per_label = int(llm_config.get("examples_per_label", 3))

    # 挑選範例只需要最近的一批候選即可湊出每個標籤的 per_label 數量，
    # 不需要整個專案的歷史資料；用 LIMIT 避免大型專案把全部資料載入記憶體。
    candidate_limit = 1000
    if mode == "corrected_only":
        candidates = conn.execute("""
            SELECT * FROM rows
            WHERE project_id=? AND corrected_relevance IS NOT NULL
              AND status IN ('approved', 'corrected')
            ORDER BY reviewed_at DESC
            LIMIT ?
        """, (project_id, candidate_limit)).fetchall()
    else:
        candidates = conn.execute("""
            SELECT * FROM rows
            WHERE project_id=? AND status IN ('approved', 'corrected')
            ORDER BY reviewed_at DESC
            LIMIT ?
        """, (project_id, candidate_limit)).fetchall()

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
