import pytest

from src.search.iterative.history import IterativeHistoryError, record_retrieval
from src.search.iterative.models import IterativeRetrievalState
from src.search.models import SearchHit
from tests.test_iterative_models import NANJING_DOCUMENT, _ifc_context


def _empty_state(*, max_hops: int = 3) -> IterativeRetrievalState:
    return IterativeRetrievalState(
        task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
        original_query="检查上传IFC模型中的疏散门净宽度是否符合规范。",
        ifc_context=_ifc_context(),
        available_documents=[NANJING_DOCUMENT],
        max_hops=max_hops,
    )


def _hit(
    content_id: str = "table_000020",
    *,
    score: float = 0.0322,
    document_id: str = NANJING_DOCUMENT,
) -> SearchHit:
    return SearchHit(
        id=content_id,
        document_id=document_id,
        modality="table",
        rank=1,
        score=score,
        page=24,
        title="表格20",
        content="疏散门净宽度应依据相关建筑设计规范确定。",
        asset_path="tables/table_000020.png",
        retrievers=["bm25", "dense"],
    )


def test_record_retrieval_adds_query_and_evidence_immutably() -> None:
    original = _empty_state()

    updated = record_retrieval(
        original,
        query="  小学疏散门的净宽度要求是什么？  ",
        dense_query="What clear-width requirements apply to school evacuation doors?",
        target_document=NANJING_DOCUMENT,
        hits=[_hit(), _hit("text_000021")],
    )

    assert original.hop == 0
    assert original.query_history == []
    assert updated.hop == 1
    assert updated.query_history[0].query == "小学疏散门的净宽度要求是什么？"
    assert updated.query_history[0].result_count == 2
    assert len(updated.evidence_history) == 2
    assert updated.evidence_history[0].content_id == "table_000020"
    assert updated.evidence_history[0].iter == 1


def test_record_retrieval_preserves_cross_document_references() -> None:
    hit = SearchHit.model_validate(
        {
            **_hit("table_000031").model_dump(mode="python"),
            "cross_document_references": [
                {
                    "target_document": "中小学校设计规范GB 50099—2011(page1-50)",
                    "target_locator": "表8.2.3",
                }
            ],
        }
    )

    updated = record_retrieval(
        _empty_state(),
        query="表8.2.3的具体数值是什么？",
        dense_query="What values are specified in Table 8.2.3?",
        target_document=NANJING_DOCUMENT,
        hits=[hit],
    )

    reference = updated.evidence_history[0].cross_document_references[0]
    assert reference.target_locator == "表8.2.3"
    assert reference.target_document.endswith("(page1-50)")
    assert updated.pending_cross_document_references == [reference]


def test_repeated_evidence_is_recorded_per_query_but_not_duplicated_globally() -> None:
    first = record_retrieval(
        _empty_state(),
        query="第一轮自然语言检索问题是什么？",
        dense_query="What is the first-hop natural-language retrieval question?",
        target_document=NANJING_DOCUMENT,
        hits=[_hit(score=0.02)],
    )

    second = record_retrieval(
        first,
        query="第二轮针对缺失阈值的自然语言检索问题是什么？",
        dense_query="What second-hop question retrieves the missing threshold?",
        target_document=NANJING_DOCUMENT,
        hits=[_hit(score=0.09), _hit("text_000021")],
    )

    repeated_id = f"{NANJING_DOCUMENT}:table_000020"
    assert second.query_history[1].result_count == 2
    assert repeated_id in second.query_history[1].evidence_ids
    assert len(second.evidence_history) == 2
    assert second.evidence_history[0].score == 0.02
    assert second.evidence_history[0].iter == 1


def test_duplicate_hits_count_as_results_but_use_one_evidence_id() -> None:
    updated = record_retrieval(
        _empty_state(),
        query="本轮检索问题是什么？",
        dense_query="What is the retrieval question for this hop?",
        target_document=NANJING_DOCUMENT,
        hits=[_hit(), _hit()],
    )

    assert updated.query_history[0].result_count == 2
    assert len(updated.query_history[0].evidence_ids) == 1
    assert len(updated.evidence_history) == 1


def test_record_retrieval_hard_limits_each_hop_to_final_top_three() -> None:
    updated = record_retrieval(
        _empty_state(),
        query="本轮最多应记录多少条最终证据？",
        dense_query="How many final evidence items may one hop retain?",
        target_document=NANJING_DOCUMENT,
        hits=[_hit(f"text_{index:06d}") for index in range(1, 6)],
    )

    assert updated.query_history[0].result_count == 3
    assert updated.query_history[0].evidence_ids == [
        f"{NANJING_DOCUMENT}:text_{index:06d}" for index in range(1, 4)
    ]
    assert [item.content_id for item in updated.evidence_history] == [
        f"text_{index:06d}" for index in range(1, 4)
    ]


def test_empty_retrieval_is_still_recorded() -> None:
    updated = record_retrieval(
        _empty_state(),
        query="没有召回结果的问题也必须留下历史吗？",
        dense_query="Should a query with no results remain in history?",
        target_document=NANJING_DOCUMENT,
        hits=[],
    )

    assert updated.hop == 1
    assert updated.query_history[0].result_count == 0
    assert updated.query_history[0].evidence_ids == []


def test_rejects_hit_from_another_document() -> None:
    with pytest.raises(IterativeHistoryError, match="other than target_document"):
        record_retrieval(
            _empty_state(),
            query="检索问题",
            dense_query="Retrieval question",
            target_document=NANJING_DOCUMENT,
            hits=[_hit(document_id="另一份规范")],
        )


def test_rejects_unavailable_document_and_empty_query() -> None:
    with pytest.raises(IterativeHistoryError, match="available_documents"):
        record_retrieval(
            _empty_state(),
            query="检索问题",
            dense_query="Retrieval question",
            target_document="另一份规范",
            hits=[],
        )
    with pytest.raises(IterativeHistoryError, match="query cannot be empty"):
        record_retrieval(
            _empty_state(),
            query=" ",
            dense_query="Retrieval question",
            target_document=NANJING_DOCUMENT,
            hits=[],
        )


def test_rejects_recording_past_max_hops() -> None:
    first = record_retrieval(
        _empty_state(max_hops=1),
        query="唯一允许的检索问题",
        dense_query="The only permitted retrieval question",
        target_document=NANJING_DOCUMENT,
        hits=[],
    )

    with pytest.raises(IterativeHistoryError, match="max_hops"):
        record_retrieval(
            first,
            query="不应执行的额外查询",
            dense_query="An additional query that must not run",
            target_document=NANJING_DOCUMENT,
            hits=[],
        )
