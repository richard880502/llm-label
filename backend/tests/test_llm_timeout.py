import pytest
from pydantic import ValidationError

from backend.llm.client import request_cycle_budget_seconds
from backend.routers.projects import LLMSlotUpdate


def test_slot_timeout_defaults_and_limits():
    assert LLMSlotUpdate().timeout_seconds == 180
    assert LLMSlotUpdate(timeout_seconds=30).timeout_seconds == 30
    assert LLMSlotUpdate(timeout_seconds=1800).timeout_seconds == 1800

    with pytest.raises(ValidationError):
        LLMSlotUpdate(timeout_seconds=29)
    with pytest.raises(ValidationError):
        LLMSlotUpdate(timeout_seconds=1801)


def test_request_cycle_budget_grows_with_model_timeout():
    default_budget = request_cycle_budget_seconds(180)
    slow_model_budget = request_cycle_budget_seconds(600)

    assert default_budget > 180
    assert slow_model_budget > default_budget
    assert slow_model_budget > 600
