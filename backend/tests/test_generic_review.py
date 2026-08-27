import pytest

from backend.annotation.models import (
    AnnotationResult,
    AnnotationSchema,
    LabelDefinition,
    RelevanceSchema,
    RelevanceValue,
    SchemaConstraints,
)
from backend.annotation.review_service import build_corrected_result, current_review_result
from backend.annotation.schema_service import SchemaValidationError


def _schema() -> AnnotationSchema:
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


def test_direct_corrected_result_is_normalized_and_validated():
    result = build_corrected_result(
        _schema(),
        {},
        corrected_result=AnnotationResult(
            relevance="relevant",
            labels=["shipping"],
            reason="配送延誤",
        ),
    )

    assert result is not None
    assert result.labels == ["after_sales", "shipping"]
    assert result.reason == "配送延誤"


def test_legacy_review_fields_accept_project_label_names():
    result = build_corrected_result(
        _schema(),
        {
            "prediction": {
                "relevance": "relevant",
                "labels": ["after_sales", "shipping"],
                "reason": "原始模型理由",
            }
        },
        corrected_labels=["售後"],
        corrected_emotional_subtypes=["退款"],
    )

    assert result is not None
    assert result.relevance == "relevant"
    assert result.labels == ["after_sales", "refund"]


def test_partial_legacy_child_update_preserves_existing_parent():
    result = build_corrected_result(
        _schema(),
        {
            "corrected_result": {
                "relevance": "relevant",
                "labels": ["after_sales", "shipping"],
                "reason": "",
            }
        },
        corrected_emotional_subtypes=["refund"],
    )

    assert result is not None
    assert result.labels == ["after_sales", "refund"]


def test_unknown_project_label_is_rejected():
    with pytest.raises(SchemaValidationError):
        build_corrected_result(
            _schema(),
            {"prediction": {"relevance": "relevant", "labels": [], "reason": ""}},
            corrected_labels=["不存在的標籤"],
            corrected_emotional_subtypes=[],
        )


def test_current_review_result_prefers_correction_over_prediction():
    result = current_review_result(
        _schema(),
        {
            "corrected_result": {
                "relevance": "relevant",
                "labels": ["after_sales", "refund"],
                "reason": "人工",
            },
            "prediction": {
                "relevance": "relevant",
                "labels": ["after_sales", "shipping"],
                "reason": "模型",
            },
        },
    )

    assert result is not None
    assert result.labels == ["after_sales", "refund"]
    assert result.reason == "人工"
