"""Single-hop VLM controller for iterative regulation retrieval."""

from __future__ import annotations

import re
import unicodedata

from pydantic import ValidationError

from prompt.iterative_retrieval import ITERATIVE_RETRIEVAL_PROMPT
from src.ai.evacuation_door_classifier import StructuredLLMClient
from src.ai.multimodal_evidence import build_multimodal_evidence_content
from src.ai.openai_compatible_client import OpenAICompatibleJSONClient
from src.search.iterative.models import (
    EvidenceHistoryItem,
    IterativeRetrievalState,
    IterativeSearchDecision,
    RetrievalAction,
)
from src.search.references import (
    RegulationReferenceLocator,
    extract_reference_locators,
    normalize_reference_text,
)


class IterativeControllerError(ValueError):
    """Raised when an otherwise valid model decision conflicts with state."""


MAX_CONTROLLER_ATTEMPTS = 3


def decide_next_action(
    state: IterativeRetrievalState,
    client: StructuredLLMClient | None = None,
) -> IterativeSearchDecision:
    """Return one valid decision, repairing invalid model JSON when needed."""

    llm_client = client or OpenAICompatibleJSONClient.from_env(
        model_env_key="model_name"
    )
    base_context = state.model_dump(
        mode="json",
        exclude={"evidence_history"},
    )
    repair_context: dict[str, object] | None = None
    last_error: ValidationError | IterativeControllerError | None = None

    for attempt in range(1, MAX_CONTROLLER_ATTEMPTS + 1):
        context = dict(base_context)
        if repair_context is not None:
            context["repair_context"] = repair_context
        content = build_multimodal_evidence_content(
            context=context,
            evidence_items=state.evidence_history,
        )
        response = llm_client.complete_json_multimodal(
            system_prompt=ITERATIVE_RETRIEVAL_PROMPT,
            content=content,
        )
        sanitized_response = dict(response)
        sanitized_response.pop("found_evidence", None)
        try:
            normalized = _enforce_decision_contract(
                sanitized_response,
                state,
            )
            decision = IterativeSearchDecision.model_validate(normalized)
            _validate_decision_against_state(decision, state)
            return decision
        except (ValidationError, IterativeControllerError) as exc:
            last_error = exc
            if attempt == MAX_CONTROLLER_ATTEMPTS:
                break
            repair_context = {
                "attempt": attempt + 1,
                "previous_invalid_response": sanitized_response,
                "validation_errors": [str(exc)],
                "instruction": (
                    "Return a complete corrected decision JSON. Keep the same "
                    "evidence boundary, fix every validation error, and make "
                    "action consistent with both calculation_ready values."
                ),
            }

    assert last_error is not None
    raise IterativeControllerError(
        "controller decision failed after "
        f"{MAX_CONTROLLER_ATTEMPTS} attempts: {last_error}"
    ) from last_error


def _enforce_decision_contract(
    response: dict[str, object],
    state: IterativeRetrievalState,
) -> dict[str, object]:
    """Normalize model booleans and enforce reference/terminal invariants.

    Readiness remains a VLM evidence-sufficiency judgment.  This function may
    make the action consistent with those judgments, but it must never derive
    readiness from a calculated IFC value or calculate either width.
    """

    normalized = dict(response)
    # Never expose model-generated evidence conclusions through the T3
    # controller contract. Evidence itself remains in evidence_history.
    normalized.pop("found_evidence", None)
    actual_ready = _normalize_ready_value(
        normalized,
        "actual_clear_width_calculation_ready",
    )
    required_ready = _normalize_ready_value(
        normalized,
        "required_clear_width_calculation_ready",
    )

    reference_target = _required_reference_target(
        normalized,
        state,
        required_ready=required_ready,
    )
    if reference_target is not None:
        required_ready = False
        normalized["required_clear_width_calculation_ready"] = False
        normalized["required_clear_width_evidence_ids"] = []
        missing = list(normalized.get("missing_evidence") or [])
        document_id, locator = reference_target
        message = f"缺少{document_id}中{locator}的完整原始证据。"
        if message not in missing:
            missing.append(message)
        normalized["missing_evidence"] = missing
        if state.hop < state.max_hops:
            normalized.update({
                "action": RetrievalAction.SEARCH.value,
                "query": (
                    f"请在《{document_id}》中查找并读取{locator}的完整原始内容，"
                    "包括适用条件、参数、公式以及相关表格或图示中的数值。"
                ),
                "dense_query": (
                    f"Find and read the complete {locator} in {document_id}, "
                    "including its applicability conditions, parameters, "
                    "formulas, and values in any related table or figure."
                ),
                "target_document": document_id,
            })
    if actual_ready and required_ready:
        normalized.update({
            "action": RetrievalAction.FINISH.value,
            "query": None,
            "dense_query": None,
            "target_document": None,
        })
    elif state.hop >= state.max_hops:
        normalized.update({
            "action": RetrievalAction.INSUFFICIENT_EVIDENCE.value,
            "query": None,
            "dense_query": None,
            "target_document": None,
        })
    return normalized


def _normalize_ready_value(
    response: dict[str, object],
    field: str,
) -> bool:
    """Normalize literal JSON-like booleans without inventing a judgment."""

    value = response.get(field)
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "false"}:
            normalized = lowered == "true"
            response[field] = normalized
            return normalized
    return value is True


def _required_reference_target(
    response: dict[str, object],
    state: IterativeRetrievalState,
    *,
    required_ready: bool,
) -> tuple[str, str] | None:
    """Return a regulation reference that still needs original evidence."""

    if not required_ready and state.pending_cross_document_references:
        reference = state.pending_cross_document_references[0]
        return reference.target_document, reference.target_locator
    if not required_ready:
        return None

    raw_ids = response.get("required_clear_width_evidence_ids")
    if not isinstance(raw_ids, list):
        return None
    evidence_by_id = {
        item.evidence_id: item for item in state.evidence_history
    }
    selected = [
        evidence_by_id[item]
        for item in raw_ids
        if isinstance(item, str) and item in evidence_by_id
    ]
    selected_documents = {item.document_id for item in selected}
    for item in selected:
        for reference in item.cross_document_references:
            if reference.target_document not in selected_documents:
                return reference.target_document, reference.target_locator

    visuals = [item for item in selected if item.modality in {"table", "image"}]
    for item in selected:
        if item.modality != "text":
            continue
        locators = extract_reference_locators(item.content)
        if not locators:
            continue
        for locator in locators:
            if not _has_original_visual(locator, item.document_id, visuals):
                return item.document_id, locator.raw
    return None


def _validate_decision_against_state(
    decision: IterativeSearchDecision,
    state: IterativeRetrievalState,
) -> None:
    known_evidence_ids = {item.evidence_id for item in state.evidence_history}
    referenced_ids = (
        set(decision.evidence_ids)
        | set(decision.actual_clear_width_evidence_ids)
        | set(decision.required_clear_width_evidence_ids)
    )
    unknown_evidence_ids = referenced_ids - known_evidence_ids
    if unknown_evidence_ids:
        unknown = ", ".join(sorted(unknown_evidence_ids))
        raise IterativeControllerError(
            f"decision references unknown evidence IDs: {unknown}"
        )

    if decision.required_clear_width_calculation_ready:
        _validate_required_width_evidence(decision, state)

    if decision.action is not RetrievalAction.SEARCH:
        return

    if state.hop >= state.max_hops:
        raise IterativeControllerError("search is not allowed at max_hops")

    assert decision.target_document is not None
    if decision.target_document not in state.available_documents:
        resolved_document = _resolve_available_document(
            decision.target_document,
            state.available_documents,
        )
        if resolved_document is None:
            raise IterativeControllerError(
                "decision target_document is not in available_documents"
            )
        decision.target_document = resolved_document

    assert decision.query is not None
    normalized_query = _normalize_query(decision.query)
    if any(
        normalized_query == _normalize_query(item.query)
        for item in state.query_history
    ):
        raise IterativeControllerError(
            "search query duplicates an executed historical query"
        )


def _validate_required_width_evidence(
    decision: IterativeSearchDecision,
    state: IterativeRetrievalState,
) -> None:
    """Reject readiness based only on an unresolved regulation reference."""

    evidence_by_id = {
        item.evidence_id: item for item in state.evidence_history
    }
    selected = [
        evidence_by_id[evidence_id]
        for evidence_id in decision.required_clear_width_evidence_ids
    ]
    selected_documents = {item.document_id for item in selected}
    unresolved = [
        reference
        for item in selected
        for reference in item.cross_document_references
        if reference.target_document not in selected_documents
    ]
    if unresolved:
        targets = ", ".join(
            sorted(
                f"{item.target_document}:{item.target_locator}"
                for item in unresolved
            )
        )
        raise IterativeControllerError(
            "required clear-width evidence relies on unresolved references: "
            f"{targets}"
        )

    visuals = [item for item in selected if item.modality in {"table", "image"}]
    for item in selected:
        if item.modality != "text":
            continue
        locators = extract_reference_locators(item.content)
        if not locators:
            continue
        for locator in locators:
            if not _has_original_visual(locator, item.document_id, visuals):
                raise IterativeControllerError(
                    "required clear-width evidence cites a locator without "
                    "its original evidence: "
                    f"{item.document_id}:{locator.raw}"
                )


def _has_original_visual(
    locator: RegulationReferenceLocator,
    document_id: str,
    visuals: list[EvidenceHistoryItem],
) -> bool:
    """Return whether a cited visual locator has matching original media."""

    if not locator.prefers_visual:
        return True
    return any(
        visual.document_id == document_id
        and (
            locator.normalized
            in normalize_reference_text(
                f"{visual.title or ''} {visual.asset_path or ''}"
            )
            or locator.core
            in normalize_reference_text(
                f"{visual.title or ''} {visual.asset_path or ''}"
            )
        )
        for visual in visuals
    )


def _normalize_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", query).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _resolve_available_document(
    requested: str,
    available_documents: list[str],
) -> str | None:
    """Resolve a unique display title to its catalog document ID."""

    requested_key = _normalize_document_title(requested)
    matches = [
        document
        for document in available_documents
        if _normalize_document_title(document) == requested_key
    ]
    return matches[0] if len(matches) == 1 else None


def _normalize_document_title(document: str) -> str:
    without_page_suffix = re.sub(
        r"\s*[（(]\s*page\s*\d+\s*[-–—]\s*\d+\s*[)）]\s*$",
        "",
        document,
        flags=re.IGNORECASE,
    )
    return _normalize_query(without_page_suffix)
