import pytest
from pydantic import ValidationError

from src.search.config import SearchConfig


def test_search_config_accepts_default_related_limits() -> None:
    config = SearchConfig()

    assert config.default_candidate_k == 50
    assert config.default_top_k == 3
    assert config.max_hops == 3


def test_search_config_rejects_candidate_k_below_top_k() -> None:
    with pytest.raises(
        ValidationError,
        match="default_candidate_k must be greater than or equal to default_top_k",
    ):
        SearchConfig(default_candidate_k=2, default_top_k=3)
