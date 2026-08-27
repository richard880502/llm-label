import json
from typing import Any

from ..database import DatabaseConnection
from .legacy import fresh_legacy_input_mapping, fresh_legacy_schema
from .models import AnnotationSchema, InputMapping
from .schema_service import validate_schema


def _decode_json(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def get_project_schema(conn: DatabaseConnection, project_id: int) -> AnnotationSchema:
    row = conn.execute("SELECT label_schema FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise LookupError("Project not found")
    raw = _decode_json(row["label_schema"])
    schema = fresh_legacy_schema() if raw is None else AnnotationSchema.model_validate(raw)
    return validate_schema(schema)


def set_project_schema(
    conn: DatabaseConnection,
    project_id: int,
    schema: AnnotationSchema,
) -> AnnotationSchema:
    validate_schema(schema)
    exists = conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
    if exists is None:
        raise LookupError("Project not found")
    payload = json.dumps(schema.model_dump(mode="json"), ensure_ascii=False)
    conn.execute("UPDATE projects SET label_schema=?::jsonb WHERE id=?", (payload, project_id))
    return schema


def get_project_input_mapping(conn: DatabaseConnection, project_id: int) -> InputMapping:
    row = conn.execute("SELECT input_mapping FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise LookupError("Project not found")
    raw = _decode_json(row["input_mapping"])
    return fresh_legacy_input_mapping() if raw is None else InputMapping.model_validate(raw)


def set_project_input_mapping(
    conn: DatabaseConnection,
    project_id: int,
    mapping: InputMapping,
) -> InputMapping:
    exists = conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
    if exists is None:
        raise LookupError("Project not found")
    payload = json.dumps(mapping.model_dump(mode="json"), ensure_ascii=False)
    conn.execute("UPDATE projects SET input_mapping=?::jsonb WHERE id=?", (payload, project_id))
    return mapping
