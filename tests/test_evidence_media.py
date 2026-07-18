from pathlib import Path

import pytest

from src.search.evidence_media import (
    EvidenceMediaResolutionError,
    EvidenceMediaResolver,
)
from src.search.iterative.models import EvidenceHistoryItem


def _evidence(
    *,
    modality: str = "table",
    asset_path: str | None = "assets/document/table.png",
) -> EvidenceHistoryItem:
    return EvidenceHistoryItem(
        evidence_id="document:table_1",
        document_id="document",
        content_id="table_1",
        modality=modality,
        content="表格证据",
        asset_path=asset_path,
        score=1.0,
        retrieved_at_hop=1,
    )


def test_resolves_relative_asset_path_against_references_root(tmp_path: Path) -> None:
    references_root = tmp_path / "references"
    asset = references_root / "assets" / "document" / "table.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"fake-png")

    result = EvidenceMediaResolver(references_root).resolve(_evidence())

    assert result.path == asset.resolve()
    assert result.mime_type == "image/png"
    assert result.size_bytes == 8


def test_rejects_text_evidence() -> None:
    with pytest.raises(EvidenceMediaResolutionError, match="is text"):
        EvidenceMediaResolver().resolve(_evidence(modality="text"))


def test_rejects_missing_original_asset(tmp_path: Path) -> None:
    with pytest.raises(EvidenceMediaResolutionError, match="does not exist"):
        EvidenceMediaResolver(tmp_path / "references").resolve(_evidence())


def test_rejects_path_outside_references_root(tmp_path: Path) -> None:
    references_root = tmp_path / "references"
    outside = tmp_path / "outside.png"
    references_root.mkdir()
    outside.write_bytes(b"fake-png")

    with pytest.raises(EvidenceMediaResolutionError, match="escapes references root"):
        EvidenceMediaResolver(references_root).resolve(
            _evidence(asset_path="../outside.png")
        )


def test_resolves_real_table_8_2_3_asset() -> None:
    asset_path = (
        "assets/中小学校设计规范GB 50099—2011(page1-50)_tables/"
        "table_0012_page_0046_表8.2.3_安全出口_疏散走道_疏散楼梯和房间.png"
    )

    result = EvidenceMediaResolver().resolve(_evidence(asset_path=asset_path))

    assert result.path.name.startswith("table_0012_page_0046_表8.2.3")
    assert result.mime_type == "image/png"
    assert result.size_bytes > 0
