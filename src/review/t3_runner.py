"""Batch T3 retrieval orchestration with building-scoped evidence reuse."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.ai.evacuation_door_classifier import StructuredLLMClient
from src.review.context_builder import build_ifc_context
from src.review.models import (
    ClassificationSource,
    DoorReviewInput,
    ReviewProgressEvent,
    ReviewStage,
)
from src.search.config import SearchConfig
from src.search.document_catalog import DocumentCatalog
from src.search.iterative.building_evidence_cache import (
    BuildingEvidenceCache,
    BuildingEvidenceResolution,
    retrieve_or_reuse_building_evidence,
)
from src.search.iterative.models import IFCContext
from src.search.iterative.service import RetrieverFactory
from src.search.models import DEFAULT_RETRIEVAL_TASK, RetrievalTask
from src.search.retrievers.vector import EmbedQuery


DEFAULT_REVIEW_QUERY = "检查上传IFC模型中疏散门净宽度是否符合适用规范。"
T3DoorStatus = Literal[
    "cache_hit",
    "retrieved_and_cached",
    "retrieved_not_cached",
    "error",
]
ContextBuilder = Callable[[DoorReviewInput], IFCContext]
ProgressCallback = Callable[[ReviewProgressEvent], None]
DEFAULT_T3_MAX_WORKERS = 4


class EvidenceResolver(Protocol):
    def __call__(
        self,
        *,
        project_id: str,
        task: RetrievalTask,
        original_query: str,
        ifc_context: IFCContext,
        cache: BuildingEvidenceCache,
    ) -> BuildingEvidenceResolution: ...


class T3DoorRun(BaseModel):
    """One door's T3 context and retrieval/reuse outcome."""

    model_config = ConfigDict(extra="forbid")

    review_input: DoorReviewInput
    ifc_context: IFCContext | None = None
    status: T3DoorStatus
    resolution: BuildingEvidenceResolution | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "T3DoorRun":
        expected_guid = self.review_input.candidate.ifc_guid
        expected_door_id = self.review_input.candidate.door_id
        if self.status == "error":
            if not self.error or not self.error.strip():
                raise ValueError("an error T3 result requires an error message")
            if self.resolution is not None:
                raise ValueError("an error T3 result cannot contain a resolution")
            return self
        if self.ifc_context is None or self.resolution is None:
            raise ValueError("a successful T3 result requires context and resolution")
        if self.error is not None:
            raise ValueError("a successful T3 result cannot contain an error")
        if self.status != self.resolution.status:
            raise ValueError("T3 status must match resolution.status")
        if self.ifc_context.subject.ifc_guid != expected_guid:
            raise ValueError("T3 context ifc_guid does not match review input")
        if self.ifc_context.subject.door_id != expected_door_id:
            raise ValueError("T3 context door_id does not match review input")
        if self.resolution.requested_ifc_guid != expected_guid:
            raise ValueError("T3 resolution ifc_guid does not match review input")
        if self.resolution.requested_door_id != expected_door_id:
            raise ValueError("T3 resolution door_id does not match review input")
        return self


class T3BatchResult(BaseModel):
    """Self-contained T3 output in the original UI door order."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    task: RetrievalTask
    original_query: str = Field(min_length=1)
    execution_order_door_ids: list[str] = Field(default_factory=list)
    door_runs: list[T3DoorRun] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_runs(self) -> "T3BatchResult":
        result_ids = [item.review_input.candidate.door_id for item in self.door_runs]
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("T3 batch door IDs must be unique")
        if len(self.execution_order_door_ids) != len(result_ids):
            raise ValueError("T3 execution order must contain every result once")
        if set(self.execution_order_door_ids) != set(result_ids):
            raise ValueError("T3 execution order and result door IDs must match")
        return self

    @property
    def successful_count(self) -> int:
        return sum(item.status != "error" for item in self.door_runs)

    @property
    def cache_hit_count(self) -> int:
        return sum(item.status == "cache_hit" for item in self.door_runs)

    @property
    def error_count(self) -> int:
        return sum(item.status == "error" for item in self.door_runs)


def run_t3_batch(
    *,
    project_id: str,
    review_inputs: list[DoorReviewInput],
    cache: BuildingEvidenceCache,
    task: RetrievalTask = DEFAULT_RETRIEVAL_TASK,
    original_query: str = DEFAULT_REVIEW_QUERY,
    progress: ProgressCallback | None = None,
    context_builder: ContextBuilder = build_ifc_context,
    evidence_resolver: EvidenceResolver | None = None,
    catalog: DocumentCatalog | None = None,
    client: StructuredLLMClient | None = None,
    config: SearchConfig | None = None,
    embed_query: EmbedQuery | None = None,
    enable_dense: bool = True,
    retriever_factory: RetrieverFactory | None = None,
    max_workers: int = DEFAULT_T3_MAX_WORKERS,
) -> T3BatchResult:
    """Run/reuse T3 per door while isolating failures and preserving UI order."""

    normalized_project = str(project_id or "").strip()
    normalized_task = str(task or "").strip()
    normalized_query = str(original_query or "").strip()
    if not normalized_project:
        raise ValueError("project_id cannot be empty")
    if not normalized_task:
        raise ValueError("task cannot be empty")
    if not normalized_query:
        raise ValueError("original_query cannot be empty")
    _validate_max_workers(max_workers)
    door_ids = [item.candidate.door_id for item in review_inputs]
    if len(door_ids) != len(set(door_ids)):
        raise ValueError("review input door IDs must be unique")

    indexed_inputs = list(enumerate(review_inputs))
    execution_order = sorted(
        indexed_inputs,
        key=lambda item: (
            0
            if item[1].classification_source is ClassificationSource.LLM
            else 1,
            item[0],
        ),
    )
    total = len(execution_order)
    _emit_progress(
        progress,
        current=0,
        total=total,
        message="正在准备 T3 规范证据检索",
    )
    runs_by_index: dict[int, T3DoorRun] = {}
    messages_by_index: dict[int, str] = {}
    execution_order_door_ids = [
        review_input.candidate.door_id
        for _, review_input in execution_order
    ]
    groups: dict[
        tuple[str, str, str],
        list[tuple[int, DoorReviewInput, IFCContext]],
    ] = {}
    for original_index, review_input in execution_order:
        door_id = review_input.candidate.door_id
        try:
            ifc_context = context_builder(review_input)
            group_key = (
                normalized_project.casefold(),
                ifc_context.building_context.building_type.strip().casefold(),
                normalized_task.casefold(),
            )
            groups.setdefault(group_key, []).append(
                (original_index, review_input, ifc_context)
            )
        except Exception as exc:
            runs_by_index[original_index] = T3DoorRun(
                review_input=review_input,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
            messages_by_index[original_index] = (
                f"{door_id} 的 T3 上下文构造失败"
            )

    completed = 0
    for original_index in sorted(runs_by_index):
        completed += 1
        _emit_progress(
            progress,
            current=completed,
            total=total,
            door_id=review_inputs[original_index].candidate.door_id,
            message=messages_by_index[original_index],
        )

    if groups:
        futures: dict[
            Future[list[tuple[int, T3DoorRun, str]]],
            tuple[str, str, str],
        ] = {}
        with ThreadPoolExecutor(
            max_workers=min(max_workers, len(groups)),
            thread_name_prefix="t3-retrieval",
        ) as executor:
            for group_key, group in groups.items():
                future = executor.submit(
                    _run_t3_group,
                    group=group,
                    project_id=normalized_project,
                    task=normalized_task,
                    original_query=normalized_query,
                    cache=cache,
                    evidence_resolver=evidence_resolver,
                    catalog=catalog,
                    client=client,
                    config=config,
                    embed_query=embed_query,
                    enable_dense=enable_dense,
                    retriever_factory=retriever_factory,
                )
                futures[future] = group_key
            for future in as_completed(futures):
                for original_index, run, message in future.result():
                    runs_by_index[original_index] = run
                    completed += 1
                    _emit_progress(
                        progress,
                        current=completed,
                        total=total,
                        door_id=run.review_input.candidate.door_id,
                        message=message,
                    )

    return T3BatchResult(
        project_id=normalized_project,
        task=normalized_task,
        original_query=normalized_query,
        execution_order_door_ids=execution_order_door_ids,
        door_runs=[runs_by_index[index] for index in range(len(review_inputs))],
    )


def _run_t3_group(
    *,
    group: list[tuple[int, DoorReviewInput, IFCContext]],
    project_id: str,
    task: RetrievalTask,
    original_query: str,
    cache: BuildingEvidenceCache,
    evidence_resolver: EvidenceResolver | None,
    catalog: DocumentCatalog | None,
    client: StructuredLLMClient | None,
    config: SearchConfig | None,
    embed_query: EmbedQuery | None,
    enable_dense: bool,
    retriever_factory: RetrieverFactory | None,
) -> list[tuple[int, T3DoorRun, str]]:
    """Process one building reuse group serially to prevent duplicate retrieval."""

    outcomes: list[tuple[int, T3DoorRun, str]] = []
    for original_index, review_input, ifc_context in group:
        door_id = review_input.candidate.door_id
        try:
            resolution = _resolve_evidence(
                project_id=project_id,
                task=task,
                original_query=original_query,
                ifc_context=ifc_context,
                cache=cache,
                evidence_resolver=evidence_resolver,
                catalog=catalog,
                client=client,
                config=config,
                embed_query=embed_query,
                enable_dense=enable_dense,
                retriever_factory=retriever_factory,
            )
            run = T3DoorRun(
                review_input=review_input,
                ifc_context=ifc_context,
                status=resolution.status,
                resolution=resolution,
            )
            message = (
                f"{door_id} 已复用规范证据"
                if resolution.status == "cache_hit"
                else f"{door_id} 已完成规范证据检索"
            )
        except Exception as exc:  # Keep one door failure from aborting the group.
            run = T3DoorRun(
                review_input=review_input,
                ifc_context=ifc_context,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
            message = f"{door_id} 的 T3 处理失败"
        outcomes.append((original_index, run, message))
    return outcomes


def _resolve_evidence(
    *,
    project_id: str,
    task: RetrievalTask,
    original_query: str,
    ifc_context: IFCContext,
    cache: BuildingEvidenceCache,
    evidence_resolver: EvidenceResolver | None,
    catalog: DocumentCatalog | None,
    client: StructuredLLMClient | None,
    config: SearchConfig | None,
    embed_query: EmbedQuery | None,
    enable_dense: bool,
    retriever_factory: RetrieverFactory | None,
) -> BuildingEvidenceResolution:
    if evidence_resolver is not None:
        return evidence_resolver(
            project_id=project_id,
            task=task,
            original_query=original_query,
            ifc_context=ifc_context,
            cache=cache,
        )
    return retrieve_or_reuse_building_evidence(
        project_id=project_id,
        task=task,
        original_query=original_query,
        ifc_context=ifc_context,
        cache=cache,
        catalog=catalog,
        client=client,
        config=config,
        embed_query=embed_query,
        enable_dense=enable_dense,
        retriever_factory=retriever_factory,
    )


def _emit_progress(
    callback: ProgressCallback | None,
    *,
    current: int,
    total: int,
    message: str,
    door_id: str | None = None,
) -> None:
    if callback is None:
        return
    callback(
        ReviewProgressEvent(
            stage=ReviewStage.T3,
            current=current,
            total=total,
            door_id=door_id,
            message=message,
        )
    )


def _validate_max_workers(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("max_workers must be a positive integer")
