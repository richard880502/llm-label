from fastapi import APIRouter, Depends, HTTPException

from ..annotation.models import AnnotationSchema, InputMapping
from ..annotation.project_service import (
    get_project_input_mapping,
    get_project_schema,
    set_project_input_mapping,
    set_project_schema,
)
from ..annotation.schema_service import SchemaValidationError
from ..auth import CurrentUser, get_current_user
from ..database import get_db

router = APIRouter()


def _schema_error(error: SchemaValidationError) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "INVALID_SCHEMA", "issues": error.issues})


@router.get("/{project_id}/schema", response_model=AnnotationSchema)
def read_project_schema(project_id: int, _: CurrentUser = Depends(get_current_user)):
    try:
        with get_db() as conn:
            return get_project_schema(conn, project_id)
    except LookupError:
        raise HTTPException(404, "Project not found")
    except SchemaValidationError as error:
        raise _schema_error(error)


@router.put("/{project_id}/schema", response_model=AnnotationSchema)
def update_project_schema(
    project_id: int,
    body: AnnotationSchema,
    _: CurrentUser = Depends(get_current_user),
):
    try:
        with get_db() as conn:
            schema = set_project_schema(conn, project_id, body)
            conn.commit()
            return schema
    except LookupError:
        raise HTTPException(404, "Project not found")
    except SchemaValidationError as error:
        raise _schema_error(error)


@router.get("/{project_id}/input-mapping", response_model=InputMapping)
def read_project_input_mapping(project_id: int, _: CurrentUser = Depends(get_current_user)):
    try:
        with get_db() as conn:
            return get_project_input_mapping(conn, project_id)
    except LookupError:
        raise HTTPException(404, "Project not found")


@router.put("/{project_id}/input-mapping", response_model=InputMapping)
def update_project_input_mapping(
    project_id: int,
    body: InputMapping,
    _: CurrentUser = Depends(get_current_user),
):
    try:
        with get_db() as conn:
            mapping = set_project_input_mapping(conn, project_id, body)
            conn.commit()
            return mapping
    except LookupError:
        raise HTTPException(404, "Project not found")
