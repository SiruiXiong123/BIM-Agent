"""Deterministic compliance-check result schema."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


NonNegativeFloat = Annotated[float, Field(ge=0)]


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    element_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    actual_value: NonNegativeFloat | None = Field(
        default=None, description="Measured value in millimetres."
    )
    required_value: NonNegativeFloat | None = Field(
        default=None, description="Required value in millimetres."
    )
    result: CheckStatus
    message: str = Field(min_length=1)
