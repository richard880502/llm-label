import pytest

from backend.annotation.legacy import (
    fresh_legacy_schema,
    generic_to_legacy_result,
    legacy_to_generic_result,
)
from backend.annotation.models import AnnotationResult, AnnotationSchema, LabelDefinition, SchemaConstraints
from backend.annotation.schema_service import (
    SchemaValidationError,
    build_schema_prompt_fragment,
    validate_result,
    validate_schema,
)


def test_legacy_schema_preserves_emotional_parent_child_rule():
    schema = fresh_legacy_schema()
    valid = legacy_to_generic_result(
        "相關",
        ["Emotional Resonance"],
        ["Excited and Proud"],
        "明確表達興奮",
    )

    validate_result(schema, valid)

    invalid = AnnotationResult(
        relevance="related",
        labels=["excited_and_proud"],
    )
    with pytest.raises(SchemaValidationError):
        validate_result(schema, invalid)


def test_legacy_generic_round_trip():
    generic = legacy_to_generic_result(
        "相關",
        ["Words of Affirmation", "Emotional Resonance"],
        ["Touched and Inspired"],
        "test",
    )
    projected = generic_to_legacy_result(generic)

    assert projected == {
        "relevance": "相關",
        "labels": ["Words of Affirmation", "Emotional Resonance"],
        "emotional_subtypes": ["Touched and Inspired"],
        "reason": "test",
    }


def test_custom_hierarchy_is_domain_agnostic():
    schema = AnnotationSchema(
        mode="multi_label",
        labels=[
            LabelDefinition(id="after_sales", name="售後"),
            LabelDefinition(id="shipping", name="物流", parent_id="after_sales"),
            LabelDefinition(id="refund", name="退款", parent_id="after_sales"),
        ],
        constraints=SchemaConstraints(max_depth=2, child_requires_parent=True),
    )
    validate_schema(schema)
    validate_result(schema, AnnotationResult(labels=["after_sales", "shipping"]))

    with pytest.raises(SchemaValidationError):
        validate_result(schema, AnnotationResult(labels=["shipping"]))


def test_schema_rejects_unknown_parent_and_cycles():
    with pytest.raises(SchemaValidationError):
        validate_schema(
            AnnotationSchema(labels=[LabelDefinition(id="child", name="Child", parent_id="missing")])
        )

    with pytest.raises(SchemaValidationError):
        validate_schema(
            AnnotationSchema(
                labels=[
                    LabelDefinition(id="a", name="A", parent_id="b"),
                    LabelDefinition(id="b", name="B", parent_id="a"),
                ]
            )
        )


def test_prompt_fragment_contains_ids_hierarchy_and_definitions():
    schema = AnnotationSchema(
        labels=[
            LabelDefinition(id="after_sales", name="售後", description="售後服務"),
            LabelDefinition(
                id="shipping",
                name="物流",
                parent_id="after_sales",
                description="配送與到貨",
                examples=["兩週還沒收到"],
            ),
        ]
    )
    fragment = build_schema_prompt_fragment(schema)

    assert "售後 > 物流 [id=shipping]" in fragment
    assert "Definition: 配送與到貨" in fragment
    assert "Examples: 兩週還沒收到" in fragment
