import pytest

from src.search.indexes.vector import _detect_id_offset


def test_detects_identity_faiss_ids() -> None:
    assert _detect_id_offset({0, 1, 2}, {0, 1, 2}) == 0


def test_detects_one_based_faiss_ids() -> None:
    assert _detect_id_offset({1, 2, 3}, {0, 1, 2}) == 1


def test_rejects_unknown_faiss_id_layout() -> None:
    with pytest.raises(ValueError, match="do not align"):
        _detect_id_offset({2, 4, 6}, {0, 1, 2})
