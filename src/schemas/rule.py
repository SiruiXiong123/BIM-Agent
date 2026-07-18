"""Minimal contracts for T4 generated calculations."""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


NonNegativeFloat = Annotated[float, Field(ge=0)]
RuleTargetField = Literal[
    "actual_clear_width_mm",
    "required_clear_width_mm",
]


class Rule(BaseModel):
    """Legacy generic rule contract retained for non-T4 callers."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    rule_id: str = Field(min_length=1)
    standard: str = Field(min_length=1)
    article: str = Field(min_length=1)
    rule_name: str = Field(min_length=1)
    applicable_building_type: list[str] = Field(default_factory=list)
    target_entity: str = Field(min_length=1)
    conditions: dict[str, Any] = Field(default_factory=dict)
    requirements: dict[str, Any] = Field(default_factory=dict)


class GeneratedFieldScript(BaseModel):
    """One VLM-generated calculation for the current door and field."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    target_field: RuleTargetField
    language: Literal["python"] = "python"
    entrypoint: Literal["calculate_value"] = "calculate_value"
    source: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class GeneratedFieldCalculation(BaseModel):
    """One VLM choice between a direct evidence value and Python code."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    target_field: RuleTargetField
    resolution: Literal["direct_value", "python_script"]
    value_mm: NonNegativeFloat | None = None
    language: Literal["python"] | None = None
    entrypoint: Literal["calculate_value"] | None = None
    source: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("value_mm", mode="before")
    @classmethod
    def validate_direct_numeric_value(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("direct field value must be numeric")
        return value

    @field_validator("value_mm")
    @classmethod
    def validate_direct_finite_value(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("direct field value must be finite")
        return value

    @model_validator(mode="after")
    def validate_resolution_fields(self) -> "GeneratedFieldCalculation":
        if self.resolution == "direct_value":
            if self.value_mm is None:
                raise ValueError("direct_value requires value_mm")
            if any(
                item is not None
                for item in (self.language, self.entrypoint, self.source)
            ):
                raise ValueError(
                    "direct_value requires null language, entrypoint and source"
                )
            return self
        if self.value_mm is not None:
            raise ValueError("python_script requires null value_mm")
        if (
            self.language != "python"
            or self.entrypoint != "calculate_value"
            or not self.source
            or not self.source.strip()
        ):
            raise ValueError(
                "python_script requires language, entrypoint and source"
            )
        return self


class ValidatedFieldScript(BaseModel):
    """A generated script that passed evidence and AST validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_field: RuleTargetField
    source: str = Field(min_length=1)
    source_hash: str = Field(min_length=64, max_length=64)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    entrypoint: Literal["calculate_value"] = "calculate_value"


class FieldCalculationOutput(BaseModel):
    """Strict output of one isolated generated script."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    target_field: RuleTargetField
    value_mm: NonNegativeFloat

    @field_validator("value_mm", mode="before")
    @classmethod
    def validate_numeric_value(cls, value: Any) -> Any:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("calculated field value must be numeric")
        return value

    @field_validator("value_mm")
    @classmethod
    def validate_finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("calculated field value must be finite")
        return value


class RuleCalculationOutput(BaseModel):
    """The two numeric values consumed by the deterministic comparator."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    actual_clear_width_mm: NonNegativeFloat
    required_clear_width_mm: NonNegativeFloat
