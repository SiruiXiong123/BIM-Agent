import json
from pathlib import Path

import pytest

from src.search.document_catalog import (
    DocumentCatalog,
    DocumentCatalogError,
    DocumentNotFoundError,
    normalize_document_name,
)


def _make_indexed_document(root: Path, document_id: str) -> Path:
    document_dir = root / document_id
    document_dir.mkdir(parents=True)
    (document_dir / "manifest.json").write_text(
        json.dumps({"document_id": document_id}, ensure_ascii=False),
        encoding="utf-8",
    )
    (document_dir / "text_metadata.jsonl").write_text("", encoding="utf-8")
    return document_dir


def test_catalog_discovers_only_complete_index_directories(tmp_path: Path) -> None:
    expected = _make_indexed_document(
        tmp_path, "中小学校设计规范GB 50099—2011(page1-50)"
    )
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    (incomplete / "manifest.json").write_text("{}", encoding="utf-8")

    catalog = DocumentCatalog.discover(tmp_path)

    assert [item.document_id for item in catalog.documents] == [expected.name]
    assert catalog.documents[0].index_dir == expected.resolve()


def test_catalog_resolves_exact_id_title_alias_and_pdf_suffix(tmp_path: Path) -> None:
    document_id = "中小学校设计规范GB 50099—2011(page1-50)"
    _make_indexed_document(tmp_path, document_id)
    catalog = DocumentCatalog.discover(tmp_path)

    assert catalog.resolve(document_id).document_id == document_id
    assert catalog.resolve("中小学校设计规范 GB 50099-2011").document_id == document_id
    assert catalog.resolve("中小学校设计规范 GB 50099—2011.pdf").document_id == document_id


def test_catalog_rejects_unknown_document_with_available_ids(tmp_path: Path) -> None:
    document_id = "南京地方标准建筑工程施工图信息模型智能审查规范"
    _make_indexed_document(tmp_path, document_id)
    catalog = DocumentCatalog.discover(tmp_path)

    with pytest.raises(DocumentNotFoundError, match=document_id):
        catalog.resolve("不存在的规范")


def test_catalog_rejects_empty_index_root(tmp_path: Path) -> None:
    with pytest.raises(DocumentCatalogError, match="No indexed documents"):
        DocumentCatalog.discover(tmp_path)


def test_normalization_is_unicode_dash_space_and_extension_insensitive() -> None:
    assert normalize_document_name(" GB 50099—2011.pdf ") == normalize_document_name(
        "GB50099-2011"
    )


def test_real_catalog_exposes_both_available_regulations() -> None:
    catalog = DocumentCatalog.discover()
    ids = set(catalog.available_documents())

    assert "南京地方标准建筑工程施工图信息模型智能审查规范" in ids
    assert "中小学校设计规范GB 50099—2011(page1-50)" in ids
