"""Configuration shared by regulation query and retrieval components."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_candidate_k: int = Field(default=50, gt=0)
    default_top_k: int = Field(default=3, gt=0)
    rrf_k: int = Field(default=60, gt=0)
    dense_weight: float = Field(default=1.0, ge=0)
    bm25_weight: float = Field(default=1.0, ge=0)
    max_hops: int = Field(default=3, gt=0)
    dense_score_threshold: float | None = None

    @model_validator(mode="after")
    def validate_related_limits(self) -> "SearchConfig":
        if self.default_candidate_k < self.default_top_k:
            raise ValueError(
                "default_candidate_k must be greater than or equal to "
                "default_top_k"
            )
        if self.dense_weight == 0 and self.bm25_weight == 0:
            raise ValueError("dense_weight and bm25_weight cannot both be zero")
        return self
