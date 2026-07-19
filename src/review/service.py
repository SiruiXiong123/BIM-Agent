"""Framework-neutral preparation service for the T6 review workflow."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from typing import Protocol

from src.ai.evacuation_door_classifier import (
    PROMPT_VERSION,
    StructuredLLMClient,
    build_classification_input,
    classify_evacuation_door,
)
from src.ifc_parser import IFCParseResult, parse_ifc, validate_max_doors
from src.review.models import (
    ClassificationSource,
    DoorReviewCandidate,
    DoorReviewInput,
    ReviewBatchResult,
    ReviewPreparation,
    ReviewProgressEvent,
    ReviewSelection,
    ReviewStage,
)
from src.review.t3_runner import (
    DEFAULT_REVIEW_QUERY,
    T3BatchResult,
    run_t3_batch,
)
from src.review.t4_runner import T4BatchResult, run_t4_batch
from src.review.t5_runner import run_t5_batch
from src.rules.result_cache import T4ResultCache
from src.schemas.assessment import (
    ClassifiedEvacuationDoorRecord,
    EvacuationDoorClass,
    EvacuationDoorClassification,
)
from src.schemas.bim import (
    DEFAULT_FIRE_RESISTANCE_GRADE,
    Door,
    InputValueSource,
)
from src.search.iterative.building_evidence_cache import BuildingEvidenceCache
from src.search.models import DEFAULT_RETRIEVAL_TASK, RetrievalTask


class IFCParser(Protocol):
    def __call__(
        self,
        path: str | Path,
        *,
        strict: bool = False,
        max_doors: int | None = None,
    ) -> IFCParseResult: ...


class DoorClassifier(Protocol):
    def __call__(
        self,
        door: Door,
        client: StructuredLLMClient,
    ) -> EvacuationDoorClassification: ...


class T3BatchRunner(Protocol):
    def __call__(
        self,
        *,
        project_id: str,
        review_inputs: list[DoorReviewInput],
        cache: BuildingEvidenceCache,
        task: RetrievalTask,
        original_query: str,
        progress: ProgressCallback | None,
        client: StructuredLLMClient | None,
    ) -> T3BatchResult: ...


class T4BatchRunner(Protocol):
    def __call__(
        self,
        *,
        t3_result: T3BatchResult,
        cache: T4ResultCache,
        progress: ProgressCallback | None,
        client: StructuredLLMClient | None,
    ) -> T4BatchResult: ...


class T5BatchRunner(Protocol):
    def __call__(
        self,
        *,
        t4_result: T4BatchResult,
        source_filename: str,
        progress: ProgressCallback | None,
        client: StructuredLLMClient | None,
    ) -> ReviewBatchResult: ...


ProgressCallback = Callable[[ReviewProgressEvent], None]
DEFAULT_CLASSIFICATION_MAX_WORKERS = 5


class ReviewPreparationError(RuntimeError):
    """Raised when T1/T2 cannot produce a trustworthy preparation result."""


class ReviewSelectionError(ValueError):
    """Raised when user choices do not match the prepared door candidates."""


class ReviewService:
    """Coordinate existing T1/T2 components without depending on a web UI."""

    def __init__(
        self,
        classification_client: StructuredLLMClient,
        *,
        review_client: StructuredLLMClient | None = None,
        parser: IFCParser = parse_ifc,
        classifier: DoorClassifier = classify_evacuation_door,
        t3_runner: T3BatchRunner = run_t3_batch,
        t4_runner: T4BatchRunner = run_t4_batch,
        t5_runner: T5BatchRunner = run_t5_batch,
        classification_max_workers: int = DEFAULT_CLASSIFICATION_MAX_WORKERS,
    ) -> None:
        if (
            isinstance(classification_max_workers, bool)
            or not isinstance(classification_max_workers, int)
            or classification_max_workers <= 0
        ):
            raise ValueError("classification_max_workers must be a positive integer")
        self._classification_client = classification_client
        self._review_client = review_client or classification_client
        self._parser = parser
        self._classifier = classifier
        self._t3_runner = t3_runner
        self._t4_runner = t4_runner
        self._t5_runner = t5_runner
        self._classification_max_workers = classification_max_workers

    def prepare_ifc(
        self,
        ifc_path: str | Path,
        *,
        strict: bool = False,
        max_doors: int | None = None,
        progress: ProgressCallback | None = None,
    ) -> ReviewPreparation:
        """Parse and classify every successfully parsed door in one IFC file."""

        validate_max_doors(max_doors)
        source = Path(ifc_path)
        _emit_progress(
            progress,
            stage=ReviewStage.PARSE,
            current=0,
            total=0,
            message="正在解析 IFC 模型",
        )
        parse_start = perf_counter()
        parse_result = self._parser(
            source,
            strict=strict,
            max_doors=max_doors,
        )
        print(
            f"[PERF] IFC parsing finished: {perf_counter() - parse_start:.2f}s",
            flush=True,
        )
        total = len(parse_result.doors)
        _emit_progress(
            progress,
            stage=ReviewStage.PARSE,
            current=total,
            total=total,
            message=f"已解析 {total} 扇门",
        )
        _emit_progress(
            progress,
            stage=ReviewStage.CLASSIFY,
            current=0,
            total=total,
            message="正在判断疏散门与防火门属性",
        )

        classification_start = perf_counter()
        classified = self._classify_doors(
            parse_result.doors,
            progress=progress,
        )
        print(
            f"[PERF] Door classification finished: {perf_counter() - classification_start:.2f}s",
            flush=True,
        )
        candidates = [
            _build_candidate(index, door, assessment)
            for index, (door, assessment) in enumerate(classified, start=1)
        ]

        source_sha256 = _sha256_file(source)
        preparation = ReviewPreparation(
            project_id=f"ifc-{source_sha256[:16]}",
            source_filename=source.name,
            source_sha256=source_sha256,
            ifc_schema=parse_result.ifc_schema,
            unit_scale_to_mm=parse_result.unit_scale_to_mm,
            total_ifc_door_count=parse_result.total_ifc_door_count,
            requested_max_doors=parse_result.requested_max_doors,
            door_count=len(candidates),
            candidates=candidates,
            parser_warnings=parse_result.warnings,
            parser_errors=parse_result.errors,
        )
        _emit_progress(
            progress,
            stage=ReviewStage.AWAITING_CONFIRMATION,
            current=total,
            total=total,
            message=(
                f"准备完成：{preparation.confirmed_evacuation_door_count} 扇疏散门，"
                f"{preparation.uncertain_door_count} 扇门等待确认"
            ),
        )
        return preparation

    def _classify_doors(
        self,
        doors: list[Door],
        *,
        progress: ProgressCallback | None,
    ) -> list[tuple[Door, EvacuationDoorClassification]]:
        """Classify doors concurrently while preserving IFC input order."""

        if not doors:
            return []
        results: list[tuple[Door, EvacuationDoorClassification] | None] = [
            None
        ] * len(doors)
        workers = min(self._classification_max_workers, len(doors))
        futures: dict[
            Future[EvacuationDoorClassification], tuple[int, Door]
        ] = {}
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="door-classifier",
        ) as executor:
            for index, door in enumerate(doors):
                future = executor.submit(
                    self._classifier,
                    door,
                    self._classification_client,
                )
                futures[future] = (index, door)
            for completed_count, future in enumerate(
                as_completed(futures),
                start=1,
            ):
                index, door = futures[future]
                try:
                    assessment = future.result()
                except Exception as exc:
                    if _is_empty_model_response_error(exc):
                        assessment = _build_uncertain_fallback_for_empty_response(
                            door,
                            model_name=self._classification_client.model_name,
                            error_message=str(exc),
                        )
                        print(
                            f"[WARN] {door.door_id} classification degraded to uncertain: {exc}",
                            flush=True,
                        )
                        results[index] = (door, assessment)
                        _emit_progress(
                            progress,
                            stage=ReviewStage.CLASSIFY,
                            current=completed_count,
                            total=len(doors),
                            door_id=door.door_id,
                            message=(
                                f"{door.door_id} 模型空响应，已降级为待确认"
                            ),
                        )
                        continue
                    for pending in futures:
                        pending.cancel()
                    raise ReviewPreparationError(
                        f"{door.door_id} classification failed: {exc}"
                    ) from exc
                if assessment.ifc_guid != door.ifc_guid:
                    for pending in futures:
                        pending.cancel()
                    raise ReviewPreparationError(
                        "classification ifc_guid does not match the parsed door: "
                        f"{assessment.ifc_guid!r} != {door.ifc_guid!r}"
                    )
                results[index] = (door, assessment)
                _emit_progress(
                    progress,
                    stage=ReviewStage.CLASSIFY,
                    current=completed_count,
                    total=len(doors),
                    door_id=door.door_id,
                    message=f"已完成 {door.door_id} 的门类型判断",
                )

        if any(item is None for item in results):
            raise ReviewPreparationError("not all doors received a classification")
        return [item for item in results if item is not None]

    def build_review_inputs(
        self,
        preparation: ReviewPreparation,
        selection: ReviewSelection,
    ) -> list[DoorReviewInput]:
        """Resolve user choices into the doors that may enter T3-T5."""

        candidates_by_id = {
            candidate.door_id: candidate for candidate in preparation.candidates
        }
        selected_uncertain_ids = set(selection.included_uncertain_door_ids)
        _validate_selected_uncertain_doors(
            candidates_by_id,
            selected_uncertain_ids,
        )

        included_ids = {
            candidate.door_id
            for candidate in preparation.candidates
            if candidate.raw_classification
            is EvacuationDoorClass.EVACUATION_DOOR
        }
        included_ids.update(selected_uncertain_ids)
        _validate_override_targets(
            candidates_by_id,
            included_ids,
            selection,
        )

        inputs: list[DoorReviewInput] = []
        for candidate in preparation.candidates:
            if candidate.door_id not in included_ids:
                continue
            inputs.append(_build_review_input(candidate, selection))
        return inputs

    def run_review(
        self,
        preparation: ReviewPreparation,
        selection: ReviewSelection,
        *,
        evidence_cache: BuildingEvidenceCache,
        t4_cache: T4ResultCache,
        task: RetrievalTask = DEFAULT_RETRIEVAL_TASK,
        original_query: str = DEFAULT_REVIEW_QUERY,
        progress: ProgressCallback | None = None,
    ) -> ReviewBatchResult:
        """Run T3-T5 for the effective evacuation-door selection."""

        review_inputs = self.build_review_inputs(preparation, selection)
        t3_result = self._t3_runner(
            project_id=preparation.project_id,
            review_inputs=review_inputs,
            cache=evidence_cache,
            task=task,
            original_query=original_query,
            progress=progress,
            client=self._review_client,
        )
        t4_result = self._t4_runner(
            t3_result=t3_result,
            cache=t4_cache,
            progress=progress,
            client=self._review_client,
        )
        result = self._t5_runner(
            t4_result=t4_result,
            source_filename=preparation.source_filename,
            progress=progress,
            client=self._review_client,
        )
        _emit_progress(
            progress,
            stage=ReviewStage.COMPLETE,
            current=result.total_doors,
            total=result.total_doors,
            message=(
                f"Review complete: {result.reviewed_doors} completed, "
                f"{result.skipped_doors} skipped, {result.error_doors} errors"
            ),
        )
        return result


def _build_candidate(
    index: int,
    door: Door,
    assessment: EvacuationDoorClassification,
) -> DoorReviewCandidate:
    classifier_input = build_classification_input(door)
    record = ClassifiedEvacuationDoorRecord.model_validate(
        {
            **classifier_input.model_dump(mode="json"),
            "assessment": assessment.model_dump(mode="json"),
        }
    )
    return DoorReviewCandidate(
        index=index,
        record=record,
    )


def _validate_selected_uncertain_doors(
    candidates_by_id: dict[str, DoorReviewCandidate],
    selected_ids: set[str],
) -> None:
    unknown = sorted(selected_ids - candidates_by_id.keys())
    if unknown:
        raise ReviewSelectionError(
            f"selected door IDs are not present in the preparation: {unknown}"
        )
    not_uncertain = sorted(
        door_id
        for door_id in selected_ids
        if candidates_by_id[door_id].raw_classification
        is not EvacuationDoorClass.UNCERTAIN
    )
    if not_uncertain:
        raise ReviewSelectionError(
            "included_uncertain_door_ids may only contain uncertain doors: "
            f"{not_uncertain}"
        )


def _validate_override_targets(
    candidates_by_id: dict[str, DoorReviewCandidate],
    included_ids: set[str],
    selection: ReviewSelection,
) -> None:
    override_ids = set(selection.occupant_load_overrides) | set(
        selection.fire_resistance_grade_overrides
    )
    unknown = sorted(override_ids - candidates_by_id.keys())
    if unknown:
        raise ReviewSelectionError(
            f"override door IDs are not present in the preparation: {unknown}"
        )
    excluded = sorted(override_ids - included_ids)
    if excluded:
        raise ReviewSelectionError(
            "overrides may only target doors entering the review: "
            f"{excluded}"
        )


def _build_review_input(
    candidate: DoorReviewCandidate,
    selection: ReviewSelection,
) -> DoorReviewInput:
    door_id = candidate.door_id
    if door_id in selection.occupant_load_overrides:
        occupant_load = selection.occupant_load_overrides[door_id]
        occupant_load_source = InputValueSource.USER
    else:
        occupant_load = candidate.occupant_load
        occupant_load_source = candidate.occupant_load_source

    if door_id in selection.fire_resistance_grade_overrides:
        fire_grade = selection.fire_resistance_grade_overrides[door_id]
        fire_grade_source = InputValueSource.USER
    elif candidate.fire_resistance_grade is not None:
        if candidate.fire_resistance_grade_source is None:
            raise ReviewSelectionError(
                f"{door_id} has a fire resistance grade without a source"
            )
        fire_grade = candidate.fire_resistance_grade
        fire_grade_source = candidate.fire_resistance_grade_source
    else:
        fire_grade = DEFAULT_FIRE_RESISTANCE_GRADE
        fire_grade_source = InputValueSource.DEFAULT

    classification_source = (
        ClassificationSource.LLM
        if candidate.raw_classification
        is EvacuationDoorClass.EVACUATION_DOOR
        else ClassificationSource.USER_CONFIRMATION
    )
    return DoorReviewInput(
        candidate=candidate,
        classification_source=classification_source,
        is_fire_door=candidate.raw_is_fire_door is True,
        occupant_load=occupant_load,
        occupant_load_source=occupant_load_source,
        fire_resistance_grade=fire_grade,
        fire_resistance_grade_source=fire_grade_source,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _emit_progress(
    callback: ProgressCallback | None,
    *,
    stage: ReviewStage,
    current: int,
    total: int,
    message: str,
    door_id: str | None = None,
) -> None:
    if callback is None:
        return
    callback(
        ReviewProgressEvent(
            stage=stage,
            current=current,
            total=total,
            door_id=door_id,
            message=message,
        )
    )


def _is_empty_model_response_error(exc: Exception) -> bool:
    return "empty response" in str(exc).casefold()


def _build_uncertain_fallback_for_empty_response(
    door: Door,
    *,
    model_name: str,
    error_message: str,
) -> EvacuationDoorClassification:
    return EvacuationDoorClassification(
        ifc_guid=door.ifc_guid,
        classification=EvacuationDoorClass.UNCERTAIN,
        is_fire_door=None,
        evidence=[],
        reasoning=(
            "Model returned an empty response. "
            "The door is downgraded to uncertain for manual confirmation."
        ),
        missing_information=[f"llm_empty_response: {error_message}"],
        evacuation_door_confidence=0.0,
        fire_door_confidence=None,
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
    )
