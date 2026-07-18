"""Persistent, validated snapshots for completed T1/T2 preparations."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.review.models import ReviewPreparation


CACHE_VERSION = 1
TOKEN_PATTERN = re.compile(
    r"^(?P<sha>[0-9a-f]{64})-(?P<limit>all|[1-9][0-9]*)-"
    r"(?P<signature>[0-9a-f]{12})$"
)


class PreparationSnapshotError(ValueError):
    """Raised when a stored preparation snapshot is missing or inconsistent."""


class PreparationSnapshotStore:
    """Store one completed T1/T2 result independently of Streamlit sessions."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save(self, preparation: ReviewPreparation) -> str:
        signature = classifier_signature(preparation)
        token = build_snapshot_token(
            source_sha256=preparation.source_sha256,
            requested_max_doors=preparation.requested_max_doors,
            classifier_signature=signature,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / f"{token}.json"
        temporary = destination.with_suffix(".json.tmp")
        payload = {
            "cache_version": CACHE_VERSION,
            "token": token,
            "saved_at": datetime.now(UTC).isoformat(),
            "classifier_signature": signature,
            "preparation": preparation.model_dump(mode="json"),
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(destination)
        return token

    def load(self, token: str) -> ReviewPreparation:
        normalized = str(token or "").strip().lower()
        if TOKEN_PATTERN.fullmatch(normalized) is None:
            raise PreparationSnapshotError("无效的准备结果恢复标识。")
        source = self.root / f"{normalized}.json"
        if not source.is_file():
            raise PreparationSnapshotError("准备结果快照不存在或已被清理。")
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PreparationSnapshotError("无法读取准备结果快照。") from exc
        if not isinstance(raw, dict) or raw.get("cache_version") != CACHE_VERSION:
            raise PreparationSnapshotError("准备结果快照版本不受支持。")
        if raw.get("token") != normalized:
            raise PreparationSnapshotError("准备结果快照标识不一致。")
        try:
            preparation = ReviewPreparation.model_validate(raw["preparation"])
        except (KeyError, ValueError, TypeError) as exc:
            raise PreparationSnapshotError("准备结果快照内容无效。") from exc
        signature = classifier_signature(preparation)
        expected = build_snapshot_token(
            source_sha256=preparation.source_sha256,
            requested_max_doors=preparation.requested_max_doors,
            classifier_signature=signature,
        )
        if expected != normalized or raw.get("classifier_signature") != signature:
            raise PreparationSnapshotError("准备结果快照校验失败。")
        return preparation


def classifier_signature(preparation: ReviewPreparation) -> str:
    """Return the stable model/prompt signature represented by a snapshot."""

    signatures = {
        (
            candidate.record.assessment.model_name,
            candidate.record.assessment.prompt_version,
        )
        for candidate in preparation.candidates
        if candidate.record.assessment is not None
    }
    if not signatures:
        return "no-classified-doors"
    return "|".join(
        f"{model_name}:{prompt_version}"
        for model_name, prompt_version in sorted(signatures)
    )


def build_snapshot_token(
    *,
    source_sha256: str,
    requested_max_doors: int | None,
    classifier_signature: str,
) -> str:
    limit = "all" if requested_max_doors is None else str(requested_max_doors)
    signature_hash = hashlib.sha256(
        classifier_signature.encode("utf-8")
    ).hexdigest()[:12]
    return f"{source_sha256}-{limit}-{signature_hash}"


def snapshot_metadata(path: str | Path) -> dict[str, Any]:
    """Read non-preparation metadata for diagnostics without loading a model."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        key: raw.get(key)
        for key in ("cache_version", "token", "saved_at", "classifier_signature")
    }
