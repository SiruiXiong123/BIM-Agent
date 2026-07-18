"""Generate the first document-aware natural-language retrieval query."""

from __future__ import annotations

from prompt.query_rewrite import QUERY_REWRITE_PROMPT
from src.ai.evacuation_door_classifier import StructuredLLMClient
from src.ai.openai_compatible_client import OpenAICompatibleJSONClient
from src.search.document_catalog import AmbiguousDocumentError, DocumentCatalog
from src.search.iterative.models import IFCContext, InitialQueryRewrite
from src.search.models import RetrievalTask

DEFAULT_INITIAL_DOCUMENT = "南京地方标准建筑工程施工图信息模型智能审查规范"


def rewrite_initial_query(
    *,
    task: RetrievalTask,
    original_query: str,
    ifc_context: IFCContext,
    catalog: DocumentCatalog | None = None,
    client: StructuredLLMClient | None = None,
) -> InitialQueryRewrite:
    """Rewrite one first-hop query while keeping document selection deterministic."""

    original_query = str(original_query or "").strip()
    if not original_query:
        raise ValueError("original_query cannot be empty")

    selected_catalog = catalog or DocumentCatalog.discover()
    target_document = select_initial_document(original_query, selected_catalog)
    llm_client = client or OpenAICompatibleJSONClient.from_env(
        model_env_key="model_name"
    )
    response = llm_client.complete_json(
        system_prompt=QUERY_REWRITE_PROMPT,
        payload={
            "task": task,
            "original_query": original_query,
            "ifc_context": ifc_context.model_dump(mode="json"),
            "available_documents": selected_catalog.available_documents(),
            "target_document": target_document,
        },
    )
    response["target_document"] = target_document
    return InitialQueryRewrite.model_validate(response)


def select_initial_document(
    original_query: str,
    catalog: DocumentCatalog,
) -> str:
    """Honor one explicit catalog document; otherwise use the agreed default."""

    mentioned = catalog.mentioned_documents(original_query)
    if len(mentioned) > 1:
        ids = ", ".join(item.document_id for item in mentioned)
        raise AmbiguousDocumentError(
            f"The original query mentions multiple documents: {ids}"
        )
    if mentioned:
        return mentioned[0].document_id
    return catalog.resolve(DEFAULT_INITIAL_DOCUMENT).document_id
