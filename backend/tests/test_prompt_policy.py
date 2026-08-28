from backend.annotation.legacy import LEGACY_LABEL_SCHEMA
from backend.llm.prompt_builder import DEFAULT_TEMPLATE
from backend.llm.prompt_policy import prompt_fingerprint


def _example(text: str = "你真的做得很好") -> dict:
    return {
        "comment_content": text,
        "corrected_relevance": "相關",
        "corrected_labels": '["Words of Affirmation"]',
        "corrected_emotional_subtypes": "[]",
        "reviewer_note": "人工確認",
    }


def test_prompt_fingerprint_is_stable_for_same_effective_rules():
    first = prompt_fingerprint(
        DEFAULT_TEMPLATE,
        [_example()],
        "只依照 Codebook 判斷。",
        LEGACY_LABEL_SCHEMA,
    )
    second = prompt_fingerprint(
        DEFAULT_TEMPLATE,
        [_example()],
        "只依照 Codebook 判斷。",
        LEGACY_LABEL_SCHEMA,
    )
    assert first == second
    assert len(first) == 64


def test_prompt_fingerprint_changes_when_codebook_changes():
    before = prompt_fingerprint(
        DEFAULT_TEMPLATE,
        [_example()],
        "規則 A",
        LEGACY_LABEL_SCHEMA,
    )
    after = prompt_fingerprint(
        DEFAULT_TEMPLATE,
        [_example()],
        "規則 B",
        LEGACY_LABEL_SCHEMA,
    )
    assert before != after


def test_prompt_fingerprint_changes_when_injected_few_shot_changes():
    before = prompt_fingerprint(
        DEFAULT_TEMPLATE,
        [_example("範例 A")],
        "固定 Codebook",
        LEGACY_LABEL_SCHEMA,
    )
    after = prompt_fingerprint(
        DEFAULT_TEMPLATE,
        [_example("範例 B")],
        "固定 Codebook",
        LEGACY_LABEL_SCHEMA,
    )
    assert before != after
