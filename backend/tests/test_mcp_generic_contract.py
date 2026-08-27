import json

from backend.annotation.legacy import fresh_legacy_schema
from backend.annotation.models import (
    AnnotationSchema,
    LabelDefinition,
    RelevanceSchema,
    RelevanceValue,
    SchemaConstraints,
)
from backend.llm.classifier import parse_response
from backend.routers.tasks import LabelingResult, _mcp_result_contract


def test_mcp_result_model_accepts_project_defined_ids():
    result = LabelingResult(
        row_id=7,
        relevance="relevant",
        labels=["after_sales", "shipping"],
        reason="delivery is late",
        metadata={"agent": "codex"},
    )

    assert result.relevance == "relevant"
    assert result.labels == ["after_sales", "shipping"]
    assert result.metadata["agent"] == "codex"


def test_mcp_contract_is_derived_from_project_schema():
    schema = AnnotationSchema(
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
            LabelDefinition(id="disabled", name="停用", enabled=False),
        ],
        constraints=SchemaConstraints(max_depth=2, child_requires_parent=True),
    )

    contract = _mcp_result_contract(schema)

    assert contract["relevance"]["allowed_ids"] == ["relevant", "irrelevant"]
    assert contract["labels"]["allowed_ids"] == ["after_sales", "shipping"]
    assert "disabled" not in contract["labels"]["allowed_ids"]


def test_legacy_mcp_subtypes_are_coerced_through_shared_parser():
    schema = fresh_legacy_schema()
    payload = LabelingResult(
        row_id=1,
        relevance="相關",
        labels=["Emotional Resonance"],
        emotional_subtypes=["Excited and Proud"],
        reason="明顯興奮與驕傲",
    )

    parsed = parse_response(
        json.dumps(
            {
                "relevance": payload.relevance,
                "labels": payload.labels,
                "emotional_subtypes": payload.emotional_subtypes,
                "reason": payload.reason,
            },
            ensure_ascii=False,
        ),
        schema,
    )

    assert parsed["fallback"] is False
    assert parsed["annotation_result"].relevance == "related"
    assert parsed["annotation_result"].labels == [
        "emotional_resonance",
        "excited_and_proud",
    ]


def test_mcp_unknown_label_is_rejected_by_shared_parser():
    schema = AnnotationSchema(
        mode="multi_label",
        labels=[LabelDefinition(id="known", name="Known")],
        constraints=SchemaConstraints(max_depth=1, child_requires_parent=False),
    )

    parsed = parse_response(
        json.dumps({"relevance": None, "labels": ["unknown"], "reason": "bad"}),
        schema,
    )

    assert parsed["fallback"] is True
    assert "unknown" in parsed["annotation_result"].reason
