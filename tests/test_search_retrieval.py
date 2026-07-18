import json
from pathlib import Path

from src.search.config import SearchConfig
from src.search.indexes.bm25 import build_bm25_index, load_metadata_records
from src.search.models import SearchHit
from src.search.retrievers.bm25 import BM25Retriever
from src.search.retrievers.hybrid import (
    _global_dense_ranking,
    is_low_quality_hit,
    reciprocal_rank_fusion,
)
from src.search.tokenization import tokenize_zh_mixed


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
        encoding="utf-8",
    )


def test_tokenizer_preserves_chinese_terms_and_dimensions() -> None:
    tokens = tokenize_zh_mixed("安全出口净宽度不应小于1200mm")

    assert "安全" in tokens
    assert "出口" in tokens
    assert "1200" in tokens
    assert "mm" in tokens


def test_bm25_builds_from_table_and_image_summaries(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "text_metadata.jsonl", [])
    _write_jsonl(
        tmp_path / "table_metadata.jsonl",
        [{"id": "table_1", "modality": "table", "page": 46, "summary": "安全出口和疏散门净宽度", "content": "最小净宽度要求"}],
    )
    _write_jsonl(
        tmp_path / "image_metadata.jsonl",
        [
            {"id": "image_1", "modality": "image", "page": 9, "summary": "BIM审查流程图", "asset_path": "images/flow.png"},
            {"id": "image_2", "modality": "image", "page": 10, "summary": "建筑立面示意图"},
            {"id": "image_3", "modality": "image", "page": 11, "summary": "结构节点示意图"},
        ],
    )

    manifest = build_bm25_index(tmp_path)
    hits = BM25Retriever(tmp_path).search("安全出口净宽度", modality="table")

    assert manifest["modality_counts"] == {"text": 0, "table": 1, "image": 3}
    assert hits[0].id == "table_1"
    assert hits[0].page == 46


def test_explicit_reference_locator_bypasses_semantic_ranking(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "text_metadata.jsonl",
        [{"id": "text_1", "content": "表8.2.3规定的计算方法。"}],
    )
    _write_jsonl(
        tmp_path / "table_metadata.jsonl",
        [{
            "id": "table_12",
            "source_title": "表8.2.3 安全出口疏散门净宽度",
            "asset_path": "assets/table_8.2.3.png",
            "content": "完整表格",
        }],
    )
    _write_jsonl(tmp_path / "image_metadata.jsonl", [])
    build_bm25_index(tmp_path)

    hits = BM25Retriever(tmp_path).search_exact_references(
        "请读取表8.2.3的完整表格"
    )

    assert [hit.id for hit in hits] == ["table_12", "text_1"]


def test_article_locator_is_resolved_without_table_specific_logic(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "text_metadata.jsonl",
        [
            {"id": "text_1", "content": "8.2.4 房间疏散门开启后的净宽要求。"},
            {"id": "text_2", "content": "其他无关条文。"},
        ],
    )
    _write_jsonl(tmp_path / "table_metadata.jsonl", [])
    _write_jsonl(tmp_path / "image_metadata.jsonl", [])
    build_bm25_index(tmp_path)

    hits = BM25Retriever(tmp_path).search_exact_references("请读取第8.2.4条")

    assert [hit.id for hit in hits] == ["text_1"]


def test_rrf_merges_same_evidence_from_both_retrievers() -> None:
    common = {"id": "table_1", "document_id": "standard", "modality": "table", "rank": 1, "content": "净宽度"}
    bm25 = SearchHit.model_validate({**common, "score": 3.2, "bm25_score": 3.2, "retrievers": ["bm25"]})
    dense = SearchHit.model_validate({**common, "score": 0.8, "dense_score": 0.8, "retrievers": ["dense"]})

    hits = reciprocal_rank_fusion([bm25], [dense], config=SearchConfig(), top_k=3)

    assert len(hits) == 1
    assert hits[0].retrievers == ["bm25", "dense"]
    assert hits[0].bm25_score == 3.2
    assert hits[0].dense_score == 0.8


def test_dense_hits_are_ranked_globally_across_modalities() -> None:
    hits = [
        SearchHit(id="text_1", document_id="standard", modality="text", rank=1, score=0.4, content="text"),
        SearchHit(id="table_1", document_id="standard", modality="table", rank=1, score=0.9, content="table"),
        SearchHit(id="image_1", document_id="standard", modality="image", rank=1, score=0.6, summary="image"),
    ]

    ranked = _global_dense_ranking(hits, top_k=2)

    assert [hit.id for hit in ranked] == ["table_1", "image_1"]
    assert [hit.rank for hit in ranked] == [1, 2]


def test_unusable_image_is_filtered_but_table_is_not() -> None:
    image = SearchHit(
        id="image_000002",
        document_id="standard",
        modality="image",
        rank=1,
        score=0.8,
        title="未识别图像",
        content="该图像模糊不清，无法提取任何有效信息。",
    )
    table = SearchHit(
        id="table_1",
        document_id="standard",
        modality="table",
        rank=1,
        score=0.8,
        content="表格OCR即使提到无法识别，也不按图片质量规则过滤。",
    )

    assert is_low_quality_hit(image)
    assert not is_low_quality_hit(table)


def test_english_unreadable_placeholder_is_filtered() -> None:
    image = SearchHit(
        id="image_3",
        document_id="standard",
        modality="image",
        rank=1,
        score=0.7,
        title="Unreadable Chart Placeholder",
        summary="The chart content is entirely indiscernible.",
    )

    assert is_low_quality_hit(image)


def test_real_asset_metadata_contains_table_summaries() -> None:
    index_root = Path(__file__).resolve().parents[1] / "references" / "assets" / "indexes"
    document_dirs = [path for path in index_root.iterdir() if path.is_dir()]

    assert document_dirs
    assert any(
        record["modality"] == "table" and (record.get("summary") or record.get("content"))
        for document_dir in document_dirs
        for record in load_metadata_records(document_dir)
    )
