import json

from ..annotation.legacy import LEGACY_LABEL_SCHEMA, legacy_to_generic_result
from ..annotation.models import AnnotationResult, AnnotationSchema
from ..annotation.schema_service import build_schema_prompt_fragment
from .prompt_builder import DEFAULT_PROJECT_INSTRUCTIONS, DEFAULT_TEMPLATE


GENERIC_PROJECT_INSTRUCTIONS = """請依照專案提供的標籤定義、階層與限制進行分類。
只根據輸入文字與 codebook 中可支持的證據判斷，不要自行創造不存在的標籤。
若證據不足，寧可少標，不要過度推論。"""

GENERIC_DEFAULT_TEMPLATE = """你是一個嚴格依照專案 schema 與人工 codebook 執行的文字標註員。

【專案 Codebook／目前生效規則】
{project_instructions}
【Codebook 結束】

【專案 Annotation Schema】
{label_schema}
【Annotation Schema 結束】

以下是人工複查後的正確分類範例：
{examples}

---
現在請分析以下主要文字：
{text}

{output_contract}
"""


def _is_legacy_schema(schema: AnnotationSchema) -> bool:
    return schema.model_dump(mode="json") == LEGACY_LABEL_SCHEMA.model_dump(mode="json")


def _parse_json_object(value) -> dict | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _parse_list(value) -> list:
    if not value:
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


def _resolve_label_id(schema: AnnotationSchema, value) -> str | None:
    if isinstance(value, dict):
        value = value.get("id") or value.get("name")
    if not isinstance(value, str):
        return None
    by_id = {label.id: label.id for label in schema.labels}
    by_name = {label.name: label.id for label in schema.labels}
    return by_id.get(value) or by_name.get(value)


def _resolve_relevance_id(schema: AnnotationSchema, value) -> str | None:
    if not schema.relevance or not schema.relevance.enabled:
        return None
    if isinstance(value, dict):
        value = value.get("id") or value.get("name")
    if not isinstance(value, str):
        return None
    by_id = {item.id: item.id for item in schema.relevance.values}
    by_name = {item.name: item.id for item in schema.relevance.values}
    return by_id.get(value) or by_name.get(value)


def _example_result(example: dict, schema: AnnotationSchema) -> AnnotationResult | None:
    for key in ("corrected_result", "prediction"):
        payload = _parse_json_object(example.get(key))
        if payload:
            try:
                return AnnotationResult.model_validate(payload)
            except Exception:
                pass

    relevance = example.get("corrected_relevance") or example.get("ai_relevance")
    labels = _parse_list(example.get("corrected_labels") or example.get("ai_labels"))
    subtypes = _parse_list(
        example.get("corrected_emotional_subtypes") or example.get("ai_emotional_subtypes")
    )
    reason = example.get("reviewer_note") or example.get("ai_reason") or ""

    if _is_legacy_schema(schema):
        return legacy_to_generic_result(relevance, labels, subtypes, reason=reason)

    resolved = []
    for item in [*labels, *subtypes]:
        label_id = _resolve_label_id(schema, item)
        if label_id and label_id not in resolved:
            resolved.append(label_id)
    return AnnotationResult(
        relevance=_resolve_relevance_id(schema, relevance),
        labels=resolved,
        reason=reason,
    )


def _render_examples(examples: list[dict], schema: AnnotationSchema) -> str:
    lines = []
    for example in examples:
        result = _example_result(example, schema)
        if result is None:
            continue
        text = example.get("text") or example.get("comment_content") or ""
        output = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        lines.append(f"TEXT: {text}\n輸出：{output}")
    return "\n\n".join(lines) if lines else "（尚無人工複查範例）"


def _output_contract(schema: AnnotationSchema) -> str:
    if schema.relevance and schema.relevance.enabled:
        relevance_rule = "relevance 必須使用 schema 中的 relevance id。"
        relevance_example = '"<relevance_id>"'
    else:
        relevance_rule = "此專案未啟用 relevance；relevance 請輸出 null。"
        relevance_example = "null"

    return f"""請只輸出一個 JSON 物件，不要 Markdown、不要額外說明。
{relevance_rule}
labels 必須只使用 schema 中的 label id；階層 child/parent 規則也必須符合 schema constraints。
不要輸出 emotional_subtypes 等專案特定欄位；所有分類都統一放在 labels 陣列。
格式：
{{"relevance": {relevance_example}, "labels": ["<label_id>"], "reason": "1-2 句簡短說明"}}"""


def build_generic_prompt(
    template: str,
    examples: list[dict],
    text: str,
    project_instructions: str,
    schema: AnnotationSchema,
) -> str:
    """Build the classifier prompt from a project-scoped annotation schema.

    Existing custom templates remain usable. New placeholders are optional:
    ``{label_schema}``, ``{text}``, and ``{output_contract}``. Legacy ``{comment}``
    and ``{examples}`` placeholders continue to work.
    """
    instructions = (project_instructions or "").strip()
    if not instructions:
        instructions = DEFAULT_PROJECT_INSTRUCTIONS if _is_legacy_schema(schema) else GENERIC_PROJECT_INSTRUCTIONS

    schema_fragment = build_schema_prompt_fragment(schema)
    constraints = schema.constraints
    if constraints.require_child_for:
        schema_fragment += "\nParents requiring at least one child: " + ", ".join(
            constraints.require_child_for
        )

    examples_text = _render_examples(examples, schema)
    output_contract = _output_contract(schema)

    if not template or template == DEFAULT_TEMPLATE:
        tmpl = GENERIC_DEFAULT_TEMPLATE
    else:
        tmpl = template

    replacements = {
        "{project_instructions}": instructions,
        "{label_schema}": schema_fragment,
        "{examples}": examples_text,
        "{comment}": text,
        "{text}": text,
        "{output_contract}": output_contract,
    }
    original_template = tmpl
    for placeholder, value in replacements.items():
        tmpl = tmpl.replace(placeholder, value)

    if "{project_instructions}" not in original_template:
        tmpl += f"\n\n【專案 Codebook／目前生效規則】\n{instructions}\n【Codebook 結束】"
    if "{label_schema}" not in original_template:
        tmpl += f"\n\n【專案 Annotation Schema】\n{schema_fragment}\n【Annotation Schema 結束】"
    if "{output_contract}" not in original_template:
        tmpl += f"\n\n{output_contract}"
    if "{comment}" not in original_template and "{text}" not in original_template:
        tmpl += f"\n\nTEXT: {text}"
    if "{examples}" not in original_template:
        tmpl += f"\n\n人工複查範例：\n{examples_text}"

    return tmpl
