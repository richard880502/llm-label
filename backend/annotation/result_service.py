from .models import AnnotationResult, AnnotationSchema


def normalize_result(schema: AnnotationSchema, result: AnnotationResult) -> AnnotationResult:
    """Normalize a result without inventing ambiguous child labels.

    The only structural correction performed here is adding required ancestors for
    selected child labels when the schema enables ``child_requires_parent``.
    Unknown labels are intentionally preserved so ``validate_result`` can report
    them instead of silently dropping model mistakes.
    """
    by_id = {label.id: label for label in schema.labels}
    normalized: list[str] = []
    seen: set[str] = set()

    def append_with_parents(label_id: str) -> None:
        label = by_id.get(label_id)
        if schema.constraints.child_requires_parent and label and label.parent_id:
            append_with_parents(label.parent_id)
        if label_id not in seen:
            seen.add(label_id)
            normalized.append(label_id)

    for label_id in result.labels:
        append_with_parents(label_id)

    relevance = result.relevance
    if not schema.relevance or not schema.relevance.enabled:
        relevance = None

    return AnnotationResult(
        relevance=relevance,
        labels=normalized,
        reason=result.reason,
        metadata=result.metadata,
    )
