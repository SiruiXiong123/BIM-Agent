"""Read-only startup checks for a portable local BIM Agent deployment."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

from src.search.document_catalog import DocumentCatalog


REQUIRED_ENV_KEYS = (
    "base_url",
    "api_key",
    "model_name",
    "evacuation_door_model_name",
    "embedding_model_name",
)
EVAL_FIXTURE = "primary_school_door_width_eval.ifc"
PLACEHOLDER_MARKERS = ("replace-me", "your-", "example-key")


class StartupCheckError(RuntimeError):
    """Raised when the cloned project cannot run its complete web workflow."""


@dataclass(frozen=True, slots=True)
class StartupReport:
    project_root: Path
    python_version: str
    document_ids: tuple[str, ...]
    embedding_model: str
    eval_fixture: Path


def run_startup_checks(project_root: Path) -> StartupReport:
    """Validate credentials, local indexes, original media, and eval input."""

    root = Path(project_root).resolve()
    _validate_python()
    settings = _load_settings(root / ".env")
    catalog = DocumentCatalog.discover(
        root / "references" / "assets" / "indexes"
    )
    _validate_indexes_and_media(
        project_root=root,
        catalog=catalog,
        expected_embedding_model=settings["embedding_model_name"],
    )
    eval_fixture = root / "eval" / EVAL_FIXTURE
    _require_real_file(eval_fixture, label="evaluation IFC")
    return StartupReport(
        project_root=root,
        python_version=(
            f"{sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        document_ids=tuple(catalog.available_documents()),
        embedding_model=settings["embedding_model_name"],
        eval_fixture=eval_fixture,
    )


def _validate_python() -> None:
    if sys.version_info < (3, 11):
        raise StartupCheckError("Python 3.11 or newer is required")


def _load_settings(env_path: Path) -> dict[str, str]:
    if not env_path.is_file():
        raise StartupCheckError(
            ".env is missing; copy .env.example to .env and fill in the values"
        )
    file_values = dotenv_values(env_path)
    settings: dict[str, str] = {}
    missing: list[str] = []
    for key in REQUIRED_ENV_KEYS:
        value = str(os.environ.get(key) or file_values.get(key) or "").strip()
        if not value or any(marker in value.casefold() for marker in PLACEHOLDER_MARKERS):
            missing.append(key)
        else:
            settings[key] = value
    if missing:
        raise StartupCheckError(
            ".env has missing or placeholder values: " + ", ".join(missing)
        )
    parsed_base_url = urlparse(settings["base_url"])
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
        raise StartupCheckError("base_url must be an absolute HTTP(S) URL")
    return settings


def _validate_indexes_and_media(
    *,
    project_root: Path,
    catalog: DocumentCatalog,
    expected_embedding_model: str,
) -> None:
    references_root = project_root / "references"
    for document in catalog.documents:
        index_dir = document.index_dir
        for filename in ("manifest.json", "bm25_manifest.json", "bm25_corpus.json.gz"):
            _require_real_file(index_dir / filename, label=f"{document.document_id} index")
        manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
        indexed_model = str(manifest.get("embedding_model") or "").strip()
        if indexed_model != expected_embedding_model:
            raise StartupCheckError(
                f"embedding_model_name={expected_embedding_model!r} does not match "
                f"{document.document_id!r} index model {indexed_model!r}"
            )
        modalities = manifest.get("modalities")
        if not isinstance(modalities, dict):
            raise StartupCheckError(
                f"invalid modality manifest for {document.document_id!r}"
            )
        for modality in ("text", "table", "image"):
            modality_manifest = modalities.get(modality)
            if not isinstance(modality_manifest, dict):
                raise StartupCheckError(
                    f"missing {modality} manifest for {document.document_id!r}"
                )
            count = int(modality_manifest.get("count", 0))
            _require_existing_file(
                index_dir / f"{modality}_metadata.jsonl",
                label=f"{document.document_id} {modality} metadata",
                allow_empty=count == 0,
            )
            _require_real_file(
                index_dir / f"{modality}.faiss",
                label=f"{document.document_id} {modality} FAISS index",
            )
        for modality in ("table", "image"):
            _validate_media_paths(
                references_root=references_root,
                metadata_path=index_dir / f"{modality}_metadata.jsonl",
            )


def _validate_media_paths(*, references_root: Path, metadata_path: Path) -> None:
    for line_number, raw_line in enumerate(
        metadata_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise StartupCheckError(
                f"invalid JSON in {metadata_path} line {line_number}"
            ) from exc
        asset_path = str(record.get("asset_path") or "").strip()
        if not asset_path:
            continue
        candidate = (references_root / asset_path).resolve()
        try:
            candidate.relative_to(references_root.resolve())
        except ValueError as exc:
            raise StartupCheckError(
                f"media path escapes references directory: {asset_path}"
            ) from exc
        _require_real_file(candidate, label="retrieval evidence media")


def _require_real_file(path: Path, *, label: str) -> None:
    _require_existing_file(path, label=label, allow_empty=False)


def _require_existing_file(
    path: Path,
    *,
    label: str,
    allow_empty: bool,
) -> None:
    if not path.is_file() or (not allow_empty and path.stat().st_size == 0):
        raise StartupCheckError(f"missing or empty {label}: {path}")
    with path.open("rb") as handle:
        prefix = handle.read(80)
    if prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
        raise StartupCheckError(
            f"{label} is a Git LFS pointer, not file content; run git lfs pull: {path}"
        )
