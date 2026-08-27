import csv
import io
import json
from datetime import date, datetime
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

from ..annotation.models import AnnotationSchema, InputMapping
from ..annotation.schema_service import SchemaValidationError, validate_schema
from ..auth import CurrentUser, get_current_user
from ..database import get_db

router = APIRouter()


class ImportPreview(BaseModel):
    filename: str
    row_count: int
    columns: list[str]
    rows: list[dict[str, Any]]
    inferred_mapping: InputMapping


class GenericProjectResponse(BaseModel):
    id: int
    name: str
    filename: str
    total_rows: int


def _json_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in row.items() if str(key)}


def _read_xlsx(content_bytes: bytes) -> list[dict[str, Any]]:
    if _load_wb is None:
        raise HTTPException(500, "伺服器未安裝 openpyxl，無法讀取 XLSX")
    try:
        workbook = _load_wb(io.BytesIO(content_bytes), read_only=True, data_only=True)
        worksheet = workbook.active
        rows_iter = worksheet.iter_rows(values_only=True)
        first = next(rows_iter, None)
        if first is None:
            workbook.close()
            return []
        headers = [str(value).strip() if value is not None else "" for value in first]
        result = []
        for values in rows_iter:
            result.append(_normalize_row({headers[i]: values[i] for i in range(min(len(headers), len(values))) if headers[i]}))
        workbook.close()
        return result
    except HTTPException:
        raise
    except Exception as xlsx_error:
        if _xlrd is None:
            raise HTTPException(400, "無法讀取此檔案，請確認格式為 .xlsx 或 .xls") from xlsx_error
        try:
            workbook = _xlrd.open_workbook(file_contents=content_bytes)
            worksheet = workbook.sheet_by_index(0)
            headers = [str(worksheet.cell_value(0, column)).strip() for column in range(worksheet.ncols)]
            return [
                _normalize_row({headers[column]: worksheet.cell_value(row, column) for column in range(worksheet.ncols) if headers[column]})
                for row in range(1, worksheet.nrows)
            ]
        except Exception as xls_error:
            raise HTTPException(400, "無法讀取此檔案，請確認格式為 .xlsx 或 .xls") from xls_error


def _read_json(content_bytes: bytes, *, jsonl: bool) -> list[dict[str, Any]]:
    try:
        text = content_bytes.decode("utf-8-sig")
        if jsonl:
            payload = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            payload = json.loads(text)
            if isinstance(payload, dict):
                if isinstance(payload.get("rows"), list):
                    payload = payload["rows"]
                elif isinstance(payload.get("data"), list):
                    payload = payload["data"]
                else:
                    payload = [payload]
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise ValueError("JSON root must be an object list")
        return [_normalize_row(item) for item in payload]
    except Exception as error:
        raise HTTPException(400, "JSON/JSONL 格式無法解析，資料必須是 object rows") from error


def _read_csv(content_bytes: bytes) -> list[dict[str, Any]]:
    try:
        text = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content_bytes.decode("big5", errors="replace")
    return [_normalize_row(dict(row)) for row in csv.DictReader(io.StringIO(text))]


def _read_upload(filename: str, content_bytes: bytes) -> list[dict[str, Any]]:
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xls")):
        return _read_xlsx(content_bytes)
    if lower.endswith(".jsonl"):
        return _read_json(content_bytes, jsonl=True)
    if lower.endswith(".json"):
        return _read_json(content_bytes, jsonl=False)
    if lower.endswith(".csv"):
        return _read_csv(content_bytes)
    raise HTTPException(400, "不支援的檔案格式，請使用 CSV、XLSX、XLS、JSON 或 JSONL")


def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for row in rows[:50]:
        for key in row:
            if key not in seen:
                seen.add(key)
                result.append(key)
    return result


def _infer_field(columns: list[str], candidates: list[str]) -> str | None:
    normalized = {column.lower().replace("-", "_").replace(" ", "_"): column for column in columns}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    for column in columns:
        lower = column.lower()
        if any(candidate in lower for candidate in candidates):
            return column
    return None


def _infer_mapping(columns: list[str]) -> InputMapping:
    text_field = _infer_field(
        columns,
        ["message", "text", "comment", "comment_content", "comments_content", "content", "description", "body", "review"],
    ) or (columns[0] if columns else "")
    id_field = _infer_field(columns, ["ticket_no", "row_id", "record_id", "external_id", "id", "uuid"])
    excluded = {text_field}
    if id_field:
        excluded.add(id_field)
    metadata_fields = [column for column in columns if column not in excluded]
    return InputMapping(
        text_field=text_field,
        id_field=id_field,
        metadata_fields=metadata_fields,
        context_fields=[],
    )


def _parse_label_field(value: Any, mapping: InputMapping) -> list[str]:
    if not mapping.labels or value is None or value == "":
        return []
    raw = str(value).strip()
    if not raw:
        return []
    if mapping.labels.format == "json":
        try:
            parsed = json.loads(raw)
            return [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else [str(parsed)]
        except Exception:
            return [raw]
    if mapping.labels.format == "delimiter":
        delimiter = mapping.labels.delimiter or ","
        return [item.strip() for item in raw.split(delimiter) if item.strip()]
    return [raw]


def _canonical_metadata(row: dict[str, Any], mapping: InputMapping) -> dict[str, Any]:
    metadata = {field: row.get(field, "") for field in mapping.metadata_fields if field in row}
    if mapping.id_field:
        metadata["_source_id"] = row.get(mapping.id_field, "")
    if mapping.context_fields:
        metadata["_context"] = {field: row.get(field, "") for field in mapping.context_fields if field in row}
    if mapping.labels:
        metadata["_source_labels"] = _parse_label_field(row.get(mapping.labels.field), mapping)
    if mapping.hierarchy:
        metadata["_source_hierarchy"] = {
            "parent": row.get(mapping.hierarchy.parent_field, "") if mapping.hierarchy.parent_field else "",
            "child": row.get(mapping.hierarchy.child_field, "") if mapping.hierarchy.child_field else "",
        }
    return metadata


def _context_text(row: dict[str, Any], mapping: InputMapping) -> str:
    return "\n".join(
        f"{field}: {row.get(field, '')}"
        for field in mapping.context_fields
        if row.get(field, "") not in (None, "")
    )


@router.post("/preview", response_model=ImportPreview)
async def preview_import(
    file: UploadFile = File(...),
    _: CurrentUser = Depends(get_current_user),
):
    content_bytes = await file.read()
    filename = file.filename or "dataset"
    rows = _read_upload(filename, content_bytes)
    if not rows:
        raise HTTPException(400, "檔案是空的")
    columns = _ordered_columns(rows)
    if not columns:
        raise HTTPException(400, "找不到可用欄位")
    return ImportPreview(
        filename=filename,
        row_count=len(rows),
        columns=columns,
        rows=rows[:20],
        inferred_mapping=_infer_mapping(columns),
    )


@router.post("/projects", response_model=GenericProjectResponse)
async def create_generic_project(
    name: str = Form(...),
    mapping_json: str = Form(...),
    schema_json: str = Form(...),
    annotation_instructions: str = Form(""),
    file: UploadFile = File(...),
    _: CurrentUser = Depends(get_current_user),
):
    try:
        mapping = InputMapping.model_validate(json.loads(mapping_json))
    except Exception as error:
        raise HTTPException(400, {"code": "INVALID_INPUT_MAPPING", "message": str(error)}) from error
    try:
        schema = validate_schema(AnnotationSchema.model_validate(json.loads(schema_json)))
    except SchemaValidationError as error:
        raise HTTPException(400, {"code": "INVALID_SCHEMA", "issues": error.issues}) from error
    except Exception as error:
        raise HTTPException(400, {"code": "INVALID_SCHEMA", "message": str(error)}) from error

    content_bytes = await file.read()
    filename = file.filename or "dataset"
    rows = _read_upload(filename, content_bytes)
    if not rows:
        raise HTTPException(400, "檔案是空的")
    columns = set(_ordered_columns(rows))
    if mapping.text_field not in columns:
        raise HTTPException(400, f"主要文字欄位不存在：{mapping.text_field}")
    referenced = set(mapping.metadata_fields) | set(mapping.context_fields)
    if mapping.id_field:
        referenced.add(mapping.id_field)
    if mapping.labels:
        referenced.add(mapping.labels.field)
    if mapping.hierarchy:
        if mapping.hierarchy.parent_field:
            referenced.add(mapping.hierarchy.parent_field)
        if mapping.hierarchy.child_field:
            referenced.add(mapping.hierarchy.child_field)
    missing = sorted(field for field in referenced if field not in columns)
    if missing:
        raise HTTPException(400, {"code": "UNKNOWN_MAPPING_FIELDS", "fields": missing})

    schema_payload = json.dumps(schema.model_dump(mode="json"), ensure_ascii=False)
    mapping_payload = json.dumps(mapping.model_dump(mode="json"), ensure_ascii=False)

    with get_db() as conn:
        try:
            project_cursor = conn.execute(
                """INSERT INTO projects
                   (name, filename, total_rows, annotation_instructions, input_mapping, label_schema)
                   VALUES (?, ?, ?, ?, ?::jsonb, ?::jsonb)""",
                (name.strip(), filename, len(rows), annotation_instructions, mapping_payload, schema_payload),
            )
            project_id = project_cursor.lastrowid
            insert_rows = []
            for index, source_row in enumerate(rows, start=1):
                text = str(source_row.get(mapping.text_field, "") or "")
                metadata = _canonical_metadata(source_row, mapping)
                context = _context_text(source_row, mapping)
                insert_rows.append((
                    project_id,
                    index,
                    json.dumps(source_row, ensure_ascii=False),
                    context or None,
                    text,
                    text,
                    json.dumps(metadata, ensure_ascii=False),
                ))
            conn.executemany(
                """INSERT INTO rows
                   (project_id, source_row_number, original_data, content, comment_content, text, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?::jsonb)""",
                insert_rows,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return GenericProjectResponse(id=project_id, name=name.strip(), filename=filename, total_rows=len(rows))
