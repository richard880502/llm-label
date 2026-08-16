import asyncio
import json
import re

from ..database import DatabaseConnection, DatabaseRow, get_db
from .client import call_llm
from .example_selector import select_examples
from .prompt_builder import build_prompt

ALLOWED_LABELS = {
    "Words of Affirmation", "Quality Time", "Acts of Service",
    "Tangible Gifts", "Physical Touch", "Mirroring", "Emotional Resonance",
}
ALLOWED_SUBTYPES = {
    "Satisfied and Pleased", "Excited and Proud", "Touched and Inspired",
    "Loved and Warm", "Accepted and Supported", "Hopeful and Expectant",
    "Relaxed and Fun", "Scared and Vulnerable", "Regretful and Missing",
    "Grateful and Heartfelt",
}


def has_valid_emotional_hierarchy(labels: list[str], subtypes: list[str]) -> bool:
    """情緒子類型只可作為 Emotional Resonance 的子分類。"""
    return not subtypes or "Emotional Resonance" in labels

# 記錄使用者按下「停止」的任務 ID。同一個 process 內跨執行緒共用，
# set 的 add/discard/contains 由 GIL 保證單一操作是原子的，這裡的用法足夠安全。
_cancelled_tasks: set[int] = set()


def mark_task_cancelled(task_id: int) -> None:
    _cancelled_tasks.add(task_id)


def _extract_names(items: list, allowed: set) -> list:
    result = []
    for item in items:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name", "")
        else:
            continue
        if name in allowed:
            result.append(name)
    return result


PARSE_FAIL_MARKER = "⚠️ 解析失敗"


def parse_response(text: str) -> dict:
    original = text.strip()
    text = original
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
        relevance = data.get("relevance", "無關")
        if relevance not in ("相關", "無關"):
            relevance = "無關"
        labels = _extract_names(data.get("labels") or [], ALLOWED_LABELS)
        subtypes = _extract_names(data.get("emotional_subtypes") or [], ALLOWED_SUBTYPES)
        # LLM 偶爾會只輸出子類型。不要把不完整階層寫入正式結果；保留其餘
        # 可用標籤，讓審查者可在介面中補判。
        if not has_valid_emotional_hierarchy(labels, subtypes):
            subtypes = []
        return {
            "ai_relevance": relevance,
            "ai_labels": json.dumps(labels, ensure_ascii=False),
            "ai_emotional_subtypes": json.dumps(subtypes, ensure_ascii=False),
            "ai_reason": data.get("reason", ""),
            "fallback": False,
        }
    except Exception:
        # 不要用預設值假裝有判斷結果；relevance 設 None，
        # 並把原始回傳內容保留下來，讓審查者知道發生了什麼、要人工判斷。
        snippet = original[:300] + ("…" if len(original) > 300 else "")
        return {
            "ai_relevance": None,
            "ai_labels": "[]",
            "ai_emotional_subtypes": "[]",
            "ai_reason": f"{PARSE_FAIL_MARKER}，原始回傳：{snippet}",
            "fallback": True,
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
    conn = get_db()

    try:
        if task_id in _cancelled_tasks:
            # 任務還在排隊（狀態仍是 pending）就被取消，直接不執行；
            # 狀態已由 cancel_task 設為 failed，這裡不需再動。
            return

        cfg = _load_slot_config(conn, project_id, slot)
        if not cfg:
            conn.execute(
                "UPDATE tasks SET status='failed', error='找不到 LLM 設定', finished_at=datetime('now', 'localtime') WHERE id=?",
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
        conn.commit()

        if total == 0:
            conn.execute("UPDATE tasks SET status='done', finished_at=datetime('now', 'localtime') WHERE id=?", (task_id,))
            conn.commit()
            return

        examples = select_examples(conn, project_id, cfg)
        project = conn.execute(
            "SELECT annotation_instructions FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        project_instructions = project["annotation_instructions"] if project else ""
        processed_count = 0
        db_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(concurrency)
        loop = asyncio.get_event_loop()

        async def process_row(row: DatabaseRow) -> None:
            nonlocal processed_count
            if task_id in _cancelled_tasks:
                return
            comment = row["comment_content"] or ""

            if not comment.strip():
                result = {
                    "ai_relevance": "無關",
                    "ai_labels": "[]",
                    "ai_emotional_subtypes": "[]",
                    "ai_reason": "無留言內容",
                    "fallback": False,
                }
            else:
                prompt = build_prompt(prompt_template, examples, comment, project_instructions)
                try:
                    raw = await loop.run_in_executor(
                        None,
                        lambda u=api_url, m=model, p=prompt, k=api_key, eb=extra_body: call_llm(
                            u, m, p, api_key=k, extra_body=eb
                        ),
                    )
                    result = parse_response(raw)
                except Exception as e:
                    result = {
                        "ai_relevance": None,
                        "ai_labels": "[]",
                        "ai_emotional_subtypes": "[]",
                        "ai_reason": f"⚠️ LLM 呼叫失敗：{e}",
                        "fallback": True,
                    }

            async with db_lock:
                conn.execute(
                    """INSERT INTO row_llm_results
                       (row_id, slot, source_name, relevance, labels, subtypes, reason, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                       ON CONFLICT (row_id, slot) DO UPDATE SET
                           source_name=EXCLUDED.source_name,
                           relevance=EXCLUDED.relevance,
                           labels=EXCLUDED.labels,
                           subtypes=EXCLUDED.subtypes,
                           reason=EXCLUDED.reason,
                           updated_at=EXCLUDED.updated_at""",
                    (row["id"], slot, source_name, result["ai_relevance"], result["ai_labels"],
                     result["ai_emotional_subtypes"], result["ai_reason"]),
                )
                # slot 1 also updates the primary ai_* columns for backward compat
                if slot == 1:
                    conn.execute(
                        """UPDATE rows SET ai_relevance=?, ai_labels=?, ai_emotional_subtypes=?, ai_reason=?,
                                  llm_updated_at=datetime('now', 'localtime')
                           WHERE id=?""",
                        (result["ai_relevance"], result["ai_labels"],
                         result["ai_emotional_subtypes"], result["ai_reason"],
                         row["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE rows SET llm_updated_at=datetime('now', 'localtime') WHERE id=?",
                        (row["id"],),
                    )
                processed_count += 1
                conn.execute("UPDATE tasks SET processed=? WHERE id=?", (processed_count, task_id))
                conn.commit()

        async def process_with_semaphore(row: DatabaseRow) -> None:
            async with semaphore:
                await process_row(row)

        await asyncio.gather(*[process_with_semaphore(row) for row in rows_to_process])

        if task_id in _cancelled_tasks:
            # 使用者已按停止；cancel_task 已把狀態設為 failed，這裡不覆蓋。
            return

        conn.execute("UPDATE tasks SET status='done', finished_at=datetime('now', 'localtime') WHERE id=?", (task_id,))
        conn.commit()

    except Exception as e:
        if task_id in _cancelled_tasks:
            return
        # The failing statement may have left the transaction aborted; without this,
        # Postgres would reject the status-update below too (transaction is aborted,
        # commands ignored until end of transaction block).
        conn.rollback()
        conn.execute(
            "UPDATE tasks SET status='failed', error=?, finished_at=datetime('now', 'localtime') WHERE id=?",
            (str(e), task_id),
        )
        conn.commit()
    finally:
        _cancelled_tasks.discard(task_id)
        conn.close()
