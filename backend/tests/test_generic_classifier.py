import json

from backend.annotation.legacy import fresh_legacy_schema
from backend.annotation.models import (
    AnnotationSchema,
    LabelDefinition,
    RelevanceSchema,
    RelevanceValue,
    SchemaConstraints,
)
from backend.llm.classifier_runtime import compatibility_projection, parse_response
from backend.llm.client import normalize_llm_content
from backend.llm.generic_prompt_builder import build_generic_prompt


def _shipping_schema() -> AnnotationSchema:
    return AnnotationSchema(
        mode="multi_label",
        relevance=RelevanceSchema(
            enabled=True,
            values=[
                RelevanceValue(id="relevant", name="相關"),
                RelevanceValue(id="irrelevant", name="無關"),
            ],
        ),
        labels=[
            LabelDefinition(id="after_sales", name="售後"),
            LabelDefinition(id="shipping", name="物流", parent_id="after_sales"),
            LabelDefinition(id="refund", name="退款", parent_id="after_sales"),
        ],
        constraints=SchemaConstraints(
            max_depth=2,
            child_requires_parent=True,
        ),
    )


def test_parse_response_accepts_names_and_normalizes_to_ids():
    schema = _shipping_schema()
    parsed = parse_response(
        json.dumps(
            {
                "relevance": "相關",
                "labels": ["物流"],
                "reason": "商品尚未送達",
            },
            ensure_ascii=False,
        ),
        schema,
    )

    assert parsed["fallback"] is False
    result = parsed["annotation_result"]
    assert result.relevance == "relevant"
    assert result.labels == ["after_sales", "shipping"]


def test_unknown_label_is_not_silently_dropped():
    parsed = parse_response(
        '{"relevance":"relevant","labels":["made_up"],"reason":"x"}',
        _shipping_schema(),
    )

    assert parsed["fallback"] is True
    assert "made_up" in parsed["annotation_result"].reason


def test_legacy_emotional_subtypes_are_absorbed_into_generic_labels():
    schema = fresh_legacy_schema()
    parsed = parse_response(
        json.dumps(
            {
                "relevance": "相關",
                "labels": ["Emotional Resonance"],
                "emotional_subtypes": ["Excited and Proud"],
                "reason": "明確表達興奮與驕傲",
            },
            ensure_ascii=False,
        ),
        schema,
    )

    assert parsed["fallback"] is False
    result = parsed["annotation_result"]
    assert result.labels == ["emotional_resonance", "excited_and_proud"]

    projection = compatibility_projection(schema, result)
    assert projection["relevance"] == "相關"
    assert projection["labels"] == ["Emotional Resonance"]
    assert projection["emotional_subtypes"] == ["Excited and Proud"]


def test_double_brace_legacy_response_is_recovered():
    raw = '{{"relevance": "相關", "labels": ["Mirroring", "Emotional Resonance"], "emotional_subtypes": ["Hopeful and Expectant"], "reason": "留言者表示想學習老師教單字的方法，並表達期待與擔心來不及的情緒。"}}'
    parsed = parse_response(raw, fresh_legacy_schema())

    assert parsed["fallback"] is False
    assert parsed["raw"] == raw
    result = parsed["annotation_result"]
    assert result.relevance == "related"
    assert result.labels == [
        "mirroring",
        "emotional_resonance",
        "hopeful_and_expectant",
    ]


def test_exact_runtime_response_with_markdown_escaped_underscore_is_recovered():
    raw = r'{{"relevance": "相關", "labels": ["Mirroring", "Emotional Resonance"], "emotional\_subtypes": ["Hopeful and Expectant"], "reason": "留言者表示想學習老師教單字的方法，並表達期待與擔心來不及的情緒。"}}'
    normalized = normalize_llm_content(raw)

    assert 'emotional\\_subtypes' not in normalized
    assert 'emotional_subtypes' in normalized

    parsed = parse_response(normalized, fresh_legacy_schema())
    assert parsed["fallback"] is False
    result = parsed["annotation_result"]
    assert result.relevance == "related"
    assert result.labels == [
        "mirroring",
        "emotional_resonance",
        "hopeful_and_expectant",
    ]


def test_prose_wrapped_json_object_is_recovered_without_rewriting_content():
    raw = '分類結果如下：\n{"relevance":"相關","labels":["物流"],"reason":"配送延遲"}\n以上。'
    parsed = parse_response(raw, _shipping_schema())

    assert parsed["fallback"] is False
    assert parsed["raw"] == raw
    result = parsed["annotation_result"]
    assert result.labels == ["after_sales", "shipping"]
    assert result.reason == "配送延遲"


def test_malformed_inner_json_still_fails_after_wrapper_recovery():
    raw = '{{"relevance":"相關","labels":["物流",],"reason":"x"}}'
    parsed = parse_response(raw, _shipping_schema())

    assert parsed["fallback"] is True
    assert "解析失敗" in parsed["annotation_result"].reason


def test_generic_projection_keeps_custom_taxonomy_readable_for_legacy_ui():
    schema = _shipping_schema()
    parsed = parse_response(
        '{"relevance":"relevant","labels":["after_sales","shipping"],"reason":"late"}',
        schema,
    )

    projection = compatibility_projection(schema, parsed["annotation_result"])
    assert projection["relevance"] == "相關"
    assert projection["labels"] == ["售後", "物流"]
    assert projection["emotional_subtypes"] == []


def test_generic_prompt_uses_project_schema_ids_and_generic_contract():
    schema = _shipping_schema()
    prompt = build_generic_prompt(
        template="",
        examples=[],
        text="我的商品兩週還沒收到",
        project_instructions="配送延遲歸類為物流。",
        schema=schema,
    )

    assert "售後 > 物流 [id=shipping]" in prompt
    assert "配送延遲歸類為物流。" in prompt
    assert '"<label_id>"' in prompt
    assert "不要輸出 emotional_subtypes" in prompt
    assert "Words of Affirmation" not in prompt
