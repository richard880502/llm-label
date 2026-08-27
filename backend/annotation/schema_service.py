from .models import AnnotationResult, AnnotationSchema


class SchemaValidationError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def validate_schema(schema: AnnotationSchema) -> AnnotationSchema:
    issues: list[str] = []
    labels = schema.labels
    by_id = {label.id: label for label in labels}

    if any(not label.id.strip() for label in labels):
        issues.append("label id 不可為空")
    if any(not label.name.strip() for label in labels):
        issues.append("label name 不可為空")
    if len(by_id) != len(labels):
        issues.append("label id 必須唯一")

    if schema.constraints.max_depth < 1:
        issues.append("max_depth 必須至少為 1")
    if schema.constraints.max_labels is not None and schema.constraints.max_labels < 1:
        issues.append("max_labels 必須為 null 或至少為 1")

    for label in labels:
        if label.parent_id is None:
            continue
        if label.parent_id == label.id:
            issues.append(f"label {label.id} 不可把自己設為 parent")
        elif label.parent_id not in by_id:
            issues.append(f"label {label.id} 的 parent_id {label.parent_id} 不存在")

    def depth(label_id: str) -> int:
        seen: set[str] = set()
        current = by_id[label_id]
        result = 1
        while current.parent_id is not None:
            if current.id in seen:
                raise SchemaValidationError([f"label hierarchy 含循環：{current.id}"])
            seen.add(current.id)
            parent = by_id.get(current.parent_id)
            if parent is None:
                return result
            current = parent
            result += 1
        return result

    if not issues:
        try:
            for label in labels:
                current_depth = depth(label.id)
                if current_depth > schema.constraints.max_depth:
                    issues.append(
                        f"label {label.id} 深度為 {current_depth}，超過 max_depth={schema.constraints.max_depth}"
                    )
        except SchemaValidationError as error:
            issues.extend(error.issues)

    require_child_for = set(schema.constraints.require_child_for)
    for label_id in require_child_for:
        if label_id not in by_id:
            issues.append(f"require_child_for 指定不存在的 label：{label_id}")
        elif not any(label.parent_id == label_id for label in labels):
            issues.append(f"require_child_for 的 label {label_id} 沒有任何 child")

    if (
        schema.mode == "single_label"
        and schema.constraints.child_requires_parent
        and any(label.parent_id is not None for label in labels)
    ):
        issues.append("single_label hierarchy 不可同時啟用 child_requires_parent")

    if schema.relevance and schema.relevance.enabled:
        values = schema.relevance.values
        ids = [value.id for value in values]
        if not values:
            issues.append("relevance 啟用時至少需要一個 value")
        if any(not value.id.strip() or not value.name.strip() for value in values):
            issues.append("relevance value 的 id/name 不可為空")
        if len(set(ids)) != len(ids):
            issues.append("relevance value id 必須唯一")

    if issues:
        raise SchemaValidationError(issues)
    return schema


def validate_result(schema: AnnotationSchema, result: AnnotationResult) -> AnnotationResult:
    validate_schema(schema)
    issues: list[str] = []
    by_id = {label.id: label for label in schema.labels}
    selected = result.labels
    selected_set = set(selected)

    if len(selected_set) != len(selected):
        issues.append("result.labels 不可包含重複 label")

    unknown = [label_id for label_id in selected if label_id not in by_id]
    if unknown:
        issues.append(f"result 含未知 label：{sorted(set(unknown))}")

    disabled = [label_id for label_id in selected if label_id in by_id and not by_id[label_id].enabled]
    if disabled:
        issues.append(f"result 含停用 label：{sorted(set(disabled))}")

    if schema.mode == "single_label" and len(selected) > 1:
        issues.append("single_label 專案每筆最多只能選一個 label")

    max_labels = schema.constraints.max_labels
    if max_labels is not None and len(selected) > max_labels:
        issues.append(f"result labels 數量超過 max_labels={max_labels}")

    if schema.constraints.child_requires_parent:
        for label_id in selected:
            label = by_id.get(label_id)
            if label and label.parent_id and label.parent_id not in selected_set:
                issues.append(f"child label {label_id} 必須同時包含 parent {label.parent_id}")

    for parent_id in schema.constraints.require_child_for:
        if parent_id not in selected_set:
            continue
        if not any(label.parent_id == parent_id and label.id in selected_set for label in schema.labels):
            issues.append(f"label {parent_id} 被選取時至少需要一個 child")

    if schema.relevance and schema.relevance.enabled:
        allowed = {value.id for value in schema.relevance.values}
        if result.relevance is None:
            issues.append("此 schema 啟用了 relevance，result.relevance 不可為空")
        elif result.relevance not in allowed:
            issues.append(f"未知 relevance value：{result.relevance}")

    if issues:
        raise SchemaValidationError(issues)
    return result


def build_schema_prompt_fragment(schema: AnnotationSchema) -> str:
    """Render project taxonomy into a deterministic prompt fragment for future LLM paths."""
    validate_schema(schema)
    by_id = {label.id: label for label in schema.labels}
    lines = [f"Classification mode: {schema.mode}", "Available labels:"]

    for label in schema.labels:
        path = [label.name]
        parent_id = label.parent_id
        while parent_id:
            parent = by_id[parent_id]
            path.append(parent.name)
            parent_id = parent.parent_id
        lines.append(f"- {' > '.join(reversed(path))} [id={label.id}]")
        if label.description:
            lines.append(f"  Definition: {label.description}")
        if label.examples:
            lines.append(f"  Examples: {' | '.join(label.examples)}")

    if schema.relevance and schema.relevance.enabled:
        values = ", ".join(f"{value.name} [id={value.id}]" for value in schema.relevance.values)
        lines.append(f"Relevance values: {values}")

    constraints = schema.constraints
    lines.append(
        "Constraints: "
        f"max_depth={constraints.max_depth}, "
        f"max_labels={constraints.max_labels}, "
        f"child_requires_parent={str(constraints.child_requires_parent).lower()}"
    )
    return "\n".join(lines)
