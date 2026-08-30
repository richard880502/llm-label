"""Compatibility facade for the project-scoped generic classifier runtime.

The main classification path no longer depends on fixed label constants. These
legacy exports remain temporarily because the current review router still imports
them; they can be removed when review persistence moves to corrected_result.
"""

from ..annotation.legacy import LEGACY_LABELS, LEGACY_SUBTYPES
from .classifier_runtime import (
    PARSE_FAIL_MARKER,
    compatibility_projection,
    mark_task_cancelled,
    parse_response,
)
from .durable_runtime import (
    resume_stale_api_tasks,
    run_classification_task,
    start_api_task_watchdog,
)


# Deprecated compatibility exports for backend/routers/rows.py.
ALLOWED_LABELS = set(LEGACY_LABELS)
ALLOWED_SUBTYPES = set(LEGACY_SUBTYPES)


def has_valid_emotional_hierarchy(labels: list[str], subtypes: list[str]) -> bool:
    """Legacy review compatibility until rows.py uses project schema validation."""
    return not subtypes or "Emotional Resonance" in labels


__all__ = [
    "ALLOWED_LABELS",
    "ALLOWED_SUBTYPES",
    "PARSE_FAIL_MARKER",
    "compatibility_projection",
    "has_valid_emotional_hierarchy",
    "mark_task_cancelled",
    "parse_response",
    "resume_stale_api_tasks",
    "run_classification_task",
    "start_api_task_watchdog",
]
