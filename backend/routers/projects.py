import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

try:
    from openpyxl import load_workbook as _load_wb
except ImportError:
    _load_wb = None

try:
    import xlrd as _xlrd
except ImportError:
    _xlrd = None

from ..auth import CurrentUser, get_current_user
from ..database import get_db

router = APIRouter()


def _mask_api_key(key: str) -> str:
    """回傳可安全送到前端的遮罩版本；長度固定，不洩漏真實金鑰長度。"""
    if not key:
        return ""
    if len(key) <= 4:
        return "*" * len(key)
    return key[:4] + "*" * 8


def _resolve_api_key(incoming: str, existing: str) -> str:
    """若前端送回的值等於既有金鑰的遮罩版本，代表使用者沒有修改，保留原始金鑰；
    否則視為使用者刻意輸入的新值（含清空成空字串）。"""
    if existing and incoming == _mask_api_key(existing):
        return existing
    return incoming


AI_COLS = {
    "ai_relevance": ["AI_RELEVANCE"],
    "ai_labels": ["AI_LABELS"],
    "ai_emotional_subtypes": ["AI_EMOTIONAL_SUBTYPES"],
    "ai_reason": ["AI_REASON"],
}
CONTENT_COLS = ["CONTENT", "content", "POST_CONTENT"]
COMMENT_COLS = ["COMMENTS_CONTENT", "comment_content", "COMMENT_CONTENT"]


def _find_col(row: dict[str, Any], candidates: list[str]) -> str:
    for c in candidates:
        if c in row:
            return row[c] or ""
    return ""


def _parse_list_field(val: str) -> str:
    if not val:
        return "[]"
    val = val.strip()
    if val.startswith("["):
        try:
            parsed = json.loads(val)
            # flatten any items that still contain | (legacy data)
            items = []
            for item in parsed:
                if "|" in item:
                    items.extend([x.strip() for x in item.split("|") if x.strip()])
                else:
                    items.append(item)
            return json.dumps(items, ensure_ascii=False)
        except Exception:
            pass
    sep = "|" if "|" in val else ","
    items = [x.strip() for x in val.split(sep) if x.strip()]
    return json.dumps(items, ensure_ascii=False)


@router.get("")
def list_projects(_: CurrentUser = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("""
        SELECT p.*,
               COUNT(r.id) as total,
               SUM(CASE WHEN r.status = 'approved'  THEN 1 ELSE 0 END) as approved,
               SUM(CASE WHEN r.status = 'corrected' THEN 1 ELSE 0 END) as corrected,
               SUM(CASE WHEN r.status = 'uncertain' THEN 1 ELSE 0 END) as uncertain,
               SUM(CASE WHEN r.status = 'pending'   THEN 1 ELSE 0 END) as pending
        FROM projects p
        LEFT JOIN rows r ON r.project_id = p.id
        GROUP BY p.id
        ORDER BY p.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _read_xlsx(content_bytes: bytes) -> list[dict[str, Any]]:
    if _load_wb is None:
        raise HTTPException(500, "伺服器未安裝 openpyxl，無法讀取 XLSX")
    try:
        wb = _load_wb(io.BytesIO(content_bytes), read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(h) if h is not None else "" for h in next(rows_iter)]
        result = []
        for row in rows_iter:
            result.append({headers[i]: (str(v) if v is not None else "") for i, v in enumerate(row)})
        wb.close()
        return result
    except Exception:
        # 嘗試舊版 .xls 格式
        if _xlrd is None:
            raise HTTPException(400, "無法讀取此檔案，請將檔案另存為 .xlsx 格式後重新上傳")
        try:
            wb = _xlrd.open_workbook(file_contents=content_bytes)
            ws = wb.sheet_by_index(0)
            headers = [str(ws.cell_value(0, c)) for c in range(ws.ncols)]
            result = []
            for r in range(1, ws.nrows):
                result.append({headers[c]: str(ws.cell_value(r, c)) for c in range(ws.ncols)})
            return result
        except Exception:
            raise HTTPException(400, "無法讀取此檔案，請確認格式為 .xlsx 或 .xls")


@router.post("")
async def create_project(name: str = Form(...), file: UploadFile = File(...), _: CurrentUser = Depends(get_current_user)):
    content_bytes = await file.read()
    fname = (file.filename or "").lower()

    if fname.endswith(".xlsx") or fname.endswith(".xls"):
        data_rows = _read_xlsx(content_bytes)
    else:
        try:
            text = content_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content_bytes.decode("big5", errors="replace")
        data_rows = list(csv.DictReader(io.StringIO(text)))

    if not data_rows:
        raise HTTPException(400, "檔案是空的")

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO projects (name, filename, total_rows) VALUES (?, ?, ?)",
        (name, file.filename, len(data_rows)),
    )
    project_id = cur.lastrowid

    insert_rows = []
    for i, row in enumerate(data_rows, start=1):
        src_num = row.get("SOURCE_ROW_NUMBER") or row.get("source_row_number") or str(i)
        try:
            src_num = int(src_num)
        except (ValueError, TypeError):
            src_num = i

        content = _find_col(row, CONTENT_COLS)
        comment = _find_col(row, COMMENT_COLS)

        ai_relevance = _find_col(row, ["AI_RELEVANCE", "ai_relevance"]) or None
        ai_labels = _parse_list_field(_find_col(row, ["AI_LABELS", "ai_labels"]))
        ai_subtypes = _parse_list_field(_find_col(row, ["AI_EMOTIONAL_SUBTYPES", "ai_emotional_subtypes"]))
        ai_reason = _find_col(row, ["AI_REASON", "ai_reason"]) or None

        insert_rows.append((
            project_id, src_num, json.dumps(row, ensure_ascii=False),
            content, comment, ai_relevance, ai_labels, ai_subtypes, ai_reason,
        ))

    conn.executemany(
        """INSERT INTO rows
           (project_id, source_row_number, original_data, content, comment_content,
            ai_relevance, ai_labels, ai_emotional_subtypes, ai_reason)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        insert_rows,
    )
    conn.commit()
    proj = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    return dict(proj)


class LLMConfigUpdate(BaseModel):
    api_url: str = ""
    api_key: str = ""
    model: str = ""
    prompt_template: str = ""
    examples_mode: str = "corrected_only"
    examples_per_label: int = 3


class LLMSlotUpdate(BaseModel):
    name: str = ""
    api_url: str = ""
    api_key: str = ""
    model: str = ""
    prompt_template: str = ""
    examples_mode: str = "corrected_only"
    examples_per_label: int = 3
    concurrency: int = 1
    extra_body: str = ""  # 進階：合併進 request body 的額外 JSON 參數（例如關閉 thinking mode）


class AnnotationInstructionsUpdate(BaseModel):
    annotation_instructions: str = ""


@router.get("/{project_id}/llm-configs")
def list_llm_configs(project_id: int, _: CurrentUser = Depends(get_current_user)):
    from ..llm.prompt_builder import DEFAULT_TEMPLATE
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM llm_configs WHERE project_id=? ORDER BY slot", (project_id,)
    ).fetchall()

    if not rows:
        proj = conn.execute("SELECT llm_config FROM projects WHERE id=?", (project_id,)).fetchone()
        if proj and proj["llm_config"]:
            try:
                old = json.loads(proj["llm_config"])
                if old.get("api_url") or old.get("model"):
                    conn.execute(
                        """INSERT INTO llm_configs
                           (project_id, slot, name, api_url, api_key, model, prompt_template, examples_mode, examples_per_label)
                           VALUES (?, 1, 'LLM 1', ?, ?, ?, ?, ?, ?)
                           ON CONFLICT (project_id, slot) DO UPDATE SET
                               name=EXCLUDED.name,
                               api_url=EXCLUDED.api_url,
                               api_key=EXCLUDED.api_key,
                               model=EXCLUDED.model,
                               prompt_template=EXCLUDED.prompt_template,
                               examples_mode=EXCLUDED.examples_mode,
                               examples_per_label=EXCLUDED.examples_per_label""",
                        (project_id, old.get("api_url", ""), old.get("api_key", ""),
                         old.get("model", ""), old.get("prompt_template", ""),
                         old.get("examples_mode", "corrected_only"), old.get("examples_per_label", 3)),
                    )
                    conn.commit()
                    rows = conn.execute(
                        "SELECT * FROM llm_configs WHERE project_id=? ORDER BY slot", (project_id,)
                    ).fetchall()
            except Exception:
                pass

    conn.close()
    by_slot = {}
    for r in rows:
        d = dict(r)
        if not d.get("prompt_template"):
            d["prompt_template"] = DEFAULT_TEMPLATE
        d["has_api_key"] = bool(d.get("api_key"))
        d["api_key"] = _mask_api_key(d.get("api_key") or "")
        by_slot[d["slot"]] = d

    result = []
    for slot in (1, 2, 3):
        if slot in by_slot:
            result.append(by_slot[slot])
        else:
            result.append({
                "project_id": project_id, "slot": slot,
                "name": f"LLM {slot}", "api_url": "", "api_key": "", "model": "",
                "prompt_template": DEFAULT_TEMPLATE,
                "examples_mode": "corrected_only", "examples_per_label": 3, "concurrency": 1,
                "extra_body": "", "has_api_key": False,
            })
    return result


@router.put("/{project_id}/llm-configs/{slot}")
def set_llm_config_slot(project_id: int, slot: int, body: LLMSlotUpdate, _: CurrentUser = Depends(get_current_user)):
    if slot not in (1, 2, 3):
        raise HTTPException(400, "slot 必須是 1、2 或 3")
    if body.extra_body.strip():
        try:
            parsed = json.loads(body.extra_body)
            if not isinstance(parsed, dict):
                raise ValueError("必須是 JSON 物件")
        except Exception:
            raise HTTPException(400, "額外請求參數必須是合法的 JSON 物件，例如 {\"chat_template_kwargs\": {\"enable_thinking\": false}}")
    conn = get_db()
    existing = conn.execute(
        "SELECT api_key FROM llm_configs WHERE project_id=? AND slot=?", (project_id, slot)
    ).fetchone()
    resolved_key = _resolve_api_key(body.api_key, existing["api_key"] if existing else "")
    conn.execute(
        """INSERT INTO llm_configs
           (project_id, slot, name, api_url, api_key, model, prompt_template, examples_mode, examples_per_label, concurrency, extra_body)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (project_id, slot) DO UPDATE SET
               name=EXCLUDED.name,
               api_url=EXCLUDED.api_url,
               api_key=EXCLUDED.api_key,
               model=EXCLUDED.model,
               prompt_template=EXCLUDED.prompt_template,
               examples_mode=EXCLUDED.examples_mode,
               examples_per_label=EXCLUDED.examples_per_label,
               concurrency=EXCLUDED.concurrency,
               extra_body=EXCLUDED.extra_body""",
        (project_id, slot, body.name or f"LLM {slot}",
         body.api_url, resolved_key, body.model,
         body.prompt_template, body.examples_mode, body.examples_per_label, max(1, body.concurrency),
         body.extra_body),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM llm_configs WHERE project_id=? AND slot=?", (project_id, slot)
    ).fetchone()
    conn.close()
    result = dict(row)
    result["has_api_key"] = bool(result.get("api_key"))
    result["api_key"] = _mask_api_key(result.get("api_key") or "")
    return result


@router.delete("/{project_id}/llm-configs/{slot}")
def delete_llm_config_slot(project_id: int, slot: int, _: CurrentUser = Depends(get_current_user)):
    conn = get_db()
    conn.execute(
        "DELETE FROM llm_configs WHERE project_id=? AND slot=?", (project_id, slot)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/{project_id}/llm-configs/{slot}/models")
def list_slot_models(project_id: int, slot: int, _: CurrentUser = Depends(get_current_user)):
    from ..llm.client import list_models
    conn = get_db()
    row = conn.execute(
        "SELECT api_url, api_key FROM llm_configs WHERE project_id=? AND slot=?", (project_id, slot)
    ).fetchone()
    conn.close()
    if not row or not row["api_url"]:
        return []
    try:
        return list_models(row["api_url"], api_key=row["api_key"] or "")
    except Exception:
        return []


@router.get("/{project_id}/llm-configs/{slot}/preview")
def preview_slot_prompt(project_id: int, slot: int, _: CurrentUser = Depends(get_current_user)):
    from ..llm.example_selector import select_examples
    from ..llm.prompt_builder import build_prompt
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM llm_configs WHERE project_id=? AND slot=?", (project_id, slot)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "此 slot 尚未設定")
    cfg = dict(row)
    examples = select_examples(conn, project_id, cfg)
    project = conn.execute(
        "SELECT annotation_instructions FROM projects WHERE id=?", (project_id,)
    ).fetchone()
    conn.close()
    sample = "這個活動辦得很好，謝謝主辦單位的用心！"
    prompt = build_prompt(
        cfg.get("prompt_template", ""),
        examples,
        sample,
        project["annotation_instructions"] if project else "",
    )
    return {"example_count": len(examples), "prompt": prompt}


@router.patch("/{project_id}/annotation-instructions")
def update_annotation_instructions(
    project_id: int,
    body: AnnotationInstructionsUpdate,
    _: CurrentUser = Depends(get_current_user),
):
    instructions = body.annotation_instructions.strip()
    if len(instructions) > 12000:
        raise HTTPException(400, "Codebook 最多可輸入 12,000 個字元")
    conn = get_db()
    updated = conn.execute(
        "UPDATE projects SET annotation_instructions=? WHERE id=?",
        (instructions, project_id),
    )
    if updated.rowcount == 0:
        conn.close()
        raise HTTPException(404, "Project not found")
    conn.commit()
    conn.close()
    return {"annotation_instructions": instructions}


@router.get("/{project_id}/llm-config")
def get_llm_config(project_id: int, _: CurrentUser = Depends(get_current_user)):
    from ..llm.prompt_builder import DEFAULT_TEMPLATE
    conn = get_db()
    proj = conn.execute(
        "SELECT llm_config, annotation_instructions FROM projects WHERE id=?", (project_id,)
    ).fetchone()
    conn.close()
    if not proj:
        raise HTTPException(404, "Project not found")
    config: dict = {}
    if proj["llm_config"]:
        try:
            config = json.loads(proj["llm_config"])
        except Exception:
            pass
    config.setdefault("prompt_template", DEFAULT_TEMPLATE)
    config.setdefault("api_url", "")
    config.setdefault("api_key", "")
    config.setdefault("model", "")
    config.setdefault("examples_mode", "corrected_only")
    config.setdefault("examples_per_label", 3)
    config["has_api_key"] = bool(config.get("api_key"))
    config["api_key"] = _mask_api_key(config.get("api_key") or "")
    return config


@router.patch("/{project_id}/llm-config")
def update_llm_config(project_id: int, body: LLMConfigUpdate, _: CurrentUser = Depends(get_current_user)):
    conn = get_db()
    proj = conn.execute("SELECT llm_config FROM projects WHERE id=?", (project_id,)).fetchone()
    existing_key = ""
    if proj and proj["llm_config"]:
        try:
            existing_key = json.loads(proj["llm_config"]).get("api_key", "")
        except Exception:
            pass
    payload = body.model_dump()
    payload["api_key"] = _resolve_api_key(payload["api_key"], existing_key)
    conn.execute(
        "UPDATE projects SET llm_config=? WHERE id=?",
        (json.dumps(payload, ensure_ascii=False), project_id),
    )
    conn.commit()
    conn.close()
    payload["has_api_key"] = bool(payload.get("api_key"))
    payload["api_key"] = _mask_api_key(payload.get("api_key") or "")
    return payload


@router.get("/{project_id}/llm-preview")
def preview_prompt(project_id: int, _: CurrentUser = Depends(get_current_user)):
    from ..llm.example_selector import select_examples
    from ..llm.prompt_builder import build_prompt
    conn = get_db()
    proj = conn.execute(
        "SELECT llm_config, annotation_instructions FROM projects WHERE id=?", (project_id,)
    ).fetchone()
    if not proj:
        conn.close()
        raise HTTPException(404, "Project not found")
    cfg: dict = {}
    if proj["llm_config"]:
        try:
            cfg = json.loads(proj["llm_config"])
        except Exception:
            pass
    examples = select_examples(conn, project_id, cfg)
    project_instructions = proj["annotation_instructions"] or ""
    conn.close()
    sample_comment = "這個活動辦得很好，謝謝主辦單位的用心！"
    prompt = build_prompt(
        cfg.get("prompt_template", ""), examples, sample_comment, project_instructions
    )
    return {"example_count": len(examples), "prompt": prompt}


@router.get("/{project_id}/llm-models")
def list_llm_models(project_id: int, _: CurrentUser = Depends(get_current_user)):
    from ..llm.client import list_models
    conn = get_db()
    proj = conn.execute("SELECT llm_config FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    if not proj or not proj["llm_config"]:
        return []
    try:
        cfg = json.loads(proj["llm_config"])
        api_url = cfg.get("api_url", "")
        api_key = cfg.get("api_key", "")
        if not api_url:
            return []
        return list_models(api_url, api_key=api_key)
    except Exception:
        return []


class AdoptSlotBody(BaseModel):
    slot: int
    target: str = "pending"  # "pending" | "all"


@router.post("/{project_id}/adopt-slot")
def adopt_slot(project_id: int, body: AdoptSlotBody, _: CurrentUser = Depends(get_current_user)):
    if body.slot not in (1, 2, 3):
        raise HTTPException(400, "slot 必須是 1、2 或 3")
    conn = get_db()
    extra = "AND r.status = 'pending'" if body.target == "pending" else ""
    results = conn.execute(
        f"""SELECT rlr.row_id, rlr.relevance, rlr.labels, rlr.subtypes
            FROM row_llm_results rlr
            JOIN rows r ON r.id = rlr.row_id
            WHERE rlr.slot = ? AND r.project_id = ? {extra}""",
        (body.slot, project_id),
    ).fetchall()
    params = [(r["relevance"], r["labels"], r["subtypes"], r["row_id"]) for r in results]
    if params:
        conn.executemany(
            """UPDATE rows SET
               corrected_relevance=?, corrected_labels=?, corrected_emotional_subtypes=?,
               status='corrected', reviewed_at=datetime('now','localtime')
               WHERE id=?""",
            params,
        )
    updated = len(params)
    conn.commit()
    conn.close()
    return {"updated": updated}


@router.delete("/{project_id}")
def delete_project(project_id: int, _: CurrentUser = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/{project_id}")
def get_project(project_id: int, _: CurrentUser = Depends(get_current_user)):
    conn = get_db()
    proj = conn.execute("""
        SELECT p.*,
               SUM(CASE WHEN r.status = 'approved'  THEN 1 ELSE 0 END) as approved,
               SUM(CASE WHEN r.status = 'corrected' THEN 1 ELSE 0 END) as corrected,
               SUM(CASE WHEN r.status = 'uncertain' THEN 1 ELSE 0 END) as uncertain,
               SUM(CASE WHEN r.status = 'pending'   THEN 1 ELSE 0 END) as pending
        FROM projects p
        LEFT JOIN rows r ON r.project_id = p.id
        WHERE p.id = ?
        GROUP BY p.id
    """, (project_id,)).fetchone()
    conn.close()
    if not proj:
        raise HTTPException(404, "Project not found")
    return dict(proj)
