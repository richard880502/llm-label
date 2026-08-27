import json
from typing import Any, Mapping

from .models import AnnotationResult, AnnotationSchema
from .result_service import normalize_result
from .schema_service import SchemaValidationError, validate_result


def _decode_json_object(value: Any) -> dict | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _decode_list(value: Any) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _token(value: Any) -> str | None:
    if isinstance(value, str):
        token = value.strip()
        return token or None
    if isinstance(value, dict):
        candidate = value.get("id") or value.get("name")
        if isinstance(candidate, str):
            candidate = candidate.strip()
            return candidate or None
    return None


def _resolve_label(schema: AnnotationSchema, value: Any) -> str | None:
    token = _token(value)
    if token is None:
        return None
    by_id = {label.id: label.id for label in schema.labels}
    by_name = {label.name: label.id for label in schema.labels}
    # Preserve unknown values so validate_result can return an explicit error.
    return by_id.get(token) or by_name.get(token) or token


def _resolve_relevance(schema: AnnotationSchema, value: Any) -> str | None:
    if not schema.relevance or not schema.relevance.enabled:
        return None
    token = _token(value)
    if token is None:
        return None
    by_id = {item.id: item.id for item in schema.relevance.values}
    by_name = {item.name: item.id for item in schema.relevance.values}
    return by_id.get(token) or by_name.get(token) or token


def _result_from_legacy_fields(
    schema: AnnotationSchema,
    relevance: Any,
    labels: Any,
    subtypes: Any,
    *,
    reason: str = "",
) -> AnnotationResult:
    selected: list[str] = []
    for item in [*_decode_list(labels), *_decode_list(subtypes)]:
        label_id = _resolve_label(schema, item)
        if label_id is not None and label_id not in selected:
            selected.append(label_id)
    result = AnnotationResult(
        relevance=_resolve_relevance(schema, relevance),
        labels=selected,
        reason=reason,
    )
    return normalize_result(schema, result)


def current_review_result(schema: AnnotationSchema, row: Mapping[str, Any]) -> AnnotationResult | None:
    """Return the best canonical result available for partial review updates."""
    for key in ("corrected_result", "prediction"):
        payload = _decode_json_object(row.get(key))
        if payload is not None:
            try:
                result = AnnotationResult.model_validate(payload)
                result = normalize_result(schema, result)
                validate_result(schema, result)
                return result
            except Exception:
                pass

    corrected_present = any(
        row.get(key) is not None
        for key in (
            "corrected_relevance",
            "corrected_labels",
            "corrected_emotional_subtypes",
        )
    )
    if corrected_present:
        candidate = _result_from_legacy_fields(
            schema,
            row.get("corrected_relevance"),
            row.get("corrected_labels"),
            row.get("corrected_emotional_subtypes"),
            reason="",
        )
        try:
            validate_result(schema, candidate)
            return candidate
        except SchemaValidationError:
            pass

    ai_present = any(
        row.get(key) is not None
        for key in ("ai_relevance", "ai_labels", "ai_emotional_subtypes")
    )
    if ai_present:
        candidate = _result_from_legacy_fields(
            schema,
            row.get("ai_relevance"),
            row.get("ai_labels"),
            row.get("ai_emotional_subtypes"),
            reason=row.get("ai_reason") or "",
        )
        try:
            validate_result(schema, candidate)
            return candidate
        except SchemaValidationError:
            pass
    return None


def build_corrected_result(
    schema: AnnotationSchema,
    row: Mapping[str, Any],
    *,
    corrected_result: AnnotationResult | None = None,
    corrected_relevance: str | None = None,
    corrected_labels: list[str] | None = None,
    corrected_emotional_subtypes: list[str] | None = None,
) -> AnnotationResult | None:
    """Build and validate a canonical correction from generic or legacy inputs.

    ``corrected_result`` is the preferred contract. Legacy review fields remain
    accepted while the current frontend migrates to the generic editor.
    """
    if corrected_result is not None:
        candidate = normalize_result(schema, corrected_result)
        return validate_result(schema, candidate)

    has_legacy_update = any(
        value is not None
        for value in (
            corrected_relevance,
            corrected_labels,
            corrected_emotional_subtypes,
        )
    )
    if not has_legacy_update:
        return None

    base = current_review_result(schema, row) or AnnotationResult()
    by_id = {label.id: label for label in schema.labels}
    base_top_level = [
        label_id for label_id in base.labels
        if label_id in by_id and by_id[label_id].parent_id is None
    ]
    base_children = [
        label_id for label_id in base.labels
        if label_id in by_id and by_id[label_id].parent_id is not None
    ]

    if corrected_labels is None:
        top_level = base_top_level
    else:
        top_level = []
        for item in corrected_labels:
            label_id = _resolve_label(schema, item)
            if label_id is not None and label_id not in top_level:
                top_level.append(label_id)

    if corrected_emotional_subtypes is None:
        children = base_children
    else:
        children = []
        for item in corrected_emotional_subtypes:
            label_id = _resolve_label(schema, item)
            if label_id is not None and label_id not in children:
                children.append(label_id)

    selected: list[str] = []
    for label_id in [*top_level, *children]:
        if label_id not in selected:
            selected.append(label_id)

    relevance = (
        _resolve_relevance(schema, corrected_relevance)
        if corrected_relevance is not None
        else base.relevance
    )
    candidate = AnnotationResult(
        relevance=relevance,
        labels=selected,
        reason=base.reason,
        metadata=base.metadata,
    )
    candidate = normalize_result(schema, candidate)
    return validate_result(schema, candidate)
