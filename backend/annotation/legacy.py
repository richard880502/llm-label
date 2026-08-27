from .models import (
    AnnotationResult,
    AnnotationSchema,
    InputMapping,
    LabelDefinition,
    RelevanceSchema,
    RelevanceValue,
    SchemaConstraints,
)


LEGACY_LABELS = [
    "Words of Affirmation",
    "Quality Time",
    "Acts of Service",
    "Tangible Gifts",
    "Physical Touch",
    "Mirroring",
    "Emotional Resonance",
]

LEGACY_SUBTYPES = [
    "Satisfied and Pleased",
    "Excited and Proud",
    "Touched and Inspired",
    "Loved and Warm",
    "Accepted and Supported",
    "Hopeful and Expectant",
    "Relaxed and Fun",
    "Scared and Vulnerable",
    "Regretful and Missing",
    "Grateful and Heartfelt",
    "未確定",
]

LEGACY_LABEL_IDS = {
    "Words of Affirmation": "words_of_affirmation",
    "Quality Time": "quality_time",
    "Acts of Service": "acts_of_service",
    "Tangible Gifts": "tangible_gifts",
    "Physical Touch": "physical_touch",
    "Mirroring": "mirroring",
    "Emotional Resonance": "emotional_resonance",
}

LEGACY_SUBTYPE_IDS = {
    "Satisfied and Pleased": "satisfied_and_pleased",
    "Excited and Proud": "excited_and_proud",
    "Touched and Inspired": "touched_and_inspired",
    "Loved and Warm": "loved_and_warm",
    "Accepted and Supported": "accepted_and_supported",
    "Hopeful and Expectant": "hopeful_and_expectant",
    "Relaxed and Fun": "relaxed_and_fun",
    "Scared and Vulnerable": "scared_and_vulnerable",
    "Regretful and Missing": "regretful_and_missing",
    "Grateful and Heartfelt": "grateful_and_heartfelt",
    "未確定": "emotional_unspecified",
}

LEGACY_RELEVANCE_IDS = {"相關": "related", "無關": "unrelated"}


LEGACY_LABEL_SCHEMA = AnnotationSchema(
    version=1,
    mode="multi_label",
    relevance=RelevanceSchema(
        enabled=True,
        values=[
            RelevanceValue(id="related", name="相關"),
            RelevanceValue(id="unrelated", name="無關"),
        ],
    ),
    labels=[
        *[LabelDefinition(id=LEGACY_LABEL_IDS[name], name=name) for name in LEGACY_LABELS],
        *[
            LabelDefinition(
                id=LEGACY_SUBTYPE_IDS[name],
                name=name,
                parent_id="emotional_resonance",
            )
            for name in LEGACY_SUBTYPES
        ],
    ],
    constraints=SchemaConstraints(
        max_depth=2,
        max_labels=None,
        child_requires_parent=True,
        require_child_for=["emotional_resonance"],
    ),
)

LEGACY_INPUT_MAPPING = InputMapping(
    text_field="COMMENTS_CONTENT",
    context_fields=["CONTENT"],
)


def fresh_legacy_schema() -> AnnotationSchema:
    return AnnotationSchema.model_validate(LEGACY_LABEL_SCHEMA.model_dump())


def fresh_legacy_input_mapping() -> InputMapping:
    return InputMapping.model_validate(LEGACY_INPUT_MAPPING.model_dump())


def legacy_to_generic_result(
    relevance: str | None,
    labels: list[str],
    emotional_subtypes: list[str],
    reason: str = "",
) -> AnnotationResult:
    selected = [LEGACY_LABEL_IDS[name] for name in labels if name in LEGACY_LABEL_IDS]
    subtype_ids = [LEGACY_SUBTYPE_IDS[name] for name in emotional_subtypes if name in LEGACY_SUBTYPE_IDS]
    if subtype_ids and "emotional_resonance" not in selected:
        selected.append("emotional_resonance")
    selected.extend(subtype_ids)
    return AnnotationResult(
        relevance=LEGACY_RELEVANCE_IDS.get(relevance),
        labels=selected,
        reason=reason,
    )


def generic_to_legacy_result(result: AnnotationResult) -> dict:
    label_names = {value: key for key, value in LEGACY_LABEL_IDS.items()}
    subtype_names = {value: key for key, value in LEGACY_SUBTYPE_IDS.items()}
    relevance_names = {value: key for key, value in LEGACY_RELEVANCE_IDS.items()}
    return {
        "relevance": relevance_names.get(result.relevance),
        "labels": [label_names[label_id] for label_id in result.labels if label_id in label_names],
        "emotional_subtypes": [subtype_names[label_id] for label_id in result.labels if label_id in subtype_names],
        "reason": result.reason,
    }
